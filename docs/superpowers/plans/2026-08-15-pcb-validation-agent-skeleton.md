# PCB生产预投业务数据校验Agent MVP骨架 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建MVP骨架：CLI入口 + 报表解析清洗 + R1~R4规则校验引擎 + LLM归因（Mock可跑通）+ 异常报告 + JSONL执行日志 + 测试，全链路可用且不依赖DeepSeek-Harness。

**Architecture:** 方案A（确定性校验内核 + LLM归因）。业务逻辑为纯Python库 `src/agent/`，Agent编排仅为main.py中的顺序流程；LLM调用统一走OpenAI兼容client接口，harness就绪后可替换编排层而不动业务代码。

**Tech Stack:** Python 3.10+、pandas、openpyxl、pyyaml、pytest、requests。

**Spec:** `docs/superpowers/specs/2026-08-15-pcb-validation-agent-design.md`

## Global Constraints

- Python ≥3.10；第三方依赖仅限：pandas、openpyxl、pyyaml、pytest、requests
- 所有源码文件UTF-8编码；CSV读取用 `encoding="utf-8-sig"`（兼容Excel导出带BOM）
- **所有文件操作使用完整绝对Windows路径（盘符+反斜杠）**，如 `D:\Python\Claude Code\Programs\PCB生产预投业务数据校验Agent\src\agent\schema.py`
- API密钥不硬编码：优先环境变量 `DEEPSEEK_API_KEY` / `CLAUDE_API_KEY`，其次 `config/settings.yaml`
- 判定条件可迭代原则：每条规则的判定逻辑集中在一个类文件内；阈值类参数放 `config/settings.yaml`；规则编号（R1~R4、D0）作为报告引用标识
- 异常数据模型：`Anomaly(rule_id, rule_name, factory, order_id, description, evidence: dict, location: str)`；数据质量异常 rule_id 恒为 "D0"
- TDD流程：先写失败测试 → 运行确认失败 → 写最小实现 → 运行确认通过 → 提交
- 项目根目录：`D:\Python\Claude Code\Programs\PCB生产预投业务数据校验Agent`（下文称 `<ROOT>`）
- 运行测试命令统一：`cd "<ROOT>" && python -m pytest tests\<file> -v`（Git Bash下用正斜杠亦可）
- git为可选：Task 0如初始化git则每任务末尾执行提交；未初始化则跳过所有提交步骤

---

### Task 0: 项目初始化（依赖、目录骨架、测试配置）

**Files:**
- Create: `<ROOT>\requirements.txt`
- Create: `<ROOT>\pytest.ini`
- Create: `<ROOT>\conftest.py`（空文件，让pytest把项目根加入sys.path）
- Create: 目录树及所有空 `__init__.py`：`src\__init__.py`、`src\agent\__init__.py`、`src\agent\parsers\__init__.py`、`src\agent\rules\__init__.py`、`src\agent\llm\__init__.py`、`src\agent\reporting\__init__.py`、`src\agent\trace\__init__.py`
- Create: 空目录 `config\`、`tests\`、`data\samples\`、`output\`、`logs\traces\`

**Interfaces:**
- Consumes: 无（第一个任务）
- Produces: 项目根可被pytest识别；`src.agent` 可被 `import`；依赖已安装

- [ ] **Step 1: 创建 requirements.txt**

```
pandas>=2.0
openpyxl>=3.1
pyyaml>=6.0
pytest>=8.0
requests>=2.31
```

- [ ] **Step 2: 创建 pytest.ini**

```ini
[pytest]
testpaths = tests
```

- [ ] **Step 3: 创建目录骨架与空 __init__.py**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && mkdir -p config tests data/samples output logs/traces src/agent/parsers src/agent/rules src/agent/llm src/agent/reporting src/agent/trace && touch conftest.py src/__init__.py src/agent/__init__.py src/agent/parsers/__init__.py src/agent/rules/__init__.py src/agent/llm/__init__.py src/agent/reporting/__init__.py src/agent/trace/__init__.py
```

- [ ] **Step 4: 安装依赖**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && pip install -r requirements.txt
```

（如在PyCharm虚拟环境内，用该venv的解释器执行。如公司网络无法访问PyPI，使用公司镜像源：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`）

- [ ] **Step 5: 验证环境**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -c "import pandas, openpyxl, yaml, pytest, requests; print('deps ok')"
```

Expected: 输出 `deps ok`

- [ ] **Step 6: （可选）初始化git仓库**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && git init
```

若执行了此步，本任务提交：

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && git add requirements.txt pytest.ini conftest.py && git commit -m "chore: init project skeleton"
```

若未执行，后续所有任务的"提交"步骤跳过。

---

### Task 1: 数据模型 schema.py

**Files:**
- Create: `<ROOT>\src\agent\schema.py`
- Test: `<ROOT>\tests\test_schema.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `STANDARD_COLUMNS: list[str]` —— 标准化列名全集
  - `REPORT_TYPES = ("补投日报", "余数入库日报", "余数报废日报", "综合日报")`
  - `@dataclass StandardReport(report_type: str, factory: str, source_path: str, df, quality_issues: list)` —— df为pandas.DataFrame，列对齐STANDARD_COLUMNS；`quality_issues` 默认空列表
  - `@dataclass Anomaly(rule_id: str, rule_name: str, factory: str, order_id: str, description: str, evidence: dict, location: str)` —— evidence默认空dict

- [ ] **Step 1: 写失败测试 tests\test_schema.py**

```python
import pandas as pd
from src.agent.schema import STANDARD_COLUMNS, REPORT_TYPES, StandardReport, Anomaly


def test_standard_columns_contains_core_fields():
    for col in ["工厂", "订单号", "产品料号", "客户", "批次号",
                "需求数", "已产出数", "在线数",
                "补投数", "补投日期", "入库数", "入库日期", "报废数", "报废日期"]:
        assert col in STANDARD_COLUMNS


def test_report_types():
    assert REPORT_TYPES == ("补投日报", "余数入库日报", "余数报废日报", "综合日报")


def test_anomaly_defaults():
    a = Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="珠海一厂",
                order_id="A001", description="x", location="第3行")
    assert a.evidence == {}
    assert a.rule_id == "R1"


def test_standard_report_default_quality_issues():
    r = StandardReport(report_type="综合日报", factory="珠海一厂", source_path="a.csv", df=pd.DataFrame())
    assert r.quality_issues == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_schema.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'src.agent.schema'`）

- [ ] **Step 3: 实现 src\agent\schema.py**

```python
"""标准化数据模型：所有报表解析后的统一结构，及校验异常结构。"""
from dataclasses import dataclass, field
from typing import Any

# 标准化后的报表列名（解析后的所有报表对齐到这些列，缺的列允许不存在）
STANDARD_COLUMNS = [
    "工厂", "订单号", "产品料号", "客户", "批次号",
    "需求数", "已产出数", "在线数",
    "补投数", "补投日期",
    "入库数", "入库日期",
    "报废数", "报废日期",
]

# 支持的报表类型（MVP：不含预投日报，二期补）
REPORT_TYPES = ("补投日报", "余数入库日报", "余数报废日报", "综合日报")


@dataclass
class StandardReport:
    """标准化后的报表：DataFrame + 元信息。"""
    report_type: str          # 取值见 REPORT_TYPES
    factory: str              # 如 "珠海一厂"
    source_path: str          # 原始文件路径
    df: Any = None            # pandas.DataFrame，列对齐 STANDARD_COLUMNS，另含隐藏列 "_行号"
    quality_issues: list = field(default_factory=list)  # 第0类异常（数据质量，rule_id="D0"）


@dataclass
class Anomaly:
    """一条校验异常。"""
    rule_id: str              # R1..R4 / D0
    rule_name: str
    factory: str
    order_id: str
    description: str
    evidence: dict = field(default_factory=dict)  # 证据字段，如 {"在线数": 10, "需求数": 20}
    location: str = ""        # 定位信息，如 "第3行"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_schema.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && git add src/agent/schema.py tests/test_schema.py && git commit -m "feat: add standard data model (schema)"
```

---

### Task 2: 配置加载（settings.yaml + field_mapping.yaml + config.py）

**Files:**
- Create: `<ROOT>\config\settings.yaml`
- Create: `<ROOT>\config\field_mapping.yaml`
- Create: `<ROOT>\src\agent\config.py`
- Test: `<ROOT>\tests\test_config.py`

**Interfaces:**
- Consumes: Task 1（无直接依赖）
- Produces:
  - `config.PROJECT_ROOT: Path` —— 项目根目录
  - `config.load_settings() -> dict` —— settings.yaml内容
  - `config.load_field_mapping() -> dict` —— field_mapping.yaml内容
  - `config.resolve_api_key(settings: dict) -> str` —— 环境变量优先

- [ ] **Step 1: 写失败测试 tests\test_config.py**

