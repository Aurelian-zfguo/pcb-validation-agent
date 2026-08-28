import pandas as pd

from src.agent.rules.scrap import RuleR4ScrapWithOnlineBoards
from src.agent.schema import StandardReport


def _make_report(rows):
    df = pd.DataFrame(rows)
    for c in ["需求数", "已产出数", "在线数", "报废数"]:
        df[c] = pd.to_numeric(df.get(c, pd.Series([None] * len(df))), errors="coerce")
    df["_行号"] = range(2, 2 + len(df))
    return StandardReport(report_type="综合日报", factory="珠海一厂",
                          source_path="x.csv", df=df)


def test_r4_hit_scrap_while_online_boards_exist():
    report = _make_report([
        {"订单号": "A004", "批次号": "B1", "需求数": 10, "已产出数": 5,
         "在线数": 4, "报废数": 3, "报废日期": "2026-08-13"},
    ])
    anomalies = RuleR4ScrapWithOnlineBoards().validate(report)
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.rule_id == "R4" and a.order_id == "A004"
    assert a.evidence["在线数"] == 4 and a.evidence["报废数"] == 3


def test_r4_pass_no_scrap():
    report = _make_report([
        {"订单号": "A004", "在线数": 4, "报废数": None},
    ])
    assert RuleR4ScrapWithOnlineBoards().validate(report) == []


def test_r4_pass_no_online_boards():
    report = _make_report([
        {"订单号": "A004", "在线数": 0, "报废数": 3},
    ])
    assert RuleR4ScrapWithOnlineBoards().validate(report) == []


def test_r4_skip_when_column_missing():
    report = _make_report([{"订单号": "A004", "在线数": 4}])
    assert RuleR4ScrapWithOnlineBoards().validate(report) == []
