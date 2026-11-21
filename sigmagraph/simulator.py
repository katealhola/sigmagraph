# SPDX-License-Identifier: GPL-3.0-or-later
"""Stimulus/probe frequency response window with live edits and CSV export."""
from __future__ import annotations
import csv
import math
from pathlib import Path
from PySide6.QtCore import Qt,QRectF,QPointF,QTimer
from PySide6.QtGui import QPainter,QColor,QPen,QPainterPath
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QLabel,
    QComboBox,QPushButton,QCheckBox,QFileDialog,QMessageBox,QDoubleSpinBox)
from .dsp import simulate,DSPError,delay_samples

def frequency_grid(project,lo,hi,fs):
    # Keep pure-delay phase increments below 90 degrees before unwrapping.
    delay=sum(delay_samples(n) for n in project.nodes.values() if n.kind=='delay' and n.enabled)
    step=fs/(4*max(delay,1));result=[lo]
    for i in range(1,601):
        f=lo*(hi/lo)**(i/600);last=result[-1];count=max(1,math.ceil((f-last)/step))
        result.extend(last+(f-last)*j/count for j in range(1,count+1))
        if len(result)>20001:raise DSPError('The total delay requires more than 20,000 phase samples. Reduce the range or delay.')
    return result

def unwrap(values):
    result=[]
    for value in values:
        angle=math.degrees(math.atan2(value.imag,value.real))
        if result:
            while angle-result[-1]>180:angle-=360
            while angle-result[-1]<-180:angle+=360
        result.append(angle)
    return result

