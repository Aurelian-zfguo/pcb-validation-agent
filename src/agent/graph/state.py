"""编排层的共享状态。

无 checkpointer（不做 HITL），因此 State 无需可序列化——
DataFrame、Tracer、LLM 客户端等对象实例可以直接放。
"""
import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    # ── 输入（main.py 从 argparse 组装，全程只读）──
    factory: str                    # 工厂名，--file 模式下缺省为 "测试"
    report_type: str                # REPORT_TYPES 之一
    file_path: str | None           # 非 None ⇒ 测试模式（route_mode 的判据）
    sheet: str | None
    bt_files: list[str] | None
    order_files: list[str] | None
    hist_files: list[str] | None
    output_dir: str | None
    trace_dir: str | None
    use_mock: bool

    # ── 运行时句柄（load_config 产出，之后只读）──
    settings: dict
    field_mapping: dict
    tracer: Any                     # Tracer 实例；@traced_node 从这里取
    engine: Any                     # ValidationEngine（已注册 R1~R4）
    llm_client: Any | None          # None ⇒ 无密钥，触发跳过归因分支

    # ── 中间数据 ──
    report: Any | None              # StandardReport
    order_df: Any | None            # pd.DataFrame；测试模式为 None
    hist_index: dict                # 历史报废率索引；测试模式为 {}
    anomalies: list                 # list[Anomaly] = quality_issues + 规则异常
    rule_errors: list               # engine.errors 快照

    # ── 输出 ──
    attributions: list              # list[Attribution]
    skip_reason: str                # 跳过归因的原因
    excel_path: str
    md_path: str

    # ── 控制流 ──
    messages: Annotated[list[str], operator.add]
    error: str | None
    exit_code: int                  # 0 成功 / 2 失败
