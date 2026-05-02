"""天气查询工具。

数据源策略：
  - 主：Open-Meteo 公共 API（无需 key）。先经 geocoding 把城市名转坐标，再取
    current/daily 预报；中文返回 weather_code 映射成中文天气描述。
  - 兜底：wttr.in（无需 key）。`weather_now` 在主源失败时用；`weather_forecast`
    在主源任一步失败（含 forecast 502 等）时用 j1 的 `weather` 多日块（通常约 3 天）。

设计取舍：
  - geocoding 对长查询（如「广州番禺」）可能命中失败。我们采用"原串 → 末尾分词"
    的退化策略，避免直接给模型一个 LookupError。
  - 网络异常或两源都失败时抛 RuntimeError，由调用方决定是否给用户报错。
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from _meta import skill


_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_WTTR_URL = "https://wttr.in/{q}?format=j1&lang=zh"

# WMO 天气代码 → 中文（参见 https://open-meteo.com/en/docs WMO Weather Code）
_WEATHER_CODE_ZH: dict[int, str] = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨（弱）",
    53: "毛毛雨",
    55: "毛毛雨（强）",
    56: "冻毛毛雨（弱）",
    57: "冻毛毛雨（强）",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨（弱）",
    67: "冻雨（强）",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "冰粒",
    80: "阵雨（弱）",
    81: "阵雨",
    82: "阵雨（强）",
    85: "阵雪（弱）",
    86: "阵雪（强）",
    95: "雷阵雨",
    96: "雷阵雨伴小冰雹",
    99: "雷阵雨伴大冰雹",
}


def _http_get_json(url: str, timeout: float = 8.0, retries: int = 2) -> dict[str, Any]:
    """GET JSON；对 502/503/504 做有限重试（Open-Meteo 偶发网关错误）。"""
    req = urllib.request.Request(url, headers={"User-Agent": "aicli-weather/1.0"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            if exc.code in (502, 503, 504) and attempt < retries:
                time.sleep(0.35 * (attempt + 1))
                continue
            raise
    assert False, "unreachable"  # pragma: no cover


def _weather_desc(code: Optional[int]) -> str:
    if code is None:
        return "未知"
    try:
        return _WEATHER_CODE_ZH.get(int(code), f"code={code}")
    except (TypeError, ValueError):
        return f"code={code}"


def _candidate_queries(query: str) -> list[str]:
    """生成 geocoding 退化候选：原串 → 拆掉前缀的子串 → 最后 2-4 个汉字。

    例：'广州番禺' → ['广州番禺', '番禺']
       '广东省广州市番禺区' → ['广东省广州市番禺区', '广州市番禺区', '番禺区', '番禺']
       'New York City' → ['New York City', 'York City', 'City']
    """
    raw = query.strip()
    if not raw:
        return []
    out: list[str] = [raw]

    # 英文：按空格切，从右向左拼接
    if " " in raw:
        parts = raw.split()
        for i in range(1, len(parts)):
            out.append(" ".join(parts[i:]))

    # 中文：按 省/市/区/县/镇/街道 关键字切
    cn_split = re.split(r"(?<=[省市区县镇州])", raw)
    cn_split = [s for s in cn_split if s]
    if len(cn_split) > 1:
        for i in range(1, len(cn_split)):
            out.append("".join(cn_split[i:]))

    # 中文：尾部 2-4 字
    cn_chars = re.findall(r"[\u4e00-\u9fff]+", raw)
    if cn_chars:
        tail = cn_chars[-1]
        for n in (4, 3, 2):
            if len(tail) >= n:
                out.append(tail[-n:])

    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        s = item.strip()
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _geocode(query: str, language: str = "zh") -> dict[str, Any]:
    last_err: Exception | None = None
    for cand in _candidate_queries(query):
        params = urllib.parse.urlencode(
            {"name": cand, "count": 1, "language": language, "format": "json"}
        )
        try:
            data = _http_get_json(f"{_GEOCODE_URL}?{params}")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
        results = data.get("results") or []
        if results:
            return results[0]
    if last_err:
        raise last_err
    raise LookupError(f"未找到城市: {query}")


def _open_meteo_forecast(lat: float, lon: float, days: int = 1) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "latitude": f"{lat}",
            "longitude": f"{lon}",
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,sunrise,sunset",
            "forecast_days": max(1, min(int(days), 7)),
            "timezone": "auto",
        }
    )
    return _http_get_json(f"{_FORECAST_URL}?{params}")


def _wttr_fallback(query: str) -> dict[str, Any]:
    """wttr.in 兜底；接受中文/拼音/英文城市名。"""
    return _http_get_json(_WTTR_URL.format(q=urllib.parse.quote(query)))


def _wttr_day_condition_zh(day: dict[str, Any]) -> str:
    """从 wttr.in j1 单日块取中文概况（取中间时刻 hourly）。"""
    hourly = day.get("hourly") or []
    if not hourly:
        return "未知"
    mid = hourly[len(hourly) // 2]
    lz = mid.get("lang_zh")
    if isinstance(lz, list) and lz and isinstance(lz[0], dict):
        v = lz[0].get("value")
        if v:
            return str(v).strip()
    wd = mid.get("weatherDesc")
    if isinstance(wd, list) and wd and isinstance(wd[0], dict):
        v = wd[0].get("value")
        if v:
            return str(v).strip()
    return "未知"


def _wttr_format_forecast(query: str, days: int) -> dict[str, Any]:
    """wttr.in 多日预报（j1 默认约 3 天）；与 open-meteo 返回字段尽量对齐。"""
    data = _wttr_fallback(query)
    nearest = (data.get("nearest_area") or [{}])[0]
    area = ((nearest.get("areaName") or [{}])[0] or {}).get("value") or query
    region = ((nearest.get("region") or [{}])[0] or {}).get("value") or ""
    country = ((nearest.get("country") or [{}])[0] or {}).get("value") or ""
    lat_s, lon_s = nearest.get("latitude"), nearest.get("longitude")
    lat: float | None = None
    lon: float | None = None
    try:
        if lat_s not in (None, ""):
            lat = float(lat_s)
        if lon_s not in (None, ""):
            lon = float(lon_s)
    except (TypeError, ValueError):
        lat = lon = None

    weather_days = data.get("weather") or []
    if not weather_days:
        raise RuntimeError("wttr.in 未返回 weather 预报块")

    n = max(1, min(int(days), len(weather_days), 7))
    daily: list[dict[str, Any]] = []
    for i in range(n):
        d = weather_days[i]
        hourly = d.get("hourly") or []
        code: int | None = None
        if hourly:
            mid = hourly[len(hourly) // 2]
            try:
                raw_c = mid.get("weatherCode")
                code = int(raw_c) if raw_c not in (None, "") else None
            except (TypeError, ValueError):
                code = None
        precip_sum = 0.0
        wind_max = 0.0
        for h in hourly:
            try:
                precip_sum += float(h.get("precipMM") or 0) or 0.0
            except (TypeError, ValueError):
                pass
            try:
                w = float(h.get("windspeedKmph") or 0) or 0.0
                wind_max = max(wind_max, w)
            except (TypeError, ValueError):
                pass
        astro = (d.get("astronomy") or [{}])[0] if d.get("astronomy") else {}
        daily.append(
            {
                "date": d.get("date"),
                "weather_code": code,
                "condition": _wttr_day_condition_zh(d),
                "temp_max_c": _to_float(d.get("maxtempC")),
                "temp_min_c": _to_float(d.get("mintempC")),
                "precipitation_mm": precip_sum or None,
                "wind_max_kmh": wind_max or None,
                "sunrise": astro.get("sunrise"),
                "sunset": astro.get("sunset"),
            }
        )

    return {
        "source": "wttr.in",
        "city": area,
        "admin": region,
        "country": country,
        "latitude": lat,
        "longitude": lon,
        "timezone": None,
        "daily": daily,
    }


def _wttr_format_now(query: str) -> dict[str, Any]:
    data = _wttr_fallback(query)
    cur_list = data.get("current_condition") or []
    cur = cur_list[0] if cur_list else {}
    nearest = (data.get("nearest_area") or [{}])[0]
    area = ((nearest.get("areaName") or [{}])[0] or {}).get("value") or query
    region = ((nearest.get("region") or [{}])[0] or {}).get("value") or ""
    country = ((nearest.get("country") or [{}])[0] or {}).get("value") or ""
    cond_zh = ""
    if cur.get("lang_zh"):
        cond_zh = (cur["lang_zh"][0] or {}).get("value") or ""
    if not cond_zh:
        cond_zh = (cur.get("weatherDesc") or [{}])[0].get("value", "") or "未知"
    return {
        "source": "wttr.in",
        "city": area,
        "admin": region,
        "country": country,
        "time": cur.get("localObsDateTime"),
        "temperature_c": _to_float(cur.get("temp_C")),
        "feels_like_c": _to_float(cur.get("FeelsLikeC")),
        "humidity": _to_int(cur.get("humidity")),
        "wind_kmh": _to_float(cur.get("windspeedKmph")),
        "precipitation_mm": _to_float(cur.get("precipMM")),
        "condition": cond_zh,
    }


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


@skill(
    desc="查询某城市的当前天气（温度/天气状况/湿度/风速）。中文/英文/拼音城市名都支持。",
    examples=[
        "weather_now('广州番禺')",
        "weather_now('Beijing')",
        "weather_now('Tokyo')",
    ],
)
def weather_now(city: str) -> dict[str, Any]:
    """返回结构化的当前天气字典；失败时抛 RuntimeError。"""
    if not city or not str(city).strip():
        raise ValueError("city 不能为空")

    primary_err: Exception | None = None
    try:
        loc = _geocode(city)
        lat = float(loc["latitude"])
        lon = float(loc["longitude"])
        forecast = _open_meteo_forecast(lat, lon, days=1)
        cur = forecast.get("current") or {}
        return {
            "source": "open-meteo",
            "city": loc.get("name") or city,
            "admin": loc.get("admin1") or loc.get("admin2") or "",
            "country": loc.get("country") or "",
            "latitude": lat,
            "longitude": lon,
            "timezone": forecast.get("timezone"),
            "time": cur.get("time"),
            "temperature_c": cur.get("temperature_2m"),
            "feels_like_c": cur.get("apparent_temperature"),
            "humidity": cur.get("relative_humidity_2m"),
            "wind_kmh": cur.get("wind_speed_10m"),
            "precipitation_mm": cur.get("precipitation"),
            "condition": _weather_desc(cur.get("weather_code")),
            "weather_code": cur.get("weather_code"),
        }
    except Exception as exc:  # noqa: BLE001
        primary_err = exc

    try:
        return _wttr_format_now(city)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"天气查询失败: open-meteo={primary_err}; wttr.in={exc}"
        ) from exc


@skill(
    desc="查询未来若干天天气预报（默认 3 天，最多 7 天）。",
    examples=[
        "weather_forecast('广州番禺', days=3)",
        "weather_forecast('Beijing', days=7)",
    ],
)
def weather_forecast(city: str, days: int = 3) -> dict[str, Any]:
    """返回 {city, daily: [{date, condition, temp_min_c, temp_max_c, ...}, ...]}"""
    if not city or not str(city).strip():
        raise ValueError("city 不能为空")
    days = max(1, min(int(days), 7))

    primary_err: Exception | None = None
    try:
        loc = _geocode(city)
        lat = float(loc["latitude"])
        lon = float(loc["longitude"])
        forecast = _open_meteo_forecast(lat, lon, days=days)
        daily = forecast.get("daily") or {}
        times = daily.get("time") or []
        codes = daily.get("weather_code") or []
        tmaxs = daily.get("temperature_2m_max") or []
        tmins = daily.get("temperature_2m_min") or []
        precs = daily.get("precipitation_sum") or []
        winds = daily.get("wind_speed_10m_max") or []
        sunrises = daily.get("sunrise") or []
        sunsets = daily.get("sunset") or []

        result: list[dict[str, Any]] = []
        for i, t in enumerate(times):
            code = codes[i] if i < len(codes) else None
            result.append(
                {
                    "date": t,
                    "weather_code": code,
                    "condition": _weather_desc(code),
                    "temp_max_c": tmaxs[i] if i < len(tmaxs) else None,
                    "temp_min_c": tmins[i] if i < len(tmins) else None,
                    "precipitation_mm": precs[i] if i < len(precs) else None,
                    "wind_max_kmh": winds[i] if i < len(winds) else None,
                    "sunrise": sunrises[i] if i < len(sunrises) else None,
                    "sunset": sunsets[i] if i < len(sunsets) else None,
                }
            )

        return {
            "source": "open-meteo",
            "city": loc.get("name") or city,
            "admin": loc.get("admin1") or loc.get("admin2") or "",
            "country": loc.get("country") or "",
            "latitude": lat,
            "longitude": lon,
            "timezone": forecast.get("timezone"),
            "daily": result,
        }
    except Exception as exc:  # noqa: BLE001
        primary_err = exc

    try:
        return _wttr_format_forecast(city, days)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"天气预报失败: open-meteo={primary_err}; wttr.in={exc}"
        ) from exc
