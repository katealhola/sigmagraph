# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from hardware_test import Session,CONFIG_WIDTHS,digest
from sigmagraph.codec1701 import NOP

class InterruptedUSB:
    """Emulate a transfer that changes target RAM before reporting failure."""
    info={}
    def __init__(self,program,parameters):
        self.memory={0x400:program,0:parameters,0x800:bytes(32),0x81c:bytes.fromhex('001c')}
        self.memory.update({r:bytes(w) for r,w in CONFIG_WIDTHS.items()})
        self.fail_once=True;self.writes=[]
    def read(self,address,reg,words,width):return self.memory[reg][:words*width]
    def write(self,address,reg,blob,width):
        self.writes.append(reg)
        if reg==0x400 and self.fail_once:
            self.fail_once=False
            self.memory[reg]=blob[:60]+self.memory[reg][60:]
            raise RuntimeError('Disconnected after partial program write')
        self.memory[reg]=blob

class RestorationTests(unittest.TestCase):
    def fixture(self,root):
        backup=root/'backup';backup.mkdir();out=root/'test';out.mkdir()
        program=NOP*1024;parameters=bytes(4096)
        (backup/'program.bin').write_bytes(program);(backup/'parameters.bin').write_bytes(parameters)
        meta={'program_sha256':digest(program),'parameters_sha256':digest(parameters),
              'registers_before':{'081c':'001c',**{f'{r:04x}':bytes(w).hex() for r,w in CONFIG_WIDTHS.items()}}}
        (backup/'backup.json').write_text(json.dumps(meta))
        usb=InterruptedUSB(program,parameters)
        return Session(usb,0x34,backup,out),usb,program,parameters

    def test_partial_program_failure_restores_before_resuming_audio(self):
        with tempfile.TemporaryDirectory() as d:
            session,usb,program,parameters=self.fixture(Path(d))
            with patch('hardware_test.signal.signal'),patch('hardware_test.time.sleep'):
                with self.assertRaisesRegex(RuntimeError,'partial program'):session.run()
            self.assertEqual(usb.memory[0x400],program)
            self.assertEqual(usb.memory[0],parameters)
            self.assertEqual(usb.memory[0x81c],bytes.fromhex('001c'))
            self.assertTrue(session.report['restoration']['verified'])
            self.assertFalse(session.report['passed'])

    def test_modified_backup_rejected_before_target_writes(self):
        with tempfile.TemporaryDirectory() as d:
            session,usb,program,parameters=self.fixture(Path(d))
            (session.backup/'parameters.bin').write_bytes(bytes([1])+parameters[1:])
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                Session(usb,0x34,session.backup,session.out)
            self.assertEqual(usb.writes,[])

    def test_negative_interface_word_is_sign_extended(self):
        with tempfile.TemporaryDirectory() as d:
            session,usb,_,_=self.fixture(Path(d));usb.memory[0x800]=bytes.fromhex('fff00000')+bytes(28)
            self.assertEqual(session.expect((-.125,))['actual'],[-.125])

if __name__=='__main__':unittest.main()
