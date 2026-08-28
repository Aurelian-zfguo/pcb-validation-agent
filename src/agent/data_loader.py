"""真实数据源：按工厂匹配文件 + 补投明细与订单完成情况的多表关联。"""
from pathlib import Path

import pandas as pd


def normalize_factory(name) -> str:
    """去掉 'SUNTAK_' 前缀，让 '珠海一厂' 和 'SUNTAK_珠海一厂' 归一化一致。"""
    s = str(name).strip()
    if s.startswith("SUNTAK_"):
        s = s[len("SUNTAK_"):]
    return s


def _file_belongs_to_factory(path, factory, column="生产工厂") -> bool:
    """读文件第一行数据的 column 列，判断是否属于目标工厂（无该列则默认采用）。"""
    try:
        df = pd.read_excel(path, nrows=1)
        if column not in df.columns:
            return True
        return normalize_factory(df[column].iloc[0]) == normalize_factory(factory)
    except Exception:
        return True


def _match_file(files, factory, column):
    """从文件路径列表中找到 column 列匹配 factory 的文件，无则 None。"""
    for f in files:
        if _file_belongs_to_factory(f, factory, column):
            return str(f)
    return None


def discover_files(factory, data_dir, bt_files=None, order_files=None, hist_files=None) -> dict:
    """匹配补投明细表/订单完成情况/历史报废率文件。显式列表优先，否则 glob；缺失返回 None。"""
    data_dir = Path(data_dir)
    result = {"补投": None, "订单": None, "报废": None}
    # 补投：1个文件（含所有厂），取第一个
    bt = [str(f) for f in bt_files] if bt_files else [str(f) for f in sorted(data_dir.glob("*补投明细表*.xlsx"))]
    if bt:
        result["补投"] = bt[0]
    # 订单：按 生产工厂(AB列) 匹配
    order = [str(f) for f in order_files] if order_files else [str(f) for f in sorted(data_dir.glob("*订单完成情况*.xlsx"))]
    result["订单"] = _match_file(order, factory, "生产工厂")
    # 报废：按 组织(A列) 匹配
    hist = [str(f) for f in hist_files] if hist_files else [str(f) for f in sorted(data_dir.glob("*历史报废率*.xlsx"))]
    result["报废"] = _match_file(hist, factory, "组织")
    return result


def join_order_info(main_df, order_df):
    """左连接：主表补投明细 + 关联表订单完成情况。

    带回 订单欠数/是否够订单/销售员，新增「匹配方式」列。
    匹配优先级：精确(销售单号 == SO号-行) -> 大行(销售单号去小数 == SO号-大行) -> 未匹配。
    左连接，主表行数不减少。
    """
    main = main_df.copy()
    order = order_df.copy()
    order["_exact"] = order["SO号"].astype(str) + "-" + order["行"].astype(str)
    order["_big"] = order["SO号"].astype(str) + "-" + order["行"].fillna(0).astype(int).astype(str)
    cols = ["订单欠数", "是否够订单", "销售员"]
    exact_map = order.drop_duplicates("_exact").set_index("_exact")[cols]
    big_map = order.drop_duplicates("_big").set_index("_big")[cols]

    main["_exact"] = main["订单号"].astype(str)
    main["_big"] = main["订单号"].astype(str).str.rsplit(".", n=1).str[0]

    # 第一轮：精确匹配
    main = main.join(exact_map, on="_exact", how="left")
    main["匹配方式"] = "未匹配"
    main.loc[main["订单欠数"].notna(), "匹配方式"] = "精确匹配"

    # 第二轮：大行匹配（仅对未精确命中的行）
    fill = main["订单欠数"].isna()
    if fill.any():
        sub = main.loc[fill, ["_big"]].join(big_map, on="_big", how="left")
        for c in cols:
            main.loc[fill, c] = sub[c].values
        main.loc[fill & main["订单欠数"].notna(), "匹配方式"] = "大行匹配"

    return main.drop(columns=["_exact", "_big"])
