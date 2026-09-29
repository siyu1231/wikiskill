"""Mock backend: deterministic, offline — for tests and `wikiskill evolve --backend mock`.

Two behaviors in one, selected by the prompt it receives:
- ACTOR prompts (carry the Maintainer/Proposer system prompt): return canned
  JSON so the full loop — patches, proposals, gating — runs offline.
- TASK prompts (rollouts): answered in the team format ONLY iff the injected
  active-skill text contains the phrase the task needs (mirrors the
  convention-dependent demo bench). Zero API cost, demonstrates accept+reject.
"""
from __future__ import annotations

import json
import os
import re

from .base import RunResult, register

# operator -> (skill phrase that unlocks it, expected-answer template)
RULES = {
    "*": ("multiply", "product={value}"),
    "+": ("add", "sum={value}"),
}

MAINTAINER_CANNED = {
    "patches": [{
        "file": "patterns/multiplication.md", "op": "append",
        "text": "# Multiplication format failures\nEvidence: agents computed the right "
                "number but never emitted the required product=<value> format.\n",
    }],
    "log_summary": "Root cause: no skill states the answer-format convention.",
}

CREATE_MULTIPLY = {
    "proposal": {
        "action": "create", "skill": "multiply",
        "content": "# Multiply\n\nMultiply the two numbers.\n\n"
                   "Answer format for multiplication results: `product=<value>` "
                   "(exact prefix, no spaces).\n",
        "rationale": "train traces failed on the required product= format",
        "source_patterns": ["multiplication"],
    }
}

CREATE_JUNK = {
    "proposal": {
        "action": "create", "skill": "color",
        "content": "# Color\n\nPrefer blue.\n",
        "rationale": "unrelated idea (demo of a rejected proposal)",
    }
}


def _expected_from_prompt(prompt: str) -> tuple[str, str] | None:
    m = re.search(r"(-?\d+)\s*([*+])\s*(-?\d+)", prompt)
    if not m:
        return None
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    return op, str(a * b if op == "*" else a + b)


class MockBackend:
    name = "mock"

    def bootstrap(self, ws_root: str) -> None:
        os.makedirs(os.path.join(ws_root, "runs"), exist_ok=True)

    def run(self, ws_root: str, prompt: str, *, tag: str,
            toolsets: str | None = None, max_turns: int = 15,
            run_budget: int = 300, workdir: str | None = None,
            dry_run: bool = False) -> RunResult:
        cmd = ["mock-backend", "--tag", tag]
        if dry_run:
            return RunResult(cmd=cmd, dry_run=True)

        # --- actor roles (runner="backend") ---
        if "You are the Wiki Maintainer" in prompt:
            return self._ok(cmd, json.dumps(MAINTAINER_CANNED, ensure_ascii=False))
        if "You are the Skill Proposer" in prompt:
            active = prompt.split("## active skills", 1)[-1][:400]
            body = CREATE_MULTIPLY if "(none)" in active else CREATE_JUNK
            return self._ok(cmd, json.dumps(body, ensure_ascii=False))

        # --- inference rollout ---
        exp = _expected_from_prompt(prompt)
        answer = "idk"
        if exp is not None:
            op, value = exp
            need, tpl = RULES[op]
            # correct only if the convention-carrying skill was injected
            answer = tpl.format(value=value) if need in prompt else value
        elif "?" in prompt:
            answer = "42"
        out = f"(mock) reasoning about: {prompt.splitlines()[0][:60]}\nANSWER: {answer}"
        return self._ok(cmd, out)

    @staticmethod
    def _ok(cmd: list[str], stdout: str) -> RunResult:
        return RunResult(cmd=cmd, exit_code=0, stdout=stdout, duration_s=0.0)


register("mock", MockBackend)
