from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


_LOGGER = logging.getLogger("omlxcli")
if not _LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.addHandler(handler)
_LOGGER.setLevel(logging.INFO)


def log_event(event_type: str, **fields: Any) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        **fields,
    }
    _LOGGER.info(json.dumps(payload, ensure_ascii=False, default=str))
