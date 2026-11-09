"""Build the bundled detector offline on Linux; no sudo, pip, downloads or OpenCV replacement."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile


# SECTION: Check prerequisites and source integrity before running any compiler.
# Source is pinned to the commit/hash in the accompanying manifest. All output
# stays beside this script, so a successful build needs no administrator access.
def prerequisites(root):
    if platform.system() != 'Linux':
        raise RuntimeError('Run this installer on the Jetson, not the Windows laptop')
    compiler = shutil.which('cc') or shutil.which('gcc')
    if not compiler:
        raise RuntimeError('C compiler missing. Ask staff for gcc/build-essential offline; no packages were changed.')
    try:
        import numpy
    except ImportError:
        raise RuntimeError('NumPy is missing in this Python; use the Jetson interpreter that imports OpenCV.')
    archive = root / 'team8apriltag-source.tar.gz'
    metadata = json.loads((root / 'team8apriltag-source.json').read_text())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != metadata['sha256']:
        raise RuntimeError('Bundled source checksum mismatch; copy the deployment ZIP again')
    print('Python / machine:', platform.python_version(), platform.machine())
    print('Compiler:', compiler, '| NumPy:', numpy.__version__)
    print('Upstream commit:', metadata['commit'])
    return compiler, archive, metadata


# SECTION: Extract only ordinary source files inside a new temporary directory.
# Reject links and escaping paths rather than trusting an archive member name.
# The pinned CMake source list defines exactly which native C units are compiled.
def extract_sources(archive, destination):
    destination = destination.resolve()
    with tarfile.open(str(archive), 'r:gz') as source:
        for member in source.getmembers():
            if not member.isfile():
                raise RuntimeError('Unexpected non-file source archive member')
            relative = Path(*Path(member.name).parts[1:])
            target = (destination / relative).resolve()
            if destination not in target.parents:
                raise RuntimeError('Unsafe source archive path')
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as incoming, target.open('wb') as outgoing:
                shutil.copyfileobj(incoming,outgoing)
    cmake = (destination/'core/CMakeLists.txt').read_text()
    match = re.search(r'set\(sources\s+(.*?)\)', cmake, re.S)
    if not match:
        raise RuntimeError('Bundled C source list not found')
    sources = match.group(1).split()
    if not sources or any(not name.endswith('.c') or '..' in name or not (destination/'core'/name).is_file() for name in sources):
        raise RuntimeError('Invalid C source list')
    return [str(destination/'core'/name) for name in sources]


# SECTION: Compile for the current Jetson CPU and run real decoder smoke tests.
# Linking the small C library directly avoids CMake, Python development headers
# and optional upstream OpenCV example programs. Upstream source is unchanged;
# the copied wrapper changes only its library filename to the team8-prefixed one.
def install(check_only=False):
    root = Path(__file__).resolve().parent
    compiler, archive, metadata = prerequisites(root)
    if check_only:
        print('BUILD PREREQUISITES OK. No compiler was run.')
        return
    output = root / 'team8apriltag_native'
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='team8-apriltag-') as temporary:
        work = Path(temporary)
        sources = extract_sources(archive,work)
        library = work/'team8libapriltag.so'
        command = [compiler,'-shared','-fPIC','-O2','-std=gnu99','-D_GNU_SOURCE','-pthread',
                   '-I'+str(work/'core'),'-I'+str(work/'core/common'),'-I'+str(work/'core/contrib')]
        command += sources + ['-lm','-o',str(library)]
        print('Compiling AprilTag locally. This may take a few minutes.',flush=True)
        subprocess.check_call(command)
        wrapper = (work/'python/apriltag.py').read_text()
        original = "filename = 'libapriltag'+extension"
        if wrapper.count(original) != 1:
            raise RuntimeError('Upstream wrapper library-name location changed')
        wrapper = wrapper.replace(original,"filename = 'team8libapriltag'+extension")
        shutil.copyfile(str(library),str(output/'team8libapriltag.so.new'))
        os.replace(str(output/'team8libapriltag.so.new'),str(output/'team8libapriltag.so'))
        (output/'team8upstream_apriltag.py').write_text(wrapper)
        shutil.copyfile(str(work/'LICENSE.md'),str(output/'team8UPSTREAM_LICENSE.md'))
    from team8apriltag_native import self_test
    print(self_test())
    (output/'team8build.json').write_text(json.dumps(dict(metadata,architecture=platform.machine()),indent=2))
    print('Installed locally. Next: python3 team8apriltag_camera.py --check --backend bundled')


# SECTION: Provide a prerequisite-only mode and readable errors for onsite setup.
# A failed build leaves its output visible in the terminal for staff/debugging;
# it never attempts an online installation as a fallback.
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    try:
        install(args.check)
    except (RuntimeError,OSError,subprocess.CalledProcessError) as error:
        parser.exit(1,'AprilTag setup failed: '+str(error)+'\n')
