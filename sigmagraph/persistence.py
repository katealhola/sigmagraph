# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned, data-only native projects; atomic saves never overwrite an import."""
from __future__ import annotations
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import tempfile
from .model import Project, Node, Port, Connection, from_dspproj

FORMAT = 'SigmaGraph project'
SCHEMA = 1
MAX_BYTES = 64 * 1024 * 1024


def save_project(project, path):
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() != '.sgproj':
        raise ValueError('Save native projects with the .sgproj extension. SigmaStudio .dspproj files are imports.')
    payload = {'format': FORMAT, 'schema': SCHEMA, 'project': asdict(project)}
    data = (json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2)+'\n').encode('utf-8')
    if len(data) > MAX_BYTES:
        raise ValueError('Project exceeds the 64 MiB native project limit.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.'+path.name, suffix='.tmp', delete=False) as stream:
            temporary = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return path


def load_project(path):
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() == '.dspproj':
        return from_dspproj(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Project exceeds the 64 MiB native project limit.')
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out: raise ValueError('Duplicate JSON key: '+key)
            out[key] = value
        return out
    try:
        doc = json.loads(path.read_text('utf-8'), object_pairs_hook=pairs,
                         parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Non-finite number: '+x)))
        if doc['format'] != FORMAT or type(doc['schema']) is not int or doc['schema'] != SCHEMA:
            raise ValueError('Unsupported SigmaGraph project format or schema version.')
        raw = doc['project']
        project = Project(**{k:v for k,v in raw.items() if k not in ('nodes','connections')})
        if not isinstance(project.name,str) or not isinstance(project.target,str): raise ValueError('Invalid project metadata.')
        for key, value in raw['nodes'].items():
            node = Node(**{**value, 'ports':[Port(**p) for p in value['ports']]})
            if not isinstance(key,str) or node.id != key or not key or not isinstance(node.label,str):
                raise ValueError('Invalid block identity.')
            if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in (node.x,node.y,node.fs)) or node.fs <= 0:
                raise ValueError('Invalid block position or sample rate.')
            if any(not isinstance(v,dict) for v in (node.properties,node.ui,node.source_cell,node.source_algorithm)):
                raise ValueError('Invalid block settings.')
            seen = set()
            for port in node.ports:
                if not isinstance(port.id,str) or not port.id or port.id in seen or port.direction not in ('in','out'):
                    raise ValueError('Invalid or duplicate block port.')
                seen.add(port.id)
            project.nodes[key] = node
        inputs = set()
        for key,value in raw['connections'].items():
            edge = Connection(**value)
            if edge.id != key or not key: raise ValueError('Invalid connection identity.')
            a,b = project.port(edge.source_node,edge.source_port),project.port(edge.target_node,edge.target_port)
            if not a or not b or a.direction != 'out' or b.direction != 'in':
                raise ValueError('Connection references an invalid port.')
            target = (edge.target_node,edge.target_port)
            if target in inputs: raise ValueError('An input has multiple connections.')
            inputs.add(target)
            project.connections[key] = edge
        return project
    except (KeyError,TypeError,AttributeError,OverflowError,RecursionError) as exc:
        raise ValueError('Malformed SigmaGraph project: '+str(exc)) from exc
