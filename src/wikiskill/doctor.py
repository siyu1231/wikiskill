"""wikiskill doctor — one-command environment self-check.

The agently-cli `+me` equivalent: verify before an expensive evolve run that
the package, backends, agent binary, workspace and (optionally) the direct
LLM endpoint are all usable.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    skipped: bool = False


# ------------------------------------------------------------- probes
def _find_hermes() -> str | None:
    p = shutil.which("hermes")
    if p:
        return p
    la = os.environ.get("LOCALAPPDATA")
    if la:
        cand = Path(la) / "hermes" / "hermes-agent" / "venv" / "Scripts" / \
            ("hermes.exe" if os.name == "nt" else "hermes")
        if cand.exists():
            return str(cand)
    return None


def _hermes_version(path: str) -> str:
    import subprocess
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20)
    except Exception as e:  # noqa: BLE001
        return f"spawn failed: {e}"
    first = (r.stdout or r.stderr or "").strip().splitlines()
    return first[0] if first else f"exit {r.returncode}"


def _probe(base_url: str, api_key: str, timeout: float = 10.0) -> Check:
    """GET {base}/models — free, no token cost. Verifies reachability + auth."""
    if not base_url:
        return Check("llm-probe", False,
                     "no base_url (workspace.json llm.base_url / --llm-base / OPENAI_BASE_URL)")
    import urllib.error
    import urllib.request
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"User-Agent": "wikiskill-doctor/0.1"})
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = resp.status == 200
            return Check("llm-probe", ok, f"{url} -> HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        hint = " (auth rejected — check api_key)" if e.code in (401, 403) else ""
        return Check("llm-probe", False, f"{url} -> HTTP {e.code}{hint}")
    except Exception as e:  # noqa: BLE001
        return Check("llm-probe", False, f"{url} unreachable: {e.__class__.__name__}: {e}")


# ------------------------------------------------------------- checks
def checks(ws_dir: str | None = None, probe_llm: bool = False) -> list[Check]:
    out: list[Check] = []

    v = sys.version_info
    out.append(Check("python", v >= (3, 10), f"{v.major}.{v.minor}.{v.micro}"))

    try:
        from importlib.metadata import version
        out.append(Check("package", True, f"wikiskill {version('wikiskill')}"))
    except Exception:  # noqa: BLE001
        out.append(Check("package", True, "importable (version unknown — editable install)"))

    from .backends import available_backends
    out.append(Check("backends", "mock" in available_backends(),
                     ", ".join(available_backends())))

    cfg: dict | None = None
    backend_name = "mock"
    ws: Path | None = None
    if ws_dir:
        ws = Path(ws_dir).resolve()
        cfgp = ws / "workspace.json"
        if not cfgp.exists():
            out.append(Check("workspace", False,
                             f"missing workspace.json: {ws} (run: wikiskill init {ws_dir})"))
        else:
            try:
                cfg = json.loads(cfgp.read_text(encoding="utf-8"))
                backend_name = cfg.get("backend", "mock")
                out.append(Check("workspace", True, f"{ws}  backend={backend_name}"))
            except Exception as e:  # noqa: BLE001
                out.append(Check("workspace", False, f"workspace.json unreadable: {e}"))

    # hermes binary — only required when the workspace backend is hermes
    hp = _find_hermes()
    if hp:
        ver = _hermes_version(hp)
        out.append(Check("hermes-cli", "spawn failed" not in ver and "exit" not in ver,
                         f"{hp}  ({ver})"))
    else:
        needed = backend_name == "hermes"
        out.append(Check("hermes-cli", not needed,
                         "not found — install hermes or use --backend mock" if needed
                         else "not found (backend=mock — not required)"))

    if ws and ws.exists():
        missing = [d for d in ("raw", "wiki", "skills") if not (ws / d).is_dir()]
        out.append(Check("layers", not missing,
                         "raw/ wiki/ skills/ present" if not missing
                         else f"missing layer dirs: {', '.join(missing)}"))

        tp = ws / (cfg or {}).get("tasks", "tasks.jsonl")
        if tp.exists():
            try:
                from .harness import load_tasks, split_tasks
                tasks = load_tasks(tp)
                train, val = split_tasks(tasks, seed=(cfg or {}).get("seed", 42))
                ids = [t.id for t in tasks]
                ok = len(ids) == len(set(ids)) and len(train) > 0 and len(val) > 0
                out.append(Check("tasks", ok,
                                 f"{len(tasks)} tasks -> train {len(train)} / val {len(val)}"
                                 + ("" if ok else " (duplicate ids or empty split)")))
            except Exception as e:  # noqa: BLE001
                out.append(Check("tasks", False, str(e)))
        else:
            out.append(Check("tasks", False, f"missing {tp.name}"))

        if backend_name == "hermes":
            prof = ws / ".hermes-home"
            if prof.is_dir() and (prof / "config.yaml").exists():
                out.append(Check("hermes-profile", True, "isolated profile + config.yaml present"))
            else:
                out.append(Check("hermes-profile", True,
                                 "not bootstrapped yet (created idempotently on first run)"))

    if probe_llm:
        llm = (cfg or {}).get("llm") or {}
        out.append(_probe(llm.get("base_url") or os.environ.get("OPENAI_BASE_URL", ""),
                          llm.get("api_key") or os.environ.get("OPENAI_API_KEY", "")))
    else:
        out.append(Check("llm-probe", True, "skipped (pass --probe-llm to test direct endpoint)",
                         skipped=True))
    return out


def report(cs: list[Check], ws: str | None = None) -> int:
    print(f"wikiskill doctor{f'  ws={Path(ws).resolve()}' if ws else '  (global)'}")
    width = max(len(c.name) for c in cs)
    for c in cs:
        tag = "SKIP" if c.skipped else ("OK  " if c.ok else "FAIL")
        print(f"[{tag}] {c.name:<{width}}  {c.detail}")
    failed = [c for c in cs if not c.ok and not c.skipped]
    print(f"---\n{len(cs)} checks: {len(cs) - len(failed)} ok, {len(failed)} failed")
    return 1 if failed else 0
