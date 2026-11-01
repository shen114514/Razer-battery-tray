"""设备电量状态机：把一次 HID 读取结果折叠成可展示的状态。

背景：无线键盘会自动待机省电，此时读取可能「成功」但返回 0（或干脆超时）。
如果直接把 0 当成真实电量，就会反复弹出「电量 0%」的假警报。

处理策略：
  - 0%（以及负值）视为无效读数，默认忽略（可配置），不更新显示、不触发提醒；
  - 保留上一次有效电量，界面不会在 0 与真实值之间来回跳；
  - 连续 0% → 状态 standby（设备待机）；连续失败 → 状态 error（无响应）；
  - 状态里带 last_valid_ts，面板/托盘据此明确标注「旧数据」。

本模块只做纯数据折叠，不依赖 Tkinter，可在任意线程调用（内部加锁）。
"""

import json
import os
import threading
import time
from dataclasses import dataclass, replace

STATUS_OK = "ok"
STATUS_STANDBY = "standby"
STATUS_ERROR = "error"
STATUS_UNKNOWN = "unknown"
STATUS_DISCONNECTED = "disconnected"
STATUS_CACHED = "cached"          # 本次运行还没读到，显示上次运行的有效值

# 面板状态文案
STATUS_TEXT = {
    STATUS_OK: "正常",
    STATUS_STANDBY: "设备待机",
    STATUS_ERROR: "读取无响应",
    STATUS_UNKNOWN: "等待读取",
    STATUS_DISCONNECTED: "未连接",
    STATUS_CACHED: "上次读数",
}


@dataclass(frozen=True)
class DeviceState:
    key: str
    name: str
    connected: bool = False
    percent: int | None = None          # 最近一次有效电量（0 不会写入）
    raw: int | None = None
    last_valid_ts: float = 0.0          # 最近一次有效读数时间
    last_attempt_ts: float = 0.0        # 最近一次尝试时间（无论成败）
    status: str = STATUS_UNKNOWN
    error: str = ""
    zero_streak: int = 0                # 连续 0% 次数
    fail_streak: int = 0                # 连续失败次数

    @property
    def fresh(self):
        """最近一次读数是否有效且新鲜。"""
        return self.status == STATUS_OK

    @property
    def has_value(self):
        return self.percent is not None

    def valid_time_text(self):
        if not self.last_valid_ts:
            return "--:--:--"
        return time.strftime("%H:%M:%S", time.localtime(self.last_valid_ts))

    def attempt_time_text(self):
        if not self.last_attempt_ts:
            return "--:--:--"
        return time.strftime("%H:%M:%S", time.localtime(self.last_attempt_ts))

    def age_text(self, now=None):
        """「刚刚 / 3 分钟前 / 2 小时前」，用于提示数据新鲜度。"""
        if not self.last_valid_ts:
            return ""
        now = time.time() if now is None else now
        secs = max(0, int(now - self.last_valid_ts))
        if secs < 60:
            return "刚刚"
        if secs < 3600:
            return "%d 分钟前" % (secs // 60)
        if secs < 86400:
            return "%d 小时前" % (secs // 3600)
        return "%d 天前" % (secs // 86400)


class BatteryStore:
    """所有设备的电量状态表（线程安全）。"""

    def __init__(self, ignore_zero=True):
        self._lock = threading.Lock()
        self._states = {}
        self.ignore_zero = bool(ignore_zero)

    # ---- 设备注册 / 连接状态 ----
    def ensure(self, key, name):
        with self._lock:
            st = self._states.get(key)
            if st is None:
                self._states[key] = DeviceState(key=key, name=name)
                return self._states[key]
            if name and st.name != name:
                self._states[key] = replace(st, name=name)
            return self._states[key]

    def set_connected(self, key, connected, name=None):
        with self._lock:
            st = self._states.get(key) or DeviceState(key=key, name=name or key)
            if name:
                st = replace(st, name=name)
            if connected:
                if not st.connected:
                    # 刚连上：等待一次新读数，避免把旧值当成新数据
                    status = STATUS_CACHED if (st.percent is not None and st.last_valid_ts) else STATUS_UNKNOWN
                    st = replace(st, connected=True, status=status, zero_streak=0, fail_streak=0)
            else:
                st = replace(st, connected=False, status=STATUS_DISCONNECTED)
            self._states[key] = st
            return st

    # ---- 上次运行的有效值（冷启动时避免显示 -- / ?） ----
    def seed(self, cache):
        """cache: {key: {"percent": int, "ts": float, "raw": int}}。"""
        with self._lock:
            for key, item in (cache or {}).items():
                st = self._states.get(key)
                if st is None:
                    continue
                try:
                    percent = int(item.get("percent"))
                    ts = float(item.get("ts") or 0.0)
                except (TypeError, ValueError, AttributeError):
                    continue
                if not (0 < percent <= 100):
                    continue
                self._states[key] = replace(
                    st,
                    percent=percent,
                    raw=item.get("raw"),
                    last_valid_ts=ts,
                    status=STATUS_CACHED,
                    error="本次运行尚未读到新数据",
                )

    # ---- 吸收一次读取结果 ----
    def apply(self, res):
        """res: reader.ReadResult（有 key/name/percent/raw/success/timestamp/error）。"""
        with self._lock:
            st = self._states.get(res.key)
            if st is None:
                st = DeviceState(key=res.key, name=res.name)
            name = res.name or st.name
            ts = res.timestamp or time.time()

            if res.success and res.percent is not None:
                if self.ignore_zero and res.percent <= 0:
                    # 待机/假 0：保留旧值，只标记状态
                    st = replace(
                        st, name=name, connected=True,
                        last_attempt_ts=ts,
                        status=STATUS_STANDBY,
                        zero_streak=st.zero_streak + 1,
                        fail_streak=0,
                        error=res.error or "读到 0%（疑似设备待机，已忽略）",
                    )
                else:
                    st = replace(
                        st, name=name, connected=True,
                        percent=int(res.percent), raw=res.raw,
                        last_valid_ts=ts, last_attempt_ts=ts,
                        status=STATUS_OK,
                        zero_streak=0, fail_streak=0,
                        error="",
                    )
            else:
                st = replace(
                    st, name=name, connected=True,
                    last_attempt_ts=ts,
                    status=STATUS_ERROR,
                    zero_streak=0,
                    fail_streak=st.fail_streak + 1,
                    error=res.error or "读取超时/无响应",
                )
            self._states[res.key] = st
            return st

    # ---- 查询 ----
    def get(self, key):
        with self._lock:
            return self._states.get(key)

    def all(self):
        with self._lock:
            return list(self._states.values())


# ---- 上次运行有效值的持久化（state.json） ----
def load_cached(path):
    """读取上次运行保存的有效电量；任何异常都返回空表。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    devices = data.get("devices") if isinstance(data, dict) else None
    return devices if isinstance(devices, dict) else {}


def save_cached(path, states):
    """原子写入有效电量（0/None 不保存）。"""
    payload = {"version": 1, "devices": {}}
    for st in states:
        if st.percent is None:
            continue
        try:
            percent = int(st.percent)
        except (TypeError, ValueError):
            continue
        if not (0 < percent <= 100):
            continue
        payload["devices"][st.key] = {
            "percent": percent,
            "ts": round(float(st.last_valid_ts), 3),
            "raw": st.raw,
        }
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False
