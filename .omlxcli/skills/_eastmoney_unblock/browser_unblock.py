from __future__ import annotations

import json
import sys
import time


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        print(f"playwright_unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    max_wait_sec = 120.0
    poll_sec = 1.2
    min_interactive_sec = 20.0
    url = "https://www.eastmoney.com/"
    check_url = "https://i.eastmoney.com/websitecaptcha/api/checkuser?callback=wsc_checkuser"
    probe_url = (
        "https://push2.eastmoney.com/api/qt/stock/get?"
        "fltt=2&invt=2&fields=f57,f58,f43,f170&secid=1.000001"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.bring_to_front()
            print("请在弹出的浏览器中完成东方财富拼图验证，脚本将自动检测是否解封...", file=sys.stderr)

            deadline = time.time() + max_wait_sec
            started_at = time.time()
            seen_blocked_true = False
            last_err = ""
            while time.time() < deadline:
                try:
                    resp = context.request.get(check_url, timeout=15000)
                    text = resp.text()
                    start = text.find("(")
                    end = text.rfind(")")
                    if start > 0 and end > start:
                        obj = json.loads(text[start + 1 : end])
                        # 注意：仅 checkuser=false 可能出现假阴性，需叠加真实行情接口探活通过。
                        blocked_raw = obj.get("block")
                        blocked = bool(blocked_raw) if blocked_raw is not None else True
                        if blocked is True:
                            seen_blocked_true = True
                        # 强制预留最短人工交互时长，避免“秒开秒关”。
                        if (time.time() - started_at) < min_interactive_sec:
                            time.sleep(poll_sec)
                            continue
                        # 只有观察到过 blocked=true，再转为 false 且探活成功才判定解封。
                        if seen_blocked_true and blocked is False:
                            probe = context.request.get(probe_url, timeout=15000)
                            ptxt = probe.text()
                            pobj = json.loads(ptxt or "{}")
                            data = pobj.get("data") or {}
                            if data.get("f57"):
                                print(json.dumps({"ok": True, "action": "browser_manual_unblocked"}))
                                return 0
                except Exception as exc:  # noqa: BLE001
                    last_err = f"{type(exc).__name__}: {exc}"
                time.sleep(poll_sec)
            if last_err:
                print(f"browser_manual_timeout_last_error={last_err}", file=sys.stderr)
            print("browser_manual_timeout_still_blocked", file=sys.stderr)
            return 3
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())

