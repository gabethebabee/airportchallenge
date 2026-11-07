"""Offline monitoring integration tests. No broker, PLC, or camera access."""
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import team8dashboard as dashboard
from team8monitor import CameraFrames, MQTTInputs, SensorMonitor
from team8transit import TransitTracker


# Group the related offline regression checks so failures identify the affected feature.
# These regression scenarios group the behavior of this feature in isolation. Shared setup
# supplies temporary/in-memory state; no test is allowed to depend on a running physical
# conveyor. A failure identifies a broken assumption before deployment.
class MonitorTests(unittest.TestCase):
    # Create isolated in-memory state and a controllable clock so this test never touches real
    # hardware.
    # Create a new isolated test world before every scenario, including an injectable clock
    # where timing matters. Sharing no mutable records between scenarios prevents one passing
    # test from hiding a failure in the next.
    def setUp(self):
        self.now = 1000.0
        self.seq = 0
        self.sensors = SensorMonitor(':memory:', limits={
            'speed_min_cm_s': 5, 'speed_max_cm_s': 10,
            'window_seconds': 60, 'outside_limit_seconds': 24,
            'minimum_running_seconds': 10,
        }, clock=lambda: self.now)
        self.sensors.connection(True, 'test broker connected')
        self.tracker = TransitTracker(':memory:', clock=lambda: self.now)
        self.config = {'broker': 'example.invalid', 'sensor_topic': 'sensors',
                       'checkpoint_topics': {'A': 'scan/a', 'B': 'scan/b'}}
        self.inputs = MQTTInputs(self.config, self.tracker, self.sensors, clock=lambda: self.now)

    # Close the test databases; the next test starts with a clean state.
    # Close the isolated stores after each scenario so file handles and state do not leak into
    # later tests. Real project databases are never opened by this cleanup.
    def tearDown(self):
        self.sensors.close()
        self.tracker.close()

    # Create a unique, ordered telemetry envelope with known units for each synthetic
    # observation.
    # Return a fresh ordered telemetry envelope with explicit station, session, units and sample
    # identity. Each test can override the measured values while preserving a valid default
    # message shape.
    def payload(self, speed=8, running=True, current=None):
        self.seq += 1
        return {'station_id': 'Conveyor3', 'event_id': 'test:'+str(self.seq), 'session_id': 'test',
                'sequence': self.seq, 'speed_cm_s': speed, 'run_requested': running, 'current_a': current}

    # Assert that this intentionally valid synthetic sensor sample is accepted.
    # Submit a deliberately valid sample and immediately assert acceptance. A later failure in a
    # health calculation should not be confused with an earlier malformed test input.
    def sample(self, **values):
        self.assertTrue(self.sensors.ingest(self.payload(**values)))

    # Move the fake clock in one-second steps and feed matching observations without real
    # waiting.
    # Move the fake clock forward one second per observation while feeding matching
    # measurements. The tests can exercise rolling windows and persistent stalls instantly
    # without waiting real minutes.
    def advance(self, seconds, **values):
        for _ in range(seconds):
            self.now += 1
            self.sample(**values)

    # Regression check: rolling threshold uses seconds not message count. Uses fakes/in-memory
    # state, never live equipment.
    # This scenario exercises rolling threshold uses seconds not message count. The setup uses
    # controlled inputs and a fake clock or mocked request instead of contacting a broker,
    # camera or PLC. Assertions below define the result that must continue working after future
    # edits.
    def test_rolling_threshold_uses_seconds_not_message_count(self):
        self.sample(speed=2)
        self.advance(24, speed=2)
        self.assertFalse(self.sensors.snapshot()['health_flag'])
        self.advance(1, speed=2)
        state = self.sensors.snapshot()
        self.assertTrue(state['health_flag'])
        self.assertEqual(state['outside_seconds'], 25)
        self.assertEqual(state['percent_within'], 0)
        maintenance = [item for item in state['incidents'] if item['sensor_kind'] == 'maintenance']
        self.assertEqual(len(maintenance), 1)
        self.advance(2, speed=2)
        self.assertEqual(len(self.sensors.snapshot()['incidents']), 1)

    # Regression check: time weighting and known stops. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises time weighting and known stops. The setup uses controlled inputs
    # and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_time_weighting_and_known_stops(self):
        self.sample(speed=8)
        self.advance(10, speed=8)
        self.sample(speed=0, running=False)
        self.advance(20, speed=0, running=False)
        state = self.sensors.snapshot()
        self.assertEqual(state['running_seconds'], 10)
        self.assertEqual(state['stopped_seconds'], 20)
        self.assertEqual(state['percent_within'], 100)
        self.assertEqual(state['state'], 'Stopped')
        self.assertFalse(state['incidents'])

    # Regression check: stale and disconnect keep incident active. Uses fakes/in-memory state,
    # never live equipment.
    # This scenario exercises stale and disconnect keep incident active. The setup uses
    # controlled inputs and a fake clock or mocked request instead of contacting a broker,
    # camera or PLC. Assertions below define the result that must continue working after future
    # edits.
    def test_stale_and_disconnect_keep_incident_active(self):
        self.sample(speed=0)
        self.advance(3, speed=0)
        state = self.sensors.snapshot()
        self.assertEqual(state['state'], 'Stalled')
        self.sensors.acknowledge(state['incidents'][0]['id'])
        self.now += 6
        state = self.sensors.snapshot()
        self.assertEqual(state['state'], 'Unknown')
        self.assertIsNone(state['incidents'][0]['resolved'])
        self.assertIsNotNone(state['incidents'][0]['acknowledged'])
        self.sensors.connection(False, 'Disconnected')
        self.assertIsNone(self.sensors.snapshot()['speed_cm_s'])
        self.sensors.connection(True, 'Reconnected')
        self.sample(speed=8)
        self.assertIsNotNone(self.sensors.snapshot()['incidents'][0]['resolved'])

    # Regression check: gaps do not add running time. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises gaps do not add running time. The setup uses controlled inputs and
    # a fake clock or mocked request instead of contacting a broker, camera or PLC. Assertions
    # below define the result that must continue working after future edits.
    def test_gaps_do_not_add_running_time(self):
        self.sample()
        self.now += 20
        self.sample()
        self.assertEqual(self.sensors.snapshot()['running_seconds'], 0)
        self.assertIsNone(self.sensors.snapshot()['percent_within'])

    # Regression check: duplicates order and retained messages. Uses fakes/in-memory state,
    # never live equipment.
    # This scenario exercises duplicates order and retained messages. The setup uses controlled
    # inputs and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_duplicates_order_and_retained_messages(self):
        payload = self.payload()
        self.assertTrue(self.sensors.ingest(payload))
        self.now += 3
        self.assertFalse(self.sensors.ingest(payload))
        self.assertFalse(self.sensors.ingest(self.payload(), retained=True))
        older = self.payload()
        older['sequence'] = 0
        self.assertFalse(self.sensors.ingest(older))
        self.now += 2
        self.assertFalse(self.sensors.snapshot()['fresh'])

    # Regression check: invalid data is unknown and does not accumulate. Uses fakes/in-memory
    # state, never live equipment.
    # This scenario exercises invalid data is unknown and does not accumulate. The setup uses
    # controlled inputs and a fake clock or mocked request instead of contacting a broker,
    # camera or PLC. Assertions below define the result that must continue working after future
    # edits.
    def test_invalid_data_is_unknown_and_does_not_accumulate(self):
        self.sample()
        bad = self.payload()
        bad['speed_cm_s'] = float('nan')
        self.assertFalse(self.sensors.ingest(bad))
        self.assertEqual(self.sensors.snapshot()['state'], 'Unknown')
        self.now += 1
        self.sample()
        self.assertEqual(self.sensors.snapshot()['running_seconds'], 0)
        self.assertFalse(self.inputs.consume('sensors', b'not json'))

    # Regression check: window clips and recovers. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises window clips and recovers. The setup uses controlled inputs and a
    # fake clock or mocked request instead of contacting a broker, camera or PLC. Assertions
    # below define the result that must continue working after future edits.
    def test_window_clips_and_recovers(self):
        self.sample(speed=2)
        self.advance(25, speed=2)
        self.assertTrue(self.sensors.snapshot()['health_flag'])
        self.sample(speed=8)
        self.advance(60, speed=8)
        state = self.sensors.snapshot()
        self.assertEqual(state['outside_seconds'], 0)
        self.assertEqual(state['percent_within'], 100)
        self.assertIsNotNone(state['incidents'][0]['resolved'])

    # Regression check: MQTT to bag incident to recovery. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises MQTT to bag incident to recovery. The setup uses controlled inputs
    # and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_MQTT_to_bag_incident_to_recovery(self):
        self.inputs.consume('scan/a', b'BAG001')
        self.now += 11
        incident = self.tracker.incidents()[0]
        self.assertIsNone(incident['resolved'])
        self.tracker.acknowledge(incident['id'])
        self.inputs.consume('scan/b', b'{"barcode":"BAG001","event_id":"b-event"}')
        state = self.tracker.incidents()[0]
        self.assertIsNotNone(state['resolved'])
        self.assertIsNotNone(state['acknowledged'])
        self.assertEqual(self.tracker.snapshot()['trips'][0]['elapsed_seconds'], 11)

    # Regression check: same checkpoint topic rejected. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises same checkpoint topic rejected. The setup uses controlled inputs
    # and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_same_checkpoint_topic_rejected(self):
        self.config['checkpoint_topics']['B'] = 'scan/a'
        with self.assertRaises(ValueError):
            MQTTInputs(self.config, self.tracker, self.sensors)

    # Regression check: retained scan and continuous scan suppressed. Uses fakes/in-memory
    # state, never live equipment.
    # This scenario exercises retained scan and continuous scan suppressed. The setup uses
    # controlled inputs and a fake clock or mocked request instead of contacting a broker,
    # camera or PLC. Assertions below define the result that must continue working after future
    # edits.
    def test_retained_scan_and_continuous_scan_suppressed(self):
        self.assertFalse(self.inputs.consume('scan/a', b'bag', retained=True))
        self.assertTrue(self.inputs.consume('scan/a', b'bag'))
        self.now += 1
        self.assertFalse(self.inputs.consume('scan/a', b'bag'))
        self.assertEqual(len(self.tracker.snapshot()['scans']), 1)

    # Regression check: incidents survive sensor restart. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises incidents survive sensor restart. The setup uses controlled inputs
    # and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_incidents_survive_sensor_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'team8monitor.sqlite3')
            sensor = SensorMonitor(path, clock=lambda: self.now)
            sensor.connection(True, 'test')
            sensor.ingest(self.payload(speed=0))
            for _ in range(3):
                self.now += 1
                sensor.ingest(self.payload(speed=0))
            sensor.acknowledge(sensor.snapshot()['incidents'][0]['id'])
            sensor.close()
            sensor = SensorMonitor(path, clock=lambda: self.now)
            result = sensor.snapshot()
            self.assertEqual(result['state'], 'Unknown')
            self.assertIsNotNone(result['incidents'][0]['acknowledged'])
            self.assertIsNone(result['incidents'][0]['resolved'])
            sensor.close()

    # Regression check: camera freshness and size. Uses fakes/in-memory state, never live
    # equipment.
    # This scenario exercises camera freshness and size. The setup uses controlled inputs and a
    # fake clock or mocked request instead of contacting a broker, camera or PLC. Assertions
    # below define the result that must continue working after future edits.
    def test_camera_freshness_and_size(self):
        frames = CameraFrames(clock=lambda: self.now)
        frames.put('A', b'\xff\xd8test\xff\xd9')
        self.assertTrue(frames.status()['A'])
        self.now += 5
        self.assertIsNone(frames.get('A'))
        with self.assertRaises(ValueError): frames.put('B', b'not a jpeg')
        with self.assertRaises(ValueError): frames.put('A', b'\xff\xd8test\xff\xd9', self.now-6)

    # Regression check: combined jam requires real overdue and live stall. Uses fakes/in-memory
    # state, never live equipment.
    # This scenario exercises combined jam requires real overdue and live stall. The setup uses
    # controlled inputs and a fake clock or mocked request instead of contacting a broker,
    # camera or PLC. Assertions below define the result that must continue working after future
    # edits.
    def test_combined_jam_requires_real_overdue_and_live_stall(self):
        self.tracker.scan('bag','A','mqtt')
        self.now += 11
        self.sensors.configure({'high_current_a': 2})
        self.sample(speed=0, current=3)
        self.advance(3, speed=0, current=3)
        handler = object.__new__(dashboard.DashboardHandler)
        handler.path = '/api/monitor'
        handler.server = MagicMock(server_port=8080)
        handler.headers = {'Host': '127.0.0.1:8080'}
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        with patch.object(dashboard, 'TRACKER', self.tracker), patch.object(dashboard, 'SENSORS', self.sensors):
            handler.do_GET()
        result = json.loads(handler.wfile.getvalue())
        self.assertTrue(result['possible_jam'])
        self.assertTrue(result['high_current_evidence'])

    # Regression check: maintenance settings and service reminder. Uses fakes/in-memory state,
    # never live equipment.
    # This scenario exercises maintenance settings and service reminder. The setup uses
    # controlled inputs and a fake clock or mocked request instead of contacting a broker,
    # camera or PLC. Assertions below define the result that must continue working after future
    # edits.
    def test_maintenance_settings_and_service_reminder(self):
        with self.assertRaises(ValueError): self.sensors.configure({'window_seconds': 0})
        with self.assertRaises(ValueError): self.sensors.configure({'current_a': 3})
        self.sensors.configure({'service_runtime_hours': 0.001})
        self.sample()
        self.advance(4)
        self.assertEqual(self.sensors.snapshot()['incidents'][0]['sensor_kind'], 'service_runtime_hours')

    # Regression check: clock rollback and order after disconnect. Uses fakes/in-memory state,
    # never live equipment.
    # This scenario exercises clock rollback and order after disconnect. The setup uses
    # controlled inputs and a fake clock or mocked request instead of contacting a broker,
    # camera or PLC. Assertions below define the result that must continue working after future
    # edits.
    def test_clock_rollback_and_order_after_disconnect(self):
        payload = self.payload()
        self.sensors.ingest(payload)
        self.sensors.connection(False, 'test disconnect')
        self.sensors.connection(True, 'test reconnect')
        older = dict(payload, event_id='old-event', sequence=0)
        self.assertFalse(self.sensors.ingest(older))
        self.now -= 1
        self.assertFalse(self.sensors.ingest(self.payload()))
        self.assertEqual(self.sensors.snapshot()['state'], 'Unknown')

    # Regression check: mqtt lifecycle subscribes without publishing. Uses fakes/in-memory
    # state, never live equipment.
    # This scenario exercises mqtt lifecycle subscribes without publishing. The setup uses
    # controlled inputs and a fake clock or mocked request instead of contacting a broker,
    # camera or PLC. Assertions below define the result that must continue working after future
    # edits.
    def test_mqtt_lifecycle_subscribes_without_publishing(self):
        client = MagicMock()
        inputs = MQTTInputs(self.config, self.tracker, self.sensors, factory=lambda name: client)
        inputs.start()
        inputs.on_connect(client, None, {}, 0)
        self.assertTrue(self.sensors.connected)
        self.assertEqual(client.subscribe.call_count, 3)
        client.publish.assert_not_called()
        inputs.on_disconnect(client, None, 1)
        self.assertFalse(self.sensors.connected)
        inputs.stop()

    # Regression check: limit and ack api require local session. Uses fakes/in-memory state,
    # never live equipment.
    # This scenario exercises limit and ack api require local session. The setup uses controlled
    # inputs and a fake clock or mocked request instead of contacting a broker, camera or PLC.
    # Assertions below define the result that must continue working after future edits.
    def test_limit_and_ack_api_require_local_session(self):
        # Build an in-memory HTTP handler so authorization/routes can be tested without a
        # network connection.
        # Construct an HTTP handler around byte buffers and mocked headers/response methods. The
        # real route code can then be exercised without opening a network socket or permitting a
        # physical output request.
        def handler(path, payload, token=''):
            h = object.__new__(dashboard.DashboardHandler)
            body = json.dumps(payload).encode()
            h.path, h.server = path, MagicMock(server_port=8080)
            h.headers = {'Host':'127.0.0.1:8080', 'Content-Length':str(len(body)), 'X-Team8-Session':token}
            h.rfile, h.wfile = io.BytesIO(body), io.BytesIO()
            h.send_response, h.send_header, h.end_headers = MagicMock(), MagicMock(), MagicMock()
            return h
        with patch.object(dashboard, 'SENSORS', self.sensors), patch.object(dashboard, 'TRACKER', self.tracker):
            h = handler('/api/monitor/limits', {'speed_min_cm_s':6})
            h.do_POST()
            h.send_response.assert_called_once_with(403)
            h = handler('/api/monitor/limits', {'speed_min_cm_s':6}, dashboard.CONTROL_SESSION)
            h.do_POST()
            self.assertEqual(self.sensors.limits['speed_min_cm_s'], 6)


if __name__ == '__main__':
    unittest.main()
