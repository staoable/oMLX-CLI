# SPDX-License-Identifier: MIT
from __future__ import annotations

from webapi.attachment_mime import effective_attachment_mime


def test_mp4_empty_browser_mime() -> None:
    att = {
        "name": "v.mp4",
        "mime": "",
        "data_url": "data:application/octet-stream;base64,AAAA",
    }
    assert effective_attachment_mime(att) == "video/mp4"


def test_mp4_octet_stream() -> None:
    att = {
        "name": "clip.MP4",
        "mime": "application/octet-stream",
        "data_url": "data:application/octet-stream;base64,AAAA",
    }
    assert effective_attachment_mime(att) == "video/mp4"


def test_wrong_image_mime_mp4_ext_wins() -> None:
    """拖放时偶发错误 Content-Type；扩展名应优先于 image/*。"""
    att = {
        "name": "v.mp4",
        "mime": "image/jpeg",
        "data_url": "data:image/jpeg;base64,/9j/",
    }
    assert effective_attachment_mime(att) == "video/mp4"


def test_no_ext_falls_back_to_data_url_header() -> None:
    att = {
        "name": "paste-1",
        "mime": "",
        "data_url": "data:video/webm;base64,AAAA",
    }
    assert effective_attachment_mime(att) == "video/webm"


def test_png_by_ext() -> None:
    att = {"name": "x.png", "mime": "", "data_url": "data:application/octet-stream;base64,AAAA"}
    assert effective_attachment_mime(att) == "image/png"
