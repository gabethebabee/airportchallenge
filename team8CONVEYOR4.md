# Conveyor 4: speed, current and FLAG

The expandable **Camera feed & AprilTag checkpoints** panel now shows MQTT camera previews and real tag-based journeys. Start the publisher on the camera-owning Jetson using [team8APRILTAGS.md](team8APRILTAGS.md). Camera/tag messages use separate topics and never modify the motor FLAG. The dashboard machine only needs broker access, not direct camera or SSH access.

The main dashboard now focuses on six values: **belt speed, motor current, FLAG, distance ran, time ran, jam counter**. Run `python3 team8dashboard.py` on the Jetson and open http://127.0.0.1:8080. Restart an already-running Python server before refreshing the page.

## Actual MQTT mappings

The local file `Node-RED stuff` establishes these published outputs:

| Data | Topic | Meaning |
| --- | --- | --- |
| Belt speed | `Conveyor4/get_belt_speed` | Plain numeric cm/s; organizer encoder conversion |
| Motor voltage | `Conveyor4/get_motor_voltage` | Analog output readback in volts, **not amperage** |
| Motor current | **Exact topic still needed** | A real current feed exists according to the team, but its topic/payload has not been supplied |

The supplied broker is `129.97.228.106:1883`. The new monitoring outputs are configurable defaults **created by this app**, not previously established topics:

| Output | Payload |
| --- | --- |
| `Conveyor4/FLAG` | Retained QoS 1 JSON boolean: exact bytes `true` or `false` |
| `Conveyor4/STATUS` | Retained JSON diagnostic state/heartbeat, published up to once a second |

The supplied Node-RED tab is saved disabled. Staff/team must enable the appropriate station publishers and verify periodic updates. No flow was deployed and no physical conveyor was actuated during implementation. Do not deploy the old Conveyor3 sensor exporter as if it were Conveyor4.

## Configure the current input

Copy `team8conveyor4.example.json` to `team8conveyor4.local.json`. The app automatically loads the local file if present; otherwise it uses the example. Set `current_topic` to the **exact** motor-current topic. It remains null by default because voltage must never be mislabelled as current.

If the current message is plain numeric `0.72`, leave `current_key` null. If it is `{"amps":0.72}`, set `current_key` to `"amps"`. Set `current_scale_to_a` to 0.001 for milliamps or 1 for amperes. Speed is already cm/s in the supplied export; change `speed_scale_to_cm_s` only if the actual publisher uses different units. Numeric strings such as `"0.72"` are not accepted as measured numbers; publish a number or the configured numeric JSON field.

Override topic names for FLAG/STATUS if your Node-RED consumers use a different contract. In Node-RED, pass incoming JSON boolean text through a JSON node before testing boolean true/false; the string `"false"` must not be treated as a truthy JavaScript string.

Both sensor feeds must send fresh samples periodically, even when values are unchanged. The default timeout is 4 seconds. Missing/retained/duplicate/invalid data cannot establish a verified normal state. If no messages arrive, use `python3 team8mqtt_inspect.py --topic 'Conveyor4/#'` on the Jetson to inspect the actual station; this diagnostic subscribes only and publishes nothing.

## Exact average and timer rules

1. Each channel warms up with **5 actual accepted observations**. Browser polls do not count as observations.
2. Its average is the arithmetic mean of up to the previous **30 accepted normal samples**.
3. Compare the next reading to that prior reference. Values **more than** 15% above or below start that channel's deviation indicator. Exactly ±15% is inside.
4. Freeze that channel's reference and exclude out-of-range readings, so a sustained fault cannot redefine itself as normal.
5. One **shared OR timer** continues while either fresh channel is outside its band. The page also shows channel-specific durations to identify the cause. The cause may switch/overlap without resetting the shared timer if an outside condition remains observed.
6. Once the shared timer is **greater than 10 seconds**, FLAG becomes false and one abnormal episode is counted. At exactly 10 seconds, it has not yet crossed the specified threshold.
7. Fresh readings returning inside their bands clear their channel candidates/alarms. Both channels must be fresh/calibrated and recovered before verified normal true returns and the episode rearms.
8. Gaps/disconnections reset unconfirmed timers. Confirmed alarms remain unresolved through missing data. No silent gap is treated as ten seconds of observed deviation.

