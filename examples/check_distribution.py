"""Check an installed wheel in a fresh environment, without source-path imports."""

import argparse
import importlib.metadata
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from boundary_audit import __version__
from boundary_audit.repair import fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    if importlib.metadata.version("lerobot-boundary-audit") != __version__:
        raise RuntimeError("Installed package metadata and runtime versions differ")
    if importlib.util.find_spec("torch") is not None:
        raise RuntimeError("Use an isolated audit environment without Torch for this check")
    checks = {}

    def run(name, arguments, expected=0):
        completed = subprocess.run(
            [sys.executable, "-I", "-m", "boundary_audit.cli", *map(str, arguments)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        if completed.returncode != expected:
            raise RuntimeError(f"{name}: expected exit {expected}, got {completed.returncode}: {completed.stderr}")
        checks[name] = {"exit_code": completed.returncode, "output": completed.stdout.strip()}

    run("version", ["--version"])
    if checks["version"]["output"] != f"lerobot-boundary-audit {__version__}":
        raise RuntimeError("CLI and installed package versions differ")
    run("demo", ["demo", "--out", out / "demo"])
    source = out / "demo/offset-one-frame"
    before = fingerprint(source)
    run("clean", ["audit", out / "demo/merged", "--decode", "--out", out / "clean"])
    run("fault", ["audit", source, "--decode", "--out", out / "fault"], expected=1)
    run("plan", ["repair-plan", source, "--assume-cfr", "--out", out / "plan.json"])
    run("apply", ["apply", out / "plan.json", "--source", source, "--out", out / "repaired"])
    run("repaired", ["audit", out / "repaired", "--decode", "--out", out / "repaired-audit"])
    run("restore", ["restore", out / "repaired", "--out", out / "restored"])
    run(
        "unsafe_index_repair",
        ["repair-plan", out / "demo/global-index-shift", "--assume-cfr", "--out", out / "blocked.json"],
        expected=1,
    )
    if fingerprint(source) != before or fingerprint(out / "restored") != before:
        raise RuntimeError("Source preservation or byte-exact restoration failed")
    result = {
        "version": __version__,
        "status": "pass",
        "torch_installed": False,
        "source_unchanged": True,
        "restored_exact": True,
        "checks": checks,
    }
    (out / "package-check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "checks"}, indent=2))


if __name__ == "__main__":
    main()
