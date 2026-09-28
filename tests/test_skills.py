import pytest

from wikiskill.skills import Proposal, ProposalError, SkillSet


def make(root):
    s = SkillSet(root)
    root.mkdir(parents=True, exist_ok=True)
    return s


def test_create_and_edit(tmp_path):
    s = make(tmp_path / "skills")
    p = Proposal(action="create", skill="adder", content="# Adder\nAdd numbers slowly.",
                 rationale="failures on addition")
    diff = s.apply(p)
    assert "adder" in s.names() and "Add numbers slowly" in s.read("adder")
    assert "+# Adder" in diff
    e = Proposal(action="edit", skill="adder", old="slowly", new="carefully")
    d2 = s.apply(e)
    assert "carefully" in s.read("adder") and "-" in d2


def test_edit_guards(tmp_path):
    s = make(tmp_path / "skills")
    s.apply(Proposal(action="create", skill="x", content="alpha beta alpha"))
    with pytest.raises(ProposalError, match="unique"):
        s.apply(Proposal(action="edit", skill="x", old="alpha", new="gamma"))
    with pytest.raises(ProposalError, match="not found"):
        s.apply(Proposal(action="edit", skill="x", old="omega", new="gamma"))
    with pytest.raises(ProposalError):
        s.apply(Proposal(action="create", skill="Bad_Name", content="x"))
    with pytest.raises(ProposalError, match="already exists"):
        s.apply(Proposal(action="create", skill="x", content="y"))


def test_snapshot_restore_skills_only(tmp_path):
    s = make(tmp_path / "skills")
    snap = s.snapshot()          # empty
    s.apply(Proposal(action="create", skill="junk", content="useless"))
    assert "junk" in s.names()
    s.restore(snap)
    assert s.names() == []