Calibrate with the conveyor in its intended steady operating condition. A zero baseline mathematically has a zero-width percentage band: a sustained nonzero value is outside it. The **Recalibrate averages** button explicitly resets baselines/active alarms and collects new warm-up samples; it preserves cumulative time, distance, readings and episode count. Recalibrate after deliberately changing sensor topics, units or intended operating conditions.

Accepted baselines survive an ordinary restart. Restored baselines still require fresh live readings before FLAG can become true; a deliberate recalibration clears the baseline and requires the full warm-up again.

## FLAG polarity and unavailable data

- **true:** both required channels are fresh/calibrated and neither has a confirmed abnormal condition. A deviation still inside its 10-second persistence window is displayed as timing, with FLAG still true.
- **false, Abnormal:** the deviation persistence rule triggered, or a previously triggered condition remains unresolved.
- **false, Unknown/Calibrating:** normal has not been verified because an input is missing, stale, invalid or warming up. These states do **not** create a jam-counter event on their own. STATUS distinguishes them from a measured abnormal condition.

This conservative unknown convention avoids publishing true without both measurements. The UI calls the state Unknown rather than falsely diagnosing a sensor outage as a physical jam.

The client sets a retained false last will and sends false on graceful shutdown. During a network partition the broker cannot instantly receive a new flag; MQTT keepalive/last-will detection takes time. Downstream equipment should also watch STATUS heartbeat freshness and treat missing heartbeats as unknown/false. These monitoring messages are not a safety-rated interlock or a motor run/stop command.

## Time, distance and counter

The incoming data does not include runtime, so Python uses a monotonic clock. For each continuous fresh speed interval:

- `distance_cm += previous_speed_cm_s * elapsed_seconds`
- moving time increments only if that previous speed exceeds `moving_threshold_cm_s` (default 0.05 cm/s)
- a known zero-speed interval adds no moving time/distance
- a stale/disconnected interval adds nothing

The display converts centimetres to metres and seconds to hours:minutes:seconds. This is observed belt-moving time, not electrical powered-on motor time; those cannot be distinguished from speed/current alone. Integration uses the preceding sample over the interval, so accuracy depends on sample rate. Runtime/distance update with received speed measurements, not browser refreshes.

The **jam counter counts confirmed abnormal episodes**, not packets, seconds or proven physical jams. Simultaneous speed/current abnormalities count once. After fresh normal recovery, a later sustained deviation can create a new episode. Overcurrent/underspeed are inspection evidence; these two measurements alone do not prove a trapped bag.

Readings, totals, accepted baselines and unresolved abnormal state persist in `team8conveyor4.sqlite3`. Process-local timer timestamps are not persisted, so downtime is never counted as an observed deviation/run interval. The charts/export show recent readings; all recorded rows remain in SQLite.

## Code map and deployment

- `team8conveyor4.py`: validated inputs, averages, shared timer, integration, persistence, MQTT subscriptions/publications.
- `team8conveyor4.html`, `.css`, `.js`: focused, small-screen display and operator-requested recalibration.
- `team8conveyor4.example.json`: documented starting settings; local JSON overrides are excluded from the USB package.
- `team8dashboard.py`: serves this page by default and evaluates/publishes monitoring state even while the browser is closed.
- Existing barcode/legacy monitoring files remain available. Launch with an older explicit `--mqtt-config` file whose monitor type is not conveyor4 to use that previous dashboard.

Paho-MQTT remains required for a real broker connection. The prepared Jetson has it according to the organizer instructions; Paho 1.x/2.x are supported. Without it, the local UI opens with an explicit unavailable message and never shows fake connected data.

Rebuild USB files with `python team8package.py`; copy/extract `team8jetson.zip`. No laptop databases or local configuration/secrets are bundled.

Tests: `python -B -m unittest team8test_conveyor4 team8test_monitor team8test_transit team8test_control` and `node team8test_flow.js`. Tests use fake clocks, simulated MQTT callbacks and mock publication queues; actual lab connectivity and the still-unspecified current topic require on-site validation.
