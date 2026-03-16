You are working on an N64 decompilation project. Your goal is to set up objdiff for progress tracking and function-level diffing.

## Context

objdiff is the tool that powers decomp.dev progress tracking. It compares "target" objects (built from ROM-extracted asm — the expected output) against "base" objects (built from your decompiled C source) to measure matching progress per-function.

The decomp project lives under the `projects/` directory. Find the target project by looking for a splat YAML config and Makefile.

## Your workflow

1. **Understand the project structure**: Read the Makefile and splat YAML config to identify:
   - All C source files (`src/*.c`) — these are the interesting compilation units
   - The compiler and flags used (IDO, gcc 2.7.2, etc.)
   - The build output paths (`BUILD_DIR`, typically `build/`)
   - ASM-only segments (entry points, etc.)

2. **Add an `expected` Makefile target** that snapshots the current build objects as the baseline. Important: store expected objects **outside** `build/` (in `expected/`) so `make clean` doesn't wipe them:
   ```makefile
   expected: rom
   	$(RM) -r expected
   	mkdir -p expected/src expected/asm
   	cp $(BUILD_DIR)/src/*.o expected/src/
   	cp $(BUILD_DIR)/asm/*.o expected/asm/

   .PHONY: ... expected
   ```
   This should be run once after achieving a matching build (before any C decompilation changes), then again whenever segments are re-split.

3. **Create `objdiff.json`** in the project directory with this structure:
   ```json
   {
     "custom_make": "make",
     "custom_args": [],
     "build_target": false,
     "build_base": true,
     "watch_patterns": [
       "src/**/*.c",
       "src/**/*.h",
       "include/**/*.h",
       "asm/**/*.s"
     ],
     "units": [],
     "progress_categories": [
       {
         "id": "game",
         "name": "Game"
       }
     ]
   }
   ```

4. **Populate `units`** — one entry per C source file:
   ```json
   {
     "name": "src/<name>",
     "target_path": "expected/src/<name>.o",
     "base_path": "build/src/<name>.o",
     "metadata": {
       "source_path": "src/<name>.c",
       "progress_categories": ["game"]
     },
     "scratch": {
       "platform": "n64",
       "compiler": "<compiler-id>",
       "c_flags": "<flags from Makefile>"
     }
   }
   ```
   - For `compiler`, use the decomp.me compiler ID: `ido7.1`, `ido5.3`, `gcc2.7.2`, etc.
   - For `c_flags`, extract from the Makefile's `CFLAGS`, `OPTFLAGS`, and `MIPS_VER` variables (exclude `-Iinclude` paths).
   - ASM-only segments can be included with `"auto_generated": true` in metadata (hidden from sidebar but counted in progress).

5. **Verify setup**: Check that `expected/src/*.o` and `build/src/*.o` both exist. If the build is broken, note it but still create the config — objdiff will work once the build is fixed.

6. **Install objdiff-cli** if not already present:
   ```bash
   # Download latest release binary
   curl -sL https://github.com/encounter/objdiff/releases/latest/download/objdiff-cli-linux-x86_64 \
     -o ~/.local/bin/objdiff-cli && chmod +x ~/.local/bin/objdiff-cli
   ```
   The GUI can also be downloaded from the same releases page (`objdiff-linux-x86_64`).

7. **Generate the expected baseline**: Run `make expected RUN_CC_CHECK=0` in the project directory. This builds the ROM and snapshots the object files into `expected/`.

8. **Verify with a report**:
   ```bash
   objdiff-cli report generate
   ```
   This outputs JSON with per-unit and per-function matching stats. Key fields:
   - `matched_code_percent` — percentage of code bytes matching
   - `matched_functions` / `total_functions` — function-level progress
   - `fuzzy_match_percent` — per-function similarity score

## Key facts

- `build_target: false` means objdiff won't try to rebuild expected objects (they're static snapshots)
- `build_base: true` means objdiff will run `make` to rebuild your C source objects when files change
- The `scratch` config enables "Create scratch" in objdiff to send functions to decomp.me
- Each project gets its own `objdiff.json` — this is per-ROM config, not shared
- objdiff compares symbol-by-symbol within each .o file, so it can track per-function matching even when undecompiled functions use INCLUDE_ASM
- Re-run `make expected` after re-splitting segments or changing the asm baseline
