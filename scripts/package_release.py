# SPDX-License-Identifier: GPL-3.0-or-later
"""Archive the native application, verifying executable type and architecture."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sigmagraph import __version__

def target():
    os_name={'darwin':'macos','linux':'linux'}.get(sys.platform)
    arch={'AMD64':'x86_64','x86_64':'x86_64','aarch64':'arm64','arm64':'arm64'}.get(platform.machine())
    if not os_name or not arch:raise ValueError('Build on a supported native macOS/Linux x86_64/ARM64 host.')
    return os_name,arch

def package(dist,output,expected=None):
    os_name,arch=target();label=f'{os_name}-{arch}'
    if expected and label!=expected:raise ValueError(f'Expected {expected}, running on {label}.')
    bundle=Path(dist)/('SigmaGraph.app' if os_name=='macos' else 'SigmaGraph')
    executable=bundle/('Contents/MacOS/SigmaGraph' if os_name=='macos' else 'SigmaGraph')
    if not executable.is_file():raise ValueError('Build the application before packaging: '+str(executable))
    description=subprocess.check_output(['file','-b',str(executable)],text=True).strip()
    signatures=('x86_64','x86-64') if arch=='x86_64' else ('arm64','aarch64')
    if not any(s in description for s in signatures):raise ValueError('Executable architecture mismatch: '+description)
    if ('Mach-O' if os_name=='macos' else 'ELF') not in description:raise ValueError('Unexpected executable format: '+description)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    stem=f'SigmaGraph-{__version__}-{label}'
    archive=output/(stem+('.zip' if os_name=='macos' else '.tar.gz'))
    if os_name=='macos':
        subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(bundle),str(archive)],check=True)
    else:
        with tarfile.open(archive,'w:gz') as tar:tar.add(bundle,arcname='SigmaGraph')
    sha=hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):sha.update(chunk)
    digest=sha.hexdigest()
    (output/(archive.name+'.sha256')).write_text(f'{digest}  {archive.name}\n')
    info={'version':__version__,'target':label,'file':archive.name,'sha256':digest,
          'bytes':archive.stat().st_size,'binary':description,'license':'GPL-3.0-or-later',
          'source':'https://github.com/katealhola/sigmagraph','commit':__import__('os').environ.get('GITHUB_SHA')}
    (output/(stem+'.json')).write_text(json.dumps(info,indent=2)+'\n')
    print(json.dumps(info,indent=2));return archive

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist',type=Path,default=ROOT/'dist')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts')
    parser.add_argument('--expected-target')
    args=parser.parse_args();package(args.dist,args.output,args.expected_target)

if __name__=='__main__':main()
