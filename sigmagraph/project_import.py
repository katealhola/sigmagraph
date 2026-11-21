# SPDX-License-Identifier: GPL-3.0-or-later
"""Project normalization recovered from the supplied SigmaStudio corpus."""
import collections
import re
import xml.etree.ElementTree as ET
from .nrbf import Reader, deref, FormatError

def expanded(g, v, seen=None):
    seen = set() if seen is None else seen
    if isinstance(v, dict) and '$ref' in v:
        oid = v['$ref']
        if oid in seen:
            return {'$cycle':oid}
        seen = seen | {oid}
        v = deref(g, v)
    if isinstance(v, dict) and 'type' in v:
        if v['type'] == 'Array':
            return [expanded(g, x, seen) for x in v['values']]
        m = v.get('members', {})
        if v['type'] == 'System.Collections.ArrayList':
            a = expanded(g, m['_items'], seen)
            return a[:m['_size']]
        if set(m) == {'value__'}:
            return m['value__']
        return {'$type':v['type'], **{k:expanded(g,x,seen) for k,x in m.items() if k not in ('password','PWCell')}}
    return v


def ui_settings(snapshot):
    result = {}
    def walk(o):
        if isinstance(o, dict):
            if o.get('$type') == 'System.Collections.Hashtable' and 'Keys' in o:
                for key,value in zip(o['Keys'],o['Values']):
                    result[key] = value.get('data') if isinstance(value,dict) and value.get('$type')=='Analog.Data.UIData' else value
            if 'key' in o and 'value' in o and isinstance(o['key'],str):
                v=o['value']
                result[o['key']] = v.get('data') if isinstance(v,dict) and v.get('$type')=='Analog.Data.UIData' else v
            for v in o.values():
                walk(v)
        elif isinstance(o,list):
            for v in o:
                walk(v)
    walk(snapshot)
    return result


def lower_graph(algs, links):
    """Collapse only observed transparent schematic helper types."""
    transparent={'SStudio.TConectionAlg','SStudio.StimulyAlg','SStudio.ProbeAlg'}
    byname={a['text']:a for a in algs}
    pin_owner={p['nid']:a for a in algs for p in a.get('pins',[]) if isinstance(p,dict)}
    incoming=collections.defaultdict(list)
    for link in links:
        incoming[link['to']].append(link['from'])
    def origin(pin,seen=None):
        seen=set() if seen is None else seen
        if pin in seen:
            raise ValueError('Routing helper cycle')
        owner=pin_owner[pin]
        if owner['$type'] not in transparent:
            p=next(p for p in owner['pins'] if p['nid']==pin)
            return [(owner['text'],p['name'])]
        result=[]
        for p in owner['pins']:
            if p['dir']==0:
                for src in incoming[p['nid']]:
                    result.extend(origin(src,seen|{pin}))
        return result
    edges=[]
    for a in algs:
        if a['$type'] in transparent:
            continue
        for p in a.get('pins',[]):
            if p['dir']==0:
                for src in incoming[p['nid']]:
                    for name,pin in origin(src):
                        edges.append({'from_algorithm':name,'from_pin':pin,
                                      'to_algorithm':a['text'],'to_pin':p['name']})
    return {'algorithms':[a['text'] for a in algs if a['$type'] not in transparent], 'edges':edges}


def compare_netlist(lowered,path):
    root=ET.parse(path).getroot()
    algorithms=root.findall('./IC/Schematic/Algorithm')
    netpins=collections.defaultdict(list)
    for a in algorithms:
        for p in a.findall('Link'):
            # Export adds _in/_out to the stored pin name.
            pin=p.attrib['pin'].removesuffix('_in').removesuffix('_out')
            netpins[p.attrib['link']].append((p.attrib['dir'],a.attrib['name'],pin))
    expected=set()
    for pairs in netpins.values():
        for d,a,p in pairs:
            if d=='in':
                for sd,sa,sp in pairs:
                    if sd=='out':expected.add((sa,sp,a,p))
    actual={tuple(e[k] for k in ('from_algorithm','from_pin','to_algorithm','to_pin')) for e in lowered['edges']}
    return {'algorithm_names_match':set(lowered['algorithms'])=={a.attrib['name'] for a in algorithms},
            'edges_match':actual==expected,'expected_edges':len(expected),'actual_edges':len(actual),
            'missing_edges':sorted(expected-actual),'extra_edges':sorted(actual-expected)}


def project_summary(g):
    root = g['objects'][g['root']]
    m = root['members']
    algs, pins, cells, links, ui = [], {}, [], [], []
    for obj in g['objects'].values():
        q = obj.get('members', {})
        if obj['type'] == 'Analog.BaseLib.BaseLink':
            links.append({k:expanded(g,v) for k,v in q.items() if k != 'points'})
        if 'cell' in q and 'dspname' in q and 'text' in q:
            a = expanded(g, {'$ref':obj['id']})
            algs.append(a)
            for p in a.get('pins', []):
                if isinstance(p, dict) and 'nid' in p:
                    pins[p['nid']] = {'algorithm':a.get('text'), 'cell_nid':a.get('cell'), **p}
        if obj['type'] == 'Analog.Data.UIData':
            ui.append(expanded(g, {'$ref':obj['id']}))
    for k,v in m.items():
        if re.fullmatch(r'lyr\d+node\d+', k):
            o = deref(g,v)
            if o['type'] == 'Analog.BaseLib.BaseLink':
                continue
            # UI snapshot contains persistence wrappers, so keep it in a separate subtree.
            cells.append({'object_id':o['id'], '$type':o['type'],
                          **{key:expanded(g,val) for key,val in o.get('members',{}).items()
                             if key not in ('PWCell','algs','UICellSnapShot')},
                          'ui_snapshot':expanded(g,o.get('members',{}).get('UICellSnapShot'))})
    for link in links:
        link['source'] = pins.get(link.get('from'))
        link['destination'] = pins.get(link.get('to'))
    # Hierarchy boards may own cells that are not direct lyrNnodeM members of
    # the outer document. Retain those cells as well for the flattened view.
    known={c['object_id'] for c in cells}
    for o in g['objects'].values():
        q=o.get('members',{})
        if o['id'] not in known and all(k in q for k in ('nid','name','algs')):
            cells.append({'object_id':o['id'],'$type':o['type'],
                **{key:expanded(g,val) for key,val in q.items() if key not in ('PWCell','algs','UICellSnapShot')},
                'ui_snapshot':expanded(g,q.get('UICellSnapShot'))})
    for cell in cells:
        cell['ui_settings']=ui_settings(cell['ui_snapshot'])
    hardware = []
    hw = deref(g,m.get('HView'))
    if hw:
        for k,v in hw['members'].items():
            if re.fullmatch(r'node\d+', k):
                hardware.append(expanded(g,v))
    return {'format':'SigmaStudio NRBF normalized graph', 'project_name':expanded(g,m.get('name')),
            'version':[m.get(k) for k in ('version','minorversion','build','revision')],
            'default_fs':m.get('defaultfs'), 'default_block_size':m.get('defaultBlockSize'),
            'layers':[{ 'name':expanded(g,m.get(f'layer{i}')), 'node_count':m.get(f'nodecount{i}')}
                      for i in range(m.get('layercount',0))],
            'hardware':hardware, 'cells':cells, 'algorithms':algs, 'links':links, 'ui_data':ui,
            'lowered_graph':lower_graph(algs,links)}
