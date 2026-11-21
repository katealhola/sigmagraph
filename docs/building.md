# Building and continuous integration

Build on the target OS and architecture with Python 3.10+ (CI uses 3.13):

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[build]'
python scripts/run_tests.py
python scripts/build_app.py --output dist
```

On Debian/Ubuntu install the libraries needed by Qt and PyInstaller:

```sh
sudo apt-get update
sudo apt-get install -y libegl1 libgl1 libopengl0 libxkbcommon0 libdbus-1-3 \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
  libxcb-xinerama0 libxcb-xkb1 libxkbcommon-x11-0 libusb-1.0-0 binutils
```

macOS outputs `dist/SigmaGraph.app`; Linux outputs the entire
`dist/SigmaGraph/` directory. Keep Linux supporting files beside the executable.
PyInstaller builds for the current Python architecture. An Intel Mac needs an
Intel Python, even if building on Apple Silicon using a translated environment.
CI instead uses native Intel and ARM64 runners.

Smoke-test the packaged GUI without user interaction:

```sh
# macOS
QT_QPA_PLATFORM=offscreen dist/SigmaGraph.app/Contents/MacOS/SigmaGraph --smoke-test
# Linux
QT_QPA_PLATFORM=offscreen dist/SigmaGraph/SigmaGraph --smoke-test
```

`python scripts/package_release.py` checks the native executable architecture,
archives the complete application, and writes a SHA-256 checksum plus a build
manifest into `artifacts/`. It uses `ditto` ZIP on macOS to preserve the app bundle
and executable permissions, and `.tar.gz` on Linux. GPL text, third-party notices
and available dependency licenses are included in the application distribution.

## GitHub Actions

`.github/workflows/build.yml` has four independent native jobs:

- `macos-15-intel` → `macos-x86_64`.
- `macos-15` → `macos-arm64`.
- `ubuntu-24.04` → `linux-x86_64`.
- `ubuntu-24.04-arm` → `linux-arm64`.

Each checks the interpreter architecture, installs pinned Qt/PyInstaller
versions, runs offline tests, freezes the application, smoke-tests the frozen
GUI, checks the archive architecture, and uploads a uniquely named artifact.
A separate job builds a Python wheel and source distribution and verifies that
they include the GPL license and toolbox data.

Pushes to `main`, `v*` tags, pull requests and manual dispatch trigger the workflow.
The workflow has read-only repository permissions and never accesses physical
USB hardware or deploys releases. Standard runners are used; no self-hosted
machines or repository secrets are required. Artifacts are retained for 30 days.

These packages do not provide universal Linux compatibility: the Qt wheel and
runner determine the minimum glibc. macOS bundles are ad-hoc signed and not
notarized. Apple developer signing/notarization can be added separately.

Runner labels are based on [GitHub's runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
Packaging uses [PyInstaller](https://pyinstaller.org/en/stable/usage.html).
