# 0.4.2 — research release, 2026-10-24

Stable promotion of the `0.4.2rc1` research preview. Package code is
unchanged since the rc tag (`e988306`); this release updates version
metadata, documentation and release automation only.

## Validation for this release

- `pytest`: 133 passed, 1 skipped (Python 3.11, Windows).
- `ruff check` on src, tests, examples and research scripts: clean.
- Offline demo (`lerobot-boundary-audit demo`): 13/13 cases pass.
- Wheel and sdist are rebuilt from this tag by CI; the wheel contains
  only the `boundary_audit` package, license metadata and the bundled
  fixture.

## Changes since 0.4.2rc1

- Documentation: README/README.zh-CN add CI/release/license badges, a
  same-input comparison table against lerobot-doctor and openbot-data
  (frozen 0.4.0 evidence), and fold dated version/research sections.
- Release automation: any `v*` tag publishes its own GitHub release and
  refuses to overwrite an already published one; rc/a/b tags are marked
  as prereleases automatically.
- New opt-in PyPI Trusted Publishing workflow (manual dispatch only).
- Track the 0.4.2rc1 release review documents and reproducibility
  scripts; ignore local scratch directories.

See [CHANGELOG.md](CHANGELOG.md) for the full history. The RTX 4090 /
TorchCodec study remains experimental and is not a stable GPU reader.
