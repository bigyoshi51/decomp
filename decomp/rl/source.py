from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_DEFINITION = re.compile(
    r"(?m)^[ \t]*(?!if\b|for\b|while\b|switch\b)"
    r"(?:(?:[A-Za-z_]\w*[ \t]+|[A-Za-z_]\w*[ \t]*\*[ \t]*)+)?"
    r"([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:[^(){};]+;\s*)*\{"
)
_INCLUDE_ASM = re.compile(
    r"\b(?:INCLUDE_ASM|GLOBAL_ASM)\s*\([^\n,]*,\s*([A-Za-z_]\w*)\s*\)"
)
_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)
_WHITESPACE = re.compile(r"\s+")
_LEXICAL_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*.*?\*/',
    re.DOTALL,
)
_BARE_COMMENT_CONTINUATION = re.compile(r"(?m)^[ \t]*\*[ \t]{2,}\S")


@dataclass(frozen=True)
class SourceSpan:
    start: int
    body_start: int
    end: int
    text: str


class SourceIndex:
    def __init__(self, paths: dict[str, tuple[Path, ...]]) -> None:
        self._paths = paths

    @classmethod
    def build(cls, root: Path, source_roots: tuple[str, ...]) -> "SourceIndex":
        mapping: dict[str, list[Path]] = {}
        for source_root in source_roots:
            directory = root / source_root
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*.c")):
                try:
                    text = path.read_text(errors="replace")
                except OSError:
                    continue
                names = {match.group(1) for match in _code_matches(_DEFINITION, text)}
                names.update(
                    match.group(1) for match in _code_matches(_INCLUDE_ASM, text)
                )
                for name in names:
                    mapping.setdefault(name, []).append(path.relative_to(root))
        return cls({name: tuple(paths) for name, paths in mapping.items()})

    def find(self, function_name: str) -> tuple[Path, ...]:
        return self._paths.get(function_name, ())


def find_function_span(source: str, function_name: str) -> SourceSpan | None:
    definition = re.compile(
        r"(?m)^[ \t]*(?!if\b|for\b|while\b|switch\b)"
        r"(?:(?:[A-Za-z_]\w*[ \t]+|[A-Za-z_]\w*[ \t]*\*[ \t]*)+)?"
        rf"{re.escape(function_name)}\s*\("
    )
    for match in _code_matches(definition, source):
        paren_start = source.find("(", match.start())
        paren_end = _balanced_end(source, paren_start, "(", ")")
        if paren_end is None:
            continue
        body_start = _skip_space_and_comments(source, paren_end)
        if body_start < len(source) and source[body_start] != "{":
            possible_body = source.find("{", body_start)
            declarations = source[paren_end:possible_body]
            if (
                possible_body != -1
                and "(" not in declarations
                and ")" not in declarations
                and re.fullmatch(r"(?:\s|/\*.*?\*/|//[^\n]*|[^;{}]+;)+", declarations)
            ):
                body_start = possible_body
        if body_start >= len(source) or source[body_start] != "{":
            continue
        body_end = _balanced_end(source, body_start, "{", "}")
        if body_end is None:
            continue

        return SourceSpan(
            start=match.start(),
            body_start=body_start,
            end=body_end,
            text=source[match.start() : body_end],
        )
    return None


def find_function_spans(source: str, function_name: str) -> tuple[SourceSpan, ...]:
    """Find every definition, including mutually exclusive preprocessor branches."""
    spans: list[SourceSpan] = []
    offset = 0
    while offset < len(source):
        span = find_function_span(source[offset:], function_name)
        if span is None:
            break
        absolute = SourceSpan(
            start=offset + span.start,
            body_start=offset + span.body_start,
            end=offset + span.end,
            text=span.text,
        )
        spans.append(absolute)
        offset = absolute.end
    return tuple(spans)


def replace_function(source: str, function_name: str, replacement: str) -> str:
    span = find_function_span(source, function_name)
    if span is None:
        raise ValueError(f"function definition not found: {function_name}")
    return source[: span.start] + replacement.rstrip() + source[span.end :]


