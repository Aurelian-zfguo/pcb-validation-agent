# LangGraph 流程编排重构 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `main.py` 中 130 行的线性 `main()` 重构为 LangGraph 图编排，使降级/数据驱动/双模式三类条件分支显式化，并让 Tracer 逐节点自动留痕。

**Architecture:** 新增 `src/agent/graph/` 包（`state.py` / `nodes.py` / `builder.py`），承载 8 个节点、3 个路由函数与 `@traced_node` 装饰器。`main.py` 瘦身为约 60 行的 CLI 壳：argparse → 组装初始 State → `graph.stream()` → 打印进度 → 按 `exit_code` 退出。所有业务模块（`rules/` `parsers/` `llm/` `reporting/` `engine.py` `history_scrap.py` `data_loader.py` `desensitize.py`）一行不改，节点只是搬运现有函数调用。

**Tech Stack:** Python 3.14.6（`.venv`）、LangGraph 1.x、pandas 3.0.5、pytest 8.x

**依据 spec:** `docs/superpowers/specs/2026-08-27-langgraph-orchestration-design.md`

## Global Constraints

以下约束适用于**每一个任务**，不再逐条重复：

- **解释器**：一律用 `.venv`。装包只能走 `".venv\Scripts\python.exe" -m pip install`，禁止用全局 `D:\Python\Python314`（踩坑记录#2）。
- **测试命令**：`PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest`。缺这个环境变量 Windows 控制台中文会乱码（踩坑记录#10）。
- **既有测试零改动**：`tests/` 下现有 16 个测试文件、共 50 个用例，**一个字都不能改**。它们全绿是每个任务的隐含验收条件。
- **业务模块零改动**：`src/agent/` 下除新增的 `graph/` 子包外，任何文件不得修改。
- **CLI 契约**：退出码 `0`（成功）/ `2`（失败）；错误信息打到 **stdout 而非 stderr**；trace JSONL 必须含 `parse` / `validate` / `attribute` / `report` 四个 step。三者分别被 `tests/test_cli_e2e.py:24`、`:57`、`:43` 断言。
- **文件路径**：所有工具调用使用完整 Windows 绝对路径（如 `D:\Python\Claude Code\Programs\PCB生产预投业务数据校验Agent\main.py`）。
- **提交粒度**：每个任务末尾提交一次，消息用中文祈使句。

---

### Task 0: 环境验证与基线固化

先证明 LangGraph 能用、并留下可回退的行为基线。**本任务失败即全盘暂停，不得继续写代码。**

**Files:**
- Create: `tests/test_langgraph_api.py`
- Modify: `requirements.txt`
- Create: `baseline/`（运行产物，需加入 .gitignore）
- Modify: `.gitignore`

**Interfaces:**
- Consumes: 无
- Produces: 已安装的 `langgraph` 包；`baseline/pytest_before.txt`；`baseline/` 下的旧版 Excel 与 Markdown 报告，供 Task 11 做等价性比对。

