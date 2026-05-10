# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
"""附件 MIME 归一化：拖放时浏览器常给出空或 application/octet-stream，需结合扩展名与 data URL 头推断。"""

from __future__ import annotations

from typing import Any


_VIDEO_EXT = {
    "mp4",
    "m4v",
    "mov",
    "webm",
    "mkv",
    "avi",
    "mpeg",
    "mpg",
    "3gp",
    "ogv",
}
_IMAGE_EXT = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "bmp",
    "heic",
    "heif",
    "avif",
    "jxl",
}
_AUDIO_EXT = {"mp3", "wav", "m4a", "flac", "ogg", "aac", "opus", "aiff", "aif", "wma"}


def _filename_ext(name: str) -> str:
    n = (name or "").strip().lower()
    if "." not in n:
        return ""
    return n.rsplit(".", 1)[-1].split("?")[0].split("#")[0]


def _mime_from_data_url_header(data_url: str) -> str:
    s = (data_url or "").strip()
    if not s.startswith("data:"):
        return ""
    comma = s.find(",")
    if comma <= 5:
        return ""
    meta = s[5:comma]
    if ";" in meta:
        media = meta.split(";", 1)[0].strip().lower()
    else:
        media = meta.strip().lower()
    return media if media and media != "application/octet-stream" else ""


def effective_attachment_mime(att: dict[str, Any]) -> str:
    """返回用于分支 image / audio / video 的 MIME 小写字符串（未知则为 application/octet-stream）。"""
    name = str(att.get("name") or "")
    raw_mime = str(att.get("mime") or "").strip().lower()
    data_url = str(att.get("data_url") or "")

    ext = _filename_ext(name)
    if ext in _VIDEO_EXT:
        if ext == "webm":
            return "video/webm"
        if ext in ("mov",):
            return "video/quicktime"
        if ext == "mkv":
            return "video/x-matroska"
        if ext in ("ogv",):
            return "video/ogg"
        return "video/mp4"
    if ext in _IMAGE_EXT:
        if ext in ("jpg", "jpeg"):
            return "image/jpeg"
        if ext == "png":
            return "image/png"
        if ext == "gif":
            return "image/gif"
        if ext == "webp":
            return "image/webp"
        if ext in ("heic", "heif"):
            return "image/heic" if ext == "heic" else "image/heif"
        if ext == "avif":
            return "image/avif"
        if ext == "jxl":
            return "image/jxl"
        return "image/bmp"
    if ext in _AUDIO_EXT:
        if ext == "mp3":
            return "audio/mpeg"
        if ext == "wav":
            return "audio/wav"
        if ext == "m4a":
            return "audio/mp4"
        if ext == "flac":
            return "audio/flac"
        if ext in ("ogg", "opus"):
            return "audio/ogg"
        if ext == "aac":
            return "audio/aac"
        if ext in ("aiff", "aif"):
            return "audio/aiff"
        return "audio/basic"

    if raw_mime and raw_mime != "application/octet-stream":
        return raw_mime

    from_header = _mime_from_data_url_header(data_url)
    if from_header:
        return from_header

    return raw_mime or "application/octet-stream"
