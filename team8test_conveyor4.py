"""Offline tests for conveyor 4's specified average/timer/FLAG behavior."""
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import team8dashboard as dashboard
from team8conveyor4 import Conveyor4Monitor, Conveyor4MQTT, validate_config


# SECTION: Fake time and in-memory storage make exact boundary tests instant.
# Every sensor sample goes through the real engine. The fake MQTT client records
# publications without reaching a real broker or changing any physical output.
class Conveyor4Tests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.config = {'current_topic': 'actual/current', 'minimum_samples': 5}
        self.monitor = Conveyor4Monitor(':memory:', self.config, clock=lambda: self.now, wall=lambda: 1000+self.now)
        self.monitor.connection(True, 'test connected')

    def tearDown(self):
        self.monitor.close()

    # Warm-up is five actual observations, rather than five browser refreshes.
    def warm(self, speed=100, current=10):
        for _ in range(5):
            self.monitor.ingest('speed', speed)
            self.monitor.ingest('current', current)
            self.now += 1

    # Deliver both streams once a second so a long deviation is continuously
    # observed. Simply advancing time without fresh readings must not flag it.
    def feed(self, seconds, speed=100, current=10):
        for _ in range(seconds):
            self.monitor.ingest('speed', speed)
            self.monitor.ingest('current', current)
            self.now += 1

    def test_warmup_and_flag_polarity(self):
        self.assertFalse(self.monitor.snapshot()['flag'])
        self.warm()
        self.assertTrue(self.monitor.snapshot()['flag'])
        self.assertEqual(self.monitor.snapshot()['state'], 'Normal')

    # ±15% itself remains inside; the specification says MORE than 15%.
    def test_exact_fifteen_percent_boundary(self):
        self.warm()
        self.monitor.ingest('speed', 115)
        self.assertFalse(self.monitor.snapshot()['metrics']['speed']['timing'])
        self.monitor.recalibrate()
        self.warm()
        self.monitor.ingest('current', 8.5)
        self.assertFalse(self.monitor.snapshot()['metrics']['current']['timing'])

    # Freeze the reference so twelve seconds of bad data cannot dilute the fault.
    # At exactly 10 seconds the flag is still true; crossing 10 changes it false.
    def test_speed_over_average_strict_ten_seconds(self):
        self.warm()
        self.feed(10, speed=120)
        self.monitor.ingest('speed', 120)
        self.monitor.ingest('current', 10)
        self.assertTrue(self.monitor.snapshot()['flag'])
        self.now += 0.1
        state = self.monitor.snapshot()
        self.assertFalse(state['flag'])
        self.assertEqual(state['jam_count'], 1)
        self.assertEqual(state['metrics']['speed']['average'], 100)

    def test_current_below_average_triggers(self):
        self.warm()
        self.feed(12, current=8)
        self.assertFalse(self.monitor.snapshot()['flag'])
        self.assertTrue(self.monitor.snapshot()['metrics']['current']['abnormal'])

    def test_continuous_timer_resets_on_recovery(self):
        self.warm()
        self.feed(8, speed=120)
        self.feed(1, speed=100)
        self.feed(8, speed=120)
        self.assertTrue(self.monitor.snapshot()['flag'])
        self.assertEqual(self.monitor.snapshot()['jam_count'], 0)

    def test_overlapping_alarms_one_episode_then_rearm(self):
        self.warm()
        self.feed(12, speed=120, current=12)
        self.assertEqual(self.monitor.snapshot()['jam_count'], 1)
        self.feed(15, speed=120, current=12)
        self.assertEqual(self.monitor.snapshot()['jam_count'], 1)
        self.feed(2)
        self.assertTrue(self.monitor.snapshot()['flag'])
        self.feed(12, speed=80)
        self.assertEqual(self.monitor.snapshot()['jam_count'], 2)

    # One shared OR timer matches the requested "either number" condition.
    # Overlap allows the cause to change without falsely resetting the elapsed time.
    def test_shared_timer_survives_change_of_deviating_channel(self):
        self.warm()
        self.feed(6, speed=120)
        self.monitor.ingest('current', 12)
        self.feed(6, speed=100, current=12)
        self.assertFalse(self.monitor.snapshot()['flag'])
        self.assertEqual(self.monitor.snapshot()['jam_count'], 1)

    def test_stale_samples_break_unconfirmed_timer(self):
        self.warm()
        self.feed(8, speed=120)
        self.now += 8
        state = self.monitor.snapshot()
        self.assertFalse(state['flag'])
        self.assertEqual(state['jam_count'], 0)
        self.feed(5, speed=120)
        self.assertEqual(self.monitor.snapshot()['jam_count'], 0)

    def test_gap_resets_timer_even_without_any_snapshot_during_gap(self):
        self.warm()
        self.feed(8, speed=120)
        self.now += 20
        self.monitor.ingest('speed', 120)
        self.monitor.ingest('current', 10)
        self.assertEqual(self.monitor.snapshot()['jam_count'], 0)
        self.assertTrue(self.monitor.snapshot()['flag'])

    def test_distance_and_runtime_integrate_speed_not_message_count(self):
        self.monitor.ingest('speed', 10)
        self.now = 2
        self.monitor.ingest('speed', 10)
        state = self.monitor.snapshot()
        self.assertEqual(state['runtime_seconds'], 2)
        self.assertEqual(state['distance_m'], 0.2)
        self.now = 3
        self.monitor.ingest('speed', 0)
        self.now = 6
        self.monitor.ingest('speed', 0)
        self.assertEqual(self.monitor.snapshot()['runtime_seconds'], 3)
        self.now = 20
        self.monitor.ingest('speed', 10)
        self.assertAlmostEqual(self.monitor.snapshot()['distance_m'], 0.3)

    def test_missing_current_never_uses_voltage_as_amperage(self):
        for _ in range(6):
            self.monitor.ingest('speed', 100)
            self.monitor.ingest('voltage', 2.3)
            self.now += 1
        state = self.monitor.snapshot()
        self.assertIsNone(state['metrics']['current']['value'])
        self.assertFalse(state['flag'])
        self.assertEqual(state['jam_count'], 0)

    def test_invalid_data_and_zero_average(self):
        self.assertFalse(self.monitor.ingest('speed', float('nan')))
        self.assertFalse(self.monitor.ingest('current', True))
        self.warm(speed=0, current=0)
        self.feed(12, speed=1, current=0)
        self.assertEqual(self.monitor.snapshot()['jam_count'], 1)

    # Reopening storage preserves totals/counts, never process-local timer times.
    def test_persistence_and_explicit_recalibration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'team8c4.sqlite3')
            saved = Conveyor4Monitor(path, self.config, clock=lambda: self.now)
            saved.connection(True, 'test')
            for _ in range(5):
                saved.ingest('speed', 100); saved.ingest('current', 10); self.now += 1
            for _ in range(12):
                saved.ingest('speed', 120); saved.ingest('current', 10); self.now += 1
            before = saved.snapshot()
            saved.close()
            saved = Conveyor4Monitor(path, self.config, clock=lambda: self.now)
            self.assertEqual(saved.snapshot()['jam_count'], 1)
            self.assertEqual(saved.snapshot()['distance_m'], before['distance_m'])
            self.assertFalse(saved.snapshot()['flag'])
            saved.recalibrate()
            self.assertEqual(saved.snapshot()['jam_count'], 1)
            self.assertEqual(saved.snapshot()['distance_m'], before['distance_m'])
            saved.close()

    # The transport publishes actual JSON booleans, with retained false as will.
    def test_mqtt_topics_flag_bytes_retained_and_last_will(self):
        client = MagicMock()
        client.publish.return_value = SimpleNamespace(rc=0, wait_for_publish=lambda timeout: None)
        service = Conveyor4MQTT(self.monitor, factory=lambda identity: client)
        service.start()
        client.will_set.assert_called_once_with('Conveyor4/FLAG', 'false', qos=1, retain=True)
        service.on_connect(client, None, {}, 0)
        self.assertIn(('Conveyor4/get_belt_speed',), [call.args for call in client.subscribe.call_args_list])
        self.warm()
        service.tick()
        flags = [call.args[1] for call in client.publish.call_args_list if call.args[0]=='Conveyor4/FLAG']
        self.assertEqual(flags, ['false','true'])
        self.feed(12, current=12)
        service.tick()
        flags = [call.args[1] for call in client.publish.call_args_list if call.args[0]=='Conveyor4/FLAG']
        self.assertEqual(flags[-1], 'false')
        service.stop()

    def test_raw_payload_field_scale_and_duplicate_rejection(self):
        client = MagicMock()
        service = Conveyor4MQTT(self.monitor, factory=lambda identity: client)
        self.monitor.config['current_key'] = 'amps'
        message = SimpleNamespace(topic='actual/current', payload=b'{"amps":2.5}', retain=False, dup=False)
        service.on_message(client, None, message)
        self.assertEqual(self.monitor.snapshot()['metrics']['current']['value'], 2.5)
        before = self.monitor.snapshot()['metrics']['current']['samples']
        message.dup = True
        service.on_message(client, None, message)
        self.assertEqual(self.monitor.snapshot()['metrics']['current']['samples'], before)
        message.dup = False; message.retain = True
        service.on_message(client, None, message)
        self.assertEqual(self.monitor.snapshot()['metrics']['current']['samples'], before)

    def test_config_prevents_input_output_loop(self):
        with self.assertRaises(ValueError):
            validate_config({'current_topic':'Conveyor4/FLAG'})

    # Broker retention has no sensor timestamp. Its values may be displayed as
    # last known but cannot supply calibration samples, movement totals or health.
    # Live messages replace the cache; late retained messages cannot overwrite a
    # currently fresh observation.
    def test_retained_cache_is_display_only_and_live_takes_priority(self):
        service=Conveyor4MQTT(self.monitor)
        for topic,payload in [('Conveyor4/get_belt_speed',b'6.783669'),('actual/current',b'3.3981')]:
            service.on_message(None,None,SimpleNamespace(topic=topic,payload=payload,retain=True,dup=False))
        self.now+=60
        state=self.monitor.snapshot()
        self.assertIsNone(state['metrics']['speed']['value'])
        self.assertEqual(state['metrics']['speed']['last_known']['source'],'retained')
        self.assertEqual(state['metrics']['current']['last_known']['value'],3.3981)
        self.assertEqual(state['metrics']['speed']['samples'],0)
        self.assertEqual(state['distance_m'],0)
        self.assertEqual(state['runtime_seconds'],0)
        self.assertFalse(state['flag'])
        self.warm()
        self.assertTrue(self.monitor.snapshot()['flag'])
        service.on_message(None,None,SimpleNamespace(topic='actual/current',payload=b'3',retain=True,dup=False))
        metric=self.monitor.snapshot()['metrics']['current']
        self.assertEqual(metric['last_known']['source'],'live')
        self.assertEqual(metric['last_known']['value'],10)
        self.now+=5
        self.assertIsNone(self.monitor.snapshot()['metrics']['current']['value'])
        self.assertEqual(self.monitor.snapshot()['metrics']['current']['last_known']['value'],10)

    def test_api_returns_focused_metrics(self):
        self.warm()
        handler = object.__new__(dashboard.DashboardHandler)
        handler.path = '/api/conveyor4'
        handler.server = MagicMock(server_port=8080)
        handler.headers = {'Host':'127.0.0.1:8080'}
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock(); handler.send_header = MagicMock(); handler.end_headers = MagicMock()
        with patch.object(dashboard,'C4',self.monitor):
            handler.do_GET()
        self.assertTrue(json.loads(handler.wfile.getvalue())['flag'])


if __name__ == '__main__':
    unittest.main()
