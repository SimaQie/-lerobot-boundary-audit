# Independent frame-identity conformance

The bundled suite tests whether the installed official LeRobot dataset loader
returns the expected frame, action and padding for a requested row or window.
It complements the storage/timeline checks performed by `audit`.

## Independent reference

Each original synthetic image contains a camera ID (8 bits), original episode
ID (12 bits), frame ID (12 bits), synchronization byte and CRC-16. Cell averages
recover the IDs after lossy H.264 encoding. The identity oracle is defined before
encoding; neither MP4 PTS nor the consumer's selected frame defines the expected
identity.

The source recordings have episode lengths [7, 9, 5] and [8, 6]. The official
LeRobot 0.6.1 recording/merge APIs produce five merged episodes and 35 rows.
Original marker episode IDs [0, 1, 2, 100, 101] persist while dataset episode IDs
become [0, 1, 2, 3, 4], allowing the suite to check renumbering independently.

## Bundled cases and read modes

The published offline suite contains 13 cases: six clean controls and seven
deliberate faults. They cover episode offsets, camera payload swaps, duplicated
or reordered pixel frames, global index shift/duplication, corrupted actions,
multiple data shards and a clean no-B-frame encoding. The complete case list is
in [USAGE.md](../USAGE.md).

Each case runs with PyAV and TorchCodec across eight phases:

- `single`, `window`, `batch`, `workers`, `subset`;
- `long-window`, `random`, `persistent`.

The full bundled matrix contains 13 脳 2 脳 8 = 208 expected outcomes. Window
checks derive episode limits, clamp requests and verify action/camera padding
independently. Worker tests use spawned processes; persistent mode reuses workers
across epochs.

Consumer code runs in a separate interpreter without adding the auditor's
third-party packages to its dependency path. Upstream installed code is called
without patching it.

## Results and reproduction

See [USAGE.md](../USAGE.md) for the separate consumer environment, then run:

```sh
.venv/bin/lerobot-boundary-audit demo --out demo-result
.venv/bin/lerobot-boundary-audit conformance demo-result \
  --python .consumer-cpu/bin/python --jobs 2 --out reports/conformance
```

A suite PASS means clean controls passed and deliberate faults were detected.
An exception or missing runtime alone cannot satisfy an expected fault.
Reports distinguish storage findings, identity errors and unavailable checks.

`fixture-suite` regenerates the original producer controls using the installed
official recording API. This is a smaller suite than the bundled 13-case matrix;
the generated manifest records its actual cases. A repaired control is added
only when the existing CFR/timeline repair guards accept it.

## Scope

The tested upstream version is LeRobot 0.6.1; optional-consumer versions and
FFmpeg setup are documented in [USAGE.md](../USAGE.md). The marker suite uses
synthetic H.264 footage. It does not establish identity ground truth for arbitrary
real footage, physical camera/action synchronization or training benefit.

For ordinary robot video, use `probe-loader` with its separate sequential PyAV
reference. Non-unique or uncertain frame matches remain partial results.
