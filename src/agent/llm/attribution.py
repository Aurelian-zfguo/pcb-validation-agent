"""LLM归因：对规则命中的异常生成归因分类、归因说明、整改建议。"""
import json
import re
from dataclasses import dataclass
from typing import Callable

from ..schema import Anomaly
from .client import LLMClient
from .rag_monitor import monitor

# 类型别名：归因模块通过该可调用对象获取知识片段（Top-1 内容），
# 由 B 项目检索服务提供；不可用或返回 None 时降级为纯硬编码 Prompt。
# 仅在调用方显式传入时才启用，避免归因模块对 B 服务产生硬依赖。
Retriever = Callable[[Anomaly], str | None]

ATTRIBUTION_CATEGORIES = ["违规行为", "流程不清", "人员偏差", "系统漏洞", "数据错误"]

SYSTEM_PROMPT = (
    "你是PCB工厂投料管理稽查助手，只负责对给定的异常项做归因。"
    "必须严格只输出一个JSON对象，不要输出任何解释、markdown代码块围栏或额外文字。"
    "输出格式固定为：{\"results\": [{\"order_id\": \"...\", \"rule_id\": \"...\", "
    "\"category\": \"违规行为|流程不清|人员偏差|系统漏洞|数据错误\", "
    "\"explanation\": \"结合投料-在线-入库-报废链路解读，并给出预大率对比历史报废率的根因结论（投料预大不足/工序异常超标）\", "
    "\"suggestion\": \"针对性整改建议\"}]}，"
    "results 数组长度必须与输入异常项数量一致。"
)


@dataclass
class Attribution:
    order_id: str
    rule_id: str
    category: str
    explanation: str
    suggestion: str


HIST_METRIC_NAMES = ["近3批平均报废率", "近3批剔除最高报废率", "近6批平均报废率", "近6批剔除最高2批报废率"]

COMPARISON_RULES = (
    "对比分析规则（判断补投根因）："
    "① 预大率 > 100%：数据错误（category 填「数据错误」）。"
    "② 否则，以「近3批剔除最高报废率」为主判断基准、「近6批剔除最高报废率」为辅助验证："
    "预大率 < 近3批剔除最高报废率（或近6批剔除最高报废率）→ 根因「投料预大不足」（计划层面，投料低估报废风险）；"
    "预大率 ≥ 近3批剔除最高报废率（或近6批剔除最高报废率）→ 根因「工序异常超标」（执行层面，投料已留够正常报废余量但实际仍超标）。"
    "③ 波动判断（两层）：阈值1「波动大」= 近3批平均 > 近3批剔除最高 × 1.5，或近6批平均 > 近6批剔除最高 × 1.5，"
    "说明该型号报废率不稳定、高高低低起伏大；阈值2「超级异常批次」= 近3批平均 - 近3批剔除最高 > 0.10，"
    "或近6批平均 - 近6批剔除最高 > 0.10，说明存在单批次超级异常报废（如整批报废）拉高平均。"
    "若两种同时满足，则归因说明中合并提示「报废率波动大」和「存在超级异常批次」。"
)


def _pct_str(v) -> str:
    return f"{v:.2%}" if v is not None else "无"


def _volatility_flags(evidence: dict) -> str:
    """确定性计算波动两层判断，返回提示文本（无则空串）。"""
    avg3 = evidence.get("近3批平均报废率")
    ex3 = evidence.get("近3批剔除最高报废率")
    avg6 = evidence.get("近6批平均报废率")
    ex6 = evidence.get("近6批剔除最高2批报废率")
    flag_volatile = flag_extreme = False
    for avg, ex in ((avg3, ex3), (avg6, ex6)):
        if avg is None or ex is None:
            continue
        if ex > 0 and avg > ex * 1.5:   # 阈值1：波动大
            flag_volatile = True
        if avg - ex > 0.10:             # 阈值2：超级异常批次
            flag_extreme = True
    if flag_volatile and flag_extreme:
        return "波动判断：报废率波动大（高高低低起伏大）＋ 存在超级异常批次（单批次整批报废拉高平均）。"
    if flag_volatile:
        return "波动判断：该型号历史报废率波动大（高高低低起伏大）。"
    if flag_extreme:
        return "波动判断：存在单批次超级异常报废（整批报废拉高平均）。"
    return ""


def _history_analysis_block(evidence: dict) -> str:
    """拼预大率 vs 历史报废率对比数据块；预大率为空则跳过对比。"""
    pre = evidence.get("预大率")
    if pre is None:
        return "历史报废率：无预大率数据，无法判断根因。"
    lines = ["历史报废率数据：",
             f"- 预大率（该订单）：{pre:.2%}"]
    for n in HIST_METRIC_NAMES:
        lines.append(f"- {n}：{_pct_str(evidence.get(n))}")
    vol = _volatility_flags(evidence)
    if vol:
        lines.append(vol)
    lines.append(COMPARISON_RULES)
    return "\n".join(lines)


