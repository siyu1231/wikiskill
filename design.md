# wikiskill — Design

Goal: a faithful, **agent-agnostic** implementation of WikiSkill (arXiv:2608.27454 Algorithm 1),
usable with Hermes Agent, Claude Code, Codex CLI, pi-agent and other CLI agents.

Non-goals (for now): reproducing the paper's 5-benchmark / 3-baseline experiment table
(needs the original datasets and model APIs — tracked as a later, optional phase).

## 1. Three-layer workspace (paper §3.1)

```
workspace/
├── raw/            # immutable execution traces (append-only, never deleted)
│   └── iter-<k>/task-<id>.jsonl
├── wiki/           # persistent knowledge — NEVER rolled back
│   ├── patterns/*.md     # one page per failure mode / strategy
│   ├── index.md          # catalog, maintained by Wiki Maintainer
│   ├── logs.md           # per-iteration evolution log
│   └── skill-impact.md   # written ONLY by the harness (proposal + diff + score + outcome)
└── skills/         # active skill set S_k (reversible)
    └── <skill>/{SKILL.md, PURPOSE.md}
```

Invariants (enforced in code, not conventions):
1. `raw/` is append-only. **No code path may delete or overwrite traces** (including eval outputs —
   eval traces go to `raw/` under a distinct iteration dir, never removed).
2. `wiki/skill-impact.md` is written exclusively by the orchestrator harness (ground-truth audit trail).
3. Rollback touches **only** `skills/`. Wiki state is monotonic.

## 2. Evolution loop (paper Algorithm 1, §3.2)

Per iteration k:
1. **Inference**: rollout on D_train with active skills S_{k-1}.
   Skills are **full-injected into the system prompt** (paper §3.2.1; ablation §5.1 shows
   retrieval/symlink self-serve degrades results). The inference agent has NO wiki access.
2. **Sample**: stratified ≤5 failing + ≤3 passing traces, 15,000 chars each (App. C).
3. **Wiki Maintenance**: one-shot LLM call M_WM(W_{k-1}, T_sample) → patch pattern pages,
   refresh index.md, append logs.md.
4. **Skill Proposal**: multi-turn ReAct agent with `read_file` over the workspace, seeded with
   wiki index + skill-impact.md + task outcome summary; emits **one atomic proposal**
   (create skill or patch existing skill).
5. **Apply + Validate**: apply proposal → run D_val → score R.
6. **Gate**: accept iff `R > R_best` (strict); else revert skills to S_{k-1}. Wiki untouched.
7. **Audit**: harness appends {proposal, target, unified diff, R, Accepted/Rejected} to
   `wiki/skill-impact.md`. Early-stop when `R_best == 1.0`.

Baseline: `R_best = R(D_val; S_0=∅)` before iteration 1.

## 3. Backend abstraction (adapted from ashutosh/wikiskill)

The **inference agent** is any CLI agent. Backend protocol (`wikiskill/backends/base.py`):

```python
class AgentBackend(Protocol):
    name: str
    def prepare(self, ws: Workspace, run_id: str) -> None: ...   # isolate config (HERMES_HOME / CLAUDE_CONFIG_DIR / …)
    def run_task(self, task: Task, skills_prompt: str, ws: Workspace) -> Transcript: ...
    def cleanup(self, run_id: str) -> None: ...
    # + transcript normalization to a common Trace schema
```

Adapters planned: `hermes` (reference, isolated `HERMES_HOME`), `claude` (`claude -p`,
isolated `CLAUDE_CONFIG_DIR`), `codex`, `pi`. Registered via a static registry
(`backends/__init__.py`), selected per-workspace in `workspace.json`.

The **Wiki Maintainer** and **Skill Proposer** are NOT backend CLIs: they are direct LLM calls
(single call / ReAct with read_file over the workspace) via an OpenAI-compatible client —
cheap, deterministic, and backend-independent. (Deviation note: the paper doesn't specify
whether these go through the same agent runtime; direct calls keep backends replaceable.)

## 4. Fidelity fixes over the two reference implementations

| # | Issue | Where | Fix |
|---|---|---|---|
| 1 | skills served by symlink / self-serve instead of prompt injection | ashutosh `hermes.py` | full text injection (§3.2.1) |
| 2 | significance test = binomial, not paired bootstrap | ashutosh `compare.py` | paired bootstrap, 1000 iters, + stratified macro-average across tasks (App. C) |
| 3 | raw layer overwritten (`overwrite=True`) / eval traces deleted | ashutosh `harness.py`, kenhuangus `orchestrator.py` | append-only enforcement in `workspace.py` |
| 4 | no held-out validation split (gating on train) | ashutosh `tasks.py` | explicit D_train / D_val / D_test split |
| 5 | `python3` hardcoded, fails on Windows | ashutosh `scoring.py` | `sys.executable` / platform-safe paths |
| 6 | LLM-only text-ReAct with regex parsing, no real agent backend | kenhuangus `agents.py` | backend protocol above |
| 7 | no multi-run averaging | both | `runs/` per-run dirs, aggregate over N runs |

## 5. Module layout

```
src/wikiskill/
├── workspace.py      # three layers, append-only raw, scoped reads, patch engine
├── skills.py         # skill set: apply_proposal, snapshot/rollback (skills only)
├── prompts.py        # Appendix E adaptations: inference / maintainer / proposer
├── agents.py         # WikiMaintainer (one-shot), SkillProposer (ReAct + read_file)
├── orchestrator.py   # Algorithm 1 + gating + skill-impact audit + early stop
├── metrics.py        # accuracy, paired bootstrap, macro-average, early-stop helpers
├── harness.py        # task loading, splits, rollout runner, scoring
├── backends/
│   ├── base.py       # AgentBackend protocol + Trace/Transcript schema + registry
│   ├── hermes.py     # reference backend
│   ├── claude.py
│   ├── codex.py
│   └── pi.py
├── llm.py            # OpenAI-compatible client + MockLLM (tests)
└── cli.py            # wikiskill init / status / evolve / run-task
```

## 6. Roadmap

- **P0 (now)**: repo skeleton, vendored references, design doc. ✅
- **P1**: `workspace.py` + `skills.py` + `orchestrator.py` with MockLLM — loop verifiable
  end-to-end without any API (test: useless proposals all rejected, skills rolled back, wiki retained).
- **P2**: `backends/hermes.py` + real rollouts; `wikiskill init|status|evolve` CLI.
- **P3**: claude / codex / pi adapters; demo task bench (auto-graded, train/val/test split);
  metrics with paired bootstrap.
- **P4 (optional)**: align with paper benchmarks (LiveMath, SealQA, SpreadSheet, OfficeQA,
  ALFWorld) and baselines (EvoSkill, SkillOpt, no-skill).

## 7. Testing

- Unit: workspace invariants (append-only raw, skills-only rollback), patch engine, sampling
  budget, gating acceptance boundary (strict >), bootstrap correctness on synthetic data.
- Integration: full loop with `MockLLM` + fixture tasks — no network, deterministic.
- Backend smoke: each adapter has a `dry-run` mode that validates isolation + transcript
  normalization without calling a model.
