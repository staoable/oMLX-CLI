from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Generator, Iterable

_RETRY_HTTP = frozenset({429, 502, 503, 504})

# chat = 仅 POST /chat/completions（默认）
# completions = 仅 POST /completions（将 messages 压成单一 prompt）
# auto = 先 chat；若整条请求在耗尽重试后仍以 HTTP 404/405/501 失败，再尝试 completions
_AUTO_FALLBACK_CODES = frozenset({404, 405, 501})


def _upstream_protocol() -> str:
    raw = (os.getenv("OMLXCLI_UPSTREAM_PROTOCOL") or "chat").strip().lower()
    if raw in ("completion", "completions", "legacy"):
        return "completions"
    if raw in ("auto", "try_completions", "try_completions_on_fail"):
        return "auto"
    return "chat"


def upstream_llm_protocol() -> str:
    """解析 `OMLXCLI_UPSTREAM_PROTOCOL` 后的取值：chat | completions | auto。"""
    return _upstream_protocol()


def _chat_http_settings(timeout_override: int | None) -> tuple[int, int, float]:
    t = int(os.getenv("OMLXCLI_CHAT_TIMEOUT_SEC", "120")) if timeout_override is None else int(timeout_override)
    retries = max(0, min(int(os.getenv("OMLXCLI_CHAT_HTTP_RETRIES", "2")), 8))
    backoff = float(os.getenv("OMLXCLI_CHAT_RETRY_BACKOFF_SEC", "0.5"))
    return t, retries, backoff


def _model_chain(primary: str) -> list[str]:
    raw = (os.getenv("OMLXCLI_MODEL_FALLBACKS") or "").strip()
    seen: set[str] = set()
    out: list[str] = []
    for m in [primary] + [x.strip() for x in raw.split(",") if x.strip()]:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _urlopen_with_retries(
    req: urllib.request.Request,
    *,
    timeout: int,
    max_retries: int,
    backoff: float,
) -> Any:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            try:
                exc.read()
            except Exception:  # noqa: BLE001
                pass
            if exc.code in _RETRY_HTTP and attempt < max_retries:
                time.sleep(backoff * (2**attempt))
                continue
            raise
        except (TimeoutError, urllib.error.URLError, OSError, ConnectionResetError) as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(backoff * (2**attempt))
                continue
            raise
    raise RuntimeError("_urlopen_with_retries: exhausted without response")


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


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if not isinstance(p, dict):
                continue
            if p.get("type") == "text" and isinstance(p.get("text"), str):
                parts.append(p["text"])
            elif isinstance(p.get("text"), str) and not p.get("type"):
                parts.append(p["text"])
        return "\n".join(parts)
    return ""


def completion_prompt_from_messages(messages: list[Dict[str, Any]]) -> str:
    """将 chat messages 压成单一 prompt，供 /completions 使用（多模态仅保留文本段）。"""
    lines: list[str] = []
    for m in messages:
        role = str(m.get("role") or "user").strip().lower()
        text = _content_to_text(m.get("content")).strip()
        if not text:
            continue
        lines.append(f"{role.upper()}:\n{text}")
    return "\n\n".join(lines).strip()


def _completions_chunk_as_chat_delta(obj: Dict[str, Any]) -> Dict[str, Any] | None:
    choices = obj.get("choices") or []
    if not choices:
        return None
    ch0 = choices[0]
    if not isinstance(ch0, dict):
        return None
    piece = ch0.get("text")
    if isinstance(piece, str) and piece:
        return {"choices": [{"delta": {"content": piece}}]}
    return None


def _iter_sse_data_lines(resp: Any) -> Generator[str, None, None]:
    for raw in resp:
        line = raw.decode("utf-8", errors="ignore").strip()
        if not line.startswith("data: "):
            continue
        yield line[6:]


