# Reading the Team 8 code

**Camera / AprilTags:** `team8apriltag_camera.py` runs on the Jetson and is the camera's owner. It detects square tags, assigns A/B image regions, and sends small previews plus checkpoint events to MQTT. `team8vision.py` checks those messages, expires old images, and passes tag identities into the existing journey timer. `team8conveyor4.py` subscribes to those separate topics; the browser's camera panel fetches images from Python. See [team8APRILTAGS.md](team8APRILTAGS.md) for commands, print guidance and limits. Section comments explain each stage in the new source files.

**Current scope:** `team8conveyor4.py` now owns the conveyor 4 rolling averages, shared >10-second deviation timer, true/false MQTT FLAG, runtime/distance integration and abnormal-episode count. `team8conveyor4.html`, `.css` and `.js` form the default focused UI; `team8conveyor4.example.json` configures exact topics and limits. Read `team8CONVEYOR4.md` first. The barcode/legacy files explained below remain available with older explicit configurations.

Comments are now included in the Python, browser JavaScript, HTML, CSS, tests, and embedded Node-RED JavaScript. This guide covers how they fit together and explains the JSON fields, because standard JSON does **not** permit comments.

Each major function/section now starts with a paragraph explaining its purpose, incoming data, resulting state/output, and relevant design choices. Read that paragraph first, then follow the code beneath it; the shorter inline notes explain particular calculations or edge cases along the way.

## Start with these files

| File | What it owns |
| --- | --- |
| `team8dashboard.py` | Starts the local web server, serves page files, and connects API requests to the other Python objects |
| `team8dashboard.html` | Page sections, buttons, input fields and modal windows |
| `team8dashboard.css` | Text sizes, colours, touch targets, and the small-screen layout |
| `team8dashboard.js` | Shared browser helpers, tab navigation, illustrative/demo views, real A-to-B display, optional control requests |
| `team8live.js` | Actual monitoring display: sensor readings, incident actions, real bag timelines, health charts and live previews |
| `team8transit.py` | Barcode journey timer, checkpoint history, deadlines and persistent bag incidents |
| `team8monitor.py` | Sensor validation, MQTT subscriber, rolling time calculations, sensor incidents and expiring JPEG cache |
| `team8barcode_scanner.py` | Owns the camera, reads barcodes, assigns A/B, sends scans, and shares preview frames |
| `team8conveyor_control.py` | Separately disabled HTTP adapter for physical run/stop requests |
| `team8mqtt_inspect.py` | Read-only topic/payload inspection; it never publishes motor commands |
| `team8build_sensor_flow.py` | Generates the read-only Node-RED MQTT sensor exporter from source-backed channel definitions |
| `team8build_control_flow.py` | Generates the optional control bridge from the original organizer ZIP |
| `team8package.py` | Creates the USB ZIP using an explicit file allowlist, excluding databases and secrets |
| `team8test_transit.py` | Offline tests of timing, scan identity, history and API authorization |
| `team8test_monitor.py` | Offline tests of sensor timing, MQTT decoding, camera expiry, incidents and combined jam evidence |
| `team8test_control.py` | Offline tests of the disabled adapter, authorization, command rejection and no-retry behavior |
| `team8test_flow.js` | Evaluates Node-RED functions in fake contexts; checks flow wiring, conversion, expiry and browser script syntax |

## Follow one bag

1. A barcode appears in the scanner's A region or arrives on the assigned A MQTT topic.
2. The server passes that code to `TransitTracker.scan()`.
3. A new `trips` row stores its start time and current travel-time limits. A `scans` row records the event.
4. The background supervisor checks deadlines even if the browser is closed.
5. Missing the deadline creates one `transit_incidents` row, rather than repeating an alert each second.
6. B's matching barcode completes the journey and records recovery. An acknowledgement only records receipt.
7. The browser polls the results and renders them. Refreshing the browser does not reset the underlying timer.

Barcode text **and source** identify a journey. A `manual` test cannot complete a `camera` or `mqtt` journey. Use the same ingestion method at A and B.

## Follow one sensor sample

1. The Node-RED exporter reads the encoder and run-request readback, converts the counter delta to cm/s, and publishes JSON.
2. `MQTTInputs.consume()` recognizes the assigned sensor topic and hands the payload to `SensorMonitor`.
3. The monitor validates units/value types, station, sequence and event ID before storing the sample.
4. When the next fresh sample arrives, the preceding sample can close an observed time interval.
5. `snapshot()` clips those intervals to the rolling window and sums observed seconds, not message counts.
6. Missing data remains unknown; known intentional stops do not count as bad running performance.
7. A sustained stall or exceeded outside-time threshold creates an inspection incident. Nothing here starts or stops the motor.

The two flow JSON files can contain `//` comments **inside their quoted JavaScript strings**. They remain valid JSON; the Node-RED runtime interprets those strings as JavaScript after import. The comments are also in the generator source so they survive regeneration.

## JSON configuration reference

### `team8mqtt.example.json` and `team8mqtt.camera.example.json`

These two files have the same structure; only their checkpoint topic choices differ. The first uses the organizer scanner at A and leaves B unconfigured. The camera version uses the new A/B scan topics from our own scanner.

