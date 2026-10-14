"""有后批订单判断（复刻 VBA CheckOrder 两轮逻辑）。"""
import datetime

import pandas as pd

from ..parsers.report_parser import normalize_product_code_99


def _strip_suntak(name) -> str:
    s = str(name)
    return s[len("SUNTAK_"):] if s.startswith("SUNTAK_") else s


def _to_dt(v):
    """转 datetime；空/NaN 返回 None。"""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    try:
        return pd.to_datetime(v)
    except (ValueError, TypeError):
        return None


def _line_fraction(line) -> str:
    """行号小数部分，如 2.1 -> '1'、2.0 -> '0'。"""
    if line is None or pd.isna(line):
        return ""
    return str(float(line)).split(".")[-1]


def _get_orders(product_code, factory, index):
    key = (normalize_product_code_99(product_code), _strip_suntak(factory))
    return index.get(key, [])


def _match(orders, replenish_date, order_big_line, window_days=7):
    """两轮匹配，返回 (状态, [匹配订单列表])。状态：'是'/'上批订单预大不足'/'否'。"""
    rep_date = _to_dt(replenish_date)
    rep_date_7 = rep_date - datetime.timedelta(days=window_days) if rep_date is not None else None
    # 第一轮：下单时间<=补料日期 且 转工单为空 且 小数位=1 且 非赠品 且 不同大行（排除自身）
    round1 = []
    for o in orders:
        order_time = _to_dt(o.get("下单时间"))
        transfer_time = _to_dt(o.get("转工单时间"))
        if (order_time is not None and rep_date is not None
                and order_time <= rep_date
                and transfer_time is None
                and _line_fraction(o.get("行号")) == "1"
                and str(o.get("赠品备品", "")) == "N"
                and str(o.get("订单大行", "")) != str(order_big_line)):
            round1.append(o)
    if round1:
        return "是", round1
    # 第二轮：转工单时间在 [补料日期-7, 补料日期) 且 不同大行
    round2 = []
    for o in orders:
        transfer_time = _to_dt(o.get("转工单时间"))
        if (transfer_time is not None and rep_date_7 is not None
                and rep_date_7 <= transfer_time < rep_date
                and str(o.get("订单大行", "")) != str(order_big_line)):
            round2.append(o)
    if round2:
        return "上批订单预大不足", round2
    return "否", []


def check_has_after_batch(product_code, factory, replenish_date, order_big_line, index,
                          window_days=7):
    """判断当前补投行是否有后批订单。返回 '是'/'上批订单预大不足'/'否'/'无数据'。"""
    orders = _get_orders(product_code, factory, index)
    if not orders:
        return "无数据"
    status, _ = _match(orders, replenish_date, order_big_line, window_days=window_days)
    return status


def after_batch_big_lines(product_code, factory, replenish_date, order_big_line, index,
                          window_days=7):
    """返回匹配到的后批订单「订单大行」列表（供证据）。"""
    orders = _get_orders(product_code, factory, index)
    _, matched = _match(orders, replenish_date, order_big_line, window_days=window_days)
    return [str(o.get("订单大行", "")) for o in matched]
