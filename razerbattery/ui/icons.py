"""托盘图标绘制：用标准 GDI 生成图标，不依赖 Pillow。

两种样式：
  - 设备图形（默认）：白色光标箭头（鼠标）/ 键盘轮廓（键盘）+ 电量数字，
    颜色即等级（绿 60-100 / 琥珀 30-59 / 橙 10-29 / 红 1-9 / 灰 未知）。
  - 电量数字：圆角彩色徽标 + 大号白色电量数字。

图标尺寸按系统 DPI 计算（Windows 在 150% 缩放时托盘小图标是 24px，
若只画 16px 会被系统放大而发虚）。

透明背景 = 32bpp 彩色位图 + 1bpp 掩码位图，CreateIconIndirect 合成。
"""

import ctypes
from ctypes import wintypes

from ..levels import dim, rgb_of

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

SM_CXSMICON = 49

BLACKNESS = 0x00000042
TRANSPARENT = 1
PS_SOLID = 0
ANTIALIASED_QUALITY = 4
DT_CENTER = 0x0001
DT_VCENTER = 0x0004
DT_SINGLELINE = 0x0020

WHITE = 0x00FFFFFF


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


# ---- 函数原型（64 位句柄/指针必须显式声明） ----
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
user32.CreateIconIndirect.restype = wintypes.HICON
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.DestroyIcon.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT]
user32.DrawTextW.restype = ctypes.c_int

gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
gdi32.CreateBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.PatBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.PatBlt.restype = wintypes.BOOL
gdi32.CreateFontW.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
]
gdi32.CreateFontW.restype = wintypes.HFONT
gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.CreatePen.restype = wintypes.HPEN
gdi32.RoundRect.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
]
gdi32.RoundRect.restype = wintypes.BOOL
gdi32.Rectangle.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.Rectangle.restype = wintypes.BOOL
gdi32.Polygon.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.POINT), ctypes.c_int]
gdi32.Polygon.restype = wintypes.BOOL
gdi32.SetBkColor.argtypes = [wintypes.HDC, wintypes.DWORD]
gdi32.SetBkColor.restype = wintypes.DWORD
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetBkMode.restype = ctypes.c_int
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
gdi32.SetTextColor.restype = wintypes.DWORD
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL

# DPI 查询：临时切换到 PerMonitorV2 线程上下文，不改变进程的 DPI 感知级别
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
if hasattr(user32, "SetThreadDpiAwarenessContext"):
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.GetDpiForSystem.argtypes = []
    user32.GetDpiForSystem.restype = ctypes.c_uint


def _colorref(rgb):
    if isinstance(rgb, int):
        return rgb & 0xFFFFFFFF
    r, g, b = rgb
    return (r & 0xFF) | ((g & 0xFF) << 8) | ((b & 0xFF) << 16)


_dpi_cache = None


def system_dpi():
    """当前会话的缩放 DPI（本进程未声明 DPI 感知，需临时切到 PerMonitorV2 查询）。"""
    global _dpi_cache
    if _dpi_cache:
        return _dpi_cache
    try:
        old = user32.SetThreadDpiAwarenessContext(
            ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        )
        try:
            dpi = int(user32.GetDpiForSystem())
        finally:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))
        if 72 <= dpi <= 480:
            _dpi_cache = dpi
            return dpi
    except (OSError, AttributeError, TypeError, ValueError):
        pass
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop\WindowMetrics") as k:
            value, _ = winreg.QueryValueEx(k, "AppliedDPI")
            dpi = int(value)
            if 72 <= dpi <= 480:
                _dpi_cache = dpi
                return dpi
    except (OSError, ValueError):
        pass
    _dpi_cache = 96
    return 96


def tray_icon_size():
    """托盘小图标的物理像素尺寸（150% 缩放 → 24）。"""
    try:
        base = int(user32.GetSystemMetrics(SM_CXSMICON)) or 16
    except (OSError, ValueError):
        base = 16
    scaled = int(round(16 * system_dpi() / 96.0))
    return max(base, min(64, max(16, scaled)))


def _text_size(size, nchars):
    """数字字号（像素高）。"""
    if nchars <= 1:
        return int(size * 0.80)
    if nchars == 2:
        return int(size * 0.68)
    return int(size * 0.52)


