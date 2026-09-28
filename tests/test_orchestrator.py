"""End-to-end Algorithm 1 with MockLLM — no network, deterministic (design.md §7)."""
import json

from wikiskill.agents import SkillProposer, WikiMaintainer
from wikiskill.harness import Task, make_trace, split_tasks
from wikiskill.llm import MockLLM
from wikiskill.skills import SkillSet
from wikiskill.orchestrator import Orchestrator
from wikiskill.workspace import Workspace

TASKS = [Task(id=f"m{i}", prompt=f"{a}*{b}", expected=str(a * b))
         for i, (a, b) in enumerate([(2, 3), (4, 5), (7, 8), (3, 3), (6, 6), (9, 9)])]


def math_rollout(tasks, skills_ctx, iteration, split):
    """Correct iff the active skills mention multiplication — scripted environment."""
    skilled = "multiply" in skills_ctx
    return [make_trace(t, str(eval(t.prompt)) if skilled else "idk") for t in tasks]


def noop_rollout(tasks, skills_ctx, iteration, split):
    """Skills never help."""
    return [make_trace(t, "idk") for t in tasks]


def maintainer_reply():
    return json.dumps({
        "patches": [{"file": "patterns/multiplication.md", "op": "append",
                     "text": "# Multiplication failures\nModel answers idk on a*b.\n"}],
        "log_summary": "Root cause: no multiplication strategy.",
    })


def build(tmp_path, rollout, proposer_script):
    ws = Workspace(tmp_path / "ws").create()
    # maintainer answers identically on every call (scripted, never exhausts)
    maintainer = WikiMaintainer(MockLLM(lambda msgs, sys=None: maintainer_reply()), ws)
    proposer = SkillProposer(MockLLM(proposer_script), ws, SkillSet(ws.skills_dir))
    return ws, Orchestrator(ws, maintainer, proposer, rollout)


CREATE_GOOD = json.dumps({"proposal": {
    "action": "create", "skill": "multiply",
    "content": "# Multiply\nTo compute a*b, multiply the digits.",
    "rationale": "all training traces answered idk on multiplication",
    "source_patterns": ["multiplication"]}})
CREATE_JUNK = json.dumps({"proposal": {
    "action": "create", "skill": "color", "content": "# Color\nPrefer blue.",
    "rationale": "unrelated"}})
JUNK2 = json.dumps({"proposal": {
    "action": "create", "skill": "mood", "content": "# Mood\nStay calm.",
    "rationale": "unrelated"}})


def test_accept_path(tmp_path):
    train, val = split_tasks(TASKS)
    ws, orch = build(tmp_path, math_rollout, [CREATE_GOOD])
    res = orch.evolve(train, val, max_iters=5)

    assert res.baseline == 0.0
    it1 = res.iterations[0]
    assert it1.accepted and it1.val_score == 1.0
    assert res.r_best == 1.0
    # accepted -> skill persists
    assert "multiply" in orch.skills.names()
    # early stop at R_best == 1.0 -> no second iteration ran
    assert len(res.iterations) == 1
    # artifacts: wiki kept, audit trail written
    assert "multiplication" in ws.list_patterns()
    impact = ws.read_skill_impact()
    assert "Iteration 1" in impact and "Accepted" in impact
    # raw holds baseline val, iter1 train, iter1 val
    assert len(ws.load_traces(0, "val")) == len(val)
    assert len(ws.load_traces(1, "train")) == len(train)
    assert len(ws.load_traces(1, "val")) == len(val)


def test_reject_rolls_back_skills_but_keeps_wiki(tmp_path):
    train, val = split_tasks(TASKS)
    ws, orch = build(tmp_path, noop_rollout, [CREATE_JUNK, JUNK2])
    res = orch.evolve(train, val, max_iters=2)

    assert not any(i.accepted for i in res.iterations)
    assert res.r_best == res.baseline == 0.0
    # skills-only rollback: junk skill removed, skills empty
    assert orch.skills.names() == []
    # wiki NEVER rolled back: pattern + logs + skill-impact all survive
    assert "multiplication" in ws.list_patterns()
    assert "Rejected" in ws.read_skill_impact()
    assert "Iteration 1" in ws.read_wiki("logs.md")


def test_invalid_proposal_is_rejected_without_crash(tmp_path):
    train, val = split_tasks(TASKS)
    # passes Proposal validation but fails at apply-time (edit of a nonexistent skill)
    EDIT_GHOST = json.dumps({"proposal": {
        "action": "edit", "skill": "ghost", "old": "a", "new": "b", "rationale": "nope"}})
    ws, orch = build(tmp_path, math_rollout, [EDIT_GHOST, CREATE_GOOD])
    res = orch.evolve(train, val, max_iters=3)
    assert res.iterations[0].notes.startswith("invalid")
    assert res.iterations[1].accepted
    assert res.r_best == 1.0
    assert "Rejected" in ws.read_skill_impact() and "Accepted" in ws.read_skill_impact()


def test_no_proposal_iteration_records_audit(tmp_path):
    train, val = split_tasks(TASKS)
    ws, orch = build(tmp_path, math_rollout, ["I refuse to answer", CREATE_GOOD])
    res = orch.evolve(train, val, max_iters=3)
    assert res.iterations[0].proposal is None
    assert "NoProposal" in ws.read_skill_impact()
    assert res.r_best == 1.0
