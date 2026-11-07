"""Team 8 conveyor dashboard. Standard library only.

Run: python team8dashboard.py
Open: http://127.0.0.1:8080
Demo views, persistent barcode timing, and an optional hardware bridge.
Frontend: team8dashboard.html, team8dashboard.css, team8dashboard.js.
"""

import argparse
import json
import secrets
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from team8transit import TransitTracker

# OPTIONAL HARDWARE MODULE: comment out this import to remove the integration.
from team8conveyor_control import ConveyorControl, ENABLE_CONVEYOR_CONTROL

CONTROL = None
TRACKER = None
CONTROL_SESSION = secrets.token_urlsafe(32)


ASSET_DIR = Path(__file__).resolve().parent



class DashboardHandler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def local_request(self):
        # Bind to loopback and reject unexpected Host headers / cross-site requests.
        expected = f'127.0.0.1:{self.server.server_port}'
        host = self.headers.get('Host', '')
        origin = self.headers.get('Origin')
        return host in (expected, f'localhost:{self.server.server_port}') and (not origin or origin == 'http://' + host)

    def do_POST(self):
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

    def do_GET(self):
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
            body = (ASSET_DIR / 'team8dashboard.html').read_bytes()
            content_type = 'text/html; charset=utf-8'
        elif self.path in ('/team8dashboard.css', '/team8dashboard.js'):
            body = (ASSET_DIR / self.path[1:]).read_bytes()
            content_type = ('text/css' if self.path.endswith('.css') else 'text/javascript') + '; charset=utf-8'
        elif self.path == '/health':
            body = json.dumps({'status': 'ok', 'mode': 'synthetic'}).encode('utf-8')
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


def main():
    global CONTROL, TRACKER
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--host', default='127.0.0.1', help='Use 0.0.0.0 only when remote checkpoint scanners must connect')
    args = parser.parse_args()
    # OPTIONAL HARDWARE HOOK: comment out this block to leave controls disabled.
    if globals().get('ENABLE_CONVEYOR_CONTROL', False):
        CONTROL = ConveyorControl(enabled=True)
    TRACKER = TransitTracker(str(Path(__file__).with_name('team8transit.sqlite3')))
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f'Team 8 dashboard: http://127.0.0.1:{args.port}')
    print('Demo dashboard. Hardware bridge ' + ('ENABLED' if CONTROL else 'DISABLED') + '. Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        TRACKER.close()


if __name__ == '__main__':
    main()
