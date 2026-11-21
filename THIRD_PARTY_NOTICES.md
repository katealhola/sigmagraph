# Third-party notices

SigmaGraph's independently written source code is licensed under
GPL-3.0-or-later. See [LICENSE](LICENSE). This license does not change the licenses
of dependencies or vendor material supplied separately by a user.

- **PySide6 / Shiboken / Qt**: Qt for Python and Qt are provided under their
  upstream open source licenses, including LGPLv3 and GPLv3. The LGPLv3 and GPLv3
  texts are in `LICENSES/`. Upstream source and notices:
  https://code.qt.io/cgit/pyside/pyside-setup.git/ and
  https://code.qt.io/cgit/qt/qtbase.git/ .
- **PyInstaller**: build tool under GPLv2-or-later with its distribution exception;
  the exception permits distribution of generated applications under their own
  license. https://pyinstaller.org/en/stable/license.html .
- Python and other libraries bundled by PyInstaller retain their own licenses.
  The packaging step includes license/notice files exposed by installed runtime
  distribution metadata, plus Python's license.

The toolbox JSON records interoperable algorithm identifiers, pin counts,
category names and preset values extracted from a local SigmaStudio
installation. [docs/toolbox.md](docs/toolbox.md) records the provenance. Drawings
are independently implemented Qt vector graphics; vendor artwork is not bundled.

No Analog Devices DLLs, SigmaStudio executables, USBi firmware, proprietary
example project corpus, or device RAM backup is included. The optional ICP3 RAM
loader requires the user's locally installed, hash-checked `ADI_USBi.spt`.

SigmaStudio, SigmaDSP and ADAU1701 are Analog Devices names. This project is an
independent implementation and is not affiliated with Analog Devices or WONDOM.
