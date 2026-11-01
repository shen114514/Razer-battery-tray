"""HID 设备句柄与读写：CreateFile + HidD_GetFeature/SetFeature/GetInputReport。

所有 HID 通信都走这里，统一句柄管理与错误处理。
"""

import ctypes
from ctypes import wintypes

from . import winapi as W

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)

kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

hid.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetFeature.restype = wintypes.BOOL
hid.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_SetFeature.restype = wintypes.BOOL
hid.HidD_GetInputReport.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetInputReport.restype = wintypes.BOOL


class HidError(Exception):
    pass


def open_battery_device(path):
    """打开电池读取句柄。

    正常情况用 READ|WRITE；若被 Razer 驱动独占（READ 被拒），降级为 WRITE-only
    ——WRITE 句柄在本机验证过同样能 GetFeature 读回电池。
    """
    try:
        return open_device(path, read=True, write=True)
    except HidError:
        return open_device(path, read=False, write=True)


def open_device(path, read=True, write=True):
    access = 0
    if read:
        access |= W.GENERIC_READ
    if write:
        access |= W.GENERIC_WRITE
    h = kernel32.CreateFileW(
        path,
        access,
        W.FILE_SHARE_READ | W.FILE_SHARE_WRITE,
        None,
        W.OPEN_EXISTING,
        0,
        None,
    )
    if W.invalid_handle(h):
        err = ctypes.get_last_error()
        raise HidError("CreateFile 失败: %s (WinError %d)" % (path, err))
    return h


def close_device(h):
    if not W.invalid_handle(h):
        kernel32.CloseHandle(h)


def get_feature_report(h, report_id, length):
    """读一个 Feature Report。buf[0]=report_id，返回完整报告字节列表。"""
    buf = (ctypes.c_ubyte * length)()
    buf[0] = report_id & 0xFF
    if not hid.HidD_GetFeature(h, buf, length):
        err = ctypes.get_last_error()
        raise HidError("HidD_GetFeature 失败 (WinError %d)" % err)
    return bytes(buf)


def set_feature_report(h, data, length=None):
    """写一个 Feature Report。data[0] 应为 report_id。"""
    n = length if length is not None else len(data)
    buf = (ctypes.c_ubyte * n)()
    for i, b in enumerate(data[:n]):
        buf[i] = b
    if not hid.HidD_SetFeature(h, buf, n):
        err = ctypes.get_last_error()
        raise HidError("HidD_SetFeature 失败 (WinError %d)" % err)
    return True


def get_input_report(h, report_id, length):
    """读一个 Input Report（同步轮询用）。"""
    buf = (ctypes.c_ubyte * length)()
    buf[0] = report_id & 0xFF
    if not hid.HidD_GetInputReport(h, buf, length):
        err = ctypes.get_last_error()
        raise HidError("HidD_GetInputReport 失败 (WinError %d)" % err)
    return bytes(buf)
