# SPDX-License-Identifier: GPL-3.0-or-later
from spt_fixture import fixture
import struct
import unittest
from usbi_protocol import write_chunks,read_chunk,inspect_spt,Transfer

class ProtocolTests(unittest.TestCase):
    def test_core_register_write_matches_recovered_setup(self):
        packet=write_chunks(0x34,0x081c,bytes.fromhex('0018'),2)[0]
        self.assertEqual(packet.setup.hex(),'40b2340000000400')
        self.assertEqual(packet.data.hex(),'081c0018')

    def test_read_register_has_four_phases(self):
        packets=read_chunk(0x34,0x081c,2)
        self.assertEqual([p.setup.hex() for p in packets],['40b3340000000200','c0b5340000000100','c0b4340000000200','c0b6340000000100'])
        self.assertEqual(packets[0].data.hex(),'081c')

    def test_program_chunks_preserve_five_byte_words_and_word_addresses(self):
        data=bytes(i%256 for i in range(5120));packets=write_chunks(0x34,0x400,data,5)
        self.assertEqual(len(packets),86)
        self.assertEqual(packets[1].data[:2],bytes.fromhex('040c'))
        self.assertEqual(packets[-1].data[:2],bytes.fromhex('07fc'))
        self.assertEqual(b''.join(p.data[2:] for p in packets),data)
        self.assertTrue(all(len(p.data)<=64 and (len(p.data)-2)%5==0 for p in packets))

    def test_parameter_chunks_preserve_four_byte_words(self):
        packets=write_chunks(0x34,0,bytes(4096),4)
        self.assertEqual(len(packets),69)
        self.assertEqual(packets[1].data[:2],bytes.fromhex('000f'))
        self.assertEqual(packets[-1].data[:2],bytes.fromhex('03fc'))

    def test_byte_addressed_storage_does_not_advance_by_words(self):
        packets=write_chunks(0x50,0x100,bytes(100),4,byte_addressed=True)
        self.assertEqual(packets[1].data[:2],bytes.fromhex('013c'))

    def test_invalid_word_ranges_and_eight_bit_address_rejected(self):
        for args in [(0x34,0,bytes(3),4),(0x34,65535,bytes(8),4),(0xa0,0,bytes(4),4)]:
            with self.assertRaises(ValueError):write_chunks(*args)

    def test_truncated_spt_rejected(self):
        for data in [b'CSPT',b'CSPT'+bytes(28),b'BAD!'+bytes(28)]:
            with self.assertRaises(ValueError):inspect_spt(data)

    def test_synthetic_firmware_has_two_images_and_programmed_identity(self):
        info=inspect_spt(fixture())
        self.assertEqual(info['record_count'],98)
        images=info['firmware_images'];self.assertEqual(len(images),2)
        self.assertEqual([(x['vid'],x['pid']) for x in images[0]['descriptors']],[('04b4','1004')])
        self.assertEqual([(x['vid'],x['pid']) for x in images[1]['descriptors']],[('0456','7031')])
        self.assertEqual([r['cpu_reset'] for r in info['records'] if 'cpu_reset' in r],[1,0,1,0])

if __name__=='__main__':unittest.main()
