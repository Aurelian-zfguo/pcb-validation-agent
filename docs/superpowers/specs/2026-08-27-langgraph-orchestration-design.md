# LangGraph 流程编排重构设计

日期：2026-08-27
范围：项目 A（PCB生产预投业务数据校验Agent）的编排层
状态：待实施

## 1. 目标与非目标

### 目标

把 `main.py` 中 130 行的线性 `main()` 拆成 LangGraph 图，达成三件事：

1. **条件分支显式化**：把现在散在 `if/else` 里的三类分叉提升为图的边——降级/容错分支、数据驱动分支、双模式加载分支。
2. **可观测性自动化**：节点进出自动写 Tracer JSONL（含耗时），并通过 `graph.stream()` 把节点级进度实时打到 stdout 供 `gui.py` 显示。取代现在手写的 4 处 `tracer.log()`。

**本次是纯编排重构：业务行为零改动。** 唯一可观察的行为变化是 trace 日志更细、stdout 多了节点级进度。

### 非目标

- 不引入 HITL（人工审核中断），因此**不需要 checkpointer / interrupt**。
- 不接 LangSmith。执行元数据发往外部服务与决策记录#8 的合规立场冲突。
- 不新增确定性归因逻辑。无密钥时 `attributions=[]`，行为与现状一致。
- **不碰脱敏。** 调查发现"脱敏死代码"的修复方向站不住脚（证据见 §12），已移出本次范围，图中不设 `desensitize` 节点、不设 fail-closed 条件边。`desensitize.py` 模块完全不动。
- 不改动任何业务模块（`rules/` `parsers/` `llm/` `reporting/` `engine.py` `history_scrap.py` `data_loader.py` `desensitize.py`）。
- 不改 `gui.py`。

## 2. 必须守住的外部契约

| 契约 | 来源 | 约束 |
|---|---|---|
| `main.py` 的 CLI 参数与退出码 `0`/`2` | `gui.py` 走 subprocess 调用 | 参数名、退出码语义不变 |
| stdout 含"校验完成"、错误信息打到 **stdout 而非 stderr** | `tests/test_cli_e2e.py:24,26,57` | 打印目标流不能改 |
| trace JSONL 中必须出现 `parse` / `validate` / `attribute` / `report` 四个 step | `tests/test_cli_e2e.py:43` | 即使跳过归因，`attribute` step 也必须留痕 |
| 现有 50 个 pytest 全绿 | 项目验收基线 | 一个测试文件都不改 |

## 3. 环境前置

`.venv` 为 **Python 3.14.6**，当前**未安装** langgraph / langchain-core / pydantic。

**实施第 0 步：在 `.venv` 真实安装 langgraph 并 import 验证**，命令走
`".venv\Scripts\python.exe" -m pip install langgraph`（踩坑记录#2：绝不能用全局 Python）。
装不上则暂停，回到设计讨论，不带假设继续编码。

安装成功后把 langgraph 追加进 `requirements.txt`。

## 4. 文件布局

新增：

```
src/agent/graph/
├── __init__.py      # 导出 build_graph
├── state.py         # AgentState
├── nodes.py         # 8 个节点 + 3 个路由函数 + @traced_node 装饰器
└── builder.py       # build_graph()：装配节点与边，返回编译后的图
```

改动：

- `main.py` — 瘦身至约 50 行：argparse → 组装初始 State → `graph.stream()` → 打印进度 → 读 `exit_code` 退出。
- `requirements.txt` — 追加 langgraph。

新增测试：`tests/test_graph.py`。

`@traced_node` 放在 `nodes.py` 而非独立文件：它只服务于节点，且与节点定义紧邻更易读。若后续超过 40 行再拆出 `_trace.py`。

## 5. AgentState

`src/agent/graph/state.py`：

```python
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
    skip_reason: str                # 跳过归因的原因，写入摘要
    excel_path: str
    md_path: str

    # ── 控制流 ──
    messages: Annotated[list[str], operator.add]
    error: str | None
    exit_code: int                  # 0 成功 / 2 失败
```

设计理由：

