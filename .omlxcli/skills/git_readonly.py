"""Git 只读：diff / log / show（受限子进程，cwd 在仓库内）。"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from _meta import skill

_MAX_OUTPUT_CHARS = 400_000


def _safe_ref(ref: str) -> str:
    s = (ref or "").strip()
    if not s or len(s) > 240:
        raise ValueError("ref 无效或过长")
    if s.startswith("-") or "\n" in s or "\r" in s:
        raise ValueError("ref 包含非法字符")
    if ":" in s:
        raise ValueError("ref 包含非法字符")
    bad = set('`$;&|<>()#*?')
    if any(c in s for c in bad):
        raise ValueError("ref 包含非法字符")
    return s


def _safe_pathspec(spec: str) -> str:
    s = (spec or "").strip()
    if not s:
        return ""
    if "\n" in s or "\r" in s or ".." in s:
        raise ValueError("pathspec 非法")
    if s.startswith(("/", "-")):
        raise ValueError("pathspec 必须以相对仓库根的路径表示")
    bad = set('`$;&|<>#*?')
    if any(c in s for c in bad):
        raise ValueError("pathspec 包含非法字符")
    return s


def _git_repo_root(repo_path: str) -> str:
    root = os.path.abspath(os.path.expanduser(repo_path))
    if not os.path.isdir(root):
        raise NotADirectoryError(f"目录不存在: {root}")
    proc = subprocess.run(
        ["git", "-C", root, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"不是 git 仓库: {root}\n{proc.stderr.strip()[:400]}")
    return os.path.abspath(proc.stdout.strip())


def _run_git(repo: str, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        timeout=90,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        check=False,
    )
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"git 失败 (exit {proc.returncode}): {out.strip()[:800]}")
    if len(out) > _MAX_OUTPUT_CHARS:
        return out[:_MAX_OUTPUT_CHARS] + "\n…(输出已截断)"
    return out


@skill(
    desc="在本地仓库执行只读 git：action=log|diff|show；log 为 oneline，diff/show 可 --stat。",
    examples=[
        "git_snapshot('log', repo_path='.', limit=30)",
        "git_snapshot('diff', repo_path='.', stat_only=True, pathspec='webapi/app.py')",
        "git_snapshot('show', ref='HEAD', repo_path='.')",
    ],
)
def git_snapshot(
    action: str,
    repo_path: str = ".",
    limit: int = 50,
    ref: str = "HEAD",
    pathspec: str = "",
    stat_only: bool = True,
) -> dict[str, Any]:
    """action: log | diff | show。limit 用于 log 条数；diff 可与 pathspec 合用。"""
    act = (action or "").strip().lower()
    if act not in ("log", "diff", "show"):
        raise ValueError("action 必须是 log、diff 或 show")

    repo = _git_repo_root(repo_path)
    limit = max(1, min(int(limit), 500))
    ref_s = _safe_ref(ref)
    ps = _safe_pathspec(pathspec)

    if act == "log":
        out = _run_git(
            repo,
            [
                "log",
                f"-n{limit}",
                "--oneline",
                "--no-decorate",
                "--no-color",
            ],
        )
    elif act == "diff":
        cmd = ["diff", "--no-color"]
        if stat_only:
            cmd.append("--stat")
        if ps:
            cmd.extend(["--", ps])
        out = _run_git(repo, cmd)
    else:
        if stat_only:
            cmd = ["show", "--no-color", "--stat", ref_s]
        else:
            cmd = ["show", "--no-color", ref_s]
        out = _run_git(repo, cmd)

    return {
        "repo": repo,
        "action": act,
        "ref": ref_s if act == "show" else None,
        "pathspec": ps or None,
        "stat_only": bool(stat_only),
        "output": out,
    }
