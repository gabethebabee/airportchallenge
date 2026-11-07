"""Camera barcode checkpoint sender. Optional MQTT bridge for organizer scanners.

Camera: python team8barcode_scanner.py --checkpoint A --camera 0
MQTT: python team8barcode_scanner.py --checkpoint A --mqtt-topic Conveyor3/barcode_value --broker HOST
Install camera extras: pip install opencv-python pyzbar
MQTT extra: pip install paho-mqtt
"""
import argparse
import json
import os
import time
import urllib.request
import uuid
import threading
from team8monitor import mqtt_client


# Upload previews on a separate thread so slow HTTP responses do not block camera acquisition.
# This owns only preview delivery, not camera acquisition or motor control. It keeps the latest
# JPEG per checkpoint and uploads from a background thread, allowing the capture loop to keep
# reading while the server is slow.
class PreviewSender:
    """Upload only the latest frame off the capture thread. No video is stored."""
    # Create the latest-frame queue and start its background upload worker.
    # The server address and scanner token determine the authenticated upload target. Pending
    # images live only in memory, and an event lets shutdown wake the worker without waiting for
    # another camera frame.
    def __init__(self, server, token):
        self.server, self.token = server.rstrip('/'), token
        self.lock = threading.Lock()
        self.pending = {}
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.work, daemon=True)
        self.thread.start()

    # Replace any queued preview for this checkpoint; stale video should not build up in a
    # backlog.
    # Each checkpoint has one pending slot containing capture time and JPEG bytes. Replacing
    # that slot drops older waiting frames, avoiding a video backlog that would make the
    # dashboard appear more current than it is.
    def put(self, checkpoint, jpeg, captured_at):
        with self.lock:
            self.pending[checkpoint] = (captured_at, jpeg)

    # Send recent JPEGs only, dropping stale frames and letting the dashboard report failed
    # previews as unavailable.
    # The worker periodically takes the latest queued frames, discards stale ones and uploads
    # each bounded JPEG. Failed uploads are not endlessly retried; the dashboard independently
    # expires the previous preview and reports it unavailable.
    def work(self):
        while not self.stopped.wait(0.25):
            with self.lock:
                pending, self.pending = self.pending, {}
            for checkpoint, (captured_at, jpeg) in pending.items():
                if time.time() - captured_at > 3:
                    continue
                try:
                    request = urllib.request.Request(self.server+'/api/camera/'+checkpoint,
                        data=jpeg, headers={'Content-Type':'image/jpeg','X-Team8-Scan-Token':self.token,
                                            'X-Team8-Captured-At':str(captured_at)}, method='POST')
                    with urllib.request.urlopen(request, timeout=1) as response:
                        response.read()
                except Exception:
                    pass  # Dashboard independently marks missing/stale previews unavailable.

    # Release owned resources after the worker/server has stopped using them.
    # Set the stop event and wait briefly for any bounded upload to finish. Camera cleanup can
    # then proceed without leaving a preview thread attempting to use the shutting-down
    # application.
    def close(self):
        self.stopped.set()
        self.thread.join(timeout=3)


