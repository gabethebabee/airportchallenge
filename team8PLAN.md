# Team 8 build plan

## Available work time

- Saturday November 7, 2026: remaining time until **5:00 p.m.**
- Sunday November 8, 2026: **9:00 a.m.–2:30 p.m.** (5.5 hours)
- All times are Waterloo local time (America/Toronto).

## MVP and boundaries

One monitored conveyor zone, one observation producer, one dashboard. Show zone, bag track ID, movement status, alert age, and camera evidence if available. Give operators an acknowledgement action. Acknowledgement records receipt; it does not clear the physical condition.

Barcode observations can provide identity context but cannot establish a stoppage. Detect movement across successive camera observations. A camera track ID is temporary and must not be presented as a globally unique bag ID.

Defer motor maintenance prediction, motor-current hardware, airport-wide pathfinding, flight cancellation handling, multiple-camera identity matching, cloud infrastructure, and automatic PLC control. Motor runtime alone does not establish motor health. Add stretch work only after the full demo passes.

## Suggested ownership

Assign names together; no owners are assumed here. With two people, combine integration and detection. With more people, give one person the pitch/demo evidence.

| Workstream | Deliverable |
| --- | --- |
| Vision | Timestamped movement observations for one tracked bag/zone |
| Dashboard | Clear normal, jam, paused, and unknown states; acknowledgement |
| Integration/demo | Replay data, connect producer, verify scenarios, capture backup |

## Saturday: get one vertical slice working

| Block | Target |
| --- | --- |
| First 30 minutes | Confirm zone/camera access, choose movement approach, assign owners, agree event fields |
| Main build block | Build camera observations and dashboard independently against the same event contract |
| By 4:00 p.m., or immediately if already later | Integrate; stop adding features |
| 4:00–5:00 p.m. | Run normal → jam → recovery; record blockers and preserve a working offline replay |

If hardware access or tracking blocks progress, use replay immediately to complete the dashboard. A recorded camera clip is the next fallback; label its source. Do not spend the entire work window fighting the lab network.

## Sunday: integration and evidence

| Time | Target |
| --- | --- |
| 9:00–10:00 | Resolve the single biggest blocker; connect camera observations if feasible |
| 10:00–11:00 | Tune thresholds on the actual belt; test intentional stops and occlusion |
| 11:00–12:00 | Execute acceptance checks; fix failures; collect measured detection times |
| 12:00–1:00 | Prepare a short pitch and record a backup demo |
| 1:00–2:00 | Rehearse end to end; fix only demo-blocking issues |
| 2:00–2:30 | Freeze changes, save final files, verify launch instructions and submission requirements |

## Decisions to settle first

- Can you read actual belt-running state? If not, show it as unknown and label stationary-bag alerts as suspected stoppages.
- Which camera/model works on the available machine? Prove one short clip before committing to it. Avoid training a model during the hackathon.
- How will a temporary track persist through a brief missed detection?
- What motion threshold and persistence window fit the actual camera resolution, angle, and belt speed?

Success is a repeatable detection-and-alert demonstration with honest limitations, not the number of features listed.
