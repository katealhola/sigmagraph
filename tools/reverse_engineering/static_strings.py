# SPDX-License-Identifier: GPL-3.0-or-later
"""Research-only, bounded IL interpreter for SigmaStudio string-table recovery.

Implements a limited whitelist of .NET IL operations and in-memory stream APIs.
Does not load or run .NET assemblies, call native target code, or deserialize
projects. Requires dnfile/dncil. Not a general CLR or a security sandbox.
The initial field defaults and cryptography factory stub match inspected files.
"""
import sys, io, struct, collections
from pathlib import Path
from inspect_il import Assembly
from dncil.clr.token import Token

class VM:
 def __init__(self,path):
  self.a=Assembly(path);self.static={};self.calls=[];self.cache={}
  for f in self.a.pe.net.mdtables.Field.rows:
   sig=f.Signature.value
   self.static[id(f)]=[] if sig[1:2]==b'\x1d' else None if sig[1:2] in [b'\x12',b'\x1c'] else 0
 def row(self,t):return self.a.pe.net.mdtables.tables[t>>24].rows[(t&0xffffff)-1]
 def name(self,t):return self.a.resolve(t).split(' [')[0]
 def sig(self,t,new=False):
  b=self.row(t).Signature.value;pos=1
  def uint():
   nonlocal pos
   x=b[pos];pos+=1
   if x<128:return x
   if x<192:y=((x&63)<<8)|b[pos];pos+=1;return y
   y=((x&31)<<24)|int.from_bytes(b[pos:pos+3],'big');pos+=3;return y
  if b[0]&16:uint()
  n=uint();return n+(bool(b[0]&32) and not new),b[pos]!=1
 def run(self,t,args=()):
  self.calls.append(self.name(t));stack=[];loc=collections.defaultdict(int)
  if t not in self.cache:
   b=self.a.body(self.row(t));self.cache[t]=(b.instructions,{x.offset:i for i,x in enumerate(b.instructions)})
  ins,off=self.cache[t];pc=0
  try:
   for step in range(160000000):
    i=ins[pc];pc+=1;op=i.opcode.name;v=i.operand
    if op.startswith('ldc.i4'):
     stack.append(v if op in ['ldc.i4','ldc.i4.s'] else -1 if op.endswith('m1') else int(op[-1]))
    elif op.startswith('ldarg'):stack.append(args[v.index if v is not None else int(op[-1])])
    elif op.startswith('ldloc'):stack.append(loc[v.index if v is not None else int(op[-1])])
    elif op.startswith('stloc'):loc[v.index if v is not None else int(op[-1])]=stack.pop()
    elif op=='ldnull':stack.append(None)
    elif op=='ldstr':stack.append(str(self.a.pe.net.user_strings.get(v.value&0xffffff)))
    elif op=='ldtoken':stack.append(v.value)
    elif op=='dup':stack.append(stack[-1])
    elif op=='pop':stack.pop()
    elif op=='newarr':stack.append([0]*stack.pop())
    elif op=='ldlen':stack.append(len(stack.pop()))
    elif op.startswith('ldelem'):
     ix=stack.pop();a=stack.pop();stack.append(a[ix])
    elif op.startswith('stelem'):
     val=stack.pop();ix=stack.pop();a=stack.pop();a[ix]=val&255 if op=='stelem.i1' else val
    elif op=='ldsfld':stack.append(self.static.get(id(self.row(v.value)),0))
    elif op=='stsfld':self.static[id(self.row(v.value))]=stack.pop()
    elif op.startswith('conv'):
     val=stack.pop()
     if op in ['conv.u1','conv.u4','conv.u8','conv.u']:val=int(val)&((1<<({'conv.u1':8,'conv.u8':64}.get(op,32)))-1)
     elif op=='conv.i4':val=(int(val)+2**31)%2**32-2**31
     elif op in ['conv.r.un','conv.r8']:val=float(val)
     else:val=int(val)
     stack.append(val)
    elif op in ['add','sub','mul','and','or','xor','shl','shr.un','shr','div','div.un','rem','rem.un']:
     r,l=stack.pop(),stack.pop()
     if op=='add':val=l+r
     elif op=='sub':val=l-r
     elif op=='mul':val=l*r
     elif op=='and':val=l&r
     elif op=='or':val=l|r
     elif op=='xor':val=l^r
     elif op=='shl':val=l<<(r&31)
     elif op=='shr.un':val=(l&0xffffffff)>>(r&31)
     elif op=='shr':val=l>>(r&31)
     elif op.startswith('div'):val=l//r
     elif op.startswith('rem'):val=l%r
     stack.append(val&0xffffffff if isinstance(val,int) and op not in ['div','rem','shr'] else val)
    elif op in ['br','br.s','leave','leave.s']:pc=off[v]
    elif op in ['brtrue','brtrue.s','brfalse','brfalse.s']:
     z=stack.pop();truth=(z is not None and z is not False and not (isinstance(z,(int,float)) and z==0))
     if truth==op.startswith('brtrue'):pc=off[v]
    elif op.startswith(('beq','bne','blt','bgt','ble','bge')):
     r,l=stack.pop(),stack.pop()
     if ((l==r) if op.startswith('beq') else (l!=r) if op.startswith('bne') else (l<r) if op.startswith('blt') else (l>r) if op.startswith('bgt') else (l<=r) if op.startswith('ble') else (l>=r)):pc=off[v]
    elif op=='switch':
     ix=stack.pop()
     if 0<=ix<len(v):pc=off[v[ix]]
    elif op in ['call','callvirt','newobj']:
     n,ret=self.sig(v.value,op=='newobj');aa=stack[-n:] if n else []
     if n:del stack[-n:]
     res=self.call(v.value,aa,op=='newobj')
     if ret or op=='newobj':stack.append(res)
    elif op in ['nop','castclass','box','unbox.any']:pass
    elif op=='ret':return stack.pop() if stack else None
    else:raise ValueError('unsupported '+op)
   raise ValueError('step limit')
  except Exception as e:
   if not getattr(e,'seen',False):
    e.seen=True;print('VM FAIL',self.name(t),hex(i.offset),op, 'stack',repr(stack)[:300], 'locals',{k:('<array '+str(len(v))+'>') if isinstance(v,list) else repr(v)[:100] for k,v in loc.items()},file=sys.stderr)
   raise
  finally:self.calls.pop()
 def call(self,t,a,new=False):
  name=self.name(t)
  if t>>24==6:
   if name.endswith('::CN9CFDh0N'):return {'aes':True}
   return self.run(t,a)
  if name.endswith('::GetTypeFromHandle'):return 'type'
  if name.endswith('::get_Assembly'):return 'assembly'
  if name.endswith('::GetManifestResourceStream'):
   return io.BytesIO(next(r.data for r in self.a.pe.net.resources if r.name==a[1]))
  if name=='System.IO.BinaryReader::.ctor':return a[0]
  if name.endswith('::get_BaseStream'):return a[0]
  if name.endswith('::set_Position'):a[0].seek(a[1]);return
  if name.endswith('::get_Length'):return len(a[0].getvalue())
  if name.endswith('::ReadBytes'):return list(a[0].read(a[1]))
  if name.endswith('::Close') or name.endswith('::set_UseMachineKeyStore'):return
  if name.endswith('::Reverse'):a[0].reverse();return
  if name.endswith('::GetName'):return 'assemblyname'
  if name.endswith('::GetPublicKeyToken'):return []
  if name.endswith('::ToInt32'):return struct.unpack_from('<i',bytes(a[0]),a[1])[0]
  if name.endswith('::get_Unicode'):return 'utf-16le'
  if name.endswith('::GetString'):return bytes(a[1][a[2]:a[2]+a[3]]).decode(a[0])
  if name.endswith('::set_Mode'):a[0]['mode']=a[1];return
  if name.endswith('::CreateDecryptor'):return {'key':a[1],'iv':a[2]}
  if name=='System.IO.MemoryStream::.ctor':return io.BytesIO()
  if name=='System.Security.Cryptography.CryptoStream::.ctor':return {'stream':a[0],'transform':a[1],'buffer':bytearray()}
  if name.endswith('::Write'):
   if isinstance(a[0],dict):a[0]['buffer'].extend(a[1][a[2]:a[2]+a[3]])
   else:a[0].write(bytes(a[1][a[2]:a[2]+a[3]]))
   return
  if name.endswith('::FlushFinalBlock'):
   import subprocess
   x=a[0];tr=x['transform'];key=bytes(tr['key']);iv=bytes(tr['iv'])
   p=subprocess.run(['openssl','enc','-d','-aes-'+str(len(key)*8)+'-cbc','-K',key.hex(),'-iv',iv.hex()],input=bytes(x['buffer']),capture_output=True,check=True)
   x['stream'].write(p.stdout);return
  if name.endswith('::ToArray'):return list(a[0].getvalue())
  raise ValueError('external '+name+' args '+repr(a)[:200])

if __name__ == '__main__':
 import argparse, json
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('assembly',type=Path)
 ap.add_argument('-o','--output',type=Path,required=True)
 args=ap.parse_args()
 vm=VM(args.assembly)
 token=next(0x06000000+i for owner,i,m in vm.a.methods if str(m.Name)=='U8IPZoo1I')
 vm.run(token,[0])
 blobs=[bytes(v) for v in vm.static.values() if isinstance(v,list) and len(v)>100]
 blob=max(blobs,key=len)
 at=0;strings={}
 while at<len(blob):
  n=struct.unpack_from('<i',blob,at)[0]
  if n<0 or n%2 or at+4+n>len(blob):
   raise ValueError(f'Invalid recovered string length at {at}')
  strings[str(at)]=blob[at+4:at+4+n].decode('utf-16le')
  at+=4+n
 args.output.write_text(json.dumps(strings,indent=2)+'\n')
 print(f'Recovered {len(strings)} strings, {at} bytes')
