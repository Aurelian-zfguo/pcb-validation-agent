import json

import pandas as pd
import pytest

from src.agent.graph.nodes import enrich, validate
from src.agent.rules.base import RulePlugin
from src.agent.schema import Anomaly, StandardReport
from src.agent.trace.tracer import Tracer


def _report(df=None, quality_issues=None):
    return StandardReport(
        report_type="综合日报", factory="测试", source_path="x",
        df=df if df is not None else pd.DataFrame(
            {"订单号": ["SO-1"], "_行号": [1], "入库数": [0],
             "在线数": [0], "已产出数": [0], "需求数": [0], "报废数": [0]}),
        quality_issues=quality_issues or [])


def test_enrich_is_noop_when_no_order_and_no_hist(tmp_path):
    """测试模式：order_df=None、hist_index={} —— 正常通过，不写 error。"""
    rep = _report()
    before = rep.df.copy()
    out = enrich({"report": rep, "order_df": None, "hist_index": {},
                  "tracer": Tracer(tmp_path)})
    assert "error" not in out
    pd.testing.assert_frame_equal(out["report"].df, before)


def test_enrich_is_noop_when_order_df_is_empty(tmp_path):
    """订单表存在但过滤后为空，属正常业务场景，不得报错。"""
    out = enrich({"report": _report(), "order_df": pd.DataFrame(),
                  "hist_index": {}, "tracer": Tracer(tmp_path)})
    assert "error" not in out


def test_enrich_aborts_when_join_itself_raises(tmp_path, monkeypatch):
    """匹配过程本身出错才 abort。"""
    import src.agent.graph.nodes as nodes

    def boom(*a, **k):
        raise ValueError("join 崩了")

    monkeypatch.setattr(nodes, "join_order_info", boom)
    out = enrich({"report": _report(), "order_df": pd.DataFrame({"a": [1]}),
                  "hist_index": {}, "tracer": Tracer(tmp_path)})
    assert out["exit_code"] == 2
    assert "join 崩了" in out["error"]


class _BoomRule(RulePlugin):
    rule_id = "RX"
    rule_name = "会炸的规则"

    def validate(self, report):
        raise RuntimeError("规则内部错误")


def test_validate_merges_quality_issues_and_rule_anomalies(tmp_path):
    from src.agent.graph.nodes import build_engine
    d0 = Anomaly(rule_id="D0", rule_name="数据质量", factory="测试",
                 order_id="SO-1", description="缺订单号")
    out = validate({"report": _report(quality_issues=[d0]),
                    "engine": build_engine(), "tracer": Tracer(tmp_path)})
    assert out["anomalies"][0].rule_id == "D0"
    assert out["rule_errors"] == []


def test_validate_isolates_failing_rule_and_traces_it(tmp_path):
    from src.agent.engine import ValidationEngine
    tracer = Tracer(tmp_path)
    engine = ValidationEngine()
    engine.register(_BoomRule())
    out = validate({"report": _report(), "engine": engine, "tracer": tracer})
    assert "error" not in out              # 单条规则失败不中断流程
    assert out["rule_errors"][0]["rule_id"] == "RX"
    entries = [json.loads(l) for l in
               tracer.file.read_text(encoding="utf-8").strip().splitlines()]
    assert any(e["step"] == "validate" and e["status"] == "fail" for e in entries)
