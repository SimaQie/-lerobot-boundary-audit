# Same-input comparison (0.4.0)

Configuration and raw reports: summary.json. Original synthetic inputs only; no universal ranking.

| Case | v0.3 storage | v0.4 storage | doctor | openbot | full loader |
|---|---|---|---|---|---|
| recorded-a | pass | pass | no_blocking_error | reported_error | pass |
| recorded-b | pass | pass | no_blocking_error | reported_error | pass |
| merged | pass | pass | no_blocking_error | reported_error | pass |
| offset-one-frame | fail | fail | no_blocking_error | reported_error | fail |
| camera-swap | pass | pass | no_blocking_error | reported_error | fail |
| repaired-offset | pass | pass | no_blocking_error | reported_error | pass |
| global-index-shift | pass | fail | reported_warning | reported_error | fail |
| duplicate-global-index | pass | fail | reported_warning | reported_error | fail |
| action-window-corrupt | pass | pass | no_blocking_error | reported_error | fail |
| multi-data-shard | pass | pass | no_blocking_error | reported_error | pass |
| duplicate-pixel-frame | pass | pass | no_blocking_error | reported_error | fail |
| pixel-order-swap | pass | pass | no_blocking_error | reported_error | fail |
| no-b-frames | pass | pass | no_blocking_error | reported_error | pass |
