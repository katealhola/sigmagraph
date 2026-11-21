# SigmaGraph 0.3

A native SigmaDSP graph editor for macOS and Linux. Import SigmaStudio projects, edit and save graphs, compile supported ADAU1701 designs, and analyze frequency response without Wine or SigmaStudio running.

## Run

Download the matching architecture from a successful GitHub Actions run. See [building.md](building.md) for the four native targets.

From source on Linux or macOS:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python run.py /path/to/project.dspproj
```

Python 3.10 or newer is required. Linux needs the usual desktop X11/Wayland and OpenGL libraries. CI builds and smoke-tests both Linux architectures on native Ubuntu 24.04 runners.

## Save projects

Use **Save** / Cmd+S / Ctrl+S or **File → Save project as…**. Native projects use `.sgproj`, a versioned, data-only JSON format. Reopen them with **Open project…**, drag onto the canvas, or pass their path on the command line.

Saves retain block identities, ports, connections, positions, sample rates, edited settings, unknown imported settings, and the original parsed serialization graph. Writes use a temporary file and atomic replacement. Saving marks the undo history clean; subsequent edits and undo/redo update the modified indicator. Closing or replacing an edited document offers Save, Discard, and Cancel.

SigmaStudio `.dspproj` remains an import format. Native `.sgproj` files cannot be opened by SigmaStudio. The application does not write back an edited BinaryFormatter `.dspproj` or modify the original input file.

## Compile for ADAU1701

Click **Compile DSP** or choose **DSP → Compile for ADAU1701…**. The graph is validated before asking for the parent output folder. A new, timestamped build directory contains:

| File | Content |
|---|---|
| `program.bin` | 1,024 five-byte instructions, starting at DSP control-port word address `0x0400` |
| `parameters.bin` | 1,024 four-byte parameter words, starting at `0x0000` |
| `dsp.h` | C arrays containing both RAM images |
| `program.asm` | Allocated assembly before trailing NOP padding |
| `parameters.json` | Parameter names, addresses, encoding, values and exact bytes |
| `memory.json` | Data RAM allocation map |
| `manifest.json` | Resources, image addresses, checksums, integration steps and limitations |

The compiler is independent Python code. It performs topological scheduling, signal/history and delay allocation, parameter allocation, 5.23 quantization, instruction encoding, conservative pipeline spacing, and resource checks. It does not invoke installed ADI assemblies. Filters use double-precision feedback state.

Supported configurations:

| Block | Scope |
|---|---|
| Audio input | One `ICSigma100In`, contiguous ADC 0 and optionally ADC 1 |
| Audio output | `ICSigma100Out`, unique DAC0–3 or DIG0–7 destinations |
| Volume | `SWGain1940DBAlg`, matching audio channels, RC slew |
| Parametric EQ | `PEQ1Chan`, peaking bands (type 0), per-band bypass |
| General filter | `NthOrderDouble`, Butterworth order 2 or 4, low-pass or high-pass, without phase shift |
| First-order filter | `FistOrderSingle`, one low-pass section |
| General biquad | `EQ1940SingleS`, standard high-pass, Type 2 / GeneralType 1, gain 0 dB, without phase shift |
| Crossover | `CrossoverFilter2WayAlgDP`, recovered Type1…4 = 1,1,1,0 configuration, Gain1/2 = 0 dB; low/high inversion and Gain3 supported |
| Delay | `MultCtrlDel1940Alg`, mono integer samples; allocation fixed at compile time |
| Arithmetic | `AdderAlg`, `SubAlg`, `EQ1940Invert` |

Use one consistent rate, 44,100 or 48,000 Hz. Unsupported algorithms/configurations, unconnected inputs, feedback cycles, incompatible rates and exhausted RAM produce diagnostics. Other toolbox entries remain available for graph editing and saving; their presence in the catalog does not imply compiler support.

**The compiler is experimental.** A later [ICP3 hardware test](hardware.md) verified an instrumented gain/EQ/low-pass/delay graph at DC on a physical ADAU1701; analog I/O, frequency response, delay timing and other blocks remain unverified. It exports RAM images, not a complete board configuration, USBi download, or EEPROM self-boot image. Configure the board's clock, serial I/O, DACs and GPIO separately, stop/reset the core and clear its state, load the images, then start execution. The build manifest records these integration requirements. Runtime changes that increase a delay require recompilation.

The compiler also runs without Qt:

```sh
python -m sigmagraph.compiler /path/to/project.sgproj -o /path/to/new-build
```

## Frequency simulation

Click **Simulate** or choose **DSP → Simulate frequency response…**. Selecting a block first makes it the initial probe. The canvas context menu also offers **Probe selected block…**.

- Choose a stimulus output port and a probe output or hardware sink input.
- Inject a unit response at the stimulus; other independent sources are zero.
- Plot cascaded and summed paths, including complex phase and integer delay.
- Change block settings in the editor while the response window remains open; plots update automatically.
- Set the frequency range, optionally quantize coefficients to 5.23, and hover for values.
- Export frequency, magnitude, unwrapped phase, real and imaginary values to CSV.

This is linear, steady-state analysis. Volume uses its settled gain. It does not emulate nonlinear blocks, clipping, sample audio, RC startup transients or the DSP's complete bit/pipeline behavior. Unsupported paths produce a diagnostic. It shares the supported filter models with the compiler and the block previews.

ADI's [Stimulus/Probe tutorial](https://wiki.analog.com/resources/tools-software/sigmastudio/tutorials/probeandstimulusblocks) describes frequency-response probing; its [capability notes](https://ez.analog.com/dsp/sigmadsp/a/documents/DO26409/stimulus-probe-capability-and-limitations) explain that this is not bit-accurate DSP simulation.

## Graph editing and toolbox

The independent library contains 288 non-obsolete Sigma100 algorithm definitions and eight quick-start presets. Search by block, category, operation or class; double-click or drag to add. Specialized vector drawings appear inside blocks. Forty presets came from installed example projects. See [toolbox.md](toolbox.md) for catalog provenance.

Drag ports to connect, replace occupied inputs, move/select/delete/duplicate blocks, and undo/redo edits. Space+drag or middle-drag pans; the wheel zooms; F fits the graph. **Arrange** lays out the graph; **View → Restore imported positions** restores source coordinates. Grow/reduce blocks with repeater metadata through the Inspector. Unknown scalar settings remain available under Stored settings.

The importer flattens nested board cells. Existing probes, stimuli and T-routing helpers are collapsed into their signal connections. Algorithm rates take precedence over the document's default rate. Imported schematics remain editable when the compiler cannot yet handle their algorithms.

## Build on Linux or macOS

Build on the target OS and architecture:

```sh
python -m pip install -r requirements-build.txt
python build.py --output dist
```

macOS produces `dist/SigmaGraph.app`; Linux produces `dist/SigmaGraph/SigmaGraph` with supporting files in that directory. Use an Intel Python/Qt installation for Intel Mac builds. The build includes the catalog JSON and native document associations. See the official [Qt installation](https://doc.qt.io/qtforpython-6/gettingstarted.html) and [deployment](https://doc.qt.io/qtforpython-6/deployment/index.html) documentation.

## Validation

```sh
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

Tests cover importing the original files and all 19 installed examples, graph editing and wiring, undo/redo, catalog growth, lossless native round trips and failed-save preservation, GUI saving/reopening, build export, live simulation and CSV export, instruction byte vectors, gain slew, sample delay and filter response.

The reference checks compare all 254 parameter values against the StereoPA SigmaStudio export after matching its two high-pass frequencies. A test-only functional instruction interpreter compares the generated stereo program with the original SigmaStudio program on the same input signals. All 32 FaneImperiumSub04 parameter values also match its export. These are software checks, not physical hardware validation.

`StereoPA2tie011` and `FaneImperiumSub04` compile within all three ADAU1701 memory budgets. `FaneImperiumSub` uses a crossover configuration still outside the supported subset; `FaneImperiumSub02` additionally contains mixed algorithm sample rates. Those cases are reported explicitly.
