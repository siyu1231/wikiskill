"""Skills layer: atomic proposals, apply, snapshot/rollback (skills only — never the wiki).

A proposal targets ONE skill (paper §3.2.3 "atomic proposal"):
  action="create"  -> new skill dir with SKILL.md + PURPOSE.md
  action="edit"    -> find/replace within an existing SKILL.md (old span must be unique)
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class ProposalError(ValueError):
    pass


@dataclass
class Proposal:
    action: str                      # "create" | "edit"
    skill: str                       # skill name (dir under skills/)
    rationale: str = ""              # why (traces/patterns that motivate it)
    source_patterns: list[str] = field(default_factory=list)
    content: str | None = None       # create: full SKILL.md body
    old: str | None = None           # edit: span to find (must be unique)
    new: str | None = None           # edit: replacement

    @classmethod
    def from_dict(cls, d: dict) -> "Proposal":
        p = cls(
            action=str(d.get("action", "")),
            skill=str(d.get("skill", "")),
            rationale=str(d.get("rationale", "")),
            source_patterns=[str(x) for x in d.get("source_patterns", [])],
            content=d.get("content"),
            old=d.get("old"),
            new=d.get("new"),
        )
        p.validate()
        return p

    def validate(self) -> None:
        if self.action not in ("create", "edit"):
            raise ProposalError(f"action must be create|edit, got {self.action!r}")
        if not NAME_RE.match(self.skill):
            raise ProposalError(f"illegal skill name: {self.skill!r}")
        if self.action == "create":
            if not self.content or not self.content.strip():
                raise ProposalError("create requires non-empty content")
            if len(self.content) > 60_000:
                raise ProposalError("content too large")
        else:
            if not self.old or self.old == self.new:
                raise ProposalError("edit requires old != new, non-empty old")
            if self.new is None:
                raise ProposalError("edit requires new")

    def to_markdown(self) -> str:
        lines = [f"- action: `{self.action}`, skill: `{self.skill}`"]
        if self.rationale:
            lines.append(f"  rationale: {self.rationale}")
        if self.source_patterns:
            lines.append("  patterns: " + ", ".join(self.source_patterns))
        return "\n".join(lines)


class SkillSet:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    # ---------- read ----------
    def names(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir()) if self.root.is_dir() else []

    def skill_path(self, name: str) -> Path:
        if not NAME_RE.match(name):
            raise ProposalError(f"illegal skill name: {name!r}")
        return self.root / name

    def read(self, name: str) -> str:
        p = self.skill_path(name) / "SKILL.md"
        if not p.is_file():
            raise ProposalError(f"no such skill: {name}")
        return p.read_text(encoding="utf-8")

    def full_context(self) -> str:
        """Full skill set, for injection into the inference prompt (paper §3.2.1)."""
        parts = []
        for n in self.names():
            parts.append(f"### skill: {n}\n{self.read(n)}")
        return "\n\n".join(parts)

    # ---------- apply (atomic per proposal) ----------
    def apply(self, p: Proposal) -> str:
        """Apply one proposal; returns a unified diff. Raises ProposalError on invalid."""
        p.validate()
        d = self.skill_path(p.skill)
        if p.action == "create":
            if d.exists():
                raise ProposalError(f"skill already exists: {p.skill}")
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(p.content, encoding="utf-8")
            purpose = f"# Purpose\n\n{p.rationale or '(unspecified)'}\n"
            if p.source_patterns:
                purpose += "\nInspired by wiki patterns: " + ", ".join(p.source_patterns) + "\n"
            (d / "PURPOSE.md").write_text(purpose, encoding="utf-8")
            return f"--- /dev/null\n+++ skills/{p.skill}/SKILL.md\n" + "".join(
                f"+{l}\n" for l in p.content.splitlines()
            )
        # edit
        f = d / "SKILL.md"
        if not f.is_file():
            raise ProposalError(f"no such skill: {p.skill}")
        before = f.read_text(encoding="utf-8")
        n = before.count(p.old)
        if n == 0:
            raise ProposalError("old span not found in SKILL.md")
        if n > 1:
            raise ProposalError(f"old span not unique ({n} occurrences)")
        after = before.replace(p.old, p.new, 1)
        f.write_text(after, encoding="utf-8")
        return "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile=f"skills/{p.skill}/SKILL.md(old)", tofile=f"skills/{p.skill}/SKILL.md(new)",
            )
        )

    # ---------- snapshot / rollback (SKILLS ONLY) ----------
    def snapshot(self) -> dict[str, str]:
        return {n: self.read(n) for n in self.names()}

    def restore(self, snap: dict[str, str]) -> None:
        current = set(self.names())
        for n in current - set(snap):
            _rm_tree(self.root / n)
        for n, content in snap.items():
            d = self.root / n
            d.mkdir(parents=True, exist_ok=True)
            if not (d / "PURPOSE.md").exists():
                (d / "PURPOSE.md").write_text("# Purpose\n(rolled back)\n", encoding="utf-8")
            (d / "SKILL.md").write_text(content, encoding="utf-8")


def _rm_tree(p: Path) -> None:
    import shutil
    if p.is_dir():
        shutil.rmtree(p)