```python
from src.agent.config import load_settings, load_field_mapping, resolve_api_key, PROJECT_ROOT


def test_project_root_points_to_project_dir():
    assert (PROJECT_ROOT / "config" / "settings.yaml").exists()


def test_load_settings_has_sections():
    s = load_settings()
    assert set(s) >= {"llm", "trace", "output"}
    assert "provider" in s["llm"] and "model" in s["llm"]


def test_field_mapping_has_supported_types():
    m = load_field_mapping()
    for t in ("补投日报", "余数入库日报", "余数报废日报", "综合日报"):
        assert t in m["report_types"]
        assert "订单号" in m["report_types"][t]


def test_resolve_api_key_env_first(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    assert resolve_api_key({"llm": {"api_key": "yaml-key"}}) == "env-key"
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert resolve_api_key({"llm": {"api_key": "yaml-key"}}) == "yaml-key"
    assert resolve_api_key({"llm": {"api_key": ""}}) == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'src.agent.config'`）

- [ ] **Step 3: 创建 config\settings.yaml**

```yaml
# LLM 调用配置
llm:
  provider: openai-compatible  # mock | openai-compatible（DeepSeek/Claude均走OpenAI兼容接口）
  base_url: https://api.deepseek.com/v1
  api_key: ""                  # 留空则读环境变量 DEEPSEEK_API_KEY / CLAUDE_API_KEY
  model: deepseek-chat
  timeout_seconds: 60

# 执行日志目录（相对项目根）
trace:
  dir: logs/traces

# 报告输出目录（相对项目根）
output:
  dir: output
```

- [ ] **Step 4: 创建 config\field_mapping.yaml**

```yaml
# 各报表类型的中文列名别名映射：标准列名 -> 实际报表中可能出现的别名列表
report_types:
  补投日报:
    工厂: [工厂, 厂区]
    订单号: [订单号, 订单编号, 单号, 生产单号]
    产品料号: [产品料号, 料号, 型号, 品号]
    客户: [客户, 客户名称]
    批次号: [批次号, 批号, LOT]
    需求数: [需求数, 订单数量, 需求数量]
    已产出数: [已产出数, 已产出, 产出数]
    在线数: [在线数, 在线数量, WIP数, 在制数]
    补投数: [补投数, 补投数量, 补料数]
    补投日期: [补投日期, 补料日期]
  余数入库日报:
    工厂: [工厂, 厂区]
    订单号: [订单号, 订单编号, 单号, 生产单号]
    产品料号: [产品料号, 料号, 型号, 品号]
    客户: [客户, 客户名称]
    批次号: [批次号, 批号, LOT]
    需求数: [需求数, 订单数量, 需求数量]
    已产出数: [已产出数, 已产出, 产出数]
    在线数: [在线数, 在线数量, WIP数, 在制数]
    入库数: [入库数, 入库数量, 入仓数]
    入库日期: [入库日期, 入仓日期]
  余数报废日报:
    工厂: [工厂, 厂区]
    订单号: [订单号, 订单编号, 单号, 生产单号]
    产品料号: [产品料号, 料号, 型号, 品号]
    客户: [客户, 客户名称]
    批次号: [批次号, 批号, LOT]
    需求数: [需求数, 订单数量, 需求数量]
    已产出数: [已产出数, 已产出, 产出数]
    在线数: [在线数, 在线数量, WIP数, 在制数]
    报废数: [报废数, 报废数量]
    报废日期: [报废日期, 报废时间]
  综合日报:
    工厂: [工厂, 厂区]
    订单号: [订单号, 订单编号, 单号, 生产单号]
    产品料号: [产品料号, 料号, 型号, 品号]
    客户: [客户, 客户名称]
    批次号: [批次号, 批号, LOT]
    需求数: [需求数, 订单数量, 需求数量]
    已产出数: [已产出数, 已产出, 产出数]
    在线数: [在线数, 在线数量, WIP数, 在制数]
    补投数: [补投数, 补投数量, 补料数]
    补投日期: [补投日期, 补料日期]
    入库数: [入库数, 入库数量, 入仓数]
    入库日期: [入库日期, 入仓日期]
    报废数: [报废数, 报废数量]
    报废日期: [报废日期, 报废时间]
```

- [ ] **Step 5: 实现 src\agent\config.py**

```python
"""配置加载：settings.yaml、field_mapping.yaml、API密钥解析。"""
import os
from pathlib import Path

import yaml

# 项目根目录 = config.py 的上两级（src/agent -> src -> 项目根）
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_settings(path: Path | None = None) -> dict:
    p = path or PROJECT_ROOT / "config" / "settings.yaml"
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_field_mapping(path: Path | None = None) -> dict:
    p = path or PROJECT_ROOT / "config" / "field_mapping.yaml"
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_api_key(settings: dict) -> str:
    """密钥优先级：环境变量 > settings.yaml。DeepSeek与Claude的密钥都检查。"""
    return (os.environ.get("DEEPSEEK_API_KEY", "")
            or os.environ.get("CLAUDE_API_KEY", "")
            or settings.get("llm", {}).get("api_key", ""))
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_config.py -v`
Expected: PASS（4 passed）

- [ ] **Step 7: 提交**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && git add config/settings.yaml config/field_mapping.yaml src/agent/config.py tests/test_config.py && git commit -m "feat: add config loading (settings + field mapping)"
```

---

### Task 3: 报表解析与数据质检 parsers/report_parser.py

**Files:**
- Create: `<ROOT>\src\agent\parsers\report_parser.py`
- Test: `<ROOT>\tests\test_parser.py`

**Interfaces:**
- Consumes:
  - `schema.STANDARD_COLUMNS`、`schema.StandardReport`、`schema.Anomaly`（Task 1）
  - `config.load_field_mapping()`（Task 2，测试中用真实配置）
- Produces:
  - `class ReportParseError(Exception)` —— 解析失败（文件不存在/类型不支持/类型未知/无法识别订单号字段）
  - `class ReportParser:`
    - `__init__(self, field_mapping: dict)`
    - `parse(self, path: str, factory: str, report_type: str) -> StandardReport`
    - 行为：读取Excel/CSV → 列名别名映射 → 附加隐藏列 `_行号`（=行号+1，与Excel一致）→ 数值列to_numeric → 数据质检生成D0异常 → 返回StandardReport
  - 数据质检三检查：订单号为空、完全重复行、数值列存在非数字值；D0异常factory=传入的factory，location为"第N行"

- [ ] **Step 1: 写失败测试 tests\test_parser.py**

```python
import pandas as pd
import pytest

from src.agent.config import load_field_mapping
from src.agent.parsers.report_parser import ReportParser, ReportParseError
from src.agent.schema import StandardReport

MAPPING = load_field_mapping()


