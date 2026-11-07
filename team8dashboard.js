'use strict';

// Compatibility helpers for the older browser commonly installed on Jetson images.
// Request local API data with a timeout; use the older-browser path when AbortController is unavailable.
/* SECTION DETAIL:
 * Callers provide a local URL and ordinary fetch options. The helper adds a
 * five-second abort when supported and clears its timer on either success or
 * failure. It returns the response for the feature code to decode, preserving
 * compatibility with the older Jetson browser.
 */
function team8Fetch(url, options = {}) {
  if (typeof AbortController === 'undefined') return fetch(url, options);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  return fetch(url, Object.assign({}, options, {signal: controller.signal}))
    .then(response => { clearTimeout(timeout); return response; },
          error => { clearTimeout(timeout); throw error; });
}

// Give a manual scan a unique delivery ID so a retried request can be identified as the same event.
/* SECTION DETAIL:
 * Each manual submission needs a delivery identity independent of its barcode.
 * This uses browser randomness when available, with a timestamp/random
 * fallback for older browsers. The backend can reject a repeated delivery
 * without confusing it with a genuinely new journey.
 */
function team8EventID() {
  const random = new Uint32Array(4);
  if (window.crypto && window.crypto.getRandomValues) {
    window.crypto.getRandomValues(random);
    return Array.from(random, value => value.toString(16)).join('-');
  }
  return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
}

// Integration seam: replace makeDemo() with validated sensor/backend data.
// Demo views use synthetic records. Real timing and optional controls use separate APIs.
// Short DOM lookup helper: $("name") finds the element whose id is name.
/* SECTION DETAIL:
 * Most UI handlers need to find a named page element. This shorthand performs a normal
 * document lookup, keeping rendering code shorter while still using the HTML id as the
 * shared connection between page structure and behavior.
 */
const $=id=>document.getElementById(id);
// Escape untrusted labels before putting them inside HTML templates.
/* SECTION DETAIL:
 * Barcodes, locations and API messages are data, not HTML instructions. Escaping
 * special characters before template insertion prevents those values from being
 * interpreted as markup. Static templates remain separate from the dynamic text they
 * contain.
 */
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
// Return illustrative records only. These values must never be mistaken for the live monitor input.
/* SECTION DETAIL:
 * These records make the illustrative pages usable without hardware. They
 * include camera names, bag timelines, motor readings and example alerts;
 * changing them only changes the demo views. The live monitor and recorded
 * timing use separate server APIs.
 */
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
/* SECTION DETAIL:
 * The initial application state chooses a demo camera and the real monitoring landing
 * page. These browser variables describe presentation only; changing them does not
 * change PLC output or erase the persistent timing/sensor records.
 */
let data=makeDemo(),
selectedCamera='CAM-02',
activeTab='live';
const media=new Map();
// 2. DEMO VIEW RENDERING — camera illustrations, histories and charts.
// Choose a visual status style while keeping the status text visible for readers who cannot distinguish colours.
/* SECTION DETAIL:
 * Status text determines a readable colour/background pair. The text remains
 * visible so colour perception is not required to understand the result.
 * Returning a small HTML fragment lets several demo views share consistent
 * labels.
 */
function badge(text) {
  let cls=['Stuck',
  'Stalled'].includes(text)?'bad':['Missing',
  'Inspection needed'].includes(text)?'warn':['Moving',
  'Running',
  'Delivered'].includes(text)?'good':'';
  return `<span class="badge ${cls}">${esc(text)}</span>`;
}
// Show the selected panel, update accessible tab state, and hide unrelated demo headings.
/* SECTION DETAIL:
 * The selected name matches a panel id and a data-tab attribute. Other panels
 * are hidden, accessible selection/tab order is updated, and demo headings are
 * suppressed on real monitoring pages. Switching views does not start or reset
 * any backend measurement.
 */
function tab(name) {
  activeTab=name;
  document.querySelectorAll('.demo-heading').forEach(el=>el.classList.toggle('hidden',
  name!=='overview'));
  document.querySelector('.banner').classList.toggle('hidden',
  name==='live'||name==='transit'||name==='hardware');
  for(const b of document.querySelectorAll('[data-tab]')) {
    const selected=b.dataset.tab===name;
    b.setAttribute('aria-selected',
    String(selected));
    b.tabIndex=selected?0:-1;
    $(b.dataset.tab).classList.toggle('hidden',
    !selected);
  }
}
// Build a demo illustration or local media preview; this is separate from actual scanner JPEGs in team8live.js.
/* SECTION DETAIL:
 * A selected demo camera either displays a user-chosen local file or a
 * generated conveyor illustration. This function returns markup rather than
 * opening a device. The real scanner preview has its own authenticated image
 * route and freshness checks.
 */
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
// Refresh the selected demo camera and selector buttons, including its expanded view if open.
/* SECTION DETAIL:
 * The current camera id chooses both the main preview and active selector
 * styling. If its enlarged modal is open, that view is refreshed too.
 * Rebuilding this markup affects presentation only and does not identify bags
 * or command the belt.
 */
