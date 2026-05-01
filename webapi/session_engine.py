from __future__ import annotations

import os
import re
import subprocess
import time
import urllib.error
from dataclasses import dataclass
from typing import Any, Generator

from oi_runtime_core import auto_context_window, chat_completion_once, stream_chat_completions
from webapi.context_manager import ContextManager
from webapi.engine_protocol import (
    CONFIRM_EXEC_RE,
    FINAL_ANSWER_RE,
    RUN_SHELL_RE,
    RUN_SKILL_RE,
    chunk_text,
    extract_assistant_text,
    is_workdir_query,
    strip_model_leak_tokens,
)
from webapi.execution_policy import check_command_policy
from webapi.logging_utils import log_event
from webapi.session_store import SessionStore
from webapi.skill_runner import load_skills_registry, run_skill_call


@dataclass(slots=True)
class SessionRunConfig:
    model: str
    api_base: str
    api_key: str
    context_window: int
    temperature: float = 0.2
    max_tokens: int | None = None


_DEFAULT_AUTO_TITLES = frozenset({"新会话", "新建会话", "新对话"})


def _approx_tokens(text: str) -> int:
    """中英混排粗略 token 估计（无 tokenizer 时的展示用）。"""
    if not text:
        return 0
    return max(1, int(len(text) * 0.45))




