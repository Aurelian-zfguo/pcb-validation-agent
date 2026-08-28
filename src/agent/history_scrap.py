"""历史报废率计算（复刻 VBA modMain.bas 的 HistoryBatch/HistoryRow + CalculateScrapRates）。

面积加权公式：Σ报废面积 / (Σ报废面积 + Σ入库面积)，非算术平均。
剔除逻辑：3批去掉最高1批，6批去掉最高2批。
"""
from dataclasses import dataclass, field

import pandas as pd

from .data_loader import normalize_factory


# ===== 列号常量（对应 VBA HIST_*，1-based；读 iloc 时 -1）=====
HIST_ORG = 1            # A - 组织
HIST_ORDER_NO = 2       # B - 本批订单号
HIST_PRODUCT = 3        # C - 生产型号
HIST_ISSUE_DATE = 4     # D - 工单发放时间
HIST_SHIP_DATE = 5      # E - 计划发运日期
HIST_ORDER_TYPE = 6     # F - 订单类型
HIST_ORDER_AREA = 7     # G - 订单面积
HIST_SCRAP_AREA = 8     # H - 报废面积
HIST_ISSUE_AREA = 9     # I - 发放面积
HIST_STOCK_AREA = 10    # J - 入库面积
HIST_SCRAP_RATE = 11    # K - 报废率
HIST_BATCH_START = 12   # L - 历史订单号-1（每批5列，AA列为间隙）
HIST_BATCH_COUNT = 6

# 4 个输出指标列名
HIST_AVG3_COL = "近3批平均报废率"
HIST_AVG3EX_COL = "近3批剔除最高报废率"
HIST_AVG6_COL = "近6批平均报废率"
HIST_AVG6EX_COL = "近6批剔除最高2批报废率"
HIST_RESULT_COLS = [HIST_AVG3_COL, HIST_AVG3EX_COL, HIST_AVG6_COL, HIST_AVG6EX_COL]


@dataclass
class HistoryBatch:
    order_no: str = ""
    order_area: float = 0.0
    scrap_area: float = 0.0
    stock_in_area: float = 0.0
    scrap_rate: float = 0.0


@dataclass
class HistoryRow:
    org: str = ""
    order_no: str = ""
    product_model: str = ""
    issue_date: str = ""
    plan_ship_date: str = ""
    order_type: str = ""
    order_area: float = 0.0
    scrap_area: float = 0.0
    issue_area: float = 0.0
    stock_in_area: float = 0.0
    scrap_rate: float = 0.0
    batches: list = field(default_factory=lambda: [HistoryBatch() for _ in range(6)])
    avg3: float = 0.0
    avg3_exclude: float = 0.0
    avg6: float = 0.0
    avg6_exclude: float = 0.0


def _safe_str(val) -> str:
    if pd.isna(val):
        return ""
    return str(val).strip()


def _safe_cdbl(val) -> float:
    if pd.isna(val):
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _batch_base_col(b: int) -> int:
    """批次 b（1-based）的起始列（0-based）。b>=4 时跳过 AA 间隙列。"""
    base = HIST_BATCH_START + (b - 1) * 5  # 1-based：12/17/22/27/32/37
    if b >= 4:
        base += 1  # 28/33/38
    return base - 1  # 0-based


def read_history_row(hist_df, row) -> HistoryRow:
    """从历史报废率 DataFrame 读取一行（列按 VBA 59列顺序），解析6批。"""
    vals = hist_df.iloc[row].tolist()
    data = HistoryRow()
    data.org = _safe_str(vals[HIST_ORG - 1])
    data.order_no = _safe_str(vals[HIST_ORDER_NO - 1])
    data.product_model = _safe_str(vals[HIST_PRODUCT - 1])
    data.issue_date = _safe_str(vals[HIST_ISSUE_DATE - 1])
    data.plan_ship_date = _safe_str(vals[HIST_SHIP_DATE - 1])
    data.order_type = _safe_str(vals[HIST_ORDER_TYPE - 1])
    data.order_area = _safe_cdbl(vals[HIST_ORDER_AREA - 1])
    data.scrap_area = _safe_cdbl(vals[HIST_SCRAP_AREA - 1])
    data.issue_area = _safe_cdbl(vals[HIST_ISSUE_AREA - 1])
    data.stock_in_area = _safe_cdbl(vals[HIST_STOCK_AREA - 1])
    data.scrap_rate = _safe_cdbl(vals[HIST_SCRAP_RATE - 1])
    for b in range(1, HIST_BATCH_COUNT + 1):
        base = _batch_base_col(b)
        batch = data.batches[b - 1]
        batch.order_no = _safe_str(vals[base])
        batch.order_area = _safe_cdbl(vals[base + 1])
        batch.scrap_area = _safe_cdbl(vals[base + 2])
        batch.stock_in_area = _safe_cdbl(vals[base + 3])
        s, t = batch.scrap_area, batch.stock_in_area
        batch.scrap_rate = s / (s + t) if (s + t) > 0 else 0.0
    return data