function renderCamera() {
  $('camera').innerHTML=cameraMarkup(selectedCamera);
  $('cameraButtons').innerHTML=data.cameras.map(c=>`<button aria-pressed="${c.id===selectedCamera}" data-camera="${c.id}">${esc(c.id)} · ${esc(c.name)}</button>`).join('');
  if($('cameraDialog').open)$('largeCamera').innerHTML=cameraMarkup(selectedCamera);
}
// Create the illustrative bag table; escape text before inserting it into HTML.
/* SECTION DETAIL:
 * The input is a list of illustrative bag objects. Each row shows status, last
 * location and an action to open its sample history; dynamic text is escaped
 * before insertion. Narrow-screen labels are attached later by the shared
 * table accessibility helper.
 */
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
<td>${esc(b.events[b.events.length-1][0])} (demo)</td>
<td>
<button data-bag="${b.id}">View timeline</button>
</td>
</tr>`).join('')||'<tr><td colspan="5">No matching bags.</td></tr>'}</tbody>
</table>`;
}
// Filter demo bags by ID/location and rebuild the demo list; real bag timelines use the live API.
/* SECTION DETAIL:
 * The search field is compared to demo bag ids and locations without changing
 * the underlying records. Matching rows and the short activity list are
 * rebuilt. This is separate from real recorded journey timelines opened from
 * live incidents.
 */
function renderBags() {
  const q=$('bagSearch').value.toLowerCase();
  $('bagTable').innerHTML=bagTable(data.bags.filter(b=>(b.id+' '+b.location).toLowerCase().includes(q)));
  $('recent').innerHTML=`<div class="table-wrap">${bagTable(data.bags.slice(0,3))}</div>`;
}
// Draw a simple SVG graph from demo values; horizontal dashed lines show the supplied limits.
/* SECTION DETAIL:
 * A supplied sample series is mapped into an SVG coordinate system. Configured
 * thresholds become horizontal dashed lines so the reader can compare values
 * visually. The resulting graph is a demo presentation, not evidence of
 * current sensor behavior.
 */
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
// Present the selected demo motor and its sample graphs; the percentage is within-time divided by running-time.
/* SECTION DETAIL:
 * The selected illustrative motor supplies speed, current, running-time totals
 * and sample histories. The displayed percentage comes from within-range
 * seconds divided by running seconds. Actual encoder cm/s and measured current
 * belong to the live panel instead.
 */
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
// Refresh all illustrative summary/alert/report views from the current demo state, not from MQTT.
/* SECTION DETAIL:
 * This rebuilds demo totals, alerts, tables and reports after a demo
 * interaction. Acknowledging one of these sample alerts changes only its local
 * demo object. Persistent real incidents are maintained by Python and rendered
 * by team8live.js.
 */
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
// Open an illustrative bag timeline; the live incident handler builds recorded journey timelines separately.
/* SECTION DETAIL:
 * A demo bag id selects its example event chain and last-confirmed camera
 * action. The shared modal displays that content until closed. The live
 * incident handler can reuse the modal, but fills it with recorded server
 * history and an explicit recorded-journey label.
 */
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
// One delegated click handler serves buttons created later when a view is redrawn.
/* SECTION DETAIL:
 * Buttons inside rendered tables may not exist when the page first loads.
 * Listening at document level lets new buttons participate without registering
 * handlers after every redraw. Data attributes identify the requested feature
 * and its record.
 */
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
// Arrow/Home/End keys move between tabs without requiring a mouse or touchscreen.
/* SECTION DETAIL:
 * Keyboard users can navigate the same views as touch users. Arrow keys cycle
 * the available tabs and Home/End select the edges; focus follows selection so
 * the highlighted control and displayed panel remain consistent.
 */
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
// Connect the demo controls to their render functions after all page elements exist.
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
// Local files are shown by browser-only object URLs; no media is uploaded by this demo control.
/* SECTION DETAIL:
 * This is an illustrative media-preview control rather than the scanner feed.
 * A browser object URL displays the selected file locally and the old URL is
 * released when replaced. No camera detection, upload or motor action is
 * triggered here.
 */
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
// Reset only the demo state; this does not erase real scan records, sensor history, or PLC state.
/* SECTION DETAIL:
 * Only illustrative state and local media previews are restored to their
 * original examples. Real SQLite history and PLC outputs are deliberately
 * outside this action, so testing the demo cannot erase or reset live
 * operation.
 */
