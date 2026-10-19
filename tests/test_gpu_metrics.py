import numpy as np

from boundary_audit.gpu_metrics import (
    chunked,
    compare_frame,
    limited_to_full,
    rgb_difference,
    summarize_values,
    to_hwc_uint8,
)


def frame(value):
    return np.full((4, 5, 3), value, dtype=np.uint8)


def test_layout_and_limited_range_conversion():
    chw = np.zeros((3, 4, 5), dtype=np.uint8)
    chw[0] = 16
    chw[1] = 126
    chw[2] = 235
    hwc = to_hwc_uint8(chw)
    assert hwc.shape == (4, 5, 3)
    converted = limited_to_full(hwc)
    assert converted[..., 0].min() == 0
    assert converted[..., 2].max() == 255
    assert abs(float(converted[..., 1].mean()) - 128.2) < 0.3


def test_exact_neighbour_rules_are_not_weakened_by_range_conversion():
    references = {0: frame(10), 1: frame(40), 2: frame(10)}
    wrong = compare_frame(frame(10), references, 1, allow_limited_range=True)
    assert wrong["status"] == "wrong_frame"
    assert wrong["matched_indices"] == [0, 2]
    ambiguous = compare_frame(frame(40), references, 0, allow_limited_range=True)
    assert ambiguous["status"] == "wrong_frame"


def test_limited_range_cuda_output_can_be_identified_without_hiding_raw_error():
    cpu = np.zeros((4, 5, 3), dtype=np.uint8)
    cpu[..., 0] = np.arange(20, dtype=np.uint8).reshape(4, 5) * 9
    cpu[..., 1] = 100
    cpu[..., 2] = 40
    cuda = np.clip(cpu.astype(np.float32) * 219 / 255 + 16.0, 0, 255).astype(np.uint8)
    references = {0: cpu, 1: np.roll(cpu, 1, axis=0), 2: np.full_like(cpu, 255)}
    result = compare_frame(cuda, references, 0, allow_limited_range=True)
    assert result["raw"]["status"] == "ambiguous"
    assert result["limited_range_adjusted"]["status"] == "pass"
    assert result["status"] == "pass"
    assert result["match"] == "limited_range_rgb"
    assert result["color_range_adjustment"] is True
    assert result["limited_range_adjusted"]["against_expected"]["mean_absolute_error"] < 2


def test_raw_cpu_output_is_not_range_adjusted_by_default():
    cpu = np.full((4, 5, 3), 200, dtype=np.uint8)
    shifted = np.clip(cpu.astype(np.float32) * 219 / 255 + 16.0, 0, 255).astype(np.uint8)
    references = {0: cpu, 1: np.full_like(cpu, 0), 2: np.full_like(cpu, 255)}
    result = compare_frame(shifted, references, 0)
    assert result["raw"]["status"] == "ambiguous"
    assert result["limited_range_adjusted"] is None


def test_rgb_difference_shape_mismatch_and_summaries():
    assert "shape_mismatch" in rgb_difference(np.zeros((2, 2, 3), np.uint8), np.zeros((3, 2, 3), np.uint8))
    metrics = rgb_difference(np.full((2, 2, 3), 10, np.uint8), np.full((2, 2, 3), 12, np.uint8))
    assert metrics["mean_absolute_error"] == 2
    assert metrics["max_absolute_error"] == 2
    assert summarize_values([]) == {"count": 0}
    assert summarize_values([1.0, 3.0])["median"] == 2.0
    assert chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
