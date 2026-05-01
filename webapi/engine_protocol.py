from __future__ import annotations

import re
from typing import Any

WORKDIR_QUERY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(当前|默认).{0,6}(工作目录|目录|路径)"),
    re.compile(r"(工作目录|workspace|workdir).{0,6}(是|为|在哪|是什么|多少|路径)"),
    re.compile(r"(where|what).{0,12}(work(ing)?\s*dir|workspace)", re.IGNORECASE),
)
CONFIRM_EXEC_RE = re.compile(r"^\s*(确认执行|confirm)\s*[:：]\s*(.+)$", re.IGNORECASE)
RUN_SHELL_RE = re.compile(r"<run_shell>([\s\S]*?)</run_shell>", re.IGNORECASE)
RUN_SKILL_RE = re.compile(r"<run_skill>([\s\S]*?)</run_skill>", re.IGNORECASE)
FINAL_ANSWER_RE = re.compile(r"<final_answer>([\s\S]*?)</final_answer>", re.IGNORECASE)

LEAK_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<\|redacted_im_end\|>\s*", re.IGNORECASE),
    re.compile(r"<\|im_end\|>\s*", re.IGNORECASE),
    re.compile(r"<\|endoftext\|>\s*", re.IGNORECASE),
)


def strip_model_leak_tokens(text: str) -> str:
    s = text or ""
    for _ in range(8):
        prev = s
        for pat in LEAK_TOKEN_PATTERNS:
            s = pat.sub("", s)
        s = s.rstrip()
        if s == prev:
            break
    return s


def is_workdir_query(text: str) -> bool:
    s = " ".join((text or "").split())
    if not s:
        return False
    return any(p.search(s) for p in WORKDIR_QUERY_PATTERNS)


def extract_assistant_text(obj: dict[str, Any]) -> str:
    choices = obj.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for p in content:
            if isinstance(p, dict) and isinstance(p.get("text"), str):
                out.append(p["text"])
        return "\n".join(out)
    return ""


def chunk_text(text: str, size: int = 120) -> list[str]:
    if not text:
        return [""]
    return [text[i : i + size] for i in range(0, len(text), size)]
