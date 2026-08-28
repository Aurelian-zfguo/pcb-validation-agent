import pandas as pd

from src.agent.rules.replenish import RuleR3DuplicateReplenish
from src.agent.schema import StandardReport


def _make_report(rows):
    df = pd.DataFrame(rows)
    for c in ["需求数", "已产出数", "在线数", "补投数"]:
        df[c] = pd.to_numeric(df.get(c, pd.Series([None] * len(df))), errors="coerce")
    df["_行号"] = range(2, 2 + len(df))
    return StandardReport(report_type="综合日报", factory="珠海一厂",
                          source_path="x.csv", df=df)


def test_r3_hit_same_order_same_date_twice():
    report = _make_report([
        {"订单号": "A003", "批次号": "B1", "补投数": 4, "补投日期": "2026-08-12"},
        {"订单号": "A003", "批次号": "B2", "补投数": 2, "补投日期": "2026-08-12"},
    ])
    anomalies = RuleR3DuplicateReplenish().validate(report)
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.rule_id == "R3" and a.order_id == "A003"
    assert a.evidence["同日补投记录数"] == 2


def test_r3_pass_different_dates():
    report = _make_report([
        {"订单号": "A003", "批次号": "B1", "补投数": 4, "补投日期": "2026-08-12"},
        {"订单号": "A003", "批次号": "B2", "补投数": 2, "补投日期": "2026-08-13"},
    ])
    assert RuleR3DuplicateReplenish().validate(report) == []


def test_r3_pass_single_replenish():
    report = _make_report([
        {"订单号": "A003", "批次号": "B1", "补投数": 4, "补投日期": "2026-08-12"},
    ])
    assert RuleR3DuplicateReplenish().validate(report) == []


def test_r3_skip_when_column_missing():
    report = _make_report([{"订单号": "A003"}])
    assert RuleR3DuplicateReplenish().validate(report) == []


def test_r3_only_checks_finished_category():
    report = _make_report([
        {"订单号": "A003", "批次号": "B1", "补投数": 4, "补投日期": "2026-08-12", "补料类别": "成品"},
        {"订单号": "A003", "批次号": "B2", "补投数": 2, "补投日期": "2026-08-12", "补料类别": "成品"},
        {"订单号": "A004", "批次号": "B1", "补投数": 3, "补投日期": "2026-08-12", "补料类别": "芯料"},
        {"订单号": "A004", "批次号": "B2", "补投数": 1, "补投日期": "2026-08-12", "补料类别": "芯料"},
    ])
    anomalies = RuleR3DuplicateReplenish().validate(report)
    # 只命中A003（成品重复补投）；A004（非成品）跳过
    assert len(anomalies) == 1
    assert anomalies[0].order_id == "A003"


def test_r3_same_day_different_time_is_duplicate():
    report = _make_report([
        {"订单号": "A005", "批次号": "B1", "补投日期": "2026-08-12 09:25:18", "补料类别": "成品"},
        {"订单号": "A005", "批次号": "B2", "补投日期": "2026-08-12 14:30:00", "补料类别": "成品"},
    ])
    anomalies = RuleR3DuplicateReplenish().validate(report)
    # 同一天不同时刻，仍按"天"判为重复
    assert len(anomalies) == 1
    assert anomalies[0].evidence["补料日期"] == "2026-08-12"
