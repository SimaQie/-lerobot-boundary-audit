from collections import Counter

import numpy as np
import pytest

from boundary_audit.fixtures import export_demo
from boundary_audit.probe import prepare_probe
from boundary_audit.probe_driver import compare_actions, compare_pixels
from boundary_audit.probe_evidence import summarize_probe
from boundary_audit.row_contract import row_label_errors


def test_duplicate_wrong_neighbours_are_a_defect_not_ambiguity():
    frames = {0: np.zeros((2, 2, 3), np.uint8), 1: np.ones((2, 2, 3), np.uint8), 2: np.zeros((2, 2, 3), np.uint8)}
    result = compare_pixels(frames[0], frames, 1)
    assert result["status"] == "wrong_frame"
    assert result["matched_samples"] == [0, 2]
    frames[1] = frames[0].copy()
    assert compare_pixels(frames[0], frames, 1)["status"] == "ambiguous"


@pytest.mark.parametrize("value", [0.9, 0.0, True, False, float("nan"), float("inf"), "0", None])
def test_reader_labels_cannot_be_truncated_or_coerced(value):
    expected = {"index": 0, "episode_index": 0, "frame_index": 0}
    errors = row_label_errors({**expected, "index": value}, expected)
    assert len(errors) == 1
    assert errors[0]["reason"] == "non_integer"
    assert row_label_errors(expected, expected) == []


def test_equal_flattened_actions_do_not_hide_wrong_axes():
    expected = np.arange(6).reshape(3, 2)
    assert compare_actions(expected.reshape(2, 3), expected)[0]["kind"] == "action_shape"
    assert compare_actions(expected, expected) == []
    assert compare_actions(np.array(2.0), np.array(2.0)) == []
    assert compare_actions(np.array([2.0]), np.array(2.0))[0]["kind"] == "action_shape"
    assert compare_actions(np.full((3, 2), np.nan), expected)[0]["kind"] == "action_window"


@pytest.fixture
def request_plan(tmp_path):
    root = tmp_path / "suite"
    export_demo(root)
    request = prepare_probe(root / "merged", cameras=["observation.images.left"], max_rows=6)
    request["phase"] = "window"
    return request


def evidence(request):
    return [
        {"index": q["index"], "camera": c, "delta": d, "status": "pass", "match": "exact"}
        for q in request["queries"]
        for c in request["cameras"]
        for d in request["offsets"]
    ]


def test_empty_pass_or_duplicate_evidence_cannot_certify_a_probe(request_plan):
    n = len(request_plan["queries"])
    empty = summarize_probe({"status": "pass", "checked_rows": n}, request_plan)
    assert empty["status"] == "partial"
    assert empty["coverage"]["missing_query_slots"] == 18
    records = evidence(request_plan)
    records[-1] = records[0].copy()
    duplicate = summarize_probe({"status": "pass", "checked_rows": n, "records": records}, request_plan)
    assert duplicate["status"] == "partial"
    assert duplicate["coverage"]["missing_query_slots"] == 1
    assert duplicate["coverage"]["unexpected_query_slots"] == 1


def test_coverage_separates_ambiguity_and_sampling_scope(request_plan):
    records = evidence(request_plan)
    records[0].update(status="ambiguous", reason="identical neighbouring frames")
    result = summarize_probe({"status": "pass", "checked_rows": 6, "records": records}, request_plan)
    assert result["status"] == "partial"
    coverage = result["coverage"]
    assert coverage["query_slots_complete"]
    assert coverage["unique_query_rows"] == 6
    assert coverage["dataset_rows"] > coverage["unique_query_rows"]
    assert coverage["per_camera"]["observation.images.left"]["ambiguous_reasons"] == {
        "identical neighbouring frames": 1
    }


@pytest.mark.parametrize("phase,repeats", [("window", 1), ("persistent", 2), ("random", 1)])
def test_request_multiplicity_is_preserved(request_plan, phase, repeats):
    request_plan["phase"] = phase
    records = evidence(request_plan) * repeats
    checked = 6 * repeats
    if phase == "random":
        import random

        order = list(range(6))
        random.Random(request_plan["seed"]).shuffle(order)
        selected = {request_plan["queries"][i]["index"] for i in order[:3]}
        records += [r.copy() for r in records if r["index"] in selected]
        checked += 3
    result = summarize_probe({"status": "pass", "checked_rows": checked, "records": records}, request_plan)
    assert result["status"] == "pass"
    assert result["coverage"]["query_slots_complete"]
    assert result["coverage"]["requested_rows"] == checked


def test_stratification_is_seeded_and_does_not_choose_images(tmp_path):
    root = tmp_path / "suite"
    export_demo(root)
    kwargs = dict(cameras=["observation.images.left"], max_rows=6, sampling="stratified", seed=123)
    request = prepare_probe(root / "merged", **kwargs)
    assert request == prepare_probe(root / "merged", **kwargs)
    assert Counter(q["episode_index"] for q in request["queries"]) == {0: 3, 4: 3}
    for episode in [0, 4]:
        begin, end = request["episode_ranges"][str(episode)]
        indices = [q["index"] for q in request["queries"] if q["episode_index"] == episode]
        assert len(set(indices)) == 3
        for slot, index in enumerate(indices):
            assert begin + slot * (end - begin) // 3 <= index < begin + (slot + 1) * (end - begin) // 3
