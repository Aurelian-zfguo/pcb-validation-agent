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