def _write_csv(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8-sig")  # 带BOM模拟Excel导出
    return str(p)


def test_parse_maps_alias_columns(tmp_path):
    p = _write_csv(tmp_path, "t.csv",
                   "单号,批次号,需求数量,已产出,在线数量,补投数量,补料日期,厂区\n"
                   "A001,B1,20,8,10,5,2026-08-10,珠海一厂\n")
    report = ReportParser(MAPPING).parse(p, "珠海一厂", "补投日报")
    assert isinstance(report, StandardReport)
    assert "订单号" in report.df.columns and "需求数" in report.df.columns
    assert report.df.loc[0, "订单号"] == "A001"
    assert report.df.loc[0, "_行号"] == 2
    assert report.df.loc[0, "补投数"] == 5.0  # 数值已转换


def test_parse_unknown_report_type(tmp_path):
    p = _write_csv(tmp_path, "t.csv", "单号\nA001\n")
    with pytest.raises(ReportParseError, match="未知报表类型"):
        ReportParser(MAPPING).parse(p, "珠海一厂", "不存在的日报")


def test_parse_missing_order_column_reports_columns(tmp_path):
    p = _write_csv(tmp_path, "t.csv", "备注\nxxx\n")
    with pytest.raises(ReportParseError, match="无法识别订单号字段"):
        ReportParser(MAPPING).parse(p, "珠海一厂", "补投日报")


def test_parse_nonexistent_file(tmp_path):
    with pytest.raises(ReportParseError, match="文件不存在"):
        ReportParser(MAPPING).parse(str(tmp_path / "no.csv"), "珠海一厂", "补投日报")


def test_quality_issues_empty_order_id(tmp_path):
    p = _write_csv(tmp_path, "t.csv",
                   "订单号,需求数,在线数\n,20,5\nA002,30,0\n")
    report = ReportParser(MAPPING).parse(p, "珠海一厂", "综合日报")
    d0 = [a for a in report.quality_issues if a.rule_id == "D0"]
    assert any("订单号为空" in a.description for a in d0)


def test_quality_issues_duplicate_rows(tmp_path):
    p = _write_csv(tmp_path, "t.csv",
                   "订单号,需求数,在线数\nA001,20,5\nA001,20,5\n")
    report = ReportParser(MAPPING).parse(p, "珠海一厂", "综合日报")
    assert any("重复" in a.description for a in report.quality_issues)


def test_quality_issues_non_numeric(tmp_path):
    p = _write_csv(tmp_path, "t.csv",
                   "订单号,需求数,在线数\nA001,二十,5\n")
    report = ReportParser(MAPPING).parse(p, "珠海一厂", "综合日报")
    assert any("需求数" in a.description and "有效数字" in a.description
               for a in report.quality_issues)
    assert pd.isna(report.df.loc[0, "需求数"])  # 已coerce为NaN


def test_parse_xlsx(tmp_path):
    p = str(tmp_path / "t.xlsx")
    pd.DataFrame({"订单号": ["A001"], "需求数": [20], "在线数": [5]}).to_excel(p, index=False)
    report = ReportParser(MAPPING).parse(p, "珠海一厂", "综合日报")
    assert len(report.df) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_parser.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 src\agent\parsers\report_parser.py**

```python
"""报表解析与清洗：字段别名映射、类型转换、数据质检（第0类异常）。"""
from pathlib import Path

import pandas as pd

from ..schema import STANDARD_COLUMNS, Anomaly, StandardReport


class ReportParseError(Exception):
    """报表无法解析时抛出，消息需明确列出问题字段，不静默跳过。"""


# 需要转为数值的标准列
NUMERIC_COLUMNS = ["需求数", "已产出数", "在线数", "补投数", "入库数", "报废数"]


def _read_file(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise ReportParseError(f"文件不存在: {path}")
    suffix = p.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    if suffix == ".csv":
        # utf-8-sig 兼容Excel导出的BOM
        return pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    raise ReportParseError(f"不支持的文件类型: {p.suffix}（支持 .xlsx/.xls/.csv）")


def _map_columns(df: pd.DataFrame, aliases: dict) -> pd.DataFrame:
    """把实际列名按别名映射为标准列名；标准列已存在则不覆盖。"""
    rename = {}
    for std, alias_list in aliases.items():
        if std in df.columns:
            continue
        for alias in alias_list:
            if alias in df.columns:
                rename[alias] = std
                break
    return df.rename(columns=rename)


class ReportParser:
    def __init__(self, field_mapping: dict):
        self.field_mapping = field_mapping

    def parse(self, path: str, factory: str, report_type: str) -> StandardReport:
        report_types = self.field_mapping.get("report_types", {})
        if report_type not in report_types:
            raise ReportParseError(
                f"未知报表类型「{report_type}」，已支持: {list(report_types)}")
        df = _read_file(path)
        df = _map_columns(df, report_types[report_type])
        if "订单号" not in df.columns:
            raise ReportParseError(
                f"无法识别订单号字段，报表现有列: {list(df.columns)}，"
                f"已支持别名见 config/field_mapping.yaml")
        # 隐藏行号列：Excel第1行是表头，数据行从第2行起
        df["_行号"] = range(2, len(df) + 2)
        issues = self._quality_check(df, factory)
        for col in NUMERIC_COLUMNS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return StandardReport(report_type=report_type, factory=factory,
                              source_path=str(path), df=df, quality_issues=issues)

    def _quality_check(self, df: pd.DataFrame, factory: str) -> list:
        issues = []
        # 1) 订单号为空
        empty_order = df["订单号"].isna() | (df["订单号"].astype(str).str.strip() == "")
        for _, row in df[empty_order].iterrows():
            issues.append(Anomaly(
                rule_id="D0", rule_name="数据质量", factory=factory, order_id="(空)",
                description="订单号为空，无法参与校验",
                location=f"第{row['_行号']}行"))
        # 2) 完全重复的行
        for _, row in df[df.duplicated(keep=False)].iterrows():
            issues.append(Anomaly(
                rule_id="D0", rule_name="数据质量", factory=factory,
                order_id=str(row["订单号"]),
                description="存在完全重复的行",
                location=f"第{row['_行号']}行"))
        # 3) 数值列存在非数字值
        for col in NUMERIC_COLUMNS:
            if col not in df.columns:
                continue
            coerced = pd.to_numeric(df[col], errors="coerce")
            bad = df[coerced.isna() & df[col].notna()]
            for _, row in bad.iterrows():
                issues.append(Anomaly(
                    rule_id="D0", rule_name="数据质量", factory=factory,
                    order_id=str(row["订单号"]),
                    description=f"「{col}」不是有效数字: {row[col]}",
                    evidence={col: str(row[col])},
                    location=f"第{row['_行号']}行"))
        return issues
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_parser.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && git add src/agent/parsers/report_parser.py tests/test_parser.py && git commit -m "feat: add report parser with field mapping and data quality checks"
```

---

### Task 4: R1 违规入余数仓 规则插件

**Files:**
- Create: `<ROOT>\src\agent\rules\base.py`
- Create: `<ROOT>\src\agent\rules\warehouse_in.py`
- Test: `<ROOT>\tests\test_rule_r1.py`

**Interfaces:**
- Consumes: `schema.StandardReport`、`schema.Anomaly`（Task 1）
- Produces:
  - `rules.base.RulePlugin(ABC)`：类属性 `rule_id: str`、`rule_name: str`；抽象方法 `validate(self, report: StandardReport) -> list[Anomaly]`
  - `rules.warehouse_in.RuleR1WarehouseIn(RulePlugin)`：`rule_id="R1"`、`rule_name="违规入余数仓"`
  - R1判定条件（当前版本，可迭代）：`入库数>0 且 在线数>0 且 已产出数<需求数`；报表无"入库数"列时返回空列表（规则不适用）；证据含在线数/已产出数/需求数/入库数/入库日期

- [ ] **Step 1: 写失败测试 tests\test_rule_r1.py**

```python
import pandas as pd

from src.agent.rules.warehouse_in import RuleR1WarehouseIn
from src.agent.schema import StandardReport


def _make_report(rows):
    df = pd.DataFrame(rows)
    for c in ["需求数", "已产出数", "在线数", "入库数"]:
        df[c] = pd.to_numeric(df.get(c, pd.Series([None] * len(df))), errors="coerce")
    df["_行号"] = range(2, 2 + len(df))
    return StandardReport(report_type="综合日报", factory="珠海一厂",
                          source_path="x.csv", df=df)


def test_r1_hit_online_and_not_enough():
    report = _make_report([
        {"订单号": "A001", "批次号": "B1", "需求数": 20, "已产出数": 8,
         "在线数": 10, "入库数": 2, "入库日期": "2026-08-10"},
    ])
    anomalies = RuleR1WarehouseIn().validate(report)
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.rule_id == "R1" and a.order_id == "A001"
    assert a.evidence["在线数"] == 10 and a.evidence["需求数"] == 20
    assert a.location == "第2行"


def test_r1_pass_when_online_zero():
    report = _make_report([
        {"订单号": "A001", "需求数": 20, "已产出数": 8, "在线数": 0, "入库数": 2},
    ])
    assert RuleR1WarehouseIn().validate(report) == []


def test_r1_pass_when_produced_ge_demand():
    report = _make_report([
        {"订单号": "A001", "需求数": 20, "已产出数": 20, "在线数": 10, "入库数": 2},
    ])
    assert RuleR1WarehouseIn().validate(report) == []


def test_r1_pass_when_no_warehouse_in():
    report = _make_report([
        {"订单号": "A001", "需求数": 20, "已产出数": 8, "在线数": 10, "入库数": None},
    ])
    assert RuleR1WarehouseIn().validate(report) == []


def test_r1_skip_when_column_missing():
    report = _make_report([
        {"订单号": "A001", "需求数": 20, "已产出数": 8, "在线数": 10},
    ])
    assert RuleR1WarehouseIn().validate(report) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_rule_r1.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 src\agent\rules\base.py**

```python
"""规则插件基类：所有校验规则实现同一接口，二期可扩展为配置驱动。"""
from abc import ABC, abstractmethod

from ..schema import Anomaly, StandardReport


class RulePlugin(ABC):
    """规则插件接口。判定条件集中在本类文件中，可独立修改、独立测试。"""

    rule_id: str = ""
    rule_name: str = ""

    @abstractmethod
    def validate(self, report: StandardReport) -> list[Anomaly]:
        """对标准化报表执行判定，返回命中的异常列表。"""
```

- [ ] **Step 4: 实现 src\agent\rules\warehouse_in.py**

```python
"""R1 违规入余数仓：在线有板且订单不够数时，余数不应入库。"""
from ..schema import Anomaly, StandardReport
from .base import RulePlugin


class RuleR1WarehouseIn(RulePlugin):
    rule_id = "R1"
    rule_name = "违规入余数仓"

    def validate(self, report: StandardReport) -> list[Anomaly]:
        df = report.df
        if not {"入库数", "在线数", "已产出数", "需求数"}.issubset(df.columns):
            return []  # 该报表缺少本规则所需列，规则不适用
        mask = (
            df["入库数"].fillna(0) > 0
            & (df["在线数"].fillna(0) > 0)
            & (df["已产出数"].fillna(0) < df["需求数"].fillna(0))
        )
        anomalies = []
        for _, row in df[mask].iterrows():
            anomalies.append(Anomaly(
                rule_id=self.rule_id, rule_name=self.rule_name,
                factory=report.factory, order_id=str(row["订单号"]),
                description="在线有板且订单不够数时余数入库",
                evidence={
                    "在线数": row["在线数"], "已产出数": row["已产出数"],
                    "需求数": row["需求数"], "入库数": row["入库数"],
                    "入库日期": row.get("入库日期", ""),
                },
                location=f"第{row['_行号']}行"))
        return anomalies
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_rule_r1.py -v`
Expected: PASS（5 passed）

- [ ] **Step 6: 提交**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && git add src/agent/rules/base.py src/agent/rules/warehouse_in.py tests/test_rule_r1.py && git commit -m "feat: add rule R1 warehouse-in violation check"
```

---

### Task 5: R2 违规补投 + R3 重复补投 规则插件

**Files:**
- Create: `<ROOT>\src\agent\rules\replenish.py`
- Test: `<ROOT>\tests\test_rule_r2_r3.py`

**Interfaces:**
- Consumes: `rules.base.RulePlugin`（Task 4）、`schema.StandardReport/Anomaly`
- Produces:
  - `rules.replenish.RuleR2ReplenishWithLaterBatch(RulePlugin)`：`rule_id="R2"`、`rule_name="违规补投（有后批在线）"`
  - `rules.replenish.RuleR3DuplicateReplenish(RulePlugin)`：`rule_id="R3"`、`rule_name="重复补投（同日）"`
  - R2判定条件（当前版本）：某行 `补投数>0`，且同一订单号下存在其他批次行 `在线数>0`。证据含后批批次号列表、后批在线数列表、补投数。报表无"补投数"列时返回空列表
  - R3判定条件（当前版本）：按(订单号, 补投日期)分组，组内补投记录数>1。证据含补投日期、补投次数、行号列表

- [ ] **Step 1: 写失败测试 tests\test_rule_r2_r3.py**

```python
import pandas as pd

from src.agent.rules.replenish import RuleR2ReplenishWithLaterBatch, RuleR3DuplicateReplenish
from src.agent.schema import StandardReport


def _make_report(rows):
    df = pd.DataFrame(rows)
    for c in ["需求数", "已产出数", "在线数", "补投数"]:
        df[c] = pd.to_numeric(df.get(c, pd.Series([None] * len(df))), errors="coerce")
    df["_行号"] = range(2, 2 + len(df))
    return StandardReport(report_type="综合日报", factory="珠海一厂",
                          source_path="x.csv", df=df)


def test_r2_hit_replenish_while_later_batch_online():
    report = _make_report([
        {"订单号": "A002", "批次号": "B1", "补投数": 5, "在线数": 0, "补投日期": "2026-08-11"},
        {"订单号": "A002", "批次号": "B2", "在线数": 3},
    ])
    anomalies = RuleR2ReplenishWithLaterBatch().validate(report)
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.rule_id == "R2" and a.order_id == "A002"
    assert "B2" in a.evidence["后批批次号"]


def test_r2_pass_without_other_online_batch():
    report = _make_report([
        {"订单号": "A002", "批次号": "B1", "补投数": 5, "在线数": 0},
    ])
    assert RuleR2ReplenishWithLaterBatch().validate(report) == []


def test_r2_pass_later_batch_not_online():
    report = _make_report([
        {"订单号": "A002", "批次号": "B1", "补投数": 5, "在线数": 0},
        {"订单号": "A002", "批次号": "B2", "在线数": 0},
    ])
    assert RuleR2ReplenishWithLaterBatch().validate(report) == []


def test_r2_skip_when_column_missing():
    report = _make_report([{"订单号": "A002", "在线数": 3}])
    assert RuleR2ReplenishWithLaterBatch().validate(report) == []


def test_r3_hit_same_order_same_date_twice():
    report = _make_report([
        {"订单号": "A003", "批次号": "B1", "补投数": 4, "补投日期": "2026-08-12"},
        {"订单号": "A003", "批次号": "B2", "补投数": 2, "补投日期": "2026-08-12"},
    ])
    anomalies = RuleR3DuplicateReplenish().validate(report)
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.rule_id == "R3" and a.order_id == "A003"
    assert a.evidence["补投次数"] == 2


def test_r3_pass_different_dates():
    report = _make_report([
        {"订单号": "A003", "批次号": "B1", "补投数": 4, "补投日期": "2026-08-12"},
        {"订单号": "A003", "批次号": "B2", "补投数": 2, "补投日期": "2026-08-13"},
    ])
    assert RuleR3DuplicateReplenish().validate(report) == []


def test_r3_pass_single_replenish():
    report = _make_report([
        {"订单号": "A003", "批次号": "B1", "补投数": 4, "补投日期": "2026-08-12"},
    ])
    assert RuleR3DuplicateReplenish().validate(report) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_rule_r2_r3.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 src\agent\rules\replenish.py**

```python
"""R2 违规补投（有后批在线）与 R3 重复补投（同日）。"""
import pandas as pd

from ..schema import Anomaly, StandardReport
from .base import RulePlugin


class RuleR2ReplenishWithLaterBatch(RulePlugin):
    rule_id = "R2"
    rule_name = "违规补投（有后批在线）"

    def validate(self, report: StandardReport) -> list[Anomaly]:
        df = report.df
        if not {"补投数", "批次号", "在线数"}.issubset(df.columns):
            return []
        replenished = df[df["补投数"].fillna(0) > 0]
        anomalies = []
        for _, row in replenished.iterrows():
            others = df[
                (df["订单号"] == row["订单号"])
                & (df["批次号"] != row["批次号"])
                & (df["在线数"].fillna(0) > 0)
            ]
            if others.empty:
                continue
            anomalies.append(Anomaly(
                rule_id=self.rule_id, rule_name=self.rule_name,
                factory=report.factory, order_id=str(row["订单号"]),
                description="有后批在线时补投（应等待后批产出后再判定是否补投）",
                evidence={
                    "补投数": row["补投数"],
                    "补投日期": row.get("补投日期", ""),
                    "后批批次号": others["批次号"].astype(str).tolist(),
                    "后批在线数": others["在线数"].tolist(),
                },
                location=f"第{row['_行号']}行"))
        return anomalies


class RuleR3DuplicateReplenish(RulePlugin):
    rule_id = "R3"
    rule_name = "重复补投（同日）"

    def validate(self, report: StandardReport) -> list[Anomaly]:
        df = report.df
        if "补投数" not in df.columns or "补投日期" not in df.columns:
            return []
        rep = df[df["补投数"].fillna(0) > 0]
        if rep.empty:
            return []
        dup_mask = rep.duplicated(subset=["订单号", "补投日期"], keep=False)
        anomalies = []
        for (order_id, date), grp in rep[dup_mask].groupby(["订单号", "补投日期"]):
            anomalies.append(Anomaly(
                rule_id=self.rule_id, rule_name=self.rule_name,
                factory=report.factory, order_id=str(order_id),
                description="同一订单当天重复补投",
                evidence={
                    "补投日期": str(date),
                    "补投次数": int(len(grp)),
                    "行号": grp["_行号"].astype(int).tolist(),
                },
                location=f"第{grp['_行号'].astype(int).tolist()}行"))
        return anomalies
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_rule_r2_r3.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && git add src/agent/rules/replenish.py tests/test_rule_r2_r3.py && git commit -m "feat: add rule R2 replenish-with-later-batch and R3 duplicate-replenish checks"
```

---

### Task 6: R4 违规报废 规则插件

**Files:**
- Create: `<ROOT>\src\agent\rules\scrap.py`
- Test: `<ROOT>\tests\test_rule_r4.py`

**Interfaces:**
- Consumes: `rules.base.RulePlugin`（Task 4）、`schema.StandardReport/Anomaly`
- Produces:
  - `rules.scrap.RuleR4ScrapWithOnlineBoards(RulePlugin)`：`rule_id="R4"`、`rule_name="违规报废（在线仍有可用板）"`
  - R4判定条件（当前版本）：`报废数>0 且 在线数>0`；报表无"报废数"列时返回空列表；证据含在线数/报废数/报废日期

- [ ] **Step 1: 写失败测试 tests\test_rule_r4.py**

```python
import pandas as pd

from src.agent.rules.scrap import RuleR4ScrapWithOnlineBoards
from src.agent.schema import StandardReport


def _make_report(rows):
    df = pd.DataFrame(rows)
    for c in ["需求数", "已产出数", "在线数", "报废数"]:
        df[c] = pd.to_numeric(df.get(c, pd.Series([None] * len(df))), errors="coerce")
    df["_行号"] = range(2, 2 + len(df))
    return StandardReport(report_type="综合日报", factory="珠海一厂",
                          source_path="x.csv", df=df)


def test_r4_hit_scrap_while_online_boards_exist():
    report = _make_report([
        {"订单号": "A004", "批次号": "B1", "需求数": 10, "已产出数": 5,
         "在线数": 4, "报废数": 3, "报废日期": "2026-08-13"},
    ])
    anomalies = RuleR4ScrapWithOnlineBoards().validate(report)
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.rule_id == "R4" and a.order_id == "A004"
    assert a.evidence["在线数"] == 4 and a.evidence["报废数"] == 3


def test_r4_pass_no_scrap():
    report = _make_report([
        {"订单号": "A004", "在线数": 4, "报废数": None},
    ])
    assert RuleR4ScrapWithOnlineBoards().validate(report) == []


def test_r4_pass_no_online_boards():
    report = _make_report([
        {"订单号": "A004", "在线数": 0, "报废数": 3},
    ])
    assert RuleR4ScrapWithOnlineBoards().validate(report) == []


def test_r4_skip_when_column_missing():
    report = _make_report([{"订单号": "A004", "在线数": 4}])
    assert RuleR4ScrapWithOnlineBoards().validate(report) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_rule_r4.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 src\agent\rules\scrap.py**

```python
"""R4 违规报废：在线仍有可用板时提前报废。"""
from ..schema import Anomaly, StandardReport
from .base import RulePlugin


class RuleR4ScrapWithOnlineBoards(RulePlugin):
    rule_id = "R4"
    rule_name = "违规报废（在线仍有可用板）"

    def validate(self, report: StandardReport) -> list[Anomaly]:
        df = report.df
        if not {"报废数", "在线数"}.issubset(df.columns):
            return []
        mask = (df["报废数"].fillna(0) > 0) & (df["在线数"].fillna(0) > 0)
        anomalies = []
        for _, row in df[mask].iterrows():
            anomalies.append(Anomaly(
                rule_id=self.rule_id, rule_name=self.rule_name,
                factory=report.factory, order_id=str(row["订单号"]),
                description="在线仍有可用板时提前报废（本可继续使用的余数被报废）",
                evidence={
                    "在线数": row["在线数"], "报废数": row["报废数"],
                    "报废日期": row.get("报废日期", ""),
                },
                location=f"第{row['_行号']}行"))
        return anomalies
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_rule_r4.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && git add src/agent/rules/scrap.py tests/test_rule_r4.py && git commit -m "feat: add rule R4 scrap-with-online-boards check"
```

---

### Task 7: 校验引擎 engine.py（注册/执行/错误隔离/去重）

**Files:**
- Create: `<ROOT>\src\agent\engine.py`
- Test: `<ROOT>\tests\test_engine.py`

**Interfaces:**
- Consumes: `rules.base.RulePlugin`（Task 4）、各规则类（Task 4-6）、`schema`
- Produces:
  - `class ValidationEngine:`
    - `__init__(self)`：`self.rules: list`、`self.errors: list`（每项为 `{"rule_id": str, "error": str}`）
    - `register(self, rule: RulePlugin) -> ValidationEngine`（链式）
    - `run(self, report: StandardReport) -> list[Anomaly]`：逐条执行规则；单条规则抛异常时记入errors、其余规则继续；返回去重后的异常
    - `@staticmethod dedupe(anomalies: list[Anomaly]) -> list[Anomaly]`：按(rule_id, order_id, description)去重

- [ ] **Step 1: 写失败测试 tests\test_engine.py**

```python
import pandas as pd

from src.agent.engine import ValidationEngine
from src.agent.rules.base import RulePlugin
from src.agent.rules.warehouse_in import RuleR1WarehouseIn
from src.agent.schema import Anomaly, StandardReport


class AlwaysHitRule(RulePlugin):
    rule_id = "T1"
    rule_name = "测试规则"

    def validate(self, report):
        return [Anomaly(rule_id=self.rule_id, rule_name=self.rule_name,
                        factory=report.factory, order_id="A001",
                        description="命中")]


class BadRule(RulePlugin):
    rule_id = "BAD"
    rule_name = "会报错的规则"

    def validate(self, report):
        raise RuntimeError("boom")


def _make_report():
    df = pd.DataFrame([
        {"订单号": "A001", "需求数": 20, "已产出数": 8, "在线数": 10,
         "入库数": 2, "入库日期": "2026-08-10"},
    ])
    df["需求数"] = pd.to_numeric(df["需求数"]); df["已产出数"] = pd.to_numeric(df["已产出数"])
    df["在线数"] = pd.to_numeric(df["在线数"]); df["入库数"] = pd.to_numeric(df["入库数"])
    df["_行号"] = [2]
    return StandardReport(report_type="综合日报", factory="珠海一厂",
                          source_path="x.csv", df=df)


def test_engine_runs_registered_rules():
    engine = ValidationEngine().register(RuleR1WarehouseIn()).register(AlwaysHitRule())
    anomalies = engine.run(_make_report())
    assert len(anomalies) == 2
    assert {a.rule_id for a in anomalies} == {"R1", "T1"}
    assert engine.errors == []


def test_engine_isolates_rule_failure():
    engine = ValidationEngine().register(BadRule()).register(AlwaysHitRule())
    anomalies = engine.run(_make_report())
    assert len(anomalies) == 1 and anomalies[0].rule_id == "T1"
    assert len(engine.errors) == 1
    assert engine.errors[0]["rule_id"] == "BAD"


def test_dedupe_identical_anomalies():
    a1 = Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="珠海一厂",
                 order_id="A001", description="x")
    a2 = Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="珠海一厂",
                 order_id="A001", description="x")
    a3 = Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="珠海一厂",
                 order_id="A002", description="x")
    result = ValidationEngine.dedupe([a1, a2, a3])
    assert len(result) == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_engine.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 src\agent\engine.py**

```python
"""校验引擎：注册规则插件、执行校验、错误隔离、异常去重。"""
from .rules.base import RulePlugin
from .schema import Anomaly, StandardReport


class ValidationEngine:
    def __init__(self):
        self.rules: list = []
        self.errors: list = []  # [{"rule_id": str, "error": str}]

    def register(self, rule: RulePlugin) -> "ValidationEngine":
        self.rules.append(rule)
        return self

    def run(self, report: StandardReport) -> list[Anomaly]:
        anomalies = []
        for rule in self.rules:
            try:
                anomalies.extend(rule.validate(report))
            except Exception as e:  # 单条规则失败不影响其余规则（插件隔离性）
                self.errors.append({"rule_id": getattr(rule, "rule_id", "?"),
                                    "error": str(e)})
        return self.dedupe(anomalies)

    @staticmethod
    def dedupe(anomalies: list[Anomaly]) -> list[Anomaly]:
        seen, out = set(), []
        for a in anomalies:
            key = (a.rule_id, a.order_id, a.description)
            if key not in seen:
                seen.add(key)
                out.append(a)
        return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_engine.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && git add src/agent/engine.py tests/test_engine.py && git commit -m "feat: add validation engine with rule isolation and dedupe"
```

---

### Task 8: 执行日志 trace/tracer.py

**Files:**
- Create: `<ROOT>\src\agent\trace\tracer.py`
- Test: `<ROOT>\tests\test_tracer.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `class Tracer:`
    - `__init__(self, trace_dir)` —— 目录不存在则创建；生成文件 `trace_YYYYmmdd_HHMMSS.jsonl`
    - `file: Path` —— 当前日志文件
    - `log(self, step: str, status: str, detail: dict)` —— 追加一行JSON，含 `ts`（时间戳字符串）、`step`、`status`、`detail`；中文不转义

- [ ] **Step 1: 写失败测试 tests\test_tracer.py**

```python
import json

from src.agent.trace.tracer import Tracer


def test_tracer_appends_jsonl_lines(tmp_path):
    t = Tracer(tmp_path)
    t.log("parse", "ok", {"rows": 3})
    t.log("validate", "fail", {"rule_id": "BAD", "error": "boom"})
    lines = t.file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["step"] == "parse" and first["status"] == "ok"
    assert first["detail"]["rows"] == 3
    assert "ts" in first
    second = json.loads(lines[1])
    assert second["detail"]["error"] == "boom"
    assert "违规" not in t.file.read_text(encoding="ascii", errors="ignore")  # 中文保留为UTF-8原文


def test_tracer_creates_dir_and_names_file():
    t = Tracer(tmp_path / "nested" / "dir")
    assert t.file.exists()
    assert t.file.name.startswith("trace_") and t.file.name.endswith(".jsonl")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_tracer.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 src\agent\trace\tracer.py**

```python
"""执行日志溯源：每次校验的每个步骤写入JSONL，可回溯排查。"""
import json
import time
from pathlib import Path


class Tracer:
    def __init__(self, trace_dir):
        self.trace_dir = Path(trace_dir)
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.file = self.trace_dir / f"trace_{stamp}.jsonl"

    def log(self, step: str, status: str, detail: dict):
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "step": step,
            "status": status,
            "detail": detail,
        }
        with open(self.file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_tracer.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && git add src/agent/trace/tracer.py tests/test_tracer.py && git commit -m "feat: add JSONL execution tracer"
```

---

### Task 9: LLM层（client适配 + 脱敏 + 归因）

**Files:**
- Create: `<ROOT>\src\agent\llm\client.py`
- Create: `<ROOT>\src\agent\llm\desensitize.py`
- Create: `<ROOT>\src\agent\llm\attribution.py`
- Test: `<ROOT>\tests\test_llm.py`

**Interfaces:**
- Consumes: `schema.Anomaly/StandardReport`（Task 1）
- Produces:
  - `client.LLMClient(ABC)`：`chat(self, messages: list) -> str`
  - `client.MockLLMClient(LLMClient)`：无API密钥时跑通链路，返回50条固定归因JSON
  - `client.OpenAICompatClient(LLMClient)`：`__init__(self, base_url: str, api_key: str, model: str, timeout: int = 60)`；POST `{base_url}/chat/completions`，返回 `choices[0].message.content`
  - `desensitize.desensitize_text(value, prefix: str, mapping: dict) -> str`：MD5前8位+序号代号
  - `desensitize.desensitize_report(report: StandardReport, mapping: dict | None = None) -> tuple[pd.DataFrame, dict]`：对"客户""产品料号"列脱敏，返回(脱敏后df, 映射表)
  - `attribution.Attribution(order_id, rule_id, category, explanation, suggestion)` dataclass
  - `attribution.ATTRIBUTION_CATEGORIES = ["违规行为", "流程不清", "人员偏差", "系统漏洞", "数据错误"]`
  - `attribution.build_prompt(anomalies: list[Anomaly]) -> str`
  - `attribution.parse_json_response(text: str) -> list`：从模型回复提取JSON数组
  - `attribution.attribute_anomalies(anomalies, client: LLMClient) -> list[Attribution]`：类别不在列表内钳制为"其他"；条目缺失时用fallback（"未归因"）

- [ ] **Step 1: 写失败测试 tests\test_llm.py**

```python
import json
import pandas as pd

from src.agent.llm.attribution import (
    ATTRIBUTION_CATEGORIES, attribute_anomalies, build_prompt, parse_json_response)
from src.agent.llm.client import MockLLMClient
from src.agent.llm.desensitize import desensitize_report, desensitize_text
from src.agent.schema import Anomaly, StandardReport


def _make_anomalies():
    return [
        Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="珠海一厂",
                order_id="A001", description="在线有板且订单不够数时余数入库",
                evidence={"在线数": 10, "需求数": 20}),
        Anomaly(rule_id="R3", rule_name="重复补投（同日）", factory="珠海一厂",
                order_id="A003", description="同一订单当天重复补投",
                evidence={"补投次数": 2}),
    ]


