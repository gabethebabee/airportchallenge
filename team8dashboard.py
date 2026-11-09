"""Team 8 conveyor dashboard. MQTT input uses optional Paho.

Run: python team8dashboard.py
Open: http://127.0.0.1:8080
Default: conveyor 4 speed/current monitoring and MQTT FLAG publication.
Camera: Jetson MQTT previews and AprilTag journeys via team8vision.py.
Older explicit MQTT configs retain barcode timing and the legacy dashboard.
Default frontend: team8conveyor4.html, team8conveyor4.css, team8conveyor4.js.
"""

import argparse
import json
import secrets
import os
import threading

from pathlib import Path
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler
try:
    from http.server import ThreadingHTTPServer
except ImportError:  # Python 3.6 on older Jetson images.
    from http.server import HTTPServer
    from socketserver import ThreadingMixIn

    # Compatibility fallback: handle simultaneous requests on older Python versions shipped on
    # Jetson.
    # Older Python images do not provide the newer threaded server class. Combining the standard
    # mixin and HTTP server lets camera uploads, polling and button requests proceed
    # independently instead of blocking each other.
    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

from team8transit import TransitTracker
from team8monitor import CameraFrames, MQTTInputs, SensorMonitor
from team8conveyor4 import Conveyor4Monitor, Conveyor4MQTT
from team8vision import VisionInbox

# OPTIONAL HARDWARE MODULE: comment out this import to remove the integration.
from team8conveyor_control import ConveyorControl, ENABLE_CONVEYOR_CONTROL

# These objects are started in main(), not on import, so tests can supply safe in-memory substitutes.
CONTROL = None
TRACKER = None
SENSORS = None
MQTT = None
C4 = None
C4_MQTT = None
VISION = None
VISION_B = None
USE_CONVEYOR4 = True
FRAMES = CameraFrames()
# This browser-session token is separate from the scanner password and the PLC control token.
CONTROL_SESSION = secrets.token_urlsafe(32)


ASSET_DIR = Path(__file__).resolve().parent



