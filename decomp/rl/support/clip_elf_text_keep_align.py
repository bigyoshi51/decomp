#!/usr/bin/env python3
"""Clip a big-endian ELF .text section without rejecting shorter candidates.

This verifier-only variant preserves the project's exact-candidate behavior,
including forced symbol sizes and relocation clipping. Unlike the production
landing helper, a candidate whose .text is shorter than the requested layout
is allowed to proceed so an empty or partial RL solution can still be scored.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ELF_HEADER = struct.Struct(">16sHHIIIIIHHHHHH")
SECTION_HEADER = struct.Struct(">IIIIIIIIII")
SYMBOL = struct.Struct(">IIIBBH")
RELOCATION = struct.Struct(">II")


def _name(data: bytearray, string_offset: int, name_offset: int) -> str:
    start = string_offset + name_offset
    end = data.index(b"\x00", start)
    return bytes(data[start:end]).decode("ascii")


def clip_elf_text(
    path: Path,
    target_size: int,
    forced_sizes: dict[str, int],
) -> None:
    data = bytearray(path.read_bytes())
    if data[:4] != b"\x7fELF" or data[5] != 2:
        raise SystemExit(f"{path}: expected big-endian ELF")

    header = ELF_HEADER.unpack_from(data)
    section_offset = header[6]
    section_entry_size = header[11]
    section_count = header[12]
    section_names_index = header[13]
    sections = [
        list(
            SECTION_HEADER.unpack_from(
                data, section_offset + index * section_entry_size
            )
        )
        for index in range(section_count)
    ]
    section_names = sections[section_names_index]

    def section_name(index: int) -> str:
        return _name(data, section_names[4], sections[index][0])

    text_index = next(
        index for index in range(section_count) if section_name(index) == ".text"
    )
    symbol_table_index = next(
        index for index in range(section_count) if sections[index][1] == 2
    )
    string_table_index = sections[symbol_table_index][6]

    text = sections[text_index]
    if text[5] > target_size:
        previous_size = text[5]
        text[5] = target_size
        SECTION_HEADER.pack_into(
            data,
            section_offset + text_index * section_entry_size,
            *text,
        )
        print(
            f"{path}: clipped .text from 0x{previous_size:x} "
            f"to 0x{target_size:x}"
        )
    elif text[5] < target_size:
        print(
            f"{path}: verifier candidate .text is shorter "
            f"(0x{text[5]:x} < 0x{target_size:x}); no clip needed"
        )

    symbol_table = sections[symbol_table_index]
    symbol_offset, symbol_size, symbol_entry_size = (
        symbol_table[4],
        symbol_table[5],
        symbol_table[9],
    )
    string_offset = sections[string_table_index][4]
    for index in range(symbol_size // symbol_entry_size):
        entry_offset = symbol_offset + index * symbol_entry_size
        fields = list(SYMBOL.unpack_from(data, entry_offset))
        name_offset, value, size, _info, _other, section_index = fields
        if section_index != text_index:
            continue
        name = _name(data, string_offset, name_offset) if name_offset else ""
        new_size = forced_sizes.get(name)
        if new_size is None and value + size > target_size:
            new_size = max(0, target_size - value)
        if new_size is not None and new_size != size:
            fields[2] = new_size
            SYMBOL.pack_into(data, entry_offset, *fields)
            print(
                f"{path}: resized symbol {name or '<no-name>'} "
                f"@ 0x{value:x} from 0x{size:x} to 0x{new_size:x}"
            )

    for index, section in enumerate(sections):
        section_type, section_info = section[1], section[7]
        if section_type not in (4, 9) or section_info != text_index:
            continue
        relocation_offset, relocation_size, relocation_entry_size = (
            section[4],
            section[5],
            section[9],
        )
        kept = bytearray()
        dropped = 0
        for offset in range(
            relocation_offset,
            relocation_offset + relocation_size,
            relocation_entry_size,
        ):
            relocation_address, _relocation_info = RELOCATION.unpack_from(
                data, offset
            )
            if relocation_address < target_size:
                kept.extend(data[offset : offset + relocation_entry_size])
            else:
                dropped += 1
        if dropped:
            end = relocation_offset + relocation_size
            data[relocation_offset : relocation_offset + len(kept)] = kept
            data[relocation_offset + len(kept) : end] = b"\x00" * (
                relocation_size - len(kept)
            )
            section[5] = len(kept)
            SECTION_HEADER.pack_into(
                data,
                section_offset + index * section_entry_size,
                *section,
            )
            print(
                f"{path}: dropped {dropped} .text relocation(s) "
                f"at/after 0x{target_size:x}"
            )

    path.write_bytes(data)


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "usage: clip_elf_text_keep_align.py "
            "<elf_file> <text_size> [symbol=size ...]"
        )
    forced_sizes = {}
    for value in sys.argv[3:]:
        name, raw_size = value.split("=", 1)
        forced_sizes[name] = int(raw_size, 0)
    clip_elf_text(Path(sys.argv[1]), int(sys.argv[2], 0), forced_sizes)


if __name__ == "__main__":
    main()
