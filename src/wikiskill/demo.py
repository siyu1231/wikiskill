"""Bundled demo task set (12 auto-graded arithmetic tasks).

Placeholder bench until P3 ships real benchmarks with train/val/test splits —
these exist so `wikiskill init` works out of the box and the mock backend can
demonstrate the full loop offline. Format: one JSON object per line.
"""
from __future__ import annotations

import json
from pathlib import Path

from .harness import Task

_DEMO = [
    ("d01", "Compute 23 * 17 and reply with only the number.", "391"),
    ("d02", "Compute 14 * 6 and reply with only the number.", "84"),
    ("d03", "Compute 7 * 8 and reply with only the number.", "56"),
    ("d04", "Compute 12 * 12 and reply with only the number.", "144"),
    ("d05", "Compute 9 * 9 and reply with only the number.", "81"),
    ("d06", "Compute 15 * 7 and reply with only the number.", "105"),
    ("d07", "Compute 100 + 200 and reply with only the number.", "300"),
    ("d08", "Compute 34 + 57 and reply with only the number.", "91"),
    ("d09", "Compute 7 + 9 and reply with only the number.", "16"),
    ("d10", "Compute 250 + 125 and reply with only the number.", "375"),
    ("d11", "Compute 8 + 8 and reply with only the number.", "16"),
    ("d12", "Compute 63 + 19 and reply with only the number.", "82"),
]


def demo_tasks() -> list[Task]:
    return [Task(id=i, prompt=p, expected=e) for i, p, e in _DEMO]


def write_demo_tasks(path: str | Path) -> int:
    tasks = demo_tasks()
    Path(path).write_text(
        "\n".join(json.dumps({"id": t.id, "prompt": t.prompt, "expected": t.expected},
                             ensure_ascii=False) for t in tasks) + "\n",
        encoding="utf-8")
    return len(tasks)
