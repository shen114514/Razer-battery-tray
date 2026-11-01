"""单实例：命名互斥量 + 命名事件。

- 互斥量保证只运行一个实例；
- 第二次启动时 SetEvent 唤醒已运行实例的面板（相当于「双击图标」），
  而不是像以前那样默默退出。
"""

import ctypes
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258

_MUTEX_NAME = "Local\\RazerBatteryTool_SingleInstance_9F3C"
_EVENT_NAME = "Local\\RazerBatteryTool_Activate_9F3C"

kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.SetEvent.restype = wintypes.BOOL
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


class SingleInstance:
    def __init__(self):
        self._handle = None

    def acquire(self):
        """尝试获取单实例锁；已被占用返回 False。"""
        h = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        err = ctypes.get_last_error()
        if err == ERROR_ALREADY_EXISTS:
            if h:
                kernel32.CloseHandle(h)
            return False
        self._handle = h
        return True

    def release(self):
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None


class ActivationSignal:
    """跨进程「请打开面板」信号（自动重置事件）。"""

    def __init__(self):
        self._handle = None

    def create(self):
        self._handle = kernel32.CreateEventW(None, False, False, _EVENT_NAME)
        return bool(self._handle)

    def wait(self, timeout=0.5):
        if not self._handle:
            return False
        return kernel32.WaitForSingleObject(self._handle, int(timeout * 1000)) == WAIT_OBJECT_0

    def signal(self):
        """在其他实例中调用：打开（或创建）事件并触发一次。"""
        h = kernel32.CreateEventW(None, False, False, _EVENT_NAME)
        if not h:
            return False
        try:
            return bool(kernel32.SetEvent(h))
        finally:
            kernel32.CloseHandle(h)

    def close(self):
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None
