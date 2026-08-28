"""异常报告生成：Excel（异常明细+汇总统计）与Markdown摘要。"""
import json

import pandas as pd

from ..llm.attribution import Attribution
from ..schema import Anomaly

DETAIL_COLUMNS = ["序号", "工厂", "订单号", "规则编号", "规则名称", "异常描述",
                  "位置", "证据", "归因分类", "归因说明", "整改建议"]


def _attribution_map(attributions: list[Attribution]) -> dict:
    return {(a.order_id, a.rule_id): a for a in attributions}


def _build_full_detail(df, anomalies: list[Anomaly]) -> "pd.DataFrame":
    """全量明细：原始所有行 + 一列「校验结果」。成品违规=异常，非成品=跳过，正常成品=正常。"""
    flagged_rows = set()
    for an in anomalies:
        rows = an.evidence.get("行号", [])
        if isinstance(rows, (list, tuple)):
            flagged_rows.update(int(r) for r in rows)
    has_category = "补料类别" in df.columns

    def status_of(row):
        if has_category and not (pd.notna(row.get("补料类别"))
                                 and str(row["补料类别"]) == "成品"):
            return "跳过"
        return "异常" if row["_行号"] in flagged_rows else "正常"

    full = df.copy()
    full["校验结果"] = full.apply(status_of, axis=1)
    if "_行号" in full.columns:
        full = full.drop(columns=["_行号"])
    return full


def write_excel_report(anomalies: list[Anomaly], attributions: list[Attribution],
                       output_path: str, df=None) -> str:
    attr = _attribution_map(attributions)
    rows = []
    for i, an in enumerate(anomalies, 1):
        a = attr.get((an.order_id, an.rule_id))
        rows.append({
            "序号": i, "工厂": an.factory, "订单号": an.order_id,
            "规则编号": an.rule_id, "规则名称": an.rule_name,
            "异常描述": an.description, "位置": an.location,
            "证据": json.dumps(an.evidence, ensure_ascii=False, default=str),
            "归因分类": a.category if a else "—",
            "归因说明": a.explanation if a else "—",
            "整改建议": a.suggestion if a else "—",
        })
    detail_df = pd.DataFrame(rows, columns=DETAIL_COLUMNS)

    if anomalies:
        by_rule = (pd.DataFrame(
            {"规则编号": [a.rule_id for a in anomalies],
             "规则名称": [a.rule_name for a in anomalies]})
            .groupby(["规则编号", "规则名称"], as_index=False).size()
            .rename(columns={"size": "异常数"}))
        by_factory = (pd.DataFrame({"工厂": [a.factory for a in anomalies]})
                      .groupby("工厂", as_index=False).size()
                      .rename(columns={"size": "异常数"}))
    else:
        by_rule = pd.DataFrame(columns=["规则编号", "规则名称", "异常数"])
        by_factory = pd.DataFrame(columns=["工厂", "异常数"])

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        if df is not None:
            _build_full_detail(df, anomalies).to_excel(
                writer, sheet_name="全量明细", index=False)
        detail_df.to_excel(writer, sheet_name="异常明细", index=False)
        by_rule.to_excel(writer, sheet_name="汇总统计", index=False, startrow=0)
        by_factory.to_excel(writer, sheet_name="汇总统计", index=False,
                            startrow=len(by_rule) + 3)
    return output_path


def write_markdown_summary(anomalies: list[Anomaly], attributions: list[Attribution],
                           output_path: str) -> str:
    attr = _attribution_map(attributions)
    lines = ["# 校验摘要", "",
             f"- 异常总数：{len(anomalies)}", ""]
    lines.append("## 异常明细")
    if anomalies:
        for i, an in enumerate(anomalies, 1):
            a = attr.get((an.order_id, an.rule_id))
            category = a.category if a else "未归因"
            lines.append(f"{i}. 【{an.rule_id} {an.rule_name}·{category}】{an.factory} "
                         f"订单{an.order_id}：{an.description}（{an.location}）")
            if a:
                lines.append(f"   - 归因：{a.explanation}")
                lines.append(f"   - 建议：{a.suggestion}")
    else:
        lines.append("无异常。")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return output_path
