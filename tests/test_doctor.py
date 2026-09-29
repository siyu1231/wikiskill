"""doctor: env self-check pass/fail semantics."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from wikiskill import doctor
from wikiskill.cli import main


def _fake_hermes(monkeypatch, path="C:/fake/hermes.exe", ver="hermes 9.9.9-test"):
    monkeypatch.setattr(doctor, "_find_hermes", lambda: path)
    monkeypatch.setattr(doctor, "_hermes_version", lambda p: ver)


def _init_mock(tmp_path):
    ws = str(tmp_path / "ws")
    main(["init", ws])
    return ws


# ---------------- global / workspace checks ----------------
def test_global_checks_pass(tmp_path, monkeypatch):
    _fake_hermes(monkeypatch)
    cs = doctor.checks()  # no workspace
    assert all(c.ok or c.skipped for c in cs)
    assert any(c.name == "llm-probe" and c.skipped for c in cs)
    assert doctor.report(cs) == 0


def test_fresh_workspace_all_ok(tmp_path, monkeypatch):
    _fake_hermes(monkeypatch)
    ws = _init_mock(tmp_path)
    cs = doctor.checks(ws)
    by = {c.name: c for c in cs}
    assert by["workspace"].ok and by["layers"].ok and by["tasks"].ok
    assert "train 8 / val 4" in by["tasks"].detail
    assert doctor.report(cs, ws) == 0


def test_missing_workspace_fails(tmp_path, monkeypatch):
    _fake_hermes(monkeypatch)
    cs = doctor.checks(str(tmp_path / "nope"))
    by = {c.name: c for c in cs}
    assert not by["workspace"].ok
    assert doctor.report(cs) == 1


def test_hermes_required_when_backend_hermes(tmp_path, monkeypatch):
    ws = str(tmp_path / "ws-real")
    main(["init", ws, "--backend", "hermes"])   # real bootstrap, offline
    monkeypatch.setattr(doctor, "_find_hermes", lambda: None)
    by = {c.name: c for c in doctor.checks(ws)}
    assert not by["hermes-cli"].ok and "install hermes" in by["hermes-cli"].detail
    # profile check itself is advisory (bootstrapped idempotently on first run)
    assert by["hermes-profile"].ok
    assert doctor.report(doctor.checks(ws), ws) == 1

    # mock workspace: hermes binary not required
    ws_m = _init_mock(tmp_path)
    by_m = {c.name: c for c in doctor.checks(ws_m)}
    assert by_m["hermes-cli"].ok


# ---------------- llm probe ----------------
class _ModelsHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.endswith("/models"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data": []}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):  # silence
        pass


@pytest.fixture()
def fake_endpoint():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _ModelsHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()
    srv.server_close()


def test_probe_ok(tmp_path, monkeypatch, fake_endpoint):
    _fake_hermes(monkeypatch)
    ws = _init_mock(tmp_path)
    cfgp = tmp_path / "ws" / "workspace.json"
    cfg = json.loads(cfgp.read_text(encoding="utf-8"))
    cfg["llm"]["base_url"] = fake_endpoint
    cfgp.write_text(json.dumps(cfg), encoding="utf-8")
    by = {c.name: c for c in doctor.checks(ws, probe_llm=True)}
    assert by["llm-probe"].ok and "HTTP 200" in by["llm-probe"].detail


def test_probe_unreachable_fails():
    c = doctor._probe("http://127.0.0.1:1/v1", "")
    assert not c.ok
    c2 = doctor._probe("", "")
    assert not c2.ok and "no base_url" in c2.detail
