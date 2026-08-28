"""规则插件基类：所有校验规则实现同一接口，二期可扩展为配置驱动。"""
from abc import ABC, abstractmethod

from ..schema import Anomaly, StandardReport


class RulePlugin(ABC):
    """规则插件接口。判定条件集中在本类文件中，可独立修改、独立测试。"""

    rule_id: str = ""
    rule_name: str = ""

    @abstractmethod
    def validate(self, report: StandardReport) -> list[Anomaly]:
        """对标准化报表执行判定，返回命中的异常列表。"""
