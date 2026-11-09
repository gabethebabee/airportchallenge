"""Generate exact tag36h11 PNGs from the bundled detector's code table; no dependencies."""
from pathlib import Path
import re
import struct
import tarfile
import zlib


# SECTION: Encode plain grayscale PNG chunks with standard-library tools.
# Each row uses PNG's no-filter mode, so black/white tag cells remain exact.
# This creates a machine-readable pattern rather than an illustration of a tag.
def chunk(kind, payload):
    return struct.pack('!I',len(payload))+kind+payload+struct.pack('!I',zlib.crc32(kind+payload)&0xffffffff)


# SECTION: Read genuine family codes from the source used by the native detector.
# A tag has 6x6 data cells, a one-cell black border and a two-cell white margin.
# The most significant code bit is the top-left data cell, matching the decoder
# self-test that already passed on the Jetson. Original license stays in the ZIP.
def make_tags():
    root = Path(__file__).resolve().parent
    with tarfile.open(str(root/'team8apriltag-source.tar.gz'),'r:gz') as archive:
        name = next(member.name for member in archive.getmembers() if member.name.endswith('/core/tag36h11.c'))
        source = archive.extractfile(name).read().decode('utf-8')
    for identity in range(3):
        match = re.search(r'tf->codes\['+str(identity)+r'\]\s*=\s*(0x[0-9a-fA-F]+)',source)
        if not match:
            raise RuntimeError('Tag code missing from upstream table')
        code = int(match.group(1),16)
        cells = [[255]*12 for _ in range(12)]
        for y in range(2,10):
            for x in range(2,10):
                cells[y][x] = 0
        for index in range(36):
            cells[3+index//6][3+index%6] = 255 if code & (1 << (35-index)) else 0
        scale = 60
        rows = []
        for row in cells:
            pixels = b''.join(bytes([value])*scale for value in row)
            rows.extend([b'\x00'+pixels]*scale)
        size = 12*scale
        header = struct.pack('!IIBBBBB',size,size,8,0,0,0,0)
        png = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',header)+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')
        path = root/'team8tag36h11-{}.png'.format(identity)
        path.write_bytes(png)
        print(path.name)


if __name__ == '__main__':
    make_tags()
