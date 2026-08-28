"""R1 违规入余数仓：在线有板且订单不够数时，余数不应入库。"""
from ..schema import Anomaly, StandardReport
from .base import RulePlugin


class RuleR1WarehouseIn(RulePlugin):
    rule_id = "R1"
    rule_name = "违规入余数仓"

    def validate(self, report: StandardReport) -> list[Anomaly]:
        df = report.df
        if not {"入库数", "在线数", "已产出数", "需求数"}.issubset(df.columns):
            return []  # 该报表缺少本规则所需列，规则不适用
        mask = (
            (df["入库数"].fillna(0) > 0)
            & (df["在线数"].fillna(0) > 0)
            & (df["已产出数"].fillna(0) < df["需求数"].fillna(0))
        )
        anomalies = []
        for _, row in df[mask].iterrows():
            anomalies.append(Anomaly(
                rule_id=self.rule_id, rule_name=self.rule_name,
                factory=report.factory, order_id=str(row["订单号"]),
                description="在线有板且订单不够数时余数入库",
                evidence={
                    "在线数": row["在线数"], "已产出数": row["已产出数"],
                    "需求数": row["需求数"], "入库数": row["入库数"],
                    "入库日期": row.get("入库日期", ""),
                },
                location=f"第{row['_行号']}行"))
        return anomalies
