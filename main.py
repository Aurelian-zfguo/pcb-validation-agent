"""PCB生产预投业务数据校验Agent —— CLI入口。

用法:
    python main.py --工厂 珠海一厂                   # 工厂模式：自动匹配目录下文件并关联
    python main.py --file xxx.xlsx --sheet 补投       # 测试模式：直接指定文件
"""
import argparse
import functools
import sys
import time
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")  # Windows控制台中文输出

from src.agent.config import PROJECT_ROOT, load_field_mapping, load_settings, resolve_api_key
from src.agent.data_loader import discover_files, join_order_info, normalize_factory
from src.agent.engine import ValidationEngine
from src.agent.history_scrap import (
    build_history_index, enrich_anomalies_with_metrics, match_history_columns)
from src.agent.llm.attribution import attribute_anomalies
from src.agent.llm.client import LLMClient, MockLLMClient, OpenAICompatClient
from src.agent.llm.knowledge import B_BASE_URL, B_TIMEOUT_SECONDS, retrieve_knowledge
from src.agent.llm.rag_monitor import monitor
from src.agent.llm.desensitize import desensitize_report
from src.agent.parsers.report_parser import (
    ReportParseError, ReportParser, build_product_order_index, filter_order_by_products)
from src.agent.reporting.report_writer import write_excel_report, write_markdown_summary
from src.agent.rules.replenish import RuleR2AfterBatch, RuleR3DuplicateReplenish
from src.agent.rules.scrap import RuleR4ScrapWithOnlineBoards
from src.agent.rules.warehouse_in import RuleR1WarehouseIn
from src.agent.schema import REPORT_TYPES
from src.agent.trace.tracer import Tracer


def build_engine() -> ValidationEngine:
    engine = ValidationEngine()
    engine.register(RuleR1WarehouseIn())
    engine.register(RuleR2AfterBatch())
    engine.register(RuleR3DuplicateReplenish())
    engine.register(RuleR4ScrapWithOnlineBoards())
    return engine