- [ ] **Step 1: 安装 langgraph 到 .venv**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent"
".venv/Scripts/python.exe" -m pip install langgraph
```

- [ ] **Step 2: 验证能 import 且打印版本**

```bash
".venv/Scripts/python.exe" -c "import langgraph, langgraph.graph as g; print('langgraph', langgraph.__version__); print(g.StateGraph, g.START, g.END)"
```

Expected: 打印版本号与三个对象，无 traceback。

**若这一步报错（Python 3.14 不兼容、依赖冲突等），立即停止本计划，把完整报错交回讨论。不要尝试降级 Python、不要改代码绕过。**

- [ ] **Step 3: 写 LangGraph API 契约测试**

这个测试锁死整个重构依赖的三条 API 假设。第三方库升级导致假设失效时，它会第一时间失败，而不是让你在 8 个节点里瞎找原因。

创建 `tests/test_langgraph_api.py`：

```python
"""锁定本项目依赖的 LangGraph API 契约。

这是少见的"测第三方库"的测试，理由：整个 graph/ 包建立在下面三条假设上，
一旦 langgraph 升级破坏了它们，这里失败比在 8 个节点里排查便宜得多。
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class _S(TypedDict, total=False):
    n: int
    path: str


def _build():
    def start(state):
        return {"n": state.get("n", 0) + 1}

    def left(state):
        return {"path": "left"}

    def right(state):
        return {"path": "right"}

    def route(state):
        return "left" if state["n"] > 0 else "right"

    b = StateGraph(_S)
    b.add_node("start", start)
    b.add_node("left", left)
    b.add_node("right", right)
    b.add_edge(START, "start")
    b.add_conditional_edges("start", route, ["left", "right"])
    b.add_edge("left", END)
    b.add_edge("right", END)
    return b.compile()


def test_conditional_edges_route_by_return_value():
    """假设1：路由函数返回节点名字符串即可决定走向。"""
    assert _build().invoke({"n": 5})["path"] == "left"
    assert _build().invoke({"n": -5})["path"] == "right"


def test_stream_multi_mode_yields_mode_chunk_tuples():
    """假设2：stream_mode=["updates","values"] 产出 (mode, chunk) 二元组。

    updates 的 chunk 形如 {节点名: 局部更新}；values 的 chunk 是完整 State 快照。
    main.py 靠这个形态同时拿到"节点进度"和"最终状态"。
    """
    modes, updates_nodes, last_values = [], [], None
    for mode, chunk in _build().stream({"n": 5}, stream_mode=["updates", "values"]):
        modes.append(mode)
        if mode == "updates":
            updates_nodes.extend(chunk.keys())
        else:
            last_values = chunk

    assert set(modes) <= {"updates", "values"}
    assert "start" in updates_nodes and "left" in updates_nodes
    assert last_values is not None and last_values["path"] == "left"


def test_conditional_edges_can_target_end():
    """假设3：路由函数可以返回 END 直接终止，用于错误短路。"""
    def only(state):
        return {"path": "done"}

    b = StateGraph(_S)
    b.add_node("only", only)
    b.add_edge(START, "only")
    b.add_conditional_edges("only", lambda s: END, [END])
    assert b.compile().invoke({"n": 1})["path"] == "done"
```

- [ ] **Step 4: 跑 API 契约测试**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_langgraph_api.py -v
```

Expected: 3 passed。

任何一条失败，说明 spec §8 预设的 API 形态与实际不符——停下来把失败输出交回讨论，再决定改用 `stream_mode="updates"` 自行合并的退路。

- [ ] **Step 5: 固化测试基线**

```bash
mkdir -p baseline
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest -q 2>&1 | tee baseline/pytest_before.txt
tail -3 baseline/pytest_before.txt
```

Expected: 末尾显示 `53 passed`（原有 50 + 本任务新增 3）。若原有部分不是 50 passed，**记录实际数字**并以它为准，Task 11 按实际基线比对。

- [ ] **Step 6: 固化行为基线（旧版报告产物）**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" main.py --工厂 金州厂 --输出目录 baseline/before --trace-dir baseline/traces_before
ls -la baseline/before
```

Expected: `baseline/before/` 下生成一个 `异常校验报告_金州厂_*.xlsx` 和一个 `校验摘要_金州厂_*.md`。

若无 API 密钥导致归因为空也没关系——Task 11 只比对**异常行数与规则编号分布**，那部分不依赖 LLM。

- [ ] **Step 7: 更新 requirements.txt 与 .gitignore**

`requirements.txt` 追加一行（放在 requests 之后）：

```
langgraph>=1.0
```

`.gitignore` 追加：

```
# 重构基线产物（Task 0 生成，仅本地比对用）
baseline/
```

- [ ] **Step 8: 提交**

```bash
git add tests/test_langgraph_api.py requirements.txt .gitignore
git commit -m "chore: 安装 langgraph 并锁定其 API 契约，固化重构基线"
```

---

### Task 1: AgentState 定义

**Files:**
- Create: `src/agent/graph/__init__.py`
- Create: `src/agent/graph/state.py`
- Test: `tests/test_graph_state.py`

**Interfaces:**
- Consumes: 无
- Produces: `AgentState`（TypedDict，`total=False`），供 `nodes.py` 与 `builder.py` 使用。字段清单见 Step 3。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_graph_state.py`：

```python
from src.agent.graph.state import AgentState


def test_state_is_total_false_typeddict():
    """total=False：节点只返回局部更新，不必填满所有字段。"""
    assert AgentState.__total__ is False


def test_state_declares_all_pipeline_fields():
    keys = set(AgentState.__annotations__)
    expected = {
        # 输入
        "factory", "report_type", "file_path", "sheet",
        "bt_files", "order_files", "hist_files",
        "output_dir", "trace_dir", "use_mock",
        # 运行时句柄
        "settings", "field_mapping", "tracer", "engine", "llm_client",
        # 中间数据
        "report", "order_df", "hist_index", "anomalies", "rule_errors",
        # 输出
        "attributions", "skip_reason", "excel_path", "md_path",
        # 控制流
        "messages", "error", "exit_code",
    }
    assert keys == expected


def test_messages_uses_add_reducer():
    """messages 是唯一带 reducer 的字段：多个节点的警告要累加而非覆盖。"""
    import operator
    from typing import get_args
    ann = AgentState.__annotations__["messages"]
    assert operator.add in get_args(ann)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_state.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.graph'`

- [ ] **Step 3: 实现 state.py**

创建 `src/agent/graph/__init__.py`（暂时留空，Task 9 再填导出）：

```python
"""LangGraph 编排层：State 定义、节点实现与图装配。"""
```

创建 `src/agent/graph/state.py`：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_state.py -v
```

Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add src/agent/graph/__init__.py src/agent/graph/state.py tests/test_graph_state.py
git commit -m "feat: 新增 LangGraph 编排层的 AgentState 定义"
```

---

### Task 2: @traced_node 装饰器

这是可观测性自动化的核心：取代现在手写的 4 处 `tracer.log()`，并统一"节点挂了怎么办"。

**Files:**
- Create: `src/agent/graph/nodes.py`
- Test: `tests/test_graph_nodes.py`

**Interfaces:**
- Consumes: `src.agent.trace.tracer.Tracer`（`log(step, status, detail)`）
- Produces:
  - `traced_node(step: str, on_error: str = "abort") -> Callable` — 装饰器工厂。
  - 被装饰函数签名 `(state: AgentState) -> dict`。返回字典中的 `_trace`（dict）与 `_status`（str）为**装饰器私有约定**，会被 pop 掉，不进入 State。
  - `on_error="abort"` ⇒ 异常时返回 `{"error": str, "exit_code": 2}`。
  - `on_error="degrade"` ⇒ 异常时返回 `{"messages": [警告文本]}`，不写 `error`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_graph_nodes.py`：

```python
import json

from src.agent.graph.nodes import traced_node
from src.agent.trace.tracer import Tracer


def _entries(tracer):
    return [json.loads(l) for l in
            tracer.file.read_text(encoding="utf-8").strip().splitlines()]


def test_traced_node_logs_ok_and_strips_private_keys(tmp_path):
    tracer = Tracer(tmp_path)

    @traced_node("demo")
    def node(state):
        return {"foo": 1, "_trace": {"rows": 3}}

    out = node({"tracer": tracer})
    assert out == {"foo": 1}                 # _trace 已被剥离，不污染 State
    entry = _entries(tracer)[0]
    assert entry["step"] == "demo"
    assert entry["status"] == "ok"
    assert entry["detail"]["rows"] == 3
    assert isinstance(entry["detail"]["elapsed_ms"], int)


def test_traced_node_honours_custom_status(tmp_path):
    tracer = Tracer(tmp_path)

    @traced_node("attribute")
    def node(state):
        return {"_status": "skip", "_trace": {"reason": "无异常"}}

    out = node({"tracer": tracer})
    assert out == {}
    entry = _entries(tracer)[0]
    assert entry["status"] == "skip"
    assert entry["detail"]["reason"] == "无异常"


def test_traced_node_abort_writes_error_and_exit_code(tmp_path):
    tracer = Tracer(tmp_path)

    @traced_node("demo", on_error="abort")
    def node(state):
        raise RuntimeError("boom")

    out = node({"tracer": tracer})
    assert out["exit_code"] == 2
    assert "boom" in out["error"]
    entry = _entries(tracer)[0]
    assert entry["status"] == "fail"
    assert "boom" in entry["detail"]["error"]


def test_traced_node_degrade_does_not_abort(tmp_path):
    tracer = Tracer(tmp_path)

    @traced_node("demo", on_error="degrade")
    def node(state):
        raise RuntimeError("boom")

    out = node({"tracer": tracer})
    assert "error" not in out
    assert "exit_code" not in out
    assert len(out["messages"]) == 1 and "boom" in out["messages"][0]
    assert _entries(tracer)[0]["status"] == "fail"


def test_traced_node_without_tracer_does_not_crash():
    """load_config 自身运行时 State 里还没有 tracer。"""

    @traced_node("config")
    def node(state):
        return {"ok": True}

    assert node({}) == {"ok": True}


def test_traced_node_uses_tracer_returned_by_the_node_itself(tmp_path):
    """load_config 在自己内部创建 Tracer，装饰器要能用上它记录自己这条。"""
    made = Tracer(tmp_path)

    @traced_node("config")
    def node(state):
        return {"tracer": made, "_trace": {"provider": "mock"}}

    node({})
    assert _entries(made)[0]["detail"]["provider"] == "mock"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_nodes.py -v
```

Expected: FAIL — `ImportError: cannot import name 'traced_node'`

- [ ] **Step 3: 实现装饰器**

创建 `src/agent/graph/nodes.py`：

```python
"""编排层节点实现。

