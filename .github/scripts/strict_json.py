"""JSON at service boundaries must not hide duplicate keys or nonfinite numbers."""

import json
import math


def loads(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"Duplicate JSON key: {key}")
            value[key] = item
        return value

    def nonfinite(value):
        raise ValueError(f"Nonfinite JSON number: {value}")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            return nonfinite(value)
        return number

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=finite_float)


def positive_integer(value):
    return type(value) is int and value > 0
