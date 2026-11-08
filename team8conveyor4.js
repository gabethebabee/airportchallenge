'use strict';

/* SECTION: Browser helpers format values and request server-owned state.
 * No average, timer or total is calculated from browser refresh counts. The
 * monotonic Python clock continues running when this page is hidden or closed.
 */
const c4 = id => document.getElementById(id);
const c4escape = value => String(value).replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[character]));
const c4number = (value, unit) => value == null ? 'Unknown' : Number(value).toFixed(2) + ' ' + unit;
let c4busy = false;
let c4latest = null;
let c4frameURL = null;
let c4frameBusy = false;
let c4tagSettingsLoaded = false;

/* SECTION: A hung request must not leave old values looking indefinitely live.
 * Race local fetch against a five-second deadline and abort when the browser
 * supports it. The error path clears speed/current and marks FLAG unknown.
 */
function c4request(url, options = {}) {
  const controller = typeof AbortController === 'undefined' ? null : new AbortController();
  let timer;
  const timeout = new Promise((resolve, reject) => {
    timer = setTimeout(() => {
      if (controller) controller.abort();
      reject(new Error('Dashboard request timed out'));
    }, 5000);
  });
  const requestOptions = Object.assign({}, options, controller ? {signal: controller.signal} : {});
  return Promise.race([fetch(url, requestOptions), timeout]).then(
    response => { clearTimeout(timer); return response; },
    error => { clearTimeout(timer); throw error; }
  );
}

/* SECTION: Runtime is displayed as hours:minutes:seconds, not wall-clock time.
 * Python integrates valid moving intervals; formatting never advances the total
 * while the browser is open or estimates unobserved downtime.
 */
function c4duration(seconds) {
  seconds = Math.max(0, Math.floor(seconds));
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
    .map(value => String(value).padStart(2, '0')).join(':');
}

/* SECTION: Show the six metrics, with the true/false convention explicit.
 * Missing data clears live readings, while cumulative totals remain historical.
 * Warm-up and sensor loss use false conservatively, labelled as unverified rather
 * than being counted as newly confirmed abnormal episodes.
 */
