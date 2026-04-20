# decomp

A general-purpose, ROM-agnostic N64 decompilation agent. Uses Claude to iteratively read assembly, write candidate C, compile, diff, and refine until functions match byte-for-byte.

Wraps the standard N64 decomp ecosystem: splat, asm-differ, decomp-permuter, m2c, and IDO (via ido-static-recomp).

Heavily inspired by https://github.com/cdlewis/snowboardkids2-decomp.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this-repo>
cd decomp
uv sync
```

This installs the Python-based tools automatically:
- **asm-differ** — instruction-level diffing
- **m2c** — assembly-to-C decompiler
- **splat64** — ROM splitting

### ido-static-recomp (required)

Statically recompiled IDO 5.3/7.1 compilers that run natively on Linux — no qemu-irix needed.

```bash
sudo apt-get install build-essential  # if not already installed
git clone https://github.com/decompals/ido-static-recomp.git
cd ido-static-recomp
make setup
make VERSION=7.1
make VERSION=5.3
```

Binaries land in `build/{5.3,7.1}/out`. Point your `decomp.yaml` at this directory.

### decomp-permuter (optional)

Brute-force search for matching C permutations.

```bash
git clone https://github.com/simonlindholm/decomp-permuter.git
pip install pynacl Levenshtein  # optional deps for distributed mode
```

### Existing decomp project

You need an existing N64 decomp project to target (e.g., [sm64](https://github.com/n64decomp/sm64), [oot](https://github.com/zeldaret/oot), [mm](https://github.com/zeldaret/mm)). Follow that project's setup instructions to get it building first.

## Configuration

Create a `decomp.yaml` in your decomp project root:

```yaml
project_root: /path/to/your/decomp/project
base_rom: baserom.us.z64

# Tool paths
ido_recomp: /path/to/ido-static-recomp  # required
permuter: /path/to/decomp-permuter       # optional

# Agent settings
max_attempts: 30
model: claude-opus-4-7  # bumped to Opus 4.7 when it shipped; we upgrade as new Claude models release

# Project structure (defaults shown, relative to project_root)
asm_dir: asm/non_matchings
src_dir: src
include_dir: include
```

Also supported as `decomp.toml`.

## Usage

```bash
# Show project info
uv run python -m decomp.main info --config /path/to/decomp.yaml

# List unmatched functions
uv run python -m decomp.main discover
uv run python -m decomp.main discover --sort-by size

# Decompile a function with m2c (initial pseudo-C)
uv run python -m decomp.main m2c <function_name>

# Diff a function against target assembly
uv run python -m decomp.main diff <function_name>
```

## Roadmap

- [x] Project structure + config
- [x] Tool wrappers (compiler, differ, m2c, permuter)
- [x] CLI for discovery and manual tool use
- [x] Claude agent loop for automated decompilation (via `/decompile` skill + `/loop`)
- [ ] Function scoring and batch processing
- [x] Episode logging for future RL (canonical `Episode`/`Step` schema via `log-exact-episode`)
