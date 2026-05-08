"""A 股市场信息查询技能（MVP）。

当前实现：
  - stock_quote: 多股票实时行情（东方财富）
  - stock_hot_list: 热股榜/飙升榜（东方财富）
  - stock_unusual: 盘口异动
  - stock_search: 代码/名称检索
  - stock_brief: 单票聚合视图（行情+热榜+异动）
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import time
from datetime import datetime
import urllib.parse
import urllib.request
from typing import Any

from _meta import skill

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_UNUSUAL_ENUM = {
    402: "火箭发射",
    403: "快速反弹",
    2: "大笔买入",
    201: "封涨停板",
    302: "打开跌停板",
    1: "有大买盘",
    404: "竞价上涨",
    203: "高开5日线",
    401: "向上缺口",
    204: "60日新高",
    405: "60日大幅上涨",
    503: "加速下跌",
    502: "高台跳水",
    102: "大笔卖出",
    301: "封跌停板",
    202: "打开涨停板",
    101: "有大卖盘",
    504: "竞价下跌",
    303: "低开5日线",
    501: "向下缺口",
    304: "60日新低",
    505: "60日大幅下跌",
}

_EXCHANGE_NAME = {
    0: "深交所",
    1: "上交所",
    2: "北交所",
    105: "美股",
    116: "港股",
}

_UNBLOCK_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "_eastmoney_unblock",
    "pass.js",
)
_UNBLOCK_LOCK = threading.Lock()
_UNBLOCK_RUNNING = False
_UNBLOCK_COND = threading.Condition(_UNBLOCK_LOCK)
_UNBLOCK_STATS = {
    "triggered": 0,
    "waited": 0,
    "success": 0,
    "failed": 0,
    "timeout": 0,
}
_UNBLOCK_LAST: dict[str, Any] = {
    "status": "idle",
    "message": "",
    "returncode": None,
    "ts": None,
}
_UNBLOCK_PROCESS_MIN_TIMEOUT_SEC = 90.0


def _unblock_debug_enabled() -> bool:
    raw = (os.getenv("OMLXCLI_STOCK_UNBLOCK_DEBUG") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    # 默认开启，可通过 OMLXCLI_STOCK_UNBLOCK_DEBUG=0 显式关闭。
    return True


def _unblock_log(msg: str) -> None:
    if not _unblock_debug_enabled():
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[stock_unblock] {now} {msg}", file=sys.stderr, flush=True)


def _set_unblock_last(status: str, message: str, returncode: int | None = None) -> None:
    _UNBLOCK_LAST["status"] = status
    _UNBLOCK_LAST["message"] = message
    _UNBLOCK_LAST["returncode"] = returncode
    _UNBLOCK_LAST["ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _classify_unblock_failure(returncode: int | None, stdout_text: str, stderr_text: str) -> tuple[str, str]:
    s = f"{stdout_text}\n{stderr_text}".lower()
    if "browser_fallback_locked_by_other_process" in s:
        return "running", "browser_fallback_in_progress_elsewhere"
    if "playwright_unavailable" in s or "no module named 'playwright'" in s:
        return "failed", "playwright_missing: pip install playwright && python -m playwright install chromium"
    if "preflight_failed" in s and "python3_unavailable" in s:
        return "failed", "python3_unavailable"
    if "preflight_failed" in s and "missing_gen_track" in s:
        return "failed", "gen_track_missing"
    if "preflight_failed" in s and "missing_browser_fallback" in s:
        return "failed", "browser_fallback_missing"
    if "still_blocked_after_browser_fallback" in s:
        return "failed", "still_blocked_after_browser_fallback"
    if "still_blocked_after_unblock_attempts" in s:
        return "failed", "still_blocked_after_auto_attempts"
    if returncode not in (None, 0):
        return "failed", f"pass_js_returncode={returncode}"
    return "failed", "unblock_not_effective"


def _unblock_state_snapshot(timeout: float = 3.0) -> dict[str, Any]:
    blocked, check_err = _eastmoney_check_block(timeout=timeout)
    with _UNBLOCK_LOCK:
        stats = dict(_UNBLOCK_STATS)
        last = dict(_UNBLOCK_LAST)
        running = bool(_UNBLOCK_RUNNING)
    return {
        "enabled": True,
        "running": running,
        "check_blocked": blocked,
        "check_error": check_err,
        "stats": stats,
        "last": last,
    }


def _http_get_json(url: str, timeout: float = 8.0, retries: int = 1) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "application/json,text/plain,*/*",
        },
    )
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(0.3 * (attempt + 1))
                continue
    raise RuntimeError(f"请求失败: {type(last_err).__name__}: {last_err}") from last_err


def _eastmoney_get_json(url: str, timeout: float = 8.0, retries: int = 3) -> dict[str, Any]:
    """东财专用 GET：浏览器头 + 退避重试 + 可选代理。

    可选环境变量：
      - OMLXCLI_STOCK_EASTMONEY_PROXY=http://host:port
      - OMLXCLI_STOCK_PROXY=http://host:port
    """
    proxy = (
        os.getenv("OMLXCLI_STOCK_EASTMONEY_PROXY", "").strip()
        or os.getenv("OMLXCLI_STOCK_PROXY", "").strip()
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else urllib.request.ProxyHandler({})
    )
    headers = {
        "User-Agent": _UA,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity",
        "Referer": "https://quote.eastmoney.com/",
        "Origin": "https://quote.eastmoney.com",
    }
    last_err: Exception | None = None
    unblock_attempted = False
    for i in range(retries + 1):
        if i == 0 and (not unblock_attempted) and _eastmoney_is_blocked(timeout=timeout):
            _eastmoney_try_unblock(timeout=timeout)
            unblock_attempted = True
        req = urllib.request.Request(url, headers=headers)
        try:
            with opener.open(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if (not unblock_attempted) and _eastmoney_is_blocked(timeout=timeout):
                _eastmoney_try_unblock(timeout=timeout)
                unblock_attempted = True
            # RemoteDisconnected/502/503 等风控或网关波动场景，做退避重试
            if i < retries:
                time.sleep(0.4 * (i + 1))
                continue
    raise RuntimeError(
        "eastmoney request failed (possible WAF/rate-limit/block): "
        f"{type(last_err).__name__}: {last_err}"
    ) from last_err


def _eastmoney_check_block(timeout: float = 6.0) -> tuple[bool | None, str | None]:
    """通过 checkuser 接口判断封控状态，返回 (blocked, error)。"""
    url = "https://i.eastmoney.com/websitecaptcha/api/checkuser?callback=wsc_checkuser"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        m = re.search(r"wsc_checkuser\((.*)\)", text)
        if not m:
            return None, "checkuser_parse_failed"
        data = json.loads(m.group(1))
        return bool(data.get("block")), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def _eastmoney_is_blocked(timeout: float = 6.0) -> bool:
    """兼容旧调用：异常/未知按未封控处理。"""
    blocked, _ = _eastmoney_check_block(timeout=timeout)
    return bool(blocked)


def _eastmoney_try_unblock(timeout: float = 20.0) -> None:
    """执行内置解封脚本（node pass.js），失败不抛出。"""
    global _UNBLOCK_RUNNING
    if not os.path.isfile(_UNBLOCK_SCRIPT):
        _set_unblock_last("skipped", "pass.js not found")
        _unblock_log("skip: pass.js not found")
        return
    blocked_before, before_err = _eastmoney_check_block(timeout=min(float(timeout), 8.0))
    if blocked_before is False:
        _set_unblock_last("skipped", "checkuser says not blocked")
        _unblock_log("skip: checkuser says not blocked")
        return
    if blocked_before is None:
        _set_unblock_last("unknown", f"checkuser unknown before unblock ({before_err})")
        _unblock_log(f"warn: checkuser unknown before unblock ({before_err})")
    wait_timeout = max(1.0, min(float(timeout), 30.0))
    with _UNBLOCK_LOCK:
        if _UNBLOCK_RUNNING:
            # 并发单飞：已有解封流程在跑，等待其完成后直接返回，避免重复触发。
            _UNBLOCK_STATS["waited"] += 1
            _unblock_log(f"wait: another unblock is running, wait_timeout={wait_timeout:.1f}s")
            _UNBLOCK_COND.wait(timeout=wait_timeout)
            return
        _UNBLOCK_RUNNING = True
        _UNBLOCK_STATS["triggered"] += 1
        _set_unblock_last("running", f"start pass.js timeout={timeout}s")
        _unblock_log(f"trigger: start pass.js, timeout={timeout}s")
    try:
        unblock_timeout = max(float(timeout), _UNBLOCK_PROCESS_MIN_TIMEOUT_SEC)
        proc = subprocess.run(
            ["node", _UNBLOCK_SCRIPT],
            shell=False,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=unblock_timeout,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if int(proc.returncode or 0) == 0:
            blocked_after, after_err = _eastmoney_check_block(timeout=min(float(timeout), 8.0))
            if blocked_after is False:
                _UNBLOCK_STATS["success"] += 1
                _set_unblock_last("success", "unblocked=true", 0)
                _unblock_log(f"done: returncode=0 unblocked=true stats={_UNBLOCK_STATS}")
            else:
                _UNBLOCK_STATS["failed"] += 1
                detail = after_err or "still_blocked"
                _set_unblock_last("failed", f"unblock_not_effective detail={detail}", 0)
                _unblock_log(
                    "done: returncode=0 but unblock_not_effective "
                    f"detail={detail} stdout={out[:180]} stderr={err[:180]} stats={_UNBLOCK_STATS}"
                )
        else:
            _UNBLOCK_STATS["failed"] += 1
            st, msg = _classify_unblock_failure(int(proc.returncode or 0), out, err)
            _set_unblock_last(st, msg, int(proc.returncode or 0))
            _unblock_log(
                f"done: returncode={proc.returncode} stdout={out[:180]} stderr={err[:180]} stats={_UNBLOCK_STATS}"
            )
    except subprocess.TimeoutExpired:
        _UNBLOCK_STATS["timeout"] += 1
        _set_unblock_last("timeout", "pass.js timeout", None)
        _unblock_log(f"error: timeout stats={_UNBLOCK_STATS}")
    except Exception:  # noqa: BLE001
        _UNBLOCK_STATS["failed"] += 1
        _set_unblock_last("failed", "exception during unblock")
        _unblock_log(f"error: exception stats={_UNBLOCK_STATS}")
    finally:
        with _UNBLOCK_LOCK:
            _UNBLOCK_RUNNING = False
            _UNBLOCK_COND.notify_all()


def _http_post_json(
    url: str,
    payload: dict[str, Any],
    timeout: float = 8.0,
    retries: int = 1,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "User-Agent": _UA,
            "Accept": "application/json,text/plain,*/*",
            "Content-Type": "application/json",
        },
    )
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(0.3 * (attempt + 1))
                continue
    raise RuntimeError(f"请求失败: {type(last_err).__name__}: {last_err}") from last_err


def _eastmoney_post_json(
    url: str,
    payload: dict[str, Any],
    timeout: float = 8.0,
    retries: int = 3,
) -> dict[str, Any]:
    """东财专用 POST：带风控检测与自动解封逻辑。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "User-Agent": _UA,
        "Accept": "application/json,text/plain,*/*",
        "Content-Type": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity",
        "Referer": "https://quote.eastmoney.com/",
        "Origin": "https://quote.eastmoney.com",
    }
    unblock_attempted = False
    last_err: Exception | None = None
    for i in range(retries + 1):
        if i == 0 and (not unblock_attempted) and _eastmoney_is_blocked(timeout=timeout):
            _eastmoney_try_unblock(timeout=timeout)
            unblock_attempted = True
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if (not unblock_attempted) and _eastmoney_is_blocked(timeout=timeout):
                _eastmoney_try_unblock(timeout=timeout)
                unblock_attempted = True
            if i < retries:
                time.sleep(0.4 * (i + 1))
                continue
    raise RuntimeError(
        "eastmoney post failed (possible WAF/rate-limit/block): "
        f"{type(last_err).__name__}: {last_err}"
    ) from last_err


