"""RAG 监控模块：记录每次知识检索与归因，生成 CSV 与统计摘要。

单例模式：全局共享同一个实例（`monitor`），避免多处调用时数据分散。
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

# 项目根目录 = rag_monitor.py 的上三级（src/agent/llm -> src/agent -> src -> 项目根）
PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAG_LOG_DIR = PROJECT_ROOT / "rag_logs"

CSV_FIELDS = ["时间", "异常ID", "Query", "是否检索成功", "Top1-4 来源", "归因说明是否包含'知识补充'字样"]


class RagMonitor:
    """RAG 监控单例。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._records = {}
        return cls._instance

    def log_retrieval(self, anomaly_id, query, success, top_results):
        """记录一次检索请求。top_results 为 [{content, source}, ...] 列表。"""
        rec = self._records.setdefault(
            anomaly_id, {"query": "", "success": False, "top_results": [], "final_answer": ""})
        rec["query"] = query or ""
        rec["success"] = bool(success)
        rec["top_results"] = list(top_results or [])

    def log_attribution(self, anomaly_id, final_answer):
        """记录最终生成的归因说明。"""
        rec = self._records.setdefault(
            anomaly_id, {"query": "", "success": False, "top_results": [], "final_answer": ""})
        rec["final_answer"] = final_answer or ""

    def _save_csv(self):
        RAG_LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = RAG_LOG_DIR / f"rag_{time.strftime('%Y-%m-%d')}.csv"
        with open(path, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            if path.stat().st_size == 0:  # 当天文件为空时先写表头
                writer.writerow(CSV_FIELDS)
            for aid, rec in self._records.items():
                sources = "、".join(
                    r.get("source", "") for r in rec["top_results"][:4] if r.get("source"))
                writer.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    aid,
                    rec["query"],
                    "是" if rec["success"] else "否",
                    sources,
                    "是" if "知识补充" in rec["final_answer"] else "否",
                ])
        return path

    def generate_summary(self):
        """生成 CSV 并打印统计摘要到控制台。"""
        path = self._save_csv()
        total = len(self._records)
        success = sum(1 for r in self._records.values() if r["success"])
        cited = sum(1 for r in self._records.values() if "知识补充" in r["final_answer"])
        hit_rate = f"{cited / total:.1%}" if total else "0.0%"
        print("\n===== RAG 监控统计 =====")
        print(f"总异常数: {total}")
        print(f"检索成功次数: {success}")
        print(f"归因引用知识次数: {cited}（命中率 {hit_rate}）")
        print(f"RAG监控报告已保存至 rag_logs/{path.name}")
        print("========================\n")


# 模块级单例，供全局 import 使用
monitor = RagMonitor()
