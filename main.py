"""PCB生产预投业务数据校验Agent —— CLI入口。

用法:
    python main.py --工厂 珠海一厂                   # 工厂模式：自动匹配目录下文件并关联
    python main.py --file xxx.xlsx --sheet 补投       # 测试模式：直接指定文件

本文件只负责 CLI：解析参数 → 组装初始 State → 驱动 LangGraph 图 → 打印与退出。
流程编排在 src/agent/graph/。
"""
import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8")  # Windows控制台中文输出

from src.agent.graph import build_graph
from src.agent.llm.rag_monitor import monitor
from src.agent.schema import REPORT_TYPES

# 节点名 → 进度文案。gui.py 靠实时读 stdout 显示日志。
NODE_LABELS = {
    "load_config": "加载配置",
    "parse_file": "解析报表（测试模式）",
    "parse_factory": "解析报表（工厂模式）",
    "enrich": "多表关联与指标补齐",
    "validate": "规则校验",
    "attribute": "LLM归因",
    "attribute_skipped": "跳过归因",
    "write_report": "生成报告",
}


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="PCB生产预投业务数据校验Agent")
    parser.add_argument("--file", dest="file", default=None, help="测试模式：直接指定报表文件路径")
    parser.add_argument("--工厂", "--factory", dest="factory", default=None,
                        help="工厂名，如 珠海一厂（工厂模式必填，自动匹配目录下文件）")
    parser.add_argument("--类型", "--type", dest="report_type", default="补投日报",
                        choices=REPORT_TYPES, help="报表类型（工厂模式默认补投日报）")
    parser.add_argument("--输出目录", "--output-dir", dest="output_dir", default=None)
    parser.add_argument("--trace-dir", dest="trace_dir", default=None)
    parser.add_argument("--sheet", dest="sheet", default=None, help="测试模式下Excel的Sheet名")
    parser.add_argument("--补投", dest="bt_files", action="append", default=None,
                        help="补投明细表文件（可多次指定）")
    parser.add_argument("--订单", dest="order_files", action="append", default=None,
                        help="订单完成情况文件（可多次指定，按生产工厂匹配）")
    parser.add_argument("--报废", dest="hist_files", action="append", default=None,
                        help="历史报废率文件（可多次指定，按组织匹配）")
    parser.add_argument("--mock-llm", action="store_true", help="用MockLLM跑通链路（无API密钥时）")
    return parser.parse_args(argv)


def _initial_state(args) -> dict:
    return {
        "factory": args.factory,
        "report_type": args.report_type,
        "file_path": args.file,
        "sheet": args.sheet,
        "bt_files": args.bt_files,
        "order_files": args.order_files,
        "hist_files": args.hist_files,
        "output_dir": args.output_dir,
        "trace_dir": args.trace_dir,
        "use_mock": args.mock_llm,
        "messages": [],
    }


def _finish(final: dict) -> int:
    """打印最终结果并返回退出码。错误信息走 stdout（gui.py 与 e2e 测试依赖）。"""
    for msg in final.get("messages", []):
        print(msg)

    if final.get("error"):
        print(f"[错误] {final['error']}")
        return final.get("exit_code", 2)

    report = final.get("report")
    rows = len(report.df) if report is not None else 0
    quality = len(report.quality_issues) if report is not None else 0
    print(f"校验完成：数据 {rows} 行，数据质量问题 {quality}，"
          f"异常 {len(final.get('anomalies', []))}，"
          f"归因 {len(final.get('attributions', []))}")
    print(f"Excel报告: {final.get('excel_path')}")
    print(f"摘要: {final.get('md_path')}")
    tracer = final.get("tracer")
    if tracer is not None:
        print(f"执行日志: {tracer.file}")
    monitor.generate_summary()  # 生成 rag_logs/ 的 CSV 并打印统计摘要
    return final.get("exit_code", 0)


def main(argv=None) -> int:
    args = _parse_args(argv)
    final: dict = {}
    try:
        for mode, chunk in build_graph().stream(
                _initial_state(args), stream_mode=["updates", "values"]):
            if mode == "updates":
                for node_name in chunk:
                    print(f"→ {NODE_LABELS.get(node_name, node_name)}", flush=True)
            else:
                final = chunk
    except Exception as e:  # 兜底：不让 gui.py 的日志框冒出裸 traceback
        print(f"[错误] 流程异常终止：{e}")
        return 2
    return _finish(final)


if __name__ == "__main__":
    sys.exit(main())
