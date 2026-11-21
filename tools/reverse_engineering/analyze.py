# SPDX-License-Identifier: GPL-3.0-or-later
"""Inventory SigmaStudio projects and verify exported artifacts, without executing CLR code."""
import argparse
import collections
import csv
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from nrbf import Reader, deref, FormatError
from adau1701 import c_arrays, hex_bytes, decode_program, pack_instruction, FIELDS, parameter_image, decode_q523


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')


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


def parse_params(text):
    out = []
    text = re.split(r'Parameter data for:', text, maxsplit=1)[0]
    for chunk in re.split(r'(?=Cell Name\s*=)', text):
        def field(name):
            m = re.search(re.escape(name)+r'\s*=\s*([^\r\n]+)', chunk)
            return m[1].strip() if m else None
        if field('Parameter Address') is None:
            continue
        data = hex_bytes(chunk)
        out.append({'cell':field('Cell Name'), 'name':field('Parameter Name'),
                    'address':int(field('Parameter Address')), 'value':field('Parameter Value'),
                    'data_hex':data.hex(), 'byte_count':len(data),
                    'q523':decode_q523(data) if len(data)==4 else None})
    return out


def analyze(source, dest):
    dest.mkdir(parents=True, exist_ok=True)
    inventory, project_results, exports = [], [], []
    for p in sorted(source.rglob('*')):
        if p.is_file() and p.suffix.lower() in ('.dspproj','.hex','.params','.dat','.h','.xml'):
            b=p.read_bytes()
            inventory.append({'path':str(p), 'bytes':len(b), 'sha256':sha(b)})
    for p in sorted(source.rglob('*.dspproj')):
        result = {'path':str(p), 'bytes':p.stat().st_size}
        try:
            g=Reader(p.read_bytes()).parse()
            summary=project_summary(g)
            result.update(status='ok', objects=len(g['objects']), records=len(g['records']),
                          trailing_bytes=g['trailing_bytes'], algorithm_count=len(summary['algorithms']),
                          links=len(summary['links']))
            netlist=source/(p.stem+'_NetList.xml')
            if netlist.exists():
                result['netlist_comparison']=compare_netlist(summary['lowered_graph'],netlist)
            # Duplicate input copies get distinct filenames while preserving source evidence.
            prefix = p.stem if p.parent == source else p.stem+'-nested'
            write_json(dest/(prefix+'.project.json'), summary)
            write_json(dest/(prefix+'.schemas.json'), g['schemas'])
        except (FormatError, UnicodeError, KeyError, ValueError) as e:
            result.update(status='invalid', error=str(e))
        project_results.append(result)
    for p in sorted(source.glob('*_IC_1.h')):
        stem=p.name.removesuffix('_IC_1.h')
        arrays=c_arrays(p.read_text(encoding='utf-8-sig'))
        e={'name':stem, 'arrays':{k:{'bytes':len(v),'sha256':sha(v)} for k,v in arrays.items()}, 'checks':{}}
        param=arrays.get('Param_Data_IC_1')
        prog=arrays.get('Program_Data_IC_1')
        e['has_program']=prog is not None
        for name, data in [('parameters',param),('program',prog)]:
            if data is not None:
                (dest/(stem+'.'+name+'.bin')).write_bytes(data)
        if prog is not None:
            decoded=decode_program(prog)
            encoded=b''.join(pack_instruction(**{k:r[k] for k,_ in FIELDS}) for r in decoded)
            e['checks']['instruction_field_roundtrip']=encoded==prog
            e['instruction_count']=len(decoded)
            e['last_non_nop_pc']=max((r['pc'] for r in decoded if not r['is_nop']), default=None)
            e['nop_count']=sum(r['is_nop'] for r in decoded)
            write_json(dest/(stem+'.instructions.json'), decoded)
            with (dest/(stem+'.instructions.csv')).open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(decoded[0]));writer.writeheader();writer.writerows(decoded)
        hp=source/(stem+'.hex')
        if hp.exists():
            hx=hex_bytes(hp.read_text())
            e['hex_bytes']=len(hx)
            e['checks']['hex_equals_parameter_array']=hx==param
            if len(hx)==len(param or b'')+4:
                e['hex_trailing_bytes']=hx[-4:].hex()
                e['checks']['hex_prefix_equals_parameter_array']=hx[:-4]==param
        pp=source/(stem+'.params')
        if pp.exists():
            records=parse_params(pp.read_text())
            write_json(dest/(stem+'.parameters.json'), records)
            e['parameter_records']=len(records)
            counts=collections.Counter(r['address'] for r in records)
            e['duplicate_parameter_addresses']={str(k):v for k,v in counts.items() if v>1}
            try:
                image=parameter_image(records)
                e['checks']['params_rebuild_equals_array']=image==param
                if image!=param:
                    e['rebuild_differing_words']=[i for i in range(1024) if image[i*4:i*4+4]!=param[i*4:i*4+4]] if param and len(param)==4096 else None
            except ValueError as err:
                e['parameter_rebuild_error']=str(err)
        xp=source/(stem+'.xml')
        if xp.exists():
            xml=ET.parse(xp).getroot()
            e['xml_download_blocks']=[]
            for node in xml.findall('./IC/*'):
                if node.tag not in ('Program','Register'):
                    continue
                data=hex_bytes(node.findtext('Data',''))
                e['xml_download_blocks'].append({'kind':node.tag,'name':node.findtext('Name'),
                    'address':node.findtext('Address'),'size':node.findtext('Size'),
                    'bytes':len(data),'sha256':sha(data)})
                if node.tag=='Program':
                    e['checks']['xml_program_equals_header']=data==prog
                if node.findtext('Name')=='Param':
                    e['checks']['xml_parameters_equal_header']=data==param
        exports.append(e)
    tx=source/'TxBuffer_IC_1.dat'
    nb=source/'NumBytes_IC_1.dat'
    transactions=[]
    if tx.exists() and nb.exists():
        b=hex_bytes(tx.read_text());lengths=[int(n) for n in re.findall(r'\d+',nb.read_text())]
        at=0
        for n in lengths:
            block=b[at:at+n]
            transactions.append({'offset':at, 'declared_bytes':n,'bytes':len(block),
                 'address':int.from_bytes(block[:2],'big'), 'payload_hex':block[2:].hex()})
            at+=n
        write_json(dest/'transactions.json', {'total_bytes':len(b),'consumed_bytes':at,
                   'transactions':transactions})
    summary={'source':str(source),'files':inventory,'projects':project_results,'exports':exports}
    write_json(dest/'analysis.json',summary)
    return summary


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path)
    ap.add_argument('-o','--output',type=Path,required=True)
    args=ap.parse_args()
    s=analyze(args.source,args.output)
    print(json.dumps({'projects':s['projects'],'exports':s['exports']},indent=2))