def _norm_codes(codes: Any) -> list[str]:
    if isinstance(codes, str):
        raw = [x.strip() for x in codes.replace("，", ",").split(",")]
    elif isinstance(codes, list):
        raw = [str(x).strip() for x in codes]
    else:
        raise ValueError("codes 必须是逗号分隔字符串或字符串数组")
    out: list[str] = []
    for item in raw:
        if not item:
            continue
        if not item.isdigit():
            raise ValueError(f"非法股票代码: {item}")
        out.append(item)
    if not out:
        raise ValueError("codes 不能为空")
    return out


def _norm_identifiers(codes_or_names: Any) -> list[str]:
    if isinstance(codes_or_names, str):
        raw = [x.strip() for x in codes_or_names.replace("，", ",").split(",")]
    elif isinstance(codes_or_names, list):
        raw = [str(x).strip() for x in codes_or_names]
    else:
        raise ValueError("codes 必须是逗号分隔字符串或字符串数组")
    out = [x for x in raw if x]
    if not out:
        raise ValueError("codes 不能为空")
    return out


def _resolve_identifier(identifier: str, timeout_sec: float = 8.0) -> dict[str, Any]:
    s = str(identifier or "").strip()
    if not s:
        raise ValueError("标的不能为空")
    if s.isdigit():
        return {"input": s, "code": s, "market": None, "security_type": None, "name": None}
    search_res = stock_search(s, limit=5, timeout_sec=timeout_sec)
    items = search_res.get("items") or []
    if not items:
        raise ValueError(f"未找到标的: {s}")
    x = items[0]
    return {
        "input": s,
        "code": str(x.get("code") or ""),
        "market": x.get("market"),
        "security_type": x.get("security_type"),
        "name": x.get("name"),
    }


