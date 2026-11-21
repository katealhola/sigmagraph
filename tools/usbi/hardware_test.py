# SPDX-License-Identifier: GPL-3.0-or-later
"""Reversible ADAU1701 RAM/execution test. Requires an existing verified backup.

Audio converters remain muted during testing. No EEPROM or GPIO writes.
Run from the research directory's parent or supply explicit paths. The companion
SigmaGraph source tree supplies only the independent instruction codec.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import signal
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sigmagraph.codec1701 import NOP, pack_instruction, encode_q523, decode_q523
from usb_transport import LibUSB, atomic_json

CONFIG_WIDTHS={0x81e:2,0x81f:1,0x820:3,0x821:3,0x822:2,0x824:2,0x826:2,0x827:2}

def digest(blob):return hashlib.sha256(blob).hexdigest()

def diagnostic_images():
    """Only constant MACs, NOPs and host interface writes; no DAC/GPIO ops."""
    code=[]
    def mac(index,add=False,subtract=False):
        code.append(pack_instruction(data_address=8190,coeff_address=512+index,
            reg_destination=1,mux=int(add),subtract=int(subtract)))
    def out(index):
        code.extend([NOP,pack_instruction(data_address=8144+index,mux=1),NOP,NOP])
    mac(0);out(0)
    mac(1);out(1)
    mac(0);mac(1,add=True);out(2)
    mac(2);mac(0,add=True,subtract=True);out(3)
    program=b''.join(code+[NOP]*(1024-len(code)))
    # Unused parameter locations exercise all 28 data bits without executing them.
    parameters=bytearray(b''.join(((i*0x13579b+0x2468ac)&0x0fffffff).to_bytes(4,'big') for i in range(1024)))
    for i,value in enumerate((.25,-.125,.5)):
        parameters[i*4:i*4+4]=encode_q523(value)
    return program,bytes(parameters)

class Session:
    def __init__(self,usb,address,backup,out):
        self.usb,self.address,self.backup,self.out=usb,address,Path(backup),Path(out)
        self.meta=json.loads((self.backup/'backup.json').read_text())
        if 'address7' in self.meta and int(self.meta['address7'],0)!=address:
            raise ValueError('Selected DSP address differs from the backup.')
        self.program=(self.backup/'program.bin').read_bytes()
        self.parameters=(self.backup/'parameters.bin').read_bytes()
        for name,blob,size in [('program',self.program,5120),('parameters',self.parameters,4096)]:
            if len(blob)!=size or digest(blob)!=self.meta[name+'_sha256']:
                raise ValueError('Backup size/hash mismatch: '+name)
        self.original=int(self.meta['registers_before']['081c'],16)
        if self.original & ~0x1f:raise ValueError('Unsupported original core-control state.')
        self.muted=self.original & ~0x18
        self.clear=self.muted & ~4
        self.report={'device':usb.info,'address7':hex(address),'tests':{},'restoration':{'attempted':False}}
        self.interfaces=None

    def read(self,reg,words,width):return self.usb.read(self.address,reg,words,width)
    def write(self,reg,blob,width):self.usb.write(self.address,reg,blob,width)
    def core(self,value):
        self.write(0x81c,value.to_bytes(2,'big'),2)
        actual=self.read(0x81c,1,2)
        if int.from_bytes(actual,'big')!=(value & ~0x20):
            raise RuntimeError(f'Core control mismatch: expected {value:04x}, read {actual.hex()}')
    def config(self):return {f'{r:04x}':self.read(r,1,w).hex() for r,w in CONFIG_WIDTHS.items()}
    def verify_images(self,program,parameters):
        p=self.read(0x400,1024,5);q=self.read(0,1024,4)
        if p!=program or q!=parameters:
            raise RuntimeError(f'RAM verification failed: program={p==program}, parameters={q==parameters}')
        return {'program_sha256':digest(p),'parameters_sha256':digest(q),'program_bytes':len(p),'parameter_bytes':len(q)}
    def load(self,program,parameters):
        self.core(self.muted);time.sleep(.05);self.core(self.clear)
        self.write(0x400,program,5);self.write(0,parameters,4)
        return self.verify_images(program,parameters)
    def seed_interfaces(self):
        sentinels=b''.join(encode_q523(v) for v in (1,2,3,4))+self.interfaces[16:]
        self.core(self.clear|0x40);self.write(0x800,sentinels,4)
        if self.read(0x800,8,4)!=sentinels:raise RuntimeError('Host interface sentinel write failed.')
        self.core(self.clear)
        return sentinels[:16].hex()
    def expect(self,values):
        raw=self.read(0x800,len(values),4)
        wanted=b''.join(encode_q523(v) for v in values)
        actual=[decode_q523(raw[i:i+4]) for i in range(0,len(raw),4)]
        # Interface registers sign-extend 28-bit negative results to 32 bits.
        canonical=b''.join((int.from_bytes(raw[i:i+4],'big')&0x0fffffff).to_bytes(4,'big') for i in range(0,len(raw),4))
        if canonical!=wanted:raise RuntimeError(f'DSP output mismatch: expected {list(values)}, read {actual} ({raw.hex()})')
        return {'expected':list(values),'actual':actual,'raw_hex':raw.hex()}
    def restore(self):
        # Catchable interruptions must not interrupt the restoration itself.
        for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,signal.SIG_IGN)
        state=self.report['restoration'];state['attempted']=True;state['errors']=[]
        for attempt in range(2):
            try:
                self.core(self.clear)
                self.write(0x400,self.program,5);self.write(0,self.parameters,4)
                state.update(self.verify_images(self.program,self.parameters))
                if self.interfaces is not None:
                    self.core(self.clear|0x40);self.write(0x800,self.interfaces,4)
                    if self.read(0x800,8,4)!=self.interfaces:raise RuntimeError('Interface restoration mismatch.')
                    state['interfaces_restored']=True
                # Release IFCW and CR while converters are still muted.
                self.core(self.clear);self.core(self.muted);time.sleep(.05)
                actual=self.config()
                expected={r:self.meta['registers_before'][r] for r in actual}
                if actual!=expected:raise RuntimeError('Configuration differs from backup.')
                self.core(self.original)
                state.update(verified=True,core_control=f'{self.original:04x}',configuration=actual)
                return
            except Exception as exc:
                state['errors'].append(repr(exc));time.sleep(.05)
        state['verified']=False
        try:self.core(self.clear)
        except Exception as exc:state['errors'].append('Could not leave muted: '+repr(exc))
        raise RuntimeError('Restoration failed; inspect report and use --restore-only.')

    def run(self,restore_only=False,compiler_test=False):
        changed=False
        try:
            if restore_only:
                path=self.out/'interfaces.bin'
                self.interfaces=path.read_bytes()
                if len(self.interfaces)!=32:raise ValueError('Recovery requires the original 32-byte interface snapshot.')
                self.restore();return
            self.verify_images(self.program,self.parameters)
            current=self.read(0x81c,1,2).hex()
            if current!=self.meta['registers_before']['081c']:raise RuntimeError('Core state differs from backup.')
            config=self.config()
            if config!={r:self.meta['registers_before'][r] for r in config}:
                raise RuntimeError('Configuration differs from backup.')
            self.interfaces=self.read(0x800,8,4)
            (self.out/'interfaces.bin').write_bytes(self.interfaces)
            atomic_json(self.out/'preflight.json',{'core':current,'interfaces_hex':self.interfaces.hex(),'backup':str(self.backup.resolve())})
            changed=True
            if compiler_test:
                from compiler_probe import run_compiler_probe
                self.report['tests']['compiled_graph']=run_compiler_probe(self)
                self.report['passed']=True
                return
            program,parameters=diagnostic_images()
            (self.out/'diagnostic-program.bin').write_bytes(program)
            (self.out/'diagnostic-parameters.bin').write_bytes(parameters)
            print('Writing and reading back diagnostic RAM',flush=True)
            self.report['tests']['full_ram_write_read']=self.load(program,parameters)
            print('Seeding host interfaces and running DSP arithmetic',flush=True)
            sentinels=self.seed_interfaces()
            self.core(self.muted);time.sleep(.03)
            self.report['tests']['arithmetic']={'sentinels_hex':sentinels,**self.expect((.25,-.125,.125,.25))}
            print('Testing live hardware safeload',flush=True)
            self.write(0x810,b'\0'+encode_q523(.5),5)
            self.write(0x815,b'\0\0',2)
            self.write(0x81c,(self.muted|0x20).to_bytes(2,'big'),2)
            time.sleep(.03)
            updated=self.read(0,1,4)
            if updated!=encode_q523(.5):raise RuntimeError('Safeload parameter mismatch: '+updated.hex())
            self.report['tests']['safeload']={'parameter0_hex':updated.hex(),**self.expect((.5,-.125,.375,0))}
            self.report['passed']=True
        except BaseException as exc:
            self.report.update(passed=False,error=repr(exc));raise
        finally:
            if changed:
                print('Restoring original RAM and core control',flush=True)
                try:self.restore()
                finally:atomic_json(self.out/'results.json',self.report)
            else:atomic_json(self.out/'results.json',self.report)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--address',type=lambda x:int(x,0),default=0x34)
    parser.add_argument('--restore-only',action='store_true')
    parser.add_argument('--compiler-test',action='store_true',help='Test an instrumented SigmaGraph graph instead of the arithmetic diagnostic')
    args=parser.parse_args()
    if args.output.exists() and not args.restore_only:parser.error('Use a new output directory to preserve prior results.')
    args.output.mkdir(parents=True,exist_ok=True)
    def interrupted(sig,frame):raise KeyboardInterrupt(f'Signal {sig}')
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,interrupted)
    with LibUSB() as lib:
        with lib.open_usbi() as usb:
            session=Session(usb,args.address,args.backup,args.output)
            try:session.run(args.restore_only,args.compiler_test)
            finally:atomic_json(args.output/'usb-trace.json',usb.trace)
            print(json.dumps(session.report,indent=2))

if __name__=='__main__':main()