def _stream_chat_completions_impl(
    api_base: str,
    api_key: str,
    model: str,
    messages: list[Dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: int | None = None,
) -> Generator[Dict[str, Any], None, None]:
    t, max_retries, backoff = _chat_http_settings(timeout)
    models = _model_chain(model)
    last_model_exc: urllib.error.HTTPError | None = None
    for m in models:
        payload: Dict[str, Any] = {
            "model": m,
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
        try:
            with _urlopen_with_retries(req, timeout=t, max_retries=max_retries, backoff=backoff) as resp:
                for data in _iter_sse_data_lines(resp):
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    yield obj
            return
        except urllib.error.HTTPError as exc:
            try:
                exc.read()
            except Exception:  # noqa: BLE001
                pass
            if exc.code == 404 and m != models[-1]:
                last_model_exc = exc
                continue
            raise
    if last_model_exc:
        raise last_model_exc


def _stream_completions_normalized(
    api_base: str,
    api_key: str,
    model: str,
    messages: list[Dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: int | None = None,
) -> Generator[Dict[str, Any], None, None]:
    prompt = completion_prompt_from_messages(messages)
    if not prompt:
        raise ValueError("completions 协议需要非空 prompt（messages 无可用文本）")
    t, max_retries, backoff = _chat_http_settings(timeout)
    models = _model_chain(model)
    last_model_exc: urllib.error.HTTPError | None = None
    for m in models:
        payload: Dict[str, Any] = {
            "model": m,
            "prompt": prompt,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        req = urllib.request.Request(
            url=api_base.rstrip("/") + "/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with _urlopen_with_retries(req, timeout=t, max_retries=max_retries, backoff=backoff) as resp:
                for data in _iter_sse_data_lines(resp):
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    norm = _completions_chunk_as_chat_delta(obj)
                    if norm is not None:
                        yield norm
            return
        except urllib.error.HTTPError as exc:
            try:
                exc.read()
            except Exception:  # noqa: BLE001
                pass
            if exc.code == 404 and m != models[-1]:
                last_model_exc = exc
                continue
            raise
    if last_model_exc:
        raise last_model_exc


def stream_chat_completions(
    api_base: str,
    api_key: str,
    model: str,
    messages: list[Dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: int | None = None,
) -> Generator[Dict[str, Any], None, None]:
    proto = _upstream_protocol()
    if proto == "completions":
        yield from _stream_completions_normalized(
            api_base,
            api_key,
            model,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        return
    if proto == "auto":
        try:
            yield from _stream_chat_completions_impl(
                api_base,
                api_key,
                model,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        except urllib.error.HTTPError as exc:
            if exc.code not in _AUTO_FALLBACK_CODES:
                raise
            yield from _stream_completions_normalized(
                api_base,
                api_key,
                model,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        return
    yield from _stream_chat_completions_impl(
        api_base,
        api_key,
        model,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )


def _chat_completion_once_impl(
    api_base: str,
    api_key: str,
    model: str,
    messages: list[Dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: int | None = None,
) -> Dict[str, Any]:
    t, max_retries, backoff = _chat_http_settings(timeout)
    models = _model_chain(model)
    last_model_exc: urllib.error.HTTPError | None = None
    for m in models:
        payload: Dict[str, Any] = {
            "model": m,
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
        try:
            with _urlopen_with_retries(req, timeout=t, max_retries=max_retries, backoff=backoff) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
            return json.loads(body)
        except urllib.error.HTTPError as exc:
            try:
                exc.read()
            except Exception:  # noqa: BLE001
                pass
            if exc.code == 404 and m != models[-1]:
                last_model_exc = exc
                continue
            raise
    if last_model_exc:
        raise last_model_exc
    raise RuntimeError("chat_completion_once: no model candidates")


def _completion_once_impl(
    api_base: str,
    api_key: str,
    model: str,
    messages: list[Dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: int | None = None,
) -> Dict[str, Any]:
    prompt = completion_prompt_from_messages(messages)
    if not prompt:
        raise ValueError("completions 协议需要非空 prompt（messages 无可用文本）")
    t, max_retries, backoff = _chat_http_settings(timeout)
    models = _model_chain(model)
    last_model_exc: urllib.error.HTTPError | None = None
    for m in models:
        payload: Dict[str, Any] = {
            "model": m,
            "prompt": prompt,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        req = urllib.request.Request(
            url=api_base.rstrip("/") + "/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with _urlopen_with_retries(req, timeout=t, max_retries=max_retries, backoff=backoff) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
            return json.loads(body)
        except urllib.error.HTTPError as exc:
            try:
                exc.read()
            except Exception:  # noqa: BLE001
                pass
            if exc.code == 404 and m != models[-1]:
                last_model_exc = exc
                continue
            raise
    if last_model_exc:
        raise last_model_exc
    raise RuntimeError("completion_once: no model candidates")


def chat_completion_once(
    api_base: str,
    api_key: str,
    model: str,
    messages: list[Dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: int | None = None,
) -> Dict[str, Any]:
    proto = _upstream_protocol()
    if proto == "completions":
        return _completion_once_impl(
            api_base,
            api_key,
            model,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
    if proto == "auto":
        try:
            return _chat_completion_once_impl(
                api_base,
                api_key,
                model,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        except urllib.error.HTTPError as exc:
            if exc.code not in _AUTO_FALLBACK_CODES:
                raise
            return _completion_once_impl(
                api_base,
                api_key,
                model,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
    return _chat_completion_once_impl(
        api_base,
        api_key,
        model,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