class OiSessionEngine:
    def __init__(self, store: SessionStore, context_manager: ContextManager) -> None:
        self.store = store
        self.context_manager = context_manager

    @staticmethod
    def _effective_model(stored: str) -> str:
        """oMLX 不接受占位名 local；旧会话可能仍存 local，这里统一回落到环境或可用默认。"""
        m = (stored or "").strip()
        if m.lower() in ("local", "default", ""):
            return os.getenv("OI_MODEL", "Qwen3.5-35B-A3B-8bit")
        return m

    @staticmethod
    def default_config(model: str, api_base: str, api_key: str) -> SessionRunConfig:
        return SessionRunConfig(
            model=model,
            api_base=api_base.rstrip("/"),
            api_key=api_key,
            context_window=auto_context_window(),
            temperature=0.2,
            max_tokens=None,
        )

    def stream_reply(
        self,
        *,
        session_id: str,
        user_input: str,
        system_prompt: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> Generator[dict[str, Any], None, str]:
        session = self.store.get_session(session_id)
        resolved_model = self._effective_model(session.model)
        if resolved_model != session.model:
            self.store.update_session(session_id, model=resolved_model)
            session = self.store.get_session(session_id)
        config = self.default_config(
            model=resolved_model,
            api_base=session.api_base,
            api_key=os.getenv("OI_API_KEY", "not-needed"),
        )
        history = self.store.list_messages(session_id, limit=300)
        prompt_messages, prompt_debug = self.context_manager.build_prompt_messages_debug(
            session_id=session_id,
            system_prompt=system_prompt,
            recent_messages=history,
            user_input=user_input,
            attachments=attachments,
        )
        for row in prompt_debug:
            self.store.add_context_injection(
                session_id=session_id,
                source=str(row.get("source") or "unknown"),
                role=str(row.get("role") or "system"),
                char_count=int(row.get("char_count") or 0),
                dropped=bool(row.get("dropped") or False),
                reason=str(row.get("reason") or ""),
            )
        log_event(
            "context_injection_recorded",
            session_id=session_id,
            total_rows=len(prompt_debug),
            dropped_rows=sum(1 for r in prompt_debug if r.get("dropped")),
            input_chars=len(user_input or ""),
        )
        persisted_attachments = [
            {
                "name": str(a.get("name") or ""),
                "mime": str(a.get("mime") or ""),
                "size": int(a.get("size") or 0),
            }
            for a in (attachments or [])
        ]
        self.store.add_message(
            session_id=session_id,
            role="user",
            content=user_input,
            kind="user",
            attachments=persisted_attachments,
        )

        m_confirm = CONFIRM_EXEC_RE.match(user_input or "")
        if m_confirm and session.execution_enabled:
            cmd = m_confirm.group(2).strip()
            return (yield from self._confirm_and_run(
                session_id=session_id,
                session=session,
                cmd=cmd,
                user_input=user_input,
            ))

        # 强一致兜底：目录查询不走模型，直接读当前会话配置，避免旧历史上下文污染。
        if is_workdir_query(user_input):
            workdir = os.path.abspath(os.path.expanduser(session.workspace_path or "."))
            answer = (
                f"当前会话的默认工作目录是：`{workdir}`。\n\n"
                "若你未指定完整绝对路径，写笔记和文件会默认在此目录下进行。"
            )
            metrics: dict[str, Any] = {
                "ttft_ms": 0.0,
                "gen_duration_ms": 0.0,
                "tps": 0.0,
                "input_tokens_est": _approx_tokens(user_input),
                "output_tokens_est": _approx_tokens(answer),
                "total_tokens_est": _approx_tokens(user_input) + _approx_tokens(answer),
            }
            yield {"type": "delta", "content": answer}
            yield {"type": "metrics", **metrics}
            self.store.add_message(
                session_id=session_id,
                role="assistant",
                content=answer,
                kind="assistant",
                metrics=metrics,
            )
            self._maybe_auto_rename_session(session_id, user_input)
            return answer

        if session.execution_enabled:
            return (yield from self._stream_reply_with_execution(
                session_id=session_id,
                session=session,
                config=config,
                user_input=user_input,
                prompt_messages=prompt_messages,
            ))

        chunks: list[str] = []
        t0 = time.perf_counter()
        first_token_t: float | None = None
        try:
            stream = stream_chat_completions(
                api_base=config.api_base,
                api_key=config.api_key,
                model=config.model,
                messages=prompt_messages,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
            for obj in stream:
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {})
                piece = delta.get("content") or ""
                if not piece:
                    continue
                if first_token_t is None:
                    first_token_t = time.perf_counter()
                chunks.append(piece)
                yield {"type": "delta", "content": piece}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            msg = f"上游模型服务错误: HTTP {exc.code} {body[:300]}"
            self.store.add_message(session_id=session_id, role="assistant", content=msg, kind="error")
            yield {"type": "error", "content": msg}
            return msg
        except Exception as exc:  # noqa: BLE001
            msg = f"请求模型失败: {type(exc).__name__}: {exc}"
            self.store.add_message(session_id=session_id, role="assistant", content=msg, kind="error")
            yield {"type": "error", "content": msg}
            return msg

        answer = strip_model_leak_tokens("".join(chunks).strip())
        t_end = time.perf_counter()
        if first_token_t is None:
            first_token_t = t_end
        ttft_ms = round((first_token_t - t0) * 1000, 1)
        gen_s = max(t_end - first_token_t, 1e-6)
        input_tokens_est = _approx_tokens(
            "".join(str(m.get("content", "")) for m in prompt_messages)
        )
        output_tokens_est = _approx_tokens(answer) if answer else 0
        total_tokens_est = input_tokens_est + output_tokens_est
        tps = round(output_tokens_est / gen_s, 2) if output_tokens_est else 0.0
        metrics: dict[str, Any] = {
            "ttft_ms": ttft_ms,
            "gen_duration_ms": round(gen_s * 1000, 1),
            "tps": tps,
            "input_tokens_est": input_tokens_est,
            "output_tokens_est": output_tokens_est,
            "total_tokens_est": total_tokens_est,
        }
        yield {"type": "metrics", **metrics}
        self.store.add_message(
            session_id=session_id,
            role="assistant",
            content=answer,
            kind="assistant",
            metrics=metrics,
        )
        self._maybe_auto_rename_session(session_id, user_input)

        # 长会话自动摘要检查点
        all_messages = self.store.list_messages(session_id, limit=500)
        if len(all_messages) % 12 == 0:
            summary = self._build_quick_summary(all_messages[-12:])
            self.context_manager.create_checkpoint(
                session_id=session_id,
                summary=summary,
                recent_messages=all_messages,
            )
        return answer

    def _confirm_and_run(
        self,
        *,
        session_id: str,
        session: Any,
        cmd: str,
        user_input: str,
    ) -> Generator[dict[str, Any], None, str]:
        pending = (session.pending_command or "").strip()
        if pending and pending != cmd:
            msg = (
                f"待确认命令与当前输入不一致。\n"
                f"- 待确认: `{pending}`\n"
                f"- 当前输入: `{cmd}`\n"
                "请重新确认原命令，或先取消后再发起新命令。"
            )
            for piece in chunk_text(msg):
                yield {"type": "delta", "content": piece}
            return msg

        workdir = os.path.abspath(os.path.expanduser(session.workspace_path or "."))
        os.makedirs(workdir, exist_ok=True)
        ok, reason, need_confirm = check_command_policy(
            cmd=cmd,
            cwd=workdir,
            confirm_each=False,  # 用户显式确认后，放行风险确认但仍执行黑名单/沙箱检查
        )
        if not ok:
            msg = f"命令被安全策略阻止：{reason}\n\n命令：`{cmd}`"
            log_event("exec_blocked", session_id=session_id, exec_type="shell", command=cmd, reason=reason)
            self.store.add_execution(
                session_id=session_id,
                exec_type="shell",
                command=cmd,
                status="blocked",
                reason=reason,
            )
            for piece in chunk_text(msg):
                yield {"type": "delta", "content": piece}
            self.store.update_session(session_id, pending_command="")
            return msg
        if need_confirm:
            # 显式确认后不应再触发确认
            need_confirm = False

        yield {"type": "exec_step", "command": cmd, "status": "running"}
        result = self._run_shell_command(cmd=cmd, cwd=workdir, timeout_sec=90)
        log_event(
            "exec_finished",
            session_id=session_id,
            exec_type="shell",
            command=cmd,
            exit_code=result["exit_code"],
            duration_ms=result.get("duration_ms"),
        )
        self.store.add_execution(
            session_id=session_id,
            exec_type="shell",
            command=cmd,
            status="success" if int(result["exit_code"]) == 0 else "error",
            exit_code=int(result["exit_code"]),
            stdout=str(result["stdout"]),
            stderr=str(result["stderr"]),
            duration_ms=float(result.get("duration_ms") or 0.0),
            metadata={"source": "confirm"},
        )
        yield {"type": "exec_result", "command": cmd, **result}
        answer = (
            f"已执行命令：`{cmd}`\n\n"
            f"- exit_code: {result['exit_code']}\n"
            f"- stdout:\n```text\n{result['stdout'] or '(empty)'}\n```\n"
            f"- stderr:\n```text\n{result['stderr'] or '(empty)'}\n```"
        )
        metrics: dict[str, Any] = {
            "ttft_ms": 0.0,
            "gen_duration_ms": 0.0,
            "tps": 0.0,
            "input_tokens_est": _approx_tokens(user_input),
            "output_tokens_est": _approx_tokens(answer),
            "total_tokens_est": _approx_tokens(user_input) + _approx_tokens(answer),
        }
        for piece in chunk_text(answer):
            yield {"type": "delta", "content": piece}
        yield {"type": "metrics", **metrics}
        self.store.add_message(
            session_id=session_id,
            role="assistant",
            content=answer,
            kind="assistant",
            metrics=metrics,
        )
        self.store.update_session(session_id, pending_command="")
        return answer

    def run_confirmed_command(self, session_id: str, command: str) -> dict[str, Any]:
        session = self.store.get_session(session_id)
        cmd = (command or "").strip()
        pending = (session.pending_command or "").strip()
        if pending and pending != cmd:
            raise ValueError(f"待确认命令不匹配，待确认为: {pending}")
        workdir = os.path.abspath(os.path.expanduser(session.workspace_path or "."))
        os.makedirs(workdir, exist_ok=True)
        ok, reason, _ = check_command_policy(cmd=cmd, cwd=workdir, confirm_each=False)
        if not ok:
            self.store.update_session(session_id, pending_command="")
            log_event("exec_blocked", session_id=session_id, exec_type="shell", command=cmd, reason=reason)
            raise ValueError(reason)
        result = self._run_shell_command(cmd=cmd, cwd=workdir, timeout_sec=90)
        log_event(
            "exec_finished",
            session_id=session_id,
            exec_type="shell",
            command=cmd,
            exit_code=result["exit_code"],
            duration_ms=result.get("duration_ms"),
        )
        self.store.add_execution(
            session_id=session_id,
            exec_type="shell",
            command=cmd,
            status="success" if int(result["exit_code"]) == 0 else "error",
            exit_code=int(result["exit_code"]),
            stdout=str(result["stdout"]),
            stderr=str(result["stderr"]),
            duration_ms=float(result.get("duration_ms") or 0.0),
            metadata={"source": "confirm_api"},
        )
        answer = (
            f"已执行命令：`{cmd}`\n\n"
            f"- exit_code: {result['exit_code']}\n"
            f"- stdout:\n```text\n{result['stdout'] or '(empty)'}\n```\n"
            f"- stderr:\n```text\n{result['stderr'] or '(empty)'}\n```"
        )
        metrics: dict[str, Any] = {
            "ttft_ms": 0.0,
            "gen_duration_ms": 0.0,
            "tps": 0.0,
            "input_tokens_est": _approx_tokens(cmd),
            "output_tokens_est": _approx_tokens(answer),
            "total_tokens_est": _approx_tokens(cmd) + _approx_tokens(answer),
        }
        self.store.add_message(
            session_id=session_id,
            role="assistant",
            content=answer,
            kind="assistant",
            metrics=metrics,
        )
        self.store.update_session(session_id, pending_command="")
        return {
            "command": cmd,
            "exit_code": result["exit_code"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "answer": answer,
            "metrics": metrics,
        }

    def _stream_reply_with_execution(
        self,
        *,
        session_id: str,
        session: Any,
        config: SessionRunConfig,
        user_input: str,
        prompt_messages: list[dict[str, Any]],
    ) -> Generator[dict[str, Any], None, str]:
        t0 = time.perf_counter()
        workdir = os.path.abspath(os.path.expanduser(session.workspace_path or "."))
        os.makedirs(workdir, exist_ok=True)
        skill_funcs, skills_md = load_skills_registry()
        skill_enabled = bool(skill_funcs)

        control_prompt = (
            "你是可执行本地 CLI 的助手。你必须遵守如下输出协议：\n"
            "1) 需要执行命令时，严格只输出：<run_shell>命令</run_shell>。\n"
            "2) 需要调用本地技能函数时，严格只输出：<run_skill>函数调用表达式</run_skill>。\n"
            "3) 不需要继续执行时，输出：<final_answer>中文答复</final_answer>。\n"
            "4) 一次只允许一个 run_shell 或一个 run_skill。\n"
            "5) 不要伪造执行结果；必须等待系统回传输出。\n"
            f"6) 当前工作目录固定为：{workdir}\n"
            + (
                "7) 已加载本地 skills，可优先使用 run_skill 调用。\n"
                if skill_enabled
                else "7) 当前未加载到本地 skills，仅可使用 run_shell。\n"
            )
        )
        convo = list(prompt_messages) + [{"role": "system", "content": control_prompt}]
        if skills_md:
            convo.append({"role": "system", "content": skills_md})
        first_token_t: float | None = None
        # 复杂任务（如定位文件后继续读取/分析）通常需要更多轮次
        max_rounds = 8
        final_answer = ""
        executed_any = False

        for _ in range(max_rounds):
            try:
                obj = chat_completion_once(
                    api_base=config.api_base,
                    api_key=config.api_key,
                    model=config.model,
                    messages=convo,
                    temperature=0.1,
                    max_tokens=config.max_tokens,
                )
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")
                final_answer = f"上游模型服务错误: HTTP {exc.code} {body[:300]}"
                break
            except Exception as exc:  # noqa: BLE001
                final_answer = f"请求模型失败: {type(exc).__name__}: {exc}"
                break
            if first_token_t is None:
                first_token_t = time.perf_counter()
            assistant_text = strip_model_leak_tokens(extract_assistant_text(obj).strip())
            if not assistant_text:
                continue

            m_final = FINAL_ANSWER_RE.search(assistant_text)
            if m_final:
                final_answer = m_final.group(1).strip()
                break

            m_skill = RUN_SKILL_RE.search(assistant_text)
            if m_skill:
                skill_expr = m_skill.group(1).strip()
                if not skill_expr:
                    final_answer = "技能调用为空，未执行。"
                    break
                yield {"type": "exec_step", "command": f"skill: {skill_expr}", "status": "running"}
                skill_ret = run_skill_call(skill_expr, skill_funcs)
                log_event(
                    "exec_finished",
                    session_id=session_id,
                    exec_type="skill",
                    command=skill_expr,
                    exit_code=skill_ret["exit_code"],
                )
                self.store.add_execution(
                    session_id=session_id,
                    exec_type="skill",
                    command=skill_expr,
                    status="success" if int(skill_ret["exit_code"]) == 0 else "error",
                    exit_code=int(skill_ret["exit_code"]),
                    stdout=str(skill_ret["stdout"]),
                    stderr=str(skill_ret["stderr"]),
                )
                yield {
                    "type": "exec_result",
                    "command": f"skill: {skill_expr}",
                    "exit_code": skill_ret["exit_code"],
                    "stdout": skill_ret["stdout"],
                    "stderr": skill_ret["stderr"],
                }
                executed_any = True
                convo.append({"role": "assistant", "content": f"<run_skill>{skill_expr}</run_skill>"})
                convo.append(
                    {
                        "role": "system",
                        "content": (
                            f"[技能调用结果]\n> {skill_expr}\n"
                            f"exit_code: {skill_ret['exit_code']}\n"
                            f"stdout:\n{skill_ret['stdout']}\n\nstderr:\n{skill_ret['stderr']}\n"
                            "请基于真实输出继续决策：如已完成，则输出 <final_answer>...</final_answer>；"
                            "若需下一步，再输出一个 <run_shell>...</run_shell> 或 <run_skill>...</run_skill>。"
                        ),
                    }
                )
                continue

            m_run = RUN_SHELL_RE.search(assistant_text)
            if not m_run:
                final_answer = assistant_text
                break

            cmd = m_run.group(1).strip()
            if not cmd:
                final_answer = "命令为空，未执行。"
                break
            ok, reason, need_confirm = check_command_policy(
                cmd=cmd,
                cwd=workdir,
                confirm_each=session.confirm_each,
            )
            if not ok:
                final_answer = f"命令被安全策略阻止：{reason}\n\n命令：`{cmd}`"
                log_event("exec_blocked", session_id=session_id, exec_type="shell", command=cmd, reason=reason)
                self.store.add_execution(
                    session_id=session_id,
                    exec_type="shell",
                    command=cmd,
                    status="blocked",
                    reason=reason,
                )
                self.store.update_session(session_id, pending_command="")
                break
            if need_confirm:
                self.store.update_session(session_id, pending_command=cmd)
                log_event("exec_need_confirm", session_id=session_id, exec_type="shell", command=cmd, reason=reason)
                self.store.add_execution(
                    session_id=session_id,
                    exec_type="shell",
                    command=cmd,
                    status="need_confirm",
                    reason=reason,
                )
                yield {
                    "type": "require_confirm",
                    "command": cmd,
                    "reason": reason,
                }
                final_answer = (
                    "该命令需要确认后才能执行。\n"
                    f"- 原因：{reason}\n"
                    f"- 命令：`{cmd}`\n"
                    "请点击确认弹窗，或发送：`确认执行: <命令>`。"
                )
                break
            self.store.update_session(session_id, pending_command="")
            yield {"type": "exec_step", "command": cmd, "status": "running"}
            exec_result = self._run_shell_command(cmd=cmd, cwd=workdir, timeout_sec=90)
            log_event(
                "exec_finished",
                session_id=session_id,
                exec_type="shell",
                command=cmd,
                exit_code=exec_result["exit_code"],
                duration_ms=exec_result.get("duration_ms"),
            )
            self.store.add_execution(
                session_id=session_id,
                exec_type="shell",
                command=cmd,
                status="success" if int(exec_result["exit_code"]) == 0 else "error",
                exit_code=int(exec_result["exit_code"]),
                stdout=str(exec_result["stdout"]),
                stderr=str(exec_result["stderr"]),
                duration_ms=float(exec_result.get("duration_ms") or 0.0),
                metadata={"source": "auto_exec_loop"},
            )
            yield {"type": "exec_result", "command": cmd, **exec_result}
            executed_any = True
            convo.append({"role": "assistant", "content": f"<run_shell>{cmd}</run_shell>"})
            convo.append(
                {
                    "role": "system",
                    "content": (
                        f"[命令执行结果]\n$ {cmd}\n"
                        f"exit_code: {exec_result['exit_code']}\n"
                        f"stdout:\n{exec_result['stdout']}\n\nstderr:\n{exec_result['stderr']}\n"
                        "请基于真实输出继续决策：如已完成，则输出 <final_answer>...</final_answer>；"
                        "若需下一步，再输出一个 <run_shell>...</run_shell>。"
                    ),
                }
            )

        if not final_answer and executed_any:
            # 若多轮执行后仍未显式给出 <final_answer>，强制一次“只允许总结”的收敛回合，
            # 避免用户反复输入“继续”。
            try:
                finalize_obj = chat_completion_once(
                    api_base=config.api_base,
                    api_key=config.api_key,
                    model=config.model,
                    messages=convo
                    + [
                        {
                            "role": "system",
                            "content": (
                                "你已经拿到命令执行结果。现在禁止再输出 <run_shell>。"
                                "请直接基于现有结果给出最终中文答复，并使用 "
                                "<final_answer>...</final_answer> 包裹。"
                            ),
                        }
                    ],
                    temperature=0.0,
                    max_tokens=config.max_tokens,
                )
                finalize_text = strip_model_leak_tokens(extract_assistant_text(finalize_obj).strip())
                m_final = FINAL_ANSWER_RE.search(finalize_text)
                if m_final and m_final.group(1).strip():
                    final_answer = m_final.group(1).strip()
                elif finalize_text:
                    final_answer = re.sub(r"</?run_shell>", "", finalize_text, flags=re.IGNORECASE)
                    final_answer = re.sub(r"</?run_skill>", "", final_answer, flags=re.IGNORECASE).strip()
            except Exception:  # noqa: BLE001
                # 保底走通，不让一次收敛失败破坏主流程
                pass

        if not final_answer:
            if executed_any:
                final_answer = "命令已执行，但未能自动收敛出最终结论。请补充你希望我继续的方向（例如：读取文件、提取要点、给出风险清单）。"
            else:
                final_answer = "未能得到有效结果，请重试。"

        for piece in chunk_text(final_answer):
            yield {"type": "delta", "content": piece}

        t_end = time.perf_counter()
        if first_token_t is None:
            first_token_t = t_end
        ttft_ms = round((first_token_t - t0) * 1000, 1)
        gen_s = max(t_end - first_token_t, 1e-6)
        input_tokens_est = _approx_tokens("".join(str(m.get("content", "")) for m in prompt_messages))
        output_tokens_est = _approx_tokens(final_answer)
        metrics: dict[str, Any] = {
            "ttft_ms": ttft_ms,
            "gen_duration_ms": round(gen_s * 1000, 1),
            "tps": round(output_tokens_est / gen_s, 2) if output_tokens_est else 0.0,
            "input_tokens_est": input_tokens_est,
            "output_tokens_est": output_tokens_est,
            "total_tokens_est": input_tokens_est + output_tokens_est,
        }
        yield {"type": "metrics", **metrics}
        self.store.add_message(
            session_id=session_id,
            role="assistant",
            content=final_answer,
            kind="assistant",
            metrics=metrics,
        )
        self._maybe_auto_rename_session(session_id, user_input)
        return final_answer

    @staticmethod
    def _run_shell_command(cmd: str, cwd: str, timeout_sec: int = 90) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                ["/bin/zsh", "-lc", cmd],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            stdout = (proc.stdout or "").strip()[:12000]
            stderr = (proc.stderr or "").strip()[:12000]
            return {
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": 124,
                "stdout": "",
                "stderr": "命令执行超时。",
                "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": f"执行失败: {exc}",
                "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            }

    @staticmethod
    def _title_from_user_text(text: str, max_len: int = 40) -> str | None:
        raw = " ".join((text or "").split())
        if len(raw) < 2:
            return None
        if raw.lstrip().startswith("%"):
            return None
        t = raw.strip()[:max_len].rstrip()
        return t or None

    def _maybe_auto_rename_session(self, session_id: str, user_input: str) -> None:
        """首轮对话成功后，若标题仍为默认且未锁定，则用首条用户消息生成标题。"""
        session = self.store.get_session(session_id)
        if session.title_locked:
            return
        if session.title.strip() not in _DEFAULT_AUTO_TITLES:
            return
        all_messages = self.store.list_messages(session_id, limit=80)
        n_user = sum(1 for m in all_messages if m.get("role") == "user")
        if n_user != 1:
            return
        new_title = self._title_from_user_text(user_input)
        if new_title:
            self.store.update_session(session_id, title=new_title)

    @staticmethod
    def _build_quick_summary(messages: list[dict[str, Any]]) -> str:
        user_text = [m["content"][:120] for m in messages if m["role"] == "user"][-3:]
        assistant_text = [m["content"][:120] for m in messages if m["role"] == "assistant"][-3:]
        return (
            "最近会话摘要："
            f"用户关注点={ ' | '.join(user_text) if user_text else '无'}；"
            f"助手输出={ ' | '.join(assistant_text) if assistant_text else '无'}"
        )
