# Native USBi and ICP3 tools

Portable Python ctypes/libusb transport for classic USBi protocol, tested with
one WONDOM ICP3 on macOS. See [hardware findings](../../docs/hardware.md) for the
exact scope. Linux needs `libusb-1.0-0` and device permissions; macOS can use
`brew install libusb`. The graph editor does not yet expose USB programming.

Run from the repository root. Listing and reading do not replace DSP RAM:

```sh
python tools/usbi/usb_transport.py list
python tools/usbi/usb_transport.py read --address 0x34 --register 0x081c --word-bytes 2
python tools/usbi/backup_target.py --output local/my-backup
```

The backup reads program/parameters twice and requires stable registers. It
publishes a verified backup only when both complete reads match. Use a new output
directory. Keep backups under the ignored `local/` directory.

If the confirmed ICP3 enumerates in FX2 boot mode, use its bus and port path from
`list` and your locally installed firmware (not supplied here):

```sh
python tools/usbi/usb_transport.py load-firmware \
  --firmware '/path/to/ADI_USBi.spt' --bus 0 --ports 1.2.3 --trace local/startup.json
```

Only SPT SHA-256
`d173637d868aee207c0e91b644f5b902a1509cedb2df39b519c96c2dee6db2fb`
is accepted. The loader writes only volatile programmer RAM, preserves the two
firmware stages, and does not require an intermediate re-enumeration. It is not
an arbitrary FX2 board programmer. It refuses to reflash a running USBi.

## Manual hardware diagnostics

These commands **temporarily replace DSP RAM** and mute the converters. They
require the fresh verified backup above and attempt full verified restoration
in `finally`, including on SIGINT/SIGTERM. USB disconnection or process termination
can prevent restoration; reconnect and use recovery if required. No hardware
command is run by GitHub Actions or the default test suite.

```sh
python tools/usbi/hardware_test.py --backup local/my-backup --output local/arithmetic-test
python tools/usbi/hardware_test.py --compiler-test --backup local/my-backup --output local/compiler-test
python tools/usbi/hardware_test.py --restore-only --backup local/my-backup --output local/arithmetic-test
```

Recovery requires the existing test directory's original 32-byte interface
snapshot. Tests check RAM hashes before starting and restore program/parameter
RAM before re-enabling the original core/audio state. GPIO configuration and
EEPROM writes are outside these tests. Internal filter/delay history is reset.

The compiler probe requires the repository's `sigmagraph` package but does not
require Qt. Test outputs include editable native projects, raw instrumented
binaries and USB traces. Run offline transport tests with
`python -m unittest discover -s tools/usbi -p 'test_*.py'`.

## Protocol

- Endpoint 0 vendor control: `B2` write, `B3` read-address setup, `B4` read data,
  `B5` write status, `B6` read status. Success status is 1; polling is bounded.
- `wValue` is the 7-bit I²C address; ADAU1701 `0x34` is SigmaStudio's `0x68`.
- Data/address `wIndex=0x0100`; status index zero. B3 setup includes a 1 ms wait.
- Maximum write payload is 64 bytes including a two-byte subaddress. Program
  words are five bytes; parameter words four. Address advancement is in words.
- DSP writes are restricted to ADAU1701 addresses 0x34–0x37. Generic EEPROM reads
  need a separate subaddress-width profile; these tools do not program EEPROM.
- Legacy B7 reset was accepted in diagnostics. BA reset-level control stalled on
  this firmware and is not used. B8 power control was not tested.

For Linux desktop access an administrator can install a udev rule for runtime
`0456:7031`, for example:

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="0456", ATTR{idProduct}=="7031", TAG+="uaccess"
```

Boot identities need their own explicitly scoped permissions. `04B4:8613` is
shared by unrelated Cypress devices; identify the physical programmer first.
