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
