"""PCB生产预投业务数据校验Agent —— 桌面GUI（Tkinter）。

用法: python gui.py
多选工厂 + 可选多选数据源文件 → 点「运行校验」→ 逐厂跑 → 完成后自动打开 output/。
"""
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    TK_AVAILABLE = True
except ImportError:
    TK_AVAILABLE = False

BASE_DIR = Path(__file__).resolve().parent      # 项目根目录（gui.py 与 main.py 同级）
MAIN_PY = BASE_DIR / "main.py"
OUTPUT_DIR = BASE_DIR / "output"

FACTORIES = ["金州厂", "珠海一厂", "珠海二厂", "江门一厂", "江门二厂"]
# (显示名, key, 是否多选)
FILE_KEYS = [("补投明细表", "补投", False),
             ("订单完成情况", "订单", True),
             ("历史报废率", "报废", True)]


class App:
    def __init__(self, root):
        self.root = root
        self.files = {"补投": [], "订单": [], "报废": []}
        root.title("PCB生产预投业务数据校验Agent")
        root.geometry("820x680")
        self._build_ui()

    def _build_ui(self):
        # 数据源文件（补投单选，订单/报废多选，留空=自动匹配）
        frm_files = ttk.LabelFrame(self.root, text="数据源文件（可选，留空=自动匹配目录下文件）")
        frm_files.pack(fill="x", padx=10, pady=(10, 5))
        self.file_vars = {}
        for label, key, multi in FILE_KEYS:
            row = ttk.Frame(frm_files)
            row.pack(fill="x", padx=5, pady=2)
            ttk.Label(row, text=label, width=12).pack(side="left")
            var = tk.StringVar(value="（自动匹配）")
            self.file_vars[key] = var
            ttk.Entry(row, textvariable=var, state="readonly").pack(
                side="left", fill="x", expand=True, padx=5)
            ttk.Button(row, text="选择", command=lambda k=key, m=multi: self.choose_file(k, m)).pack(side="left", padx=2)
            ttk.Button(row, text="清除", command=lambda k=key: self.clear_file(k)).pack(side="left", padx=2)

        # 工厂多选
        frm_factory = ttk.LabelFrame(self.root, text="工厂（可多选，至少选一个）")
        frm_factory.pack(fill="x", padx=10, pady=5)
        self.factory_vars = {}
        for f in FACTORIES:
            v = tk.BooleanVar(value=False)
            self.factory_vars[f] = v
            ttk.Checkbutton(frm_factory, text=f, variable=v).pack(side="left", padx=8, pady=5)
        ttk.Button(frm_factory, text="全选", command=self.select_all).pack(side="left", padx=8)

        # 运行按钮
        self.run_btn = ttk.Button(self.root, text="运行校验", command=self.start_run)
        self.run_btn.pack(fill="x", padx=10, pady=5)

        # 运行日志
        frm_log = ttk.LabelFrame(self.root, text="运行日志")
        frm_log.pack(fill="both", expand=True, padx=10, pady=(5, 10))
        self.log_text = tk.Text(frm_log, wrap="word", state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scroll = ttk.Scrollbar(frm_log, command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scroll.set)

    def select_all(self):
        for v in self.factory_vars.values():
            v.set(True)

    def choose_file(self, key, multi):
        if multi:
            paths = filedialog.askopenfilenames(
                title="选择数据源文件（可多选）", filetypes=[("Excel 文件", "*.xlsx"), ("所有文件", "*.*")])
        else:
            p = filedialog.askopenfilename(
                title="选择数据源文件", filetypes=[("Excel 文件", "*.xlsx"), ("所有文件", "*.*")])
            paths = (p,) if p else ()
        if paths:
            self.files[key] = list(paths)
            self._refresh_file_display(key)

    def clear_file(self, key):
        self.files[key] = []
        self.file_vars[key].set("（自动匹配）")

    def _refresh_file_display(self, key):
        paths = self.files[key]
        if not paths:
            self.file_vars[key].set("（自动匹配）")
        elif len(paths) == 1:
            self.file_vars[key].set(paths[0])
        else:
            self.file_vars[key].set(f"已选 {len(paths)} 个文件")

    def _selected_factories(self):
        return [f for f in FACTORIES if self.factory_vars[f].get()]

    def _build_cmd(self, factory):
        cmd = [sys.executable, "-u", str(MAIN_PY), "--工厂", factory]
        for f in self.files["补投"]:
            cmd += ["--补投", f]
        for f in self.files["订单"]:
            cmd += ["--订单", f]
        for f in self.files["报废"]:
            cmd += ["--报废", f]
        return cmd

    def _append_log(self, text):
        self.log_text.config(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def start_run(self):
        for key, paths in self.files.items():
            for p in paths:
                if not Path(p).exists():
                    messagebox.showerror("错误", f"文件不存在：{p}")
                    return
        factories = self._selected_factories()
        if not factories:
            messagebox.showerror("错误", "请至少选择一个工厂")
            return
        self.run_btn.config(state="disabled")
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

        q = queue.Queue()

        def worker():
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            exit_codes = []
            for fac in factories:
                cmd = self._build_cmd(fac)
                q.put(("line", f"\n========== {fac} ==========\n> {' '.join(cmd)}\n"))
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    cwd=str(BASE_DIR), env=env)
                for line in proc.stdout:
                    q.put(("line", line))
                proc.wait()
                exit_codes.append(proc.returncode)
                q.put(("line", f"[{fac}] 退出码 {proc.returncode}\n"))
            q.put(("done", 0 if all(c == 0 for c in exit_codes) else 1))

        threading.Thread(target=worker, daemon=True).start()
        self._poll_queue(q)

    def _poll_queue(self, q):
        try:
            while True:
                kind, payload = q.get_nowait()
                if kind == "line":
                    self._append_log(payload)
                elif kind == "done":
                    self.run_btn.config(state="normal")
                    self._append_log(f"\n[全部完成] 退出码 {payload}\n")
                    if payload == 0:
                        self._open_output()
        except queue.Empty:
            pass
        if self.run_btn["state"] == "disabled":
            self.root.after(100, lambda: self._poll_queue(q))

    def _open_output(self):
        OUTPUT_DIR.mkdir(exist_ok=True)
        try:
            os.startfile(str(OUTPUT_DIR))  # Windows 打开文件夹
        except Exception:
            messagebox.showwarning("提示", f"报告已生成，请手动打开：{OUTPUT_DIR}")


def main():
    if not TK_AVAILABLE:
        print("当前 Python 环境未安装 Tkinter，无法启动 GUI。")
        print("替代方案：")
        print("  1) 直接用命令行：python main.py --工厂 金州厂")
        print("  2) 安装带 Tkinter 的 Python，或用 Streamlit：pip install streamlit")
        sys.exit(1)
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
