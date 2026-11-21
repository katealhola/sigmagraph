# SPDX-License-Identifier: GPL-3.0-or-later
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDoubleSpinBox, QTableWidget
from sigmagraph.app import create_application, MainWindow
from sigmagraph.model import demo_project
from sigmagraph.controller import Controller


APP=create_application(['sigmagraph-tests'])


class UndoTests(unittest.TestCase):
    def setUp(self):
        self.c=Controller();self.c.load(demo_project())

    def test_edit_move_undo_redo(self):
        n=next(n for n in self.c.project.nodes.values() if n.kind=='gain')
        key=n.id;original=(n.x,n.y)
        self.c.edit(key,'properties','gain',-6.)
        self.c.move({key:(120,240)})
        self.assertFalse(self.c.undo.isClean())
        self.assertEqual(self.c.project.nodes[key].properties['gain'],-6)
        self.c.undo.undo()
        n=self.c.project.nodes[key];self.assertEqual((n.x,n.y),original)
        self.c.undo.undo();self.assertEqual(self.c.project.nodes[key].properties['gain'],0)
        self.assertTrue(self.c.undo.isClean())
        self.c.undo.redo();self.assertEqual(self.c.project.nodes[key].properties['gain'],-6)

    def test_add_delete_and_duplicate_group_undo(self):
        n1=self.c.add('peq',100,100);n2=self.c.add('delay',350,100)
        a,b=self.c.project.nodes[n1],self.c.project.nodes[n2]
        self.c.connect(a.id,a.outputs[0].id,b.id,b.inputs[0].id)
        before=self.c.project.state()
        clones=self.c.duplicate([n1,n2])
        self.assertEqual(len(clones),2)
        cloned_edges=[e for e in self.c.project.connections.values() if e.source_node in clones and e.target_node in clones]
        self.assertEqual(len(cloned_edges),1)
        self.c.undo.undo();self.assertEqual(self.c.project.state(),before)
        self.c.remove([n1]);self.assertNotIn(n1,self.c.project.nodes)
        self.c.undo.undo();self.assertEqual(self.c.project.state(),before)

    def test_invalid_mutation_is_transactional(self):
        before=self.c.project.state()
        a,b=[n for n in self.c.project.nodes.values() if n.outputs][:2]
        with self.assertRaises(ValueError):self.c.connect(a.id,a.outputs[0].id,b.id,b.outputs[0].id)
        self.assertEqual(self.c.project.state(),before)
        self.assertEqual(self.c.undo.count(),0)

    def test_new_eq_bands_initialized_and_undo_restores_dormant_state(self):
        node=next(n for n in self.c.project.nodes.values() if n.kind=='peq')
        key=node.id;before=self.c.project.state()
        self.c.edit(key,'ui','S0.R0.Index',5)
        node=self.c.project.nodes[key]
        self.assertEqual(len(node.eq_bands()),6)
        self.assertTrue(all(0<node.ui[f'S0.R0.Frequency1{i}']<node.fs/2 for i in node.eq_bands()))
        self.c.undo.undo();self.assertEqual(self.c.project.state(),before)


