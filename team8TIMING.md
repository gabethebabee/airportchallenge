# Barcode A-to-B travel timing

## Try it now without cameras

1. Restart `python team8dashboard.py`, then refresh http://127.0.0.1:8080.
2. Open **A to B timing**. Set minimum/maximum acceptable seconds (default 0–10 seconds is a placeholder, not calibrated).
3. Enter a test barcode, click **Scan at A**, wait, then click **Scan at B** with exactly the same barcode.
4. Watch the elapsed time and result. Leave another barcode at A to see it become overdue. Expand checkpoint history to see every scan.

This tab uses actual received scan records. It is separate from the original synthetic bag/motor demo. Manual tests are labelled `manual` and cannot complete camera or MQTT journeys.

## Connect two camera scanners

The dashboard is the timing server. On that machine, set a shared scan token before starting it:

```powershell
$env:TEAM8_SCAN_TOKEN = 'choose-a-random-secret-at-least-24-characters'
python team8dashboard.py
```

On each scanner machine, set the same environment variable. Install `opencv-python` and `pyzbar` in its Python environment (the organizer Jetson already has OpenCV/PyZbar). PyZbar also needs the native ZBar library; use the organizer-prepared environment or install the appropriate native dependency if imports fail. Run two terminals for two cameras on the same machine:

```powershell
python team8barcode_scanner.py --checkpoint A --camera 0
python team8barcode_scanner.py --checkpoint B --camera 1
```

Each scanner opens its own labelled camera window. ESC closes it. Do not open the same camera device in this script and the organizer scanner simultaneously; devices may be exclusive. Camera indices are examples; verify the actual indices on your computer.

If scanners run on other machines, start the dashboard with `--host 0.0.0.0` on the lab network and pass `--server http://DASHBOARD-LAN-IP:8080` to both scanners. Use your dashboard laptop's actual reachable IP, not 127.0.0.1. Firewall/network isolation may require lab assistance. The browser dashboard is still operated locally on its host machine. The scan token does not grant conveyor-control access. Plain HTTP carries the token unencrypted; use only the assigned trusted lab network or a trusted HTTPS proxy.

## Reuse the organizer's barcode scanners via MQTT

Instead of opening the cameras again, run a separate bridge process for each checkpoint's raw barcode topic:

```powershell
python team8barcode_scanner.py --checkpoint A --broker 129.97.228.106 --mqtt-topic Conveyor3/barcode_value
python team8barcode_scanner.py --checkpoint B --broker 129.97.228.106 --mqtt-topic YOUR_SECOND_SCANNER_TOPIC
```

MQTT bridge mode requires `paho-mqtt` version 2. Both processes also need `TEAM8_SCAN_TOKEN`. The ZIP supplies one station's `Conveyor3/barcode_value` topic, **not an established second checkpoint**. Configure/confirm the second scanner's distinct topic with your team. Subscribing both A and B to one topic would produce meaningless near-zero trips. Use either camera mode for both checkpoints or MQTT mode for both; their source namespaces deliberately do not mix. The bridge also accepts the organizer's `/baggage_routing` JSON format and ignores retained MQTT messages.

## Rules and limits

- Exact barcode text identifies a bag within a source namespace. Ensure each physical bag has a distinct code; two bags sharing a code cannot be distinguished.
- A starts one active journey for that barcode/source; repeats do not reset it. B completes only that journey. B without A is logged but produces no inferred travel time.
- Camera/MQTT senders suppress repeated observations until the barcode has been unseen for 2 seconds. The backend also suppresses rapid repeated A scans for 3 seconds. Re-presenting a completed bag at A after that period begins a new journey.
- Journeys retain the minimum/maximum configured when A was scanned. Boundaries are inclusive. Below minimum = too fast, above maximum = late; no B after maximum = overdue.
- Repeated delivery with the same event ID is idempotent. A failed delivery gets one retry using that ID. Failed unconfirmed scans are printed in the scanner terminal and are not silently treated as successful.
- Timing uses server receipt timestamps for both checkpoints, including travel during intentional belt pauses. It is affected by delivery latency and server clock changes. Scanner-local clocks are not used. Large clock rollback is treated as an error when detected. For precise timing, use synchronized capture timestamps or a shared hardware clock in a later version.
- Records persist in `team8transit.sqlite3` beside the dashboard; do not commit real bag records or the scan token. The tab shows the latest 100 journeys/scans; older records remain in the database.
- This script does not diagnose a physical jam, stop the conveyor, or publish fake routing commands. Overdue can mean a scan/network failure as well as a delayed bag.
- The scanner camera window decodes barcodes; its video is not streamed to the dashboard camera panel.

Tests: `python -B -m unittest team8test_transit team8test_control` and `node team8test_flow.js`. Camera hardware and live MQTT operation still need local validation.
