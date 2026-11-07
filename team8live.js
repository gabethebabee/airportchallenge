/* Live operations UI. No sample data is created here.
 * The Python monitor owns timing, incident persistence and health calculations.
 * Browser polling only presents those results; it never sends motor commands.
 */

/* SECTION DETAIL:
 * These variables hold browser-only session, polling and camera-preview state. Busy
 * flags prevent overlapping requests; the selected checkpoint and object URL identify
 * the current visual task. They do not replace persisted sensor or incident state on
 * the server.
 */
let liveSession = '';
let liveBusy = false;
let liveSettingsLoaded = false;
let selectedLiveCamera = 'A';
let currentPreviewURL = null;
let previewBusy = false;

// Read live monitor state or submit an authenticated acknowledgement/settings update to Python.
/* SECTION DETAIL:
 * The path selects monitor state, acknowledgements or limit updates. Changes
 * obtain a local session token, while read requests carry no mutation body.
 * Successful JSON is returned to the caller; HTTP errors become readable UI
 * messages instead of being silently treated as valid sensor data.
 */
async function monitorRequest(path = '', payload = null) {
  if (payload && !liveSession) {
    const response = await team8Fetch('/api/conveyor/session');
    if (!response.ok) throw new Error('Local session unavailable');
    liveSession = (await response.json()).token;
  }

  const response = await team8Fetch('/api/monitor' + path, {
    method: payload ? 'POST' : 'GET',
    cache: 'no-store',
    headers: payload ? {
      'Content-Type': 'application/json',
      'X-Team8-Session': liveSession
    } : {},
    body: payload ? JSON.stringify(payload) : undefined
  });

  const result = await response.json();
  if (!response.ok) throw new Error(result.message || 'Monitoring request failed');
  return result;
}

// Display missing measurements as Unknown instead of turning null into a misleading zero.
/* SECTION DETAIL:
 * Measurements can be a real number or null when unavailable. Numeric values
 * receive consistent precision and units, while null is displayed as Unknown.
 * This distinction prevents missing current/speed data from falsely looking
 * like a measured zero.
 */
function formatReading(value, unit, digits = 1) {
  return value == null ? 'Unknown' : Number(value).toFixed(digits) + ' ' + unit;
}

// Present measured/requested values, topic configuration and freshness without supplying substitute samples.
/* SECTION DETAIL:
 * The Python snapshot supplies broker state, sensor freshness, measurements
 * and combined jam evidence. This formats those values and camera availability
 * flags without inventing replacements. Connection state and measurement
 * freshness are displayed separately because a connected broker can still have
 * stale sensors.
 */
function renderLiveReadings(state) {
  $('mqttStatus').textContent = state.connected
    ? (state.fresh ? 'MQTT · FRESH' : 'MQTT · READINGS UNKNOWN')
    : 'MQTT · DISCONNECTED / OFF';
  $('mqttStatus').className = 'badge ' + (state.fresh ? 'good' : 'warn');

  const topics = state.checkpoint_topics || {};
  $('mqttDetail').textContent = state.station_id + ' · ' + state.connection_message
    + ' · A: ' + (topics.A || 'not configured')
    + ' · B: ' + (topics.B || 'not configured')
    + (state.last_error ? ' · Invalid telemetry: ' + state.last_error : '');

  const readings = [
    ['Belt state', state.state],
    ['Encoder speed', formatReading(state.speed_cm_s, 'cm/s')],
    ['Measured current', formatReading(state.current_a, 'A')],
    ['Observed within range', formatReading(state.percent_within, '%')]
  ];
  $('liveReadings').innerHTML = readings.map(([label, value]) => `
    <div class="card">
      <span class="muted">${esc(label)}</span>
      <div class="number" style="font-size:25px">${esc(value)}</div>
    </div>
  `).join('');

  $('jamEvidence').textContent = state.high_current_evidence
    ? 'Possible jam: a bag is overdue, run is requested, the encoder is near zero, and measured current is high. Inspect locally.'
    : state.possible_jam
      ? 'Possible jam: a bag is overdue and the belt appears stalled while run is requested. Inspect the route and camera.'
      : 'A late bag alone does not confirm a jam. Unknown sensor data is not treated as normal operation.';

  $('liveCameraStatus').textContent = ['A', 'B'].map(point =>
    'Camera ' + point + ': ' + (state.cameras[point] ? 'preview available' : 'unavailable / stale')
  ).join(' · ');
}

// Show every active episode plus recovery history; acknowledgement changes receipt status, not the condition.
/* SECTION DETAIL:
 * The snapshot contains unresolved and recently recovered episodes with
 * independent acknowledgement timestamps. Active cards provide receipt and
 * camera/history actions; the history table preserves earlier recovery. A
 * button acknowledges an episode but cannot clear its physical or timing
 * condition.
 */
