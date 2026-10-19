"""Reproduce mixed/stratified probes without selecting by observed image quality."""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from boundary_audit.download import SAMPLES, sha256
from boundary_audit.probe import probe_loader
from boundary_audit.repair import fingerprint
from boundary_audit.report import write_probe_html
from boundary_audit.storage import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, default=Path("samples"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--ffmpeg-bin", type=Path)
    args = parser.parse_args()
    samples, output = args.samples.resolve(), args.out.resolve()
    if output.exists() or output.is_relative_to(samples) or samples.is_relative_to(output):
        raise ValueError("Use a fresh output directory outside the input samples")
    before, sources = {}, {}
    for sample in ("agibot2026", "aloha_screw_driver"):
        root = samples / sample
        manifest = json.loads((root / "source_manifest.json").read_text())
        if (manifest["repository"], manifest["revision"]) != (SAMPLES[sample]["repo"], SAMPLES[sample]["revision"]):
            raise ValueError("Unexpected source revision")
        if any(sha256(root / f["path"]) != f["sha256"] for f in manifest["files"]):
            raise ValueError("Source differs from pinned download receipt")
        before[sample] = fingerprint(root)
        sources[sample] = {k: manifest[k] for k in ("repository", "revision", "license", "total_bytes")}
    output.mkdir(parents=True)
    tasks = [
        (sample, backend, sampling)
        for sample in sources
        for backend in ("pyav", "torchcodec")
        for sampling in ("mixed", "stratified")
    ]

    def execute(task):
        sample, backend, sampling = task
        result = probe_loader(
            samples / sample,
            args.python,
            cameras=SAMPLES[sample]["cameras"],
            backend=backend,
            phase="workers",
            max_rows=6,
            radius=1,
            seed=20261014,
            sampling=sampling,
            timeout=600,
            ffmpeg_bin=args.ffmpeg_bin,
        )
        # The consumer already redacts its inputs. Also remove the auditor's
        # absolute workspace prefix from errors or future provenance fields.
        text = json.dumps(result, allow_nan=False)
        project = str(Path(__file__).resolve().parents[1])
        for prefix in (project, project.replace("\\", "/")):
            text = text.replace(json.dumps(prefix)[1:-1], "<project>")
        result = json.loads(text)
        target = output / sample / f"{backend}-{sampling}"
        write_json(target / "probe-report.json", result)
        write_probe_html(result, target / "report.html")
        print(
            f"{sample}/{backend}/{sampling}: {result['status']}; "
            f"{result.get('passed_frame_checks', 0)} matches, "
            f"{result.get('ambiguous_frame_checks', 0)} ambiguous",
            flush=True,
        )
        return {
            "sample": sample,
            "backend": backend,
            "sampling": sampling,
            "report": target.relative_to(output).as_posix() + "/probe-report.json",
            **{
                k: result.get(k)
                for k in (
                    "status",
                    "checked_rows",
                    "frame_checks",
                    "passed_frame_checks",
                    "ambiguous_frame_checks",
                    "row_errors",
                    "errors",
                    "coverage",
                    "source_unchanged",
                    "elapsed_seconds",
                )
            },
        }

    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(execute, tasks))
    unchanged = {s: fingerprint(samples / s) == before[s] for s in sources}
    complete = all(
        c["source_unchanged"]
        and c["coverage"]["query_slots_complete"]
        and c["checked_rows"] == c["coverage"]["requested_rows"]
        and not c["row_errors"]
        and not c["errors"]
        and c["status"] in {"pass", "partial"}
        for c in checks
    ) and all(unchanged.values())
    summary = {
        "schema_version": "boundary-probe-review.v1",
        "measurement_date": "2026-10-20",
        "platform": "Windows CPU",
        "sources": sources,
        "checks": checks,
        "source_hashes_unchanged": unchanged,
        "status": ("review_required" if not complete else "completed_with_ambiguity"
                   if any(c["ambiguous_frame_checks"] for c in checks) else "completed"),
        "note": "No image-based query selection, no discarded ambiguity, no natural defect or GPU claim.",
    }
    write_json(output / "summary.json", summary)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