每个节点是 (state: AgentState) -> dict 的纯函数，返回"局部更新"由 LangGraph 合并。
不依赖 LangGraph 运行时，因此可以脱离图单独单测。
"""
import functools
import time
import traceback


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
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_nodes.py -v
```

Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add src/agent/graph/nodes.py tests/test_graph_nodes.py
git commit -m "feat: 新增 @traced_node 装饰器，实现逐节点自动追踪与分级容错"
```

---

### Task 3: load_config 节点

**Files:**
- Modify: `src/agent/graph/nodes.py`（追加）
- Test: `tests/test_graph_nodes.py`（追加）

**Interfaces:**
- Consumes: `traced_node`（Task 2）；`src.agent.config` 的 `PROJECT_ROOT` / `load_settings` / `load_field_mapping` / `resolve_api_key`；`src.agent.trace.tracer.Tracer`；`src.agent.engine.ValidationEngine`；`src.agent.llm.client` 的 `MockLLMClient` / `OpenAICompatClient`；四条规则类。
- Produces:
  - `build_engine() -> ValidationEngine` —— 从 `main.py:37-43` 原样搬运。
  - `build_llm_client(settings: dict, use_mock: bool) -> LLMClient | None` —— 从 `main.py:46-56` 搬运并去掉下划线前缀（跨模块使用）。
  - `load_config(state) -> dict` —— 写 `settings` `field_mapping` `tracer` `engine` `llm_client`。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_graph_nodes.py`：

```python
from src.agent.graph.nodes import build_engine, build_llm_client, load_config
from src.agent.llm.client import MockLLMClient


def test_build_engine_registers_four_rules():
    engine = build_engine()
    assert [r.rule_id for r in engine.rules] == ["R1", "R2", "R3", "R4"]


def test_build_llm_client_returns_mock_when_use_mock():
    client = build_llm_client({"llm": {"provider": "openai-compatible"}}, True)
    assert isinstance(client, MockLLMClient)


def test_build_llm_client_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    settings = {"llm": {"provider": "openai-compatible", "api_key": "",
                        "base_url": "http://x", "model": "m"}}
    assert build_llm_client(settings, False) is None


def test_load_config_populates_runtime_handles(tmp_path):
    out = load_config({"trace_dir": str(tmp_path), "use_mock": True})
    assert out["settings"]["llm"]["provider"]
    # load_field_mapping 返回原始 YAML，顶层键是 report_types
    assert "订单号" in out["field_mapping"]["report_types"]["补投日报"]
    assert out["tracer"].file.exists()
    assert [r.rule_id for r in out["engine"].rules] == ["R1", "R2", "R3", "R4"]
    assert isinstance(out["llm_client"], MockLLMClient)


def test_load_config_writes_its_own_trace_entry(tmp_path):
    out = load_config({"trace_dir": str(tmp_path), "use_mock": True})
    entry = _entries(out["tracer"])[0]
    assert entry["step"] == "config" and entry["status"] == "ok"
    assert entry["detail"]["llm_ready"] is True
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_nodes.py -v -k "build_engine or build_llm or load_config"
```

Expected: FAIL — `ImportError: cannot import name 'build_engine'`

- [ ] **Step 3: 实现**

在 `src/agent/graph/nodes.py` 顶部补充 import：

```python
from pathlib import Path

from ..config import (PROJECT_ROOT, load_field_mapping, load_settings,
                      resolve_api_key)
from ..engine import ValidationEngine
from ..llm.client import MockLLMClient, OpenAICompatClient
from ..rules.replenish import RuleR2AfterBatch, RuleR3DuplicateReplenish
from ..rules.scrap import RuleR4ScrapWithOnlineBoards
from ..rules.warehouse_in import RuleR1WarehouseIn
from ..trace.tracer import Tracer
```

在 `traced_node` 之后追加：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_nodes.py -v
```

Expected: 11 passed

- [ ] **Step 5: 提交**

```bash
git add src/agent/graph/nodes.py tests/test_graph_nodes.py
git commit -m "feat: 新增 load_config 节点，集中构建配置/Tracer/引擎/LLM客户端"
```

---

### Task 4: parse_file 与 parse_factory 节点

两个节点是姊妹关系，共用同一套错误契约（`error` + `exit_code=2` + `_status="fail"`），放同一任务实现。

**Files:**
- Modify: `src/agent/graph/nodes.py`（追加）
- Test: `tests/test_graph_parse_nodes.py`

**Interfaces:**
- Consumes: `traced_node`；`src.agent.parsers.report_parser` 的 `ReportParser` / `ReportParseError` / `build_product_order_index` / `filter_order_by_products`；`src.agent.data_loader` 的 `discover_files` / `normalize_factory`；`src.agent.history_scrap.build_history_index`。
- Produces:
  - `parse_file(state) -> dict` —— 写 `report` `factory` `order_df=None` `hist_index={}`，或 `error`+`exit_code=2`。
  - `parse_factory(state) -> dict` —— 写 `report`（含 `product_order_index`）`order_df` `hist_index` `messages`，或 `error`+`exit_code=2`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_graph_parse_nodes.py`：

```python
from pathlib import Path

import pandas as pd
import pytest

from src.agent.config import load_field_mapping
from src.agent.graph.nodes import parse_factory, parse_file
from src.agent.trace.tracer import Tracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = PROJECT_ROOT / "data" / "samples" / "综合日报.csv"


@pytest.fixture
def base_state(tmp_path):
    return {"field_mapping": load_field_mapping(),
            "tracer": Tracer(tmp_path),
            "report_type": "综合日报"}


def test_parse_file_produces_report_and_empty_join_inputs(base_state):
    state = {**base_state, "file_path": str(SAMPLE), "factory": "珠海一厂"}
    out = parse_file(state)
    assert out["report"].factory == "珠海一厂"
    assert len(out["report"].df) > 0
    assert out["order_df"] is None
    assert out["hist_index"] == {}
    assert "error" not in out


def test_parse_file_defaults_factory_to_test(base_state):
    """--file 模式未给 --工厂 时缺省为 "测试"（对齐 main.py 旧行为）。"""
    out = parse_file({**base_state, "file_path": str(SAMPLE), "factory": None})
    assert out["factory"] == "测试"
    assert out["report"].factory == "测试"


def test_parse_file_reports_error_without_aborting_process(base_state, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("备注\nxxx\n", encoding="utf-8-sig")
    out = parse_file({**base_state, "file_path": str(bad), "factory": "珠海一厂"})
    assert out["exit_code"] == 2
    assert "无法识别订单号字段" in out["error"]
    assert "report" not in out


def test_parse_factory_requires_factory_name(base_state):
    out = parse_factory({**base_state, "factory": None})
    assert out["exit_code"] == 2
    assert "必须提供 --工厂" in out["error"]


def test_parse_factory_errors_when_no_replenish_file(base_state, tmp_path, monkeypatch):
    """补投文件缺失是硬错误（对齐 main.py:104-106）。"""
    import src.agent.graph.nodes as nodes
    monkeypatch.setattr(nodes, "discover_files",
                        lambda *a, **k: {"补投": None, "订单": None, "报废": None})
    out = parse_factory({**base_state, "factory": "金州厂"})
    assert out["exit_code"] == 2
    assert "未找到补投明细表文件" in out["error"]
    assert any("未找到订单文件" in m for m in out["messages"])


def test_parse_factory_warns_but_proceeds_without_order_file(
        base_state, tmp_path, monkeypatch):
    """订单文件缺失只是警告，主流程照走（左连接不丢主表行的精神）。"""
    import src.agent.graph.nodes as nodes
    bt = tmp_path / "bt.xlsx"
    pd.DataFrame({"销售单号": ["SO-1.1"], "补料类别": ["成品"],
                  "补投数": [10]}).to_excel(bt, index=False)
    monkeypatch.setattr(nodes, "discover_files",
                        lambda *a, **k: {"补投": str(bt), "订单": None, "报废": None})
    out = parse_factory({**base_state, "factory": "金州厂",
                         "report_type": "补投日报"})
    assert "error" not in out
    assert out["order_df"] is None
    assert out["hist_index"] == {}
    assert out["report"].product_order_index == {}
    assert any("未找到订单文件" in m for m in out["messages"])
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_parse_nodes.py -v
```

Expected: FAIL — `ImportError: cannot import name 'parse_file'`

- [ ] **Step 3: 实现**

在 `src/agent/graph/nodes.py` 顶部补充 import：

```python
import pandas as pd

from ..data_loader import discover_files, normalize_factory
from ..history_scrap import build_history_index
from ..parsers.report_parser import (ReportParseError, ReportParser,
                                     build_product_order_index,
                                     filter_order_by_products)
```

追加节点：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_parse_nodes.py -v
```

Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add src/agent/graph/nodes.py tests/test_graph_parse_nodes.py
git commit -m "feat: 新增 parse_file / parse_factory 双模式解析节点"
```

---

### Task 5: enrich 与 validate 节点

**Files:**
- Modify: `src/agent/graph/nodes.py`（追加）
- Test: `tests/test_graph_pipeline_nodes.py`

**Interfaces:**
- Consumes: `traced_node`；`src.agent.data_loader.join_order_info`；`src.agent.history_scrap` 的 `match_history_columns` / `enrich_anomalies_with_metrics`。
- Produces:
  - `enrich(state) -> dict` —— 写 `report`（df 已关联）。
  - `validate(state) -> dict` —— 写 `anomalies` `rule_errors`。

**关键语义（spec §7 评审确认）**：`enrich` 中"匹配不到历史数据/订单信息"是**正常业务场景**——留空即可，不抛异常、不 abort。只有匹配过程本身抛异常才走 abort。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_graph_pipeline_nodes.py`：

```python
import json

import pandas as pd
import pytest

from src.agent.graph.nodes import enrich, validate
from src.agent.rules.base import RulePlugin
from src.agent.schema import Anomaly, StandardReport
from src.agent.trace.tracer import Tracer


def _report(df=None, quality_issues=None):
    return StandardReport(
        report_type="综合日报", factory="测试", source_path="x",
        df=df if df is not None else pd.DataFrame(
            {"订单号": ["SO-1"], "_行号": [1], "入库数": [0],
             "在线数": [0], "已产出数": [0], "需求数": [0], "报废数": [0]}),
        quality_issues=quality_issues or [])


def test_enrich_is_noop_when_no_order_and_no_hist(tmp_path):
    """测试模式：order_df=None、hist_index={} —— 正常通过，不写 error。"""
    rep = _report()
    before = rep.df.copy()
    out = enrich({"report": rep, "order_df": None, "hist_index": {},
                  "tracer": Tracer(tmp_path)})
    assert "error" not in out
    pd.testing.assert_frame_equal(out["report"].df, before)


def test_enrich_is_noop_when_order_df_is_empty(tmp_path):
    """订单表存在但过滤后为空，属正常业务场景，不得报错。"""
    out = enrich({"report": _report(), "order_df": pd.DataFrame(),
                  "hist_index": {}, "tracer": Tracer(tmp_path)})
    assert "error" not in out


def test_enrich_aborts_when_join_itself_raises(tmp_path, monkeypatch):
    """匹配过程本身出错才 abort。"""
    import src.agent.graph.nodes as nodes

    def boom(*a, **k):
        raise ValueError("join 崩了")

    monkeypatch.setattr(nodes, "join_order_info", boom)
    out = enrich({"report": _report(), "order_df": pd.DataFrame({"a": [1]}),
                  "hist_index": {}, "tracer": Tracer(tmp_path)})
    assert out["exit_code"] == 2
    assert "join 崩了" in out["error"]


class _BoomRule(RulePlugin):
    rule_id = "RX"
    rule_name = "会炸的规则"

    def validate(self, report):
        raise RuntimeError("规则内部错误")


def test_validate_merges_quality_issues_and_rule_anomalies(tmp_path):
    from src.agent.graph.nodes import build_engine
    d0 = Anomaly(rule_id="D0", rule_name="数据质量", factory="测试",
                 order_id="SO-1", description="缺订单号")
    out = validate({"report": _report(quality_issues=[d0]),
                    "engine": build_engine(), "tracer": Tracer(tmp_path)})
    assert out["anomalies"][0].rule_id == "D0"
    assert out["rule_errors"] == []


def test_validate_isolates_failing_rule_and_traces_it(tmp_path):
    from src.agent.engine import ValidationEngine
    tracer = Tracer(tmp_path)
    engine = ValidationEngine()
    engine.register(_BoomRule())
    out = validate({"report": _report(), "engine": engine, "tracer": tracer})
    assert "error" not in out              # 单条规则失败不中断流程
    assert out["rule_errors"][0]["rule_id"] == "RX"
    entries = [json.loads(l) for l in
               tracer.file.read_text(encoding="utf-8").strip().splitlines()]
    assert any(e["step"] == "validate" and e["status"] == "fail" for e in entries)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_pipeline_nodes.py -v
```

Expected: FAIL — `ImportError: cannot import name 'enrich'`

- [ ] **Step 3: 实现**

补充 import：

```python
from ..data_loader import join_order_info
from ..history_scrap import enrich_anomalies_with_metrics, match_history_columns
```

追加节点：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_pipeline_nodes.py -v
```

Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add src/agent/graph/nodes.py tests/test_graph_pipeline_nodes.py
git commit -m "feat: 新增 enrich 与 validate 节点，区分业务留空与真实故障"
```

---

### Task 6: attribute 与 attribute_skipped 节点

**Files:**
- Modify: `src/agent/graph/nodes.py`（追加）
- Test: `tests/test_graph_attribute_nodes.py`

**Interfaces:**
- Consumes: `traced_node`；`src.agent.llm.attribution.attribute_anomalies`；`src.agent.llm.knowledge` 的 `retrieve_knowledge` / `B_BASE_URL` / `B_TIMEOUT_SECONDS`。
- Produces:
  - `attribute(state) -> dict` —— 写 `attributions`。`on_error="degrade"`。
  - `attribute_skipped(state) -> dict` —— 写 `attributions=[]` `skip_reason` `messages`，trace 状态为 `"skip"`。

**为什么 `attribute_skipped` 必须是真节点**：`tests/test_cli_e2e.py:43` 断言 trace 含 `attribute` step。若跳过归因时什么都不记，"异常数为 0"的场景会让该断言失败。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_graph_attribute_nodes.py`：

```python
import json

from src.agent.graph.nodes import attribute, attribute_skipped
from src.agent.llm.client import MockLLMClient
from src.agent.schema import Anomaly
from src.agent.trace.tracer import Tracer

SKIP_WARNING = "[警告] 未配置API密钥，跳过LLM归因（报告仅含规则判定与证据）"


def _anomaly():
    return Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="测试",
                   order_id="SO-1", description="在线有板仍入库",
                   evidence={"在线数": 10, "需求数": 20})


def _entries(tracer):
    return [json.loads(l) for l in
            tracer.file.read_text(encoding="utf-8").strip().splitlines()]


def test_attribute_produces_attributions_with_mock_client(tmp_path):
    out = attribute({"anomalies": [_anomaly()], "llm_client": MockLLMClient(),
                     "settings": {"knowledge": {"base_url": "http://127.0.0.1:9",
                                                "timeout_seconds": 0.01}},
                     "tracer": Tracer(tmp_path)})
    assert len(out["attributions"]) == 1
    assert "error" not in out


def test_attribute_degrades_instead_of_aborting(tmp_path, monkeypatch):
    """归因崩了不能拖垮主流程（决策记录#4）。"""
    import src.agent.graph.nodes as nodes

    def boom(*a, **k):
        raise RuntimeError("DeepSeek 挂了")

    monkeypatch.setattr(nodes, "attribute_anomalies", boom)
    tracer = Tracer(tmp_path)
    out = attribute({"anomalies": [_anomaly()], "llm_client": MockLLMClient(),
                     "settings": {}, "tracer": tracer})
    assert "error" not in out and "exit_code" not in out
    assert any("DeepSeek 挂了" in m for m in out["messages"])
    assert _entries(tracer)[0]["status"] == "fail"