def test_desensitize_stable_and_distinct():
    m = {}
    assert desensitize_text("客户甲", "客户", m) == desensitize_text("客户甲", "客户", m)
    assert desensitize_text("客户乙", "客户", m) != desensitize_text("客户甲", "客户", m)
    assert "客户甲" not in desensitize_text("客户甲", "客户", m)


def test_desensitize_report_masks_customer_and_part():
    df = pd.DataFrame({"订单号": ["A001"], "客户": ["客户甲"], "产品料号": ["PN-001"]})
    report = StandardReport(report_type="综合日报", factory="珠海一厂",
                            source_path="x.csv", df=df)
    safe_df, mapping = desensitize_report(report)
    assert safe_df.loc[0, "客户"] != "客户甲"
    assert safe_df.loc[0, "产品料号"] != "PN-001"
    assert len(mapping) == 2


def test_build_prompt_contains_evidence():
    prompt = build_prompt(_make_anomalies())
    assert "R1" in prompt and "在线数" in prompt and "补投次数" in prompt


def test_parse_json_response_extracts_array():
    text = "好的，结果如下：\n```json\n[{\"category\": \"违规行为\", \"explanation\": \"a\", \"suggestion\": \"b\"}]\n```"
    parsed = parse_json_response(text)
    assert isinstance(parsed, list) and parsed[0]["category"] == "违规行为"


