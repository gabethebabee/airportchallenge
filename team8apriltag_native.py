"""Load the project-local AprilTag C library through its bundled Python wrapper."""
import importlib.util
from pathlib import Path


# SECTION: Keep the detector local to this project, without pip or system changes.
# The installer compiles the matching upstream C source on the target Jetson.
# Loading that same source's wrapper avoids mixing incompatible native APIs.
def load_detector(family='tag36h11', decimate=2.0):
    root = Path(__file__).resolve().parent / 'team8apriltag_native'
    wrapper = root / 'team8upstream_apriltag.py'
    if not wrapper.is_file() or not (root / 'team8libapriltag.so').is_file():
        raise RuntimeError('Run python3 team8install_apriltag.py on the Jetson first')
    spec = importlib.util.spec_from_file_location('team8upstream_apriltag', str(wrapper))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Detector(module.DetectorOptions(families=family, nthreads=2,
                           quad_decimate=decimate), searchpath=[str(root)])


# SECTION: A synthetic tag and blank image verify native decoding without a camera.
# ID 0's 36-bit code comes from the bundled upstream tag36h11.c table. The image
# includes its black border and a broad white margin, enlarged without smoothing.
# This proves library/wrapper agreement; it does not validate camera capture.
def self_test(detector=None):
    import numpy as np
    detector = detector or load_detector(decimate=1.0)
    cells = np.full((12,12),255,dtype=np.uint8)
    cells[2:10,2:10] = 0
    code = 0xD5D628584
    for index in range(36):
        cells[3+index//6,3+index%6] = 255 if code & (1 << (35-index)) else 0
    image = np.repeat(np.repeat(cells,24,axis=0),24,axis=1)
    found = detector.detect(image)
    if not any(int(tag.tag_id) == 0 and int(tag.hamming) == 0 for tag in found):
        raise RuntimeError('Native detector self-test could not read generated tag36h11 ID 0')
    if detector.detect(np.full_like(image,255)):
        raise RuntimeError('Native detector incorrectly found a tag in a blank image')
    return 'SELF-TEST PASSED: tag36h11 ID 0 decoded; blank image rejected'


if __name__ == '__main__':
    print(self_test())