class TransferPlot(QWidget):
    def __init__(self):
        super().__init__();self.setMinimumSize(640,400)
        self.frequencies=[];self.values=[];self.phase=[];self.error='Choose a stimulus and a probe.'
        self.setMouseTracking(True);self.cursor=None

    def mouseMoveEvent(self,event):
        self.cursor=event.position();self.update()
    def leaveEvent(self,event):self.cursor=None;self.update()

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(),QColor('#101b2b'))
        upper=QRectF(62,30,self.width()-85,(self.height()-125)*.62)
        lower=QRectF(62,upper.bottom()+45,self.width()-85,(self.height()-125)*.38)
        if not self.values:
            painter.setPen(QColor('#b0c1d8'));painter.drawText(QRectF(self.rect()).adjusted(25,20,-25,-20),Qt.AlignmentFlag.AlignCenter|Qt.TextFlag.TextWordWrap,self.error);return
        db=[20*math.log10(max(abs(v),1e-12)) for v in self.values]
        low=min(-24,math.floor(min(db)/12)*12);low=max(low,-144)
        high=max(12,math.ceil(max(db)/12)*12)
        plow=math.floor(min(self.phase)/90)*90;phigh=math.ceil(max(self.phase)/90)*90
        if phigh==plow:plow-=90;phigh+=90
        fmin,fmax=self.frequencies[0],self.frequencies[-1]
        def xp(f):return upper.left()+math.log(f/fmin)/math.log(fmax/fmin)*upper.width()
        for rect,lo,hi,title,unit in [(upper,low,high,'MAGNITUDE','dB'),(lower,plow,phigh,'PHASE · UNWRAPPED','°')]:
            painter.setPen(QColor('#9eafc6'));painter.drawText(QRectF(rect.left(),rect.top()-24,rect.width(),20),title)
            increment=max(12,math.ceil((hi-lo)/6/12)*12) if rect==upper else max(90,math.ceil((hi-lo)/5/90)*90)
            ticks=range(math.ceil(lo/increment)*increment,int(hi)+1,increment)
            for v in ticks:
                y=rect.bottom()-(v-lo)/(hi-lo)*rect.height()
                painter.setPen(QPen(QColor('#2b3b52'),1));painter.drawLine(QPointF(rect.left(),y),QPointF(rect.right(),y))
                painter.setPen(QColor('#91a3bd'));painter.drawText(QRectF(0,y-9,54,18),Qt.AlignmentFlag.AlignRight,f'{v:g}{unit}')
            for f in [10,20,50,100,200,500,1000,2000,5000,10000,20000]:
                if not fmin<=f<=fmax:continue
                x=xp(f);painter.setPen(QPen(QColor('#23334a'),1));painter.drawLine(QPointF(x,rect.top()),QPointF(x,rect.bottom()))
                if rect==lower:
                    painter.setPen(QColor('#91a3bd'));painter.drawText(QRectF(x-22,rect.bottom()+8,44,20),Qt.AlignmentFlag.AlignCenter,f'{f/1000:g}k' if f>=1000 else str(f))
            path=QPainterPath()
            for i,value in enumerate(db if rect==upper else self.phase):
                point=QPointF(xp(self.frequencies[i]),rect.bottom()-(max(lo,min(hi,value))-lo)/(hi-lo)*rect.height())
                if i==0:path.moveTo(point)
                else:path.lineTo(point)
            painter.save();painter.setClipRect(rect);painter.setPen(QPen(QColor('#85e1c7' if rect==upper else '#91bfff'),2));painter.drawPath(path);painter.restore()
        if self.cursor and upper.left()<=self.cursor.x()<=upper.right():
            i=round((self.cursor.x()-upper.left())/upper.width()*(len(db)-1));i=max(0,min(len(db)-1,i))
            painter.setPen(QPen(QColor('#8eabc1'),1,Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(self.cursor.x(),upper.top()),QPointF(self.cursor.x(),lower.bottom()))
            painter.setPen(QColor('#edf6ff'));painter.drawText(QRectF(upper.left(),self.height()-23,upper.width(),20),
                Qt.AlignmentFlag.AlignCenter,f'{self.frequencies[i]:.1f} Hz     {db[i]:+.3f} dB     {self.phase[i]:+.2f}°')


class SimulationDialog(QDialog):
    def __init__(self,controller,parent=None,selected_node=None):
        super().__init__(parent);self.setWindowTitle('Frequency response · Stimulus / Probe')
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);self.resize(980,730)
        self.controller=controller;self.pending=False
        outer=QVBoxLayout(self);outer.setContentsMargins(22,20,22,20);outer.setSpacing(14)
        title=QLabel('Simulated frequency response');title.setStyleSheet('font-size:21px;font-weight:600;');outer.addWidget(title)
        row=QHBoxLayout();row.addWidget(QLabel('Stimulus'))
        self.source=QComboBox();self.source.setMinimumWidth(245);row.addWidget(self.source,1)
        row.addWidget(QLabel('Probe'));self.probe=QComboBox();self.probe.setMinimumWidth(245);row.addWidget(self.probe,1);outer.addLayout(row)
        options=QHBoxLayout();self.quantized=QCheckBox('5.23 quantized coefficients');options.addWidget(self.quantized)
        options.addStretch();options.addWidget(QLabel('Hz'))
        self.minimum=QDoubleSpinBox();self.minimum.setRange(.1,20000);self.minimum.setValue(10);self.minimum.setDecimals(1);options.addWidget(self.minimum)
        options.addWidget(QLabel('to'));self.maximum=QDoubleSpinBox();self.maximum.setRange(1,96000);self.maximum.setValue(20000);self.maximum.setDecimals(1);options.addWidget(self.maximum)
        outer.addLayout(options)
        self.plot=TransferPlot();outer.addWidget(self.plot,1)
        self.status=QLabel();self.status.setWordWrap(True);outer.addWidget(self.status)
        footer=QHBoxLayout();note=QLabel('Linear steady-state analysis. Volume slew, clipping and nonlinear audio behavior are not simulated.');note.setWordWrap(True);note.setObjectName('muted');footer.addWidget(note,1)
        self.export_button=QPushButton('Export CSV…');self.export_button.clicked.connect(self.export_csv);footer.addWidget(self.export_button);outer.addLayout(footer)
        self.refill(selected_node)
        self.source.currentIndexChanged.connect(self.recompute);self.probe.currentIndexChanged.connect(self.recompute)
        self.quantized.toggled.connect(self.recompute);self.minimum.valueChanged.connect(self.recompute);self.maximum.valueChanged.connect(self.recompute)
        controller.changed.connect(self.changed);self.recompute()

    def refill(self,selected_node=None):
        previous_source=self.source.currentData();previous_probe=self.probe.currentData()
        self.source.blockSignals(True);self.probe.blockSignals(True);self.source.clear();self.probe.clear()
        nodes=list(self.controller.project.nodes.values())
        names={}
        for node in nodes:
            same=[n for n in nodes if n.label==node.label]
            suffix=(f" [{node.properties.get('selectedchannel','DAC0')}]" if node.kind=='output' else
                    f' #{same.index(node)+1}' if len(same)>1 else '')
            names[node.id]=node.label+suffix
        # Hardware inputs first; sink inputs first in the probe selector.
        for node in sorted(nodes,key=lambda n:n.kind!='input'):
            for port in node.outputs:self.source.addItem(f'{names[node.id]} / {port.label}',(node.id,port.id))
        for node in sorted(nodes,key=lambda n:n.kind!='output'):
            for port in (node.outputs or node.inputs):self.probe.addItem(f'{names[node.id]} / {port.label}',(node.id,port.id))
        for combo,previous in [(self.source,previous_source),(self.probe,previous_probe)]:
            index=combo.findData(previous)
            if index>=0:combo.setCurrentIndex(index)
        if selected_node:
            for i in range(self.probe.count()):
                if self.probe.itemData(i)[0]==selected_node:self.probe.setCurrentIndex(i);break
        self.source.blockSignals(False);self.probe.blockSignals(False)

    def changed(self,kind):
        if kind=='position':return
        if not self.pending:
            self.pending=True;QTimer.singleShot(80,self.refresh)
    def refresh(self):
        self.pending=False;self.refill();self.recompute()

    def recompute(self,*args):
        self.plot.values=[];self.plot.frequencies=[];self.plot.phase=[]
        try:
            source,probe=self.source.currentData(),self.probe.currentData()
            if not source or not probe:raise DSPError('Add source and probe ports to the graph.')
            fs=self.controller.project.nodes[source[0]].fs
            lo,hi=self.minimum.value(),min(self.maximum.value(),fs*.499)
            if lo>=hi:raise DSPError('The minimum frequency must be below the maximum and Nyquist frequency.')
            frequencies=frequency_grid(self.controller.project,lo,hi,fs)
            values=simulate(self.controller.project,source,probe,frequencies,self.quantized.isChecked())
            self.plot.frequencies=frequencies;self.plot.values=values;self.plot.phase=unwrap(values)
            self.status.setText(f'{fs:g} Hz sample rate · {len(values)} frequency points · live graph response'+
                                (' · No signal path from stimulus to probe.' if all(abs(v)<1e-20 for v in values) else ''))
            self.status.setStyleSheet('color:#a5d9c8;')
        except (ValueError,OverflowError,KeyError) as exc:
            self.plot.error=str(exc);self.status.setText('Response unavailable: '+str(exc));self.status.setStyleSheet('color:#edb46d;')
        self.export_button.setEnabled(bool(self.plot.values));self.plot.update()

    def export_csv(self):
        path,_=QFileDialog.getSaveFileName(self,'Export frequency response','response.csv','CSV (*.csv)')
        if not path:return
        try:
            with Path(path).open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['frequency_hz','magnitude_db','phase_degrees','real','imaginary'])
                for f,h,p in zip(self.plot.frequencies,self.plot.values,self.plot.phase):writer.writerow([f,20*math.log10(max(abs(h),1e-12)),p,h.real,h.imag])
        except OSError as exc:QMessageBox.warning(self,'Export failed',str(exc))