def _fill_round_rect(dc, x1, y1, x2, y2, radius, rgb):
    brush = gdi32.CreateSolidBrush(_colorref(rgb))
    pen = gdi32.CreatePen(PS_SOLID, 0, _colorref(rgb))
    old_brush = gdi32.SelectObject(dc, brush)
    old_pen = gdi32.SelectObject(dc, pen)
    try:
        gdi32.RoundRect(dc, x1, y1, x2, y2, max(1, radius), max(1, radius))
    finally:
        gdi32.SelectObject(dc, old_brush)
        gdi32.SelectObject(dc, old_pen)
        gdi32.DeleteObject(brush)
        gdi32.DeleteObject(pen)


def _fill_rect(dc, x1, y1, x2, y2, rgb):
    if x2 <= x1 or y2 <= y1:
        return
    brush = gdi32.CreateSolidBrush(_colorref(rgb))
    pen = gdi32.CreatePen(PS_SOLID, 0, _colorref(rgb))
    old_brush = gdi32.SelectObject(dc, brush)
    old_pen = gdi32.SelectObject(dc, pen)
    try:
        gdi32.Rectangle(dc, x1, y1, x2, y2)
    finally:
        gdi32.SelectObject(dc, old_brush)
        gdi32.SelectObject(dc, old_pen)
        gdi32.DeleteObject(brush)
        gdi32.DeleteObject(pen)


def _draw_text(dc, text, rgb, rect, font_px, weight=700):
    font = gdi32.CreateFontW(
        -max(5, int(font_px)), 0, 0, 0, weight, 0, 0, 0, 1, 0, 0,
        ANTIALIASED_QUALITY, 0, "Segoe UI",
    )
    old_font = gdi32.SelectObject(dc, font)
    try:
        gdi32.SetBkMode(dc, TRANSPARENT)
        gdi32.SetTextColor(dc, _colorref(rgb))
        user32.DrawTextW(
            dc, text, -1, ctypes.byref(rect), DT_CENTER | DT_VCENTER | DT_SINGLELINE
        )
    finally:
        gdi32.SelectObject(dc, old_font)
        gdi32.DeleteObject(font)


def _render_icon(size, paint):
    """创建彩色/掩码位图，paint(cdc, mdc) 负责绘制，返回 HICON。"""
    screen_dc = user32.GetDC(None)
    if not screen_dc:
        return None
    color_bmp = mask_bmp = color_dc = mask_dc = None
    try:
        color_bmp = gdi32.CreateCompatibleBitmap(screen_dc, size, size)
        mask_bmp = gdi32.CreateBitmap(size, size, 1, 1, None)
        color_dc = gdi32.CreateCompatibleDC(screen_dc)
        mask_dc = gdi32.CreateCompatibleDC(screen_dc)
        old_color = gdi32.SelectObject(color_dc, color_bmp)
        old_mask = gdi32.SelectObject(mask_dc, mask_bmp)
        try:
            gdi32.PatBlt(color_dc, 0, 0, size, size, BLACKNESS)
            gdi32.PatBlt(mask_dc, 0, 0, size, size, BLACKNESS)
            paint(color_dc, mask_dc)
            info = ICONINFO(True, 0, 0, mask_bmp, color_bmp)
            return user32.CreateIconIndirect(ctypes.byref(info))
        finally:
            gdi32.SelectObject(color_dc, old_color)
            gdi32.SelectObject(mask_dc, old_mask)
    finally:
        if color_dc:
            gdi32.DeleteDC(color_dc)
        if mask_dc:
            gdi32.DeleteDC(mask_dc)
        if color_bmp:
            gdi32.DeleteObject(color_bmp)
        if mask_bmp:
            gdi32.DeleteObject(mask_bmp)
        user32.ReleaseDC(None, screen_dc)


def badge_icon(text, rgb, size=None, text_rgb=(255, 255, 255)):
    """纯数字徽标：圆角彩色底 + 白色文字，返回 HICON（用完需 DestroyIcon）。"""
    if size is None:
        size = tray_icon_size()
    size = int(size)
    if size <= 0:
        return None
    radius = max(3, int(round(size * 0.30)))

    def paint(cdc, mdc):
        _fill_round_rect(cdc, 0, 0, size, size, radius, rgb)
        _fill_round_rect(mdc, 0, 0, size, size, radius, WHITE)
        rect = wintypes.RECT(0, 0, size, size)
        _draw_text(cdc, text, text_rgb, rect, _text_size(size, len(text)))

    return _render_icon(size, paint)