def _to_secid(code: str) -> str:
    # 东方财富 secid: 1=沪市, 0=深市(含北交所常见代码兜底)
    if code.startswith(("5", "6", "9")):
        return f"1.{code}"
    return f"0.{code}"


def _to_float(v: Any) -> float | None:
    try:
        if v in (None, ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int | None:
    try:
        if v in (None, ""):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _exchange_name(exchange_id: Any) -> str | None:
    eid = _to_int(exchange_id)
    if eid is None:
        return None
    return _EXCHANGE_NAME.get(eid, f"id={eid}")


def _guess_secid_candidates(code: str, market_hint: Any = None) -> list[str]:
    hint = str(market_hint or "").strip()
    out: list[str] = []
    if hint in ("0", "1"):
        out.append(f"{hint}.{code}")
    # 兜底：同时尝试深/沪
    for x in (f"0.{code}", f"1.{code}"):
        if x not in out:
            out.append(x)
    return out


def _instrument_match(security_type: str, instrument: str) -> bool:
    t = (security_type or "").lower()
    if instrument == "auto":
        return True
    if instrument == "stock":
        return any(k in t for k in ("a股", "股票", "stock"))
    if instrument == "index":
        return any(k in t for k in ("指数", "index"))
    if instrument == "fund":
        return any(k in t for k in ("基金", "etf", "lof", "fund"))
    return True


def _fetch_quote_by_secid(secid: str, timeout_sec: float = 8.0) -> dict[str, Any] | None:
    params = urllib.parse.urlencode(
        {
            "fltt": 2,
            "invt": 2,
            "fields": "f57,f58,f43,f170,f60,f169,f13,f6,f47,f48",
            "secid": secid,
        }
    )
    url = f"https://push2.eastmoney.com/api/qt/stock/get?{params}"
    data = _eastmoney_get_json(url, timeout=float(timeout_sec), retries=3)
    d = data.get("data") or {}
    if not d or not d.get("f57"):
        return None
    return {
        "code": str(d.get("f57") or ""),
        "name": str(d.get("f58") or ""),
        "exchange_id": d.get("f13"),
        "exchange": _exchange_name(d.get("f13")),
        "secid": secid,
        "new_price": _to_float(d.get("f43")),
        "change_percent": _to_float(d.get("f170")),
        "opening_price": _to_float(d.get("f60")),
        "change_amount": _to_float(d.get("f169")),
        "volume": _to_float(d.get("f47")),
        "turnover": _to_float(d.get("f48")),
        "amount": _to_float(d.get("f6")),
    }


def _sina_symbol_candidates(code: str, instrument: str = "auto") -> list[str]:
    cands: list[str] = []
    if instrument in ("auto", "stock", "fund"):
        cands.extend([f"sh{code}", f"sz{code}"])
    if instrument in ("auto", "index"):
        cands.extend([f"s_sh{code}", f"s_sz{code}"])
    # 去重保持顺序
    out: list[str] = []
    seen: set[str] = set()
    for x in cands:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _fetch_quote_via_sina(code: str, instrument: str = "auto", timeout_sec: float = 8.0) -> dict[str, Any] | None:
    symbols = _sina_symbol_candidates(code, instrument=instrument)
    if not symbols:
        return None
    url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Referer": "https://finance.sina.com.cn/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        body = resp.read().decode("gbk", errors="replace")
    lines = [x for x in body.splitlines() if "var hq_str_" in x]
    for line in lines:
        m = re.search(r'var hq_str_([a-zA-Z0-9_]+)="(.*)";', line)
        if not m:
            continue
        symbol, payload = m.group(1), m.group(2)
        parts = payload.split(",")
        if not parts or not parts[0]:
            continue
        # 指数简版: s_sh000001="上证指数,3346.35,6.37,0.19,2660827,33278895"
        if symbol.startswith("s_sh") or symbol.startswith("s_sz"):
            name = parts[0] if len(parts) > 0 else ""
            new_price = _to_float(parts[1] if len(parts) > 1 else None)
            change_amount = _to_float(parts[2] if len(parts) > 2 else None)
            change_percent = _to_float(parts[3] if len(parts) > 3 else None)
            return {
                "code": code,
                "name": name,
                "exchange_id": None,
                "exchange": "上交所" if symbol.startswith("s_sh") else "深交所",
                "secid": None,
                "new_price": new_price,
                "change_percent": change_percent,
                "opening_price": None,
                "change_amount": change_amount,
                "volume": _to_float(parts[4] if len(parts) > 4 else None),
                "turnover": _to_float(parts[5] if len(parts) > 5 else None),
                "amount": None,
                "fallback_source": "sina",
            }
        # 股票/基金标准版
        # sh600519="贵州茅台,1410.000,1377.560,1377.580,..."
        name = parts[0] if len(parts) > 0 else ""
        opening_price = _to_float(parts[1] if len(parts) > 1 else None)
        prev_close = _to_float(parts[2] if len(parts) > 2 else None)
        new_price = _to_float(parts[3] if len(parts) > 3 else None)
        change_amount = None
        change_percent = None
        if new_price is not None and prev_close not in (None, 0):
            change_amount = round(new_price - prev_close, 6)
            change_percent = round((change_amount / prev_close) * 100, 4)
        return {
            "code": code,
            "name": name,
            "exchange_id": None,
            "exchange": "上交所" if symbol.startswith("sh") else "深交所",
            "secid": None,
            "new_price": new_price,
            "change_percent": change_percent,
            "opening_price": opening_price,
            "change_amount": change_amount,
            "volume": _to_float(parts[8] if len(parts) > 8 else None),
            "turnover": _to_float(parts[9] if len(parts) > 9 else None),
            "amount": None,
            "fallback_source": "sina",
        }
    return None


@skill(
    desc="查询 A 股多只股票实时行情（支持代码或中文名称，返回最新价、涨跌幅、开盘价）。",
    examples=[
        "stock_quote('600519,000001')",
        "stock_quote(['600519', '000001'])",
        "stock_quote('红利100,贵州茅台')",
        "stock_quote('红利100', instrument='index')",
        "stock_quote('红利100', instrument='auto')  # 返回 ambiguities 候选",
    ],
)
def stock_quote(
    codes: Any,
    source: str = "eastmoney",
    instrument: str = "auto",
    timeout_sec: float = 8.0,
) -> dict[str, Any]:
    """返回 {source, instrument, count, quotes:[...], unresolved:[...], ambiguities:[...]}。"""
    src = (source or "").strip().lower()
    if src != "eastmoney":
        raise ValueError("当前仅支持 source='eastmoney'")
    inst = (instrument or "auto").strip().lower()
    if inst not in ("auto", "stock", "index", "fund"):
        raise ValueError("instrument 必须是 auto/stock/index/fund")
    identifiers = _norm_identifiers(codes)
    plans: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    ambiguities: list[dict[str, Any]] = []
    for item in identifiers:
        if item.isdigit():
            plans.append({"input": item, "code": item, "market_hint": None})
            continue
        search_res = stock_search(item, limit=5, timeout_sec=timeout_sec)
        found = search_res.get("items") or []
        if len(found) > 1:
            ambiguities.append(
                {
                    "input": item,
                    "candidates": [
                        {
                            "code": str(x.get("code") or ""),
                            "name": str(x.get("name") or ""),
                            "security_type": x.get("security_type"),
                            "market": x.get("market"),
                            "score": x.get("score"),
                        }
                        for x in found[:5]
                    ],
                }
            )
        filtered = [x for x in found if _instrument_match(str(x.get("security_type") or ""), inst)]
        pick = (filtered or found)[:1]
        if pick:
            plans.append(
                {
                    "input": item,
                    "code": str(pick[0].get("code") or ""),
                    "market_hint": pick[0].get("market"),
                    "security_type": pick[0].get("security_type"),
                }
            )
        else:
            unresolved.append({"input": item, "reason": "not_found"})

    quotes: list[dict[str, Any]] = []
    for p in plans:
        code = str(p.get("code") or "")
        if not code:
            continue
        quote = None
        last_error = ""
        for secid in _guess_secid_candidates(code, p.get("market_hint")):
            try:
                quote = _fetch_quote_by_secid(secid, timeout_sec=timeout_sec)
                if quote:
                    break
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                continue
        if quote:
            quote["input"] = p.get("input")
            quote["security_type"] = p.get("security_type")
            quotes.append(quote)
        else:
            try:
                fb = _fetch_quote_via_sina(code, instrument=inst, timeout_sec=timeout_sec)
            except Exception as exc:  # noqa: BLE001
                fb = None
                if not last_error:
                    last_error = f"{type(exc).__name__}: {exc}"
            if fb:
                fb["input"] = p.get("input")
                fb["security_type"] = p.get("security_type")
                quotes.append(fb)
            else:
                unresolved.append(
                    {
                        "input": p.get("input"),
                        "code": code,
                        "reason": "quote_unavailable",
                        "detail": last_error or None,
                    }
                )

    return {
        "source": "eastmoney",
        "instrument": inst,
        "count": len(quotes),
        "quotes": quotes,
        "unresolved": unresolved,
        "ambiguities": ambiguities,
        "unblock": _unblock_state_snapshot(timeout=min(float(timeout_sec), 3.0)),
    }


@skill(
    desc="查询 A 股热股榜/飙升榜（默认东方财富热榜前 10）。",
    examples=[
        "stock_hot_list()",
        "stock_hot_list(kind='skyrocket', limit=15)",
    ],
)
def stock_hot_list(
    source: str = "eastmoney",
    kind: str = "hot",
    limit: int = 10,
    timeout_sec: float = 8.0,
) -> dict[str, Any]:
    """返回 {source, kind, count, items:[...]}。"""
    src = (source or "").strip().lower()
    if src != "eastmoney":
        raise ValueError("当前仅支持 source='eastmoney'")
    k = (kind or "hot").strip().lower()
    if k not in ("hot", "skyrocket"):
        raise ValueError("kind 必须是 'hot' 或 'skyrocket'")
    size = max(1, min(int(limit), 50))
    service = "getAllCurrentList" if k == "hot" else "getAllHisRcList"

    rank_data = _eastmoney_post_json(
        f"https://emappdata.eastmoney.com/stockrank/{service}",
        payload={
            "appId": "appId01",
            "globalId": "786e4c21-70dc-435a-93bb-39",
            "marketType": "",
            "pageNo": 1,
            "pageSize": size,
        },
        timeout=float(timeout_sec),
        retries=1,
    )
    sc_list = rank_data.get("data") or []
    secids: list[str] = []
    for item in sc_list:
        sc = str(item.get("sc") or "")
        if len(sc) < 3:
            continue
        prefix = sc[:2].upper()
        code = sc[2:]
        if prefix == "SH":
            secids.append(f"1.{code}")
        elif prefix == "SZ":
            secids.append(f"0.{code}")
    if not secids:
        return {"source": "eastmoney", "kind": k, "count": 0, "items": []}

    params = urllib.parse.urlencode(
        {
            "ut": "f057cbcbce2a86e2866ab8877db1d059",
            "fltt": 2,
            "invt": 2,
            "fields": "f14,f148,f3,f12,f2,f13,f29",
            "secids": ",".join(secids),
        }
    )
    detail_url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?{params}"
    detail_data = _eastmoney_get_json(detail_url, timeout=float(timeout_sec), retries=3)
    diff = (detail_data.get("data") or {}).get("diff") or []
    items: list[dict[str, Any]] = []
    for row in diff[:size]:
        items.append(
            {
                "code": str(row.get("f12") or ""),
                "name": str(row.get("f14") or ""),
                "new_price": _to_float(row.get("f2")),
                "change_percent": _to_float(row.get("f3")),
                "rank_value": _to_float(row.get("f148")),
            }
        )
    return {
        "source": "eastmoney",
        "kind": k,
        "count": len(items),
        "items": items,
    }


@skill(
    desc="查询 A 股盘口异动（东方财富）。",
    examples=[
        "stock_unusual()",
        "stock_unusual(limit=20)",
    ],
)
def stock_unusual(limit: int = 50, timeout_sec: float = 8.0) -> dict[str, Any]:
    """返回 {source, count, items:[...]}。"""
    lmt = max(1, min(int(limit), 100))
    params = urllib.parse.urlencode(
        {
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fields": "f1,f2,f3,f4,f5,f6,f7",
            "lmt": lmt,
            "_": int(time.time() * 1000),
        }
    )
    url = f"https://push2.eastmoney.com/api/qt/pkyd/get?{params}"
    data = _http_get_json(url, timeout=float(timeout_sec), retries=1)
    rows = (data.get("data") or {}).get("pkyd") or []
    exchange_enum = ["深证", "上证"]
    direction_enum = {1: "涨", 2: "跌"}
    items: list[dict[str, Any]] = []
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 7:
            continue
        time_s, code, exch, name, unusual_type, desc, direction = parts[:7]
        exch_i = _to_int(exch)
        dir_i = _to_int(direction)
        type_i = _to_int(unusual_type)
        items.append(
            {
                "time": time_s,
                "code": code,
                "name": name,
                "exchange": exchange_enum[exch_i] if exch_i in (0, 1) else None,
                "unusual_type": _UNUSUAL_ENUM.get(type_i, str(unusual_type)),
                "desc": desc,
                "direction": direction_enum.get(dir_i),
            }
        )
    return {"source": "eastmoney", "count": len(items), "items": items}


@skill(
    desc="按股票代码或名称搜索 A 股列表（东方财富）。",
    examples=[
        "stock_search('平安银行')",
        "stock_search('600519', limit=5)",
    ],
)
def stock_search(keyword: str, limit: int = 20, timeout_sec: float = 8.0) -> dict[str, Any]:
    """返回 {source, keyword, count, items:[...]}。"""
    q = (keyword or "").strip()
    if not q:
        raise ValueError("keyword 不能为空")
    size = max(1, min(int(limit), 100))
    url = f"https://searchapi.eastmoney.com/api/suggest/get?input={urllib.parse.quote(q)}&type=14&token=D43BF722C8E33BDC906FB84D85E326E8&count={size}"
    data = _http_get_json(url, timeout=float(timeout_sec), retries=1)
    rows = (data.get("QuotationCodeTable") or {}).get("Data") or []

    def _search_score(code: str, name: str) -> int:
        code_l = code.lower()
        name_l = name.lower()
        q_l = q.lower()
        if code_l == q_l:
            return 100
        if name_l == q_l:
            return 95
        if code_l.startswith(q_l):
            return 90
        if name_l.startswith(q_l):
            return 85
        if q_l in code_l:
            return 70
        if q_l in name_l:
            return 60
        return 10

    items: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("Code") or "")
        name = str(row.get("Name") or "")
        sec = str(row.get("SecurityTypeName") or "")
        market = str(row.get("MktNum") or "")
        if not code:
            continue
        items.append(
            {
                "code": code,
                "name": name,
                "security_type": sec,
                "market": market,
                "score": _search_score(code, name),
            }
        )
    items.sort(key=lambda x: (int(x.get("score") or 0), x.get("code") == q), reverse=True)
    items = items[:size]
    return {
        "source": "eastmoney",
        "keyword": q,
        "count": len(items),
        "items": items,
    }


