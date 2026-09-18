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

RETRY_SYSTEM_PROMPT = SYSTEM_PROMPT + (
    "再次强调：只输出一个纯 JSON 对象，禁止任何 markdown 代码块围栏、"
    "禁止任何前置或后置说明文字。"
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


def _strip_code_fence(text: str) -> str:
    """剥离首尾的 markdown 代码块围栏（如 ```json ... ```）。"""
    t = text.strip()
    t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _extract_json_candidate(text: str) -> str:
    """从回复里提取最外层的 JSON 文本。

    从第一个 { 或 [ 起做括号配对扫描（跳过字符串内部），找到最外层 JSON：
    括号闭合即返回；未闭合（截断）则返回从起点到末尾，交给截断修复处理。
    """
    t = _strip_code_fence(text)
    starts = [i for i in (t.find("{"), t.find("[")) if i != -1]
    if not starts:
        return t
    start = min(starts)

    stack = []
    in_str = False
    escaped = False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch == "}":
            if not stack or stack[-1] != "}":
                break
            stack.pop()
        elif ch == "]":
            if not stack or stack[-1] != "]":
                break
            stack.pop()
        if not stack:
            return t[start:i + 1]
    return t[start:]  # 未闭合：截断的 JSON


def _scan_json_delimiters(text: str):
    """扫描 JSON 文本，返回 (未闭合的闭合符栈, 是否在字符串内截断)。

    逐字符扫描并正确处理字符串内的转义与 { } [ ]，因此不会被字符串里的括号误导。
    """
    stack = []
    in_str = False
    escaped = False
    for ch in text:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch == "}":
            if not stack or stack[-1] != "}":
                return [], False  # 多余闭合，结构已损坏
            stack.pop()
        elif ch == "]":
            if not stack or stack[-1] != "]":
                return [], False
            stack.pop()
    return stack, in_str


def _repair_truncated_json(text: str) -> str | None:
    """启发式修复被截断的 JSON（括号不匹配但结构完整时补全缺失的闭合符）。

    严格约束：
    1. 截断点若落在未闭合的字符串内（扫描到末尾仍在引号内），直接放弃，返回 None。
    2. 只补全缺失的 } / ]，不做任何字段级修复。
    3. 补全后必须由调用方 json.loads 校验；校验失败仍视为未修复。

    这是启发式修复，可能失败。
    """
    stack, in_str = _scan_json_delimiters(text)
    if in_str or not stack:
        return None
    return text + "".join(reversed(stack))


def _detect_truncation(text: str) -> bool:
    """检测文本是否疑似被截断（括号不平衡，或结尾落在字符串内部）。"""
    stack, in_str = _scan_json_delimiters(_extract_json_candidate(text))
    return in_str or bool(stack)


def parse_json_response(text: str) -> list:
    """解析模型回复中的 results 数组，容错处理包裹/截断。

    顺序：剥离围栏 → 提取最外层 JSON → json.loads → 截断补全再试 →
    兼容顶层数组 → 校验 results 结构。任何失败抛 ValueError。
    """
    candidate = _extract_json_candidate(text)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        repaired = _repair_truncated_json(candidate)
        if repaired is None:
            raise ValueError(f"模型回复无法解析为JSON: {text[:200]}")
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON修复后仍无法解析: {e}；原文: {text[:200]}")

    if isinstance(parsed, list):
        return parsed  # 防御性：顶层数组直接视为 results
    if isinstance(parsed, dict) and isinstance(parsed.get("results"), list):
        return parsed["results"]
    raise ValueError(f"期望 {{results: [...]}}，实际为: {type(parsed)}")


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
    """批量调用LLM归因。类别非法钳制为'其他'；条目缺失用fallback，不中断。

    三层防护：
    1. 格式感知重试：解析失败/空结果时，用更严格的 Prompt 重试一次。
    2. JSON 修复：parse_json_response 内部剥离围栏、截断补全、兼容顶层数组。
    3. 降级兜底：解析彻底失败仍返回 category="未归因"，不中断、报告照出。
    """
    if not anomalies:
        return []
    # 先统一检索一遍知识：既拼入 Prompt 供 LLM 参考，也追加到归因说明保证报告可见。
    knowledge_list = _retrieve_knowledge(anomalies, retriever)
    print(f"[知识] 检索命中 {sum(1 for k in knowledge_list if k)}/{len(anomalies)} 条")
    prompt = build_prompt(anomalies, knowledge_list=knowledge_list)

    parsed, parse_failed, last_raw = [], True, ""
    try:
        last_raw = client.chat([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        parsed = parse_json_response(last_raw)
        parse_failed = False
    except Exception:
        parse_failed = True

    # 第1层：格式感知重试（仅一次）——解析失败或返回空结果时，用更严格 Prompt 再试
    if parse_failed or not parsed:
        try:
            last_raw = client.chat([
                {"role": "system", "content": RETRY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ])
            parsed = parse_json_response(last_raw)
            parse_failed = False
        except Exception:
            parse_failed = True
            parsed = []

    # 第3层：区分"解析失败"与"模型返回空"，并记录 finish_reason 便于排查
    if parse_failed:
        fr = getattr(client, "last_finish_reason", None)
        if not last_raw:
            reason = "LLM 调用失败，已降级"
        elif _detect_truncation(last_raw):
            reason = ("LLM 输出解析失败，已降级（疑似被截断"
                      + (f"，finish_reason={fr}" if fr else "")
                      + "）")
        else:
            reason = "LLM 输出解析失败，已降级（输出非 JSON）"
    else:
        reason = "模型未返回有效归因"

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
            explanation = _with_knowledge(reason + "，请人工复核。", knowledge)
            monitor.log_attribution(str(a.order_id), explanation)
            attributions.append(Attribution(
                order_id=a.order_id, rule_id=a.rule_id, category="未归因",
                explanation=explanation,
                suggestion="人工复核异常项。"))
    return attributions