def test_attribute_skipped_no_anomalies(tmp_path):
    tracer = Tracer(tmp_path)
    out = attribute_skipped({"anomalies": [], "llm_client": None,
                             "tracer": tracer})
    assert out["attributions"] == []
    assert out["skip_reason"] == "无异常"
    assert out["messages"] == []
    entry = _entries(tracer)[0]
    assert entry["step"] == "attribute" and entry["status"] == "skip"


def test_attribute_skipped_no_api_key_emits_legacy_warning(tmp_path):
    """警告文案必须与旧 main.py:160 逐字一致，gui.py 的日志框依赖它。"""
    tracer = Tracer(tmp_path)
    out = attribute_skipped({"anomalies": [_anomaly()], "llm_client": None,
                             "tracer": tracer})
    assert out["skip_reason"] == "无API密钥"
    assert out["messages"] == [SKIP_WARNING]
    assert _entries(tracer)[0]["detail"]["reason"] == "无API密钥"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_attribute_nodes.py -v
```

Expected: FAIL — `ImportError: cannot import name 'attribute'`

- [ ] **Step 3: 实现**

补充 import：

```python
from ..llm.attribution import attribute_anomalies
from ..llm.knowledge import B_BASE_URL, B_TIMEOUT_SECONDS, retrieve_knowledge
```

追加节点：

```python
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
        timeout=float(kb.get("timeout_seconds", B_TIMEOUT_SECONDS)))
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
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_attribute_nodes.py -v
```

Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/agent/graph/nodes.py tests/test_graph_attribute_nodes.py
git commit -m "feat: 新增 attribute 与 attribute_skipped 节点，跳过归因也留痕"
```

