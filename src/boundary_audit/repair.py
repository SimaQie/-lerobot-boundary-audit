"""Reviewable plans and verified derivative copies under an explicit CFR contract.

No input is opened for writing. Only small, one-tick stts defects and video
offset metadata are supported. Data rows, actions and physical timing are never
inferred or regenerated. Restore reconstructs the exact original file hashes.
"""

import hashlib
import json
import shutil
import tempfile
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

from .audit import audit_dataset, contained
from .download import sha256
from .mp4 import read_timeline
from .storage import publish_new_directory, write_json


def fingerprint(root):
    root = Path(root).resolve()
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Repair input must not contain symlinks")
        if path.is_file() and ".boundary_audit" not in path.relative_to(root).parts:
            files[path.relative_to(root).as_posix()] = sha256(path)
    return files


def document_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def make_plan(root, *, cameras=None, assume_cfr=False):
    import pyarrow.parquet as pq

    root = Path(root).resolve()
    if (root / ".boundary_audit").exists():
        raise ValueError("Plan from an original input; nested repair transactions are not supported")
    files = fingerprint(root)
    audit = audit_dataset(root, cameras=cameras)
    plan = {
        "schema_version": "boundary-repair-plan.v1",
        "source_files": files,
        "cameras": audit["selection"]["checked_cameras"],
        "assume_cfr": assume_cfr,
        "contract": "All referenced video frames are ordered, contiguous samples at declared FPS; this is a user-supplied recording contract, not inferred physical truth.",
        "operations": [],
        "refusals": [],
        "status": "no_changes",
    }
    if audit.get("fps") is None:
        plan["status"] = "blocked"
        plan["refusals"].append("Dataset prerequisites are invalid; no timing changes can be proposed")
        if files != fingerprint(root):
            raise ValueError("Source changed during planning")
        plan["fingerprint"] = document_hash(plan)
        return plan
    if not assume_cfr:
        plan["status"] = "contract_required"
        plan["refusals"].append("Explicit --assume-cfr is required before proposing timing changes")
    else:
        allowed = {"VIDEO_GRID_DEVIATION", "EPISODE_START_MISMATCH", "EPISODE_END_MISMATCH", "BOUNDARY_QUERY_MISMATCH"}
        unsupported = set(audit["finding_counts"]) - allowed
        if unsupported:
            plan["refusals"].append("Non-repairable findings: " + ", ".join(sorted(unsupported)))
        fps = Fraction(audit["fps"])
        corrected_videos = set()
        timelines = {}
        for video in audit["video_reports"]:
            relative = video["path"]
            timeline = read_timeline(contained(root, relative))
            timelines[relative] = timeline
            interval = Fraction(timeline.timescale, 1) / fps
            if video["exact_grid"]:
                continue
            if (
                timeline.composition is not None
                or timeline.edit_media_time
                or timeline.track_count != 1
                or interval.denominator != 1
            ):
                plan["refusals"].append(f"Unsupported video repair: {relative}")
                continue
            expected = int(interval)
            offenders = [(i, count, delta) for i, (count, delta) in enumerate(timeline.runs) if delta != expected]
            if (
                not offenders
                or sum(count for _, count, _ in offenders) > 8
                or any(abs(delta - expected) != 1 for _, _, delta in offenders)
            ):
                plan["refusals"].append(
                    f"Only at most eight anomalous one-tick sample durations can be repaired: {relative}"
                )
                continue
            patches = [
                {
                    "field": f"stts[{i}].sample_delta",
                    "offset": timeline.delta_offsets[i],
                    "width": 4,
                    "before": delta,
                    "after": expected,
                }
                for i, _, delta in offenders
            ]
            duration_width = 4 if timeline.mdhd_version == 0 else 8
            patches.append(
                {
                    "field": "mdhd.duration",
                    "offset": timeline.duration_offset,
                    "width": duration_width,
                    "before": timeline.duration,
                    "after": timeline.samples * expected,
                }
            )
            duration_names = {f["field"] for f in timeline.duration_fields or []}
            if not {"mvhd.duration", "tkhd.duration"} <= duration_names or not all(
                f["timescale"] for f in timeline.duration_fields
            ):
                plan["refusals"].append(f"Complete movie/track duration provenance required: {relative}")
                continue
            for field in timeline.duration_fields:
                after = round(Fraction(timeline.samples * expected * field["timescale"], timeline.timescale))
                if field["before"] != after:
                    patches.append({k: field[k] for k in ["field", "offset", "width", "before"]} | {"after": after})
            if any(not 0 <= p["after"] < 2 ** (p["width"] * 8) for p in patches):
                plan["refusals"].append(f"Repaired duration exceeds field width: {relative}")
                continue
            plan["operations"].append({"kind": "mp4_fields", "path": relative, "patches": patches})
            corrected_videos.add(relative)
        info = json.loads((root / "meta/info.json").read_text())
        rows = []
        for path in sorted((root / "meta/episodes").glob("chunk-*/file-*.parquet")):
            table = pq.read_table(contained(root, path.relative_to(root)))
            columns = [c for c in table.column_names if not c.startswith("stats/")]
            rows.extend((row, path.relative_to(root).as_posix()) for row in table.select(columns).to_pylist())
        rows.sort(key=lambda pair: pair[0]["episode_index"])
        cursors = defaultdict(int)
        changes = defaultdict(list)
        for row, metadata_path in rows:
            for camera in plan["cameras"]:
                prefix = f"videos/{camera}"
                relative = info["video_path"].format(
                    video_key=camera, chunk_index=row[f"{prefix}/chunk_index"], file_index=row[f"{prefix}/file_index"]
                )
                timeline = timelines.get(relative)
                cursor, length = cursors[relative], row["length"]
                cursors[relative] += length
                if timeline is None or cursor + length > timeline.samples:
                    continue
                for column, index in [
                    (f"{prefix}/from_timestamp", cursor),
                    (f"{prefix}/to_timestamp", cursor + length),
                ]:
                    if relative in corrected_videos:
                        expected = float(Fraction(index, 1) / fps)
                    else:
                        tick = timeline.tick_at(index) if index == cursor else timeline.end_tick_at(index - 1)
                        expected = tick / timeline.timescale
                    # Preserve insignificant producer rounding; repair only an
                    # actual blocked offset, never reserialize all metadata.
                    if abs(float(row[column]) - expected) > audit["tolerance_seconds"]:
                        changes[metadata_path].append(
                            {
                                "episode_index": row["episode_index"],
                                "column": column,
                                "before": row[column],
                                "after": expected,
                            }
                        )
        for path, values in sorted(changes.items()):
            plan["operations"].append({"kind": "episode_offsets", "path": path, "changes": values})
        plan["status"] = "blocked" if plan["refusals"] else "ready" if plan["operations"] else "no_changes"
    if files != fingerprint(root):
        raise ValueError("Source changed during planning")
    plan["fingerprint"] = document_hash(plan)
    return plan


