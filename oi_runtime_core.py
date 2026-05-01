from __future__ import annotations

import json
import socket
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Generator, Iterable


@dataclass(slots=True)
class ApiProbeResult:
    api_base: str
    last_error: str | None = None


def detect_memory_gb() -> int:
    try:
        out = subprocess.check_output(["sysctl", "-n", "hw.memsize"]).decode().strip()
        mem_bytes = int(out)
        return mem_bytes // (1024**3)
    except Exception:
        return 32


def auto_context_window() -> int:
    mem_gb = detect_memory_gb()
    if mem_gb >= 120:
        return 65536
    if mem_gb >= 64:
        return 32768
    return 16384


def auto_max_tokens(context_window: int) -> int:
    return max(1024, min(8192, context_window // 8))


def build_api_base_candidates(preferred_api_base: str) -> list[str]:
    preferred = preferred_api_base.rstrip("/")
    candidates = [preferred]
    if "127.0.0.1:8000" not in preferred:
        candidates.append("http://127.0.0.1:8000/v1")
    if "localhost:8000" not in preferred:
        candidates.append("http://localhost:8000/v1")
    candidates.append(f"http://{socket.gethostname()}:8000/v1")
    return candidates


def probe_api_base(candidates: Iterable[str], api_key: str, timeout: int = 3) -> ApiProbeResult | None:
    last_exc: Exception | None = None
    for base in candidates:
        models_url = base.rstrip("/") + "/models"
        req = urllib.request.Request(
            models_url,
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status < 400:
                    return ApiProbeResult(api_base=base.rstrip("/"))
                last_exc = RuntimeError(f"HTTP {resp.status}")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 502):
                return ApiProbeResult(api_base=base.rstrip("/"), last_error=str(exc))
            last_exc = exc
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    return None if last_exc is None else ApiProbeResult(api_base="", last_error=str(last_exc))


def stream_chat_completions(
    api_base: str,
    api_key: str,
    model: str,
    messages: list[Dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: int = 120,
) -> Generator[Dict[str, Any], None, None]:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    req = urllib.request.Request(
        url=api_base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            yield obj


def chat_completion_once(
    api_base: str,
    api_key: str,
    model: str,
    messages: list[Dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    req = urllib.request.Request(
        url=api_base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
    return json.loads(body)
