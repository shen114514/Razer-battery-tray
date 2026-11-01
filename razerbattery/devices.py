"""目标设备定义与接口→设备关联规则。

关联规则核心：Razer（VID 0x1532）设备里，带 Feature Report（feat_len > 0）
的 HID 接口就是电池/控制接口。

多设备共用一个 HyperSpeed 接收器时，所有设备会复合在同一个 PID（通常是
鼠标的 PID）下，只暴露一个带 Feature Report 的接口（如 MI_00），靠「交易 ID
txid」的高位（0x80）区分设备：鼠标 txid=0x1F，键盘 txid=0x9F。因此：
  - 设备有自己的 PID 接口 → 用自己的接口读；
  - 设备自己的 PID 接口不在线（如键盘的 02B9）→ 用共享的第一个电池接口，
    并带它自己的 txid。
"""

from dataclasses import dataclass

RAZER_VID = 0x1532


@dataclass(frozen=True)
class DeviceModel:
    key: str
    name: str
    vid: int
    pid: int | None = None          # None = PID 未验证，靠名称匹配
    txid: int = 0x1F                # 交易 ID（多设备共享接收器时用不同 txid 寻址）
    kind: str = "mouse"             # mouse / keyboard：决定托盘图标画什么
    name_patterns: tuple = ()


# pid / txid 均已实机验证。
MODELS = (
    DeviceModel("deathadder_v3_pro", "Razer DeathAdder V3 Pro", RAZER_VID, 0x00B7, 0x1F, "mouse"),
    DeviceModel("blackwidow_v4_mini_hs", "Razer BlackWidow V4 Mini HyperSpeed", RAZER_VID, 0x02B9, 0x9F, "keyboard"),
)


def match_model(hid_info):
    """给一个 HID 接口匹配设备型号，匹配不到返回 None。"""
    if hid_info.vid != RAZER_VID:
        return None
    for m in MODELS:
        if m.pid is not None and hid_info.pid == m.pid:
            return m
    text = " ".join((hid_info.product, hid_info.description, hid_info.friendly_name)).lower()
    for m in MODELS:
        if m.pid is None:
            for pat in m.name_patterns:
                if pat.lower() in text:
                    return m
    return None


def resolve_targets(hid_devices):
    """枚举结果 → [(DeviceModel, HidDeviceInfo)]。

    每个 model 关联一个电池接口：优先用自己 PID 的接口，否则用共享接口
    （多设备接收器场景，如键盘走鼠标的 MI_00）。
    """
    battery_ifs = [d for d in hid_devices if d.vid == RAZER_VID and d.feature_report_len > 0]
    if not battery_ifs:
        return []
    by_pid = {}
    for d in battery_ifs:
        by_pid.setdefault(d.pid, d)

    result = []
    for model in MODELS:
        if model.pid is not None and model.pid in by_pid:
            info = by_pid[model.pid]
        else:
            info = battery_ifs[0]  # 共享接口
        result.append((model, info))
    return result


def scan():
    """枚举并解析当前在线的目标设备。"""
    from .hid_enum import enumerate_hid_devices

    return resolve_targets(enumerate_hid_devices())