---

### Task 7: write_report 节点

**Files:**
- Modify: `src/agent/graph/nodes.py`（追加）
- Test: `tests/test_graph_report_node.py`

**Interfaces:**
- Consumes: `traced_node`；`src.agent.reporting.report_writer` 的 `write_excel_report` / `write_markdown_summary`。
- Produces: `write_report(state) -> dict` —— 写 `excel_path` `md_path` `exit_code=0`。

**防御性读取**：`attribute` 节点在 degrade 失败时**不会**返回 `attributions` 键，所以这里必须用 `state.get("attributions") or []`，不能用 `state["attributions"]`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_graph_report_node.py`：

```python
import pandas as pd

from src.agent.graph.nodes import write_report
from src.agent.schema import Anomaly, StandardReport
from src.agent.trace.tracer import Tracer


def _state(tmp_path, **over):
    rep = StandardReport(
        report_type="综合日报", factory="测试", source_path="x",
        df=pd.DataFrame({"订单号": ["SO-1"], "_行号": [1], "客户": ["甲"]}))
    base = {"report": rep, "factory": "测试",
            "anomalies": [Anomaly(rule_id="R1", rule_name="违规入余数仓",
                                  factory="测试", order_id="SO-1",
                                  description="d", evidence={"行号": [1]})],
            "attributions": [], "settings": {"output": {"dir": "output"}},
            "output_dir": str(tmp_path / "out"), "tracer": Tracer(tmp_path)}
    base.update(over)
    return base


