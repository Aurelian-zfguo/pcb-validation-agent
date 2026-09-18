import json
import pandas as pd

from src.agent.llm.attribution import (
    ATTRIBUTION_CATEGORIES, attribute_anomalies, build_prompt, parse_json_response)
from src.agent.llm.client import MockLLMClient
from src.agent.llm.desensitize import desensitize_report, desensitize_text
from src.agent.schema import Anomaly, StandardReport


def _make_anomalies():
    return [
        Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="珠海一厂",
                order_id="A001", description="在线有板且订单不够数时余数入库",
                evidence={"在线数": 10, "需求数": 20}),
        Anomaly(rule_id="R3", rule_name="重复补投（同日）", factory="珠海一厂",
                order_id="A003", description="同一订单当天重复补投",
                evidence={"补投次数": 2}),
    ]


def test_desensitize_stable_and_distinct():
    m = {}
    assert desensitize_text("客户甲", "客户", m) == desensitize_text("客户甲", "客户", m)
    assert desensitize_text("客户乙", "客户", m) != desensitize_text("客户甲", "客户", m)
    assert "客户甲" not in desensitize_text("客户甲", "客户", m)


def test_desensitize_report_masks_customer_and_part():
    df = pd.DataFrame({"订单号": ["A001"], "客户": ["客户甲"], "产品料号": ["PN-001"]})
    report = StandardReport(report_type="综合日报", factory="珠海一厂",
                            source_path="x.csv", df=df)
    safe_df, mapping = desensitize_report(report)
    assert safe_df.loc[0, "客户"] != "客户甲"
    assert safe_df.loc[0, "产品料号"] != "PN-001"
    assert len(mapping) == 2


def test_build_prompt_contains_evidence():
    prompt = build_prompt(_make_anomalies())
    assert "R1" in prompt and "在线数" in prompt and "补投次数" in prompt


def test_parse_json_response_extracts_array():
    text = "好的，结果如下：\n```json\n{\"results\": [{\"category\": \"违规行为\", \"explanation\": \"a\", \"suggestion\": \"b\"}]}\n```"
    parsed = parse_json_response(text)
    assert isinstance(parsed, list) and parsed[0]["category"] == "违规行为"


def test_parse_json_response_raises_on_garbage():
    import pytest
    with pytest.raises(ValueError):
        parse_json_response("这不是JSON")


def test_attribute_anomalies_with_mock():
    attrs = attribute_anomalies(_make_anomalies(), MockLLMClient())
    assert len(attrs) == 2
    assert all(a.order_id in {"A001", "A003"} for a in attrs)
    assert all(a.rule_id in {"R1", "R3"} for a in attrs)
    assert attrs[0].category in ATTRIBUTION_CATEGORIES + ["其他"]


def test_attribute_clamps_unknown_category():
    class WeirdClient:
        def chat(self, messages):
            return json.dumps({"results": [{"category": "外星原因", "explanation": "x", "suggestion": "y"}]},
                              ensure_ascii=False)
    attrs = attribute_anomalies(_make_anomalies(), WeirdClient())
    assert attrs[0].category == "其他"


def test_attribute_fallback_when_entries_missing():
    class EmptyClient:
        def chat(self, messages):
            return '{"results": []}'
    attrs = attribute_anomalies(_make_anomalies(), EmptyClient())
    assert len(attrs) == 2
    assert attrs[0].category == "未归因"


def test_attribute_pre_rate_overflow_marks_data_error():
    class AnyClient:
        def chat(self, messages):
            return json.dumps({"results": [{"category": "违规行为", "explanation": "x", "suggestion": "y"}]},
                              ensure_ascii=False)
    anomalies = [Anomaly(rule_id="R2", rule_name="x", factory="金州厂",
                         order_id="A001", description="x", evidence={"预大率": 1.5})]
    attrs = attribute_anomalies(anomalies, AnyClient())
    # 预大率>100% 强制标记为数据错误，覆盖 AI 的"违规行为"
    assert attrs[0].category == "数据错误"
    assert "超过100%" in attrs[0].explanation


def test_volatility_flags():
    from src.agent.llm.attribution import _volatility_flags
    # 阈值1 波动大：平均 > 剔除最高 × 1.5
    ev1 = {"近3批平均报废率": 0.05, "近3批剔除最高报废率": 0.02,
           "近6批平均报废率": 0.05, "近6批剔除最高2批报废率": 0.02}
    assert "波动大" in _volatility_flags(ev1)
    # 阈值2 超级异常：平均 - 剔除最高 > 0.10，且同时满足阈值1
    ev2 = {"近3批平均报废率": 0.15, "近3批剔除最高报废率": 0.02,
           "近6批平均报废率": 0.15, "近6批剔除最高2批报废率": 0.02}
    assert "超级异常" in _volatility_flags(ev2)
    assert "波动大" in _volatility_flags(ev2)
    # 都不满足
    ev3 = {"近3批平均报废率": 0.05, "近3批剔除最高报废率": 0.04,
           "近6批平均报废率": 0.05, "近6批剔除最高2批报废率": 0.04}
    assert _volatility_flags(ev3) == ""


