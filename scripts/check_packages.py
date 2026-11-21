# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify source/wheel assets and license, then record package checksums."""
import hashlib
from pathlib import Path
import tarfile
import zipfile

root=Path(__file__).resolve().parents[1];dist=root/'dist'
wheels=list(dist.glob('*.whl'));sources=list(dist.glob('*.tar.gz'))
assert len(wheels)==len(sources)==1,'Expected one wheel and source distribution.'
with zipfile.ZipFile(wheels[0]) as z:
    assert 'sigmagraph/data/catalog.json' in z.namelist()
    assert 'sigmagraph/data/example-presets.json' in z.namelist()
    assert any(n.endswith('/licenses/LICENSE') for n in z.namelist())
    metadata=z.read(next(n for n in z.namelist() if n.endswith('.dist-info/METADATA')))
    assert b'License-Expression: GPL-3.0-or-later' in metadata
with tarfile.open(sources[0]) as t:
    names=t.getnames()
    prefix=names[0].split('/')[0]
    assert prefix+'/build.py' not in names,'Root build.py would shadow the Python build frontend.'
    for suffix in ('/LICENSE','/scripts/build_app.py','/scripts/package_release.py','/tools/usbi/usb_transport.py','/.github/workflows/build.yml','/examples/stereo-crossover.sgproj'):
        assert any(n.endswith(suffix) for n in names),suffix
with (dist/'SHA256SUMS.txt').open('w') as sums:
    for p in sorted(wheels+sources):
        sha=hashlib.sha256()
        with p.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):sha.update(chunk)
        digest=sha.hexdigest()
        sums.write(f'{digest}  {p.name}\n')
print('Wheel/source data, license and checksums verified.')
