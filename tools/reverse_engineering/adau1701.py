# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent ADAU1701 instruction field codec and parameter image primitives.

Field layout recovered from Sigma100Compiler.dll's decodedbits (0x06000017)
and OpcodeFldLengths_S100 (0x0600004a). No vendor runtime is required.
This is a backend building block, not a complete schematic compiler.
"""
import argparse
import json
import math
import re
from pathlib import Path

# MSB first. Names follow OpcodeFields; the field-length table uses misleading
# Data/Coeff_Address_Offset_Enable labels, so retain the actual register names.
FIELDS = [
    ('data_address', 13), ('coeff_address', 11), ('reg_destination', 3),
    ('mux', 4), ('use_yreg_offset', 1),
    ('use_xreg_offset', 1), ('subtract', 1),
    ('skip_on_condition', 1), ('swap_on_condition', 1),
    ('update_condition', 1), ('condition_select', 3),
]
DEST = {0:'none', 1:'accum0', 2:'accum1', 3:'accum2', 4:'dbreg',
        5:'xreg', 6:'yreg', 7:'data'}
MUX = {0:'0', 1:'accum0', 2:'accum1', 3:'accum2', 4:'ser_port',
       5:'accum0_and_xreg', 6:'accum0_or_xreg', 7:'accum0_xor_xreg',
       8:'accum0_abs', 9:'accum0_shiftleft23',
       10:'accum0_shiftright23', 11:'db'}
CONDITIONS = {0:'acc0_gte_0', 1:'acc0_gte_acc1', 2:'acc0_lte_acc1',
              3:'acc0_gt_acc1', 4:'acc0_eq_acc1', 5:'acc0_lte_0',
              6:'acc0_eq_0', 7:'acc0_gt_0'}
NOP = bytes.fromhex('0000000001')


def unpack_instruction(word):
    if len(word) != 5:
        raise ValueError('An instruction is exactly five bytes')
    n, shift, out = int.from_bytes(word, 'big'), 40, {}
    for name, width in FIELDS:
        shift -= width
        out[name] = (n >> shift) & ((1 << width)-1)
    return out


def pack_instruction(**fields):
    unknown = fields.keys() - dict(FIELDS).keys()
    if unknown:
        raise ValueError(f'Unknown fields: {unknown}')
    n = 0
    for name, width in FIELDS:
        v = fields.get(name, 1 if name == 'condition_select' else 0)
        if not isinstance(v, int) or not 0 <= v < (1 << width):
            raise ValueError(f'{name} must fit in {width} bits')
        n = (n << width) | v
    return n.to_bytes(5, 'big')


def decode_q523(data):
    if len(data) != 4:
        raise ValueError('A parameter transfer word is exactly four bytes')
    n = int.from_bytes(data, 'big') & 0x0fffffff
    return (n - (1 << 28) if n & (1 << 27) else n) / (1 << 23)


def encode_q523(value):
    """Match inspected FixInt32.set_DataFloat: nearest, ties toward +infinity."""
    d = float(value)
    if not math.isfinite(d) or not -16 <= d <= 16-2**-23:
        raise ValueError('Value out of signed 5.23 range')
    integer = math.trunc(d)
    fraction = math.floor((d-integer)/2**-23 + 0.5)
    n = integer*2**23 + fraction
    return (n & 0x0fffffff).to_bytes(4, 'big')


def parameter_image(records, size=1024):
    """Place exact exported bytes by word address; reject conflicting overlaps."""
    image, placed = bytearray(size*4), {}
    for r in records:
        data = bytes.fromhex(r['data_hex'])
        if not data or len(data) % 4:
            raise ValueError('Parameter record must contain whole four-byte words')
        addr = r['address']
        if not isinstance(addr, int) or addr < 0 or addr + len(data)//4 > size:
            raise ValueError('Parameter record outside parameter RAM')
        for i in range(0, len(data), 4):
            at, word = addr + i//4, data[i:i+4]
            if at in placed and placed[at] != word:
                raise ValueError(f'Conflicting parameter address {at}')
            placed[at] = word
            image[at*4:at*4+4] = word
    return bytes(image)


def hex_bytes(text):
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    return bytes(int(h, 16) for h in re.findall(r'\b0x([0-9a-fA-F]{2})\b', text))


def c_arrays(text):
    return {m[1]:hex_bytes(m[2]) for m in re.finditer(
        r'(\w+)\s*\[[^\]]+\]\s*=\s*\{(.*?)\};', text, re.S)}


def decode_program(program):
    if len(program) % 5:
        raise ValueError('Program size must be a multiple of five bytes')
    out = []
    for pc in range(len(program)//5):
        word = program[pc*5:pc*5+5]
        f = unpack_instruction(word)
        out.append({'pc':pc, 'control_port_address':1024+pc, 'hex':word.hex(),
                    **f, 'destination_label':DEST[f['reg_destination']],
                    'mux_label':MUX.get(f['mux'], 'reserved'),
                    'condition_label':CONDITIONS[f['condition_select']],
                    'is_nop':word == NOP})
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('disassemble')
    p.add_argument('program', type=Path, help='Raw program binary or generated C header')
    p.add_argument('-o', '--output', type=Path, required=True)
    p = sub.add_parser('assemble')
    p.add_argument('instructions', type=Path, help='JSON rows from disassemble, or field dictionaries')
    p.add_argument('-o', '--output', type=Path, required=True)
    args = ap.parse_args()
    if args.command == 'disassemble':
        data = args.program.read_bytes()
        if args.program.suffix.lower() == '.h':
            arrays = c_arrays(data.decode('utf-8-sig'))
            key = next(k for k in arrays if k.startswith('Program_Data_'))
            data = arrays[key]
        args.output.write_text(json.dumps(decode_program(data), indent=2)+'\n')
    else:
        rows = json.loads(args.instructions.read_text())
        args.output.write_bytes(b''.join(pack_instruction(**{k:r[k] for k,_ in FIELDS if k in r}) for r in rows))
