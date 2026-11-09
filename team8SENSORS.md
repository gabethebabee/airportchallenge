# Connect actual Conveyor 4 sensor data

## Existing broker stream discovered

The onsite inspection confirmed `Conveyor4/get_belt_speed` and
`Conveyor4/get_motor_current`, initially delivered as retained numeric values.
The dashboard now subscribes to that current topic by default. It assumes the
existing cm/s and amperes scale of 1; confirm units/calibration with the publisher.
No Node-RED bridge is required if these topics continue receiving live updates.

Retained readings appear in the cards as **Last known — retained; source age
unknown**. They do not calibrate averages, verify motor FLAG or advance distance,
runtime, deviation timers or service ETA. A retained message's receipt time does
not reveal when the sensor measured it. Fresh incoming measurements take over
automatically; if they stop, the cards show last-known values while health is
unverified. Restart the laptop dashboard to load the topic/config changes.

`Conveyor4/get_motor_voltage` has not yet been observed in the shared inspection
output. Its card remains unknown until that topic supplies a real measurement.
The read-only bridge below is a fallback for missing publications, not a required
replacement for the discovered stream. A local JSON config, if present, overrides
defaults; ensure its `current_topic` matches the confirmed topic too.

The MQTT broker relays messages; it cannot provide measurements that nobody is
publishing. The supplied `Node-RED stuff` flow identifies the server-side Groov
inputs. The prepared `team8conveyor4_sensors.json` bridge reads those inputs and
publishes values on the dashboard's existing topics. It is not deployed yet.

| Measurement | Supplied hardware source | Published topic | Dashboard |
| --- | --- | --- | --- |
| Belt speed | Channel 0 encoder, converted to cm/s | `Conveyor4/get_belt_speed` | Speed, distance, runtime, service estimate |
| Motor voltage | Channel 7 analog output readback, volts | `Conveyor4/get_motor_voltage` | Voltage card |
| Actual current | Not specified in supplied files | Staff must supply a calibrated input/topic | Unknown until mapped |

An encoder measures movement; it does not measure current or voltage. Channel 7
is voltage readback rather than an independently calibrated motor-terminal
measurement. Do not convert its voltage into amperage without the actual sensor
and calibration information.

## Activate on the assigned PLC/server

1. Get the **assigned Conveyor 4 Node-RED editor URL** from staff. This is the
   PLC's Node-RED runtime, not the MQTT broker's port 1883 or the Jetson terminal.
2. Export/backup the current flow. Import `team8conveyor4_sensors.json` as a new
   tab. It is also downloadable from the dashboard's MQTT setup section.
3. Verify the Groov device is the assigned local PLC, encoder channel is 0 and
   voltage readback channel is 7. Those mappings come from the supplied flow.
4. Check MQTT broker `129.97.228.106:1883` and any lab authentication requirements.
5. Disable duplicate exporters publishing these **same sensor topics** so two
   producers do not interleave readings. This bridge has no motor output writes;
   existing motor control stays on its own flow.
6. Enable the imported read-only tab and deploy it. No motor run/stop commands
   are included. Confirm actual samples in Node-RED Debug and in the dashboard.

The encoder calculation needs two real observations. First readings, gaps over
3 seconds and counter rollback send JSON null, meaning unknown. Inputs poll at
1 second with deadband 0, but actual unchanged-value reporting depends on the
installed Groov node; verify it while stationary. The dashboard expires stale
readings rather than reporting invented zero speed.

The conversion uses 700 counts/revolution, pulley ratio 4 and circumference
10.5 × 3.14 cm, copied from the supplied station calculation. Confirm constants
against the assigned testbed before presenting measured distance as calibrated.

To inspect existing publications without changing outputs, on the laptop run:

```powershell
python -u team8mqtt_inspect.py --topic Conveyor4/get_belt_speed --topic Conveyor4/get_motor_voltage --seconds 10
```

For current, ask staff for the actual input channel, sensor scaling, unit and
message/topic. If an actual current topic already exists, set `current_topic`
in `team8conveyor4.local.json` to that verified topic, with scale/key if required.
Otherwise staff need to add the calibrated current input to the server exporter.
There is no current-channel guess in the provided bridge. Motor FLAG remains
unverified until both real current and speed are fresh.

## Reset bag journeys

The camera panel's **Reset journeys** now clears the displayed trips and overdue
alerts locally in the browser, without a backend POST. It stores the highest
cleared journey ID in local storage, so old records cannot reappear on the next
poll, after a reload, or when switching cameras. New journeys with higher IDs
remain visible. **Show cleared** restores the original view. This applies to the
current browser/origin; other browsers retain their own views. If browser storage
is blocked, the reset lasts only for that tab. Server records and tracking state
are retained, and no camera/motor/total/timing setting changes.

The browser reset does not restart an already-active server journey for the same
bag. Finish that trip at B or use a different tag to create a new visible trip.
New server journeys can still create future overdue warnings.

Hard-refresh the browser for this frontend reset change. Restart the laptop Python
dashboard for sensor mapping/backend updates. The camera programs on the Jetson
do not need updating for these changes.