function renderLiveIncidents(incidents) {
  const active = incidents.filter(item => item.resolved == null);
  $('liveAlerts').innerHTML = active.length ? active.map(item => `
    <article class="alert ${item.kind === 'sensor' ? 'warning' : ''}">
      <h3>${esc(item.title)}</h3>
      <p>${esc(item.barcode || item.station_id || '')}
        ${item.source ? ' · ' + esc(item.source) : ''}
        · Raised ${localTime(item.raised)}</p>
      <p>${esc(item.detail)}</p>
      <div class="row">
        <button data-live-camera="${esc(item.checkpoint)}">View last checkpoint</button>
        ${item.kind === 'bag' ? `<button data-live-trip="${item.id}">Bag timeline</button>` : ''}
        <button data-live-ack="${item.id}" data-live-kind="${item.kind}"
          ${item.acknowledged == null ? '' : 'disabled'}>
          ${item.acknowledged == null ? 'Acknowledge' : 'Acknowledged — still active'}
        </button>
      </div>
    </article>
  `).join('') : '<p class="notice">No active incidents recorded. Check input freshness before assuming the system is healthy.</p>';

  $('liveIncidentHistory').innerHTML = `
    <table>
      <thead><tr><th>Incident</th><th>Bag / station</th><th>Raised</th><th>Acknowledged</th><th>Recovered</th></tr></thead>
      <tbody>${incidents.map(item => `
        <tr>
          <td>${esc(item.title)}</td>
          <td>${esc(item.barcode || item.station_id)} ${esc(item.source || '')}</td>
          <td>${localTime(item.raised)}</td>
          <td>${item.acknowledged == null ? 'No' : localTime(item.acknowledged)}</td>
          <td>${item.resolved == null ? 'Active' : localTime(item.resolved)}</td>
        </tr>
      `).join('')}</tbody>
    </table>`;
}

// Display server-calculated durations/coverage; stopped and unknown time are excluded from the running percentage.
/* SECTION DETAIL:
 * All time integration has already been performed on the server. This presents
 * within-range/running seconds, outside-time thresholds, unknown coverage and
 * accumulated service totals, then draws received speed history. It does not
 * count browser refreshes as operating time.
 */
function renderLiveHealth(state) {
  const limits = state.limits;
  const percentage = state.percent_within;
  const percentLabel = percentage == null ? 'No valid running-time data' : percentage.toFixed(1) + '% within range';
  $('liveHealth').innerHTML = `
    <p><strong>${esc(percentLabel)}</strong> ·
      ${limits.speed_min_cm_s}–${limits.speed_max_cm_s} cm/s acceptable range</p>
    ${percentage == null ? '' : `<progress class="health-meter" max="100" value="${percentage}" aria-label="Percentage of valid running time within speed range"></progress>`}
    <p>${state.within_seconds.toFixed(1)} s within range /
       ${state.running_seconds.toFixed(1)} s observed running.</p>
    <p>Outside range: <strong>${state.outside_seconds.toFixed(1)} s</strong> /
       ${limits.outside_limit_seconds} s allowed in the last ${limits.window_seconds} s.</p>
    <p>Stopped: ${state.stopped_seconds.toFixed(1)} s · Unknown / not observed:
       ${state.unknown_seconds.toFixed(1)} s. Intentional stops and unknown time are excluded from the running percentage.</p>
    <p class="badge ${state.health_flag ? 'bad' : 'warn'}">
      ${state.health_flag ? 'Inspection threshold exceeded' : state.sufficient_data ? 'Threshold not exceeded in observed data' : 'Collecting data — insufficient running time'}
    </p>
    <p>Recorded runtime: ${state.runtime_hours.toFixed(3)} hours ·
       Recorded belt travel: ${state.distance_km.toFixed(4)} km.
       These totals exclude unobserved intervals and are not remaining-life estimates.</p>`;

  $('liveSpeedChart').innerHTML = speedHistoryChart(state.history, limits, state.fresh);
}

// Plot measured speed with acceptable limits, breaking the line over missing readings and long gaps.
/* SECTION DETAIL:
 * Received sample times and speeds are projected into an SVG plot with
 * horizontal calibrated limits. Null measurements and long gaps split the line
 * so interpolation cannot hide missing evidence. A stale feed keeps an
 * explicitly historical graph rather than claiming the last point is current.
 */
