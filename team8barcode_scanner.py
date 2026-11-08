"""Compatibility entry point: identification now uses AprilTags, not barcodes.

Use team8apriltag_camera.py directly for its --check and MQTT options.
No pyzbar/Code128 parser is imported by this entry point anymore.
"""
from team8apriltag_camera import main


# SECTION: Preserve the old script filename without maintaining two camera owners.
# Existing --camera/--checkpoint arguments still work. Transport options now use
# the AprilTag publisher CLI; previous HTTP barcode commands should be updated.
if __name__ == '__main__':
    print('AprilTags replaced barcode scanning. Starting team8apriltag_camera.py')
    main()