| Field | Meaning |
| --- | --- |
| `broker` | Local MQTT server address; this is not an internet API |
| `port` | MQTT TCP port, normally 1883 in the supplied lab setup |
| `station_id` | Expected physical testbed identity; messages for another station are rejected |
| `sensor_topic` | Exact topic carrying the structured sensor envelope below |
| `checkpoint_topics.A` | Exact topic for scans at the first checkpoint |
| `checkpoint_topics.B` | Distinct second-checkpoint topic; null means not configured |
| `limits` | Sensor-health settings described next |

### Every `limits` field

| Field | Meaning / units |
| --- | --- |
| `speed_min_cm_s` | Lowest acceptable belt speed in centimetres per second |
| `speed_max_cm_s` | Highest acceptable belt speed in centimetres per second |
| `window_seconds` | Length of the moving observation window |
| `outside_limit_seconds` | Maximum allowed observed running time outside the speed range within that window |
| `minimum_running_seconds` | Amount of valid running data required before evaluating the maintenance threshold |
| `stale_seconds` | Maximum gap/age before sensor continuity is unknown |
| `stall_speed_cm_s` | Near-zero speed threshold used with an explicit run request |
| `stall_seconds` | How long near-zero speed must persist while run is requested |
| `high_current_a` | Optional measured-amperage threshold; null disables this extra evidence |
| `service_runtime_hours` | Optional reminder based on recorded valid running hours; null disables it |
| `service_distance_km` | Optional reminder based on recorded valid belt distance; null disables it |

The example speed limits need calibration on the actual belt. Motor output voltage is not motor current. These settings are inspection rules, not a prediction of component failure.

### Incoming sensor JSON

| Field | Meaning |
| --- | --- |
| `station_id` | Must match the configured station |
| `event_id` | Unique delivery identity; repeated IDs do not refresh freshness or accumulate time |
| `session_id` | New producer identity after exporter restart |
| `sequence` | Increasing sample number within that producer session |
| `speed_cm_s` | Measured belt linear speed; null when unavailable |
| `run_requested` | true, false or null; a request is not proof of motion |
| `current_a` | Actual measured amperage, or null without a current sensor |

### Scan messages

Raw organizer topics may contain only the barcode text. Our scanner's structured message contains `barcode`, `checkpoint`, `source`, and `event_id`. The MQTT topic mapping determines A versus B on receipt; it does not trust a payload to select an arbitrary route. No scan message is a motor command.

### `team8config.example.json`

This is the **earlier observation/replay proposal**, not the live monitor configuration. It is retained for reference and is not loaded by the current dashboard.

| Group | Fields explained |
| --- | --- |
| `schema_version`, `mode`, `replay_file` | Proposal version, replay mode, and synthetic input filename |
| `mqtt` | Proposed enable flag, host, port, observation/barcode topics and client identity |
| `detection.motion_threshold_px_per_s` | Proposed camera-image motion threshold; pixels/s is different from encoder cm/s |
| `detection.stationary_seconds` | Proposed duration before classifying a stationary camera track |
| `detection.recovery_seconds` | Proposed sustained movement required to recover |
| `detection.telemetry_timeout_seconds` | Proposed observation freshness limit |
| `detection.minimum_confidence` | Proposed detector confidence cutoff |
| `zones` | Proposed zone IDs, display labels, camera indexes and optional image regions |
| `notes` | Human-readable limitations; not an executable instruction |

### `team8demo_events.json`

Also part of the original replay proposal. `observations` contains timestamped synthetic zone/track movement, belt state, confidence and optional evidence-image paths. `checkpoints` contains expected results at specific replay-clock times. A checkpoint assertion is not another sensor observation. The live application does not automatically load this file.

### `team8conveyor_flow.json` and `team8sensor_flow.json`

These arrays are importable Node-RED graphs, rather than application settings. Both are saved disabled until commissioned at the assigned station.

| Common field | Meaning |
| --- | --- |
| `id` | Unique node identity; wires refer to these values |
| `type` | Node implementation, such as `function`, `mqtt out`, or `groov-io-input` |
| `z` | Tab owning the node |
| `name` / tab `label` | Visible description in the Node-RED editor |
| `x`, `y` | Visual canvas position, not physical coordinates |
| `wires` | Lists of downstream node IDs, grouped by output |
| `func` | JavaScript body of a function node |
| `initialize` | JavaScript that resets node-local state when deployed/started |
| `device`, `dataType`, `channelIndex` | Groov device and I/O interpretation; verify against the assigned testbed |
| `broker`, `topic`, `qos`, `retain` | MQTT connection/topic/delivery settings |
| `repeat`, `once`, `onceDelay` | Timer/inject scheduling behavior |

The sensor flow has no output-write nodes. The control flow has explicit channel writes and separate authentication/run limits. Adding comments does not enable or deploy either flow.

## Small glossary

- **API:** the request/response interface between browser/scanner and Python.
- **MQTT topic:** a named message channel on the broker.
- **Callback:** a function called when an event occurs, such as a new message or button click.
- **Lock:** keeps two server threads from modifying shared state simultaneously.
- **SQLite transaction:** a group of database operations committed together.
- **Idempotent retry:** sending the same event again does not count it twice.
- **Rolling window:** the most recent configured span of time, rather than time since startup.
- **Unknown:** insufficient current evidence; it is deliberately different from stopped or normal.

After editing code, run `python -B -m unittest team8test_monitor team8test_transit team8test_control` and `node team8test_flow.js`. Rebuild the USB ZIP with `python team8package.py` when deploying updated files.
