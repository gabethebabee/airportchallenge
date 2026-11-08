# Team 8 — Baggage stoppage monitoring

## Start here

**Camera and AprilTags:** read [team8APRILTAGS.md](team8APRILTAGS.md). Run `python3 team8apriltag_camera.py --check` on the Jetson, then start its camera publisher. The default dashboard now has an expandable **Camera feed & AprilTag checkpoints** panel below the motor readings. It receives bounded JPEG previews and tag events through MQTT. The new camera path uses AprilTags; earlier barcode instructions below are legacy. Hardware/dependencies still require an onsite check.

**Current scope — conveyor 4:** the default page now shows speed, current, FLAG, distance, runtime and an abnormal-episode counter. See `team8CONVEYOR4.md` for the ±15% / >10-second shared-timer rule, MQTT topics and startup. The supplied station flow confirms speed and voltage topics; the team's exact actual-current topic still needs configuration. Voltage is never relabelled as current.

**Live monitoring implemented:** start with `team8LIVE.md` for MQTT sensor input, persistent incidents, camera previews and rolling belt-health flags. The dashboard now opens on Live monitor. `python team8package.py` creates `team8jetson.zip` for USB deployment, excluding private runtime databases and credentials. MQTT remains optional and read-only; the generated sensor flow still needs local commissioning.

**Checkpoint timing:** the current camera panel matches AprilTag family/ID at A and B and compares elapsed seconds against configurable limits. `team8barcode_scanner.py` is now a compatibility entry point for the AprilTag publisher. The older A-to-B tab remains only in the legacy dashboard.

**Organizer ZIP reviewed:** see `team8CONTROL.md` for the revised single-testbed scope and optional conveyor-control setup. Run/stop is isolated in `team8conveyor_control.py`, disabled by default. The importable `team8conveyor_flow.json` is generated from the supplied Node-RED flows; it has not been deployed. The rest of the dashboard still uses synthetic data.

Detect a bag that has stopped unexpectedly, identify its monitored zone, and show an actionable alert with a camera view or last observed image.

`team8dashboard.py` now serves a working dashboard prototype with clearly labelled synthetic data. Run `python team8dashboard.py` and open http://127.0.0.1:8080. See `team8DASHBOARD.md` for features, limitations, and integration guidance. No live hardware integration has been verified in this checkout.

| File | Purpose |
| --- | --- |
| `team8PLAN.md` | Scope, work blocks, milestones, and fallback |
| `team8INTERFACES.md` | Shared observation format, state rules, and MQTT integration |
| `team8config.example.json` | Proposed local settings; thresholds need calibration |
| `team8demo_events.json` | Synthetic observations for an offline demo |
| `team8DEMO.md` | Acceptance checks and presentation outline |
| `team8dashboard.py` | Runnable dashboard prototype with synthetic data |
| `team8DASHBOARD.md` | Launch instructions and integration status |

## Build order

1. Agree on the event contract in `team8INTERFACES.md`.
2. Display the synthetic sequence in the dashboard and verify the state transitions manually.
3. Connect one camera/zone to the same contract.
4. Demonstrate normal movement, an unexpected stoppage, recovery, and lost telemetry.

Keep the dashboard usable offline. Label synthetic input clearly. Do not claim that a mock demonstration is connected to the conveyor.

## What is available versus referenced

This checkout initially contains only `README.md` and an empty `team8dashboard.py`. The supplied notes reference a separate challenge bundle with `barcode-conveyor/barcode_scanner.py`, a Node-RED guide, `securebag/` samples, and `bhs-simulation/` data. Those resources are **not present in this checkout**. Obtain the relevant scanner/guide from the organizer bundle when integrating; do not assume those paths already exist locally.

The source context for these additions is the team's supplied tentative notes and physical conveyor tutorial (`Pasted text.txt` / `Pasted text(1).txt`, November 7). Broader ideas in those notes are exploratory, not committed requirements.
