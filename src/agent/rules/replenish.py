"""补投类规则：R2 违规补投（有后批订单）、R3 重复补投（同日同SO行）。"""
import pandas as pd

from ..schema import Anomaly, StandardReport
from .after_batch import after_batch_big_lines, check_has_after_batch
from .base import RulePlugin


class RuleR2AfterBatch(RulePlugin):
    rule_id = "R2"
    rule_name = "违规补投（有后批订单）"

    def __init__(self, window_days: int = 7):
        # 后批订单时间窗口从 config/rules.yaml 注入，默认 7 天保持向后兼容。
        self.window_days = window_days

    def validate(self, report: StandardReport) -> list[Anomaly]:
        df = report.df
        if not {"产品料号", "工厂", "补投日期", "订单号"}.issubset(df.columns):
            return []
        # 只对"成品"补料判后批；非成品跳过
        if "补料类别" in df.columns:
            df = df[df["补料类别"] == "成品"]
        anomalies = []
        for _, row in df.iterrows():
            order_big = str(row["订单号"]).rsplit(".", 1)[0]
            status = check_has_after_batch(
                row["产品料号"], row["工厂"], row["补投日期"], order_big,
                report.product_order_index, window_days=self.window_days)
            if status not in ("是", "上批订单预大不足"):
                continue
            big_lines = after_batch_big_lines(
                row["产品料号"], row["工厂"], row["补投日期"], order_big,
                report.product_order_index, window_days=self.window_days)
            anomalies.append(Anomaly(
                rule_id=self.rule_id, rule_name=self.rule_name,
                factory=report.factory, order_id=str(row["订单号"]),
                description=f"有后批订单（{status}）",
                evidence={
                    "后批订单大行": big_lines,
                    "后批订单数": len(big_lines),
                },
                location=f"第{row['_行号']}行"))
        return anomalies


class RuleR3DuplicateReplenish(RulePlugin):
    rule_id = "R3"
    rule_name = "重复补投（同日同SO行）"

    def validate(self, report: StandardReport) -> list[Anomaly]:
        df = report.df
        if not {"订单号", "补投日期"}.issubset(df.columns):
            return []
        # 只对"成品"类补料执行判重；非成品行跳过（不报错）
        if "补料类别" in df.columns:
            df = df[df["补料类别"] == "成品"]
        # 一行一条补投记录；销售单号即SO行，按"日期(天)"判重，忽略时分秒
        df = df.copy()
        df["_补投日"] = pd.to_datetime(df["补投日期"], errors="coerce").dt.strftime("%Y-%m-%d")
        dup_mask = df.duplicated(subset=["订单号", "_补投日"], keep=False)
        anomalies = []
        for (order_id, day), grp in df[dup_mask].groupby(["订单号", "_补投日"]):
            anomalies.append(Anomaly(
                rule_id=self.rule_id, rule_name=self.rule_name,
                factory=report.factory, order_id=str(order_id),
                description="同一SO行同一天重复补投",
                evidence={
                    "补料日期": day,
                    "同日补投记录数": int(len(grp)),
                    "行号": grp["_行号"].astype(int).tolist(),
                },
                location=f"第{grp['_行号'].astype(int).tolist()}行"))
        return anomalies
