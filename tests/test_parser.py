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
