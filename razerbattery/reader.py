"""后台电池读取：独立工作线程 + queue.Queue，合并重复请求，不阻塞 GUI。

约束（按 spec）：
  - 后台线程执行 HID 通信，结果放队列，主线程用 root.after 泵取。
  - 后台线程不调用 Tkinter / root.after。
  - 同一设备进行中时合并重复请求（标记为待刷新），避免并发冲突。
  - 退出时置 stop 标志，轮询循环 5ms 内感知并中止，不阻塞进程退出。
"""

import queue
import threading
import time
from dataclasses import dataclass

from . import hid_device as HD
from . import protocol
from .devices import scan


@dataclass
class ReadResult:
    key: str
    name: str
    percent: int | None
    raw: int | None
    success: bool
    timestamp: float
    error: str = ""
    source: str = "HID Feature Report (Razer 协议)"


class BatteryReader:
    def __init__(self):
        self._req_queue = queue.Queue()
        self._res_queue = queue.Queue()
        self._in_flight = set()
        self._pending = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._devices = {}  # key -> {"path", "feature_len", "name"}

    # ---- 设备路径维护 ----
    def rescan(self):
        """重新枚举并更新设备路径映射；返回当前目标 [(model, info)]。"""
        targets = scan()
        new_map = {}
        for model, info in targets:
            new_map[model.key] = {
                "path": info.path,
                "feature_len": info.feature_report_len,
                "name": model.name,
                "txid": model.txid,
            }
        with self._lock:
            self._devices = new_map
        return targets

    def known_keys(self):
        with self._lock:
            return list(self._devices.keys())

    # ---- 请求入口 ----
    def request(self, key):
        """请求读取某个设备；进行中则合并为待刷新，不重复入队。"""
        with self._lock:
            if key not in self._devices:
                return False
            if key in self._in_flight:
                self._pending.add(key)
                return True
            self._in_flight.add(key)
        self._req_queue.put(key)
        return True

    def request_all(self):
        for key in self.known_keys():
            self.request(key)

    # ---- 工作线程 ----
    def _worker(self):
        while not self._stop.is_set():
            try:
                key = self._req_queue.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                result = self._read(key)
            except Exception as e:  # 兜底，任何异常都转为失败结果
                result = ReadResult(
                    key=key,
                    name=self._name(key),
                    percent=None,
                    raw=None,
                    success=False,
                    timestamp=time.time(),
                    error=str(e),
                )
            self._res_queue.put(result)
            with self._lock:
                self._in_flight.discard(key)
                if key in self._pending and not self._stop.is_set():
                    self._pending.discard(key)
                    self._in_flight.add(key)
                    self._req_queue.put(key)
            self._req_queue.task_done()

    def _name(self, key):
        with self._lock:
            dev = self._devices.get(key)
        return dev["name"] if dev else key

    def _read(self, key):
        with self._lock:
            dev = self._devices.get(key)
        if not dev:
            return ReadResult(key, self._name(key), None, None, False, time.time(), "设备未找到")
        try:
            h = HD.open_battery_device(dev["path"])
        except HD.HidError as e:
            return ReadResult(key, dev["name"], None, None, False, time.time(), "打开失败: %s" % e)
        try:
            raw = protocol.read_battery_raw(h, dev["feature_len"], txid=dev["txid"], cancel=self._stop.is_set)
        finally:
            HD.close_device(h)
        percent = protocol.raw_to_percent(raw)
        if raw is None:
            return ReadResult(key, dev["name"], None, None, False, time.time(), "读取超时/无响应")
        return ReadResult(key, dev["name"], percent, raw, True, time.time())

    # ---- 结果泵取（主线程调用） ----
    def pump(self):
        """非阻塞取出全部结果。"""
        out = []
        while True:
            try:
                out.append(self._res_queue.get_nowait())
            except queue.Empty:
                break
        return out

    # ---- 生命周期 ----
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, daemon=True, name="battery-reader")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._thread = None
