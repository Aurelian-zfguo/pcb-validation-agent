import json

from src.agent.trace.tracer import Tracer


def test_tracer_appends_jsonl_lines(tmp_path):
    t = Tracer(tmp_path)
    t.log("parse", "ok", {"rows": 3})
    t.log("validate", "fail", {"rule_id": "BAD", "error": "boom"})
    lines = t.file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["step"] == "parse" and first["status"] == "ok"
    assert first["detail"]["rows"] == 3
    assert "ts" in first
    second = json.loads(lines[1])
    assert second["detail"]["error"] == "boom"


def test_tracer_creates_dir_and_names_file(tmp_path):
    t = Tracer(tmp_path / "nested" / "dir")
    assert t.file.exists()
    assert t.file.name.startswith("trace_") and t.file.name.endswith(".jsonl")
