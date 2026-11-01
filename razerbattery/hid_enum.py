"""HID 设备枚举：SetupAPI + HID.dll（ctypes），无第三方依赖。

能力：
  - 枚举全部 HID 接口，得到设备路径、VID/PID/版本、Usage Page/Usage、三种报告长度、
    厂商/产品/序列号字符串、硬件 ID、父设备实例 ID 等。
  - 把设备路径解析成 SetupAPI 实例 ID，与 devinfo 快照关联，补齐注册表属性。
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field

from . import winapi as W


setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# SP_DEVICE_INTERFACE_DETAIL_DATA_W 的 cbSize：64 位下为 8，32 位下为 6
DETAIL_DATA_CBSIZE = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6


# ---------------------------------------------------------------------------
# 函数原型
# ---------------------------------------------------------------------------
setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(W.GUID),
    wintypes.LPCWSTR,
    wintypes.HWND,
    wintypes.DWORD,
]
setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE

setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(W.SP_DEVINFO_DATA),
    ctypes.POINTER(W.GUID),
    wintypes.DWORD,
    ctypes.POINTER(W.SP_DEVICE_INTERFACE_DATA),
]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL

setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(W.SP_DEVICE_INTERFACE_DATA),
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(W.SP_DEVINFO_DATA),
]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL

setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

setupapi.SetupDiEnumDeviceInfo.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.POINTER(W.SP_DEVINFO_DATA),
]
setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL

setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(W.SP_DEVINFO_DATA),
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
setupapi.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL

setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(W.SP_DEVINFO_DATA),
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
setupapi.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL

hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(W.HIDD_ATTRIBUTES)]
hid.HidD_GetAttributes.restype = wintypes.BOOL

hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_GetPreparsedData.restype = wintypes.BOOL

hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidD_FreePreparsedData.restype = wintypes.BOOL

hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(W.HIDP_CAPS)]
hid.HidP_GetCaps.restype = wintypes.LONG

hid.HidD_GetManufacturerString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetManufacturerString.restype = wintypes.BOOL
hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetProductString.restype = wintypes.BOOL
hid.HidD_GetSerialNumberString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetSerialNumberString.restype = wintypes.BOOL


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class HidDeviceInfo:
    path: str = ""
    vid: int = 0
    pid: int = 0
    version: int = 0
    usage_page: int = 0
    usage: int = 0
    input_report_len: int = 0
    output_report_len: int = 0
    feature_report_len: int = 0
    manufacturer: str = ""
    product: str = ""
    serial: str = ""
    instance_id: str = ""
    hardware_ids: list = field(default_factory=list)
    description: str = ""
    friendly_name: str = ""
    parent_instance_id: str = ""

    @property
    def vid_hex(self):
        return "0x%04X" % self.vid

    @property
    def pid_hex(self):
        return "0x%04X" % self.pid

    def short_key(self):
        return "VID_%04X&PID_%04X" % (self.vid, self.pid)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def instance_id_from_path(path: str):
    """从 HID 设备路径解析出 SetupAPI 实例 ID。

    例：\\\\?\\hid#vid_1532&pid_00b7&mi_00#7&2d2f77a&0&0000#{...}
        -> HID\\VID_1532&PID_00B7&MI_00\\7&2D2F77A&0&0000
    """
    if not path or not path.startswith("\\\\?\\"):
        return ""
    rest = path[4:]
    idx = rest.rfind("#{")
    if idx != -1:
        rest = rest[:idx]
    parts = rest.split("#")
    if len(parts) < 2:
        return ""
    enumerator = parts[0]
    device_id = parts[1]
    suffix = "#".join(parts[2:])
    iid = enumerator + "\\" + device_id
    if suffix:
        iid += "\\" + suffix
    return iid.upper()


def _read_reg_prop(dev_info, dev_data, prop):
    """读一个注册表属性；返回字符串（多值以 '\\0' 分隔保留原样）或 ''。"""
    data_type = wintypes.DWORD()
    size = wintypes.DWORD()
    setupapi.SetupDiGetDeviceRegistryPropertyW(
        dev_info, dev_data, prop, ctypes.byref(data_type), None, 0, ctypes.byref(size)
    )
    if size.value == 0:
        return ""
    buf = ctypes.create_string_buffer(size.value)
    ok = setupapi.SetupDiGetDeviceRegistryPropertyW(
        dev_info, dev_data, prop, ctypes.byref(data_type), buf, size.value, ctypes.byref(size)
    )
    if not ok:
        return ""
    raw = buf.raw[: size.value]
    if data_type.value == 1:  # REG_SZ：单个 UTF-16 字符串，去掉尾部空字符
        return raw.decode("utf-16-le", "replace").rstrip("\x00")
    # REG_MULTI_SZ 或其它：按 UTF-16 解码，保留内嵌空字符供上层切分
    return raw.decode("utf-16-le", "replace")


def build_devinfo_snapshot():
    """枚举全部存在的设备，建立 实例ID(大写) -> 属性字典 的映射。"""
    snap = {}
    dev_info = setupapi.SetupDiGetClassDevsW(None, None, None, W.DIGCF_ALLCLASSES | W.DIGCF_PRESENT)
    if W.invalid_handle(dev_info):
        return snap
    try:
        idx = 0
        while True:
            dev_data = W.SP_DEVINFO_DATA()
            dev_data.cbSize = ctypes.sizeof(W.SP_DEVINFO_DATA)
            if not setupapi.SetupDiEnumDeviceInfo(dev_info, idx, ctypes.byref(dev_data)):
                break
            idx += 1
            need = wintypes.DWORD()
            setupapi.SetupDiGetDeviceInstanceIdW(
                dev_info, ctypes.byref(dev_data), None, 0, ctypes.byref(need)
            )
            if need.value == 0:
                continue
            buf = ctypes.create_unicode_buffer(need.value)
            if not setupapi.SetupDiGetDeviceInstanceIdW(
                dev_info, ctypes.byref(dev_data), buf, need.value, ctypes.byref(need)
            ):
                continue
            iid = buf.value.upper()
            entry = {
                "hardware_ids": _read_reg_prop(dev_info, ctypes.byref(dev_data), W.SPDRP_HARDWAREID),
                "description": _read_reg_prop(dev_info, ctypes.byref(dev_data), W.SPDRP_DEVICEDESC),
                "friendly_name": _read_reg_prop(dev_info, ctypes.byref(dev_data), W.SPDRP_FRIENDLYNAME),
                "mfg": _read_reg_prop(dev_info, ctypes.byref(dev_data), W.SPDRP_MFG),
                "parent": _read_reg_prop(dev_info, ctypes.byref(dev_data), W.SPDRP_PARENT),
            }
            snap[iid] = entry
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(dev_info)
    return snap


def enumerate_hid_devices():
    """枚举全部 HID 接口，返回 HidDeviceInfo 列表。"""
    result = []
    snap = build_devinfo_snapshot()

    dev_info = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(W.GUID_HID), None, None, W.DIGCF_PRESENT | W.DIGCF_DEVICEINTERFACE
    )
    if W.invalid_handle(dev_info):
        return result
    try:
        idx = 0
        while True:
            if_data = W.SP_DEVICE_INTERFACE_DATA()
            if_data.cbSize = ctypes.sizeof(W.SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                dev_info, None, ctypes.byref(W.GUID_HID), idx, ctypes.byref(if_data)
            ):
                break
            idx += 1

            # 第一遍拿所需缓冲区大小
            need = wintypes.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                dev_info, ctypes.byref(if_data), None, 0, ctypes.byref(need), None
            )
            if need.value == 0:
                continue
            buf = ctypes.create_string_buffer(need.value)
            # 把 cbSize 写进缓冲区头部（64 位为 8，32 位为 6）
            ctypes.c_uint32.from_buffer(buf, 0).value = DETAIL_DATA_CBSIZE
            detail_ptr = ctypes.cast(buf, ctypes.c_void_p)
            dev_data = W.SP_DEVINFO_DATA()
            dev_data.cbSize = ctypes.sizeof(W.SP_DEVINFO_DATA)
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                dev_info,
                ctypes.byref(if_data),
                detail_ptr,
                need.value,
                ctypes.byref(need),
                ctypes.byref(dev_data),
            ):
                continue
            # DevicePath 紧跟 cbSize(DWORD) 之后，偏移 4
            path = ctypes.wstring_at(ctypes.cast(buf, ctypes.c_void_p).value + 4)

            info = HidDeviceInfo(path=path)
            info.instance_id = instance_id_from_path(path)
            entry = snap.get(info.instance_id)
            if entry:
                info.hardware_ids = [s for s in entry["hardware_ids"].split("\x00") if s]
                info.description = entry["description"]
                info.friendly_name = entry["friendly_name"]
                info.parent_instance_id = entry["parent"]

            h = _open_readonly(path)
            if not W.invalid_handle(h):
                try:
                    attrs = W.HIDD_ATTRIBUTES()
                    attrs.Size = ctypes.sizeof(W.HIDD_ATTRIBUTES)
                    if hid.HidD_GetAttributes(h, ctypes.byref(attrs)):
                        info.vid = attrs.VendorID
                        info.pid = attrs.ProductID
                        info.version = attrs.VersionNumber
                    info.manufacturer = _hid_string(h, hid.HidD_GetManufacturerString)
                    info.product = _hid_string(h, hid.HidD_GetProductString)
                    info.serial = _hid_string(h, hid.HidD_GetSerialNumberString)

                    ppd = ctypes.c_void_p()
                    if hid.HidD_GetPreparsedData(h, ctypes.byref(ppd)) and ppd.value:
                        caps = W.HIDP_CAPS()
                        if hid.HidP_GetCaps(ppd, ctypes.byref(caps)) == W.HIDP_STATUS_SUCCESS:
                            info.usage_page = caps.UsagePage
                            info.usage = caps.Usage
                            info.input_report_len = caps.InputReportByteLength
                            info.output_report_len = caps.OutputReportByteLength
                            info.feature_report_len = caps.FeatureReportByteLength
                        hid.HidD_FreePreparsedData(ppd)
                finally:
                    _close(h)
            result.append(info)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(dev_info)
    return result


def _open_readonly(path):
    """用最小权限打开设备以查询元数据。

    键盘/鼠标 Collection 常被系统独占，GENERIC_WRITE 会失败；
    依次尝试 0 / GENERIC_READ / GENERIC_READ|GENERIC_WRITE。
    """
    for access in (0, W.GENERIC_READ, W.GENERIC_READ | W.GENERIC_WRITE):
        h = kernel32.CreateFileW(
            path,
            access,
            W.FILE_SHARE_READ | W.FILE_SHARE_WRITE,
            None,
            W.OPEN_EXISTING,
            0,
            None,
        )
        if not W.invalid_handle(h):
            return h
    return None


def _close(h):
    kernel32.CloseHandle(h)


def _hid_string(h, func):
    buf = ctypes.create_unicode_buffer(128)
    if func(h, buf, ctypes.sizeof(buf)):
        return buf.value
    return ""


if __name__ == "__main__":
    devs = enumerate_hid_devices()
    print("枚举到 %d 个 HID 接口\n" % len(devs))
    for d in devs:
        print("=" * 70)
        print("Product : %s" % d.product)
        print("  VID:PID : %04X:%04X  ver %d" % (d.vid, d.pid, d.version))
        print("  Usage   : page=0x%04X usage=0x%04X" % (d.usage_page, d.usage))
        print(
            "  Report  : in=%d out=%d feat=%d"
            % (d.input_report_len, d.output_report_len, d.feature_report_len)
        )
        print("  Mfg     : %s" % d.manufacturer)
        print("  Serial  : %s" % d.serial)
        print("  Desc    : %s" % d.description)
        print("  Instance: %s" % d.instance_id)
        if d.hardware_ids:
            print("  HWIDs   : %s" % "; ".join(d.hardware_ids))
        print("  Path    : %s" % d.path)