- **句柄放 State 而非 LangGraph context**：无 checkpointer ⇒ State 无需可序列化，DataFrame 与对象实例可直接放。节点签名保持 `(state) -> dict` 单参数，脱离 LangGraph 也能单测，不绑死 1.0 的 context API。
- **只有 `messages` 使用 `operator.add` reducer**，其余走默认 replace，避免隐式累加。
- **`report` 整体传递**而非拆成 `df` + `quality_issues` + `product_order_index`：`engine.run(report)` 与 `RuleR2` 都消费 `StandardReport`，拆开需在节点里反复重组。
- `engine` 进 State 使测试可注入替身引擎。

## 6. 节点与路由

### 节点签名

全部为 `(state: AgentState) -> dict`，返回局部更新由 LangGraph 合并。

| 节点 | trace step | on_error | 读 | 写 |
|---|---|---|---|---|
| `load_config` | `config` | abort | 输入参数 | `settings` `field_mapping` `tracer` `engine` `llm_client` |
| `parse_file` | `parse` | abort | `file_path` `sheet` `factory` `report_type` | `report`，`order_df=None`，`hist_index={}`；或 `error`+`exit_code=2` |
| `parse_factory` | `parse` | abort | `factory` `bt_files` `order_files` `hist_files` | `report`（含 `product_order_index`）`order_df` `hist_index`；或 `error`+`exit_code=2` |
| `enrich` | `enrich` | abort | `report` `order_df` `hist_index` | `report`（df 经 `join_order_info` + `match_history_columns`） |
| `validate` | `validate` | abort | `report` `engine` | `anomalies` `rule_errors` |
| `attribute` | `attribute` | degrade | `anomalies` `llm_client` `settings` | `attributions` |
| `attribute_skipped` | `attribute` | degrade | `anomalies` `llm_client` | `attributions=[]` `skip_reason` `messages` |
| `write_report` | `report` | abort | `anomalies` `attributions` `report` `output_dir` | `excel_path` `md_path` `exit_code=0` |

### 路由函数（纯读，无副作用）

```python
def route_mode(state)           -> str   # "parse_file" | "parse_factory"
def route_after_parse(state)    -> str   # "enrich" | END
def route_after_validate(state) -> str   # "attribute" | "attribute_skipped"
```

判据：

- `route_mode`：`state.get("file_path")` 非 None ⇒ `parse_file`，否则 `parse_factory`。
- `route_after_parse`：`state.get("error")` 非空 ⇒ `END`，否则 `enrich`。
- `route_after_validate`：`not state["anomalies"]` 或 `state.get("llm_client") is None` ⇒ `attribute_skipped`，
  否则 `attribute`。

`skip_reason` 由 `attribute_skipped` 节点自行判定（路由函数保持纯读）：
无异常 ⇒ `"无异常"`；否则 ⇒ `"无API密钥"`。后者同时向 `messages` 追加
`"[警告] 未配置API密钥，跳过LLM归因（报告仅含规则判定与证据）"`，与现状 `main.py:160` 的 stdout 文案逐字一致。

### 图结构

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

图为无环 DAG，不存在递归超限风险。

### 三个关键设计点

**`attribute_skipped` 必须是真节点。** `tests/test_cli_e2e.py:43` 断言 trace 含 `attribute` step。若跳过归因时什么都不记，异常数为 0 的场景会让该断言失败。让它成为节点并以 `@traced_node("attribute")` 记 `status="skip"` 与原因，既守住测试契约，又让"为何无归因"可查。

**trace step 名与节点名解耦。** `parse_file` 与 `parse_factory` 都记为 `step="parse"`，因此现有四个 step 断言零改动通过。

**B 服务降级不上图。** `attribute` 节点内部照原样调
`attribute_anomalies(anomalies, client, retriever=partial(retrieve_knowledge, ...))`。
`attribution.py` 已封装"B 服务不可用返回 None 自动降级"，图层不重复实现。

## 7. 错误处理

### 第 1 层：预期业务失败 → 写 `error` 短路到 END

`parse_file` / `parse_factory` 内部捕获 `ReportParseError`、文件缺失、参数缺失，返回
`{"error": msg, "exit_code": 2}`，不让异常穿透到 LangGraph。

