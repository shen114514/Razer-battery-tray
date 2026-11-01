"""config.json 的读写与校验（无第三方依赖）。

字段（全部可选，缺失或非法值自动回落到默认值）：
    interval             刷新间隔（秒），只能取 INTERVAL_OPTIONS 里的值
    low_threshold        低电量阈值（%），默认 10
    confirm_reads        连续确认次数，默认 2
    rearm_margin         回差（%），默认 5
    cooldown_minutes     重复提醒冷却（分钟），默认 60
    popup_seconds        弹窗停留秒数（0 = 不自动关闭），默认 15
    ignore_zero          忽略 0% 异常读数（设备待机保护），默认 true
    alerts_enabled       低电量提醒总开关，默认 true
    tray_icon_style      托盘图标样式："number"（电量数字）/ "device"（设备图标）
    start_minimized      开机自启时只显示托盘，默认 true
"""

import json
import os

INTERVAL_OPTIONS = [
    ("30 秒", 30),
    ("1 分钟", 60),
    ("2 分钟", 120),
    ("5 分钟", 300),
    ("10 分钟", 600),
    ("15 分钟", 900),
    ("30 分钟", 1800),
]

DEFAULTS = {
    "interval": 60,
    "low_threshold": 10,
    "confirm_reads": 2,
    "rearm_margin": 5,
    "cooldown_minutes": 60,
    "popup_seconds": 15,
    "ignore_zero": True,
    "alerts_enabled": True,
    "tray_icon_style": "device",
    "start_minimized": True,
}

TRAY_ICON_STYLES = ("number", "device")


def _as_int(value, default, lo, hi):
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _as_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "是")
    return default


def _snap_interval(value):
    n = _as_int(value, DEFAULTS["interval"], 30, 1800)
    return min((secs for _, secs in INTERVAL_OPTIONS), key=lambda s: abs(s - n))


class Config:
    def __init__(self, data=None):
        data = data if isinstance(data, dict) else {}
        self.interval = _snap_interval(data.get("interval", DEFAULTS["interval"]))
        self.low_threshold = _as_int(data.get("low_threshold"), DEFAULTS["low_threshold"], 1, 50)
        self.confirm_reads = _as_int(data.get("confirm_reads"), DEFAULTS["confirm_reads"], 1, 10)
        self.rearm_margin = _as_int(data.get("rearm_margin"), DEFAULTS["rearm_margin"], 0, 30)
        self.cooldown_minutes = _as_int(
            data.get("cooldown_minutes"), DEFAULTS["cooldown_minutes"], 0, 1440
        )
        self.popup_seconds = _as_int(data.get("popup_seconds"), DEFAULTS["popup_seconds"], 0, 600)
        self.ignore_zero = _as_bool(data.get("ignore_zero"), DEFAULTS["ignore_zero"])
        self.alerts_enabled = _as_bool(data.get("alerts_enabled"), DEFAULTS["alerts_enabled"])
        style = data.get("tray_icon_style", DEFAULTS["tray_icon_style"])
        self.tray_icon_style = style if style in TRAY_ICON_STYLES else DEFAULTS["tray_icon_style"]
        self.start_minimized = _as_bool(data.get("start_minimized"), DEFAULTS["start_minimized"])

    @classmethod
    def load(cls, path):
        try:
            # utf-8-sig：兼容记事本另存为「UTF-8 带 BOM」的情况
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {}
        return cls(data)

    def to_dict(self):
        return {
            "interval": self.interval,
            "low_threshold": self.low_threshold,
            "confirm_reads": self.confirm_reads,
            "rearm_margin": self.rearm_margin,
            "cooldown_minutes": self.cooldown_minutes,
            "popup_seconds": self.popup_seconds,
            "ignore_zero": self.ignore_zero,
            "alerts_enabled": self.alerts_enabled,
            "tray_icon_style": self.tray_icon_style,
            "start_minimized": self.start_minimized,
        }

    def update(self, values):
        """按字典批量更新（只接受已知字段），返回自身。"""
        for key, value in (values or {}).items():
            if hasattr(self, key):
                setattr(self, key, value)
        # 再走一遍校验，防止对话框传入越界值
        clean = Config(self.to_dict())
        for key in DEFAULTS:
            setattr(self, key, getattr(clean, key))
        return self

    def save(self, path):
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True
        except OSError:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return False
