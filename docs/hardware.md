# ICP3 and ADAU1701 hardware findings

Tested 21 November 2026 on native macOS arm64 with a WONDOM ICP3 and WONDOM
AA-AP23123 / ADSP1701-2.4U preamp (product 800). This is one tested combination.

| Operation | Result |
|---|---|
| Native libusb enumeration/open | `0456:7031` |
| DSP I²C core reads | Eight consecutive `001C` values at 7-bit address `0x34` |
| RAM backup | Program 5,120 bytes and parameters 4,096 bytes, each read twice identically |
| RAM write/read-back | Complete diagnostic images matched |
| Arithmetic | Expected positive/negative multiply, add and subtract results |
| Live safeload | Updated coefficient and running interface results matched |
| Compiled graph | Three DC cases through gain, three PEQ sections, first-order low-pass and delay |
| Restoration | Original RAM, interface registers and configuration verified; core `001C` |

Gain output was exact; the largest downstream compiled-graph error was one 5.23
step (`2^-23`). Each graph case used 130 instructions, 23 parameters and 51 data
words. The input was replaced with an internal DC stimulus and four DAC writes
were redirected to host interface registers; the DSP gain/filter/delay code was
unchanged. Audio converters stayed muted during tests. Analog I/O, frequency
response and actual delay timing were not measured. Transient DSP history is
reset during RAM replacement. No target/programmer EEPROM was written.

A physical ICP3 reset exposed boot identity `04B4:8613`. A compatible locally
installed two-stage SPT was downloaded only to volatile FX2 RAM. Stage one
retained `04B4:8613`; stage two enumerated `0456:7031`. The loader checks the known
SPT hash and requires an explicit physical USB bus/port path.

The working sequence was ICP3 startup in PROGRAM with the six-pin target cable
detached, then connecting the powered preamp. Earlier status-3/status-4 failures
persisted through a USB reset. Connecting in this order restored communication.
The preamp's front switches control mute/phase; the APM2 RUN-switch guidance does
not apply to this model. No cable rewiring was needed.

Native transport uses `wIndex=0x0100` for I²C data/address requests, one millisecond
after B3 address setup before polling, and index zero for status requests. Read
and write chunks respect complete DSP words. Negative host-interface results
are sign-extended to 32 bits. Interface 0–7 corresponds to instruction data
addresses 8144–8151 with destination zero.

Linux uses the same portable backend, but physical Linux USB operation has not
been tested. Other clones, SPI and EEPROM self-boot are not established. The
command-line tools are separate from the editor's UI. Backups and raw traces
are local test artifacts and are intentionally absent from this repository.

See [USBi tools](../tools/usbi/README.md), the
[WONDOM ICP3 guide](https://store.sure-electronics.com/upload/download/1/WONDOM%20ICP3%20User%20Guide522.pdf),
[preamp manual](https://files.sure-electronics.com/download/ADSP1701-2.4U_USER_MANUAL.pdf),
[ADAU1701 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/ADAU1701.pdf)
and [ADI safeload guide](https://ez.analog.com/dsp/sigmadsp/a/documents/c/adau1701-faq/DO26286/implementing-safeload-writes-on-the-adau1701).
