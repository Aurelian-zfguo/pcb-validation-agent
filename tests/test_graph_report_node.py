import pandas as pd

from src.agent.graph.nodes import write_report
from src.agent.schema import Anomaly, StandardReport
from src.agent.trace.tracer import Tracer


def _state(tmp_path, **over):
    rep = StandardReport(
        report_type="综合日报", factory="测试", source_path="x",
        df=pd.DataFrame({"订单号": ["SO-1"], "_行号": [1], "客户": ["甲"]}))
    base = {"report": rep, "factory": "测试",
            "anomalies": [Anomaly(rule_id="R1", rule_name="违规入余数仓",
                                  factory="测试", order_id="SO-1",
                                  description="d", evidence={"行号": [1]})],
            "attributions": [], "settings": {"output": {"dir": "output"}},
            "output_dir": str(tmp_path / "out"), "tracer": Tracer(tmp_path)}
    base.update(over)
    return base


def test_write_report_produces_both_files_and_exit_zero(tmp_path):
    out = write_report(_state(tmp_path))
    assert out["exit_code"] == 0
    assert out["excel_path"].endswith(".xlsx")
    assert out["md_path"].endswith(".md")
    files = list((tmp_path / "out").iterdir())
    assert len(files) == 2


def test_write_report_survives_missing_attributions_key(tmp_path):
    """attribute 节点 degrade 失败时不返回 attributions，这里不能 KeyError。"""
    state = _state(tmp_path)
    state.pop("attributions")
    out = write_report(state)
    assert out["exit_code"] == 0


def test_write_report_keeps_customer_column_unmasked(tmp_path):
    """脱敏已移出本次范围（spec §12.1）：全量明细里客户名保持原文。"""
    out = write_report(_state(tmp_path))
    full = pd.read_excel(out["excel_path"], sheet_name="全量明细")
    assert full.loc[0, "客户"] == "甲"
