"""Test NVIDIA capture conversion with fake CUDA/camera objects, no Jetson required."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
from team8jetson_capture import JetsonCapture
from team8apriltag_camera import open_capture


# SECTION: Mock only the NVIDIA binding; real NumPy performs the image conversion.
# A distinct fake camera lets tests check device selection, zero-copy requests,
# synchronization, colour order and ownership without accessing any hardware.
class JetsonCaptureTests(unittest.TestCase):
    def setup_capture(self, modern=False):
        self.rgba = np.array([[[10.5,20.5,300,255],[40,50,60,255]]],dtype=np.float32)
        self.device = MagicMock()
        image = SimpleNamespace(width=2,height=1)
        self.device.CaptureRGBA.return_value = image if modern else (image,2,1)
        self.utils = SimpleNamespace(gstCamera=MagicMock(return_value=self.device),
            cudaDeviceSynchronize=MagicMock(),cudaToNumpy=MagicMock(return_value=self.rgba))
        if modern:
            self.utils.cudaToNumpy.side_effect = lambda *args: self.rgba if len(args)==1 else self.reject_old_signature()
        with patch.dict(sys.modules,{'jetson.utils':self.utils}), patch('team8jetson_capture.time.sleep'):
            return JetsonCapture(1,1280,720,4)

    def reject_old_signature(self):
        raise TypeError('Modern binding expects cudaImage only')

    def test_staff_legacy_capture_and_bgr_copy(self):
        capture = self.setup_capture()
        self.utils.gstCamera.assert_called_with(1280,720,'/dev/video1')
        ok,frame = capture.read()
        self.assertTrue(ok)
        self.device.CaptureRGBA.assert_called_with(zeroCopy=1)
        self.utils.cudaDeviceSynchronize.assert_called_once()
        self.assertEqual(frame.dtype,np.uint8)
        self.assertEqual(frame.tolist(),[[[255,20,10],[60,50,40]]])
        self.rgba[:] = 0
        self.assertEqual(frame[0,0].tolist(),[255,20,10])
        capture.release()
        self.device.Close.assert_called_once()
        self.assertFalse(capture.isOpened())

    def test_modern_cuda_image_conversion(self):
        capture = self.setup_capture(modern=True)
        self.assertTrue(capture.read()[0])
        self.assertEqual(len(self.utils.cudaToNumpy.call_args.args),1)

    def test_invalid_frame_returns_failure_instead_of_previous_image(self):
        capture = self.setup_capture()
        self.device.CaptureRGBA.side_effect = RuntimeError('Capture timeout')
        self.assertEqual(capture.read(),(False,None))
        self.assertIn('timeout',capture.last_error)

    def test_capture_backend_routes_to_staff_adapter(self):
        with patch('team8jetson_capture.JetsonCapture') as factory:
            open_capture(None,2,backend='jetson',width=640,height=480,warmup=0)
            factory.assert_called_once_with(2,640,480,0)
        with self.assertRaises(ValueError):
            open_capture(None,pipeline='pipeline',backend='jetson')


if __name__ == '__main__':
    unittest.main()
