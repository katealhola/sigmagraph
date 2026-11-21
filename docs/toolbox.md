# Toolbox provenance and implementation scope

The 0.3 catalog contains 288 algorithm types discovered in the installed `ADICtrls.dll` that directly implement `ADICtrls.IDspSigma100`, have friendly-name and pin metadata, and are not marked obsolete. It is not generated from the current project's block instances.

Source assembly SHA-256:

```text
32f63690f5f88ef3a8d58780154ed27ae7fc9a5455928df57f8e91374c0def7a
```

The extraction reads metadata only. `RequiredAlgIntfAttribute` associates algorithms with cell categories; `TreeToolBoxAtt` supplies subcategory paths; `PinsAttribute`, `PinNameAtt`, and `RepeaterAttribute` supply pin names and growth rules. Empty pin-name placeholders are not counted as real input pins. Presets from 40 types in the example corpus improve dynamic layouts and stored defaults where available.

| Category | Definitions |
|---|---:|
| Dynamics Processors | 66 |
| Filters | 42 |
| Basic DSP | 41 |
| Sources | 33 |
| Muxes/Demuxes | 18 |
| GPIO Conditioning | 16 |
| Level Detectors/Lookup Tables | 16 |
| Mixers/Splitters | 15 |
| ADI Algorithms | 14 |
| IO | 7 |
| Counters | 5 |
| Volume Controls | 5 |
| Other algorithms | 4 |
| Advanced DSP | 3 |
| Non Linear Processors | 3 |

The eight quick-start presets are additional convenience variants. The library therefore reports 296 entries. It can be searched by label, class, category or path. Imported algorithms outside this catalog still retain their settings and ports, but do not imply compilation support.

The catalog covers the installed core assembly's Sigma100 types. It does not claim every algorithm across all SigmaStudio processor families or separately licensed plugins. ADI's [toolbox documentation](https://wiki.analog.com/resources/tools-software/sigmastudio/toolbox) distinguishes processor-specific availability.

The functional drawings were implemented as scalable Qt vector schematics, informed by the operation descriptions in ADI's [Basic DSP](https://wiki.analog.com/resources/tools-software/sigmastudio/toolbox/basicdsp), [Sources](https://wiki.analog.com/resources/tools-software/sigmastudio/toolbox/sources), and [Mixers/Splitters](https://wiki.analog.com/resources/tools-software/sigmastudio/toolbox/mixerssplitters) sections. The [tutorials and examples](https://wiki.analog.com/resources/tools-software/sigmastudio/tutorials) and the locally installed sample projects were used to check representative signal flows.

The drawings show block functions. Only explicitly recognized filter configurations have calculated response curves. Generic `H(z)` symbols, oscillator waveforms, compressors and other symbols are illustrative; the app is not a realtime DSP simulator. Some complex algorithms use a general `f(x)` transfer-function symbol until a dedicated drawing is added.

Creating a block from catalog metadata establishes its editor identity, ports and settings; it does not establish a valid firmware implementation. Version 0.3 saves all catalog blocks in native .sgproj projects and compiles a verified subset. See README.md for the supported configurations and simulation scope.
