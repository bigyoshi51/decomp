"""Bootstrap a new N64 decomp project from a raw ROM."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

# Paths relative to the decomp tool's own root (where pyproject.toml lives)
TOOL_ROOT = Path(__file__).resolve().parent.parent
IDO_RECOMP_DIR = TOOL_ROOT / "tools" / "ido-static-recomp"
ASM_PROCESSOR_DIR = TOOL_ROOT / "tools" / "asm-processor"


def bootstrap(rom_path: Path, project_dir: Path) -> None:
    """Create a new decomp project from a ROM.

    Steps:
        1. Create directory structure
        2. Copy ROM into project
        3. Run splat create_config
        4. Run splat split
        5. Set up toolchain (ido, asm-processor)
        6. Generate Makefile
        7. Generate decomp.yaml for our tool
    """
    rom_path = rom_path.resolve()
    project_dir = project_dir.resolve()

    if not rom_path.exists():
        print(f"Error: ROM not found: {rom_path}", file=sys.stderr)
        sys.exit(1)

    if project_dir.exists() and any(project_dir.iterdir()):
        print(f"Error: Directory not empty: {project_dir}", file=sys.stderr)
        sys.exit(1)

    # 1. Create directory structure
    print(f"Creating project in {project_dir}")
    project_dir.mkdir(parents=True, exist_ok=True)
    for d in ("src", "include", "assets", "tools"):
        (project_dir / d).mkdir(exist_ok=True)

    # 2. Copy ROM
    baserom = project_dir / "baserom.z64"
    print(f"Copying ROM to {baserom}")
    shutil.copy2(rom_path, baserom)

    # Compute SHA1 for later verification
    sha1 = hashlib.sha1(baserom.read_bytes()).hexdigest()
    (project_dir / "checksum.md5").write_text("")  # placeholder

    # Read ROM name from header (bytes 0x20-0x33)
    rom_data = baserom.read_bytes()
    rom_name = rom_data[0x20:0x34].decode("ascii", errors="replace").strip()
    # Clean name for use as basename
    basename = "".join(c if c.isalnum() else "_" for c in rom_name).strip("_").lower()
    if not basename:
        basename = "game"
    print(f"ROM: {rom_name} (basename: {basename})")

    # 3. Run splat create_config
    print("Running splat create_config...")
    result = subprocess.run(
        [sys.executable, "-m", "splat", "create_config", str(baserom)],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"splat create_config failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(result.stdout)

    # Find the generated yaml
    splat_yaml = _find_splat_yaml(project_dir)
    if not splat_yaml:
        print("Error: splat did not generate a YAML config", file=sys.stderr)
        sys.exit(1)
    print(f"Splat config: {splat_yaml.name}")

    # 4. Run splat split
    print("Running splat split...")
    result = subprocess.run(
        [sys.executable, "-m", "splat", "split", str(splat_yaml)],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"splat split failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    # Print a summary rather than the full output
    lines = result.stdout.strip().splitlines()
    if lines:
        # Show last few lines which typically have the summary
        for line in lines[-10:]:
            print(f"  {line}")

    # 5. Set up toolchain
    print("Setting up toolchain...")
    _setup_toolchain(project_dir)

    # 6. Generate Makefile
    print("Generating Makefile...")
    makefile = _generate_makefile(basename, splat_yaml.name)
    (project_dir / "Makefile").write_text(makefile)

    # 7. Generate include/common.h
    _generate_common_header(project_dir)

    # 8. Generate decomp.yaml for our tool
    print("Generating decomp.yaml...")
    decomp_yaml = _generate_decomp_yaml(project_dir, basename)
    (project_dir / "decomp.yaml").write_text(decomp_yaml)

    # 9. Generate .gitignore
    _generate_gitignore(project_dir)

    print(f"\nProject bootstrapped at {project_dir}")
    print(f"  ROM:    {rom_name}")
    print(f"  SHA1:   {sha1}")
    print(f"  Config: {splat_yaml.name}")
    print(f"\nNext steps:")
    print(f"  cd {project_dir}")
    print(f"  make          # attempt initial build")


def _find_splat_yaml(project_dir: Path) -> Path | None:
    """Find the YAML config splat generated."""
    for f in project_dir.iterdir():
        if f.suffix in (".yaml", ".yml") and f.name != "decomp.yaml":
            return f
    return None


def _setup_toolchain(project_dir: Path) -> None:
    """Symlink ido-static-recomp and asm-processor into the project."""
    tools_dir = project_dir / "tools"

    # Symlink ido
    ido_link = tools_dir / "ido-static-recomp"
    if not ido_link.exists():
        if IDO_RECOMP_DIR.exists():
            ido_link.symlink_to(IDO_RECOMP_DIR)
            print(f"  Linked ido-static-recomp")
        else:
            print(f"  Warning: ido-static-recomp not found at {IDO_RECOMP_DIR}")

    # Set up ido version dirs matching the Makefile convention: tools/ido/<os>/<version>/
    ido_os_dir = tools_dir / "ido" / "linux"
    ido_os_dir.mkdir(parents=True, exist_ok=True)
    for version in ("5.3", "7.1"):
        version_link = ido_os_dir / version
        recomp_out = IDO_RECOMP_DIR / "build" / version / "out"
        if not version_link.exists() and recomp_out.exists():
            version_link.symlink_to(recomp_out)
            print(f"  Linked IDO {version}")

    # Symlink asm-processor
    asm_proc_link = tools_dir / "asm-processor"
    if not asm_proc_link.exists():
        if ASM_PROCESSOR_DIR.exists():
            asm_proc_link.symlink_to(ASM_PROCESSOR_DIR)
            print(f"  Linked asm-processor")
        else:
            print(f"  Warning: asm-processor not found at {ASM_PROCESSOR_DIR}")


def _generate_makefile(basename: str, splat_yaml: str) -> str:
    """Generate a Makefile for the decomp project."""
    return f"""\
