from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any


def _normalize(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _normalize(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        ordered = sorted(value.items(), key=lambda pair: str(pair[0]))
        return {str(key): _normalize(item) for key, item in ordered}
    if isinstance(value, (tuple, list, set, frozenset)):
        values = [_normalize(item) for item in value]
        if isinstance(value, (set, frozenset)):
            return sorted(values, key=lambda item: json.dumps(item, sort_keys=True))
        return values
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
