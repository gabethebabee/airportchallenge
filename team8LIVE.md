# Team 8 live monitoring — Jetson setup

For a beginner-friendly explanation of the source files, JSON fields, and data flow, read `team8CODE_GUIDE.md`. Runtime functions, UI sections, test helpers and generated Node-RED JavaScript now include inline comments.

## What is implemented

The **Live monitor** tab is now the main screen. It displays MQTT connection/freshness, actual encoder speed, requested belt state, measured current if supplied, rolling belt health, incident acknowledgement/history, and scanner camera previews. The original overview/bag/motor/report views still contain explicitly labelled illustrative data; do not present those as live measurements.

Two independent workflows run on the server, even while the browser is closed:

1. A barcode at A starts a journey. Missing its deadline creates one persistent overdue incident. Arrival at B resolves it; acknowledgement alone does not. The bag's checkpoint history and the incident remain in SQLite.
2. Fresh MQTT speed/run-request readings create time-weighted intervals. Known intentional stops are excluded from running-time performance. Missing/invalid/disconnected data stays unknown. A sustained stall or too much out-of-range running time creates a separate inspection incident.

No monitor code publishes motor commands. The optional conveyor-control integration remains separately disabled by default.

## USB: copy the ready-to-run folder

On your laptop, run `python team8package.py`, then copy/extract **team8jetson.zip** into the Jetson Home folder. All bundled files belong in the same folder. No internet, npm, or frontend build step is needed. Do not copy laptop SQLite databases or secrets: the package deliberately excludes them.

The runtime needs nine files together: `team8dashboard.py`, `team8transit.py`, `team8monitor.py`, `team8conveyor_control.py`, `team8barcode_scanner.py`, `team8dashboard.html`, `team8dashboard.css`, `team8dashboard.js`, and `team8live.js`.

Python 3.6 syntax and the older threaded-server fallback are supported. The scanner needs the organizer-preinstalled OpenCV/PyZbar/native ZBar; MQTT needs Paho. The compatibility adapter supports Paho 1.x and 2.x. The Jetson's actual browser/hardware still requires local testing.

## 1. Inspect the assigned MQTT station first

From a terminal in your copied folder on the Jetson:

```bash
python3 team8mqtt_inspect.py
```

This listens for 15 seconds to `Conveyor3/#` and `team8/Conveyor3/#`, prints messages, and publishes nothing. Override `--broker` and repeat `--topic` for your assigned station if different. Internet access is unnecessary; local connectivity to the broker is required.

The organizer scanner publishes `Conveyor3/barcode_value` and `/baggage_routing`. **The new `team8/Conveyor3/telemetry` topic is our proposed sensor format; it was not supplied as an existing topic in the ZIP.** If staff already publishes sensor messages, inspect them and map them to the documented format rather than guessing units or channel meanings.

## 2. Provide the sensor messages

If no suitable sensor topic exists, import **team8sensor_flow.json** into a new Node-RED tab on your assigned PLC. It is disabled initially and contains no `groov-io-write` nodes. It can coexist with the assigned operational flow because it only reads sensors and publishes telemetry.

Before enabling/deploying it, verify with staff:

- Encoder channel **0**, using the organizer conversion: 700 counts/rev, pulley ratio 4, pulley circumference 10.5 × 3.14 cm. The result is **belt linear speed in cm/s**, not motor RPM.
- Analog channel **7** output readback. Positive output is interpreted as a run request, not physical movement. The archive establishes the output-write mapping; whether the configured device exposes that output through this read node still needs an on-site check. If unsupported, provide run-request state from the existing control flow and leave the field null meanwhile.
- The input nodes actually emit updates for unchanged readings with the selected `deadband=0` setting. Stationary counters must be sampled periodically to establish a measured zero. If unchanged values are not emitted on your installed nodes, use a staff-verified periodic read configuration; the app intentionally shows unknown once updates age out rather than pretending that silence means zero.
- Broker, station ID and topic match your equipment. The example is station `Conveyor3` at `129.97.228.106:1883`.

The exporter sends once per second, does not retain telemetry, and marks sensor fields null after three seconds without a fresh underlying input. The dashboard rejects retained samples, duplicate IDs, and out-of-order samples within a producer session. After a restart or gap it begins a new observed interval; it does not backfill downtime.

**Current is null:** no current sensor mapping was provided in the source. Supply actual calibrated amperage as `current_a` if available. Do not substitute output voltage or infer current from the motor command.

To regenerate this read-only flow on the laptop: `python team8build_sensor_flow.py`. It uses the locally saved source-backed channel definitions in `team8conveyor_flow.json` and never deploys anything.

## 3. Start the dashboard

For the existing organizer barcode scanner at A:

```bash
export TEAM8_SCAN_TOKEN='team8-local-test-2026-scan-token'
python3 team8dashboard.py --mqtt-config team8mqtt.example.json
```

Open **http://127.0.0.1:8080** in the Jetson browser. This config has A set to the organizer's raw barcode topic and B unset. Set B to an actual distinct checkpoint topic when available. Do not run the old HTTP-to-MQTT bridge and the dashboard subscriber against the same inputs; use one ingest path.

For our camera scanner with two regions on one conveyor camera, use the following alternative instead:

