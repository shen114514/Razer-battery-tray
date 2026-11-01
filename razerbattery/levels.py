"""电量等级、配色与文案（面板与托盘图标共用同一套规则）。

等级划分：
    60-100  ok      绿
    30-59   mid     琥珀
    10-29   low     橙
    1-9     crit    红
    其它    unknown 灰（None / 0 / 非法值）

0% 在这里按「未知」处理：设备待机时可能返回 0，不能当成真实电量显示。
"""

# 状态色（RGB）。饱和度较高，保证在浅色/深色任务栏上都能看清。
COLOR_OK = (30, 158, 74)
COLOR_MID = (208, 139, 0)
COLOR_LOW = (224, 100, 30)
COLOR_CRIT = (210, 43, 43)
COLOR_UNKNOWN = (107, 114, 128)

LEVEL_TEXT = {
    "ok": "电量充足",
    "mid": "电量一般",
    "low": "电量偏低",
    "crit": "电量告急",
    "unknown": "未知",
}

_COLORS = {
    "ok": COLOR_OK,
    "mid": COLOR_MID,
    "low": COLOR_LOW,
    "crit": COLOR_CRIT,
    "unknown": COLOR_UNKNOWN,
}


def level_of(percent):
    """百分比 → 等级名；None / 0 / 负数均视为 unknown。"""
    if percent is None:
        return "unknown"
    try:
        p = int(percent)
    except (TypeError, ValueError):
        return "unknown"
    if p <= 0:
        return "unknown"
    if p >= 60:
        return "ok"
    if p >= 30:
        return "mid"
    if p >= 10:
        return "low"
    return "crit"


def rgb_of(percent):
    return _COLORS[level_of(percent)]


def hex_of(percent):
    r, g, b = rgb_of(percent)
    return "#%02x%02x%02x" % (r, g, b)


def status_text(percent):
    return LEVEL_TEXT[level_of(percent)]


def dim(rgb, factor=0.55):
    """把颜色压暗，用于「数据已过期」的托盘图标。"""
    return tuple(max(0, min(255, int(c * factor))) for c in rgb)