$('reset').onclick=()=> {
  data=makeDemo();
  for(const m of media.values())URL.revokeObjectURL(m.url);
  media.clear();
  selectedCamera='CAM-02';
  $('bagSearch').value='';
  render();
};
// Export the illustrative session. The Live monitor has its own separate real-data export.
/* SECTION DETAIL:
 * The current illustrative objects are serialized into a downloaded JSON
 * report. This export is explicitly separate from the live monitoring report;
 * keeping them separate prevents example sensor values from being represented
 * as measurements.
 */
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
tab('live');
render();
// 4. OPTIONAL PHYSICAL CONVEYOR CONTROLS
// Optional controls: deleting this block leaves the demo dashboard functional.
let controlBusy=false,
controlToken='';
// Call the optional hardware bridge once. A timeout leaves outcome unknown, so Run is never automatically retried.
/* SECTION DETAIL:
 * Status and operator-requested actions go to the optional local control
 * adapter with a browser session token. Buttons are temporarily disabled while
 * a request is in flight. A rejected or timed-out command must not be mistaken
 * for confirmed physical movement or automatically retried.
 */
async function controlRequest(action) {
  if(controlBusy)return;
  controlBusy=true;
  $('controlRun').disabled=true;
  $('controlStop').disabled=true;
  try {
    if(!controlToken) {
      const session=await team8Fetch('/api/conveyor/session',
      {
        cache:'no-store'
      });
      if(!session.ok)throw Error('Cannot obtain local control session');
      controlToken=(await session.json()).token;
    }
    const r=await team8Fetch('/api/conveyor',
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
// Run requires an explicit operator click/confirmation; periodic refreshes request status only.
/* SECTION DETAIL:
 * A physical run requires an explicit operator confirmation and goes through
 * the separately enabled backend adapter. Merely opening the control tab or
 * refreshing status does not request movement. Server-side and PLC-side checks
 * still determine whether a request is permitted.
 */
$('controlRun').onclick=()=> {
  if(confirm('Request a 3-second run on the physical conveyor? Confirm the belt is clear and you are at the assigned testbed.'))controlRequest('run');
};
$('controlStop').onclick=()=>controlRequest('stop');
$('controlRefresh').onclick=()=>controlRequest('status');
controlRequest('status');
// 5. REAL BARCODE TIMING — poll the Python server once per second.
/* SECTION DETAIL:
 * These flags prevent overlapping timing polls and preserve edits to the settings form
 * after its first initialization. The browser has no independent journey clock; it
 * presents values owned by the Python tracker.
 */
let transitBusy=false,
transitInitialized=false;
const localTime=t=>t==null?'Not seen':new Date(t*1000).toLocaleTimeString();
// Read/update the real timing API; manual changes include a local browser session token.
/* SECTION DETAIL:
 * A missing body means read current timing state; a supplied body submits a
 * manual scan or limit update. Mutations include the local session token.
 * Backend validation remains authoritative even if the browser input fields
 * already restrict the values.
 */
async function transitRequest(path,
body) {
  if(body&&!controlToken) {
    const r=await team8Fetch('/api/conveyor/session');
    if(!r.ok)throw Error('Session unavailable');
    controlToken=(await r.json()).token;
  }
  const r=await team8Fetch('/api/transit'+path,
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

  });
  const s=await r.json();
  if(!r.ok)throw Error(s.message||'Timing request failed');
  return s;
}
// Poll recorded journeys and show server-calculated classifications; browser polling does not own the timer.
/* SECTION DETAIL:
 * The server supplies journeys, scans and each departure standard. This
 * formats them into summaries and rows, initializes settings only once, and
 * reports connection loss explicitly. The Python clock/supervisor keeps
 * running independently of how often this view is polled.
 */
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
// Send both limits together; the backend validates them and applies them only to new journeys.
/* SECTION DETAIL:
 * The form sends both acceptable-time boundaries together and reports the
 * backend response. Only future departures use the updated standard,
 * preserving the meaning of journeys already measured or still travelling.
 */
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
// Manual scans exercise timing without a camera and remain labelled manual in storage.
/* SECTION DETAIL:
 * The clicked submit button identifies A versus B. The barcode is sent with a
 * new event ID and manual source so these tests exercise the timer without
 * finishing a real camera/MQTT journey. Updated results are requested after
 * the server accepts the event.
 */
$('transitManual').onsubmit=async e=> {
  e.preventDefault();
  const checkpoint=(e.submitter || document.activeElement).value;
  if(!['A',
  'B'].includes(checkpoint))return;
  try {
    const s=await transitRequest('/scan',
    {
      barcode:$('transitBarcode').value,
      checkpoint,
      source:'manual',
      event_id:team8EventID()
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
// Copy column headings onto fields so narrow-screen card layouts remain understandable.
/* SECTION DETAIL:
 * On small screens, table rows become cards and would otherwise lose the
 * meaning supplied by their column headings. This copies each heading into a
 * cell data attribute used by CSS. The observer watches child changes only so
 * adding attributes does not trigger an endless update loop.
 */
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
