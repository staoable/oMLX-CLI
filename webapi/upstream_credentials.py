# SPDX-License-Identifier: MIT
# Copyright (c) 2026 oMLX CLI contributors
"""根据会话绑定在 SQLite 中的模型设置（vendors）解析 api_base 与 api_key。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webapi.session_store import SessionRecord, SessionStore


def resolve_upstream_credentials(
    session: SessionRecord,
    store: SessionStore,
) -> tuple[str, str]:
    """返回 `(api_base, api_key)`。密钥仅存数据库 vendors.api_key，不使用进程环境兜底。"""
    base = (session.api_base or "").strip().rstrip("/")
    vid = (getattr(session, "vendor_id", None) or "").strip()
    if store.count_vendors() == 0:
        raise RuntimeError(
            "尚未配置任何模型设置。请先在 Web 侧栏打开「模型设置」添加至少一条 "
            "（名称、API Base、API Key），保存后再发起对话。"
        )
    if not vid:
        raise RuntimeError(
            "当前会话未选择模型设置。请在「设置」中为该会话选择一条已保存的模型设置后再试。"
        )
    vendor = store.get_vendor(vid)
    key = (vendor.api_key or "").strip()
    if not key:
        raise RuntimeError(
            f"模型设置「{vendor.name}」未配置 API Key。请打开「模型设置」编辑该条并保存密钥。"
        )
    vb = (vendor.api_base or "").strip().rstrip("/")
    return (vb or base).rstrip("/"), key
