Use this skill when decompiling functions that construct F3DEX2 display lists. Indicators: `Gfx` type, display list pointer increments, raw hex values like `0xDA`, `0x06`, `0xB8`, `0xE7` in `.word` data or struct assignments.

## Identifying F3DEX2 Code

Display list functions write 8-byte microcode commands to a `Gfx*` pointer. In decompiled code, this looks like:

```c
// Naive (wrong) decompilation:
ptr->words.w0 = 0xDA380003;
ptr->words.w1 = (s32)arg->mtx;

// Correct (using GBI macros):
gSPMatrix(ptr++, arg->mtx, G_MTX_NOPUSH | G_MTX_LOAD | G_MTX_MODELVIEW);
```

## Using gfxdis

Disassemble raw hex to identify F3DEX2 commands:

```bash
uv run python -m decomp.tools.gfxdis <hex_bytes>
```

Example:
```bash
uv run python -m decomp.tools.gfxdis DA38000300000000
# Output: gsSPMatrix(0x00000000, G_MTX_NOPUSH | G_MTX_LOAD | G_MTX_MODELVIEW)
```

For multiple commands, concatenate the hex:
```bash
uv run python -m decomp.tools.gfxdis DA380003000000000600000000000000
```

## Converting gfxdis Output to C Macros

gfxdis outputs `gsSP*` / `gsDP*` macros (static versions). For display list construction, use the dynamic `gSP*` / `gDP*` variants that take a display list pointer:

| gfxdis output | C code |
|---|---|
| `gsSPMatrix(addr, flags)` | `gSPMatrix(dl++, addr, flags)` |
| `gsSPVertex(addr, n, v0)` | `gSPVertex(dl++, addr, n, v0)` |
| `gsSP2Triangles(...)` | `gSP2Triangles(dl++, ...)` |
| `gsDPSetPrimColor(...)` | `gDPSetPrimColor(dl++, ...)` |
| `gsSPEndDisplayList()` | `gSPEndDisplayList(dl++)` |

The display list pointer is typically `gRegionAllocPtr` or a local `Gfx*` variable that gets incremented with each command.

## Aggregate Macros

Some GBI macros expand to MULTIPLE 8-byte commands. Look for consecutive commands that form these patterns:

- `gDPLoadTextureBlock` / `gDPLoadTextureBlock_4b` — loads textures (multiple commands)
- `gDPLoadTLUT` / `gDPLoadTLUT_pal16` / `gDPLoadTLUT_pal256` — loads palettes
- `gSPTextureRectangle` — textured rectangle (2-3 commands)
- `gDPFillRectangle` — solid rectangle

Check `include/PR/gbi.h` for the complete list of macros and their command expansions.

## Common F3DEX2 Opcodes

| Byte | Command | Description |
|------|---------|-------------|
| `0x01` | G_VTX | Load vertices |
| `0x05` | G_TRI1 | Draw 1 triangle |
| `0x06` | G_TRI2 / G_SP2Triangles | Draw 2 triangles |
| `0xB8` | G_ENDDL | End display list |
| `0xDA` | G_MTX | Set matrix |
| `0xDB` | G_MOVEWORD | Set RDP word |
| `0xDE` | G_DL | Branch to sub-display list |
| `0xE4` | G_TEXRECT | Texture rectangle |
| `0xE7` | G_RDPPIPESYNC | RDP pipeline sync |
| `0xF5` | G_SETTILE | Set tile descriptor |
| `0xFB` | G_SETENVCOLOR | Set environment color |
| `0xFC` | G_SETCOMBINE | Set color combiner |
| `0xFD` | G_SETTIMG | Set texture image |

## Glover-Specific Notes

Glover uses F3DEX2 (`-DF3DEX_GBI_2`). The GBI header is at `include/PR/gbi.h` (from libultra). Display list functions will be in the 18020 (game) segment, not D910 (debug).
