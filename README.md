# Team 8 — Baggage stoppage monitoring

## Start here

Detect a bag that has stopped unexpectedly, identify its monitored zone, and show an actionable alert with a camera view or last observed image.

This is the proposed MVP based on the team's notes, not an implemented system. The existing `team8dashboard.py` is empty. No live hardware integration has been verified in this checkout.

| File | Purpose |
| --- | --- |
| `team8PLAN.md` | Scope, work blocks, milestones, and fallback |
| `team8INTERFACES.md` | Shared observation format, state rules, and MQTT integration |
| `team8config.example.json` | Proposed local settings; thresholds need calibration |
| `team8demo_events.json` | Synthetic observations for an offline demo |
| `team8DEMO.md` | Acceptance checks and presentation outline |
| `team8dashboard.py` | Existing dashboard entry point; implementation pending |

## Build order

1. Agree on the event contract in `team8INTERFACES.md`.
2. Display the synthetic sequence in the dashboard and verify the state transitions manually.
3. Connect one camera/zone to the same contract.
4. Demonstrate normal movement, an unexpected stoppage, recovery, and lost telemetry.

Keep the dashboard usable offline. Label synthetic input clearly. Do not claim that a mock demonstration is connected to the conveyor.

## What is available versus referenced

This checkout initially contains only `README.md` and an empty `team8dashboard.py`. The supplied notes reference a separate challenge bundle with `barcode-conveyor/barcode_scanner.py`, a Node-RED guide, `securebag/` samples, and `bhs-simulation/` data. Those resources are **not present in this checkout**. Obtain the relevant scanner/guide from the organizer bundle when integrating; do not assume those paths already exist locally.

The source context for these additions is the team's supplied tentative notes and physical conveyor tutorial (`Pasted text.txt` / `Pasted text(1).txt`, November 7). Broader ideas in those notes are exploratory, not committed requirements.
