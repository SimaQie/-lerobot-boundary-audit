# Contributing

## Development environment

Python 3.11 and 3.12 are tested on Linux and Windows. From a source checkout:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e ".[repair,dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests examples research/validate_real_sample.py
```

On Windows replace `.venv/bin/python` with `.venv\Scripts\python.exe`.
Keep the audit installation free of Torch and network services. Optional
official-reader checks use a separate environment as described in
[USAGE.md](USAGE.md); installed upstream code must not be modified.

## Reporting a problem

Include the tool version (`lerobot-boundary-audit --version`), source commit,
OS, Python and relevant LeRobot/Torch/decoder/FFmpeg versions. Supply the exact
command, expected result, observed result and JSON report when possible.
For loader failures, include independently known expected frame identities and
state whether the issue occurred naturally or was deliberately injected.

Prefer a minimal synthetic reproducer. Remove credentials and private paths
from reports, and respect dataset licenses when sharing input data.

## Validation requirements

- Preserve source files; repairs and restoration always create new directories.
- Keep missing runtimes, unsupported layouts and incomplete evidence explicit.
- Preserve ambiguous frame matches as partial results.
- Add regression coverage for incorrect PASS results, unsafe writes or invalid
  repair acceptance. An ordinal timestamp match alone does not prove frame
  identity or physical synchronization.
- Run relevant tests and the checks above before submitting a change.

CI also checks official-loader conformance and fresh installations from built
distributions. To reproduce the distribution check on Linux:

```sh
.venv/bin/python -m pip install build
.venv/bin/python -m build
python -m venv .package-env
.package-env/bin/python -m pip install 'dist/lerobot_boundary_audit-0.4.3-py3-none-any.whl[repair]'
.package-env/bin/python -I examples/check_distribution.py --out package-check
```

Use a fresh environment and output directory. The check exercises the installed
CLI, bundled demo, clean/faulty audits, copy-based repair, byte-exact restoration
and refusal to repair corrupted global indexes. Its output includes
`package-check/package-check.json`.

## Release preparation

Keep `pyproject.toml`, `boundary_audit.__version__` and `CITATION.cff` consistent.
Record changes under the pending version in [CHANGELOG.md](CHANGELOG.md).
Before a tagged release, run CI on the intended commit, verify both wheel and
sdist, and finalize the version and citation date.

Publish from the tested commit. Released tags and assets are immutable snapshots;
subsequent source changes require a new version. Updating `main` does not publish
to PyPI or replace GitHub release assets.
