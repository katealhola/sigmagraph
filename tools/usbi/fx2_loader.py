# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit, RAM-only bootstrap for the hardware-tested ICP3 firmware profile.

No firmware is bundled. Only the inspected SigmaStudio SPT is accepted. A failed
download never resumes partially loaded code; unplug/replug recovers boot mode.
"""
from __future__ import annotations
import hashlib
import struct
import time
from usbi_protocol import inspect_spt

FIRMWARE_SHA256='d173637d868aee207c0e91b644f5b902a1509cedb2df39b519c96c2dee6db2fb'
BOOT_IDS=(('04b4','8613'),('0456','7030'))
LOADER_IDS=BOOT_IDS+(('04b4','1004'),)
RUNTIME_IDS=(('0456','7031'),)

def checked_firmware(data):
    data=bytes(data)
    if hashlib.sha256(data).hexdigest()!=FIRMWARE_SHA256:
        raise ValueError('Firmware does not match the inspected, hardware-tested SPT profile. No firmware bytes were sent.')
    info=inspect_spt(data)
    if info['record_count']!=98 or len(info['firmware_images'])!=2:raise ValueError('Unexpected firmware sequence.')
    for row in info['records']:
        if row['value']!=0xe600 and row['value']+row['bytes']>0x4000:
            raise ValueError('Firmware would address non-RAM storage.')
    return data,info

def load_firmware(lib,data,bus,ports,timeout=8):
    """Bootstrap a confirmed ICP3 at the explicit physical USB bus/port path.

    The first image does NOT have to re-enumerate as 04b4:1004. The observed
    ICP3 retains 04b4:8613 until the second image finishes; requiring the
    intermediate descriptor identity prevents a valid two-stage download.
    """
    from usb_transport import USBError
    data,info=checked_firmware(data)
    if type(bus) is not int or bus<0 or not ports or any(type(p) is not int or not 1<=p<=255 for p in ports):
        raise ValueError('Select an explicit physical USB bus and nonempty port path.')
    def wait_for(identities):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            found=[d for d in lib.list() if d['bus']==bus and d['ports']==list(ports) and (d['vid'],d['pid']) in identities]
            if len(found)==1:return found[0]
            time.sleep(.1)
        raise USBError('Firmware re-enumeration timed out. Reconnect the ICP3 to recover its boot state.')
    report={'firmware_sha256':info['sha256'],'physical_bus':bus,'physical_ports':list(ports),
            'storage':'programmer volatile RAM','eeprom_writes':False,'stages':[]}
    for i,image in enumerate(info['firmware_images']):
        identities=BOOT_IDS if i==0 else LOADER_IDS
        stage={'stage':i+1,'records_completed':0};report['stages'].append(stage)
        with lib.open_at_port(identities,bus,ports) as usb:
            stage['device_before']=usb.info
            for row in info['records'][image['first_record']:image['last_record']+1]:
                offset=row['offset'];total,header=struct.unpack_from('<II',data,offset+4)
                payload=data[offset+header:offset+total]
                try:usb.control(0x40,0xa0,row['value'],0,data=payload,timeout_ms=2000)
                except USBError as exc:
                    # CPU release can detach before the USB status completes.
                    # Only final re-enumeration can establish its success.
                    if row.get('cpu_reset')==0:stage['release_usb_result']=str(exc)
                    else:raise USBError('RAM download failed. Code was not resumed; reconnect the ICP3 to recover boot mode. '+str(exc)) from exc
                stage['records_completed']+=1
        time.sleep(.25)
        stage['device_after']=wait_for(LOADER_IDS if i==0 else RUNTIME_IDS)
    report['success']=True
    return report
