"""Read-only sensor monitoring, rolling health windows and MQTT input adapters.

No motor commands are published here. Optional Paho is imported only when enabled.
"""
import json
import math
import sqlite3
import threading
import time
import uuid


# Defaults are starting points, not calibrated sensor specifications. None disables an optional rule.
# These defaults establish speed bounds, observation duration, freshness and optional
# service rules. They are merged with a launch config and validated before use. Calibrate
# speed/current thresholds on the assigned hardware; unset optional rules stay disabled.
DEFAULT_LIMITS = {
    'speed_min_cm_s': 5.0,  # Lower acceptable belt speed; cm/s is not motor RPM.
    'speed_max_cm_s': 30.0,  # Upper acceptable belt speed.
    'window_seconds': 3600.0,  # Rolling history horizon: the most recent hour.
    'outside_limit_seconds': 1440.0,  # Flag after more than 24 out-of-range minutes.
    'minimum_running_seconds': 60.0,  # Avoid evaluating a nearly empty dataset.
    'stale_seconds': 4.0,  # Older telemetry cannot describe the current belt state.
    'stall_speed_cm_s': 0.5,  # Near-zero threshold, used only with a run request.
    'stall_seconds': 3.0,  # Require sustained evidence, not one noisy reading.
    'high_current_a': None,  # Only enable once actual calibrated amperage is supplied.
    'service_runtime_hours': None,
    'service_distance_km': None,
}


