"""Bounded MQTT JPEG previews and AprilTag checkpoint observations (Python 3.6+).

Camera images are unretained, low-rate JPEG snapshots, not full-motion video.
The database keeps the legacy 'barcode' field name, containing an AprilTag key.
"""
from collections import deque
import json
import math
import struct
import threading
import time


FAMILIES = {'tag36h11': 587, 'tag25h9': 35, 'tag16h5': 30}
MAX_JPEG = 64000
MAX_PACKET = MAX_JPEG + 2056
MAGIC = b'T8J1'


# SECTION: Normalize a tag identity independently of camera/process sessions.
# The same printed family/id must match at A and B even on different Jetsons.
# Session IDs identify deliveries, while this key identifies the physical label.
def tag_key(family, tag_id):
    if family not in FAMILIES or type(tag_id) is not int or not 0 <= tag_id < FAMILIES[family]:
        raise ValueError('Invalid AprilTag family or ID')
    return 'apriltag:{}:{}'.format(family, tag_id)


# SECTION: Frame metadata precedes raw JPEG bytes in one bounded MQTT payload.
# A small binary envelope avoids base64 expansion while retaining sequence/session
# information. Header lengths are validated before any JSON or image is accepted.
def pack_frame(header, jpeg):
    if not 4 <= len(jpeg) <= MAX_JPEG or not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
        raise ValueError('Expected JPEG no larger than 64 kB')
    metadata = json.dumps(header, separators=(',', ':')).encode('utf-8')
    if len(metadata) > 2048:
        raise ValueError('Frame header is too large')
    return MAGIC + struct.pack('!I', len(metadata)) + metadata + jpeg


def unpack_frame(payload):
    if not 12 <= len(payload) <= MAX_PACKET or payload[:4] != MAGIC:
        raise ValueError('Invalid MQTT preview envelope')
    length = struct.unpack('!I', payload[4:8])[0]
    if not 2 <= length <= 2048 or 8+length >= len(payload):
        raise ValueError('Invalid frame header length')
    header = json.loads(payload[8:8+length].decode('utf-8'))
    if not isinstance(header, dict):
        raise ValueError('Frame header must be a JSON object')
    jpeg = payload[8+length:]
    if not 4 <= len(jpeg) <= MAX_JPEG or not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
        raise ValueError('Invalid JPEG content')
    return header, jpeg


# SECTION: Debounce tag appearances and use a central dead zone in AB mode.
# A tag emits an event when it enters a different checkpoint or returns after
# being absent. Tags in the gap retain their previous region until they reach
# the opposite side, reducing boundary jitter compared with one dividing pixel.
class TagCheckpoints:
    def __init__(self, checkpoint='AB', a_side='left', split=0.5, gap=0.1, rearm_seconds=2.0):
        if checkpoint not in ('A', 'B', 'AB') or a_side not in ('left', 'right'):
            raise ValueError('Invalid checkpoint arrangement')
        if not 0 <= gap < min(split, 1-split) or not 0 < split < 1:
            raise ValueError('Invalid checkpoint split/gap')
        self.checkpoint, self.a_side, self.split, self.gap = checkpoint, a_side, split, gap
        self.rearm = rearm_seconds
        self.last = {}

    def observe(self, detections, width, now):
        output, entered = [], []
        for detection in detections:
            item = dict(detection)
            identity = tag_key(item['family'], item['tag_id'])
            x = item['center'][0] / width
            checkpoint = self.checkpoint
            if checkpoint == 'AB':
                side = 'left' if x < self.split-self.gap else 'right' if x > self.split+self.gap else None
                checkpoint = None if side is None else 'A' if side == self.a_side else 'B'
            item.update(identifier=identity, checkpoint=checkpoint)
            output.append(item)
            previous = self.last.get(identity)
            reappeared = previous is None or now-previous['seen'] >= self.rearm
            if checkpoint is not None and (reappeared or previous['checkpoint'] != checkpoint):
                entered.append({'family': item['family'], 'tag_id': item['tag_id'], 'checkpoint': checkpoint})
            self.last[identity] = {'seen': now, 'checkpoint': checkpoint if checkpoint is not None else
                                   previous['checkpoint'] if previous else None}
        self.last = {key: value for key, value in self.last.items() if now-value['seen'] < 60}
        return output, entered