@skill(
    desc="查询单只股票聚合信息（实时行情 + 所在热榜位置 + 最近异动）。",
    examples=[
        "stock_brief('600519')",
        "stock_brief('000001', hot_limit=30, unusual_limit=80)",
        "stock_brief('600519', include_unusual_items=True)",
    ],
)
def stock_brief(
    code: str,
    hot_limit: int = 50,
    unusual_limit: int = 100,
    include_hot_items: bool = False,
    include_unusual_items: bool = False,
    timeout_sec: float = 8.0,
) -> dict[str, Any]:
    """返回 {quote, hot_rank, unusual:[...]}。"""
    c = str(code or "").strip()
    if not c or not c.isdigit():
        raise ValueError("code 必须是纯数字股票代码")

    quote_data = stock_quote(c, timeout_sec=timeout_sec)
    quote = quote_data.get("quotes", [])
    one_quote = quote[0] if quote else None

    hot_data = stock_hot_list(limit=hot_limit, timeout_sec=timeout_sec)
    hot_items = hot_data.get("items", [])
    hot_rank: dict[str, Any] | None = None
    for idx, item in enumerate(hot_items, start=1):
        if str(item.get("code") or "") == c:
            hot_rank = {"rank": idx, "kind": "hot", "in_list": True}
            break
    if hot_rank is None:
        sky_data = stock_hot_list(kind="skyrocket", limit=hot_limit, timeout_sec=timeout_sec)
        sky_items = sky_data.get("items", [])
        for idx, item in enumerate(sky_items, start=1):
            if str(item.get("code") or "") == c:
                hot_rank = {"rank": idx, "kind": "skyrocket", "in_list": True}
                break
    if hot_rank is None:
        hot_rank = {"in_list": False}

    unusual_data = stock_unusual(limit=unusual_limit, timeout_sec=timeout_sec)
    unusual_items = unusual_data.get("items", [])
    matched_unusual = [x for x in unusual_items if str(x.get("code") or "") == c][:10]

    result = {
        "source": "eastmoney",
        "code": c,
        "quote": one_quote,
        "hot_rank": hot_rank,
        "unusual_count": len(matched_unusual),
    }
    if include_hot_items:
        result["hot_items"] = hot_items
    if include_unusual_items:
        result["unusual"] = matched_unusual
    return result


