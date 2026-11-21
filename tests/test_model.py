# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import os
import unittest
from pathlib import Path
from sigmagraph.model import Project, make_node, demo_project, from_dspproj

REFERENCE=Path(os.environ.get('SIGMAGRAPH_REFERENCE_DIR',Path(__file__).parent/'private-reference'))


class GraphModelTests(unittest.TestCase):
    def setUp(self):
        self.p=demo_project()

    def test_demo_has_no_unconnected_inputs(self):
        self.assertEqual(len(self.p.nodes),14)
        self.assertEqual(self.p.issues(),[])

    def test_input_driver_replaced_output_fanout_retained(self):
        sources=[n for n in self.p.nodes.values() if n.outputs]
        target=next(n for n in self.p.nodes.values() if n.kind=='peq')
        first,second=sources[:2]
        count=len(self.p.connections)
        self.p.connect(first.id,first.outputs[0].id,target.id,target.inputs[0].id)
        self.p.connect(second.id,second.outputs[0].id,target.id,target.inputs[0].id)
        self.assertEqual(len(self.p.connections),count)
        incoming=[e for e in self.p.connections.values() if e.target_port==target.inputs[0].id]
        self.assertEqual(len(incoming),1)
        self.assertEqual(incoming[0].source_node,second.id)
        self.assertGreaterEqual(len([e for e in self.p.connections.values() if e.source_node==second.id]),2)

    def test_duplicate_connection_noop(self):
        e=next(iter(self.p.connections.values()))
        before=copy.deepcopy(self.p.connections)
        self.p.connect(e.source_node,e.source_port,e.target_node,e.target_port)
        self.assertEqual(self.p.connections,before)

    def test_incompatible_ports_rejected_without_mutation(self):
        a,b=[n for n in self.p.nodes.values() if n.outputs][:2]
        before=self.p.state()
        with self.assertRaisesRegex(ValueError,'output to an input'):
            self.p.connect(a.id,a.outputs[0].id,b.id,b.outputs[0].id)
        self.assertEqual(self.p.state(),before)
        target=next(n for n in self.p.nodes.values() if n.kind=='peq')
        target.fs=96000
        with self.assertRaisesRegex(ValueError,'sample rates'):
            self.p.connect(a.id,a.outputs[0].id,target.id,target.inputs[0].id)

    def test_delete_removes_incident_connections(self):
        key=next(n.id for n in self.p.nodes.values() if n.kind=='gain')
        self.p.remove([key])
        self.assertNotIn(key,self.p.nodes)
        self.assertTrue(all(e.source_node!=key and e.target_node!=key for e in self.p.connections.values()))

    def test_layout_keeps_branch_lanes_and_terminates_on_cycles(self):
        self.p.layout()
        initial={k:(n.x,n.y) for k,n in self.p.nodes.items()}
        self.p.layout()
        self.assertEqual(initial,{k:(n.x,n.y) for k,n in self.p.nodes.items()})
        p=Project();a,b=make_node('delay'),make_node('peq');p.nodes={a.id:a,b.id:b}
        p.connect(a.id,a.outputs[0].id,b.id,b.inputs[0].id)
        p.connect(b.id,b.outputs[0].id,a.id,a.inputs[0].id)
        p.layout()
        self.assertNotEqual((a.x,a.y),(b.x,b.y))

    @unittest.skipUnless(REFERENCE.exists(),'Original user project corpus unavailable')
    def test_real_stereo_graph_and_parameters(self):
        p=from_dspproj(REFERENCE/'StereoPA2tie011.dspproj')
        self.assertEqual((len(p.nodes),len(p.connections)),(18,18))
        self.assertEqual(p.issues(),[])
        self.assertEqual(p.sample_rate,44100)
        self.assertEqual(len(p.nodes['PEQ1Chan1'].eq_bands()),12)
        self.assertEqual(len(p.nodes['PEQ1Chan2'].eq_bands()),8)
        self.assertEqual(p.nodes['NthOrderDouble2'].properties['Frequency'],37)
        self.assertIsNotNone(p.original_graph)

    @unittest.skipUnless(REFERENCE.exists(),'Original user project corpus unavailable')
    def test_all_intact_projects_load(self):
        for name in ['FaneImperiumSub','FaneImperiumSub02','FaneImperiumSub04','StereoPA2tie011']:
            with self.subTest(name=name):
                p=from_dspproj(REFERENCE/(name+'.dspproj'))
                self.assertGreater(len(p.nodes),0)
                self.assertTrue(all(p.port(e.source_node,e.source_port) and p.port(e.target_node,e.target_port) for e in p.connections.values()))

    @unittest.skipUnless(REFERENCE.exists(),'Original user project corpus unavailable')
    def test_empty_and_truncated_projects_rejected(self):
        for name in ['StereoPA2tie010.dspproj','FaneImperiumSub03.dspproj','FaneImperiumSub04 - Copy.dspproj']:
            with self.subTest(name=name),self.assertRaises(ValueError):
                from_dspproj(REFERENCE/name)
