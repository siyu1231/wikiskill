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

## 8. Design decisions (2026-09-29, user-reviewed)

### 8.1 Runner 统一：三个角色同一个 `run(prompt, system)` 接口

Maintainer / Proposer / Inference 不再默认分两条 LLM 通路：

- `runner = "backend"`（**默认**）：三个角色全走 agent CLI——复用 agent 自己的凭证，
  零额外配置，且符合论文原意（论文中 M_WM、M_P 与 Inference 同为 agent）。
  实现为 `BackendRunner`：把 system+messages 渲染成单次 oneshot prompt 交给 backend。
- `runner = "direct"`（可选优化）：Maintainer/Proposer 直连 OpenAI 兼容端点，
  用于省 token / 用不同模型（`--llm-base/--llm-key/--llm-model`）。

### 8.2 CLI 形态的理由：核心是库，外壳是 CLI，文件是状态

1. 编排对象本身是 CLI agent（hermes chat / claude -p / codex exec），子进程+stdout 是跨
   agent 最通用接口；
2. 演化循环是批处理（跑完退出），不是在线服务；
3. 状态是文件系统里的 markdown/json——可读、可 git 管、可 diff，支撑"wiki 可审计"；
4. **裁判权必须在被训练者之外**：gating/回滚/审计是独立父进程的代码路径，agent 只是
   启动者或子进程，循环状态不进 agent 的 context。

Web UI（`wikiskill serve`）后置到 P4；不做 MCP/插件（违背 agent-agnostic）。

### 8.3 分层执法：什么形态放哪里

- **演化引擎（循环、门控、回滚、审计）= 代码/CLI**：机械不变量（append-only raw、
  严格 `>`、快照恢复）由测试锁死，靠 prose 嘱托会随 context 漂移；
- **Maintainer/Proposer 角色指令 = prose prompt（skill 形态的本职）**：本来就是给模型的
  说明书，backend 模式下即注入的 system prompt；
- **入口 UX = 可选薄 skill**（P3+）：`/wikiskill` skill 当遥控器调 `wikiskill evolve`。
  skill 也可打包 scripts/ 分发（PEP 723），与 CLI 是同一份库的不同包装——包装不改变
  执法者仍是代码这一事实；防御点是 SKILL.md 写死"workspace 写操作必须经脚本"，
  且状态全落盘、`wikiskill status` 可验污染。
