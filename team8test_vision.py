"""Offline camera transport/checkpoint tests; no hardware or native decoder needed."""
import io
import json
import unittest
import hashlib
import tarfile
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import team8dashboard as dashboard
from team8apriltag_camera import CameraPublisher, initial_frame, make_detector, normalized, open_capture
from team8conveyor4 import Conveyor4Monitor, Conveyor4MQTT
from team8transit import TransitTracker
from team8vision import MAX_JPEG, TagCheckpoints, VisionInbox, pack_frame, unpack_frame, tag_key
from team8install_apriltag import extract_sources


# SECTION: Fake time and a temporary in-memory journey store exercise actual
# persistence and timeout decisions instantly. The JPEG marker bytes deliberately
# test transport framing only; real optical decoding needs the Jetson camera.
class VisionTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.tracker = TransitTracker(':memory:', clock=lambda: self.now)
        self.inbox = VisionInbox(self.tracker, clock=lambda: self.now)
        self.jpeg = b'\xff\xd8' + b'x'*5000 + b'\xff\xd9'

    def tearDown(self):
        self.tracker.close()

    def header(self, sequence=1, session='first', **extra):
        result = dict(conveyor=4, session_id=session, sequence=sequence, capture_age_ms=10)
        result.update(extra)
        return result

    def packet(self, sequence=1, session='first', **extra):
        return pack_frame(self.header(sequence, session, **extra), self.jpeg)

    def tags(self, checkpoint='A', sequence=1, session='first', event_id=None):
        tag = dict(family='tag36h11', tag_id=0, checkpoint=checkpoint)
        data = self.header(sequence, session)
        data.update(tags=[tag], events=[dict(tag, event_id=event_id or session+str(sequence))])
        return json.dumps(data).encode('utf-8')

    # Bounds and replay checks prevent oversized, retained and previous-session
    # previews from being presented as the current conveyor image.
    def test_frame_roundtrip_and_expiry(self):
        self.assertEqual(unpack_frame(self.packet()), (self.header(), self.jpeg))
        self.assertTrue(self.inbox.receive_frame(self.packet()))
        self.assertTrue(self.inbox.snapshot()['fresh'])
        self.now += 4.01
        self.assertIsNone(self.inbox.jpeg())
        self.assertFalse(self.inbox.snapshot()['fresh'])

    def test_bounds_and_invalid_headers(self):
        for payload in (b'', b'nope'*500, self.packet()[:-1], pack_frame([], self.jpeg)):
            self.assertFalse(self.inbox.receive_frame(payload))
        with self.assertRaises(ValueError):
            pack_frame(self.header(), b'\xff\xd8'+b'x'*MAX_JPEG+b'\xff\xd9')
        self.assertFalse(self.inbox.receive_frame(self.packet(capture_age_ms=1501)))
        self.assertFalse(self.inbox.receive_frame(self.packet(capture_age_ms=float('nan'))))
        self.assertFalse(self.inbox.receive_frame(self.packet(conveyor=3)))
        self.assertFalse(self.inbox.receive_frame(self.packet(), retained=True))
        self.assertIsNone(self.inbox.jpeg())

    def test_sequence_and_retired_session(self):
        self.assertTrue(self.inbox.receive_frame(self.packet(sequence=2)))
        self.assertFalse(self.inbox.receive_frame(self.packet(sequence=1)))
        self.assertFalse(self.inbox.receive_frame(self.packet(sequence=2)))
        self.assertTrue(self.inbox.receive_frame(self.packet(session='second')))
        self.assertFalse(self.inbox.receive_frame(self.packet(sequence=50)))

    def test_matching_offline_status_and_disconnect(self):
        self.inbox.receive_frame(self.packet(session='second'))
        old = json.dumps(dict(conveyor=4, session_id='first', online=False)).encode()
        self.assertFalse(self.inbox.receive_status(old))
        self.assertIsNotNone(self.inbox.jpeg())
        current = json.dumps(dict(conveyor=4, session_id='second', online=False)).encode()
        self.assertTrue(self.inbox.receive_status(current))
        self.assertIsNone(self.inbox.jpeg())
        self.inbox.receive_frame(self.packet(sequence=2, session='second'))
        self.inbox.disconnect()
        self.assertFalse(self.inbox.snapshot()['fresh'])

    # A and B match the canonical family/id, regardless of JSON event delivery.
    # An overdue warning survives acknowledgement until a real B event arrives.
    def test_real_journey_overdue_ack_and_recovery(self):
        self.assertTrue(self.inbox.receive_tags(self.tags()))
        self.assertFalse(self.inbox.receive_tags(self.tags()))
        self.now += 11
        state = self.inbox.snapshot()
        self.assertEqual(state['trips'][0]['status'], 'Overdue')
        self.assertFalse(state['tags_fresh'])
        incident = state['incidents'][0]
        self.tracker.acknowledge(incident['id'])
        self.assertIsNone(self.tracker.incidents()[0]['resolved'])
        self.assertTrue(self.inbox.receive_tags(self.tags('B', 2)))
        state = self.inbox.snapshot()
        self.assertEqual(state['trips'][0]['barcode'], 'apriltag:tag36h11:0')
        self.assertEqual(state['trips'][0]['elapsed_seconds'], 11)
        self.assertEqual(state['trips'][0]['status'], 'Late')
        self.assertIsNotNone(state['incidents'][0]['resolved'])

    def test_on_time_duplicate_event_and_b_without_a(self):
        self.inbox.receive_tags(self.tags('B'))
        self.assertEqual(self.inbox.snapshot()['trips'], [])
        self.inbox.receive_tags(self.tags('A', 2, event_id='a'))
        self.now += 5
        self.inbox.receive_tags(self.tags('A', 3, event_id='a'))
        self.inbox.receive_tags(self.tags('B', 4))
        trip = self.inbox.snapshot()['trips'][0]
        self.assertEqual(trip['status'], 'On time')
        self.assertEqual(trip['elapsed_seconds'], 5)

    def test_bad_tag_shapes_fail_without_writes(self):
        for data in ([], {'tags':[None]}, {'tags':[[]]}, {'events':[None]},
                     {'events':[{'family':'tag36h11','tag_id':999}]},
                     {'tags':[{'family':'tag36h11','tag_id':True}]},
                     {'events':'bad'}):
            self.assertFalse(self.inbox.receive_tags(json.dumps(data).encode()))
        self.assertFalse(self.inbox.receive_tags(self.tags(), retained=True))
        self.assertEqual(self.tracker.snapshot()['trips'], [])

    # Region hysteresis suppresses jitter while a tag crosses the middle gap.
    # A reversed camera view and dedicated A/B cameras share the same gate logic.
    def test_regions_gap_reentry_and_reversed_direction(self):
        gate = TagCheckpoints()
        def observe(x, now):
            return gate.observe([dict(family='tag36h11',tag_id=0,center=[x,10])], 100, now)
        self.assertEqual(observe(10,0)[1][0]['checkpoint'], 'A')
        self.assertEqual(observe(20,.1)[1], [])
        self.assertIsNone(observe(50,.2)[0][0]['checkpoint'])
        self.assertEqual(observe(30,.3)[1], [])
        self.assertEqual(observe(90,.4)[1][0]['checkpoint'], 'B')
        self.assertEqual(observe(90,3)[1][0]['checkpoint'], 'B')
        reverse = TagCheckpoints(a_side='right')
        tag = dict(family='tag36h11',tag_id=0,center=[90,10])
        self.assertEqual(reverse.observe([tag],100,0)[1][0]['checkpoint'],'A')
        fixed = TagCheckpoints(checkpoint='B')
        self.assertEqual(fixed.observe([tag],100,0)[1][0]['checkpoint'],'B')
        self.assertNotEqual(tag_key('tag36h11',0), tag_key('tag16h5',0))

    # Exercise the actual HTTP handler without opening a listening port. Local
    # freshness/auth checks still run, while fake response methods capture bytes.
    def handler(self, path, payload=None, token=None):
        handler = object.__new__(dashboard.DashboardHandler)
        handler.path = path
        handler.server = MagicMock(server_port=8080)
        handler.headers = {'Host':'127.0.0.1:8080'}
        raw = json.dumps(payload).encode() if payload is not None else b''
        handler.headers['Content-Length'] = str(len(raw))
        if token:
            handler.headers['X-Team8-Session'] = token
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        return handler

    def test_camera_http_fresh_stale_and_remote_denied(self):
        with patch.object(dashboard,'VISION',self.inbox):
            handler = self.handler('/api/conveyor4/camera')
            handler.do_GET()
            handler.send_response.assert_called_with(503)
            self.inbox.receive_frame(self.packet())
            handler = self.handler('/api/conveyor4/camera?t=1')
            handler.do_GET()
            handler.send_response.assert_called_with(200)
            self.assertEqual(handler.wfile.getvalue(),self.jpeg)
            handler = self.handler('/api/conveyor4/camera')
            handler.headers['Host'] = 'outside:8080'
            handler.do_GET()
            handler.send_response.assert_called_with(403)

    def test_tag_ack_http_requires_session(self):
        self.inbox.receive_tags(self.tags())
        self.now += 11
        trip = self.inbox.snapshot()['trips'][0]
        with patch.object(dashboard,'TRACKER',self.tracker):
            handler = self.handler('/api/conveyor4/tag-ack', {'trip_id':trip['id']})
            handler.do_POST()
            handler.send_response.assert_called_with(403)
            handler = self.handler('/api/conveyor4/tag-ack', {'trip_id':trip['id']}, dashboard.CONTROL_SESSION)
            handler.do_POST()
            handler.send_response.assert_called_with(200)
            self.assertIsNotNone(self.tracker.incidents()[0]['acknowledged'])

    # Reset is scoped to authenticated browser actions and the journey store.
    # Reject missing confirmation/session before deleting any real records.
    def test_reset_http_requires_session_and_explicit_action(self):
        self.inbox.receive_tags(self.tags())
        self.now+=11
        self.assertEqual(len(self.inbox.snapshot()['incidents']),1)
        with patch.object(dashboard,'TRACKER',self.tracker):
            handler=self.handler('/api/conveyor4/reset-journeys',{'clear':True})
            handler.do_POST()
            handler.send_response.assert_called_with(403)
            handler=self.handler('/api/conveyor4/reset-journeys',{'clear':False},dashboard.CONTROL_SESSION)
            handler.do_POST()
            handler.send_response.assert_called_with(400)
            self.assertEqual(len(self.tracker.snapshot()['trips']),1)
            handler=self.handler('/api/conveyor4/reset-journeys',{'clear':True},dashboard.CONTROL_SESSION)
            handler.do_POST()
            handler.send_response.assert_called_with(200)
            self.assertEqual(self.inbox.snapshot()['trips'],[])
            self.assertEqual(self.inbox.snapshot()['incidents'],[])

    def test_camera_mqtt_dispatch_keeps_sensor_state_unchanged(self):
        monitor = Conveyor4Monitor(':memory:')
        try:
            adapter = Conveyor4MQTT(monitor, vision=self.inbox)
            before = monitor.snapshot()
            message = SimpleNamespace(topic=monitor.config['camera_topic'],payload=self.packet(),retain=False)
            adapter.on_message(None,None,message)
            self.assertIsNotNone(self.inbox.jpeg())
            after = monitor.snapshot()
            self.assertEqual(before['metrics'], after['metrics'])
            self.assertEqual(before['jam_count'],after['jam_count'])
            client = MagicMock()
            adapter.on_connect(client,None,None,0)
            client.subscribe.assert_any_call(monitor.config['camera_topic'],qos=0)
            client.subscribe.assert_any_call(monitor.config['tags_topic'],qos=1)
            adapter.on_disconnect(client,None,1)
            self.assertIsNone(self.inbox.jpeg())
        finally:
            monitor.close()

    # Two publishers have unrelated session IDs and sequence counters. Routing
    # must keep their images/offline states separate while matching one bag's
    # A event from camera A with its B event from camera B in the shared tracker.
    def test_two_camera_routing_and_shared_journey(self):
        second = VisionInbox(self.tracker,clock=lambda:self.now)
        monitor = Conveyor4Monitor(':memory:')
        try:
            adapter = Conveyor4MQTT(monitor,vision=self.inbox,vision_b=second)
            def deliver(key,payload):
                adapter.on_message(None,None,SimpleNamespace(topic=monitor.config[key],payload=payload,retain=False))
            deliver('camera_topic',self.packet(session='camera-a'))
            jpeg_b = b'\xff\xd8second camera\xff\xd9'
            deliver('camera_b_topic',pack_frame(self.header(session='camera-b'),jpeg_b))
            self.assertEqual(self.inbox.jpeg(),self.jpeg)
            self.assertEqual(second.jpeg(),jpeg_b)
            deliver('tags_topic',self.tags('A',session='camera-a'))
            self.now += 3
            deliver('tags_b_topic',self.tags('B',session='camera-b'))
            self.assertEqual(second.snapshot()['trips'][0]['elapsed_seconds'],3)
            self.assertEqual(second.snapshot()['trips'][0]['status'],'On time')
            deliver('camera_b_status_topic',json.dumps(dict(conveyor=4,session_id='camera-b',online=False)).encode())
            self.assertIsNone(second.jpeg())
            self.assertIsNotNone(self.inbox.jpeg())
            client = MagicMock()
            adapter.on_connect(client,None,None,0)
            client.subscribe.assert_any_call(monitor.config['camera_b_topic'],qos=0)
            client.subscribe.assert_any_call(monitor.config['tags_b_topic'],qos=1)
            adapter.on_disconnect(client,None,1)
            self.assertIsNone(self.inbox.jpeg())
        finally:
            monitor.close()

    def test_second_camera_http_and_topic_collision(self):
        from team8conveyor4 import validate_config
        with self.assertRaises(ValueError):
            validate_config({'camera_b_topic':'Conveyor4/camera/frame'})
        second = VisionInbox(self.tracker,clock=lambda:self.now)
        jpeg_b = b'\xff\xd8second camera\xff\xd9'
        second.receive_frame(pack_frame(self.header(session='camera-b'),jpeg_b))
        with patch.object(dashboard,'VISION_B',second), patch.object(dashboard,'VISION',self.inbox):
            handler = self.handler('/api/conveyor4/camera/B')
            handler.do_GET()
            handler.send_response.assert_called_with(200)
            self.assertEqual(handler.wfile.getvalue(),jpeg_b)
            self.assertIsNone(self.inbox.jpeg())
            self.now += 5
            handler = self.handler('/api/conveyor4/camera/B')
            handler.do_GET()
            handler.send_response.assert_called_with(503)


