import pandas as pd

from src.agent.history_scrap import (
    HistoryBatch, HistoryRow, _parse_pct, build_history_index, calculate_scrap_rates,
    match_history_columns, read_history_row)


def test_parse_pct():
    assert abs(_parse_pct("9.55%") - 0.0955) < 1e-9
    assert _parse_pct("") is None
    assert _parse_pct(None) is None
    assert _parse_pct("abc") is None


def test_calculate_scrap_rates_area_weighted():
    data = HistoryRow()
    # 3批有效，总面积不同（10/20/30），报废率 0.1 / 0.3 / 0.5（rate 在 read_history_row 由面积算出）
    data.batches[0] = HistoryBatch(scrap_area=1, stock_in_area=9, scrap_rate=0.1)
    data.batches[1] = HistoryBatch(scrap_area=6, stock_in_area=14, scrap_rate=0.3)
    data.batches[2] = HistoryBatch(scrap_area=15, stock_in_area=15, scrap_rate=0.5)
    calculate_scrap_rates(data)
    # 面积加权 avg3 = (1+6+15)/(10+20+30) = 22/60（非算术平均 0.3）
    assert abs(data.avg3 - 22 / 60) < 1e-9
    # 剔除最高(批次3=0.5) = (1+6)/(10+20) = 7/30
    assert abs(data.avg3_exclude - 7 / 30) < 1e-9
    # 近6批平均 = 22/60（批4-6无效）
    assert abs(data.avg6 - 22 / 60) < 1e-9
    # 剔除最高2(批次3、批次2) = 1/10 = 0.1
    assert abs(data.avg6_exclude - 0.1) < 1e-9


def _make_hist_df():
    cols = [f"c{i}" for i in range(59)]
    row = [None] * 59
    row[0] = "SUNTAK_金州厂"   # 组织
    row[1] = "240103054-44"    # 本批订单号
    row[7] = 10.0              # 订单面积
    row[8] = 2.0               # 报废面积
    row[10] = 5.0              # 入库面积
    # 批次1: 11=order, 13=scrap, 14=stock
    row[11] = "240103054-43"
    row[13] = 1.0
    row[14] = 9.0
    return pd.DataFrame([row], columns=cols)


def test_read_and_build_index():
    df = _make_hist_df()
    data = read_history_row(df, 0)
    assert data.org == "SUNTAK_金州厂"
    assert data.order_no == "240103054-44"
    assert data.batches[0].scrap_area == 1.0
    assert abs(data.batches[0].scrap_rate - 0.1) < 1e-9
    index = build_history_index(df)
    assert ("金州厂", "240103054-44") in index  # 组织已去 SUNTAK_ 前缀


def test_match_history_columns():
    index = build_history_index(_make_hist_df())
    df = pd.DataFrame({"工厂": ["SUNTAK_金州厂", "SUNTAK_金州厂"],
                       "订单号": ["240103054-44.1", "999999999-1.1"]})
    result = match_history_columns(df, index)
    # 第一行匹配成功，第二行匹配失败留空
    assert result.iloc[0]["近3批平均报废率"] == 0.1
    assert pd.isna(result.iloc[1]["近3批平均报废率"])
    for c in ["近3批平均报废率", "近3批剔除最高报废率", "近6批平均报废率", "近6批剔除最高2批报废率"]:
        assert c in result.columns
