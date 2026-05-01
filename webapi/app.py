from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from webapi.context_manager import ContextManager
from webapi.logging_utils import log_event
from webapi.session_engine import OiSessionEngine
from webapi.session_store import SessionStore


ROOT = Path(__file__).resolve().parent.parent
WEBUI_DIR = ROOT / "webui"
APP_NAME = "oMLX CLI"
DATA_DIR = Path(os.getenv("OMLXCLI_DATA_DIR", str(ROOT / ".omlxcli" / "web")))
DB_PATH = DATA_DIR / "sessions.db"
DEFAULT_WORKSPACE = os.path.abspath(
    os.path.expanduser(os.getenv("OMLXCLI_DEFAULT_WORKSPACE", str(ROOT)))
)

store = SessionStore(str(DB_PATH))
ctx = ContextManager(store)
engine = OiSessionEngine(store, ctx)

app = FastAPI(title=APP_NAME, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
    model: str = Field(
        default_factory=lambda: os.getenv("OI_MODEL", "Qwen3.5-35B-A3B-8bit")
    )
    api_base: str = Field(default_factory=lambda: os.getenv("OI_API_BASE", "http://127.0.0.1:8000/v1"))
    auto_run: bool = True
    execution_enabled: bool = False
    confirm_each: bool = True


class UpdateSessionReq(BaseModel):
    title: str | None = None
    workspace_path: str | None = None
    model: str | None = None
    api_base: str | None = None
    auto_run: bool | None = None
    execution_enabled: bool | None = None
    confirm_each: bool | None = None


class SendMessageReq(BaseModel):
    content: str
    system_prompt: str = "你是本地 CLI 助手，默认用简体中文回答并优先给出可执行建议。"
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class ContextReq(BaseModel):
    content: str


class CheckpointReq(BaseModel):
    summary: str


class ResumeReq(BaseModel):
    checkpoint_id: str


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


@app.get("/api/models")
def list_models(
    api_base: str | None = Query(
        default=None,
        description="OpenAI 兼容根地址，例如 http://127.0.0.1:8000/v1",
    ),
) -> dict[str, Any]:
    """代理上游 /v1/models，供前端下拉选择（避免浏览器跨域）。"""
    base = (api_base or os.getenv("OI_API_BASE", "http://127.0.0.1:8000/v1")).rstrip("/")
    key = os.getenv("OI_API_KEY", "not-needed")
    url = base + "/models"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
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
    return {"api_base": base, "models": models}


@app.post("/api/sessions")
def create_session(req: CreateSessionReq) -> dict[str, Any]:
    workspace_path = _normalize_workspace_path(req.workspace_path)
    record = store.create_session(
        title=req.title,
        workspace_path=workspace_path,
        model=req.model,
        api_base=req.api_base,
        auto_run=req.auto_run,
    )
    if req.execution_enabled or (req.confirm_each is not True):
        record = store.update_session(
            record.id,
            execution_enabled=req.execution_enabled,
            confirm_each=req.confirm_each,
        )
    log_event("session_created", session_id=record.id, workspace_path=workspace_path, model=req.model)
    return asdict(record)


@app.get("/api/sessions")
def list_sessions() -> list[dict[str, Any]]:
    return [asdict(s) for s in store.list_sessions()]


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
    try:
        updated = store.update_session(session_id, **data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return asdict(updated)


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, str]:
    store.delete_session(session_id)
    return {"status": "ok"}


@app.post("/api/sessions/{session_id}/messages")
def send_message(session_id: str, req: SendMessageReq) -> StreamingResponse:
    log_event("session_message_received", session_id=session_id, content_chars=len(req.content or ""))
    def event_stream():
        try:
            _ = store.get_session(session_id)
        except KeyError:
            yield "event: error\ndata: " + json.dumps({"message": "session not found"}, ensure_ascii=False) + "\n\n"
            return

        for event in engine.stream_reply(
            session_id=session_id,
            user_input=req.content,
            system_prompt=req.system_prompt,
            attachments=req.attachments,
        ):
            yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
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


@app.post("/api/sessions/{session_id}/context/pin")
def pin_context(session_id: str, req: ContextReq) -> dict[str, Any]:
    return ctx.add_pinned(session_id, req.content)


@app.post("/api/sessions/{session_id}/context/working")
def add_working_context(session_id: str, req: ContextReq) -> dict[str, Any]:
    return ctx.add_working(session_id, req.content)


@app.post("/api/sessions/{session_id}/context/checkpoint")
def create_checkpoint(session_id: str, req: CheckpointReq) -> dict[str, Any]:
    recent = store.list_messages(session_id, limit=200)
    return ctx.create_checkpoint(session_id, req.summary, recent)


@app.post("/api/sessions/{session_id}/resume")
def resume_checkpoint(session_id: str, req: ResumeReq) -> dict[str, Any]:
    try:
        checkpoint = ctx.restore_from_checkpoint(session_id, req.checkpoint_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return checkpoint


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


if WEBUI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(WEBUI_DIR), html=True), name="ui")


@app.get("/ui/index.html")
def index_file() -> FileResponse:
    return FileResponse(str(WEBUI_DIR / "index.html"))
