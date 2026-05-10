#!/usr/bin/env python3
"""最小 HTTP 冒烟：对运行中的 Web 服务拉取若干路径（仅标准库）。

用法：
  python3 scripts/smoke_http.py http://127.0.0.1:8788

典型在 CI 中与 `uvicorn webapi.app:app` 联用（见 `.github/workflows/ci.yml`）。
"""

from __future__ import annotations

import sys
import json
import urllib.error
import urllib.request


def _get(url: str, timeout: float = 15.0) -> int:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        _ = resp.read(512)
        return int(resp.status)


def _get_json(url: str, timeout: float = 15.0, max_bytes: int = 262144) -> tuple[int, dict]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = int(resp.status)
        raw = resp.read(max_bytes).decode("utf-8", errors="replace")
    try:
        return status, json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return status, {"_raw": raw[:500]}


def _request_json(
    url: str,
    *,
    method: str,
    payload: dict | None = None,
    timeout: float = 15.0,
) -> tuple[int, dict]:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, method=method.upper(), data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(4096).decode("utf-8", errors="replace")
        if not raw:
            return int(resp.status), {}
        try:
            return int(resp.status), json.loads(raw)
        except json.JSONDecodeError:
            return int(resp.status), {"_raw": raw}


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: smoke_http.py BASE_URL", file=sys.stderr)
        raise SystemExit(2)
    base = sys.argv[1].rstrip("/")
    paths = ("/healthz", "/ui/", "/api/sessions")
    for p in paths:
        url = f"{base}{p}"
        try:
            code = _get(url)
        except urllib.error.HTTPError as exc:
            print(f"FAIL {url} HTTP {exc.code}", file=sys.stderr)
            raise SystemExit(1) from exc
        except OSError as exc:
            print(f"FAIL {url} {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if code >= 400:
            print(f"FAIL {url} status={code}", file=sys.stderr)
            raise SystemExit(1)
        print(f"OK {code} {url}")

    diag_url = f"{base}/api/diagnostics"
    try:
        dcode, ddata = _get_json(diag_url)
    except urllib.error.HTTPError as exc:
        print(f"FAIL {diag_url} HTTP {exc.code}", file=sys.stderr)
        raise SystemExit(1) from exc
    except OSError as exc:
        print(f"FAIL {diag_url} {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if dcode >= 400 or not isinstance(ddata, dict) or "python" not in ddata:
        print(f"FAIL {diag_url} status={dcode} body_keys={list(ddata)[:8]}", file=sys.stderr)
        raise SystemExit(1)
    print(f"OK {dcode} {diag_url}")

    ui_url = f"{base}/api/ui-config"
    try:
        ucode, udata = _get_json(ui_url)
    except urllib.error.HTTPError as exc:
        print(f"FAIL {ui_url} HTTP {exc.code}", file=sys.stderr)
        raise SystemExit(1) from exc
    except OSError as exc:
        print(f"FAIL {ui_url} {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if ucode >= 400 or not isinstance(udata, dict) or "msg_max_attachment_each_bytes" not in udata:
        print(f"FAIL {ui_url} status={ucode} body_keys={list(udata)[:8]}", file=sys.stderr)
        raise SystemExit(1)
    print(f"OK {ucode} {ui_url}")

    # 写路径最小冒烟：POST -> PATCH -> DELETE 会话。
    post_url = f"{base}/api/sessions"
    code, data = _request_json(post_url, method="POST", payload={"title": "smoke-http-write"})
    if code >= 400:
        print(f"FAIL {post_url} status={code}", file=sys.stderr)
        raise SystemExit(1)
    sid = str(data.get("id") or "").strip()
    if not sid:
        print(f"FAIL {post_url} missing session id in response", file=sys.stderr)
        raise SystemExit(1)
    print(f"OK {code} {post_url} id={sid}")

    patch_url = f"{base}/api/sessions/{sid}"
    code, _ = _request_json(patch_url, method="PATCH", payload={"archived": True})
    if code >= 400:
        print(f"FAIL {patch_url} status={code}", file=sys.stderr)
        raise SystemExit(1)
    print(f"OK {code} {patch_url}")

    del_url = f"{base}/api/sessions/{sid}"
    code, _ = _request_json(del_url, method="DELETE")
    if code >= 400:
        print(f"FAIL {del_url} status={code}", file=sys.stderr)
        raise SystemExit(1)
    print(f"OK {code} {del_url}")
    print("smoke_http: all checks passed", file=sys.stderr)


if __name__ == "__main__":
    main()
