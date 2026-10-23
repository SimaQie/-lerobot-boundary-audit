# New pinned samples: cmu_stretch and utokyo_xarm (2026-10-24)

Local Windows (Python 3.11, PyAV 16.1.0) validation of the two additional
`download` presets added after the 0.4.2 release.

| Sample | Repo @ pinned revision | License | Layout | Coverage | Result |
|---|---|---|---|---|---|
| cmu_stretch | lerobot/cmu_stretch @ `d8457423` | MIT | chunked video, per-episode parquet | 135 episodes, 1 camera, 25,016 rows, 405/405 boundary queries decoded | PASS, 0 findings |
| utokyo_xarm | lerobot/utokyo_xarm_pick_and_place @ `da56c23e` | Apache-2.0 | sharded `file-N` data/video layout | 102 episodes, 2 of 3 cameras, 7,490 rows, 204/204 episode-camera pairs, 612/612 boundary queries decoded | PASS, 0 findings |

Both datasets declare AV1 video. Neither defect injection nor repair was
performed: these are untouched upstream samples, so a PASS means the stored
timelines and selected decode checks were self-consistent, not that any
upstream fault was (or was not) present.

- `cmu-stretch-report.json` — full audit report (audit --decode)
- `utokyo-xarm-report.json` — full audit report (audit --decode)

Commands and budgets are in the presets in `src/boundary_audit/download.py`.
The dataset card of `cmu_stretch` still embeds a stale v2.0 `info.json`
excerpt while the actual `meta/info.json` at the pinned revision is v3.0;
the audit used the actual files.
