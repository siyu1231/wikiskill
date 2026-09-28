"""WikiMaintainer (one-shot consolidation) and SkillProposer (ReAct + read_file)."""
from __future__ import annotations

import json
from typing import Callable

from .llm import LLM, extract_json
from .prompts import MAINTAINER_SYSTEM, PROPOSER_SYSTEM, OUTCOME_SUMMARY_PROMPT
from .skills import Proposal, ProposalError, SkillSet
from .workspace import TRACE_CAP, Workspace, WorkspaceError

# paper App. C: up to 8 traces/iteration — max 5 failing + max 3 passing
MAX_FAILING = 5
MAX_PASSING = 3
PROPOSER_MAX_TURNS = 12


def stratified_sample(traces: list[dict]) -> list[dict]:
    failing = [t for t in traces if not t.get("pass")]
    passing = [t for t in traces if t.get("pass")]
    picked = failing[:MAX_FAILING] + passing[:MAX_PASSING]
    out = []
    for t in picked:
        t = dict(t)
        for key in ("prompt", "answer", "reasoning", "messages", "log"):
            if isinstance(t.get(key), str) and len(t[key]) > TRACE_CAP:
                t[key] = t[key][:TRACE_CAP] + "\n…[truncated]"
        out.append(t)
    return out


def _compact(traces: list[dict], cap: int = TRACE_CAP) -> str:
    parts = []
    for t in traces:
        slim = {k: v for k, v in t.items() if not k.startswith("_")}
        s = json.dumps(slim, ensure_ascii=False, indent=1)
        parts.append(s if len(s) <= cap else s[:cap] + "\n…[truncated]")
    return "\n\n".join(parts)


class WikiMaintainer:
    """W'_k <- M_WM(W_{k-1}, T_sample,k)  (paper §3.2.2, one LLM call)."""

    def __init__(self, llm: LLM, ws: Workspace):
        self.llm = llm
        self.ws = ws

    def _wiki_context(self) -> str:
        parts = []
        for rel in ["index.md", "logs.md"]:
            txt = self.ws.read_wiki(rel)
            if txt:
                parts.append(f"--- wiki/{rel}\n{txt[:TRACE_CAP]}")
        for name in self.ws.list_patterns():
            txt = self.ws.read_wiki(f"patterns/{name}.md") or ""
            parts.append(f"--- wiki/patterns/{name}.md\n{txt[:TRACE_CAP]}")
        return "\n\n".join(parts) or "(empty wiki)"

    def consolidate(self, sampled: list[dict]) -> int:
        user = (
            f"## Current wiki\n{self._wiki_context()}\n\n"
            f"## Sampled traces (stratified)\n{_compact(sampled)}\n\n"
            "Return the JSON patches now."
        )
        reply = self.llm.chat([{"role": "user", "content": user}], system=MAINTAINER_SYSTEM)
        data = extract_json(reply)
        applied = 0
        if not isinstance(data, dict):
            return 0
        for patch in data.get("patches", []) or []:
            try:
                self._apply_patch(patch)
                applied += 1
            except (WorkspaceError, ProposalError, KeyError, TypeError, AttributeError):
                continue
        if data.get("index_text"):
            self.ws.write_wiki("index.md", str(data["index_text"]))
        if data.get("log_summary"):
            self.ws.append_log(str(data["log_summary"]))
        return applied

    def _apply_patch(self, patch: dict) -> None:
        rel = str(patch["file"])
        if rel.startswith("wiki/"):
            rel = rel[5:]
        op = patch.get("op")
        current = self.ws.read_wiki(rel)
        text = str(patch.get("text", ""))
        if op == "append":
            self.ws.write_wiki(rel, (current or "") + text)
        elif op == "replace":
            old = str(patch["old"])
            if current is None or current.count(old) != 1:
                raise WorkspaceError("replace: old span missing or not unique")
            self.ws.write_wiki(rel, current.replace(old, text, 1))
        elif op == "insert_after":
            anchor = str(patch["anchor"])
            if current is None or current.count(anchor) != 1:
                raise WorkspaceError("insert_after: anchor missing or not unique")
            i = current.index(anchor) + len(anchor)
            self.ws.write_wiki(rel, current[:i] + text + current[i:])
        else:
            raise WorkspaceError(f"unknown op: {op!r}")


class SkillProposer:
    """P_k <- M_P(W'_k, S_{k-1}, T_train,k)  (paper §3.2.3, ReAct with read_file)."""

    def __init__(self, llm: LLM, ws: Workspace, skills: SkillSet):
        self.llm = llm
        self.ws = ws
        self.skills = skills

    def propose(self, train_traces: list[dict], iteration: int) -> Proposal | None:
        summary = "\n".join(
            f"- {t.get('task_id', '?')}: {'PASS' if t.get('pass') else 'FAIL'}"
            f" | pred={t.get('answer')!r} gt={t.get('expected')!r}"
            for t in train_traces
        ) or "(no traces)"
        messages: list[dict] = [{
            "role": "user",
            "content": (
                f"## wiki/index.md\n{(self.ws.read_wiki('index.md') or '')[:TRACE_CAP]}\n\n"
                f"## wiki/skill-impact.md\n{self.ws.read_skill_impact()[:TRACE_CAP]}\n\n"
                f"## active skills\n{(self.skills.full_context() or '(none)')[:TRACE_CAP]}\n\n"
                + OUTCOME_SUMMARY_PROMPT.format(iteration=iteration, summary=summary)
            ),
        }]
        for _ in range(PROPOSER_MAX_TURNS):
            reply = self.llm.chat(messages, system=PROPOSER_SYSTEM)
            data = extract_json(reply)
            if not isinstance(data, dict):
                return None
            if data.get("tool") == "read_file":
                try:
                    result = self.ws.read_file(str(data.get("path", "")))
                except WorkspaceError as e:
                    result = f"ERROR: {e}"
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": f"read_file result:\n{result}"})
                continue
            if "proposal" in data:
                try:
                    return Proposal.from_dict(data["proposal"])
                except ProposalError:
                    return None
            return None
        return None
