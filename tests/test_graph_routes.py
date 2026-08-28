from langgraph.graph import END

from src.agent.graph.nodes import (guard, route_after_parse,
                                   route_after_validate, route_mode)


# ── route_mode：双模式加载分支 + 配置失败短路 ──
def test_route_mode_picks_file_branch():
    assert route_mode({"file_path": "a.xlsx"}) == "parse_file"


def test_route_mode_picks_factory_branch():
    assert route_mode({"file_path": None, "factory": "金州厂"}) == "parse_factory"


def test_route_mode_short_circuits_on_config_error():
    assert route_mode({"error": "配置炸了", "file_path": "a.xlsx"}) == END


# ── route_after_parse：解析失败短路 ──
def test_route_after_parse_continues_to_enrich():
    assert route_after_parse({"report": object()}) == "enrich"


def test_route_after_parse_short_circuits_on_error():
    assert route_after_parse({"error": "无法识别订单号字段"}) == END


# ── route_after_validate：数据驱动分支 + 降级分支 ──
def test_route_after_validate_skips_when_no_anomalies():
    assert route_after_validate(
        {"anomalies": [], "llm_client": object()}) == "attribute_skipped"


def test_route_after_validate_skips_when_no_llm_client():
    assert route_after_validate(
        {"anomalies": [object()], "llm_client": None}) == "attribute_skipped"


def test_route_after_validate_attributes_normally():
    assert route_after_validate(
        {"anomalies": [object()], "llm_client": object()}) == "attribute"


def test_route_after_validate_short_circuits_on_error():
    assert route_after_validate(
        {"error": "校验炸了", "anomalies": [object()],
         "llm_client": object()}) == END


# ── guard 工厂 ──
def test_guard_passes_through_when_clean():
    assert guard("validate")({}) == "validate"


def test_guard_returns_end_on_error():
    assert guard("validate")({"error": "boom"}) == END
