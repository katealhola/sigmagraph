# SPDX-License-Identifier: GPL-3.0-or-later
"""Editable graph IR, independent of both Qt and the original serializer."""
from __future__ import annotations
import copy
import math
import re
import uuid
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from .nrbf import Reader, FormatError
from .project_import import project_summary


def uid():
    return uuid.uuid4().hex


@dataclass
class Port:
    id: str
    label: str
    direction: str
    signal: int = 0
    data: int = 1
    source_name: str = ''


@dataclass
class Node:
    id: str
    label: str
    kind: str
    family: str
    algorithm: str
    fs: float
    x: float
    y: float
    ports: list[Port]
    properties: dict = field(default_factory=dict)
    ui: dict = field(default_factory=dict)
    source_cell: dict = field(default_factory=dict)
    source_algorithm: dict = field(default_factory=dict)
    catalog_id: str = ''
    symbol: str = ''

    @property
    def inputs(self):
        return [p for p in self.ports if p.direction == 'in']

    @property
    def outputs(self):
        return [p for p in self.ports if p.direction == 'out']

    @property
    def enabled(self):
        return self.properties.get('enable', True)

    def brief(self):
        if self.kind == 'gain':
            return f"{self.properties.get('gain', 0):+g} dB · RC slew"
        if self.kind == 'delay':
            samples = self.properties.get('Value0', 1)
            return f'{samples:g} samples · {samples / self.fs * 1000:.3f} ms'
        if self.kind == 'crossover':
            lo = self.ui.get('S0.R0.FrequencyLow', 1000)
            hi = self.ui.get('S0.R0.FrequencyHigh', 1500)
            return f'{lo:g} / {hi:g} Hz · 2 way'
        if self.kind == 'peq':
            return f'{len(self.eq_bands())} bands · double precision'
        if self.kind in ('filter', 'first_order'):
            f = self.properties.get('Frequency', self.properties.get('firstorder_freq0', 1000))
            order = self.properties.get('Order', 1)
            return f'{f:g} Hz · order {order:g}'
        if self.kind == 'input':
            return f'{len(self.outputs)} channels · analog input'
        if self.kind == 'output':
            return str(self.properties.get('selectedchannel', 'DAC0'))
        if self.kind in ('sine','square','triangle','saw','chime'):
            return f"{self.properties.get('freq',self.properties.get('frequency',500)):g} Hz · source"
        if self.kind=='dc':return f"DC = {self.properties.get('textvalue',self.properties.get('value',1)):g}"
        if self.kind=='external_gain':return 'External volume control · slew'
        return self.family

    def eq_bands(self):
        # ParametricEQ.PackData explicitly uses UI Index + 1 as filter count.
        # Preserve dormant slots, but do not include them in the response/editor.
        indices = sorted({int(m[1]) for k in self.ui
                          if (m := re.fullmatch(r'S0\.R0\.Frequency1(\d+)', k))})
        if 'S0.R0.Index' in self.ui:
            return [i for i in indices if i <= self.ui['S0.R0.Index']]
        return [i for i in indices if 0 < self.ui[f'S0.R0.Frequency1{i}'] < self.fs / 2]


@dataclass
class Connection:
    id: str
    source_node: str
    source_port: str
    target_node: str
    target_port: str


