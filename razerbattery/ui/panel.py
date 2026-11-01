"""简洁面板（tkinter）：两张设备卡片 + 刷新间隔 + 开机自启 + 设置入口。

每张卡片：设备名、大号电量、进度条、状态、更新时间、来源。
电量分色（与托盘图标同一套规则）：绿 60+ / 琥珀 30-59 / 橙 10-29 / 红 1-9 / 灰未知。
设备待机（读到 0%）或无响应时，保留上一次有效电量并明确标注为旧数据，
不会把 0% 当成真实电量显示。
"""

import tkinter as tk
from tkinter import ttk

from ..config import INTERVAL_OPTIONS
from ..levels import hex_of, status_text
from ..state import (
    STATUS_CACHED,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_STANDBY,
)

STALE_COLOR = "#9a9a9a"


class _Card:
    def __init__(self, parent, name):
        self.name = name
        self.state = None
        self._bar_retry = None

        frame = tk.Frame(parent, bd=1, relief="solid", padx=12, pady=10)
        frame.pack(fill="x", padx=10, pady=6)
        self.frame = frame

        tk.Label(
            frame, text=name, font=("Microsoft YaHei UI", 11, "bold"), anchor="w",
        ).pack(fill="x")

        self.pct_label = tk.Label(frame, text="--", font=("Segoe UI", 28, "bold"), fg=STALE_COLOR)
        self.pct_label.pack(pady=(4, 0))

        self.bar = tk.Canvas(frame, height=8, bg="#e9e9e9", highlightthickness=0)
        self.bar.pack(fill="x", pady=(4, 3))
        self._bar_w = None
        self._bar_value = (0, STALE_COLOR)

        self.status_label = tk.Label(
            frame, text="等待读取…", font=("Microsoft YaHei UI", 9), fg="#777777", anchor="w",
        )
        self.status_label.pack(fill="x")
        self.time_label = tk.Label(
            frame, text="更新：--:--:--", font=("Microsoft YaHei UI", 8), fg="#888888", anchor="w",
        )
        self.time_label.pack(fill="x")
        self.source_label = tk.Label(
            frame, text="HID Feature Report · Razer 协议",
            font=("Microsoft YaHei UI", 8), fg="#b5b5b5", anchor="w",
        )
        self.source_label.pack(fill="x", pady=(2, 0))

        self.refresh_btn = tk.Button(frame, text="刷新", command=self._on_refresh)
        self.refresh_btn.pack(anchor="e", pady=(2, 0))
        self._refresh_cb = None

    def set_refresh_cb(self, cb):
        self._refresh_cb = cb

    def _on_refresh(self):
        if self._refresh_cb:
            self._refresh_cb()

    # ---- 渲染 ----
    def render(self, state):
        self.state = state
        pct = state.percent
        connected = state.connected

        value_text = "--" if pct is None else "%d%%" % pct

        if not connected:
            color = STALE_COLOR
            if pct is None:
                status = "未连接"
            else:
                status = "未连接 · 上次读数 %s" % state.valid_time_text()
        elif state.status == STATUS_OK:
            color = hex_of(pct)
            status = status_text(pct)
        elif state.status == STATUS_STANDBY:
            color = STALE_COLOR
            status = "设备待机中（读到 0%，已忽略）"
        elif state.status == STATUS_CACHED:
            color = STALE_COLOR
            status = "上次读数（等待设备响应）"
        elif state.status == STATUS_ERROR:
            color = STALE_COLOR
            status = "读取无响应" + ("，显示上次有效值" if pct is not None else "")
        elif state.status == STATUS_DISCONNECTED:
            color = STALE_COLOR
            status = "未连接"
        else:  # STATUS_UNKNOWN
            color = STALE_COLOR
            status = "等待读取…"

        self.pct_label.config(text=value_text, fg=color)
        self.status_label.config(text=status, fg=color if state.status == STATUS_OK else "#777777")

        if state.last_valid_ts:
            text = "更新：%s" % state.valid_time_text()
            if state.status != STATUS_OK:
                age = state.age_text()
                text += "（%s）" % age if age else ""
            self.time_label.config(text=text)
        else:
            self.time_label.config(text="更新：--:--:--")

        self._draw_bar(pct or 0, color if state.status == STATUS_OK else STALE_COLOR)

    def _draw_bar(self, percent, color):
        self._bar_value = (percent, color)
        w = self.bar.winfo_width()
        if w <= 1:
            if self._bar_retry is None:
                self._bar_retry = self.bar.after(50, self._redraw_bar)
            return
        self._bar_retry = None
        self.bar.delete("all")
        fill_w = int(w * max(0, min(100, percent)) / 100)
        if fill_w > 0:
            self.bar.create_rectangle(0, 0, fill_w, 8, fill=color, outline=color)

    def _redraw_bar(self):
        self._bar_retry = None
        p, c = self._bar_value
        self._draw_bar(p, c)


class BatteryPanel:
    def __init__(self, root, device_names):
        self.root = root
        self.cards = {}

        head = tk.Frame(root, padx=12, pady=10)
        head.pack(fill="x")
        tk.Label(
            head, text="Razer 无线设备电量",
            font=("Microsoft YaHei UI", 12, "bold"), anchor="w",
        ).pack(fill="x")
        self.summary_label = tk.Label(
            head, text="", font=("Microsoft YaHei UI", 8), fg="#888888", anchor="w",
        )
        self.summary_label.pack(fill="x", pady=(2, 0))

        for key, name in device_names:
            self.cards[key] = _Card(root, name)

        footer = tk.Frame(root, padx=10, pady=8)
        footer.pack(fill="x", side="bottom")
        tk.Label(footer, text="刷新间隔", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.interval_var = tk.StringVar(value="1 分钟")
        self.interval_combo = ttk.Combobox(
            footer, textvariable=self.interval_var, state="readonly",
            values=[o[0] for o in INTERVAL_OPTIONS], width=7,
        )
        self.interval_combo.pack(side="left", padx=6)

        self.settings_btn = tk.Button(footer, text="设置…", width=6)
        self.settings_btn.pack(side="right", padx=(8, 0))

        self.autostart_var = tk.BooleanVar(value=False)
        self.autostart_cb = tk.Checkbutton(
            footer, text="开机自启", variable=self.autostart_var,
            font=("Microsoft YaHei UI", 9),
        )
        self.autostart_cb.pack(side="right")

    # ---- 回调绑定 ----
    def set_refresh_cb(self, cb):
        for c in self.cards.values():
            c.set_refresh_cb(cb)

    def set_autostart_toggle_cb(self, cb):
        def _on_change():
            cb(self.autostart_var.get())
        self.autostart_cb.config(command=_on_change)

    def set_interval_change_cb(self, cb):
        def _on_change(_evt):
            label = self.interval_var.get()
            for text, secs in INTERVAL_OPTIONS:
                if text == label:
                    cb(secs)
                    break
        self.interval_combo.bind("<<ComboboxSelected>>", _on_change)

    def set_settings_cb(self, cb):
        self.settings_btn.config(command=cb)

    def set_autostart_state(self, enabled):
        self.autostart_var.set(bool(enabled))

    def set_interval(self, seconds):
        for text, secs in INTERVAL_OPTIONS:
            if secs == seconds:
                self.interval_var.set(text)
                break

    def set_summary(self, text):
        self.summary_label.config(text=text)

    # ---- 数据更新 ----
    def apply_state(self, state):
        card = self.cards.get(state.key)
        if card:
            card.render(state)
