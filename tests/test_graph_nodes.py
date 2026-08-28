import json

from src.agent.graph.nodes import traced_node
from src.agent.trace.tracer import Tracer


def _entries(tracer):
    return [json.loads(l) for l in
            tracer.file.read_text(encoding="utf-8").strip().splitlines()]


def test_traced_node_logs_ok_and_strips_private_keys(tmp_path):
    tracer = Tracer(tmp_path)

    @traced_node("demo")
    def node(state):
        return {"foo": 1, "_trace": {"rows": 3}}

    out = node({"tracer": tracer})
    assert out == {"foo": 1}                 # _trace 已被剥离，不污染 State
    entry = _entries(tracer)[0]
    assert entry["step"] == "demo"
    assert entry["status"] == "ok"
    assert entry["detail"]["rows"] == 3
    assert isinstance(entry["detail"]["elapsed_ms"], int)


def test_traced_node_honours_custom_status(tmp_path):
    tracer = Tracer(tmp_path)

    @traced_node("attribute")
    def node(state):
        return {"_status": "skip", "_trace": {"reason": "无异常"}}

    out = node({"tracer": tracer})
    assert out == {}
    entry = _entries(tracer)[0]
    assert entry["status"] == "skip"
    assert entry["detail"]["reason"] == "无异常"


def test_traced_node_abort_writes_error_and_exit_code(tmp_path):
    tracer = Tracer(tmp_path)

    @traced_node("demo", on_error="abort")
    def node(state):
        raise RuntimeError("boom")

    out = node({"tracer": tracer})
    assert out["exit_code"] == 2
    assert "boom" in out["error"]
    entry = _entries(tracer)[0]
    assert entry["status"] == "fail"
    assert "boom" in entry["detail"]["error"]


def test_traced_node_degrade_does_not_abort(tmp_path):
    tracer = Tracer(tmp_path)

    @traced_node("demo", on_error="degrade")
    def node(state):
        raise RuntimeError("boom")

    out = node({"tracer": tracer})
    assert "error" not in out
    assert "exit_code" not in out
    assert len(out["messages"]) == 1 and "boom" in out["messages"][0]
    assert _entries(tracer)[0]["status"] == "fail"


def test_traced_node_without_tracer_does_not_crash():
    """load_config 自身运行时 State 里还没有 tracer。"""

    @traced_node("config")
    def node(state):
        return {"ok": True}

    assert node({}) == {"ok": True}


def test_traced_node_uses_tracer_returned_by_the_node_itself(tmp_path):
    """load_config 在自己内部创建 Tracer，装饰器要能用上它记录自己这条。"""
    made = Tracer(tmp_path)

    @traced_node("config")
    def node(state):
        return {"tracer": made, "_trace": {"provider": "mock"}}

    node({})
    assert _entries(made)[0]["detail"]["provider"] == "mock"


from src.agent.graph.nodes import build_engine, build_llm_client, load_config
from src.agent.llm.client import MockLLMClient


def test_build_engine_registers_four_rules():
    engine = build_engine()
    assert [r.rule_id for r in engine.rules] == ["R1", "R2", "R3", "R4"]


def test_build_llm_client_returns_mock_when_use_mock():
    client = build_llm_client({"llm": {"provider": "openai-compatible"}}, True)
    assert isinstance(client, MockLLMClient)


def test_build_llm_client_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    settings = {"llm": {"provider": "openai-compatible", "api_key": "",
                        "base_url": "http://x", "model": "m"}}
    assert build_llm_client(settings, False) is None


def test_load_config_populates_runtime_handles(tmp_path):
    out = load_config({"trace_dir": str(tmp_path), "use_mock": True})
    assert out["settings"]["llm"]["provider"]
    # load_field_mapping 返回原始 YAML，顶层键是 report_types
    assert "订单号" in out["field_mapping"]["report_types"]["补投日报"]
    assert out["tracer"].file.exists()
    assert [r.rule_id for r in out["engine"].rules] == ["R1", "R2", "R3", "R4"]
    assert isinstance(out["llm_client"], MockLLMClient)


def test_load_config_writes_its_own_trace_entry(tmp_path):
    out = load_config({"trace_dir": str(tmp_path), "use_mock": True})
    entry = _entries(out["tracer"])[0]
    assert entry["step"] == "config" and entry["status"] == "ok"
    assert entry["detail"]["llm_ready"] is True