def test_parse_json_response_raises_on_garbage():
    import pytest
    with pytest.raises(ValueError):
        parse_json_response("这不是JSON")


def test_attribute_anomalies_with_mock():
    attrs = attribute_anomalies(_make_anomalies(), MockLLMClient())
    assert len(attrs) == 2
    assert all(a.order_id in {"A001", "A003"} for a in attrs)
    assert all(a.rule_id in {"R1", "R3"} for a in attrs)
    assert attrs[0].category in ATTRIBUTION_CATEGORIES + ["其他"]


def test_attribute_clamps_unknown_category():
    class WeirdClient:
        def chat(self, messages):
            return json.dumps([{"category": "外星原因", "explanation": "x", "suggestion": "y"}],
                              ensure_ascii=False)
    attrs = attribute_anomalies(_make_anomalies(), WeirdClient())
    assert attrs[0].category == "其他"


def test_attribute_fallback_when_entries_missing():
    class EmptyClient:
        def chat(self, messages):
            return "[]"
    attrs = attribute_anomalies(_make_anomalies(), EmptyClient())
    assert len(attrs) == 2
    assert attrs[0].category == "未归因"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_llm.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 src\agent\llm\client.py**

```python
"""LLM调用客户端：统一OpenAI兼容接口，DeepSeek/Claude/harness均可对接。"""
import json
from abc import ABC, abstractmethod

import requests


class LLMClient(ABC):
    @abstractmethod
    def chat(self, messages: list) -> str:
        """输入messages列表，返回模型回复文本。"""


class MockLLMClient(LLMClient):
    """无API密钥/未配置harness时使用：返回固定格式归因，用于跑通全链路。"""

    def chat(self, messages: list) -> str:
        items = [{
            "category": "违规行为",
            "explanation": "（模拟归因）接入真实API或DeepSeek-Harness后生成完整分析。",
            "suggestion": "通报工厂核实并纠正。",
        }] * 50
        return json.dumps(items, ensure_ascii=False)


class OpenAICompatClient(LLMClient):
    """OpenAI兼容接口：DeepSeek(deepseek-chat)、Claude(经兼容网关)均可用。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def chat(self, messages: list) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {"model": self.model, "messages": messages}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
```

