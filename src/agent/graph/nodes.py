"""编排层节点实现。

每个节点是 (state: AgentState) -> dict 的纯函数，返回"局部更新"由 LangGraph 合并。
不依赖 LangGraph 运行时，因此可以脱离图单独单测。
"""
import functools
import time
import traceback
from pathlib import Path

import pandas as pd
from langgraph.graph import END

from ..config import (PROJECT_ROOT, load_field_mapping, load_rule_config,
                      load_settings, resolve_api_key)
from ..data_loader import discover_files, join_order_info, normalize_factory
from ..engine import ValidationEngine
from ..history_scrap import (build_history_index,
                             enrich_anomalies_with_metrics,
                             match_history_columns)
from ..llm.attribution import attribute_anomalies
from ..llm.client import MockLLMClient, OpenAICompatClient
from ..llm.knowledge import B_BASE_URL, B_TIMEOUT_SECONDS, retrieve_knowledge
from ..parsers.report_parser import (ReportParseError, ReportParser,
                                     build_product_order_index,
                                     filter_order_by_products)
from ..reporting.report_writer import write_excel_report, write_markdown_summary
from ..rules.replenish import RuleR2AfterBatch, RuleR3DuplicateReplenish
from ..rules.scrap import RuleR4ScrapWithOnlineBoards
from ..rules.warehouse_in import RuleR1WarehouseIn
from ..trace.tracer import Tracer


def _log(tracer, step, status, detail):
    if tracer is not None:
        tracer.log(step, status, detail)


