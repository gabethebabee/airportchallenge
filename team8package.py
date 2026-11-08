"""Create a USB deployment ZIP without private databases, tokens or sample readings."""
from pathlib import Path
import zipfile


# Deliberate allowlist: never sweep the folder, because it may contain real bag databases or credentials.
FILES = [
    'team8vision.py', 'team8apriltag_camera.py', 'team8APRILTAGS.md',
    'team8conveyor4.py', 'team8conveyor4.html', 'team8conveyor4.css', 'team8conveyor4.js',
    'team8conveyor4.example.json', 'team8CONVEYOR4.md',
    'team8dashboard.py', 'team8dashboard.html', 'team8dashboard.css',
    'team8dashboard.js', 'team8live.js', 'team8transit.py',
    'team8monitor.py', 'team8conveyor_control.py', 'team8barcode_scanner.py',
    'team8mqtt_inspect.py', 'team8mqtt.example.json', 'team8mqtt.camera.example.json',
    'team8sensor_flow.json', 'team8conveyor_flow.json', 'team8build_sensor_flow.py',
    'team8LIVE.md', 'team8CONTROL.md', 'team8TIMING.md', 'team8CODE_GUIDE.md',
]


# Bundle an explicit allowlist of deployable files; exclude SQLite records, tokens and local
# configuration.
# Check every named deployment file exists before building the ZIP. Only allowlisted
# source/config/documentation files enter the archive, excluding local databases, private scan
# history and token-bearing configuration.
def main():
    root = Path(__file__).resolve().parent
    for name in FILES:
        if not (root / name).is_file():
            raise FileNotFoundError(name)
    with zipfile.ZipFile(root / 'team8jetson.zip', 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name in FILES:
            bundle.write(root / name, 'team8jetson/' + name)
    print('Created team8jetson.zip - read team8APRILTAGS.md for camera setup; team8CONVEYOR4.md for sensors')


if __name__ == '__main__':
    main()
