# SPDX-License-Identifier: GPL-3.0-or-later
"""Run portable app and offline USBi suites without touching USB hardware."""
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    env=os.environ.copy();env.setdefault('QT_QPA_PLATFORM','offscreen')
    env['PYTHONPATH']=str(ROOT)+os.pathsep+env.get('PYTHONPATH','')
    for suite in ('tests','tools/usbi'):
        subprocess.run([sys.executable,'-m','unittest','discover','-s',suite,'-p','test_*.py','-v'],cwd=ROOT,env=env,check=True)

if __name__=='__main__':main()
