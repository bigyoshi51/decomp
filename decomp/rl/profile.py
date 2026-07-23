from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import ProjectProfile


def load_project_profile(path: Path) -> ProjectProfile:
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"project profile must be a mapping: {path}")

    tuple_fields = {
        "source_roots",
        "asm_roots",
        "make_args",
        "immutable_paths",
        "hidden_paths",
        "allowed_source_suffixes",
    }
    normalized: dict[str, Any] = dict(data)
    for field_name in tuple_fields:
        if field_name in normalized:
            value = normalized[field_name]
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValueError(f"{field_name} must be a list of strings")
            normalized[field_name] = tuple(value)
    return ProjectProfile(**normalized)