### 第 2 层：非预期异常 → `@traced_node` 统一兜底，分两种态度

```python
@traced_node("validate",  on_error="abort")    # 写 error + exit_code=2，短路到 END
@traced_node("attribute", on_error="degrade")  # 吞掉异常，记 warning，继续出报告
```

`abort` 用于 `load_config` `parse_*` `enrich` `validate` `write_report`——数据链路断了，报告没有意义。
`degrade` 用于 `attribute` `attribute_skipped`——决策记录#4 的原则：LLM/知识侧失败绝不影响校验主流程。
`attribute` 失败时写 `attributions=[]` 并向 `messages` 追加警告，流程继续走到 `write_report`，`exit_code` 保持 0。

装饰器职责：记录节点进入、`elapsed_ms`、状态（ok/skip/fail）、节点自报的 detail 摘要、异常 traceback。
不负责打印——stdout 进度由 `main.py` 消费 `graph.stream()` 输出，职责分离。
`state.get("tracer")` 为 None 时（仅 `load_config` 自身）跳过写入，由该节点在创建 Tracer 后自行补记一条。

**统一短路边**：每条出边用同一工厂函数生成，避免逐边手写路由：

```python
def _guard(next_node):
    return lambda s: END if s.get("error") else next_node
```

### 第 3 层：规则级隔离

`engine.run()` 内现有的 per-rule try/except 原样保留。`validate` 节点把 `engine.errors` 搬进
`rule_errors`，并逐条 `tracer.log("validate", "fail", err)`，与现状行为一致。

### exit_code 与 stdout 契约

`main.py` 从最终 State 读 `exit_code`（缺省 0）。`error` 非空时打印 `[错误] {error}` 到 **stdout**
（`tests/test_cli_e2e.py:57` 断言的是 `result.stdout`）。外层包一个 try/except 兜底 fatal 异常，
记 trace 后返回 2，避免 `gui.py` 日志框出现裸 traceback。

`monitor.generate_summary()` 留在 `main.py` 图执行完成之后，不进图——它是全局单例的副作用输出，
与 State 无关，且现状仅在成功路径调用，保持不变。

## 8. main.py 的形态

```python
def main(argv=None) -> int:
    args = _parse_args(argv)
    graph = build_graph()
    initial = _build_initial_state(args)      # argparse → AgentState
    final = {}
    for mode, chunk in graph.stream(initial, stream_mode=["updates", "values"]):
        if mode == "updates":
            _print_progress(chunk)            # "→ 正在执行：规则校验"
        else:
            final = chunk
    return _finish(final)                     # 打印摘要/错误，返回 exit_code
```

`stream_mode=["updates", "values"]` 的多模式返回形态需在实施时以已安装版本验证。
若该形态与预期不符，退路是 `stream_mode="updates"` 并在 `main.py` 内自行合并增量为最终 State——
两条路都不影响图本身的设计。

## 9. 测试策略

### 现有测试

**50 个测试预期全部原样通过，一个文件都不改。** 依据：业务模块零改动；`test_cli_e2e.py` 走 subprocess
只认 CLI 契约（returncode、stdout 文案、trace 的四个 step），而 trace step 名与节点名解耦正是为守住这条。

### 新增 `tests/test_graph.py`

重点压在条件分支——那是本次重构唯一的新行为。

1. **节点单测**：签名为 `(state) -> dict` 的纯函数，不建图即可测。每个节点喂最小 State，断言返回的 key。
2. **路由单测（核心）**：5 条分支各一用例——
   `route_mode` 的 `--file` / `--工厂` 两条；
   `route_after_parse` 的 `error` 非空 ⇒ END；
   `route_after_validate` 的 异常数=0 ⇒ `attribute_skipped`、`llm_client is None` ⇒ `attribute_skipped`、
   正常 ⇒ `attribute`。
3. **`attribute_skipped` 的 skip_reason 判定**：无异常 ⇒ `"无异常"`；有异常但无 client ⇒ `"无API密钥"`
   且 `messages` 含与 `main.py:160` 逐字一致的警告文案。
