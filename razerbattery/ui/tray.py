"""Windows 原生托盘：Shell_NotifyIconW + NOTIFYICONDATAW，独立消息循环线程。

- 图标：默认显示「设备图形 + 电量数字」（颜色 = 电量等级，待机/旧数据会压暗），
  也可在设置里切换为仅电量数字。
- 左键：打开电量面板；中键：立即刷新；右键：菜单（电量摘要 / 打开面板 /
  立即刷新 / 暂停自动刷新 / 低电量提醒开关 / 设置 / 退出）。
- SetTimer 驱动周期刷新；定时器通过自定义消息切回托盘线程设置，避免跨线程 SetTimer。
- 悬停 tooltip：设备名 + 电量 + 更新时间 + 状态。
- 退出：删除全部图标、KillTimer、销毁窗口、PostQuitMessage。
"""

import ctypes
import threading
from ctypes import wintypes

from .. import winapi as W
from ..levels import dim, rgb_of
from . import icons

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# NOTIFYICONDATA 常量
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 0x1
NIF_ICON = 0x2
NIF_TIP = 0x4
NIF_INFO = 0x10

NIIF_INFO = 0x1
NIIF_WARNING = 0x2

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_TIMER = 0x0113
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_MBUTTONUP = 0x0208

TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
TPM_NONOTIFY = 0x0080
MF_STRING = 0x0
MF_SEPARATOR = 0x800
MF_GRAYED = 0x1
MF_CHECKED = 0x8

MENU_OPEN = 1
MENU_REFRESH = 2
MENU_PAUSE = 3
MENU_ALERTS = 4
MENU_SETTINGS = 5
MENU_EXIT = 6

TIMER_ID = 1


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", W.GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


