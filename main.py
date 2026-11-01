"""Razer 无线键鼠电量工具 —— 入口。

用法：
  python main.py                   正常启动（简洁面板 + 托盘）
  python main.py --minimized       启动时只显示托盘图标，不弹面板
  python main.py --debug           附加调试界面
  python main.py --no-tray         不显示托盘（仅面板，关闭即退出）
  python main.py --smoke N         冒烟测试：启动 N 秒后自动退出

仅依赖标准库 + ctypes；运行时无日志文件、无第三方依赖。
"""

import argparse
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

from razerbattery import __version__
from razerbattery import config as config_mod
from razerbattery.alerting import AlertSettings, LowBatteryMonitor
from razerbattery.devices import MODELS
from razerbattery.levels import rgb_of
from razerbattery.platform import autostart, single_instance
from razerbattery.reader import BatteryReader
from razerbattery.state import (
    STATUS_CACHED,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_STANDBY,
    BatteryStore,
    load_cached,
    save_cached,
)
from razerbattery.ui import panel as panel_mod
from razerbattery.ui import toast as toast_mod
from razerbattery.ui import tray as tray_mod
from razerbattery.ui.debug_ui import DebugWindow
from razerbattery.ui.settings_ui import SettingsDialog

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")
STATE_PATH = os.path.join(PROJECT_DIR, "state.json")
RESCAN_EVERY = 30.0  # 每 30s 重新枚举一次，感知设备插拔


def pythonw_path():
    """优先用 pythonw.exe 启动（无控制台窗口）。"""
    exe = sys.executable or ""
    candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return candidate if os.path.exists(candidate) else exe


def startup_arguments(cfg):
    """开机自启快捷方式的参数；勾选「只显示托盘」时附加 --minimized。"""
    args = '"%s"' % os.path.join(PROJECT_DIR, "main.py")
    if cfg.start_minimized:
        args += " --minimized"
    return args


