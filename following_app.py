"""Small Chinese Windows GUI for unlimited followed-creator archiving."""

import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.yml"
STATE = ROOT / "state"


class FollowingApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("抖音关注珍藏（开源无限版）")
        self.geometry("840x600")
        self.minsize(720, 500)
        self.process = None
        self.download_dir = tk.StringVar(value=str(ROOT / "Downloaded-Following"))
        self.status = tk.StringVar(value="准备就绪")
        self._build()
        self._ensure_config()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="抖音关注珍藏", font=("Microsoft YaHei UI", 20, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            frame,
            text="同步全部关注作者并全量/增量备份；没有作者人数上限。请仅备份你有权保存的内容。",
        ).pack(anchor="w", pady=(4, 14))

        path_row = ttk.Frame(frame)
        path_row.pack(fill="x", pady=4)
        ttk.Label(path_row, text="保存目录：").pack(side="left")
        ttk.Entry(path_row, textvariable=self.download_dir).pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Button(path_row, text="选择", command=self.choose_dir).pack(side="left")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=10)
        ttk.Button(buttons, text="1. 登录/更新登录", command=self.login).pack(side="left", padx=3)
        ttk.Button(buttons, text="2. 同步全部关注", command=self.sync_following).pack(
            side="left", padx=3
        )
        ttk.Button(buttons, text="3. 下载全部作品", command=self.download).pack(
            side="left", padx=3
        )
        ttk.Button(buttons, text="停止", command=self.stop).pack(side="right", padx=3)

        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=(4, 6))
        self.log = tk.Text(
            frame, wrap="word", bg="#171717", fg="#e7e7e7", insertbackground="white"
        )
        self.log.pack(fill="both", expand=True)

    def _ensure_config(self) -> None:
        if not CONFIG.exists():
            shutil.copyfile(ROOT / "config.example.yml", CONFIG)
        (ROOT / "config").mkdir(exist_ok=True)

    def choose_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.download_dir.get())
        if selected:
            self.download_dir.set(selected)

    def login(self) -> None:
        command = [
            sys.executable,
            "-m",
            "tools.cookie_fetcher",
            "--output",
            str(ROOT / "config" / "cookies.json"),
            "--config",
            str(CONFIG),
            "--include-all",
        ]
        subprocess.Popen(command, cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE)
        messagebox.showinfo(
            "登录",
            "已打开独立登录窗口。请在浏览器完成抖音登录，然后回到黑色命令窗口按 Enter。",
        )

    def sync_following(self) -> None:
        self._run(
            [
                sys.executable,
                "-m",
                "tools.following_sync",
                "--config",
                str(CONFIG),
                "--state-dir",
                str(STATE),
                "--download-dir",
                self.download_dir.get(),
            ],
            "正在同步全部关注作者…",
        )

    def download(self) -> None:
        generated = STATE / "following.config.yml"
        if not generated.exists():
            messagebox.showwarning("尚未同步", "请先点击“同步全部关注”。")
            return
        self._run(
            [sys.executable, str(ROOT / "run.py"), "-c", str(generated)],
            "正在下载；已存在的作品会自动跳过…",
        )

    def _run(self, command, label: str) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showwarning("任务进行中", "请先等待当前任务完成或点击停止。")
            return
        self.status.set(label)
        self.log.insert("end", f"\n> {' '.join(command)}\n")
        self.log.see("end")

        def worker() -> None:
            self.process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.after(0, self._append, line)
            code = self.process.wait()
            self.after(0, self.status.set, "任务完成" if code == 0 else f"任务失败（代码 {code}）")

        threading.Thread(target=worker, daemon=True).start()

    def _append(self, line: str) -> None:
        self.log.insert("end", line)
        self.log.see("end")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.status.set("正在停止…")


if __name__ == "__main__":
    FollowingApp().mainloop()
