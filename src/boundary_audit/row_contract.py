"""Reader label checks without numeric coercion or a Torch dependency."""


def row_label_errors(actual, expected):
    errors = []
    for field in ("index", "episode_index", "frame_index"):
        value = actual[field]
        if type(value) is not int or value != expected[field]:
            errors.append(
                {
                    "kind": "row_identity",
                    "field": field,
                    "expected": expected[field],
                    "actual": value if type(value) in {int, str, bool, type(None)} else repr(value),
                    "reason": "non_integer" if type(value) is not int else "value_mismatch",
                }
            )
    return errors
