#!/usr/bin/env python3
"""最小 HTTP 冒烟：对运行中的 Web 服务拉取若干路径（仅标准库）。

用法：
  python3 scripts/smoke_http.py http://127.0.0.1:8788

典型在 CI 中与 `uvicorn webapi.app:app` 联用（见 `.github/workflows/ci.yml`）。
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request


def _get(url: str, timeout: float = 15.0) -> int:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        _ = resp.read(512)
        return int(resp.status)


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
    print("smoke_http: all checks passed", file=sys.stderr)


if __name__ == "__main__":
    main()
