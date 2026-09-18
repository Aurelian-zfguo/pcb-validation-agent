# 模块职责与数据流（v2 · LangGraph 重构后）

> 本文档在旧版《职责模块与数据流.md》基础上更新，反映 **2026-08-28 LangGraph 重构**完成后的架构。
> 变化标记说明：
> - 🆕 新增
> - ✏️ 修改
> - 🗑️ 移除
>
> 旧版原文**完整保留在下方「# 附：旧版原文」**，供逐段对照，未做任何删除。

---

# 重构前后对比

## 流程控制方式

| 维度 | 旧版 | 新版 |
|---|---|---|
| 流程控制 | ✏️ `main.py` 内**线性顺序执行**（194 行硬编码顺序） | 🆕 LangGraph **状态机**（StateGraph，8 节点 + 条件边） |
| 中间数据 | ✏️ 局部变量逐段传递（`report`/`order_df`/`hist_index`/`anomalies`/`attributions`） | 🆕 集中在 `AgentState`（30 字段 TypedDict） |
| 条件分支 | ✏️ 散在 `if/else` 里 | 🆕 显式路由函数 + 条件边（3 路由 + guard 工厂） |
| 可观测性 | ✏️ 4 处手写 `tracer.log()`，无耗时 | 🆕 `@traced_node` 自动逐节点留痕，每条带 `elapsed_ms` |
| 进度展示 | ✏️ 最终一次性打印 | 🆕 `graph.stream()` 实时逐节点打印到 stdout |

## 节点数量变化

| | 旧版 | 新版 |
|---|---|---|
| 逻辑步骤 | 约 12 个顺序步骤（见旧版「二、整体数据流」） | 🆕 8 个显式节点 |
| 分支决策点 | 3 处 `if/else`（`--file`/`--工厂`、无密钥、无异常） | 🆕 3 个路由函数 + guard 工厂 |

**8 个节点**：`load_config` / `parse_file` / `parse_factory` / `enrich` / `validate` / `attribute` / `attribute_skipped` / `write_report`。

## 条件分支的显式化程度

| 分支 | 旧版实现 | 新版实现 |
|---|---|---|
| 双模式加载（`--file` vs `--工厂`） | `main.py` 里 50 行 `if args.file: ... else: ...` | 🆕 `route_mode` 路由 |
| 解析失败退出 | `return 2` 散在 try/except | 🆕 `route_after_parse` + guard 短路到 END |
| 无异常 / 无密钥跳过归因 | `if client is None: ...` | 🆕 `route_after_validate` → `attribute_skipped` 节点 |
| 单条规则失败隔离 | `engine.run()` 内 per-rule try/except | ✏️ 保持不变（在 `validate` 节点内复用） |
| B 服务不可用降级 | `attribution.py` 内部 try/except | ✏️ 保持不变（`attribute` 节点内复用） |

## 可观测性提升

| 旧版 | 新版 |
|---|---|
| 4 处手写 `tracer.log("parse"/"validate"/"attribute"/"report", ...)` | 🆕 `@traced_node(step, on_error=...)` 装饰器自动留痕 |
| 无耗时字段 | 🆕 每条 trace 带 `elapsed_ms` |
| 无失败区分 | 🆕 `on_error="abort"`（致命）vs `"degrade"`（降级）两级 |
| 无进度流 | 🆕 `graph.stream(stream_mode=["updates","values"])` 逐节点打印 |

实测新版 trace（真实金州厂数据）：

```
config       ok       8ms
parse        ok   12570ms    ← 读 Excel 是瓶颈，一眼可见
enrich       ok     110ms
validate     ok     148ms   anomalies=7
attribute    ok   22184ms    ← LLM 归因是瓶颈，一眼可见
report       ok     183ms
```

## main.py 代码行数变化

