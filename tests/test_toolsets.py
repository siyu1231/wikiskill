"""Generic toolsets plumbing: init --toolsets -> workspace.json -> rollout/runner
-> backend.run(toolsets=...). Core only transports; vocabulary belongs to adapters."""
import json

from wikiskill import doctor
from wikiskill.backends import get_backend
from wikiskill.backends.base import RunResult
from wikiskill.backends.hermes import HermesBackend
from wikiskill.cli import main
from wikiskill.harness import BackendRollout, Task
from wikiskill.runners import BackendRunner, make_runner


class RecBackend:
    """Records the toolsets it was called with."""
    name = "rec"

    def __init__(self):
        self.seen = []

    def run(self, ws_root, prompt, *, tag, toolsets=None, **kw):
        self.seen.append(toolsets)
        return RunResult(cmd=["rec", "--tag", tag], exit_code=0, stdout="ANSWER: 1")


def test_rollout_passes_configured_toolsets(tmp_path):
    b = RecBackend()
    r = BackendRollout(b, str(tmp_path), toolsets="terminal,file,vision", verbose=False)
    r([Task(id="t1", prompt="p", expected="1")], "", 1, "val")
    assert b.seen == ["terminal,file,vision"]


def test_rollout_default_is_none_meaning_adapter_default(tmp_path):
    b = RecBackend()
    r = BackendRollout(b, str(tmp_path), verbose=False)
    r([Task(id="t1", prompt="p", expected="1")], "", 1, "val")
    assert b.seen == [None]   # core never hardcodes adapter vocabulary


def test_make_runner_passes_toolsets(tmp_path):
    runner = make_runner("backend", get_backend("mock"), str(tmp_path), toolsets="a,b")
    assert isinstance(runner, BackendRunner)
    assert runner.toolsets == "a,b"
    # default -> None -> adapter default
    runner2 = make_runner("backend", get_backend("mock"), str(tmp_path))
    assert runner2.toolsets is None


def test_init_stores_toolsets_in_workspace_json(tmp_path, capsys):
    ws = str(tmp_path / "ws")
    main(["init", ws, "--toolsets", "terminal,file,vision"])
    cfg = json.loads((tmp_path / "ws" / "workspace.json").read_text(encoding="utf-8"))
    assert cfg["toolsets"] == "terminal,file,vision"
    assert "toolsets  : terminal,file,vision" in capsys.readouterr().out


def test_init_default_toolsets_empty(tmp_path):
    ws = str(tmp_path / "ws")
    main(["init", ws])
    cfg = json.loads((tmp_path / "ws" / "workspace.json").read_text(encoding="utf-8"))
    assert cfg["toolsets"] == ""


def test_hermes_adapter_maps_toolsets_to_cli_flag(tmp_path):
    res = HermesBackend().run(str(tmp_path), "p", tag="t",
                              toolsets="terminal,file,vision", dry_run=True)
    assert "-t" in res.cmd
    assert res.cmd[res.cmd.index("-t") + 1] == "terminal,file,vision"
    # no toolsets -> adapter default (still explicit in argv, from DEFAULT_TOOLSETS)
    res2 = HermesBackend().run(str(tmp_path), "p", tag="t", dry_run=True)
    assert res2.cmd[res2.cmd.index("-t") + 1] == "terminal,file"


def test_doctor_shows_toolsets(tmp_path):
    ws = str(tmp_path / "ws")
    main(["init", ws, "--toolsets", "a,b"])
    by = {c.name: c for c in doctor.checks(ws)}
    assert "toolsets=a,b" in by["workspace"].detail

    ws2 = str(tmp_path / "ws2")
    main(["init", ws2])
    by2 = {c.name: c for c in doctor.checks(ws2)}
    assert "toolsets=(adapter default)" in by2["workspace"].detail
