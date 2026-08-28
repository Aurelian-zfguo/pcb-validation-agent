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
