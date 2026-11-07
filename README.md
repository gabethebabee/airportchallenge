# Team 8 — Baggage stoppage monitoring

## Start here

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