def is_valid_batch(batch: HistoryBatch) -> bool:
    return batch.scrap_area > 0 or batch.stock_in_area > 0


def get_sorted_batch_indices(data: HistoryRow, batch_count: int) -> list:
    """按报废率降序返回有效批次索引（0-based）。"""
    indices = [i for i in range(batch_count) if is_valid_batch(data.batches[i])]
    indices.sort(key=lambda i: data.batches[i].scrap_rate, reverse=True)
    return indices


def calculate_scrap_rates(data: HistoryRow):
    """面积加权计算四个指标。3批剔除最高1，6批剔除最高2。"""
    count3 = sum_scrap3 = sum_total3 = 0.0
    for i in range(3):
        if is_valid_batch(data.batches[i]):
            count3 += 1
            sum_scrap3 += data.batches[i].scrap_area
            sum_total3 += data.batches[i].scrap_area + data.batches[i].stock_in_area
    count6 = sum_scrap6 = sum_total6 = 0.0
    for i in range(6):
        if is_valid_batch(data.batches[i]):
            count6 += 1
            sum_scrap6 += data.batches[i].scrap_area
            sum_total6 += data.batches[i].scrap_area + data.batches[i].stock_in_area

    data.avg3 = sum_scrap3 / sum_total3 if (count3 > 0 and sum_total3 > 0) else 0.0
    if count3 <= 1:
        data.avg3_exclude = data.avg3
    else:
        excl = get_sorted_batch_indices(data, 3)[0]
        s = t = 0.0
        for i in range(3):
            if is_valid_batch(data.batches[i]) and i != excl:
                s += data.batches[i].scrap_area
                t += data.batches[i].scrap_area + data.batches[i].stock_in_area
        data.avg3_exclude = s / t if t > 0 else 0.0

    data.avg6 = sum_scrap6 / sum_total6 if (count6 > 0 and sum_total6 > 0) else 0.0
    if count6 <= 2:
        data.avg6_exclude = data.avg6
    else:
        sorted6 = get_sorted_batch_indices(data, 6)
        e1, e2 = sorted6[0], sorted6[1]
        s = t = 0.0
        for i in range(6):
            if is_valid_batch(data.batches[i]) and i != e1 and i != e2:
                s += data.batches[i].scrap_area
                t += data.batches[i].scrap_area + data.batches[i].stock_in_area
        data.avg6_exclude = s / t if t > 0 else 0.0


def build_history_index(hist_df) -> dict:
    """构建 (组织, 本批订单号) -> HistoryRow 的索引。"""
    index = {}
    for i in range(len(hist_df)):
        data = read_history_row(hist_df, i)
        calculate_scrap_rates(data)
        org = normalize_factory(data.org)
        if data.order_no:
            index[(org, data.order_no)] = data
    return index


def match_history_columns(report_df, hist_index):
    """为补投表新增4列历史报废率指标；匹配失败留空(NaN)。返回新 DataFrame。"""
    df = report_df.copy()
    for c in HIST_RESULT_COLS:
        df[c] = None
    for idx, row in df.iterrows():
        factory = normalize_factory(row["工厂"])
        order_big = str(row["订单号"]).rsplit(".", 1)[0]
        data = hist_index.get((factory, order_big))
        if data is not None:
            df.at[idx, HIST_AVG3_COL] = data.avg3
            df.at[idx, HIST_AVG3EX_COL] = data.avg3_exclude
            df.at[idx, HIST_AVG6_COL] = data.avg6
            df.at[idx, HIST_AVG6EX_COL] = data.avg6_exclude
    return df


def _parse_pct(val):
    """'9.55%' -> 0.0955；空/非数值 -> None。"""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().rstrip("%").strip()
    if not s:
        return None
    try:
        return float(s) / 100.0
    except ValueError:
        return None


def enrich_anomalies_with_metrics(anomalies, report_df):
    """给每个 anomaly 补充历史报废率4指标 + 预大率（按订单号大行匹配，有值才补）。"""
    big_metrics = {}
    for _, row in report_df.iterrows():
        big = str(row["订单号"]).rsplit(".", 1)[0]
        if big in big_metrics:
            continue
        vals = {c: row.get(c) for c in HIST_RESULT_COLS}
        vals["预大率"] = _parse_pct(row.get("预大率"))
        if vals[HIST_AVG3_COL] is not None or vals["预大率"] is not None:
            big_metrics[big] = vals
    for an in anomalies:
        big = str(an.order_id).rsplit(".", 1)[0]
        m = big_metrics.get(big)
        if m:
            an.evidence.update(m)
    return anomalies