function renderConveyor4(state) {
  c4latest = state;
  const config = state.config;
  c4('c4connection').textContent = state.connected ? 'MQTT CONNECTED' : 'MQTT DISCONNECTED';
  c4('c4connection').className = 'badge ' + (state.connected ? 'good' : 'warn');
  c4('c4speed').textContent = c4number(state.metrics.speed.value, 'cm/s');
  c4('c4current').textContent = c4number(state.metrics.current.value, 'A');
  c4('c4flag').textContent = state.flag ? 'TRUE' : 'FALSE';
  c4('c4flag').className = 'number ' + (state.flag ? 'good' : state.state === 'Abnormal' ? 'bad' : 'warn');
  c4('c4state').textContent = state.state + (state.state === 'Unknown' || state.state === 'Calibrating' ? ' · normal unverified' : '');
  c4('c4distance').textContent = c4number(state.distance_m, 'm');
  c4('c4runtime').textContent = c4duration(state.runtime_seconds);
  c4('c4jams').textContent = state.jam_count;
  c4('c4sharedTimer').textContent = 'Either reading outside range: ' + state.deviation_seconds.toFixed(1)
    + ' / ' + config.deviation_seconds + ' seconds continuously';

  c4('c4message').textContent = !config.current_topic
    ? 'Actual current topic is not configured. The supplied flow publishes voltage; current remains unknown and FLAG cannot be verified true.'
    : state.state === 'Abnormal'
      ? 'Abnormal: a speed/current deviation persisted for more than ' + config.deviation_seconds + ' seconds. Inspect the conveyor.'
      : state.state === 'Calibrating'
        ? 'Learning the normal averages from ' + config.minimum_samples + ' valid readings per channel. Keep the belt in its intended steady operating condition.'
        : state.state === 'Unknown'
          ? 'Waiting for fresh speed and current. Missing readings are not counted as normal operation.'
          : 'Normal. Either reading staying more than ' + (config.deviation_fraction * 100).toFixed(0) + '% outside its average for over ' + config.deviation_seconds + ' seconds will set FLAG false.';

  c4('c4timers').innerHTML = ['speed', 'current'].map(name => {
    const metric = state.metrics[name];
    const unit = name === 'speed' ? 'cm/s' : 'A';
    const label = name === 'speed' ? 'Belt speed' : 'Motor current';
    const status = metric.abnormal ? 'ABNORMAL' : metric.value == null ? 'UNKNOWN' : !metric.ready ? 'CALIBRATING' : metric.timing ? 'DEVIATION TIMING' : 'WITHIN RANGE';
    return `<article class="c4timer">
      <strong>${label}</strong><span class="badge ${metric.abnormal ? 'bad' : metric.timing ? 'warn' : ''}">${status}</span>
      <p>Average: ${c4number(metric.average, unit)} · Band: ${c4number(metric.lower, unit)} to ${c4number(metric.upper, unit)}</p>
      <p>Deviation timer: <strong>${metric.deviation_seconds.toFixed(1)} / ${config.deviation_seconds} s</strong>
        · Baseline samples: ${metric.samples}${metric.timing || metric.abnormal ? ' · reference frozen' : ''}</p>
    </article>`;
  }).join('');
  c4('c4rules').textContent = 'Averages use up to ' + config.baseline_samples + ' accepted normal samples. The shared timer continues while either fresh reading is outside its band; channel timers identify the cause. Missing evidence resets unconfirmed timers. Recalibrating resets alarms/averages, preserving totals and episode count.';
  c4('c4charts').innerHTML = ['speed', 'current'].map(name => c4chart(name, state)).join('');
  c4('c4setup').innerHTML = ['broker', 'speed_topic', 'current_topic', 'voltage_topic', 'flag_topic', 'status_topic']
    .map(key => `<p><strong>${c4escape(key)}:</strong> ${c4escape(config[key] || 'Not configured')}</p>`).join('');
  c4('c4voltage').textContent = 'Separate voltage readback: ' + c4number(state.metrics.voltage.value, 'V') + '. This is not motor current.';
  c4('c4publish').textContent = state.publish_error || 'FLAG is queued on changes as retained JSON true/false; STATUS carries the reason/state. ' + state.connection_message;
  renderAprilTagCamera(state.vision);
}

/* SECTION: The camera/tags arrive via MQTT on the Python subscriber, not by
 * opening the Jetson camera from this browser. Only recent tag metadata is shown
 * as current; recorded journeys/alerts remain available after a feed outage.
 */
function renderAprilTagCamera(vision) {
  if (!vision) {
    c4('c4cameraState').textContent = 'NOT STARTED';
    c4('c4cameraInfo').textContent = 'Camera subscriber unavailable. Start the conveyor 4 dashboard and Jetson publisher.';
    clearC4Frame();
    return;
  }
  c4('c4cameraState').textContent = vision.fresh ? 'PREVIEW AVAILABLE' : 'UNAVAILABLE / STALE';
  c4('c4cameraState').className = 'badge ' + (vision.fresh ? 'good' : 'warn');
  c4('c4cameraInfo').textContent = vision.publisher_status
    + (vision.fresh ? ' · latest preview received ' + vision.age_seconds.toFixed(1) + ' s ago' : ' · no recent image')
    + (vision.last_error ? ' · ' + vision.last_error : '');
  c4('c4tags').innerHTML = vision.tags_fresh
    ? vision.tags.map(tag => `<span class="badge">${c4escape(tag.family)} · ID ${tag.tag_id} · ${c4escape(tag.checkpoint || 'GAP')}</span>`).join('') || '<p>No AprilTags visible in the latest detection.</p>'
    : '<p>AprilTag observations unavailable or stale.</p>';
  c4('c4tagTrips').innerHTML = vision.trips.slice(0, 12).map(trip => `
    <article class="c4tagTrip">
      <strong>${c4escape(trip.barcode.replace('apriltag:', ''))}</strong>
      <span class="badge ${['Late', 'Overdue'].includes(trip.status) ? 'bad' : trip.status === 'On time' ? 'good' : 'warn'}">${c4escape(trip.status)}</span>
      <p>A → B: ${trip.elapsed_seconds.toFixed(2)} s · Standard ${trip.minimum}–${trip.maximum} s · Journey ${trip.id}</p>
    </article>`).join('') || '<p>No tag journeys yet. Present a tag at A, then the same tag at B.</p>';
  c4('c4tagAlerts').innerHTML = vision.incidents.filter(item => item.resolved == null).map(item => `
    <article class="alert"><strong>AprilTag overdue: ${c4escape(item.barcode.replace('apriltag:', ''))}</strong>
      <p>Last confirmed at A. Check the camera, route and tag reader; this does not prove a jam.</p>
      <button data-c4-tag-ack="${item.id}" ${item.acknowledged == null ? '' : 'disabled'}>${item.acknowledged == null ? 'Acknowledge' : 'Acknowledged — still active'}</button>
    </article>`).join('');
  if (!c4tagSettingsLoaded) {
    c4('c4tagMin').value = vision.standard.minimum;
    c4('c4tagMax').value = vision.standard.maximum;
    c4tagSettingsLoaded = true;
  }
  if (!vision.fresh || !c4('c4visionPanel').open) clearC4Frame();
  else refreshC4Frame();
}

