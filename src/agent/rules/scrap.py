"""R4 违规报废：在线仍有可用板时提前报废。"""
from ..schema import Anomaly, StandardReport
from .base import RulePlugin


class RuleR4ScrapWithOnlineBoards(RulePlugin):
    rule_id = "R4"
    rule_name = "违规报废（在线仍有可用板）"

    def validate(self, report: StandardReport) -> list[Anomaly]:
        df = report.df
        if not {"报废数", "在线数"}.issubset(df.columns):
            return []
        mask = (df["报废数"].fillna(0) > 0) & (df["在线数"].fillna(0) > 0)
        anomalies = []
        for _, row in df[mask].iterrows():
            anomalies.append(Anomaly(
                rule_id=self.rule_id, rule_name=self.rule_name,
                factory=report.factory, order_id=str(row["订单号"]),
                description="在线仍有可用板时提前报废（本可继续使用的余数被报废）",
                evidence={
                    "在线数": row["在线数"], "报废数": row["报废数"],
                    "报废日期": row.get("报废日期", ""),
                },
                location=f"第{row['_行号']}行"))
        return anomalies