function speedHistoryChart(history, limits, fresh) {
  if (!history.length) return '<p class="notice">Waiting for MQTT encoder readings. No sample readings are substituted.</p>';
  const ceiling = Math.max(1, limits.speed_max_cm_s * 1.2, ...history.map(item => item.speed || 0));
  const x = index => 55 + index * 660 / Math.max(1, history.length - 1);
  const y = speed => 175 - speed / ceiling * 140;
  const segments = [];
  let points = [];
  history.forEach((item, index) => {
    if (index && item.received - history[index - 1].received > limits.stale_seconds) {
      if (points.length) segments.push(points.join(' '));
      points = [];
    }
    if (item.speed == null) {
      if (points.length) segments.push(points.join(' '));
      points = [];
    } else {
      points.push(x(index) + ',' + y(item.speed));
    }
  });
  if (points.length) segments.push(points.join(' '));

  return `
    <p><strong>Encoder speed history</strong> · ${fresh ? 'Latest received samples' : 'Historical — live readings unavailable'}</p>
    <svg class="live-chart" viewBox="0 0 760 215" role="img" aria-label="Measured belt speed with configured upper and lower limits">
      <title>Measured belt speed in centimetres per second. Gaps indicate unavailable data.</title>
      ${[limits.speed_min_cm_s, limits.speed_max_cm_s].map(limit => `
        <line x1="55" x2="715" y1="${y(limit)}" y2="${y(limit)}" stroke="#9b6608" stroke-dasharray="6 5"/>
        <text x="55" y="${y(limit) - 6}">Limit ${limit} cm/s</text>
      `).join('')}
      ${segments.map(segment => `<polyline points="${segment}" fill="none" stroke="#167b9b" stroke-width="3"/>`).join('')}
      <text x="55" y="204">${localTime(history[0].received)}</text>
      <text x="620" y="204">${localTime(history[history.length - 1].received)}</text>
    </svg>`;
}

// Keep one poll in flight; on failure remove current readings and mark previews unavailable.
/* SECTION DETAIL:
 * Only one request is permitted in flight at a time. A successful response
 * refreshes readings, incidents, health and any open preview; settings are
 * initialized without overwriting an operator edit every second. A failure
 * removes current readings and warns that prior history may be stale.
 */
async function refreshLiveMonitor() {
  if (liveBusy) return;
  liveBusy = true;
  try {
    const state = await monitorRequest();
    renderLiveReadings(state);
    renderLiveIncidents(state.incidents);
    renderLiveHealth(state);

    if (!liveSettingsLoaded) {
      Object.entries(state.limits).forEach(([name, value]) => {
        const input = $('liveLimits').elements.namedItem(name);
        if (input) input.value = value == null ? '' : value;
      });
      liveSettingsLoaded = true;
    }
    if ($('liveCameraDialog').open) await updateLivePreview(state.cameras);
  } catch (error) {
    $('mqttStatus').textContent = 'MONITOR CONNECTION LOST';
    $('mqttStatus').className = 'badge bad';
    $('mqttDetail').textContent = error.message + '. Previous readings may be stale.';
    $('liveReadings').innerHTML = '<p class="notice">Live measurements unknown until the connection recovers.</p>';
    if ($('liveCameraDialog').open) hideLivePreview('Preview unknown — monitor connection lost.');
  } finally {
    liveBusy = false;
  }
}

// Clear the visible image and release its browser object URL so an old frame cannot keep looking current.
/* SECTION DETAIL:
 * The image source and browser object URL are both cleared when the frame is
 * unavailable or the modal closes. Hiding an old image is deliberate: leaving
 * it on screen could look like fresh visual confirmation of a bag or belt
 * state.
 */
function hideLivePreview(message) {
  $('livePreviewStatus').textContent = message;
  $('livePreview').classList.add('hidden');
  $('livePreview').removeAttribute('src');
  if (currentPreviewURL) URL.revokeObjectURL(currentPreviewURL);
  currentPreviewURL = null;
}

// Fetch a fresh JPEG only while the selected camera dialog is open; discard responses for a camera switched away.
/* SECTION DETAIL:
 * The monitor first tells us whether the selected checkpoint has a recent
 * frame. A separate image request downloads that JPEG only when its modal is
 * open. If the operator changes cameras while waiting, the old response is
 * discarded instead of appearing under the new camera title.
 */
async function updateLivePreview(cameras) {
  if (previewBusy) return;
  if (!cameras[selectedLiveCamera]) {
    hideLivePreview('Camera unavailable or older than 4 seconds. Start the scanner preview for this checkpoint.');
    return;
  }
  previewBusy = true;
  const checkpoint = selectedLiveCamera;
  try {
    const response = await team8Fetch('/api/camera/' + checkpoint + '?t=' + Date.now(), {cache: 'no-store'});
    if (!response.ok) throw new Error('Preview unavailable');
    const blob = await response.blob();
    if (!$('liveCameraDialog').open || selectedLiveCamera !== checkpoint) return;
    if (currentPreviewURL) URL.revokeObjectURL(currentPreviewURL);
    currentPreviewURL = URL.createObjectURL(blob);
    $('livePreview').src = currentPreviewURL;
    $('livePreview').classList.remove('hidden');
    $('livePreviewStatus').textContent = 'Recent scanner frame · refreshes approximately once per second';
  } catch (error) {
    hideLivePreview(error.message + ' — no current image.');
  } finally {
    previewBusy = false;
  }
}

