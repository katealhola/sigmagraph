# SPDX-License-Identifier: GPL-3.0-or-later
"""Data-only MS-NRBF reader. Never loads assemblies or instantiates CLR objects.

Supports records observed in SigmaStudio 4.6 .dspproj files plus common arrays.
Object identities and references are retained in a JSON-friendly graph.
"""
import argparse
import json
import math
import struct
from pathlib import Path


class FormatError(ValueError):
    pass


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.objects = {}
        self.schemas = {}
        self.libraries = {}
        self.records = []
        self.root = None

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise FormatError(f"Truncated at 0x{self.pos:x}: need {n} bytes")
        out = self.data[self.pos:self.pos+n]
        self.pos += n
        return out

    def unpack(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))[0]

    def byte(self):
        return self.unpack('B')

    def i32(self):
        return self.unpack('i')

    def count(self):
        n = self.i32()
        if not 0 <= n <= 10_000_000:
            raise FormatError(f"Invalid count {n} at 0x{self.pos:x}")
        return n

    def string(self):
        n = 0
        for shift in range(0, 35, 7):
            b = self.byte()
            n |= (b & 127) << shift
            if b < 128:
                return self.take(n).decode('utf-8', errors='strict')
        raise FormatError('Invalid string length')

    def primitive(self, kind):
        fmts = {1:'?', 2:'B', 6:'d', 7:'h', 8:'i', 9:'q', 10:'b',
                11:'f', 12:'q', 13:'Q', 14:'H', 15:'I', 16:'Q'}
        if kind in fmts:
            v = self.unpack(fmts[kind])
            return v if not isinstance(v, float) or math.isfinite(v) else str(v)
        if kind in (5, 18):
            return self.string()
        if kind == 17:
            return None
        if kind == 3:
            first = self.take(1)
            n = 1 if first[0] < 128 else 2 if first[0] < 224 else 3 if first[0] < 240 else 4
            return (first + self.take(n-1)).decode('utf-8')
        raise FormatError(f'Unsupported primitive {kind} at 0x{self.pos:x}')

    def type_info(self, kind):
        if kind in (0, 7):
            return self.byte()
        if kind == 3:
            return self.string()
        if kind == 4:
            return {'name': self.string(), 'library': self.i32()}
        if kind in (1, 2, 5, 6):
            return None
        raise FormatError(f'Unsupported binary type {kind}')

    def value(self):
        while True:
            kind, v = self.record()
            if kind != 12:
                return v

    def members(self, oid, schema):
        obj = {'id':oid, 'type':schema['name'], 'library':schema.get('library'), 'members':{}}
        self.objects[oid] = obj
        for name, kind, info in zip(schema['names'], schema['kinds'], schema['info']):
            obj['members'][name] = self.primitive(info) if kind == 0 else self.value()
        return {'$ref':oid}

    def array_values(self, n, kind, info):
        if kind == 0:
            return [self.primitive(info) for _ in range(n)]
        out = []
        while len(out) < n:
            v = self.value()
            if isinstance(v, dict) and '$nulls' in v:
                if v['$nulls'] < 1 or len(out) + v['$nulls'] > n:
                    raise FormatError('Invalid null run')
                out.extend([None] * v['$nulls'])
            else:
                out.append(v)
        return out

    def record(self):
        start = self.pos
        kind = self.byte()
        self.records.append({'offset':start, 'record':kind})
        if kind == 0:
            self.root = self.i32()
            v = {'root':self.root, 'header':self.i32(), 'major':self.i32(), 'minor':self.i32()}
            if v['major'] != 1 or v['minor'] != 0:
                raise FormatError('Unsupported stream version')
        elif kind == 12:
            oid = self.i32()
            self.libraries[oid] = self.string()
            v = None
        elif kind in (2, 3, 4, 5):
            oid, name, n = self.i32(), self.string(), self.count()
            names = [self.string() for _ in range(n)]
            kinds = [self.byte() for _ in range(n)] if kind in (4, 5) else [2]*n
            info = [self.type_info(k) for k in kinds]
            lib = self.i32() if kind in (3, 5) else None
            schema = {'name':name, 'names':names, 'kinds':kinds, 'info':info, 'library':lib}
            self.schemas[oid] = schema
            v = self.members(oid, schema)
        elif kind == 1:
            oid, metadata = self.i32(), self.i32()
            if metadata not in self.schemas:
                raise FormatError(f'Unknown class metadata {metadata}')
            v = self.members(oid, self.schemas[metadata])
        elif kind == 6:
            oid = self.i32()
            self.objects[oid] = {'id':oid, 'type':'System.String', 'value':self.string()}
            v = {'$ref':oid}
        elif kind == 7:
            oid, array_type, rank = self.i32(), self.byte(), self.count()
            lengths = [self.count() for _ in range(rank)]
            lower = [self.i32() for _ in range(rank)] if array_type in (3, 4, 5) else None
            bt = self.byte()
            info = self.type_info(bt)
            obj = {'id':oid, 'type':'Array', 'element_type':bt, 'element_info':info,
                   'array_type':array_type, 'lengths':lengths, 'lower_bounds':lower}
            self.objects[oid] = obj
            n = math.prod(lengths)
            if n > 10_000_000:
                raise FormatError('Array too large')
            obj['values'] = self.array_values(n, bt, info)
            v = {'$ref':oid}
        elif kind == 8:
            v = self.primitive(self.byte())
        elif kind == 9:
            v = {'$ref':self.i32()}
        elif kind == 10:
            v = None
        elif kind == 11:
            v = {'$end':True}
        elif kind in (13, 14):
            v = {'$nulls':self.byte() if kind == 13 else self.count()}
        elif kind in (15, 16, 17):
            oid, n = self.i32(), self.count()
            bt, info = (0, self.byte()) if kind == 15 else (2 if kind == 16 else 1, None)
            obj = {'id':oid, 'type':'Array', 'element_type':bt, 'element_info':info, 'lengths':[n]}
            self.objects[oid] = obj
            obj['values'] = self.array_values(n, bt, info)
            v = {'$ref':oid}
        else:
            raise FormatError(f'Unsupported record {kind} at 0x{start:x}')
        return kind, v

    def parse(self):
        if not self.data:
            raise FormatError('Empty file')
        if self.data[:1] != b'\0':
            raise FormatError('Expected SerializedStreamHeader')
        while self.pos < len(self.data):
            k, _ = self.record()
            if k == 11:
                break
        else:
            raise FormatError('Missing MessageEnd')
        refs = set()
        def collect(x):
            if isinstance(x, dict):
                if '$ref' in x:
                    refs.add(x['$ref'])
                else:
                    for y in x.values(): collect(y)
            elif isinstance(x, list):
                for y in x: collect(y)
        collect(list(self.objects.values()))
        missing = sorted(refs - self.objects.keys())
        if missing:
            raise FormatError(f'Unresolved references: {missing}')
        return {'format':'MS-NRBF', 'root':self.root, 'bytes_consumed':self.pos,
                'trailing_bytes':len(self.data)-self.pos, 'libraries':self.libraries,
                'objects':self.objects, 'schemas':self.schemas, 'records':self.records}


def deref(graph, v):
    if isinstance(v, dict) and '$ref' in v:
        objects = graph['objects']
        v = objects.get(v['$ref'], objects.get(str(v['$ref'])))
        if v and v['type'] == 'System.String':
            return v['value']
    return v


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('project', type=Path)
    ap.add_argument('-o', '--output', type=Path)
    args = ap.parse_args()
    graph = Reader(args.project.read_bytes()).parse()
    result = json.dumps(graph, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(result + '\n')
    else:
        print(result)
