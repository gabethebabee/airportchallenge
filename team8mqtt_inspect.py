"""Read-only MQTT topic inspection. Never publishes or changes PLC outputs."""
import argparse
import threading
import uuid
from team8monitor import mqtt_client


# Entry point: read terminal options, start the requested components, and clean up on exit.
# Read broker/topic options and listen for a bounded amount of time. This diagnostic prints
# message examples to help verify payloads and units, and never publishes sensor values or motor
# commands.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--broker', default='129.97.228.106')
    parser.add_argument('--topic', action='append', help='Assigned station prefix; repeat for multiple prefixes')
    parser.add_argument('--seconds', type=float, default=15)
    parser.add_argument('--sensors-only', action='store_true', help='Hide Team8 camera/tag/health traffic and show up to three samples per other topic')
    args = parser.parse_args()
    topics = args.topic or ['Conveyor4/#']
    client = mqtt_client('team8-inspect-' + uuid.uuid4().hex[:10])
    seen = {}
    accepted = threading.Event()

    # Subscribe only to the requested station prefixes after connecting; this diagnostic
    # publishes nothing.
    # A successful broker connection triggers only subscriptions to the requested station
    # prefixes. A rejected connection is reported directly, so an empty message listing is not
    # automatically interpreted as healthy equipment.
    def connected(connection, userdata, flags, rc):
        print('MQTT connection result:', rc, flush=True)
        if rc == 0:
            accepted.set()
            for topic in topics:
                connection.subscribe(topic, qos=0)

    # Print a bounded preview of the actual payload so topic names, units and retained data can
    # be checked.
    # Print the topic, retained/new indicator and a bounded decoded payload preview. The output
    # is for diagnosing actual message shape; it does not update the dashboard or treat retained
    # data as a new scan.
    def message(connection, userdata, msg):
        # SECTION: Discovery excludes our own preview/detection/health outputs,
        # which can otherwise hide actual PLC messages in a busy camera stream.
        # Limit printed samples, but count all matched deliveries for the summary.
        # A retained message is labelled explicitly; it is not proof of live data.
        lower = msg.topic.lower()
        if args.sensors_only and ('/camera/' in lower or '/apriltags' in lower or
                                 lower.endswith('/flag') or lower.endswith('/status') or
                                 msg.payload.startswith((b'T8J1',b'\xff\xd8'))):
            return
        seen[msg.topic] = seen.get(msg.topic,0)+1
        if args.sensors_only and seen[msg.topic]>3:
            return
        print(msg.topic, '(retained)' if msg.retain else '(new)',
              msg.payload[:1500].decode('utf-8', errors='replace'),flush=True)

    client.on_connect = connected
    client.on_message = message
    client.connect_async(args.broker, 1883, 30)
    client.loop_start()
    try:
        threading.Event().wait(max(1, min(args.seconds, 120)))
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()
        client.loop_stop()
        if args.sensors_only:
            if not accepted.is_set():
                print('No accepted MQTT connection observed; topic availability is unverified.')
            elif not seen:
                print('No sensor candidates under these filters during this window. Check the exact topic prefix/case; this does not prove the PLC is silent.')
            else:
                print('Candidate topic delivery counts:',seen)


if __name__ == '__main__':
    main()