def _build_llm_client(settings: dict, use_mock: bool) -> LLMClient | None:
    """无API密钥且非mock模式时返回None（归因降级，仅规则判定）。"""
    if use_mock or settings["llm"].get("provider") == "mock":
        return MockLLMClient()
    api_key = resolve_api_key(settings)
    if not api_key:
        return None
    return OpenAICompatClient(
        base_url=settings["llm"]["base_url"], api_key=api_key,
        model=settings["llm"]["model"],
        timeout=settings["llm"].get("timeout_seconds", 60))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PCB生产预投业务数据校验Agent")
    parser.add_argument("--file", dest="file", default=None, help="测试模式：直接指定报表文件路径")
    parser.add_argument("--工厂", "--factory", dest="factory", default=None,
                        help="工厂名，如 珠海一厂（工厂模式必填，自动匹配目录下文件）")
    parser.add_argument("--类型", "--type", dest="report_type", default="补投日报",
                        choices=REPORT_TYPES, help="报表类型（工厂模式默认补投日报）")
    parser.add_argument("--输出目录", "--output-dir", dest="output_dir", default=None)
    parser.add_argument("--trace-dir", dest="trace_dir", default=None)
    parser.add_argument("--sheet", dest="sheet", default=None, help="测试模式下Excel的Sheet名")
    parser.add_argument("--补投", dest="bt_files", action="append", default=None, help="补投明细表文件（可多次指定）")
    parser.add_argument("--订单", dest="order_files", action="append", default=None, help="订单完成情况文件（可多次指定，按生产工厂匹配）")
    parser.add_argument("--报废", dest="hist_files", action="append", default=None, help="历史报废率文件（可多次指定，按组织匹配）")
    parser.add_argument("--mock-llm", action="store_true", help="用MockLLM跑通链路（无API密钥时）")
    args = parser.parse_args(argv)

    settings = load_settings()
    tracer = Tracer(args.trace_dir or (PROJECT_ROOT / settings["trace"]["dir"]))

    # 1) 获取数据源：--file 测试模式 或 --工厂 自动匹配模式
    t0 = time.perf_counter()
    report_parser = ReportParser(load_field_mapping())
    hist_index = {}  # 历史报废率索引（--file 模式为空）
    if args.file:
        # 测试模式：直接解析指定文件
        factory = args.factory or "测试"
        try:
            report = report_parser.parse(args.file, factory, args.report_type, args.sheet)
        except ReportParseError as e:
            tracer.log("parse", "fail", {"error": str(e)})
            print(f"[错误] {e}")
            return 2
        order_df = None
    else:
        # 工厂模式：自动匹配文件 + 按工厂过滤 + 多表关联
        if not args.factory:
            print("[错误] 未指定 --file 时，必须提供 --工厂")
            return 2
        factory = args.factory
        files = discover_files(factory, PROJECT_ROOT,
                               bt_files=args.bt_files, order_files=args.order_files,
                               hist_files=args.hist_files)
        for name in ("补投", "订单"):
            if files[name] is None:
                print(f"[警告] 未找到{name}文件，对应关联字段将留空")
        if files["补投"] is None:
            print("[错误] 未找到补投明细表文件")
            return 2
        try:
            bt_raw = pd.read_excel(files["补投"])
            if "组织名称" in bt_raw.columns:
                bt_raw = bt_raw[bt_raw["组织名称"].map(normalize_factory) == normalize_factory(factory)]
            # 成品筛选后的补投（功能一取产品编号用）
            bt_finished = bt_raw[bt_raw["补料类别"] == "成品"] if "补料类别" in bt_raw.columns else bt_raw
            report = report_parser.parse_df(bt_raw, factory, args.report_type, source_path=files["补投"])
            # 订单：先读全部行（供功能一/二），再按工厂过滤（供销售单号关联）
            order_full = None
            order_df = None
            if files["订单"]:
                order_full = pd.read_excel(files["订单"])
                if "生产工厂" in order_full.columns:
                    order_df = order_full[order_full["生产工厂"].map(normalize_factory) == normalize_factory(factory)]
                else:
                    order_df = order_full
            # 功能一/二：构建型号订单索引（空则空字典，不报错）
            report.product_order_index = build_product_order_index(
                filter_order_by_products(order_full, bt_finished))
            # 历史报废率索引（无文件则空）
            if files["报废"]:
                hist_index = build_history_index(pd.read_excel(files["报废"]))
        except ReportParseError as e:
            tracer.log("parse", "fail", {"error": str(e)})
            print(f"[错误] {e}")
            return 2
    tracer.log("parse", "ok", {
        "rows": len(report.df), "quality_issues": len(report.quality_issues),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000)})

    # 1.5) 多表关联（左连接，不减少主表行）
    if order_df is not None and not order_df.empty:
        report.df = join_order_info(report.df, order_df)
        tracer.log("join", "ok", {"order_rows": len(order_df)})
    # 历史报废率4列（匹配失败留空）
    if hist_index:
        report.df = match_history_columns(report.df, hist_index)
    tracer.log("index", "ok", {"product_order_keys": len(report.product_order_index),
                               "hist_keys": len(hist_index)})

    # 2) 校验（数据质量问题D0 + 规则异常）
    engine = build_engine()
    anomalies = list(report.quality_issues) + engine.run(report)
    anomalies = enrich_anomalies_with_metrics(anomalies, report.df)  # 补历史报废率指标供归因
    for err in engine.errors:
        tracer.log("validate", "fail", err)
    tracer.log("validate", "ok", {
        "anomalies": len(anomalies), "rule_errors": len(engine.errors)})

    # 3) 脱敏 + LLM归因
    desensitize_report(report)  # 生成映射表；归因提示词只含规则证据，不含客户/料号原文
    client = _build_llm_client(settings, args.mock_llm)
    if client is None:
        print("[警告] 未配置API密钥，跳过LLM归因（报告仅含规则判定与证据）")
        attributions = []
    else:
        # 可选增强：接入 B 项目知识检索（retrieve_knowledge 内部会记录到 RAG 监控）。
        # 服务未启动/超时/异常时返回 None，自动降级为纯硬编码 Prompt。
        kb = settings.get("knowledge", {}) if isinstance(settings, dict) else {}
        retriever = functools.partial(
            retrieve_knowledge,
            base_url=kb.get("base_url", B_BASE_URL),
            timeout=float(kb.get("timeout_seconds", B_TIMEOUT_SECONDS)),
        )
        attributions = attribute_anomalies(anomalies, client, retriever=retriever)
    tracer.log("attribute", "ok", {"count": len(attributions)})

    # 4) 报告输出
    out_dir = Path(args.output_dir) if args.output_dir else (PROJECT_ROOT / settings["output"]["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    excel_path = write_excel_report(
        anomalies, attributions, str(out_dir / f"异常校验报告_{factory}_{stamp}.xlsx"),
        df=report.df)
    md_path = write_markdown_summary(
        anomalies, attributions, str(out_dir / f"校验摘要_{factory}_{stamp}.md"))
    tracer.log("report", "ok", {"excel": excel_path, "markdown": md_path})

    print(f"校验完成：数据 {len(report.df)} 行，数据质量问题 {len(report.quality_issues)}，"
          f"异常 {len(anomalies)}，归因 {len(attributions)}")
    print(f"Excel报告: {excel_path}")
    print(f"摘要: {md_path}")
    print(f"执行日志: {tracer.file}")
    monitor.generate_summary()  # 生成 rag_logs/ 的 CSV 并打印统计摘要
    return 0


if __name__ == "__main__":
    sys.exit(main())