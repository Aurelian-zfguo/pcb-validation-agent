"""标准化数据模型：所有报表解析后的统一结构，及校验异常结构。"""
from dataclasses import dataclass, field
from typing import Any

# 标准化后的报表列名（解析后的所有报表对齐到这些列，缺的列允许不存在）
STANDARD_COLUMNS = [
    "工厂", "订单号", "产品料号", "客户", "批次号",
    "需求数", "已产出数", "在线数",
    "补投数", "补投日期",
    "入库数", "入库日期",
    "报废数", "报废日期",
]

# 支持的报表类型（MVP：不含预投日报，二期补），元组，不支持修改
REPORT_TYPES = ("补投日报", "余数入库日报", "余数报废日报", "综合日报")


@dataclass
class StandardReport:
    """标准化后的报表：DataFrame + 元信息。"""
    report_type: str          # 取值见 REPORT_TYPES
    factory: str              # 如 "珠海一厂"
    source_path: str          # 原始文件路径
    df: Any = None            # pandas.DataFrame，列对齐 STANDARD_COLUMNS，另含隐藏列 "_行号"
    quality_issues: list = field(default_factory=list)  # 第0类异常（数据质量，rule_id="D0"）
    product_order_index: dict = field(default_factory=dict)  # 型号订单索引（功能二产出，供CheckOrder）


@dataclass
class Anomaly:
    """一条校验异常。"""
    rule_id: str              # R1..R4 / D0
    rule_name: str
    factory: str
    order_id: str
    description: str
    evidence: dict = field(default_factory=dict)  # 证据字段，如 {"在线数": 10, "需求数": 20}
    location: str = ""        # 定位信息，如 "第3行"
