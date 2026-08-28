"""编排层节点实现。

每个节点是 (state: AgentState) -> dict 的纯函数，返回"局部更新"由 LangGraph 合并。
不依赖 LangGraph 运行时，因此可以脱离图单独单测。
"""
import functools
import time
import traceback
from pathlib import Path

from ..config import (PROJECT_ROOT, load_field_mapping, load_settings,
                      resolve_api_key)
from ..engine import ValidationEngine
from ..llm.client import MockLLMClient, OpenAICompatClient
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


def build_engine() -> ValidationEngine:
    """从 main.py 原样搬运：注册四条规则插件。"""
    engine = ValidationEngine()
    engine.register(RuleR1WarehouseIn())
    engine.register(RuleR2AfterBatch())
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
    trace_dir = state.get("trace_dir") or (PROJECT_ROOT / settings["trace"]["dir"])
    tracer = Tracer(trace_dir)
    client = build_llm_client(settings, state.get("use_mock", False))
    return {
        "settings": settings,
        "field_mapping": field_mapping,
        "tracer": tracer,
        "engine": build_engine(),
        "llm_client": client,
        "_trace": {"provider": settings["llm"].get("provider"),
                   "llm_ready": client is not None},
    }