// One delegated click handler serves buttons created later when a view is redrawn.
/* SECTION DETAIL:
 * Buttons inside rendered tables may not exist when the page first loads.
 * Listening at document level lets new buttons participate without registering
 * handlers after every redraw. Data attributes identify the requested feature
 * and its record.
 */
document.addEventListener('click', async event => {
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.liveCamera) {
    selectedLiveCamera = button.dataset.liveCamera;
    $('liveCameraTitle').textContent = 'Checkpoint ' + selectedLiveCamera + ' · scanner preview';
    hideLivePreview('Checking camera preview.');
    if (!$('liveCameraDialog').open) $('liveCameraDialog').showModal();
    await refreshLiveMonitor();
  }
  if (button.dataset.liveAck) {
    try {
      const result = await monitorRequest('/ack', {
        kind: button.dataset.liveKind,
        id: Number(button.dataset.liveAck)
      });
      $('liveMessage').textContent = result.message;
      await refreshLiveMonitor();
    } catch (error) {
      $('liveMessage').textContent = error.message;
    }
  }
  if (button.dataset.liveTrip) {
    try {
      const response = await team8Fetch('/api/transit/trip/' + button.dataset.liveTrip, {cache: 'no-store'});
      const history = await response.json();
      if (!response.ok) throw new Error(history.message);
      $('bagTitle').textContent = history.trip.barcode + ' · recorded journey';
      $('bagHistory').innerHTML = `
        <p>Source: ${esc(history.trip.source)} · Journey ${history.trip.id}</p>
        <p>Standard at departure: ${history.trip.minimum}–${history.trip.maximum} seconds</p>
        <ol class="timeline">${history.scans.map(scan => `
          <li><strong>Checkpoint ${esc(scan.checkpoint)}</strong>
            <p>${esc(scan.outcome)}</p><small>${localTime(scan.at)}</small></li>
        `).join('')}</ol>`;
      if (!$('bagDialog').open) $('bagDialog').showModal();
    } catch (error) {
      $('liveMessage').textContent = error.message;
    }
  }
});

// Both the Close button and Escape release the displayed preview through the dialog close event.
/* SECTION DETAIL:
 * Closing the modal, pressing Escape or failing image decode all lead to preview
 * cleanup. This releases the temporary object URL and clears visual evidence, while
 * camera acquisition and stored journey/incident records continue independently.
 */
$('closeLiveCamera').onclick = () => $('liveCameraDialog').close();
$('liveCameraDialog').addEventListener('close', () => hideLivePreview('Preview closed.'));
$('livePreview').onerror = () => hideLivePreview('Image could not be decoded. Preview unavailable.');

// Optional empty thresholds become null; all entered values are validated again by the server.
/* SECTION DETAIL:
 * Every named health field is collected as a number, with optional empty
 * values becoming null. The server validates the entire candidate before
 * accepting any change. These limits apply to this process session; the launch
 * configuration remains a separate file.
 */
$('liveLimits').onsubmit = async event => {
  event.preventDefault();
  const values = {};
  Array.from($('liveLimits').elements).filter(input => input.name).forEach(input => {
    values[input.name] = input.value === '' ? null : Number(input.value);
  });
  try {
    const result = await monitorRequest('/limits', values);
    $('liveMessage').textContent = result.message;
    await refreshLiveMonitor();
  } catch (error) {
    $('liveMessage').textContent = error.message;
  }
};

// Fetch monitoring and timing together for a report; no sample/demo records are included.
/* SECTION DETAIL:
 * Fresh monitor and timing snapshots are fetched before building the
 * downloadable report. The report includes recorded evidence and incident
 * history rather than the demo objects. Fetch errors are shown instead of
 * producing a misleading partial success message.
 */
$('liveExport').onclick = async () => {
  try {
    const monitor = await monitorRequest();
    const transit = await transitRequest('');
    const report = {exported_at: new Date().toISOString(), monitor, transit};
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'team8monitor_report.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    $('liveMessage').textContent = error.message;
  }
};

refreshLiveMonitor();
// Polling presents state only; the Python supervisor continues evaluating even if this tab closes.
setInterval(refreshLiveMonitor, 1000);
