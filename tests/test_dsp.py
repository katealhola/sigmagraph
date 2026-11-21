# SPDX-License-Identifier: GPL-3.0-or-later
import cmath
import os
import copy
from dataclasses import asdict
import json
import math
from pathlib import Path
import tempfile
import unittest
from sigmagraph.model import Project,make_node,demo_project,from_dspproj
from sigmagraph.persistence import save_project,load_project
from sigmagraph.compiler import compile_project
from sigmagraph.codec1701 import unpack_instruction,encode_q523
from sigmagraph.dsp import simulate,DSPError

ROOT=Path(__file__).resolve().parents[2]
REFERENCE=Path(os.environ.get('SIGMAGRAPH_ANALYSIS_DIR',ROOT/'tests'/'private-analysis'))
SOURCE=Path(os.environ.get('SIGMAGRAPH_REFERENCE_DIR',ROOT/'tests'/'private-reference'))

def mono(kind=None):
    p=Project();a=make_node('input');o=make_node('output')
    p.nodes={a.id:a,o.id:o};n=make_node(kind) if kind else None
    if n:
        p.nodes[n.id]=n
        if kind=='gain':n.ports=[n.inputs[0],n.outputs[0]]
        p.connect(a.id,a.outputs[0].id,n.id,n.inputs[0].id)
        p.connect(n.id,n.outputs[0].id,o.id,o.inputs[0].id)
    else:p.connect(a.id,a.outputs[0].id,o.id,o.inputs[0].id)
    return p,a,n,o

class InstructionModel:
    """Test-only functional instruction interpreter; no pipeline/hardware claim.

    Interprets emitted bytes independently of graph models and compiler macros.
    Lower-word writes retain the fractional 23 bits. Wide products use integers.
    """
    def __init__(self,program,parameters):
        self.code=[unpack_instruction(program[i:i+5]) for i in range(0,len(program),5)]
        self.parameters=[int.from_bytes(parameters[i:i+4],'big') for i in range(0,len(parameters),4)]
        self.memory=[0]*2048;self.frame=0

    @staticmethod
    def signed(v):return v-(1<<28) if v&(1<<27) else v

    def run(self,inputs):
        acc=0;x=0;y=0;serial=iter(inputs);out=[0]*12
        def data(address):
            if address==8190:return 1<<23
            if address==8189:return 0
            if not 0<=address<2048:raise AssertionError('Unmodeled data address '+str(address))
            return self.memory[(address+self.frame)%2048]
        def coeff(address):
            if address==2047:return y
            if 512<=address<1536:return self.signed(self.parameters[address-512])
            if 260<=address<=287:return round(2**(264-address)*(1<<23))
            if address==0:return 0
            raise AssertionError('Unmodeled coefficient '+str(address))
        for f in self.code:
            dest,mux=f['reg_destination'],f['mux'];d=f['data_address']+(x if f['use_xreg_offset'] else 0)
            if dest==5:x=self.parameters[f['coeff_address']-512];continue
            if dest==6:y=data(d);continue
            if dest==1:
                initial={0:0,1:acc,10:acc>>23}.get(mux)
                if initial is None:raise AssertionError('Unmodeled MAC mux')
                term=coeff(f['coeff_address'])*data(d)
                acc=initial+(-term if f['subtract'] else term)
            elif dest==7:
                if mux==4:value=round(next(serial)*(1<<23))
                elif mux==1:value=max(-(1<<27),min((1<<27)-1,acc>>23))
                elif mux==9:value=acc&((1<<23)-1)
                else:raise AssertionError('Unmodeled RAM mux')
                self.memory[(d+self.frame)%2048]=value
            elif dest==0 and 8165<=d<=8176:
                out[d-8165]=(acc>>23)/(1<<23)
            elif dest!=0:raise AssertionError('Unmodeled destination')
        self.frame+=1
        return out

