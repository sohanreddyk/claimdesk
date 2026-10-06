"""Audit trail. Events are scrubbed on creation so raw PII can never be stored in them."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from .masking import PII_KEYS, mask_value


class AuditEvent(BaseModel):
    seq: int  # monotonically increasing per session; no wall-clock time keeps tests deterministic
    type: str
    data: dict[str, Any] = {}


def scrub(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of `data` with any known-PII string values masked, recursively."""
    return {key: _scrub_value(key, value) for key, value in data.items()}


def _scrub_value(key: str, value: Any) -> Any:
    if key in PII_KEYS and isinstance(value, str):
        return mask_value(key, value)
    if isinstance(value, Mapping):
        return scrub(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_scrub_value(key, item) for item in value]
    return value