# HTTP endpoints used by the browser and scanner; this class routes requests to the owning
# backend.
# The browser asks this class for pages, sensor state and recorded journeys. Scanner uploads
# arrive here too. Each endpoint validates its caller before handing data to a store; the HTTP
# layer does not calculate motor health itself.
class DashboardHandler(BaseHTTPRequestHandler):
    # Encode an API response, declare its byte length, and prevent cached sensor/status
    # responses.
    # Other endpoints pass in a Python dictionary and HTTP status code. This turns the
    # dictionary into UTF-8 JSON and sends the correct headers so the browser knows how to read
    # it and does not reuse an old sensor response.
    def send_json(self, data, status=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    # Check the requested host and browser origin before allowing local dashboard actions.
    # The server normally listens on this computer only. Host and Origin checks additionally
    # distinguish the local dashboard from requests initiated by another website; this check is
    # one part of authorization, not the PLC password.
    def local_request(self):
        # Bind to loopback and reject unexpected Host headers / cross-site requests.
        expected = f'127.0.0.1:{self.server.server_port}'
        host = self.headers.get('Host', '')
        origin = self.headers.get('Origin')
        return host in (expected, f'localhost:{self.server.server_port}') and (not origin or origin == 'http://' + host)

    # Dispatch incoming updates/actions; conveyor commands remain behind their own session
    # check.
    # POST requests change something, such as saving a scan, acknowledging an alert or
    # explicitly requesting a conveyor action. This dispatcher separates those routes so scanner
    # credentials cannot grant physical-control access.
    def do_POST(self):
        # Journey reset has its own authenticated action. It clears the journey
        # store only; motor totals, camera sessions and hardware are independent.
        if self.path == '/api/conveyor4/reset-journeys':
            if not self.local_request() or self.headers.get('X-Team8-Session') != CONTROL_SESSION:
                return self.send_json({'message':'Invalid local session'},403)
            if TRACKER is None:
                return self.send_json({'message':'Journey tracker unavailable'},503)
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 256:
                    raise ValueError('Invalid request size')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload,dict) or payload.get('clear') is not True:
                    raise ValueError('Expected clear: true')
                return self.send_json(TRACKER.reset_journeys())
            except (TypeError,ValueError) as error:
                return self.send_json({'message':str(error)},400)
        if self.path == '/api/conveyor4/tag-ack':
            if not self.local_request() or self.headers.get('X-Team8-Session') != CONTROL_SESSION:
                return self.send_json({'message': 'Invalid local session'}, 403)
            if TRACKER is None:
                return self.send_json({'message': 'Journey tracker unavailable'}, 503)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024:
                    raise ValueError('Invalid request size')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict) or type(payload.get('trip_id')) is not int:
                    raise ValueError('Expected integer trip_id')
                return self.send_json(TRACKER.acknowledge(payload['trip_id']))
            except (ValueError, TypeError) as error:
                return self.send_json({'message': str(error)}, 400)
        if self.path == '/api/conveyor4/recalibrate':
            if not self.local_request() or self.headers.get('X-Team8-Session') != CONTROL_SESSION:
                return self.send_json({'message': 'Invalid local session'}, 403)
            if C4 is None:
                return self.send_json({'message': 'Conveyor 4 monitor unavailable'}, 503)
            C4.recalibrate()
            if C4_MQTT:
                C4_MQTT.tick(force=True)
            return self.send_json({'message': 'Recalibrating from new readings; cumulative totals are preserved.'})
        if self.path.startswith('/api/camera/'):
            return self.camera_post()
        if self.path.startswith('/api/monitor/'):
            return self.monitor_post()
        if self.path.startswith('/api/transit/'):
            return self.transit_post()
        if self.path != '/api/conveyor':
            return self.send_json({'message': 'Not found'}, 404)
        if not self.local_request() or self.headers.get('X-Team8-Session') != CONTROL_SESSION:
            return self.send_json({'message': 'Invalid local control session'}, 403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024:
                raise ValueError('Invalid request size')
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict) or payload.get('action') not in ('status', 'run', 'stop'):
                raise ValueError('Invalid action')
            if CONTROL is None:
                return self.send_json({'enabled': False, 'message': 'Hardware module disabled; no command sent.'})
            return self.send_json(CONTROL.request(payload['action']))
        except (ValueError, json.JSONDecodeError):
            return self.send_json({'message': 'Invalid control request'}, 400)
        except Exception:
            # Never leak PLC credentials or automatically retry physical commands.
            return self.send_json({'message': 'PLC request failed or was rejected; inspect PLC and connection. Command outcome unknown.'}, 502)

    # Serve only allowlisted frontend files, recorded state, and fresh camera frames.
    # GET requests read state or fetch frontend assets. Route-specific stores own the returned
    # data, while a fixed filename allowlist prevents a URL from exposing arbitrary project
    # files. Reading this interface never requests a motor run.
    def do_GET(self):
        self.path = urlsplit(self.path).path
        if self.path in ('/api/conveyor4/camera', '/api/conveyor4/camera/B'):
            if not self.local_request():
                return self.send_json({'message': 'Local dashboard requests only'}, 403)
            # Separate inboxes prevent one camera's sequence/session or offline
            # state from replacing the other camera's current image.
            inbox = VISION_B if self.path.endswith('/B') else VISION
            frame = inbox.jpeg() if inbox else None
            if frame is None:
                return self.send_json({'message': 'MQTT camera unavailable or stale'}, 503)
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(frame)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return self.wfile.write(frame)
        if self.path == '/api/conveyor4':
            if not self.local_request():
                return self.send_json({'message': 'Local dashboard requests only'}, 403)
            if C4 is None:
                return self.send_json({'message': 'Conveyor 4 monitor unavailable in legacy mode'}, 503)
            state = C4.snapshot()
            state['publish_error'] = C4_MQTT.publish_error if C4_MQTT else 'MQTT client not started'
            state['vision'] = VISION.snapshot() if VISION else None
            state['vision_b'] = VISION_B.snapshot() if VISION_B else None
            return self.send_json(state)
        if self.path.startswith('/api/transit/trip/'):
            if not self.local_request():
                return self.send_json({'message': 'Local dashboard requests only'}, 403)
            if TRACKER is None:
                return self.send_json({'message': 'Tracker unavailable'}, 503)
            try:
                return self.send_json(TRACKER.history(int(self.path.rsplit('/', 1)[1])))
            except ValueError:
                return self.send_json({'message': 'Journey not found'}, 404)
        if self.path == '/api/monitor':
            if not self.local_request():
                return self.send_json({'message': 'Local dashboard requests only'}, 403)
            if SENSORS is None or TRACKER is None:
                return self.send_json({'message': 'Monitor unavailable'}, 503)
            state = SENSORS.snapshot()
            bags = TRACKER.incidents()
            overdue = [item for item in bags if item['resolved'] is None and item['source'] != 'manual']
            # Combine only physical camera/MQTT bag evidence with fresh stall readings; manual tests are excluded.
            state['possible_jam'] = bool(overdue and state['fresh'] and state['state'] == 'Stalled')
            threshold = state['limits']['high_current_a']
            state['high_current_evidence'] = (state['possible_jam'] and threshold is not None and
                                              state['current_a'] is not None and state['current_a'] > threshold)
            state['incidents'] = sorted(state['incidents'] + bags, key=lambda item: item['raised'], reverse=True)
            state['cameras'] = FRAMES.status()
            state['checkpoint_topics'] = MQTT.config.get('checkpoint_topics', {}) if MQTT else {}
            state['mqtt_errors'] = MQTT.errors if MQTT else 0
            return self.send_json(state)
        if self.path in ('/api/camera/A', '/api/camera/B'):
            if not self.local_request():
                return self.send_json({'message': 'Local dashboard requests only'}, 403)
            frame = FRAMES.get(self.path[-1])
            if frame is None:
                return self.send_json({'message': 'Camera unavailable or stale'}, 503)
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(frame)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return self.wfile.write(frame)
        if self.path == '/api/transit':
            if not self.local_request():
                return self.send_json({'message': 'Local dashboard requests only'}, 403)
            if TRACKER is None:
                return self.send_json({'message': 'Timing tracker unavailable'}, 503)
            return self.send_json(TRACKER.snapshot())
        if self.path == '/api/conveyor/session':
            if not self.local_request():
                return self.send_json({'message': 'Local requests only'}, 403)
            return self.send_json({'token': CONTROL_SESSION})
        if self.path in ('/', '/index.html'):
            body = (ASSET_DIR / ('team8conveyor4.html' if USE_CONVEYOR4 else 'team8dashboard.html')).read_bytes()
            content_type = 'text/html; charset=utf-8'
        # An explicit asset list prevents URLs from reading arbitrary files from the project folder.
        elif self.path == '/team8conveyor4_sensors.json':
            body = (ASSET_DIR / 'team8conveyor4_sensors.json').read_bytes()
            content_type = 'application/json; charset=utf-8'
        elif self.path in ('/team8dashboard.css', '/team8dashboard.js', '/team8live.js', '/team8conveyor4.js', '/team8conveyor4.css'):
            body = (ASSET_DIR / self.path[1:]).read_bytes()
            content_type = ('text/css' if self.path.endswith('.css') else 'text/javascript') + '; charset=utf-8'
        elif self.path == '/health':
            body = json.dumps({'status': 'ok', 'mode': 'conveyor4' if USE_CONVEYOR4 else 'monitoring',
                               'mqtt_enabled': C4_MQTT is not None if USE_CONVEYOR4 else MQTT is not None}).encode('utf-8')
            content_type = 'application/json'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    # Check the shared scanner password without exposing it to the browser page.
    # The camera process sends a shared token in an HTTP header. This checks it against the
    # server environment using a timing-resistant comparison; the token is not read from a
    # submitted barcode or exposed in the page source.
    def scan_authorized(self):
        token = os.environ.get('TEAM8_SCAN_TOKEN', '')
        return len(token) >= 24 and secrets.compare_digest(self.headers.get('X-Team8-Scan-Token', ''), token)

    # Accept a bounded, timestamped JPEG from the scanner; no camera is opened by the server.
    # The scanner sends JPEG bytes and a capture timestamp for A or B. Size, format markers and
    # age are checked before the in-memory frame is replaced. Invalid or delayed frames do not
    # become a fresh-looking preview.
    def camera_post(self):
        if self.path not in ('/api/camera/A', '/api/camera/B'):
            return self.send_json({'message': 'Unknown checkpoint'}, 404)
        if not self.scan_authorized():
            return self.send_json({'message': 'Invalid scan token'}, 403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 4 <= size <= 300000:
                raise ValueError('JPEG must be under 300 kB')
            FRAMES.put(self.path[-1], self.rfile.read(size), self.headers.get('X-Team8-Captured-At'))
            return self.send_json({'message': 'Preview updated'})
        except ValueError as error:
            return self.send_json({'message': str(error)}, 400)

    # Apply health settings or acknowledge an incident; acknowledgement does not resolve its
    # condition.
    # The live settings form and incident buttons use this route with the local session token.
    # Settings go to the sensor monitor, while acknowledgements go to the appropriate bag/sensor
    # store; neither operation publishes a motor command.
    def monitor_post(self):
        if not self.local_request() or self.headers.get('X-Team8-Session') != CONTROL_SESSION:
            return self.send_json({'message': 'Invalid local session'}, 403)
        if SENSORS is None or TRACKER is None:
            return self.send_json({'message': 'Monitor unavailable'}, 503)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096:
                raise ValueError('Invalid request size')
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError('Expected JSON object')
            if self.path == '/api/monitor/limits':
                return self.send_json(SENSORS.configure(payload))
            if self.path == '/api/monitor/ack':
                kind, incident_id = payload.get('kind'), payload.get('id')
                if type(incident_id) is not int or kind not in ('bag', 'sensor'):
                    raise ValueError('Invalid incident')
                target = TRACKER if kind == 'bag' else SENSORS
                return self.send_json(target.acknowledge(incident_id))
            return self.send_json({'message': 'Not found'}, 404)
        except (TypeError, ValueError) as error:
            return self.send_json({'message': str(error)}, 400)

    # Keep manual tests and authenticated scanner submissions in their correct source
    # namespaces.
    # This accepts manual browser scans, authenticated camera scans and new timing standards.
    # Sources remain distinct so pressing a test button cannot finish a camera journey;
    # validation errors return a useful client response instead of a server crash.
    def transit_post(self):
        browser = self.local_request() and self.headers.get('X-Team8-Session') == CONTROL_SESSION
        token = os.environ.get('TEAM8_SCAN_TOKEN', '')
        scanner = len(token) >= 24 and secrets.compare_digest(self.headers.get('X-Team8-Scan-Token', ''), token)
        if not browser and not (scanner and self.path == '/api/transit/scan'):
            return self.send_json({'message': 'Invalid scan/session token'}, 403)
        if TRACKER is None:
            return self.send_json({'message': 'Timing tracker unavailable'}, 503)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 4096:
                raise ValueError('Invalid request size')
            p=json.loads(self.rfile.read(size))
            if not isinstance(p,dict): raise ValueError('Expected a JSON object')
            if self.path == '/api/transit/standard' and browser:
                result=TRACKER.configure(p.get('minimum'),p.get('maximum'))
            elif self.path == '/api/transit/scan':
                source=p.get('source','manual')
                if browser and source!='manual': raise ValueError('Browser tests must use manual source')
                if not browser and source not in ('camera','mqtt'): raise ValueError('Scanner must use camera or mqtt source')
                result=TRACKER.scan(p.get('barcode'),p.get('checkpoint'),source,p.get('event_id'))
            else:
                return self.send_json({'message':'Not found'},404)
            return self.send_json(result)
        except (TypeError,ValueError) as error:
            return self.send_json({'message':str(error)},400)
        except Exception:
            return self.send_json({'message':'Timing record could not be saved; inspect server logs/database'},500)


# Entry point: read terminal options, start the requested components, and clean up on exit.
# Terminal options choose the HTTP address and optional MQTT config. This creates the persistent
# stores, starts the subscriber/supervisor, and serves the page. Shutdown stops background users
# before closing their database connections.
def main():
    global CONTROL, TRACKER, SENSORS, MQTT, C4, C4_MQTT, USE_CONVEYOR4, VISION, VISION_B
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--host', default='127.0.0.1', help='Use 0.0.0.0 only when remote checkpoint scanners must connect')
    parser.add_argument('--mqtt-config', help='MQTT config path; defaults to conveyor4 local/example JSON')
    args = parser.parse_args()
    # OPTIONAL HARDWARE HOOK: comment out this block to leave controls disabled.
    if globals().get('ENABLE_CONVEYOR_CONTROL', False):
        CONTROL = ConveyorControl(enabled=True)
    TRACKER = TransitTracker(str(Path(__file__).with_name('team8transit.sqlite3')))
    config = {}
    # Explicit old configurations select legacy monitoring. With no argument,
    # use the local conveyor 4 mapping if present, otherwise the documented example.
    if args.mqtt_config:
        config = json.loads(Path(args.mqtt_config).read_text(encoding='utf-8-sig'))
    else:
        default_path = ASSET_DIR / 'team8conveyor4.local.json'
        if not default_path.exists():
            default_path = ASSET_DIR / 'team8conveyor4.example.json'
        config = json.loads(default_path.read_text(encoding='utf-8-sig'))
    USE_CONVEYOR4 = config.get('monitor_type') == 'conveyor4'
    if USE_CONVEYOR4:
        C4 = Conveyor4Monitor(str(ASSET_DIR / 'team8conveyor4.sqlite3'), config)
        VISION = VisionInbox(TRACKER)
        VISION_B = VisionInbox(TRACKER)
        C4_MQTT = Conveyor4MQTT(C4, vision=VISION, vision_b=VISION_B)
        try:
            C4_MQTT.start()
        except ImportError:
            C4.connection(False, 'Paho-MQTT missing: use the prepared Jetson environment or install paho-mqtt')
    else:
        SENSORS = SensorMonitor(str(ASSET_DIR / 'team8monitor.sqlite3'),
                                config.get('station_id', 'Conveyor3'), config.get('limits'))
        if config:
            MQTT = MQTTInputs(config, TRACKER, SENSORS)
            try:
                MQTT.start()
            except ImportError:
                parser.error('Paho-MQTT is missing. Use the prepared Jetson environment.')
    stop_monitor = threading.Event()

    # Evaluate deadlines/health every second even when no browser tab is open.
    # This loop runs independently of browser polling and checks deadlines once per second.
    # Consequently a bag can become overdue while the browser is closed. Exceptions are reported
    # without silently terminating all later monitoring evaluations.
    def supervise():
        while not stop_monitor.wait(1):
            try:
                TRACKER.evaluate_incidents()
                if SENSORS:
                    SENSORS.snapshot()
                if C4_MQTT:
                    C4_MQTT.tick()
            except Exception as error:
                print('Monitoring evaluation failed:', type(error).__name__)

    worker = threading.Thread(target=supervise, daemon=True)
    worker.start()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f'Team 8 dashboard: http://127.0.0.1:{args.port}')
    print(('Conveyor 4 monitor' if USE_CONVEYOR4 else 'Legacy dashboard') +
          '. Hardware control bridge ' + ('ENABLED' if CONTROL else 'DISABLED') + '. Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        # Stop background producers before closing the SQLite connections they can still access.
        stop_monitor.set()
        worker.join(timeout=3)
        if MQTT:
            MQTT.stop()
        if C4_MQTT:
            C4_MQTT.stop()
        if C4:
            C4.close()
        if SENSORS:
            SENSORS.close()
        TRACKER.close()


if __name__ == '__main__':
    main()
