# SPDX-License-Identifier: GPL-3.0-or-later
"""Native libusb transport for classic USBi. No Windows runtime or PyUSB needed.

CLI defaults to read-only operations. Uses endpoint 0 without changing USB
configuration, driver bindings, target power, reset pins or EEPROM contents.
"""
from __future__ import annotations
import argparse
import ctypes as c
import ctypes.util
import json
import os
from pathlib import Path
import struct
import threading
import time
from usbi_protocol import write_chunks

class USBError(RuntimeError):pass

class Descriptor(c.Structure):
    _fields_=[('length',c.c_ubyte),('type',c.c_ubyte),('usb',c.c_ushort),
              ('device_class',c.c_ubyte),('subclass',c.c_ubyte),('protocol',c.c_ubyte),
              ('max_packet',c.c_ubyte),('vendor',c.c_ushort),('product',c.c_ushort),
              ('device',c.c_ushort),('manufacturer_string',c.c_ubyte),
              ('product_string',c.c_ubyte),('serial_string',c.c_ubyte),('configs',c.c_ubyte)]

class LibUSB:
    def __init__(self,path=None):
        names=[path] if path else [ctypes.util.find_library('usb-1.0'),'/opt/homebrew/lib/libusb-1.0.dylib','/usr/local/lib/libusb-1.0.dylib']
        self.lib=None;fail=[]
        for name in filter(None,names):
            try:self.lib=c.CDLL(name);self.path=name;break
            except OSError as exc:fail.append(str(exc))
        if self.lib is None:raise USBError('libusb is unavailable: '+'; '.join(fail))
        def bind(name,args,ret):
            fn=getattr(self.lib,'libusb_'+name);fn.argtypes=args;fn.restype=ret
        bind('init',[c.POINTER(c.c_void_p)],c.c_int)
        bind('exit',[c.c_void_p],None)
        bind('error_name',[c.c_int],c.c_char_p)
        bind('get_device_list',[c.c_void_p,c.POINTER(c.POINTER(c.c_void_p))],c.c_ssize_t)
        bind('free_device_list',[c.POINTER(c.c_void_p),c.c_int],None)
        bind('get_device_descriptor',[c.c_void_p,c.POINTER(Descriptor)],c.c_int)
        bind('get_bus_number',[c.c_void_p],c.c_ubyte)
        bind('get_device_address',[c.c_void_p],c.c_ubyte)
        bind('get_device_speed',[c.c_void_p],c.c_int)
        bind('get_port_numbers',[c.c_void_p,c.POINTER(c.c_ubyte),c.c_int],c.c_int)
        bind('open',[c.c_void_p,c.POINTER(c.c_void_p)],c.c_int)
        bind('close',[c.c_void_p],None)
        bind('control_transfer',[c.c_void_p,c.c_ubyte,c.c_ubyte,c.c_ushort,c.c_ushort,c.POINTER(c.c_ubyte),c.c_ushort,c.c_uint],c.c_int)
        self.context=c.c_void_p();self.check(self.lib.libusb_init(c.byref(self.context)))

    def check(self,code):
        if code<0:raise USBError(self.lib.libusb_error_name(code).decode()+' ('+str(code)+')')
        return code
    def close(self):
        if self.context:self.lib.libusb_exit(self.context);self.context=None
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def _devices(self):
        devices=c.POINTER(c.c_void_p)()
        count=self.check(self.lib.libusb_get_device_list(self.context,c.byref(devices)))
        return devices,count
    def info(self,device):
        d=Descriptor();self.check(self.lib.libusb_get_device_descriptor(device,c.byref(d)))
        ports=(c.c_ubyte*8)();n=self.lib.libusb_get_port_numbers(device,ports,8)
        return {'vid':f'{d.vendor:04x}','pid':f'{d.product:04x}',
                'bus':self.lib.libusb_get_bus_number(device),'address':self.lib.libusb_get_device_address(device),
                'ports':list(ports[:max(n,0)]),'speed_code':self.lib.libusb_get_device_speed(device),
                'usb_bcd':f'{d.usb:04x}','device_bcd':f'{d.device:04x}',
                'device_class':d.device_class,'ep0_packet_bytes':d.max_packet,'configurations':d.configs}
    def list(self):
        devices,count=self._devices()
        try:return [self.info(devices[i]) for i in range(count)]
        finally:self.lib.libusb_free_device_list(devices,1)
    def open_usbi(self,bus=None,address=None):
        devices,count=self._devices()
        try:
            found=[]
            for i in range(count):
                info=self.info(devices[i])
                if (info['vid'],info['pid'])==('0456','7031') and (bus is None or info['bus']==bus) and (address is None or info['address']==address):
                    found.append((devices[i],info))
            if len(found)!=1:raise USBError(f'Expected one programmed USBi (0456:7031); found {len(found)}. Select --bus/--device if several are connected. The app sandbox can hide USB devices.')
            handle=c.c_void_p();self.check(self.lib.libusb_open(found[0][0],c.byref(handle)))
            return USBi(self,handle,found[0][1])
        finally:self.lib.libusb_free_device_list(devices,1)

    def open_at_port(self,identities,bus,ports):
        """Open an explicitly selected physical port, including FX2 boot mode."""
        devices,count=self._devices()
        try:
            found=[]
            for i in range(count):
                info=self.info(devices[i])
                if info['bus']==bus and info['ports']==list(ports) and (info['vid'],info['pid']) in identities:
                    found.append((devices[i],info))
            if len(found)!=1:raise USBError('Expected one supported device at the selected USB bus/port path.')
            handle=c.c_void_p();self.check(self.lib.libusb_open(found[0][0],c.byref(handle)))
            return USBi(self,handle,found[0][1])
        finally:self.lib.libusb_free_device_list(devices,1)

