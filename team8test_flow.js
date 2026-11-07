// Offline evaluation of Node-RED function nodes; no PLC or network access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = JSON.parse(fs.readFileSync('team8conveyor_flow.json', 'utf8'));
const byId = Object.fromEntries(nodes.map(n=>[n.id,n]));
assert.equal(byId['team8-control-tab'].disabled,true);
for(const n of nodes) for(const group of n.wires||[]) for(const target of group) assert.ok(byId[target],target);
for(const n of nodes.filter(n=>n.type==='function')) {
 new vm.Script('(function(msg){'+n.func+'})');
 if(n.initialize)new vm.Script(n.initialize);
}
const store=new Map(), globals=new Map();let now=100000;
const ctx={flow:{get:k=>store.get(k),set:(k,v)=>store.set(k,v)},global:{get:k=>globals.get(k)},env:{get:()=> 'x'.repeat(32)},Date:{now:()=>now},Number,Math};
function execute(id,msg){return vm.runInNewContext('(function(msg){'+byId[id].func+'})(msg)',{...ctx,msg});}
const command=action=>execute('team8-command',{payload:{action},req:{headers:{'x-team8-token':'x'.repeat(32)}}});
assert.equal(command('run')[0].statusCode,409); // No route means no start.
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
const python=fs.readFileSync('team8dashboard.py','utf8');
new vm.Script(python.match(/<script>([\s\S]*?)<\/script>/)[1]);
console.log('Flow wiring, authorization, routing, expiry, stop race, encoder units, and browser script syntax passed.');