def validate_document(value):
    body = {k: v for k, v in value.items() if k != "fingerprint"}
    if value.get("fingerprint") != document_hash(body):
        raise ValueError("Plan/receipt fingerprint mismatch")


def validate_output(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Use a new output directory that does not overlap the input")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return source, destination


def media_hash(path):
    from .mp4 import boxes

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        ranges = [b for b in boxes(stream, 0, Path(path).stat().st_size) if b.kind == b"mdat"]
        if not ranges:
            raise ValueError("MP4 has no media payload")
        for box in ranges:
            digest.update((box.end - box.start).to_bytes(8, "big"))
            stream.seek(box.start)
            remaining = box.end - box.start
            while remaining:
                block = stream.read(min(remaining, 1024 * 1024))
                if not block:
                    raise ValueError("Truncated media payload")
                digest.update(block)
                remaining -= len(block)
    return digest.hexdigest()


def apply_plan(plan, source, output):
    import pyarrow as pa
    import pyarrow.parquet as pq

    validate_document(plan)
    source, output = validate_output(source, output)
    if plan["status"] != "ready":
        raise ValueError("Only a ready plan with recording contract can be applied")
    if fingerprint(source) != plan["source_files"]:
        raise ValueError("Source fingerprint changed after planning")
    derived = make_plan(source, cameras=plan["cameras"], assume_cfr=plan["assume_cfr"])
    if derived["fingerprint"] != plan["fingerprint"] or derived["status"] != "ready":
        raise ValueError("Plan operations do not match the allowed parser-derived changes")
    receipt = {
        "schema_version": "boundary-repair-receipt.v1",
        "source_files": plan["source_files"],
        "plan_fingerprint": plan["fingerprint"],
        "operations": plan["operations"],
        "cameras": plan["cameras"],
        "media_payloads": {},
        "metadata_backups": {},
    }
    with tempfile.TemporaryDirectory(prefix=".boundary-audit-", dir=output.parent) as temporary:
        stage = Path(temporary) / "dataset"
        shutil.copytree(source, stage)
        if fingerprint(stage) != plan["source_files"]:
            raise ValueError("Input changed during copying")
        for operation in plan["operations"]:
            path = contained(stage, operation["path"])
            if operation["kind"] == "mp4_fields":
                before_media = media_hash(path)
                # Validate every expected value before the first write.
                with path.open("r+b") as stream:
                    for patch in operation["patches"]:
                        stream.seek(patch["offset"])
                        if int.from_bytes(stream.read(patch["width"]), "big") != patch["before"]:
                            raise ValueError("Patch precondition failed")
                    for patch in operation["patches"]:
                        stream.seek(patch["offset"])
                        stream.write(patch["after"].to_bytes(patch["width"], "big"))
                if media_hash(path) != before_media:
                    raise ValueError("Repair changed media payload")
                receipt["media_payloads"][operation["path"]] = before_media
            elif operation["kind"] == "episode_offsets":
                backup_relative = ".boundary_audit/originals/" + operation["path"]
                backup = contained(stage, backup_relative)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, backup)
                receipt["metadata_backups"][operation["path"]] = backup_relative
                table = pq.read_table(path)
                ids = table["episode_index"].to_pylist()
                for change in operation["changes"]:
                    index = ids.index(change["episode_index"])
                    values = table[change["column"]].to_pylist()
                    if values[index] != change["before"]:
                        raise ValueError("Metadata precondition failed")
                    values[index] = change["after"]
                    table = table.set_column(
                        table.schema.get_field_index(change["column"]),
                        table.schema.field(change["column"]),
                        pa.array(values, type=table[change["column"]].type),
                    )
                pq.write_table(table, path)
            else:
                raise ValueError("Unknown operation")
        verification = audit_dataset(stage, cameras=plan["cameras"], decode=True)
        if verification["status"] != "pass":
            raise ValueError("Repaired output did not pass requested storage and PyAV checks")
        receipt["verification"] = {k: verification[k] for k in ["status", "coverage", "selection", "decoder"]}
        receipt["repaired_files"] = fingerprint(stage)
        receipt["fingerprint"] = document_hash(receipt)
        write_json(stage / ".boundary_audit/receipt.json", receipt)
        if fingerprint(source) != plan["source_files"]:
            raise ValueError("Source changed during repair")
        publish_new_directory(stage, output)
    return receipt


