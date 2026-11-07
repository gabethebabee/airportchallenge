"""Build an isolated Node-RED flow from the organizer ZIP; never deploys it."""
import copy
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent


def build():
    with zipfile.ZipFile(ROOT / 'F26-Airport-Innovation-Challenge.zip') as archive:
        prefix = 'F26-Airport-Innovation-Challenge/baggage-handling-system-subproblem/barcode-conveyor/'
        baseline = json.loads(archive.read(prefix + 'flows.json'))
        motion = json.loads(archive.read(prefix + 'Basic Motion and Divert.json'))
    by_id = {node['id']: node for node in baseline}
    tab = 'team8-control-tab'
    nodes = [{'id': tab, 'type': 'tab', 'label': 'Team8 conveyor control', 'disabled': True,
              'info': 'Derived from organizer flows.json and Basic Motion and Divert.json. See team8CONTROL.md before enabling.'}]

    def add(id, type, name='', wires=None, **extra):
        node = {'id': id, 'type': type, 'z': tab, 'name': name,
                'x': extra.pop('x', 400), 'y': extra.pop('y', 200), 'wires': wires or [[]], **extra}
        nodes.append(node)
        return node

    # Reuse the exact organizer channel definitions without copying credential configs.
    device = copy.deepcopy(by_id['82bcbeb0.3e26a'])
    device['id'] = 'team8-groov-device'
    nodes.append(device)
    broker = copy.deepcopy(by_id['c21a17d0.91ece8'])
    broker.update(id='team8-mqtt-broker', clientid='team8-conveyor-bridge', birthTopic='', closeTopic='', willTopic='')
    nodes.append(broker)
    for original, id, name in [('7cd59d77060952c9','team8-write-speed','Belt output (channel 7)'),
                                ('d399c781b674f3ab','team8-write-direction','Fixed organizer direction (channel 6)')]:
        node = copy.deepcopy(by_id[original])
        node.update(id=id, z=tab, device=device['id'], name=name, x=1050, y=200 if id.endswith('speed') else 140, wires=[[]])
        nodes.append(node)

    add('team8-http', 'http in', 'Team8 command API', [['team8-command']], url='/team8/conveyor', method='post', upload=False, swaggerDoc='', x=160, y=80)
    add('team8-response','http response','Command result',statusCode='',headers={},x=1050,y=80)
    add('team8-command','function','Validate command and route gate',
        [['team8-response'],['team8-write-speed'],['team8-write-direction']],outputs=3,
        initialize='flow.set("team8Deadline",0); flow.set("team8RouteOK",false); flow.set("team8LastCommand","unknown after deploy");',
        func='''const token = env.get("TEAM8_CONTROL_TOKEN");
const reply = (code, message, speed, direction) => {
    msg.statusCode = code;
    const seen = flow.get("team8EncoderAt") || 0;
    msg.payload = {message, last_command:flow.get("team8LastCommand") || "none",
      output_requested:flow.get("team8Output") ?? null,
      route_allowed:flow.get("team8RouteOK") === true,
      pulse_remaining_ms:Math.max(0,(flow.get("team8Deadline")||0)-Date.now()),
      speed_cm_s:Date.now()-seen < 3000 ? flow.get("team8Speed") ?? null : null,
      encoder_fresh:Date.now()-seen < 3000,
      note:"Command state is not physical motor confirmation"};
    return [msg, speed === undefined ? null : {payload:speed}, direction === undefined ? null : {payload:direction}];
};
if (!token || token.length < 24 || msg.req.headers['x-team8-token'] !== token) return reply(403,"Control token missing or invalid");
const action = msg.payload && msg.payload.action;
if (action === 'status') return reply(200,"PLC bridge available");
if (action === 'stop') {
    flow.set("team8Deadline",0); flow.set("team8Output",0); flow.set("team8LastCommand","stop requested");
    return reply(200,"Stop output requested",0);
}
if (action !== 'run') return reply(400,"Unknown action");
if (flow.get("team8RouteOK") !== true) return reply(409,"Scan an allowed barcode for the active destination before Run");
if (flow.get("team8RouteDestination") !== (global.get("active_conveyor") || "conveyor_1")) return reply(409,"Active destination changed; scan again");
if (Date.now()-(flow.get("team8RouteAt")||0)>10000) return reply(409,"Route check expired; scan an allowed barcode again");
// Organizer flows.json uses 2.3 V on channel 7 and 0 on direction channel 6.
// Direction is written separately BEFORE the run output (see wiring below).
flow.set("team8Deadline",Date.now()+3000); flow.set("team8Output",2.3); flow.set("team8LastCommand","3-second run requested");
return reply(200,"3-second run requested; verify motion at the belt",undefined,0);''',x=550,y=80)
    # Direction node completion triggers run, so direction is not changed after starting.
    direction = next(n for n in nodes if n['id']=='team8-write-direction')
    direction['wires']=[['team8-after-direction']]
    add('team8-after-direction','function','Run only if lease and route still valid',[['team8-write-speed']],outputs=1,
        func='return flow.get("team8RouteOK") === true && Date.now() < (flow.get("team8Deadline")||0) ? {payload:2.3} : {payload:0};',x=820,y=140)
    add('team8-tick','inject','Stop on deploy / pulse expiry',[['team8-watchdog']],repeat='0.25',crontab='',once=True,onceDelay=0.1,
        props=[{'p':'payload'}],payload='',payloadType='date',x=170,y=280)
    add('team8-watchdog','function','Bound each run to 3 seconds',[['team8-write-speed']],outputs=1,
        initialize='flow.set("team8NeedsStop",true); flow.set("team8Deadline",0);',
        func='''if (flow.get("team8NeedsStop") || ((flow.get("team8Deadline")||0)>0 && Date.now()>=flow.get("team8Deadline"))) {
 flow.set("team8NeedsStop",false); flow.set("team8Deadline",0); flow.set("team8Output",0);
 flow.set("team8LastCommand","automatic stop requested"); return {payload:0};
} return null;''',x=550,y=280)
    route = copy.deepcopy(by_id['9d7b2f3f4ed8caec'])
    route.update(id='team8-routing',z=tab,broker=broker['id'],name='Organizer routing input',wires=[['team8-route-check']],x=170,y=400,datatype='utf8',rap=False)
    nodes.append(route)
    add('team8-route-check','function','Preserve rejection stop; do not auto-restart',[['team8-write-speed']],outputs=1,
        initialize='flow.set("team8RouteOK",false);',
        func='''let p; try {p=typeof msg.payload === 'string' ? JSON.parse(msg.payload) : msg.payload;} catch(e) {p=null;}
const active = global.get("active_conveyor") || "conveyor_1";
const ok = !msg.retain && p && typeof p.barcode === 'string' && p.barcode.length>0 && p.in_picklist === true && p.conveyor === active;
flow.set("team8RouteOK",!!ok); flow.set("team8RouteAt",Date.now()); flow.set("team8RouteDestination",ok ? p.conveyor : null);
if (!ok) {flow.set("team8Deadline",0);flow.set("team8Output",0);flow.set("team8LastCommand","routing rejection stop requested");return {payload:0};}
return null;''',x=550,y=400)
    encoder = copy.deepcopy(next(n for n in motion if n.get('name')=='encoder'))
    encoder.update(id='team8-encoder',z=tab,device=device['id'],wires=[['team8-encoder-speed']],x=170,y=520)
    nodes.append(encoder)
    add('team8-encoder-speed','function','Organizer encoder formula (cm/s)',outputs=1,
        initialize='flow.set("team8PreviousEncoder",null);flow.set("team8EncoderAt",0);flow.set("team8Speed",null);',
        func='''const now=Date.now(), count=Number(msg.payload), prev=flow.get("team8PreviousEncoder");
if (!Number.isFinite(count)) return null;
if (prev && now>prev.time) {
 const delta=count-prev.count;
 flow.set("team8Speed",delta>=0 ? delta/(700*4)*(10.5*3.14)/((now-prev.time)/1000) : null);
}
flow.set("team8PreviousEncoder",{count,time:now}); flow.set("team8EncoderAt",now);return null;''',x=550,y=520)
    # Ensure all references point inside the generated flow.
    ids={n['id'] for n in nodes}
    assert all(target in ids for n in nodes for group in n.get('wires',[]) for target in group)
    output=ROOT/'team8conveyor_flow.json'
    output.write_text(json.dumps(nodes,indent=2)+'\n',encoding='utf-8')
    print('Built',output.name,'(disabled; not deployed)')


if __name__=='__main__':
    build()