class USBi:
    def __init__(self,owner,handle,info):
        self.owner,self.handle,self.info=owner,handle,info;self.trace=[];self.lock=threading.RLock()
        # BaseLib.USBiHWDriver.ReadData initializes clatch to one even for I2C.
        self.latch=1
    def close(self):
        if self.handle:self.owner.lib.libusb_close(self.handle);self.handle=None
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def control(self,request_type,request,value,index=0,data=b'',length=None,timeout_ms=1000):
        incoming=bool(request_type&0x80)
        if incoming:
            if length is None or data:raise ValueError('IN transfer needs only a length.')
            buffer=(c.c_ubyte*max(length,1))()
        else:
            if length is not None:raise ValueError('OUT transfer length is derived from data.')
            data=bytes(data);length=len(data);buffer=(c.c_ubyte*max(length,1))()
            if length:c.memmove(buffer,data,length)
        if not 0<=length<=4096:raise ValueError('USB transfer length outside supported range.')
        row={'request_type':request_type,'request':request,'value':value,'index':index,'length':length,
             'setup_hex':struct.pack('<BBHHH',request_type,request,value,index,length).hex()}
        if not incoming:row['data_hex']=data.hex()
        started=time.monotonic()
        code=self.owner.lib.libusb_control_transfer(self.handle,request_type,request,value,index,buffer,length,timeout_ms)
        row['returned']=code;row['duration_ms']=round((time.monotonic()-started)*1000,3)
        if incoming and code>=0:row['data_hex']=bytes(buffer[:code]).hex()
        self.trace.append(row);self.owner.check(code)
        if code!=length:raise USBError(f'Short USB transfer for request {request:02x}: {code}/{length} bytes.')
        return bytes(buffer[:code]) if incoming else code
    def poll(self,address7,read=False):
        request,busy=(0xB6,0) if read else (0xB5,2)
        for _ in range(101):
            status=self.control(0xC0,request,address7,length=1)[0]
            if status==1:return
            if status!=busy:raise USBError(f'USBi {"read" if read else "write"} status {status} at I2C address 0x{address7:02x}.')
            time.sleep(.001)
        raise USBError('USBi completion polling timed out.')
    @staticmethod
    def check_address(address7):
        if type(address7) is not int or not 0x08<=address7<=0x77:raise ValueError('Use a non-reserved 7-bit I2C address, e.g. 0x34 (SigmaStudio 0x68).')
    def read(self,address7,subaddress,words,word_bytes):
        self.check_address(address7)
        if address7 not in range(0x34,0x38):
            raise ValueError('read() uses ADAU1701 two-byte subaddresses and is restricted to 0x34..0x37. Other devices require their own address-width profile.')
        if type(words) is not int or words<1 or not 1<=word_bytes<=64 or not 0<=subaddress<=65535 or subaddress+words>65536:
            raise ValueError('Invalid read range.')
        with self.lock:
            result=bytearray();maximum=64//word_bytes
            for offset in range(0,words,maximum):
                length=min(maximum,words-offset)*word_bytes
                self.control(0x40,0xB3,address7,index=self.latch<<8,data=(subaddress+offset).to_bytes(2,'big'))
                # ADIUSBi.ReadData sleeps 1 ms before checking completion in
                # 64-byte I2C mode. Without it an old Success status can be
                # observed before this address phase has started.
                time.sleep(.001)
                self.poll(address7)
                result.extend(self.control(0xC0,0xB4,address7,index=self.latch<<8,length=length))
                self.poll(address7,read=True)
            return bytes(result)
    def write(self,address7,subaddress,data,word_bytes):
        self.check_address(address7)
        # Target RAM/control registers only. EEPROM addressing is deliberately
        # unavailable through this test transport, including address 0x50.
        if address7 not in range(0x34,0x38):raise ValueError('Writes are restricted to ADAU1701 target addresses 0x34..0x37.')
        with self.lock:
            for packet in write_chunks(address7,subaddress,data,word_bytes,latch=self.latch):
                self.control(packet.request_type,packet.request,packet.value,packet.index,packet.data)
                self.poll(address7)

