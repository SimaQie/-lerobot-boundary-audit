"""Device-neutral frame metrics for the standalone GPU decode experiment.

The helpers accept arrays and never import torch, so the normal CPU audit
install can use them without pulling in CUDA.  They do not decide that a GPU
decoder is correct; they only expose the raw and colour-range-adjusted RGB
differences next to an independent ordinal reference.
"""

from __future__ import annotations

import math

APPROXIMATE_MAX_MAE = 2.0
APPROXIMATE_MIN_SEPARATION = 0.25
LIMITED_RANGE_OFFSET = 16.0
LIMITED_RANGE_SCALE = 255.0 / 219.0


def _numpy():
    try:
        import numpy
    except ImportError as exc:
        raise ImportError("GPU benchmark metrics need numpy in the consumer environment") from exc
    return numpy


def to_hwc_uint8(frame):
    """Normalise a decoded frame to contiguous HWC uint8 RGB."""
    np = _numpy()
    array = np.asarray(frame)
    if array.ndim != 3:
        raise ValueError("A frame must be a 3-dimensional array")
    if array.shape[2] not in (1, 3, 4) and array.shape[0] in (1, 3, 4):
        array = np.moveaxis(array, 0, -1)
    if array.shape[2] == 4:
        array = array[..., :3]
    if array.shape[2] != 3:
        raise ValueError("A frame must have three RGB channels")
    if array.dtype != np.uint8:
        if np.issubdtype(array.dtype, np.floating) and np.isfinite(array).all() and array.max() <= 1.0:
            array = array * 255.0
        array = np.clip(np.rint(array), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(array)


def limited_to_full(frame):
    """Map TV-range RGB (16..235) to full range without hiding raw differences."""
    np = _numpy()
    return np.clip((to_hwc_uint8(frame).astype(np.float32) - LIMITED_RANGE_OFFSET) * LIMITED_RANGE_SCALE, 0, 255)


def rgb_difference(actual, reference) -> dict:
    np = _numpy()
    actual_u8, reference_u8 = to_hwc_uint8(actual), to_hwc_uint8(reference)
    if actual_u8.shape != reference_u8.shape:
        return {"shape_mismatch": [list(actual_u8.shape), list(reference_u8.shape)]}
    difference = np.abs(actual_u8.astype(np.float32) - reference_u8.astype(np.float32))
    return {
        "exact": bool(np.array_equal(actual_u8, reference_u8)),
        "mean_absolute_error": float(difference.mean()),
        "max_absolute_error": float(difference.max()),
        "channel_mean_absolute_error": [float(value) for value in difference.reshape(-1, 3).mean(axis=0)],
        "actual_min_max": [int(actual_u8.min()), int(actual_u8.max())],
        "reference_min_max": [int(reference_u8.min()), int(reference_u8.max())],
    }


def _distances(actual, references):
    np = _numpy()
    result = {}
    for index, reference in references.items():
        candidate = to_hwc_uint8(reference)
        if candidate.shape != actual.shape:
            continue
        result[index] = float(np.abs(actual.astype(np.float32) - candidate.astype(np.float32)).mean())
    return result


def _decision(distances: dict[int, float], expected_index: int) -> tuple[str, int | None, float | None]:
    if not distances:
        return "no_comparable_reference", None, None
    ranked = sorted(distances, key=distances.get)
    best = ranked[0]
    separation = float(distances[ranked[1]] - distances[best]) if len(ranked) > 1 else float("inf")
    if distances[best] > APPROXIMATE_MAX_MAE or separation < APPROXIMATE_MIN_SEPARATION:
        return "ambiguous", best, separation
    return ("pass" if best == expected_index else "wrong_frame"), best, separation


def compare_frame(
    actual,
    references: dict,
    expected_index: int,
    *,
    allow_limited_range: bool = False,
) -> dict:
    """Compare one decoded frame with ordinal neighbours.

    Exact equality is checked before any approximate rule.  For CUDA output the
    caller may allow the documented limited-to-full conversion; both raw and
    adjusted metrics are always returned, and the successful rule is named.
    """
    np = _numpy()
    actual_u8 = to_hwc_uint8(actual)
    comparable = {
        index: to_hwc_uint8(frame)
        for index, frame in references.items()
        if to_hwc_uint8(frame).shape == actual_u8.shape
    }
    if not comparable:
        return {
            "status": "wrong_shape",
            "expected_index": expected_index,
            "reason": "no reference frame has the decoded shape",
            "references": sorted(references),
        }

    exact = sorted(index for index, frame in comparable.items() if np.array_equal(actual_u8, frame))
    if exact and expected_index not in exact:
        return {
            "status": "wrong_frame",
            "expected_index": expected_index,
            "match": "exact",
            "matched_indices": exact,
            "reason": "exact matches exclude the expected frame",
        }
    if len(exact) > 1:
        return {
            "status": "ambiguous",
            "expected_index": expected_index,
            "match": "exact",
            "matched_indices": exact,
            "reason": "identical neighbouring frames",
        }
    if exact == [expected_index]:
        return {
            "status": "pass",
            "expected_index": expected_index,
            "match": "exact",
            "matched_index": expected_index,
            "raw": rgb_difference(actual_u8, comparable[expected_index]),
            "color_range_adjustment": False,
        }

    raw_distances = _distances(actual_u8, comparable)
    raw_status, raw_best, raw_separation = _decision(raw_distances, expected_index)
    adjusted = limited_to_full(actual_u8) if allow_limited_range else None
    adjusted_distances = _distances(adjusted, comparable) if adjusted is not None else {}
    adjusted_status, adjusted_best, adjusted_separation = _decision(adjusted_distances, expected_index)

    raw_metrics = rgb_difference(actual_u8, comparable[expected_index]) if expected_index in comparable else {}
    adjusted_metrics = (
        rgb_difference(adjusted, comparable[expected_index])
        if adjusted is not None and expected_index in comparable
        else {}
    )
    result = {
        "expected_index": expected_index,
        "raw": {
            "status": raw_status,
            "distances": {str(k): round(v, 6) for k, v in raw_distances.items()},
            "matched_index": raw_best,
            "separation": float(raw_separation) if math.isfinite(raw_separation) else None,
            "against_expected": raw_metrics,
        },
        "limited_range_adjusted": {
            "status": adjusted_status,
            "distances": {str(k): round(v, 6) for k, v in adjusted_distances.items()},
            "matched_index": adjusted_best,
            "separation": float(adjusted_separation) if math.isfinite(adjusted_separation) else None,
            "against_expected": adjusted_metrics,
        }
        if allow_limited_range
        else None,
        "color_range_adjustment": False,
    }
    if raw_status in {"pass", "wrong_frame"}:
        result.update(status=raw_status, match="rgb", matched_index=raw_best)
        return result
    if allow_limited_range and adjusted_status in {"pass", "wrong_frame"}:
        result.update(status=adjusted_status, match="limited_range_rgb", matched_index=adjusted_best, color_range_adjustment=True)
        return result
    reasons = ["raw RGB does not separate a unique neighbour"]
    if allow_limited_range:
        reasons.append("limited-to-full correction does not separate a unique neighbour")
    result.update(status="ambiguous", match=None, reason="; ".join(reasons))
    return result


def summarize_values(values: list[float]) -> dict:
    np = _numpy()
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": float(min(values)),
        "median": float(np.median(values)),
        "max": float(max(values)),
        "mean": float(np.mean(values)),
    }


def chunked(values: list, size: int) -> list[list]:
    if size <= 0:
        raise ValueError("Batch size must be positive")
    return [values[start : start + size] for start in range(0, len(values), size)]
