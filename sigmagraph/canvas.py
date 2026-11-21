# SPDX-License-Identifier: GPL-3.0-or-later
"""Native Qt graphics scene: nodes, ports, patch cables and navigation."""
import math
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QTimer
from PySide6.QtGui import QColor, QPen, QBrush, QPainter, QPainterPath, QPainterPathStroker, QFont, QTransform
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsItem,
                              QGraphicsObject, QGraphicsPathItem, QMenu)

COLORS = {'input':'#66d8bc', 'output':'#edb46d', 'gain':'#79b8ff',
          'peq':'#ad9cf6', 'filter':'#ad9cf6', 'first_order':'#ad9cf6',
          'crossover':'#d398e3', 'delay':'#edb46d', 'generic':'#a8b3c8'}
COLORS.update({k:'#79b8ff' for k in ['external_gain','linear_gain','button_volume','add','subtract','multiply','divide','absolute','sqrt','log','exp','invert','logic']})
COLORS.update({k:'#66d8bc' for k in ['sine','square','triangle','saw','noise','dc','chime','switch','auxadc','gpio','interface_in','interface_out']})
COLORS.update({k:'#edb46d' for k in ['counter','encoder','mux','splitter','mixer','compressor','clip','meter','lookup','function']})
COLORS['biquad']='#ad9cf6'


def font(size, bold=False):
    f = QFont()
    f.setPointSize(size)
    f.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return f


def cable_path(a, b):
    bend = max(48., abs(b.x() - a.x()) * .45)
    path = QPainterPath(a)
    path.cubicTo(a + QPointF(bend, 0), b - QPointF(bend, 0), b)
    return path


class PortItem(QGraphicsObject):
    def __init__(self, owner, port, x, y):
        super().__init__(owner)
        self.owner, self.port_id, self.direction = owner, port.id, port.direction
        self.setPos(x, y)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setZValue(4)
        self.hovered = False
        self.setToolTip(f'{port.label} · {port.direction}put\nDrag to another block to connect. Each input has one driver.')

    def boundingRect(self):
        return QRectF(-11, -11, 22, 22)

    def paint(self, painter, option, widget=None):
        color = QColor(COLORS.get(self.owner.kind, '#9eabc4'))
        painter.setPen(QPen(color, 1.8))
        painter.setBrush(color if self.hovered else QColor('#192333'))
        painter.drawEllipse(QPointF(), 5.5 if self.hovered else 4.5, 5.5 if self.hovered else 4.5)

    def hoverEnterEvent(self, event):
        self.hovered = True; self.update()

    def hoverLeaveEvent(self, event):
        self.hovered = False; self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.scene().start_wire(self, event.scenePos())
            event.accept()

    def mouseMoveEvent(self, event):
        self.scene().move_wire(event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event):
        self.scene().finish_wire(event.scenePos())
        event.accept()


class NodeItem(QGraphicsObject):
    def __init__(self, owner, node):
        super().__init__()
        self.owner, self.node_id, self.kind = owner, node.id, node.kind
        self.width = 222.
        self.height = max(202., 158. + 22 * max(len(node.inputs), len(node.outputs)))
        self.ports = {}
        self.edges = []
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setZValue(2)
        self.setToolTip(f'{node.family}\n{node.algorithm}\n{node.fs:g} Hz')
        for direction, ports in [('in', node.inputs), ('out', node.outputs)]:
            for i, p in enumerate(ports):
                self.ports[p.id] = PortItem(self, p, 0 if direction == 'in' else self.width, 157 + i * 22)

    def boundingRect(self):
        return QRectF(-2, -2, self.width + 4, self.height + 7)

    def paint(self, painter, option, widget=None):
        node = self.owner.controller.project.nodes.get(self.node_id)
        if node is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(COLORS.get(node.kind, '#a8b3c8'))
        if not node.enabled:
            painter.setOpacity(.45)
        rect = QRectF(0, 0, self.width, self.height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 55))
        painter.drawRoundedRect(rect.translated(0, 4), 10, 10)
        painter.setPen(QPen(QColor('#77dfc3') if self.isSelected() else QColor('#354257'), 2 if self.isSelected() else 1))
        painter.setBrush(QColor('#202b3d') if self.isSelected() else QColor('#1c2738'))
        painter.drawRoundedRect(rect, 9, 9)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(12, 13, 4, 16), 2, 2)
        painter.setFont(font(13, True))
        painter.setPen(QColor('#f0f4fb'))
        fm = painter.fontMetrics()
        label = fm.elidedText(node.label, Qt.TextElideMode.ElideRight, int(self.width - 40))
        painter.drawText(QRectF(24, 10, self.width-34, 24), Qt.AlignmentFlag.AlignVCenter, label)
        painter.setFont(font(9))
        painter.setPen(QColor('#98a9c3'))
        brief = painter.fontMetrics().elidedText(node.brief(), Qt.TextElideMode.ElideRight, int(self.width-28))
        painter.drawText(QRectF(14, 115, self.width-28, 18), Qt.AlignmentFlag.AlignVCenter, brief)
        from .function_art import draw_function
        draw_function(painter,node,QRectF(16,42,self.width-32,65),color)
        painter.setPen(QPen(QColor('#2a374b'), 1))
        painter.drawLine(QPointF(12, 139), QPointF(self.width-12, 139))
        painter.setFont(font(9))
        painter.setPen(QColor('#b6c4d9'))
        for direction, ports in [('in', node.inputs), ('out', node.outputs)]:
            for i, p in enumerate(ports):
                r = QRectF(13, 147+i*22, self.width-26, 20)
                label=painter.fontMetrics().elidedText(p.label,Qt.TextElideMode.ElideRight,int(self.width/2-15))
                painter.drawText(r, Qt.AlignmentFlag.AlignVCenter |
                                 (Qt.AlignmentFlag.AlignLeft if direction=='in' else Qt.AlignmentFlag.AlignRight), label)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene() and not self.owner.syncing:
            if self.owner.snap:
                return QPointF(round(value.x()/8)*8, round(value.y()/8)*8)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for edge in self.edges: edge.refresh()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        positions = {i.node_id:(i.pos().x(), i.pos().y()) for i in self.scene().selectedItems() if isinstance(i, NodeItem)}
        if positions:
            self.owner.controller.move(positions)

    def mouseDoubleClickEvent(self, event):
        self.owner.inspect_requested.emit(self.node_id)
        event.accept()


