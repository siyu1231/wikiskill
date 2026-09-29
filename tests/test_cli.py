"""CLI end-to-end (offline, mock backend): init -> status -> evolve -> run-task."""
import json

from wikiskill.cli import main
from wikiskill.workspace import Workspace


def test_init_creates_three_layers_and_demo_tasks(tmp_path, capsys):
    ws = str(tmp_path / "ws")
    assert main(["init", ws, "--backend", "mock"]) == 0
    out = capsys.readouterr().out
    assert "train 8 / val 4" in out
    root = tmp_path / "ws"
    for p in ("workspace.json", "tasks.jsonl", "raw", "wiki/patterns", "skills"):
        assert (root / p).exists(), p
    cfg = json.loads((root / "workspace.json").read_text(encoding="utf-8"))
    assert cfg["backend"] == "mock" and cfg["runner"] == "backend"
    assert len((root / "tasks.jsonl").read_text(encoding="utf-8").splitlines()) == 12
    # re-init refuses without --force
    import pytest
    with pytest.raises(SystemExit, match="already a wikiskill workspace"):
        main(["init", ws])


def test_evolve_full_loop_accept_then_reject(tmp_path, capsys):
    ws = str(tmp_path / "ws")
    main(["init", ws])
    capsys.readouterr()
    assert main(["evolve", ws, "--iters", "3", "-q"]) == 0
    out = capsys.readouterr().out

    root = tmp_path / "ws"
    w = Workspace.open(str(root))

    # iteration 1: multiply skill accepted (val has 2 mult tasks of 4)
    assert "ACCEPTED" in out and "rejected" in out
    # skills layer: multiply kept, junk rolled back
    assert (root / "skills" / "multiply" / "SKILL.md").exists()
    assert not (root / "skills" / "color").exists()
    # wiki layer never rolled back
    assert "multiplication" in w.list_patterns()
    impact = w.read_skill_impact()
    assert impact.count("outcome: Accepted") == 1
    assert impact.count("outcome: Rejected") == 2
    # raw layer: baseline val + 3 * (train + val)
    assert len(w.load_traces(0, "val")) == 4
    for k in (1, 2, 3):
        assert len(w.load_traces(k, "train")) == 8
        assert len(w.load_traces(k, "val")) == 4
    # runs/ got per-task artifacts (harness-managed layout, design.md §8)
    assert any((root / "runs").glob("iter-*-val-*"))


def test_status_reflects_evolved_state(tmp_path, capsys):
    ws = str(tmp_path / "ws")
    main(["init", ws])
    main(["evolve", ws, "--iters", "2", "-q"])
    capsys.readouterr()
    assert main(["status", ws]) == 0
    out = capsys.readouterr().out
    assert "skills/   : multiply" in out
    assert "1 accepted" in out
    assert "1 rejected" in out


def test_run_task_debug(tmp_path, capsys):
    ws = str(tmp_path / "ws")
    main(["init", ws])
    capsys.readouterr()
    # no skills yet -> format convention unknown -> exit 1 (useful signal)
    assert main(["run-task", ws, "d01"]) == 1
    out = capsys.readouterr().out
    assert "expected  : 'product=391'" in out and "FAIL" in out
    import pytest
    with pytest.raises(SystemExit, match="unknown task"):
        main(["run-task", ws, "zzz"])
