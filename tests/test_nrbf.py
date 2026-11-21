# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic serialization checks independent of any proprietary project file."""
import struct
import unittest
from sigmagraph.nrbf import Reader,FormatError,deref

def header(root=1):return b'\0'+struct.pack('<iiii',root,-1,1,0)

class NRBFTests(unittest.TestCase):
    def test_string_root_and_trailing_bytes(self):
        data=header()+b'\6'+struct.pack('<i',1)+b'\3abc'+b'\x0b'
        graph=Reader(data+b'trailing').parse()
        self.assertEqual(deref(graph,{'$ref':graph['root']}),'abc')
        self.assertEqual(graph['trailing_bytes'],8)

    def test_object_array_preserves_shared_reference_and_null(self):
        data=header()+b'\x10'+struct.pack('<ii',1,3)
        data+=b'\6'+struct.pack('<i',2)+b'\3abc'
        data+=b'\x09'+struct.pack('<i',2)+b'\x0a\x0b'
        graph=Reader(data).parse()
        self.assertEqual(graph['objects'][1]['values'],[{'$ref':2},{'$ref':2},None])

    def test_truncation_missing_end_and_unresolved_reference_rejected(self):
        for data in (b'',b'\0',header(),header()+b'\x10'+struct.pack('<ii',1,1)+b'\x09'+struct.pack('<i',99)+b'\x0b'):
            with self.subTest(data=data),self.assertRaises(FormatError):Reader(data).parse()

if __name__=='__main__':unittest.main()
