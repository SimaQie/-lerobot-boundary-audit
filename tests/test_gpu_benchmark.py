import json

from boundary_audit.gpu_benchmark import (
    dumps,
    evaluate_benchmark,
    expected_ordinal_for_time,
    map_time_to_ordinal,
    safe_time_value,
    time_matches,
    time_pts_status,
)


def normal_config(devices=None):
    return {
        "inputs": [{"id": "sample"}],
        "devices": devices or ["cpu"],
        "performance": {
            "enabled": True,
            "inputs": ["sample"],
            "batch_sizes": [1],
            "repeats": 2,
        },
    }


def normal_summary():
    return {
        "device_status": {"cpu": {"status": "available"}},
        "requests": {"sample": {"cpu": {"ordinal_repeats": 1, "time_repeats": 2}}},
        "correctness": {
            "sample": {
                "cpu": {
                    "status": "pass",
                    "checks": [{"status": "pass"}, {"status": "pass"}, {"status": "pass"}],
                    "fallback": {"occurred": False},
                }
            }
        },
        "performance": {
            "sample": {
                "cpu": {
                    "1": {
                        "status": "pass",
                        "native": {"count": 2},
                        "end_to_end": {"count": 2},
                        "raw": {"native_seconds": [0.1, 0.2], "end_to_end_seconds": [0.1, 0.2]},
                        "fallback": {"occurred": False, "known": True},
                    }
                }
            }
        },
        "integrity": {"status": "pass"},
        "source_unchanged": True,
    }


def evaluation(config, summary, devices=None, modes=None):
    devices = devices or config.get("devices", ["cpu"])
    modes = modes or {"correctness", "performance"}
    return evaluate_benchmark(config, summary, devices, modes)


def test_complete_normal_summary_passes():
    result = evaluation(normal_config(), normal_summary())
    assert result["status"] == "pass"
    assert result["correctness"]["status"] == "pass"
    assert result["performance"]["status"] == "pass"


def test_missing_correctness_cannot_pass():
    summary = normal_summary()
    del summary["correctness"]["sample"]
    result = evaluation(normal_config(), summary)
    assert result["status"] != "pass"
    assert "correctness:sample/cpu" in result["missing"]


def test_missing_cuda_subtask_cannot_pass():
    config = normal_config(["cpu", "cuda"])
    summary = normal_summary()
    summary["device_status"]["cuda"] = {"status": "available"}
    result = evaluation(config, summary)
    assert result["status"] == "partial"
    assert "correctness:sample/cuda" in result["missing"]


def test_source_change_blocks_a_pass():
    summary = normal_summary()
    summary["integrity"] = {"status": "fail"}
    summary["source_unchanged"] = False
    result = evaluation(normal_config(), summary)
    assert result["status"] == "fail"
    assert any("integrity" in issue for issue in result["issues"])


def test_performance_unavailable_is_not_dropped():
    summary = normal_summary()
    summary["performance"]["sample"]["cpu"]["1"] = {"status": "unavailable", "error": "decoder failed"}
    result = evaluation(normal_config(), summary)
    assert result["status"] == "partial"
    assert result["performance"]["status"] == "partial"


def test_short_repetition_count_is_incomplete():
    summary = normal_summary()
    result_value = summary["performance"]["sample"]["cpu"]["1"]
    result_value["native"] = {"count": 1}
    result_value["raw"]["native_seconds"] = [0.1]
    result = evaluation(normal_config(), summary)
    assert result["status"] == "partial"
    assert result["performance"]["incomplete"]


def test_empty_expected_set_cannot_pass():
    config = {"inputs": [], "devices": ["cpu"], "performance": {"enabled": False}}
    summary = {"device_status": {"cpu": {"status": "available"}}, "integrity": {"status": "pass"}}
    result = evaluation(config, summary, modes={"correctness"})
    assert result["status"] == "fail"
    assert "no expected correctness tasks" in result["issues"]


def test_performance_mode_requires_tasks():
    config = {"inputs": [{"id": "sample"}], "devices": ["cpu"], "performance": {"enabled": False}}
    summary = normal_summary()
    result = evaluation(config, summary, modes={"correctness", "performance"})
    assert result["status"] == "fail"
    assert "performance mode requested but performance is disabled" in result["issues"]
    assert result["performance"]["status"] == "fail"