# Reject booleans, negative values and NaN/infinity before sensor values enter calculations.
# JSON can represent booleans, nulls and numeric values, but only some are valid measurements.
# This helper enforces finite, nonnegative numbers and allows null only when the caller
# explicitly treats missing data as unknown.
def number(value, name, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(name + ' must be a finite nonnegative number')
    return float(value)


# Keep received telemetry, observed time intervals and inspection incidents in one thread-safe
# store.
# This class translates valid measurements into observed durations and persistent inspection
# incidents. It owns the rolling-window calculation rather than the browser, ensuring that UI
# refresh rate does not affect the result.
class SensorMonitor:
    # Open the station-specific monitoring history; start with unknown live state until fresh
    # input arrives.
    # The station name binds the database to one testbed. Raw readings, closed intervals and
    # incidents are persisted, but live connection state starts unknown after every process
    # restart. Persisted timestamps also help reject clock rollback and old samples.
    def __init__(self, path='team8monitor.sqlite3', station='Conveyor3', limits=None, clock=time.time):
        self.clock = clock
        self.station = station
        self.limits = {**DEFAULT_LIMITS, **(limits or {})}
        self.validate_limits(self.limits)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        # readings = raw valid samples; intervals = measured durations; incidents = alert episodes.
        # A separate metadata row prevents silently mixing two different stations in one database.
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS readings (
          event_id TEXT PRIMARY KEY, received REAL, session TEXT, sequence INTEGER,
          speed REAL, running INTEGER, current REAL);
        CREATE TABLE IF NOT EXISTS intervals (
          start REAL, end REAL, running INTEGER, speed REAL);
        CREATE TABLE IF NOT EXISTS sensor_incidents (
          id INTEGER PRIMARY KEY, kind TEXT, raised REAL, acknowledged REAL, resolved REAL);
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS active_sensor_incident
          ON sensor_incidents(kind) WHERE resolved IS NULL;
        ''')
        stored_station = self.db.execute('SELECT value FROM metadata WHERE key=?', ('station_id',)).fetchone()
        if stored_station is not None and stored_station['value'] != self.station:
            self.db.close()
            raise ValueError('Monitor database belongs to another station; use a separate deployment folder/database')
        self.db.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)', ('station_id', self.station))
        self.db.commit()
        self.latest_received = self.db.execute('SELECT MAX(received) FROM readings').fetchone()[0]
        self.last = None
        self.stall_since = None
        self.connected = False
        self.connection_message = 'MQTT not enabled'
        self.last_error = None
        self.rejected = 0

    # Reject contradictory speed ranges and impossible rolling-window settings.
    # Both individual values and relationships matter: minimum speed must be below maximum
    # speed, and required observation durations must fit within the window. These checks prevent
    # division/threshold logic from operating on contradictory settings.
    @staticmethod
    def validate_limits(limits):
        for key, value in limits.items():
            number(value, key, nullable=key in ('high_current_a', 'service_runtime_hours', 'service_distance_km'))
        if not limits['speed_min_cm_s'] < limits['speed_max_cm_s']:
            raise ValueError('Speed minimum must be below maximum')
        if not (0 < limits['window_seconds'] <= 86400 and
                limits['outside_limit_seconds'] <= limits['window_seconds'] and
                limits['minimum_running_seconds'] <= limits['window_seconds'] and
                limits['stale_seconds'] > 0 and limits['stall_seconds'] > 0):
            raise ValueError('Invalid monitoring window or duration')

    # Apply a validated settings copy atomically so readers cannot see half-updated limits.
    # The browser submits a subset of known limit keys. A candidate settings copy is validated
    # before replacing the active dictionary under a lock, so concurrent readers see either the
    # complete old setup or the complete new setup.
    def configure(self, values):
        if not isinstance(values, dict) or set(values) - set(DEFAULT_LIMITS):
            raise ValueError('Unknown sensor settings')
        with self.lock:
            candidate = {**self.limits, **values}
            self.validate_limits(candidate)
            self.limits = candidate
            self.stall_since = None
        return {'message': 'Health limits updated for this server session; rolling window is reevaluated.'}

    # Forget timing continuity on disconnect; unobserved downtime must not become measured
    # running time.
    # MQTT callbacks provide connection state and a readable message. On disconnect, the last
    # sample and pending stall timer are forgotten; historical incidents remain stored, but no
    # elapsed disconnected period is counted as measured belt operation.
    def connection(self, connected, message):
        with self.lock:
            self.connected = connected
            self.connection_message = message
            if not connected:
                self.last = None  # Never bridge an unobserved disconnection.
                self.stall_since = None

    # Contain bad sensor messages so one malformed packet cannot stop the MQTT worker.
    # The MQTT adapter hands in a decoded telemetry object. Validation failures are contained
    # here, counted and exposed to the UI. Bad packets break sample continuity instead of
    # refreshing a stale reading or killing the MQTT loop.
    def ingest(self, payload, retained=False):
        if retained:
            return False
        try:
            return self._ingest(payload)
        except (ValueError, TypeError, KeyError) as error:
            with self.lock:
                self.rejected += 1
                self.last_error = str(error)
                self.stall_since = None
                self.last = None
            return False

    # Validate identity/order/units, close the previous observed interval, and evaluate
    # sustained stall evidence.
    # The envelope establishes station, delivery identity, producer session and sample order. A
    # new fresh sample closes the previous observed interval only across a small continuous gap.
    # Repeated near-zero motion with a run request then builds stall evidence; a single slow
    # reading is not sufficient.
    def _ingest(self, payload):
        if not isinstance(payload, dict) or payload.get('station_id') != self.station:
            raise ValueError('Unexpected station or payload shape')
        event = payload.get('event_id')
        session = payload.get('session_id')
        sequence = payload.get('sequence')
        if not isinstance(event, str) or not 1 <= len(event) <= 128:
            raise ValueError('Telemetry requires event_id')
        if not isinstance(session, str) or not 1 <= len(session) <= 128:
            raise ValueError('Telemetry requires session_id')
        if isinstance(sequence, bool) or not isinstance(sequence, int) or not 0 <= sequence <= 2**53-1:
            raise ValueError('Telemetry requires nonnegative integer sequence')
        speed = number(payload.get('speed_cm_s'), 'speed_cm_s', nullable=True)
        current = number(payload.get('current_a'), 'current_a', nullable=True)
        if (speed is not None and speed > 100000) or (current is not None and current > 1000000):
            raise ValueError('Telemetry magnitude is outside supported sensor bounds')
        running = payload.get('run_requested')
        if running is not None and type(running) is not bool:
            raise ValueError('run_requested must be true, false or null')
        with self.lock, self.db:
            if self.db.execute('SELECT 1 FROM readings WHERE event_id=?', (event,)).fetchone():
                return False  # Duplicates never refresh freshness or accumulate time.
            watermark = self.db.execute('SELECT MAX(sequence) FROM readings WHERE session=?', (session,)).fetchone()[0]
            # Persisted sequence watermarks also reject old samples after disconnects or server restarts.
            if watermark is not None and sequence <= watermark:
                return False
            previous = self.last
            if previous and previous['session'] == session and sequence <= previous['sequence']:
                return False
            now = self.clock()
            if self.latest_received is not None and now < self.latest_received:
                raise ValueError('Server clock moved backwards; sensor timing is unknown')
            self.latest_received = now
            # A sample can close the previous interval only if no long gap/session change occurred.
            continuous = (previous is not None and previous['session'] == session and
                          0 <= now - previous['at'] <= self.limits['stale_seconds'])
            # Integrate the PREVIOUS sample across elapsed time; do not count packets as seconds.
            if continuous and previous['running'] is not None:
                if previous['running'] is False or previous['speed'] is not None:
                    self.db.execute('INSERT INTO intervals VALUES(?,?,?,?)',
                                    (previous['at'], now, previous['running'], previous['speed']))
            if not continuous:
                self.stall_since = None
            self.last = {'at': now, 'session': session, 'sequence': sequence,
                         'speed': speed, 'running': running, 'current': current}
            self.db.execute('INSERT INTO readings VALUES(?,?,?,?,?,?,?)',
                            (event, now, session, sequence, speed, running, current))
            self.last_error = None
            # Distinguish a commanded run with near-zero motion from a known intentional stop.
            if running is True and speed is not None and speed <= self.limits['stall_speed_cm_s']:
                if self.stall_since is None:
                    self.stall_since = now
                if now - self.stall_since >= self.limits['stall_seconds']:
                    self._raise('stall', self.stall_since)
            else:
                self.stall_since = None
                if running is False or (speed is not None and speed > self.limits['stall_speed_cm_s']):
                    self._resolve('stall', now)
        return True

    # Create at most one active incident of each sensor kind; later updates reuse that episode.
    # The kind selects a sensor incident category such as stall or maintenance. A database index
    # permits only one unresolved incident of that kind, preserving its original raised time and
    # avoiding repeated episodes during one continuous fault.
    def _raise(self, kind, at):
        self.db.execute('INSERT OR IGNORE INTO sensor_incidents(kind,raised) VALUES(?,?)', (kind, at))

    # Mark recovery without deleting the original incident or its acknowledgement.
    # Only unresolved incidents of the requested category are marked recovered. Their
    # raised/acknowledged values remain available for reports; resolving an incident is
    # different from deleting its history.
    def _resolve(self, kind, at):
        self.db.execute('UPDATE sensor_incidents SET resolved=? WHERE kind=? AND resolved IS NULL', (at, kind))

    # Clip observed intervals to the rolling window, calculate health, and expose unknown versus
    # fresh readings.
    # Stored intervals are clipped to the most recent configured window, then summed by observed
    # running, within-range and stopped time. Unknown time is reported separately. Freshness
    # gates live state and incident recovery, while service totals use all valid recorded
    # intervals.
    def snapshot(self):
        with self.lock, self.db:
            now = self.clock()
            last = self.last
            age = now - last['at'] if last else None
            fresh = self.connected and age is not None and 0 <= age <= self.limits['stale_seconds']
            rows = [dict(r) for r in self.db.execute('SELECT * FROM intervals WHERE end>?',
                                                   (now - self.limits['window_seconds'],))]
            # Include the as-yet-unclosed interval once; do not save it twice.
            if fresh and (last['running'] is False or (last['running'] is True and last['speed'] is not None)):
                rows.append({'start': last['at'], 'end': now, 'running': last['running'], 'speed': last['speed']})
            running_seconds = within_seconds = stopped_seconds = 0.0
            # Count only the overlap with the rolling window, including partially overlapping samples.
            for interval in rows:
                duration = max(0, min(now, interval['end']) - max(interval['start'], now - self.limits['window_seconds']))
                if interval['running']:
                    running_seconds += duration
                    if self.limits['speed_min_cm_s'] <= interval['speed'] <= self.limits['speed_max_cm_s']:
                        within_seconds += duration
                else:
                    stopped_seconds += duration
            # Unknown and stopped intervals are excluded from both parts of this running-time ratio.
            outside = max(0, running_seconds - within_seconds)
            sufficient = running_seconds >= self.limits['minimum_running_seconds']
            health_bad = sufficient and outside > self.limits['outside_limit_seconds']
            # Unknown data cannot resolve an existing incident.
            if fresh and last['running'] is not None and (last['running'] is False or last['speed'] is not None):
                if health_bad:
                    self._raise('maintenance', now)
                elif sufficient:
                    self._resolve('maintenance', now)
            # Service reminders use all recorded valid intervals; centimetres / 100000 gives kilometres.
            totals = self.db.execute('''SELECT COALESCE(SUM(end-start),0) AS runtime,
                COALESCE(SUM((end-start)*speed),0) AS distance FROM intervals WHERE running=1''').fetchone()
            if fresh:
                for key, amount in [('service_runtime_hours', totals['runtime'] / 3600),
                                    ('service_distance_km', totals['distance'] / 100000)]:
                    if self.limits[key] is not None and amount >= self.limits[key]:
                        self._raise(key, now)
            state = 'Unknown'
            if fresh and last['running'] is False:
                state = 'Stopped'
            elif fresh and last['running'] is True and last['speed'] is not None:
                state = 'Stalled' if self.stall_since is not None and now-self.stall_since >= self.limits['stall_seconds'] else 'Running'
            active = [dict(r) for r in self.db.execute('''SELECT * FROM sensor_incidents
                WHERE resolved IS NULL OR id IN (SELECT id FROM sensor_incidents ORDER BY raised DESC LIMIT 100)
                ORDER BY raised DESC''')]
            titles = {'stall': 'Possible belt stall — inspect conveyor',
                      'maintenance': 'Belt speed repeatedly outside the acceptable range',
                      'service_runtime_hours': 'Runtime service interval reached',
                      'service_distance_km': 'Distance service interval reached'}
            for row in active:
                row.update(sensor_kind=row['kind'], kind='sensor', title=titles[row['kind']], checkpoint='A',
                           station_id=self.station, detail='Inspection flag, not a diagnosis. No automatic motor command was sent.')
            history = [dict(r) for r in self.db.execute('SELECT received,speed,running,current FROM readings ORDER BY received DESC LIMIT 60')]
            return {'station_id': self.station, 'connected': self.connected, 'connection_message': self.connection_message,
                    'fresh': fresh, 'age_seconds': age, 'state': state, 'limits': self.limits,
                    'speed_cm_s': last['speed'] if fresh else None,
                    'current_a': last['current'] if fresh else None,
                    'run_requested': last['running'] if fresh else None,
                    'running_seconds': round(running_seconds, 2), 'within_seconds': round(within_seconds, 2),
                    'outside_seconds': round(outside, 2), 'stopped_seconds': round(stopped_seconds, 2),
                    'unknown_seconds': round(max(0, self.limits['window_seconds']-running_seconds-stopped_seconds), 2),
                    'percent_within': round(100*within_seconds/running_seconds, 1) if running_seconds else None,
                    'sufficient_data': sufficient, 'health_flag': health_bad,
                    'runtime_hours': totals['runtime']/3600, 'distance_km': totals['distance']/100000,
                    'history': list(reversed(history)), 'incidents': active,
                    'rejected_messages': self.rejected, 'last_error': self.last_error}

    # Persist operator receipt of the sensor incident; the flag stays active until its condition
    # recovers.
    # An incident ID identifies the operator warning being received. This saves the first
    # acknowledgement timestamp without changing the monitored condition; a later valid recovery
    # reading must independently resolve it.
    def acknowledge(self, incident_id):
        with self.lock, self.db:
            result = self.db.execute('UPDATE sensor_incidents SET acknowledged=COALESCE(acknowledged,?) WHERE id=?',
                                     (self.clock(), incident_id))
            if not result.rowcount:
                raise ValueError('Incident not found')
        return {'message': 'Acknowledged. The monitoring condition must recover separately.'}

    # Release owned resources after the worker/server has stopped using them.
    # The connection belongs to the dashboard process. Call this only after stopping
    # subscriber/supervisor activity so a late callback cannot try to write to a closed SQLite
    # handle.
    def close(self):
        self.db.close()


# Store only the newest JPEG for each checkpoint in memory; images expire rather than looking
# live forever.
# The cache holds only the newest bounded JPEG for each checkpoint. It uses capture age, not
# just arrival order, to prevent an old image from looking live, and never writes camera images
# to disk.
class CameraFrames:
    """Only the latest bounded JPEG per checkpoint; never written to disk."""
    # Initialize the small shared frame cache and an injectable clock for freshness tests.
    # The dictionary is shared by scanner-upload handlers and browser requests. A lock keeps
    # each timestamp/frame pair consistent, and the injectable clock permits deterministic
    # expiry tests.
    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.frames = {}

    # Check checkpoint, size, JPEG markers and capture age before replacing the cached frame.
    # Inputs are checkpoint, JPEG bytes and optional capture time. Unknown checkpoints,
    # excessive size, invalid markers and stale/misaligned timestamps are rejected before the
    # existing image is replaced.
    def put(self, checkpoint, body, captured_at=None):
        if checkpoint not in ('A', 'B') or not 4 <= len(body) <= 300000 or not body.startswith(b'\xff\xd8') or not body.endswith(b'\xff\xd9'):
            raise ValueError('Expected a JPEG under 300 kB for checkpoint A or B')
        at = self.clock() if captured_at is None else float(captured_at)
        if not math.isfinite(at) or not -1 <= self.clock()-at <= 4:
            raise ValueError('Preview capture timestamp is stale or clocks differ')
        with self.lock:
            self.frames[checkpoint] = (at, body)

    # Return a preview only while its capture timestamp is within the freshness window.
    # A browser preview request receives bytes only if the cached capture age remains within
    # four seconds. Otherwise it gets no image, allowing the HTTP/UI layer to show unavailable
    # rather than silently retaining old visual evidence.
    def get(self, checkpoint):
        with self.lock:
            item = self.frames.get(checkpoint)
            return item[1] if item and 0 <= self.clock()-item[0] <= 4 else None

    # Give the UI availability flags for A and B without sending image bytes in a JSON response.
    # This returns a small A/B availability map for the monitoring JSON. Image bytes travel
    # through separate JPEG requests so the regular status response stays lightweight.
    def status(self):
        return {checkpoint: self.get(checkpoint) is not None for checkpoint in ('A', 'B')}


# Choose a callback-compatible Paho client for either the lab image or newer installations.
# The lab image may have Paho 1.x while development machines use 2.x. Choosing the compatible
# callback mode here lets the same connection/message handlers work in both environments without
# changing their data-processing logic.
def mqtt_client(client_id):
    """Support both Paho 1.x from lab images and Paho 2.x."""
    import paho.mqtt.client as mqtt
    if hasattr(mqtt, 'CallbackAPIVersion'):
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=client_id)
    return mqtt.Client(client_id=client_id)


# Translate assigned MQTT topics into the same sensor/timing methods used by offline tests.
# Exact topic names map incoming messages to sensor telemetry or checkpoint A/B scans. The
# adapter translates transport formats; the separate tracker/monitor stores remain responsible
# for timing and incident decisions.
class MQTTInputs:
    # Validate distinct exact topics so one camera topic cannot accidentally become both A and
    # B.
    # Configuration supplies the broker and distinct topic mappings. Duplicate checkpoint topics
    # and wildcard input mappings are rejected because otherwise the same physical scan could
    # falsely count as both departure and arrival.
    def __init__(self, config, tracker, sensors, factory=mqtt_client, clock=time.monotonic):
        self.config, self.tracker, self.sensors = config, tracker, sensors
        self.clock = clock
        self.last_seen = {}
        self.client = None
        self.errors = 0
        self.lock = threading.RLock()
        self.topics = {topic: checkpoint for checkpoint, topic in config.get('checkpoint_topics', {}).items() if topic}
        chosen = [t for t in config.get('checkpoint_topics', {}).values() if t]
        sensor_topic = config.get('sensor_topic')
        if not sensor_topic or len(chosen) != len(set(chosen)) or sensor_topic in chosen:
            raise ValueError('Each checkpoint and telemetry must use a distinct topic')
        if any(c not in ('A', 'B') for c in config.get('checkpoint_topics', {})):
            raise ValueError('Only A and B checkpoints are supported')
        if any(not isinstance(t, str) or not t or '+' in t or '#' in t for t in chosen+[sensor_topic]):
            raise ValueError('Configure exact MQTT topics, without wildcards')
        self.factory = factory

    # Start a read-only subscriber in the background; broker loss must not freeze the local
    # dashboard.
    # This creates a uniquely named client, registers callbacks and starts its background
    # network loop. Connection attempts are asynchronous so an unreachable lab broker does not
    # prevent the local dashboard from opening.
    def start(self):
        self.client = self.factory('team8-monitor-' + uuid.uuid4().hex[:10])
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=15)
        self.client.connect_async(self.config['broker'], int(self.config.get('port', 1883)), 30)
        self.sensors.connection(False, 'Connecting to MQTT broker')
        self.client.loop_start()

    # Subscribe again after a successful connection/reconnection and expose broker state to the
    # UI.
    # Paho calls this when a broker connection succeeds or is rejected. A successful reconnect
    # renews the exact subscriptions; connection state is exposed to the UI but does not by
    # itself make old sensor values fresh.
    def on_connect(self, client, userdata, flags, rc):
        self.sensors.connection(rc == 0, 'MQTT connected' if rc == 0 else 'MQTT connection rejected')
        if rc == 0:
            for topic in [self.config['sensor_topic']] + list(self.topics):
                client.subscribe(topic, qos=1)

    # Invalidate live sensor continuity immediately when the broker connection is lost.
    # Losing the network immediately informs the sensor monitor and breaks timing continuity.
    # Recorded incidents are not cleared, because loss of data is not evidence that a fault
    # recovered.
    def on_disconnect(self, client, userdata, rc):
        self.sensors.connection(False, 'MQTT disconnected; data unknown until new readings arrive')

    # Paho callback: hand message bytes and their retained flag to the testable decoding method.
    # This is the small Paho-facing wrapper. Passing topic, raw bytes and retained flag into
    # consume keeps transport plumbing separate from decoding, which can then be tested without
    # a live broker.
    def on_message(self, client, userdata, msg):
        self.consume(msg.topic, msg.payload, msg.retain)

    # Ignore retained/oversized data, decode the correct topic format, and debounce continuous
    # barcode sightings.
    # Retained messages are not new physical observations. Sensor JSON goes through strict
    # validation; barcode text/JSON is mapped to the configured checkpoint and debounced while
    # continuously visible. Decode failures are counted, and malformed sensor data invalidates
    # continuity.
    def consume(self, topic, body, retained=False):
        if retained or len(body) > 16384:
            return False
        try:
            text = body.decode('utf-8')
            if topic == self.config['sensor_topic']:
                return self.sensors.ingest(json.loads(text))
            if topic not in self.topics:
                return False
            payload = json.loads(text) if text.lstrip().startswith('{') else {'barcode': text}
            barcode = payload.get('barcode')
            if not isinstance(barcode, str) or not barcode.strip():
                raise ValueError('Missing barcode')
            key = (topic, barcode)
            with self.lock:
                now = self.clock()
                previous = self.last_seen.get(key, -1e9)
                self.last_seen[key] = now
                if now - previous < 2:
                    return False
                if len(self.last_seen) > 2000:
                    self.last_seen = {k: t for k, t in self.last_seen.items() if now-t < 60}
            self.tracker.scan(barcode, self.topics[topic], 'mqtt', payload.get('event_id'))
            return True
        except (ValueError, TypeError, KeyError, UnicodeError):
            self.errors += 1
            if topic == self.config['sensor_topic']:
                self.sensors.ingest(None)  # Malformed telemetry invalidates continuity.
            return False

    # Stop the MQTT network loop before the server closes the databases it can update.
    # Disconnect and stop the network loop before closing the stores callbacks can access. This
    # method does not publish motor-stop commands; hardware control remains a separate
    # integration.
    def stop(self):
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
