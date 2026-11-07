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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',required=True,choices=['A','B'])
    parser.add_argument('--camera',type=int,default=0)
    parser.add_argument('--server',default='http://127.0.0.1:8080')
    parser.add_argument('--mqtt-topic')
    parser.add_argument('--broker')
    args=parser.parse_args()
    token=os.environ.get('TEAM8_SCAN_TOKEN','')
    if len(token)<24:
        parser.error('Set TEAM8_SCAN_TOKEN (at least 24 characters), same as the dashboard server')
    last_seen={}

    def send(barcode,source):
        now=time.monotonic()
        previous=last_seen.get(barcode,-1e9)
        last_seen[barcode]=now
        # Scan once per appearance; don't restart while continuously visible.
        if now-previous<2:
            return
        event={'barcode':barcode,'checkpoint':args.checkpoint,'source':source,'event_id':str(uuid.uuid4())}
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
        import paho.mqtt.client as mqtt
        client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect=lambda c,u,f,rc,p: c.subscribe(args.mqtt_topic,qos=1) if rc==0 else print('MQTT connection rejected',rc)
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
    try:
        while True:
            ok,frame=cap.read()
            if not ok: raise RuntimeError('Camera stopped supplying frames')
            for code in decode(frame):
                try: barcode=code.data.decode('utf-8')
                except UnicodeError: continue
                send(barcode,'camera')
                x,y,w,h=code.rect
                cv2.rectangle(frame,(x,y),(x+w,y+h),(0,180,0),2)
                cv2.putText(frame,args.checkpoint+': '+barcode[:50],(x,max(25,y-10)),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,180,0),1)
            cv2.imshow('Team8 checkpoint '+args.checkpoint+' (ESC to exit)',frame)
            if cv2.waitKey(1)&255==27: break
    except KeyboardInterrupt: pass
    finally: cap.release();cv2.destroyAllWindows()


if __name__=='__main__': main()
