"""校验引擎：注册规则插件、执行校验、错误隔离、异常去重。"""
from .rules.base import RulePlugin
from .schema import Anomaly, StandardReport


class ValidationEngine:
    def __init__(self):
        self.rules: list = []
        self.errors: list = []  # [{"rule_id": str, "error": str}]

    def register(self, rule: RulePlugin) -> "ValidationEngine":
        self.rules.append(rule)
        return self

    def run(self, report: StandardReport) -> list[Anomaly]:
        anomalies = []
        for rule in self.rules:
            try:
                anomalies.extend(rule.validate(report))
            except Exception as e:  # 单条规则失败不影响其余规则（插件隔离性）
                self.errors.append({"rule_id": getattr(rule, "rule_id", "?"),
                                    "error": str(e)})
        return self.dedupe(anomalies)

    @staticmethod
    def dedupe(anomalies: list[Anomaly]) -> list[Anomaly]:
        seen, out = set(), []
        for a in anomalies:
            key = (a.rule_id, a.order_id, a.description)
            if key not in seen:
                seen.add(key)
                out.append(a)
        return out
