"""Download a revision-pinned, size-bounded public sample without a Hub cache."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

REPO = "lerobot/pusht"
REVISION = "7628202a2180972f291ba1bc6723834921e72c19"
MAX_BYTES = 12_000_000


def download(destination: Path):
    base = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}"
    tree_url = f"https://huggingface.co/api/datasets/{REPO}/tree/{REVISION}?recursive=true"
    with urllib.request.urlopen(tree_url, timeout=30) as response:
        entries = json.load(response)
    files = [x for x in entries if x["type"] == "file" and x["path"] != ".gitattributes"]
    expected_bytes = sum(x["size"] for x in files)
    if expected_bytes > MAX_BYTES:
        raise ValueError(f"Sample exceeds download budget: {expected_bytes}")
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for item in files:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe remote path")
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".part")
            digest = hashlib.sha256()
            size = 0
            with urllib.request.urlopen(f"{base}/{item['path']}", timeout=60) as response:
                with temporary.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > item["size"]:
                            raise ValueError("Download exceeds advertised size")
                        digest.update(chunk)
                        output.write(chunk)
            if size != item["size"]:
                raise ValueError("Downloaded size mismatch")
            temporary.replace(path)
        if path.stat().st_size != item["size"]:
            raise ValueError("Existing sample size mismatch")
        records.append({"path": relative.as_posix(), "bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        print(f"Available: {relative.as_posix()} ({item['size']} bytes)", flush=True)
    manifest = {"repository": REPO, "revision": REVISION, "license_in_dataset_card": "MIT",
                "source_url": f"https://huggingface.co/datasets/{REPO}/tree/{REVISION}",
                "total_bytes": sum(x["bytes"] for x in records), "files": records}
    (destination.parent / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(download(args.destination), indent=2))