def restore_copy(source, output):
    source, output = validate_output(source, output)
    receipt = json.loads((source / ".boundary_audit/receipt.json").read_text(encoding="utf-8"))
    validate_document(receipt)
    if fingerprint(source) != receipt["repaired_files"]:
        raise ValueError("Repaired input has changed; restore refused")
    with tempfile.TemporaryDirectory(prefix=".boundary-restore-", dir=output.parent) as temporary:
        stage = Path(temporary) / "dataset"
        shutil.copytree(source, stage, ignore=shutil.ignore_patterns(".boundary_audit"))
        for operation in receipt["operations"]:
            path = contained(stage, operation["path"])
            if operation["kind"] == "episode_offsets":
                backup = contained(source, receipt["metadata_backups"][operation["path"]])
                if sha256(backup) != receipt["source_files"][operation["path"]]:
                    raise ValueError("Original metadata backup has changed")
                shutil.copyfile(backup, path)
            elif operation["kind"] == "mp4_fields":
                with path.open("r+b") as stream:
                    for patch in operation["patches"]:
                        stream.seek(patch["offset"])
                        if int.from_bytes(stream.read(patch["width"]), "big") != patch["after"]:
                            raise ValueError("Restore field precondition failed")
                        stream.seek(patch["offset"])
                        stream.write(patch["before"].to_bytes(patch["width"], "big"))
        if fingerprint(stage) != receipt["source_files"]:
            raise ValueError("Restored files do not match the exact original hashes")
        if fingerprint(source) != receipt["repaired_files"]:
            raise ValueError("Repaired source changed during restore")
        publish_new_directory(stage, output)
    return {
        "status": "restored",
        "original_file_hashes_verified": True,
        "files": len(receipt["source_files"]),
        "repair_receipt_fingerprint": receipt["fingerprint"],
    }
