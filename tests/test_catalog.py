# SPDX-License-Identifier: GPL-3.0-or-later
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from sigmagraph.registry import catalog,definition
from sigmagraph.model import make_node,from_dspproj
from sigmagraph.controller import Controller
from sigmagraph.app import create_application,MainWindow

APP=create_application(['catalog-tests'])
EXAMPLES=Path(os.environ.get('SIGMAGRAPH_SIGMASTUDIO_EXAMPLES',Path(__file__).parent/'private-examples'))


class CatalogTests(unittest.TestCase):
    def test_all_processor_filtered_definitions_create_nodes(self):
        self.assertEqual(len(catalog()),288)
        self.assertGreaterEqual(len({e['category'] for e in catalog().values()}),15)
        for key,entry in catalog().items():
            with self.subTest(key=key):
                n=make_node(key)
                self.assertEqual(n.catalog_id,key)
                self.assertTrue(n.symbol)
                self.assertEqual(n.source_algorithm['$type'],key)

    def test_source_has_no_placeholder_input(self):
        n=make_node(definition('sin_lookupAlg1940')['id'])
        self.assertEqual(len(n.inputs),0)
        self.assertEqual(len(n.outputs),1)
        self.assertEqual(n.symbol,'sine')

    def test_adder_growth_and_undo(self):
        c=Controller();key=c.add(definition('AdderAlg')['id'],0,0)
        n=c.project.nodes[key]
        self.assertEqual((len(n.inputs),len(n.outputs)),(2,1))
        pins=[p.id for p in n.ports]
        c.grow(key,1);n=c.project.nodes[key]
        self.assertEqual((len(n.inputs),len(n.outputs)),(3,1))
        self.assertEqual(n.source_algorithm['rep'],3)
        c.undo.undo();self.assertEqual([p.id for p in c.project.nodes[key].ports],pins)

    def test_library_search_and_add_type_not_in_project(self):
        w=MainWindow();w.show();QTest.qWait(50)
        try:
            self.assertFalse(any(n.symbol=='sine' for n in w.controller.project.nodes.values()))
            w.library.filter('Tone Synthesis')
            entry=definition('sin_lookupAlg1940')
            matches=w.library.findItems(entry['label'],Qt.MatchFlag.MatchExactly|Qt.MatchFlag.MatchRecursive)
            item=next(i for i in matches if i.data(0,Qt.ItemDataRole.UserRole)==entry['id'])
            w.library.scrollToItem(item);QTest.qWait(10)
            count=len(w.controller.project.nodes)
            QTest.mouseClick(w.library.viewport(),Qt.MouseButton.LeftButton,pos=w.library.visualItemRect(item).center())
            QTest.mouseDClick(w.library.viewport(),Qt.MouseButton.LeftButton,pos=w.library.visualItemRect(item).center())
            QTest.qWait(25)
            self.assertEqual(len(w.controller.project.nodes),count+1)
            self.assertTrue(any(n.symbol=='sine' for n in w.controller.project.nodes.values()))
        finally:w.controller.undo.setClean();w.close()

    @unittest.skipUnless(EXAMPLES.exists(),'Installed example projects unavailable')
    def test_all_local_examples_load_and_have_drawable_function_nodes(self):
        paths=list(EXAMPLES.rglob('*.dspproj'))
        self.assertEqual(len(paths),19)
        w=MainWindow();w.show();QTest.qWait(30)
        try:
            for path in paths:
                with self.subTest(project=path.name):
                    p=from_dspproj(path);w.controller.load(p);QTest.qWait(10)
                    self.assertEqual(len(w.scene.nodes),len(p.nodes))
                    w.view.fit_graph()
                    self.assertFalse(w.grab().isNull())
            p=from_dspproj(next(EXAMPLES.rglob('Volume_AuxADC_170x.dspproj')))
            self.assertTrue(any(n.kind=='external_gain' and n.symbol=='external_gain' for n in p.nodes.values()))
        finally:w.controller.undo.setClean();w.close()
