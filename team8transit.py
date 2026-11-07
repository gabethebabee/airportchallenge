"""Persistent barcode A-to-B timing. All timestamps use the dashboard server clock."""
import math
import sqlite3
import threading
import time
import uuid


class TransitTracker:
    def __init__(self, path='team8transit.sqlite3', clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, minimum REAL, maximum REAL);
        INSERT OR IGNORE INTO settings VALUES (1,0,10);
        CREATE TABLE IF NOT EXISTS trips (
          id INTEGER PRIMARY KEY, barcode TEXT, source TEXT, started REAL, arrived REAL,
          minimum REAL, maximum REAL);
        CREATE TABLE IF NOT EXISTS scans (
          event_id TEXT PRIMARY KEY, barcode TEXT, checkpoint TEXT, source TEXT, at REAL,
          trip_id INTEGER, outcome TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_trip ON trips(barcode,source) WHERE arrived IS NULL;
        ''')
        self.db.commit()

    def configure(self, minimum, maximum):
        if isinstance(minimum, bool) or isinstance(maximum, bool):
            raise ValueError('Use numeric time limits')
        low, high = float(minimum), float(maximum)
        if not (math.isfinite(low) and math.isfinite(high) and 0 <= low < high <= 86400):
            raise ValueError('Use 0 <= minimum < maximum <= 86400 seconds')
        with self.lock, self.db:
            self.db.execute('UPDATE settings SET minimum=?, maximum=? WHERE id=1', (low, high))
        return {'message': 'Standard saved for new trips. Existing trips keep their original limits.'}

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
            active=self.db.execute('SELECT * FROM trips WHERE barcode=? AND source=? AND arrived IS NULL',(barcode,source)).fetchone()
            trip_id=active['id'] if active else None
            if checkpoint=='A':
                if active:
                    outcome='Already travelling; repeated A did not restart clock'
                else:
                    last=self.db.execute('SELECT at FROM scans WHERE barcode=? AND source=? AND checkpoint=? ORDER BY at DESC LIMIT 1',(barcode,source,'A')).fetchone()
                    if last and now-last['at']<3:
                        outcome='Repeated A scan suppressed (3-second debounce)'
                    else:
                        config=self.db.execute('SELECT * FROM settings WHERE id=1').fetchone()
                        trip_id=self.db.execute('INSERT INTO trips(barcode,source,started,minimum,maximum) VALUES(?,?,?,?,?)',
                            (barcode,source,now,config['minimum'],config['maximum'])).lastrowid
                        outcome='Clock started at A'
            elif active:
                if now<active['started']:
                    raise ValueError('Server clock moved backwards; timing unavailable')
                self.db.execute('UPDATE trips SET arrived=? WHERE id=?',(now,trip_id))
                outcome='Arrived at B; travel time recorded'
            else:
                outcome='B without active A; no travel time inferred'
            self.db.execute('INSERT INTO scans VALUES(?,?,?,?,?,?,?)',(event_id,barcode,checkpoint,source,now,trip_id,outcome))
            return {'message':outcome,'trip_id':trip_id}

    def snapshot(self):
        with self.lock:
            now=self.clock()
            config=dict(self.db.execute('SELECT minimum,maximum FROM settings WHERE id=1').fetchone())
            trips=[]
            for record in self.db.execute('SELECT * FROM trips ORDER BY id DESC LIMIT 100'):
                t=dict(record)
                elapsed=(t['arrived'] if t['arrived'] is not None else now)-t['started']
                t['elapsed_seconds']=round(max(0,elapsed),2)
                t['status']=('Clock error' if elapsed<0 else
                    ('Overdue' if elapsed>t['maximum'] else 'Travelling') if t['arrived'] is None else
                    'Too fast' if elapsed<t['minimum'] else 'Late' if elapsed>t['maximum'] else 'On time')
                trips.append(t)
            scans=[dict(r) for r in self.db.execute('SELECT * FROM scans ORDER BY at DESC,rowid DESC LIMIT 100')]
            return {'standard':config,'trips':trips,'scans':scans,'server_time':now,
                    'message':'Latest 100 trips and scans; all records retained in SQLite. Overdue means B is unconfirmed, not proof of a jam.'}

    def close(self):
        self.db.close()
