"""Runner abstraction (design.md §8.1): the three roles share ONE interface.

A Runner is duck-type compatible with llm.LLM: `chat(messages, system) -> str`.

- BackendRunner (default, runner="backend"): renders system+messages into a
  single oneshot prompt and executes it through the AgentBackend — all three
  roles then live on the agent's own credentials/config (paper: M_WM and M_P
  are agents too). Actors get workdir = workspace root (they are ALLOWED to
  read raw/ and wiki/, per §3.1); the inference rollout never uses this class.
- DirectRunner: an OpenAI-compatible endpoint (runner="direct"), for cheaper /
  different models behind Maintainer+Proposer.
"""
from __future__ import annotations

from .backends.base import AgentBackend
from .llm import LLM, OpenAICompatLLM


def render_prompt(messages: list[dict], system: str | None = None) -> str:
    parts: list[str] = []
    if system:
        parts.append(system)
    for m in messages:
        role = m.get("role", "user")
        parts.append(f"[{role.upper()}]\n{m.get('content', '')}")
    return "\n\n".join(parts)


class BackendRunner(LLM):
    def __init__(self, backend: AgentBackend, ws_root: str,
                 toolsets: str = "file,terminal", max_turns: int = 12,
                 run_budget: int = 300, workdir: str | None = None):
        self.backend = backend
        self.ws_root = ws_root
        self.toolsets = toolsets
        self.max_turns = max_turns
        self.run_budget = run_budget
        self.workdir = ws_root if workdir is None else workdir
        self._n = 0

    def chat(self, messages: list[dict], system: str | None = None) -> str:
        self._n += 1
        prompt = render_prompt(messages, system)
        res = self.backend.run(self.ws_root, prompt, tag=f"actor-{self._n:03d}",
                               toolsets=self.toolsets, max_turns=self.max_turns,
                               run_budget=self.run_budget, workdir=self.workdir)
        return res.stdout


def make_runner(name: str, backend: AgentBackend | None, ws_root: str,
                llm_cfg: dict | None = None) -> LLM:
    """Build the actor runner. CLI params > workspace.json > environment."""
    if name == "backend":
        if backend is None:
            raise ValueError("runner='backend' needs a backend")
        return BackendRunner(backend, ws_root)
    if name == "direct":
        cfg = llm_cfg or {}
        llm = OpenAICompatLLM(model=cfg.get("model") or "gpt-4o-mini",
                              base_url=cfg.get("base_url"), api_key=cfg.get("api_key"))
        if not llm.api_key:
            raise SystemExit(
                "runner='direct' requires an API key: pass --llm-key, set "
                "workspace.json llm.api_key, or export OPENAI_API_KEY")
        return DirectRunner(llm)
    raise SystemExit(f"unknown runner {name!r}; expected 'backend' or 'direct'")


class DirectRunner(LLM):
    def __init__(self, llm: OpenAICompatLLM):
        self.llm = llm

    def chat(self, messages: list[dict], system: str | None = None) -> str:
        return self.llm.chat(messages, system)