@skill(
    desc="查询股票/指数/基金历史 K 线（支持中文名称）。",
    examples=[
        "stock_kline('600519', period='day', count=120, adjust='qfq')",
        "stock_kline('红利100', period='day', count=60, adjust='none')",
    ],
)
def stock_kline(
    symbol: str,
    period: str = "day",
    count: int = 120,
    adjust: str = "qfq",
    timeout_sec: float = 8.0,
) -> dict[str, Any]:
    """返回 {symbol, code, period, adjust, klines:[...]}。"""
    p = (period or "day").strip().lower()
    period_map = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "60m": "60",
        "day": "101",
        "week": "102",
        "month": "103",
    }
    if p not in period_map:
        raise ValueError("period 必须是 1m/5m/15m/30m/60m/day/week/month")
    a = (adjust or "qfq").strip().lower()
    adjust_map = {"none": "0", "qfq": "1", "hfq": "2"}
    if a not in adjust_map:
        raise ValueError("adjust 必须是 none/qfq/hfq")
    lmt = max(1, min(int(count), 1000))

    target = _resolve_identifier(symbol, timeout_sec=timeout_sec)
    code = target["code"]
    secids = _guess_secid_candidates(code, target.get("market"))

    last_error = ""
    data_obj: dict[str, Any] | None = None
    used_secid = None
    for secid in secids:
        end_date = datetime.now().strftime("%Y%m%d")
        params = urllib.parse.urlencode(
            {
                "secid": secid,
                "klt": period_map[p],
                "fqt": adjust_map[a],
                "lmt": lmt,
                "end": end_date,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            }
        )
        url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?{params}"
        try:
            payload = _eastmoney_get_json(url, timeout=float(timeout_sec), retries=3)
            data_obj = payload.get("data") or {}
            if data_obj and data_obj.get("klines"):
                used_secid = secid
                break
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            continue
    if not data_obj or not data_obj.get("klines"):
        raise RuntimeError(f"K线获取失败: {symbol} ({code}) {last_error}")

    klines: list[dict[str, Any]] = []
    for line in data_obj.get("klines") or []:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        klines.append(
            {
                "time": parts[0],
                "open": _to_float(parts[1]),
                "close": _to_float(parts[2]),
                "high": _to_float(parts[3]),
                "low": _to_float(parts[4]),
                "volume": _to_float(parts[5]),
                "turnover": _to_float(parts[6]) if len(parts) > 6 else None,
                "amplitude": _to_float(parts[7]) if len(parts) > 7 else None,
                "change_percent": _to_float(parts[8]) if len(parts) > 8 else None,
                "change_amount": _to_float(parts[9]) if len(parts) > 9 else None,
                "turnover_rate": _to_float(parts[10]) if len(parts) > 10 else None,
            }
        )
    return {
        "source": "eastmoney",
        "symbol": symbol,
        "code": code,
        "name": data_obj.get("name") or target.get("name"),
        "period": p,
        "adjust": a,
        "secid": used_secid,
        "count": len(klines),
        "klines": klines,
        "unblock": _unblock_state_snapshot(timeout=min(float(timeout_sec), 3.0)),
    }