- [ ] **Step 4: 实现 src\agent\llm\desensitize.py**

```python
"""数据脱敏层：敏感字段替换为代号后再发外部API（合规要求，fail-closed）。"""
import hashlib

import pandas as pd

from ..schema import StandardReport

# 需要脱敏的列
SENSITIVE_COLUMNS = ("客户", "产品料号")


def desensitize_text(value, prefix: str, mapping: dict) -> str:
    """同一原文稳定映射到同一代号；不同原文代号不同。"""
    key = f"{prefix}:{value}"
    if key not in mapping:
        digest = hashlib.md5(str(value).encode("utf-8")).hexdigest()[:8]
        mapping[key] = f"{prefix}_{len(mapping) + 1}_{digest}"
    return mapping[key]


def desensitize_report(report: StandardReport, mapping: dict | None = None):
    """返回(脱敏后的DataFrame副本, 映射表)。映射表保留在本地用于回溯。"""
    mapping = mapping if mapping is not None else {}
    df = report.df.copy()
    for col in SENSITIVE_COLUMNS:
        if col in df.columns:
            df[col] = df[col].map(
                lambda v, c=col: desensitize_text(v, c, mapping) if pd.notna(v) else v)
    return df, mapping
```

- [ ] **Step 5: 实现 src\agent\llm\attribution.py**

