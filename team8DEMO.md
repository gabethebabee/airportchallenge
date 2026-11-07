# Demo and acceptance checklist

## Test before presenting

Proposed checks; these have not been executed against an implementation. Record actual results instead of marking them complete by assumption.

| Scenario | Expected result | Actual |
| --- | --- | --- |
| Startup with no input | UNKNOWN; no fabricated normal status | Pending |
| Moving bag | NORMAL; correct zone/track and source label | Pending |
| Brief pause shorter than 3 seconds | No jam incident | Pending |
| Stationary bag, belt confirmed running | One JAM incident after 3 seconds plus processing latency | Pending |
| Stationary bag, belt state unavailable | SUSPECTED_STOPPAGE with explanation | Pending |
| Intentional belt stop | PAUSED; no new jam incident | Pending |
| Acknowledge active jam | Acknowledgement recorded; jam remains visible | Pending |
| Bag resumes motion for 2 seconds | Incident resolves; history retained | Pending |
| Bag disappears during jam | Review needed; do not claim confirmed recovery | Pending |
| No valid data for more than 2.5 seconds | UNKNOWN; previous incident retained | Pending |
| Low confidence or track changes | No persistence carried over to a different/uncertain track | Pending |
| Malformed, repeated, or old event | No crash, duplicate incident, or false freshness | Pending |

## Synthetic replay expectations

Use `team8demo_events.json` with event timestamps as the replay clock. The first moving event is at t=0. Stationarity begins at t=2; JAM should appear at t=5. Movement resumes at t=6 and should resolve the incident at t=8. The intentional stop at t=9–12 is PAUSED. t=13 is NORMAL. At t>15.5, the stream is stale; t=17 is a replay clock checkpoint, **not an observation**, and should show UNKNOWN.

Only feed the `observations` array into the observation handler. `checkpoints` are assertions evaluated by a replay driver. There is no replay driver in this scaffold yet.

## Short pitch

1. Problem: a stalled bag needs a location and visual context so an operator can investigate.
2. Show normal movement in one zone.
3. Create a controlled stoppage using the organizer-approved demo method; show the alert and evidence.
4. Acknowledge it, then restore movement and show resolution/history.
5. Show how intentional stops and lost telemetry are distinguished.
6. Explain limits: one zone, calibrated camera view, temporary tracks, and human response required.

Do not claim cost savings, predictive maintenance, airport-wide coverage, or measured accuracy without evidence. If belt state is not measured, demonstrate a suspected stoppage rather than asserting a confirmed jam.

## Measurements to collect

- Time from the first stationary observation to alert, across several repetitions.
- False alerts during normal motion and intentional pauses; record number of trials.
- Hardware/software used, camera position, threshold settings, and observed failure cases.

## Final handoff

- [ ] Write exact install/run commands here once the implementation and dependencies are known.
- [ ] Verify a clean start on the presentation machine.
- [ ] Verify offline replay and source labels.
- [ ] Capture a backup demonstration and identify whether it uses live or recorded input.
- [ ] Preserve the working commit/files before the 2:30 p.m. Sunday deadline.
- [ ] Confirm organizer submission requirements and required AI-use disclosure, if any.