class PersistenceTests(unittest.TestCase):
    def test_native_roundtrip_keeps_all_editable_fields_and_unknown_data(self):
        p=demo_project();p.original_graph={'objects':{1:{'unknown':[None,False,42,'x']}}}
        n=next(iter(p.nodes.values()));n.x=123.75;n.properties['future']={'unknown':[1,2,3]}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.sgproj';save_project(p,path);loaded=load_project(path)
            self.assertEqual(json.loads(json.dumps(asdict(p))),json.loads(json.dumps(asdict(loaded))))
            with self.assertRaises(ValueError):save_project(p,Path(d)/'original.dspproj')
            self.assertFalse((Path(d)/'original.dspproj').exists())

    def test_malformed_files_rejected_and_failed_save_keeps_original(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.sgproj';p=demo_project();save_project(p,path);before=path.read_bytes()
            n=next(iter(p.nodes.values()));n.x=math.nan
            with self.assertRaises(ValueError):save_project(p,path)
            self.assertEqual(path.read_bytes(),before)
            doc=json.loads(before);doc['schema']=200;path.write_text(json.dumps(doc))
            with self.assertRaises(ValueError):load_project(path)
            doc=json.loads(before);edge=next(iter(doc['project']['connections'].values()));edge['source_port']='missing';path.write_text(json.dumps(doc))
            with self.assertRaises(ValueError):load_project(path)

class DSPTests(unittest.TestCase):
    def test_passthrough_binary_vectors_and_export(self):
        p,a,n,o=mono();build=compile_project(p)
        self.assertEqual(len(build.program),5120);self.assertEqual(len(build.parameters),4096)
        self.assertEqual(build.program[:20].hex(),'0000000001000000e8010000000001000800e801')
        cpu=InstructionModel(build.program,build.parameters)
        for sample in [.25,-.5,.125,0]:self.assertEqual(cpu.run([sample,0])[8],sample)
        with tempfile.TemporaryDirectory() as d:
            root=build.export(Path(d)/'build');manifest=json.loads((root/'manifest.json').read_text())
            self.assertEqual(manifest['images'][0]['word_address'],1024)
            self.assertEqual((root/'program.bin').read_bytes(),build.program)
            with self.assertRaises(ValueError):build.export(root)

    def test_delay_program_matches_impulse_and_phase(self):
        p,a,n,o=mono('delay');n.properties['Value0']=7
        build=compile_project(p);cpu=InstructionModel(build.program,build.parameters)
        samples=[cpu.run([.5 if i==0 else 0,0])[8] for i in range(20)]
        self.assertEqual(samples,[0]*7+[.5]+[0]*12)
        h=simulate(p,(a.id,a.outputs[0].id),(o.id,o.inputs[0].id),[1000])[0]
        self.assertAlmostEqual(abs(h-cmath.exp(-2j*math.pi*1000/48000*7)),0,places=12)

    def test_gain_slew_is_executed_by_binary(self):
        p,a,n,o=mono('gain');n.properties.update(gain=-6.020599913279624,step=2)
        b=compile_project(p);cpu=InstructionModel(b.program,b.parameters)
        gain=0
        for i in range(40):
            gain+=(.5-gain)/4
            self.assertAlmostEqual(cpu.run([.25,0])[8],gain*.25,delta=3e-7)

    def test_filter_program_response_matches_frequency_analysis(self):
        p,a,n,o=mono('filter');n.properties['Frequency']=3000
        b=compile_project(p);cpu=InstructionModel(b.program,b.parameters)
        impulse=[cpu.run([.25 if i==0 else 0,0])[8] for i in range(1024)]
        for f in [300,3000,12000]:
            measured=sum(x*cmath.exp(-2j*math.pi*f/48000*i) for i,x in enumerate(impulse))/.25
            predicted=simulate(p,(a.id,a.outputs[0].id),(o.id,o.inputs[0].id),[f],True)[0]
            self.assertAlmostEqual(abs(measured-predicted),0,delta=3e-5)
        # Butterworth's defining corner attenuation, independently of the model.
        corner=simulate(p,(a.id,a.outputs[0].id),(o.id,o.inputs[0].id),[3000])[0]
        self.assertAlmostEqual(20*math.log10(abs(corner)),-3.01029995664,places=8)

    def test_summed_routes_and_internal_stimulus(self):
        from sigmagraph.registry import catalog
        entry=next(k for k,v in catalog().items() if v['type_name']=='AdderAlg')
        p,a,n,o=mono('delay');n.properties['Value0']=0
        add=make_node(entry);p.nodes[add.id]=add
        self.assertGreaterEqual(len(add.inputs),2)
        # Retain only the two tested channels if this preset is growable.
        add.ports=add.inputs[:2]+add.outputs[:1]
        p.connect(n.id,n.outputs[0].id,add.id,add.inputs[0].id)
        p.connect(n.id,n.outputs[0].id,add.id,add.inputs[1].id)
        p.connect(add.id,add.outputs[0].id,o.id,o.inputs[0].id)
        h=simulate(p,(n.id,n.outputs[0].id),(o.id,o.inputs[0].id),[1000])[0]
        self.assertEqual(h,2+0j)
        b=compile_project(p);cpu=InstructionModel(b.program,b.parameters)
        self.assertEqual(cpu.run([.125,0])[8],.25)

    def test_diagnostics_for_unknown_cycles_rates_and_resource_exhaustion(self):
        p,a,n,o=mono('delay');n.source_algorithm['$type']='ADICtrls.UnknownDelay'
        with self.assertRaisesRegex(DSPError,'unsupported algorithm'):compile_project(p)
        with self.assertRaisesRegex(DSPError,'unsupported algorithm'):simulate(p,(a.id,a.outputs[0].id),(o.id,o.inputs[0].id),[1000])
        n.source_algorithm={};n.properties['Value0']=2047
        with self.assertRaisesRegex(DSPError,'Data RAM exhausted'):compile_project(p)
        n.properties['Value0']=1;n.fs=96000
        with self.assertRaisesRegex(DSPError,'sample rates'):compile_project(p)
        n.fs=48000;p.connect(n.id,n.outputs[0].id,n.id,n.inputs[0].id)
        with self.assertRaisesRegex(DSPError,'cycles'):compile_project(p)

    @unittest.skipUnless(REFERENCE.exists() and (SOURCE/'StereoPA2tie011.dspproj').exists(),'Original reference unavailable')
    def test_original_coefficients_and_vendor_program_equivalence(self):
        p=from_dspproj(SOURCE/'StereoPA2tie011.dspproj')
        # The 010 export differs from 011 only in these two cutoff frequencies.
        for node in p.nodes.values():
            if node.kind=='filter':node.properties['Frequency']=32
        build=compile_project(p)
        params={r['name']:r['data_hex'] for r in build.parameter_map}
        original=json.loads((REFERENCE/'StereoPA2tie010.parameters.json').read_text())
        checked=0
        for r in original:
            if r['name'] in params:
                self.assertEqual(params[r['name']],r['data_hex'],r['name']);checked+=1
        self.assertEqual(checked,254)
        old=InstructionModel((REFERENCE/'StereoPA2tie010.program.bin').read_bytes(),(REFERENCE/'StereoPA2tie010.parameters.bin').read_bytes())
        new=InstructionModel(build.program,build.parameters)
        max_error=0
        for i in range(4096):
            source=[.1*math.sin(i*.31),.12*math.sin(i*.17)]
            before,after=old.run(source),new.run(source)
            max_error=max(max_error,max(abs(a-b) for a,b in zip(before[8:],after[8:])))
        self.assertLess(max_error,2e-6)

    @unittest.skipUnless((SOURCE/'FaneImperiumSub04.params').exists(),'Original Fane export unavailable')
    def test_fane_fourth_order_and_general_biquad_coefficients(self):
        import re
        p=from_dspproj(SOURCE/'FaneImperiumSub04.dspproj')
        b=compile_project(p);actual={r['name']:r['data_hex'] for r in b.parameter_map}
        text=(SOURCE/'FaneImperiumSub04.params').read_text()
        checked=0
        for block in text.split('Cell Name         = ')[1:]:
            name=re.search(r'Parameter Name\s*=\s*(\S+)',block)[1]
            data=''.join(re.findall(r'0x([0-9a-fA-F]{2})',block.split('Parameter Data :')[1])[:4]).lower()
            self.assertEqual(actual[name],data,name);checked+=1
        self.assertEqual(checked,32)
        node=next(n for n in p.nodes.values() if n.kind=='filter')
        from sigmagraph.dsp import transfer
        self.assertAlmostEqual(20*math.log10(abs(transfer(node,100))),-3.01029995664,places=7)

if __name__=='__main__':unittest.main()
