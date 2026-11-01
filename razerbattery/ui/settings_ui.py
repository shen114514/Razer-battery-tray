"""设置对话框：低电量阈值 / 确认次数 / 弹窗时长 / 冷却 / 图标样式等。"""

import tkinter as tk
from tkinter import ttk

from .. import __version__
from ..config import DEFAULTS

STYLE_LABELS = {
    "device": "设备图形 + 电量数字（推荐）",
    "number": "仅电量数字",
}
_STYLE_LABELS_REV = {v: k for k, v in STYLE_LABELS.items()}


def _read_int(var, default, lo, hi):
    try:
        value = int(float(str(var.get()).strip()))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


class SettingsDialog:
    def __init__(self, root, cfg, on_save):
        self.root = root
        self.on_save = on_save
        self.cfg = cfg

        win = tk.Toplevel(root)
        self.win = win
        win.title("设置 — Razer 电量工具")
        win.resizable(False, False)
        win.configure(padx=18, pady=14)
        win.attributes("-topmost", True)
        try:
            if root.state() != "withdrawn":
                win.transient(root)
        except tk.TclError:
            pass

        self.vars = {
            "low_threshold": tk.StringVar(value=str(cfg.low_threshold)),
            "confirm_reads": tk.StringVar(value=str(cfg.confirm_reads)),
            "popup_seconds": tk.StringVar(value=str(cfg.popup_seconds)),
            "cooldown_minutes": tk.StringVar(value=str(cfg.cooldown_minutes)),
            "ignore_zero": tk.BooleanVar(value=cfg.ignore_zero),
            "alerts_enabled": tk.BooleanVar(value=cfg.alerts_enabled),
            "tray_style": tk.StringVar(value=STYLE_LABELS.get(cfg.tray_icon_style, STYLE_LABELS["device"])),
            "start_minimized": tk.BooleanVar(value=cfg.start_minimized),
        }

        body = tk.Frame(win)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        self._spin_row(body, 0, "低电量阈值", "low_threshold", 1, 50, "%",
                       "电量低于该值时提醒；0% 永远不提醒")
        self._spin_row(body, 2, "连续确认次数", "confirm_reads", 1, 10, "次",
                       "连续 N 次都低于阈值才提醒，防偶发误读")
        self._spin_row(body, 4, "弹窗停留", "popup_seconds", 0, 600, "秒",
                       "0 = 不自动关闭，只能手动关")
        self._spin_row(body, 6, "重复提醒冷却", "cooldown_minutes", 0, 1440, "分钟",
                       "冷却期内不重复打扰；0 = 不冷却")

        ttk.Separator(body, orient="horizontal").grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=(8, 6)
        )

        tk.Checkbutton(
            body, text="忽略 0% 异常读数（键盘待机保护）",
            variable=self.vars["ignore_zero"], anchor="w",
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=2)
        tk.Label(
            body, text="设备待机时可能返回 0%，勾选后不显示、不提醒",
            fg="#999999", font=("Microsoft YaHei UI", 8), anchor="w",
        ).grid(row=10, column=0, columnspan=2, sticky="w", padx=(20, 0))

        tk.Checkbutton(
            body, text="启用低电量提醒", variable=self.vars["alerts_enabled"], anchor="w",
        ).grid(row=11, column=0, columnspan=2, sticky="w", pady=(6, 2))

        style_row = tk.Frame(body)
        style_row.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(6, 2))
        tk.Label(style_row, text="托盘图标样式", anchor="w").pack(side="left")
        ttk.Combobox(
            style_row, textvariable=self.vars["tray_style"], state="readonly",
            values=[STYLE_LABELS["device"], STYLE_LABELS["number"]], width=22,
        ).pack(side="right")

        tk.Checkbutton(
            body, text="开机自启时只显示托盘（不弹面板）",
            variable=self.vars["start_minimized"], anchor="w",
        ).grid(row=13, column=0, columnspan=2, sticky="w", pady=(6, 2))

        foot = tk.Frame(win)
        foot.pack(fill="x", pady=(14, 0))
        tk.Label(
            foot, text="v%s" % __version__, fg="#aaaaaa", font=("Segoe UI", 8),
        ).pack(side="left")
        tk.Button(foot, text="取消", width=8, command=win.destroy).pack(side="right")
        tk.Button(foot, text="保存", width=8, command=self._save).pack(side="right", padx=(0, 8))
        tk.Button(foot, text="恢复默认", width=9, command=self._reset).pack(side="right", padx=(0, 20))

        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        self._center()
        try:
            win.grab_set()
            win.focus_force()
        except tk.TclError:
            pass

    def _spin_row(self, parent, row, label, key, lo, hi, unit, hint):
        tk.Label(parent, text=label, anchor="w").grid(row=row, column=0, sticky="w", pady=3)
        holder = tk.Frame(parent)
        holder.grid(row=row, column=1, sticky="e", pady=3)
        tk.Spinbox(
            holder, from_=lo, to=hi, width=6, textvariable=self.vars[key],
            justify="right",
        ).pack(side="left")
        tk.Label(holder, text=unit, anchor="w", fg="#666666").pack(side="left", padx=(4, 0))
        tk.Label(
            parent, text=hint, fg="#999999",
            font=("Microsoft YaHei UI", 8), anchor="w",
        ).grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(0, 5))

    def _center(self):
        win = self.win
        w = win.winfo_reqwidth()
        h = win.winfo_reqheight()
        try:
            rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
            rw, rh = self.root.winfo_width(), self.root.winfo_height()
            if self.root.state() == "withdrawn":
                raise tk.TclError
            x, y = rx + (rw - w) // 2, ry + (rh - h) // 2
        except tk.TclError:
            x = (win.winfo_screenwidth() - w) // 2
            y = (win.winfo_screenheight() - h) // 2
        x = max(0, min(x, win.winfo_screenwidth() - w))
        y = max(0, min(y, win.winfo_screenheight() - h))
        win.geometry("+%d+%d" % (x, y))

    def _reset(self):
        d = DEFAULTS
        self.vars["low_threshold"].set(str(d["low_threshold"]))
        self.vars["confirm_reads"].set(str(d["confirm_reads"]))
        self.vars["popup_seconds"].set(str(d["popup_seconds"]))
        self.vars["cooldown_minutes"].set(str(d["cooldown_minutes"]))
        self.vars["ignore_zero"].set(d["ignore_zero"])
        self.vars["alerts_enabled"].set(d["alerts_enabled"])
        self.vars["tray_style"].set(STYLE_LABELS[d["tray_icon_style"]])
        self.vars["start_minimized"].set(d["start_minimized"])

    def _save(self):
        values = {
            "low_threshold": _read_int(self.vars["low_threshold"], 10, 1, 50),
            "confirm_reads": _read_int(self.vars["confirm_reads"], 2, 1, 10),
            "popup_seconds": _read_int(self.vars["popup_seconds"], 15, 0, 600),
            "cooldown_minutes": _read_int(self.vars["cooldown_minutes"], 60, 0, 1440),
            "ignore_zero": bool(self.vars["ignore_zero"].get()),
            "alerts_enabled": bool(self.vars["alerts_enabled"].get()),
            "tray_icon_style": _STYLE_LABELS_REV.get(
                self.vars["tray_style"].get(), "number"
            ),
            "start_minimized": bool(self.vars["start_minimized"].get()),
        }
        try:
            self.on_save(values)
        finally:
            self.win.destroy()
