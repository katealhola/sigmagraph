# SPDX-License-Identifier: GPL-3.0-or-later
"""Undoable mutations and clean-state tracking for saved graph documents."""
import copy
import math
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack
from .model import Project, make_node, uid, Connection


class StateCommand(QUndoCommand):
    def __init__(self, owner, text, before, after, kind):
        super().__init__(text)
        self.owner, self.before, self.after, self.kind = owner, before, after, kind

    def redo(self):
        self.owner.project.restore(self.after)
        self.owner.changed.emit(self.kind)

    def undo(self):
        self.owner.project.restore(self.before)
        self.owner.changed.emit(self.kind)


class Controller(QObject):
    changed = Signal(str)
    opened = Signal()
    message = Signal(str)

    def __init__(self):
        super().__init__()
        self.project = Project()
        self.save_path = None
        self.undo = QUndoStack(self)
        self.undo.setUndoLimit(150)

    def load(self, project, path=None):
        self.project = project
        self.save_path = path
        self.undo.clear()
        self.undo.setClean()
        self.opened.emit()
        self.changed.emit('structure')

    def save(self,path):
        from .persistence import save_project
        saved=save_project(self.project,path)
        self.save_path=str(saved)
        self.undo.setClean()
        return saved

    def perform(self, text, mutate, kind='structure'):
        before = self.project.state()
        try:
            mutate()
            after = self.project.state()
        except Exception:
            self.project.restore(before)
            raise
        self.project.restore(before)
        if before != after:
            self.undo.push(StateCommand(self, text, before, after, kind))

    def connect(self, a, ap, b, bp):
        self.perform('Connect blocks', lambda: self.project.connect(a, ap, b, bp))

    def move(self, positions):
        def apply():
            for key, (x, y) in positions.items():
                if key in self.project.nodes:
                    self.project.nodes[key].x = float(x)
                    self.project.nodes[key].y = float(y)
        self.perform('Move blocks', apply, 'position')

    def edit(self, node_id, scope, key, value):
        if node_id not in self.project.nodes:
            return
        node = self.project.nodes[node_id]
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Enter a finite number.')
        if scope == 'node' and key == 'label' and not str(value).strip():
            raise ValueError('A block needs a name.')
        if scope=='node' and key=='fs' and value<=0:
            raise ValueError('Sample rate must be positive.')
        if scope=='ui' and key=='S0.R0.Index' and not 0<=value<15:
            raise ValueError('EQ band count must be between 1 and 15.')
        def apply():
            node = self.project.nodes[node_id]
            if scope == 'node': setattr(node, key, value)
            elif scope == 'ui':
                node.ui[key] = value
                if key=='S0.R0.Index':
                    for i in range(value+1):
                        fkey=f'S0.R0.Frequency1{i}'
                        if not 0<node.ui.get(fkey,0)<node.fs/2:node.ui[fkey]=min(1000.,node.fs/4)
                        for prefix,default in [('Q',1.),('Boost',0.),('Type',0),('Bypass',False)]:
                            node.ui.setdefault(f'S0.R0.{prefix}{i}',default)
            else:
                node.properties[key] = value
                if key=='selectedchannel' and 'Item' in node.properties:node.properties['Item']=value
        self.perform('Edit '+key.rsplit('.', 1)[-1], apply, 'property')

    def add(self, kind, x, y):
        node = make_node(kind, self.project.sample_rate, x, y)
        names = {n.label for n in self.project.nodes.values()}
        base, i = node.label, 2
        while node.label in names:
            node.label = f'{base} {i}'; i += 1
        self.perform('Add '+base, lambda: self.project.nodes.update({node.id:node}))
        return node.id

    def remove(self, nodes=(), connections=()):
        self.perform('Delete selection', lambda: self.project.remove(nodes, connections))

    def duplicate(self, ids):
        clones, port_map = {}, {}
        for old in ids:
            if old not in self.project.nodes: continue
            n = copy.deepcopy(self.project.nodes[old])
            n.id, n.algorithm, n.label = uid(), uid(), n.label+' copy'
            n.x += 36; n.y += 36
            for p in n.ports:
                old_pin = p.id
                p.id = uid()
                port_map[(old, old_pin)] = (n.id, p.id)
            clones[old] = n
        edges = []
        for e in self.project.connections.values():
            if e.source_node in clones and e.target_node in clones:
                a, ap = port_map[(e.source_node, e.source_port)]
                b, bp = port_map[(e.target_node, e.target_port)]
                edges.append(Connection(uid(), a, ap, b, bp))
        def apply():
            self.project.nodes.update({n.id:n for n in clones.values()})
            self.project.connections.update({e.id:e for e in edges})
        self.perform('Duplicate blocks', apply)
        return [n.id for n in clones.values()]

    def auto_layout(self):
        self.perform('Arrange graph', self.project.layout, 'position')

    def grow(self,node_id,delta=1):
        from .registry import definition
        from .model import Port
        node=self.project.nodes[node_id]
        entry=definition(node.catalog_id)
        if not entry or not entry['repeater']:return
        rep=entry['repeater'];current=node.source_algorithm.get('rep',rep['min'])
        target=current+delta
        if not rep['min']<=target<=rep['max']:return
        def apply():
            n=self.project.nodes[node_id]
            for direction,growth in [('in',rep['in_grow']),('out',rep['out_grow'])]:
                count=abs(delta)*growth
                existing=[p for p in n.ports if p.direction==direction]
                if delta>0:
                    for i in range(count):n.ports.append(Port(uid(),('In' if direction=='in' else 'Out')+f' {len(existing)+i+1}',direction))
                elif count:
                    removed={p.id for p in existing[-count:]}
                    n.ports=[p for p in n.ports if p.id not in removed]
                    self.project.connections={k:e for k,e in self.project.connections.items() if e.source_port not in removed and e.target_port not in removed}
            n.source_algorithm['rep']=target
        self.perform('Grow block' if delta>0 else 'Reduce block',apply)
