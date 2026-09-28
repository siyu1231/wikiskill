import json

from wikiskill.agents import SkillProposer, WikiMaintainer, stratified_sample, MAX_FAILING, MAX_PASSING
from wikiskill.llm import MockLLM, extract_json
from wikiskill.skills import SkillSet
from wikiskill.workspace import Workspace, TRACE_CAP


def traces(n_fail, n_pass, cap_size=10):
    out = [{"task_id": f"f{i}", "pass": False, "prompt": "x" * cap_size} for i in range(n_fail)]
    out += [{"task_id": f"p{i}", "pass": True, "prompt": "y" * cap_size} for i in range(n_pass)]
    return out


def test_stratified_sample_budget():
    picked = stratified_sample(traces(20, 20))
    assert sum(1 for t in picked if not t["pass"]) == MAX_FAILING
    assert sum(1 for t in picked if t["pass"]) == MAX_PASSING


def test_stratified_sample_truncates_long_fields():
    picked = stratified_sample(traces(1, 1, cap_size=TRACE_CAP + 500))
    for t in picked:
        assert len(t["prompt"]) <= TRACE_CAP + 30


def test_extract_json_fenced():
    assert extract_json('here you go:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('{"nested": {"b": [1,2]}} trailing') == {"nested": {"b": [1, 2]}}
    assert extract_json("no json here") is None


def test_maintainer_applies_patches(tmp_path):
    ws = Workspace(tmp_path / "ws").create()
    reply = json.dumps({
        "patches": [
            {"file": "patterns/loop.md", "op": "append", "text": "# Looping\nEvidence: t1\n"},
            {"file": "patterns/loop.md", "op": "replace", "old": "Evidence: t1", "text": "Evidence: t1, t2"},
        ],
        "log_summary": "found a looping failure mode",
    })
    m = WikiMaintainer(MockLLM([reply]), ws)
    assert m.consolidate(traces(2, 1)) == 2
    body = ws.read_wiki("patterns/loop.md")
    assert "Evidence: t1, t2" in body and "looping" in ws.read_wiki("logs.md")


def test_proposer_tool_then_proposal(tmp_path):
    ws = Workspace(tmp_path / "ws").create()
    ws.save_trace(1, "t1", "train", {"answer": "wrong"})
    skills = SkillSet(ws.skills_dir)
    script = [
        json.dumps({"tool": "read_file", "path": "raw/iter-0001/train-t1.json"}),
        json.dumps({"proposal": {"action": "create", "skill": "tip",
                                 "content": "# Tip\nCheck the prompt.", "rationale": "t1 wrong"}}),
    ]
    p = SkillProposer(MockLLM(script), ws, skills).propose(
        [{"task_id": "t1", "pass": False, "answer": "wrong", "expected": "right"}], 1)
    assert p is not None and p.skill == "tip"


def test_proposer_rejects_invalid_proposal(tmp_path):
    ws = Workspace(tmp_path / "ws").create()
    bad = json.dumps({"proposal": {"action": "create", "skill": "UPPER", "content": "x"}})
    assert SkillProposer(MockLLM([bad]), ws, SkillSet(ws.skills_dir)).propose([], 1) is None
