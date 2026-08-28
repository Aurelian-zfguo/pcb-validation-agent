import pandas as pd

from src.agent.engine import ValidationEngine
from src.agent.rules.base import RulePlugin
from src.agent.rules.warehouse_in import RuleR1WarehouseIn
from src.agent.schema import Anomaly, StandardReport


class AlwaysHitRule(RulePlugin):
    rule_id = "T1"
    rule_name = "测试规则"

    def validate(self, report):
        return [Anomaly(rule_id=self.rule_id, rule_name=self.rule_name,
                        factory=report.factory, order_id="A001",
                        description="命中")]


class BadRule(RulePlugin):
    rule_id = "BAD"
    rule_name = "会报错的规则"

    def validate(self, report):
        raise RuntimeError("boom")


def _make_report():
    df = pd.DataFrame([
        {"订单号": "A001", "需求数": 20, "已产出数": 8, "在线数": 10,
         "入库数": 2, "入库日期": "2026-08-10"},
    ])
    df["需求数"] = pd.to_numeric(df["需求数"]); df["已产出数"] = pd.to_numeric(df["已产出数"])
    df["在线数"] = pd.to_numeric(df["在线数"]); df["入库数"] = pd.to_numeric(df["入库数"])
    df["_行号"] = [2]
    return StandardReport(report_type="综合日报", factory="珠海一厂",
                          source_path="x.csv", df=df)


def test_engine_runs_registered_rules():
    engine = ValidationEngine().register(RuleR1WarehouseIn()).register(AlwaysHitRule())
    anomalies = engine.run(_make_report())
    assert len(anomalies) == 2
    assert {a.rule_id for a in anomalies} == {"R1", "T1"}
    assert engine.errors == []


def test_engine_isolates_rule_failure():
    engine = ValidationEngine().register(BadRule()).register(AlwaysHitRule())
    anomalies = engine.run(_make_report())
    assert len(anomalies) == 1 and anomalies[0].rule_id == "T1"
    assert len(engine.errors) == 1
    assert engine.errors[0]["rule_id"] == "BAD"


def test_dedupe_identical_anomalies():
    a1 = Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="珠海一厂",
                 order_id="A001", description="x")
    a2 = Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="珠海一厂",
                 order_id="A001", description="x")
    a3 = Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="珠海一厂",
                 order_id="A002", description="x")
    result = ValidationEngine.dedupe([a1, a2, a3])
    assert len(result) == 2
