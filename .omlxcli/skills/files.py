"""文件检索工具。

依赖优先级：
  - 内容搜索：ripgrep (rg) → 纯 Python os.walk
  - 文件名搜索：fd → fnmatch + os.walk

返回值统一为绝对路径列表，方便模型继续传给其它工具。
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess

from _meta import skill


@skill(
    desc="按内容/文件名搜索文件，返回绝对路径列表。",
    examples=[
        "files_search('TODO', path='.', kind='content')",
        "files_search('*.py', path='./scripts', kind='name')",
    ],
)
def files_search(
    query: str,
    path: str = ".",
    kind: str = "content",
    max_results: int = 100,
) -> list[str]:
    """搜索文件。kind='content' 搜文本内容；kind='name' 搜文件名（支持 glob）。"""
    if not query:
        return []
    if kind not in ("content", "name"):
        raise ValueError("kind 必须是 'content' 或 'name'")

    abs_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(abs_path):
        raise FileNotFoundError(f"目录不存在: {abs_path}")

    results: list[str] = []

    if kind == "content":
        rg = shutil.which("rg")
        if rg:
            try:
                proc = subprocess.run(
                    [
                        rg,
                        "--files-with-matches",
                        "--hidden",
                        "--no-messages",
                        "-uu",
                        "--max-count",
                        "1",
                        query,
                        abs_path,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                results = [ln for ln in proc.stdout.splitlines() if ln.strip()]
            except Exception:  # noqa: BLE001
                results = []
        if not results:
            for root, _dirs, files in os.walk(abs_path):
                for fname in files:
                    fp = os.path.join(root, fname)
                    try:
                        with open(fp, "r", errors="ignore") as fh:
                            if query in fh.read(1024 * 1024):
                                results.append(fp)
                                if len(results) >= max_results:
                                    return results
                    except Exception:  # noqa: BLE001
                        continue
    else:
        fd = shutil.which("fd") or shutil.which("fdfind")
        if fd:
            try:
                proc = subprocess.run(
                    [fd, "--hidden", "--no-ignore", "--glob", query, abs_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                results = [ln for ln in proc.stdout.splitlines() if ln.strip()]
            except Exception:  # noqa: BLE001
                results = []
        if not results:
            for root, _dirs, files in os.walk(abs_path):
                for fname in files:
                    if fnmatch.fnmatch(fname, query) or query in fname:
                        results.append(os.path.join(root, fname))
                        if len(results) >= max_results:
                            return results

    return results[:max_results]


@skill(
    desc="读取文件分块内容，便于处理大文件。返回字典 {path, total_lines, lines, content}。",
    examples=["files_read_chunk('./load.py', start=0, lines=200)"],
)
def files_read_chunk(path: str, start: int = 0, lines: int = 200) -> dict:
    """从 start 行开始读 lines 行（0 索引）。文件不存在时抛 FileNotFoundError。"""
    abs_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"文件不存在: {abs_path}")

    start = max(0, int(start))
    lines = max(1, int(lines))

    with open(abs_path, "r", errors="replace") as fh:
        all_lines = fh.readlines()
    total = len(all_lines)
    end = min(total, start + lines)
    chunk = all_lines[start:end]

    return {
        "path": abs_path,
        "total_lines": total,
        "start": start,
        "end": end,
        "content": "".join(chunk),
    }