/* SECTION: JPEGs are fetched only while the camera panel is open. Closing it or
 * losing freshness clears the image and its temporary URL, so an old screenshot
 * cannot be mistaken for a current view. No received image is saved to disk.
 */
function clearC4Frame() {
  c4('c4cameraImage').classList.add('hidden');
  c4('c4cameraImage').removeAttribute('src');
  if (c4frameURL) URL.revokeObjectURL(c4frameURL);
  c4frameURL = null;
}

async function refreshC4Frame() {
  if (c4frameBusy) return;
  c4frameBusy = true;
  try {
    const response = await c4request('/api/conveyor4/camera?t=' + Date.now(), {cache: 'no-store'});
    if (!response.ok) throw new Error('MQTT camera frame unavailable');
    const blob = await response.blob();
    if (!c4('c4visionPanel').open || !c4latest || !c4latest.vision || !c4latest.vision.fresh) return;
    if (c4frameURL) URL.revokeObjectURL(c4frameURL);
    c4frameURL = URL.createObjectURL(blob);
    c4('c4cameraImage').src = c4frameURL;
    c4('c4cameraImage').classList.remove('hidden');
  } catch (error) {
    clearC4Frame();
    c4('c4cameraInfo').textContent = error.message + ' · preview is not current';
  } finally { c4frameBusy = false; }
}

/* SECTION: Historical plots show real received readings and the current band.
 * Lines break over a freshness gap. All readings remain in SQLite; this compact
 * view/export uses the latest records instead of pretending to be the whole log.
 */
function c4chart(name, state) {
  const samples = state.history.filter(item => item.channel === name).slice(-60);
  if (!samples.length) return '<p>No recorded ' + name + ' samples yet.</p>';
  const metric = state.metrics[name];
  const maximum = Math.max(1, metric.upper || 0, ...samples.map(item => item.value)) * 1.1;
  const x = index => 55 + index * 640 / Math.max(1, samples.length - 1);
  const y = value => 160 - value * 130 / maximum;
  const segments = [];
  let segment = [];
  samples.forEach((sample, index) => {
    if (index && sample.at - samples[index - 1].at > state.config.stale_seconds) {
      segments.push(segment.join(' ')); segment = [];
    }
    segment.push(x(index) + ',' + y(sample.value));
  });
  if (segment.length) segments.push(segment.join(' '));
  return `<h3>${name === 'speed' ? 'Speed (cm/s)' : 'Current (A)'} · recorded history</h3>
    <svg class="c4plot" viewBox="0 0 740 195" role="img" aria-label="Recorded ${name} values; dashed lines show the current baseline band">
      ${[metric.lower, metric.upper].filter(value => value != null).map(value => `<line x1="55" x2="695" y1="${y(value)}" y2="${y(value)}" stroke="#a46a00" stroke-dasharray="6 4"/><text x="5" y="${y(value) + 4}">${value.toFixed(2)}</text>`).join('')}
      ${segments.map(points => `<polyline points="${points}" fill="none" stroke="#157995" stroke-width="3"/>`).join('')}
      <text x="55" y="190">Earlier</text><text x="640" y="190">Latest</text>
    </svg>`;
}

