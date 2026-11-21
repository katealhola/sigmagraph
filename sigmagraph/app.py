# SPDX-License-Identifier: GPL-3.0-or-later
"""SigmaGraph's native desktop shell."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QMimeData, QTimer, QSize
from PySide6.QtGui import (QAction, QKeySequence, QDrag, QIcon, QPixmap,
                          QPainter, QColor, QPen, QPainterPath, QFont)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QToolButton, QFrame, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTabWidget, QLineEdit, QListWidget,
    QListWidgetItem, QFileDialog, QMessageBox, QComboBox, QCheckBox)
from . import __version__
from .model import Project, TEMPLATES, demo_project
from .registry import catalog
from .controller import Controller
from .canvas import GraphScene, GraphView, NodeItem, COLORS
from .inspector import Inspector
from .persistence import load_project

STYLE = '''
QWidget { background:#182232; color:#dfe7f3; font-family:"Helvetica Neue","DejaVu Sans"; font-size:12px; }
QMainWindow { background:#131c2a; }
QMenuBar { background:#182232; } QMenu { border:1px solid #364257; padding:6px; }
QMenu::item { padding:7px 24px 7px 14px; border-radius:4px; } QMenu::item:selected { background:#2e4058; }
QMenu::item:disabled { color:#65758d; }
QToolTip { background:#28364b; color:#edf5ff; border:1px solid #526581; padding:6px; }
QLabel#brand { font-size:21px; font-weight:650; color:#f2f6fc; }
QLabel#projectName { font-size:15px; font-weight:600; }
QLabel#muted { color:#91a2bc; font-size:11px; }
QLabel#sectionLabel { color:#91a2bc; font-size:10px; font-weight:600; letter-spacing:1px; }
QLabel#inspectorTitle { font-size:20px; font-weight:600; color:#f2f5fc; }
QLabel#badge { color:#a8e8d7; background:#233d3e; border:1px solid #345454; border-radius:5px; padding:5px 10px; }
QPushButton { border:1px solid #3b4a60; border-radius:6px; padding:7px 13px; background:#233045; }
QPushButton:hover { background:#30415a; border-color:#59718e; }
QPushButton:pressed { background:#172231; }
QPushButton#primary { background:#7cddc2; color:#102b29; font-weight:650; border-color:#7cddc2; }
QPushButton#primary:hover { background:#9cebd5; }
QToolButton { background:transparent; border:1px solid transparent; padding:6px 9px; border-radius:5px; }
QToolButton:hover { background:#2a394f; border-color:#42546d; }
QToolButton:disabled { color:#596a83; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox { border:1px solid #35455b; border-radius:5px; padding:6px; background:#111d2c; min-height:17px; }
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color:#7cddc2; }
QComboBox::drop-down { border:0; width:20px; }
QComboBox QAbstractItemView { background:#223047; selection-background-color:#3c526f; }
QCheckBox { spacing:7px; } QCheckBox::indicator { width:14px; height:14px; border:1px solid #546781; background:#142032; border-radius:3px; }
QCheckBox::indicator:checked { background:#7cddc2; border-color:#7cddc2; }
QTreeWidget, QListWidget { border:0; background:transparent; outline:0; }
QTreeWidget::item { padding:7px 2px; border-radius:5px; } QTreeWidget::item:hover { background:#233249; }
QTreeWidget::item:selected, QListWidget::item:selected { background:#2e4556; color:#b4f1df; }
QListWidget::item { padding:9px; border-radius:5px; }
QTabWidget::pane { border:0; border-top:1px solid #2c3a50; }
QTabBar::tab { color:#8fa2be; padding:9px 10px; border-bottom:2px solid transparent; background:transparent; }
QTabBar::tab:selected { color:#d9f7ed; border-bottom:2px solid #7cddc2; }
QTableWidget { border:1px solid #2c3a50; background:#162232; gridline-color:#29394d; border-radius:5px; selection-background-color:#2c4660; }
QTableWidget QDoubleSpinBox { border:0; border-radius:0; padding:2px; min-height:20px; background:transparent; }
QTableWidget QCheckBox { background:transparent; padding-left:7px; }
QHeaderView::section { background:#202e43; color:#91a6c1; border:0; border-bottom:1px solid #354258; padding:7px 4px; font-size:10px; }
QScrollArea { border:0; } QScrollBar:vertical { width:7px; background:#172232; } QScrollBar::handle:vertical { background:#3b4d66; border-radius:3px; min-height:25px; }
QScrollBar:horizontal { height:7px; background:#111a28; } QScrollBar::handle:horizontal { background:#3b4d66; border-radius:3px; min-width:25px; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
QSplitter::handle { background:#2c3a4f; }
QFrame[frameShape="4"], QFrame[frameShape="5"] { color:#2e3c51; }
QStatusBar { background:#152030; border-top:1px solid #2e3c51; color:#9dafc7; font-size:11px; }
QStatusBar::item { border:0; }
'''


def app_icon(size=128):
    pix=QPixmap(size,size);pix.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pix);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor('#172c35'))
    painter.drawRoundedRect(0,0,size,size,size*.23,size*.23)
    path=QPainterPath();path.moveTo(size*.18,size*.57)
    for x,y in [(.31,.57),(.39,.29),(.49,.76),(.61,.38),(.70,.57),(.83,.57)]:path.lineTo(size*x,size*y)
    painter.setPen(QPen(QColor('#83e4c7'),size*.055,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    painter.drawPath(path);painter.end()
    return QIcon(pix)


def block_icon(kind):
    pix=QPixmap(18,18);pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(COLORS.get(kind,'#a8b3c8')),1.5));p.setBrush(QColor('#243347'));p.drawRoundedRect(2,2,13,13,3,3)
    p.drawLine(5,9,12,9);p.end();return QIcon(pix)


class LibraryTree(QTreeWidget):
    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setRootIsDecorated(False)
        self.setIndentation(7)
        categories={}
        for kind,(label,_,_,_) in TEMPLATES.items():
            group='Quick start'
            if group not in categories:
                item=QTreeWidgetItem([group.upper()]);item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setForeground(0,QColor('#8195b2'));categories[group]=item;self.addTopLevelItem(item)
            item=QTreeWidgetItem([label]);item.setIcon(0,block_icon(kind));item.setData(0,Qt.ItemDataRole.UserRole,kind)
            item.setToolTip(0,'Double-click or drag onto the canvas to add.')
            categories[group].addChild(item)
        folders={}
        for key,entry in catalog().items():
            group=entry['category']
            if group not in categories:
                item=QTreeWidgetItem([group]);item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setForeground(0,QColor('#a8bfd9'));categories[group]=item;self.addTopLevelItem(item)
            parent=categories[group]
            path=[]
            for part in entry['path']:
                path.append(part);branch=(group,tuple(path))
                if branch not in folders:
                    folder=QTreeWidgetItem([part]);folder.setFlags(Qt.ItemFlag.ItemIsEnabled);parent.addChild(folder);folders[branch]=folder
                parent=folders[branch]
            item=QTreeWidgetItem([entry['label']]);item.setIcon(0,block_icon(entry['symbol']));item.setData(0,Qt.ItemDataRole.UserRole,key)
            item.setData(0,Qt.ItemDataRole.UserRole+1,' '.join([entry['label'],entry['type_name'],group,*entry['path']]))
            item.setToolTip(0,f"{entry['label']}\n{group} / {' / '.join(entry['path'])}\n{entry['type_name']}\nDouble-click or drag onto the canvas.")
            parent.addChild(item)
        self.setRootIsDecorated(True)
        for i in range(self.topLevelItemCount()):
            self.topLevelItem(i).setExpanded(self.topLevelItem(i).text(0)=='Basic DSP')

    def startDrag(self, actions):
        item=self.currentItem()
        if not item:return
        kind=item.data(0,Qt.ItemDataRole.UserRole)
        if not kind:return
        mime=QMimeData();mime.setData('application/x-sigmagraph-block',kind.encode())
        drag=QDrag(self);drag.setMimeData(mime);drag.setPixmap(block_icon(kind).pixmap(24,24));drag.exec(Qt.DropAction.CopyAction)

    def filter(self,text):
        def visit(item):
            if item.childCount():
                visible=any([visit(item.child(i)) for i in range(item.childCount())])
                item.setHidden(not visible)
                if text:item.setExpanded(visible)
                return visible
            haystack=item.data(0,Qt.ItemDataRole.UserRole+1) or item.text(0)
            show=text.lower() in haystack.lower();item.setHidden(not show);return show
        for i in range(self.topLevelItemCount()):visit(self.topLevelItem(i))


class MainWindow(QMainWindow):
    def __init__(self,project_path=None):
        super().__init__()
        self.setObjectName('SigmaGraphWindow')
        self.setWindowIcon(app_icon())
        self.resize(1540,940)
        self.setMinimumSize(1100,700)
        self.controller=Controller()
        self.scene=GraphScene(self.controller)
        self.view=GraphView(self.scene)
        self.inspector=Inspector(self.controller)
        self.last_directory=str(Path.home()/'dsp') if (Path.home()/'dsp').exists() else str(Path.home())
        self._fit_next=False
        self._closing=False
        self.setup_actions()
        self.setup_ui()
        self.scene.selectionChanged.connect(self.selection_changed)
        self.scene.inspect_requested.connect(self.inspector.set_node)
        self.scene.ready.connect(self.scene_ready)
        self.view.block_dropped.connect(self.add_block)
        self.controller.changed.connect(self.document_changed)
        self.controller.message.connect(lambda text:self.statusBar().showMessage(text,6500))
        self.controller.undo.cleanChanged.connect(lambda _:self.update_title())
        self.library.itemDoubleClicked.connect(self.library_add)
        self.project_list.itemClicked.connect(self.pick_project_node)
        self.controller.load(demo_project())
        self._fit_next=True
        if project_path:
            QTimer.singleShot(0,lambda:self.open_path(project_path))

    def setup_actions(self):
        self.open_action=QAction('Open project…',self);self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_dialog)
        self.new_action=QAction('New signal flow',self);self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.new_document)
        self.undo_action=self.controller.undo.createUndoAction(self,'Undo');self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_action=self.controller.undo.createRedoAction(self,'Redo');self.redo_action.setShortcuts(QKeySequence.keyBindings(QKeySequence.StandardKey.Redo))
        self.duplicate_action=QAction('Duplicate blocks',self);self.duplicate_action.setShortcut(QKeySequence('Ctrl+D'))
        self.duplicate_action.triggered.connect(self.duplicate_selection)
        self.fit_action=QAction('Fit graph',self);self.fit_action.setShortcut(QKeySequence('Ctrl+0'));self.fit_action.triggered.connect(self.view.fit_graph)
        self.arrange_action=QAction('Arrange graph',self);self.arrange_action.triggered.connect(self.arrange)
        self.save_action=QAction('Save project',self);self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_document)
        self.save_as_action=QAction('Save project as…',self);self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_as_action.triggered.connect(lambda:self.save_document(True))
        self.compile_action=QAction('Compile for ADAU1701…',self);self.compile_action.setShortcut(QKeySequence('Ctrl+B'))
        self.compile_action.triggered.connect(self.compile_document)
        self.simulate_action=QAction('Simulate frequency response…',self);self.simulate_action.setShortcut(QKeySequence('Ctrl+R'))
        self.simulate_action.triggered.connect(self.simulate_document)
        file=self.menuBar().addMenu('File');file.addAction(self.new_action);file.addAction(self.open_action)
        file.addSeparator()
        file.addActions([self.save_action,self.save_as_action,self.compile_action])
        file.addSeparator();quit_action=file.addAction('Quit');quit_action.setShortcut(QKeySequence.StandardKey.Quit);quit_action.triggered.connect(self.close)
        edit=self.menuBar().addMenu('Edit');edit.addActions([self.undo_action,self.redo_action]);edit.addSeparator();edit.addAction(self.duplicate_action)
        edit.addAction('Delete selection',self.scene.delete_selection)
        view=self.menuBar().addMenu('View');view.addActions([self.fit_action,self.arrange_action])
        original=view.addAction('Restore imported positions');original.triggered.connect(self.restore_imported_positions)
        tools=self.menuBar().addMenu('DSP');tools.addActions([self.compile_action,self.simulate_action])
        help_menu=self.menuBar().addMenu('Help');help_menu.addAction('About SigmaGraph',self.about)
        def documentation():
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl('https://wiki.analog.com/resources/tools-software/sigmastudio/toolbox'))
        help_menu.addAction('SigmaStudio toolbox reference',documentation)

    def tool_button(self,text,action,tooltip=None):
        w=QToolButton();w.setDefaultAction(action);w.setText(text)
        if tooltip:w.setToolTip(tooltip)
        return w

    def setup_ui(self):
        central=QWidget();main=QVBoxLayout(central);main.setContentsMargins(0,0,0,0);main.setSpacing(0)
        header=QWidget();hl=QHBoxLayout(header);hl.setContentsMargins(22,16,22,16);hl.setSpacing(12)
        icon=QLabel();icon.setPixmap(app_icon().pixmap(35,35));hl.addWidget(icon)
        brand=QLabel('SigmaGraph');brand.setObjectName('brand');hl.addWidget(brand)
        hl.addSpacing(26)
        project_info=QVBoxLayout();project_info.setSpacing(3)
        self.project_name=QLabel();self.project_name.setObjectName('projectName');project_info.addWidget(self.project_name)
        self.project_detail=QLabel();self.project_detail.setObjectName('muted');project_info.addWidget(self.project_detail)
        hl.addLayout(project_info);hl.addStretch()
        self.target=QLabel('ADAU1701');self.target.setObjectName('badge');hl.addWidget(self.target)
        opened=QPushButton('Open project…');opened.setObjectName('primary');opened.clicked.connect(self.open_dialog);hl.addWidget(opened)
        main.addWidget(header)
        toolbar=QWidget();tl=QHBoxLayout(toolbar);tl.setContentsMargins(18,4,18,6);tl.setSpacing(4)
        tl.addWidget(self.tool_button('↶',self.undo_action,'Undo · ⌘Z / Ctrl+Z'))
        tl.addWidget(self.tool_button('↷',self.redo_action,'Redo · ⌘⇧Z / Ctrl+Shift+Z'))
        tl.addSpacing(14)
        tl.addWidget(self.tool_button('Arrange',self.arrange_action,'Arrange blocks from input to output'))
        tl.addWidget(self.tool_button('Fit graph',self.fit_action,'Fit all blocks · F'))
        tl.addWidget(self.tool_button('Save',self.save_action))
        tl.addWidget(self.tool_button('Compile DSP',self.compile_action))
        tl.addWidget(self.tool_button('Simulate',self.simulate_action))
        self.snap=QCheckBox('Snap');self.snap.setChecked(True);self.snap.toggled.connect(lambda v:setattr(self.scene,'snap',v));tl.addWidget(self.snap)
        tl.addStretch()
        self.session=QLabel('EDITOR');self.session.setObjectName('sectionLabel');tl.addWidget(self.session)
        tl.addSpacing(14)
        minus=QToolButton();minus.setText('−');minus.clicked.connect(lambda:self.view.set_zoom(self.view.transform().m11()/1.2));tl.addWidget(minus)
        self.zoom_label=QLabel('100%');self.zoom_label.setMinimumWidth(42);self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter);tl.addWidget(self.zoom_label)
        plus=QToolButton();plus.setText('+');plus.clicked.connect(lambda:self.view.set_zoom(self.view.transform().m11()*1.2));tl.addWidget(plus)
        self.view.zoom_changed.connect(lambda n:self.zoom_label.setText(f'{n}%'))
        main.addWidget(toolbar)
        splitter=QSplitter(Qt.Orientation.Horizontal);splitter.setHandleWidth(1)
        library_widget=QWidget();ll=QVBoxLayout(library_widget);ll.setContentsMargins(15,18,12,12);ll.setSpacing(14)
        heading=QLabel(f'BLOCK LIBRARY · {len(catalog())+len(TEMPLATES)}');heading.setObjectName('sectionLabel');ll.addWidget(heading)
        compatibility=QLabel('Sigma100 / ADAU1701');compatibility.setObjectName('muted');ll.addWidget(compatibility)
        search=QLineEdit();search.setPlaceholderText('Find a block…');search.setObjectName('blockSearch');ll.addWidget(search)
        tabs=QTabWidget();tabs.setDocumentMode(True)
        self.library=LibraryTree();tabs.addTab(self.library,'Library')
        self.project_list=QListWidget();tabs.addTab(self.project_list,'Project');ll.addWidget(tabs,1)
        tip=QLabel('Double-click or drag a block\nto add it to your signal flow.');tip.setObjectName('muted');tip.setWordWrap(True);ll.addWidget(tip)
        search.textChanged.connect(self.library.filter)
        search.textChanged.connect(lambda t:[self.project_list.item(i).setHidden(t.lower() not in self.project_list.item(i).text().lower()) for i in range(self.project_list.count())])
        library_widget.setMinimumWidth(180);library_widget.setMaximumWidth(290);splitter.addWidget(library_widget)
        graph_wrapper=QWidget();gl=QVBoxLayout(graph_wrapper);gl.setContentsMargins(0,0,0,0);gl.setSpacing(0)
        graph_header=QWidget();gh=QHBoxLayout(graph_header);gh.setContentsMargins(19,13,18,13)
        title=QLabel('SIGNAL FLOW');title.setObjectName('sectionLabel');gh.addWidget(title);gh.addStretch()
        hint=QLabel('Drag ports to connect');hint.setObjectName('muted');gh.addWidget(hint)
        gl.addWidget(graph_header);gl.addWidget(self.view,1)
        canvas_footer=QWidget();cf=QHBoxLayout(canvas_footer);cf.setContentsMargins(18,10,18,10)
        self.stats=QLabel();self.stats.setObjectName('muted');cf.addWidget(self.stats);cf.addStretch()
        hint=QLabel('Space + drag to pan   ·   Scroll to zoom   ·   F to fit');hint.setObjectName('muted');cf.addWidget(hint)
        gl.addWidget(canvas_footer);splitter.addWidget(graph_wrapper)
        self.inspector.setMinimumWidth(300);self.inspector.setMaximumWidth(470);splitter.addWidget(self.inspector)
        splitter.setSizes([210,990,338]);splitter.setStretchFactor(1,1);main.addWidget(splitter,1)
        self.setCentralWidget(central)
        self.health=QPushButton('Connections ready');self.health.setFlat(True);self.health.clicked.connect(self.show_issues)
        self.statusBar().addPermanentWidget(self.health)
        self.statusBar().showMessage('Open a SigmaStudio project or start with the example signal flow.')

    def update_title(self):
        dirty=not self.controller.undo.isClean()
        name=self.controller.project.name
        self.setWindowTitle(f'{name}{" •" if dirty else ""} — SigmaGraph {__version__}')
        self.project_name.setText(name+('  •' if dirty else ''))
        self.session.setText(f'v{__version__} · MODIFIED' if dirty else f'v{__version__} · '+('SAVED' if self.controller.save_path else 'UNSAVED'))

    def document_changed(self,kind):
        p=self.controller.project
        self.update_title()
        self.project_detail.setText(f'{p.target}  /  IC 1  /  {p.sample_rate/1000:g} kHz')
        self.target.setText(p.target)
        self.stats.setText(f'{len(p.nodes)} blocks   ·   {len(p.connections)} connections')
        issues=p.issues();self.health.setText(f'{len(issues)} connection notes' if issues else '●  Connections ready')
        self.health.setStyleSheet('color:#edb46d;' if issues else 'color:#83d9bc;')
        if kind!='position':
            self.project_list.clear()
            for key,n in sorted(p.nodes.items(),key=lambda kv:(kv[1].x,kv[1].y)):
                item=QListWidgetItem(block_icon(n.kind),n.label);item.setData(Qt.ItemDataRole.UserRole,key);self.project_list.addItem(item)

    def scene_ready(self):
        if self._fit_next:
            self._fit_next=False
            QTimer.singleShot(20,self.view.fit_graph)
        self.selection_changed()

    def selection_changed(self):
        if self._closing or self.scene.syncing:return
        ids=self.scene.selected_node_ids()
        key=ids[0] if len(ids)==1 else None
        if self.inspector.node_id!=key:
            self.inspector.set_node(key)

    def pick_project_node(self,item):
        key=item.data(Qt.ItemDataRole.UserRole)
        self.scene.select_node(key)
        if key in self.scene.nodes:self.view.ensureVisible(self.scene.nodes[key],80,80)

    def library_add(self,item,column):
        kind=item.data(0,Qt.ItemDataRole.UserRole)
        if kind:
            point=self.view.mapToScene(self.view.viewport().rect().center())
            self.add_block(kind,point.x()-95,point.y()-50)

    def add_block(self,kind,x,y):
        if kind not in TEMPLATES and kind not in catalog():return
        key=self.controller.add(kind,x,y)
        QTimer.singleShot(0,lambda:self.scene.select_node(key))
        self.statusBar().showMessage('Block added. Drag its ports to connect it.',5000)

    def duplicate_selection(self):
        ids=self.controller.duplicate(self.scene.selected_node_ids())
        def select():
            self.scene.clearSelection()
            for key in ids:
                if key in self.scene.nodes:self.scene.nodes[key].setSelected(True)
        QTimer.singleShot(0,select)

    def arrange(self):
        self.controller.auto_layout();QTimer.singleShot(30,self.view.fit_graph)

    def restore_imported_positions(self):
        positions={key:(n.source_cell['x'],n.source_cell['y']) for key,n in self.controller.project.nodes.items() if 'x' in n.source_cell}
        if positions:
            self.controller.move(positions);QTimer.singleShot(30,self.view.fit_graph)
            self.statusBar().showMessage('Restored the original schematic positions. Arrange can spread out overlapping blocks.',6000)

    def confirm_discard(self):
        focused=QApplication.focusWidget()
        if focused is not None and self.inspector.isAncestorOf(focused):
            focused.clearFocus()
        if self.controller.undo.isClean():return True
        result=QMessageBox.warning(self,'Save project changes?',
            'Save your current changes before continuing?',
            QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
        if result==QMessageBox.StandardButton.Save:return self.save_document()
        return result==QMessageBox.StandardButton.Discard

    def save_document(self,save_as=False):
        focused=QApplication.focusWidget()
        if focused is not None:focused.clearFocus()
        path=self.controller.save_path
        if save_as or not path:
            default=str(Path(self.last_directory)/(self.controller.project.name+'.sgproj'))
            path,_=QFileDialog.getSaveFileName(self,'Save SigmaGraph project',path or default,'SigmaGraph project (*.sgproj)')
            if not path:return False
            if not Path(path).suffix:path+='.sgproj'
        try:self.controller.save(path)
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'Project could not be saved',str(exc));return False
        self.last_directory=str(Path(path).parent);self.update_title()
        self.statusBar().showMessage(f'Saved {Path(path).name}.',6000)
        return True

    def compile_document(self):
        from .compiler import compile_project
        from datetime import datetime
        import re
        focused=QApplication.focusWidget()
        if focused is not None:focused.clearFocus()
        try:
            build=compile_project(self.controller.project)
        except ValueError as exc:
            QMessageBox.warning(self,'DSP compilation failed',str(exc));return False
        folder=QFileDialog.getExistingDirectory(self,'Choose parent folder for DSP build',self.last_directory)
        if not folder:return False
        stem=re.sub(r'[^\w.-]+','_',self.controller.project.name).strip('._') or 'project'
        path=Path(folder)/(stem+'-adau1701-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
        try:build.export(path)
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'DSP build could not be exported',str(exc));return False
        self.last_directory=folder
        result=QMessageBox(self);result.setWindowTitle('ADAU1701 build exported')
        result.setText(f'{build.instructions} / 1024 instructions\n{len(build.parameter_map)} / 1024 parameters\n{build.data_words} / 2048 data words')
        result.setInformativeText(f'Program and parameter binaries, C header, assembly and address maps:\n{path}\n\nExperimental compiler; hardware validation is pending. Configure the board separately. See manifest.json for integration details.')
        result.setStandardButtons(QMessageBox.StandardButton.Ok)
        show=result.addButton('Show build folder',QMessageBox.ButtonRole.ActionRole);result.exec()
        if result.clickedButton()==show:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        return True

    def simulate_document(self):
        from .simulator import SimulationDialog
        focused=QApplication.focusWidget()
        if focused is not None:focused.clearFocus()
        ids=self.scene.selected_node_ids()
        dialog=SimulationDialog(self.controller,self,ids[0] if len(ids)==1 else None)
        dialog.show()
        return dialog

    def new_document(self):
        if self.confirm_discard():
            self.controller.load(Project());self._fit_next=True
            self.statusBar().showMessage('New signal flow. Add a block from the library.',5000)

    def open_dialog(self):
        path,_=QFileDialog.getOpenFileName(self,'Open project',self.last_directory,'DSP projects (*.sgproj *.dspproj);;SigmaGraph (*.sgproj);;SigmaStudio (*.dspproj);;All files (*)')
        if path:self.open_path(path)

    def open_path(self,path):
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            project=load_project(path)
        except (OSError,ValueError,KeyError) as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self,'Project could not be opened',str(exc));return False
        finally:
            if QApplication.overrideCursor():QApplication.restoreOverrideCursor()
        if not self.confirm_discard():return False
        self._fit_next=True
        self.scene.clearSelection()
        self.controller.load(project,str(Path(path).resolve()) if Path(path).suffix.lower()=='.sgproj' else None)
        self.last_directory=str(Path(path).parent)
        self.statusBar().showMessage(f'Loaded {Path(path).name}.',8000)
        return True

    def show_issues(self):
        issues=self.controller.project.issues()
        QMessageBox.information(self,'Connection check','\n'.join(issues) if issues else 'Every input has one connected source. Use Compile DSP to check algorithm support and memory limits.')

    def about(self):
        QMessageBox.about(self,'About SigmaGraph',f'SigmaGraph {__version__}\n\nNative SigmaDSP editor for macOS and Linux.\n\nImport SigmaStudio projects, save native .sgproj files, compile supported graphs for ADAU1701, and analyze frequency response.\n\nGPLv3 or later. Independent experimental compiler; limited hardware execution verified at DC. The toolbox contains additional blocks whose compiler models are still being recovered.')

    def closeEvent(self,event):
        if self.confirm_discard():
            self._closing=True
            self.scene.selectionChanged.disconnect(self.selection_changed)
            event.accept()
        else:event.ignore()


class SigmaApplication(QApplication):
    def event(self,event):
        from PySide6.QtCore import QEvent
        if event.type()==QEvent.Type.FileOpen and hasattr(self,'main_window'):
            self.main_window.open_path(event.file())
            return True
        return super().event(event)


def create_application(argv=None):
    app=QApplication.instance() or SigmaApplication(argv or sys.argv)
    app.setApplicationName('SigmaGraph');app.setOrganizationName('SigmaGraph')
    app.setApplicationVersion(__version__);app.setWindowIcon(app_icon())
    app.setStyle('Fusion');app.setStyleSheet(STYLE)
    return app


def main():
    parser=argparse.ArgumentParser(description='SigmaGraph desktop signal-flow editor')
    parser.add_argument('--version',action='version',version=__version__)
    parser.add_argument('--smoke-test',action='store_true',help='Render the demo graph and exit; used to validate packaged applications')
    parser.add_argument('project',nargs='?',help='SigmaStudio .dspproj or SigmaGraph .sgproj to open')
    args=parser.parse_args()
    app=create_application()
    window=MainWindow(args.project);window.show()
    app.main_window=window
    if args.smoke_test:
        from PySide6.QtCore import QTimer
        def check_window():
            valid=bool(window.scene.nodes) and not window.grab().isNull()
            window.controller.undo.setClean()
            window.close()
            app.exit(0 if valid else 1)
        QTimer.singleShot(100,check_window)
    return app.exec()


if __name__=='__main__':
    raise SystemExit(main())
