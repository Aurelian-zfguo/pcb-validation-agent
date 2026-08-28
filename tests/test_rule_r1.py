import pandas as pd

from src.agent.rules.warehouse_in import RuleR1WarehouseIn
from src.agent.schema import StandardReport


def _make_report(rows):
    df = pd.DataFrame(rows)
    for c in ["需求数", "已产出数", "在线数", "入库数"]:
        df[c] = pd.to_numeric(df.get(c, pd.Series([None] * len(df))), errors="coerce")
    df["_行号"] = range(2, 2 + len(df))
    return StandardReport(report_type="综合日报", factory="珠海一厂",
                          source_path="x.csv", df=df)


def test_r1_hit_online_and_not_enough():
    report = _make_report([
        {"订单号": "A001", "批次号": "B1", "需求数": 20, "已产出数": 8,
         "在线数": 10, "入库数": 2, "入库日期": "2026-08-10"},
    ])
    anomalies = RuleR1WarehouseIn().validate(report)
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.rule_id == "R1" and a.order_id == "A001"
    assert a.evidence["在线数"] == 10 and a.evidence["需求数"] == 20
    assert a.location == "第2行"


def test_r1_pass_when_online_zero():
    report = _make_report([
        {"订单号": "A001", "需求数": 20, "已产出数": 8, "在线数": 0, "入库数": 2},
    ])
    assert RuleR1WarehouseIn().validate(report) == []


def test_r1_pass_when_produced_ge_demand():
    report = _make_report([
        {"订单号": "A001", "需求数": 20, "已产出数": 20, "在线数": 10, "入库数": 2},
    ])
    assert RuleR1WarehouseIn().validate(report) == []


def test_r1_pass_when_no_warehouse_in():
    report = _make_report([
        {"订单号": "A001", "需求数": 20, "已产出数": 8, "在线数": 10, "入库数": None},
    ])
    assert RuleR1WarehouseIn().validate(report) == []


def test_r1_skip_when_column_missing():
    report = _make_report([
        {"订单号": "A001", "需求数": 20, "已产出数": 8, "在线数": 10},
    ])
    assert RuleR1WarehouseIn().validate(report) == []
