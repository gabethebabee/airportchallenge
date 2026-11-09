"""Jetson AprilTag detector + rate-limited MQTT camera preview (Python 3.6+).

Preflight: python3 team8apriltag_camera.py --check
Run:      python3 team8apriltag_camera.py --checkpoint AB --camera 0
No package is installed automatically. Use --preview-only if no tag backend exists.
"""
import argparse
import json
from pathlib import Path
import platform
import sys
import threading
import time
import uuid

from team8monitor import mqtt_client
from team8vision import FAMILIES, MAX_JPEG, TagCheckpoints, pack_frame, tag_key


# SECTION: Inspect Linux camera names without opening a device or MQTT connection.
# Device indexes can change when several video interfaces are present. These
# kernel-reported names help identify the actual camera instead of guessing 0.
def camera_info():
    devices = sorted(Path('/sys/class/video4linux').glob('video*/name'))
    print('System:', platform.system(), '| Python:', sys.version.split()[0])
    if not devices:
        print('No Linux video devices listed. Check camera connection and driver.')
    for device in devices:
        try:
            print('/dev/' + device.parent.name, '-', device.read_text().strip())
        except OSError as error:
            print(str(device), '-', error)


# SECTION: Let the operator select the camera transport independently of detection.
# OpenCV auto-selection on the Jetson can choose GStreamer even for a USB camera.
# Explicit V4L2 bypasses that path; a CSI camera may instead need a verified
# GStreamer pipeline. This does not change the installed OpenCV or camera driver.
def open_capture(cv2, camera=0, pipeline=None, backend='auto', width=1280, height=720, warmup=4):
    if backend == 'jetson':
        if pipeline:
            raise ValueError('Use a device index with jetson capture, not --pipeline')
        from team8jetson_capture import JetsonCapture
        return JetsonCapture(camera,width,height,warmup)
    if pipeline:
        if backend == 'v4l2':
            raise ValueError('A GStreamer pipeline cannot use the V4L2 backend')
        return cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    if backend == 'v4l2':
        return cv2.VideoCapture(camera, cv2.CAP_V4L2)
    if backend == 'gstreamer':
        return cv2.VideoCapture(camera, cv2.CAP_GSTREAMER)
    return cv2.VideoCapture(camera)


# SECTION: Opening a video device is not proof that it can deliver images.
# Allow a short sequence of failed startup reads for camera warm-up, then require
# an actual nonempty frame before announcing success or starting MQTT traffic.
# Further capture failures still stop publication rather than repeating an image.
def initial_frame(capture, attempts=8):
    if not capture.isOpened():
        raise RuntimeError('Camera did not open. Check --camera-info, permissions and other camera programs.')
    for attempt in range(attempts):
        ok, frame = capture.read()
        if ok and frame is not None and len(frame.shape) >= 2 and min(frame.shape[:2]) > 0:
            return frame
        if attempt+1 < attempts:
            time.sleep(0.1)
    raise RuntimeError('Camera opened but delivered no images. Try --capture-backend v4l2 for a USB camera; '
                       'run --camera-info to check its index. CSI cameras may need a staff-provided --pipeline.')


