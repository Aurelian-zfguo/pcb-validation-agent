"""报表解析与清洗：字段别名映射、类型转换、数据质检（第0类异常）。"""
from pathlib import Path

import pandas as pd

from ..schema import STANDARD_COLUMNS, Anomaly, StandardReport


class ReportParseError(Exception):
    """报表无法解析时抛出，消息需明确列出问题字段，不静默跳过。"""


# 需要转为数值的标准列
NUMERIC_COLUMNS = ["需求数", "已产出数", "在线数", "补投数", "入库数", "报废数"]


def _read_file(path: str, sheet: str | None = None) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise ReportParseError(f"文件不存在: {path}")
    suffix = p.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        if sheet:
            return pd.read_excel(path, sheet_name=sheet)
        return pd.read_excel(path)  # 未指定Sheet时读第一个
    if suffix == ".csv":
        # utf-8-sig 兼容Excel导出的BOM
        return pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    raise ReportParseError(f"不支持的文件类型: {p.suffix}（支持 .xlsx/.xls/.csv）")


def _map_columns(df: pd.DataFrame, aliases: dict) -> pd.DataFrame:
    """把实际列名按别名映射为标准列名；标准列已存在则不覆盖。"""
    rename = {}
    for std, alias_list in aliases.items():
        if std in df.columns:
            continue
        for alias in alias_list:
            if alias in df.columns:
                rename[alias] = std
                break
    return df.rename(columns=rename)


def normalize_product_code_99(code) -> str:
    """产品编号标准化：去空格、转大写，末尾 '00'/'99' 统一为 '99'。

    例：'100497915C1000A' -> '100497915C1099A'（倒数第2-3位 '00'/'99' 归一为 '99'，末位面次字母保留）。
    """
    if pd.isna(code):
        return ""
    s = str(code).replace(" ", "").upper()
    if len(s) >= 3 and s[-3:-1] in ("00", "99"):
        s = s[:-3] + "99" + s[-1]
    return s


def filter_order_by_products(df_order, df_main):
    """功能一：订单数据过滤。只保留产品编号（E列）在补投表G列（产品编号）中的订单行。

    df_order：订单完成情况全量 DataFrame（含 产品编号/SO号/行 等原始列）
    df_main：补投明细表（工厂+成品筛选后），含「产品编号」列
    返回：过滤后的订单 DataFrame，新增「SO号-行」列；空输入/无匹配返回空 DataFrame。
    """
    if df_order is None or df_order.empty or df_main is None or df_main.empty:
        return pd.DataFrame()
    if "产品编号" not in df_main.columns or "产品编号" not in df_order.columns:
        return pd.DataFrame()
    keys = set(df_main["产品编号"].dropna().map(normalize_product_code_99))
    norm = df_order["产品编号"].map(normalize_product_code_99)
    filtered = df_order[norm.isin(keys)].copy()
    if not filtered.empty:
        filtered["SO号-行"] = filtered["SO号"].astype(str) + "-" + filtered["行"].astype(str)
    return filtered


def build_product_order_index(df_filtered):
    """功能二：构建型号订单索引。key=(标准化产品编号, 生产工厂)，value=订单信息字典列表。

    供后续 CheckOrder 判断是否有后批订单。
    """
    index = {}
    if df_filtered is None or df_filtered.empty:
        return index
    for _, row in df_filtered.iterrows():
        product = normalize_product_code_99(row["产品编号"])
        line = row.get("行")
        big = int(line) if pd.notna(line) else ""
        order_big = f"{row['SO号']}-{big}"
        factory = str(row.get("生产工厂", ""))
        if factory.startswith("SUNTAK_"):
            factory = factory[len("SUNTAK_"):]
        key = (product, factory)
        item = {
            "下单时间": row.get("下单时间", ""),
            "转工单时间": row.get("转工单时间", ""),
            "行号": line,
            "赠品备品": row.get("赠品备品", ""),
            "订单大行": order_big,
            "行状态": row.get("行状态", ""),
            "订单审核状态": row.get("订单审核状态", ""),
        }
        index.setdefault(key, []).append(item)
    return index


class ReportParser:
    def __init__(self, field_mapping: dict):
        self.field_mapping = field_mapping

    def parse(self, path: str, factory: str, report_type: str,
              sheet: str | None = None) -> StandardReport:
        report_types = self.field_mapping.get("report_types", {})
        if report_type not in report_types:
            raise ReportParseError(
                f"未知报表类型「{report_type}」，已支持: {list(report_types)}")
        df = _read_file(path, sheet)
        return self.parse_df(df, factory, report_type, source_path=str(path))

    def parse_df(self, df: pd.DataFrame, factory: str, report_type: str,
                 source_path: str = "") -> StandardReport:
        """对已读入的DataFrame做列映射+质检（供工厂模式先过滤再解析）。"""
        report_types = self.field_mapping.get("report_types", {})
        if report_type not in report_types:
            raise ReportParseError(
                f"未知报表类型「{report_type}」，已支持: {list(report_types)}")
        df = _map_columns(df, report_types[report_type])
        if "订单号" not in df.columns:
            raise ReportParseError(
                f"无法识别订单号字段，报表现有列: {list(df.columns)}，"
                f"已支持别名见 config/field_mapping.yaml")
        df = df.reset_index(drop=True)  # 过滤后索引可能不连续，重置保证_行号对齐
        # 隐藏行号列：Excel第1行是表头，数据行从第2行起
        df["_行号"] = range(2, len(df) + 2)
        issues = self._quality_check(df, factory)
        for col in NUMERIC_COLUMNS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return StandardReport(report_type=report_type, factory=factory,
                              source_path=source_path, df=df, quality_issues=issues)

    def _quality_check(self, df: pd.DataFrame, factory: str) -> list:
        issues = []
        # 1) 订单号为空
        empty_order = df["订单号"].isna() | (df["订单号"].astype(str).str.strip() == "")
        for _, row in df[empty_order].iterrows():
            issues.append(Anomaly(
                rule_id="D0", rule_name="数据质量", factory=factory, order_id="(空)",
                description="订单号为空，无法参与校验",
                location=f"第{row['_行号']}行"))
        # 2) 完全重复的行（排除隐藏行号列）
        dup_mask = df.drop(columns=["_行号"]).duplicated(keep=False)
        for _, row in df[dup_mask].iterrows():
            issues.append(Anomaly(
                rule_id="D0", rule_name="数据质量", factory=factory,
                order_id=str(row["订单号"]),
                description="存在完全重复的行",
                location=f"第{row['_行号']}行"))
        # 3) 数值列存在非数字值
        for col in NUMERIC_COLUMNS:
            if col not in df.columns:
                continue
            coerced = pd.to_numeric(df[col], errors="coerce")
            bad = df[coerced.isna() & df[col].notna()]
            for _, row in bad.iterrows():
                issues.append(Anomaly(
                    rule_id="D0", rule_name="数据质量", factory=factory,
                    order_id=str(row["订单号"]),
                    description=f"「{col}」不是有效数字: {row[col]}",
                    evidence={col: str(row[col])},
                    location=f"第{row['_行号']}行"))
        return issues