def _paint_mouse_glyph(dc, rgb, size):
    """白色鼠标指针（光标箭头）—— 20px 下比鼠标剪影更容易辨认。

    返回图形底边 y，供数字定位。
    """
    gw = size * 0.50
    gh = size * 0.45
    x0 = (size - gw) / 2.0
    y0 = size * 0.02
    sx = gw / 10.0
    sy = gh / 12.0
    pts = [
        (int(round(x0 + x * sx)), int(round(y0 + y * sy)))
        for x, y in ((0, 0), (0, 11), (3, 8), (5, 12), (7, 11), (5, 7), (10, 7))
    ]
    arr = (wintypes.POINT * len(pts))(*[wintypes.POINT(x, y) for x, y in pts])
    brush = gdi32.CreateSolidBrush(WHITE)
    pen = gdi32.CreatePen(PS_SOLID, 0, WHITE)
    old_brush = gdi32.SelectObject(dc, brush)
    old_pen = gdi32.SelectObject(dc, pen)
    try:
        gdi32.Polygon(dc, arr, len(pts))
    finally:
        gdi32.SelectObject(dc, old_brush)
        gdi32.SelectObject(dc, old_pen)
        gdi32.DeleteObject(brush)
        gdi32.DeleteObject(pen)
    return int(round(y0 + gh))


def _paint_keyboard_glyph(dc, rgb, size):
    """白色键盘轮廓 + 两排按键 + 空格条，返回图形底边 y。"""
    gw = max(8, int(round(size * 0.88)))
    gh = max(6, int(round(size * 0.50)))
    x1 = (size - gw) // 2
    x2 = x1 + gw
    y1 = max(0, int(round(size * 0.05)))
    y2 = min(size - 1, y1 + gh)
    _fill_round_rect(dc, x1, y1, x2, y2, max(2, int(round(size * 0.10))), WHITE)
    step = max(2, int(round(size * 0.14)))
    x = x1 + step
    while x + 2 <= x2 - step:
        _fill_rect(dc, x, y1 + 2, x + 2, y1 + 3, rgb)
        x += step
    x = x1 + step + max(1, step // 2)
    while x + 2 <= x2 - step:
        _fill_rect(dc, x, y1 + 4, x + 2, y1 + 5, rgb)
        x += step
    _fill_rect(dc, x1 + step, y2 - 3, x2 - step, y2 - 2, rgb)
    return y2


def device_badge_icon(text, rgb, kind, size=None, text_rgb=(255, 255, 255)):
    """设备图形 + 电量数字：一眼看出是鼠标还是键盘，同时保留百分比。"""
    if size is None:
        size = tray_icon_size()
    size = int(size)
    if size <= 0:
        return None
    radius = max(3, int(round(size * 0.26)))

    def paint(cdc, mdc):
        _fill_round_rect(cdc, 0, 0, size, size, radius, rgb)
        _fill_round_rect(mdc, 0, 0, size, size, radius, WHITE)
        if kind == "mouse":
            bottom = _paint_mouse_glyph(cdc, rgb, size)
            font_px = size * 0.42
        else:
            bottom = _paint_keyboard_glyph(cdc, rgb, size)
            font_px = size * 0.46
        if len(text) >= 3:
            font_px *= 0.82
        rect = wintypes.RECT(0, max(0, bottom - 1), size, size)
        _draw_text(cdc, text, text_rgb, rect, font_px)

    return _render_icon(size, paint)


def battery_icon(percent, fresh=True, size=None, kind=None):
    """按电量生成图标；None/0 画灰色的 '?'。

    kind=None  → 纯数字徽标（电量优先）
    kind=mouse/keyboard → 设备图形 + 数字（身份优先）
    """
    if percent is None or int(percent) <= 0:
        text = "?"
        color = rgb_of(None)
    else:
        value = int(max(0, min(100, percent)))
        text = str(value)
        color = rgb_of(value)
        if not fresh:
            color = dim(color)
    if kind in ("mouse", "keyboard"):
        return device_badge_icon(text, color, kind, size)
    return badge_icon(text, color, size)


def destroy_icon(hicon):
    if hicon:
        user32.DestroyIcon(hicon)
