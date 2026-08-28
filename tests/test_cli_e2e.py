import subprocess
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = PROJECT_ROOT / "data" / "samples" / "综合日报.csv"


def _run_main(args, tmp_path):
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"),
         "--file", str(SAMPLE), "--工厂", "珠海一厂", "--类型", "综合日报",
         "--输出目录", str(tmp_path / "out"), "--trace-dir", str(tmp_path / "traces"),
         "--mock-llm"] + args,
        capture_output=True, text=True, encoding="utf-8", timeout=120,
        cwd=str(PROJECT_ROOT))
    return result


def test_cli_end_to_end_full_pipeline(tmp_path):
    result = _run_main([], tmp_path)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "校验完成" in result.stdout
    assert "异常 3" in result.stdout

    excel_files = list((tmp_path / "out").glob("异常校验报告*.xlsx"))
    md_files = list((tmp_path / "out").glob("校验摘要*.md"))
    assert len(excel_files) == 1 and len(md_files) == 1

    detail = pd.read_excel(excel_files[0], sheet_name="异常明细")
    assert set(detail["规则编号"]) == {"R1", "R3", "R4"}
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
         "--file", str(bad), "--工厂", "珠海一厂", "--类型", "综合日报",
         "--输出目录", str(tmp_path / "out"), "--trace-dir", str(tmp_path / "traces")],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
        cwd=str(PROJECT_ROOT))
    assert result.returncode == 2
    assert "无法识别订单号字段" in result.stdout
