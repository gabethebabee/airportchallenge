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
    args = parser.parse_args()
    topics = args.topic or ['Conveyor4/#']
    client = mqtt_client('team8-inspect-' + uuid.uuid4().hex[:10])

    # Subscribe only to the requested station prefixes after connecting; this diagnostic
    # publishes nothing.
    # A successful broker connection triggers only subscriptions to the requested station
    # prefixes. A rejected connection is reported directly, so an empty message listing is not
    # automatically interpreted as healthy equipment.
    def connected(connection, userdata, flags, rc):
        print('MQTT connection result:', rc)
        if rc == 0:
            for topic in topics:
                connection.subscribe(topic, qos=0)

    # Print a bounded preview of the actual payload so topic names, units and retained data can
    # be checked.
    # Print the topic, retained/new indicator and a bounded decoded payload preview. The output
    # is for diagnosing actual message shape; it does not update the dashboard or treat retained
    # data as a new scan.
    def message(connection, userdata, msg):
        print(msg.topic, '(retained)' if msg.retain else '(new)',
              msg.payload[:1500].decode('utf-8', errors='replace'))

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


if __name__ == '__main__':
    main()
