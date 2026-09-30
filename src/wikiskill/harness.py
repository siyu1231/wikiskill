"""Task loading, splits, prompt assembly, answer parsing, backend rollout.

Shared by ALL backends (design.md §3): prompt building with full skill
injection (paper §3.2.1), the ANSWER: output contract, and trace
normalization live here — not in adapters.
"""
from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path

from .backends.base import AgentBackend
from .prompts import INFERENCE_SYSTEM

ANSWER_HINT = "\n\nEnd your reply with one line exactly of the form: ANSWER: <answer>"


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
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            tasks.append(Task.from_dict(json.loads(line)))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            raise ValueError(
                f"{path} line {n}: {e} — expected one JSON object per line: "
                '{"id", "prompt", "expected"} (validate with: wikiskill tasks check)'
            ) from e
    return tasks


def save_tasks(tasks: list[Task], path: str | Path) -> None:
    Path(path).write_text(
        "\n".join(json.dumps({"id": t.id, "prompt": t.prompt, "expected": t.expected},
                             ensure_ascii=False) for t in tasks) + "\n",
        encoding="utf-8")


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


def build_prompt(skills_ctx: str, task: Task) -> str:
    """Full-injection setting: entire active skill text goes into the prompt
    (paper §3.2.1) — no retrieval, no symlinked skill dir for the inference run."""
    sys = INFERENCE_SYSTEM.format(skills=skills_ctx.strip() or "(no active skills)")
    return f"{sys}\n## Task\n{task.prompt}{ANSWER_HINT}"


_ANSWER_RE = re.compile(r"^\s*ANSWER:\s*(.*?)\s*$", re.I | re.M)


def parse_answer(stdout: str) -> str:
    """Last ANSWER: line wins; else last non-empty line; else empty."""
    if not stdout:
        return ""
    matches = _ANSWER_RE.findall(stdout)
    if matches:
        return matches[-1].strip()
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


class BackendRollout:
    """rollout(tasks, skills_ctx, iteration, split) -> traces — the single
    function the orchestrator knows about (design.md §3).

    Inference runs get workdir = <ws>/runs/work, a NEUTRAL cwd with no view of
    raw/ or wiki/ (paper §3.2: inference agent must not access the wiki; the
    only skill signal is the injected prompt).
    """

    def __init__(self, backend: AgentBackend, ws_root: str,
                 max_turns: int = 15, run_budget: int = 300,
                 workdir: str | None = None, verbose: bool = True,
                 toolsets: str | None = None, workers: int = 1):
        self.backend = backend
        self.ws_root = ws_root
        self.max_turns = max_turns
        self.run_budget = run_budget
        self.workdir = workdir or os.path.join(ws_root, "runs", "work")
        self.verbose = verbose
        # None = adapter's own default (core never encodes adapter vocab)
        self.toolsets = toolsets
        # >1: fan out backend.run calls (subprocess-per-task adapters make this
        # safe: each task owns its runs/<tag>/ dir). Trace order stays = task
        # order regardless of completion order.
        self.workers = max(1, int(workers))

    def _run_one(self, task: Task, skills_ctx: str, iteration: int,
                 split: str) -> dict:
        prompt = build_prompt(skills_ctx, task)
        tag = f"iter-{iteration:04d}-{split}-{task.id}"
        # harness-managed runs/ layout (design.md §8): every backend gets
        # the same on-disk artifacts for auditability, adapters only exec.
        run_dir = os.path.join(self.ws_root, "runs", tag)
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "query.txt"), "w", encoding="utf-8") as f:
            f.write(prompt)
        res = self.backend.run(self.ws_root, prompt, tag=tag,
                               toolsets=self.toolsets,
                               max_turns=self.max_turns, run_budget=self.run_budget,
                               workdir=self.workdir)
        stdout_path = res.stdout_path or os.path.join(run_dir, "stdout.txt")
        if not res.stdout_path:
            with open(stdout_path, "w", encoding="utf-8") as f:
                f.write(res.stdout)
        answer = parse_answer(res.stdout)
        trace = make_trace(task, answer)
        trace["run"] = {
            "backend": getattr(self.backend, "name", "?"),
            "tag": tag,
            "exit": res.exit_code,
            "duration_s": res.duration_s,
            "session": res.session_file,
        }
        return trace

    def _report(self, trace: dict, iteration: int, split: str) -> None:
        mark = "PASS" if trace["pass"] else "FAIL"
        print(f"  [{split} {iteration}] {trace['task_id']} {mark} "
              f"ans={trace['answer']!r} ({trace['run']['duration_s']}s)")

    def __call__(self, tasks: list[Task], skills_ctx: str, iteration: int, split: str) -> list[dict]:
        os.makedirs(self.workdir, exist_ok=True)
        if self.workers == 1 or len(tasks) <= 1:
            # serial: report each task as it finishes (live progress feedback)
            traces = []
            for t in tasks:
                trace = self._run_one(t, skills_ctx, iteration, split)
                traces.append(trace)
                if self.verbose:
                    self._report(trace, iteration, split)
            return traces
        # parallel: report live as tasks complete; collect in TASK order so
        # downstream (save_trace, gating) never depends on completion order
        from concurrent.futures import ThreadPoolExecutor, as_completed
        ordered: list[dict | None] = [None] * len(tasks)
        with ThreadPoolExecutor(max_workers=min(self.workers, len(tasks))) as ex:
            futs = {ex.submit(self._run_one, t, skills_ctx, iteration, split): i
                    for i, t in enumerate(tasks)}
            for fut in as_completed(futs):
                i = futs[fut]
                ordered[i] = fut.result()
                if self.verbose:
                    self._report(ordered[i], iteration, split)
        return [t for t in ordered if t is not None]


def _norm(s: str) -> str:
    return " ".join(str(s).strip().lower().split())