# SECTION: Receive camera messages without coupling them to motor FLAG decisions.
# Images live only in memory and expire by receipt age; retired sessions and old
# sequence numbers are rejected. Accepted tag events enter the existing persistent
# journey tracker using canonical AprilTag keys rather than free barcode text.
class VisionInbox:
    def __init__(self, tracker, clock=time.monotonic, stale_seconds=4):
        self.tracker, self.clock, self.stale = tracker, clock, stale_seconds
        self.lock = threading.RLock()
        self.frame = None
        self.tags = []
        self.tag_at = None
        self.orders = {}
        self.publisher_status = 'Waiting for Jetson camera publisher'
        self.errors = 0
        self.last_error = None

    # Validate source identity/order separately for frames and tag metadata.
    # Retired sessions cannot reappear after reconnect and overwrite a newer view.
    def _header(self, stream, header):
        if not isinstance(header, dict) or header.get('conveyor') != 4:
            raise ValueError('Preview is not for conveyor 4')
        session, sequence = header.get('session_id'), header.get('sequence')
        if not isinstance(session, str) or not 1 <= len(session) <= 128:
            raise ValueError('Missing camera session')
        if type(sequence) is not int or not 0 <= sequence < 2**53:
            raise ValueError('Invalid camera sequence')
        state = self.orders.get(stream)
        if state:
            if session in state['retired'] or (session == state['session'] and sequence <= state['sequence']):
                return False
            if session != state['session']:
                state['retired'].append(state['session'])
                state['session'] = session
            state['sequence'] = sequence
        else:
            self.orders[stream] = {'session': session, 'sequence': sequence, 'retired': deque(maxlen=32)}
        return True

    # Frame freshness is based on local receipt time because the offline Jetson
    # and laptop need not share an NTP clock. Sender-side capture age is also bounded;
    # QoS 0, no retain, sequence checks and rate limiting avoid replay/backlogs.
    def receive_frame(self, payload, retained=False):
        if retained:
            return False
        try:
            header, jpeg = unpack_frame(payload)
            age = header.get('capture_age_ms', 0)
            if type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= 1500:
                raise ValueError('Publisher frame was already stale before sending')
            with self.lock:
                if not self._header('frame', header):
                    return False
                self.frame = {'at': self.clock(), 'jpeg': jpeg, 'header': header}
                self.last_error = None
            return True
        except (ValueError, TypeError, KeyError, UnicodeError, struct.error) as error:
            self._error(str(error))
            return False

    # Parse a bounded list of currently visible tags plus sparse checkpoint-entry
    # events. Event IDs make QoS 1 retransmissions idempotent in the journey store.
    # Capture coordinates remain diagnostic; they are not calibrated belt speed.
    def receive_tags(self, payload, retained=False):
        if retained or len(payload) > 16384:
            return False
        try:
            data = json.loads(payload.decode('utf-8'))
            if not isinstance(data, dict):
                raise ValueError('Tag payload must be an object')
            tags, events = data.get('tags', []), data.get('events', [])
            if not isinstance(tags, list) or not isinstance(events, list) or len(tags) > 64 or len(events) > 64:
                raise ValueError('Too many or invalid tag observations')
            cleaned = []
            for tag in tags:
                if not isinstance(tag, dict):
                    raise ValueError('Tag observation must be an object')
                identity = tag_key(tag['family'], tag['tag_id'])
                if tag.get('checkpoint') not in ('A', 'B', None):
                    raise ValueError('Invalid checkpoint')
                cleaned.append({'identifier': identity, 'family': tag['family'], 'tag_id': tag['tag_id'],
                                'checkpoint': tag.get('checkpoint')})
            for event in events:
                if not isinstance(event, dict):
                    raise ValueError('Tag event must be an object')
                tag_key(event['family'], event['tag_id'])
                if event.get('checkpoint') not in ('A', 'B') or not isinstance(event.get('event_id'), str) or not 1 <= len(event['event_id']) <= 128:
                    raise ValueError('Invalid tag event')
            with self.lock:
                if not self._header('tags', data):
                    return False
                for event in events:
                    self.tracker.scan(tag_key(event['family'], event['tag_id']), event['checkpoint'],
                                      'mqtt', event['event_id'])
                self.tags, self.tag_at = cleaned, self.clock()
                self.publisher_status = str(data.get('detector', 'AprilTag publisher'))[:120]
                self.last_error = None
            return True
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            self._error(str(error))
            return False

    # Online status is descriptive only; it never makes an old frame fresh.
    # A matching offline/will message clears the preview immediately. An old
    # publisher's delayed will cannot clear the currently active newer session.
    def receive_status(self, payload):
        try:
            if len(payload) > 4096:
                raise ValueError('Camera status too large')
            data = json.loads(payload.decode('utf-8'))
            if data.get('conveyor') != 4 or type(data.get('online')) is not bool or not isinstance(data.get('session_id'), str):
                raise ValueError('Invalid camera status')
            with self.lock:
                current = self.orders.get('frame') or self.orders.get('tags')
                if current and data['session_id'] != current['session']:
                    return False
                self.publisher_status = str(data.get('message', 'Camera publisher online' if data['online'] else 'Camera publisher offline'))[:160]
                if not data['online']:
                    self.frame, self.tag_at = None, None
            return True
        except (ValueError, TypeError, AttributeError, UnicodeError) as error:
            self._error(str(error))
            return False

    def _error(self, message):
        with self.lock:
            self.errors += 1
            self.last_error = message

    # Broker disconnect invalidates the visual feed just as it invalidates sensor
    # freshness, but it does not erase any persistent tag journeys or incidents.
    def disconnect(self):
        with self.lock:
            self.frame, self.tag_at = None, None
            self.publisher_status = 'Dashboard disconnected from MQTT'

    def jpeg(self):
        with self.lock:
            return self.frame['jpeg'] if self.frame and 0 <= self.clock()-self.frame['at'] <= self.stale else None

    # Join recent transport state with the persistent A-to-B records. The legacy
    # storage field stays named barcode to avoid migrating/deleting old history;
    # only canonical AprilTag keys are presented in this new camera panel.
    def snapshot(self):
        with self.lock:
            age = self.clock()-self.frame['at'] if self.frame else None
            tags_fresh = self.tag_at is not None and 0 <= self.clock()-self.tag_at <= self.stale
            state = {'fresh': self.jpeg() is not None, 'age_seconds': age,
                     'tags': self.tags if tags_fresh else [], 'tags_fresh': tags_fresh,
                     'publisher_status': self.publisher_status, 'errors': self.errors, 'last_error': self.last_error}
        transit = self.tracker.snapshot()
        state['standard'] = transit['standard']
        state['trips'] = [trip for trip in transit['trips'] if trip['barcode'].startswith('apriltag:')]
        state['incidents'] = [item for item in self.tracker.incidents() if item['barcode'].startswith('apriltag:')]
        return state
