# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline USBi packet planner and inspector. Never opens a USB device.

Recovered from installed SigmaStudio 4.5 ADIUSBi.dll and CyUSB.dll by static IL
inspection. This is a protocol research aid, not a hardware-tested programmer.
Only the observed 32-byte CSPT record layout is supported by inspect_spt().
"""
from dataclasses import dataclass
from pathlib import Path
import argparse
import hashlib
import json
import struct

COMMANDS={'write':0xB2,'address_for_read':0xB3,'read':0xB4,
          'write_status':0xB5,'read_status':0xB6,'reset_target':0xB7,
          'target_power':0xB8,'led':0xB9,'reset_level':0xBA}
STATUS={0:'None',1:'Success',2:'Writing',3:'Failed',4:'Error',5:'Exception'}
PROGRAMMED_ID=(0x0456,0x7031)

@dataclass(frozen=True)
class Transfer:
    operation: str
    request_type: int
    request: int
    value: int
    index: int=0
    data: bytes=b''
    read_length: int=0

    @property
    def setup(self):
        length=self.read_length if self.request_type&0x80 else len(self.data)
        return struct.pack('<BBHHH',self.request_type,self.request,self.value,self.index,length)

    def record(self):
        return {'operation':self.operation,'setup_hex':self.setup.hex(),
                'data_hex':self.data.hex(),'read_length':self.read_length}

def bus_fields(address7,spi=False,latch=0):
    # Public API uses 7-bit addresses. The Windows API takes an 8-bit address
    # and shifts it right once before placing it in wValue.
    if type(address7) is not int or not 0<=address7<=0x7f:
        raise ValueError('Expected a 7-bit chip address; SigmaStudio 0x68 is 0x34 here.')
    if type(latch) is not int or not 0<=latch<=255:raise ValueError('Latch must fit one byte.')
    return address7,(latch<<8)|int(bool(spi))

def status_request(address7,read=False):
    address,_=bus_fields(address7)
    name='read_status' if read else 'write_status'
    return Transfer(name,0xC0,COMMANDS[name],address,read_length=1)

def write_chunks(address7,subaddress,data,word_bytes,limit=64,spi=False,latch=0,byte_addressed=False):
    """Two-byte subaddresses; DSP word addressing or EEPROM byte addressing.

    This only plans protocol transfers. EEPROM page boundaries and write-cycle
    waits must be handled separately. SPI is encoded but not hardware-tested.
    """
    address,index=bus_fields(address7,spi,latch)
    data=bytes(data)
    if type(word_bytes) is not int or word_bytes<=0 or len(data)%word_bytes:
        raise ValueError('Data must contain complete words.')
    if type(limit) is not int or not 2+word_bytes<=limit<=4096:
        raise ValueError('Transfer limit cannot hold a subaddress and one word.')
    if type(subaddress) is not int or not 0<=subaddress<=65535:raise ValueError('Invalid subaddress.')
    increment=len(data) if byte_addressed else len(data)//word_bytes
    if subaddress+increment>65536:raise ValueError('Transfer wraps the 16-bit subaddress.')
    size=(limit-2)//word_bytes*word_bytes
    result=[]
    for at in range(0,len(data),size):
        offset=at if byte_addressed else at//word_bytes
        payload=(subaddress+offset).to_bytes(2,'big')+data[at:at+size]
        result.append(Transfer('write',0x40,COMMANDS['write'],address,index,payload))
    return result

def read_chunk(address7,subaddress,length,spi=False,latch=0):
    address,index=bus_fields(address7,spi,latch)
    if type(length) is not int or not 1<=length<=(4096 if spi else 64):raise ValueError('Invalid read length.')
    if type(subaddress) is not int or not 0<=subaddress<=65535:raise ValueError('Invalid subaddress.')
    return [Transfer('address_for_read',0x40,COMMANDS['address_for_read'],address,index,subaddress.to_bytes(2,'big')),
            status_request(address7),
            Transfer('read',0xC0,COMMANDS['read'],address,index,read_length=length),
            status_request(address7,read=True)]

def inspect_spt(data):
    """Summarize locally supplied firmware without exporting or loading it."""
    data=bytes(data);offset=0;records=[];images=[];image=None
    while offset<len(data):
        if len(data)-offset<32:raise ValueError('Truncated CSPT header.')
        header=data[offset:offset+32]
        magic,total,size=struct.unpack_from('<4sII',header)
        length=struct.unpack_from('<I',header,28)[0]
        if magic!=b'CSPT' or size!=32 or total!=size+length or offset+total>len(data):
            raise ValueError('Unsupported or malformed CSPT record.')
        request_type,request=header[15],header[16]
        value,index=struct.unpack_from('<HH',header,18)
        payload=data[offset+32:offset+total]
        if request_type!=0x40 or request!=0xA0 or index!=0:
            raise ValueError('This inspector only supports the observed FX2 RAM-write script.')
        row={'record':len(records),'offset':offset,'request_type':request_type,'request':request,
             'value':value,'index':index,'bytes':length}
        if value==0xE600:
            if payload not in (b'\0',b'\1'):raise ValueError('Unknown CPUCS payload.')
            row['cpu_reset']=payload[0]
            if payload==b'\1':
                if image is not None:raise ValueError('Nested firmware reset sequence.')
                image={'first_record':len(records),'memory':{},'write_records':0,'data_bytes':0}
            elif image is not None:
                memory=image.pop('memory');blob=bytes(memory.get(i,255) for i in range(max(memory,default=-1)+1))
                image['last_record']=len(records);image['descriptors']=[]
                image['reconstructed_image_sha256']=hashlib.sha256(blob).hexdigest()
                image['gap_fill']=255
                for i in range(max(0,len(blob)-17)):
                    if blob[i:i+2]==b'\x12\x01' and blob[i+7] in (8,16,32,64):
                        vendor,product=struct.unpack_from('<HH',blob,i+8)
                        image['descriptors'].append({'ram_address':i,'vid':f'{vendor:04x}','pid':f'{product:04x}'})
                images.append(image);image=None
        else:
            if image is None:raise ValueError('RAM write outside a reset sequence.')
            if value+length>65536:raise ValueError('RAM write wraps address space.')
            image['write_records']+=1;image['data_bytes']+=length
            for i,byte in enumerate(payload):image['memory'][value+i]=byte
        records.append(row);offset+=total
    if image is not None:raise ValueError('Firmware script leaves CPU in reset.')
    return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'record_count':len(records),'firmware_images':images,'records':records}

def plan_images(directory,address7=0x34):
    """RAM writes only: no power, reset, register configuration or core start."""
    directory=Path(directory)
    program=(directory/'program.bin').read_bytes();parameters=(directory/'parameters.bin').read_bytes()
    if (len(program),len(parameters))!=(5120,4096):raise ValueError('Expected full ADAU1701 RAM images.')
    result=[]
    for start,data,width in [(0x400,program,5),(0,parameters,4)]:
        for transfer in write_chunks(address7,start,data,width):
            result.extend([transfer,status_request(address7)])
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--inspect-firmware',type=Path)
    group.add_argument('--plan-build',type=Path)
    ap.add_argument('--address',type=lambda s:int(s,0),default=0x34,help='7-bit target address, default 0x34')
    ap.add_argument('-o','--output',type=Path)
    args=ap.parse_args()
    if args.inspect_firmware:result=inspect_spt(args.inspect_firmware.read_bytes())
    else:
        transfers=plan_images(args.plan_build,args.address)
        result={'hardware_tested':False,'offline_only':True,
                'scope':'RAM writes only. Configure/reset DSP separately; poll each status until success.',
                'write_status_poll':{'success':1,'busy':2,'maximum_tries_in_vendor_host':101,'sleep_ms':1},
                'read_status_poll':{'success':1,'busy':0,'maximum_tries_in_vendor_host':101,'sleep_ms':1},
                'transfers':[t.record() for t in transfers]}
    text=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.write_text(text)
    else:print(text,end='')

if __name__=='__main__':main()
