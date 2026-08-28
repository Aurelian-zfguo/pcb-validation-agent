import pandas as pd

from src.agent.data_loader import join_order_info, normalize_factory


def test_normalize_factory_strips_prefix():
    assert normalize_factory("SUNTAK_珠海一厂") == "珠海一厂"
    assert normalize_factory("珠海一厂") == "珠海一厂"


def test_join_order_info_exact_match():
    main = pd.DataFrame({"订单号": ["260716743-3.1", "260716743-3.2"]})
    order = pd.DataFrame({
        "SO号": [260716743, 260716743],
        "行": [3.1, 3.2],
        "订单欠数": [10, 20],
        "是否够订单": ["是", "否"],
        "销售员": ["张三", "李四"],
    })
    joined = join_order_info(main, order)
    assert joined["匹配方式"].tolist() == ["精确匹配", "精确匹配"]
    assert joined["订单欠数"].tolist() == [10, 20]
    assert joined["销售员"].tolist() == ["张三", "李四"]


def test_join_order_info_big_line_match():
    main = pd.DataFrame({"订单号": ["260716743-3.1", "260716743-3.2"]})
    order = pd.DataFrame({
        "SO号": [260716743],
        "行": [3.0],  # 只有大行，无小行
        "订单欠数": [99],
        "是否够订单": ["是"],
        "销售员": ["王五"],
    })
    joined = join_order_info(main, order)
    assert joined["匹配方式"].tolist() == ["大行匹配", "大行匹配"]
    assert joined["订单欠数"].tolist() == [99, 99]


def test_join_order_info_unmatched():
    main = pd.DataFrame({"订单号": ["999999999-1.1"]})
    order = pd.DataFrame({
        "SO号": [260716743], "行": [3.1],
        "订单欠数": [10], "是否够订单": ["是"], "销售员": ["张三"],
    })
    joined = join_order_info(main, order)
    assert joined["匹配方式"].tolist() == ["未匹配"]
    assert pd.isna(joined["订单欠数"].iloc[0])


def test_join_preserves_main_rows():
    main = pd.DataFrame({"订单号": ["a-1.1", "b-1.1", "c-1.1"]})
    order = pd.DataFrame({"SO号": [1], "行": [1.1], "订单欠数": [5],
                          "是否够订单": ["是"], "销售员": ["赵六"]})
    joined = join_order_info(main, order)
    assert len(joined) == 3  # 左连接不减少主表行
