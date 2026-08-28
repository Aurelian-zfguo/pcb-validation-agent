import json

from src.agent.graph.nodes import attribute, attribute_skipped
from src.agent.llm.client import MockLLMClient
from src.agent.schema import Anomaly
from src.agent.trace.tracer import Tracer

SKIP_WARNING = "[警告] 未配置API密钥，跳过LLM归因（报告仅含规则判定与证据）"


def _anomaly():
    return Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="测试",
                   order_id="SO-1", description="在线有板仍入库",
                   evidence={"在线数": 10, "需求数": 20})


def _entries(tracer):
    return [json.loads(l) for l in
            tracer.file.read_text(encoding="utf-8").strip().splitlines()]


def test_attribute_produces_attributions_with_mock_client(tmp_path):
    out = attribute({"anomalies": [_anomaly()], "llm_client": MockLLMClient(),
                     "settings": {"knowledge": {"base_url": "http://127.0.0.1:9",
                                                "timeout_seconds": 0.01}},
                     "tracer": Tracer(tmp_path)})
    assert len(out["attributions"]) == 1
    assert "error" not in out


def test_attribute_degrades_instead_of_aborting(tmp_path, monkeypatch):
    """归因崩了不能拖垮主流程（决策记录#4）。"""
    import src.agent.graph.nodes as nodes

    def boom(*a, **k):
        raise RuntimeError("DeepSeek 挂了")

    monkeypatch.setattr(nodes, "attribute_anomalies", boom)
    tracer = Tracer(tmp_path)
    out = attribute({"anomalies": [_anomaly()], "llm_client": MockLLMClient(),
                     "settings": {}, "tracer": tracer})
    assert "error" not in out and "exit_code" not in out
    assert any("DeepSeek 挂了" in m for m in out["messages"])
    assert _entries(tracer)[0]["status"] == "fail"


def test_attribute_skipped_no_anomalies(tmp_path):
    tracer = Tracer(tmp_path)
    out = attribute_skipped({"anomalies": [], "llm_client": None,
                             "tracer": tracer})
    assert out["attributions"] == []
    assert out["skip_reason"] == "无异常"
    assert out["messages"] == []
    entry = _entries(tracer)[0]
    assert entry["step"] == "attribute" and entry["status"] == "skip"


def test_attribute_skipped_no_api_key_emits_legacy_warning(tmp_path):
    """警告文案必须与旧 main.py:160 逐字一致，gui.py 的日志框依赖它。"""
    tracer = Tracer(tmp_path)
    out = attribute_skipped({"anomalies": [_anomaly()], "llm_client": None,
                             "tracer": tracer})
    assert out["skip_reason"] == "无API密钥"
    assert out["messages"] == [SKIP_WARNING]
    assert _entries(tracer)[0]["detail"]["reason"] == "无API密钥"
