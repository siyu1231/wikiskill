"""wikiskill init | status | evolve | run-task — thin CLI over the library.

Core is the library; this is the entry point (design.md §8.2: "核心是库，
外壳是 CLI，文件是状态"). Config precedence: CLI flags > workspace.json >
environment (OPENAI_BASE_URL / OPENAI_API_KEY).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import backends as _backends  # noqa: F401  (registers adapters)
from .backends import available_backends, get_backend
from .agents import SkillProposer, WikiMaintainer
from .demo import write_demo_tasks
from .doctor import checks as doctor_checks
from .doctor import report as doctor_report
from .harness import BackendRollout, load_tasks, split_tasks
from .orchestrator import Orchestrator
from .runners import make_runner
from .skills import SkillSet
from .workspace import Workspace

DEFAULTS = {
    "backend": "mock",
    "runner": "backend",
    "tasks": "tasks.jsonl",
    "seed": 42,
    "max_turns": 15,
    "run_budget": 300,
    "llm": {"base_url": "", "api_key": "", "model": ""},
}


def _ws(dirpath: str) -> Path:
    return Path(dirpath).resolve()


def _cfg_path(ws: Path) -> Path:
    return ws / "workspace.json"


def _load_cfg(ws: Path) -> dict:
    p = _cfg_path(ws)
    if not p.exists():
        raise SystemExit(f"not a wikiskill workspace (missing workspace.json): {ws}")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    for k, v in DEFAULTS.items():
        cfg.setdefault(k, v)
    return cfg


def _save_cfg(ws: Path, cfg: dict) -> None:
    _cfg_path(ws).write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")


# ---------------------------------------------------------------- init
def cmd_init(args: argparse.Namespace) -> int:
    ws = _ws(args.dir)
    if _cfg_path(ws).exists() and not args.force:
        raise SystemExit(f"already a wikiskill workspace: {ws} (use --force to re-init)")
    ws.mkdir(parents=True, exist_ok=True)
    Workspace(ws).create()

    if args.tasks:
        src = Path(args.tasks)
        if not src.exists():
            raise SystemExit(f"tasks file not found: {src}")
        n = len(load_tasks(src))
        (ws / "tasks.jsonl").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        n = write_demo_tasks(ws / "tasks.jsonl")

    cfg = {**DEFAULTS, "backend": args.backend, "seed": args.seed}
    _save_cfg(ws, cfg)

    backend = get_backend(cfg["backend"])
    backend.bootstrap(str(ws))

    tasks = load_tasks(ws / "tasks.jsonl")
    train, val = split_tasks(tasks, seed=cfg["seed"])
    print(f"workspace : {ws}")
    print(f"backend   : {cfg['backend']} (available: {', '.join(available_backends())})")
    print(f"tasks     : {n} total -> train {len(train)} / val {len(val)} "
          f"(seed {cfg['seed']}, held-out for gating)")
    print("next      : wikiskill evolve " + str(args.dir))
    return 0


# ---------------------------------------------------------------- status
def cmd_status(args: argparse.Namespace) -> int:
    ws = _ws(args.dir)
    cfg = _load_cfg(ws)
    w = Workspace.open(str(ws))
    skills = SkillSet(w.skills_dir)

    raw = list(w.iter_trace_paths())
    per_iter: dict[str, int] = {}
    for p in raw:
        per_iter[p.parent.name] = per_iter.get(p.parent.name, 0) + 1

    impact = w.read_skill_impact()
    outcomes = {"Accepted": impact.count("outcome: Accepted"),
                "Rejected": impact.count("outcome: Rejected"),
                "NoProposal": impact.count("outcome: NoProposal")}
    r_best = ""
    for line in impact.splitlines():
        if line.startswith("- R_best after gate:"):
            r_best = line.split(":", 1)[1].strip()

    print(f"workspace : {ws}")
    print(f"backend   : {cfg['backend']}    runner: {cfg['runner']}    seed: {cfg['seed']}")
    print(f"raw/      : {len(raw)} traces  "
          + ", ".join(f"{k}:{v}" for k, v in sorted(per_iter.items())))
    print(f"wiki/     : {len(w.list_patterns())} patterns, "
          f"logs {len(w.read_wiki('logs.md') or '')} chars")
    print(f"skills/   : {', '.join(skills.names()) or '(none)'}")
    print(f"gating    : {outcomes['Accepted']} accepted / "
          + " / ".join(f"{v} {k.lower()}" for k, v in outcomes.items() if k != "Accepted")
          + (f"    R_best={r_best}" if r_best else ""))
    return 0


# ---------------------------------------------------------------- evolve
def cmd_evolve(args: argparse.Namespace) -> int:
    ws = _ws(args.dir)
    cfg = _load_cfg(ws)
    if args.backend:
        cfg["backend"] = args.backend
    if args.runner:
        cfg["runner"] = args.runner
    if args.max_turns:
        cfg["max_turns"] = args.max_turns
    if args.run_budget:
        cfg["run_budget"] = args.run_budget
    if args.llm_base:
        cfg["llm"]["base_url"] = args.llm_base
    if args.llm_key:
        cfg["llm"]["api_key"] = args.llm_key
    if args.llm_model:
        cfg["llm"]["model"] = args.llm_model

    w = Workspace.open(str(ws))
    backend = get_backend(cfg["backend"])
    backend.bootstrap(str(ws))

    tasks = load_tasks(ws / cfg["tasks"])
    train, val = split_tasks(tasks, seed=cfg["seed"])

    rollout = BackendRollout(backend, str(ws), max_turns=cfg["max_turns"],
                             run_budget=cfg["run_budget"], verbose=not args.quiet)
    runner = make_runner(cfg["runner"], backend, str(ws), cfg.get("llm"))
    skills = SkillSet(w.skills_dir)
    maintainer = WikiMaintainer(runner, w)
    proposer = SkillProposer(runner, w, skills)
    orch = Orchestrator(w, maintainer, proposer, rollout)

    print(f"evolve    : {ws}  backend={cfg['backend']} runner={cfg['runner']}")
    print(f"data      : train {len(train)} / val {len(val)}   iters<= {args.iters}")
    t0 = _now()
    res = orch.evolve(train, val, max_iters=args.iters)
    print(f"\n{'iter':>4}  {'train':>6}  {'val':>6}  {'gate':>8}  {'R_best':>7}  proposal")
    for it in res.iterations:
        gate = "ACCEPTED" if it.accepted else ("no-op" if it.proposal is None else "rejected")
        prop = (f"{it.proposal.action}:{it.proposal.skill}" if it.proposal else it.notes)
        print(f"{it.k:>4}  {it.train_score:>6.2f}  {it.val_score:>6.2f}  "
              f"{gate:>8}  {it.r_best:>7.2f}  {prop}")
    print(f"\nbaseline={res.baseline:.2f}  final R_best={res.r_best:.2f}  "
          f"accepted={res.accepted_count}/{len(res.iterations)}  ({_now()-t0:.0f}s)")
    print(f"skills/   : {', '.join(SkillSet(w.skills_dir).names()) or '(none)'}")
    return 0


# ---------------------------------------------------------------- run-task
def cmd_run_task(args: argparse.Namespace) -> int:
    ws = _ws(args.dir)
    cfg = _load_cfg(ws)
    w = Workspace.open(str(ws))
    tasks = {t.id: t for t in load_tasks(ws / cfg["tasks"])}
    if args.task_id not in tasks:
        raise SystemExit(f"unknown task {args.task_id!r}; have: {', '.join(sorted(tasks))}")
    backend = get_backend(cfg["backend"])
    backend.bootstrap(str(ws))
    rollout = BackendRollout(backend, str(ws), max_turns=cfg["max_turns"],
                             run_budget=cfg["run_budget"])
    skills_ctx = SkillSet(w.skills_dir).full_context()
    traces = rollout([tasks[args.task_id]], skills_ctx, 0, "debug")
    t = traces[0]
    print(f"expected  : {t['expected']!r}\nanswer    : {t['answer']!r}  "
          f"-> {'PASS' if t['pass'] else 'FAIL'}")
    return 0 if t["pass"] else 1


def _now() -> int:
    import time
    return int(time.time())


# ---------------------------------------------------------------- doctor
def cmd_doctor(args: argparse.Namespace) -> int:
    cs = doctor_checks(args.dir, probe_llm=args.probe_llm)
    return doctor_report(cs, args.dir)


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="wikiskill",
                                description="WikiSkill: compile agent experience into "
                                            "persistent knowledge for skill evolution "
                                            "(arXiv:2608.27454)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="create a workspace (three-layer dirs + tasks)")
    pi.add_argument("dir")
    pi.add_argument("--backend", default="mock", choices=available_backends())
    pi.add_argument("--tasks", help="own tasks.jsonl (default: bundled demo bench)")
    pi.add_argument("--seed", type=int, default=42, help="train/val split seed")
    pi.add_argument("--force", action="store_true")

    ps = sub.add_parser("status", help="show workspace layers, skills, gating history")
    ps.add_argument("dir")

    pe = sub.add_parser("evolve", help="run the Algorithm 1 evolution loop")
    pe.add_argument("dir")
    pe.add_argument("--iters", type=int, default=5)
    pe.add_argument("--runner", choices=["backend", "direct"])
    pe.add_argument("--backend", choices=available_backends())
    pe.add_argument("--llm-base", dest="llm_base")
    pe.add_argument("--llm-key", dest="llm_key")
    pe.add_argument("--llm-model", dest="llm_model")
    pe.add_argument("--max-turns", type=int, dest="max_turns")
    pe.add_argument("--run-budget", type=int, dest="run_budget")
    pe.add_argument("-q", "--quiet", action="store_true")

    pr = sub.add_parser("run-task", help="run one task once (debug rollout)")
    pr.add_argument("dir")
    pr.add_argument("task_id")

    pd = sub.add_parser("doctor", help="environment self-check (package/backends/workspace/endpoint)")
    pd.add_argument("dir", nargs="?", help="workspace to inspect (omit for global checks only)")
    pd.add_argument("--probe-llm", action="store_true",
                    help="GET {base_url}/models to verify the direct LLM endpoint")

    args = p.parse_args(argv)
    handler = {"init": cmd_init, "status": cmd_status,
               "evolve": cmd_evolve, "run-task": cmd_run_task,
               "doctor": cmd_doctor}[args.cmd]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
