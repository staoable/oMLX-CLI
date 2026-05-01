"""时间/日期工具。

system_message 会在启动时注入一次"当前时间"，但长会话跨过 24:00 时该提示就过期了。
本 skill 让模型可在任意时刻通过 `date_now()` 重新拿到本机的当前日期与星期。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from _meta import skill


_ZH_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


@skill(
    desc="返回当前本机时间（含日期、星期、时区）。处理'今天/明天'等相对时间时先调用它。",
    examples=["date_now()"],
)
def date_now() -> dict[str, Any]:
    """返回 {date, time, datetime, weekday_zh, weekday_idx, timezone, iso, epoch}。"""
    now = datetime.now().astimezone()
    return {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday_zh": _ZH_WEEKDAYS[now.weekday()],
        "weekday_idx": now.weekday(),
        "timezone": now.tzname() or "",
        "utc_offset_minutes": int(now.utcoffset().total_seconds() // 60) if now.utcoffset() else 0,
        "iso": now.isoformat(timespec="seconds"),
        "epoch": int(now.timestamp()),
    }
