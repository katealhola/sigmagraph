# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic inert CSPT data; not operating firmware and never used on hardware."""
import struct

def record(address,payload):
    header=bytearray(32)
    struct.pack_into('<4sII',header,0,b'CSPT',32+len(payload),32)
    header[15]=0x40;header[16]=0xa0
    struct.pack_into('<HH',header,18,address,0)
    struct.pack_into('<I',header,28,len(payload))
    return bytes(header)+payload

def fixture():
    chunks=[]
    for count,vid,pid in ((43,0x04b4,0x1004),(55,0x0456,0x7031)):
        descriptor=bytearray(18);descriptor[:2]=b'\x12\x01';descriptor[7]=64
        struct.pack_into('<HH',descriptor,8,vid,pid)
        chunks.append(record(0xe600,b'\1'))
        chunks.append(record(0x100,bytes(descriptor)))
        chunks.extend(record(0x200+i,b'\0') for i in range(count-3))
        chunks.append(record(0xe600,b'\0'))
    return b''.join(chunks)