```bash
export TEAM8_SCAN_TOKEN='team8-local-test-2026-scan-token'
python3 team8dashboard.py --mqtt-config team8mqtt.camera.example.json
```

In a second terminal, in the same folder:

```bash
export TEAM8_SCAN_TOKEN='team8-local-test-2026-scan-token'
python3 team8barcode_scanner.py --checkpoint AB --camera 0 \
  --broker 129.97.228.106 --publish-topic team8/Conveyor3/scans
```

The scanner publishes to `/A` and `/B` under that prefix; the camera example config subscribes to those exact topics. Preview JPEGs go directly to the local dashboard, not through MQTT. **Close other camera programs first.** This scanner does not reproduce the organizer's baggage-routing control publisher; use it for monitoring and keep any required conveyor routing integration distinct.

AB mode assigns a barcode to A on the left and B on the right. Use `--a-side right` for opposite belt direction, or `--split-x 0.4` to adjust the boundary. This is valid only if the lens covers two meaningful positions and reads the barcode in both. Boundary jitter can produce a very short journey; use a sensible minimum travel time and verify results against observation. If your view is too narrow, use two physical cameras/scanners instead.

With two cameras on the same Jetson, start separate scanner processes with `--checkpoint A --camera 0 --publish-topic team8/Conveyor3/scans/A` and `--checkpoint B --camera 1 --publish-topic team8/Conveyor3/scans/B`, each with the same broker argument. A and B preview windows correspond to their own cameras. Both processes share the same scan token.

Without any MQTT setup, `python3 team8dashboard.py` still supports direct HTTP/manual timing and previews. MQTT fields remain unknown; sensor readings are never fabricated.

## 4. Calibrate thresholds and test

The example **5–30 cm/s** range and **10-second** bag deadline are placeholders. Measure normal travel and belt speed first, then set your actual standard. The A-to-B tab retains standards per journey.

The default health window implements the document's example: more than **1440 seconds outside the speed range in a rolling 3600-second window**, with at least 60 seconds of observed running data. For a short demonstration, change all three together in Live monitor → Set belt-health limits: for example window **30 s**, allowed outside **6 s**, minimum running data **5 s**. Label those as accelerated demo settings. GUI health-limit changes apply to the current session; save desired launch values in your MQTT config.

Percentage within range = observed running seconds within range / observed running seconds. Intentional stops and unknown time are excluded, and both amounts are shown separately. Sparse telemetry can therefore reduce coverage rather than falsely improve performance. The graph shows the last 60 received speed samples with horizontal acceptable-speed limits and breaks across unknown readings/gaps.

Jam evidence is staged: a real camera/MQTT bag overdue plus sustained near-zero encoder speed while run is requested gives a possible-jam message. If current is actually measured and exceeds a configured threshold, it adds supporting evidence. Manual test bags are excluded from this combined physical-jam inference. This is an inspection aid, not a diagnosis or a safety-rated stop.

Optional service-runtime/distance thresholds are reminders based on recorded valid running intervals, not predictions of remaining motor life. They stay flagged until serviced; a service-reset workflow is future work. Coverage gaps and operation before logging are excluded.

Verify locally:

1. A scan, on-time B scan, and a late/no-B scan.
2. A single alert per trip, acknowledgement, then recovery at B with history retained.
3. Encoder speed on the live screen while the physical belt moves.
4. Intentional stop versus run-requested stall; only establish a stall using staff-approved methods.
5. Stale camera/MQTT inputs become unknown; old incidents remain visible.
6. Speed outside the range for the configured duration produces an inspection flag.

## Persistence, source labels and limitations

- `team8transit.sqlite3` stores bags, checkpoint scans, standards and bag incidents. Existing data is migrated by creating the incident table without dropping any tables.
- `team8monitor.sqlite3` stores received sensor samples, observed intervals and sensor incidents. Only the latest camera frame is held in memory; camera images are not saved to disk.
- One monitor database belongs to one station; use a separate deployment folder/database for a different station. Preview frames carry capture timestamps and expire after four seconds. Running scanner and dashboard on the same Jetson provides their shared clock; remote preview senders need clocks aligned within one second.
- Source namespaces `manual`, `camera` and `mqtt` are separate. Use the same ingestion method for both ends of a journey. Each physical bag needs a unique barcode.
- Timing and health durations use server receipt times. Network delay/server clock adjustments affect measurements. No claim of precision motion measurement is made.
- Live preview and monitoring flags are not physical emergency-stop systems. Nothing was deployed or actuated by Codex.
- Reports contain monitoring history; the original demo report remains separate.
- Include AI assistance with code, flow generation, tests and documentation in the organizer-required AI disclosure using https://aidframework.org/.

## Verification performed

Offline tests cover MQTT input decoding, retained/duplicate rejection, rolling-window duration and clipping, intentional stops, gaps/unknown state, sustained stalls, incident acknowledgement/recovery/persistence, bag timing, camera expiry and combined jam evidence. Node-RED functions are evaluated offline for encoder conversion, unknown/stale values and absence of write nodes. Browser checks at 800×480, 1024×600 and 480×800 use mocked API responses for live readings, incident actions, preview freshness, navigation, and disconnection display. Live broker/PLC/camera behavior remains to be commissioned at the station.
