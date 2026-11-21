# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
from spt_fixture import fixture
import unittest
from unittest.mock import patch
from fx2_loader import load_firmware,FIRMWARE_SHA256
from usb_transport import USBError

SYNTHETIC=fixture()

class FakeBoot:
    def __init__(self,fail_at=None):self.calls=[];self.stage=0;self.fail_at=fail_at
    def info(self):
        return {'vid':'0456' if self.stage==2 else '04b4','pid':'7031' if self.stage==2 else '8613','bus':0,'ports':[1,2,3]}
    def list(self):return [self.info()]
    def open_at_port(self,identities,bus,ports):
        info=self.info()
        assert (info['vid'],info['pid']) in identities
        assert (bus,ports)==(0,[1,2,3])
        owner=self
        class Device:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            @property
            def info(self):return owner.info()
            def control(self,typ,req,value,index,data,timeout_ms):
                if owner.fail_at==len(owner.calls):raise USBError('Injected USB failure')
                owner.calls.append((typ,req,value,index,data))
                if value==0xe600 and data==b'\0':owner.stage+=1
                return len(data)
        return Device()

class LoaderTests(unittest.TestCase):
    def setUp(self):
        # Only tests accept the synthetic fixture hash; production remains pinned.
        patcher=patch('fx2_loader.FIRMWARE_SHA256',hashlib.sha256(SYNTHETIC).hexdigest())
        patcher.start();self.addCleanup(patcher.stop)

    def test_unknown_firmware_is_rejected_before_device_access(self):
        with self.assertRaisesRegex(ValueError,'does not match'):load_firmware(None,b'unknown',0,[1])
    def test_both_images_load_when_first_keeps_boot_usb_identity(self):
        fake=FakeBoot()
        with patch('fx2_loader.time.sleep'):
            report=load_firmware(fake,SYNTHETIC,0,[1,2,3])
        self.assertTrue(report['success'])
        self.assertEqual(len(fake.calls),98)
        self.assertEqual([s['records_completed'] for s in report['stages']],[43,55])
        self.assertEqual(report['stages'][0]['device_after']['pid'],'8613')
        self.assertEqual(report['stages'][1]['device_after']['pid'],'7031')
        self.assertTrue(all(req==0xa0 and typ==0x40 and index==0 for typ,req,value,index,data in fake.calls))
    def test_interrupted_download_does_not_resume_incomplete_code(self):
        fake=FakeBoot(fail_at=4)
        with self.assertRaisesRegex(USBError,'Code was not resumed'):
            load_firmware(fake,SYNTHETIC,0,[1,2,3])
        self.assertEqual(fake.calls[0][2:],(0xe600,0,b'\1'))
        self.assertFalse(any(value==0xe600 and data==b'\0' for typ,req,value,index,data in fake.calls))
    def test_physical_port_selection_required(self):
        with self.assertRaisesRegex(ValueError,'physical USB bus'):
            load_firmware(None,SYNTHETIC,0,[])

if __name__=='__main__':unittest.main()