# SECTION: Adapt existing AprilTag libraries instead of requiring a new Python.
# Prefer OpenCV's actual AprilTag dictionary if its aruco module is present;
# otherwise try the Pupil or legacy AprilTag bindings already installed locally.
# Each backend returns the same family/id, centre and four-corner representation.
def make_detector(cv2, family='tag36h11', backend='auto'):
    if family not in FAMILIES:
        raise ValueError('Unsupported AprilTag family')
    failures = []
    if backend in ('auto', 'bundled'):
        try:
            from team8apriltag_native import load_detector
            detector = load_detector(family)
            return 'Bundled native AprilTag', lambda gray: normalized(detector.detect(gray), family)
        except Exception as error:
            failures.append('bundled: ' + str(error))
    if backend in ('auto', 'opencv'):
        try:
            aruco = cv2.aruco
            dictionary_id = getattr(aruco, 'DICT_APRILTAG_' + family[3:])
            dictionary = (aruco.getPredefinedDictionary(dictionary_id) if hasattr(aruco, 'getPredefinedDictionary')
                          else aruco.Dictionary_get(dictionary_id))
            parameters = aruco.DetectorParameters_create() if hasattr(aruco, 'DetectorParameters_create') else aruco.DetectorParameters()
            detector = aruco.ArucoDetector(dictionary, parameters) if hasattr(aruco, 'ArucoDetector') else None

            def detect(gray):
                corners, ids, _ = detector.detectMarkers(gray) if detector else aruco.detectMarkers(gray, dictionary, parameters=parameters)
                output = []
                if ids is not None:
                    for points, identity in zip(corners, ids.flatten()):
                        coordinates = points.reshape(4, 2).tolist()
                        output.append({'family': family, 'tag_id': int(identity), 'corners': coordinates,
                                       'center': [sum(point[axis] for point in coordinates)/4 for axis in (0, 1)]})
                return output
            return 'OpenCV AprilTag dictionary', detect
        except Exception as error:
            failures.append('OpenCV aruco: ' + str(error))
    if backend in ('auto', 'pupil'):
        try:
            from pupil_apriltags import Detector
            detector = Detector(families=family, nthreads=2, quad_decimate=2.0)
            return 'pupil_apriltags', lambda gray: normalized(detector.detect(gray), family)
        except Exception as error:
            failures.append('pupil_apriltags: ' + str(error))
    if backend in ('auto', 'apriltag'):
        try:
            import apriltag
            detector = apriltag.Detector(apriltag.DetectorOptions(families=family))
            return 'apriltag', lambda gray: normalized(detector.detect(gray), family)
        except Exception as error:
            failures.append('apriltag: ' + str(error))
    raise RuntimeError('No usable AprilTag backend. Ask staff to provide a Jetson-compatible detector; '
                       'do not replace the prepared OpenCV blindly. Details: ' + '; '.join(failures))


# SECTION: Keep transport independent from a binding's NumPy/native objects.
# Only exact/error-free native decodes are used when hamming information exists.
# Pose estimation is unnecessary: identification and checkpoint regions need only
# the printed ID and its image position, not a camera calibration or tag size.
def normalized(detections, family):
    result = []
    for detection in detections:
        if getattr(detection, 'hamming', 0) != 0:
            continue
        identity = int(detection.tag_id)
        tag_key(family, identity)
        result.append({'family': family, 'tag_id': identity,
                       'center': [float(value) for value in detection.center],
                       'corners': [[float(value) for value in point] for point in detection.corners]})
    return result