def empty_function_body(source: str, function_name: str) -> str:
    """Keep a function's historical declaration while replacing its body."""
    span = find_function_span(source, function_name)
    if span is None:
        raise ValueError(f"function definition not found: {function_name}")
    declaration = source[span.start : span.body_start].rstrip()
    return f"{declaration} {{\n}}\n"


def nonexact_function_body(source: str, function_name: str) -> str:
    """Preserve a declaration while forcing a compilable non-empty body."""
    span = find_function_span(source, function_name)
    if span is None:
        raise ValueError(f"function definition not found: {function_name}")
    declaration = source[span.start : span.body_start].rstrip()
    return (
        f"{declaration} {{\n"
        "    volatile int decomp_rl_probe;\n"
        "    decomp_rl_probe = 0;\n"
        "}\n"
    )


def relocation_scaffold_function_body(source: str, function_name: str) -> str:
    """Preserve a definition while forcing one removable text relocation.

    Donor-splice build recipes can require the destination object to already
    contain ``.rel.text``.  Public fixtures use this only for duplicate target
    definitions: the verifier later replaces their bytes with the candidate's
    donor body, while the temporary unresolved call keeps the ELF section
    available for that splice.
    """
    span = find_function_span(source, function_name)
    if span is None:
        raise ValueError(f"function definition not found: {function_name}")
    declaration = source[span.start : span.body_start].rstrip()
    return (
        "extern void decomp_rl_relocation_probe(void);\n"
        f"{declaration} {{\n"
        "    decomp_rl_relocation_probe();\n"
        "}\n"
    )


def canonicalize_c(source: str) -> str:
    return _WHITESPACE.sub("", _COMMENT.sub("", source))


def same_function(left: str, right: str) -> bool:
    return canonicalize_c(left) == canonicalize_c(right)


def looks_like_comment_fragment(source: str) -> bool:
    """Detect pseudocode copied out of a block comment without its opener.

    A few legacy episode loggers captured an inner ``fn(...) {`` line and the
    following doc-comment lines, producing text that balances braces but is
    not C. Real block comments are ignored; only bare, multi-space ``*``
    continuation lines in code count.
    """
    return next(_code_matches(_BARE_COMMENT_CONTINUATION, source), None) is not None


def _balanced_end(source: str, start: int, opening: str, closing: str) -> int | None:
    depth = 0
    idx = start
    state = "code"
    while idx < len(source):
        char = source[idx]
        nxt = source[idx + 1] if idx + 1 < len(source) else ""
        if state == "code":
            if char == "/" and nxt == "*":
                state = "block_comment"
                idx += 2
                continue
            if char == "/" and nxt == "/":
                state = "line_comment"
                idx += 2
                continue
            if char == '"':
                state = "string"
            elif char == "'":
                state = "char"
            elif char == opening:
                depth += 1
            elif char == closing:
                depth -= 1
                if depth == 0:
                    return idx + 1
        elif state == "block_comment" and char == "*" and nxt == "/":
            state = "code"
            idx += 2
            continue
        elif state == "line_comment" and char == "\n":
            state = "code"
        elif state in {"string", "char"}:
            if char == "\\":
                idx += 2
                continue
            if (state == "string" and char == '"') or (state == "char" and char == "'"):
                state = "code"
        idx += 1
    return None


def _skip_space_and_comments(source: str, start: int) -> int:
    idx = start
    while idx < len(source):
        if source[idx].isspace():
            idx += 1
            continue
        if source.startswith("/*", idx):
            end = source.find("*/", idx + 2)
            return (
                len(source) if end == -1 else _skip_space_and_comments(source, end + 2)
            )
        if source.startswith("//", idx):
            end = source.find("\n", idx + 2)
            return (
                len(source) if end == -1 else _skip_space_and_comments(source, end + 1)
            )
        break
    return idx


def _code_matches(pattern: re.Pattern[str], source: str) -> Iterator[re.Match[str]]:
    """Yield regex matches whose starting offset is outside comments/strings."""
    tokens = iter(_LEXICAL_TOKEN.finditer(source))
    token = next(tokens, None)
    for match in pattern.finditer(source):
        while token is not None and token.end() <= match.start():
            token = next(tokens, None)
        if token is not None and token.start() <= match.start() < token.end():
            continue
        yield match
