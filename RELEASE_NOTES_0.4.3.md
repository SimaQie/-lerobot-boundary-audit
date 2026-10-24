# 0.4.3 — 2026-10-24

Focused maintenance release of the CPU audit tool: two additional pinned
real-data sources, GPU-workstation compatibility validation, and a cleaned
public source tree.

## New pinned samples

- `cmu_stretch`: real Stretch mobile manipulator, 135 episodes at 5 FPS, one
  camera, chunked video layout, MIT license (~39 MB download).
- `utokyo_xarm`: real xArm pick-and-place, 102 episodes at 10 FPS, two of
  three cameras, sharded data/video layout, Apache-2.0 license (~30 MB).
- `download` and `validate_real_sample.py` now derive their sample choices
  from `SAMPLES`, so every preset is accepted uniformly.

With the existing AgiBot and ALOHA presets this covers four real platforms at
three frame rates, two storage layouts, and the AV1 codec family, alongside
the H.264 synthetic fixture.

## GPU-workstation compatibility

The supported product is the CPU data pipeline; a GPU machine is fully
supported because no component requires one. On an RTX 4090 / WSL2 host
(baseline `61719d0`, LeRobot 0.6.1, PyAV and TorchCodec):

- 208/208 fixture conformance expected outcomes.
- 78/78 conformance under the CUDA Torch build (decode device remains CPU:
  the stock LeRobot reader is CPU-only by design).
- Four source audits pass with every boundary query decoded
  (60/60, 300/300, 405/405, 612/612).
- Four full validation workflows report `expected_outcomes_met`, including
  official-reader checks, authored-offset localization, guarded repair and
  exact restoration.

Explicit CUDA/NVDEC decoding is out of scope: the stock reader does not use
it, and mixed RGB ranges make pixel-identity evidence ambiguous. See
[research/GPU_MACHINE_VALIDATION.md](research/GPU_MACHINE_VALIDATION.md).

## Distribution checks

`examples/check_distribution.py` verifies an installed wheel in a fresh
environment: version consistency, bundled demo, fault detection, guarded
repair, exact restoration, unsafe-repair rejection and source preservation —
with no Torch on the path. Validated on Windows for this release.

## Source tree cleanup

- Removed exploratory GPU/TorchCodec benchmark code, dated review documents
  and per-run result dumps from the tracked tree; the release keeps only the
  validation summary and its reproduction commands.
- `MANIFEST.in` now ships the user documentation, the validation summary and
  the real-sample validation script.
- Release notes and workflow files for previous versions are retained as
  release-attachment snapshots; this tag is built by CI from the tag itself.

See [CHANGELOG.md](CHANGELOG.md) for the full history.
