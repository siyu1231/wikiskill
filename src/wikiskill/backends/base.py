"""AgentBackend protocol + RunResult + registry (design.md §3, §8).

Adapted from ashutoshsinghpr7/wikiskill (MIT) — trimmed to what Algorithm 1
actually needs: bootstrap an isolated environment, run one prompt, hand back
output. Skill provisioning is FULL PROMPT INJECTION (paper §3.2.1), so
backends do NOT manage symlinked skills the way the reference impl does.

Optional capability: a backend may expose `export_transcript(ws, dest)` for
full session traces; backends without it just contribute stdout to raw/.
`runs/` layout and answer parsing live in harness.py, NOT in adapters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class RunResult:
    cmd: list[str]
    exit_code: int | None = None
    duration_s: float = 0.0
    stdout: str = ""
    stdout_path: str | None = None
    session_file: str | None = None
    dry_run: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code in (0, None)


@runtime_checkable
class AgentBackend(Protocol):
    name: str

    def bootstrap(self, ws_root: str) -> None:
        """Prepare the isolated environment for this workspace (idempotent)."""
        ...

    def run(self, ws_root: str, prompt: str, *, tag: str,
            toolsets: str | None = None, max_turns: int = 15,
            run_budget: int = 300, workdir: str | None = None,
            dry_run: bool = False) -> RunResult:
        """Execute one prompt. Must return RunResult even on failure."""
        ...


_REGISTRY: dict[str, type] = {}


def register(name: str, cls: type) -> None:
    _REGISTRY[name] = cls


def get_backend(name: str) -> AgentBackend:
    if name not in _REGISTRY:
        raise KeyError(f"unknown backend {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def available_backends() -> list[str]:
    return sorted(_REGISTRY)
