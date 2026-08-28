import pandas as pd

from src.agent.parsers.report_parser import (
    build_product_order_index, filter_order_by_products, normalize_product_code_99)


def test_normalize_product_code_99():
    assert normalize_product_code_99("100497915C1000A") == "100497915C1099A"
    assert normalize_product_code_99("100497915C1099A") == "100497915C1099A"  # 已是99，不变
    assert normalize_product_code_99(" abc1000a ") == "ABC1099A"  # 去空格转大写
    assert normalize_product_code_99(None) == ""
    assert normalize_product_code_99(float("nan")) == ""


def test_filter_order_by_products():
    main = pd.DataFrame({"产品编号": ["100497915C1000A"]})
    order = pd.DataFrame({
        "产品编号": ["100497915C1000A", "999999999C1000A"],
        "SO号": [260403302, 260403303],
        "行": [2.1, 1.1],
    })
    filtered = filter_order_by_products(order, main)
    assert len(filtered) == 1
    assert filtered.iloc[0]["SO号"] == 260403302
    assert "SO号-行" in filtered.columns
    assert filtered.iloc[0]["SO号-行"] == "260403302-2.1"


def test_filter_order_by_products_empty():
    assert filter_order_by_products(None, pd.DataFrame({"产品编号": ["x"]})).empty
    assert filter_order_by_products(pd.DataFrame(), pd.DataFrame({"产品编号": ["x"]})).empty


def test_build_product_order_index():
    filtered = pd.DataFrame({
        "产品编号": ["100497915C1000A"],
        "生产工厂": ["SUNTAK_金州厂"],
        "SO号": [260403302],
        "行": [47.3],
        "下单时间": ["2026-08-10"],
        "转工单时间": ["2026-08-11"],
        "赠品备品": ["否"],
        "行状态": ["OPEN"],
        "订单审核状态": ["Y"],
    })
    index = build_product_order_index(filtered)
    key = ("100497915C1099A", "金州厂")  # 生产工厂已去 SUNTAK_ 前缀
    assert key in index
    assert len(index[key]) == 1
    item = index[key][0]
    assert item["订单大行"] == "260403302-47"
    assert item["行号"] == 47.3
    assert item["下单时间"] == "2026-08-10"
    assert item["订单审核状态"] == "Y"


def test_build_product_order_index_empty():
    assert build_product_order_index(pd.DataFrame()) == {}