# SECTION: MQTT camera traffic is isolated from sensor/FLAG topics.
# Preview snapshots use QoS 0 and no retain, with a strict byte/FPS cap. Tag
# checkpoint entries use IDs and QoS 1; ordinary visible-tag refreshes use QoS 0.
# A publisher last will clears its preview status after unexpected loss.
class CameraPublisher:
    def __init__(self, broker, port, frame_topic, tags_topic, status_topic, detector_name, factory=mqtt_client):
        topics = [frame_topic, tags_topic, status_topic]
        if len(set(topics)) != 3 or any(not topic or '+' in topic or '#' in topic for topic in topics):
            raise ValueError('Use three distinct exact camera/tag topics')
        self.session = uuid.uuid4().hex
        self.frame_topic, self.tags_topic, self.status_topic = topics
        self.detector = detector_name
        self.connected = threading.Event()
        self.generation = 0
        self.client = factory('team8-camera-' + self.session[:10])
        self.client.max_inflight_messages_set(4)
        self.client.max_queued_messages_set(8)
        self.client.will_set(status_topic, self.status(False, 'Jetson camera disconnected'), qos=1, retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = lambda client, userdata, rc: self.connected.clear()
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        self.client.connect_async(broker, port, 15)

    def status(self, online, message):
        return json.dumps({'conveyor': 4, 'session_id': self.session, 'online': online,
                           'detector': self.detector, 'message': message})

    # Report online only after the broker accepts the connection. The capture
    # loop notices generation changes and rearms visible tags, allowing fresh
    # checkpoint observations instead of replaying an offline observation log.
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.generation += 1
            self.connected.set()
            client.publish(self.status_topic, self.status(True, self.detector), qos=1, retain=True)
            print('MQTT camera connected')
        else:
            self.connected.clear()
            print('MQTT rejected camera connection:', rc)

    def start(self):
        self.client.loop_start()

    # A frame is published only if connected and still recent before transmission.
    # The envelope retains raw JPEG bytes rather than expanding them to base64.
    # Transport failures drop this preview; a later current frame replaces it.
    def frame(self, sequence, jpeg, captured_at, age_ms):
        if not self.connected.is_set() or age_ms > 1500:
            return False
        packet = pack_frame({'conveyor': 4, 'session_id': self.session, 'sequence': sequence,
                             'captured_at': captured_at, 'capture_age_ms': age_ms}, jpeg)
        return self.client.publish(self.frame_topic, packet, qos=0, retain=False).rc == 0

    # Tag identities stay stable across cameras, while event IDs identify specific
    # A/B entries. No barcode parser or baggage-routing/motor topic is involved.
    # The subscriber maps these canonical identities into persistent A-to-B history.
    def tags(self, sequence, detections, entries):
        if not self.connected.is_set():
            return False
        for entry in entries:
            entry['event_id'] = uuid.uuid4().hex
        payload = json.dumps({'conveyor': 4, 'session_id': self.session, 'sequence': sequence,
                              'detector': self.detector, 'tags': detections, 'events': entries})
        if len(payload.encode('utf-8')) > 16384:
            print('Tag payload too large; reduce number of visible tags')
            return False
        return self.client.publish(self.tags_topic, payload, qos=1 if entries else 0, retain=False).rc == 0

    # Graceful exit publishes the same offline state as the crash last will.
    # The camera is released by main(), while the subscriber independently expires
    # its in-memory image even if a final status publication cannot be delivered.
    def close(self):
        try:
            info = self.client.publish(self.status_topic, self.status(False, 'Jetson camera stopped'), qos=1, retain=True)
            try:
                info.wait_for_publish(timeout=1)
            except TypeError:  # Older lab Paho exposes no timed wait.
                pass
        finally:
            self.client.disconnect()
            self.client.loop_stop()


# SECTION: Capture on the Jetson; view it through the dashboard elsewhere.
# Preflight opens no camera/network connection. Runtime reads one device, detects
# real AprilTags, annotates the image, and publishes at a capped preview rate.
# Detection rate is separate so A/B observations can be faster than image updates.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--camera-info', action='store_true', help='List Linux camera device names without opening them')
    parser.add_argument('--capture-check', action='store_true', help='Read five frames without MQTT or an AprilTag detector')
    parser.add_argument('--capture-backend', choices=['auto', 'v4l2', 'gstreamer', 'jetson'], default='auto')
    parser.add_argument('--capture-width', type=int, default=1280, help='Requested gstCamera width')
    parser.add_argument('--capture-height', type=int, default=720, help='Requested gstCamera height')
    parser.add_argument('--capture-warmup', type=float, default=4, help='gstCamera warm-up seconds')
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--pipeline', help='Optional staff-verified CSI/GStreamer camera pipeline')
    parser.add_argument('--checkpoint', choices=['A', 'B', 'AB'], default='AB')
    parser.add_argument('--a-side', choices=['left', 'right'], default='left')
    parser.add_argument('--split-x', type=float, default=0.5)
    parser.add_argument('--gap', type=float, default=0.1)
    parser.add_argument('--family', choices=sorted(FAMILIES), default='tag36h11')
    parser.add_argument('--backend', choices=['auto', 'bundled', 'opencv', 'pupil', 'apriltag'], default='auto')
    parser.add_argument('--preview-only', action='store_true')
    parser.add_argument('--broker', default='129.97.228.106')
    parser.add_argument('--port', type=int, default=1883)
    parser.add_argument('--frame-topic', default='Conveyor4/camera/frame')
    parser.add_argument('--tags-topic', default='Conveyor4/apriltags')
    parser.add_argument('--status-topic', default='Conveyor4/camera/status')
    parser.add_argument('--fps', type=float, default=1.0, help='MQTT preview snapshots/second, maximum 5')
    parser.add_argument('--detect-fps', type=float, default=5.0, help='Detection loops/second, maximum 15')
    parser.add_argument('--width', type=int, default=480, help='Preview width, maximum 960 pixels')
    parser.add_argument('--quality', type=int, default=45)
    parser.add_argument('--display', action='store_true', help='Also display the image on the Jetson screen')
    args = parser.parse_args()
    if args.camera_info:
        camera_info()
        return
    if not (160 <= args.capture_width <= 3840 and 120 <= args.capture_height <= 2160 and 0 <= args.capture_warmup <= 10):
        parser.error('Use capture width 160-3840, height 120-2160 and warmup 0-10 seconds')
    if not (0 < args.fps <= 5 and 0 < args.detect_fps <= 15 and 160 <= args.width <= 960 and 10 <= args.quality <= 85):
        parser.error('Use FPS 0–5, detection FPS 0–15, width 160–960, quality 10–85')
    try:
        import cv2
    except ImportError:
        parser.error('OpenCV is missing in this Python environment; use the prepared Jetson interpreter')
    if args.capture_check:
        capture = None
        try:
            capture = open_capture(cv2, args.camera, args.pipeline, args.capture_backend,
                                   args.capture_width,args.capture_height,args.capture_warmup)
            frame = initial_frame(capture)
            for _ in range(4):
                ok, next_frame = capture.read()
                if not ok or next_frame is None:
                    raise RuntimeError('Capture failed after the first frame')
                frame = next_frame
            print('CAPTURE OK: five frames, {} x {}, backend {}'.format(
                frame.shape[1], frame.shape[0], args.capture_backend))
            print('No MQTT connection or AprilTag detector was started.')
            return
        except (ValueError, RuntimeError, ImportError) as error:
            parser.error(str(error))
        finally:
            if capture is not None:
                capture.release()
    try:
        detector_name, detect = ('PREVIEW ONLY — AprilTag detection disabled', lambda gray: []) if args.preview_only else make_detector(cv2, args.family, args.backend)
        gate = TagCheckpoints(args.checkpoint, args.a_side, args.split_x, args.gap)
        if args.check:
            import paho.mqtt.client
            print('Python:', sys.version.split()[0], 'Architecture:', platform.machine())
            print('OpenCV:', cv2.__version__, 'Detector:', detector_name, 'Family:', args.family)
            print('Paho import works. No camera/broker opened.')
            return
    except (RuntimeError, ValueError, ImportError) as error:
        parser.error(str(error))
    capture = None
    try:
        capture = open_capture(cv2, args.camera, args.pipeline, args.capture_backend,
                               args.capture_width,args.capture_height,args.capture_warmup)
        first_frame = initial_frame(capture)
    except (ValueError, RuntimeError, ImportError) as error:
        if capture is not None:
            capture.release()
        parser.error(str(error))
    publisher = None
    try:
        publisher = CameraPublisher(args.broker, args.port, args.frame_topic, args.tags_topic, args.status_topic, detector_name)
        publisher.start()
        sequence, last_preview, generation = 0, -1e9, -1
        print('Camera running:', detector_name, '| MQTT previews:', args.fps, 'fps | Ctrl+C to stop')
        while True:
            started = time.monotonic()
            if first_frame is not None:
                frame, first_frame = first_frame, None
                ok = True
            else:
                ok, frame = capture.read()
            if not ok or frame is None:
                raise RuntimeError('Camera stopped supplying frames')
            captured_at = time.time()
            sequence += 1
            if generation != publisher.generation:
                gate = TagCheckpoints(args.checkpoint, args.a_side, args.split_x, args.gap)
                generation = publisher.generation
            detections = detect(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))[:16]
            observations, entries = gate.observe(detections, frame.shape[1], started)
            for tag in observations:
                corners = [(int(point[0]), int(point[1])) for point in tag['corners']]
                for index in range(4):
                    cv2.line(frame, corners[index], corners[(index+1)%4], (0, 190, 0), 2)
                label = '{} ID {} {}'.format(tag['family'], tag['tag_id'], tag['checkpoint'] or 'GAP')
                cv2.putText(frame, label, corners[0], cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 190, 0), 1)
            if args.checkpoint == 'AB':
                for position in (args.split_x-args.gap, args.split_x+args.gap):
                    x = int(frame.shape[1]*position)
                    cv2.line(frame, (x, 0), (x, frame.shape[0]), (255, 180, 0), 2)
            preview_due = started-last_preview >= 1/args.fps
            if entries or preview_due:
                publisher.tags(sequence, observations, entries)
            if preview_due:
                last_preview = started
                width = min(args.width, frame.shape[1])
                small = cv2.resize(frame, (width, int(frame.shape[0]*width/frame.shape[1])))
                encoded, jpeg = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, args.quality])
                if encoded and len(jpeg) > MAX_JPEG:
                    encoded, jpeg = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 20])
                if encoded and len(jpeg) <= MAX_JPEG:
                    publisher.frame(sequence, jpeg.tobytes(), captured_at, (time.monotonic()-started)*1000)
            if args.display:
                cv2.imshow('Team8 AprilTags', frame)
                if cv2.waitKey(1)&255 == 27:
                    break
            time.sleep(max(0, 1/args.detect_fps-(time.monotonic()-started)))
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if publisher:
                publisher.close()
        finally:
            capture.release()
            if args.display:
                cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
