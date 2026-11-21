# Reverse-engineering utilities

Independent data-only NRBF parsing, graph/export analysis, ADAU1701 assembly and
coefficient tools. No vendor binaries or user project corpus is distributed.
The production importer/codec/compiler live in the top-level `sigmagraph/` package.

```sh
python tools/reverse_engineering/nrbf.py /path/to/project.dspproj -o local/objects.json
python tools/reverse_engineering/analyze.py /path/to/corpus -o local/analysis
python tools/reverse_engineering/asm1701.py disassemble /path/to/program.bin -o local/program.asm
```

`verify.py` reproduces the original research checks only with the specifically
named local project/export corpus described in its source. These are research
utilities rather than a general graph compiler.

Static .NET metadata/IL inspection is optional:

```sh
python -m pip install -r tools/reverse_engineering/requirements.txt
python tools/reverse_engineering/inspect_il.py --help
python tools/extract_catalog.py /path/to/ADICtrls.dll -o local/catalog.json
```

The utilities inspect local files without loading the vendor runtime. Do not
commit DLLs, SPT firmware, proprietary samples or extracted user data. See
[format notes](../../docs/formats.md) and [toolbox provenance](../../docs/toolbox.md).
