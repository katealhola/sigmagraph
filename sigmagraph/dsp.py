# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared verified linear models used by the compiler and frequency analyzer.

Feedback coefficients are stored with SigmaDSP's negated-denominator convention.
Unknown toolbox classes are never inferred from the icon or display label.
"""
from __future__ import annotations
import cmath
import math
from collections import deque

class DSPError(ValueError):
    pass

TYPES = {'input':{'ICSigma100In'}, 'output':{'ICSigma100Out'},
         'gain':{'SWGain1940DBAlg'}, 'peq':{'PEQ1Chan'},
         'filter':{'NthOrderDouble'}, 'first_order':{'FistOrderSingle'},
         'crossover':{'CrossoverFilter2WayAlgDP'}, 'delay':{'MultCtrlDel1940Alg'},
         'biquad':{'EQ1940SingleS'},
         'add':{'AdderAlg'}, 'subtract':{'SubAlg'}, 'invert':{'EQ1940Invert'}}

def checked(node):
    typename = node.source_algorithm.get('$type',node.catalog_id).split(',')[0].split('.')[-1]
    if node.kind not in TYPES or (typename and typename not in TYPES[node.kind]):
        raise DSPError(f'{node.label}: unsupported algorithm {typename or node.kind}.')
    ni,no=len(node.inputs),len(node.outputs)
    if ((node.kind in ('peq','filter','first_order','biquad','delay','invert') and (ni,no)!=(1,1)) or
        (node.kind=='crossover' and (ni,no)!=(1,2)) or
        (node.kind=='gain' and (ni!=no or ni==0)) or
        (node.kind=='output' and (ni,no)!=(1,0)) or
        (node.kind in ('add','subtract') and (ni<2 or no!=1))):
        raise DSPError(f'{node.label}: unsupported port configuration.')

def finite(value, label):
    try: value = float(value)
    except (ValueError, TypeError): raise DSPError(label+': invalid numeric value.')
    if not math.isfinite(value): raise DSPError(label+': expected a finite value.')
    return value

def frequency(fs, value):
    f = finite(value,'Frequency')
    if not 0 < f < fs/2: raise DSPError('Filter frequency must lie between 0 Hz and Nyquist.')
    return f

def peaking(fs,f,q,g):
    f=frequency(fs,f);q=finite(q,'Q');g=finite(g,'Boost')
    if q <= 0: raise DSPError('EQ Q must be positive.')
    a=10**(g/40);w=2*math.pi*f/fs;alpha=math.sin(w)/(2*q);norm=1+alpha/a
    return [(1+alpha*a)/norm,-2*math.cos(w)/norm,(1-alpha*a)/norm,
            2*math.cos(w)/norm,-(1-alpha/a)/norm]

def butterworth(fs,f,highpass,q=1/math.sqrt(2)):
    w=2*math.pi*frequency(fs,f)/fs;alpha=math.sin(w)/(2*q);norm=1+alpha
    b=(1+math.cos(w))/2/norm if highpass else (1-math.cos(w))/2/norm
    return [b,(-2 if highpass else 2)*b,b,2*math.cos(w)/norm,-(1-alpha)/norm]

def sections(node,branch=0):
    """Return cascaded [b0,b1,b2,feedback1,feedback2] sections."""
    checked(node)
    p,u,fs=node.properties,node.ui,node.fs
    if not node.enabled: return []
    if node.kind=='peq':
        result=[]
        for i in node.eq_bands():
            get=lambda k,d:u.get(f'S0.R0.{k}{i}',d)
            if get('Bypass',False): result.append([1,0,0,0,0]);continue
            if get('Type',0)!=0: raise DSPError('Only peaking EQ bands (type 0) are supported.')
            result.append(peaking(fs,get('Frequency1',1000),get('Q',1),get('Boost',0)))
        return result
    if node.kind=='filter':
        if not p.get('FilterEnabled',True): return []
        order=finite(p.get('Order',2),'Order')
        if p.get('type',0)!=0 or order not in (2,4) or p.get('BitmapIndex',1) not in (0,1) or p.get('PhaseShiftEnabled',False):
            raise DSPError('Supported general filter: order-2 or order-4 Butterworth, low-pass or high-pass, without phase shift.')
        return [butterworth(fs,p.get('Frequency',40),p.get('BitmapIndex',1)==1,
                            1/(2*math.cos(math.pi*(2*i+1)/(2*order)))) for i in range(int(order)//2)]
    if node.kind=='biquad':
        get=lambda k,d:u.get('S0.R0.'+k,d)
        if not get('FilterEnable',True):return []
        if get('Type',2)!=2 or get('GeneralType',1)!=1 or get('PhaseShifted',False) or get('Gain',0)!=0 or get('ClassicEE_Filtering',False):
            raise DSPError('Supported general biquad: standard high-pass (Type 2, GeneralType 1), 0 dB gain, without phase shift.')
        q=finite(get('Q',1.41),'Q')
        if q<=0:raise DSPError('Filter Q must be positive.')
        return [butterworth(fs,get('Frequency1',20),True,q)]
    if node.kind=='first_order':
        count=p.get('Count',1)
        if count!=1 or p.get('firstorder_type0',0)!=0:
            raise DSPError('Supported first-order filter: one low-pass section.')
        a=2.7**(-2*math.pi*frequency(fs,p.get('firstorder_freq0',2000))/fs)
        return [[10**(finite(p.get('firstorder_gain0',0),'Gain')/20)*(1-a),0,0,a,0]]
    if node.kind=='crossover':
        get=lambda k,d:u.get('S0.R0.'+k,d)
        if [get('Type'+str(i),d) for i,d in enumerate([1,1,1,0],1)]!=[1,1,1,0]:
            raise DSPError('Supported crossover shape: Type1..4 = 1,1,1,0 (the recovered reference configuration).')
        if get('Gain1',0)!=0 or get('Gain2',0)!=0:
            raise DSPError('Crossover Gain1 and Gain2 must be 0 dB in this compiler.')
        if branch==0:
            result=[butterworth(fs,get('FrequencyLow',1000),False) for _ in range(2)]
        else:
            t=math.tan(math.pi*frequency(fs,get('FrequencyHigh',1500))/fs);b=1/(1+t)
            gain=10**(finite(get('Gain3',0),'Gain3')/20)
            result=[[b*gain,-b*gain,0,(1-t)/(1+t),0],[b,-b,0,(1-t)/(1+t),0]]
        if get('InvertLow' if branch==0 else 'InvertHigh',False):
            result[0]=[-x if i<3 else x for i,x in enumerate(result[0])]
        return result
    return []

def delay_samples(node):
    n=finite(node.properties.get('Value0',1),'Delay')
    if n != int(n) or not 0<=n<2048: raise DSPError('Delay must be an integer from 0 to 2047 samples.')
    return int(n)

def topological(project):
    counts={k:0 for k in project.nodes};children={k:[] for k in project.nodes}
    for edge in project.connections.values():
        if edge.source_node not in counts or edge.target_node not in counts: raise DSPError('Missing block in connection.')
        counts[edge.target_node]+=1;children[edge.source_node].append(edge.target_node)
    queue=deque(k for k in counts if counts[k]==0);out=[]
    while queue:
        k=queue.popleft();out.append(project.nodes[k])
        for child in children[k]:
            counts[child]-=1
            if counts[child]==0: queue.append(child)
    if len(out)!=len(counts): raise DSPError('Feedback cycles are not yet supported. Break the cycle to compile or analyze.')
    return out

def quantize(value):
    from .codec1701 import encode_q523,decode_q523
    return decode_q523(encode_q523(value))

def transfer(node,f,branch=0,quantized=False):
    checked(node)
    if not node.enabled: return 1+0j
    if node.kind=='gain':
        g=10**(finite(node.properties.get('gain',0),'Gain')/20)
        return complex(quantize(g) if quantized else g)
    if node.kind=='delay': return cmath.exp(-2j*math.pi*f/node.fs*delay_samples(node))
    if node.kind=='invert': return -1+0j
    h=1+0j;z=cmath.exp(-2j*math.pi*f/node.fs)
    for values in sections(node,branch):
        b0,b1,b2,a1,a2=map(quantize,values) if quantized else values
        den=1-a1*z-a2*z*z
        if abs(den)<1e-25: raise DSPError('Filter has a singular response.')
        h*=(b0+b1*z+b2*z*z)/den
    return h

def simulate(project,source,probe,frequencies,quantized=False):
    """Inject unity at an output; probe any output or sink input. Other sources=0.

    Unrelated branches do not prevent probing a supported path. A signal through
    an unsupported block produces a diagnostic rather than a fictitious curve.
    """
    if not project.port(*source) or project.port(*source).direction!='out': raise DSPError('Select a stimulus output port.')
    if not project.port(*probe): raise DSPError('Select a probe port.')
    order=topological(project)
    edges={(e.target_node,e.target_port):(e.source_node,e.source_port) for e in project.connections.values()}
    relevant=set();pending=[probe]
    while pending:
        key=pending.pop()
        if key in relevant or key==source:continue
        relevant.add(key);node=project.nodes[key[0]];port=project.port(*key)
        if port.direction=='in':
            if key not in edges: raise DSPError(f'{node.label} · {port.label}: unconnected input on probe path.')
            pending.append(edges[key])
        else: pending.extend((node.id,p.id) for p in node.inputs)
    for key in relevant:
        n=project.nodes[key[0]]
        if n.fs!=project.nodes[source[0]].fs: raise DSPError('The probe path contains mixed sample rates.')
        checked(n)
    result=[]
    for f in frequencies:
        values={source:1+0j}
        for node in order:
            ins=[]
            for p in node.inputs:
                key=(node.id,p.id);values[key]=values.get(edges.get(key),0j);ins.append(values[key])
            outs=node.outputs
            if not outs:continue
            if not any((node.id,p.id) in relevant for p in outs):continue
            if not ins: signal=[0j]*len(outs)
            elif node.kind=='add': signal=[sum(ins)]*len(outs)
            elif node.kind=='subtract': signal=[ins[0]-sum(ins[1:])]*len(outs)
            else:
                signal=[ins[min(i,len(ins)-1)] if node.kind=='gain' else ins[0] for i in range(len(outs))]
            for i,p in enumerate(outs):
                key=(node.id,p.id)
                if key==source:continue
                if key in relevant:
                    try: values[key]=signal[i]*transfer(node,f,i,quantized)
                    except (ValueError,OverflowError) as exc: raise DSPError(f'{node.label}: {exc}') from exc
        result.append(values.get(probe,0j))
    return result
