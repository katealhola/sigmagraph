# SPDX-License-Identifier: GPL-3.0-or-later
"""Static managed-IL inspector; requires dnfile and dncil, never runs target code."""
import argparse
import json
import logging
import re
from pathlib import Path
import dnfile
from dncil.cil.body.reader import read_method_body_from_bytes
from dncil.clr.token import Token

logging.getLogger('dnfile').setLevel(logging.ERROR)


class Assembly:
    def __init__(self, path):
        self.pe = dnfile.dnPE(str(path))
        self.owners = {}
        self.methods = []
        for t in self.pe.net.mdtables.TypeDef:
            owner = str(t.TypeNamespace) + '.' + str(t.TypeName)
            for m in t.MethodList:
                self.owners[(6, m.row_index)] = owner
                self.methods.append((owner, m.row_index, m.row))
            for f in t.FieldList:
                self.owners[(4, f.row_index)] = owner

    def resolve(self, token):
        value = token.value if isinstance(token, Token) else token
        table, index = value >> 24, value & 0xffffff
        try:
            if table == 0x70:
                return repr(str(self.pe.net.user_strings.get(index)))
            row = self.pe.net.mdtables.tables[table].rows[index-1]
            if index < 1:
                return f'INVALID(0x{value:08x})'
            name = str(getattr(row, 'Name', getattr(row, 'TypeName', '?')))
            owner = self.owners.get((table, index), '')
            if table == 10:
                c = row.Class.row
                owner = str(getattr(c, 'TypeNamespace', ''))+'.'+str(getattr(c, 'TypeName', getattr(c, 'Name', '?')))
            return f'{owner}::{name} [0x{value:08x}]'
        except (KeyError, IndexError, AttributeError):
            return f'UNRESOLVED(0x{value:08x})'

    def body(self, method):
        return read_method_body_from_bytes(self.pe.get_data(method.Rva))

    def dump(self, pattern=''):
        out = []
        for owner, index, m in self.methods:
            if pattern and pattern.lower() not in (owner+'::'+str(m.Name)).lower():
                continue
            out.append(f'\nMETHOD {owner}::{m.Name} token=0x{0x06000000+index:08x} RVA=0x{m.Rva:x}')
            if not m.Rva:
                continue
            try:
                body = self.body(m)
                for ins in body.instructions:
                    arg = self.resolve(ins.operand) if isinstance(ins.operand, Token) else str(ins.operand) if ins.operand is not None else ''
                    out.append(f'{ins.offset:04x} {str(ins.opcode.name):18} {arg}')
            except Exception as e:
                out.append('ERROR '+repr(e))
        return '\n'.join(out)+'\n'


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('assembly', type=Path)
    ap.add_argument('--match', default='')
    ap.add_argument('--strings', type=Path, help='Optional JSON string table from static_strings.py')
    ap.add_argument('-o', '--output', type=Path)
    args = ap.parse_args()
    text = Assembly(args.assembly).dump(args.match)
    if args.strings:
        strings=json.loads(args.strings.read_text())
        text=re.sub(r'ldc.i4\s+(\d+)\n([0-9a-f]+) call\s+[^\n]+::U8IPZoo1I \[0x[0-9a-f]+\]',
                    lambda m:'ldstr.decoded      '+repr(strings.get(m[1],'<missing>'))+'\n'+m[2]+' string.lookup      '+m[1],text)
    if args.output:
        args.output.write_text(text)
    else:
        print(text)
