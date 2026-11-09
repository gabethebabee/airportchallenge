# Jetson camera -> MQTT -> dashboard, using AprilTags

## Staff gstCamera capture option

`--capture-backend jetson` uses the staff's `jetson.utils.gstCamera` method. It
requests 1280x720 by default, allows four seconds to initialize, then calls
`CaptureRGBA(zeroCopy=1)`. CUDA pixels are synchronized, mapped through NumPy and
copied to uint8 BGR frames for the existing detector/JPEG publisher. No
`jetson.inference` or `glDisplay` window is needed. NVIDIA libraries must already
be installed in that Jetson's Python environment; the laptop does not need them.

Copy the updated `team8apriltag_camera.py` and new `team8jetson_capture.py` to the
existing Jetson project folder. No detector rebuild is needed. Stop the previous
publisher for the camera being tested, and close any staff test program using
that same device. Then, for example, test device 1:

```bash
python3 team8apriltag_camera.py --capture-check --capture-backend jetson --camera 1
```

Use the actual device index from `--camera-info`, not necessarily 1. Optional
`--capture-width 640 --capture-height 480` changes the requested capture size if
1280x720 fails or two cameras exceed the available USB bandwidth. Requested
resolution is not a guarantee that the device/installed driver can support it.

After capture succeeds, camera B can run using its distinct existing topics:

```bash
python3 -u team8apriltag_camera.py --backend bundled --capture-backend jetson --camera 1 --checkpoint B --frame-topic Conveyor4/camera/B/frame --tags-topic Conveyor4/apriltags/B --status-topic Conveyor4/camera/B/status
```

Camera A may keep using its working V4L2 method. Both backends produce the same
MQTT protocol, so no dashboard or sensor changes are required for this adapter.
The adapter is tested with simulated NVIDIA objects; actual capture still needs
the onsite five-frame check. Staff's original sample uses a display loop; its
bare `except` continues into rendering after a failed read. This adapter instead
rejects that failed frame, so it cannot silently reuse the previous image.

## Two physical cameras: laptop update, no Jetson rebuild

The laptop dashboard now supports independent A/B camera inboxes and a **View
camera** selector. Both feed the same persistent tag journeys. Restart the laptop
dashboard to load its new Python subscriptions, then hard-refresh the browser.
The existing Jetson publisher already supports all the options below; no script
upload, detector rebuild or configuration editing is required on the Jetson.

First identify device indexes from the laptop's PowerShell:

```powershell
ssh ideasclinic@172.18.26.168 "cd ~/team8jetson && python3 team8apriltag_camera.py --camera-info"
```

Do not assume the second physical camera is `/dev/video1`: some webcams expose
multiple video interfaces. Test its candidate index (replace `1` as needed):

```powershell
ssh ideasclinic@172.18.26.168 "cd ~/team8jetson && python3 team8apriltag_camera.py --capture-check --capture-backend v4l2 --camera 1"
```

Stop the previous one-camera/AB publisher before starting camera A, so it does not
keep the device occupied or generate a B event within A's image. If an old SSH
session exited but its camera process remains alive, inspect it before restarting;
do not start competing publishers on one camera or shared topic.

**Camera A**, in one PowerShell window (existing original topics):

```powershell
ssh -t ideasclinic@172.18.26.168 "cd ~/team8jetson && python3 -u team8apriltag_camera.py --backend bundled --capture-backend v4l2 --camera 0 --checkpoint A"
```

**Camera B**, in another PowerShell window (use the device index that passed):

```powershell
ssh -t ideasclinic@172.18.26.168 "cd ~/team8jetson && python3 -u team8apriltag_camera.py --backend bundled --capture-backend v4l2 --camera 1 --checkpoint B --frame-topic Conveyor4/camera/B/frame --tags-topic Conveyor4/apriltags/B --status-topic Conveyor4/camera/B/status"
```