| | 旧版 | 新版 |
|---|---|---|
| `main.py` | ✏️ 194 行 | ✏️ 110 行（**-43%**） |
| 编排逻辑位置 | ✏️ 全在 `main.py` | 🆕 迁至 `src/agent/graph/`（state 46 + nodes 328 + builder 41） |

---

# 重构后的 LangGraph 节点流转图

🗑️ 旧版「二、整体数据流」的线性 ASCII 图与「四、Mermaid 架构图」已由以下状态机图取代：

```mermaid
flowchart TD
    START((START)) --> load_config["load_config<br/>加载配置/建Tracer/建引擎/建LLM客户端"]

    load_config -->|"route_mode<br/>error?"| R_ERR1{ }
    R_ERR1 -->|error| END
    R_ERR1 -->|"--file 模式"| parse_file["parse_file<br/>测试模式解析"]
    R_ERR1 -->|"--工厂 模式"| parse_factory["parse_factory<br/>工厂模式解析+建索引"]

    parse_file -->|"route_after_parse"| R_P1{ }
    parse_factory -->|"route_after_parse"| R_P1{ }
    R_P1 -->|error| END
    R_P1 -->|ok| enrich["enrich<br/>多表关联+历史指标"]

    enrich -->|"guard(validate)"| R_E{ }
    R_E -->|error| END
    R_E -->|ok| validate["validate<br/>D0质检+规则校验"]

    validate -->|"route_after_validate"| R_V{ }
    R_V -->|error| END
    R_V -->|"有异常 且 有LLM客户端"| attribute["attribute<br/>LLM归因"]
    R_V -->|"无异常 或 无密钥"| attribute_skipped["attribute_skipped<br/>跳过归因(留痕)"]

    attribute --> write_report["write_report<br/>生成Excel+MD报告"]
    attribute_skipped --> write_report

    write_report --> END((END))

    style END fill:#f9f,stroke:#333
```

节点与 trace step、容错策略的映射（`@traced_node` 的 step 名与节点名**解耦**，以守住 e2e 契约的四个 step）：

| 节点 | trace step | 异常态度 |
|---|---|---|
| `load_config` | `config` | abort |
| `parse_file` / `parse_factory` | `parse` | abort |
| `enrich` | `enrich` | abort |
| `validate` | `validate` | abort |
| `attribute` / `attribute_skipped` | `attribute` | degrade |
| `write_report` | `report` | abort |

---

# 新版源文件清单（变化标注版）

> 只列与旧版**不同**的条目；未列的与旧版一致。

## src/agent/（核心包）

| 文件 | 职责 | 变化 |
|---|---|---|
| 🆕 `graph/state.py` | `AgentState`：编排层共享状态（30 字段，仅 `messages` 用 `operator.add` reducer） | 🆕 新增 |
| 🆕 `graph/nodes.py` | 8 个节点 + 3 路由 + guard 工厂 + `@traced_node` 装饰器 + `build_engine`/`build_llm_client` | 🆕 新增（自 `main.py` 迁入） |
| 🆕 `graph/builder.py` | `build_graph()`：装配节点与条件边，返回编译后的图 | 🆕 新增 |
| 🆕 `graph/__init__.py` | 导出 `AgentState` / `build_graph` | 🆕 新增 |

| 文件 | 变化 |
|---|---|
| ✏️ `main.py` | 职责从"CLI 入口 + 全程编排"改为"**仅 CLI 壳**：解析参数 → 组装初始 State → 驱动图 → 打印退出"。行数 194→110。 |
| ✏️ `requirements.txt` | 追加 `langgraph>=1.0` |

> 🗑️ **移除项**：旧版 `main.py` 里的 `desensitize_report(report)` 调用在重构中**不再出现**（该调用经核实为死代码，详见《LangGraph重构总结_20260828.md》第 5 节偏差 #6 及设计 spec §12.1）。`desensitize.py` 模块本身保留未动。

## tests/

