# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Any

from webapi.dotenv_loader import load_dotenv_files

_ROOT_FOR_ENV = Path(__file__).resolve().parent.parent
load_dotenv_files(_ROOT_FOR_ENV)

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from webapi.context_manager import ContextManager
from webapi.claude_job_runtime import configure_claude_job_runtime, get_claude_job_service
from webapi.claude_job_service import claude_code_public_status
from webapi.diagnostics import build_diagnostics_payload
from webapi.logging_utils import log_event
from webapi.session_engine import DEFAULT_SESSION_MODEL_ID, OiSessionEngine
from webapi.session_store import SessionStore


ROOT = _ROOT_FOR_ENV
WEBUI_DIR = ROOT / "webui"
APP_NAME = "oMLX CLI"
DATA_DIR = Path(os.getenv("OMLXCLI_DATA_DIR", str(ROOT / ".omlxcli" / "web")))
DB_PATH = DATA_DIR / "sessions.db"
DEFAULT_WORKSPACE = os.path.abspath(
    os.path.expanduser(os.getenv("OMLXCLI_DEFAULT_WORKSPACE", str(ROOT)))
)

store = SessionStore(str(DB_PATH))
configure_claude_job_runtime(store=store, jobs_root=DATA_DIR / "claude-jobs")
ctx = ContextManager(store)
engine = OiSessionEngine(store, ctx)

_msg_rate_lock = threading.Lock()
_msg_rate_hits: dict[str, deque[float]] = {}


def _msg_rate_limit_count() -> int:
    raw = (os.getenv("OMLXCLI_MSG_RATE_LIMIT_COUNT") or "20").strip()
    try:
        n = int(raw)
    except ValueError:
        return 20
    return max(1, min(n, 500))


def _msg_rate_limit_window_sec() -> int:
    raw = (os.getenv("OMLXCLI_MSG_RATE_LIMIT_WINDOW_SEC") or "60").strip()
    try:
        n = int(raw)
    except ValueError:
        return 60
    return max(1, min(n, 3600))


def _allow_message_request(session_id: str, client_ip: str) -> tuple[bool, int]:
    limit = _msg_rate_limit_count()
    window = float(_msg_rate_limit_window_sec())
    now = time.monotonic()
    cutoff = now - window
    key = f"{session_id}:{client_ip or '-'}"
    with _msg_rate_lock:
        # 清理过期 key，避免 _msg_rate_hits 长时间增长。
        stale_keys: list[str] = []
        for k, qq in _msg_rate_hits.items():
            while qq and qq[0] < cutoff:
                qq.popleft()
            if not qq:
                stale_keys.append(k)
        for k in stale_keys:
            _msg_rate_hits.pop(k, None)

        q = _msg_rate_hits.get(key)
        if q is None:
            q = deque()
            _msg_rate_hits[key] = q
        if len(q) >= limit:
            retry_after = max(1, int(window - (now - q[0])))
            return False, retry_after
        q.append(now)
    return True, 0


def _msg_max_body_bytes() -> int:
    raw = (os.getenv("OMLXCLI_MSG_MAX_BODY_BYTES") or "5242880").strip()
    try:
        n = int(raw)
    except ValueError:
        return 5 * 1024 * 1024
    return max(64 * 1024, min(n, 50 * 1024 * 1024))


def _msg_max_attachments_bytes() -> int:
    raw = (os.getenv("OMLXCLI_MSG_MAX_ATTACHMENTS_BYTES") or "6291456").strip()
    try:
        n = int(raw)
    except ValueError:
        return 6 * 1024 * 1024
    return max(64 * 1024, min(n, 200 * 1024 * 1024))


def _estimate_attachments_bytes(attachments: list[dict[str, Any]]) -> int:
    total = 0
    for a in attachments or []:
        declared = int(a.get("size") or 0)
        data_url = str(a.get("data_url") or "")
        # data_url 通常是 base64 文本，估算用字符长度，取与 declared 的较大值更保守。
        total += max(0, declared, len(data_url))
    return total


def _vendor_dict(v: Any, *, include_api_key: bool = False) -> dict[str, Any]:
    """列表与创建/更新响应默认剔除 api_key；单条 GET 含 api_key 供管理界面编辑与下载模型列表。"""
    d = asdict(v)
    if not include_api_key:
        d.pop("api_key", None)
    return d


