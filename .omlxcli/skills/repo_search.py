"""仓库内文本搜索（ripgrep 优先）。"""

from __future__ import annotations

import os
import shutil
import subprocess
from _meta import skill


@skill(
    desc="在目录内用 ripgrep 搜索正则或关键词，返回匹配文件绝对路径列表（最多 max_matches 条）。",
    examples=[
        "repo_grep('def stream_reply', path='.')",
        "repo_grep('SessionStore', path='./webapi', max_matches=40)",
    ],
)
def repo_grep(pattern: str, path: str = ".", max_matches: int = 80) -> list[str]:
    if not (pattern or "").strip():
        raise ValueError("pattern 不能为空")
    max_matches = max(1, min(int(max_matches), 200))
    root = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(root):
        raise FileNotFoundError(f"目录不存在: {root}")

    rg = shutil.which("rg")
    if rg:
        try:
            proc = subprocess.run(
                [
                    rg,
                    "--files-with-matches",
                    "--no-messages",
                    "--max-count",
                    "1",
                    "-S",
                    "--",
                    pattern,
                    root,
                ],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            if proc.returncode not in (0, 1):
                raise RuntimeError(proc.stderr.strip()[:400] or f"rg exit {proc.returncode}")
            lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
            return lines[:max_matches]
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("rg 搜索超时（45s）") from exc

    # 无 rg 时退化：纯 Python 慢扫（仅小目录可用）
    out: list[str] = []
    for dirpath, _, files in os.walk(root):
        for fname in files:
            fp = os.path.join(dirpath, fname)
            if fname.startswith("."):
                continue
            try:
                with open(fp, "r", errors="ignore") as fh:
                    if pattern in fh.read(512 * 1024):
                        out.append(os.path.abspath(fp))
                        if len(out) >= max_matches:
                            return out
            except OSError:
                continue
    return out
