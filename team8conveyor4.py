"""Conveyor 4: MQTT speed/current, frozen-baseline deviation timers and totals.

FLAG is a JSON boolean: true means verified normal, false means abnormal OR not
yet verified (missing/stale/calibrating). STATUS explains which case applies.
This publishes monitoring state only, never motor commands.
"""
from collections import deque
import json
import math
import sqlite3
import threading
import time
import uuid

from team8monitor import mqtt_client


DEFAULTS = {
    'broker': '129.97.228.106', 'port': 1883, 'monitor_type': 'conveyor4',
    'speed_topic': 'Conveyor4/get_belt_speed',
    'current_topic': None,  # The supplied flow contains voltage, not an amperage topic.
    'voltage_topic': 'Conveyor4/get_motor_voltage',
    'flag_topic': 'Conveyor4/FLAG', 'status_topic': 'Conveyor4/STATUS',
    'speed_key': None, 'current_key': None, 'voltage_key': None,
    'speed_scale_to_cm_s': 1.0, 'current_scale_to_a': 1.0,
    'baseline_samples': 30, 'minimum_samples': 5,
    'deviation_fraction': 0.15, 'deviation_seconds': 10.0,
    'stale_seconds': 4.0, 'moving_threshold_cm_s': 0.05,
    'camera_topic': 'Conveyor4/camera/frame', 'tags_topic': 'Conveyor4/apriltags',
    'camera_status_topic': 'Conveyor4/camera/status',
}


# SECTION: Validate deployment settings before subscribing or publishing.
# Topics must be distinct exact names: a flag output must never loop into a sensor
# input. Limits define prior-normal sample averages, persistence time and freshness.
# Sensor topic names may be unset until staff supplies them; unset is not zero.
def validate_config(config):
    values = {**DEFAULTS, **config}
    topic_keys = ('speed_topic', 'current_topic', 'voltage_topic', 'flag_topic', 'status_topic',
                  'camera_topic', 'tags_topic', 'camera_status_topic')
    for key in topic_keys:
        topic = values[key]
        if topic is not None and (not isinstance(topic, str) or not topic.strip() or '+' in topic or '#' in topic):
            raise ValueError(key + ' must be an exact MQTT topic or null')
    topics = [values[key] for key in topic_keys if values[key]]
    if len(topics) != len(set(topics)) or not values['flag_topic'] or not values['status_topic']:
        raise ValueError('Sensor/FLAG/STATUS topics must be distinct; both output topics are required')
    for key in ('baseline_samples', 'minimum_samples'):
        if type(values[key]) is not int or not 1 <= values[key] <= 1000:
            raise ValueError(key + ' must be an integer from 1 to 1000')
    if not 2 <= values['minimum_samples'] <= values['baseline_samples']:
        raise ValueError('Use at least 2 baseline samples, within the configured window')
    for key in ('deviation_fraction', 'deviation_seconds', 'stale_seconds',
                'speed_scale_to_cm_s', 'current_scale_to_a', 'moving_threshold_cm_s'):
        number = values[key]
        if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
            raise ValueError(key + ' must be finite and nonnegative')
    if not 0 < values['deviation_fraction'] < 1 or min(values['stale_seconds'], values['deviation_seconds'],
            values['speed_scale_to_cm_s'], values['current_scale_to_a']) <= 0:
        raise ValueError('Invalid percentage, timer, freshness or scale')
    return values


