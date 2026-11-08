# Jetson camera -> MQTT -> dashboard, using AprilTags

The Jetson reads its attached camera. It recognizes printed AprilTags, sends checkpoint events to the lab MQTT broker, and publishes small JPEG previews. The dashboard subscribes to that broker and displays them under **Camera feed & AprilTag checkpoints**, below the six motor readings. The browser never opens the Jetson camera directly.

## 1. Copy and check on the Jetson

Extract the latest `team8jetson.zip` onto a USB drive. Copy its `team8jetson` folder onto the Jetson. Open a terminal inside that folder and run:

```bash
python3 team8apriltag_camera.py --check
```

This checks Python, OpenCV, an AprilTag detector, and Paho without opening the camera or contacting the broker. The code supports Python 3.6.9. It tries existing OpenCV AprilTag dictionaries, then `pupil_apriltags`, then `apriltag`. One working backend is required; ordinary barcode support alone is insufficient.

**If this check fails, show its exact output to staff.** This project does not install packages automatically. Do not blindly replace the Jetson's prepared OpenCV. Offline packages/native libraries must match the Jetson's architecture and Python 3.6, rather than your Windows laptop. Python syntax compatibility does not guarantee these native dependencies are installed.

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

Use real **tag36h11** AprilTag images, each with a different ID. Start with IDs **0, 1, and 2**. Get the original images from the [AprilRobotics tag image repository](https://github.com/AprilRobotics/apriltag-imgs/tree/master/tag36h11). Preserve the white margin, print clearly, keep the tag flat and well lit, and make it large enough to occupy many camera pixels. These are square AprilTags, not QR codes or ordinary barcodes.

The default `AB` setup uses **one camera with a wide view**:

1. The left 40% of the image is checkpoint A.
2. The middle 20% is a gap to reduce boundary jitter.
3. The right 40% is checkpoint B.
4. Seeing an ID enter A starts its journey. Seeing that same family/ID enter B finishes it.

Move a printed tag from left to right. The preview shows tag outlines and checkpoint labels. The journey row shows elapsed seconds and whether that matches your chosen standard. Change that standard inside the camera panel; existing journeys keep their original limits. A missing B arrival raises an overdue alert. Acknowledge means someone saw it; only a B observation resolves it.

If travel is right to left, add `--a-side right`. Adjust the regions with `--split-x 0.5 --gap 0.1`. These are image positions, not measured physical distances. The detector runs up to 5 times per second by default, so a tag must be visible long enough in each region. Seeing B first does not invent an A departure. Repeated views at A do not reset its clock. After completion, a new A can start another trip, subject to the existing 3-second A debounce.

**One active camera publisher is supported by this dashboard inbox.** If the camera cannot see both physical checkpoints, this one-camera arrangement cannot measure the whole journey. `--checkpoint A` or `B` can test a single checkpoint, but two simultaneous camera publishers require a separate per-camera inbox/topic extension. Do not run competing publishers on these shared topics. Each physical bag needs its own family/ID while in flight; two bags with the same printed ID cannot be distinguished.

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
