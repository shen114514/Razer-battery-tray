"""开机自启：通过 COM IShellLink + IPersistFile 在当前用户「启动」文件夹创建 .lnk。

不使用注册表 Run 项，不依赖外部 PowerShell。目标程序 pythonw.exe，参数指向主程序，
工作目录指向项目目录，可在任务管理器「启动」中显示/启停。
"""

import ctypes
import os
from ctypes import wintypes

ole32 = ctypes.WinDLL("ole32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

CLSCTX_INPROC_SERVER = 1
COINIT_APARTMENTTHREADED = 0x2
S_OK = 0
SW_SHOWNORMAL = 1
CSIDL_STARTUP = 7


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(data1, data2, data3, d4):
    return GUID(data1, data2, data3, (ctypes.c_ubyte * 8)(*d4))


CLSID_SHELL_LINK = _guid(0x00021401, 0x0000, 0x0000, (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))
IID_ISHELL_LINK_W = _guid(0x000214F9, 0x0000, 0x0000, (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))
IID_IPERSIST_FILE = _guid(0x0000010B, 0x0000, 0x0000, (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))


def _com_method(iface, index, restype, *argtypes):
    """从接口指针取第 index 个 vtable 方法（首个参数为 this 指针）。"""
    vtbl = ctypes.cast(iface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(vtbl[index])


def _startup_folder():
    buf = ctypes.create_unicode_buffer(260)
    hr = shell32.SHGetFolderPathW(None, CSIDL_STARTUP, None, 0, buf)
    if hr != S_OK:
        return os.path.join(
            os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
        )
    return buf.value


def startup_shortcut_path(name="电量托盘.lnk"):
    return os.path.join(_startup_folder(), name)


def shortcut_exists(name="电量托盘.lnk"):
    return os.path.exists(startup_shortcut_path(name))


def create_startup_shortcut(target_exe, args, workdir, name="电量托盘.lnk", description="Razer 无线键鼠电量托盘"):
    """创建开机自启快捷方式，返回 (成功, 原因字符串)。"""
    lnk_path = startup_shortcut_path(name)
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    try:
        iface = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_SHELL_LINK),
            None,
            CLSCTX_INPROC_SERVER,
            ctypes.byref(IID_ISHELL_LINK_W),
            ctypes.byref(iface),
        )
        if hr != S_OK or not iface.value:
            return False, "CoCreateInstance 失败 (HRESULT 0x%08X)" % (hr & 0xFFFFFFFF)

        set_path = _com_method(iface, 20, ctypes.c_long, wintypes.LPCWSTR)
        set_args = _com_method(iface, 11, ctypes.c_long, wintypes.LPCWSTR)
        set_wdir = _com_method(iface, 9, ctypes.c_long, wintypes.LPCWSTR)
        set_desc = _com_method(iface, 7, ctypes.c_long, wintypes.LPCWSTR)
        set_show = _com_method(iface, 15, ctypes.c_long, wintypes.INT)
        release = _com_method(iface, 2, ctypes.c_ulong)

        set_path(iface, target_exe)
        set_args(iface, args)
        set_wdir(iface, workdir)
        set_desc(iface, description)
        set_show(iface, SW_SHOWNORMAL)

        qi = _com_method(iface, 0, ctypes.c_long, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
        pf = ctypes.c_void_p()
        hr = qi(iface, ctypes.byref(IID_IPERSIST_FILE), ctypes.byref(pf))
        if hr != S_OK or not pf.value:
            release(iface)
            return False, "QueryInterface(IPersistFile) 失败 (HRESULT 0x%08X)" % (hr & 0xFFFFFFFF)

        save = _com_method(pf, 6, ctypes.c_long, wintypes.LPCWSTR, wintypes.BOOL)
        hr = save(pf, lnk_path, True)
        release(iface)
        release(pf)
        if hr != S_OK:
            return False, "保存快捷方式失败 (HRESULT 0x%08X)" % (hr & 0xFFFFFFFF)
        return True, lnk_path
    except OSError as e:
        return False, str(e)
    finally:
        ole32.CoUninitialize()


def remove_startup_shortcut(name="电量托盘.lnk"):
    """删除开机自启快捷方式，返回 (成功, 原因)。"""
    lnk_path = startup_shortcut_path(name)
    try:
        if os.path.exists(lnk_path):
            os.remove(lnk_path)
        return True, ""
    except OSError as e:
        return False, str(e)
