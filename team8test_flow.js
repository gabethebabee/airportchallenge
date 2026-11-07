// Offline evaluation of Node-RED function nodes; no PLC or network access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
// Read the saved graph, not a PLC: all function execution below happens in an isolated JS context.
/* SECTION DETAIL:
 * The saved control graph is loaded as ordinary JSON and checked for valid references
 * and disabled startup state. Function strings are compiled before their logic is
 * exercised, catching malformed generated JavaScript without importing it into a PLC.
 */
const nodes = JSON.parse(fs.readFileSync('team8conveyor_flow.json', 'utf8'));
const byId = Object.fromEntries(nodes.map(n=>[n.id,n]));
assert.equal(byId['team8-control-tab'].disabled,true);
for(const n of nodes) for(const group of n.wires||[]) for(const target of group) assert.ok(byId[target],target);
for(const n of nodes.filter(n=>n.type==='function')) {
 new vm.Script('(function(msg){'+n.func+'})');
 if(n.initialize)new vm.Script(n.initialize);
}
// These maps stand in for Node-RED flow/global context; advancing now simulates elapsed time instantly.
/* SECTION DETAIL:
 * These maps stand in for Node-RED flow/global state and the supplied environment
 * token. A controllable clock allows expiry and freshness scenarios to run instantly.
 * No real node implementation or physical output is invoked.
 */
const store=new Map(), globals=new Map();let now=100000;
const ctx={flow:{get:k=>store.get(k),set:(k,v)=>store.set(k,v)},global:{get:k=>globals.get(k)},env:{get:()=> 'x'.repeat(32)},Date:{now:()=>now},Number,Math};
// Execute only the selected function body with fake context and a supplied test message.
/* SECTION DETAIL:
 * The function body for a selected node runs inside a fresh VM context with the fake
 * stores and provided message. Its returned messages can be inspected as plain data,
 * making output routing and rejection behavior testable without a network connection.
 */
function execute(id,msg){return vm.runInNewContext('(function(msg){'+byId[id].func+'})(msg)',{...ctx,msg});}
// Construct an authenticated command request locally; no HTTP or motor outputs are involved.
/* SECTION DETAIL:
 * This helper constructs the same request shape expected by the control function,
 * including its test-only token. Scenarios then compare its reply/output messages
 * against the intended permission and expiry rules; nothing is sent over HTTP.
 */
const command=action=>execute('team8-command',{payload:{action},req:{headers:{'x-team8-token':'x'.repeat(32)}}});
assert.equal(command('run')[0].statusCode,409); // No route means no start.
// A valid route permits a bounded run; expiry and a later route rejection must both request zero output.
execute('team8-route-check',{payload:{barcode:'test',in_picklist:true,conveyor:'conveyor_1'}});
assert.equal(command('run')[0].statusCode,200);
assert.equal(execute('team8-after-direction',{}).payload,2.3);
now+=3001;
assert.equal(execute('team8-watchdog',{}).payload,0);
assert.equal(execute('team8-watchdog',{}),null); // No repeat writes when idle.
execute('team8-route-check',{payload:{barcode:'test',in_picklist:true,conveyor:'conveyor_1'}});
command('run');
assert.equal(execute('team8-route-check',{payload:{barcode:'bad',in_picklist:false,conveyor:'conveyor_1'}}).payload,0);
assert.equal(execute('team8-after-direction',{}).payload,0); // Pending start cannot undo rejection.
assert.equal(command('run')[0].statusCode,409);
assert.equal(command('stop')[1].payload,0);
assert.equal(execute('team8-route-check',{payload:'broken JSON'}).payload,0);
execute('team8-route-check',{payload:{barcode:'test',in_picklist:true,conveyor:'conveyor_1'}});
now+=10001;assert.equal(command('run')[0].statusCode,409);
execute('team8-route-check',{payload:{barcode:'test',in_picklist:true,conveyor:'conveyor_1'}});
globals.set('active_conveyor','conveyor_2');assert.equal(command('run')[0].statusCode,409);globals.clear();
assert.equal(execute('team8-route-check',{retain:true,payload:{barcode:'test',in_picklist:true,conveyor:'conveyor_1'}}).payload,0);
assert.equal(execute('team8-command',{payload:{action:'run'},req:{headers:{}}})[0].statusCode,403);
execute('team8-encoder-speed',{payload:0});now+=1000;
execute('team8-encoder-speed',{payload:2800});
assert.ok(Math.abs(store.get('team8Speed')-32.97)<0.001);
now+=4000;assert.equal(command('status')[0].payload.speed_cm_s,null);
new vm.Script(fs.readFileSync('team8dashboard.js','utf8'));
new vm.Script(fs.readFileSync('team8live.js','utf8'));

// Read-only sensor exporter: preserve actual encoder conversion, never write outputs.
/* SECTION DETAIL:
 * The passive exporter graph is checked independently from the control graph. Tests
 * ensure it is disabled, contains no output-write nodes, has valid wiring and
 * compiles, then verify conversion and stale-value behavior against synthetic encoder
 * counts.
 */
const sensorNodes = JSON.parse(fs.readFileSync('team8sensor_flow.json','utf8'));
const sensorById = Object.fromEntries(sensorNodes.map(node => [node.id,node]));
assert.equal(sensorById['team8-sensor-tab'].disabled,true);
assert.ok(sensorNodes.every(node => node.type !== 'groov-io-write'));
for (const node of sensorNodes) {
 for (const group of node.wires || []) for (const target of group) assert.ok(sensorById[target]);
 if (node.type === 'function') {
  new vm.Script('(function(msg){' + node.func + '})');
  if(node.initialize)vm.runInNewContext(node.initialize,ctx);
 }
}
// Evaluate the passive sensor-exporter functions against the same fake clock and stores.
/* SECTION DETAIL:
 * The passive sensor function is evaluated against the same controllable stores and
 * clock. Tests can feed counter/readback values and inspect the published payload
 * without attaching actual Groov input channels.
 */
function sensorExecute(id,msg={}) {
 return vm.runInNewContext('(function(msg){'+sensorById[id].func+'})(msg)',{...ctx,msg});
}
// One pulley revolution is 2800 counts after gearing; the supplied circumference gives 32.97 cm/s.
sensorExecute('team8-sensor-speed',{payload:0});now+=1000;
sensorExecute('team8-sensor-speed',{payload:2800});
sensorExecute('team8-sensor-run',{payload:2.3});
let telemetry = JSON.parse(sensorExecute('team8-sensor-payload').payload);
assert.ok(Math.abs(telemetry.speed_cm_s-32.97)<0.001);
assert.equal(telemetry.run_requested,true);assert.equal(telemetry.current_a,null);
now+=4000;
telemetry=JSON.parse(sensorExecute('team8-sensor-payload').payload);
assert.equal(telemetry.speed_cm_s,null);assert.equal(telemetry.run_requested,null);
console.log('Read-only MQTT sensor exporter conversion, freshness, and no-write checks passed.');
console.log('Flow wiring, authorization, routing, expiry, stop race, encoder units, and browser script syntax passed.');
