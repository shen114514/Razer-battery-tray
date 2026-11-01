"""右下角低电量提示窗：无边框、置顶、不抢焦点、到点自动关闭。

- 默认 15 秒后自动关闭（可在设置里改，0 = 只手动关闭）；
- 关闭按钮 / 「打开面板」按钮；
- 同时弹出多条时向上堆叠，最多 3 条，超出时关掉最早的一条；
- 淡入淡出；使用 SetWindowPos(SWP_NOACTIVATE) 置顶，避免打断用户输入。
"""

import ctypes
import math
import time
import tkinter as tk
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

SPI_GETWORKAREA = 0x0030
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
GA_ROOT = 2


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL


def _work_area(root):
    r = _RECT()
    try:
        if user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0):
            if r.right > r.left and r.bottom > r.top:
                return r.left, r.top, r.right, r.bottom
    except OSError:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def _topmost_no_activate(win):
    try:
        hwnd = user32.GetAncestor(win.winfo_id(), GA_ROOT) or win.winfo_id()
        user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
    except (OSError, tk.TclError):
        pass


class _Toast:
    WIDTH = 380
    MARGIN = 16
    GAP = 8

    def __init__(self, manager, key, title, message, hint, rgb, seconds):
        self.manager = manager
        self.key = key
        self.height = 0
        self._closed = False
        self._jobs = []
        self._deadline = None
        color = hex_of_rgb(rgb)

        win = tk.Toplevel(manager.root)
        self.win = win
        win.withdraw()
        win.overrideredirect(True)
        win.configure(bg="#c8c8c8")
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        inner = tk.Frame(win, bg="#ffffff")
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Frame(inner, bg=color, width=6).pack(side="left", fill="y")

        body = tk.Frame(inner, bg="#ffffff", padx=14, pady=11)
        body.pack(side="left", fill="both", expand=True)

        head = tk.Frame(body, bg="#ffffff")
        head.pack(fill="x")
        tk.Label(
            head, text=title, bg="#ffffff", fg=color,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(side="left")
        close_btn = tk.Label(
            head, text="\u00d7", bg="#ffffff", fg="#9a9a9a",
            font=("Microsoft YaHei UI", 13, "bold"), cursor="hand2", padx=2,
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda _e: self.close())

        tk.Label(
            body, text=message, bg="#ffffff", fg="#333333",
            font=("Microsoft YaHei UI", 10), justify="left",
            wraplength=self.WIDTH - 64,
        ).pack(anchor="w", pady=(6, 0))

        if hint:
            tk.Label(
                body, text=hint, bg="#ffffff", fg="#8a8a8a",
                font=("Microsoft YaHei UI", 8), justify="left",
                wraplength=self.WIDTH - 64,
            ).pack(anchor="w", pady=(3, 0))

        foot = tk.Frame(body, bg="#ffffff")
        foot.pack(fill="x", pady=(9, 0))
        self.countdown = tk.Label(
            foot, text="", bg="#ffffff", fg="#9a9a9a",
            font=("Microsoft YaHei UI", 8),
        )
        self.countdown.pack(side="left")
        tk.Button(
            foot, text="知道了", command=self.close, relief="flat", bd=0,
            bg="#f1f1f1", activebackground="#e4e4e4", fg="#333333",
            font=("Microsoft YaHei UI", 9), padx=12, pady=2, cursor="hand2",
        ).pack(side="right")
        tk.Button(
            foot, text="打开面板", command=self._open_panel, relief="flat", bd=0,
            bg="#eaf2fd", activebackground="#dbe8fb", fg="#1a5fb4",
            font=("Microsoft YaHei UI", 9), padx=12, pady=2, cursor="hand2",
        ).pack(side="right", padx=(0, 6))

        win.update_idletasks()
        self.height = win.winfo_reqheight()
        win.geometry("%dx%d" % (self.WIDTH, self.height))
        self._seconds = int(seconds or 0)

    def reveal(self):
        """定位完成后再显示，避免在左上角闪一下。"""
        if self._closed:
            return
        try:
            self.win.deiconify()
            self.win.update_idletasks()
        except tk.TclError:
            return
        _topmost_no_activate(self.win)
        self._fade_in(0.15)
        if self._seconds > 0:
            self._deadline = time.monotonic() + float(self._seconds)
        self._tick()

    # ---- 位置 ----
    def move(self, x, y):
        try:
            self.win.geometry("+%d+%d" % (int(x), int(y)))
        except tk.TclError:
            pass

    # ---- 动画 ----
    def _fade_in(self, alpha):
        if self._closed:
            return
        alpha = min(1.0, alpha + 0.18)
        try:
            self.win.attributes("-alpha", alpha)
        except tk.TclError:
            return
        if alpha < 1.0:
            self._after(25, lambda: self._fade_in(alpha))

    def _fade_out(self, alpha):
        if not self._win_alive():
            self._destroy()
            return
        alpha = max(0.0, alpha - 0.2)
        try:
            self.win.attributes("-alpha", alpha)
        except tk.TclError:
            alpha = 0.0
        if alpha <= 0.0:
            self._destroy()
        else:
            self._after(20, lambda: self._fade_out(alpha))

    # ---- 定时 ----
    def _after(self, ms, fn):
        job = self.win.after(ms, fn)
        self._jobs.append(job)
        return job

    def _tick(self):
        if self._closed:
            return
        if self._deadline is not None:
            left = self._deadline - time.monotonic()
            if left <= 0:
                self.close()
                return
            try:
                self.countdown.config(text="%d 秒后自动关闭" % int(math.ceil(left)))
            except tk.TclError:
                return
        else:
            try:
                self.countdown.config(text="点「知道了」关闭")
            except tk.TclError:
                return
        self._after(250, self._tick)

    # ---- 关闭 ----
    def _win_alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _cancel_jobs(self):
        for job in self._jobs:
            try:
                self.win.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        self._jobs.clear()

    def _open_panel(self):
        self.manager.open_panel()
        self.close()

    def close(self, fade=True):
        if self._closed:
            return
        self._closed = True
        self._cancel_jobs()
        if fade:
            self._fade_out(1.0)
        else:
            self._destroy()

    def _destroy(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.manager.forget(self)


def hex_of_rgb(rgb):
    r, g, b = rgb
    return "#%02x%02x%02x" % (r, g, b)


class ToastManager:
    def __init__(self, root, on_open_panel=None, seconds=15, max_toasts=3):
        self.root = root
        self._on_open_panel = on_open_panel
        self.seconds = int(seconds)
        self.max_toasts = max(1, int(max_toasts))
        self._toasts = {}
        self._stack = []

    def set_seconds(self, seconds):
        self.seconds = int(seconds)

    def open_panel(self):
        if self._on_open_panel:
            try:
                self._on_open_panel()
            except Exception:
                pass

    def show(self, key, title, message, hint="", rgb=(210, 43, 43), seconds=None):
        old = self._toasts.get(key)
        if old is not None:
            old.close(fade=False)
        try:
            toast = _Toast(
                self, key, title, message, hint, rgb,
                self.seconds if seconds is None else int(seconds),
            )
        except tk.TclError:
            return None
        self._toasts[key] = toast
        self._stack.append(toast)
        while len(self._stack) > self.max_toasts:
            self._stack[0].close(fade=False)
        self.reposition()
        toast.reveal()
        return toast

    def forget(self, toast):
        if self._toasts.get(toast.key) is toast:
            del self._toasts[toast.key]
        try:
            self._stack.remove(toast)
        except ValueError:
            pass
        self.reposition()

    def reposition(self):
        try:
            left, top, right, bottom = _work_area(self.root)
            x = right - _Toast.WIDTH - _Toast.MARGIN
            y = bottom - _Toast.MARGIN
            for toast in reversed(self._stack):
                y -= toast.height
                toast.move(x, y)
                y -= _Toast.GAP
        except (tk.TclError, OSError):
            pass

    def close_all(self):
        for toast in list(self._stack):
            toast.close(fade=False)