@dataclass
class Project:
    name: str = 'Untitled signal flow'
    source_path: str | None = None
    version: list = field(default_factory=list)
    target: str = 'ADAU1701'
    nodes: dict[str, Node] = field(default_factory=dict)
    connections: dict[str, Connection] = field(default_factory=dict)
    original_graph: dict | None = None
    normalized_source: dict | None = None
    notes: list[str] = field(default_factory=list)

    def state(self):
        return copy.deepcopy((self.nodes, self.connections))

    def restore(self, state):
        self.nodes, self.connections = copy.deepcopy(state)

    @property
    def sample_rate(self):
        rates = Counter(n.fs for n in self.nodes.values())
        return rates.most_common(1)[0][0] if rates else 48000

    def port(self, node_id, port_id):
        node = self.nodes.get(node_id)
        if node:
            return next((p for p in node.ports if p.id == port_id), None)
        return None

    def connect(self, first_node, first_port, second_node, second_port):
        a, b = self.port(first_node, first_port), self.port(second_node, second_port)
        if a is None or b is None:
            raise ValueError('One of these ports no longer exists.')
        if a.direction == b.direction:
            raise ValueError('Connect an output to an input.')
        if a.direction == 'in':
            first_node, second_node = second_node, first_node
            first_port, second_port = second_port, first_port
            a, b = b, a
        if (a.signal, a.data) != (b.signal, b.data):
            raise ValueError('These ports use different signal types.')
        if self.nodes[first_node].fs != self.nodes[second_node].fs:
            raise ValueError('These blocks use different sample rates. Match their rates before connecting.')
        if any((e.source_node, e.source_port, e.target_node, e.target_port) ==
               (first_node, first_port, second_node, second_port) for e in self.connections.values()):
            return
        # Inputs have a single driver. Replacing it is one undoable operation.
        for key, edge in list(self.connections.items()):
            if (edge.target_node, edge.target_port) == (second_node, second_port):
                del self.connections[key]
        edge = Connection(uid(), first_node, first_port, second_node, second_port)
        self.connections[edge.id] = edge

    def remove(self, node_ids=(), connection_ids=()):
        ids = set(node_ids)
        for key in ids:
            self.nodes.pop(key, None)
        for key, edge in list(self.connections.items()):
            if key in connection_ids or edge.source_node in ids or edge.target_node in ids:
                del self.connections[key]

    def issues(self):
        result = []
        seen = set()
        for edge in self.connections.values():
            a, b = self.port(edge.source_node, edge.source_port), self.port(edge.target_node, edge.target_port)
            if not a or not b:
                result.append('Connection references a missing port.')
                continue
            if a.direction != 'out' or b.direction != 'in':
                result.append('Connection direction is invalid.')
            if self.nodes[edge.source_node].fs != self.nodes[edge.target_node].fs:
                result.append('Connected blocks use different sample rates.')
            key = (edge.target_node, edge.target_port)
            if key in seen:
                result.append('Input has more than one driver.')
            seen.add(key)
        for node in self.nodes.values():
            if not math.isfinite(node.fs) or node.fs <= 0:
                result.append(f'{node.label}: invalid sample rate.')
            for port in node.inputs:
                if (node.id, port.id) not in seen:
                    result.append(f'{node.label} · {port.label} is unconnected.')
        return result

    def layout(self):
        """Deterministic layered layout; cycles remain editable in a fallback column."""
        indegree = {k: 0 for k in self.nodes}
        children = defaultdict(list)
        for e in self.connections.values():
            if e.source_node in self.nodes and e.target_node in self.nodes:
                children[e.source_node].append(e.target_node)
                indegree[e.target_node] += 1
        queue = deque(sorted((k for k, n in indegree.items() if n == 0),
                             key=lambda k: (self.nodes[k].y, self.nodes[k].label)))
        depth = defaultdict(int)
        ordered = []
        while queue:
            key = queue.popleft()
            ordered.append(key)
            for target in children[key]:
                depth[target] = max(depth[target], depth[key] + 1)
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        remaining = [k for k in self.nodes if k not in ordered]
        for key in remaining:
            depth[key] = max(depth.values(), default=0) + 1
        # Align sinks and preserve branch lanes across shorter/longer paths.
        last_column=max(depth.values(),default=0)
        for key,n in self.nodes.items():
            if n.kind=='output': depth[key]=last_column
        port_order={p.id:i for n in self.nodes.values() for i,p in enumerate(n.outputs)}
        edge_order={(e.source_node,e.target_node):port_order.get(e.source_port,0) for e in self.connections.values()}
        leaves=[]
        visited=set()
        for root in ordered+remaining:
            stack=[root]
            while stack:
                key=stack.pop()
                if key in visited:continue
                visited.add(key)
                targets=sorted(set(children[key]),key=lambda t:(edge_order.get((key,t),0),self.nodes[t].y))
                if not targets:leaves.append(key)
                stack.extend(reversed(targets))
        leaf_rank={k:i for i,k in enumerate(leaves)}
        memo={k:({leaf_rank[k]} if k in leaf_rank else set()) for k in self.nodes}
        for key in reversed(ordered):
            for child in children[key]:memo[key].update(memo[child])
        columns = defaultdict(list)
        for key in ordered + remaining:
            columns[depth[key]].append(key)
        for col, keys in columns.items():
            def desired(key):
                values=memo.get(key,set())
                return sum(values)/len(values)*158+50 if values else self.nodes[key].y
            keys.sort(key=lambda k: (desired(k), self.nodes[k].label))
            previous_bottom=-float('inf')
            for key in keys:
                node = self.nodes[key]
                node.x, node.y = col * 290 + 50, max(desired(key)*1.4,previous_bottom+38)
                previous_bottom=node.y+max(202,158+22*max(len(node.inputs),len(node.outputs)))


