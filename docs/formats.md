# Recovered formats and compiler boundaries

## Projects

SigmaStudio `.dspproj` files in the original corpus are .NET BinaryFormatter
MS-NRBF streams. `sigmagraph/nrbf.py` parses records as data without loading
assemblies or instantiating CLR types. It retains object identities, schemas,
references and unrecognized fields. `project_import.py` recovers cells, pins,
settings and connectivity; `model.py` maps them to the editable graph.

Nested board cells are flattened. Existing stimulus/probe and routing helpers
are collapsed into signal connections. Algorithm sample rates take precedence
over document defaults. Truncated or unresolved data is rejected.

Native `.sgproj` files use versioned JSON. They retain graph IDs, settings and
unknown imported data, and are written using atomic replacement. They are not
BinaryFormatter files and cannot be opened in SigmaStudio.

## ADAU1701 images

| Memory | Control-port word address | Word size | Capacity |
|---|---|---|---|
| Program RAM | `0x0400` | 5 bytes | 1,024 instructions |
| Parameter RAM | `0x0000` | 4 bytes | 1,024 words |

Program instructions are 40 bits. The independent codec represents data and
coefficient addresses, register destination, mux, offset flags, arithmetic and
conditional fields. Parameters normally use signed 5.23 values in 28 bits;
integer controls such as delays have algorithm-specific encoding. Memory
addresses advance in words, not transfer bytes. A raw RAM image is not a target
EEPROM self-boot image.

The compiler performs topological scheduling and explicit parameter/data/history
allocation, emits conservative pipeline spacing, and pads unused program memory
with NOPs. Filter state uses double-precision feedback. Unknown configurations
produce diagnostics instead of guessed firmware.

The original offline research reassembled a 5,120-byte vendor program exactly,
matched 254 named stereo parameters and 32 subwoofer parameters, and compared
reference/generated execution through an independent functional interpreter.
Those reference files remain local. The repository includes portable instruction
vectors, generated examples and numerical checks. Hardware execution at DC has
the narrower scope documented in [hardware.md](hardware.md).
