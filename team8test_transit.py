"""Offline timing tests; no cameras, network, or conveyor commands."""
import tempfile
from pathlib import Path
import unittest
import io
import json
from unittest.mock import MagicMock, patch
import team8dashboard as dashboard
from team8transit import TransitTracker


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.0
        self.tracker=TransitTracker(':memory:',clock=lambda:self.now)
    def tearDown(self): self.tracker.close()
    def scan(self,point,barcode='bag1',source='camera',event=None):
        return self.tracker.scan(barcode,point,source,event)
    def status(self): return self.tracker.snapshot()['trips'][0]
    def test_matching_bag_time_and_limits(self):
        self.tracker.configure(4,10);self.scan('A');self.now+=7;self.scan('B')
        self.assertEqual(self.status()['elapsed_seconds'],7)
        self.assertEqual(self.status()['status'],'On time')
    def test_repeat_A_never_restarts(self):
        self.scan('A');self.now+=8;self.scan('A');self.now+=3
        self.assertEqual(self.status()['status'],'Overdue')
        self.scan('B');self.assertEqual(self.status()['status'],'Late')
        self.assertEqual(self.status()['elapsed_seconds'],11)
    def test_different_bag_or_source_cannot_complete(self):
        self.scan('A');self.now+=5;self.scan('B','other');self.scan('B',source='manual')
        self.assertEqual(self.status()['status'],'Travelling')
    def test_B_first_creates_no_fake_trip(self):
        self.assertIn('without active A',self.scan('B')['message'])
        self.assertEqual(self.tracker.snapshot()['trips'],[])
    def test_idempotent_retry_and_event_collision(self):
        self.scan('A',event='event1');self.now+=2;self.scan('A',event='event1')
        self.assertEqual(len(self.tracker.snapshot()['scans']),1)
        with self.assertRaises(ValueError):self.scan('B',event='event1')
    def test_standards_frozen_and_early_arrival(self):
        self.tracker.configure(5,10);self.scan('A');self.tracker.configure(0,2)
        self.now+=3;self.scan('B');self.assertEqual(self.status()['status'],'Too fast')
        self.assertEqual(self.status()['maximum'],10)
    def test_recirc_and_repeated_B(self):
        self.scan('A');self.now+=5;self.scan('B');self.scan('B')
        self.assertEqual(len(self.tracker.snapshot()['trips']),1)
        self.now+=4;self.scan('A');self.assertEqual(len(self.tracker.snapshot()['trips']),2)
    def test_limits_and_bad_scans(self):
        for lo,hi in [(0,0),(-1,10),(0,float('nan')),(0,float('inf'))]:
            with self.assertRaises(ValueError):self.tracker.configure(lo,hi)
        with self.assertRaises(ValueError):self.scan('C')
        with self.assertRaises(ValueError):self.scan('A','')
    def test_restart_retains_journey(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'team8test.sqlite3')
            t=TransitTracker(path,clock=lambda:100);t.scan('bag','A');t.close()
            t=TransitTracker(path,clock=lambda:108);t.scan('bag','B')
            self.assertEqual(t.snapshot()['trips'][0]['elapsed_seconds'],8);t.close()

    def test_scan_api_authentication_and_recording(self):
        def handler(headers, body):
            h=object.__new__(dashboard.DashboardHandler)
            h.path='/api/transit/scan';h.server=MagicMock(server_port=8080)
            h.headers={'Host':'127.0.0.1:8080','Content-Length':str(len(body)),**headers}
            h.rfile=io.BytesIO(body);h.wfile=io.BytesIO()
            h.send_response=MagicMock();h.send_header=MagicMock();h.end_headers=MagicMock()
            return h
        body=json.dumps({'barcode':'api-bag','checkpoint':'A','source':'manual'}).encode()
        with patch.object(dashboard,'TRACKER',self.tracker):
            h=handler({},body);h.do_POST();h.send_response.assert_called_once_with(403)
            h=handler({'X-Team8-Session':dashboard.CONTROL_SESSION},body);h.do_POST()
            self.assertEqual(json.loads(h.wfile.getvalue())['message'],'Clock started at A')
            self.assertEqual(self.status()['source'],'manual')
            camera=json.dumps({'barcode':'camera-bag','checkpoint':'A','source':'camera'}).encode()
            with patch.dict(dashboard.os.environ,{'TEAM8_SCAN_TOKEN':'s'*32}):
                h=handler({'X-Team8-Scan-Token':'s'*32},camera);h.do_POST()
                self.assertEqual(self.status()['source'],'camera')


if __name__=='__main__':unittest.main()
