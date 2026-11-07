"""Generate a read-only Node-RED MQTT exporter from verified organizer node mappings.

Uses team8conveyor_flow.json as the local copy of the organizer Groov definitions.
No deployment is performed, and the generated flow contains no output-write nodes.
"""
import copy
import json
from pathlib import Path


# Construct the read-only sensor exporter from source-backed Groov definitions; no outputs are
# written or deployed.
# Copy the verified Groov encoder/device definitions into an independent disabled read-only tab.
# Encoder deltas and output readback become non-retained telemetry with explicit unknowns; a
# final check rejects any accidental output-write node.
def build():
    root = Path(__file__).resolve().parent
    source = json.loads((root / 'team8conveyor_flow.json').read_text(encoding='utf-8'))
    by_id = {node['id']: node for node in source}
    tab = 'team8-sensor-tab'
    nodes = [{
        'id': tab, 'type': 'tab', 'label': 'Team8 read-only MQTT sensors', 'disabled': True,
        'info': 'Encoder channel 0 and analog output channel 7 readback. No writes. Verify channel 7 readback and input polling in the lab. Current is unknown.'
    }]
    device = copy.deepcopy(by_id['team8-groov-device'])
    device['id'] = 'team8-sensor-device'
    nodes.append(device)
    broker = copy.deepcopy(by_id['team8-mqtt-broker'])
    broker.update(id='team8-sensor-broker', clientid='team8-sensor-exporter')
    nodes.append(broker)

    # Append one labelled Node-RED node, keeping its wiring and sensor role visible in the
    # generated flow.
    # This constructs one labelled flow node and appends it to the export list. Explicit wires
    # make the sensor-processing path inspectable, while the helper avoids repeating canvas
    # coordinates and tab IDs everywhere.
    def add(node_id, kind, name, wires=None, **fields):
        node = {'id': node_id, 'type': kind, 'z': tab, 'name': name,
                'x': fields.pop('x', 450), 'y': fields.pop('y', 240), 'wires': wires or [[]], **fields}
        nodes.append(node)
        return node

    encoder = copy.deepcopy(by_id['team8-encoder'])
    encoder.update(id='team8-sensor-encoder', z=tab, device=device['id'],
                   deadband='0', scanTimeSec='1.0', sendInitialValue=True,
                   name='Encoder counter (organizer channel 0)', wires=[['team8-sensor-speed']], x=200, y=100)
    nodes.append(encoder)
    add('team8-sensor-speed', 'function', 'Counter delta to linear speed (cm/s)', outputs=1, x=590, y=100,
        initialize='''/* TEAM8 DETAIL:
 * This runs when the node is initialized or redeployed, before incoming messages are
 * processed. Cached timestamps, counters or permission flags start from an explicit
 * baseline so old context cannot masquerade as newly observed state.
 */
// TEAM8 NOTE: Initialize node-local timing/state for Counter delta to linear speed (cm/s).
flow.set("encoderPrevious",null);flow.set("encoderAt",0);flow.set("encoderSpeed",null);''',
        func='''/* TEAM8 DETAIL:
 * Fresh encoder counts are converted into linear belt speed using 700 counts per
 * revolution, a factor-four pulley ratio and a 10.5 cm pulley diameter. The first
 * reading establishes a baseline; invalid, reset or widely separated counts cannot
 * supply a trustworthy speed.
 */
// TEAM8 NOTE: Counter delta to linear speed (cm/s); msg is the incoming message and returned messages follow the configured wires.
if (msg.payload===null || msg.payload===undefined || typeof msg.payload==="boolean" || msg.payload==="") return null;
const now=Date.now(), count=Number(msg.payload), prev=flow.get("encoderPrevious");
if (!Number.isFinite(count)) return null;
let speed=null;
if (prev && now>prev.at && now-prev.at<=3000 && count>=prev.count) {
    speed=(count-prev.count)/(700*4)*(10.5*3.14)/((now-prev.at)/1000);
}
flow.set("encoderPrevious",{count,at:now});
flow.set("encoderAt",now);flow.set("encoderSpeed",speed);return null;''')
    output = copy.deepcopy(encoder)
    output.update(id='team8-sensor-output', dataType='channel-analog', channelIndex='7',
                  name='Channel 7 output readback (verify locally)', wires=[['team8-sensor-run']], x=200, y=200)
    nodes.append(output)
    add('team8-sensor-run', 'function', 'Output voltage indicates run requested, not motion', outputs=1, x=610, y=200,
        initialize='''/* TEAM8 DETAIL:
 * This runs when the node is initialized or redeployed, before incoming messages are
 * processed. Cached timestamps, counters or permission flags start from an explicit
 * baseline so old context cannot masquerade as newly observed state.
 */
// TEAM8 NOTE: Initialize node-local timing/state for Output voltage indicates run requested, not motion.
flow.set("outputAt",0);flow.set("outputVoltage",null);''',
        func='''/* TEAM8 DETAIL:
 * This reads the configured analog output channel without writing it. Its timestamp
 * and voltage are cached for the publisher, which uses positive voltage as run-request
 * evidence. Output readback must be verified locally and is not a measurement of
 * current or motion.
 */
// TEAM8 NOTE: Output voltage indicates run requested, not motion; msg is the incoming message and returned messages follow the configured wires.
if (msg.payload===null || msg.payload===undefined || typeof msg.payload==="boolean" || msg.payload==="") return null;
const voltage=Number(msg.payload);
if (!Number.isFinite(voltage) || voltage<0) return null;
flow.set("outputAt",Date.now());flow.set("outputVoltage",voltage);return null;''')
    add('team8-sensor-tick', 'inject', 'Publish once per second', [['team8-sensor-payload']],
        props=[{'p': 'payload'}], payload='', payloadType='date', repeat='1', once=True, onceDelay=1, crontab='', x=180, y=340)
    add('team8-sensor-payload', 'function', 'Build explicit telemetry with unknowns', [['team8-sensor-publish']], outputs=1, x=550, y=340,
        initialize='''/* TEAM8 DETAIL:
 * This runs when the node is initialized or redeployed, before incoming messages are
 * processed. Cached timestamps, counters or permission flags start from an explicit
 * baseline so old context cannot masquerade as newly observed state.
 */
// TEAM8 NOTE: Initialize node-local timing/state for Build explicit telemetry with unknowns.
flow.set("sensorSession",Date.now().toString(36)+Math.random().toString(36).slice(2));flow.set("sensorSequence",0);''',
        func='''/* TEAM8 DETAIL:
 * The periodic tick packages fresh cached measurements with a session ID and
 * increasing sequence number. Old underlying input values become null even if the MQTT
 * publisher is still connected. Current remains null until an actual calibrated sensor
 * is integrated.
 */
// TEAM8 NOTE: Build explicit telemetry with unknowns; msg is the incoming message and returned messages follow the configured wires.
const now=Date.now();
const session=flow.get("sensorSession");
const seq=(flow.get("sensorSequence")||0)+1;flow.set("sensorSequence",seq);
const encoderFresh=now-(flow.get("encoderAt")||0)<=3000;
const outputFresh=now-(flow.get("outputAt")||0)<=3000;
const voltage=flow.get("outputVoltage");
msg.payload=JSON.stringify({
    station_id:"Conveyor3",event_id:session+":"+seq,session_id:session,sequence:seq,
    speed_cm_s:encoderFresh ? flow.get("encoderSpeed") : null,
    run_requested:outputFresh && typeof voltage==="number" ? voltage>0.1 : null,
    current_a:null
});
msg.retain=false;return msg;''')
    add('team8-sensor-publish', 'mqtt out', 'Team8 telemetry (non-retained)',
        topic='team8/Conveyor3/telemetry', qos='0', retain='false', broker=broker['id'], x=920, y=340)
    add('team8-sensor-errors', 'catch', 'Sensor input errors invalidate cached readings', [['team8-sensor-invalidate']],
        scope=['team8-sensor-encoder', 'team8-sensor-output'], uncaught=False, x=230, y=440)
    add('team8-sensor-invalidate', 'function', 'Mark both readings unknown after input errors', outputs=1, x=650, y=440,
        func='/* TEAM8 DETAIL:\n * A Groov input error makes the cached encoder and output observations unusable. Their\n * timestamps and counter baseline are reset so the next publisher tick sends unknowns\n * instead of repeatedly reporting the old values as current.\n */\n// TEAM8 NOTE: Mark both readings unknown after input errors; msg is the incoming message and returned messages follow the configured wires.\nflow.set("encoderAt",0);flow.set("encoderPrevious",null);flow.set("outputAt",0);return null;')
    assert not any(node['type'] == 'groov-io-write' for node in nodes)
    ids = {node['id'] for node in nodes}
    assert all(target in ids for node in nodes for group in node.get('wires', []) for target in group)
    (root / 'team8sensor_flow.json').write_text(json.dumps(nodes, indent=2)+'\n', encoding='utf-8')
    print('Generated team8sensor_flow.json (read-only; disabled; not deployed)')


if __name__ == '__main__':
    build()