def atomic_json(path,value):
    path=Path(path);temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w') as stream:
        json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['list','read','load-firmware'])
    parser.add_argument('--bus',type=int);parser.add_argument('--device',type=int)
    parser.add_argument('--address',type=lambda x:int(x,0),default=0x34)
    parser.add_argument('--register',type=lambda x:int(x,0),default=0x81c)
    parser.add_argument('--words',type=int,default=1);parser.add_argument('--word-bytes',type=int,default=2)
    parser.add_argument('--trace',type=Path)
    parser.add_argument('--firmware',type=Path,help='Locally installed ADI_USBi.spt for FX2 RAM startup')
    parser.add_argument('--ports',help='Explicit USB port path from list, e.g. 1.2.3')
    args=parser.parse_args()
    with LibUSB() as lib:
        if args.command=='list':print(json.dumps(lib.list(),indent=2));return
        if args.command=='load-firmware':
            if args.firmware is None or args.bus is None or not args.ports:
                parser.error('load-firmware requires --firmware, --bus and --ports to select the confirmed board explicitly.')
            from fx2_loader import load_firmware
            try:
                ports=[int(p) for p in args.ports.split('.')]
                report=load_firmware(lib,args.firmware.read_bytes(),args.bus,ports)
                print(json.dumps(report,indent=2))
                if args.trace:atomic_json(args.trace,report)
            except (USBError,ValueError,OSError) as exc:parser.exit(1,str(exc)+'\n')
            return
        with lib.open_usbi(args.bus,args.device) as usbi:
            try:
                data=usbi.read(args.address,args.register,args.words,args.word_bytes)
                print(json.dumps({'device':usbi.info,'address7':hex(args.address),'register':hex(args.register),'data_hex':data.hex()},indent=2))
            except USBError as exc:parser.exit(1,str(exc)+'\n')
            finally:
                if args.trace:atomic_json(args.trace,usbi.trace)

if __name__=='__main__':main()
