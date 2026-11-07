# Run the dashboard

**Hardware integration update:** an optional physical-control panel now connects through `team8conveyor_control.py` and the generated `team8conveyor_flow.json`. It is disabled by default. See `team8CONTROL.md` for commissioning and the source-backed scope review. Synthetic motor cards/bag histories remain independent from this panel. Earlier statements below about no hardware control apply to the demo dataset, not the optional bridge.

In the VS Code terminal, from this project folder:

```powershell
python team8dashboard.py
```

Open http://127.0.0.1:8080 in your browser. Stop with Ctrl+C. If port 8080 is busy, use `python team8dashboard.py --port 8081` and open that port instead. No pip packages are required; use Python 3.9 or newer and a current browser.

If `python` opens the Microsoft Store or fails, select an installed Python interpreter in VS Code. The development environment also has this interpreter:

```powershell
& 'C:\Users\gabri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' team8dashboard.py
```

## What works now

- Overview with camera selection, enlarged preview, and per-camera local image/video preview.
- Stuck-bag, overdue-checkpoint, and motor inspection example alerts; acknowledgement retains the active condition.
- Searchable bag list and proactive checkpoint timelines, including bags without incidents.
- Motor status, speed, location, current, encoder state, speed limits, running-time percentage, and maintenance flags.
- Speed and percentage charts with horizontal limit lines.
- Session statistics, incident log, and JSON report download.
- Keyboard-accessible tabs, modal histories, and responsive light layout.

## What is still synthetic

The dashboard is a functional UI prototype with fixed sample records. Camera drawings are illustrations. Uploaded media is displayed locally but is not analyzed. No camera streaming, bag detector, MQTT consumer, automatic alert engine, or hardware control is implemented. The earlier `team8config.example.json` and `team8demo_events.json` are not loaded by this UI.

Acknowledgements are browser-memory only and disappear on refresh/reset. Motor graphs are sample data, not sampled real time. The header clock is the current local time; checkpoint and incident timestamps belong to the synthetic session.

## Next integration step

Inside `team8dashboard.py`, `makeDemo()` defines the data structure consumed by the UI. Replace that data source with validated observations/backend state. Keep stable bag IDs for checkpoint histories and separate short-lived camera track IDs. Implement overdue-checkpoint timing from an expected route/transit window, and treat missing telemetry as unknown rather than as proof that a bag is missing.

For motor calculations, agree on speed units and the calibrated minimum/maximum first. Accumulate actual sample durations while a run is requested, including stalled time; exclude intentional stops. Calculate `100 * time_within_range / total_running_time`, with unknown when the denominator is zero. Alert after a sustained below-target period/minimum observation duration, not on one noisy sample. Maintenance flags indicate inspection, not a diagnosis.

## Verification performed

Python and embedded JavaScript syntax passed. Response handlers for the page and health endpoint passed in-memory checks. UI render, 65% motor calculation, bag timeline, and empty search passed DOM-stub checks. Full browser visual testing and live HTTP requests were not verified: the execution environment blocked local socket requests.