class App:
    def __init__(self, root, args, cfg, activation=None):
        self.root = root
        self.args = args
        self.cfg = cfg
        self._demo = bool(getattr(args, "demo", False))
        self.events = queue.Queue()
        self._quitting = False
        self._paused = False
        self._t0 = time.monotonic()
        self._next_rescan = 0.0
        self._next_refresh = 0.0
        self._settings = None
        self._activation = activation
        self._activation_stop = threading.Event()

        self.device_names = [(m.key, m.name) for m in MODELS]
        self.device_kinds = {m.key: m.kind for m in MODELS}

        # 状态表 + 低电量判定
        self.store = BatteryStore(ignore_zero=cfg.ignore_zero)
        for key, name in self.device_names:
            self.store.ensure(key, name)
        # 上次运行的有效值：设备待机时也能显示「上次读数」而不是 --
        if not self._demo:
            self.store.seed(load_cached(STATE_PATH))
        self._last_state_save = 0.0
        self._saved_percents = {
            st.key: st.percent for st in self.store.all() if st.percent is not None
        }
        self.monitor = LowBatteryMonitor(AlertSettings.from_config(cfg))

        # 后台读取
        if self._demo:
            from razerbattery.demo import DemoBatteryReader

            self.reader = DemoBatteryReader()
        else:
            self.reader = BatteryReader()
            self.reader.rescan()
        self.reader.start()

        # 面板 + 提示窗
        self.panel = panel_mod.BatteryPanel(root, self.device_names)
        self.toast = toast_mod.ToastManager(
            root, on_open_panel=self._show_panel, seconds=cfg.popup_seconds
        )

        # 托盘
        self.tray = None
        if not args.no_tray:
            self.tray = tray_mod.TrayManager(self.reader.request_all, self.events.put)
            self.tray.start()
            self.tray.set_icon_style(cfg.tray_icon_style)
            self.tray.set_flags(paused=False, alerts_enabled=cfg.alerts_enabled)
            self.tray.set_interval(cfg.interval)

        # 回调
        self.panel.set_refresh_cb(lambda: self._refresh_now(force=True))
        self.panel.set_autostart_toggle_cb(self._on_autostart)
        self.panel.set_interval_change_cb(self._on_interval)
        self.panel.set_settings_cb(self._open_settings)
        self.panel.set_interval(cfg.interval)
        self.panel.set_autostart_state(autostart.shortcut_exists())

        # 已有自启快捷方式时同步参数（--minimized 可能被改过）
        if not self._demo:
            self._sync_autostart_shortcut()

        if args.no_tray:
            root.protocol("WM_DELETE_WINDOW", self.quit)
        else:
            root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

        if args.debug:
            DebugWindow(root)

        self._refresh_connection()
        self._update_summary()
        self._refresh_now(force=True)
        self._next_refresh = time.monotonic() + max(30, cfg.interval)

        if activation is not None:
            threading.Thread(target=self._watch_activation, daemon=True, name="activation").start()

        root.after(100, self._pump)

        if self._demo:
            # 演示/录屏时保持面板置顶，避免被其他窗口盖住
            root.after(600, self._demo_keep_on_top)

    def _demo_keep_on_top(self):
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
        except tk.TclError:
            pass

    # ---- 面板/托盘行为 ----
    def _hide_to_tray(self):
        self.root.withdraw()

    def _show_panel(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.root.attributes("-topmost", True)
            if not self._demo:
                self.root.after(250, self._drop_topmost)
        except tk.TclError:
            pass

    def _drop_topmost(self):
        try:
            self.root.attributes("-topmost", False)
        except tk.TclError:
            pass

    def _on_autostart(self, enabled):
        if self._demo:
            return
        if enabled:
            ok, msg = autostart.create_startup_shortcut(
                pythonw_path(), startup_arguments(self.cfg), PROJECT_DIR
            )
            if not ok:
                messagebox.showerror("开机自启失败", msg)
                self.panel.set_autostart_state(False)
        else:
            autostart.remove_startup_shortcut()

    def _sync_autostart_shortcut(self):
        if not autostart.shortcut_exists():
            return
        autostart.create_startup_shortcut(
            pythonw_path(), startup_arguments(self.cfg), PROJECT_DIR
        )

    def _on_interval(self, secs):
        self.cfg.interval = secs
        if not self._demo:
            self.cfg.save(CONFIG_PATH)
        if self.tray:
            self.tray.set_interval(secs)
        self._update_summary()

    # ---- 暂停 / 提醒开关 / 设置 ----
    def _set_tray_flags(self):
        if self.tray:
            self.tray.set_flags(paused=self._paused, alerts_enabled=self.cfg.alerts_enabled)

    def _toggle_pause(self):
        self._paused = not self._paused
        self._set_tray_flags()
        self._update_summary()
        if not self._paused:
            self._refresh_now(force=True)

    def _toggle_alerts(self):
        self.cfg.alerts_enabled = not self.cfg.alerts_enabled
        if not self._demo:
            self.cfg.save(CONFIG_PATH)
        self.monitor.configure(AlertSettings.from_config(self.cfg))
        if not self.cfg.alerts_enabled:
            self.toast.close_all()
        self._set_tray_flags()
        self._update_summary()

    def _open_settings(self):
        if self._settings is not None:
            try:
                if self._settings.win.winfo_exists():
                    self._settings.win.lift()
                    self._settings.win.focus_force()
                    return
            except tk.TclError:
                pass
        self._settings = SettingsDialog(self.root, self.cfg, self._apply_settings)

    def _apply_settings(self, values):
        self.cfg.update(values)
        if not self._demo:
            self.cfg.save(CONFIG_PATH)
        self.store.ignore_zero = self.cfg.ignore_zero
        self.monitor.configure(AlertSettings.from_config(self.cfg))
        self.toast.set_seconds(self.cfg.popup_seconds)
        if self.tray:
            self.tray.set_icon_style(self.cfg.tray_icon_style)
        self._set_tray_flags()
        if not self._demo:
            self._sync_autostart_shortcut()
        self.panel.set_interval(self.cfg.interval)
        self._update_summary()
        for state in self.store.all():
            self._update_tray(state)
        self._push_tray_status()

    def _update_summary(self):
        label = self.cfg.interval
        for text, secs in config_mod.INTERVAL_OPTIONS:
            if secs == self.cfg.interval:
                label = text
                break
        if self._paused:
            parts = ["已暂停自动刷新（右键托盘菜单可恢复）"]
        else:
            parts = ["每 %s 自动刷新" % label]
        if self.cfg.alerts_enabled:
            parts.append("低于 %d%% 提醒" % self.cfg.low_threshold)
        else:
            parts.append("低电量提醒已关闭")
        if not self.cfg.ignore_zero:
            parts.append("未忽略 0% 读数")
        self.panel.set_summary(" · ".join(parts))

    # ---- 连接状态 ----
    def _refresh_connection(self):
        connected = set(self.reader.known_keys())
        for key, name in self.device_names:
            state = self.store.set_connected(key, key in connected, name)
            self.panel.apply_state(state)
            self._update_tray(state)
        self._push_tray_status()

    def _refresh_now(self, force=False):
        if self._paused and not force:
            return
        self.reader.request_all()

    # ---- 主泵取循环 ----
    def _pump(self):
        if self._quitting:
            return

        for res in self.reader.pump():
            self._on_result(res)

        if not self._handle_events():
            return

        now = time.monotonic()

        # 周期性重扫，感知设备插拔
        if now >= self._next_rescan:
            self._next_rescan = now + RESCAN_EVERY
            self.reader.rescan()
            self._refresh_connection()

        # 没有托盘时由主循环自己驱动刷新
        if self.tray is None and now >= self._next_refresh:
            self._next_refresh = now + max(30, self.cfg.interval)
            if not self._paused:
                self.reader.request_all()

        # 冒烟测试：N 秒后自动退出
        if self.args.smoke and now - self._t0 >= self.args.smoke:
            self.quit()
            return

        self.root.after(100, self._pump)

    def _handle_events(self):
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            if ev == ("open_panel",):
                self._show_panel()
            elif ev == ("refresh",):
                self._refresh_now(force=True)
            elif ev == ("toggle_pause",):
                self._toggle_pause()
            elif ev == ("toggle_alerts",):
                self._toggle_alerts()
            elif ev == ("settings",):
                self._open_settings()
            elif ev == ("quit",):
                self.quit()
                return False
        return True

    # ---- 一条读取结果 ----
    def _on_result(self, res):
        state = self.store.apply(res)
        self.panel.apply_state(state)
        self._update_tray(state)
        self._push_tray_status()
        if state.fresh:
            self._maybe_save_state(state)

        alert = self.monitor.evaluate(state)
        if alert is not None:
            self._show_alert(alert)

    # ---- 上次有效值的持久化（变化时保存，最多每 10 分钟补写一次时间） ----
    def _maybe_save_state(self, state):
        if self._demo or state.percent is None:
            return
        now = time.monotonic()
        if (
            self._saved_percents.get(state.key) != state.percent
            or now - self._last_state_save > 600
        ):
            self._save_state()

    def _save_state(self):
        if self._demo:
            return
        states = self.store.all()
        if save_cached(STATE_PATH, states):
            self._saved_percents = {
                st.key: st.percent for st in states if st.percent is not None
            }
            self._last_state_save = time.monotonic()

    def _show_alert(self, alert):
        title = "电量告急" if alert.percent <= 5 else "低电量提醒"
        message = "%s 电量仅剩 %d%%。" % (alert.name, alert.percent)
        hint = "请尽快充电，或改用有线连接。"
        toast = self.toast.show(
            alert.key, title, message, hint, rgb=rgb_of(alert.percent)
        )
        if toast is None and self.tray:
            # Tk 窗口异常时的兜底：系统托盘气泡
            self.tray.notify(alert.key, title, message, warn=True)

    # ---- 托盘数据 ----
    def _tooltip(self, state):
        name = state.name
        if not state.connected:
            return "%s  未连接" % name
        if state.percent is None:
            if state.status == STATUS_STANDBY:
                return "%s  设备待机中（0%% 读数已忽略）" % name
            if state.status == STATUS_ERROR:
                return "%s  读取无响应" % name
            return "%s  等待读取…" % name
        when = state.valid_time_text()
        if state.status == STATUS_OK:
            return "%s  %d%%  %s" % (name, state.percent, when)
        if state.status == STATUS_STANDBY:
            return "%s  %d%%（设备待机，%s 的读数）" % (name, state.percent, when)
        if state.status == STATUS_ERROR:
            return "%s  %d%%（无响应，%s 的读数）" % (name, state.percent, when)
        if state.status == STATUS_CACHED:
            return "%s  %d%%（上次读数，%s）" % (name, state.percent, when)
        return "%s  %d%%（%s）" % (name, state.percent, when)

    def _update_tray(self, state):
        if not self.tray:
            return
        self.tray.update_device(
            state.key,
            state.percent,
            self._tooltip(state),
            fresh=state.fresh,
            connected=state.connected,
            kind=self.device_kinds.get(state.key),
        )

    def _push_tray_status(self):
        if not self.tray:
            return
        lines = []
        for key, name in self.device_names:
            state = self.store.get(key)
            if state is None:
                continue
            short = name.replace("Razer ", "")
            if not state.connected:
                lines.append("%s  未连接" % short)
            elif state.percent is None:
                lines.append("%s  --  %s" % (short, state.attempt_time_text()))
            elif state.status == STATUS_OK:
                lines.append("%s  %d%%  %s" % (short, state.percent, state.valid_time_text()))
            elif state.status == STATUS_STANDBY:
                lines.append("%s  %d%%（待机）" % (short, state.percent))
            elif state.status == STATUS_ERROR:
                lines.append("%s  %d%%（无响应）" % (short, state.percent))
            elif state.status == STATUS_CACHED:
                lines.append("%s  %d%%（上次读数）" % (short, state.percent))
            else:
                lines.append("%s  %d%%（旧数据）" % (short, state.percent))
        self.tray.set_status(lines)

    # ---- 再次启动时唤起面板 ----
    def _watch_activation(self):
        while not self._activation_stop.is_set() and not self._quitting:
            if self._activation is not None and self._activation.wait(0.5):
                self.events.put(("open_panel",))

    # ---- 退出（幂等） ----
    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        self._activation_stop.set()
        try:
            self._save_state()
        except Exception:
            pass
        try:
            self.toast.close_all()
        except Exception:
            pass
        self.reader.stop()
        if self.tray:
            self.tray.stop()
        # activation 句柄随进程退出由系统回收，避免与等待中的线程竞争
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main():
    parser = argparse.ArgumentParser(description="Razer 无线键鼠电量工具")
    parser.add_argument("--debug", action="store_true", help="附加调试界面")
    parser.add_argument("--no-tray", action="store_true", help="不显示系统托盘")
    parser.add_argument("--minimized", action="store_true", help="启动时只显示托盘")
    parser.add_argument("--demo", action="store_true", help="演示模式：使用假数据（截图/录屏用）")
    parser.add_argument("--smoke", type=int, default=0, help="冒烟测试：启动 N 秒后自动退出")
    args = parser.parse_args()

    if args.demo:
        # 演示模式：固定参数，不读写 config.json / state.json
        cfg = config_mod.Config({
            "interval": 30,
            "low_threshold": 10,
            "confirm_reads": 1,
            "popup_seconds": 15,
            "ignore_zero": True,
            "alerts_enabled": True,
            "tray_icon_style": "device",
            "start_minimized": False,
        })
    else:
        cfg = config_mod.Config.load(CONFIG_PATH)

    si = single_instance.SingleInstance()
    if not si.acquire():
        # 已有实例在运行：唤起它的面板，然后退出
        single_instance.ActivationSignal().signal()
        print("Razer 电量工具已在运行，已唤起其面板。")
        return 0

    activation = single_instance.ActivationSignal()
    activation.create()

    root = tk.Tk()
    root.title("Razer 无线键鼠电量 v%s" % __version__)
    root.geometry("380x620+880+448" if args.demo else "380x620")
    root.resizable(False, False)
    if args.minimized and not args.demo:
        root.withdraw()

    app = App(root, args, cfg, activation)

    try:
        root.mainloop()
    finally:
        si.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
