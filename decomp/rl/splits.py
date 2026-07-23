from __future__ import annotations

import hashlib
import re

_ADDRESS_COMMENT = re.compile(r"/\*[^*]*\*/")
_HEX_OR_NUMBER = re.compile(r"(?<![A-Za-z_])(?:-?0x[0-9A-Fa-f]+|-?\d+)")
_LOCAL_LABEL = re.compile(r"\.?L[0-9A-Fa-f_]+")
_SYMBOL = re.compile(r"\b(?:D|func|gl_func|game_libs_func)_[0-9A-Fa-f]+\b")


def assembly_shape(assembly: str | None) -> str:
    """Normalize addresses/addends while retaining mnemonic and operand shape."""
    if not assembly:
        return "missing"
    normalized: list[str] = []
    for raw_line in assembly.splitlines():
        line = _ADDRESS_COMMENT.sub("", raw_line).strip()
        if not line or line.startswith((".", "#", "glabel", "endlabel")):
            continue
        line = _LOCAL_LABEL.sub("<label>", line)
        line = _SYMBOL.sub("<symbol>", line)
        line = _HEX_OR_NUMBER.sub("<imm>", line)
        normalized.append(" ".join(line.split()))
    return "\n".join(normalized)


def assembly_fingerprint(assembly: str | None) -> str:
    shape = assembly_shape(assembly)
    return hashlib.blake2s(shape.encode(), digest_size=16).hexdigest()


def deterministic_split(
    group_key: str,
    *,
    seed: str = "n64-decomp-v1",
    train_ratio: float = 0.90,
    validation_ratio: float = 0.05,
) -> str:
    if not 0 <= train_ratio <= 1:
        raise ValueError("train_ratio must be in [0, 1]")
    if not 0 <= validation_ratio <= 1 or train_ratio + validation_ratio > 1:
        raise ValueError("invalid validation_ratio")
    digest = hashlib.blake2s(f"{seed}:{group_key}".encode(), digest_size=8).digest()
    value = int.from_bytes(digest, "big") / 2**64
    if value < train_ratio:
        return "train"
    if value < train_ratio + validation_ratio:
        return "validation"
    return "test"
