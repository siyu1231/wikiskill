"""Accuracy scoring (P1). Paired bootstrap + macro-average land here in P3 (paper App. C)."""
from __future__ import annotations


def accuracy(traces: list[dict]) -> float:
    if not traces:
        return 0.0
    return sum(1 for t in traces if t.get("pass")) / len(traces)
