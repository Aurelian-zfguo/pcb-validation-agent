import pandas as pd

from src.agent.parsers.report_parser import build_product_order_index
from src.agent.rules.after_batch import after_batch_big_lines, check_has_after_batch


def _index(rows):
    return build_product_order_index(pd.DataFrame(rows))


def test_no_data():
    index = _index([{"产品编号": "100497915C1000A", "生产工厂": "SUNTAK_金州厂",
                     "SO号": 260403302, "行": 2.1, "下单时间": "2026-08-01",
                     "转工单时间": None, "赠品备品": "N"}])
    assert check_has_after_batch("999999999C1000A", "金州厂", "2026-08-10", "x-1", index) == "无数据"


def test_round1_yes():
    index = _index([
        {"产品编号": "100497915C1000A", "生产工厂": "SUNTAK_金州厂", "SO号": 260403302,
         "行": 2.1, "下单时间": "2026-08-01", "转工单时间": None, "赠品备品": "N"},
        {"产品编号": "100497915C1000A", "生产工厂": "SUNTAK_金州厂", "SO号": 260403303,
         "行": 3.1, "下单时间": "2026-08-15", "转工单时间": "2026-08-05", "赠品备品": "N"},
    ])
    # 第一单：下单时间<=补料日期、转工单空、小数位1(2.1)、非赠品(N) -> 是
    assert check_has_after_batch("100497915C1000A", "金州厂", "2026-08-10", "x-1", index) == "是"
    assert "260403302-2" in after_batch_big_lines("100497915C1000A", "金州厂", "2026-08-10", "x-1", index)


def test_round2_insufficient():
    index = _index([
        {"产品编号": "100497915C1000A", "生产工厂": "SUNTAK_金州厂", "SO号": 260403303,
         "行": 3.1, "下单时间": "2026-08-15", "转工单时间": "2026-08-08", "赠品备品": "N"},
    ])
    # 下单时间>补料日期(第一轮不中)；转工单在[补料日期-7,补料日期)且大行不同 -> 上批订单预大不足
    assert check_has_after_batch("100497915C1000A", "金州厂", "2026-08-10", "260403303-4", index) == "上批订单预大不足"


def test_round1_excludes_own_big_line():
    # 后批订单大行 == 当前补投大行 -> 自己不算自己，返回'否'
    index = _index([
        {"产品编号": "100497915C1000A", "生产工厂": "SUNTAK_金州厂", "SO号": 260403302,
         "行": 2.1, "下单时间": "2026-08-01", "转工单时间": None, "赠品备品": "N"},
    ])
    assert check_has_after_batch("100497915C1000A", "金州厂", "2026-08-10", "260403302-2", index) == "否"


def test_no_match():
    index = _index([
        {"产品编号": "100497915C1000A", "生产工厂": "SUNTAK_金州厂", "SO号": 260403303,
         "行": 3.1, "下单时间": "2026-08-15", "转工单时间": "2026-05-05", "赠品备品": "N"},
    ])
    assert check_has_after_batch("100497915C1000A", "金州厂", "2026-08-10", "260403303-4", index) == "否"


def test_window_days_from_config():
    # 同一份数据：转工单 08-08 落在补料日期 08-10 的 7 天窗口内 → 命中第二轮；
    # 窗口收窄为 0 天时，08-08 不在 [08-10, 08-10) 内 → 不命中。两者结果应不同。
    index = _index([
        {"产品编号": "100497915C1000A", "生产工厂": "SUNTAK_金州厂", "SO号": 260403303,
         "行": 3.1, "下单时间": "2026-08-15", "转工单时间": "2026-08-08", "赠品备品": "N"},
    ])
    with7 = check_has_after_batch(
        "100497915C1000A", "金州厂", "2026-08-10", "260403303-4", index, window_days=7)
    with0 = check_has_after_batch(
        "100497915C1000A", "金州厂", "2026-08-10", "260403303-4", index, window_days=0)
    assert with7 == "上批订单预大不足"
    assert with0 == "否"
    assert with7 != with0