class CableItem(QGraphicsPathItem):
    def __init__(self, owner, connection):
        super().__init__()
        self.owner, self.edge_id = owner, connection.id
        self.a = owner.nodes[connection.source_node].ports[connection.source_port]
        self.b = owner.nodes[connection.target_node].ports[connection.target_port]
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(0)
        self.hovered = False
        self.a.owner.edges.append(self)
        self.b.owner.edges.append(self)
        self.refresh()

    def refresh(self):
        self.setPath(cable_path(self.a.scenePos(), self.b.scenePos()))

    def shape(self):
        stroke = QPainterPathStroker()
        stroke.setWidth(12)
        return stroke.createStroke(self.path())

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = self.isSelected() or self.hovered
        painter.setPen(QPen(QColor('#b6f4df') if selected else QColor('#667e9b'), 3 if selected else 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())

    def hoverEnterEvent(self, event):
        self.hovered = True; self.update()

    def hoverLeaveEvent(self, event):
        self.hovered = False; self.update()


class GraphScene(QGraphicsScene):
    inspect_requested = Signal(str)
    ready = Signal()

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.nodes, self.cables = {}, {}
        self.snap, self.syncing = True, False
        self.pending = False
        self.wire = None
        self.wire_start = None
        self.last_kind = 'structure'
        controller.changed.connect(self.schedule_sync)
        self.setSceneRect(-4000, -3000, 10000, 7000)

    def schedule_sync(self, kind):
        if kind == 'structure': self.last_kind = 'structure'
        elif not self.pending: self.last_kind = kind
        if not self.pending:
            self.pending = True
            QTimer.singleShot(0, self.sync)

    def sync(self):
        self.pending = False
        self.syncing = True
        selected_nodes = {i.node_id for i in self.selectedItems() if isinstance(i, NodeItem)}
        selected_edges = {i.edge_id for i in self.selectedItems() if isinstance(i, CableItem)}
        project = self.controller.project
        if self.last_kind == 'structure' or set(self.nodes) != set(project.nodes):
            self.cancel_wire()
            self.clear()
            self.nodes, self.cables = {}, {}
            for key, node in project.nodes.items():
                item = NodeItem(self, node)
                self.nodes[key] = item
                self.addItem(item)
                item.setPos(node.x, node.y)
                item.setSelected(key in selected_nodes)
            for key, edge in project.connections.items():
                if edge.source_node in self.nodes and edge.target_node in self.nodes:
                    item = CableItem(self, edge)
                    self.cables[key] = item
                    self.addItem(item)
                    item.setSelected(key in selected_edges)
        else:
            for key, node in project.nodes.items():
                item = self.nodes[key]
                item.setPos(node.x, node.y)
                item.update()
                item.setToolTip(f'{node.family}\n{node.algorithm}\n{node.fs:g} Hz')
            for cable in self.cables.values(): cable.refresh()
        self.syncing = False
        self.ready.emit()

    def start_wire(self, port, pos):
        self.cancel_wire()
        self.wire_start = port
        self.wire = QGraphicsPathItem()
        self.wire.setPen(QPen(QColor('#78e2c5'), 2.5, Qt.PenStyle.DashLine))
        self.wire.setZValue(5)
        self.addItem(self.wire)
        self.move_wire(pos)
        self.controller.message.emit('Drag to a port. Connecting to an occupied input replaces its cable.')

    def move_wire(self, pos):
        if self.wire and self.wire_start:
            a, b = self.wire_start.scenePos(), pos
            self.wire.setPath(cable_path(a, b) if self.wire_start.direction=='out' else cable_path(b, a))

    def finish_wire(self, pos):
        start = self.wire_start
        target = next((i for i in self.items(pos) if isinstance(i, PortItem) and i is not start), None)
        self.cancel_wire()
        if start and target:
            try:
                self.controller.connect(start.owner.node_id, start.port_id, target.owner.node_id, target.port_id)
                self.controller.message.emit('Connected. Undo restores the previous wiring.')
            except ValueError as exc:
                self.controller.message.emit(str(exc))
        else:
            self.controller.message.emit('Connection cancelled.')

    def cancel_wire(self):
        if self.wire:
            self.removeItem(self.wire)
        self.wire = self.wire_start = None

    def selected_node_ids(self):
        return [i.node_id for i in self.selectedItems() if isinstance(i, NodeItem)]

    def delete_selection(self):
        nodes = self.selected_node_ids()
        edges = [i.edge_id for i in self.selectedItems() if isinstance(i, CableItem)]
        if nodes or edges: self.controller.remove(nodes, edges)

    def select_node(self, node_id):
        self.clearSelection()
        if node_id in self.nodes: self.nodes[node_id].setSelected(True)


class GraphView(QGraphicsView):
    zoom_changed = Signal(int)
    block_dropped = Signal(str, float, float)

    def __init__(self, scene):
        super().__init__(scene)
        self.setObjectName('graphView')
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setBackgroundBrush(QColor('#111a28'))
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.panning = False
        self.space = False
        self.last_pan = None

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor('#111a28'))
        scale = self.transform().m11()
        grid = 24 if scale >= .55 else 48
        start_x = math.floor(rect.left()/grid)*grid
        start_y = math.floor(rect.top()/grid)*grid
        painter.setPen(QPen(QColor('#2a3547'), 1/scale))
        points = [QPointF(x,y) for x in range(start_x, int(rect.right())+grid, grid)
                  for y in range(start_y, int(rect.bottom())+grid, grid)]
        painter.drawPoints(points)

    def set_zoom(self, scale):
        scale = min(2.5, max(.2, scale))
        self.setTransform(QTransform.fromScale(scale, scale))
        self.zoom_changed.emit(round(scale*100))

    def wheelEvent(self, event):
        self.set_zoom(self.transform().m11() * (1.16 if event.angleDelta().y()>0 else 1/1.16))
        event.accept()

    def fit_graph(self):
        if self.scene().nodes:
            rect = QRectF()
            for item in self.scene().nodes.values(): rect = rect.united(item.sceneBoundingRect())
            rect = rect.adjusted(-50, -70, 50, 70)
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            if self.transform().m11() > 1: self.set_zoom(1)
            self.centerOn(rect.center())
            self.zoom_changed.emit(round(self.transform().m11()*100))

    def mousePressEvent(self, event):
        if event.button()==Qt.MouseButton.MiddleButton or (self.space and event.button()==Qt.MouseButton.LeftButton):
            self.panning = True
            self.last_pan = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else: super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.panning:
            delta = event.position() - self.last_pan
            self.last_pan = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-round(delta.y()))
            event.accept()
        else: super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.panning:
            self.panning = False
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.space else Qt.CursorShape.ArrowCursor)
            event.accept()
        else: super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key()==Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space = True; self.setCursor(Qt.CursorShape.OpenHandCursor); event.accept()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.scene().delete_selection(); event.accept()
        elif event.key()==Qt.Key.Key_Escape:
            self.scene().cancel_wire(); self.scene().clearSelection(); event.accept()
        elif event.key()==Qt.Key.Key_F:
            self.fit_graph(); event.accept()
        else: super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key()==Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space = False; self.setCursor(Qt.CursorShape.ArrowCursor); event.accept()
        else: super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.space = self.panning = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().focusOutEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat('application/x-sigmagraph-block'): event.acceptProposedAction()
        elif event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasFormat('application/x-sigmagraph-block'):
            kind = bytes(event.mimeData().data('application/x-sigmagraph-block')).decode()
            pos = self.mapToScene(event.position().toPoint())
            self.block_dropped.emit(kind, pos.x(), pos.y())
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                self.window().open_path(urls[0].toLocalFile())
                event.acceptProposedAction()

    def contextMenuEvent(self, event):
        from .model import TEMPLATES
        from .registry import catalog
        menu = QMenu(self)
        if self.scene().selectedItems():
            menu.addAction('Delete selection', self.scene().delete_selection)
            menu.addAction('Duplicate blocks', lambda: self.scene().controller.duplicate(self.scene().selected_node_ids()))
            if self.scene().selected_node_ids():menu.addAction('Probe selected block…',self.window().simulate_document)
            menu.addSeparator()
        add = menu.addMenu('Add block')
        pos = self.mapToScene(event.pos())
        for key, info in TEMPLATES.items():
            add.addAction(info[0], lambda k=key: self.block_dropped.emit(k, pos.x(), pos.y()))
        add.addSeparator()
        categories={}
        for key,entry in catalog().items():
            group=entry['category']
            if group not in categories:categories[group]=add.addMenu(group)
            categories[group].addAction(entry['label'],lambda k=key:self.block_dropped.emit(k,pos.x(),pos.y()))
        menu.addSeparator()
        menu.addAction('Fit graph', self.fit_graph)
        menu.exec(event.globalPos())