# ─────────────────────────── 三层防护：解析降级 ───────────────────────────

def test_repair_truncated_json_simple_object():
    """最小截断样例：{"a": 1 → {"a": 1}"""
    from src.agent.llm.attribution import _repair_truncated_json
    assert _repair_truncated_json('{"a": 1') == '{"a": 1}'


def test_parse_json_response_repairs_truncated_json():
    # 括号不匹配但结构完整：少了末尾的 ] 和 }
    text = ('{"results": [{"category": "违规行为", "explanation": "a", '
            '"suggestion": "b"}')
    parsed = parse_json_response(text)
    assert parsed[0]["category"] == "违规行为"


def test_parse_json_response_gives_up_when_truncated_inside_string():
    # 截断在 explanation 字段中间（字符串未闭合）→ 修复函数放弃 → 抛 ValueError
    text = '{"results": [{"category": "违规行为", "explanation": "截断在半截'
    import pytest
    with pytest.raises(ValueError):
        parse_json_response(text)


def test_parse_json_response_accepts_top_level_array():
    # 防御性：顶层数组直接视为 results（实际不会触发）
    parsed = parse_json_response(
        '[{"category": "违规行为", "explanation": "a", "suggestion": "b"}]')
    assert parsed[0]["category"] == "违规行为"


def test_attribute_anomalies_parses_markdown_wrapped_json():
    """验收1：LLM 返回 markdown 包裹的 JSON，应正确解析。"""
    class MarkdownClient:
        def chat(self, messages):
            return ('好的，结果如下：\n```json\n'
                    '{"results": ['
                    '{"category": "违规行为", "explanation": "a", "suggestion": "b"},'
                    '{"category": "流程不清", "explanation": "c", "suggestion": "d"}'
                    ']}\n```')
    attrs = attribute_anomalies(_make_anomalies(), MarkdownClient())
    assert attrs[0].category == "违规行为"
    assert attrs[1].category == "流程不清"


def test_attribute_anomalies_degrade_on_pure_text():
    """验收2：完全无 JSON 时降级为未归因，不抛异常。"""
    class GarbageClient:
        def chat(self, messages):
            return "这不是JSON，是纯文本"
    attrs = attribute_anomalies(_make_anomalies(), GarbageClient())
    assert len(attrs) == 2
    assert all(a.category == "未归因" for a in attrs)
    assert all("解析失败" in a.explanation for a in attrs)


def test_attribute_anomalies_retries_then_succeeds():
    """第1层：格式感知重试——首次垃圾、第二次返回合法 JSON 应恢复。"""
    class FlakyClient:
        def __init__(self):
            self.calls = 0
        def chat(self, messages):
            self.calls += 1
            if self.calls == 1:
                return "第一次输出的是垃圾"
            return json.dumps({"results": [
                {"category": "违规行为", "explanation": "a", "suggestion": "b"},
                {"category": "流程不清", "explanation": "c", "suggestion": "d"},
            ]}, ensure_ascii=False)
    client = FlakyClient()
    attrs = attribute_anomalies(_make_anomalies(), client)
    assert client.calls == 2
    assert attrs[0].category == "违规行为"
    assert attrs[1].category == "流程不清"


# ─────────────────────────── Token 消耗统计 ───────────────────────────

def test_openai_compat_client_accumulates_usage(monkeypatch):
    """带 usage 的响应 → 每次调用累加 prompt/completion/call_count。"""
    from src.agent.llm.client import OpenAICompatClient

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                          "total_tokens": 150},
            }

    monkeypatch.setattr("requests.post", lambda *a, **k: FakeResp())
    client = OpenAICompatClient(base_url="http://x", api_key="k", model="m")
    client.chat([])
    client.chat([])
    assert client.call_count == 2
    assert client.total_prompt_tokens == 200
    assert client.total_completion_tokens == 100


def test_openai_compat_client_skips_missing_usage(monkeypatch):
    """不带 usage 的响应 → 不报错、统计保持 0。"""
    from src.agent.llm.client import OpenAICompatClient

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": "{}"},
                                 "finish_reason": "stop"}]}

    monkeypatch.setattr("requests.post", lambda *a, **k: FakeResp())
    client = OpenAICompatClient(base_url="http://x", api_key="k", model="m")
    client.chat([])
    assert client.call_count == 0
    assert client.total_prompt_tokens == 0
    assert client.total_completion_tokens == 0