# ---- 函数原型（64 位句柄/指针必须显式声明） ----
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = ctypes.c_long
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_long
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_ulonglong, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL
user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.DestroyMenu.restype = wintypes.BOOL
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_ulonglong, wintypes.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_ulonglong
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_ulonglong]
user32.KillTimer.restype = wintypes.BOOL
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class TrayManager:
    def __init__(self, refresh_cb, event_cb):
        """
        refresh_cb: 线程安全、不碰 Tkinter 的刷新回调（如 reader.request_all）。
        event_cb:   线程安全的事件回调，接收 ("open_panel",) / ("refresh",) /
                    ("toggle_pause",) / ("toggle_alerts",) / ("settings",) / ("quit",)。
        """
        self._refresh_cb = refresh_cb
        self._event_cb = event_cb
        self._thread = None
        self._hwnd = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._cb_msg = 0x8000  # WM_APP
        self._cmd_msg = 0x8001  # WM_APP + 1：从任意线程请求设置定时器
        self._icons = {}  # key -> {"uid", "hicon", "owned", "sig"}
        self._next_uid = 1
        self._wndproc_func = WNDPROC(self._wndproc)
        self._interval_ms = 60000
        self._style = "number"
        self._paused = False
        self._alerts = True
        self._status_lines = []
        self._lock = threading.Lock()

    # ---------- 消息循环线程 ----------
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="tray")
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def _run(self):
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = ctypes.cast(self._wndproc_func, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.lpszClassName = "RazerBatteryTrayWnd"
        if not user32.RegisterClassW(ctypes.byref(wc)):
            self._ready.set()
            return
        self._hwnd = user32.CreateWindowExW(0, "RazerBatteryTrayWnd", "", 0, 0, 0, 0, 0, None, None, hinst, None)
        if not self._hwnd:
            self._ready.set()
            return
        user32.SetTimer(self._hwnd, TIMER_ID, self._interval_ms, None)
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.DestroyWindow(self._hwnd)
        self._hwnd = None

    # ---------- 窗口过程 ----------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == self._cb_msg:
            mouse = lparam & 0xFFFF
            if mouse == WM_LBUTTONUP:
                self._emit(("open_panel",))
                return 0
            if mouse == WM_MBUTTONUP:
                self._refresh()
                return 0
            if mouse == WM_RBUTTONUP:
                self._show_menu()
                return 0
        elif msg == self._cmd_msg:
            user32.KillTimer(hwnd, TIMER_ID)
            user32.SetTimer(hwnd, TIMER_ID, int(wparam) & 0xFFFFFFFF, None)
            return 0
        elif msg == WM_TIMER:
            if wparam == TIMER_ID:
                if not self._paused:
                    self._refresh()
                return 0
        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ---------- 回调 ----------
    def _refresh(self):
        try:
            if self._refresh_cb:
                self._refresh_cb()
        except Exception:
            pass

    def _emit(self, ev):
        try:
            if self._event_cb:
                self._event_cb(ev)
        except Exception:
            pass

    # ---------- 菜单 ----------
    def set_status(self, lines):
        """主线程推送菜单顶部摘要（每个设备一行）。"""
        with self._lock:
            self._status_lines = list(lines or [])

    def set_flags(self, paused=None, alerts_enabled=None):
        with self._lock:
            if paused is not None:
                self._paused = bool(paused)
            if alerts_enabled is not None:
                self._alerts = bool(alerts_enabled)

    def _show_menu(self):
        with self._lock:
            lines = list(self._status_lines)
            paused = self._paused
            alerts = self._alerts
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        for line in lines[:3]:
            user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, line[:80])
        if lines:
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, MENU_OPEN, "打开电量面板")
        user32.AppendMenuW(menu, MF_STRING, MENU_REFRESH, "立即刷新")
        user32.AppendMenuW(
            menu, MF_STRING | (MF_CHECKED if paused else 0), MENU_PAUSE, "暂停自动刷新"
        )
        user32.AppendMenuW(
            menu, MF_STRING | (MF_CHECKED if alerts else 0), MENU_ALERTS, "低电量提醒"
        )
        user32.AppendMenuW(menu, MF_STRING, MENU_SETTINGS, "设置…")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, MENU_EXIT, "退出")

        user32.SetForegroundWindow(self._hwnd)
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        cmd = user32.TrackPopupMenu(
            menu, TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_NONOTIFY, pt.x, pt.y, 0, self._hwnd, None
        )
        user32.PostMessageW(self._hwnd, 0x0000, 0, 0)
        user32.DestroyMenu(menu)

        if cmd == MENU_OPEN:
            self._emit(("open_panel",))
        elif cmd == MENU_REFRESH:
            self._refresh()
        elif cmd == MENU_PAUSE:
            self._emit(("toggle_pause",))
        elif cmd == MENU_ALERTS:
            self._emit(("toggle_alerts",))
        elif cmd == MENU_SETTINGS:
            self._emit(("settings",))
        elif cmd == MENU_EXIT:
            self._emit(("quit",))

    # ---------- 图标管理（任意线程可调用） ----------
    def set_icon_style(self, style):
        self._style = style if style in ("number", "device") else "number"
        for entry in self._icons.values():
            entry["sig"] = None

    def _make_icon(self, percent, fresh, connected, kind=None):
        """返回 (hicon, 是否由本模块创建并需要销毁)。"""
        if self._style == "device" and kind in ("mouse", "keyboard"):
            value = percent if connected else None
            return icons.battery_icon(value, fresh and connected, kind=kind), True
        if not connected or percent is None or percent <= 0:
            return icons.badge_icon("?", rgb_of(None)), True
        color = rgb_of(percent)
        if not fresh:
            color = dim(color)
        return icons.badge_icon(str(int(percent)), color), True

    def add_device(self, key, tooltip, kind=None):
        if key in self._icons:
            return
        uid = self._next_uid
        self._next_uid += 1
        hicon, owned = self._make_icon(None, False, False, kind)
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = uid
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = self._cb_msg
        nid.hIcon = hicon
        nid.szTip = tooltip[:127]
        if shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            self._icons[key] = {"uid": uid, "hicon": hicon, "owned": owned, "sig": None}
        elif owned:
            icons.destroy_icon(hicon)

    def update_device(
        self, key, percent, tooltip, fresh=True, connected=True, kind=None
    ):
        entry = self._icons.get(key)
        if not entry:
            self.add_device(key, tooltip, kind)
            entry = self._icons.get(key)
            if not entry:
                return
        try:
            pct = None if percent is None else int(percent)
        except (TypeError, ValueError):
            pct = None
        sig = (self._style, bool(connected), pct, bool(fresh), kind)

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = entry["uid"]
        nid.uFlags = NIF_TIP | NIF_MESSAGE
        nid.uCallbackMessage = self._cb_msg
        nid.szTip = tooltip[:127]

        changed = entry.get("sig") != sig
        new_icon = None
        new_owned = False
        if changed:
            new_icon, new_owned = self._make_icon(pct, fresh, connected, kind)
            if new_icon:
                nid.uFlags |= NIF_ICON
                nid.hIcon = new_icon

        applied = bool(shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid)))
        if not applied:
            # Explorer 重启后原图标丢失：重新添加
            add = NOTIFYICONDATAW()
            add.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            add.hWnd = self._hwnd
            add.uID = entry["uid"]
            add.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            add.uCallbackMessage = self._cb_msg
            add.hIcon = new_icon if new_icon else entry.get("hicon")
            add.szTip = tooltip[:127]
            applied = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(add)))

        if changed and new_icon:
            if applied:
                if entry.get("owned") and entry.get("hicon") and entry["hicon"] != new_icon:
                    icons.destroy_icon(entry["hicon"])
                entry["hicon"] = new_icon
                entry["owned"] = new_owned
                entry["sig"] = sig
            elif new_owned:
                icons.destroy_icon(new_icon)

    def remove_device(self, key):
        entry = self._icons.pop(key, None)
        if not entry:
            return
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = entry["uid"]
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        if entry.get("owned"):
            icons.destroy_icon(entry["hicon"])

    def notify(self, key, title, message, warn=False):
        """托盘气泡通知（挂在指定设备的图标上）。"""
        entry = self._icons.get(key)
        if not entry:
            return
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = entry["uid"]
        nid.uFlags = NIF_INFO
        nid.szInfo = message[:255]
        nid.szInfoTitle = title[:63]
        nid.dwInfoFlags = NIIF_WARNING if warn else NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    # ---------- 定时刷新调度 ----------
    def set_interval(self, seconds):
        """设置刷新间隔（秒）；投递消息到托盘线程设置 SetTimer。"""
        self._interval_ms = max(30, int(seconds)) * 1000
        hwnd = self._hwnd
        if hwnd:
            user32.PostMessageW(hwnd, self._cmd_msg, self._interval_ms, 0)

    # ---------- 退出 ----------
    def remove_all(self):
        for key in list(self._icons.keys()):
            self.remove_device(key)

    def stop(self):
        self._stop.set()
        hwnd = self._hwnd
        if hwnd:
            user32.KillTimer(hwnd, TIMER_ID)
            self.remove_all()
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        if self._thread:
            self._thread.join(timeout=3.0)
        self._thread = None