def _cors_allow_origins() -> tuple[list[str], bool]:
    """返回 (origins, allow_credentials)。显式列出来源；与浏览器携带 Cookie 时兼容。"""
    default = ("http://127.0.0.1:8788", "http://localhost:8788")
    raw = (os.getenv("OMLXCLI_CORS_ORIGINS") or "").strip()
    if not raw:
        return (list(default), True)
    items = [x.strip() for x in raw.split(",") if x.strip()]
    if not items:
        return (list(default), True)
    if any(x == "*" for x in items):
        return (["*"], False)
    return (items, True)


_cors_origins, _cors_credentials = _cors_allow_origins()

app = FastAPI(title=APP_NAME, version="0.2.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_payload(*, code: str, message: str, request_id: str) -> dict[str, Any]:
    return {"error_code": code, "message": message, "request_id": request_id}


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    duration_ms = round((time.perf_counter() - t0) * 1000, 1)
    log_event(
        "http_request",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    detail = exc.detail
    if isinstance(detail, dict) and {"error_code", "message", "request_id"}.issubset(detail.keys()):
        payload = detail
    else:
        payload = _error_payload(code="HTTP_ERROR", message=str(detail), request_id=request_id)
    log_event(
        "http_exception",
        request_id=request_id,
        path=request.url.path,
        status_code=exc.status_code,
        detail=payload["message"],
        error_code=payload["error_code"],
    )
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    payload = _error_payload(code="INTERNAL_ERROR", message=str(exc), request_id=request_id)
    log_event(
        "internal_exception",
        request_id=request_id,
        path=request.url.path,
        error_code=payload["error_code"],
        detail=payload["message"],
    )
    return JSONResponse(status_code=500, content=payload)


class CreateSessionReq(BaseModel):
    title: str = Field(default="新会话")
    workspace_path: str = Field(default=DEFAULT_WORKSPACE)
    model: str = Field(default_factory=lambda: DEFAULT_SESSION_MODEL_ID)
    api_base: str = Field(default="", description="未选择模型设置时可留空；选择模型设置后由服务端同步")
    vendor_id: str | None = Field(
        default=None,
        description="若设置则从该模型设置同步 api_base；省略则会话暂不绑定模型设置（发消息前须选择并保存）",
    )
    auto_run: bool = True
    execution_enabled: bool = False
    confirm_each: bool = True


class UpdateSessionReq(BaseModel):
    title: str | None = None
    workspace_path: str | None = None
    model: str | None = None
    api_base: str | None = None
    vendor_id: str | None = None
    auto_run: bool | None = None
    execution_enabled: bool | None = None
    confirm_each: bool | None = None
    archived: bool | None = None


class VendorProbeReq(BaseModel):
    api_base: str
    api_key: str


class CreateVendorReq(BaseModel):
    name: str
    api_base: str
    default_model: str = ""
    api_key: str | None = Field(default=None, description="可选；非空则写入 SQLite vendors.api_key")


class UpdateVendorReq(BaseModel):
    name: str | None = None
    api_base: str | None = None
    default_model: str | None = None
    api_key: str | None = Field(
        default=None,
        description="若设置则更新 SQLite vendors.api_key（可传空字符串清空）",
    )


class SendMessageReq(BaseModel):
    content: str
    system_prompt: str = "你是本地 CLI 助手，默认用简体中文回答并优先给出可执行建议。"
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class ContextReq(BaseModel):
    content: str
    priority: int = Field(default=0, ge=-1000, le=1000)


class CheckpointReq(BaseModel):
    summary: str


class ResumeReq(BaseModel):
    checkpoint_id: str
    mode: str = Field(
        default="append",
        description="append：在现有 working 上追加；replace：先清空 working 再恢复",
    )


class BatchArchiveSessionsReq(BaseModel):
    session_ids: list[str] = Field(default_factory=list)
    archived: bool = True


class ConfirmCommandReq(BaseModel):
    command: str
    approve: bool = True


def _normalize_workspace_path(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return DEFAULT_WORKSPACE
    # 去掉用户常见的包裹符号，如 "(...)" 或 "'...'"
    if len(s) >= 2 and ((s[0], s[-1]) in {("(", ")"), ("'", "'"), ('"', '"')}):
        s = s[1:-1].strip()
    s = os.path.expanduser(s)
    return os.path.abspath(s)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"ok": "true"}


@app.get("/api/diagnostics")
def api_diagnostics() -> dict[str, Any]:
    """本地环境与数据目录自检 JSON（不含 API Key 等敏感字段）。"""
    return build_diagnostics_payload(
        root=ROOT,
        data_dir=DATA_DIR,
        db_path=DB_PATH,
        webui_dir=WEBUI_DIR,
        default_workspace=DEFAULT_WORKSPACE,
    )


def _fetch_upstream_model_ids(api_base: str, api_key: str) -> tuple[str, list[str]]:
    """请求上游 GET {base}/models，返回 (规范化 base, 模型 id 列表)。"""
    base = (api_base or "").strip().rstrip("/")
    if not base:
        raise HTTPException(status_code=400, detail="api_base 不能为空")
    key = (api_key or "").strip() or "not-needed"
    url = base + "/models"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {key}"},
        method="GET",
    )
    models_timeout = int(os.getenv("OMLXCLI_MODELS_LIST_TIMEOUT_SEC", "8"))
    try:
        with urllib.request.urlopen(req, timeout=models_timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")[:500]
        raise HTTPException(
            status_code=502,
            detail=f"上游 /models 失败 HTTP {exc.code}: {body}",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    models: list[str] = []
    for item in raw.get("data") or []:
        mid = item.get("id") if isinstance(item, dict) else None
        if isinstance(mid, str) and mid.strip():
            models.append(mid.strip())
    return base, models


@app.get("/api/models")
def list_models(
    api_base: str | None = Query(
        default=None,
        description="已废弃，不再使用",
    ),
    vendor_id: str | None = Query(
        default=None,
        description="模型设置 id（vendors.id），必填",
    ),
) -> dict[str, Any]:
    """代理上游 /models；密钥来自 SQLite vendors.api_key。"""
    _ = api_base
    vid = (vendor_id or "").strip()
    if not vid:
        raise HTTPException(status_code=400, detail="请传入 vendor_id（模型设置 id）。")
    if store.count_vendors() == 0:
        raise HTTPException(
            status_code=400,
            detail="尚未配置任何模型设置。请先在「模型设置」中添加至少一条并保存 API Key。",
        )
    try:
        v = store.get_vendor(vid)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    key = (v.api_key or "").strip()
    if not key:
        raise HTTPException(
            status_code=400,
            detail=f"模型设置「{v.name}」未保存 API Key，请编辑该条并保存。",
        )
    base, models = _fetch_upstream_model_ids(v.api_base, key)
    return {"api_base": base, "models": models, "vendor_id": v.id}


@app.post("/api/vendors/probe")
def probe_vendor(req: VendorProbeReq) -> dict[str, Any]:
    """使用请求体中的 api_key 拉取模型列表（不写库、不写文件）；供界面「下载模型列表」。"""
    if not (req.api_key or "").strip():
        raise HTTPException(status_code=400, detail="api_key 不能为空")
    base, models = _fetch_upstream_model_ids(req.api_base, req.api_key.strip())
    return {"ok": True, "api_base": base, "models": models}


@app.get("/api/vendors")
def list_vendors() -> list[dict[str, Any]]:
    return [_vendor_dict(v) for v in store.list_vendors()]


@app.get("/api/vendors/default")
def get_default_vendor() -> dict[str, Any]:
    return {"vendor_id": store.get_default_vendor_id()}


@app.put("/api/vendors/default")
def set_default_vendor(payload: dict[str, Any]) -> dict[str, Any]:
    raw = (payload.get("vendor_id") if isinstance(payload, dict) else None) or None
    try:
        vid = store.set_default_vendor_id(str(raw).strip() if raw is not None else None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"vendor_id": vid}


@app.get("/api/vendors/{vendor_id}")
def get_vendor_row(vendor_id: str) -> dict[str, Any]:
    try:
        return _vendor_dict(store.get_vendor(vendor_id), include_api_key=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/vendors")
def create_vendor_row(req: CreateVendorReq) -> dict[str, Any]:
    try:
        slug = store.allocate_unique_vendor_slug(req.name.strip())
        v = store.create_vendor(
            name=req.name.strip(),
            slug=slug,
            api_base=req.api_base.strip(),
            default_model=(req.default_model or "").strip(),
            api_key=(req.api_key or "").strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="slug 已存在") from exc
    log_event("vendor_created", vendor_id=v.id, slug=v.slug)
    return _vendor_dict(v)


@app.patch("/api/vendors/{vendor_id}")
def patch_vendor_row(vendor_id: str, req: UpdateVendorReq) -> dict[str, Any]:
    data = req.model_dump(exclude_unset=True)
    try:
        v = store.update_vendor(vendor_id, **data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event("vendor_updated", vendor_id=vendor_id)
    return _vendor_dict(v)


@app.delete("/api/vendors/{vendor_id}")
def delete_vendor_row(vendor_id: str) -> dict[str, str]:
    try:
        store.delete_vendor(vendor_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log_event("vendor_deleted", vendor_id=vendor_id)
    return {"status": "ok"}


@app.post("/api/sessions")
def create_session(req: CreateSessionReq) -> dict[str, Any]:
    workspace_path = _normalize_workspace_path(req.workspace_path)
    model = req.model
    api_base = (req.api_base or "").strip().rstrip("/")
    vendor_id: str | None = None
    requested_vendor = (req.vendor_id or "").strip() or store.get_default_vendor_id()
    if not requested_vendor:
        # 体验兜底：若用户尚未显式设置默认供应商，且当前仅有一条模型设置，
        # 新建会话自动绑定该条，避免“创建后仍需手动进入设置绑定”。
        vendors = store.list_vendors()
        if len(vendors) == 1:
            requested_vendor = vendors[0].id
    if requested_vendor:
        try:
            v = store.get_vendor(requested_vendor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        vendor_id = v.id
        api_base = (v.api_base or "").strip().rstrip("/")
        dm = (v.default_model or "").strip()
        if dm:
            model = dm
    record = store.create_session(
        title=req.title,
        workspace_path=workspace_path,
        model=model,
        api_base=api_base,
        auto_run=req.auto_run,
        vendor_id=vendor_id,
    )
    if req.execution_enabled or (req.confirm_each is not True):
        record = store.update_session(
            record.id,
            execution_enabled=req.execution_enabled,
            confirm_each=req.confirm_each,
        )
    log_event("session_created", session_id=record.id, workspace_path=workspace_path, model=model)
    return asdict(record)


@app.get("/api/sessions")
def list_sessions(
    include_archived: int = Query(default=0, ge=0, le=1),
) -> list[dict[str, Any]]:
    return [asdict(s) for s in store.list_sessions(include_archived=bool(include_archived))]


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    try:
        session = store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        **asdict(session),
        "messages": store.list_messages(session_id),
        "contexts": store.list_contexts(session_id),
        "checkpoints": store.list_checkpoints(session_id),
        "executions": store.list_executions(session_id, limit=100),
        "context_injections": store.list_context_injections(session_id, limit=120),
    }


@app.patch("/api/sessions/{session_id}")
def update_session(session_id: str, req: UpdateSessionReq) -> dict[str, Any]:
    data = req.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        data["title_locked"] = 1
    if "workspace_path" in data and data["workspace_path"] is not None:
        data["workspace_path"] = _normalize_workspace_path(data["workspace_path"])
    if "vendor_id" in data:
        vid = data.get("vendor_id")
        if vid:
            try:
                v = store.get_vendor(str(vid).strip())
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            data["vendor_id"] = v.id
            data["api_base"] = v.api_base
            dm = (v.default_model or "").strip()
            if dm and "model" not in data:
                data["model"] = dm
        else:
            data["vendor_id"] = None
    try:
        updated = store.update_session(session_id, **data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return asdict(updated)


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, str]:
    store.delete_session(session_id)
    return {"status": "ok"}


@app.post("/api/sessions/batch-archive")
def batch_archive_sessions(req: BatchArchiveSessionsReq) -> dict[str, Any]:
    """批量归档或取消归档会话（第 1 节：会话生命周期治理）。"""
    updated = 0
    for sid in req.session_ids[:500]:
        s = (sid or "").strip()
        if not s:
            continue
        try:
            store.update_session(s, archived=req.archived)
            updated += 1
        except KeyError:
            continue
    return {"status": "ok", "updated": updated}


@app.post("/api/sessions/{session_id}/messages")
def send_message(session_id: str, req: SendMessageReq, request: Request) -> StreamingResponse:
    content_len = request.headers.get("content-length") or ""
    if content_len:
        try:
            body_n = int(content_len)
        except ValueError:
            body_n = 0
        if body_n > _msg_max_body_bytes():
            detail = _error_payload(
                code="PAYLOAD_TOO_LARGE",
                message=f"请求体过大（>{_msg_max_body_bytes()} bytes）。",
                request_id=getattr(request.state, "request_id", str(uuid.uuid4())),
            )
            raise HTTPException(status_code=413, detail=detail)
    att_n = _estimate_attachments_bytes(req.attachments)
    if att_n > _msg_max_attachments_bytes():
        detail = _error_payload(
            code="ATTACHMENTS_TOO_LARGE",
            message=f"附件总大小过大（>{_msg_max_attachments_bytes()} bytes）。",
            request_id=getattr(request.state, "request_id", str(uuid.uuid4())),
        )
        raise HTTPException(status_code=413, detail=detail)
    client_ip = ""
    if request.client and request.client.host:
        client_ip = str(request.client.host)
    ok, retry_after = _allow_message_request(session_id, client_ip)
    if not ok:
        detail = _error_payload(
            code="RATE_LIMITED",
            message=f"请求过于频繁，请 {retry_after} 秒后重试。",
            request_id=getattr(request.state, "request_id", str(uuid.uuid4())),
        )
        raise HTTPException(status_code=429, detail=detail)
    log_event("session_message_received", session_id=session_id, content_chars=len(req.content or ""))
    def event_stream():
        try:
            _ = store.get_session(session_id)
        except KeyError:
            yield "event: error\ndata: " + json.dumps({"message": "session not found"}, ensure_ascii=False) + "\n\n"
            return

        try:
            for event in engine.stream_reply(
                session_id=session_id,
                user_input=req.content,
                system_prompt=req.system_prompt,
                attachments=req.attachments,
            ):
                yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            msg = f"会话流异常：{type(exc).__name__}: {str(exc)[:280]}"
            yield "event: error\ndata: " + json.dumps({"message": msg}, ensure_ascii=False) + "\n\n"
            return
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/sessions/{session_id}/confirm-command")
def confirm_command(session_id: str, req: ConfirmCommandReq) -> dict[str, Any]:
    try:
        session = store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not req.approve:
        store.update_session(session_id, pending_command="")
        msg = "已取消待确认命令。"
        store.add_execution(
            session_id=session_id,
            exec_type="shell",
            command=req.command,
            status="cancelled",
            reason="user_rejected",
        )
        store.add_message(session_id=session_id, role="assistant", content=msg, kind="assistant")
        log_event("command_confirm_rejected", session_id=session_id, command=req.command)
        return {"status": "cancelled", "message": msg}
    try:
        result = engine.run_confirmed_command(session_id=session_id, command=req.command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    latest = store.get_session(session_id)
    log_event("command_confirm_approved", session_id=session_id, command=req.command, exit_code=result.get("exit_code"))
    return {"status": "ok", **result, "pending_command": latest.pending_command}


@app.get("/api/sessions/{session_id}/executions")
def list_executions(session_id: str, limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    try:
        _ = store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return store.list_executions(session_id, limit=limit)


@app.get("/api/sessions/{session_id}/context-injections")
def list_context_injections(
    session_id: str, limit: int = Query(default=120, ge=1, le=500)
) -> list[dict[str, Any]]:
    try:
        _ = store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return store.list_context_injections(session_id, limit=limit)


@app.get("/api/sessions/{session_id}/agent-trace")
def list_agent_trace(
    session_id: str,
    turn_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[dict[str, Any]]:
    try:
        _ = store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return store.list_agent_trace(session_id, turn_id=turn_id, limit=limit)


def _claude_job_list_brief(row: dict[str, Any]) -> dict[str, Any]:
    p = str(row.get("prompt") or "")
    prev = p[:160] + ("…" if len(p) > 160 else "")
    return {
        "id": row["id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "exit_code": row["exit_code"],
        "prompt_preview": prev,
        "workspace_path": row["workspace_path"],
        "pid": row["pid"],
    }


@app.get("/api/claude-code/status")
def claude_code_status() -> dict[str, Any]:
    return claude_code_public_status()


@app.get("/api/sessions/{session_id}/claude-jobs")
def list_claude_jobs_api(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    try:
        _ = store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    st = claude_code_public_status()
    if not st["enabled"]:
        return {"enabled": False, "jobs": [], **st}
    rows = get_claude_job_service().list_jobs(session_id, limit=limit)
    return {"enabled": True, "jobs": [_claude_job_list_brief(r) for r in rows], **st}


@app.get("/api/sessions/{session_id}/claude-jobs/{job_id}")
def get_claude_job_api(session_id: str, job_id: str, request: Request) -> dict[str, Any]:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    st = claude_code_public_status()
    if not st["enabled"]:
        raise HTTPException(
            status_code=501,
            detail=_error_payload(
                code="CLAUDE_CODE_DISABLED",
                message=st["reason"] or "Claude Code Job 不可用",
                request_id=request_id,
            ),
        )
    try:
        row = get_claude_job_service().get_job(session_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=_error_payload(code="FORBIDDEN", message=str(exc), request_id=request_id),
        ) from exc
    return {"enabled": True, "job": row}


@app.get("/api/sessions/{session_id}/claude-jobs/{job_id}/logs")
def get_claude_job_logs_api(
    session_id: str,
    job_id: str,
    request: Request,
    tail: int = Query(default=200, ge=1, le=5000),
) -> dict[str, Any]:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    st = claude_code_public_status()
    if not st["enabled"]:
        raise HTTPException(
            status_code=501,
            detail=_error_payload(
                code="CLAUDE_CODE_DISABLED",
                message=st["reason"] or "Claude Code Job 不可用",
                request_id=request_id,
            ),
        )
    try:
        text = get_claude_job_service().tail_logs(session_id, job_id, tail_lines=tail)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=_error_payload(code="FORBIDDEN", message=str(exc), request_id=request_id),
        ) from exc
    return {"enabled": True, "tail": tail, "text": text}


@app.post("/api/sessions/{session_id}/claude-jobs/{job_id}/cancel")
def cancel_claude_job_api(session_id: str, job_id: str, request: Request) -> dict[str, Any]:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    st = claude_code_public_status()
    if not st["enabled"]:
        raise HTTPException(
            status_code=501,
            detail=_error_payload(
                code="CLAUDE_CODE_DISABLED",
                message=st["reason"] or "Claude Code Job 不可用",
                request_id=request_id,
            ),
        )
    try:
        out = get_claude_job_service().cancel_job(session_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=_error_payload(code="FORBIDDEN", message=str(exc), request_id=request_id),
        ) from exc
    log_event("claude_job_cancel", session_id=session_id, job_id=job_id)
    return {"enabled": True, **out}


@app.get("/api/admin/sessions/{session_id}/audit-export")
def admin_audit_export(session_id: str, request: Request) -> dict[str, Any]:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    admin_token = os.getenv("OMLXCLI_ADMIN_TOKEN", "").strip()
    if not admin_token:
        raise HTTPException(
            status_code=501,
            detail=_error_payload(
                code="ADMIN_NOT_CONFIGURED",
                message="未配置 OMLXCLI_ADMIN_TOKEN，无法导出审计包。",
                request_id=request_id,
            ),
        )
    if (request.headers.get("x-admin-token") or "").strip() != admin_token:
        raise HTTPException(
            status_code=403,
            detail=_error_payload(
                code="FORBIDDEN",
                message="管理员令牌无效。",
                request_id=request_id,
            ),
        )
    try:
        session = store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "session": asdict(session),
        "messages": store.list_messages(session_id, limit=400),
        "executions": store.list_executions(session_id, limit=500),
        "context_injections": store.list_context_injections(session_id, limit=300),
        "agent_trace": store.list_agent_trace(session_id, limit=500),
    }


@app.post("/api/sessions/{session_id}/context/pin")
def pin_context(session_id: str, req: ContextReq) -> dict[str, Any]:
    return ctx.add_pinned(session_id, req.content, priority=req.priority)


@app.post("/api/sessions/{session_id}/context/working")
def add_working_context(session_id: str, req: ContextReq) -> dict[str, Any]:
    return ctx.add_working(session_id, req.content, priority=req.priority)


@app.post("/api/sessions/{session_id}/context/checkpoint")
def create_checkpoint(session_id: str, req: CheckpointReq) -> dict[str, Any]:
    recent = store.list_messages(session_id, limit=200)
    return ctx.create_checkpoint(session_id, req.summary, recent)


@app.post("/api/sessions/{session_id}/resume")
def resume_checkpoint(session_id: str, req: ResumeReq) -> dict[str, Any]:
    mode = (req.mode or "append").strip().lower()
    if mode not in ("append", "replace"):
        raise HTTPException(status_code=400, detail="mode 必须是 append 或 replace")
    try:
        checkpoint = ctx.restore_from_checkpoint(
            session_id, req.checkpoint_id, mode=mode
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return checkpoint


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


if WEBUI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(WEBUI_DIR), html=True), name="ui")


@app.get("/ui/index.html")
def index_file() -> FileResponse:
    return FileResponse(str(WEBUI_DIR / "index.html"))
