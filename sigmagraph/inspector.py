# SPDX-License-Identifier: GPL-3.0-or-later
"""Block property editors and response previews for recognized filter settings."""
import math
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QFormLayout, QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox, QTabWidget,
    QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView, QFrame)
from .canvas import COLORS, font


def response(node, freq):
    from .dsp import transfer
    try:
        return 20*math.log10(max(abs(transfer(node,freq)),1e-10))
    except (ValueError,OverflowError,ZeroDivisionError):
        return None


class ResponsePlot(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller=controller
        self.node_id=None
        self.setMinimumHeight(150)
        self.setMaximumHeight(170)

    def paintEvent(self, event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=QRectF(0,0,self.width(),self.height())
        painter.fillRect(rect,QColor('#131d2c'))
        graph=rect.adjusted(32,13,-12,-25)
        painter.setFont(font(7))
        for db in [-24,-12,0,12,24]:
            y=graph.center().y()-db/48*graph.height()
            painter.setPen(QPen(QColor('#354255' if db==0 else '#253247'),1))
            painter.drawLine(QPointF(graph.left(),y),QPointF(graph.right(),y))
            painter.setPen(QColor('#8294ae'))
            painter.drawText(QRectF(0,y-7,27,14),Qt.AlignmentFlag.AlignRight,str(db))
        for f,label in [(20,'20'),(100,'100'),(1000,'1k'),(10000,'10k')]:
            x=graph.left()+math.log10(f/20)/3*graph.width()
            painter.setPen(QPen(QColor('#253247'),1))
            painter.drawLine(QPointF(x,graph.top()),QPointF(x,graph.bottom()))
            painter.setPen(QColor('#8294ae'))
            painter.drawText(QRectF(x-14,graph.bottom()+5,30,16),Qt.AlignmentFlag.AlignCenter,label)
        node=self.controller.project.nodes.get(self.node_id)
        if not node: return
        path=QPainterPath()
        valid=False
        try:
            for i in range(181):
                freq=min(20*1000**(i/180),node.fs*.499)
                db=response(node,freq)
                if db is None: break
                db=max(-24,min(24,db))
                point=QPointF(graph.left()+i/180*graph.width(),graph.center().y()-db/48*graph.height())
                if not valid: path.moveTo(point)
                else: path.lineTo(point)
                valid=True
        except (ValueError,OverflowError,ZeroDivisionError):
            valid=False
        if valid:
            painter.setPen(QPen(QColor(COLORS.get(node.kind,'#79b8ff')),2))
            painter.setClipRect(graph)
            painter.drawPath(path)
        else:
            painter.setPen(QColor('#8294ae'))
            painter.drawText(graph,Qt.AlignmentFlag.AlignCenter,'No response preview for this setting')


def section(text):
    label=QLabel(text.upper())
    label.setObjectName('sectionLabel')
    return label


class Inspector(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.setObjectName('inspector')
        self.controller=controller
        self.node_id=None
        self.refresh_pending=False
        self.outer=QVBoxLayout(self)
        self.outer.setContentsMargins(18,20,18,14)
        self.outer.setSpacing(12)
        self.outer.addWidget(section('Inspector'))
        self.title=QLabel('Your signal, shaped here.')
        self.title.setObjectName('inspectorTitle')
        self.title.setWordWrap(True)
        self.outer.addWidget(self.title)
        self.subtitle=QLabel('Select a block to edit its settings.')
        self.subtitle.setWordWrap(True)
        self.subtitle.setObjectName('muted')
        self.outer.addWidget(self.subtitle)
        self.plot=ResponsePlot(controller)
        self.outer.addWidget(self.plot)
        self.tabs=QTabWidget()
        self.tabs.setDocumentMode(True)
        self.outer.addWidget(self.tabs,1)
        self.footer=QLabel('Save as .sgproj to keep your edits.\nDSP → Simulate shows the connected response.')
        self.footer.setObjectName('muted')
        self.footer.setWordWrap(True)
        self.outer.addWidget(self.footer)
        controller.changed.connect(self.on_changed)
        controller.opened.connect(lambda:self.set_node(None))
        self.rebuild()

    def on_changed(self, kind):
        self.plot.update()
        if kind!='position' and not self.refresh_pending:
            self.refresh_pending=True
            QTimer.singleShot(0,self.rebuild)

    def set_node(self,key):
        self.node_id=key
        self.rebuild()

    def change(self,scope,key,value):
        if self.node_id:
            try: self.controller.edit(self.node_id,scope,key,value)
            except ValueError as e: self.controller.message.emit(str(e))

    def spin(self,value,low,high,scope,key,decimals=2,suffix=''):
        w=QDoubleSpinBox()
        w.setRange(low,high)
        w.setDecimals(decimals)
        w.setValue(float(value))
        w.setSuffix(suffix)
        w.setKeyboardTracking(False)
        w.setObjectName(key)
        w.editingFinished.connect(lambda:self.change(scope,key,w.value()))
        return w

    def check(self,value,scope,key,text=''):
        w=QCheckBox(text)
        w.setChecked(bool(value))
        w.setObjectName(key)
        w.toggled.connect(lambda v:self.change(scope,key,v))
        return w

    def combo(self,value,items,scope,key):
        w=QComboBox()
        for label,data in items: w.addItem(label,data)
        index=w.findData(value)
        if index<0:
            w.addItem(str(value),value); index=w.count()-1
        w.setCurrentIndex(index)
        w.currentIndexChanged.connect(lambda i:self.change(scope,key,w.itemData(i)))
        w.setObjectName(key)
        return w

    def rebuild(self):
        self.refresh_pending=False
        previous_tab=self.tabs.currentIndex()
        while self.tabs.count():
            w=self.tabs.widget(0)
            # Retiring focused editors must not recommit stale values after undo.
            for child in w.findChildren(QWidget): child.blockSignals(True)
            w.blockSignals(True)
            self.tabs.removeTab(0); w.deleteLater()
        node=self.controller.project.nodes.get(self.node_id)
        self.plot.node_id=self.node_id
        self.plot.update()
        if not node:
            self.title.setText('Your signal, shaped here.')
            self.subtitle.setText('Select a block to edit its settings.')
            self.plot.hide()
            body=QWidget(); layout=QVBoxLayout(body)
            layout.setContentsMargins(0,20,0,0)
            for title,desc in [('BUILD A SIGNAL PATH','Drag blocks from the library into the canvas.'),
                               ('PATCH IT TOGETHER','Drag from an output port to an input port.'),
                               ('MOVE AROUND','Scroll to zoom. Hold Space and drag to pan.'),
                               ('MAKE IT YOURS','Select a cable or block and press Delete. Undo is always available.')]:
                layout.addWidget(section(title))
                l=QLabel(desc); l.setWordWrap(True); l.setObjectName('muted'); layout.addWidget(l)
                layout.addSpacing(12)
            layout.addStretch()
            self.tabs.addTab(body,'Getting started')
            return
        self.title.setText(node.label)
        self.subtitle.setText(f'{node.family}  ·  {node.fs/1000:g} kHz')
        self.plot.setVisible(node.kind in ('gain','peq','filter','first_order','delay'))
        body=QWidget(); layout=QVBoxLayout(body)
        layout.setContentsMargins(0,14,2,12); layout.setSpacing(12)
        form=QFormLayout(); form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        name=QLineEdit(node.label); name.setObjectName('nodeName')
        name.editingFinished.connect(lambda:self.change('node','label',name.text().strip()))
        form.addRow('Name',name)
        form.addRow('Active',self.check(node.enabled,'properties','enable','Process signal'))
        form.addRow('Sample rate',self.combo(node.fs,[(f'{v/1000:g} kHz',float(v)) for v in [44100,48000,88200,96000,192000]],'node','fs'))
        if node.catalog_id:
            from .registry import definition
            entry=definition(node.catalog_id)
            rep=entry['repeater'] if entry else None
            if rep and (rep['in_grow'] or rep['out_grow']):
                from PySide6.QtWidgets import QPushButton
                row=QWidget();buttons=QHBoxLayout(row);buttons.setContentsMargins(0,0,0,0)
                current=node.source_algorithm.get('rep',rep['min'])
                less=QPushButton('−');more=QPushButton('+')
                less.setEnabled(current>rep['min']);more.setEnabled(current<rep['max'])
                less.clicked.connect(lambda:self.controller.grow(node.id,-1));more.clicked.connect(lambda:self.controller.grow(node.id,1))
                buttons.addWidget(less);buttons.addWidget(QLabel(str(current)));buttons.addWidget(more)
                form.addRow('Grow algorithm',row)
        layout.addLayout(form)
        line=QFrame(); line.setFrameShape(QFrame.Shape.HLine); layout.addWidget(line)
        layout.addWidget(section(node.family))
        form=QFormLayout(); form.setSpacing(10)
        p=node.properties
        if node.kind=='gain':
            form.addRow('Gain',self.spin(p.get('gain',0),-80,24,'properties','gain',2,' dB'))
            form.addRow('Slew exponent',self.spin(p.get('step',12),0,23,'properties','step',0))
            hint=QLabel('RC smoothing · smaller exponents respond faster.')
            hint.setObjectName('muted'); hint.setWordWrap(True); layout.addWidget(hint)
        elif node.kind=='delay':
            form.addRow('Samples',self.spin(p.get('Value0',1),0,max(2048,p.get('CtrlMax0',2048)),'properties','Value0',0))
            delay=p.get('Value0',1)/node.fs*1000
            form.addRow('Time',QLabel(f'{delay:.4f} ms'))
            form.addRow('Buffer limit',self.spin(p.get('CtrlMax0',2048),1,1000000,'properties','CtrlMax0',0))
        elif node.kind=='output':
            form.addRow('Channel',self.combo(p.get('selectedchannel','DAC0'),[(f'DAC {i}',f'DAC{i}') for i in range(4)]+[(f'Digital {i}',f'DIG{i}') for i in range(8)],'properties','selectedchannel'))
        elif node.kind=='input':
            form.addRow('Channels',QLabel(str(len(node.outputs))))
            l=QLabel('The importer shows the active input ports stored in the project.')
            l.setObjectName('muted');l.setWordWrap(True);layout.addWidget(l)
        elif node.kind=='filter':
            form.addRow('Frequency',self.spin(p.get('Frequency',40),1,node.fs*.499,'properties','Frequency',2,' Hz'))
            form.addRow('Order',self.combo(float(p.get('Order',2)),[(str(i),float(i)) for i in [1,2,3,4,6,8]],'properties','Order'))
            form.addRow('Enabled',self.check(p.get('FilterEnabled',True),'properties','FilterEnabled'))
        elif node.kind=='first_order':
            form.addRow('Mode',self.combo(p.get('firstorder_type0',0),[('Low-pass',0),('High-pass',1),('All-pass',2)],'properties','firstorder_type0'))
            form.addRow('Frequency',self.spin(p.get('firstorder_freq0',2000),1,node.fs*.499,'properties','firstorder_freq0',2,' Hz'))
            form.addRow('Gain',self.spin(p.get('firstorder_gain0',0),-60,24,'properties','firstorder_gain0',2,' dB'))
        elif node.kind=='crossover':
            for label,key in [('Low cutoff','FrequencyLow'),('High cutoff','FrequencyHigh')]:
                k='S0.R0.'+key
                form.addRow(label,self.spin(node.ui.get(k,1000),1,node.fs*.499,'ui',k,2,' Hz'))
            k='S0.R0.Gain3';form.addRow('High-band gain',self.spin(node.ui.get(k,0),-60,24,'ui',k,2,' dB'))
            for label,key in [('Invert low','InvertLow'),('Invert high','InvertHigh')]:
                k='S0.R0.'+key;form.addRow(label,self.check(node.ui.get(k,False),'ui',k))
        else:
            # Catalog presets expose their own scalar controls. Unknown settings
            # remain available, with original names, in the second tab.
            labels={'frequency':('Frequency',.01,node.fs*.499,2,' Hz'),
                    'freq':('Frequency',.01,node.fs*.499,2,' Hz'),
                    'amplitude':('Amplitude',0,15.99,3,''),
                    'value':('Value',-16,15.99,4,''),
                    'textvalue':('Value',-16,15.99,4,''),
                    'step':('Slew exponent',0,23,0,''),
                    'linear_gain':('Linear gain',-16,15.99,3,''),
                    'threshold':('Threshold',0,15.99,3,''),
                    'threshold_db':('Threshold',-100,24,2,' dB'),
                    'ratio':('Ratio',1,100,2,':1'),
                    'attack_ms':('Attack',.01,10000,2,' ms'),
                    'release_ms':('Release',.01,10000,2,' ms'),
                    'initial_value':('Initial value',0,1000000,0,''),
                    'modulo':('Modulo',1,1000000,0,''),
                    'table_points':('Table points',2,1024,0,'')}
            for key,(label,low,high,dec,suffix) in labels.items():
                if key in p:form.addRow(label,self.spin(p[key],low,high,'properties',key,dec,suffix))
            if 'source_on'in p:form.addRow('Source',self.check(p['source_on'],'properties','source_on','On'))
            if 'ison'in p:form.addRow('Source',self.check(p['ison'],'properties','ison','On'))
            if node.kind in ('gpio','auxadc'):
                prefix='GPIO_' if node.kind=='gpio' else 'AUX_ADC_'
                form.addRow('Channel',self.combo(p.get('selectedchannel',prefix+'0'),[(prefix+str(i),prefix+str(i)) for i in range(12 if node.kind=='gpio' else 4)],'properties','selectedchannel'))
            if node.kind=='external_gain':
                l=QLabel('Connect the external volume input to an Aux ADC, lookup table, or control source.')
                l.setWordWrap(True);l.setObjectName('muted');layout.addWidget(l)
            if node.catalog_id:
                l=QLabel(node.catalog_id.split('.')[-1]);l.setObjectName('muted');l.setWordWrap(True);layout.addWidget(l)
        layout.addLayout(form)
        if node.kind=='peq':
            count_form=QFormLayout()
            count_form.addRow('Bands',self.combo(len(node.eq_bands())-1,[(str(i),i-1) for i in range(1,16)],'ui','S0.R0.Index'))
            layout.addLayout(count_form)
            layout.addWidget(QLabel(f'{len(node.eq_bands())} bands · frequency / gain / Q'))
            table=QTableWidget(len(node.eq_bands()),5)
            table.setObjectName('eqBands')
            table.setHorizontalHeaderLabels(['#','Hz','dB','Q','Off'])
            table.verticalHeader().hide()
            table.setMinimumHeight(min(400,45+len(node.eq_bands())*30))
            table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeMode.ResizeToContents)
            for row,i in enumerate(node.eq_bands()):
                item=QTableWidgetItem(str(i+1)); item.setFlags(Qt.ItemFlag.ItemIsEnabled);table.setItem(row,0,item)
                for col,key,low,high,dec in [(1,'Frequency1',1,node.fs*.499,1),(2,'Boost',-30,30,1),(3,'Q',.05,100,2)]:
                    k=f'S0.R0.{key}{i}'
                    table.setCellWidget(row,col,self.spin(node.ui.get(k,1),low,high,'ui',k,dec))
                k=f'S0.R0.Bypass{i}'
                table.setCellWidget(row,4,self.check(node.ui.get(k,False),'ui',k))
            layout.addWidget(table)
            hint=QLabel('Dormant slots and other filter modes are retained in Stored settings.')
            hint.setObjectName('muted');hint.setWordWrap(True);layout.addWidget(hint)
        layout.addStretch()
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);scroll.setWidget(body)
        self.tabs.addTab(scroll,'Controls')
        advanced=self.build_advanced(node)
        self.tabs.addTab(advanced,'Stored settings')
        self.tabs.setCurrentIndex(max(0,min(previous_tab,self.tabs.count()-1)))

    def build_advanced(self,node):
        body=QWidget();layout=QVBoxLayout(body);layout.setContentsMargins(0,12,0,0)
        hint=QLabel('Original scalar settings are retained. Double-click a value to edit it.')
        hint.setObjectName('muted');hint.setWordWrap(True);layout.addWidget(hint)
        search=QLineEdit();search.setPlaceholderText('Filter settings…');layout.addWidget(search)
        rows=[]
        for scope,values in [('properties',node.properties),('ui',node.ui)]:
            for k,v in sorted(values.items()):
                if isinstance(v,(bool,int,float,str)) and k not in ('nid','name'):
                    rows.append((scope,k,v))
        table=QTableWidget(len(rows),2);table.setHorizontalHeaderLabels(['Setting','Value']);table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents)
        for row,(scope,k,v) in enumerate(rows):
            label=QTableWidgetItem(k.removeprefix('S0.R0.'));label.setToolTip(k)
            label.setFlags(Qt.ItemFlag.ItemIsSelectable|Qt.ItemFlag.ItemIsEnabled)
            table.setItem(row,0,label);table.setItem(row,1,QTableWidgetItem(str(v)))
        def edited(item):
            if item.column()!=1:return
            scope,k,old=rows[item.row()]
            try:
                text=item.text()
                if isinstance(old,bool):
                    if text.lower() not in ('true','false','1','0'):raise ValueError('Use true or false.')
                    value=text.lower() in ('true','1')
                elif isinstance(old,int):value=int(text)
                elif isinstance(old,float):value=float(text)
                else:value=text
                self.change(scope,k,value)
            except ValueError as e:
                self.controller.message.emit(str(e))
                table.blockSignals(True);item.setText(str(old));table.blockSignals(False)
        table.itemChanged.connect(edited)
        search.textChanged.connect(lambda text:[table.setRowHidden(i,text.lower() not in rows[i][1].lower()) for i in range(len(rows))])
        layout.addWidget(table)
        return body
