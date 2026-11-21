# SPDX-License-Identifier: GPL-3.0-or-later
"""Code-native, scalable functional schematics drawn inside DSP blocks."""
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen, QPainterPath, QPolygonF, QFont


def draw_function(p,node,rect,color):
    p.save();p.setClipRect(rect)
    p.translate(rect.topLeft());p.scale(rect.width()/190,rect.height()/64)
    p.setPen(QPen(color,1.8));p.setBrush(Qt.BrushStyle.NoBrush)
    def line(x,y,xx,yy):p.drawLine(QPointF(x,y),QPointF(xx,yy))
    def text(s,x=50,y=16,w=90,h=32,size=14):
        f=QFont();f.setPointSize(size);p.setFont(f);p.setPen(color)
        p.drawText(QRectF(x,y,w,h),Qt.AlignmentFlag.AlignCenter,str(s))
    def box(s,x=58,y=13,w=74,h=38):
        p.drawRoundedRect(QRectF(x,y,w,h),4,4);text(s,x,y,w,h,14)
    def io():line(3,32,56,32);line(134,32,187,32)
    def arrow(x,y):line(x-5,y-3,x,y);line(x-5,y+3,x,y)
    kind=node.symbol or node.kind
    if kind in ('gain','linear_gain','external_gain','button_volume'):
        line(3,30,62,30);line(129,30,187,30)
        p.drawPolygon(QPolygonF([QPointF(64,8),QPointF(64,51),QPointF(127,30)]))
        text('g',70,13,35,25,15)
        if kind=='external_gain':line(96,0,96,17);arrow(96,17)
        else:
            line(42,58,148,58)
            gain=node.properties.get('gain',0)
            x=42+max(0,min(1,(gain+60)/84))*106
            p.setBrush(color);p.drawEllipse(QPointF(x,58),3,3)
    elif kind in ('add','subtract','multiply','divide','absolute','sqrt','log','exp','invert','logic'):
        op={'add':'+','subtract':'−','multiply':'×','divide':'÷','absolute':'|x|','sqrt':'√x','log':'log x','exp':'2ˣ','invert':'−1','logic':'AND'}[kind]
        line(3,15,50,15);line(50,15,68,27)
        if len(node.inputs)>1:line(3,49,50,49);line(50,49,68,37)
        else:line(3,32,68,32)
        line(122,32,187,32)
        if kind in ('add','subtract','multiply','divide'):
            p.drawEllipse(QPointF(95,32),26,26);text(op,69,8,52,46,24)
        else:box(op,61,11,68,42)
    elif kind in ('peq','filter','first_order','biquad'):
        # Known settings use the same mathematical preview as the inspector.
        p.setPen(QPen(QColor('#52647c'),.8));line(7,50,181,50);line(7,7,7,50);line(7,30,181,30)
        path=QPainterPath();known=False
        if kind!='biquad':
            try:
                from .inspector import response
                for i in range(80):
                    value=response(node,min(20*1000**(i/79),node.fs*.499))
                    if value is None:break
                    point=QPointF(8+i/79*171,30-max(-20,min(20,value)))
                    path.lineTo(point) if known else path.moveTo(point)
                    known=True
            except (ValueError,ZeroDivisionError,OverflowError):known=False
        p.setPen(QPen(color,2.2))
        if known:p.drawPath(path)
        else:
            path.moveTo(9,45);path.cubicTo(55,45,60,10,100,14);path.cubicTo(135,18,152,17,181,17);p.drawPath(path)
            text('H(z)',70,27,60,28,12)
    elif kind=='crossover':
        line(3,32,42,32);line(42,32,57,14);line(42,32,57,50)
        box('LP',58,2,65,24);box('HP',58,38,65,24)
        line(124,14,187,14);line(124,50,187,50);arrow(183,14);arrow(183,50)
    elif kind=='delay':
        io();box('z⁻ᴰ');text('D',79,47,32,15,8)
    elif kind in ('input','auxadc'):
        box('ADC',44,12,68,39);line(112,32,187,32);arrow(182,32)
        for i in range(3):line(11+i*8,32-(i+1)*6,11+i*8,32+(i+1)*6)
    elif kind=='output':
        line(3,32,67,32);box('DAC',68,12,69,39)
        p.drawPolygon(QPolygonF([QPointF(151,26),QPointF(160,26),QPointF(170,17),QPointF(170,47),QPointF(160,38),QPointF(151,38)]))
        path=QPainterPath(QPointF(176,23));path.quadTo(187,32,176,41);p.drawPath(path)
    elif kind in ('sine','square','triangle','saw','noise','chime'):
        line(150,32,187,32);p.drawRoundedRect(QRectF(12,4,136,55),4,4)
        path=QPainterPath()
        for i in range(100):
            t=i/99
            if kind in ('sine','chime'):v=math.sin(t*math.pi*4)*(1-t*.55 if kind=='chime' else 1)
            elif kind=='square':v=1 if math.sin(t*math.pi*4)>=0 else -1
            elif kind=='triangle':v=2/math.pi*math.asin(math.sin(t*math.pi*4))
            elif kind=='saw':v=2*((t*2)%1)-1
            else:v=math.sin(i*17.12)*math.cos(i*9.4)
            q=QPointF(22+t*115,32-v*18)
            path.lineTo(q) if i else path.moveTo(q)
        p.drawPath(path)
    elif kind=='dc':
        box(str(node.properties.get('textvalue',node.properties.get('value',1))),31,12,81,40);line(113,32,187,32);arrow(183,32)
    elif kind=='switch':
        line(3,32,70,32);line(113,32,187,32)
        p.drawEllipse(QPointF(72,32),3,3);p.drawEllipse(QPointF(112,32),3,3)
        line(76,30,110,32 if node.properties.get('source_on',True) else 11)
    elif kind in ('mux','splitter'):
        p.drawPolygon(QPolygonF([QPointF(73,5),QPointF(119,17),QPointF(119,47),QPointF(73,59)]))
        for y in [16,32,48]:line(3,y,72,y)
        line(119,32,187,32);line(97,0,97,17);text('SEL',80,23,35,20,8)
        line(77,17,114,32)
    elif kind=='mixer':
        for y in [12,32,52]:
            line(3,y,52,y);line(52,y,80,32)
            p.drawEllipse(QPointF(40,y),3,3)
        p.drawEllipse(QPointF(103,32),23,23);text('Σ',82,9,43,43,23);line(126,32,187,32)
    elif kind=='compressor':
        line(10,54,10,7);line(10,54,110,54)
        path=QPainterPath(QPointF(12,52));path.lineTo(53,23);path.lineTo(110,9);p.drawPath(path)
        text('dB',125,15,50,30,12)
    elif kind=='clip':
        line(3,32,43,32);line(145,32,187,32)
        path=QPainterPath(QPointF(47,50));path.lineTo(72,50);path.lineTo(117,13);path.lineTo(142,13);p.drawPath(path)
    elif kind=='meter':
        line(3,32,53,32);box('RMS',55,9,66,44)
        for i,h in enumerate([14,22,32,42]):
            p.setBrush(color if i<3 else QColor('#304758'));p.drawRect(QRectF(135+i*10,53-h,6,h))
    elif kind in ('gpio','interface_in','interface_out'):
        line(3,32,57,32);box('GPIO' if kind=='gpio' else 'REG');line(133,32,187,32)
        for y in [18,30,42]:line(54,y,60,y);line(130,y,136,y)
    elif kind in ('counter','encoder'):
        io();box('A B' if kind=='encoder' else 'n + 1')
        if kind=='encoder':
            line(65,9,81,9);line(81,9,81,3);line(81,3,99,3)
        else:text('↻',145,7,32,40,25)
    elif kind=='lookup':
        io();box('LUT');line(69,42,80,36);line(80,36,92,37);line(92,37,109,22)
    else:
        # A functional transfer block, rather than an empty rectangle.
        io();box('f(x)');arrow(182,32)
    p.restore()
