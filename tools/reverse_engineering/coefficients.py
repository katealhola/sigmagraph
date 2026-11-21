# SPDX-License-Identifier: GPL-3.0-or-later
"""Recovered coefficient generation for the StereoPA reference configuration.

Regenerates values from .dspproj settings using an existing named address layout.
No exported parameter values are read. This intentionally supports only checked
configurations: peaking EQ, order-2 Butterworth HP, first-order LP, the observed
crossover shape, RC gain, and integer delays. It is not a general compiler.
"""
import argparse
import json
import math
import re
from pathlib import Path
from nrbf import Reader
from analyze import project_summary
from adau1701 import encode_q523, parameter_image


def peaking(fs, frequency, q, gain_db):
    w=2*math.pi*frequency/fs
    a=10**(gain_db/40)
    alpha=math.sin(w)/(2*q)
    norm=1+alpha/a
    # Sigma stores negated denominator feedback coefficients.
    return [(1+alpha*a)/norm, -2*math.cos(w)/norm, (1-alpha*a)/norm,
            2*math.cos(w)/norm, -(1-alpha/a)/norm]


def butterworth2(fs, frequency, highpass):
    w=2*math.pi*frequency/fs
    alpha=math.sin(w)/math.sqrt(2)
    norm=1+alpha
    b0=(1+math.cos(w))/2/norm if highpass else (1-math.cos(w))/2/norm
    b1=(-2 if highpass else 2)*b0
    return [b0,b1,b0,2*math.cos(w)/norm,-(1-alpha)/norm]


def first_order_lowpass(fs,frequency,gain_db=0):
    # Actual constant in FistOrderSingle.ReceiveData is 2.7, not Euler's e.
    alpha=math.pow(2.7,-2*math.pi*frequency/fs)
    return [10**(gain_db/20)*(1-alpha),0,alpha]


def regenerate(project, layout):
    cells={c['nid']:c for c in project['cells']}
    algs={a['text']:a for a in project['algorithms']}
    out=[]
    for entry in layout:
        name=entry['name']
        candidates=[a for key,a in algs.items() if name.startswith(key)]
        if not candidates:
            raise ValueError('No algorithm for '+name)
        a=max(candidates,key=lambda x:len(x['text']))
        c=cells[a['cell']]
        suffix=name[len(a['text']):]
        kind=a['$type'].split('.')[-1]
        u=c['ui_settings']
        fs=a['fs']
        value=None
        integer=False
        if kind=='SWGain1940DBAlg':
            if suffix=='target':value=10**(c['gain']/20)
            elif suffix=='step':value=2**(-c['step'])
        elif kind=='MultCtrlDel1940Alg':
            if suffix=='':
                value=c['Value0']
                if value!=int(value):raise ValueError('Fractional delay outside supported configuration')
                integer=True
        elif kind=='FistOrderSingle':
            m=re.fullmatch(r'([012])1',suffix)
            if m and c['Count']==1 and c['firstorder_type0']==0:
                value=first_order_lowpass(fs,c['firstorder_freq0'],c['firstorder_gain0'])[int(m[1])]
        elif kind in ('PEQ1Chan','NthOrderDouble'):
            m=re.fullmatch(r'([012])([BA])(\d+)',suffix)
            if m:
                pos,term,band=int(m[1]),m[2],int(m[3])-1
                index={('B',0):0,('B',1):1,('B',2):2,('A',1):3,('A',2):4}[(term,pos)]
                if kind=='PEQ1Chan':
                    def setting(key):return u[f'S0.R0.{key}{band}']
                    if setting('Type')!=0 or setting('Bypass'):
                        raise ValueError('Only enabled peaking EQ supported: '+name)
                    values=peaking(fs,setting('Frequency1'),setting('Q'),setting('Boost'))
                    value=values[index]
                elif c['type']==0 and c['Order']==2 and c['BitmapIndex']==1 and c['FilterEnabled'] and not c['PhaseShiftEnabled'] and band==0:
                    value=butterworth2(fs,c['Frequency'],True)[index]
        elif kind=='CrossoverFilter2WayAlgDP':
            def setting(key):return u['S0.R0.'+key]
            # Scope is deliberately explicit; other crossover families need more RE.
            if [setting('Type'+str(i)) for i in range(1,5)]!=[1,1,1,0] or setting('InvertHigh') or setting('InvertLow') or setting('Gain1')!=0 or setting('Gain2')!=0:
                raise ValueError('Unsupported crossover configuration')
            if suffix=='LowInvert':value=1.0
            else:
                m=re.fullmatch(r'([BA][012])_([0-3])',suffix)
                if m:
                    term,section=m[1],int(m[2])
                    if section<2:
                        values=butterworth2(fs,setting('FrequencyLow'),False)
                        value=dict(zip(('B0','B1','B2','A1','A2'),values))[term]
                    else:
                        t=math.tan(math.pi*setting('FrequencyHigh')/fs)
                        b0=1/(1+t)
                        gain=10**(setting('Gain3')/20) if section==2 else 1
                        value={'B0':b0*gain,'B1':-b0*gain,'A1':(1-t)/(1+t)}[term]
        if value is None:
            raise ValueError('Unsupported parameter: '+name)
        data=int(value).to_bytes(4,'big') if integer else encode_q523(value)
        out.append({'name':name,'cell':entry.get('cell',c['name']),
                    'address':entry['address'],'value':value,'data_hex':data.hex()})
    return out


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('project',type=Path)
    ap.add_argument('layout',type=Path,help='JSON entries containing name, address, optional cell; values ignored')
    ap.add_argument('-o','--output',type=Path,required=True)
    ap.add_argument('--records',type=Path)
    args=ap.parse_args()
    project=project_summary(Reader(args.project.read_bytes()).parse())
    records=regenerate(project,json.loads(args.layout.read_text()))
    args.output.write_bytes(parameter_image(records))
    if args.records:
        args.records.write_text(json.dumps(records,indent=2)+'\n')
    print(f'Generated {len(records)} parameters, {args.output.stat().st_size} bytes')
