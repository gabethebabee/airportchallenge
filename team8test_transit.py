"""Offline timing tests; no cameras, network, or conveyor commands."""
import tempfile
from pathlib import Path
import unittest
import io
import json
from unittest.mock import MagicMock, patch
import team8dashboard as dashboard
from team8transit import TransitTracker


# Group the related offline regression checks so failures identify the affected feature.
# These regression scenarios group the behavior of this feature in isolation. Shared setup
# supplies temporary/in-memory state; no test is allowed to depend on a running physical
# conveyor. A failure identifies a broken assumption before deployment.
class TimingTests(unittest.TestCase):
    # Create isolated in-memory state and a controllable clock so this test never touches real
    # hardware.
    # Create a new isolated test world before every scenario, including an injectable clock
    # where timing matters. Sharing no mutable records between scenarios prevents one passing
    # test from hiding a failure in the next.
    def setUp(self):
        self.now=1000.0
        self.tracker=TransitTracker(':memory:',clock=lambda:self.now)
    # Close the test databases; the next test starts with a clean state.
    # Close the isolated stores after each scenario so file handles and state do not leak into
    # later tests. Real project databases are never opened by this cleanup.
    def tearDown(self): self.tracker.close()
    # Submit a checkpoint to the test tracker while keeping the test barcode/source easy to
    # override.
    # Provide common barcode/source defaults while allowing the scenario to vary checkpoint and
    # event identity. This goes through the real tracker logic rather than manually editing its
    # database.
    def scan(self,point,barcode='bag1',source='camera',event=None):
        return self.tracker.scan(barcode,point,source,event)
    # Read the most recent journey so each test can assert its elapsed time and classification.
    # Read the newest recorded journey through the same snapshot method the dashboard uses.
    # Assertions therefore check the exposed timing classification as well as stored
    # departure/arrival behavior.
    def status(self): return self.tracker.snapshot()['trips'][0]

    # Reset clears active/completed trips and their alerts, but preserves limits
    # and old delivery IDs. A fresh A can start immediately with a new journey ID;
    # a retransmitted old A or a stale acknowledgement cannot recreate/affect it.
    def test_reset_journeys_deduplicates_old_messages_and_keeps_limits(self):
        self.tracker.configure(1,2)
        first=self.scan('A',event='old-a')['trip_id']
        self.now+=3
        self.assertEqual(len(self.tracker.incidents()),1)
        result=self.tracker.reset_journeys()
        self.assertEqual(result['cleared'],1)
        self.assertEqual(self.tracker.snapshot()['trips'],[])
        self.assertEqual(self.tracker.incidents(),[])
        self.assertEqual(self.tracker.snapshot()['standard'],{'minimum':1,'maximum':2})
        self.assertIsNone(self.scan('A',event='old-a')['trip_id'])
        new=self.scan('A',event='new-a')['trip_id']
        self.assertGreater(new,first)
        self.assertEqual(len(self.tracker.snapshot()['trips']),1)
        with self.assertRaises(ValueError):
            self.tracker.acknowledge(first)
        self.tracker.reset_journeys()
        self.assertIsNotNone(self.scan('A',event='immediate-new-a')['trip_id'])
    # Regression check: matching bag time and limits. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises matching bag time and limits. The setup uses controlled inputs and
    # a fake clock or mocked request instead of contacting a broker, camera or PLC. Assertions
    # below define the result that must continue working after future edits.
    def test_matching_bag_time_and_limits(self):
        self.tracker.configure(4,10);self.scan('A');self.now+=7;self.scan('B')
        self.assertEqual(self.status()['elapsed_seconds'],7)
        self.assertEqual(self.status()['status'],'On time')
    # Regression check: repeat A never restarts. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises repeat A never restarts. The setup uses controlled inputs and a
    # fake clock or mocked request instead of contacting a broker, camera or PLC. Assertions
    # below define the result that must continue working after future edits.
    def test_repeat_A_never_restarts(self):
        self.scan('A');self.now+=8;self.scan('A');self.now+=3
        self.assertEqual(self.status()['status'],'Overdue')
        self.scan('B');self.assertEqual(self.status()['status'],'Late')
        self.assertEqual(self.status()['elapsed_seconds'],11)
    # Regression check: different bag or source cannot complete. Uses fakes/in-memory state,
    # never live equipment.
    # This scenario exercises different bag or source cannot complete. The setup uses controlled
    # inputs and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_different_bag_or_source_cannot_complete(self):
        self.scan('A');self.now+=5;self.scan('B','other');self.scan('B',source='manual')
        self.assertEqual(self.status()['status'],'Travelling')
    # Regression check: B first creates no fake trip. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises B first creates no fake trip. The setup uses controlled inputs and
    # a fake clock or mocked request instead of contacting a broker, camera or PLC. Assertions
    # below define the result that must continue working after future edits.
    def test_B_first_creates_no_fake_trip(self):
        self.assertIn('without active A',self.scan('B')['message'])
        self.assertEqual(self.tracker.snapshot()['trips'],[])
    # Regression check: idempotent retry and event collision. Uses fakes/in-memory state, never
    # live equipment.
    # This scenario exercises idempotent retry and event collision. The setup uses controlled
    # inputs and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_idempotent_retry_and_event_collision(self):
        self.scan('A',event='event1');self.now+=2;self.scan('A',event='event1')
        self.assertEqual(len(self.tracker.snapshot()['scans']),1)
        with self.assertRaises(ValueError):self.scan('B',event='event1')
    # Regression check: standards frozen and early arrival. Uses fakes/in-memory state, never
    # live equipment.
    # This scenario exercises standards frozen and early arrival. The setup uses controlled
    # inputs and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_standards_frozen_and_early_arrival(self):
        self.tracker.configure(5,10);self.scan('A');self.tracker.configure(0,2)
        self.now+=3;self.scan('B');self.assertEqual(self.status()['status'],'Too fast')
        self.assertEqual(self.status()['maximum'],10)
    # Regression check: recirc and repeated B. Uses fakes/in-memory state, never live equipment.
    # This scenario exercises recirc and repeated B. The setup uses controlled inputs and a fake
    # clock or mocked request instead of contacting a broker, camera or PLC. Assertions below
    # define the result that must continue working after future edits.
    def test_recirc_and_repeated_B(self):
        self.scan('A');self.now+=5;self.scan('B');self.scan('B')
        self.assertEqual(len(self.tracker.snapshot()['trips']),1)
        self.now+=4;self.scan('A');self.assertEqual(len(self.tracker.snapshot()['trips']),2)
    # Regression check: limits and bad scans. Uses fakes/in-memory state, never live equipment.
    # This scenario exercises limits and bad scans. The setup uses controlled inputs and a fake
    # clock or mocked request instead of contacting a broker, camera or PLC. Assertions below
    # define the result that must continue working after future edits.
    def test_limits_and_bad_scans(self):
        for lo,hi in [(0,0),(-1,10),(0,float('nan')),(0,float('inf'))]:
            with self.assertRaises(ValueError):self.tracker.configure(lo,hi)
        with self.assertRaises(ValueError):self.scan('C')
        with self.assertRaises(ValueError):self.scan('A','')
    # Regression check: restart retains journey. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises restart retains journey. The setup uses controlled inputs and a
    # fake clock or mocked request instead of contacting a broker, camera or PLC. Assertions
    # below define the result that must continue working after future edits.
    def test_restart_retains_journey(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'team8test.sqlite3')
            t=TransitTracker(path,clock=lambda:100);t.scan('bag','A');t.close()
            t=TransitTracker(path,clock=lambda:108);t.scan('bag','B')
            self.assertEqual(t.snapshot()['trips'][0]['elapsed_seconds'],8);t.close()

    # Regression check: scan api authentication and recording. Uses fakes/in-memory state, never
    # live equipment.
    # This scenario exercises scan api authentication and recording. The setup uses controlled
    # inputs and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_scan_api_authentication_and_recording(self):
        # Build an in-memory HTTP handler so authorization/routes can be tested without a
        # network connection.
        # Construct an HTTP handler around byte buffers and mocked headers/response methods. The
        # real route code can then be exercised without opening a network socket or permitting a
        # physical output request.
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
