'use strict';
// Integration seam: replace makeDemo() with validated sensor/backend data.
// Demo views use synthetic records. Real timing and optional controls use separate APIs.
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,
c=>( {
  '&':'&amp;',
  '<':'&lt;',
  '>':'&gt;',
  '"':'&quot;',
  "'":'&#39;'
}
[c]));
// 1. EXAMPLE DATA — used only by the demo views.
function makeDemo() {
  return  {
    cameras:[ {
      id:'CAM-01',
      name:'Check-in entry',
      belt:'BELT-01'
    },
    {
      id:'CAM-02',
      name:'Transfer junction',
      belt:'BELT-02'
    },
    {
      id:'CAM-03',
      name:'Gate collection',
      belt:'BELT-03'
    }
    ],
    bags:[  {
      id:'BAG-0081',
      status:'Stuck',
      location:'Transfer junction',
      camera:'CAM-02',
      events:[['12:01:02',
      'Check-in entry',
      'Bag registered'],
      ['12:01:18',
      'BELT-01',
      'Moving toward transfer'],
      ['12:01:44',
      'Transfer junction',
      'Arrived at checkpoint'],
      ['12:01:49',
      'Transfer junction',
      'Stationary for 5 seconds; alert raised']]
    },
    {
      id:'BAG-0082',
      status:'Missing',
      location:'Check-in entry',
      camera:'CAM-01',
      events:[['12:01:10',
      'Check-in entry',
      'Bag registered'],
      ['12:01:25',
      'BELT-01',
      'Departed checkpoint'],
      ['12:02:10',
      'Transfer junction',
      'Expected arrival overdue; location unconfirmed']]
    },
    {
      id:'BAG-0083',
      status:'Moving',
      location:'Gate collection',
      camera:'CAM-03',
      events:[['12:00:42',
      'Check-in entry',
      'Bag registered'],
      ['12:01:08',
      'Transfer junction',
      'Checkpoint confirmed'],
      ['12:01:39',
      'Gate collection',
      'Checkpoint confirmed']]
    },
    {
      id:'BAG-0084',
      status:'Moving',
      location:'Check-in entry',
      camera:'CAM-01',
      events:[['12:02:02',
      'Check-in entry',
      'Bag registered'],
      ['12:02:07',
      'BELT-01',
      'Movement confirmed']]
    },
    {
      id:'BAG-0085',
      status:'Delivered',
      location:'Gate collection',
      camera:'CAM-03',
      events:[['11:59:50',
      'Check-in entry',
      'Bag registered'],
      ['12:00:20',
      'Transfer junction',
      'Checkpoint confirmed'],
      ['12:00:55',
      'Gate collection',
      'Collection confirmed']]
    }
    ],
    motors:[  {
      id:'M-01',
      belt:'BELT-01',
      location:'Check-in entry',
      status:'Running',
      speed:118,
      current:1.8,
      encoder:true,
      run:true,
      within:570,
      total:600,
      min:100,
      max:130,
      target:90,
      maintenance:false,
      speeds:[114,
      118,
      116,
      120,
      119,
      117,
      118,
      121,
      116,
      118,
      119,
      118],
      percentages:[96,
      96,
      95,
      95,
      95,
      95,
      95,
      95,
      95,
      95,
      95,
      95]
    },
    {
      id:'M-02',
      belt:'BELT-02',
      location:'Transfer junction',
      status:'Stalled',
      speed:0,
      current:4.2,
      encoder:false,
      run:true,
      within:390,
      total:600,
      min:100,
      max:130,
      target:90,
      maintenance:true,
      speeds:[118,
      115,
      108,
      92,
      104,
      85,
      72,
      100,
      40,
      0,
      0,
      0],
      percentages:[96,
      94,
      91,
      88,
      87,
      84,
      80,
      78,
      74,
      71,
      68,
      65]
    },
    {
      id:'M-03',
      belt:'BELT-03',
      location:'Gate collection',
      status:'Stopped',
      speed:0,
      current:0,
      encoder:false,
      run:false,
      within:475,
      total:500,
      min:100,
      max:130,
      target:90,
      maintenance:false,
      speeds:[120,
      119,
      121,
      117,
      120,
      118,
      119,
      120,
      0,
      0,
      0,
      0],
      percentages:[95,
      95,
      95,
      95,
      95,
      95,
      95,
      95,
      95,
      95,
      95,
      95]
    }
    ],
    alerts:[ {
      id:'INC-01',
      severity:'bad',
      title:'Bag stopped at transfer junction',
      detail:'BAG-0081 · BELT-02 · No movement for 5 seconds while run was requested.',
      bag:'BAG-0081',
      camera:'CAM-02',
      type:'Stuck bag',
      time:'12:01:49',
      ack:null
    },
    {
      id:'INC-02',
      severity:'warn',
      title:'Bag missed its next checkpoint',
      detail:'BAG-0082 · Last confirmed at check-in entry. Inspect the route; missing means overdue, not confirmed lost.',
      bag:'BAG-0082',
      camera:'CAM-01',
      type:'Missing bag',
      time:'12:02:10',
      ack:null
    },
    {
      id:'INC-03',
      severity:'warn',
      title:'Motor M-02 needs inspection',
      detail:'65% of running time within speed range; demo target is 90%. Possible jam: current present, encoder stationary, run requested.',
      camera:'CAM-02',
      type:'Motor maintenance',
      time:'12:02:12',
      ack:null
    }
    ]
  };
}
let data=makeDemo(),
selectedCamera='CAM-02',
activeTab='transit';
const media=new Map();
// 2. DEMO VIEW RENDERING — camera illustrations, histories and charts.
function badge(text) {
  let cls=['Stuck',
  'Stalled'].includes(text)?'bad':['Missing',
  'Inspection needed'].includes(text)?'warn':['Moving',
  'Running',
  'Delivered'].includes(text)?'good':'';
  return `<span class="badge ${cls}">${esc(text)}</span>`;
}
function tab(name) {
  activeTab=name;
  document.querySelectorAll('.demo-heading').forEach(el=>el.classList.toggle('hidden',
  name!=='overview'));
  document.querySelector('.banner').classList.toggle('hidden',
  name==='transit'||name==='hardware');
  for(const b of document.querySelectorAll('[data-tab]')) {
    const selected=b.dataset.tab===name;
    b.setAttribute('aria-selected',
    String(selected));
    b.tabIndex=selected?0:-1;
    $(b.dataset.tab).classList.toggle('hidden',
    !selected);
  }
}
function cameraMarkup(id) {
  const c=data.cameras.find(c=>c.id===id),
  m=media.get(id);
  let view;
  if(m) {
    view=m.type.startsWith('video/')?`<video src="${m.url}" controls muted loop playsinline>
</video>`:`<img src="${m.url}" alt="User-selected local preview for ${esc(c.name)}">`;
  }
  else {
    const stuck=id==='CAM-02';
    view=`<svg viewBox="0 0 700 330" role="img" aria-label="Synthetic illustration of ${esc(c.name)}; no live feed">
<defs>
<pattern id="rollers-${id}" width="30" height="100" patternUnits="userSpaceOnUse">
<rect width="28" height="100" rx="5" fill="#c9d5da"/>
</pattern>
</defs>
<rect x="0" y="0" width="700" height="330" fill="#e8eef0"/>
<path d="M0 105H700V245H0Z" fill="#aebfc7"/>
<rect x="0" y="117" width="700" height="115" fill="url(#rollers-${id})"/>
<path d="M45 280H220m-15-10 15 10-15 10" fill="none" stroke="#8299a5" stroke-width="4"/>
<g class="${stuck?'':'moving'}">
<rect x="270" y="139" width="100" height="73" rx="12" fill="${stuck?'#c45b4c':'#367c94'}"/>
<rect x="303" y="130" width="34" height="10" rx="4" fill="none" stroke="#29434e" stroke-width="4"/>
<rect x="255" y="121" width="130" height="106" rx="5" fill="none" stroke="${stuck?'#b8372c':'#1c7462'}" stroke-width="2" stroke-dasharray="6 4"/>
</g>
<text x="350" y="310" text-anchor="middle" font-family="system-ui" font-size="14" fill="#526b77">${stuck?'Stationary bag · synthetic example':'Moving bag · synthetic example'}</text>
</svg>`;
  }
  return `<div class="camera">${view}<span class="camera-label">${esc(c.id)} · ${m?'LOCAL MEDIA PREVIEW':'DEMO ILLUSTRATION'}</span>
</div>
<div class="row between">
<strong>${esc(c.name)}</strong>
<span class="muted">${esc(c.belt)}</span>
</div>`;
}
function renderCamera() {
  $('camera').innerHTML=cameraMarkup(selectedCamera);
  $('cameraButtons').innerHTML=data.cameras.map(c=>`<button aria-pressed="${c.id===selectedCamera}" data-camera="${c.id}">${esc(c.id)} · ${esc(c.name)}</button>`).join('');
  if($('cameraDialog').open)$('largeCamera').innerHTML=cameraMarkup(selectedCamera);
}
function bagTable(bags) {
  return `<table>
<thead>
<tr>
<th>Bag</th>
<th>Status</th>
<th>Last confirmed location</th>
<th>Last event</th>
<th>History</th>
</tr>
</thead>
<tbody>${bags.map(b=>`<tr>
<td>
<strong>${esc(b.id)}</strong>
</td>
<td>${badge(b.status)}</td>
<td>${esc(b.location)}</td>
<td>${esc(b.events.at(-1)[0])} (demo)</td>
<td>
<button data-bag="${b.id}">View timeline</button>
</td>
</tr>`).join('')||'<tr><td colspan="5">No matching bags.</td></tr>'}</tbody>
</table>`;
}
function renderBags() {
  const q=$('bagSearch').value.toLowerCase();
  $('bagTable').innerHTML=bagTable(data.bags.filter(b=>(b.id+' '+b.location).toLowerCase().includes(q)));
  $('recent').innerHTML=`<div class="table-wrap">${bagTable(data.bags.slice(0,3))}</div>`;
}
function chart(values,
min,
max,
limits,
label,
unit) {
  const x=i=>55+i*660/(values.length-1),
  y=v=>175-(v-min)/(max-min)*145;
  return `<svg class="chart" viewBox="0 0 760 215" role="img" aria-label="${esc(label)}">
<title>${esc(label)}. Demo samples: ${values.join(', ')} ${esc(unit)}. Limits: ${limits.map(l=>l.value).join(', ')}.</title>${[min,(min+max)/2,max].map(v=>`<line x1="55" y1="${y(v)}" x2="715" y2="${y(v)}" stroke="#e2e9ed"/>
<text x="8" y="${y(v)+4}">${v}</text>`).join('')}${limits.map(l=>`<line x1="55" y1="${y(l.value)}" x2="715" y2="${y(l.value)}" stroke="#b77717" stroke-dasharray="6 5"/>
<text x="58" y="${y(l.value)-6}">${esc(l.name)} ${l.value}${esc(unit)}</text>`).join('')}<polyline points="${values.map((v,i)=>`${x(i)},${y(v)}`).join(' ')}" fill="none" stroke="#207c9b" stroke-width="3"/>
<text x="55" y="204">Earlier demo samples</text>
<text x="660" y="204">Latest</text>
</svg>`;
}
function renderMotor() {
  const m=data.motors.find(m=>m.id===$('motorSelect').value),
  pct=Math.round(100*m.within/m.total);
  $('motorDetails').innerHTML=`<h3>${esc(m.id)} · ${esc(m.location)} · ${esc(m.belt)}</h3>
<div class="cards">
<div class="card">Current speed<div class="number">${m.speed}<small> rpm</small>
</div>
</div>
<div class="card">Motor current<div class="number">${m.current}<small> A</small>
</div>
</div>
<div class="card">Time within range<div class="number">${pct}%</div>
<small>${m.within}s / ${m.total}s running</small>
</div>
<div class="card">Maintenance<div style="margin-top:12px">${badge(m.maintenance?'Inspection needed':'No flag')}</div>
</div>
</div>
<p>
<strong>Speed history</strong> · Acceptable range ${m.min}–${m.max} rpm</p>${chart(m.speeds,0,160,[{value:m.min,name:'Minimum'},{value:m.max,name:'Maximum'}],'Motor speed history',' rpm')}<p>
<strong>Running time within range</strong> · Warning below ${m.target}%</p>${chart(m.percentages,0,100,[{value:m.target,name:'Target'}],'Percentage of running time within range','%')}<p class="legend">
<span class="dot">
</span>Demo readings · Dashed amber lines = configured limits</p>
<p>Run requested: <strong>${m.run?'Yes':'No'}</strong> · Encoder moving: <strong>${m.encoder?'Yes':'No'}</strong> · ${m.status==='Stopped'?'Intentional stop; excluded from running-time denominator.':m.status==='Stalled'?'Possible jam; operator inspection required.':'Within current speed range.'}</p>`;
}
function render() {
  const outstanding=data.alerts.filter(a=>!a.ack).length;
  $('summary').innerHTML=[['Bags tracked',
  data.bags.length,
  'All observed bags in this demo'],
  ['Bag exceptions',
  data.bags.filter(b=>['Stuck',
  'Missing'].includes(b.status)).length,
  '1 stuck · 1 overdue checkpoint'],
  ['Motors running',
  data.motors.filter(m=>m.status==='Running').length+' / '+data.motors.length,
  '1 stalled · 1 intentionally stopped'],
  ['Unacknowledged alerts',
  outstanding,
  'Acknowledgement does not clear an issue']].map(([l,
  n,
  s])=>`<div class="card">
<span class="muted">${l}</span>
<div class="number">${n}</div>
<small>${s}</small>
</div>`).join('');
  $('alertCount').textContent=data.alerts.length+' active';
  $('alerts').innerHTML=data.alerts.map(a=>`<article class="alert ${a.severity==='warn'?'warning':''}">
<h3>${esc(a.title)}</h3>
<p>${esc(a.detail)}</p>
<div class="row">
<button data-camera="${a.camera}" data-open-camera="true">View camera</button>${a.bag?`<button data-bag="${a.bag}">Bag history</button>`:''}<button data-ack="${a.id}" ${a.ack?'disabled':''}>${a.ack?'Acknowledged':'Acknowledge'}</button>
</div>${a.ack?`<small>Received at ${esc(a.ack)} · condition remains active</small>`:''}</article>`).join('');
  renderCamera();
  renderBags();
  $('motorTable').innerHTML=`<table>
<thead>
<tr>
<th>Motor / belt</th>
<th>Location</th>
<th>Status</th>
<th>Speed</th>
<th>Within range</th>
<th>Maintenance</th>
</tr>
</thead>
<tbody>${data.motors.map(m=>`<tr>
<td>
<button data-motor="${m.id}">${m.id} / ${m.belt}</button>
</td>
<td>${esc(m.location)}</td>
<td>${badge(m.status)}</td>
<td>${m.speed} rpm</td>
<td>${Math.round(m.within/m.total*100)}% / ${m.target}% target</td>
<td>${badge(m.maintenance?'Inspection needed':'No flag')}</td>
</tr>`).join('')}</tbody>
</table>`;
  renderMotor();
  $('reportBody').innerHTML=`<div class="cards">${[['Checkpoint events',data.bags.reduce((n,b)=>n+b.events.length,0)],['Delivered bags',data.bags.filter(b=>b.status==='Delivered').length],['Bag incidents',data.alerts.filter(a=>a.bag).length],['Maintenance flags',data.motors.filter(m=>m.maintenance).length]].map(([l,n])=>`<div class="card">${l}<div class="number">${n}</div>
</div>`).join('')}</div>
<p class="notice">These statistics describe a fixed demo session. They are not airport throughput, measured accuracy, or live sensor results. A missing-bag warning means an expected checkpoint was overdue.</p>`;
  $('incidentLog').innerHTML=`<table>
<thead>
<tr>
<th>Incident</th>
<th>Type</th>
<th>Raised (demo)</th>
<th>Acknowledgement</th>
<th>Resolution</th>
</tr>
</thead>
<tbody>${data.alerts.map(a=>`<tr>
<td>${a.id}</td>
<td>${a.type}</td>
<td>${a.time}</td>
<td>${esc(a.ack||'Not acknowledged')}</td>
<td>Active · not resolved</td>
</tr>`).join('')}</tbody>
</table>`;
}
function openBag(id) {
  const b=data.bags.find(b=>b.id===id);
  $('bagTitle').textContent=b.id+' · History';
  $('bagHistory').innerHTML=`${badge(b.status)}<p class="muted">Last confirmed: ${esc(b.location)} · Synthetic checkpoint log</p>
<ol class="timeline">${b.events.map(([t,l,d])=>`<li>
<strong>${esc(l)}</strong>
<div>${esc(d)}</div>
<small>${esc(t)} · demo session</small>
</li>`).join('')}</ol>
<button data-camera="${b.camera}" data-open-camera="true">View last confirmed camera</button>`;
  if(!$('bagDialog').open)$('bagDialog').showModal();
}
// 3. DEMO BUTTONS AND NAVIGATION
document.addEventListener('click',
e=> {
  const b=e.target.closest('button');
  if(!b)return;
  if(b.dataset.tab)tab(b.dataset.tab);
  if(b.dataset.go)tab(b.dataset.go);
  if(b.dataset.bag)openBag(b.dataset.bag);
  if(b.dataset.camera) {
    selectedCamera=b.dataset.camera;
    renderCamera();
    if(b.dataset.openCamera) {
      $('bagDialog').close();
      tab('overview');
      $('camera').scrollIntoView( {
        block:'center'
      });
    }
  }
  if(b.dataset.ack) {
    data.alerts.find(a=>a.id===b.dataset.ack).ack=new Date().toLocaleTimeString();
    render();
  }
  if(b.dataset.motor) {
    $('motorSelect').value=b.dataset.motor;
    renderMotor();
  }
});
document.querySelector('.tabs').addEventListener('keydown',
e=> {
  if(!['ArrowRight',
  'ArrowLeft',
  'Home',
  'End'].includes(e.key))return;
  const items=[...document.querySelectorAll('[data-tab]')];
  let i=items.indexOf(document.activeElement);
  if(i<0)return;
  e.preventDefault();
  i=e.key==='Home'?0:e.key==='End'?items.length-1:(i+(e.key==='ArrowRight'?1:-1)+items.length)%items.length;
  tab(items[i].dataset.tab);
  items[i].focus();
});
$('motorSelect').innerHTML=data.motors.map(m=>`<option value="${m.id}">${m.id} · ${m.belt}</option>`).join('');
$('motorSelect').value='M-02';
$('motorSelect').onchange=renderMotor;
$('bagSearch').oninput=renderBags;
$('closeBag').onclick=()=>$('bagDialog').close();
$('expand').onclick=()=> {
  $('largeCamera').innerHTML=cameraMarkup(selectedCamera);
  $('cameraDialog').showModal();
};
$('closeCamera').onclick=()=> {
  $('cameraDialog').close();
  $('largeCamera').innerHTML='';
};
$('cameraFile').onchange=e=> {
  const f=e.target.files[0];
  if(!f)return;
  if(!/^(image|video)\//.test(f.type)) {
    alert('Choose an image or video file.');
    return;
  }
  const old=media.get(selectedCamera);
  if(old)URL.revokeObjectURL(old.url);
  media.set(selectedCamera,
  {
    url:URL.createObjectURL(f),
    type:f.type
  });
  renderCamera();
  e.target.value='';
};
$('reset').onclick=()=> {
  data=makeDemo();
  for(const m of media.values())URL.revokeObjectURL(m.url);
  media.clear();
  selectedCamera='CAM-02';
  $('bagSearch').value='';
  render();
};
$('export').onclick=()=> {
  const report= {
    source:'synthetic',
    exported_at:new Date().toISOString(),
    notes:'Fixed demo data; no live sensors connected. Acknowledgement is not resolution.',
    ...data
  };
  const url=URL.createObjectURL(new Blob([JSON.stringify(report,
  null,
  2)],
  {
    type:'application/json'
  }));
  const a=document.createElement('a');
  a.href=url;
  a.download='team8system_report.json';
  a.click();
  setTimeout(()=>URL.revokeObjectURL(url),
  1000);
};
setInterval(()=> {
  $('clock').textContent=new Date().toLocaleTimeString();
},
1000);
tab('transit');
render();
// 4. OPTIONAL PHYSICAL CONVEYOR CONTROLS
// Optional controls: deleting this block leaves the demo dashboard functional.
let controlBusy=false,
controlToken='';
async function controlRequest(action) {
  if(controlBusy)return;
  controlBusy=true;
  $('controlRun').disabled=true;
  $('controlStop').disabled=true;
  try {
    if(!controlToken) {
      const session=await fetch('/api/conveyor/session',
      {
        cache:'no-store'
      });
      if(!session.ok)throw Error('Cannot obtain local control session');
      controlToken=(await session.json()).token;
    }
    const r=await fetch('/api/conveyor',
    {
      method:'POST',
      headers: {
        'Content-Type':'application/json',
        'X-Team8-Session':controlToken
      },
      body:JSON.stringify( {
        action
      }
      ),
      signal:AbortSignal.timeout(5000)
    });
    const s=await r.json();
    if(!r.ok)throw Error(s.message||'PLC request failed');
    $('controlState').textContent=s.enabled?'HARDWARE BRIDGE ENABLED':'CONTROLS DISABLED';
    $('controlState').className='badge '+(s.enabled?'warn':'');
    $('controlMessage').textContent=s.message;
    $('controlTelemetry').textContent=s.enabled?`Encoder speed: ${s.speed_cm_s==null?'unknown':Number(s.speed_cm_s).toFixed(2)+' cm/s'} · Encoder updates: ${s.encoder_fresh?'fresh':'stale / unavailable'} · Last command: ${s.last_command||'unknown'} · Requested output: ${s.output_requested==null?'unknown':s.output_requested+' V'} · Pulse remaining: ${s.pulse_remaining_ms||0} ms. This does not confirm physical motion.`:'No hardware request sent. Demo motor cards remain synthetic.';
    $('controlRun').disabled=!s.enabled;
    $('controlStop').disabled=!s.enabled;
  }
  catch(e) {
    $('controlState').textContent='CONNECTION UNKNOWN';
    $('controlMessage').textContent=e.message+'. A timed-out command may have executed. Verify the belt locally; no automatic retry.';
    $('controlTelemetry').textContent='Physical state unknown; encoder data unavailable.';
    $('controlStop').disabled=false;
  }
  finally {
    controlBusy=false;
  }
}
$('controlRun').onclick=()=> {
  if(confirm('Request a 3-second run on the physical conveyor? Confirm the belt is clear and you are at the assigned testbed.'))controlRequest('run');
};
$('controlStop').onclick=()=>controlRequest('stop');
$('controlRefresh').onclick=()=>controlRequest('status');
controlRequest('status');
// 5. REAL BARCODE TIMING — poll the Python server once per second.
let transitBusy=false,
transitInitialized=false;
const localTime=t=>t==null?'Not seen':new Date(t*1000).toLocaleTimeString();
async function transitRequest(path,
body) {
  if(body&&!controlToken) {
    const r=await fetch('/api/conveyor/session');
    if(!r.ok)throw Error('Session unavailable');
    controlToken=(await r.json()).token;
  }
  const r=await fetch('/api/transit'+path,
  {
    method:body?'POST':'GET',
    cache:'no-store',
    headers:body? {
      'Content-Type':'application/json',
      'X-Team8-Session':controlToken
    }
    : {
    },
    body:body?JSON.stringify(body):undefined,
    signal:AbortSignal.timeout(5000)
  });
  const s=await r.json();
  if(!r.ok)throw Error(s.message||'Timing request failed');
  return s;
}
async function refreshTransit() {
  if(transitBusy)return;
  transitBusy=true;
  try {
    const s=await transitRequest('');
    $('transitConnection').textContent='TIMING SERVER CONNECTED';
    $('transitConnection').className='badge good';
    if(!transitInitialized) {
      $('transitMin').value=s.standard.minimum;
      $('transitMax').value=s.standard.maximum;
      transitInitialized=true;
    }
    $('currentStandard').textContent='Standard for new journeys: '+s.standard.minimum+' to '+s.standard.maximum+' seconds';
    const completed=s.trips.filter(t=>t.arrived!==null),
    overdue=s.trips.filter(t=>t.status==='Overdue');
    $('transitSummary').innerHTML=[['Travelling',
    s.trips.filter(t=>t.arrived===null).length],
    ['Overdue arrivals',
    overdue.length],
    ['Completed',
    completed.length],
    ['Within standard',
    completed.filter(t=>t.status==='On time').length+' / '+completed.length]].map(([l,
    n])=>`<div class="card">${l}<div class="number">${n}</div>
<small>Latest 100 journeys</small>
</div>`).join('');
    $('transitTrips').innerHTML=`<table>
<thead>
<tr>
<th>Barcode / journey</th>
<th>Source</th>
<th>Seen at A</th>
<th>Seen at B</th>
<th>Elapsed</th>
<th>Standard</th>
<th>Result</th>
</tr>
</thead>
<tbody>${s.trips.map(t=>`<tr>
<td>
<strong>${esc(t.barcode)}</strong>
<br>
<small>Journey ${t.id}</small>
</td>
<td>${esc(t.source)}</td>
<td>${localTime(t.started)}</td>
<td>${localTime(t.arrived)}</td>
<td>${t.elapsed_seconds.toFixed(2)} s</td>
<td>${t.minimum}–${t.maximum} s</td>
<td>
<span class="badge ${['Late','Overdue','Clock error'].includes(t.status)?'bad':t.status==='On time'?'good':'warn'}">${esc(t.status)}</span>
</td>
</tr>`).join('')||'<tr><td colspan="7">No journeys yet. Scan a barcode at checkpoint A.</td></tr>'}</tbody>
</table>`;
    $('transitScans').innerHTML=`<table>
<thead>
<tr>
<th>Time</th>
<th>Barcode</th>
<th>Checkpoint</th>
<th>Source</th>
<th>Event</th>
</tr>
</thead>
<tbody>${s.scans.map(e=>`<tr>
<td>${localTime(e.at)}</td>
<td>${esc(e.barcode)}</td>
<td>${esc(e.checkpoint)}</td>
<td>${esc(e.source)}</td>
<td>${esc(e.outcome)}</td>
</tr>`).join('')}</tbody>
</table>`;
  }
  catch(e) {
    $('transitConnection').textContent='TIMING CONNECTION LOST';
    $('transitConnection').className='badge bad';
    $('transitMessage').textContent=e.message+' · Values shown may be stale.';
  }
  finally {
    transitBusy=false;
  }
}
$('transitStandard').onsubmit=async e=> {
  e.preventDefault();
  try {
    const s=await transitRequest('/standard',
    {
      minimum:Number($('transitMin').value),
      maximum:Number($('transitMax').value)
    });
    $('transitMessage').textContent=s.message;
    await refreshTransit();
  }
  catch(err) {
    $('transitMessage').textContent=err.message;
  }
};
$('transitManual').onsubmit=async e=> {
  e.preventDefault();
  const checkpoint=e.submitter?.value;
  if(!['A',
  'B'].includes(checkpoint))return;
  try {
    const s=await transitRequest('/scan',
    {
      barcode:$('transitBarcode').value,
      checkpoint,
      source:'manual',
      event_id:crypto.randomUUID()
    });
    $('transitMessage').textContent=s.message;
    await refreshTransit();
  }
  catch(err) {
    $('transitMessage').textContent=err.message;
  }
};
refreshTransit();
setInterval(()=> {
  if(activeTab==='transit')refreshTransit();
},
1000);
// Give every compact table field its column label. These labels are also visible
// when tables turn into cards on the Jetson screen. Only child changes are watched.
function labelTableFields()  {
  document.querySelectorAll('table').forEach(table =>  {
    const labels = Array.from(table.querySelectorAll('thead th'),
    cell => cell.textContent);
    table.querySelectorAll('tbody tr').forEach(row =>  {
      Array.from(row.cells).forEach((cell,
      index) =>  {
        cell.dataset.label = cell.colSpan > 1 ? '' : (labels[index] || '');
      });
    });
  });
}
labelTableFields();
new MutationObserver(labelTableFields).observe(document.querySelector('main'),
{
  childList: true,
  subtree: true
});
