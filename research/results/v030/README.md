# Measured evidence, 0.3.0 preview

`summary.json` records all 60 expected/actual comparisons. `full-loader-reports.zip`
contains the same summary, the offline report.html and complete per-check JSON
records with decoded pixel identities, action/padding findings and runtime versions.

From the project directory:

```sh
python -m zipfile -e research/results/v030/full-loader-reports.zip measured-evidence
```

Open measured-evidence/report.html; its JSON links work locally without a server.
`artifacts.json` records archive hashes and counts. `repair-control.json` contains
the controlled repair plan and exact-restore result. `backup-integrity.json` shows
all 6,260 files in the separate original backup stayed unchanged. No backup names
or contents are published.

`agibot2026-v020-summary.json` is the earlier pinned real-data experiment; it is
historical 0.2.0 evidence, not an independent pixel identity benchmark. External
robot data and derivative copies are excluded from every archive here.
