import pandas as pd
from src.agent.schema import STANDARD_COLUMNS, REPORT_TYPES, StandardReport, Anomaly


def test_standard_columns_contains_core_fields():
    for col in ["工厂", "订单号", "产品料号", "客户", "批次号",
                "需求数", "已产出数", "在线数",
                "补投数", "补投日期", "入库数", "入库日期", "报废数", "报废日期"]:
        assert col in STANDARD_COLUMNS


def test_report_types():
    assert REPORT_TYPES == ("补投日报", "余数入库日报", "余数报废日报", "综合日报")


def test_anomaly_defaults():
    a = Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="珠海一厂",
                order_id="A001", description="x", location="第3行")
    assert a.evidence == {}
    assert a.rule_id == "R1"


def test_standard_report_default_quality_issues():
    r = StandardReport(report_type="综合日报", factory="珠海一厂", source_path="a.csv", df=pd.DataFrame())
    assert r.quality_issues == []
