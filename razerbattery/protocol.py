"""Razer 无线设备电池读取协议（HID Feature Report 交易）。

协议来源：OpenRazer / mouse_tray 已验证实现，实机验证通过。
  90 字节 payload = 8 字节头 + 80 字节数据 + XOR 校验 + pad，
  前缀 report id 0x00 组成 91 字节 feature report。
  头: [status=0x00, txid=0x1F, 0x00, 0x00, 0x00, class=0x02, id=0x07, 0x80]
  响应: status=0x02 时，[10] 为电池原始值 0..255，换算百分比。
"""

import time

from . import hid_device as HD

_TRANSACTION_ID = 0x1F
COMMAND_CLASS = 0x02
COMMAND_ID = 0x07


def build_battery_report(feature_len=91, txid=_TRANSACTION_ID):
    """构造电池查询 feature report（含 report id 0x00）。txid 区分多设备。"""
    header = [0x00, txid & 0xFF, 0x00, 0x00, 0x00, COMMAND_CLASS, COMMAND_ID, 0x80]
    crc = 0
    for b in header[2:]:
        crc ^= b
    payload = header + [0] * 80 + [crc, 0]
    report = [0x00] + payload
    if len(report) < feature_len:
        report += [0] * (feature_len - len(report))
    return bytes(report[:feature_len])


def _read_once(handle, feature_len, timeout, poll, txid, cancel=None):
    """发送一次交易并轮询响应，返回原始电池值或 None。"""
    HD.set_feature_report(handle, build_battery_report(feature_len, txid), feature_len)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancel is not None and cancel():
            return None
        r = HD.get_feature_report(handle, 0x00, feature_len)
        if len(r) > 10 and r[2] == (txid & 0xFF) and r[1] == 0x02:
            return r[10]
        time.sleep(poll)
    return None


def read_battery_raw(handle, feature_len, txid=_TRANSACTION_ID, timeout=3.0, poll=0.005, attempts=2, cancel=None):
    """读电池原始值（0..255），带重试；失败返回 None。"""
    for _ in range(attempts):
        v = _read_once(handle, feature_len, timeout, poll, txid, cancel)
        if v is not None:
            return v
    return None


def read_battery_with_params(
    handle, feature_len, txid, command_class, command_id, response_offset,
    timeout=3.0, poll=0.005,
):
    """通用交易读取（调试/手动标定用），返回 (raw_value, full_report)。"""
    header = [0x00, txid & 0xFF, 0x00, 0x00, 0x00, command_class & 0xFF, command_id & 0xFF, 0x80]
    crc = 0
    for b in header[2:]:
        crc ^= b
    payload = header + [0] * 80 + [crc, 0]
    report = [0x00] + payload
    if len(report) < feature_len:
        report += [0] * (feature_len - len(report))
    report = bytes(report[:feature_len])
    HD.set_feature_report(handle, report, feature_len)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = HD.get_feature_report(handle, 0x00, feature_len)
        if len(r) > response_offset and r[2] == (txid & 0xFF) and r[1] == 0x02:
            return r[response_offset], r
        time.sleep(poll)
    return None, None


def raw_to_percent(raw):
    """原始电池值换算为百分比（四舍五入）。"""
    if raw is None:
        return None
    return round(max(0, min(255, raw)) / 255 * 100)
