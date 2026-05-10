# SPDX-License-Identifier: MIT
from __future__ import annotations

import base64

from webapi.video_frames import parse_data_url


def test_parse_data_url_mp4() -> None:
    payload = base64.b64encode(b"\x00\x00\x00 ftyp").decode("ascii")
    s = f"data:video/mp4;base64,{payload}"
    raw, mime = parse_data_url(s)
    assert mime == "video/mp4"
    assert raw == b"\x00\x00\x00 ftyp"
