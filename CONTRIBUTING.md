# Contributing

Use Python 3.10+ and install the project in a virtual environment:

```sh
python -m pip install -e '.[build]'
python scripts/run_tests.py
```

The default suite is portable and uses Qt's offscreen platform. It never opens
USB devices or writes DSP hardware. CI runs it before building each platform,
then runs the frozen app with `--smoke-test`.

Optional reference checks use files you supply locally. Set
`SIGMAGRAPH_REFERENCE_DIR` to your `.dspproj`/export corpus,
`SIGMAGRAPH_ANALYSIS_DIR` to its reconstructed analysis directory, and
`SIGMAGRAPH_SIGMASTUDIO_EXAMPLES` to your installed example projects. Without
these, the six private-corpus checks skip explicitly. Do not commit the corpora,
firmware, secrets or hardware backups. Use the ignored `local/` directory.

For new DSP blocks, document the exact supported algorithm/configuration and add
independent numerical or instruction-vector checks. Distinguish software models,
instrumented DSP execution, and measured analog behavior. Hardware tests are
manual and must preserve the original program.

Keep generated build outputs out of Git. Version numbers come from
`sigmagraph/__init__.py`. GitHub Actions runs on pushes to `main`, tags matching
`v*`, pull requests and manual dispatch; artifacts are available for 30 days.
Tagging does not publish a GitHub Release automatically.

Contributions are provided under GPL-3.0-or-later, the project's license.
