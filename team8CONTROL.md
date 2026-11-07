# Optional physical conveyor integration

## What the ZIP actually supplies

Source: `F26-Airport-Innovation-Challenge/baggage-handling-system-subproblem/barcode-conveyor/` inside the organizer archive.

| Source | Confirmed behavior |
| --- | --- |
| `flows.json` | Channel 7 belt analog output: 2.3 V run / 0 V stop; channel 6 fixed direction: 0. Barcode route mismatch writes 0 to channel 7. |
| `Basic Motion and Divert.json` | Another configuration uses 1.7 V; encoder channel 0; conversion uses 700 counts/rev, pulley ratio 4, circumference 10.5 × 3.14 cm. |
| `barcode_scanner.py` | Publishes barcode/routing messages, not motor commands. |
| Physical tutorial | One testbed belt. `conveyor_1/2/3` denote virtual destinations; not three independently addressable motors. |

The bridge uses the **2.3 V Barcode Scanner configuration**, not arbitrary speed settings. Verify that configuration against your assigned testbed before enabling. It exposes run/stop only; it does not add direction reversal or diverter override. Existing diverter outputs in `flows.json` are disabled; they remain outside this module. No current sensor feed is supplied in these files. Encoder linear speed is cm/s, not the demo cards' rpm.

## Files

- `team8conveyor_control.py`: optional Python HTTP adapter; standard library only.
- `team8conveyor_flow.json`: importable Node-RED bridge, disabled by default.
- `team8build_control_flow.py`: reproducibly generates that flow from the ZIP, with fresh IDs; no deployment or hardware access.
- `team8dashboard.py`: isolated physical-control panel, separate from synthetic charts and bags.

## Setup on the assigned PLC

1. Save/export the existing PLC flow. Import `team8conveyor_flow.json` into a **new flow**. Do not overwrite the organizer flow.
2. Verify the Groov device is the assigned local PLC and channel mappings match the source configuration. Verify the MQTT broker/station topic `Conveyor3/baggage_routing` matches your assigned equipment. Do not deploy to another team's station.
3. Set a Node-RED environment variable named `TEAM8_CONTROL_TOKEN` to a random secret at least 24 characters long. Use the same value on the laptop. The token is not embedded in the flow or sent to browser JavaScript.
4. Set the organizer `global.active_conveyor` value if needed (default is `conveyor_1`). This is a virtual destination filter.
5. Disable other flows that write the same outputs while using this replacement bridge, including the original Barcode Scanner and Basic Motion flows. The generated bridge includes its own routing-rejection stop; simultaneous output writers can undo a stop.
6. Enable the imported Team8 flow and deploy. It requests a stop on deployment, then waits for commands. No deployment was performed by Codex.
7. In the laptop terminal, configure the Node-RED HTTP base URL, **not** the PLC `/manage/home` portal or MQTT port:

```powershell
$env:TEAM8_PLC_URL = 'https://YOUR-NODE-RED-HTTP-BASE'
$env:TEAM8_CONTROL_TOKEN = 'YOUR-RANDOM-SECRET-AT-LEAST-24-CHARACTERS'
python team8dashboard.py
```

Use the actual HTTP base URL displayed by the assigned Node-RED setup; it is not specified in the archive. The generated endpoint adds `/team8/conveyor` to that base. HTTPS certificates must be trusted; the adapter does not disable verification.

8. Set `ENABLE_CONVEYOR_CONTROL = True` at the bottom of `team8conveyor_control.py`, then restart Python. Refresh PLC status on the dashboard.
9. With the assigned testbed clear, scan a valid barcode matching the active destination, then click Run within 10 seconds. Run requests a **3-second pulse**. The PLC-side timer requests zero output at expiry (checked every 250 ms); it does not rely on the browser staying open. Stop can be requested at any time while the bridge is reachable.

## Disable / comment out

Set `ENABLE_CONVEYOR_CONTROL = False` and restart Python. Alternatively comment out the marked import at the top of `team8dashboard.py`; the UI then reports disabled. No other dashboard features depend on the module. Disable the Team8 Node-RED tab after bringing the belt to a stop and restore your previous flow when finished. Disabling Python access is not itself a motor stop.

## Interlocks and limitations

- The Node-RED bridge requires a non-retained, well-formed allowed barcode/routing message. Invalid codes or mismatched destinations request a stop and revoke Run permission; a later valid scan is required. Run also requires that the scan be less than 10 seconds old.
- Valid routing messages never automatically restart the belt.
- Fixed direction is written first; its completion triggers the bounded run request only while the lease and route permission remain valid.
- Commands are not automatically retried. If a request times out, the output may already have changed. Verify at the belt; do not assume success or failure from a network timeout.
- The three-second expiry is application logic on the PLC's Node-RED runtime. It is **not** a safety-rated watchdog and cannot guarantee stopping if Node-RED/PLC execution fails. Use the testbed's physical emergency stop when needed.
- Status reports requested output and fresh encoder speed, not guaranteed actuator feedback. Encoder data becomes unknown after 3 seconds without updates. With the starter's change-triggered encoder input, no updates can mean a stationary belt or a failed input.
- No hardware was connected or actuated during implementation. Commission and test locally before using the controls in the demo.

## Reconsidered project scope

Keep the team's core goal: identify an unexpected bag stoppage, locate the monitored checkpoint, alert an operator, and provide camera context. The archive supports a single-checkpoint physical demonstration; it does not make the existing synthetic multi-camera histories real.

Next priority is connecting the camera detector and barcode checkpoints to persistent incident/bag histories. Use the encoder to distinguish belt motion from bag motion; when either measurement is unavailable, show unknown. Missing luggage requires a defined expected next checkpoint and transit timeout; one missed camera frame is insufficient.

Keep motor-current-based jam diagnosis and predictive maintenance as stretch work until actual sensors/data exist. Do not infer amperage from the analog output voltage. Keep the broader UI for illustrating expansion, clearly labelled synthetic, and demonstrate the actual hardware panel independently.

The organizer rubric prioritizes focused working functionality, reliability, operator safety, and clear trade-offs. Submission requires a 3–5 minute presentation and AI disclosure using https://aidframework.org/. Work still ends at approximately 2:30 p.m. Sunday for judging.