```python
"""LLM归因：对规则命中的异常生成归因分类、归因说明、整改建议。"""
import json
import re
from dataclasses import dataclass

from ..schema import Anomaly
from .client import LLMClient

ATTRIBUTION_CATEGORIES = ["违规行为", "流程不清", "人员偏差", "系统漏洞", "数据错误"]


@dataclass
class Attribution:
    order_id: str
    rule_id: str
    category: str
    explanation: str
    suggestion: str


def build_prompt(anomalies: list[Anomaly]) -> str:
    lines = []
    for i, a in enumerate(anomalies):
        evidence = json.dumps(a.evidence, ensure_ascii=False, default=str)
        lines.append(f"{i + 1}. 规则{a.rule_id}「{a.rule_name}」：{a.description}；证据：{evidence}")
    return (
        "你是PCB工厂投料管理稽查助手。以下是通过规则引擎校验出的异常项，"
        "请逐条归因，并仅输出一个JSON数组（不要输出其他文字）：\n"
        + "\n".join(lines)
        + "\n每条格式：{\"order_id\": \"订单号\", \"rule_id\": \"规则编号\", "
        "\"category\": \"违规行为|流程不清|人员偏差|系统漏洞|数据错误\", "
        "\"explanation\": \"结合投料-在线-入库-报废数据链路的解读\", "
        "\"suggestion\": \"针对性整改建议\"}"
    )


def parse_json_response(text: str) -> list:
    """从模型回复中提取JSON数组（容忍```json代码块围栏等包装）。"""
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        raise ValueError(f"模型回复中未找到JSON数组: {text[:200]}")
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON解析失败: {e}；原文: {text[:200]}")
    if not isinstance(parsed, list):
        raise ValueError(f"期望JSON数组，实际为: {type(parsed)}")
    return parsed


def attribute_anomalies(anomalies: list[Anomaly], client: LLMClient) -> list[Attribution]:
    """批量调用LLM归因。类别非法钳制为'其他'；条目缺失用fallback，不中断。"""
    if not anomalies:
        return []
    prompt = build_prompt(anomalies)
    try:
        response = client.chat([{"role": "user", "content": prompt}])
        parsed = parse_json_response(response)
    except Exception:
        parsed = []  # 模型不可用：整体降级为未归因，报告仍输出规则判定
    attributions = []
    for i, a in enumerate(anomalies):
        item = parsed[i] if i < len(parsed) and isinstance(parsed[i], dict) else None
        if item and item.get("category"):
            category = str(item["category"])
            if category not in ATTRIBUTION_CATEGORIES:
                category = "其他"
            attributions.append(Attribution(
                order_id=a.order_id, rule_id=a.rule_id, category=category,
                explanation=str(item.get("explanation", "")),
                suggestion=str(item.get("suggestion", ""))))
        else:
            attributions.append(Attribution(
                order_id=a.order_id, rule_id=a.rule_id, category="未归因",
                explanation="模型未返回有效归因，请人工复核。",
                suggestion="人工复核异常项。"))
    return attributions
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_llm.py -v`
Expected: PASS（8 passed）

- [ ] **Step 7: 提交**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && git add src/agent/llm/client.py src/agent/llm/desensitize.py src/agent/llm/attribution.py tests/test_llm.py && git commit -m "feat: add LLM layer (client adapter, desensitization, attribution)"
```

---

### Task 10: 报告生成 reporting/report_writer.py

**Files:**
- Create: `<ROOT>\src\agent\reporting\report_writer.py`
- Test: `<ROOT>\tests\test_report_writer.py`

**Interfaces:**
- Consumes: `schema.Anomaly`、`attribution.Attribution`（Task 9）
- Produces:
  - `write_excel_report(anomalies: list[Anomaly], attributions: list[Attribution], output_path: str) -> str` —— 两个sheet："异常明细"（列：序号/工厂/订单号/规则编号/规则名称/异常描述/位置/证据/归因分类/归因说明/整改建议）、"汇总统计"（按规则编号计数+按工厂计数）；返回output_path
  - `write_markdown_summary(anomalies, attributions, output_path: str) -> str` —— 摘要：数据行数由调用方不传，仅含异常统计与明细；返回output_path
  - 归因匹配键：`(Attribution.order_id, Attribution.rule_id)`；无归因时该列填"—"

- [ ] **Step 1: 写失败测试 tests\test_report_writer.py**

```python
import pandas as pd

from src.agent.llm.attribution import Attribution
from src.agent.reporting.report_writer import write_excel_report, write_markdown_summary
from src.agent.schema import Anomaly


def _make_data():
    anomalies = [
        Anomaly(rule_id="R1", rule_name="违规入余数仓", factory="珠海一厂",
                order_id="A001", description="在线有板且订单不够数时余数入库",
                evidence={"在线数": 10, "需求数": 20}, location="第2行"),
        Anomaly(rule_id="R3", rule_name="重复补投（同日）", factory="珠海一厂",
                order_id="A003", description="同一订单当天重复补投",
                evidence={"补投次数": 2}, location="第4行"),
    ]
    attributions = [
        Attribution(order_id="A001", rule_id="R1", category="违规行为",
                    explanation="入库时在线10块且未达需求数", suggestion="通报工厂纠正"),
    ]
    return anomalies, attributions


def test_excel_report_two_sheets_and_columns(tmp_path):
    anomalies, attributions = _make_data()
    out = str(tmp_path / "报告.xlsx")
    assert write_excel_report(anomalies, attributions, out) == out
    detail = pd.read_excel(out, sheet_name="异常明细")
    assert list(detail.columns)[:4] == ["序号", "工厂", "订单号", "规则编号"]
    assert len(detail) == 2
    assert detail.loc[0, "归因分类"] == "违规行为"
    assert detail.loc[1, "归因分类"] == "—"  # 无归因时占位
    summary = pd.read_excel(out, sheet_name="汇总统计")
    assert not summary.empty


def test_markdown_summary_contains_rules(tmp_path):
    anomalies, attributions = _make_data()
    out = str(tmp_path / "摘要.md")
    assert write_markdown_summary(anomalies, attributions, out) == out
    text = open(out, encoding="utf-8").read()
    assert "R1" in text and "违规入余数仓" in text and "珠海一厂" in text


def test_empty_anomalies_still_writes(tmp_path):
    out = str(tmp_path / "空.xlsx")
    write_excel_report([], [], out)
    detail = pd.read_excel(out, sheet_name="异常明细")
    assert len(detail) == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_report_writer.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 src\agent\reporting\report_writer.py**

```python
"""异常报告生成：Excel（异常明细+汇总统计）与Markdown摘要。"""
import json

import pandas as pd

from ..llm.attribution import Attribution
from ..schema import Anomaly

DETAIL_COLUMNS = ["序号", "工厂", "订单号", "规则编号", "规则名称", "异常描述",
                  "位置", "证据", "归因分类", "归因说明", "整改建议"]


def _attribution_map(attributions: list[Attribution]) -> dict:
    return {(a.order_id, a.rule_id): a for a in attributions}


def write_excel_report(anomalies: list[Anomaly], attributions: list[Attribution],
                       output_path: str) -> str:
    attr = _attribution_map(attributions)
    rows = []
    for i, an in enumerate(anomalies, 1):
        a = attr.get((an.order_id, an.rule_id))
        rows.append({
            "序号": i, "工厂": an.factory, "订单号": an.order_id,
            "规则编号": an.rule_id, "规则名称": an.rule_name,
            "异常描述": an.description, "位置": an.location,
            "证据": json.dumps(an.evidence, ensure_ascii=False, default=str),
            "归因分类": a.category if a else "—",
            "归因说明": a.explanation if a else "—",
            "整改建议": a.suggestion if a else "—",
        })
    detail_df = pd.DataFrame(rows, columns=DETAIL_COLUMNS)

    by_rule = pd.DataFrame(
        {"规则编号": [a.rule_id for a in anomalies],
         "规则名称": [a.rule_name for a in anomalies]}) \
        .groupby(["规则编号", "规则名称"], as_index=False).size() \
        .rename(columns={"size": "异常数"}) if anomalies else pd.DataFrame(
        columns=["规则编号", "规则名称", "异常数"])
    by_factory = pd.DataFrame({"工厂": [a.factory for a in anomalies]}) \
        .groupby("工厂", as_index=False).size() \
        .rename(columns={"size": "异常数"}) if anomalies else pd.DataFrame(
        columns=["工厂", "异常数"])

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        detail_df.to_excel(writer, sheet_name="异常明细", index=False)
        by_rule.to_excel(writer, sheet_name="汇总统计", index=False, startrow=0)
        by_factory.to_excel(writer, sheet_name="汇总统计", index=False,
                            startrow=len(by_rule) + 3)
    return output_path


def write_markdown_summary(anomalies: list[Anomaly], attributions: list[Attribution],
                           output_path: str) -> str:
    attr = _attribution_map(attributions)
    lines = ["# 校验摘要", "",
             f"- 异常总数：{len(anomalies)}", ""]
    lines.append("## 异常明细")
    if anomalies:
        for i, an in enumerate(anomalies, 1):
            a = attr.get((an.order_id, an.rule_id))
            category = a.category if a else "未归因"
            lines.append(f"{i}. 【{an.rule_id}·{category}】{an.factory} "
                         f"订单{an.order_id}：{an.description}（{an.location}）")
            if a:
                lines.append(f"   - 归因：{a.explanation}")
                lines.append(f"   - 建议：{a.suggestion}")
    else:
        lines.append("无异常。")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return output_path
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_report_writer.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && git add src/agent/reporting/report_writer.py tests/test_report_writer.py && git commit -m "feat: add Excel and Markdown anomaly report writers"
```

---

### Task 11: CLI入口 main.py + 样例数据 + 端到端烟雾测试

**Files:**
- Create: `<ROOT>\main.py`（替换PyCharm默认示例）
- Create: `<ROOT>\data\samples\综合日报.csv`（样例，含R1~R4各一条命中）
- Test: `<ROOT>\tests\test_cli_e2e.py`

**Interfaces:**
- Consumes: Tasks 1-10全部
- Produces:
  - `main.build_engine() -> ValidationEngine` —— 注册R1~R4
  - `main.main(argv=None) -> int` —— 退出码：0成功 / 2解析失败
  - CLI参数：`report_path`（必填）、`--工厂/--factory`（必填）、`--类型/--type`（必填，choices=REPORT_TYPES）、`--输出目录/--output-dir`（可选）、`--trace-dir`（可选，默认settings）、`--mock-llm`（flag）
  - 流程：parse → validate（D0+规则异常合并）→ 脱敏 → 归因（无密钥且非mock则跳过归因并警告）→ Excel+MD报告 → 控制台摘要

- [ ] **Step 1: 创建样例数据 data\samples\综合日报.csv**

文件内容（UTF-8，无BOM；留空字段为空）：

```
订单号,批次号,产品料号,客户,需求数,已产出数,在线数,补投数,补投日期,入库数,入库日期,报废数,报废日期,工厂
A001,B1,PN-001,客户甲,20,8,10,,,2,2026-08-10,,,珠海一厂
A002,B1,PN-002,客户乙,30,30,0,5,2026-08-11,,,,,珠海一厂
A002,B2,PN-002,客户乙,30,30,3,,,,,,,珠海一厂
A003,B1,PN-003,客户丙,15,15,0,4,2026-08-12,,,,,珠海一厂
A003,B2,PN-003,客户丙,15,15,0,2,2026-08-12,,,,,珠海一厂
A004,B1,PN-004,客户丁,10,5,4,,,,,3,2026-08-13,珠海一厂
```

预期：A001→R1；A002（B1补投且B2在线）→R2；A003同日两次补投→R3；A004在线+报废→R4。共4条异常。

- [ ] **Step 2: 写失败测试 tests\test_cli_e2e.py**

```python
import subprocess
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = PROJECT_ROOT / "data" / "samples" / "综合日报.csv"


def _run_main(args, tmp_path):
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"),
         str(SAMPLE), "--工厂", "珠海一厂", "--类型", "综合日报",
         "--输出目录", str(tmp_path / "out"), "--trace-dir", str(tmp_path / "traces"),
         "--mock-llm"] + args,
        capture_output=True, text=True, encoding="utf-8", timeout=120,
        cwd=str(PROJECT_ROOT))
    return result


def test_cli_end_to_end_full_pipeline(tmp_path):
    result = _run_main([], tmp_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "校验完成" in result.stdout
    assert "异常 4" in result.stdout

    excel_files = list((tmp_path / "out").glob("异常校验报告*.xlsx"))
    md_files = list((tmp_path / "out").glob("校验摘要*.md"))
    assert len(excel_files) == 1 and len(md_files) == 1

    detail = pd.read_excel(excel_files[0], sheet_name="异常明细")
    assert set(detail["规则编号"]) == {"R1", "R2", "R3", "R4"}
    assert detail.loc[0, "证据"]  # 证据已序列化

    md_text = md_files[0].read_text(encoding="utf-8")
    assert "R1" in md_text and "R4" in md_text

    trace_files = list((tmp_path / "traces").glob("trace_*.jsonl"))
    assert len(trace_files) == 1
    lines = trace_files[0].read_text(encoding="utf-8").strip().splitlines()
    steps = [line.split('"step": "')[1].split('"')[0] for line in lines]
    for step in ("parse", "validate", "attribute", "report"):
        assert step in steps, f"日志缺少步骤 {step}"


def test_cli_parse_error_exit_code_2(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("备注\nxxx\n", encoding="utf-8-sig")
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"),
         str(bad), "--工厂", "珠海一厂", "--类型", "综合日报",
         "--输出目录", str(tmp_path / "out"), "--trace-dir", str(tmp_path / "traces")],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
        cwd=str(PROJECT_ROOT))
    assert result.returncode == 2
    assert "无法识别订单号字段" in result.stdout
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_cli_e2e.py -v`
Expected: FAIL（`main.py` 还是PyCharm示例脚本，找不到main函数）

- [ ] **Step 4: 实现 main.py（覆盖PyCharm默认示例）**

```python
"""PCB生产预投业务数据校验Agent —— CLI入口。