# SECTION: The measurement/state engine is independent from MQTT and the browser.
# Each channel owns its last sample, accepted baseline and continuous-deviation
# timer. SQLite retains readings, totals and abnormal episode count across restarts.
# Monotonic time drives durations so wall-clock adjustments do not extend a fault.
class Conveyor4Monitor:
    # Restore the saved baseline and cumulative operating history, but not live
    # sensor timestamps. Freshness starts unknown after every process restart;
    # this prevents downtime from becoming measured running/deviation duration.
    def __init__(self, path='team8conveyor4.sqlite3', config=None, clock=time.monotonic, wall=time.time):
        self.config = validate_config(config or {})
        self.clock, self.wall = clock, wall
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS readings(id INTEGER PRIMARY KEY, at REAL, channel TEXT, value REAL);
          CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY, payload TEXT);
        ''')
        saved = self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()
        saved = json.loads(saved['payload']) if saved else {}
        self.runtime = saved.get('runtime_seconds', 0.0)
        self.distance_cm = saved.get('distance_cm', 0.0)
        self.jam_count = saved.get('jam_count', 0)
        self.episode = saved.get('episode', False)
        self.deviation_since = None  # Shared timer: speed outside OR current outside.
        self.abnormal = saved.get('abnormal', False)
        self.channels = {}
        for name in ('speed', 'current', 'voltage'):
            previous = saved.get('channels', {}).get(name, {})
            self.channels[name] = {
                'samples': deque(previous.get('samples', []), maxlen=self.config['baseline_samples']),
                'value': None, 'at': None, 'pending': None,
                'reference': previous.get('reference'), 'alarm': previous.get('alarm', False),
            }
        self.connected = False
        self.message = 'MQTT not connected'
        self.last_error = None
        self.bad_messages = 0

    # SECTION: Connection loss breaks timer and integration continuity.
    # Baselines and unresolved abnormal episodes are retained, but old readings lose
    # their freshness. A reconnect therefore cannot turn an outage into measured
    # running distance or make a broken sensor look continuously out of range.
    def connection(self, connected, message):
        with self.lock:
            self.connected, self.message = connected, message
            if not connected:
                self.deviation_since = None
                for channel in self.channels.values():
                    channel['at'] = None
                    channel['pending'] = None

    # SECTION: Parse plain numeric MQTT payloads or a configured JSON field.
    # Speed units are converted to cm/s and current to amperes using explicit scales.
    # Retained/duplicate deliveries are filtered by the transport before this point;
    # malformed input invalidates its channel rather than supplying a made-up zero.
    def ingest(self, name, value):
        if name not in self.channels:
            raise ValueError('Unknown sensor channel')
        if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1e9:
            self.invalidate(name, 'Invalid ' + name + ' measurement')
            return False
        with self.lock, self.db:
            now = self.clock()
            # Expire old evidence BEFORE replacing it with a new fresh sample.
            # Otherwise a long silent gap followed by another bad reading could
            # accidentally inherit the old shared timer's start time.
            self._evaluate(now)
            channel = self.channels[name]
            previous_age = now - channel['at'] if channel['at'] is not None else None
            continuous = previous_age is not None and 0 <= previous_age <= self.config['stale_seconds']
            if name == 'speed' and continuous and self.connected:
                # Left-endpoint integration: assume the last fresh measured speed
                # held until this observation. No interval spanning a gap is added.
                if channel['value'] > self.config['moving_threshold_cm_s']:
                    self.runtime += previous_age
                    self.distance_cm += channel['value'] * previous_age
            if not continuous:
                channel['pending'] = None
            channel['value'], channel['at'] = float(value), now
            if name in ('speed', 'current'):
                self._classify(channel, now)
            self.db.execute('INSERT INTO readings(at,channel,value) VALUES(?,?,?)', (self.wall(), name, value))
            self.last_error = None
            self._evaluate(now)
            self._save()
        return True

    # SECTION: Establish a prior-normal rolling average, then test this reading.
    # Warm-up collects actual observations. Once a reading crosses the ±15% band,
    # the reference freezes and abnormal samples are excluded from the average.
    # Returning inside that frozen band clears the candidate/alarm for this channel.
    def _classify(self, channel, now):
        samples = channel['samples']
        if len(samples) < self.config['minimum_samples'] and not channel['alarm']:
            samples.append(channel['value'])
            channel['reference'] = sum(samples) / len(samples)
            return
        reference = channel['reference'] if channel['pending'] is not None or channel['alarm'] else sum(samples) / len(samples)
        channel['reference'] = reference
        deviation = abs(channel['value'] - reference)
        outside = deviation > abs(reference) * self.config['deviation_fraction'] + 1e-12
        if outside:
            if channel['pending'] is None:
                channel['pending'] = now
        else:
            channel['pending'], channel['alarm'] = None, False
            samples.append(channel['value'])
            channel['reference'] = sum(samples) / len(samples)

    # SECTION: Count abnormal episodes, not timer ticks or individual packets.
    # The shared timer runs while EITHER fresh reading is outside its band.
    # Overlapping current/speed alarms count as one unresolved episode. Gaps never
    # clear an existing alarm; both fresh normal channels are needed for recovery.
    def _evaluate(self, now):
        for name in ('speed', 'current'):
            channel = self.channels[name]
            fresh = self._fresh(channel, now)
            if not fresh:
                channel['pending'] = None
        deviating = [self.channels[name] for name in ('speed','current')
                     if self._fresh(self.channels[name], now) and self.channels[name]['pending'] is not None]
        if deviating:
            if self.deviation_since is None:
                self.deviation_since = now
            if now-self.deviation_since > self.config['deviation_seconds']:
                self.abnormal = True
                for channel in deviating:
                    channel['alarm'] = True
        else:
            self.deviation_since = None
            if all(self._ready(self.channels[name], now) for name in ('speed','current')):
                self.abnormal = False
        alarm = self.abnormal or any(self.channels[name]['alarm'] for name in ('speed', 'current'))
        if alarm and not self.episode:
            self.episode = True
            self.jam_count += 1
        elif not alarm and all(self._ready(self.channels[name], now) for name in ('speed', 'current')):
            self.episode = False

    # SECTION: Separate a fresh observation from an initialized baseline.
    # A channel can have a useful historical average but no recent measurement.
    # This is why freshness and minimum sample count are tested independently.
    def _fresh(self, channel, now):
        return self.connected and channel['at'] is not None and 0 <= now-channel['at'] <= self.config['stale_seconds']

    # SECTION: Verified normal requires freshness and an established average.
    # Fresh data alone is insufficient: a baseline also needs enough observations.
    # Restored baselines still require a new live measurement after restarting.
    def _ready(self, channel, now):
        return self._fresh(channel, now) and len(channel['samples']) >= self.config['minimum_samples']

    # SECTION: Invalid packets explicitly break that channel's continuity.
    # Their arrival does not refresh its value. Persisted alarms and accepted
    # baseline samples remain available for an honest recovery comparison later.
    def invalidate(self, name, message):
        with self.lock:
            self.channels[name]['at'] = None
            self.channels[name]['pending'] = None
            self.bad_messages += 1
            self.last_error = message

    # SECTION: Operator-requested baseline reset, without erasing operating totals.
    # Do this only with the belt in its intended steady operating condition.
    # Existing alarms are explicitly reset by this action; FLAG remains false
    # through warm-up, while prior episode count and recorded readings remain.
    def recalibrate(self):
        with self.lock, self.db:
            for name in ('speed', 'current'):
                channel = self.channels[name]
                channel['samples'].clear()
                channel['pending'], channel['reference'], channel['alarm'] = None, None, False
            self.episode = False
            self.abnormal, self.deviation_since = False, None
            self._save()

    # SECTION: Persist totals, baseline and unresolved episode state together.
    # Monotonic timestamps are intentionally not saved: they are process-local,
    # and downtime must never be integrated as belt travel after restarting.
    def _save(self):
        payload = {'runtime_seconds': self.runtime, 'distance_cm': self.distance_cm,
                   'jam_count': self.jam_count, 'episode': self.episode, 'abnormal': self.abnormal,
                   'channels': {name: {'samples': list(channel['samples']), 'reference': channel['reference'],
                                       'alarm': channel['alarm']} for name, channel in self.channels.items()}}
        self.db.execute('INSERT OR REPLACE INTO state VALUES(1,?)', (json.dumps(payload),))

    # SECTION: Produce the dashboard and publication state from one evaluation.
    # FLAG is true only when both channels are fresh/calibrated and no alarm exists.
    # Before the 10-second deadline a candidate remains normal but visibly timing.
    # Missing or warming data publishes false with a distinct explanatory STATUS.
    def snapshot(self):
        with self.lock, self.db:
            now = self.clock()
            self._evaluate(now)
            metrics = {}
            for name, channel in self.channels.items():
                fresh = self._fresh(channel, now)
                ready = self._ready(channel, now)
                reference = channel['reference']
                metrics[name] = {
                    'value': channel['value'] if fresh else None,
                    'average': reference, 'samples': len(channel['samples']), 'ready': ready,
                    'lower': reference*(1-self.config['deviation_fraction']) if reference is not None else None,
                    'upper': reference*(1+self.config['deviation_fraction']) if reference is not None else None,
                    'deviation_seconds': max(0, now-channel['pending']) if channel['pending'] is not None else 0,
                    'timing': channel['pending'] is not None, 'abnormal': channel['alarm'],
                }
            alarm = self.abnormal or any(metrics[name]['abnormal'] for name in ('speed','current'))
            fresh = all(metrics[name]['value'] is not None for name in ('speed','current'))
            ready = all(metrics[name]['ready'] for name in ('speed','current'))
            state = 'Abnormal' if alarm else 'Unknown' if not fresh else 'Calibrating' if not ready else 'Normal'
            flag = ready and not alarm
            history = [dict(row) for row in self.db.execute('SELECT at,channel,value FROM readings ORDER BY id DESC LIMIT 180')]
            self._save()
            return {'conveyor': 4, 'connected': self.connected, 'connection_message': self.message,
                    'flag': bool(flag), 'state': state, 'metrics': metrics,
                    'runtime_seconds': self.runtime, 'distance_m': self.distance_cm/100,
                    'jam_count': self.jam_count, 'history': list(reversed(history)),
                    'deviation_seconds': max(0, now-self.deviation_since) if self.deviation_since is not None else 0,
                    'timing': self.deviation_since is not None,
                    'config': self.config, 'last_error': self.last_error, 'bad_messages': self.bad_messages}

    # SECTION: Release SQLite only after the subscriber and evaluator stop.
    # This prevents a late MQTT callback from writing into a closed connection.
    def close(self):
        self.db.close()


# SECTION: Transport adapter for the supplied conveyor 4 raw topics.
# It subscribes only to configured inputs and publishes JSON true/false plus a
# diagnostic STATUS on the same broker. FLAG is not a run/stop motor command.
class Conveyor4MQTT:
    # Build exact input-topic mappings and publication bookkeeping. No connection
    # is made until start() runs, so unit tests can supply a recording fake client
    # without touching the laboratory broker or any physical device.
    def __init__(self, monitor, factory=mqtt_client, vision=None):
        self.monitor, self.config, self.factory = monitor, monitor.config, factory
        self.vision = vision
        self.client = None
        self.last_published = None
        self.lock = threading.Lock()
        self.topics = {self.config[name+'_topic']: name for name in ('speed','current','voltage') if self.config[name+'_topic']}
        self.publish_error = None
        self.last_status_at = None

    # SECTION: Configure a false last will before initiating the MQTT session.
    # If the process/network disappears unexpectedly, downstream subscribers see
    # false rather than a retained old normal state. Sensor values must still
    # arrive after connection; retained readings do not establish live health.
    def start(self):
        self.client = self.factory('team8-c4-' + uuid.uuid4().hex[:10])
        self.client.will_set(self.config['flag_topic'], 'false', qos=1, retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        self.monitor.connection(False, 'Connecting to MQTT broker')
        self.client.connect_async(self.config['broker'], int(self.config['port']), 30)
        self.client.loop_start()

    # SECTION: Re-subscribe on reconnect and force an initial state publication.
    # Connection alone never restores old readings. A new fresh speed/current
    # pair must establish health before FLAG can become true again.
    def on_connect(self, client, userdata, flags, rc):
        self.monitor.connection(rc == 0, 'MQTT connected' if rc == 0 else 'Broker rejected connection')
        if rc == 0:
            for topic in self.topics:
                client.subscribe(topic, qos=1)
            if self.vision:
                for key in ('camera_topic', 'tags_topic', 'camera_status_topic'):
                    if self.config[key]:
                        client.subscribe(self.config[key], qos=0 if key == 'camera_topic' else 1)
            self.last_published = None
            self.tick(force=True)

    # SECTION: Mark local data unknown immediately when the connection is lost.
    # The broker's retained false last-will covers an unexpected remote loss.
    # No disconnected interval can continue a timer or add operating distance.
    def on_disconnect(self, client, userdata, rc):
        self.monitor.connection(False, 'MQTT disconnected — readings unknown')
        if self.vision:
            self.vision.disconnect()

    # SECTION: Decode exactly the configured raw number or JSON field.
    # Speed/current scaling is explicit. Retained and duplicate deliveries do not
    # advance warm-up or timers, and voltage is never relabelled as amperage.
    def on_message(self, client, userdata, message):
        # Camera bytes never enter the numeric sensor decoder or FLAG logic.
        # The preview is deliberately unretained; tag events use delivery IDs.
        if self.vision:
            if message.topic == self.config['camera_topic']:
                self.vision.receive_frame(message.payload, message.retain)
                return
            if message.topic == self.config['tags_topic']:
                self.vision.receive_tags(message.payload, message.retain)
                return
            if message.topic == self.config['camera_status_topic']:
                self.vision.receive_status(message.payload)
                return
        if message.retain or getattr(message, 'dup', False) or len(message.payload) > 4096:
            return
        name = self.topics.get(message.topic)
        if name is None:
            return
        try:
            value = json.loads(message.payload.decode('utf-8'))
            key = self.config.get(name+'_key')
            if key:
                value = value[key]
            if type(value) not in (int, float):
                raise ValueError('Expected numeric sensor payload')
            if name == 'speed':
                value *= self.config['speed_scale_to_cm_s']
            elif name == 'current':
                value *= self.config['current_scale_to_a']
            self.monitor.ingest(name, value)
        except (ValueError, TypeError, KeyError, UnicodeError):
            self.monitor.invalidate(name, 'Invalid payload on ' + message.topic)
        self.tick()

    # SECTION: Publish transitions promptly and diagnostics at most once per second.
    # JSON booleans are encoded as the exact bytes true/false, not Python True/False.
    # A failed publish is visible to the UI and retried at the next supervisor tick.
    def tick(self, force=False):
        # Serialize snapshot and queueing together so concurrent callbacks cannot
        # publish an older normal state after a newer abnormal state was queued.
        with self.lock, self.monitor.lock:
            state = self.monitor.snapshot()
            if not self.client or not state['connected']:
                return state
            identity = (state['flag'], state['state'])
            if force or identity != self.last_published:
                info = self.client.publish(self.config['flag_topic'], json.dumps(state['flag']), qos=1, retain=True)
                if info.rc == 0:
                    self.last_published = identity
                    self.publish_error = None
                else:
                    self.publish_error = 'FLAG publish not queued; MQTT rc=' + str(info.rc)
            status = {'flag': state['flag'], 'state': state['state'], 'conveyor': 4, 'at': self.monitor.wall(),
                      'jam_count': state['jam_count'], 'reason': self.monitor.last_error,
                      'current_configured': bool(self.config['current_topic'])}
            now = self.monitor.clock()
            if force or self.last_status_at is None or now-self.last_status_at >= 1:
                info = self.client.publish(self.config['status_topic'], json.dumps(status), qos=0, retain=True)
                if info.rc == 0:
                    self.last_status_at = now
                else:
                    self.publish_error = 'STATUS publish not queued; MQTT rc=' + str(info.rc)
            return state

    # SECTION: Clear retained normal state during an orderly shutdown too.
    # Wait briefly for the false publication, then stop the MQTT loop before
    # the owner closes the measurement store. The last will covers crashes.
    def stop(self):
        if self.client:
            try:
                info = self.client.publish(self.config['flag_topic'], 'false', qos=1, retain=True)
                info.wait_for_publish(timeout=2)
            except Exception:
                pass
            self.client.disconnect()
            self.client.loop_stop()
