"""Scoring (P1). Paired bootstrap + macro-average land here in P3 (paper App. C).

Two metrics (workspace.json `metric`):

- ``exact`` (default, paper-faithful): mean exact-match accuracy — pass/fail per task.
  An abstention (e.g. ``verdict=unknown``) never matches the expected label, so it
  scores as a failure: the paper has no notion of selective prediction.

- ``selective`` (custom, abstention-aware): R = (correct − λ·abstain − μ·wrong) / N.
  Encodes an asymmetric preference: guessing wrong is the most expensive outcome (μ),
  admitting uncertainty costs only coverage (λ < μ), answering correctly earns full
  credit. A skill that abstains only where it would likely be wrong therefore scores
  higher than one that guesses everywhere — this is how "let the model flag its own
  uncertainty" gets optimized without touching Algorithm 1 (still a scalar, still
  strict ``>`` gating). λ > 0 keeps blanket abstention from ever being optimal:
  all-abstain scores −λ, while answering at accuracy p scores p − μ(1−p); the two
  cross at p = (μ−λ)/(1+μ), far below any competent model's accuracy.
"""
from __future__ import annotations

import re

# Abstention vocabulary: whatever the skill teaches, these strings mean
# "the model explicitly declined to give a definite verdict".
ABSTAIN_RE = re.compile(
    r"verdict=(unknown|uncertain|abstain|unsure)"
    r"|\b(uncertain|unclear|abstain(?:ed|ing)?|unsure|idk"
    r"|not\s+sure|i\s+don'?t\s+know|can'?t\s+(?:tell|determine|decide))\b"
    r"|(不确定|存疑|无法判断|弃权)",
    re.I,
)


def is_abstain(answer: str) -> bool:
    """True if the answer string is an explicit abstention (metric-agnostic)."""
    return bool(ABSTAIN_RE.search(answer or ""))


def outcome_of(trace: dict) -> str:
    """correct | abstain | wrong — metric-agnostic classification of one answer."""
    if trace.get("pass"):
        return "correct"
    return "abstain" if is_abstain(trace.get("answer") or "") else "wrong"


def accuracy(traces: list[dict]) -> float:
    if not traces:
        return 0.0
    return sum(1 for t in traces if t.get("pass")) / len(traces)


def selective_score(traces: list[dict], abstain: float = 0.25, wrong: float = 1.0) -> float:
    if not traces:
        return 0.0
    total = 0.0
    for t in traces:
        o = outcome_of(t)
        total += 1.0 if o == "correct" else (-abstain if o == "abstain" else -wrong)
    return total / len(traces)


def score(traces: list[dict], metric: dict | None) -> float:
    """The gating scalar. metric=None / {"name": "exact"} -> paper metric."""
    if (metric or {}).get("name", "exact") == "selective":
        return selective_score(
            traces,
            abstain=float(metric.get("abstain", 0.25)),   # type: ignore[union-attr]
            wrong=float(metric.get("wrong", 1.0)),        # type: ignore[union-attr]
        )
    return accuracy(traces)


def select_stats(traces: list[dict]) -> dict:
    """Tri-metric report for selective workspaces: coverage / abstain rate /
    accuracy among answered. Also useful under exact (reported as extra)."""
    n = len(traces)
    if not n:
        return {"n": 0, "correct": 0, "abstain": 0, "wrong": 0,
                "coverage": 0.0, "abstain_rate": 0.0, "cond_acc": 0.0}
    c = sum(1 for t in traces if outcome_of(t) == "correct")
    a = sum(1 for t in traces if outcome_of(t) == "abstain")
    answered = n - a
    return {
        "n": n, "correct": c, "abstain": a, "wrong": n - c - a,
        "coverage": answered / n,
        "abstain_rate": a / n,
        "cond_acc": c / answered if answered else 0.0,
    }