def test_missing_performance_result_cannot_pass():
    summary = normal_summary()
    del summary["performance"]["sample"]["cpu"]["1"]
    result = evaluation(normal_config(), summary)
    assert result["status"] == "partial"
    assert "performance:sample/cpu/batch1" in result["missing"]


def test_time_mapping_is_independent_of_returned_frame_pts():
    intervals = [
        {"pts_seconds": 0.0, "duration_seconds": 1 / 30},
        {"pts_seconds": 1 / 30, "duration_seconds": 1 / 30},
        {"pts_seconds": 2 / 30, "duration_seconds": 1 / 30},
    ]
    mapping = map_time_to_ordinal(0.0, intervals)
    assert mapping["status"] == "ok"
    assert mapping["ordinal"] == 0
    assert expected_ordinal_for_time(0.0, 30, 3) == 0
    # Both paths could return the next frame; the independent contract must reject it.
    assert time_matches(1 / 30, mapping) is False
    assert time_matches(0.0, mapping) is True
    mid = map_time_to_ordinal(0.5 / 30, intervals)
    assert mid["ordinal"] == 0
    boundary = map_time_to_ordinal(1 / 30, intervals)
    assert boundary["ordinal"] == 1
    assert map_time_to_ordinal(3 / 30, intervals)["status"] == "out_of_range"


def test_nonuniform_or_gapped_intervals_are_unverified():
    intervals = [
        {"pts_seconds": 0.0, "duration_seconds": 1 / 30},
        {"pts_seconds": 2 / 30, "duration_seconds": 1 / 30},
    ]
    assert map_time_to_ordinal(1 / 30, intervals)["status"] == "unverified"
    assert map_time_to_ordinal(0.0, [{"pts_seconds": 0.0, "duration_seconds": 0.0}])["status"] == "unverified"


class FakeFrame:
    shape = (3, 4, 5)
    dtype = "torch.uint8"
    device = "cuda:0"


def test_raw_tensors_are_dropped_from_json_safe_time_results():
    result = safe_time_value(
        {
            "status": "ok",
            "frame": FakeFrame(),
            "device": "cuda:0",
            "pts_seconds": 0.0,
            "duration_seconds": 1 / 30,
        }
    )
    assert "frame" not in result
    assert result["shape"] == [3, 4, 5]
    assert json.loads(dumps(result))["device"] == "cuda:0"


def test_one_sided_error_is_serializable():
    result = safe_time_value({"status": "error", "error_type": "RuntimeError", "message": "decode failed"})
    assert json.loads(dumps(result))["status"] == "error"
    assert "frame" not in result


def test_both_paths_returning_next_frame_is_a_pts_mismatch():
    intervals = [
        {"pts_seconds": 0.0, "duration_seconds": 1 / 30},
        {"pts_seconds": 1 / 30, "duration_seconds": 1 / 30},
    ]
    mapping = map_time_to_ordinal(0.0, intervals)
    assert time_pts_status(mapping, 1 / 30, 1 / 30) == "pts_mismatch"
    assert time_pts_status(mapping, 0.0, 0.0) == "pass"
    end = map_time_to_ordinal(2 / 30, intervals)
    assert time_pts_status(end, None, None) == "expected_boundary_error"
    assert time_pts_status(end, 2 / 30, None) == "device_disagreement"


def test_write_artifacts_survives_a_partial_summary(tmp_path):
    import importlib.util

    path = __import__("pathlib").Path(__file__).parents[1] / "research" / "benchmark_gpu_decode.py"
    spec = importlib.util.spec_from_file_location("benchmark_gpu_decode_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "environment.json").write_text("{}", encoding="utf-8")
    summary = {
        "status": "partial",
        "correctness": {},
        "performance": {},
        "controls": {"counts": {}},
        "integrity": {"before": {}, "after": {}, "unchanged": None, "status": "unknown"},
        "limitations": "bounded test",
        "evaluation": {"status": "partial"},
    }
    module.write_artifacts(tmp_path, summary, {}, {"counts": {}}, [])
    assert json.loads((tmp_path / "summary.json").read_text())["status"] == "partial"
    assert json.loads((tmp_path / "source-integrity.json").read_text())["status"] == "unknown"
    assert (tmp_path / "evidence.zip").is_file()