def traced_node(step: str, on_error: str = "abort"):
    """把节点包装成"自动写 trace + 统一异常态度"的形式。

    Args:
        step: 写入 Tracer 的步骤名。**与节点名解耦**——parse_file 与 parse_factory
            都记 "parse"，以此守住 tests/test_cli_e2e.py:43 的四个 step 断言。
        on_error: "abort" ⇒ 异常写 error + exit_code=2，由路由短路到 END；
            "degrade" ⇒ 异常只追加 messages，流程继续（决策记录#4：
            LLM/知识侧失败绝不影响校验主流程）。

    节点可在返回值里带两个私有键，装饰器会取走且不写进 State：
        _trace: dict —— 本次执行的摘要，合并进 trace 的 detail
        _status: str —— 覆盖默认的 "ok"（如 attribute_skipped 用 "skip"）
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(state):
            t0 = time.perf_counter()

            try:
                result = fn(state) or {}
            except Exception as e:
                elapsed = round((time.perf_counter() - t0) * 1000)
                _log(state.get("tracer"), step, "fail",
                     {"error": str(e), "node": fn.__name__,
                      "traceback": traceback.format_exc(limit=3),
                      "elapsed_ms": elapsed})
                if on_error == "abort":
                    return {"error": f"{fn.__name__} 失败：{e}", "exit_code": 2}
                return {"messages": [f"[警告] {fn.__name__} 失败，已降级继续：{e}"]}

            detail = result.pop("_trace", {})
            status = result.pop("_status", "ok")
            detail["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)
            # load_config 在自己内部建 Tracer，优先用它返回的那个
            _log(result.get("tracer") or state.get("tracer"), step, status, detail)
            return result
        return wrapper
    return decorator


def build_engine(rule_config: dict | None = None) -> ValidationEngine:
    """从 main.py 原样搬运：注册四条规则插件。

    rule_config 为 config/rules.yaml 的规则参数（可为 None/{}），用于把会变的
    业务阈值（如后批订单时间窗口）注入规则，改数值不动代码、不发版。
    """
    rule_config = rule_config or {}
    engine = ValidationEngine()
    engine.register(RuleR1WarehouseIn())
    engine.register(RuleR2AfterBatch(
        window_days=int(rule_config.get("r2_after_batch_window_days", 7))))
    engine.register(RuleR3DuplicateReplenish())
    engine.register(RuleR4ScrapWithOnlineBoards())
    return engine


def build_llm_client(settings: dict, use_mock: bool):
    """无API密钥且非mock模式时返回 None（归因降级，仅规则判定）。"""
    if use_mock or settings["llm"].get("provider") == "mock":
        return MockLLMClient()
    api_key = resolve_api_key(settings)
    if not api_key:
        return None
    return OpenAICompatClient(
        base_url=settings["llm"]["base_url"], api_key=api_key,
        model=settings["llm"]["model"],
        timeout=settings["llm"].get("timeout_seconds", 60))


@traced_node("config")
def load_config(state):
    settings = load_settings()
    field_mapping = load_field_mapping()
    rule_config = load_rule_config()
    trace_dir = state.get("trace_dir") or (PROJECT_ROOT / settings["trace"]["dir"])
    tracer = Tracer(trace_dir)
    client = build_llm_client(settings, state.get("use_mock", False))
    return {
        "settings": settings,
        "field_mapping": field_mapping,
        "tracer": tracer,
        "engine": build_engine(rule_config),
        "llm_client": client,
        "_trace": {"provider": settings["llm"].get("provider"),
                   "llm_ready": client is not None},
    }


@traced_node("parse")
def parse_file(state):
    """测试模式：直接解析 --file 指定的单个文件（搬运 main.py:82-91）。"""
    factory = state.get("factory") or "测试"
    parser = ReportParser(state["field_mapping"])
    try:
        report = parser.parse(state["file_path"], factory,
                              state["report_type"], state.get("sheet"))
    except ReportParseError as e:
        return {"error": str(e), "exit_code": 2, "_status": "fail",
                "_trace": {"error": str(e)}}
    return {"report": report, "factory": factory,
            "order_df": None, "hist_index": {},
            "_trace": {"rows": len(report.df),
                       "quality_issues": len(report.quality_issues)}}


@traced_node("parse")
def parse_factory(state):
    """工厂模式：自动匹配文件 + 按工厂过滤 + 建索引（搬运 main.py:93-132）。"""
    factory = state.get("factory")
    if not factory:
        msg = "未指定 --file 时，必须提供 --工厂"
        return {"error": msg, "exit_code": 2, "_status": "fail",
                "_trace": {"error": msg}}

    files = discover_files(factory, PROJECT_ROOT,
                           bt_files=state.get("bt_files"),
                           order_files=state.get("order_files"),
                           hist_files=state.get("hist_files"))
    msgs = [f"[警告] 未找到{name}文件，对应关联字段将留空"
            for name in ("补投", "订单") if files[name] is None]

    if files["补投"] is None:
        msg = "未找到补投明细表文件"
        return {"error": msg, "exit_code": 2, "messages": msgs,
                "_status": "fail", "_trace": {"error": msg}}

    try:
        bt_raw = pd.read_excel(files["补投"])
        if "组织名称" in bt_raw.columns:
            bt_raw = bt_raw[bt_raw["组织名称"].map(normalize_factory)
                            == normalize_factory(factory)]
        # 成品筛选后的补投（功能一取产品编号用）
        bt_finished = (bt_raw[bt_raw["补料类别"] == "成品"]
                       if "补料类别" in bt_raw.columns else bt_raw)

        parser = ReportParser(state["field_mapping"])
        report = parser.parse_df(bt_raw, factory, state["report_type"],
                                 source_path=files["补投"])

        # 订单：先读全部行（供功能一/二），再按工厂过滤（供销售单号关联）
        order_full, order_df = None, None
        if files["订单"]:
            order_full = pd.read_excel(files["订单"])
            order_df = (order_full[order_full["生产工厂"].map(normalize_factory)
                                   == normalize_factory(factory)]
                        if "生产工厂" in order_full.columns else order_full)

        report.product_order_index = build_product_order_index(
            filter_order_by_products(order_full, bt_finished))
        hist_index = (build_history_index(pd.read_excel(files["报废"]))
                      if files["报废"] else {})
    except ReportParseError as e:
        return {"error": str(e), "exit_code": 2, "messages": msgs,
                "_status": "fail", "_trace": {"error": str(e)}}

    return {"report": report, "order_df": order_df, "hist_index": hist_index,
            "messages": msgs,
            "_trace": {"rows": len(report.df),
                       "quality_issues": len(report.quality_issues),
                       "product_order_keys": len(report.product_order_index),
                       "hist_keys": len(hist_index)}}


@traced_node("enrich")
def enrich(state):
    """多表关联（搬运 main.py:137-145）。

    左连接不减少主表行。匹配不到订单/历史数据属正常业务场景——对应列留空即可，
    不视为错误；只有关联过程本身抛异常才由 @traced_node 兜底 abort。
    """
    report = state["report"]
    order_df = state.get("order_df")
    hist_index = state.get("hist_index") or {}

    order_rows = 0
    if order_df is not None and not order_df.empty:
        report.df = join_order_info(report.df, order_df)
        order_rows = len(order_df)
    if hist_index:
        report.df = match_history_columns(report.df, hist_index)

    return {"report": report,
            "_trace": {"order_rows": order_rows, "hist_keys": len(hist_index)}}


@traced_node("validate")
def validate(state):
    """数据质量问题 D0 + 规则异常（搬运 main.py:147-154）。"""
    report, engine = state["report"], state["engine"]
    anomalies = list(report.quality_issues) + engine.run(report)
    anomalies = enrich_anomalies_with_metrics(anomalies, report.df)

    tracer = state.get("tracer")
    for err in engine.errors:
        _log(tracer, "validate", "fail", err)

    return {"anomalies": anomalies, "rule_errors": list(engine.errors),
            "_trace": {"anomalies": len(anomalies),
                       "rule_errors": len(engine.errors)}}


SKIP_WARNING = "[警告] 未配置API密钥，跳过LLM归因（报告仅含规则判定与证据）"


@traced_node("attribute", on_error="degrade")
def attribute(state):
    """LLM 归因（搬运 main.py:163-171）。

    B 项目知识检索的降级逻辑封装在 attribution.py 内部（服务不可用返回 None
    自动降级），图层不重复实现。
    """
    settings = state.get("settings") or {}
    kb = settings.get("knowledge", {}) if isinstance(settings, dict) else {}
    retriever = functools.partial(
        retrieve_knowledge,
        base_url=kb.get("base_url", B_BASE_URL),
        timeout=float(kb.get("timeout_seconds", B_TIMEOUT_SECONDS)),
        retry_times=int(kb.get("retry_times", 2)),
        retry_backoff_seconds=float(kb.get("retry_backoff_seconds", 0.5)))
    attributions = attribute_anomalies(state["anomalies"], state["llm_client"],
                                       retriever=retriever)
    return {"attributions": attributions, "_trace": {"count": len(attributions)}}


@traced_node("attribute", on_error="degrade")
def attribute_skipped(state):
    """跳过归因的显式节点。

    必须是真节点而非直连 write_report：tests/test_cli_e2e.py:43 断言 trace 含
    attribute step，跳过时也要留痕，同时让"为何无归因"可查。
    """
    if not state.get("anomalies"):
        reason, msgs = "无异常", []
    else:
        reason, msgs = "无API密钥", [SKIP_WARNING]
    return {"attributions": [], "skip_reason": reason, "messages": msgs,
            "_status": "skip", "_trace": {"reason": reason}}


@traced_node("report")
def write_report(state):
    """生成 Excel 报告与 Markdown 摘要（搬运 main.py:174-183）。"""
    settings = state.get("settings") or {}
    out_dir = (Path(state["output_dir"]) if state.get("output_dir")
               else PROJECT_ROOT / settings["output"]["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    factory = state.get("factory") or "测试"
    anomalies = state.get("anomalies") or []
    # attribute 在 degrade 失败时不返回该键，必须防御性读取
    attributions = state.get("attributions") or []
    report = state["report"]

    excel_path = write_excel_report(
        anomalies, attributions,
        str(out_dir / f"异常校验报告_{factory}_{stamp}.xlsx"), df=report.df)
    md_path = write_markdown_summary(
        anomalies, attributions,
        str(out_dir / f"校验摘要_{factory}_{stamp}.md"))

    return {"excel_path": excel_path, "md_path": md_path, "exit_code": 0,
            "_trace": {"excel": excel_path, "markdown": md_path}}


# ─────────────────────────── 路由函数 ───────────────────────────
# 全部为纯读函数：只看 State、不产生副作用、不修改 State。
# skip_reason 之类的判定留给节点，路由只回答"下一步去哪"。

def guard(next_node: str):
    """生成"有 error 就去 END，否则去 next_node"的路由函数。"""
    def route(state):
        return END if state.get("error") else next_node
    return route


def route_mode(state):
    """双模式加载分支：--file 走测试模式，--工厂 走工厂模式。"""
    if state.get("error"):
        return END
    return "parse_file" if state.get("file_path") else "parse_factory"


def route_after_parse(state):
    """解析失败（ReportParseError / 文件缺失 / 参数缺失）直接终止。"""
    return END if state.get("error") else "enrich"


def route_after_validate(state):
    """数据驱动分支 + 降级分支。

    无异常 ⇒ 没有归因的必要；无 llm_client ⇒ 无密钥，不具备归因能力。
    两者都转 attribute_skipped，由该节点自行判定 skip_reason。
    """
    if state.get("error"):
        return END
    if not state.get("anomalies") or state.get("llm_client") is None:
        return "attribute_skipped"
    return "attribute"
