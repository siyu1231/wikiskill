"""Concurrency contract: workers>1 must be transparent — identical traces in task
order, live progress output in both modes, and headers that expose the worker count
(so experiments can be reconstructed from logs)."""
from wikiskill.cli import main
from wikiskill.harness import BackendRollout, Task

TASKS = [
    Task(id="a1", prompt="Compute 3 + 5 and reply with only the number.", expected="8"),
    Task(id="a2", prompt="Compute 12 - 4 and reply with only the number.", expected="8"),
    Task(id="b1", prompt="Greet the user politely.", expected="x"),      # mock: idk -> FAIL
    Task(id="b2", prompt="Compute 2 * 3 and reply with only the number.", expected="6"),
    Task(id="c1", prompt="Compute 100 / 4 and reply with only the number.", expected="25"),
]


def _run(root, workers):
    r = BackendRollout(_backend(), str(root), workers=workers, verbose=False)
    return r(TASKS, "", 1, "val")


class _Mock:
    pass


def _backend():
    from wikiskill.backends import get_backend
    return get_backend("mock")


def test_parallel_traces_identical_to_serial_in_task_order(tmp_path):
    serial = _run(tmp_path / "s", workers=1)
    parallel = _run(tmp_path / "p", workers=4)
    key = lambda t: (t["task_id"], t["answer"], t["pass"], t["run"]["tag"])
    assert [key(t) for t in serial] == [key(t) for t in parallel]
    assert [t["task_id"] for t in parallel] == [t.id for t in TASKS]  # task order


def test_parallel_writes_all_run_dirs(tmp_path):
    _run(tmp_path / "p", workers=3)
    runs = tmp_path / "p" / "runs"
    tags = {t.id for t in TASKS}
    dirs = {d.name for d in runs.iterdir() if d.is_dir() and d.name != "work"}
    assert dirs == {f"iter-0001-val-{t}" for t in tags}
    for t in TASKS:
        assert (runs / f"iter-0001-val-{t.id}" / "query.txt").exists()
        assert (runs / f"iter-0001-val-{t.id}" / "stdout.txt").exists()


def test_serial_progress_prints_each_task(tmp_path, capsys):
    r = BackendRollout(_backend(), str(tmp_path), workers=1, verbose=True)
    r(TASKS, "", 1, "val")
    out = capsys.readouterr().out
    for t in TASKS:
        assert out.count(f"{t.id} ") == 1, f"{t.id} not printed exactly once"


def test_parallel_progress_prints_each_task_live(tmp_path, capsys):
    r = BackendRollout(_backend(), str(tmp_path), workers=4, verbose=True)
    r(TASKS, "", 1, "val")
    out = capsys.readouterr().out
    for t in TASKS:
        assert out.count(f"{t.id} ") == 1, f"{t.id} not printed exactly once"


def test_verbose_false_prints_nothing(tmp_path, capsys):
    r = BackendRollout(_backend(), str(tmp_path), workers=2, verbose=False)
    r(TASKS, "", 1, "val")
    assert capsys.readouterr().out == ""


def test_init_persists_workers(tmp_path, capsys):
    ws = str(tmp_path / "ws")
    main(["init", ws, "--workers", "4"])
    out = capsys.readouterr().out
    assert "workers   : 4 (parallel rollout)" in out
    import json
    cfg = json.loads((tmp_path / "ws" / "workspace.json").read_text(encoding="utf-8"))
    assert cfg["workers"] == 4


def test_status_and_evolve_headers_expose_workers(tmp_path, capsys):
    ws = str(tmp_path / "ws")
    main(["init", ws, "--backend", "mock", "--workers", "4"])
    capsys.readouterr()
    main(["status", ws])
    assert "workers: 4" in capsys.readouterr().out
    main(["evolve", ws, "--iters", "1", "--workers", "4", "-q"])
    out = capsys.readouterr().out
    assert "workers=4" in out


def test_default_workers_is_one(tmp_path, capsys):
    ws = str(tmp_path / "ws")
    main(["init", ws, "--backend", "mock"])
    out = capsys.readouterr().out
    assert "workers   :" not in out   # unchanged default stays silent
    import json
    cfg = json.loads((tmp_path / "ws" / "workspace.json").read_text(encoding="utf-8"))
    assert cfg["workers"] == 1
