"""Small atomic output helpers; data publication never replaces an existing directory."""

import json
import os
import tempfile
from pathlib import Path


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, indent=2, ensure_ascii=False, allow_nan=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish_new_directory(staged, destination):
    """Windows rename is no-replace; on other hosts use a reserved destination.

    Non-Windows publication is not atomic as a whole directory, but an explicit
    INCOMPLETE marker remains until publication succeeds. Consumers must reject it.
    """
    staged, destination = Path(staged), Path(destination)
    if os.name == "nt":
        os.rename(staged, destination)
        return
    destination.mkdir()  # atomic exclusive reservation; never overwrite other work
    marker = destination / "INCOMPLETE"
    marker.write_text("Publication has not completed. Do not consume this directory.\n")
    for child in staged.iterdir():
        os.rename(child, destination / child.name)
    marker.unlink()
    staged.rmdir()
