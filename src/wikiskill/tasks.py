"""Task-set authoring spec + `wikiskill tasks check` (the gate before init).

Spec (documented in skill/SKILL.md — keep the two in sync):
- one JSON object per line: {"id", "prompt", "expected"}
- id: [A-Za-z0-9._-] only, unique — ids become runs/<tag> dir names
- prompt: self-contained; the answer must be uniquely determined by it
- expected: single line; graded by EXACT match after case/whitespace
  normalization — no regex, no numeric tolerance, no LLM judge
- >= 2 tasks required for the train/val split; >= 20 recommended (val is 34%,
  so small N makes the gating score jump in big steps)
- failure must be attributable: the wiki maintainer has to be able to root-cause
  a trace, otherwise patterns can't form and proposals become guesses
- skill-dependent info (conventions, formats, rules) belongs in the evolved
  skill, NOT in the prompt — otherwise baseline already passes
- whoever authors `expected` (agent or human) must verify it with tools:
  the task author and the solver may be the same model
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .doctor import Check
from .harness import Task, split_tasks

_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_MAX_LISTED = 5


def _norm(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


def check_tasks(path: str | Path, seed: int = 42) -> list[Check]:
    p = Path(path)
    if not p.exists():
        return [Check("file", False, f"not found: {p}")]

    lines = p.read_text(encoding="utf-8").splitlines()
    rows: list[tuple[int, str, str, str]] = []   # (lineno, id, prompt, expected)
    parse_errs: list[str] = []
    for n, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s:
            continue
        try:
            d = json.loads(s)
        except json.JSONDecodeError as e:
            parse_errs.append(f"line {n}: invalid JSON ({e.msg}, col {e.colno})")
            continue
        if not isinstance(d, dict):
            parse_errs.append(f"line {n}: expected a JSON object, got {type(d).__name__}")
            continue
        missing = [k for k in ("id", "prompt", "expected") if k not in d]
        if missing:
            parse_errs.append(f"line {n}: missing field(s) {', '.join(missing)}")
            continue
        rows.append((n, str(d["id"]), str(d["prompt"]), str(d["expected"])))

    out: list[Check] = []
    err_detail = "; ".join(parse_errs[:_MAX_LISTED])
    if len(parse_errs) > _MAX_LISTED:
        err_detail += f" (+{len(parse_errs) - _MAX_LISTED} more)"
    out.append(Check("parse", not parse_errs,
                     f"{len(rows)} tasks parsed" if not parse_errs else err_detail))

    # ---- id rules (filesystem safety + uniqueness) ----
    id_errs: list[str] = []
    first_seen: dict[str, int] = {}
    for n, tid, _pr, _ex in rows:
        if not _ID_RE.match(tid):
            id_errs.append(f"line {n}: id {tid!r} — only [A-Za-z0-9._-] "
                           "(ids name runs/ directories)")
        elif tid in first_seen:
            id_errs.append(f"line {n}: duplicate id {tid!r} (first at line {first_seen[tid]})")
        else:
            first_seen[tid] = n
    id_detail = "unique, filesystem-safe" if not id_errs else \
        "; ".join(id_errs[:_MAX_LISTED]) + \
        (f" (+{len(id_errs) - _MAX_LISTED} more)" if len(id_errs) > _MAX_LISTED else "")
    out.append(Check("ids", not id_errs, id_detail))

    # ---- content rules ----
    content_errs: list[str] = []
    content_warns: list[str] = []
    for n, tid, prompt, expected in rows:
        if not prompt.strip():
            content_errs.append(f"line {n} ({tid}): prompt is empty")
        if not expected.strip():
            content_errs.append(f"line {n} ({tid}): expected is empty")
        elif "\n" in expected or "\r" in expected:
            content_errs.append(f"line {n} ({tid}): expected must be a single line "
                                "(the ANSWER: parser reads one line)")
        elif expected != expected.strip():
            content_warns.append(f"line {n} ({tid}): expected has leading/trailing "
                                 "whitespace — normalization strips it, drop it here")
        elif expected.rstrip()[-1:] in ".,;:!?" :
            content_warns.append(f"line {n} ({tid}): expected ends with punctuation "
                                 f"({expected!r}) — model will likely answer without it")
        # answer leaked into the prompt -> task passes with no skill at all
        if expected.strip() and _norm(expected) in _norm(prompt):
            content_warns.append(f"line {n} ({tid}): expected appears verbatim in the "
                                 "prompt — task passes without learning anything")
    c_warn = "; ".join(content_warns[:_MAX_LISTED]) + \
        (f" (+{len(content_warns) - _MAX_LISTED} more)" if len(content_warns) > _MAX_LISTED else "")
    out.append(Check("content", not content_errs,
                     "prompt/expected present, single-line" if not content_errs
                     else "; ".join(content_errs[:_MAX_LISTED])
                     + (f" (+{len(content_errs) - _MAX_LISTED} more)"
                        if len(content_errs) > _MAX_LISTED else "")))
    if content_warns:
        out.append(Check("grading-risk", False, c_warn, warn=True))

    # ---- size + split ----
    n = len(rows)
    if n < 2:
        out.append(Check("size", False, f"{n} tasks — need >= 2 for a train/val split"))
    else:
        tasks = [Task(id=tid, prompt=pr, expected=ex) for _n, tid, pr, ex in rows]
        train, val = split_tasks(tasks, seed=seed)
        out.append(Check("size", True,
                         f"{n} tasks -> train {len(train)} / val {len(val)} (seed {seed})"
                         + ("" if n >= 20 else f"  — small: <20 makes gating noisy")))
        if n < 20:
            out.append(Check("recommend", False,
                             f"N={n} < 20 — val has only {len(val)} tasks; "
                             "one flip moves the gate score by "
                             f"{1 / max(1, len(val)):.0%}", warn=True))
        if not train or not val:
            out.append(Check("split", False, "empty train or val split"))
    return out


def report(cs: list[Check], path: str | Path) -> int:
    print(f"tasks check: {Path(path).resolve()}")
    width = max(len(c.name) for c in cs)
    for c in cs:
        tag = "SKIP" if c.skipped else ("OK  " if c.ok else ("WARN" if c.warn else "FAIL"))
        print(f"[{tag}] {c.name:<{width}}  {c.detail}")
    n_warn = sum(1 for c in cs if c.warn and not c.skipped and not c.ok)
    failed = [c for c in cs if not c.ok and not c.skipped and not c.warn]
    print(f"---\n{len(cs)} checks: {len(cs) - len(failed) - n_warn} ok, "
          f"{n_warn} warnings, {len(failed)} failed")
    if not failed:
        print("next      : wikiskill init <dir> --tasks " + str(path))
    return 1 if failed else 0
