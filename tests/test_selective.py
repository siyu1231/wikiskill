"""Selective (abstention-aware) metric: classification, scoring math, actor notes,
sampling diversification, CLI wiring. exact stays the paper default and must keep
its old behavior bit-for-bit."""
from wikiskill.agents import MAX_FAILING, stratified_sample
from wikiskill.cli import main
from wikiskill.harness import Task, make_trace
from wikiskill.metrics import (accuracy, is_abstain, outcome_of, score,
                               select_stats, selective_score)
from wikiskill.prompts import scoring_note


# ------------------------------------------------------------ classification
def test_is_abstain_vocab():
    for a in ["verdict=unknown", "verdict=uncertain", "不确定", "存疑", "idk",
              "I don't know", "not sure", "abstain", "无法判断"]:
        assert is_abstain(a), a


def test_not_abstain():
    for a in ["verdict=correct", "verdict=wrong", "correct", "wrong", "391", "是", "否"]:
        assert not is_abstain(a), a


def test_outcome_of():
    assert outcome_of({"pass": True, "answer": "verdict=correct"}) == "correct"
    assert outcome_of({"pass": False, "answer": "verdict=unknown"}) == "abstain"
    assert outcome_of({"pass": False, "answer": "verdict=wrong"}) == "wrong"
    # an abstention that matches the expected label is still correct
    assert outcome_of({"pass": True, "answer": "不确定"}) == "correct"


def test_make_trace_outcome_field():
    t = Task(id="x", prompt="p", expected="verdict=correct")
    assert make_trace(t, "verdict=correct")["outcome"] == "correct"
    assert make_trace(t, "verdict=unknown")["outcome"] == "abstain"
    assert make_trace(t, "verdict=wrong")["outcome"] == "wrong"
    assert make_trace(t, "verdict=unknown")["pass"] is False


# ------------------------------------------------------------ scoring math
def _traces():
    return [
        {"pass": True, "answer": "a"},    # correct
        {"pass": True, "answer": "b"},    # correct
        {"pass": True, "answer": "c"},    # correct
        {"pass": False, "answer": "verdict=unknown"},  # abstain
        {"pass": False, "answer": "verdict=wrong"},    # wrong
    ]


def test_accuracy_unchanged_by_abstain():
    # paper metric: abstention is just a failed exact match
    assert accuracy(_traces()) == 3 / 5


def test_selective_score_math():
    # (3 correct − 0.25·1 abstain − 1.0·1 wrong) / 5 = 1.75/5 = 0.35
    assert abs(selective_score(_traces()) - 0.35) < 1e-9
    # (3 − 0.5·1 − 2.0·1)/5 = 0.5/5 = 0.1
    assert abs(selective_score(_traces(), abstain=0.5, wrong=2.0) - 0.1) < 1e-9


def test_abstain_cheaper_than_wrong():
    one_wrong = [{"pass": False, "answer": "verdict=wrong"}]
    one_abstain = [{"pass": False, "answer": "verdict=unknown"}]
    assert selective_score(one_abstain) > selective_score(one_wrong)


def test_score_dispatch():
    assert score(_traces(), None) == 3 / 5
    assert score(_traces(), {"name": "exact"}) == 3 / 5
    assert abs(score(_traces(), {"name": "selective"}) - 0.35) < 1e-9
    assert abs(score(_traces(),
                     {"name": "selective", "abstain": 0.0, "wrong": 1.0})
               - 0.4) < 1e-9


def test_all_abstain_never_wins():
    # blanket abstention scores -λ while competent answering scores ~+0.9
    all_abstain = [{"pass": False, "answer": "verdict=unknown"}] * 10
    confident = [{"pass": True, "answer": "v"}] * 9 + [
        {"pass": False, "answer": "verdict=wrong"}]
    assert selective_score(confident) > 0 > selective_score(all_abstain)


def test_select_stats():
    st = select_stats(_traces())
    assert st["n"] == 5 and st["correct"] == 3 and st["abstain"] == 1 and st["wrong"] == 1
    assert abs(st["coverage"] - 0.8) < 1e-9
    assert abs(st["abstain_rate"] - 0.2) < 1e-9
    assert abs(st["cond_acc"] - 0.75) < 1e-9
    assert select_stats([])["n"] == 0


# ------------------------------------------------------------ actors & sampling
def test_scoring_note_only_for_selective():
    assert scoring_note(None) == ""
    assert scoring_note({"name": "exact"}) == ""
    note = scoring_note({"name": "selective", "abstain": 0.25, "wrong": 1.0})
    assert "-0.25" in note and "-1" in note and "verdict=unknown" in note


def test_stratified_sample_diversifies_failing_by_outcome():
    traces = ([{"id": f"a{i}", "pass": False, "outcome": "abstain"} for i in range(4)]
              + [{"id": f"w{i}", "pass": False, "outcome": "wrong"} for i in range(4)]
              + [{"id": f"p{i}", "pass": True, "outcome": "correct"} for i in range(3)])
    picked = stratified_sample(traces)
    fails = [t for t in picked if not t["pass"]]
    passes = [t for t in picked if t["pass"]]
    assert len(fails) == MAX_FAILING
    assert len(passes) == 3
    outs = {t["outcome"] for t in fails}
    assert outs == {"abstain", "wrong"}   # both kinds survive the ≤5 budget


def test_stratified_sample_legacy_traces_unchanged():
    # traces without an outcome key keep the original first-N-failing order
    traces = ([{"id": f"f{i}", "pass": False} for i in range(7)]
              + [{"id": f"p{i}", "pass": True} for i in range(4)])
    picked = stratified_sample(traces)
    assert [t["id"] for t in picked[:5]] == [f"f{i}" for i in range(5)]


# ------------------------------------------------------------ CLI wiring
def test_init_selective_metric_persisted(tmp_path, capsys):
    ws = str(tmp_path / "ws")
    main(["init", ws, "--metric", "selective",
          "--abstain-penalty", "0.3", "--wrong-penalty", "2"])
    out = capsys.readouterr().out
    assert "metric    : selective (abstain=-0.3 wrong=-2)" in out
    import json
    cfg = json.loads((tmp_path / "ws" / "workspace.json").read_text(encoding="utf-8"))
    assert cfg["metric"] == {"name": "selective", "abstain": 0.3, "wrong": 2.0}


def test_init_default_metric_exact(tmp_path, capsys):
    ws = str(tmp_path / "ws")
    main(["init", ws])
    assert "metric    :" not in capsys.readouterr().out
    import json
    cfg = json.loads((tmp_path / "ws" / "workspace.json").read_text(encoding="utf-8"))
    assert cfg["metric"] == {"name": "exact"}


def test_full_mock_loop_selective_report(tmp_path, capsys):
    ws = str(tmp_path / "ws")
    main(["init", ws, "--backend", "mock", "--metric", "selective"])
    capsys.readouterr()
    main(["evolve", ws, "--iters", "1", "-q"])
    out = capsys.readouterr().out
    assert "metric=selective" in out
    main(["status", ws])
    out = capsys.readouterr().out
    assert "metric    : selective" in out
    assert "selective : iter-" in out
    assert "coverage=" in out and "cond_acc=" in out
    impact = (tmp_path / "ws" / "wiki" / "skill-impact.md").read_text(encoding="utf-8")
    assert "- selective: correct=" in impact
