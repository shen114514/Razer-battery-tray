"""演示/录屏用的假数据源（`python main.py --demo`）。

不接触真实 HID 设备，按时间线产生可预期的读数，方便截图、录屏和演示：

    0.6s   鼠标 82%、键盘 61%（正常电量）
    20s    键盘读到 0%（模拟待机）→ 保留上次有效值，状态显示「设备待机」
    34s    鼠标降到 9% → 触发低电量弹窗（演示配置里 confirm_reads=1）

接口与 `BatteryReader` 保持一致，主程序无需区分。
"""

import os
import queue
import threading
import time

from .reader import ReadResult

DEMO_NAMES = {
    "deathadder_v3_pro": "Razer DeathAdder V3 Pro",
    "blackwidow_v4_mini_hs": "Razer BlackWidow V4 Mini HyperSpeed",
}

# (相对启动的秒数, [(key, percent, success), ...])
DEMO_TIMELINE = (
    (0.6, [("deathadder_v3_pro", 82, True), ("blackwidow_v4_mini_hs", 61, True)]),
    (20.0, [("blackwidow_v4_mini_hs", 0, True)]),
    (34.0, [("deathadder_v3_pro", 9, True)]),
)


def timeline_from_env():
    """允许用环境变量覆盖时间线（录屏时对齐旁白）：RAZER_DEMO_TIMELINE="31.5,44"."""
    raw = os.environ.get("RAZER_DEMO_TIMELINE", "").strip()
    if not raw:
        return DEMO_TIMELINE
    try:
        first, second = (float(part) for part in raw.split(",")[:2])
    except ValueError:
        return DEMO_TIMELINE
    return (
        DEMO_TIMELINE[0],
        (first, [("blackwidow_v4_mini_hs", 0, True)]),
        (second, [("deathadder_v3_pro", 9, True)]),
    )


class DemoBatteryReader:
    def __init__(self, timeline=None):
        self._q = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._t0 = time.monotonic()
        self._timeline = timeline or timeline_from_env()
        self._done = set()

    # ---- 与 BatteryReader 相同的接口 ----
    def rescan(self):
        return []

    def known_keys(self):
        return list(DEMO_NAMES)

    def request(self, key):
        return True

    def request_all(self):
        pass

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True, name="demo-reader")
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            elapsed = time.monotonic() - self._t0
            for idx, (when, events) in enumerate(self._timeline):
                if idx in self._done or elapsed < when:
                    continue
                self._done.add(idx)
                stamp = time.time()
                for key, percent, success in events:
                    raw = None if percent is None else int(percent * 255 / 100)
                    self._q.put(ReadResult(
                        key=key,
                        name=DEMO_NAMES[key],
                        percent=percent,
                        raw=raw,
                        success=success,
                        timestamp=stamp,
                        error="" if success else "演示：模拟读取失败",
                    ))
            time.sleep(0.05)

    def pump(self):
        out = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                break
        return out

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
