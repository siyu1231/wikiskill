"""Hermes Agent backend (reference adapter).

Adapted from ashutoshsinghpr7/wikiskill (MIT). Deviations on purpose:
- skills are NOT symlinked into the profile — the harness injects full active
  skill text into the prompt (paper §3.2.1), so profile skills/ stays opted out;
- runs/ layout and stdout parsing live in harness.py (design.md §8 layering).

Isolation: a dedicated HERMES_HOME per workspace with copied config/.env
credentials but fresh sessions/ and memories/ — inference runs cannot see the
user's real profile memory, and the prompt (not ambient state) is the only
skill signal.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time

from .base import RunResult, register

PROFILE_DIR = ".hermes-home"
DEFAULT_TOOLSETS = "terminal,file"


def real_home() -> str:
    if os.environ.get("HERMES_HOME"):
        return os.environ["HERMES_HOME"]
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return os.path.join(local, "hermes")
    return os.path.expanduser("~/.hermes")


def hermes_bin() -> str:
    """Resolve the hermes executable: env override > PATH > standard install."""
    override = os.environ.get("WIKISKILL_HERMES_BIN")
    if override:
        return override
    found = shutil.which("hermes")
    if found:
        return found
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        std = os.path.join(local, "hermes", "hermes-agent", "venv", "Scripts", "hermes.exe")
        if os.path.exists(std):
            return std
    for cand in ("/usr/local/bin/hermes", os.path.expanduser("~/.local/bin/hermes")):
        if os.path.exists(cand):
            return cand
    return "hermes"


def profile_dir(ws_root: str) -> str:
    return os.path.join(ws_root, PROFILE_DIR)


def hermes_env(ws_root: str) -> dict:
    env = dict(os.environ)
    env["HERMES_HOME"] = profile_dir(ws_root)
    return env


def bootstrap(ws_root: str, real: str | None = None) -> str:
    """Create the isolated profile: copy secrets/config, empty sessions+memory,
    opt out of bundled-skill seeding (profile skills/ must stay empty so the
    prompt injection is the ONLY skill signal). Idempotent."""
    real = real or real_home()
    prof = profile_dir(ws_root)
    for d in ("sessions", "skills", "memories", "logs"):
        os.makedirs(os.path.join(prof, d), exist_ok=True)
    for f in ("config.yaml", ".env", "auth.json"):
        src = os.path.join(real, f)
        dst = os.path.join(prof, f)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
    try:
        subprocess.run([hermes_bin(), "skills", "opt-out"], env=hermes_env(ws_root),
                       capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return prof


def _session_id_from_stdout(stdout_path: str) -> str | None:
    try:
        with open(stdout_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    m = re.search(r"[Ss]ession[ _-]?id[:\s]+([0-9a-zA-Z_\-]+)", text)
    return m.group(1) if m else None


def export_session(ws_root: str, dest: str, session_id: str | None = None) -> str | None:
    """OPTIONAL capability: export the isolated profile's session as JSONL."""
    env = hermes_env(ws_root)
    try:
        if session_id is None:
            p = subprocess.run([hermes_bin(), "sessions", "list"], env=env,
                               capture_output=True, text=True, timeout=60)
            ids = [ln.strip().split()[-1] for ln in p.stdout.splitlines()
                   if ln.strip() and not ln.strip().startswith("Title") and "─" not in ln]
            if not ids:
                return None
            session_id = ids[0]  # newest first
        q = subprocess.run([hermes_bin(), "sessions", "export", "--format", "jsonl",
                            "--session-id", session_id, dest],
                           env=env, capture_output=True, text=True, timeout=120)
        if q.returncode != 0 or not os.path.exists(dest):
            return None
        return dest
    except (OSError, subprocess.TimeoutExpired):
        return None


class HermesBackend:
    name = "hermes"
    profile_dir_name = PROFILE_DIR

    def bootstrap(self, ws_root: str) -> None:
        bootstrap(ws_root)

    def run(self, ws_root: str, prompt: str, *, tag: str,
            toolsets: str | None = None, max_turns: int = 15,
            run_budget: int = 300, workdir: str | None = None,
            dry_run: bool = False) -> RunResult:
        run_dir = os.path.join(ws_root, "runs", tag)
        os.makedirs(run_dir, exist_ok=True)
        qfile = os.path.join(run_dir, "query.txt")
        with open(qfile, "w", encoding="utf-8") as f:
            f.write(prompt)

        cmd = [hermes_bin(), "chat", "--query-file", qfile, "-Q", "--oneshot",
               "-t", toolsets or DEFAULT_TOOLSETS, "--max-turns", str(max_turns),
               "--run-budget", str(run_budget)]
        if workdir:
            cmd += ["--in", workdir]

        if dry_run:
            return RunResult(cmd=cmd, dry_run=True,
                             extra={"run_dir": run_dir, "qfile": qfile,
                                    "env": {"HERMES_HOME": profile_dir(ws_root)}})

        t0 = time.time()
        out_path = os.path.join(run_dir, "stdout.txt")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                p = subprocess.run(cmd, env=hermes_env(ws_root), stdout=f,
                                   stderr=subprocess.STDOUT, text=True,
                                   timeout=run_budget + 120)
            exit_code = p.returncode
        except subprocess.TimeoutExpired:
            exit_code = -1
        dur = round(time.time() - t0, 1)
        stdout = ""
        if os.path.exists(out_path):
            with open(out_path, encoding="utf-8", errors="replace") as f:
                stdout = f.read()
        session_file = export_session(ws_root, os.path.join(run_dir, "session.jsonl"),
                                      _session_id_from_stdout(out_path))
        return RunResult(cmd=cmd, exit_code=exit_code, duration_s=dur,
                         stdout=stdout, stdout_path=out_path, session_file=session_file)

    # optional capability (design.md §3): full transcript export
    def export_transcript(self, ws_root: str, dest: str, session_id: str | None = None) -> str | None:
        return export_session(ws_root, dest, session_id)


register("hermes", HermesBackend)
