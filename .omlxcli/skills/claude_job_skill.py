"""Claude Code CLI 长任务（Job + 轮询）；仅 Web 会话内 run_skill 可用。"""

from __future__ import annotations

from typing import Any

from _meta import skill

from webapi.claude_job_runtime import get_claude_job_service
from webapi.claude_job_service import claude_code_unavailable_reason
from webapi.skill_context import get_skill_session_id, get_skill_workdir


def _require_context() -> tuple[str, str] | dict[str, Any]:
    sid = get_skill_session_id()
    wd = get_skill_workdir()
    if not sid or not wd:
        return {
            "ok": False,
            "error": "no_skill_context",
            "message": "claude_job_* 仅能在 Web 对话中通过 run_skill 调用（需要会话与工作目录上下文）。",
        }
    return (sid, wd)


@skill(
    desc="启动 Claude Code CLI 后台任务（headless `-p`）。默认 `context_mode=continue` 复用同会话历史；可设 isolated。",
    examples=[
        "claude_job_start('只读列出 src 下的 Python 文件，不要修改任何文件。')",
        "claude_job_start('继续上一轮分析并补充风险项', context_mode='continue')",
        "claude_job_start('为 tests 增加一条单测', max_turns=16, context_mode='isolated')",
    ],
)
def claude_job_start(
    prompt: str,
    max_turns: int | None = 32,
    context_mode: str = "continue",
) -> dict[str, Any]:
    ctx = _require_context()
    if isinstance(ctx, dict):
        return ctx
    sid, wd = ctx
    reason = claude_code_unavailable_reason()
    if reason:
        return {"ok": False, "error": "unavailable", "message": reason}
    mode = (context_mode or "continue").strip().lower()
    if mode not in ("continue", "isolated"):
        return {"ok": False, "error": "bad_context_mode", "message": "context_mode 仅支持 continue 或 isolated。"}
    svc = get_claude_job_service()
    ret = svc.start_job(
        session_id=sid,
        workdir=wd,
        prompt=prompt,
        max_turns=max_turns,
        context_mode=mode,
    )
    if not bool(ret.get("ok")):
        return ret
    job_id = str(ret.get("job_id") or "").strip()
    if not job_id:
        return {"ok": False, "error": "start_missing_job_id", "message": "任务启动返回缺少 job_id。"}
    try:
        # 防误导：启动成功后立即回读，确保任务确实落在当前会话与当前实例数据库中。
        _ = svc.get_job(sid, job_id)
    except KeyError:
        return {
            "ok": False,
            "error": "start_not_found_after_create",
            "message": "任务启动返回成功，但在当前会话中查询不到该 job。请确认会话未切换，或重启后重试。",
            "job_id": job_id,
        }
    except PermissionError as exc:
        return {
            "ok": False,
            "error": "start_job_session_mismatch",
            "message": f"任务启动后会话校验失败：{exc}",
            "job_id": job_id,
        }
    return ret


@skill(
    desc="查询 Claude Code 任务状态（running/completed/failed/cancelled）。",
    examples=["claude_job_status('abc123...')"],
)
def claude_job_status(job_id: str) -> dict[str, Any]:
    ctx = _require_context()
    if isinstance(ctx, dict):
        return ctx
    sid, _ = ctx
    reason = claude_code_unavailable_reason()
    if reason:
        return {"ok": False, "error": "unavailable", "message": reason}
    svc = get_claude_job_service()
    try:
        row = svc.get_job(sid, (job_id or "").strip())
    except KeyError:
        return {"ok": False, "error": "not_found", "message": "无此 job_id。"}
    except PermissionError as exc:
        return {"ok": False, "error": "forbidden", "message": str(exc)}
    return {"ok": True, **row}


@skill(
    desc="读取 Claude Code 任务日志尾部（UTF-8 文本）。",
    examples=["claude_job_logs('abc123...', tail_lines=120)"],
)
def claude_job_logs(job_id: str, tail_lines: int = 200) -> dict[str, Any]:
    ctx = _require_context()
    if isinstance(ctx, dict):
        return ctx
    sid, _ = ctx
    reason = claude_code_unavailable_reason()
    if reason:
        return {"ok": False, "error": "unavailable", "message": reason}
    svc = get_claude_job_service()
    try:
        text = svc.tail_logs(sid, (job_id or "").strip(), tail_lines=int(tail_lines))
    except KeyError:
        return {"ok": False, "error": "not_found", "message": "无此 job_id。"}
    except PermissionError as exc:
        return {"ok": False, "error": "forbidden", "message": str(exc)}
    return {"ok": True, "job_id": job_id.strip(), "tail_lines": int(tail_lines), "text": text}


@skill(
    desc="取消运行中的 Claude Code 任务（发送 SIGTERM 至进程组）。",
    examples=["claude_job_cancel('abc123...')"],
)
def claude_job_cancel(job_id: str) -> dict[str, Any]:
    ctx = _require_context()
    if isinstance(ctx, dict):
        return ctx
    sid, _ = ctx
    reason = claude_code_unavailable_reason()
    if reason:
        return {"ok": False, "error": "unavailable", "message": reason}
    svc = get_claude_job_service()
    try:
        return svc.cancel_job(sid, (job_id or "").strip())
    except KeyError:
        return {"ok": False, "error": "not_found", "message": "无此 job_id。"}
    except PermissionError as exc:
        return {"ok": False, "error": "forbidden", "message": str(exc)}
