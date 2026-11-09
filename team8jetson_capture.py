"""Adapt staff's jetson.utils.gstCamera capture to the existing BGR frame reader."""
import importlib
import time


# SECTION: Keep NVIDIA-specific imports out of the laptop dashboard and other
# camera backends. gstCamera owns the requested /dev/video device; no glDisplay
# is created, so this backend can run through SSH without a graphical session.
class JetsonCapture:
    def __init__(self, camera=0, width=1280, height=720, warmup=4):
        self.utils = importlib.import_module('jetson.utils')
        self.camera = self.utils.gstCamera(width, height, '/dev/video{}'.format(camera))
        self.last_error = None
        print('Jetson gstCamera: /dev/video{} requested {}x{}; warming up {} s'.format(
            camera,width,height,warmup),flush=True)
        time.sleep(warmup)

    def isOpened(self):
        return self.camera is not None

    # SECTION: Capture mapped RGBA memory and copy it to OpenCV's BGR convention.
    # Legacy CaptureRGBA returns (capsule,width,height); newer versions may return
    # a cudaImage. zeroCopy requests CPU-accessible memory. Synchronize before
    # reading CUDA output, then make an independent uint8 BGR copy so the next
    # capture cannot overwrite the frame being detected or JPEG-encoded.
    def read(self):
        import numpy as np
        if self.camera is None:
            return False,None
        try:
            result = self.camera.CaptureRGBA(zeroCopy=1)
            if isinstance(result,tuple):
                image,width,height = result
                if image is None:
                    raise RuntimeError('CaptureRGBA returned no image')
            else:
                image = result
                if image is None:
                    raise RuntimeError('CaptureRGBA returned no image')
                width,height = image.width,image.height
            if hasattr(self.utils,'cudaDeviceSynchronize'):
                self.utils.cudaDeviceSynchronize()
            try:
                rgba = self.utils.cudaToNumpy(image,width,height,4)
            except TypeError:
                rgba = self.utils.cudaToNumpy(image)
            rgba = np.asarray(rgba)
            if rgba.ndim != 3 or rgba.shape != (height,width,4):
                raise RuntimeError('Unexpected RGBA shape {}'.format(rgba.shape))
            bgr = np.ascontiguousarray(np.clip(rgba[:,:,:3],0,255).astype(np.uint8)[:,:,::-1])
            self.last_error = None
            return True,bgr
        except (RuntimeError,ValueError,TypeError,AttributeError) as error:
            self.last_error = str(error)
            print('Jetson capture failed:',self.last_error,flush=True)
            return False,None

    # SECTION: Release this camera only. The Python binding's available close
    # method varies by version; dropping its owned reference also permits native
    # cleanup. Other camera publishers and the dashboard are left running.
    def release(self):
        camera,self.camera = self.camera,None
        if camera is not None:
            close = getattr(camera,'Close',None) or getattr(camera,'close',None)
            if callable(close):
                close()