def test_write_report_produces_both_files_and_exit_zero(tmp_path):
    out = write_report(_state(tmp_path))
    assert out["exit_code"] == 0
    assert out["excel_path"].endswith(".xlsx")
    assert out["md_path"].endswith(".md")
    files = list((tmp_path / "out").iterdir())
    assert len(files) == 2


def test_write_report_survives_missing_attributions_key(tmp_path):
    """attribute 节点 degrade 失败时不返回 attributions，这里不能 KeyError。"""
    state = _state(tmp_path)
    state.pop("attributions")
    out = write_report(state)
    assert out["exit_code"] == 0


def test_write_report_keeps_customer_column_unmasked(tmp_path):
    """脱敏已移出本次范围（spec §12.1）：全量明细里客户名保持原文。"""
    out = write_report(_state(tmp_path))
    full = pd.read_excel(out["excel_path"], sheet_name="全量明细")
    assert full.loc[0, "客户"] == "甲"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_report_node.py -v
```

Expected: FAIL — `ImportError: cannot import name 'write_report'`

- [ ] **Step 3: 实现**

补充 import：

```python
from ..reporting.report_writer import write_excel_report, write_markdown_summary
```

追加节点：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_report_node.py -v
```

Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add src/agent/graph/nodes.py tests/test_graph_report_node.py
git commit -m "feat: 新增 write_report 节点"
```

---

### Task 8: 路由函数

条件分支的核心。这是本次重构唯一的新行为，测试要压在这里。

**Files:**
- Modify: `src/agent/graph/nodes.py`（追加）
- Test: `tests/test_graph_routes.py`

**Interfaces:**
- Consumes: `langgraph.graph.END`
- Produces:
  - `route_mode(state) -> str` —— `END` / `"parse_file"` / `"parse_factory"`
  - `route_after_parse(state) -> str` —— `END` / `"enrich"`
  - `route_after_validate(state) -> str` —— `END` / `"attribute"` / `"attribute_skipped"`
  - `guard(next_node: str) -> Callable[[dict], str]` —— 纯错误短路边的工厂

- [ ] **Step 1: 写失败测试**

创建 `tests/test_graph_routes.py`：

```python
from langgraph.graph import END

from src.agent.graph.nodes import (guard, route_after_parse,
                                   route_after_validate, route_mode)


# ── route_mode：双模式加载分支 + 配置失败短路 ──
def test_route_mode_picks_file_branch():
    assert route_mode({"file_path": "a.xlsx"}) == "parse_file"


def test_route_mode_picks_factory_branch():
    assert route_mode({"file_path": None, "factory": "金州厂"}) == "parse_factory"


def test_route_mode_short_circuits_on_config_error():
    assert route_mode({"error": "配置炸了", "file_path": "a.xlsx"}) == END


# ── route_after_parse：解析失败短路 ──
def test_route_after_parse_continues_to_enrich():
    assert route_after_parse({"report": object()}) == "enrich"


def test_route_after_parse_short_circuits_on_error():
    assert route_after_parse({"error": "无法识别订单号字段"}) == END


# ── route_after_validate：数据驱动分支 + 降级分支 ──
def test_route_after_validate_skips_when_no_anomalies():
    assert route_after_validate(
        {"anomalies": [], "llm_client": object()}) == "attribute_skipped"


def test_route_after_validate_skips_when_no_llm_client():
    assert route_after_validate(
        {"anomalies": [object()], "llm_client": None}) == "attribute_skipped"


def test_route_after_validate_attributes_normally():
    assert route_after_validate(
        {"anomalies": [object()], "llm_client": object()}) == "attribute"


def test_route_after_validate_short_circuits_on_error():
    assert route_after_validate(
        {"error": "校验炸了", "anomalies": [object()],
         "llm_client": object()}) == END


# ── guard 工厂 ──
def test_guard_passes_through_when_clean():
    assert guard("validate")({}) == "validate"


def test_guard_returns_end_on_error():
    assert guard("validate")({"error": "boom"}) == END
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_routes.py -v
```

Expected: FAIL — `ImportError: cannot import name 'guard'`

- [ ] **Step 3: 实现**

补充 import：

```python
from langgraph.graph import END
```

追加路由函数：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_routes.py -v
```

Expected: 11 passed

- [ ] **Step 5: 提交**

```bash
git add src/agent/graph/nodes.py tests/test_graph_routes.py
git commit -m "feat: 新增 3 个路由函数与 guard 工厂，条件分支显式化"
```

---

### Task 9: 图装配 build_graph

**Files:**
- Create: `src/agent/graph/builder.py`
- Modify: `src/agent/graph/__init__.py`
- Test: `tests/test_graph_builder.py`

**Interfaces:**
- Consumes: Task 1 的 `AgentState`；Task 3–8 的 8 个节点与 4 个路由函数。
- Produces: `build_graph() -> CompiledStateGraph`，可通过 `from src.agent.graph import build_graph` 导入。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_graph_builder.py`：

```python
from pathlib import Path

import pandas as pd
import pytest

from src.agent.graph import build_graph

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = PROJECT_ROOT / "data" / "samples" / "综合日报.csv"

