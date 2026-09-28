"""Three-layer workspace (paper §3.1): immutable raw/, persistent wiki/, active skills/.

Invariants enforced here (design.md §1):
1. raw/ is append-only — save_trace() refuses to overwrite.
2. wiki/skill-impact.md is appended only via append_skill_impact() (orchestrator harness).
3. Rollback never touches this layer — skills live in skills.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

TRACE_CAP = 15_000  # chars, per App. C: cap before prompt injection


class WorkspaceError(RuntimeError):
    pass


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    # ---------- lifecycle ----------
    def create(self) -> "Workspace":
        for d in ("raw", "wiki", "wiki/patterns", "skills"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        idx = self.root / "wiki" / "index.md"
        if not idx.exists():
            idx.write_text("# Pattern Index\n", encoding="utf-8")
        log = self.root / "wiki" / "logs.md"
        if not log.exists():
            log.write_text("# Evolution Log\n", encoding="utf-8")
        si = self.root / "wiki" / "skill-impact.md"
        if not si.exists():
            si.write_text("# Skill Impact Tracker\n\n", encoding="utf-8")
        return self

    @classmethod
    def open(cls, root: str | Path) -> "Workspace":
        ws = cls(root)
        if not (ws.root / "raw").is_dir():
            raise WorkspaceError(f"not a wikiskill workspace: {root}")
        return ws

    @property
    def raw_dir(self) -> Path:
        return self.root / "raw"

    @property
    def wiki_dir(self) -> Path:
        return self.root / "wiki"

    @property
    def skills_dir(self) -> Path:
        return self.root / "skills"

    # ---------- raw layer (append-only) ----------
    def _trace_path(self, iteration: int, name: str, split: str) -> Path:
        if not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
            raise WorkspaceError(f"illegal trace name: {name!r}")
        return self.raw_dir / f"iter-{iteration:04d}" / f"{split}-{name}.json"

    def save_trace(self, iteration: int, name: str, split: str, trace: dict) -> Path:
        """Persist one execution trace. IMMUTABLE: raises if it already exists."""
        path = self._trace_path(iteration, name, split)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise WorkspaceError(f"raw layer is append-only: {path} exists")
        path.write_text(json.dumps(trace, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def iter_trace_paths(self, iteration: int | None = None) -> Iterator[Path]:
        if iteration is None:
            dirs = sorted(self.raw_dir.glob("iter-*"))
        else:
            d = self.raw_dir / f"iter-{iteration:04d}"
            dirs = [d] if d.is_dir() else []
        for d in dirs:
            yield from sorted(d.glob("*.json"))

    def load_traces(self, iteration: int | None = None, split: str | None = None) -> list[dict]:
        out = []
        for p in self.iter_trace_paths(iteration):
            if split and not p.name.startswith(f"{split}-"):
                continue
            t = json.loads(p.read_text(encoding="utf-8"))
            t["_file"] = str(p.relative_to(self.root))
            out.append(t)
        return out

    # ---------- wiki layer (monotonic) ----------
    def wiki_path(self, rel: str) -> Path:
        p = (self.wiki_dir / rel).resolve()
        if not str(p).startswith(str(self.wiki_dir.resolve())):
            raise WorkspaceError(f"wiki path escapes wiki/: {rel}")
        return p

    def read_wiki(self, rel: str) -> str | None:
        p = self.wiki_path(rel)
        return p.read_text(encoding="utf-8") if p.exists() else None

    def write_wiki(self, rel: str, content: str) -> Path:
        p = self.wiki_path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def list_patterns(self) -> list[str]:
        d = self.wiki_dir / "patterns"
        return sorted(p.stem for p in d.glob("*.md")) if d.is_dir() else []

    def append_log(self, text: str) -> None:
        log = self.wiki_dir / "logs.md"
        with log.open("a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n\n")

    def append_skill_impact(self, entry: str) -> None:
        """ORCHESTRATOR ONLY — the ground-truth audit trail (§3.2.4)."""
        p = self.wiki_dir / "skill-impact.md"
        with p.open("a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def read_skill_impact(self) -> str:
        return (self.wiki_dir / "skill-impact.md").read_text(encoding="utf-8")

    # ---------- scoped read (proposer tool) ----------
    def read_file(self, rel: str) -> str:
        """read_file tool for agents: must stay inside the workspace root."""
        p = (self.root / rel).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise WorkspaceError(f"read outside workspace denied: {rel}")
        if not p.is_file():
            raise WorkspaceError(f"no such file: {rel}")
        if p.stat().st_size > 1_000_000:
            raise WorkspaceError(f"file too large: {rel}")
        return p.read_text(encoding="utf-8")
