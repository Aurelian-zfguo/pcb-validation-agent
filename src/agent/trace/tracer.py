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
        self.file.touch(exist_ok=True)  # 构造即创建，一次校验启动即使中途崩溃也留痕

    def log(self, step: str, status: str, detail: dict):
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "step": step,
            "status": status,
            "detail": detail,
        }
        with open(self.file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
