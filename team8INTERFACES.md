# Proposed integration contract — version 1

This contract is a team proposal. The organizer's barcode payload is separate and does not contain movement, belt state, or timestamps.

## Existing organizer integration (from supplied tutorial)

| Topic | Payload | Notes |
| --- | --- | --- |
| `Conveyor3/barcode_value` | Raw barcode text | Tutorial specifies QoS 0 |
| `Conveyor3/baggage_routing` | `{"barcode":"JD\u007c23.4\u007cRED\u007cGA2","in_picklist":true,"conveyor":"conveyor_1"}` | Tutorial specifies QoS 1 |

Confirm the assigned station and routing meaning with organizers before connecting. A topic's station number and a payload's destination conveyor need not match. Keep broker settings local; use organizer connection instructions. Preserve baseline Node-RED flows. The monitor should not publish motor/diverter commands or change existing interlocks.

## Team observation event

Proposed topic: `team8/observations`. All producers, including offline replay, should emit this shape:

```json
{
  "schema_version": 1,
  "event_id": "demo-001",
  "timestamp": "2026-11-07T18:00:00Z",
  "source": "synthetic",
  "zone_id": "zone_1",
  "track_id": "track_1",
  "bag_present": true,
  "motion_px_per_s": 40.0,
  "belt_running": true,
  "confidence": 0.95,
  "image_path": null
}
```

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer 1 |
| `event_id` | Unique producer event ID; deduplicate QoS 1 repeats |
| `timestamp` | UTC observation time; use elapsed observation time during replay |
| `source` | `synthetic`, `recorded`, or `live`; always visible in UI |
| `zone_id` | Known monitored region |
| `track_id` | Temporary track within the source/zone; null when no bag is visible |
| `bag_present` | True/false; false is observed absence, not missing camera data |
| `motion_px_per_s` | Nonnegative image-plane speed; null if unmeasurable |
| `belt_running` | true, false, or null when not measured; never infer belt state from bag motion |
| `confidence` | Detection confidence from 0 to 1; not a probability that a jam exists |
| `image_path` | Optional local evidence image; null if unavailable |

Compute motion from displacement over elapsed time for the same track within a fixed camera region. Camera movement, lighting, occlusion, and identity switches can invalidate that estimate. Measure in pixels/second initially; do not report physical speed without calibration.

## Proposed state rules

- Reject invalid values; discard duplicates and older/out-of-order observations per source/zone. Invalid observations must not refresh the last-valid-observation timer.
- Default **UNKNOWN** until valid observations arrive. Stale telemetry, low confidence, missing motion for a present bag, or a lost track leads to UNKNOWN; absence of updates never means normal operation.
- A present bag below the configured motion threshold starts a candidate timer for that source/zone/track. Require consecutive qualifying observations across the persistence window. Movement, observed absence, a changed track, a known belt stop, an invalid observation, or a telemetry gap resets the candidate timer.
- If stationary for the persistence window with `belt_running=true`, raise **JAM**. If belt state is null, raise **SUSPECTED_STOPPAGE** and explain that belt state is unavailable.
- If `belt_running=false`, show **PAUSED** and suppress new jam alerts. Retain existing incidents in history.
- Movement shows **NORMAL**. Sustained movement for the recovery window resolves an active incident. Observed absence alone does not prove recovery; flag an active incident for operator review if the bag disappears.
- Telemetry loss during an active incident shows UNKNOWN while retaining that incident. Acknowledgement never substitutes for recovery.
- Record one incident per episode; update its last-seen time rather than flooding new alerts. Resolve and rearm before issuing a new episode.

Store incident ID, source, zone, track, first stationary time, raised time, state, acknowledged time, resolved time, and evidence path. Use monotonic elapsed time for live timeout handling; replay uses event timestamps. Do not compare the dated synthetic fixture to the current wall clock.
