"""Windows API 常量与结构体定义（ctypes）。

本模块只放与 HID / SetupAPI 相关的通用定义；托盘、COM 等各自模块内自持。
所有结构体字段宽度严格按 Win32 头文件布局，兼容 32/64 位。
"""

import ctypes
from ctypes import wintypes

# 指针宽度无符号/有符号整数（wintypes 在部分版本不提供 ULONG_PTR）
ULONG_PTR = ctypes.c_size_t
LONG_PTR = ctypes.c_ssize_t

# ---------------------------------------------------------------------------
# 基础常量
# ---------------------------------------------------------------------------
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = 0xFFFFFFFFFFFFFFFF


def invalid_handle(h):
    """判断句柄是否为无效值（含 c_void_p 的 None/0 与全 1 两种表示）。"""
    return h is None or h in (0, -1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF)

# SetupAPI
DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010
DIGCF_ALLCLASSES = 0x00000004

SPDRP_DEVICEDESC = 0x00000000
SPDRP_HARDWAREID = 0x00000001
SPDRP_MFG = 0x00000011
SPDRP_FRIENDLYNAME = 0x0000000C
SPDRP_PARENT = 0x0000001E
SPDRP_LOCATION_INFORMATION = 0x0000000D

# HID 状态码
HIDP_STATUS_SUCCESS = 0x00110000

# GUID_DEVINTERFACE_HID = {4D1E55B2-F16F-11CF-88CB-001111000030}
GUID_DEVINTERFACE_HID = (
    0x4D1E55B2,
    0xF16F,
    0x11CF,
    (0x88, 0xCB, 0x00, 0x11, 0x11, 0x00, 0x00, 0x30),
)


# ---------------------------------------------------------------------------
# 结构体
# ---------------------------------------------------------------------------
class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]

    @classmethod
    def from_tuple(cls, t):
        g = cls()
        g.Data1, g.Data2, g.Data3 = t[0], t[1], t[2]
        g.Data4 = (ctypes.c_byte * 8)(*t[3])
        return g

    def as_string(self):
        d4 = "".join("%02X" % (b & 0xFF) for b in self.Data4)
        return "{%08X-%04X-%04X-%s-%s}" % (
            self.Data1,
            self.Data2,
            self.Data3,
            d4[:4],
            d4[4:],
        )


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ULONG_PTR),
    ]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", GUID),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ULONG_PTR),
    ]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.ULONG),
        ("VendorID", wintypes.USHORT),
        ("ProductID", wintypes.USHORT),
        ("VersionNumber", wintypes.USHORT),
    ]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


def guid_from_tuple(t):
    return GUID.from_tuple(t)


GUID_HID = GUID.from_tuple(GUID_DEVINTERFACE_HID)