/* SECTION: Poll presentation only; errors immediately clear current measurements.
 * Persisted totals are not reset by a reload, and no browser request in this file
 * starts/stops hardware. A stalled page cannot affect server-side 10-second logic.
 */
async function refreshConveyor4() {
  if (c4busy) return;
  c4busy = true;
  try {
    const response = await c4request('/api/conveyor4', {cache: 'no-store'});
    const state = await response.json();
    if (!response.ok) throw new Error(state.message || 'Monitor unavailable');
    renderConveyor4(state);
  } catch (error) {
    c4('c4connection').textContent = 'DASHBOARD CONNECTION LOST';
    c4('c4connection').className = 'badge bad';
    c4('c4speed').textContent = 'Unknown';
    c4('c4current').textContent = 'Unknown';
    c4('c4flag').textContent = 'UNKNOWN';
    c4('c4flag').className = 'number warn';
    c4('c4state').textContent = 'Cannot confirm published FLAG';
    c4('c4message').textContent = error.message + '. Last totals shown are historical.';
    clearC4Frame();
    c4('c4cameraState').textContent = 'DASHBOARD CONNECTION LOST';
  } finally { c4busy = false; }
}

/* SECTION: Recalibration is explicit and keeps accumulated operating history.
 * The operator confirms that current conditions represent the intended normal
 * state. Fresh samples must warm up again before a verified true FLAG returns.
 */
c4('c4recalibrate').onclick = async () => {
  if (!confirm('Reset averages and active alarms? Run the belt in its intended steady normal condition. Distance, runtime and jam count will stay.')) return;
  try {
    const session = await (await c4request('/api/conveyor/session')).json();
    const response = await c4request('/api/conveyor4/recalibrate', {method: 'POST', headers: {'X-Team8-Session': session.token}});
    const result = await response.json();
    if (!response.ok) throw new Error(result.message);
    c4('c4action').textContent = result.message;
    await refreshConveyor4();
  } catch (error) { c4('c4action').textContent = error.message; }
};
/* SECTION: Export the latest real measurements and monitoring state as JSON.
 * The file is a recent snapshot, not the entire SQLite history. Browser reloads
 * or downloads do not change averages, incident counts or accumulated totals.
 */
c4('c4export').onclick = () => {
  if (!c4latest) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(c4latest, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'team8conveyor4-report.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

/* SECTION: Tag timing settings and acknowledgements use existing server-owned
 * records. They do not change speed/current averages or the published motor FLAG.
 * Local session authentication is separate from MQTT transport configuration.
 */
async function c4tagPost(path, payload) {
  const session = await (await c4request('/api/conveyor/session')).json();
  const response = await c4request(path, {method: 'POST', headers: {
    'Content-Type': 'application/json', 'X-Team8-Session': session.token
  }, body: JSON.stringify(payload)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.message);
  return result;
}
c4('c4tagLimits').onsubmit = async event => {
  event.preventDefault();
  try {
    const result = await c4tagPost('/api/transit/standard', {
      minimum: Number(c4('c4tagMin').value), maximum: Number(c4('c4tagMax').value)
    });
    c4('c4tagAction').textContent = result.message;
    await refreshConveyor4();
  } catch (error) { c4('c4tagAction').textContent = error.message; }
};
document.addEventListener('click', async event => {
  const button = event.target.closest('[data-c4-tag-ack]');
  if (!button) return;
  try {
    const result = await c4tagPost('/api/conveyor4/tag-ack', {trip_id: Number(button.dataset.c4TagAck)});
    c4('c4tagAction').textContent = result.message;
    await refreshConveyor4();
  } catch (error) { c4('c4tagAction').textContent = error.message; }
});
c4('c4visionPanel').addEventListener('toggle', () => {
  if (!c4('c4visionPanel').open) clearC4Frame();
  else if (c4latest) renderAprilTagCamera(c4latest.vision);
});
c4('c4cameraImage').onerror = () => {
  clearC4Frame();
  c4('c4cameraInfo').textContent = 'JPEG could not be decoded. Preview unavailable.';
};
refreshConveyor4();
setInterval(refreshConveyor4, 1000);