MAKEFLAGS += --no-builtin-rules

SHELL = /bin/bash
.SHELLFLAGS = -o pipefail -c

#### Defaults ####
VERSION  ?= us
COMPARE  ?= 1
NON_MATCHING ?= 0
CROSS    ?= mips-linux-gnu-
PYTHON   ?= python3

TARGET   := {basename}

#### Directories ####
BUILD_DIR := build
SRC_DIRS  := $(shell find src -type d 2>/dev/null)
ASM_DIRS  := $(shell find asm -type d -not -path "asm/nonmatchings/*" 2>/dev/null)
BIN_DIRS  := $(shell find assets -type d 2>/dev/null)

#### Tools ####
CC       := tools/ido/linux/7.1/cc
CC_OLD   := tools/ido/linux/5.3/cc
AS       := $(CROSS)as
LD       := $(CROSS)ld
OBJCOPY  := $(CROSS)objcopy
OBJDUMP  := $(CROSS)objdump
CPP      := cpp
ASM_PROC := $(PYTHON) tools/asm-processor/build.py

SPLAT      ?= $(PYTHON) -m splat split
SPLAT_YAML ?= {splat_yaml}

#### Flags ####
CFLAGS    := -G 0 -non_shared -Xcpluscomm -nostdinc -Wab,-r4300_mul
WARNINGS  := -fullwarn -verbose -woff 624,649,838,712,516,513,596,564,594
OPTFLAGS  := -O2 -g3
MIPS_VER  := -mips2
ASFLAGS   := -march=vr4300 -32 -G0
LDFLAGS   := --no-check-sections --accept-unknown-input-arch --emit-relocs
ENDIAN    := -EB

IINC := -Iinclude -I.

C_DEFINES  := -DLANGUAGE_C -D_LANGUAGE_C -D_MIPS_SZLONG=32 -DNDEBUG -D_FINALROM
AS_DEFINES := -DMIPSEB -D_LANGUAGE_ASSEMBLY -D_ULTRA64

ASM_PROC_FLAGS := --input-enc=utf-8 --output-enc=euc-jp --convert-statics=global-with-filename

#### Host CC check ####
CC_CHECK       := gcc
CC_CHECK_FLAGS := -MMD -MP -fno-builtin -fsyntax-only -funsigned-char -std=gnu89 -m32 \\
                  -DNON_MATCHING -DCC_CHECK=1 \\
                  -Wall -Wextra -Wno-unknown-pragmas -Wno-missing-braces -Wno-sign-compare

MIPS_BUILTIN_DEFS := -DMIPSEB -D_MIPS_FPSET=16 -D_MIPS_ISA=2 -D_ABIO32=1 \\
                     -D_MIPS_SIM=_ABIO32 -D_MIPS_SZINT=32 -D_MIPS_SZPTR=32

