"""Command line entry points; audit outputs stay outside the input."""

import argparse
import json
import sys
from pathlib import Path

from .audit import audit_dataset
from .report import write_reports
from .storage import write_json


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {
        "audit",
        "verify",
        "download",
        "repair-plan",
        "apply",
        "restore",
        "fixture-suite",
        "verify-loader",
        "conformance",
    }
    if argv and argv[0] not in commands and not argv[0].startswith("-"):
        argv.insert(0, "audit")
    parser = argparse.ArgumentParser(description="LeRobot episode boundary audit and guarded repair")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["audit", "verify", "repair-plan"]:
        cmd = sub.add_parser(name)
        cmd.add_argument("root", type=Path)
        cmd.add_argument("--out", type=Path, required=True)
        cmd.add_argument("--camera", action="append", dest="cameras")
        if name == "audit":
            cmd.add_argument("--decode", action="store_true")
            cmd.add_argument("--tolerance", type=float, default=0.0001)
        elif name == "verify":
            cmd.add_argument("--python", required=True, help="Interpreter with official LeRobot installed")
            cmd.add_argument("--backend", choices=["torchcodec", "pyav"], default="torchcodec")
            cmd.add_argument("--ffmpeg-bin", type=Path)
        else:
            cmd.add_argument(
                "--assume-cfr", action="store_true", help="Assert ordered contiguous frames at declared FPS"
            )
    cmd = sub.add_parser("download")
    cmd.add_argument("sample", choices=["agibot2026", "pusht"])
    cmd.add_argument("--out", type=Path, required=True)
    cmd.add_argument("--max-bytes", type=int)
    cmd = sub.add_parser("apply")
    cmd.add_argument("plan", type=Path)
    cmd.add_argument("--source", type=Path, required=True)
    cmd.add_argument("--out", type=Path, required=True)
    cmd = sub.add_parser("restore")
    cmd.add_argument("root", type=Path)
    cmd.add_argument("--out", type=Path, required=True)
    for name in ["fixture-suite", "verify-loader", "conformance"]:
        cmd = sub.add_parser(name)
        if name != "fixture-suite":
            cmd.add_argument("root", type=Path)
        cmd.add_argument("--out", type=Path, required=True)
        cmd.add_argument("--python", required=True)
        cmd.add_argument("--ffmpeg-bin", type=Path)
        if name == "verify-loader":
            cmd.add_argument("--backend", choices=["pyav", "torchcodec"], default="pyav")
            cmd.add_argument("--phase", choices=["single", "window", "batch", "workers", "subset"], default="single")
        elif name == "conformance":
            cmd.add_argument("--backend", choices=["pyav", "torchcodec"], action="append", dest="backends")
            cmd.add_argument(
                "--phase", choices=["single", "window", "batch", "workers", "subset"], action="append", dest="phases"
            )
    args = parser.parse_args(argv)
    if args.command in {
        "audit",
        "verify",
        "repair-plan",
        "verify-loader",
        "conformance",
    } and args.out.resolve().is_relative_to(args.root.resolve()):
        parser.error("Output must be outside the source dataset")
    try:
        if args.command in {"fixture-suite", "verify-loader", "conformance"}:
            from .conformance import PHASES, generate_suite, run_suite, verify_loader

            if args.command == "fixture-suite":
                result = generate_suite(args.out, args.python, ffmpeg_bin=args.ffmpeg_bin)
            elif args.command == "verify-loader":
                result = verify_loader(
                    args.root, args.python, backend=args.backend, phase=args.phase, ffmpeg_bin=args.ffmpeg_bin
                )
                args.out.mkdir(parents=True, exist_ok=True)
                write_json(args.out / "loader-report.json", result)
            else:
                result = run_suite(
                    args.root,
                    args.out,
                    args.python,
                    backends=args.backends or ("pyav", "torchcodec"),
                    phases=args.phases or PHASES,
                    ffmpeg_bin=args.ffmpeg_bin,
                )
            summary = {k: v for k, v in result.items() if k != "records"}
        elif args.command == "download":
            from .download import fetch_sample

            result = fetch_sample(args.sample, args.out, max_bytes=args.max_bytes)
            summary = {k: result[k] for k in ["repository", "revision", "total_bytes", "selected_cameras"]}
        elif args.command == "repair-plan":
            from .repair import make_plan

            result = make_plan(args.root, cameras=args.cameras, assume_cfr=args.assume_cfr)
            write_json(args.out, result)
            summary = {
                "status": result["status"],
                "operations": len(result["operations"]),
                "refusals": result["refusals"],
            }
        elif args.command == "apply":
            from .repair import apply_plan

            result = apply_plan(json.loads(args.plan.read_text(encoding="utf-8")), args.source, args.out)
            summary = {"status": "applied", "verification": result["verification"]}
        elif args.command == "restore":
            from .repair import restore_copy

            result = restore_copy(args.root, args.out)
            summary = result
        else:
            if args.command == "audit":
                result = audit_dataset(args.root, decode=args.decode, tolerance=args.tolerance, cameras=args.cameras)
            else:
                from .verify import verify_consumer

                result = verify_consumer(
                    args.root,
                    args.python,
                    cameras=args.cameras,
                    backend=args.backend,
                    ffmpeg_bin=args.ffmpeg_bin.resolve() if args.ffmpeg_bin else None,
                )
            manifest = args.root / "source_manifest.json"
            if manifest.exists():
                source = json.loads(manifest.read_text(encoding="utf-8"))
                result["sample_source"] = {
                    k: source[k] for k in ["repository", "revision", "license", "note", "source_url"] if k in source
                }
            write_reports(result, args.out)
            summary = {k: result[k] for k in ["status", "selection", "coverage", "decoder", "timing_seconds"]}
            if "consumer_verification" in result:
                summary["consumer_verification"] = {
                    k: v for k, v in result["consumer_verification"].items() if k != "records"
                }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        status = result.get("status", "pass")
        return (
            1
            if status in {"fail", "review", "blocked"}
            else 2
            if status in {"partial", "contract_required", "unavailable"}
            else 0
        )
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        print(f"Could not complete: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
