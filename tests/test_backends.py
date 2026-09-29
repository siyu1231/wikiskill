"""Backend layer: registry, mock behavior (tasks + actor roles), hermes isolation."""
import json
import os

import pytest

from wikiskill.backends import available_backends, get_backend
from wikiskill.backends import hermes as hermes_mod


def test_registry():
    assert "mock" in available_backends() and "hermes" in available_backends()
    assert get_backend("mock").name == "mock"
    with pytest.raises(KeyError, match="unknown backend"):
        get_backend("nope")


# ---------------- mock: inference rollout ----------------
def test_mock_rollout_needs_injected_skill(tmp_path):
    b = get_backend("mock")
    r = b.run(str(tmp_path), "## Task\nCompute 23 * 17 ...", tag="t1")
    assert "ANSWER: idk" in r.stdout
    r2 = b.run(str(tmp_path), "### skill: multiply\nmultiply the two numbers\n## Task\nCompute 23 * 17",
               tag="t2")
    assert "ANSWER: 391" in r2.stdout


# ---------------- mock: actor roles ----------------
def test_mock_maintainer_actor_returns_patches(tmp_path):
    b = get_backend("mock")
    r = b.run(str(tmp_path), "You are the Wiki Maintainer.\n...current wiki...", tag="a1")
    data = json.loads(r.stdout)
    assert data["patches"][0]["file"].startswith("patterns/")
    assert data["log_summary"]


def test_mock_proposer_actor_state_aware(tmp_path):
    b = get_backend("mock")
    none_ctx = b.run(str(tmp_path),
                     "You are the Skill Proposer.\n## active skills\n(none)", tag="a2")
    assert json.loads(none_ctx.stdout)["proposal"]["skill"] == "multiply"
    skilled_ctx = b.run(str(tmp_path),
                        "You are the Skill Proposer.\n## active skills\n"
                        "### skill: multiply\nTo compute a * b ...", tag="a3")
    assert json.loads(skilled_ctx.stdout)["proposal"]["skill"] == "color"


# ---------------- hermes: isolation, no execution ----------------
def test_hermes_dry_run_builds_argv_without_executing(tmp_path):
    b = get_backend("hermes")
    r = b.run(str(tmp_path), "hello", tag="dry", dry_run=True)
    assert r.dry_run and "--query-file" in r.cmd and "-Q" in r.cmd and "--oneshot" in r.cmd
    assert r.extra["env"]["HERMES_HOME"].endswith(hermes_mod.PROFILE_DIR)


def test_hermes_bootstrap_copies_credentials_into_isolated_profile(tmp_path, monkeypatch):
    real = tmp_path / "real-home"
    real.mkdir()
    (real / "config.yaml").write_text("model:\n  default: kimi-k3\n", encoding="utf-8")
    (real / ".env").write_text("FOO=bar\n", encoding="utf-8")
    prof = hermes_mod.bootstrap(str(tmp_path / "ws"), real=str(real))
    for d in ("sessions", "skills", "memories", "logs"):
        assert os.path.isdir(os.path.join(prof, d))
    assert (tmp_path / "ws" / hermes_mod.PROFILE_DIR / "config.yaml").exists()
    assert (tmp_path / "ws" / hermes_mod.PROFILE_DIR / ".env").exists()
    # env override points subprocesses at the isolated profile
    env = hermes_mod.hermes_env(str(tmp_path / "ws"))
    assert env["HERMES_HOME"] == prof
    # idempotent: second run doesn't clobber an edited profile config
    cfg = tmp_path / "ws" / hermes_mod.PROFILE_DIR / "config.yaml"
    cfg.write_text("model:\n  default: edited\n", encoding="utf-8")
    hermes_mod.bootstrap(str(tmp_path / "ws"), real=str(real))
    assert "edited" in cfg.read_text(encoding="utf-8")
