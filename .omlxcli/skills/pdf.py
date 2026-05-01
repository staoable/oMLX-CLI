"""PDF 阅读与解析（含 OCR）。

# 推荐用法（按优先级排序）

  pdf_read(path)              一站式读 PDF。**默认入口**：
                              · 有文字层 → 直接提取
                              · 没文字层（扫描件）→ 自动 macOS Vision OCR
                              · 混合文档 → 逐页判断

  pdf_ocr(path)               强制 OCR（已知是扫描件时直接用）

  pdf_to_text(path)           纯文字层提取，禁用 OCR（明确知道有文字层时用）

  pdf_meta(path)              元信息：页数、标题、作者…

  pdf_search(path, query)     全文搜索关键词，返回页号 + 上下文

# 关于 OCR 后端

  优先 macOS Vision（通过本目录下的 `_ocr_macos.swift`）—— Apple 官方模型，
  对中英文混排质量优秀，**零依赖**（只需要 Xcode CLT）。

  Vision 不可用（非 macOS）时回退 tesseract（需 `brew install tesseract tesseract-lang`）。

# 关于 `pages` 参数（所有函数一致；1-indexed）

  None        → 全部
  3           → 第 3 页
  (1, 5)      → 第 1 到第 5 页（含两端）
  [1, 3, 7]   → 仅这三页
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from glob import glob
from typing import Iterable, List, Optional, Union

from _meta import skill

PageSpec = Union[None, int, tuple, list]

_HERE = os.path.dirname(os.path.abspath(__file__))
_OCR_SWIFT_SCRIPT = os.path.join(_HERE, "_ocr_macos.swift")


# ------------------------------- 通用工具 ------------------------------- #


def _resolve_path(path: str) -> str:
    abs_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"PDF 不存在: {abs_path}")
    return abs_path


def _normalize_pages(pages: PageSpec, total: int) -> List[int]:
    """统一返回 0-indexed 升序无重的页号列表。"""
    if pages is None:
        return list(range(total))
    if isinstance(pages, int):
        idx = pages - 1
        return [idx] if 0 <= idx < total else []
    if isinstance(pages, tuple):
        if len(pages) != 2:
            raise ValueError("tuple 形式 pages 必须是 (start, end)，1-indexed")
        start, end = int(pages[0]) - 1, int(pages[1]) - 1
        if start > end:
            start, end = end, start
        return [i for i in range(start, end + 1) if 0 <= i < total]
    if isinstance(pages, (list, set)):
        seen = sorted({int(p) - 1 for p in pages if isinstance(p, int)})
        return [i for i in seen if 0 <= i < total]
    raise ValueError(f"不支持的 pages 参数类型: {type(pages).__name__}")


def _open_fitz(abs_path: str):
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None
    try:
        return fitz.open(abs_path)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"PyMuPDF 打开 PDF 失败: {type(exc).__name__}: {exc}") from exc


# ------------------------------- OCR 后端 ------------------------------- #


def _ocr_image_macos(image_path: str, langs: Optional[List[str]] = None, timeout: int = 120) -> str:
    """调 _ocr_macos.swift，对 PNG/JPG 做 OCR，返回拼接好的文本。"""
    swift = shutil.which("swift") or "/usr/bin/swift"
    if not os.path.exists(swift):
        raise RuntimeError("未找到 swift 命令；macOS Vision OCR 需要 Xcode Command Line Tools。")
    if not os.path.isfile(_OCR_SWIFT_SCRIPT):
        raise RuntimeError(f"OCR 脚本不存在: {_OCR_SWIFT_SCRIPT}")
    cmd = [swift, _OCR_SWIFT_SCRIPT, image_path]
    if langs:
        cmd += list(langs)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"swift Vision OCR 失败 (rc={proc.returncode}): {proc.stderr.strip()[:300]}"
        )
    return proc.stdout


def _ocr_image_tesseract(image_path: str, langs: Optional[List[str]] = None, timeout: int = 120) -> str:
    """tesseract 回退路径。langs 例：['chi_sim', 'eng']。"""
    tess = shutil.which("tesseract")
    if not tess:
        raise RuntimeError(
            "未找到 tesseract。可执行: brew install tesseract tesseract-lang"
        )
    lang_arg = "+".join(langs) if langs else "chi_sim+eng"
    cmd = [tess, image_path, "stdout", "-l", lang_arg]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"tesseract OCR 失败 (rc={proc.returncode}): {proc.stderr.strip()[:300]}"
        )
    return proc.stdout


def _ocr_image(image_path: str, langs: Optional[List[str]] = None) -> str:
    """统一入口：优先 macOS Vision，回退 tesseract。"""
    import platform

    errors = []
    if platform.system() == "Darwin":
        try:
            return _ocr_image_macos(image_path, langs=langs)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"macOS Vision: {type(exc).__name__}: {exc}")
    try:
        return _ocr_image_tesseract(image_path, langs=langs)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"tesseract: {type(exc).__name__}: {exc}")
    raise RuntimeError("所有 OCR 后端都失败：\n" + "\n".join(errors))


def _render_page_to_png(doc, page_index: int, dpi: int = 200) -> str:
    """fitz 渲染单页到 PNG，写到临时文件，返回路径。"""
    import fitz  # 已经在 _open_fitz 验证可用

    page = doc[page_index]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    pix.save(tmp.name)
    return tmp.name


def _pdf_total_pages_via_pdfinfo(abs_path: str) -> int:
    """通过 pdfinfo 获取总页数；失败时返回 -1。"""
    pdfinfo = shutil.which("pdfinfo")
    if not pdfinfo:
        return -1
    try:
        proc = subprocess.run(
            [pdfinfo, abs_path],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if proc.returncode != 0:
            return -1
        for line in proc.stdout.splitlines():
            s = line.strip()
            if s.lower().startswith("pages:"):
                try:
                    return int(s.split(":", 1)[1].strip())
                except Exception:  # noqa: BLE001
                    return -1
    except Exception:  # noqa: BLE001
        return -1
    return -1


def _select_pages_one_indexed(pages: PageSpec, total_pages: int) -> List[int]:
    """统一返回 1-indexed 页号列表；unknown total 时尽力从 pages 参数推导。"""
    if total_pages > 0:
        return [i + 1 for i in _normalize_pages(pages, total_pages)]
    if pages is None:
        raise RuntimeError("无法确定 PDF 总页数，且未指定 pages。请先安装 pdfinfo 或显式传 pages。")
    if isinstance(pages, int):
        p = int(pages)
        return [p] if p > 0 else []
    if isinstance(pages, tuple):
        if len(pages) != 2:
            raise ValueError("tuple 形式 pages 必须是 (start, end)，1-indexed")
        start, end = int(pages[0]), int(pages[1])
        if start > end:
            start, end = end, start
        return [i for i in range(start, end + 1) if i > 0]
    if isinstance(pages, (list, set)):
        seen = sorted({int(p) for p in pages if isinstance(p, int)})
        return [i for i in seen if i > 0]
    raise ValueError(f"不支持的 pages 参数类型: {type(pages).__name__}")


def _extract_meaningful_len(text: str) -> int:
    """忽略 form-feed 等空白符后的有效字符数。"""
    return len((text or "").replace("\f", "").strip())


def _ocr_pdf_via_pdftoppm(
    abs_path: str,
    pages: PageSpec,
    dpi: int,
    ocr_langs: Optional[List[str]],
) -> dict:
    """无 PyMuPDF 时，走 pdftoppm + OCR 的 PDF 读取路径。"""
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("未找到 pdftoppm；请安装 poppler（brew install poppler）。")

    total_pages = _pdf_total_pages_via_pdfinfo(abs_path)
    page_nums = _select_pages_one_indexed(pages, total_pages)
    if not page_nums:
        return {
            "path": abs_path,
            "backend": "pdftoppm+ocr",
            "total_pages": total_pages,
            "pages_extracted": [],
            "ocr_used": [],
            "text": "",
        }

    parts: List[str] = []
    ocr_used: List[int] = []
    with tempfile.TemporaryDirectory(prefix="omlx-pdf-") as tmpdir:
        for p in page_nums:
            prefix = os.path.join(tmpdir, f"page-{p}")
            proc = subprocess.run(
                [pdftoppm, "-f", str(p), "-l", str(p), "-r", str(dpi), "-png", abs_path, prefix],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"pdftoppm 渲染第 {p} 页失败: {proc.stderr.strip()[:240]}")

            images = sorted(glob(f"{prefix}-*.png"))
            if not images:
                raise RuntimeError(f"pdftoppm 未输出第 {p} 页图片。")

            page_texts = []
            for img in images:
                page_texts.append(_ocr_image(img, langs=ocr_langs))
            parts.append("\n".join(page_texts))
            ocr_used.append(p)

    return {
        "path": abs_path,
        "backend": "pdftoppm+ocr",
        "total_pages": total_pages,
        "pages_extracted": page_nums,
        "ocr_used": ocr_used,
        "text": "\n".join(parts),
    }


# ------------------------------- 工具函数 ------------------------------- #


@skill(
    desc="读取 PDF 元信息：总页数、标题、作者、是否加密等。",
    examples=["pdf_meta('paper.pdf')"],
)
def pdf_meta(path: str) -> dict:
    """返回 dict: {path, total_pages, title, author, subject, creation_date, encrypted, backend}."""
    abs_path = _resolve_path(path)

    doc = _open_fitz(abs_path)
    if doc is not None:
        try:
            meta = dict(doc.metadata or {})
            return {
                "path": abs_path,
                "backend": "pymupdf",
                "total_pages": doc.page_count,
                "title": meta.get("title", "") or "",
                "author": meta.get("author", "") or "",
                "subject": meta.get("subject", "") or "",
                "creation_date": meta.get("creationDate", "") or "",
                "encrypted": doc.is_encrypted,
            }
        finally:
            doc.close()

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        raise RuntimeError(
            "无可用 PDF 后端。请安装：pip install PyMuPDF（推荐）/ pypdf。"
        )
    reader = PdfReader(abs_path)
    meta = reader.metadata or {}
    return {
        "path": abs_path,
        "backend": "pypdf",
        "total_pages": len(reader.pages),
        "title": str(meta.get("/Title", "") or ""),
        "author": str(meta.get("/Author", "") or ""),
        "subject": str(meta.get("/Subject", "") or ""),
        "creation_date": str(meta.get("/CreationDate", "") or ""),
        "encrypted": reader.is_encrypted,
    }


@skill(
    desc="一站式读 PDF（推荐入口）。auto: 每页若有文字层就提取，否则自动 OCR；off: 仅文字层；force: 强制 OCR。",
    examples=[
        "pdf_read('合同.pdf')",
        "pdf_read('paper.pdf', pages=(1, 3))",
        "pdf_read('扫描件.pdf', ocr='force')",
    ],
)
def pdf_read(
    path: str,
    pages: PageSpec = None,
    ocr: str = "auto",
    ocr_threshold: int = 20,
    ocr_langs: Optional[List[str]] = None,
    dpi: int = 200,
) -> dict:
    """
    返回 dict: {path, total_pages, pages_extracted (1-indexed), ocr_used (1-indexed), text, backend}.

    参数：
      ocr: 'auto'（默认）/ 'off' / 'force'
      ocr_threshold: auto 模式下，单页文字层字符数 < 阈值则该页 OCR（默认 20）
      ocr_langs: OCR 语言。Vision 用 ['zh-Hans', 'en-US']；tesseract 用 ['chi_sim', 'eng']。
                 不指定时各后端用各自合理默认。
      dpi: OCR 前的页面渲染 DPI。默认 200，复杂版式可调到 300。
    """
    if ocr not in ("auto", "off", "force"):
        raise ValueError("ocr 必须是 'auto' / 'off' / 'force'")

    abs_path = _resolve_path(path)
    doc = _open_fitz(abs_path)
    if doc is None:
        # 缺少 PyMuPDF 时：先走文字层；若 auto 且文本近乎为空，则自动尝试 pdftoppm+OCR。
        bundle = pdf_to_text(abs_path, pages=pages)
        text = str(bundle.get("text", "") or "")
        if ocr == "off":
            return {
                "path": abs_path,
                "backend": f"{bundle.get('backend', 'unknown')} (fallback-no-pymupdf)",
                "total_pages": int(bundle.get("total_pages", -1) or -1),
                "pages_extracted": bundle.get("pages_extracted", []),
                "ocr_used": [],
                "text": text,
                "warning": "当前环境未安装 PyMuPDF，已按 ocr='off' 走文字层提取。",
            }

        # force 或 auto 且文字层几乎为空时，尝试 OCR 兜底。
        should_try_ocr = ocr == "force" or _extract_meaningful_len(text) < ocr_threshold
        if should_try_ocr:
            try:
                ocr_bundle = _ocr_pdf_via_pdftoppm(abs_path, pages=pages, dpi=dpi, ocr_langs=ocr_langs)
                ocr_bundle["backend"] = f"{ocr_bundle.get('backend', 'pdftoppm+ocr')} (fallback-no-pymupdf)"
                if _extract_meaningful_len(text) > 0 and ocr == "auto":
                    ocr_bundle["warning"] = (
                        "当前环境未安装 PyMuPDF；检测到文字层较少，已自动切换到 OCR。"
                    )
                return ocr_bundle
            except Exception as exc:  # noqa: BLE001
                if ocr == "force":
                    raise RuntimeError(
                        "当前环境缺少 PyMuPDF，且 OCR 兜底失败。"
                        f"请安装 PyMuPDF 或检查 OCR 依赖。详情: {type(exc).__name__}: {exc}"
                    ) from exc
                return {
                    "path": abs_path,
                    "backend": f"{bundle.get('backend', 'unknown')} (fallback-no-pymupdf)",
                    "total_pages": int(bundle.get("total_pages", -1) or -1),
                    "pages_extracted": bundle.get("pages_extracted", []),
                    "ocr_used": [],
                    "text": text,
                    "warning": (
                        "当前环境未安装 PyMuPDF，且自动 OCR 兜底失败；已返回文字层提取结果。"
                        f" OCR 错误: {type(exc).__name__}: {exc}"
                    ),
                }

        return {
            "path": abs_path,
            "backend": f"{bundle.get('backend', 'unknown')} (fallback-no-pymupdf)",
            "total_pages": int(bundle.get("total_pages", -1) or -1),
            "pages_extracted": bundle.get("pages_extracted", []),
            "ocr_used": [],
            "text": text,
            "warning": "当前环境未安装 PyMuPDF；文字层可用，已直接返回提取结果。",
        }

    try:
        total = doc.page_count
        indices = _normalize_pages(pages, total)
        parts: List[str] = []
        ocr_used: List[int] = []

        for i in indices:
            text_layer = "" if ocr == "force" else doc[i].get_text()
            need_ocr = ocr == "force" or (
                ocr == "auto" and len(text_layer.strip()) < ocr_threshold
            )

            if need_ocr:
                tmp_png = _render_page_to_png(doc, i, dpi=dpi)
                try:
                    page_text = _ocr_image(tmp_png, langs=ocr_langs)
                finally:
                    try:
                        os.unlink(tmp_png)
                    except OSError:
                        pass
                ocr_used.append(i + 1)
            else:
                page_text = text_layer

            parts.append(page_text)

        return {
            "path": abs_path,
            "backend": "pymupdf+ocr" if ocr_used else "pymupdf",
            "total_pages": total,
            "pages_extracted": [i + 1 for i in indices],
            "ocr_used": ocr_used,
            "text": "\n".join(parts),
        }
    finally:
        doc.close()


@skill(
    desc="对 PDF 强制走 OCR（已知是扫描件时优先用）。等价于 pdf_read(ocr='force')。",
    examples=[
        "pdf_ocr('扫描件.pdf')",
        "pdf_ocr('扫描件.pdf', pages=(1, 5))",
    ],
)
def pdf_ocr(
    path: str,
    pages: PageSpec = None,
    ocr_langs: Optional[List[str]] = None,
    dpi: int = 200,
) -> dict:
    """返回结构同 pdf_read。"""
    return pdf_read(path, pages=pages, ocr="force", ocr_langs=ocr_langs, dpi=dpi)


@skill(
    desc="仅提取 PDF 文字层（不 OCR）。明确知道 PDF 有文字层时用；扫描件请改用 pdf_read 或 pdf_ocr。",
    examples=[
        "pdf_to_text('paper.pdf')",
        "pdf_to_text('paper.pdf', pages=(1, 3))",
        "pdf_to_text('paper.pdf', pages=[1, 5, 10])",
    ],
)
def pdf_to_text(path: str, pages: PageSpec = None) -> dict:
    """返回 dict: {path, total_pages, pages_extracted (1-indexed), text, backend}."""
    abs_path = _resolve_path(path)

    doc = _open_fitz(abs_path)
    if doc is not None:
        try:
            total = doc.page_count
            indices = _normalize_pages(pages, total)
            parts = [doc[i].get_text() for i in indices]
            return {
                "path": abs_path,
                "backend": "pymupdf",
                "total_pages": total,
                "pages_extracted": [i + 1 for i in indices],
                "text": "\n".join(parts),
            }
        finally:
            doc.close()

    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        cmd = [pdftotext, "-layout", "-q"]
        first = last = None
        if isinstance(pages, int):
            first = last = pages
        elif isinstance(pages, tuple) and len(pages) == 2:
            first, last = sorted([int(pages[0]), int(pages[1])])
        if first is not None:
            cmd += ["-f", str(first), "-l", str(last)]
        cmd += [abs_path, "-"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
            if proc.returncode != 0:
                raise RuntimeError(f"pdftotext 失败: {proc.stderr.strip()[:200]}")
            return {
                "path": abs_path,
                "backend": "pdftotext",
                "total_pages": -1,
                "pages_extracted": list(range(first or 1, (last or 0) + 1)) if first else [],
                "text": proc.stdout,
            }
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("pdftotext 超时（120s）。建议改用 pdf_read（PyMuPDF）") from exc

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        raise RuntimeError(
            "无可用 PDF 后端。请安装：pip install PyMuPDF（推荐）/ pypdf；或 brew install poppler。"
        )
    reader = PdfReader(abs_path)
    total = len(reader.pages)
    indices = _normalize_pages(pages, total)
    parts = [reader.pages[i].extract_text() or "" for i in indices]
    return {
        "path": abs_path,
        "backend": "pypdf",
        "total_pages": total,
        "pages_extracted": [i + 1 for i in indices],
        "text": "\n".join(parts),
    }


@skill(
    desc="在 PDF 文字层里搜索关键词，返回每个命中点的页号（1-indexed）与上下文。扫描件请先 pdf_ocr 拿到文本后用 in 操作。",
    examples=[
        "pdf_search('paper.pdf', 'transformer')",
        "pdf_search('paper.pdf', '损失函数', context_chars=300, max_hits=20)",
    ],
)
def pdf_search(
    path: str,
    query: str,
    context_chars: int = 200,
    max_hits: int = 50,
    case_sensitive: bool = False,
) -> list:
    """返回列表 [{page, snippet, offset}, ...]。query 为空时返回空列表。"""
    if not query:
        return []
    abs_path = _resolve_path(path)

    doc = _open_fitz(abs_path)
    if doc is None:
        bundle = pdf_to_text(abs_path, pages=None)
        text = bundle["text"]
        return _search_in_text(text, query, context_chars, max_hits, case_sensitive)

    try:
        hits: list = []
        q = query if case_sensitive else query.lower()
        for i in range(doc.page_count):
            page_text = doc[i].get_text()
            haystack = page_text if case_sensitive else page_text.lower()
            start_at = 0
            while len(hits) < max_hits:
                idx = haystack.find(q, start_at)
                if idx < 0:
                    break
                left = max(0, idx - context_chars // 2)
                right = min(len(page_text), idx + len(query) + context_chars // 2)
                snippet = page_text[left:right].replace("\n", " ").strip()
                hits.append({"page": i + 1, "snippet": snippet, "offset": idx})
                start_at = idx + len(q)
            if len(hits) >= max_hits:
                break
        return hits
    finally:
        doc.close()


def _search_in_text(
    text: str, query: str, context_chars: int, max_hits: int, case_sensitive: bool
) -> list:
    haystack = text if case_sensitive else text.lower()
    q = query if case_sensitive else query.lower()
    hits: list = []
    start_at = 0
    while len(hits) < max_hits:
        idx = haystack.find(q, start_at)
        if idx < 0:
            break
        left = max(0, idx - context_chars // 2)
        right = min(len(text), idx + len(query) + context_chars // 2)
        snippet = text[left:right].replace("\n", " ").strip()
        hits.append({"page": -1, "snippet": snippet, "offset": idx})
        start_at = idx + len(q)
    return hits
