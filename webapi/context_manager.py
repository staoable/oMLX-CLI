# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from webapi.session_store import SessionStore


@dataclass(slots=True)
class ContextBundle:
    pinned: list[str]
    working: list[str]
    archived: list[str]


class ContextManager:
    def __init__(self, store: SessionStore) -> None:
        self.store = store

    def add_pinned(self, session_id: str, content: str, *, priority: int = 0) -> dict[str, Any]:
        return self.store.add_context(
            session_id=session_id, layer="pinned", content=content, priority=priority
        )

    def add_working(self, session_id: str, content: str, *, priority: int = 0) -> dict[str, Any]:
        return self.store.add_context(
            session_id=session_id, layer="working", content=content, priority=priority
        )

    def add_archived(self, session_id: str, content: str, *, priority: int = 0) -> dict[str, Any]:
        return self.store.add_context(
            session_id=session_id, layer="archived", content=content, priority=priority
        )

    def build_bundle(self, session_id: str, working_limit: int = 8, archived_limit: int = 5) -> ContextBundle:
        pinned_rows = self.store.list_contexts(session_id, layer="pinned")
        working_rows = self.store.list_contexts(session_id, layer="working")
        archived_rows = self.store.list_contexts(session_id, layer="archived")
        return ContextBundle(
            pinned=[r["content"] for r in pinned_rows],
            working=[r["content"] for r in working_rows[:working_limit]],
            archived=[r["content"] for r in archived_rows[:archived_limit]],
        )

    def build_prompt_messages(
        self,
        *,
        session_id: str,
        system_prompt: str,
        recent_messages: list[dict[str, Any]],
        user_input: str,
        attachments: list[dict[str, Any]] | None = None,
        token_budget_chars: int = 24000,
    ) -> list[dict[str, Any]]:
        messages, _debug = self.build_prompt_messages_debug(
            session_id=session_id,
            system_prompt=system_prompt,
            recent_messages=recent_messages,
            user_input=user_input,
            attachments=attachments,
            token_budget_chars=token_budget_chars,
        )
        return messages

    def build_prompt_messages_debug(
        self,
        *,
        session_id: str,
        system_prompt: str,
        recent_messages: list[dict[str, Any]],
        user_input: str,
        attachments: list[dict[str, Any]] | None = None,
        token_budget_chars: int = 24000,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        bundle = self.build_bundle(session_id)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        debug_rows: list[dict[str, Any]] = [
            {
                "source": "system_prompt",
                "role": "system",
                "char_count": len(system_prompt),
                "dropped": False,
                "reason": "",
            }
        ]

        try:
            sess = self.store.get_session(session_id)
            wp = (sess.workspace_path or "").strip()
        except KeyError:
            wp = ""
        abs_wp = os.path.abspath(os.path.expanduser(wp)) if wp else ""
        abs_path_re = re.compile(r"/Users/[^\s`\"'<>]+")

        def _normalize_history_paths(role: str, content: str) -> str:
            if not abs_wp or role not in ("assistant", "system"):
                return content
            if "/Users/" not in content:
                return content

            def _repl(m: re.Match[str]) -> str:
                p = m.group(0)
                if p.startswith(abs_wp):
                    return p
                base = os.path.basename(p.rstrip("/"))
                # 文件路径保留文件名，目录路径直接替换为当前目录
                if "." in base:
                    return f"{abs_wp}/{base}"
                return abs_wp

            return abs_path_re.sub(_repl, content)

        def _push_context(title: str, chunks: list[str]) -> None:
            if not chunks:
                return
            merged = "\n\n".join(f"- {x}" for x in chunks)
            content = f"[{title}]\n{merged}"
            messages.append({"role": "system", "content": content})
            debug_rows.append(
                {
                    "source": title,
                    "role": "system",
                    "char_count": len(content),
                    "dropped": False,
                    "reason": "",
                }
            )

        _push_context("PinnedContext", bundle.pinned)
        _push_context("WorkingContext", bundle.working)
        _push_context("ArchivedContext", bundle.archived)

        history = recent_messages[-20:]
        for m in history:
            if m["role"] not in ("user", "assistant", "system"):
                continue
            c = m["content"]
            if isinstance(c, str):
                c = _normalize_history_paths(m["role"], c)
            messages.append({"role": m["role"], "content": c})
            debug_rows.append(
                {
                    "source": "history",
                    "role": m["role"],
                    "char_count": len(c) if isinstance(c, str) else len(str(c)),
                    "dropped": False,
                    "reason": "",
                }
            )

        user_content_parts: list[dict[str, Any]] = []
        if user_input.strip():
            user_content_parts.append({"type": "text", "text": user_input})
        for att in attachments or []:
            data_url = str(att.get("data_url") or "")
            mime = str(att.get("mime") or "").lower()
            if not data_url:
                continue
            if mime.startswith("image/"):
                user_content_parts.append(
                    {"type": "image_url", "image_url": {"url": data_url}}
                )
            elif mime.startswith("audio/"):
                # OpenAI 兼容多模态音频：部分服务实现 input_audio content part。
                audio_data = data_url.split(",", 1)[1] if "," in data_url else data_url
                user_content_parts.append(
                    {"type": "input_audio", "input_audio": {"data": audio_data, "format": mime}}
                )
            elif mime.startswith("video/"):
                # video 在 OpenAI 兼容实现中并不统一，先透传为 input_video（若后端支持可直接消费）。
                video_data = data_url.split(",", 1)[1] if "," in data_url else data_url
                user_content_parts.append(
                    {"type": "input_video", "input_video": {"data": video_data, "format": mime}}
                )
            else:
                user_content_parts.append(
                    {
                        "type": "text",
                        "text": f"[附件] {att.get('name', 'unknown')} ({mime or 'application/octet-stream'})",
                    }
                )
        if abs_wp:
            # 放在历史消息之后、用户消息之前，确保旧历史中的目录信息不会覆盖当前设置。
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "## 当前会话工作目录（最终权威）\n"
                        f"当前默认工作目录绝对路径：`{abs_wp}`。\n"
                        "若历史对话里出现其它目录，均视为过期信息，应忽略。\n"
                        "当用户要求写笔记、保存文件、导出内容，或未提供完整绝对路径时，"
                        "默认使用该目录（相对路径均相对该目录）。\n"
                        "若用户明确给出其它绝对路径，则按用户路径执行。"
                    ),
                }
            )
            debug_rows.append(
                {
                    "source": "workspace_guard",
                    "role": "system",
                    "char_count": len(messages[-1]["content"]),
                    "dropped": False,
                    "reason": "",
                }
            )

        if user_content_parts:
            messages.append({"role": "user", "content": user_content_parts})
            debug_rows.append(
                {
                    "source": "current_user",
                    "role": "user",
                    "char_count": len(user_input) + sum(
                        len(str(p.get("text", ""))) for p in user_content_parts if isinstance(p, dict)
                    ),
                    "dropped": False,
                    "reason": "",
                }
            )
        else:
            messages.append({"role": "user", "content": user_input})
            debug_rows.append(
                {
                    "source": "current_user",
                    "role": "user",
                    "char_count": len(user_input),
                    "dropped": False,
                    "reason": "",
                }
            )
        trimmed = self._trim_to_budget(messages, token_budget_chars)
        if len(trimmed) < len(messages):
            dropped = len(messages) - len(trimmed)
            debug_rows.append(
                {
                    "source": "budget_trim",
                    "role": "system",
                    "char_count": 0,
                    "dropped": True,
                    "reason": f"trimmed_messages={dropped}",
                }
            )
        return trimmed, debug_rows

    def create_checkpoint(self, session_id: str, summary: str, recent_messages: list[dict[str, Any]]) -> dict[str, Any]:
        bundle = self.build_bundle(session_id)
        payload = {
            "summary": summary,
            "pinned": bundle.pinned,
            "working": bundle.working,
            "archived": bundle.archived,
            "recent_messages": recent_messages[-12:],
        }
        self.add_archived(session_id, summary)
        self.store.update_session(session_id, summary=summary)
        return self.store.add_checkpoint(session_id=session_id, summary=summary, payload=payload)

    def restore_from_checkpoint(
        self,
        session_id: str,
        checkpoint_id: str,
        *,
        mode: str = "append",
    ) -> dict[str, Any]:
        checkpoints = self.store.list_checkpoints(session_id, limit=50)
        target = next((c for c in checkpoints if c["id"] == checkpoint_id), None)
        if target is None:
            raise KeyError(f"checkpoint not found: {checkpoint_id}")
        payload = target["payload"]
        m = (mode or "append").strip().lower()
        if m == "replace":
            self.store.delete_contexts_by_layer(session_id, "working")
        elif m != "append":
            raise ValueError("mode 必须是 append 或 replace")
        for line in payload.get("working", []):
            self.add_working(session_id, line)
        return target

    @staticmethod
    def measure_messages_chars(messages: list[dict[str, Any]]) -> int:
        def _content_len(c: Any) -> int:
            if isinstance(c, str):
                return len(c)
            if isinstance(c, list):
                n = 0
                for part in c:
                    if isinstance(part, dict):
                        if isinstance(part.get("text"), str):
                            n += len(part["text"])
                        if isinstance(part.get("data"), str):
                            n += min(len(part["data"]), 512)
                        iu = part.get("image_url")
                        if isinstance(iu, dict) and isinstance(iu.get("url"), str):
                            n += min(len(iu["url"]), 512)
                return n
            return len(str(c))

        return sum(_content_len(m.get("content")) for m in messages)

    @staticmethod
    def _trim_to_budget(messages: list[dict[str, Any]], budget_chars: int) -> list[dict[str, Any]]:
        def _content_len(c: Any) -> int:
            if isinstance(c, str):
                return len(c)
            if isinstance(c, list):
                n = 0
                for part in c:
                    if isinstance(part, dict):
                        if isinstance(part.get("text"), str):
                            n += len(part["text"])
                        if isinstance(part.get("data"), str):
                            n += min(len(part["data"]), 512)
                        iu = part.get("image_url")
                        if isinstance(iu, dict) and isinstance(iu.get("url"), str):
                            n += min(len(iu["url"]), 512)
                return n
            return len(str(c))

        total = sum(_content_len(m["content"]) for m in messages)
        if total <= budget_chars:
            return messages
        keep: list[dict[str, Any]] = []
        consumed = 0
        for m in reversed(messages):
            size = _content_len(m["content"])
            if consumed + size > budget_chars and m["role"] != "system":
                continue
            keep.append(m)
            consumed += size
        return list(reversed(keep))
