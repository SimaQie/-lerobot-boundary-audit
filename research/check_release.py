"""Fail a release tag when versioned metadata or required notes disagree."""

from __future__ import annotations

import argparse
import ast
import json
import re
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path


def _assignment(text, name):
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    return None


def check(root, tag, dist=None):
    root = Path(root).resolve()
    if not tag.startswith("v") or len(tag) < 2:
        raise ValueError("Release tag must look like v<version>")
    version = tag[1:]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = pyproject["project"]["version"]
    runtime_version = _assignment((root / "src/boundary_audit/__init__.py").read_text(encoding="utf-8"), "__version__")
    citation = (root / "CITATION.cff").read_text(encoding="utf-8")
    citation_version = re.search(r"(?m)^version:\s*[\"']?([^\"'\s]+)", citation)
    citation_version = citation_version.group(1) if citation_version else None
    problems = []
    for name, value in (
        ("tag", version),
        ("pyproject", project_version),
        ("runtime", runtime_version),
        ("CITATION.cff", citation_version),
    ):
        if value != version:
            problems.append(f"{name} version is {value!r}, tag implies {version!r}")
    notes = [root / f"RELEASE_NOTES_{tag}.md", root / f"RELEASE_NOTES_{version}.md"]
    present = next((path for path in notes if path.is_file()), None)
    if present is None:
        problems.append(f"missing RELEASE_NOTES_{tag}.md or RELEASE_NOTES_{version}.md")
    artifacts = {}
    if dist is not None:
        directory = Path(dist)
        wheels = sorted(directory.glob("*.whl"))
        sdists = sorted(directory.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            problems.append(f"expected one wheel and one sdist, found {len(wheels)} wheel(s) and {len(sdists)} sdist(s)")
        for path in wheels + sdists:
            expected = (f"lerobot_boundary_audit-{version}-py3-none-any.whl" if path.suffix == ".whl"
                        else f"lerobot_boundary_audit-{version}.tar.gz")
            if path.name != expected:
                problems.append(f"artifact does not carry tag version: {path.name}")
                continue
            try:
                if path.suffix == ".whl":
                    with zipfile.ZipFile(path) as archive:
                        names = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
                        if len(names) != 1:
                            raise ValueError("expected one wheel METADATA")
                        metadata = archive.read(names[0]).decode("utf-8")
                else:
                    with tarfile.open(path) as archive:
                        member = archive.getmember(f"lerobot_boundary_audit-{version}/PKG-INFO")
                        metadata = archive.extractfile(member).read().decode("utf-8")
                parsed = Parser().parsestr(metadata)
                if parsed["Version"] != version or parsed["Name"] != "lerobot-boundary-audit":
                    raise ValueError("embedded package name/version disagrees with tag")
            except (OSError, ValueError, KeyError, zipfile.BadZipFile, tarfile.TarError) as exc:
                problems.append(f"invalid artifact {path.name}: {exc}")
        artifacts = {"wheels": [path.name for path in wheels], "sdists": [path.name for path in sdists]}
    if problems:
        raise ValueError("; ".join(problems))
    return {
        "status": "pass",
        "tag": tag,
        "version": version,
        "release_notes": present.name,
        "citation_version": citation_version,
        "artifacts": artifacts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--dist", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.root, args.tag, args.dist), indent=2))


if __name__ == "__main__":
    main()
