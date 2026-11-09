"""Build a read-only Conveyor 4 MQTT exporter from the supplied station flow."""
import copy
import json
from pathlib import Path


# SECTION: Reuse the assigned station's verified input/device definitions only.
# The generated tab has fresh IDs and is disabled for review before deployment.
# It reads encoder channel 0 and channel 7 voltage; it contains no output writes,
# motor commands, routing logic or guessed current-sensor channel.
def build():
    root = Path(__file__).resolve().parent
    source = json.loads((root/'Node-RED stuff').read_text(encoding='utf-8'))
    lookup = {node['id']:node for node in source}
    tab = 'team8-c4-sensors-tab'
    nodes = [dict(id=tab,type='tab',label='Team8 Conveyor 4 read-only sensors',disabled=True,
                  info='Review on the assigned PLC before enabling. Encoder 0, voltage readback 7. Current not mapped.')]
    broker = copy.deepcopy(lookup['c21a17d0.91ece8'])
    broker.update(id='team8-c4-sensors-broker',clientid='',birthTopic='',closeTopic='',willTopic='')
    device = copy.deepcopy(lookup['1d984926.1d3e57'])
    device['id'] = 'team8-c4-sensors-device'
    nodes += [broker,device]

    # SECTION: These Groov inputs poll rather than accepting commands. A zero
    # deadband requests maximum reporting; actual unchanged-value emission must
    # be checked onsite. The dashboard expires missing samples instead of assuming
    # that an unchanged encoder means zero speed or a healthy sensor.
    encoder = copy.deepcopy(lookup['fdf231e55ca4f09f'])
    voltage = copy.deepcopy(lookup['7015db7c715b8bf5'])
    for original,name,identity,target,y in (
            (encoder,'Read encoder count (channel 0)','encoder','speed',100),
            (voltage,'Read voltage (channel 7)','voltage','volts',240)):
        original.update(id='team8-c4-'+identity,z=tab,device=device['id'],deadband='0',
                        sendInitialValue=True,scanTimeSec='1.0',name=name,x=180,y=y,
                        wires=[['team8-c4-'+target]])
        nodes.append(original)

    # SECTION: Convert two actual encoder observations into linear belt speed.
    # Conversion constants are from the supplied station function. First samples,
    # long gaps and counter rollback cannot produce a trustworthy speed. Send a
    # JSON null for those cases, which the existing dashboard marks unknown.
    speed = '''// Read-only calculation: no PLC output is written.
const now=Date.now(), raw=msg.payload;
const count=Number(raw), prev=context.get('previous');
let speed=null;
if (raw!==null && raw!=='' && typeof raw!=='boolean' && Number.isFinite(count) && count>=0) {
  if (prev && now>prev.at && now-prev.at<=3000 && count>=prev.count)
    speed=(count-prev.count)/(700*4)*(10.5*3.14)/((now-prev.at)/1000);
  context.set('previous',{count,at:now});
} else context.set('previous',null);
msg.payload=JSON.stringify(speed);msg.retain=false;return msg;'''
    volts = '''// Read actual channel 7 voltage; never relabel it as amperage.
const raw=msg.payload, value=Number(raw);
msg.payload=JSON.stringify(raw!==null && raw!=='' && typeof raw!=='boolean' && Number.isFinite(value) && value>=0 ? value : null);
msg.retain=false;return msg;'''
    for identity,label,function,topic,y in (
            ('speed','Encoder to cm/s',speed,'Conveyor4/get_belt_speed',100),
            ('volts','Voltage in V',volts,'Conveyor4/get_motor_voltage',240)):
        nodes.append(dict(id='team8-c4-'+identity,type='function',z=tab,name=label,func=function,
                          initialize="// Clear pre-deploy counter history.\ncontext.set('previous',null);",
                          outputs=1,x=490,y=y,wires=[['team8-c4-publish-'+identity]]))
        nodes.append(dict(id='team8-c4-publish-'+identity,type='mqtt out',z=tab,name=topic,
                          topic=topic,qos='0',retain='false',broker=broker['id'],x=830,y=y,wires=[]))

    # SECTION: Validate the graph before writing a reviewable import file.
    # Rebuilding this file is a local action, not a deployment to the lab server.
    assert not any(node['type'] in ('groov-io-write','mqtt in') for node in nodes)
    ids = {node['id'] for node in nodes}
    assert all(target in ids for node in nodes for group in node.get('wires',[]) for target in group)
    output = root/'team8conveyor4_sensors.json'
    output.write_text(json.dumps(nodes,indent=2)+'\n',encoding='utf-8')
    print('Created',output.name,'- read-only, disabled, not deployed')


if __name__ == '__main__':
    build()
