"""Mock backend: deterministic, offline — for tests and `wikiskill evolve --backend mock`.

Two behaviors in one, selected by the prompt it receives:
- ACTOR prompts (carry the Maintainer/Proposer system prompt): return canned
  JSON so the full loop — patches, proposals, gating — runs offline.
- TASK prompts (rollouts): answered correctly iff the injected active-skill
  text contains the phrase the task needs. Lets the full CLI loop run with
  zero API cost and demonstrates accept + reject paths.
"""
from __future__ import annotations

import json
import os
import re

from .base import RunResult, register

# task prompt marker -> skill phrase that unlocks a correct answer
RULES = [("*", "multiply"), ("+", "add")]

MAINTAINER_CANNED = {
    "patches": [{
        "file": "patterns/multiplication.md", "op": "append",
        "text": "# Multiplication failures\nEvidence: agents answer 'idk' on a*b "
                "tasks unless a multiply skill is active.\n",
    }],
    "log_summary": "Root cause: no multiplication strategy in the active skill set.",
}

CREATE_MULTIPLY = {
    "proposal": {
        "action": "create", "skill": "multiply",
        "content": "# Multiply\n\nTo compute a * b, multiply the two numbers "
                   "and reply with the product.\n",
        "rationale": "train traces answered idk on every multiplication task",
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
    return (op, str(a * b if op == "*" else a + b))


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
            need = RULES[0][1] if op == "*" else RULES[1][1]
            if need in prompt:      # skill text was injected into the prompt
                answer = value
        elif "?" in prompt:
            answer = "42"
        out = f"(mock) reasoning about: {prompt.splitlines()[0][:60]}\nANSWER: {answer}"
        return self._ok(cmd, out)

    @staticmethod
    def _ok(cmd: list[str], stdout: str) -> RunResult:
        return RunResult(cmd=cmd, exit_code=0, stdout=stdout, duration_s=0.0)


register("mock", MockBackend)
