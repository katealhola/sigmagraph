# SPDX-License-Identifier: GPL-3.0-or-later
"""Instrument actual compiler output with a DC source and host-readable probes.

ADC reads become a constant injection; DAC writes become interface-register
writes. Gain, three PEQ sections, low-pass and delay instructions stay intact.
This tests steady-state DSP execution, not analog I/O or frequency response.
"""
import math
import time
from sigmagraph.compiler import compile_project
from sigmagraph.model import Project,make_node
from sigmagraph.persistence import save_project
from sigmagraph.codec1701 import NOP,pack_instruction,unpack_instruction,encode_q523,decode_q523
from sigmagraph.dsp import transfer

def project(gain_db):
    p=Project('Hardware probe: gain, EQ, low-pass, delay')
    adc,gain,eq,lp,delay=[make_node(k) for k in ('input','gain','peq','first_order','delay')]
    gain.ports=[gain.inputs[0],gain.outputs[0]]
    gain.properties['gain']=gain_db
    eq.ui['S0.R0.Boost1']=6.
    delay.properties['Value0']=7
    nodes=[adc,gain,eq,lp,delay]
    outputs=[make_node('output') for _ in range(4)]
    for i,n in enumerate(outputs):n.properties['selectedchannel']=f'DAC{i}'
    for i,n in enumerate(nodes+outputs):
        p.nodes[n.id]=n;n.x=i*150;n.y=50 if n not in outputs else 250
    for a,b in zip(nodes,nodes[1:]):p.connect(a.id,a.outputs[0].id,b.id,b.inputs[0].id)
    for a,b in zip(nodes[1:],outputs):p.connect(a.id,a.outputs[0].id,b.id,b.inputs[0].id)
    return p,nodes

def instrument(build,stimulus):
    program=bytearray(build.program);parameters=bytearray(build.parameters)
    index=len(build.parameter_map)
    if index>=1024:raise ValueError('No free parameter for stimulus.')
    parameters[index*4:index*4+4]=encode_q523(stimulus)
    # Same four-instruction extent as the compiler's two ADC staging reads.
    program[:20]=b''.join([
        pack_instruction(data_address=8190,coeff_address=512+index,reg_destination=1),NOP,
        pack_instruction(data_address=0,reg_destination=7,mux=1),
        pack_instruction(data_address=1,reg_destination=7,mux=0)])
    probes=[]
    for pc in range(4,1024):
        f=unpack_instruction(program[pc*5:pc*5+5])
        if f['reg_destination']==0 and 8173<=f['data_address']<=8176:
            channel=f['data_address']-8173
            f['data_address']=8144+channel
            program[pc*5:pc*5+5]=pack_instruction(**f)
            probes.append({'pc':pc,'DAC':channel,'interface':channel})
    if len(probes)!=4:raise ValueError('Expected four DAC probes.')
    return bytes(program),bytes(parameters),probes,index

def run_compiler_probe(session):
    results=[]
    for i,(stimulus,gain_db) in enumerate(((.25,-6.020599913279624),(-.25,0.),(.25,-12.041199826559248))):
        print(f'Testing compiled graph case {i+1}: input {stimulus}, gain {gain_db:g} dB',flush=True)
        root=session.out/f'case-{i+1}';root.mkdir()
        p,nodes=project(gain_db);save_project(p,root/'project.sgproj')
        build=compile_project(p);build.export(root/'compiler-build')
        program,parameters,probes,index=instrument(build,stimulus)
        (root/'instrumented-program.bin').write_bytes(program)
        (root/'instrumented-parameters.bin').write_bytes(parameters)
        readback=session.load(program,parameters)
        session.seed_interfaces();session.core(session.muted)
        time.sleep(1.5) # RC slew plus filter/delay state settling.
        expected=[];value=stimulus
        for node in nodes[1:]:
            value*=transfer(node,0,quantized=True).real
            expected.append(value)
        reads=[]
        for _ in range(2):
            raw=session.read(0x800,4,4)
            actual=[decode_q523(raw[j:j+4]) for j in range(0,16,4)]
            reads.append({'actual':actual,'raw_hex':raw.hex()})
            if any(not math.isfinite(a) or abs(a-b)>3e-5 for a,b in zip(actual,expected)):
                raise RuntimeError(f'Compiled graph case {i+1}: expected {expected}, read {actual}')
            time.sleep(.05)
        result={'stimulus':stimulus,'gain_db':gain_db,'expected_dc':expected,
                'reads':reads,'absolute_tolerance':3e-5,'resources':build.resources,
                'instrumentation':{'stimulus_parameter':index,'output_replacements':probes},
                'ram_readback':readback}
        from usb_transport import atomic_json
        atomic_json(root/'results.json',result);results.append(result)
    return {'cases':results,'scope':'Instrumented graph execution at DC. Analog ADC/DAC I/O, delay timing and filter frequency response not measured.'}