def build_prompt(anomalies: list[Anomaly], retriever: Retriever | None = None,
                 knowledge_list: list | None = None) -> str:
    """拼装归因提示词。

    Args:
        anomalies: 待归因的异常项。
        retriever: 可选的知识检索回调。传入后，对每条异常调用一次 B 检索接口，
            将 Top-1 片段内容作为「知识补充」拼入对应条目；返回 None 或抛异常时
            静默跳过，保持原有硬编码 Prompt 不变。
        knowledge_list: 可选，预检索好的知识列表（与 anomalies 等长），优先于 retriever。
    """
    lines = []
    for i, a in enumerate(anomalies):
        evidence = json.dumps(a.evidence, ensure_ascii=False, default=str)
        hist = _history_analysis_block(a.evidence)
        entry = f"{i + 1}. 规则{a.rule_id}「{a.rule_name}」：{a.description}；证据：{evidence}"

        knowledge = None
        if knowledge_list is not None:
            knowledge = knowledge_list[i]
        elif retriever is not None:
            try:
                knowledge = retriever(a)
            except Exception:
                knowledge = None  # B 服务异常不阻断归因，降级为纯硬编码 Prompt
        if knowledge:
            entry += f"\n【知识补充】{knowledge}"

        lines.append(f"{entry}\n{hist}")
    return "以下是通过规则引擎校验出的异常项，请逐条归因：\n" + "\n\n".join(lines)


def parse_json_response(text: str) -> list:
    """从模型回复中提取JSON对象并返回其 results 数组（容忍代码块围栏等包装）。"""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"模型回复中未找到JSON对象: {text[:200]}")
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON解析失败: {e}；原文: {text[:200]}")
    if not isinstance(parsed, dict) or not isinstance(parsed.get("results"), list):
        raise ValueError(f"期望 {{results: [...]}}，实际为: {type(parsed)}")
    return parsed["results"]


def _retrieve_knowledge(anomalies: list[Anomaly], retriever: Retriever | None) -> list:
    """为每条异常检索知识；retriever 为空或异常时返回 None（不阻断）。"""
    if retriever is None:
        return [None] * len(anomalies)
    result = []
    for a in anomalies:
        try:
            result.append(retriever(a))
        except Exception:
            result.append(None)
    return result


def _with_knowledge(explanation: str, knowledge: str | None) -> str:
    """把知识片段作为「知识补充」追加到归因说明末尾（报告可见）。"""
    if knowledge:
        return f"{explanation}\n【知识补充】{knowledge}"
    return explanation


def attribute_anomalies(anomalies: list[Anomaly], client: LLMClient,
                        retriever: Retriever | None = None) -> list[Attribution]:
    """批量调用LLM归因。类别非法钳制为'其他'；条目缺失用fallback，不中断。"""
    if not anomalies:
        return []
    # 先统一检索一遍知识：既拼入 Prompt 供 LLM 参考，也追加到归因说明保证报告可见。
    knowledge_list = _retrieve_knowledge(anomalies, retriever)
    print(f"[知识] 检索命中 {sum(1 for k in knowledge_list if k)}/{len(anomalies)} 条")
    prompt = build_prompt(anomalies, knowledge_list=knowledge_list)
    try:
        response = client.chat([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        parsed = parse_json_response(response)
    except Exception:
        parsed = []  # 模型不可用：整体降级为未归因，报告仍输出规则判定
    attributions = []
    for i, a in enumerate(anomalies):
        knowledge = knowledge_list[i]
        # 预大率 > 100% 强行标记为数据错误（不依赖 AI 输出）
        pre = a.evidence.get("预大率")
        if pre is not None and isinstance(pre, (int, float)) and pre > 1.0:
            explanation = _with_knowledge("预大率超过100%，数据异常，无法判断补投根因。", knowledge)
            monitor.log_attribution(str(a.order_id), explanation)
            attributions.append(Attribution(
                order_id=a.order_id, rule_id=a.rule_id, category="数据错误",
                explanation=explanation,
                suggestion="核实「投料扣除余数实际预大率」数据。"))
            continue
        item = parsed[i] if i < len(parsed) and isinstance(parsed[i], dict) else None
        if item and item.get("category"):
            category = str(item["category"])
            if category not in ATTRIBUTION_CATEGORIES:
                category = "其他"
            explanation = _with_knowledge(str(item.get("explanation", "")), knowledge)
            monitor.log_attribution(str(a.order_id), explanation)
            attributions.append(Attribution(
                order_id=a.order_id, rule_id=a.rule_id, category=category,
                explanation=explanation,
                suggestion=str(item.get("suggestion", ""))))
        else:
            explanation = _with_knowledge("模型未返回有效归因，请人工复核。", knowledge)
            monitor.log_attribution(str(a.order_id), explanation)
            attributions.append(Attribution(
                order_id=a.order_id, rule_id=a.rule_id, category="未归因",
                explanation=explanation,
                suggestion="人工复核异常项。"))
    return attributions