class DesktopInteractionTests(unittest.TestCase):
    def setUp(self):
        self.w=MainWindow();self.w.show();QTest.qWait(80)

    def tearDown(self):
        self.w.controller.undo.setClean();self.w.close();QTest.qWait(10)

    def test_save_open_and_undo_clean_state(self):
        key=next(k for k,n in self.w.controller.project.nodes.items() if n.kind=='gain')
        self.w.controller.edit(key,'properties','gain',-8)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'roundtrip.sgproj'
            with patch('sigmagraph.app.QFileDialog.getSaveFileName',return_value=(str(path),'')):
                self.assertTrue(self.w.save_document())
            self.assertTrue(self.w.controller.undo.isClean())
            self.w.controller.edit(key,'properties','gain',-12)
            self.assertFalse(self.w.controller.undo.isClean())
            self.w.controller.undo.undo();self.assertTrue(self.w.controller.undo.isClean())
            self.assertTrue(self.w.open_path(str(path)))
            self.assertEqual(self.w.controller.project.nodes[key].properties['gain'],-8)
            self.assertEqual(self.w.controller.save_path,str(path.resolve()))
            self.assertIn('SAVED',self.w.session.text())

    def test_compile_menu_exports_complete_build(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('sigmagraph.app.QFileDialog.getExistingDirectory',return_value=directory),patch('sigmagraph.app.QMessageBox.exec'):
                self.assertTrue(self.w.compile_document())
            builds=list(Path(directory).iterdir());self.assertEqual(len(builds),1)
            self.assertEqual((builds[0]/'program.bin').stat().st_size,5120)
            self.assertEqual((builds[0]/'parameters.bin').stat().st_size,4096)
            self.assertTrue((builds[0]/'manifest.json').exists())
            self.assertIsNone(self.w.controller.save_path)

    def test_simulation_live_gain_and_csv(self):
        dialog=self.w.simulate_document();QTest.qWait(20)
        self.assertEqual(len(dialog.plot.values),601)
        before=abs(dialog.plot.values[0])
        key=next(k for k,n in self.w.controller.project.nodes.items() if n.kind=='gain')
        self.w.controller.edit(key,'properties','gain',-6.020599913279624)
        QTest.qWait(200)
        self.assertAlmostEqual(abs(dialog.plot.values[0])/before,.5,places=8)
        self.assertIn('DAC0',dialog.probe.currentText())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'response.csv'
            with patch('sigmagraph.simulator.QFileDialog.getSaveFileName',return_value=(str(path),'')):
                dialog.export_csv()
            self.assertEqual(len(path.read_text().splitlines()),602)
        dialog.close();QTest.qWait(10)

    def test_large_delay_phase_sampling_avoids_aliasing(self):
        from sigmagraph.simulator import frequency_grid,unwrap
        from sigmagraph.dsp import simulate
        from sigmagraph.model import Project,make_node
        p=Project();a,n,o=make_node('input'),make_node('delay'),make_node('output')
        p.nodes={x.id:x for x in (a,n,o)}
        p.connect(a.id,a.outputs[0].id,n.id,n.inputs[0].id)
        p.connect(n.id,n.outputs[0].id,o.id,o.inputs[0].id);n.properties['Value0']=2000
        f=frequency_grid(p,10,20000,48000)
        self.assertGreater(len(f),601)
        h=simulate(p,(a.id,a.outputs[0].id),(o.id,o.inputs[0].id),f)
        phase=unwrap(h)
        self.assertAlmostEqual(phase[-1]-phase[0],-360*2000/48000*(f[-1]-f[0]),places=6)

    def test_inspector_gain_edit_and_undo(self):
        key=next(k for k,n in self.w.controller.project.nodes.items() if n.kind=='gain')
        self.w.scene.select_node(key);QTest.qWait(15)
        spin=self.w.inspector.findChild(QDoubleSpinBox,'gain')
        self.assertIsNotNone(spin)
        self.assertGreater(spin.lineEdit().width(),20)
        spin.setValue(-9);spin.editingFinished.emit();QTest.qWait(20)
        self.assertEqual(self.w.controller.project.nodes[key].properties['gain'],-9)
        self.w.controller.undo.undo();QTest.qWait(15)
        self.assertEqual(self.w.inspector.findChild(QDoubleSpinBox,'gain').value(),0)

    def test_eq_values_visible_and_editable(self):
        key=next(k for k,n in self.w.controller.project.nodes.items() if n.kind=='peq')
        self.w.scene.select_node(key);QTest.qWait(15)
        table=self.w.inspector.findChild(QTableWidget,'eqBands')
        spin=table.cellWidget(0,2)
        self.assertGreater(spin.lineEdit().width(),20)
        spin.setValue(4.5);spin.editingFinished.emit();QTest.qWait(20)
        self.assertEqual(self.w.controller.project.nodes[key].ui['S0.R0.Boost0'],4.5)

    def test_drag_node_updates_model_and_undo(self):
        key=next(k for k,n in self.w.controller.project.nodes.items() if n.kind=='gain')
        node=self.w.scene.nodes[key]
        old=node.pos()
        start=self.w.view.mapFromScene(node.mapToScene(QPointF(90,22)))
        end=start+QPoint(70,35)
        QTest.mousePress(self.w.view.viewport(),Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseMove(self.w.view.viewport(),end,20)
        QTest.mouseRelease(self.w.view.viewport(),Qt.MouseButton.LeftButton,pos=end)
        QTest.qWait(20)
        n=self.w.controller.project.nodes[key]
        self.assertNotEqual((n.x,n.y),(old.x(),old.y()))
        self.w.controller.undo.undo();QTest.qWait(10)
        n=self.w.controller.project.nodes[key]
        self.assertEqual((n.x,n.y),(old.x(),old.y()))

    def test_drag_cable_replaces_input_and_undo(self):
        p=self.w.controller.project
        source=next(n for n in p.nodes.values() if n.kind=='gain')
        target=next(n for n in p.nodes.values() if n.kind=='peq')
        original=next(e for e in p.connections.values() if e.target_node==target.id)
        a=self.w.scene.nodes[source.id].ports[source.outputs[0].id]
        b=self.w.scene.nodes[target.id].ports[target.inputs[0].id]
        start,end=self.w.view.mapFromScene(a.scenePos()),self.w.view.mapFromScene(b.scenePos())
        QTest.mousePress(self.w.view.viewport(),Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseMove(self.w.view.viewport(),end,20)
        QTest.mouseRelease(self.w.view.viewport(),Qt.MouseButton.LeftButton,pos=end)
        QTest.qWait(25)
        incoming=[e for e in p.connections.values() if e.target_node==target.id]
        self.assertEqual(len(incoming),1)
        self.assertEqual(incoming[0].source_node,source.id)
        self.w.controller.undo.undo();QTest.qWait(15)
        self.assertIn(original.id,p.connections)

    def test_delete_key_and_undo(self):
        key=next(k for k,n in self.w.controller.project.nodes.items() if n.kind=='delay')
        self.w.scene.select_node(key);self.w.view.setFocus();QTest.qWait(10)
        QTest.keyClick(self.w.view,Qt.Key.Key_Delete);QTest.qWait(20)
        self.assertNotIn(key,self.w.controller.project.nodes)
        self.w.controller.undo.undo();QTest.qWait(15)
        self.assertIn(key,self.w.scene.nodes)

    def test_undo_does_not_recommit_retired_focused_editor(self):
        key=next(k for k,n in self.w.controller.project.nodes.items() if n.kind=='gain')
        self.w.scene.select_node(key);QTest.qWait(15)
        spin=self.w.inspector.findChild(QDoubleSpinBox,'gain')
        spin.setFocus();spin.setValue(-6);spin.editingFinished.emit();QTest.qWait(15)
        spin=self.w.inspector.findChild(QDoubleSpinBox,'gain');spin.setFocus()
        self.w.controller.undo.undo();QTest.qWait(30)
        self.assertEqual(self.w.controller.project.nodes[key].properties['gain'],0)
        self.assertTrue(self.w.controller.undo.isClean())
