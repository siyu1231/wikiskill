import pytest

from wikiskill.workspace import Workspace, WorkspaceError


def ws(tmp_path):
    return Workspace(tmp_path / "ws").create()


def test_layers_created(tmp_path):
    w = ws(tmp_path)
    assert (w.root / "raw").is_dir()
    assert (w.root / "wiki" / "patterns").is_dir()
    assert (w.root / "skills").is_dir()
    assert w.read_wiki("index.md").startswith("# Pattern Index")
    assert w.read_wiki("skill-impact.md").startswith("# Skill Impact")


def test_raw_is_append_only(tmp_path):
    w = ws(tmp_path)
    w.save_trace(1, "t1", "train", {"answer": "a"})
    with pytest.raises(WorkspaceError, match="append-only"):
        w.save_trace(1, "t1", "train", {"answer": "b"})
    traces = w.load_traces(1, "train")
    assert len(traces) == 1 and traces[0]["answer"] == "a"


def test_raw_illegal_name(tmp_path):
    w = ws(tmp_path)
    with pytest.raises(WorkspaceError):
        w.save_trace(1, "../evil", "train", {})


def test_read_file_scoped(tmp_path):
    w = ws(tmp_path)
    w.save_trace(1, "t1", "train", {"x": 1})
    assert "x" in w.read_file("raw/iter-0001/train-t1.json")
    with pytest.raises(WorkspaceError):
        w.read_file("../../outside.txt")
    with pytest.raises(WorkspaceError):
        w.read_file("nope.json")


def test_wiki_pattern_ops(tmp_path):
    w = ws(tmp_path)
    w.write_wiki("patterns/a.md", "# A\n")
    assert w.list_patterns() == ["a"]
    p = w.wiki_path("patterns/a.md")
    with pytest.raises(WorkspaceError):
        w.wiki_path("../skills/x")
    w.append_log("did a thing")
    assert "did a thing" in w.read_wiki("logs.md")
    w.append_skill_impact("### Iteration 1\n- outcome: Rejected")
    assert "Rejected" in w.read_skill_impact()
