# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from usb_transport import USBi,USBError

class Recorder(USBi):
    def __init__(self,statuses=None):
        super().__init__(None,None,{})
        self.calls=[];self.statuses=iter(statuses or [])
    def control(self,typ,req,value,index=0,data=b'',length=None,timeout_ms=1000):
        self.calls.append((typ,req,value,index,bytes(data),length))
        if req in (0xb5,0xb6):return bytes([next(self.statuses,1)])
        if typ&0x80:return bytes(length)
        return len(data)

class TransportTests(unittest.TestCase):
    def test_read_program_splits_on_five_byte_word_boundaries(self):
        usb=Recorder();self.assertEqual(len(usb.read(0x34,0x400,15,5)),75)
        address_calls=[c for c in usb.calls if c[1]==0xb3]
        self.assertEqual([c[4].hex() for c in address_calls],['0400','040c'])
        self.assertTrue(all(c[3]==0x100 for c in address_calls))
        self.assertEqual([c[5] for c in usb.calls if c[1]==0xb4],[60,15])
        self.assertTrue(all(c[1]!=0xb2 for c in usb.calls))
    def test_failed_address_phase_prevents_data_fetch(self):
        usb=Recorder([3])
        with self.assertRaisesRegex(USBError,'status 3'):usb.read(0x34,0x81c,1,2)
        self.assertEqual([c[1] for c in usb.calls],[0xb3,0xb5])
    def test_busy_polls_are_retried_with_correct_status_commands(self):
        usb=Recorder([2,2,1,0,1]);usb.read(0x34,0x81c,1,2)
        self.assertEqual([c[1] for c in usb.calls],[0xb3,0xb5,0xb5,0xb5,0xb4,0xb6,0xb6])
    def test_timeout_polling_is_bounded(self):
        usb=Recorder([2]*102)
        with self.assertRaisesRegex(USBError,'timed out'):usb.poll(0x34)
        self.assertEqual(len(usb.calls),101)
    def test_target_eeprom_writes_are_rejected(self):
        usb=Recorder()
        with self.assertRaises(ValueError):usb.write(0x50,0,bytes(4),1)
        self.assertEqual(usb.calls,[])
    def test_generic_eeprom_reads_need_a_separate_address_width_profile(self):
        usb=Recorder()
        with self.assertRaises(ValueError):usb.read(0x50,0,1,4)
        self.assertEqual(usb.calls,[])
    def test_program_write_splits_and_checks_every_transfer(self):
        usb=Recorder();usb.write(0x34,0x400,bytes(75),5)
        self.assertEqual([c[1] for c in usb.calls],[0xb2,0xb5,0xb2,0xb5])
        self.assertEqual([c[4][:2].hex() for c in usb.calls if c[1]==0xb2],['0400','040c'])
        self.assertTrue(all(c[3]==0x100 for c in usb.calls if c[1]==0xb2))
    def test_address_and_range_checks_happen_before_io(self):
        for address,start,words,width in [(0,0,1,2),(0xa0,0,1,2),(0x34,0xFFFF,2,4),(0x34,0,0,2)]:
            usb=Recorder()
            with self.assertRaises(ValueError):usb.read(address,start,words,width)
            self.assertEqual(usb.calls,[])

if __name__=='__main__':unittest.main()
