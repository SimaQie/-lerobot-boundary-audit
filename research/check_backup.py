"""Read-only verification of the saved materials against the pre-development hashes."""

import argparse
import json
from pathlib import Path

from boundary_audit.download import sha256
from boundary_audit.storage import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.out.resolve().is_relative_to(root):
        raise ValueError("Verification output must be outside the backup")
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = {p.relative_to(root).as_posix(): sha256(p) for p in root.rglob("*") if p.is_file()}
    result = {
        "unchanged": before == after,
        "before_files": len(before),
        "after_files": len(after),
        "added": sorted(set(after) - set(before)),
        "removed": sorted(set(before) - set(after)),
        "changed": sorted(k for k in before.keys() & after.keys() if before[k] != after[k]),
    }
    write_json(args.out, result)
    print(json.dumps(result, indent=2))
    if not result["unchanged"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