| 变化 |
|---|
| 🆕 新增 10 个 graph 测试文件：`test_langgraph_api`、`test_graph_state`、`test_graph_nodes`、`test_graph_parse_nodes`、`test_graph_pipeline_nodes`、`test_graph_attribute_nodes`、`test_graph_report_node`、`test_graph_routes`、`test_graph_builder` |
| ✏️ 测试文件总数从 16 → 26，用例从 76 → 127（16 个旧测试文件**零改动**） |

---

# 附：旧版原文

> 以下为旧版《职责模块与数据流.md》的完整原文，保留作逐段对照。
> 其中 `main.py` 职责、整体数据流图、测试文件数等已在上方用 ✏️/🆕/🗑️ 标注变化。

---

我先准确扫描文件清单，并读取核心模块的当前内容（保证逐行解释准确，不做任何修改）。

Glob 被 .venv 污染了，我直接读取核心模块的准确内容（parser/rules/llm 共 9 个文件）：

扫描完成。以下是完整梳理（只解释，不改任何代码）。

---

# 一、源文件清单（按目录分组）

## 项目根目录

| 文件 | 职责 | 依赖 | 被谁依赖 |
|---|---|---|---|
| `main.py` | ✏️ CLI 入口：解析参数 → 数据源准备 → 校验 → 归因 → 报告，全程编排 | config、data_loader、engine、history_scrap、llm.*、parsers、reporting、rules.*、schema、trace | 被 `gui.py` 通过 subprocess 调用；被 `tests/test_cli_e2e.py` 调用 |
| `gui.py` | Tkinter 桌面界面：多选工厂、多选文件、subprocess 调 main.py、实时日志 | 仅标准库（tkinter/subprocess 等） | 无（用户直接 `python gui.py`） |
| `requirements.txt` | ✏️ 依赖清单（pandas/openpyxl/pyyaml/pytest/requests/**langgraph**） | 无 | pip 安装 |
| `pytest.ini` | pytest 配置（testpaths=tests） | 无 | pytest |
| `conftest.py` | 空文件，让 pytest 把项目根加入 sys.path | 无 | pytest |
| `.env` | DeepSeek API 密钥（`DEEPSEEK_API_KEY=sk-...`） | 无 | 被 `config.py` 的 `_load_dotenv()` 读取 |

## config/

| 文件 | 职责 | 依赖 | 被谁依赖 |
|---|---|---|---|
| `settings.yaml` | LLM 配置（provider/base_url/model/api_key/timeout）、trace/output 目录 | 无 | `config.py` |
| `field_mapping.yaml` | 各报表类型的**中文列名别名映射**（如"销售单号→订单号"、"投料扣除余数实际预大率→预大率"） | 无 | `config.py` → `ReportParser` |

## src/agent/（核心包）

| 文件 | 职责 | 依赖 | 被谁依赖 |
|---|---|---|---|
| `schema.py` | 数据模型：`StandardReport`（标准化报表）、`Anomaly`（异常）、`STANDARD_COLUMNS`、`REPORT_TYPES` | 无（纯 dataclass） | 几乎所有模块 |
| `config.py` | 配置加载：`load_settings`/`load_field_mapping`/`resolve_api_key`，含 `.env` 自动加载 | yaml、os、Path | main.py |
| `engine.py` | 校验引擎 `ValidationEngine`：注册规则、执行、错误隔离、去重 | rules.base、schema | main.py |
| `data_loader.py` | 文件自动匹配 `discover_files`、工厂归一化 `normalize_factory`、销售单号关联 `join_order_info` | pandas、Path | main.py、history_scrap.py |
| `history_scrap.py` | 历史报废率计算（复刻 VBA）：dataclass、`read_history_row`、`build_history_index`、`calculate_scrap_rates`、`match_history_columns`、`enrich_anomalies_with_metrics` | pandas、data_loader | main.py |
| 🆕 `graph/` | 编排层：State + 8 节点 + 3 路由 + 图装配（见上文） | langgraph、以上各业务模块 | main.py |

### parsers/

| 文件 | 职责 | 依赖 | 被谁依赖 |
|---|---|---|---|
| `report_parser.py` | 报表解析清洗（字段映射+质检）、产品编号标准化、订单过滤/索引构建 | schema | main.py、rules/after_batch.py |

### rules/

| 文件 | 职责 | 依赖 | 被谁依赖 |
|---|---|---|---|
| `base.py` | 规则插件基类 `RulePlugin`（抽象 `validate`） | schema | 所有规则文件 |
| `warehouse_in.py` | R1 违规入余数仓 | schema、base | main.py |
| `replenish.py` | R2 违规补投（有后批）、R3 重复补投 | schema、base、after_batch | main.py |
| `scrap.py` | R4 违规报废 | schema、base | main.py |
| `after_batch.py` | `check_has_after_batch`（复刻 VBA CheckOrder 两轮逻辑） | report_parser、pandas | replenish.py |

### llm/

| 文件 | 职责 | 依赖 | 被谁依赖 |
|---|---|---|---|
| `client.py` | LLM 客户端：`LLMClient`（抽象）、`MockLLMClient`、`OpenAICompatClient`（带重试/JSON模式） | requests | main.py、attribution.py |
| `desensitize.py` | 数据脱敏（客户/料号 → 哈希代号）（已不再被主流程调用） | schema、hashlib | 🗑️ main.py（重构后不再调用） |
| `attribution.py` | 归因：`build_prompt`、`parse_json_response`、`attribute_anomalies`、对比规则、知识检索(retriever) | schema、client、rag_monitor | main.py |
| 🆕 `knowledge.py` | B 项目知识检索：`retrieve_knowledge` 调 /retrieve 接口，失败静默降级（A 独立性优先） | requests、rag_monitor | nodes.py |
| 🆕 `rag_monitor.py` | RAG 监控单例（`monitor`）：记录检索与归因，生成 CSV 统计摘要 | csv、time | knowledge.py、attribution.py、main.py |

### reporting/ 和 trace/

| 文件 | 职责 | 依赖 | 被谁依赖 |
|---|---|---|---|
| `report_writer.py` | 报告生成 `write_excel_report`（Excel 三 sheet）、`write_markdown_summary` | attribution、schema、pandas | main.py |
| `tracer.py` | 执行日志 `Tracer`（JSONL 溯源） | json、time、Path | main.py、🆕 graph/nodes.py |

### tests/（✏️ 16 → 26 个测试文件）

`test_schema` / `test_config` / `test_parser` / `test_rule_r1` / `test_rule_r2_r3` / `test_rule_r4` / `test_engine` / `test_tracer` / `test_llm` / `test_report_writer` / `test_cli_e2e` / `test_data_loader` / `test_product_order_index` / `test_after_batch` / `test_history_scrap`。

🆕 另有：`test_langgraph_api` / `test_graph_state` / `test_graph_nodes` / `test_graph_parse_nodes` / `test_graph_pipeline_nodes` / `test_graph_attribute_nodes` / `test_graph_report_node` / `test_graph_routes` / `test_graph_builder`。

## 其他目录

- `data/samples/综合日报.csv`：早期样例（含 R1~R4 各一条的虚构数据）
- `docs/superpowers/specs/`、`plans/`：设计文档、实施计划
- `output/`、`logs/traces/`：运行时产物（报告、执行日志）
- 根目录下的 `.xlsx`：真实数据源（补投明细表、订单完成情况、历史报废率）

---

# 二、整体数据流（命令行 → 报告）

> 🗑️ 本节的线性 ASCII 数据流图**已被上方「重构后的 LangGraph 节点流转图」取代**，保留旧图如下仅供对照。

以工厂模式 `python main.py --工厂 金州厂` 为例：

```
main()                                # main.py 入口，argparse 解析参数
 ├─ load_settings() / load_field_mapping()   # config.py 读配置
 ├─ Tracer(...)                               # trace/tracer.py 建日志文件
 │
 ├─ discover_files(工厂, 根目录)              # data_loader.py 按文件名+列匹配3个文件
 │     ├─ 补投: glob *补投明细表*.xlsx
 │     ├─ 订单: glob *订单完成情况*.xlsx → 按"生产工厂"列认领工厂
 │     └─ 报废: glob *历史报废率*.xlsx → 按"组织"列认领工厂
 │
 ├─ pd.read_excel(补投) → 按"组织名称"过滤工厂 → parse_df()
 │     ├─ _map_columns()   # 别名→标准列名（销售单号→订单号 等）
 │     └─ _quality_check() # 数据质检 → D0 异常（缺订单号/重复行/非数字）
 │
 ├─ filter_order_by_products(订单全量, 补投成品)  # report_parser.py 功能一
 │     └─ build_product_order_index(过滤后)       # 功能二：型号订单索引
 │
 ├─ build_history_index(报废)          # history_scrap.py 历史报废率索引
 ├─ join_order_info(补投, 订单)        # data_loader.py 销售单号关联（精确/大行/未匹配）
 ├─ match_history_columns(补投, 历史索引)  # history_scrap.py 新增4列历史指标
 │
 ├─ build_engine() → engine.run(report)   # engine.py 执行 R1/R2/R3/R4
 │     ├─ RuleR1WarehouseIn.validate()
 │     ├─ RuleR2AfterBatch.validate()      # 调 check_has_after_batch()
 │     ├─ RuleR3DuplicateReplenish.validate()
 │     └─ RuleR4ScrapWithOnlineBoards.validate()
 │
 ├─ enrich_anomalies_with_metrics()    # history_scrap.py 补 预大率+4历史指标 进证据
 ├─ 🗑️ desensitize_report()               # llm/desensitize.py 脱敏（重构后不再调用）
 ├─ _build_llm_client()                # llm/client.py 选 Mock 或 OpenAICompat
 ├─ attribute_anomalies(异常, client)  # llm/attribution.py
 │     ├─ build_prompt()               # 拼异常+预大率+历史报废率+对比规则
 │     ├─ client.chat()                # 调 DeepSeek
 │     └─ parse_json_response()        # 解析 JSON → Attribution 列表
 │
 ├─ write_excel_report()               # reporting/report_writer.py → Excel
 └─ write_markdown_summary()           # → Markdown 摘要
```

---

# 三、核心模块逐行解释

## 3.1 parsers/report_parser.py

**`_read_file(path, sheet)`（17-29 行）**：按扩展名读文件。`.xlsx/.xls` 用 `pd.read_excel`（可指定 sheet）；`.csv` 用 `utf-8-sig` 编码（兼容 Excel 导出的 BOM）。文件不存在/类型不支持则抛 `ReportParseError`。

**`_map_columns(df, aliases)`（32-42 行）**：核心是"别名→标准列名"映射。遍历 field_mapping.yaml 里每个标准列（如"订单号"）的别名列表（如 `[销售单号, 订单号, 单号...]`），找到第一个在报表里出现的别名，重命名成标准列。标准列已存在则跳过。

**`normalize_product_code_99(code)`（45-55 行）**：产品编号标准化。去空格、转大写；若倒数第 2-3 位是 `00`/`99`，统一成 `99`（如 `100497915C1000A → 100497915C1099A`）。用于后续订单匹配。

**`filter_order_by_products(df_order, df_main)`（58-74 行）**：功能一。取补投表的产品编号集合（标准化后），过滤订单表——只保留产品编号在补投表里出现过的订单行，并新增 `SO号-行` 拼接列。

**`build_product_order_index(df_filtered)`（77-104 行）**：功能二。遍历过滤后的订单，按 `(标准化产品编号, 生产工厂)` 建字典，value 是订单信息列表（下单时间/转工单时间/行号/赠品备品/订单大行/行状态/审核状态）。供 R2 的 `check_has_after_batch` 使用。

**`ReportParser.parse()`（111-118 行）**：读文件 → 调 `parse_df`。

**`parse_df()`（120-140 行）**：列映射 → 检查"订单号"列存在 → `reset_index` → 加隐藏列 `_行号`（=行号+1，对齐 Excel 行号）→ 质检 → 数值列 `to_numeric` → 返回 `StandardReport`。

**`_quality_check()`（142-172 行）**：三类数据质量问题（rule_id="D0"）：① 订单号为空 ② 完全重复的行 ③ 数值列存在非数字值。每条都生成一个 `Anomaly` 并带定位（第 N 行）。

## 3.2 rules/

**`base.py` — `RulePlugin`（7-15 行）**：抽象基类。定义 `rule_id`/`rule_name` 类属性 + 抽象方法 `validate(report) -> list[Anomaly]`。所有规则实现同一接口，保证引擎统一调用、可插拔。

**`warehouse_in.py` — R1（10-31 行）**：判断"在线有板且订单不够数时余数入库"。先检查所需 4 列是否存在（缺列则规则不适用返回空）；`mask` 用三个条件按位与（`入库数>0 且 在线数>0 且 已产出<需求`）；命中的行生成 Anomaly，证据带在线/已产出/需求/入库数。

**`replenish.py` — R2（9-40 行）**：违规补投（有后批订单）。先过滤"成品"；逐行算"订单大行"（销售单号去掉小行），调 `check_has_after_batch` 判断；状态是"是/上批订单预大不足"则生成异常，证据带后批订单大行列表。

**`replenish.py` — R3（43-70 行）**：重复补投。过滤"成品"；把补料日期归一成"天"（忽略时分秒）生成 `_补投日` 列；`duplicated(订单号, _补投日)` 找出同日同 SO 行的多行，按组生成异常，证据带同日补投记录数。

**`scrap.py` — R4（10-26 行）**：违规报废。`报废数>0 且 在线数>0` 即"在线仍有可用板却报废"，生成异常。

**`after_batch.py` — `check_has_after_batch`（69-75 行）**：R2 的核心判断。`_get_orders` 用 `(标准化产品编号, 去SUNTAK_前缀的工厂)` 查索引，无数据返回"无数据"，否则调 `_match` 返回状态。

**`after_batch.py` — `_match`（38-66 行）**：两轮逻辑。第一轮（43-55 行）：下单时间≤补料日期 且 转工单为空 且 小数位=1 且 非赠品(N) 且 不同大行 → "是"；第二轮（57-65 行）：转工单时间在 `[补料日期-7天, 补料日期)` 且 不同大行 → "上批订单预大不足"；否则"否"。

## 3.3 llm/

**`client.py` — `LLMClient`（9-12 行）**：抽象基类，`chat(messages) -> str`。

**`MockLLMClient`（15-24 行）**：无 API 密钥时用，返回固定格式归因 JSON（50 条占位），用于跑通链路。

**`OpenAICompatClient.chat`（39-63 行）**：真实调用。payload 带 `response_format={"type":"json_object"}`（强制 JSON）；`for` 循环重试 `max_retries` 次；401/403 鉴权错误不重试直接抛，429/5xx/网络错误重试（退避 `retry_backoff * (attempt+1)` 秒）。

**`desensitize.py` — `desensitize_text`（12-18 行）**：敏感值 → 代号（`前缀_序号_md5前8位`），同一原文稳定映射同一代号。**`desensitize_report`（21-29 行）**：对报表的"客户/产品料号"列做脱敏，返回副本+映射表。

**`attribution.py` — `build_prompt`（57-63 行附近）**：把每个异常拼成 `规则X「名称」：描述；证据：{json}`，并附加 `_history_analysis_block`（预大率+4历史指标+对比规则）。

**`attribution.py` — `_history_analysis_block`**：预大率为空→写"无预大率数据"；有值→列预大率+4指标+波动判断（`_volatility_flags`）+对比规则。

**`attribution.py` — `_volatility_flags`**：确定性算两层波动（阈值1 平均>剔除最高×1.5、阈值2 平均-剔除最高>0.10），返回提示文本。

**`attribution.py` — `parse_json_response`（66-77 行）**：正则提取模型回复里的 `{...}` JSON 对象 → 取 `results` 数组。

**`attribution.py` — `attribute_anomalies`**：先查每条异常的预大率，若 >100% 强制 category="数据错误"（跳过 AI）；否则用 AI 返回的 category（非法则钳制"其他"）；无返回则 fallback "未归因"。

---

# 四、Mermaid 架构图

> 🗑️ 本节的旧版模块依赖图**已被上方「重构后的 LangGraph 节点流转图」取代**，保留旧图如下仅供对照。

```mermaid
graph TD
    subgraph 入口层
        CLI[main.py CLI入口]
        GUI[gui.py 桌面界面] -->|subprocess| CLI
    end

    subgraph 配置层
        CFG[config.py 配置加载] --> SET[settings.yaml]
        CFG --> FM[field_mapping.yaml]
        ENV[.env API密钥] --> CFG
    end

    subgraph 数据层
        DL[data_loader.py<br/>文件匹配+关联]
        HS[history_scrap.py<br/>历史报废率计算]
        PR[parsers/report_parser.py<br/>解析/标准化/索引]
    end

    subgraph 校验层
        ENG[engine.py 校验引擎]
        R1[rules/warehouse_in.py R1]
        R2[rules/replenish.py R2/R3]
        R4[rules/scrap.py R4]
        AB[rules/after_batch.py CheckOrder]
        BASE[rules/base.py RulePlugin]
        R1 -.实现.-> BASE
        R2 -.实现.-> BASE
        R4 -.实现.-> BASE
        R2 --> AB
        AB --> PR
        ENG --> BASE
    end

    subgraph LLM层
        CL[llm/client.py 客户端]
        DE[llm/desensitize.py 脱敏]
        AT[llm/attribution.py 归因]
        AT --> CL
    end

    subgraph 输出层
        RW[reporting/report_writer.py 报告]
        TR[trace/tracer.py 日志]
    end

    SCHEMA[schema.py 数据模型]

    CLI --> CFG
    CLI --> DL
    CLI --> PR
    CLI --> HS
    CLI --> ENG
    CLI --> DE
    CLI --> AT
    CLI --> RW
    CLI --> TR

    DL -.用.-> SCHEMA
    HS -.用.-> SCHEMA
    PR -.用.-> SCHEMA
    ENG -.用.-> SCHEMA
    RW -.用.-> SCHEMA
    AT -.用.-> SCHEMA
    R1 -.用.-> SCHEMA
    R2 -.用.-> SCHEMA
    R4 -.用.-> SCHEMA
```

**核心依赖关系一句话总结**：

- `schema.py` 是被依赖最多的"地基"（数据模型）。
- ✏️ `main.py` 是唯一的编排器 → 🆕 编排已迁至 `src/agent/graph/`，`main.py` 退化为 CLI 壳。
- `rules/` 是插件层（`base.py` 定义接口，四个规则实现它），`engine.py` 统一调度。
- `llm/` 只被 `main.py` 调用（归因、脱敏、客户端），`attribution.py` 依赖 `client.py`。→ ✏️ 现被 `graph/nodes.py` 的节点调用。
- `data_loader.py` + `history_scrap.py` + `report_parser.py` 是数据处理三件套，供 `main.py` 编排。→ ✏️ 现供 `graph/nodes.py` 的节点调用。
- `gui.py` 完全独立，只通过 subprocess 调 `main.py`，不 import 任何业务模块。

这就是整个系统的完整架构和业务流程。