EXPECTED_NODES = {"load_config", "parse_file", "parse_factory", "enrich",
                  "validate", "attribute", "attribute_skipped", "write_report"}


def _initial(tmp_path, **over):
    state = {"factory": "珠海一厂", "report_type": "综合日报",
             "file_path": str(SAMPLE), "sheet": None,
             "bt_files": None, "order_files": None, "hist_files": None,
             "output_dir": str(tmp_path / "out"),
             "trace_dir": str(tmp_path / "traces"),
             "use_mock": True, "messages": []}
    state.update(over)
    return state


def test_graph_compiles_with_all_nodes():
    graph = build_graph()
    assert EXPECTED_NODES <= set(graph.get_graph().nodes)


def test_full_run_with_mock_llm_produces_report(tmp_path):
    final = build_graph().invoke(_initial(tmp_path))
    assert final["exit_code"] == 0
    assert final.get("error") is None
    assert len(final["anomalies"]) == 3
    assert Path(final["excel_path"]).exists()
    assert Path(final["md_path"]).exists()


def test_trace_contains_four_contract_steps(tmp_path):
    """守住 tests/test_cli_e2e.py:43 的契约。"""
    import json
    build_graph().invoke(_initial(tmp_path))
    trace = next((tmp_path / "traces").glob("trace_*.jsonl"))
    steps = {json.loads(l)["step"]
             for l in trace.read_text(encoding="utf-8").strip().splitlines()}
    assert {"parse", "validate", "attribute", "report"} <= steps


def test_degraded_run_without_llm_client_still_reports(tmp_path, monkeypatch):
    """降级分支全图验证：无密钥 ⇒ 跳过归因，但报告照出、退出码仍为 0。"""
    import src.agent.graph.nodes as nodes
    monkeypatch.setattr(nodes, "build_llm_client", lambda settings, use_mock: None)

    final = build_graph().invoke(_initial(tmp_path, use_mock=False))
    assert final["exit_code"] == 0
    assert final["attributions"] == []
    assert final["skip_reason"] == "无API密钥"
    assert Path(final["excel_path"]).exists()


