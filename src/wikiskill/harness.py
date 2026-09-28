"""Task loading, splits, rollout scoring (P2 wires real backends; P1 uses scripted runners)."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Task:
    id: str
    prompt: str
    expected: str

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(id=str(d["id"]), prompt=str(d["prompt"]), expected=str(d["expected"]))


def load_tasks(path: str | Path) -> list[Task]:
    tasks = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            tasks.append(Task.from_dict(json.loads(line)))
    return tasks


def split_tasks(tasks: list[Task], val_ratio: float = 0.34, seed: int = 42) -> tuple[list[Task], list[Task]]:
    """Deterministic D_train / D_val split (design.md §4 #4: gating must never see train)."""
    idx = list(range(len(tasks)))
    random.Random(seed).shuffle(idx)
    n_val = max(1, int(round(len(tasks) * val_ratio))) if len(tasks) > 1 else 0
    val_ids = set(idx[:n_val])
    val = [tasks[i] for i in idx if i in val_ids]
    train = [tasks[i] for i in idx if i not in val_ids]
    return train, val


def make_trace(task: Task, answer: str) -> dict:
    return {
        "task_id": task.id,
        "prompt": task.prompt,
        "expected": task.expected,
        "answer": answer,
        "pass": _norm(answer) == _norm(task.expected),
    }


def _norm(s: str) -> str:
    return " ".join(str(s).strip().lower().split())
