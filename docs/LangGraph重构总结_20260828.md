# LangGraph 重构总结

日期：2026-08-28
状态：已完成并验收通过（git tag `langgraph-refactor-done`）

## 1. 重构动机

重构前，`main.py` 的 `main()` 是一条 194 行的线性函数，从加载配置、解析报表、多表关联、规则校验、脱敏、LLM 归因一直到报告输出，按固定顺序硬编码排布。这条线性链路有三个具体痛点：

1. **条件分支被埋在 `if/else` 里**：无 API 密钥要不要调归因、异常数为 0 要不要继续、`--file` 测试模式还是 `--工厂` 工厂模式——这些决策点都散在几十行代码中间，读代码的人要在头脑里"还原"控制流，改一处容易漏一处。
2. **可观测性靠手写**：只有 4 处手工 `tracer.log()`，没有每步耗时，某个环节慢或失败时无法快速定位。
3. **编排与业务纠缠**：编排逻辑（先做什么后做什么）与业务逻辑（怎么解析、怎么判定）混在 `main.py` 里，想换成别的编排框架（当时预留的"harness 待定"）就得整体重写。

重构目标不是换业务逻辑，而是**把"先做什么、遇到什么条件走哪条路"这件事从代码里显式提出来**，让流程变成一张可以看、可以追踪、可以单测的图。

## 2. 重构前后架构对比（高层）

**重构前**：`main.py` 是唯一的编排器，一段线性代码顺序调用各业务模块，中间数据靠局部变量（`report` / `order_df` / `hist_index` / `anomalies` / `attributions`）逐段传递。

**重构后**：编排层抽成 `src/agent/graph/` 包（State + 8 节点 + 3 路由 + guard 工厂），`main.py` 瘦身为约 50 行有效逻辑的 CLI 壳，只做"解析参数 → 组装初始 State → 驱动图 → 打印退出"。业务模块（`rules/` `parsers/` `llm/` `reporting/` 等）**一行未改**。

| 维度 | 重构前 | 重构后 |
|---|---|---|
| 流程控制 | `main()` 内线性顺序执行 | LangGraph 状态机（StateGraph） |
| 中间数据 | 局部变量逐段传递 | 集中在 `AgentState`（30 字段） |
| 条件分支 | 散在 `if/else` 里 | 显式路由函数 + 条件边（3 路由 + guard） |
| 可观测性 | 4 处手写 `tracer.log()` | `@traced_node` 自动逐节点留痕（含耗时） |
| 进度展示 | 最终一次性打印 | `graph.stream()` 实时逐节点打印 |
| 编排 vs 业务 | 混在 `main.py` | 完全解耦（graph 包 vs 业务模块） |
| `main.py` 行数 | 194 行 | 110 行（-43%） |
| 错误处理 | 分散的 `try/except` + `return 2` | 装饰器统一 abort/degrade + 路由短路 |

## 3. 最终交付物清单

### 新增（源文件）

| 文件 | 职责 | 行数 |
|---|---|---|
| `src/agent/graph/state.py` | `AgentState`（TypedDict，30 字段，仅 `messages` 用 `operator.add` reducer） | 46 |
| `src/agent/graph/nodes.py` | 8 个节点 + 3 路由 + guard 工厂 + `@traced_node` 装饰器 + `build_engine`/`build_llm_client` | 328 |
| `src/agent/graph/builder.py` | `build_graph()`：装配节点与条件边 | 41 |
| `src/agent/graph/__init__.py` | 导出 `AgentState` / `build_graph` | 5 |

### 新增（测试，10 个文件共 51 用例）

`test_langgraph_api`（3）、`test_graph_state`（3）、`test_graph_nodes`（11）、`test_graph_parse_nodes`（6）、`test_graph_pipeline_nodes`（5）、`test_graph_attribute_nodes`（4）、`test_graph_report_node`（3）、`test_graph_routes`（11）、`test_graph_builder`（5）。

### 修改

| 文件 | 变化 |
|---|---|
| `main.py` | 194 → 110 行，整体替换为 CLI 壳 |
| `requirements.txt` | 追加 `langgraph>=1.0` |
| `.gitignore` | 追加 `baseline/` |
| `docs/superpowers/specs/2026-08-27-langgraph-orchestration-design.md` | 设计文档（评审修正 + `guard` 命名统一） |
| `docs/superpowers/plans/2026-08-28-langgraph-implementation-plan.md` | 实施计划（4 处算术/API 修正） |

### 未改动（关键约束达成）

- 16 个既有测试文件：**零改动**
- 全部业务模块（`rules/` `parsers/` `llm/` `reporting/` `engine.py` `history_scrap.py` `data_loader.py` `desensitize.py`）：**零改动**
- `gui.py`：**零改动**

## 4. 验证结果

| 项 | 结果 |
|---|---|
| 全量测试 | **127 passed**（既有 76 + 新增 51） |
| 既有测试零改动 | `git diff <首提交> -- 16个测试文件` 无输出 ✓ |
| e2e 契约 | `returncode 0/2`、stdout 文案、trace 四 step 全部保持 ✓ |
| 等价性验收 | 真实金州厂数据，异常行数/规则编号分布/订单号集合/工厂分布四项全 OK ✓ |
| trace 可观测性 | 6 步逐节点留痕，各带 `elapsed_ms`（旧版无耗时字段） |
| git tag | `langgraph-refactor-done` |

## 5. 重构过程中修正的关键偏差

| # | 偏差 | 修正 |
|---|---|---|
| 1 | langgraph 1.2.x 无 `__version__` 属性，计划的版本检查一行会报 `AttributeError` | 改用 `importlib.metadata.version()` |
| 2 | 计划沿用记忆里"50 个测试"的旧基线 | 实际既有测试是 **76**，Task 0 现跑记录真实基线 |
| 3 | 计划把 Task 5 用例数写成 6 | 实际是 **5**（3 enrich + 2 validate） |
| 4 | 计划把最终总数写成 124（76+48） | 漏算 langgraph 契约的 3 个，实际 **127 = 76 + 51** |
| 5 | 计划/spec 里 guard 函数写成 `_guard`（私有） | `builder.py` 需跨模块 import，改为公开 `guard` |
| 6 | 脱敏"修复"方向经代码核实后站不住脚 | 移出本次范围（详见 spec §12.1：Prompt 不读 df、写回会破坏内部报告的客户名） |

## 6. 上下游项目同步进展（B 项目 RAG 知识库）

| 时间 | 进展 | 对 A 的影响 |
|---|---|---|
| 2026-09 | RAGAS 量化评估通过（Faithfulness 1.0） | A 归因引用的知识片段准确可靠 |
| 2026-09 | Docker 容器化（docker compose up -d 一键启动） | A 调用 /retrieve 无需改动 |