def test_parse_error_short_circuits_to_end(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("备注\nxxx\n", encoding="utf-8-sig")
    final = build_graph().invoke(_initial(tmp_path, file_path=str(bad)))
    assert final["exit_code"] == 2
    assert "无法识别订单号字段" in final["error"]
    assert "excel_path" not in final          # 没有走到 write_report
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_builder.py -v
```

Expected: FAIL — `ImportError: cannot import name 'build_graph'`

- [ ] **Step 3: 实现 builder.py**

创建 `src/agent/graph/builder.py`：

```python
"""图装配：把节点与条件边连成执行图。

图为无环 DAG，无 checkpointer（不做 HITL），因此不存在递归超限风险。
"""
from langgraph.graph import END, START, StateGraph

from .nodes import (attribute, attribute_skipped, enrich, guard, load_config,
                    parse_factory, parse_file, route_after_parse,
                    route_after_validate, route_mode, validate, write_report)
from .state import AgentState


def build_graph():
    b = StateGraph(AgentState)

    b.add_node("load_config", load_config)
    b.add_node("parse_file", parse_file)
    b.add_node("parse_factory", parse_factory)
    b.add_node("enrich", enrich)
    b.add_node("validate", validate)
    b.add_node("attribute", attribute)
    b.add_node("attribute_skipped", attribute_skipped)
    b.add_node("write_report", write_report)

    b.add_edge(START, "load_config")
    # 双模式加载分支（配置失败则短路）
    b.add_conditional_edges("load_config", route_mode,
                            ["parse_file", "parse_factory", END])
    # 解析失败短路
    b.add_conditional_edges("parse_file", route_after_parse, ["enrich", END])
    b.add_conditional_edges("parse_factory", route_after_parse, ["enrich", END])
    b.add_conditional_edges("enrich", guard("validate"), ["validate", END])
    # 数据驱动分支 + 降级分支
    b.add_conditional_edges("validate", route_after_validate,
                            ["attribute", "attribute_skipped", END])
    # attribute / attribute_skipped 都是 degrade，不会写 error，直连即可
    b.add_edge("attribute", "write_report")
    b.add_edge("attribute_skipped", "write_report")
    b.add_edge("write_report", END)

    return b.compile()
```

改写 `src/agent/graph/__init__.py`：

```python
"""LangGraph 编排层：State 定义、节点实现与图装配。"""
from .builder import build_graph
from .state import AgentState

__all__ = ["AgentState", "build_graph"]
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_graph_builder.py -v
```

Expected: 5 passed

若 `test_full_run_with_mock_llm_produces_report` 的 `len(final["anomalies"]) == 3` 失败，
对照 `tests/test_cli_e2e.py:27` 的 `"异常 3"`——这是同一份样例数据的同一个数字，
不一致说明节点搬运时漏了逻辑，回到 Task 4/5 排查，**不要改这个断言**。

- [ ] **Step 5: 提交**

```bash
git add src/agent/graph/builder.py src/agent/graph/__init__.py tests/test_graph_builder.py
git commit -m "feat: 装配 LangGraph 执行图，打通全链路与降级分支"
```

---

### Task 10: main.py 瘦身为 CLI 壳

**Files:**
- Modify: `D:\Python\Claude Code\Programs\PCB生产预投业务数据校验Agent\main.py`（整体替换 `main()` 与 import 区）
- Test: 复用现有 `tests/test_cli_e2e.py`（不改）

**Interfaces:**
- Consumes: `src.agent.graph.build_graph`；`src.agent.llm.rag_monitor.monitor`；`src.agent.schema.REPORT_TYPES`
- Produces: `main(argv=None) -> int`，CLI 契约与改造前完全一致。

**注意**：`build_engine` 与 `_build_llm_client` 已迁到 `nodes.py`（Task 3），`main.py` 中的旧定义要删除。`sys.stdout.reconfigure(encoding="utf-8")` 必须保留（踩坑记录#10）。

- [ ] **Step 1: 先跑一次 e2e 测试，确认改造前是绿的**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_cli_e2e.py -v
```

Expected: 2 passed。这是本任务的"改造前"参照。

- [ ] **Step 2: 改写 main.py**

把 `main.py` 全文替换为：

```python
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
```

- [ ] **Step 3: 跑 e2e 测试确认契约未破**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest tests/test_cli_e2e.py -v
```

Expected: 2 passed

**若 `test_cli_end_to_end_full_pipeline` 失败**，按断言逐条对照：
`returncode == 0` → 检查 `_finish` 的返回值；`"校验完成" in stdout` 与 `"异常 3" in stdout` → 检查
`_finish` 的打印格式；trace 四个 step → 检查 `@traced_node` 的 step 名。
**任何情况下都不要修改 `tests/test_cli_e2e.py`。**

- [ ] **Step 4: 手工验证 stdout 进度可见**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" main.py --file "data/samples/综合日报.csv" --工厂 珠海一厂 --类型 综合日报 --mock-llm --输出目录 baseline/smoke --trace-dir baseline/smoke_traces
```

Expected: 依次出现 `→ 加载配置`、`→ 解析报表（测试模式）`、`→ 多表关联与指标补齐`、
`→ 规则校验`、`→ LLM归因`、`→ 生成报告`，然后是"校验完成"那几行。

- [ ] **Step 5: 提交**

```bash
git add main.py
git commit -m "refactor: main.py 瘦身为 CLI 壳，流程编排交给 LangGraph 图"
```

---

### Task 11: 全量回归与等价性验收

证明"结构变了、行为没变"。

**Files:**
- 无新增；仅运行与比对

**Interfaces:**
- Consumes: Task 0 产出的 `baseline/pytest_before.txt` 与 `baseline/before/` 下的旧版报告
- Produces: 验收结论（通过 / 不通过 + 差异清单）

- [ ] **Step 1: 全量测试**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -m pytest -q 2>&1 | tail -5
```

Expected: **102 passed** = 原有 50 + Task 0 的 3 + 新增 graph 测试 49
（state 3 + 装饰器 6 + load_config 5 + parse 6 + pipeline 6 + attribute 4 + report 3 + routes 11 + builder 5）。

若 Task 0 Step 5 记录的原有基线不是 50，按实际数字加总。

关键是**原有 50 个用例全绿且一个都没改过**。用下面这条确认那 16 个测试文件未被篡改
（与仓库首个提交——即 Task 0 之前的基线——比对，不依赖中间提交个数）：

```bash
git diff "$(git rev-list --max-parents=0 HEAD)" --stat -- \
  tests/test_after_batch.py tests/test_cli_e2e.py tests/test_config.py \
  tests/test_data_loader.py tests/test_engine.py tests/test_history_scrap.py \
  tests/test_knowledge.py tests/test_llm.py tests/test_parser.py \
  tests/test_product_order_index.py tests/test_report_writer.py \
  tests/test_rule_r1.py tests/test_rule_r2_r3.py tests/test_rule_r4.py \
  tests/test_schema.py tests/test_tracer.py
```

Expected: 无输出（这 16 个文件零改动）。有任何输出都说明动了既有测试，必须回滚那部分改动。

- [ ] **Step 2: 用真实数据跑新版**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" main.py --工厂 金州厂 --输出目录 baseline/after --trace-dir baseline/traces_after
```

Expected: 退出码 0，`baseline/after/` 下生成报告。

- [ ] **Step 3: 等价性比对**

创建并运行 `baseline/compare.py`：

```python
"""比对重构前后两版报告的异常明细是否等价。

只比对确定性部分（异常行数、规则编号分布、订单号集合）——
归因列由 LLM 生成，两次运行本就不会逐字相同，不参与比对。
"""
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent


def load(sub):
    files = sorted((BASE / sub).glob("异常校验报告_*.xlsx"))
    if not files:
        sys.exit(f"[错误] {sub} 下没有找到报告文件")
    return pd.read_excel(files[-1], sheet_name="异常明细")


before, after = load("before"), load("after")

checks = {
    "异常总行数": (len(before), len(after)),
    "规则编号分布": (Counter(before["规则编号"]), Counter(after["规则编号"])),
    "订单号集合": (set(before["订单号"]), set(after["订单号"])),
    "工厂分布": (Counter(before["工厂"]), Counter(after["工厂"])),
}

failed = False
for name, (b, a) in checks.items():
    ok = b == a
    failed |= not ok
    print(f"{'OK  ' if ok else 'DIFF'} {name}")
    if not ok:
        print(f"     旧: {b}")
        print(f"     新: {a}")

print("\n等价性验收：" + ("不通过" if failed else "通过"))
sys.exit(1 if failed else 0)
```

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" baseline/compare.py
```

Expected: 四项全部 `OK`，末行"等价性验收：通过"。

**任何一项 DIFF 都是重构引入的行为变更，必须定位到具体节点并修复——不要调整比对脚本来让它通过。**

- [ ] **Step 4: 确认 trace 变得更细**

```bash
PYTHONIOENCODING=utf-8 ".venv/Scripts/python.exe" -c "
import json, pathlib
f = sorted(pathlib.Path('baseline/traces_after').glob('trace_*.jsonl'))[-1]
for line in f.read_text(encoding='utf-8').strip().splitlines():
    e = json.loads(line)
    print(f\"{e['step']:12} {e['status']:5} {e['detail'].get('elapsed_ms','-'):>6}ms\")
"
```

Expected: 按顺序打印 `config` / `parse` / `enrich` / `validate` / `attribute` / `report`，每行带耗时。
这就是本次重构在可观测性上的交付物——对照旧版只有 4 条手写日志、且没有耗时。

- [ ] **Step 5: 提交并打标签**

```bash
git add -A
git commit -m "test: 完成 LangGraph 重构的全量回归与等价性验收"
git tag langgraph-refactor-done
```

---

## 附录：完成后的图结构

```
START → load_config ──route_mode──┬→ parse_file    ─┐
                                  └→ parse_factory ─┴─route_after_parse─┬→ END (error, exit=2)
                                                                        └→ enrich → validate

validate ──route_after_validate──┬→ attribute          (有异常 且 llm_client 非 None)
                                 └→ attribute_skipped  (无异常 或 无密钥)

attribute ─────────┐
                   ├→ write_report → END (exit=0)
attribute_skipped ─┘
```

trace step 与节点名的映射（step 名刻意与节点名解耦，以守住 e2e 契约）：

| 节点 | trace step | on_error |
|---|---|---|
| `load_config` | `config` | abort |
| `parse_file` / `parse_factory` | `parse` | abort |
| `enrich` | `enrich` | abort |
| `validate` | `validate` | abort |
| `attribute` / `attribute_skipped` | `attribute` | degrade |
| `write_report` | `report` | abort |
