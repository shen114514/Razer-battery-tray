"""低电量提醒策略（纯逻辑，可单测）。

规则（针对「键盘待机读到 0% 反复弹窗」设计）：
  1. 只有 status == ok 的**新鲜有效**读数才参与判断；0%/待机/无响应一律不提醒。
  2. 必须连续 confirm_reads 次（默认 2 次）读到 0 < pct < threshold 才提醒，
     偶发抽风一次不会打扰用户。
  3. 提醒后进入「已告知」状态，只有电量回升到 threshold + rearm_margin 以上
     才重新武装（回差，避免在阈值附近反复弹）。
  4. 冷却时间内不重复提醒（默认 60 分钟），即使回差后再次掉下来。
"""

import time
from dataclasses import dataclass, field

from .levels import level_of
from .state import STATUS_OK


@dataclass
class AlertSettings:
    enabled: bool = True
    threshold: int = 10          # 低于此百分比触发
    confirm_reads: int = 2       # 连续确认次数
    rearm_margin: int = 5        # 回差：回升到 threshold + margin 才重新武装
    cooldown_minutes: int = 60   # 冷却时间（0 = 不冷却）

    @classmethod
    def from_config(cls, cfg):
        return cls(
            enabled=bool(getattr(cfg, "alerts_enabled", True)),
            threshold=int(getattr(cfg, "low_threshold", 10)),
            confirm_reads=max(1, int(getattr(cfg, "confirm_reads", 2))),
            rearm_margin=max(0, int(getattr(cfg, "rearm_margin", 5))),
            cooldown_minutes=max(0, int(getattr(cfg, "cooldown_minutes", 60))),
        )


@dataclass
class LowAlert:
    key: str
    name: str
    percent: int
    timestamp: float
    level: str = "crit"


@dataclass
class _DeviceTrack:
    streak: int = 0
    armed: bool = True
    last_alert_ts: float = 0.0


@dataclass
class LowBatteryMonitor:
    settings: AlertSettings = field(default_factory=AlertSettings)
    _tracks: dict = field(default_factory=dict, repr=False)

    def configure(self, settings):
        self.settings = settings

    def _track(self, key):
        t = self._tracks.get(key)
        if t is None:
            t = _DeviceTrack()
            self._tracks[key] = t
        return t

    def reset(self, key=None):
        if key is None:
            self._tracks.clear()
        else:
            self._tracks.pop(key, None)

    def evaluate(self, state, now=None):
        """返回 LowAlert 或 None。state 为 state.DeviceState。"""
        s = self.settings
        if not s.enabled:
            return None
        # 只信任新鲜的有效读数：待机 / 无响应 / 未连接都不提醒
        if state is None or state.status != STATUS_OK or state.percent is None:
            return None
        pct = int(state.percent)
        now = time.time() if now is None else now
        track = self._track(state.key)

        if pct >= s.threshold + s.rearm_margin:
            track.streak = 0
            track.armed = True
            return None
        if pct >= s.threshold:
            track.streak = 0
            return None

        # 0 < pct < threshold
        track.streak += 1
        if not track.armed:
            return None
        if track.streak < s.confirm_reads:
            return None
        if s.cooldown_minutes > 0 and track.last_alert_ts:
            if now - track.last_alert_ts < s.cooldown_minutes * 60:
                return None
        track.armed = False
        track.last_alert_ts = now
        return LowAlert(
            key=state.key,
            name=state.name,
            percent=pct,
            timestamp=now,
            level=level_of(pct),
        )