@skill(
    desc="查询当日分时成交明细（支持中文名称，返回最近若干笔）。",
    examples=[
        "stock_history_trades('600519', count=100)",
        "stock_history_trades('红利100ETF景顺', count=50)",
    ],
)
def stock_history_trades(
    symbol: str,
    count: int = 200,
    timeout_sec: float = 8.0,
) -> dict[str, Any]:
    """返回 {symbol, code, trades:[...]}。"""
    lmt = max(1, min(int(count), 1000))
    target = _resolve_identifier(symbol, timeout_sec=timeout_sec)
    code = target["code"]
    secids = _guess_secid_candidates(code, target.get("market"))

    last_error = ""
    details: list[str] = []
    used_secid = None
    for secid in secids:
        params = urllib.parse.urlencode(
            {
                "secid": secid,
                "pos": f"-{lmt}",
                "fltt": 2,
                "invt": 2,
                "fields1": "f1,f2,f3,f4",
                "fields2": "f51,f52,f53,f54,f55",
            }
        )
        url = f"https://push2.eastmoney.com/api/qt/stock/details/get?{params}"
        try:
            payload = _eastmoney_get_json(url, timeout=float(timeout_sec), retries=3)
            data_obj = payload.get("data") or {}
            details = data_obj.get("details") or []
            if details:
                used_secid = secid
                break
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            continue
    if not details:
        raise RuntimeError(f"成交明细获取失败: {symbol} ({code}) {last_error}")

    direction_map = {"1": "sell", "2": "buy", "3": "neutral", "4": "auction"}
    trades: list[dict[str, Any]] = []
    for row in details:
        parts = str(row).split(",")
        if len(parts) < 3:
            continue
        trades.append(
            {
                "time": parts[0],
                "price": _to_float(parts[1]),
                "volume": _to_float(parts[2]),
                "lots": _to_float(parts[3]) if len(parts) > 3 else None,
                "direction": direction_map.get(parts[4], parts[4] if len(parts) > 4 else None),
            }
        )
    return {
        "source": "eastmoney",
        "symbol": symbol,
        "code": code,
        "name": target.get("name"),
        "secid": used_secid,
        "count": len(trades),
        "trades": trades,
        "unblock": _unblock_state_snapshot(timeout=min(float(timeout_sec), 3.0)),
    }


