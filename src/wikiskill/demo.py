"""Bundled demo task set (12 auto-graded tasks, convention-dependent).

The expected answer carries a team-specific FORMAT convention
(`product=<n>` / `sum=<n>`) that the prompt explicitly defers to the active
skills: without a skill the agent cannot know the format and fails; with the
evolved skill it passes. This is what makes skill evolution observable on a
demo bench regardless of how strong the base model is (a pure-arithmetic bench
would just early-stop at baseline=1.0 — observed with a real backend).

Placeholder bench until P3 ships real benchmarks with train/val/test splits.
Format: one JSON object per line.
"""
from __future__ import annotations

import json
from pathlib import Path

from .harness import Task

_FMT = "Reply using the team answer format defined in your skills (the exact prefix matters)."

_DEMO = [
    ("d01", f"Compute 23 * 17. {_FMT}", "product=391"),
    ("d02", f"Compute 14 * 6. {_FMT}", "product=84"),
    ("d03", f"Compute 7 * 8. {_FMT}", "product=56"),
    ("d04", f"Compute 12 * 12. {_FMT}", "product=144"),
    ("d05", f"Compute 9 * 9. {_FMT}", "product=81"),
    ("d06", f"Compute 15 * 7. {_FMT}", "product=105"),
    ("d07", f"Compute 100 + 200. {_FMT}", "sum=300"),
    ("d08", f"Compute 34 + 57. {_FMT}", "sum=91"),
    ("d09", f"Compute 7 + 9. {_FMT}", "sum=16"),
    ("d10", f"Compute 250 + 125. {_FMT}", "sum=375"),
    ("d11", f"Compute 8 + 8. {_FMT}", "sum=16"),
    ("d12", f"Compute 63 + 19. {_FMT}", "sum=82"),
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
