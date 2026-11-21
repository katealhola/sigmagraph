# SPDX-License-Identifier: GPL-3.0-or-later
"""Small independent assembler for the recovered, allocated Sigma100 syntax.

Accepts numeric internal DSP addresses and .equ symbols. It does not allocate
memory, resolve schematics, or insert pipeline stalls. Unsupported syntax fails.
"""
import argparse
import re
from pathlib import Path
from .codec1701 import pack_instruction, unpack_instruction, DEST, MUX, CONDITIONS, NOP

SYMBOLS = {'ONE':8190, 'ZERO':8189, 'xreg':8188, 'yreg':2047}
SYMBOLS.update({f'2_POW_P{i}':264-i for i in range(5)})
SYMBOLS.update({f'2_POW_M{i}':264+i for i in range(1,24)})


def number(text, symbols):
    text=text.strip()
    if text in symbols:
        return symbols[text]
    return int(text, 0)


def address(text, symbols, offset_register):
    parts=re.split(r'\s*\+\s*',text.strip())
    if len(parts)==1:
        return number(parts[0],symbols), 0
    if len(parts)==2 and parts[1]==offset_register:
        return number(parts[0],symbols), 1
    raise ValueError(f'Unsupported address: {text}')


def assemble_line(line, symbols=None):
    symbols=SYMBOLS if symbols is None else symbols
    line=line.strip().rstrip(';').strip()
    if line.lower()=='nop':
        return NOP
    base, *modifiers = line.split('|')
    f={}
    for mod in modifiers:
        mod=mod.strip()
        if mod in ('skip','swap','ucr'):
            f[{'skip':'skip_on_condition','swap':'swap_on_condition','ucr':'update_condition'}[mod]]=1
        elif mod.startswith('condition='):
            f['condition_select']={v:k for k,v in CONDITIONS.items()}[mod.split('=',1)[1].strip()]
        else:
            raise ValueError(f'Unsupported modifier: {mod}')
    m=re.fullmatch(r'(accum[012]|dbreg)\s*=\s*(\w+)\s*([+-])\s*coeff\[([^]]+)\]\s*\*\s*data\[([^]]+)\]',base.strip())
    if m:
        d,src,sign,coeff,data=m.groups()
        f.update(reg_destination={v:k for k,v in DEST.items()}[d], mux={v:k for k,v in MUX.items()}[src], subtract=int(sign=='-'))
        f['coeff_address'],f['use_yreg_offset']=address(coeff,symbols,'yreg')
        f['data_address'],f['use_xreg_offset']=address(data,symbols,'xreg')
        return pack_instruction(**f)
    m=re.fullmatch(r'data\[([^]]+)\]\s*=\s*(\w+)',base.strip())
    if m:
        addr,src=m.groups()
        f['data_address'],f['use_xreg_offset']=address(addr,symbols,'xreg')
        f.update(reg_destination=7,mux={v:k for k,v in MUX.items()}[src])
        return pack_instruction(**f)
    m=re.fullmatch(r'(yreg|xreg)\s*=\s*(data|coeff)\[([^]]+)\]',base.strip())
    if m:
        dest,kind,addr=m.groups()
        if (dest,kind) not in [('yreg','data'),('xreg','coeff')]:
            raise ValueError('Observed compiler writes yreg from data and xreg from coeff')
        f['reg_destination']=6 if dest=='yreg' else 5
        key='data_address' if kind=='data' else 'coeff_address'
        flag='use_xreg_offset' if kind=='data' else 'use_yreg_offset'
        f[key],f[flag]=address(addr,symbols,'xreg' if kind=='data' else 'yreg')
        return pack_instruction(**f)
    m=re.fullmatch(r'digout\[([^]]+)\]\s*=\s*(\w+)',base.strip())
    if m:
        index=number(m[1],symbols)
        if not 0<=index<=11:
            raise ValueError('digout index outside observed range 0..11')
        f.update(data_address=8165+index,mux={v:k for k,v in MUX.items()}[m[2]])
        return pack_instruction(**f)
    raise ValueError('Unsupported instruction: '+line)


def assemble(text, pad_to=None):
    symbols=SYMBOLS.copy()
    out=bytearray()
    for n,line in enumerate(text.splitlines(),1):
        line=line.split('//',1)[0].strip()
        if not line:
            continue
        if line.startswith('.equ '):
            name,val=line[5:].split('=',1)
            symbols[name.strip()]=number(val,symbols)
            continue
        try:
            out.extend(assemble_line(line,symbols))
        except (ValueError,KeyError) as e:
            raise ValueError(f'Line {n}: {e}') from e
    if pad_to is not None:
        if len(out)//5>pad_to:
            raise ValueError('Program exceeds instruction budget')
        out.extend(NOP*(pad_to-len(out)//5))
    if len(out)>5120:
        raise ValueError('ADAU1701 program RAM holds at most 1024 instructions')
    return bytes(out)


def disassemble_word(word):
    f=unpack_instruction(word)
    if word==NOP:
        return 'nop'
    d,c=f['data_address'],f['coeff_address']
    da=str(d)+(' + xreg' if f['use_xreg_offset'] else '')
    ca=str(c)+(' + yreg' if f['use_yreg_offset'] else '')
    dest,mux=f['reg_destination'],MUX.get(f['mux'])
    if mux is None:
        raise ValueError('Unrecognized mux code')
    if dest in (1,2,3,4):
        text=f"{DEST[dest]} = {mux} {'-' if f['subtract'] else '+'} coeff[{ca}]*data[{da}]"
    elif dest==7 and c==0 and not f['use_yreg_offset']:
        text=f'data[{da}] = {mux}'
    elif dest==5 and d==0 and f['mux']==0:
        text=f'xreg = coeff[{ca}]'
    elif dest==6 and c==0 and f['mux']==0:
        text=f'yreg = data[{da}]'
    elif dest==0 and c==0 and 8165<=d<=8176:
        text=f'digout[{d-8165}] = {mux}'
    else:
        raise ValueError(f'Unsupported instruction pattern {word.hex()}')
    for flag,mod in [('skip_on_condition','skip'),('swap_on_condition','swap'),('update_condition','ucr')]:
        if f[flag]:
            text+=' | '+mod
    if f['condition_select']!=1:
        text+=' | condition='+CONDITIONS[f['condition_select']]
    if assemble_line(text)!=word:
        raise ValueError(f'Instruction has fields outside supported syntax: {word.hex()}')
    return text+';'


def disassemble(program):
    if len(program)%5:
        raise ValueError('Program size must be a multiple of five')
    return '\n'.join(disassemble_word(program[i:i+5])+f' // PC {i//5}' for i in range(0,len(program),5))+'\n'


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['assemble','disassemble'])
    p.add_argument('source',type=Path)
    p.add_argument('-o','--output',type=Path,required=True)
    p.add_argument('--pad-to',type=int)
    args=p.parse_args()
    if args.command=='assemble':
        args.output.write_bytes(assemble(args.source.read_text(),args.pad_to))
    else:
        args.output.write_text(disassemble(args.source.read_bytes()))
