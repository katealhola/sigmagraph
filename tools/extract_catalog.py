# SPDX-License-Identifier: GPL-3.0-or-later
"""Extract the installed Sigma100 toolbox from .NET metadata without executing it.

Developer utility; requires dnfile. Production ships the resulting JSON only.
"""
import argparse
import collections
import hashlib
import json
import logging
import struct
from pathlib import Path
import dnfile
logging.getLogger('dnfile').setLevel(logging.ERROR)

class Blob:
 def __init__(self,b):self.b=b;self.p=2
 def i32(self):v=struct.unpack_from('<i',self.b,self.p)[0];self.p+=4;return v
 def string(self):
  x=self.b[self.p];self.p+=1
  if x==255:return None
  if x<128:n=x
  elif x<192:n=((x&63)<<8)|self.b[self.p];self.p+=1
  else:n=((x&31)<<24)|int.from_bytes(self.b[self.p:self.p+3],'big');self.p+=3
  s=self.b[self.p:self.p+n].decode('utf-8');self.p+=n;return s
 def strings(self):return [self.string() for _ in range(self.i32())]

def extract(path):
 pe=dnfile.dnPE(str(path));tables=pe.net.mdtables
 interfaces=collections.defaultdict(list)
 def type_name(t):return str(t.TypeNamespace)+'.'+str(t.TypeName)
 for r in tables.InterfaceImpl:interfaces[id(r.Class.row)].append(type_name(r.Interface.row))
 attributes=collections.defaultdict(dict)
 for r in tables.CustomAttribute:
  if r.Parent.table.name!='TypeDef':continue
  try:
   owner=r.Type.row.Class.row;name=str(owner.TypeName);reader=Blob(r.Value.value)
   if name in ('TreeToolBoxAtt','AlgFriendlyName','CategoryAttribute','CellFriendlyName'):value=reader.string()
   elif name=='RequiredAlgIntfAttribute':value=reader.strings()
   elif name=='PinsAttribute':value=[reader.i32(),reader.i32()]
   elif name=='PinNameAtt':value=[reader.strings(),reader.strings()]
   elif name=='RepeaterAttribute':value=[reader.i32() for _ in range(6)]
   elif name=='ObsoleteAttribute':value=True
   else:continue
   attributes[id(r.Parent.row)][name]=value
  except (IndexError,AttributeError,UnicodeError,struct.error):pass
 cells=[]
 for t in tables.TypeDef:
  a=attributes[id(t)]
  if 'RequiredAlgIntfAttribute' in a:cells.append((t,a))
 result=[]
 for t in tables.TypeDef:
  impl=interfaces[id(t)];a=attributes[id(t)]
  if 'ADICtrls.IDspSigma100' not in impl or not a.get('AlgFriendlyName') or 'PinsAttribute' not in a or a.get('ObsoleteAttribute'):continue
  compatible=[(c,ca) for c,ca in cells if any(i in impl for i in ca['RequiredAlgIntfAttribute'])]
  compatible.sort(key=lambda x:len(x[1]['RequiredAlgIntfAttribute']))
  cell,ca=compatible[0] if compatible else (None,{})
  category=ca.get('CategoryAttribute','Other algorithms')
  tree=a.get('TreeToolBoxAtt','')
  labels=a.get('PinNameAtt',[[],[]]);base=a['PinsAttribute'];rep=a.get('RepeaterAttribute')
  inputs,outputs=base
  if rep:
   inputs=max(inputs,base[0]+(rep[0]-1)*rep[4]);outputs=max(outputs,base[1]+(rep[0]-1)*rep[5])
  # Empty PinNameAtt arrays can contain one empty placeholder even for zero
  # actual inputs (e.g. oscillators). Counts come from Pins/Repeater, not names.
  ports=[]
  for direction,count,names in [('in',inputs,labels[0]),('out',outputs,labels[1])]:
   for i in range(count):ports.append({'label':names[i] if i<len(names) else ('In' if direction=='in' else 'Out')+f' {i+1}', 'direction':direction,'signal':0,'data':1})
  result.append({'id':type_name(t),'type_name':str(t.TypeName),'label':a['AlgFriendlyName'].strip(),
   'category':category,'path':[p for p in tree.split('.') if p],
   'cell_type':type_name(cell) if cell else None,'ports':ports,
   'repeater':{'min':rep[0],'max':rep[1],'in_grow':rep[4],'out_grow':rep[5]} if rep else None,
   'dynamic_pins':any(str(m.row.Name) in ('get_InputPinCount','get_OutputPinCount','MakePin') for m in t.MethodList)})
 return {'target':'ADAU1701 / Sigma100','source_assembly':path.name,
  'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
  'documentation':'https://wiki.analog.com/resources/tools-software/sigmastudio/toolbox',
  'entries':sorted(result,key=lambda x:(x['category'],x['path'],x['label']))}

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('assembly',type=Path);p.add_argument('-o','--output',type=Path,required=True);args=p.parse_args()
 result=extract(args.assembly);args.output.write_text(json.dumps(result,indent=2)+'\n')
 print(len(result['entries']),'algorithms');print(collections.Counter(e['category'] for e in result['entries']))
