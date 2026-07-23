from __future__ import annotations

import re

from .models import PolicyViolation
from .source import find_function_span

_FORBIDDEN_SOURCE = (
    ("preprocessor", re.compile(r"(?m)^\s*#")),
    ("include_asm", re.compile(r"\b(?:INCLUDE_ASM|GLOBAL_ASM)\s*\(")),
    ("inline_asm", re.compile(r"\b(?:__asm__|__asm|asm)\s*\(")),
    ("raw_bytes", re.compile(r"\.(?:byte|word|incbin)\b")),
    (
        "post_compile_patch",
        re.compile(r"\b(?:INSN_PATCH|PREFIX_BYTES|SUFFIX_BYTES|PROLOGUE_STEALS)\b"),
    ),
)


def validate_candidate_source(
    source: str,
    function_name: str,
    *,
    max_bytes: int = 128_000,
) -> tuple[str | None, tuple[PolicyViolation, ...]]:
    violations: list[PolicyViolation] = []
    if len(source.encode()) > max_bytes:
        violations.append(
            PolicyViolation(
                code="source_too_large",
                message=f"candidate source exceeds {max_bytes} bytes",
            )
        )
        return None, tuple(violations)

    span = find_function_span(source, function_name)
    if span is None:
        violations.append(
            PolicyViolation(
                code="missing_function",
                message=f"candidate does not define {function_name}",
            )
        )
        return None, tuple(violations)

    candidate = span.text.rstrip() + "\n"
    for code, pattern in _FORBIDDEN_SOURCE:
        if pattern.search(candidate):
            violations.append(
                PolicyViolation(
                    code=code,
                    message=f"candidate uses forbidden mechanism: {code}",
                )
            )
    return candidate, tuple(violations)