# Entry point: read terminal options, start the requested components, and clean up on exit.
# Command-line options select direct camera reading or an existing MQTT scanner feed. Camera
# mode can assign two image regions to A/B and share previews; neither mode reproduces the
# organizer motor-routing controller.
def main():
    # Camera mode reads frames; MQTT bridge mode reuses an already-running organizer scanner.
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',required=True,choices=['A','B','AB'])
    parser.add_argument('--camera',type=int,default=0)
    parser.add_argument('--server',default='http://127.0.0.1:8080')
    parser.add_argument('--mqtt-topic')
    parser.add_argument('--broker')
    parser.add_argument('--publish-topic', help='Publish structured scans to this NEW topic instead of HTTP; AB adds /A or /B')
    parser.add_argument('--no-preview', action='store_true', help='Disable local dashboard preview upload')
    parser.add_argument('--split-x', type=float, default=0.5, help='AB mode split position as fraction of image width')
    parser.add_argument('--a-side', choices=['left','right'], default='left')
    args=parser.parse_args()
    token=os.environ.get('TEAM8_SCAN_TOKEN','')
    if len(token)<24:
        parser.error('Set TEAM8_SCAN_TOKEN (at least 24 characters), same as the dashboard server')
    last_seen={}
    if not 0 < args.split_x < 1:
        parser.error('--split-x must be between 0 and 1')
    if args.mqtt_topic and (args.checkpoint == 'AB' or args.publish_topic):
        parser.error('MQTT bridge mode requires A or B and cannot republish')
    publisher = None
    if args.publish_topic:
        if not args.broker:
            parser.error('--publish-topic requires --broker')
        publisher = mqtt_client('team8-camera-' + uuid.uuid4().hex[:10])
        publisher.connect(args.broker, 1883, 30)
        publisher.loop_start()

    # Emit one scan per barcode appearance/checkpoint, using the same event ID for an HTTP
    # retry.
    # A barcode/checkpoint pair is sent only once per continuous appearance. MQTT delivery is
    # explicitly marked queued rather than confirmed; HTTP gets one retry with the same event ID
    # so a delayed response cannot count the scan twice.
    def send(barcode,source,checkpoint=None):
        checkpoint = checkpoint or args.checkpoint
        now=time.monotonic()
        key = (checkpoint, barcode)
        previous=last_seen.get(key,-1e9)
        last_seen[key]=now
        # Scan once per appearance; don't restart while continuously visible.
        if now-previous<2:
            return
        event={'barcode':barcode,'checkpoint':checkpoint,'source':source,'event_id':str(uuid.uuid4())}
        # Publishing a scan does not publish a motor command or a baggage-routing decision.
        if publisher is not None:
            topic = args.publish_topic + ('/'+checkpoint if args.checkpoint == 'AB' else '')
            info = publisher.publish(topic, json.dumps(event), qos=1, retain=False)
            print(checkpoint, barcode, 'queued for MQTT; receipt must be verified on dashboard', info.rc)
            return
        for attempt in range(2):
            try:
                request=urllib.request.Request(args.server.rstrip('/')+'/api/transit/scan',data=json.dumps(event).encode(),
                    headers={'Content-Type':'application/json','X-Team8-Scan-Token':token},method='POST')
                with urllib.request.urlopen(request,timeout=3) as r:
                    print(barcode,json.loads(r.read())['message'])
                return
            except Exception as error:
                print('Scan delivery failed:',type(error).__name__)
                # Same event ID makes a retry idempotent; receive-time latency still matters.
                if attempt==0: time.sleep(0.2)
        print('SCAN NOT CONFIRMED. Remove/re-present the barcode to try again; inspect connection.')

    if args.mqtt_topic:
        if not args.broker: parser.error('--broker is required for MQTT')
        client=mqtt_client('team8-scan-bridge-' + uuid.uuid4().hex[:10])
        client.on_connect=lambda c,u,f,rc: c.subscribe(args.mqtt_topic,qos=1) if rc==0 else print('MQTT connection rejected',rc)
        # Adapt an existing raw/routing MQTT barcode message into a timing submission.
        # Existing scanner topics can carry raw barcode text or the organizer routing JSON.
        # Retained/invalid messages are ignored; valid text is passed to the same timing sender
        # without inventing additional bag metadata.
        def on_message(c,u,msg):
            if msg.retain: return
            try:
                text=msg.payload.decode('utf-8')
                if args.mqtt_topic.endswith('/baggage_routing'): text=json.loads(text)['barcode']
                if not isinstance(text,str) or not text.strip(): return
                send(text,'mqtt')
            except (UnicodeError,ValueError,KeyError,TypeError): print('Invalid barcode message ignored')
        client.on_message=on_message
        client.connect(args.broker,1883,60)
        try: client.loop_forever()
        except KeyboardInterrupt: pass
        finally: client.disconnect()
        return
    import cv2
    from pyzbar.pyzbar import decode
    cap=cv2.VideoCapture(args.camera)
    if not cap.isOpened(): raise RuntimeError('Camera unavailable; verify --camera index and camera permissions')
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    previews = None if args.no_preview else PreviewSender(args.server, token)
    last_preview = -1e9
    try:
        while True:
            ok,frame=cap.read()
            if not ok: raise RuntimeError('Camera stopped supplying frames')
            captured_at = time.time()
            for code in decode(frame):
                try: barcode=code.data.decode('utf-8')
                except UnicodeError: continue
                x,y,w,h=code.rect
                checkpoint = args.checkpoint
                # One wide view can supply two spatial regions; verify direction and coverage physically.
                if checkpoint == 'AB':
                    side = 'left' if x+w/2 < frame.shape[1]*args.split_x else 'right'
                    checkpoint = 'A' if side == args.a_side else 'B'
                send(barcode,'camera',checkpoint)
                cv2.rectangle(frame,(x,y),(x+w,y+h),(0,180,0),2)
                cv2.putText(frame,checkpoint+': '+barcode[:50],(x,max(25,y-10)),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,180,0),1)
            if args.checkpoint == 'AB':
                split = int(frame.shape[1]*args.split_x)
                cv2.line(frame,(split,0),(split,frame.shape[0]),(255,180,0),2)
                cv2.putText(frame,'A: '+args.a_side+' | B: opposite side',(10,25),cv2.FONT_HERSHEY_SIMPLEX,0.6,(255,180,0),2)
            # Share the acquired frame with the dashboard; do not open the same camera a second time.
            if previews is not None and time.monotonic()-last_preview >= 0.5:
                last_preview = time.monotonic()
                scale = min(1,640/frame.shape[1])
                preview = cv2.resize(frame,(int(frame.shape[1]*scale),int(frame.shape[0]*scale)))
                encoded, jpeg = cv2.imencode('.jpg',preview,[cv2.IMWRITE_JPEG_QUALITY,60])
                if encoded:
                    for point in ('A','B') if args.checkpoint == 'AB' else (args.checkpoint,):
                        previews.put(point,jpeg.tobytes(),captured_at)
            cv2.imshow('Team8 checkpoint '+args.checkpoint+' (ESC to exit)',frame)
            if cv2.waitKey(1)&255==27: break
    except KeyboardInterrupt: pass
    finally:
        if previews is not None:
            previews.close()
        if publisher is not None:
            publisher.disconnect()
            publisher.loop_stop()
        cap.release()
        cv2.destroyAllWindows()


if __name__=='__main__': main()
