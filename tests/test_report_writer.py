import pandas as pd

from src.agent.llm.attribution import Attribution
from src.agent.reporting.report_writer import write_excel_report, write_markdown_summary
from src.agent.schema import Anomaly


def _make_data():
    anomalies = [
        Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="珠海一厂",
                order_id="A001", description="在线有板且订单不够数时余数入库",
                evidence={"在线数": 10, "需求数": 20}, location="第2行"),
        Anomaly(rule_id="R3", rule_name="重复补投（同日）", factory="珠海一厂",
                order_id="A003", description="同一订单当天重复补投",
                evidence={"补投次数": 2}, location="第4行"),
    ]
    attributions = [
        Attribution(order_id="A001", rule_id="R1", category="违规行为",
                    explanation="入库时在线10块且未达需求数", suggestion="通报工厂纠正"),
    ]
    return anomalies, attributions


def test_excel_report_two_sheets_and_columns(tmp_path):
    anomalies, attributions = _make_data()
    out = str(tmp_path / "报告.xlsx")
    assert write_excel_report(anomalies, attributions, out) == out
    detail = pd.read_excel(out, sheet_name="异常明细")
    assert list(detail.columns)[:4] == ["序号", "工厂", "订单号", "规则编号"]
    assert len(detail) == 2
    assert detail.loc[0, "归因分类"] == "违规行为"
    assert detail.loc[1, "归因分类"] == "—"  # 无归因时占位
    summary = pd.read_excel(out, sheet_name="汇总统计")
    assert not summary.empty


def test_markdown_summary_contains_rules(tmp_path):
    anomalies, attributions = _make_data()
    out = str(tmp_path / "摘要.md")
    assert write_markdown_summary(anomalies, attributions, out) == out
    text = open(out, encoding="utf-8").read()
    assert "R1" in text and "违规入余数仓" in text and "珠海一厂" in text


def test_empty_anomalies_still_writes(tmp_path):
    out = str(tmp_path / "空.xlsx")
    write_excel_report([], [], out)
    detail = pd.read_excel(out, sheet_name="异常明细")
    assert len(detail) == 0


def test_full_detail_sheet_with_status(tmp_path):
    df = pd.DataFrame({
        "订单号": ["A001", "A001", "A002"],
        "补投日期": ["2026-08-12", "2026-08-12", "2026-08-12"],
        "补料类别": ["成品", "成品", "芯料"],
        "_行号": [2, 3, 4],
    })
    anomalies = [Anomaly(rule_id="R3", rule_name="重复补投（同日同SO行）",
                         factory="珠海一厂", order_id="A001", description="x",
                         evidence={"行号": [2, 3]}, location="第[2, 3]行")]
    out = str(tmp_path / "全量.xlsx")
    write_excel_report(anomalies, [], out, df=df)
    full = pd.read_excel(out, sheet_name="全量明细")
    assert list(full["校验结果"]) == ["异常", "异常", "跳过"]
    assert "_行号" not in full.columns
