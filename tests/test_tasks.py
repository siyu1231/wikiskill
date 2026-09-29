"""wikiskill tasks check: authoring-spec gate (line-level errors + advisory warns)."""
import json

import pytest

from wikiskill.cli import main
from wikiskill.harness import load_tasks
from wikiskill.tasks import check_tasks


def _by(cs):
    return {c.name: c for c in cs}


def _write(tmp_path, lines, name="t.jsonl"):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


# ---------------- spec-valid file ----------------
def test_valid_file_passes(tmp_path):
    lines = [json.dumps({"id": f"t{i:02d}", "prompt": f"Compute {i} * {i + 1}.",
                         "expected": f"product={i * (i + 1)}"}) for i in range(1, 21)]
    f = _write(tmp_path, lines)
    cs = check_tasks(f)
    by = _by(cs)
    assert by["parse"].ok and by["ids"].ok and by["content"].ok and by["size"].ok
    assert "train 13 / val 7" in by["size"].detail      # 34% of 20
    assert not any(c.warn for c in cs)
    assert main(["tasks", "check", f]) == 0


# ---------------- line-level errors ----------------
def test_bad_json_reports_line_number(tmp_path):
    f = _write(tmp_path, [
        json.dumps({"id": "a1", "prompt": "p", "expected": "x"}),
        '{"id": "a2", "prompt": "p", }',          # line 2 broken
    ])
    by = _by(check_tasks(f))
    assert not by["parse"].ok and "line 2" in by["parse"].detail
    assert main(["tasks", "check", f]) == 1


def test_missing_field_reports_line(tmp_path):
    f = _write(tmp_path, [json.dumps({"id": "a1", "prompt": "p"})])
    by = _by(check_tasks(f))
    assert not by["parse"].ok and "expected" in by["parse"].detail and "line 1" in by["parse"].detail


def test_id_charset_and_duplicates(tmp_path):
    f = _write(tmp_path, [
        json.dumps({"id": "a/b", "prompt": "p1", "expected": "v"}),
        json.dumps({"id": "ok", "prompt": "p2", "expected": "v"}),
        json.dumps({"id": "ok", "prompt": "p3", "expected": "v"}),
    ])
    by = _by(check_tasks(f))
    assert not by["ids"].ok
    assert "[A-Za-z0-9._-]" in by["ids"].detail and "duplicate" in by["ids"].detail


def test_multiline_expected_rejected(tmp_path):
    f = _write(tmp_path, [json.dumps({"id": "a1", "prompt": "p", "expected": "v1\nv2"})])
    by = _by(check_tasks(f))
    assert not by["content"].ok and "single line" in by["content"].detail


def test_empty_prompt_rejected(tmp_path):
    f = _write(tmp_path, [json.dumps({"id": "a1", "prompt": "  ", "expected": "v"})])
    by = _by(check_tasks(f))
    assert not by["content"].ok and "prompt is empty" in by["content"].detail


# ---------------- advisory warnings (exit 0) ----------------
def test_warnings_do_not_fail(tmp_path):
    f = _write(tmp_path, [
        json.dumps({"id": "a1", "prompt": "The answer is 391. Repeat it.", "expected": "391."}),
        json.dumps({"id": "a2", "prompt": "Compute 2 + 2", "expected": "4"}),
    ])
    cs = check_tasks(f)
    by = _by(cs)
    assert by["grading-risk"].warn and not by["grading-risk"].ok
    assert "verbatim" in by["grading-risk"].detail or "punctuation" in by["grading-risk"].detail
    assert by["recommend"].warn     # N=2 < 20
    assert main(["tasks", "check", f]) == 0   # warns never block


def test_single_task_fails(tmp_path):
    f = _write(tmp_path, [json.dumps({"id": "a1", "prompt": "p", "expected": "v"})])
    by = _by(check_tasks(f))
    assert not by["size"].ok
    assert main(["tasks", "check", f]) == 1


def test_missing_file_fails(tmp_path):
    assert main(["tasks", "check", str(tmp_path / "nope.jsonl")]) == 1


# ---------------- load_tasks friendly errors ----------------
def test_load_tasks_message_has_line_and_hint(tmp_path):
    f = _write(tmp_path, ['{"id": "a1", "prompt": "p"}'])
    with pytest.raises(ValueError, match=r"line 1.*tasks check"):
        load_tasks(f)