用法:
    python main.py 综合日报.csv --工厂 珠海一厂 --类型 综合日报 --mock-llm
"""
import argparse
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Windows控制台中文输出

from src.agent.config import PROJECT_ROOT, load_field_mapping, load_settings, resolve_api_key
from src.agent.engine import ValidationEngine
from src.agent.llm.attribution import attribute_anomalies
from src.agent.llm.client import LLMClient, MockLLMClient, OpenAICompatClient
from src.agent.llm.desensitize import desensitize_report
from src.agent.parsers.report_parser import ReportParseError, ReportParser
from src.agent.reporting.report_writer import write_excel_report, write_markdown_summary
from src.agent.rules.replenish import RuleR2ReplenishWithLaterBatch, RuleR3DuplicateReplenish
from src.agent.rules.scrap import RuleR4ScrapWithOnlineBoards
from src.agent.rules.warehouse_in import RuleR1WarehouseIn
from src.agent.schema import REPORT_TYPES
from src.agent.trace.tracer import Tracer


def build_engine() -> ValidationEngine:
    engine = ValidationEngine()
    engine.register(RuleR1WarehouseIn())
    engine.register(RuleR2ReplenishWithLaterBatch())
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
    parser.add_argument("report_path", help="报表文件路径（.xlsx/.xls/.csv）")
    parser.add_argument("--工厂", "--factory", dest="factory", required=True, help="工厂名，如 珠海一厂")
    parser.add_argument("--类型", "--type", dest="report_type", required=True,
                        choices=REPORT_TYPES, help="报表类型")
    parser.add_argument("--输出目录", "--output-dir", dest="output_dir", default=None)
    parser.add_argument("--trace-dir", dest="trace_dir", default=None)
    parser.add_argument("--mock-llm", action="store_true", help="用MockLLM跑通链路（无API密钥时）")
    args = parser.parse_args(argv)

    settings = load_settings()
    tracer = Tracer(args.trace_dir or (PROJECT_ROOT / settings["trace"]["dir"]))

    # 1) 解析
    t0 = time.perf_counter()
    try:
        report = ReportParser(load_field_mapping()).parse(
            args.report_path, args.factory, args.report_type)
    except ReportParseError as e:
        tracer.log("parse", "fail", {"error": str(e)})
        print(f"[错误] {e}")
        return 2
    tracer.log("parse", "ok", {
        "rows": len(report.df), "quality_issues": len(report.quality_issues),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000)})

    # 2) 校验（数据质量问题D0 + 规则异常）
    engine = build_engine()
    anomalies = list(report.quality_issues) + engine.run(report)
    for err in engine.errors:
        tracer.log("validate", "fail", err)
    tracer.log("validate", "ok", {
        "anomalies": len(anomalies), "rule_errors": len(engine.errors)})

    # 3) 脱敏 + LLM归因
    desensitize_report(report)  # 生成映射表；归因提示词不含客户/料号列，无需传脱敏后df
    client = _build_llm_client(settings, args.mock_llm)
    if client is None:
        print("[警告] 未配置API密钥，跳过LLM归因（报告仅含规则判定与证据）")
        attributions = []
    else:
        attributions = attribute_anomalies(anomalies, client)
    tracer.log("attribute", "ok", {"count": len(attributions)})

    # 4) 报告输出
    out_dir = Path(args.output_dir) if args.output_dir else (PROJECT_ROOT / settings["output"]["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    excel_path = write_excel_report(
        anomalies, attributions, str(out_dir / f"异常校验报告_{args.factory}_{stamp}.xlsx"))
    md_path = write_markdown_summary(
        anomalies, attributions, str(out_dir / f"校验摘要_{args.factory}_{stamp}.md"))
    tracer.log("report", "ok", {"excel": excel_path, "markdown": md_path})

    print(f"校验完成：数据 {len(report.df)} 行，数据质量问题 {len(report.quality_issues)}，"
          f"异常 {len(anomalies)}，归因 {len(attributions)}")
    print(f"Excel报告: {excel_path}")
    print(f"摘要: {md_path}")
    print(f"执行日志: {tracer.file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest tests\test_cli_e2e.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: 手动冒烟运行（PyCharm里也可直接运行main.py）**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python main.py "data/samples/综合日报.csv" --工厂 珠海一厂 --类型 综合日报 --mock-llm`
Expected: 控制台输出"校验完成：数据 6 行，数据质量问题 0，异常 4，归因 4"，`output\` 下生成Excel与MD文件，`logs\traces\` 下生成JSONL

- [ ] **Step 7: 全量回归 + 提交**

Run: `cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && python -m pytest -v`
Expected: 全部通过（约39个测试）

```bash
cd "D:/Python/Claude Code/Programs/PCB生产预投业务数据校验Agent" && git add main.py data/samples/综合日报.csv tests/test_cli_e2e.py && git commit -m "feat: add CLI entry and end-to-end smoke test"
```

---

## 完成后验收对照（对应Spec成功标准）

| Spec要求 | 落地位置 | 验证方式 |
|---|---|---|
| 报表自动解析清洗（字段识别、数据质检） | Task 3 parsers | `test_parser.py` 8用例 |
| R1~R4规则插件化校验 | Task 4-6 rules | 各规则测试16用例 |
| 异常报告（位置/规则/证据/归因/建议） | Task 10 | `test_report_writer.py` |
| 执行日志溯源 | Task 8 | `test_tracer.py` + E2E断言步骤 |
| 脱敏后才调用外部API（合规） | Task 9 desensitize | `test_llm.py` |
| LLM可切换（DeepSeek/Claude/Mock） | Task 9 client | OpenAI兼容接口+配置切换 |
| 与DeepSeek-Harness解耦 | 全局架构 | 业务层零框架依赖，编排仅在main.py |
| 端到端可用 | Task 11 | E2E：样例数据→4异常→报告→日志 |

## 后续（二期，不在本计划内）

- 4类规则完整插件化配置（YAML驱动）
- RAG知识库（规则文档整理 + 本地向量库 + 归因时检索）
- 预投类规则（预大率区间、历史报废率对比）
- 金标准回归数据集（从历史稽查通报标注，验收召回≥90%/误报≤10%）
- Streamlit界面
- DeepSeek-Harness接入（替换main.py编排层，业务函数作tools暴露）