4. **降级全图测试**：`llm_client=None` 跑完整图 → `attributions == []`、`skip_reason == "无API密钥"`、
   `exit_code == 0`、Excel 照常产出、trace 含 `attribute` step（`status="skip"`）。
5. **装饰器单测**：`abort` 模式抛异常 ⇒ 写 `error` + `exit_code=2` + trace 有 fail 记录；
   `degrade` 模式抛异常 ⇒ 不写 `error`，只进 `messages`。
6. **图装配测试**：`build_graph()` 编译成功，节点集合齐全（8 个节点）。

### 等价性验收

单测证明结构正确，等价性验收证明行为没变：

- 重构前先跑 `PYTHONIOENCODING=utf-8 python -m pytest` 记录基线（预期 50 passed）。
- 重构前后各跑一次 `--工厂 金州厂` 真实数据，对比两版 Excel 的**异常行数**与**规则编号分布**，必须完全一致。

（踩坑记录#10：Windows 控制台跑测试须带 `PYTHONIOENCODING=utf-8`。）

## 10. 实施顺序

0. `.venv` 安装 langgraph 并 import 验证；跑 pytest 记录基线；跑 `--工厂 金州厂` 留存旧版 Excel。
1. `state.py` — `AgentState`。
2. `nodes.py` — `@traced_node` 装饰器 + 单测。
3. `nodes.py` — 8 个节点（纯搬运现有调用）+ 节点单测。
4. `nodes.py` — 3 个路由函数 + 路由单测（5 条分支）。
5. `builder.py` — `build_graph()` + 装配测试。
6. `main.py` — 瘦身为 CLI 壳。
7. 全量 pytest + 等价性验收（Excel diff）。
8. `requirements.txt` 追加 langgraph。

## 11. 已知风险

| 风险 | 应对 |
|---|---|
| langgraph 在 Python 3.14.6 上装不上 | 实施第 0 步先验证；失败则暂停回到设计讨论 |
| `stream_mode=["updates","values"]` 返回形态与预期不符 | 退路见 §8，不影响图设计 |
| `load_config` 内建 Tracer，该节点自身失败时无 trace 可查 | 与现状等价（现状也是 `load_settings()` 先于 `Tracer()`）。`main.py` 外层 try/except 会把 fatal 打到 stdout，不会静默 |

## 12. 遗留观察（不在本次范围）

### 12.1 脱敏调用是死代码，且"修好它"的方向是错的

`main.py:157` 的 `desensitize_report(report)` 丢弃返回值。调查后确认，把它"修好"（写回 `report.df`）
不但没有收益，反而是回归：

- **对外部 API 零影响**：`build_prompt`（`attribution.py:96-127`）只读
  `a.rule_id` / `a.rule_name` / `a.description` / `a.evidence`，**完全不读 `report.df`**。
  脱敏 df 不会改变发往 DeepSeek 的任何一个字。
- **会破坏内部报告**：`write_excel_report(df=report.df)` → `_build_full_detail`
  （`report_writer.py:32`）执行 `full = df.copy()`，把 df 全部原始列写进"全量明细" sheet。
  脱敏写回后，用户打开 Excel 看到的客户名会变成 `客户_1_a3f2b1c`。

结论：`SENSITIVE_COLUMNS = ("客户", "产品料号")` 这两列**从未进入过 Prompt**。
决策记录#8 描述的 fail-closed 在当前链路上没有对应的真实风险面。

因此新流水线中**不再调用** `desensitize_report`（`desensitize.py` 模块保持不动）。
这是有意为之，不是重构疏漏。

### 12.2 真正的合规缺口

实际流向 DeepSeek 的业务标识是 `Anomaly.order_id`（销售单号）与 `description`，
而它们**不在** `SENSITIVE_COLUMNS` 里。若要真正落实决策记录#8，需要：

1. 对 `order_id` / `description` 脱敏后再拼 Prompt；
2. 归因返回后用映射表还原——注意 `_attribution_map`（`report_writer.py:14`）按
   `(order_id, rule_id)` 匹配，脱敏后必须能还原回去，否则归因结果会全部对不上号。

这是一件独立的功能开发，工作量与风险都不小，建议单开一轮，并同步更正决策记录#8 的表述。
