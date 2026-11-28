"""Small idempotency receipts shared by reward settlement entry points."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MAX_RECEIPTS = 256
KEY = "settlement_receipts"


def _ext(doc: Any) -> dict[str, Any]:
    if isinstance(doc, dict):
        ext = doc.get("ext")
        if not isinstance(ext, dict):
            ext = {}
            doc["ext"] = ext
        return ext
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        ext = {}
        setattr(doc, "ext", ext)
    return ext


def receipt_key(kind: str, settlement_id: str) -> str:
    kind = str(kind or "").strip()
    settlement_id = str(settlement_id or "").strip()
    if not kind or not settlement_id:
        raise ValueError("settlement kind and id are required")
    return f"{kind}:{settlement_id}"


def claimed(doc: Any, kind: str, settlement_id: str) -> bool:
    records = _ext(doc).get(KEY)
    return isinstance(records, Mapping) and receipt_key(kind, settlement_id) in records


def claim(doc: Any, kind: str, settlement_id: str, now: float) -> bool:
    """Add one receipt to the player snapshot; caller saves it with its rewards."""
    ext = _ext(doc)
    records = ext.get(KEY)
    records = dict(records) if isinstance(records, Mapping) else {}
    key = receipt_key(kind, settlement_id)
    if key in records:
        return False
    records[key] = float(now)
    while len(records) > MAX_RECEIPTS:
        records.pop(next(iter(records)))
    ext[KEY] = records
    return True