Leave both windows running. Present the same tag family/ID at physical A then
physical B. In this arrangement the **whole image** of each camera is its assigned
checkpoint; the earlier left/gap/right split applies only to `--checkpoint AB`.
Bag timing continues regardless of the selected preview. A stale/offline camera
does not replace the other image, and historical journeys remain visible.

| Camera | Frame topic | Tag topic | Status topic |
| --- | --- | --- | --- |
| A | `Conveyor4/camera/frame` | `Conveyor4/apriltags` | `Conveyor4/camera/status` |
| B | `Conveyor4/camera/B/frame` | `Conveyor4/apriltags/B` | `Conveyor4/camera/B/status` |

Optional laptop configuration keys for B are `camera_b_topic`, `tags_b_topic`,
and `camera_b_status_topic`. Their defaults match the command above. Sensor and
motor FLAG behavior is unchanged. Each camera publishes about one preview per
second by default; operating both increases traffic and native detector CPU use.

## Offline detector included: start here on this Jetson

The Jetson reported that all preinstalled detector options are missing. The ZIP
now includes a pinned copy of [swatbotics/apriltag](https://github.com/swatbotics/apriltag)
C source and its Python wrapper, plus a local build installer. No internet, pip,
sudo, CMake or OpenCV replacement is used. The Jetson needs an existing C compiler
(`cc` or `gcc`), its normal C development headers/pthread library, and NumPy.

After copying/extracting the updated ZIP, run inside `~/team8jetson`:

```bash
python3 team8install_apriltag.py --check
python3 team8install_apriltag.py
python3 team8apriltag_camera.py --check --backend bundled
```

The installer verifies the archive hash, compiles a native library for that
machine, and checks that a generated tag36h11 ID 0 is decoded while a blank image
produces no tag. Success says `SELF-TEST PASSED`. If compilation fails, send the
full error; missing development tools may require staff's offline packages.
This has no automatic network/package installation fallback.

Then run the publisher with `--backend bundled` and the capture options that
passed the independent camera test. For a verified USB camera on device 0:

```bash
python3 team8apriltag_camera.py --backend bundled --capture-backend v4l2 --camera 0 --checkpoint AB
```

This does not solve the separate camera-frame failure: capture still has to pass.
There is no `--preview-only` on the detection command, since that disables tags.

The source commit and archive SHA-256 are in `team8apriltag-source.json`.
The source archive retains upstream copyright/license notices. The local copy of
the wrapper changes only the expected native library basename to
`team8libapriltag.so`; its matching upstream C code is unchanged. Generated files
live under `team8apriltag_native/`; no global Python installation is modified.
Our integration/build scripts contain explanatory comments. The bundled
third-party implementation retains its original comments and file structure.

The Jetson reads its attached camera. It recognizes printed AprilTags, sends checkpoint events to the lab MQTT broker, and publishes small JPEG previews. The dashboard subscribes to that broker and displays them under **Camera feed & AprilTag checkpoints**, below the six motor readings. The browser never opens the Jetson camera directly.

## 1. Copy and check on the Jetson

Extract the latest `team8jetson.zip` onto a USB drive. Copy its `team8jetson` folder onto the Jetson. Open a terminal inside that folder and run:

```bash
python3 team8apriltag_camera.py --check
```

This checks Python, OpenCV, an AprilTag detector, and Paho without opening the camera or contacting the broker. The code supports Python 3.6.9. It tries existing OpenCV AprilTag dictionaries, then `pupil_apriltags`, then `apriltag`. One working backend is required; ordinary barcode support alone is insufficient.

**If this check fails, use the bundled offline build above and send its exact error if it fails.** This project does not install packages automatically. Do not blindly replace the Jetson's prepared OpenCV. Offline packages/native libraries must match the Jetson's architecture and Python 3.6, rather than your Windows laptop. Python syntax compatibility does not guarantee these native dependencies are installed.

To test just the camera preview if a detector is missing:

```bash
python3 team8apriltag_camera.py --preview-only --camera 0
```

That mode explicitly disables tag detection and timing events.

## 2. Start the actual camera publisher

If OpenCV opens the camera but then reports `Camera stopped supplying frames`,
test capture independently of MQTT/detection:

```bash
python3 team8apriltag_camera.py --camera-info
python3 team8apriltag_camera.py --capture-check --capture-backend v4l2 --camera 0
```

`--camera-info` lists Linux device indexes/names. For a USB camera, explicit V4L2
avoids OpenCV's automatic GStreamer selection. A five-frame successful check
confirms basic capture; it does not guarantee continued operation. If it passes,
add `--capture-backend v4l2` to the publisher command. If it fails, send the device
list and exact capture-check output; the camera index, device ownership, format
or driver/pipeline still needs investigation. CSI cameras may need the staff's
GStreamer pipeline instead. The capture check needs no AprilTag detector or Paho.

The publisher now requires a nonempty startup frame before starting MQTT and
announcing that the camera is running. The previous unsupported buffer-size
setting has been removed; this does not repair a broken camera/driver.

Close any other program using that camera, then run:

```bash
python3 team8apriltag_camera.py --camera 0 --checkpoint AB --broker 129.97.228.106
```

Leave that terminal running. Ctrl+C stops it. Add `--display` to also show a camera window on the Jetson screen. If device 0 is wrong, staff can identify the correct index (`--camera 1`, for example). A CSI ribbon camera may require the staff-provided GStreamer pipeline instead:

```bash
python3 team8apriltag_camera.py --pipeline 'STAFF_PROVIDED_PIPELINE' --checkpoint AB
```

The placeholder is not a working pipeline. USB cameras generally use the device-index form. Only one process should own a camera.

## 3. Start the dashboard

On either the laptop or the Jetson, open a second terminal in the project folder:

```bash
python3 team8dashboard.py
```

On Windows use `python` if that is your installed command. Open `http://127.0.0.1:8080/` on the same machine and expand **Camera feed & AprilTag checkpoints**. Restart an older dashboard process to load these changes.

Both machines must be able to reach **129.97.228.106:1883**. Internet access is unnecessary at runtime, but a working local route to the broker is essential. MQTT does not bypass eduroam isolation or a disconnected Ethernet cable. If only the Jetson reaches the lab network, run the dashboard there too and use its small screen. No direct laptop-to-Jetson SSH connection is needed for this setup.

## 4. Print tags and test A-to-B

Matching test images are now included: `team8tag36h11-0.png`,
`team8tag36h11-1.png`, and `team8tag36h11-2.png`. They use exact codes from
the bundled detector's source table, with the same cell layout as its passing
Jetson self-test. Regenerate with `python3 team8make_tags.py` (standard library
only). Start by presenting **one** image, fully visible and flat, with its white
margin preserved. Hold it still until the dashboard displays its family and ID.
An active preview proves image transport, not recognition of an arbitrary marker.

Use real **tag36h11** AprilTag images, each with a different ID. Start with IDs **0, 1, and 2**. Get the original images from the [AprilRobotics tag image repository](https://github.com/AprilRobotics/apriltag-imgs/tree/master/tag36h11). Preserve the white margin, print clearly, keep the tag flat and well lit, and make it large enough to occupy many camera pixels. These are square AprilTags, not QR codes or ordinary barcodes.

The default `AB` setup uses **one camera with a wide view**:

1. The left 40% of the image is checkpoint A.
2. The middle 20% is a gap to reduce boundary jitter.
3. The right 40% is checkpoint B.
4. Seeing an ID enter A starts its journey. Seeing that same family/ID enter B finishes it.

Move a printed tag from left to right. The preview shows tag outlines and checkpoint labels. The journey row shows elapsed seconds and whether that matches your chosen standard. Change that standard inside the camera panel; existing journeys keep their original limits. A missing B arrival raises an overdue alert. Acknowledge means someone saw it; only a B observation resolves it.

If travel is right to left, add `--a-side right`. Adjust the regions with `--split-x 0.5 --gap 0.1`. These are image positions, not measured physical distances. The detector runs up to 5 times per second by default, so a tag must be visible long enough in each region. Seeing B first does not invent an A departure. Repeated views at A do not reset its clock. After completion, a new A can start another trip, subject to the existing 3-second A debounce.

**One-camera mode remains supported on camera A's original topics.** For two
physical checkpoints, use the two-camera setup at the top of this guide with
separate topics/inboxes. Each physical bag needs its own family/ID while in
flight; two bags with the same printed ID cannot be distinguished.

## MQTT topics and limits

| Topic | Content | Delivery |
| --- | --- | --- |
| `Conveyor4/camera/frame` | Binary envelope containing header + JPEG | QoS 0, not retained |
| `Conveyor4/apriltags` | JSON visible tags and checkpoint entry events | QoS 1 for events, otherwise 0; not retained |
| `Conveyor4/camera/status` | JSON online/offline status and session | QoS 1, retained, offline last will |

These are new application topics. They do not replace speed/current inputs or `Conveyor4/FLAG`. Publisher CLI overrides and dashboard `team8conveyor4.local.json` overrides must agree if topic names change. The dashboard config keys are `camera_topic`, `tags_topic`, and `camera_status_topic`.

The default preview is **1 JPEG per second**, width at most 480 pixels, quality 45, and at most 64,000 JPEG bytes. It is a lightweight preview, not smooth video. Increase `--fps` cautiously (maximum 5); camera traffic shares the broker with sensor messages. Frames older than 1.5 seconds before sending are dropped. Received images and visible-tag metadata expire after 4 seconds without refresh. Retained images/events are ignored. Image bytes stay in memory rather than being saved.

The frame envelope is `T8J1`, four bytes of unsigned big-endian header length, UTF-8 JSON header, then raw JPEG. The header supplies conveyor, session, sequence, and capture-age metadata. Tags contain `family`, `tag_id`, and `checkpoint`; event IDs prevent duplicate QoS 1 deliveries from creating duplicate records. Restart/session order checks reject old frames after a new publisher becomes active.

Timing uses the **dashboard's event receipt clock**, so network delays and detector sampling affect accuracy. Offline clocks need not agree. No offline event archive is replayed intentionally, but QoS 1 delivery/reconnect delays can still affect timing. Treat this as a hackathon checkpoint monitor, not precision instrumentation. An overdue tag means B is unconfirmed, which can also mean a hidden tag, camera outage, or dropped connection; it does not prove a jam.

## Files and existing history

- `team8apriltag_camera.py`: Jetson capture, detector adapters, checkpoint regions, and MQTT publication.
- `team8vision.py`: bounded frame decoding, freshness checks, and AprilTag events into the journey store.
- `team8conveyor4.py`: existing sensor monitor, plus isolated MQTT camera subscriptions.
- `team8conveyor4.html`, `.css`, `.js`: small-screen motor dashboard and expandable camera/tag panel.
- `team8transit.py`: persistent journey timing; its older database field is still called `barcode`, but new values look like `apriltag:tag36h11:0`. Existing history is preserved.

`team8barcode_scanner.py` now forwards to the AprilTag publisher for filename compatibility. The old barcode/HTTP scanning instructions and options are superseded by this guide. The default Conveyor 4 dashboard uses AprilTag identification; old legacy dashboard assets remain for explicit legacy configurations.

Camera loss and tag lateness do not change the **motor** FLAG. That boolean continues to depend on fresh speed/current measurements and their 15% / more-than-10-second rule. The actual current topic still needs to be configured if staff have not supplied it; voltage is not current.

OpenCV's documented [AprilTag dictionaries](https://docs.opencv.org/3.4.20/d9/d6a/group__aruco.html) are optional build capabilities. The physical Jetson camera, installed detector, and lab broker must still be tested onsite.
