"""How concentrated a marked book is.

Ghostfolio-style wealth software shows the mix. This one also keeps the
Indian exit cost next to the weight, because a large line is expensive
to leave as well as risky to hold. Weights use marked value, not what
was paid.
"""

from __future__ import annotations


def summarize(rows: list[dict]) -> dict:
    """Summarise marked rows. Each row needs name, value, and invested."""
    invested = round(sum(float(row["invested"]) for row in rows), 2)
    value = round(sum(float(row["value"]) for row in rows), 2)
    if value <= 0:
        weights = [0.0 for _ in rows]
    else:
        weights = [float(row["value"]) / value for row in rows]
    order = sorted(zip(rows, weights), key=lambda pair: pair[1], reverse=True)
    top = order[0] if order else (None, 0.0)
    by_platform: dict[str, float] = {}
    by_kind: dict[str, float] = {}
    for row, weight in order:
        by_platform[row.get("platform", "other")] = by_platform.get(row.get("platform", "other"), 0.0) + weight
        by_kind[row.get("kind", "other")] = by_kind.get(row.get("kind", "other"), 0.0) + weight
    return {
        "invested": invested,
        "value": value,
        "pnl": round(value - invested, 2),
        "return": (value / invested - 1) if invested else 0.0,
        "top_name": None if top[0] is None else top[0]["name"],
        "top_weight": round(top[1], 4),
        "herfindahl": round(sum(weight * weight for weight in weights), 4),
        "by_platform": {key: round(weight, 4) for key, weight in by_platform.items()},
        "by_kind": {key: round(weight, 4) for key, weight in by_kind.items()},
        "lines": [
            {**row, "weight": round(weight, 4)}
            for row, weight in order
        ],
    }
