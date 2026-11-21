# SPDX-License-Identifier: GPL-3.0-or-later
"""Read and verify a full ADAU1701 RAM backup via a running classic USBi."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from usb_transport import LibUSB,atomic_json

WIDTHS={0x81c:2,0x81e:2,0x81f:1,0x820:3,0x821:3,0x822:2,0x824:2,0x826:2,0x827:2,0x808:2}

def backup(usb,address,root):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=False)
    try:
        started=time.monotonic()
        regs=lambda:{f'{r:04x}':usb.read(address,r,1,w).hex() for r,w in WIDTHS.items()}
        before=regs()
        program=usb.read(address,0x400,1024,5);parameters=usb.read(address,0,1024,4)
        program2=usb.read(address,0x400,1024,5);parameters2=usb.read(address,0,1024,4)
        after=regs()
        if program!=program2 or parameters!=parameters2:raise RuntimeError('RAM changed between reads; no verified backup published.')
        if before!=after:raise RuntimeError('Registers changed during backup; retry in a stable state.')
        report={'device':usb.info,'target':'ADAU1701','address7':hex(address),
                'registers_before':before,'registers_after':after,
                'program_reads_equal':True,'parameter_reads_equal':True,
                'program_sha256':hashlib.sha256(program).hexdigest(),
                'parameters_sha256':hashlib.sha256(parameters).hexdigest(),
                'program_bytes':len(program),'parameter_bytes':len(parameters),
                'elapsed_seconds':round(time.monotonic()-started,3),'usb_control_transfers':len(usb.trace)}
        (root/'program.bin').write_bytes(program);(root/'parameters.bin').write_bytes(parameters)
        atomic_json(root/'backup.json',report)
        return report
    finally:atomic_json(root/'usb-trace.json',usb.trace)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--address',type=lambda x:int(x,0),default=0x34)
    args=parser.parse_args()
    with LibUSB() as lib:
        with lib.open_usbi() as usb:print(json.dumps(backup(usb,args.address,args.output),indent=2))

if __name__=='__main__':main()