#### Files ####
C_FILES   := $(foreach dir,$(SRC_DIRS),$(wildcard $(dir)/*.c))
S_FILES   := $(foreach dir,$(ASM_DIRS) $(SRC_DIRS),$(wildcard $(dir)/*.s))
BIN_FILES := $(foreach dir,$(BIN_DIRS),$(wildcard $(dir)/*.bin))

O_FILES := $(foreach f,$(C_FILES:.c=.o),$(BUILD_DIR)/$f) \\
           $(foreach f,$(S_FILES:.s=.o),$(BUILD_DIR)/$f) \\
           $(foreach f,$(BIN_FILES:.bin=.o),$(BUILD_DIR)/$f)

DEP_FILES := $(O_FILES:.o=.d) $(O_FILES:.o=.asmproc.d)

# Create build directories
$(shell mkdir -p $(foreach dir,$(SRC_DIRS) $(ASM_DIRS) $(BIN_DIRS),$(BUILD_DIR)/$(dir)))

#### Linker script ####
LDSCRIPT := $(BUILD_DIR)/$(TARGET).ld

# Route C files through asm-processor for GLOBAL_ASM support
build/src/%.o: CC := $(ASM_PROC) $(ASM_PROC_FLAGS) $(CC) -- $(AS) $(ASFLAGS) --

#### Targets ####
all: rom

rom: $(BUILD_DIR)/$(TARGET).z64
ifneq ($(COMPARE),0)
	@md5sum $<
endif

clean:
	$(RM) -r $(BUILD_DIR)

distclean: clean
	$(RM) -r asm/ assets/

extract:
	$(RM) -r asm/ assets/
	$(SPLAT) $(SPLAT_YAML)

.PHONY: all rom clean distclean extract
.DEFAULT_GOAL := rom
.SECONDARY:

#### Recipes ####

$(BUILD_DIR)/$(TARGET).z64: $(BUILD_DIR)/$(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(BUILD_DIR)/$(TARGET).elf: $(O_FILES) $(LDSCRIPT)
	$(LD) $(LDFLAGS) -T $(LDSCRIPT) -Map $(BUILD_DIR)/$(TARGET).map -o $@

$(LDSCRIPT): $(TARGET).ld
	$(CPP) -P $(IINC) -o $@ $<

$(BUILD_DIR)/%.o: %.c
	$(CC_CHECK) $(CC_CHECK_FLAGS) $(IINC) -I $(dir $*) $(C_DEFINES) $(MIPS_BUILTIN_DEFS) -o $@ $<
	$(CC) -c $(CFLAGS) $(IINC) $(WARNINGS) $(MIPS_VER) $(ENDIAN) $(C_DEFINES) $(OPTFLAGS) -o $@ $<
	$(OBJCOPY) --remove-section .mdebug $@ 2>/dev/null || true

$(BUILD_DIR)/%.o: %.s
	$(AS) $(ASFLAGS) $(ENDIAN) $(IINC) -I $(dir $*) $(AS_DEFINES) -o $@ $<

$(BUILD_DIR)/%.o: %.bin
	$(OBJCOPY) -I binary -O elf32-big $< $@

-include $(DEP_FILES)

print-% : ; $(info $* is a $(flavor $*) variable set to [$($*)]) @true
"""


def _generate_common_header(project_dir: Path) -> None:
    """Generate a minimal include/common.h."""
    header = """\
#ifndef COMMON_H
#define COMMON_H

#include "ultra64.h"

#endif /* COMMON_H */
"""
    (project_dir / "include" / "common.h").write_text(header)


def _generate_decomp_yaml(project_dir: Path, basename: str) -> str:
    """Generate the decomp.yaml config for our decompilation tool."""
    return f"""\
# decomp agent configuration
project_root: {project_dir}
base_rom: baserom.z64
ido_recomp: tools/ido-static-recomp

# Agent settings
max_attempts: 30
model: claude-sonnet-4-20250514

# Project structure
asm_dir: asm/nonmatchings
src_dir: src
include_dir: include
"""


def _generate_gitignore(project_dir: Path) -> None:
    """Generate a .gitignore for the decomp project."""
    gitignore = """\
build/
baserom.z64
*.z64
*.n64
*.v64
.splat/
__pycache__/
*.pyc
"""
    (project_dir / ".gitignore").write_text(gitignore)
