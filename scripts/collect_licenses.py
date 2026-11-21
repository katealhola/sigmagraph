# SPDX-License-Identifier: GPL-3.0-or-later
"""Include project and installed dependency notices in frozen distributions."""
from importlib.metadata import distributions
from pathlib import Path
import json
import shutil
import sys
import sysconfig

ROOT=Path(__file__).resolve().parents[1]

def collect(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'LICENSE',output/'SigmaGraph-LICENSE.txt')
    shutil.copy2(ROOT/'THIRD_PARTY_NOTICES.md',output/'THIRD_PARTY_NOTICES.md')
    for path in (ROOT/'LICENSES').glob('*.txt'):shutil.copy2(path,output/path.name)
    inventory=[]
    for dist in distributions():
        name=dist.metadata['Name'];notices=[]
        for item in dist.files or ():
            if item.name.lower().startswith(('license','copying','notice','copyright')):
                source=Path(dist.locate_file(item))
                if not source.is_file():continue
                dest=output/name/str(item).replace('../','').replace('..\\','')
                dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
                notices.append(str(dest.relative_to(output)))
        inventory.append({'name':name,'version':dist.version,'license':dist.metadata.get('License-Expression') or dist.metadata.get('License'),
                          'homepage':dist.metadata.get('Home-page'),'notice_files':notices})
    for base in (Path(sys.base_prefix),Path(sysconfig.get_path('stdlib'))):
        for name in ('LICENSE','LICENSE.txt'):
            path=base/name
            if path.is_file():shutil.copy2(path,output/'Python-LICENSE.txt');break
    (output/'dependencies.json').write_text(json.dumps(inventory,indent=2)+'\n')

if __name__=='__main__':collect(ROOT/'.build/licenses')