TYPE_INFO = {
    'ICSigma100In': ('input', 'Audio input'),
    'ICSigma100Out': ('output', 'Audio output'),
    'SWGain1940DBAlg': ('gain', 'Volume'),
    'MultCtrlDel1940Alg': ('delay', 'Delay'),
    'CrossoverFilter2WayAlgDP': ('crossover', 'Crossover'),
    'PEQ1Chan': ('peq', 'Parametric EQ'),
    'NthOrderDouble': ('filter', 'Butterworth filter'),
    'FistOrderSingle': ('first_order', 'First-order filter'),
}


def from_dspproj(path: str | Path):
    path = Path(path)
    data = path.read_bytes()
    if len(data) > 64 * 1024 * 1024:
        raise FormatError('This project exceeds the 64 MB import limit.')
    try:
        raw = Reader(data).parse()
        source = project_summary(raw)
    except (ValueError, KeyError, UnicodeError, RecursionError) as exc:
        raise FormatError(f'Cannot read {path.name}: {exc}') from exc
    p = Project(path.stem, str(path.resolve()), source['version'],
                original_graph=raw, normalized_source=source)
    hardware_types={h.get('$type','') for h in source['hardware'] if isinstance(h,dict)}
    for hardware,target in [('Sigma100.DSPSigma100','ADAU1701'),('Sigma200.DSPSigma200','ADAU144x'),
                            ('SigmaLp1.DSPSigmaLP1','ADAU176x'),('SigmaLp2.DSPSigmaLp2','ADAU138x'),('ADICtrls.DSP1940','AD1940')]:
        if hardware in hardware_types:p.target=target;break
    cells = {c['nid']: c for c in source['cells'] if 'nid' in c}
    allowed = set(source['lowered_graph']['algorithms'])
    by_port_name = {}
    for alg in source['algorithms']:
        if alg['text'] not in allowed:
            continue
        c = cells[alg['cell']]
        typename = alg['$type'].split('.')[-1]
        from .registry import definition
        entry=definition(alg['$type']) or definition(typename)
        from .registry import classify
        kind, family = TYPE_INFO.get(typename, ((entry['symbol'],entry['label']) if entry else (classify(typename),typename)))
        key = alg['text']
        ports = []
        for pin in alg['pins']:
            if not pin.get('active', True):
                continue
            direction = 'in' if pin['dir'] == 0 else 'out'
            index = sum(x.direction == direction for x in ports)
            label = ('In' if direction == 'in' else 'Out')
            if kind == 'input':
                label = f'ADC {index}'
            elif kind == 'gain':
                label = ('L', 'R')[index] if index < 2 else str(index+1)
            elif kind == 'crossover' and direction == 'out':
                label = ('Low', 'High')[index] if index < 2 else str(index+1)
            elif len([q for q in alg['pins'] if q['dir'] == pin['dir'] and q.get('active', True)]) > 1:
                label += f' {index+1}'
            if entry and typename not in TYPE_INFO:
                metadata_ports=[p for p in entry['ports'] if p['direction']==direction]
                label=(pin.get('gpToolTipName') or (metadata_ports[index]['label'] if index<len(metadata_ports) else label))
            port = Port(str(pin['nid']), label, direction, pin.get('signal', 0),
                        pin.get('data', 1), pin['name'])
            ports.append(port)
            by_port_name[(key, pin['name'])] = port.id
        props = {k: copy.deepcopy(v) for k, v in c.items()
                 if k not in ('object_id', '$type', 'ui_settings', 'ui_snapshot', 'x', 'y')}
        if 'selectedchannel' in alg:
            props['selectedchannel'] = alg['selectedchannel']
        fs,x,y=float(alg['fs']),float(c.get('x',0)),float(c.get('y',0))
        if not all(math.isfinite(v) for v in (fs,x,y)) or fs<=0:
            raise FormatError(f'{key} has an invalid sample rate or position.')
        p.nodes[key] = Node(key, c['name'], kind, family, key, fs, x, y, ports,
                            props, copy.deepcopy(c['ui_settings']), copy.deepcopy(c), copy.deepcopy(alg))
        p.nodes[key].catalog_id=entry['id'] if entry else ''
        p.nodes[key].symbol=entry['symbol'] if entry else kind
    for edge in source['lowered_graph']['edges']:
        a, b = edge['from_algorithm'], edge['to_algorithm']
        ap, bp = by_port_name.get((a, edge['from_pin'])), by_port_name.get((b, edge['to_pin']))
        if ap is not None and bp is not None:
            e = Connection(uid(), a, ap, b, bp)
            p.connections[e.id] = e
        else:
            p.notes.append('A connection to an inactive or unknown pin was omitted.')
    p.notes.append('Probes, stimulus controls, and routing helpers are collapsed in signal-flow view.')
    p.layout()
    return p