@skill(
    desc="对历史 K 线做快速摘要（高低点、区间涨跌、振幅、均线趋势）。",
    examples=[
        "stock_kline_summary('600519', period='day', bars=60)",
        "stock_kline_summary('红利100', period='day', bars=120, adjust='none')",
    ],
)
def stock_kline_summary(
    symbol: str,
    period: str = "day",
    bars: int = 60,
    adjust: str = "qfq",
    timeout_sec: float = 8.0,
) -> dict[str, Any]:
    """返回历史 K 线统计摘要。"""
    n = max(20, min(int(bars), 500))
    raw = stock_kline(symbol, period=period, count=n, adjust=adjust, timeout_sec=timeout_sec)
    klines = raw.get("klines") or []
    if not klines:
        raise RuntimeError("kline 为空，无法生成摘要")

    closes = [x.get("close") for x in klines if isinstance(x.get("close"), (int, float))]
    highs = [x.get("high") for x in klines if isinstance(x.get("high"), (int, float))]
    lows = [x.get("low") for x in klines if isinstance(x.get("low"), (int, float))]
    if len(closes) < 2 or not highs or not lows:
        raise RuntimeError("有效 K 线数据不足，无法生成摘要")

    first_close = closes[0]
    last_close = closes[-1]
    highest = max(highs)
    lowest = min(lows)
    span_change = None
    span_change_pct = None
    if first_close not in (None, 0):
        span_change = round(last_close - first_close, 6)
        span_change_pct = round((span_change / first_close) * 100, 4)
    amplitude_pct = None
    if lowest not in (None, 0):
        amplitude_pct = round(((highest - lowest) / lowest) * 100, 4)

    def _ma(arr: list[float], win: int) -> float | None:
        if len(arr) < win:
            return None
        return round(sum(arr[-win:]) / win, 6)

    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    ma20 = _ma(closes, 20)

    trend = "neutral"
    if all(v is not None for v in (ma5, ma10, ma20)):
        if ma5 >= ma10 >= ma20:
            trend = "bullish"
        elif ma5 <= ma10 <= ma20:
            trend = "bearish"
        else:
            trend = "mixed"

    return {
        "source": raw.get("source"),
        "symbol": symbol,
        "code": raw.get("code"),
        "name": raw.get("name"),
        "period": period,
        "adjust": adjust,
        "bars": len(klines),
        "window": {
            "start": klines[0].get("time"),
            "end": klines[-1].get("time"),
        },
        "price_stats": {
            "first_close": first_close,
            "last_close": last_close,
            "highest": highest,
            "lowest": lowest,
            "span_change": span_change,
            "span_change_pct": span_change_pct,
            "amplitude_pct": amplitude_pct,
        },
        "moving_averages": {
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "trend": trend,
        },
    }
