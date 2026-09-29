"""Runner layer (design.md §8.1): backend runner renders roles into prompts."""
import json

from wikiskill.backends import get_backend
from wikiskill.prompts import MAINTAINER_SYSTEM, PROPOSER_SYSTEM
from wikiskill.runners import BackendRunner, make_runner, render_prompt


def test_render_prompt_includes_system_and_roles():
    out = render_prompt([{"role": "user", "content": "hello"},
                         {"role": "assistant", "content": "hi"}], system="SYS")
    assert out.startswith("SYS") and "[USER]\nhello" in out and "[ASSISTANT]\nhi" in out


def test_backend_runner_executes_roles_through_backend(tmp_path):
    b = get_backend("mock")
    runner = BackendRunner(b, str(tmp_path))
    # the mock keys on the role system prompt -> proves it was rendered into
    # the prompt passed to the backend
    reply = runner.chat([{"role": "user", "content": "go"}], system=MAINTAINER_SYSTEM)
    assert json.loads(reply)["patches"]
    reply2 = runner.chat([{"role": "user", "content": "## active skills\n(none)"}],
                         system=PROPOSER_SYSTEM)
    assert json.loads(reply2)["proposal"]["skill"] == "multiply"


def test_make_runner_backend_and_direct(tmp_path):
    b = get_backend("mock")
    r = make_runner("backend", b, str(tmp_path), {})
    assert isinstance(r, BackendRunner)
    import pytest
    with pytest.raises(SystemExit, match="requires an API key"):
        make_runner("direct", b, str(tmp_path), {"model": "m"})
    with pytest.raises(SystemExit, match="unknown runner"):
        make_runner("weird", b, str(tmp_path), {})