TEMPLATES = {
    'input': ('Audio input', 'I/O', [], ['ADC 0', 'ADC 1']),
    'output': ('Audio output', 'I/O', ['In'], []),
    'gain': ('Volume', 'Level', ['L', 'R'], ['L', 'R']),
    'peq': ('Parametric EQ', 'Filters', ['In'], ['Out']),
    'filter': ('High-pass filter', 'Filters', ['In'], ['Out']),
    'first_order': ('Low-pass filter', 'Filters', ['In'], ['Out']),
    'crossover': ('2-way crossover', 'Filters', ['In'], ['Low', 'High']),
    'delay': ('Delay', 'Time', ['In'], ['Out']),
}


def make_node(kind, fs=48000, x=0, y=0):
    if kind not in TEMPLATES:
        from .registry import catalog, defaults
        entry=catalog()[kind]
        preset=copy.deepcopy(entry.get('preset',{}))
        base=make_node(entry['symbol'],fs,x,y) if entry['symbol'] in TEMPLATES else None
        props={**(base.properties if base else {'enable':True}),**defaults(entry),**preset.get('properties',{})}
        if 'textvalue' in props:props.pop('value',None)
        if 'freq' in props:props.pop('frequency',None)
        if 'ison' in props:props.pop('source_on',None)
        ports=[Port(uid(),p['label'],p['direction'],p.get('signal',0),p.get('data',1))
               for p in preset.get('ports',entry['ports'])]
        return Node(uid(),entry['label'],entry['symbol'],entry['label'],entry['id'],fs,x,y,ports,
                    props,{**(base.ui if base else {}),**preset.get('ui',{})},source_algorithm={'$type':entry['id'],'rep':preset.get('repetitions',entry['repeater']['min'] if entry['repeater'] else 1)},
                    catalog_id=entry['id'],symbol=entry['symbol'])
    label, _, ins, outs = TEMPLATES[kind]
    key = uid()
    props = {'enable': True}
    ui = {}
    if kind == 'gain':
        props.update(gain=0., min=-80., max=24., step=12.)
    elif kind == 'delay':
        props.update(Value0=1., CtrlMax0=2047, CtrlNumber=1)
    elif kind == 'filter':
        props.update(Frequency=40., Order=2., type=0, BitmapIndex=1,
                     FilterEnabled=True, PhaseShiftEnabled=False)
    elif kind == 'first_order':
        props.update(Count=1, firstorder_type0=0, firstorder_freq0=2000., firstorder_gain0=0.)
    elif kind == 'output':
        props.update(selectedchannel='DAC0')
    elif kind == 'crossover':
        for i, t in enumerate([1, 1, 1, 0], 1): ui[f'S0.R0.Type{i}'] = t
        ui.update({'S0.R0.FrequencyLow':1000., 'S0.R0.FrequencyHigh':1500.,
                   'S0.R0.FrequencyMidLow':250., 'S0.R0.FrequencyMidHigh':3000.,
                   'S0.R0.Gain1':0., 'S0.R0.Gain2':0., 'S0.R0.Gain3':0.,
                   'S0.R0.InvertLow':False, 'S0.R0.InvertHigh':False})
    elif kind == 'peq':
        ui['S0.R0.Index'] = 2
        for i, f in enumerate([100., 1000., 6000.]):
            for name, value in [('Frequency1', f), ('Q', 1.), ('Boost', 0.), ('Type', 0), ('Bypass', False)]:
                ui[f'S0.R0.{name}{i}'] = value
    ports = [Port(uid(), name, direction) for direction, names in [('in', ins), ('out', outs)] for name in names]
    return Node(key, label, kind, label, key, fs, x, y, ports, props, ui)


def demo_project():
    p = Project('Stereo crossover', notes=['Example signal flow. Open a .dspproj to edit your own design.'])
    nodes = [make_node(k) for k in ['input', 'gain', 'crossover', 'crossover', 'peq', 'peq', 'peq', 'peq', 'delay', 'delay', 'output', 'output', 'output', 'output']]
    for i,n in enumerate(nodes[10:]): n.properties['selectedchannel']=f'DAC{i}'
    for n in nodes: p.nodes[n.id] = n
    def link(i, a, j, b=0):
        p.connect(nodes[i].id, nodes[i].outputs[a].id, nodes[j].id, nodes[j].inputs[b].id)
    link(0, 0, 1, 0); link(0, 1, 1, 1)
    link(1, 0, 2); link(1, 1, 3)
    link(2, 0, 4); link(2, 1, 5); link(3, 0, 6); link(3, 1, 7)
    link(4, 0, 8); link(6, 0, 9)
    link(8, 0, 10); link(5, 0, 11); link(9, 0, 12); link(7, 0, 13)
    for i, n in enumerate(nodes): n.y = i * 70
    p.layout()
    return p
