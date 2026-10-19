"""Audit requested query slots independently of the consumer's status string."""

from collections import Counter


def summarize_probe(report, request):
    queries = request["queries"]
    order = list(range(len(queries)))
    if request["phase"] == "random":
        import random

        random.Random(request["seed"]).shuffle(order)
        order += order[: min(3, len(order))]
    epochs = 2 if request["phase"] == "persistent" else 1
    requested = Counter(
        (queries[i]["index"], camera, delta)
        for _ in range(epochs)
        for i in order
        for camera in request["cameras"]
        for delta in request["offsets"]
    )
    records = report.get("records", [])
    observed = Counter((r.get("index"), r.get("camera"), r.get("delta")) for r in records)
    missing, extra = sum((requested - observed).values()), sum((observed - requested).values())
    expected_checks = sum(requested.values())
    requested_rows = len(order) * epochs
    statuses = Counter(r.get("status", "unknown") for r in records)
    per_camera = {}
    for camera in request["cameras"]:
        subset = [r for r in records if r.get("camera") == camera]
        per_camera[camera] = {
            "requested_checks": requested_rows * len(request["offsets"]),
            "observed_checks": len(subset),
            "statuses": dict(Counter(r.get("status", "unknown") for r in subset)),
            "match_rules": dict(Counter(r.get("match", "unresolved") for r in subset)),
            "ambiguous_reasons": dict(
                Counter(r.get("reason", "unspecified") for r in subset if r.get("status") == "ambiguous")
            ),
        }
    all_ranges = request["episode_ranges"]
    selected_ids = set(all_ranges) if request["episodes"] is None else {str(e) for e in request["episodes"]}
    report["coverage"] = {
        "requested_rows": requested_rows,
        "checked_rows": report.get("checked_rows", 0),
        "requested_frame_checks": expected_checks,
        "observed_frame_checks": len(records),
        "missing_query_slots": missing,
        "unexpected_query_slots": extra,
        "query_slots_complete": bool(expected_checks and not missing and not extra),
        "dataset_rows": sum(end - begin for begin, end in all_ranges.values()),
        "selected_episode_rows": sum(end - begin for ep, (begin, end) in all_ranges.items() if ep in selected_ids),
        "unique_query_rows": len({q["index"] for q in queries}),
        "unique_window_rows": len(request["rows"]),
        "sampled_episode_ids": sorted({q["episode_index"] for q in queries}),
        "statuses": dict(statuses),
        "per_camera": per_camera,
        "note": "Counts describe requested query slots, including repeats/padding; not whole-dataset correctness.",
    }
    wrong = statuses["wrong_frame"] or statuses["wrong_shape"] or report.get("row_errors")
    complete = (
        expected_checks
        and not missing
        and not extra
        and statuses["pass"] == expected_checks
        and report.get("checked_rows", 0) == requested_rows
        and not report.get("errors")
    )
    if wrong:
        report["status"] = "fail"
    elif report["status"] == "pass" and not complete:
        report["status"] = "partial"
    return report
