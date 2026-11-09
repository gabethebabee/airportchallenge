"""Persistent barcode A-to-B timing. All timestamps use the dashboard server clock."""
import math
import sqlite3
import threading
import time
import uuid


# Own the persistent journey/scan records and bag incidents, independently of the display.
# This is the source of truth for the A-to-B workflow. It stores departures, scans and incidents
# in SQLite so reloading the browser or restarting Python does not erase bag history. An
# injected clock makes time-based behavior testable without waiting.
class TransitTracker:
    # Open SQLite, create missing tables without deleting existing history, and serialize
    # concurrent access.
    # The database path chooses persistent storage or an in-memory test database. Missing tables
    # and a unique active-journey index are created without dropping previous records. A
    # reentrant lock lets HTTP and MQTT threads share the connection safely.
    def __init__(self, path='team8transit.sqlite3', clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        # trips stores each A-to-B journey; scans is its event trail; incidents records alert receipt/recovery.
        # CREATE IF NOT EXISTS adds new structures without erasing previously recorded bags.
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, minimum REAL, maximum REAL);
        INSERT OR IGNORE INTO settings VALUES (1,0,10);
        CREATE TABLE IF NOT EXISTS trips (
          id INTEGER PRIMARY KEY, barcode TEXT, source TEXT, started REAL, arrived REAL,
          minimum REAL, maximum REAL);
        CREATE TABLE IF NOT EXISTS scans (
          event_id TEXT PRIMARY KEY, barcode TEXT, checkpoint TEXT, source TEXT, at REAL,
          trip_id INTEGER, outcome TEXT);
        CREATE TABLE IF NOT EXISTS journey_sequence (id INTEGER PRIMARY KEY, next_id INTEGER);
        INSERT OR IGNORE INTO journey_sequence SELECT 1,COALESCE(MAX(id),0)+1 FROM trips;
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_trip ON trips(barcode,source) WHERE arrived IS NULL;
        CREATE TABLE IF NOT EXISTS transit_incidents (
          trip_id INTEGER PRIMARY KEY, raised REAL, acknowledged REAL, resolved REAL);
        ''')
        self.db.commit()

    # Validate a new travel-time standard; running journeys retain the limits captured at
    # departure.
    # Inputs are the minimum and maximum allowed seconds. The range is validated and saved for
    # future departures; an active trip already contains its own copy, so adjusting the standard
    # cannot silently reclassify its earlier departure.
    def configure(self, minimum, maximum):
        if isinstance(minimum, bool) or isinstance(maximum, bool):
            raise ValueError('Use numeric time limits')
        low, high = float(minimum), float(maximum)
        if not (math.isfinite(low) and math.isfinite(high) and 0 <= low < high <= 86400):
            raise ValueError('Use 0 <= minimum < maximum <= 86400 seconds')
        with self.lock, self.db:
            self.db.execute('UPDATE settings SET minimum=?, maximum=? WHERE id=1', (low, high))
        return {'message': 'Standard saved for new trips. Existing trips keep their original limits.'}

    # Match the barcode/source to an active journey; A starts it and B completes it without
    # resetting on duplicates.
    # Inputs identify a barcode, checkpoint, source and optional delivery ID. Duplicate IDs and
    # repeated A sightings do not restart a journey. A valid B arrival records elapsed
    # time/recovery; a B scan without A is only logged, because no start time can be inferred.
    def scan(self, barcode, checkpoint, source='manual', event_id=None):
        if not isinstance(barcode, str) or not barcode.strip() or len(barcode)>256:
            raise ValueError('Barcode must contain 1–256 characters')
        barcode=barcode.strip()
        if checkpoint not in ('A','B') or source not in ('manual','camera','mqtt'):
            raise ValueError('Checkpoint must be A or B; source must be manual, camera, or mqtt')
        event_id=event_id or str(uuid.uuid4())
        if not isinstance(event_id,str) or not 1 <= len(event_id) <= 128:
            raise ValueError('Invalid event ID')
        with self.lock, self.db:
            old=self.db.execute('SELECT * FROM scans WHERE event_id=?',(event_id,)).fetchone()
            if old:
                if (old['barcode'],old['checkpoint'],old['source']) != (barcode,checkpoint,source):
                    raise ValueError('Event ID already belongs to another scan')
                return {'message':'Duplicate event ignored','trip_id':old['trip_id']}
            now=self.clock()
            # Barcode AND source identify an active journey: a manual test must not finish a real bag.
            active=self.db.execute('SELECT * FROM trips WHERE barcode=? AND source=? AND arrived IS NULL',(barcode,source)).fetchone()
            trip_id=active['id'] if active else None
            # Repeated camera frames at A leave the original start time intact.
            if checkpoint=='A':
                if active:
                    outcome='Already travelling; repeated A did not restart clock'
                else:
                    last=self.db.execute("SELECT at FROM scans WHERE barcode=? AND source=? AND checkpoint=? AND outcome!='Cleared by journey reset' ORDER BY at DESC LIMIT 1",(barcode,source,'A')).fetchone()
                    if last and now-last['at']<3:
                        outcome='Repeated A scan suppressed (3-second debounce)'
                    else:
                        config=self.db.execute('SELECT * FROM settings WHERE id=1').fetchone()
                        # Keep journey IDs increasing across resets, preventing an
                        # old acknowledgement request from targeting a new bag.
                        trip_id=self.db.execute('SELECT next_id FROM journey_sequence WHERE id=1').fetchone()[0]
                        self.db.execute('UPDATE journey_sequence SET next_id=next_id+1 WHERE id=1')
                        self.db.execute('INSERT INTO trips(id,barcode,source,started,minimum,maximum) VALUES(?,?,?,?,?,?)',
                            (trip_id,barcode,source,now,config['minimum'],config['maximum']))
                        outcome='Clock started at A'
            # A B scan with no active A is logged below but cannot invent a travel time.
            elif active:
                if now<active['started']:
                    raise ValueError('Server clock moved backwards; timing unavailable')
                # Record a late arrival even if no browser was open at its deadline.
                if now - active['started'] > active['maximum']:
                    self.db.execute('INSERT OR IGNORE INTO transit_incidents(trip_id,raised) VALUES(?,?)',
                                    (trip_id, active['started'] + active['maximum']))
                self.db.execute('UPDATE trips SET arrived=? WHERE id=?',(now,trip_id))
                self.db.execute('UPDATE transit_incidents SET resolved=? WHERE trip_id=?', (now,trip_id))
                outcome='Arrived at B; travel time recorded'
            else:
                outcome='B without active A; no travel time inferred'
            self.db.execute('INSERT INTO scans VALUES(?,?,?,?,?,?,?)',(event_id,barcode,checkpoint,source,now,trip_id,outcome))
            return {'message':outcome,'trip_id':trip_id}

    # Build the current timing view from server timestamps, including overdue trips that have
    # not reached B.
    # The browser receives the latest journey and scan records plus calculated elapsed
    # seconds/status. Calculations use the server clock and each departure standard. Active
    # trips remain open after their deadline so a later B scan can still resolve the incident.
    def snapshot(self):
        self.evaluate_incidents()
        with self.lock:
            now=self.clock()
            config=dict(self.db.execute('SELECT minimum,maximum FROM settings WHERE id=1').fetchone())
            trips=[]
            for record in self.db.execute('SELECT * FROM trips ORDER BY id DESC LIMIT 100'):
                t=dict(record)
                elapsed=(t['arrived'] if t['arrived'] is not None else now)-t['started']
                t['elapsed_seconds']=round(max(0,elapsed),2)
                # Classify from the journey's original limits; later settings do not rewrite history.
                t['status']=('Clock error' if elapsed<0 else
                    ('Overdue' if elapsed>t['maximum'] else 'Travelling') if t['arrived'] is None else
                    'Too fast' if elapsed<t['minimum'] else 'Late' if elapsed>t['maximum'] else 'On time')
                trips.append(t)
            scans=[dict(r) for r in self.db.execute('SELECT * FROM scans ORDER BY at DESC,rowid DESC LIMIT 100')]
            return {'standard':config,'trips':trips,'scans':scans,'server_time':now,
                    'message':'Latest 100 trips and scans; all records retained in SQLite. Overdue means B is unconfirmed, not proof of a jam.'}

    # Insert one overdue incident per journey once its deadline passes; the unique trip ID
    # prevents alert floods.
    # The SQL query finds active trips whose deadline has passed and inserts their incident
    # once. The trip ID is the incident key, so periodic evaluation cannot flood the operator
    # with a new alert every second.
    def evaluate_incidents(self):
        """Runs in the server supervisor too; an open browser is not required."""
        with self.lock, self.db:
            self.db.execute('''INSERT OR IGNORE INTO transit_incidents(trip_id,raised)
                SELECT id,started+maximum FROM trips WHERE arrived IS NULL AND started+maximum < ?''',
                (self.clock(),))

    # Combine incident history with its bag details, keeping every active incident visible.
    # Incident rows are joined to their original trips to supply barcode, source and expected
    # arrival context. All unresolved incidents stay visible alongside recent recovered
    # incidents, making acknowledgement and later recovery independently reviewable.
    def incidents(self):
        self.evaluate_incidents()
        with self.lock:
            rows = self.db.execute('''SELECT i.*,t.barcode,t.source,t.started,t.maximum,t.arrived
                FROM transit_incidents i JOIN trips t ON t.id=i.trip_id
                WHERE i.resolved IS NULL OR i.trip_id IN
                  (SELECT trip_id FROM transit_incidents ORDER BY raised DESC LIMIT 100)
                ORDER BY i.raised DESC''')
            return [{**dict(row), 'kind': 'bag', 'id': row['trip_id'], 'checkpoint': 'A',
                     'title': 'Bag overdue between A and B',
                     'detail': 'Last confirmed at A. Check the route, camera and scanner; blockage is not confirmed.'}
                    for row in rows]

    # Record when an operator received the warning while leaving recovery to an actual B scan.
    # The operator provides an incident/trip ID. Only its first receipt time is saved, and its
    # resolved time is left untouched. An actual matching B scan is still needed to prove this
    # journey reached the next checkpoint.
    def acknowledge(self, trip_id):
        with self.lock, self.db:
            result = self.db.execute('UPDATE transit_incidents SET acknowledged=COALESCE(acknowledged,?) WHERE trip_id=?',
                                     (self.clock(), trip_id))
            if not result.rowcount:
                raise ValueError('Incident not found')
        return {'message': 'Alert acknowledged; arrival at B is still required to resolve it.'}

    # SECTION: Reset the operator's journey workspace atomically, including all
    # overdue incidents. Keep scan delivery receipts detached from deleted trips
    # so an MQTT retransmission cannot recreate a journey that was just cleared.
    # Detaching them also excludes old A sightings from the new-trip debounce.
    # Settings and the separate motor database are deliberately outside this reset.
    def reset_journeys(self):
        with self.lock, self.db:
            count = self.db.execute('SELECT COUNT(*) FROM trips').fetchone()[0]
            self.db.execute('DELETE FROM transit_incidents')
            self.db.execute('UPDATE scans SET trip_id=NULL, outcome=?', ('Cleared by journey reset',))
            self.db.execute('DELETE FROM trips')
        return {'message': 'Cleared {} journeys and their overdue alerts. Motor totals and timing limits kept.'.format(count),
                'cleared': count}

    # Read all checkpoint events for one journey, including events recorded before a problem
    # occurred.
    # A trip ID selects its departure limits and every linked checkpoint event in time order.
    # The live timeline therefore contains observations made before the incident, rather than
    # beginning its history only when an alarm was raised.
    def history(self, trip_id):
        with self.lock:
            trip = self.db.execute('SELECT * FROM trips WHERE id=?', (trip_id,)).fetchone()
            if trip is None:
                raise ValueError('Journey not found')
            scans = self.db.execute('SELECT * FROM scans WHERE trip_id=? ORDER BY at,rowid', (trip_id,))
            return {'trip': dict(trip), 'scans': [dict(row) for row in scans]}

    # Release owned resources after the worker/server has stopped using them.
    # The owning server calls this after stopping background threads. Closing earlier could race
    # an MQTT or HTTP write, which is why lifecycle ordering is handled by the dashboard main
    # function.
    def close(self):
        self.db.close()