# SECTION: Fake Paho and OpenCV objects test API adaptation and MQTT parameters.
# They do not certify camera drivers or native AprilTag decoding, which require
# the onsite preflight and a printed tag in front of the physical camera.
class CameraAdapterTests(unittest.TestCase):
    # Verify the shipped source really matches its manifest and is sufficient to
    # construct a native build. The unsafe-member case exercises archive handling
    # independently from the trusted upstream payload, without running a compiler.
    def test_bundled_source_integrity_and_build_inputs(self):
        root = Path(__file__).resolve().parent
        archive = root/'team8apriltag-source.tar.gz'
        metadata = json.loads((root/'team8apriltag-source.json').read_text())
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),metadata['sha256'])
        with tempfile.TemporaryDirectory(prefix='team8-source-test-') as folder:
            sources = extract_sources(archive,Path(folder))
            self.assertGreater(len(sources),20)
            self.assertTrue(all(Path(name).is_file() for name in sources))
            wrapper = (Path(folder)/'python/apriltag.py').read_text()
            self.assertEqual(wrapper.count("filename = 'libapriltag'+extension"),1)
            self.assertTrue((Path(folder)/'LICENSE.md').is_file())

    def test_source_archive_rejects_path_escape(self):
        with tempfile.TemporaryDirectory(prefix='team8-unsafe-test-') as folder:
            archive = Path(folder)/'team8bad.tar.gz'
            with tarfile.open(str(archive),'w:gz') as stream:
                info = tarfile.TarInfo('upstream/../../escape.c')
                info.size = 1
                stream.addfile(info,io.BytesIO(b'x'))
            with self.assertRaises(RuntimeError):
                extract_sources(archive,Path(folder)/'sources')

    def test_bundled_adapter_passes_through_normalized_results(self):
        tag = SimpleNamespace(tag_id=0,hamming=0,center=[10,20],corners=[[0,0]]*4)
        detector = SimpleNamespace(detect=lambda gray:[tag])
        with patch('team8apriltag_native.load_detector',return_value=detector):
            name, detect = make_detector(SimpleNamespace(),backend='bundled')
            self.assertEqual(detect(None)[0]['tag_id'],0)
            self.assertIn('Bundled',name)

    # Capture routing and startup validation use fake device objects, so these
    # tests catch regressions without depending on a local webcam or native cv2.
    def test_capture_backend_selection(self):
        cv2 = SimpleNamespace(VideoCapture=MagicMock(), CAP_V4L2=200, CAP_GSTREAMER=1800)
        open_capture(cv2, 1, backend='v4l2')
        cv2.VideoCapture.assert_called_with(1, 200)
        open_capture(cv2, 0, pipeline='camera ! appsink')
        cv2.VideoCapture.assert_called_with('camera ! appsink', 1800)
        open_capture(cv2, 2)
        cv2.VideoCapture.assert_called_with(2)
        with self.assertRaises(ValueError):
            open_capture(cv2, pipeline='camera ! appsink', backend='v4l2')

    def test_capture_warmup_requires_an_actual_image(self):
        capture = MagicMock()
        frame = SimpleNamespace(shape=(480,640,3))
        capture.read.side_effect = [(False,None),(True,frame)]
        with patch('team8apriltag_camera.time.sleep'):
            self.assertIs(initial_frame(capture),frame)
        capture.read.side_effect = None
        capture.read.return_value = (True,SimpleNamespace(shape=(0,0,3)))
        with patch('team8apriltag_camera.time.sleep'), self.assertRaises(RuntimeError):
            initial_frame(capture,attempts=2)
        capture.isOpened.return_value = False
        with self.assertRaises(RuntimeError):
            initial_frame(capture)

    def test_camera_publisher_bounds_qos_and_offline(self):
        client = MagicMock()
        client.publish.return_value.rc = 0
        publisher = CameraPublisher('broker',1883,'frame','tags','status','test',factory=lambda _:client)
        jpeg = b'\xff\xd8test\xff\xd9'
        self.assertFalse(publisher.frame(1,jpeg,100,1))
        publisher.on_connect(client,None,None,0)
        self.assertTrue(publisher.frame(1,jpeg,100,1))
        args, kwargs = client.publish.call_args
        self.assertEqual(kwargs,dict(qos=0,retain=False))
        self.assertEqual(unpack_frame(args[1])[1],jpeg)
        self.assertFalse(publisher.frame(2,jpeg,100,1501))
        entry = dict(family='tag36h11',tag_id=0,checkpoint='A')
        publisher.tags(2,[entry.copy()],[entry])
        args, kwargs = client.publish.call_args
        self.assertEqual(kwargs,dict(qos=1,retain=False))
        self.assertTrue(json.loads(args[1])['events'][0]['event_id'])
        client.will_set.assert_called_once()
        publisher.close()
        client.disconnect.assert_called_once()
        client.loop_stop.assert_called_once()

    def test_opencv_old_and_new_interfaces(self):
        points = MagicMock()
        points.reshape.return_value.tolist.return_value = [[0,0],[10,0],[10,10],[0,10]]
        ids = MagicMock()
        ids.flatten.return_value = [3]
        for modern in (False,True):
            aruco = SimpleNamespace(DICT_APRILTAG_36h11=20,
                getPredefinedDictionary=lambda _: 'dictionary', DetectorParameters_create=lambda: 'params')
            if modern:
                aruco.ArucoDetector = lambda *_: SimpleNamespace(detectMarkers=lambda gray:([points],ids,[]))
            else:
                aruco.detectMarkers = lambda *args,**kwargs:([points],ids,[])
            name, detect = make_detector(SimpleNamespace(aruco=aruco),backend='opencv')
            self.assertEqual(detect('gray')[0]['tag_id'],3)
            self.assertEqual(detect('gray')[0]['center'],[5,5])
        with self.assertRaises(RuntimeError):
            make_detector(SimpleNamespace(),backend='opencv')

    def test_native_binding_normalization_ignores_corrected_decodes(self):
        good = SimpleNamespace(tag_id=1,hamming=0,center=[1,2],corners=[[0,0]]*4)
        bad = SimpleNamespace(tag_id=2,hamming=1,center=[1,2],corners=[[0,0]]*4)
        self.assertEqual([tag['tag_id'] for tag in normalized([good,bad],'tag36h11')],[1])


if __name__ == '__main__':
    unittest.main()
