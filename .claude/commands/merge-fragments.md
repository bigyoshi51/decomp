Merge function fragments in the N64 decomp project. Splat sometimes splits single functions into multiple asm files at incorrect boundaries. This skill merges them back together.

## Finding fragments

A fragment is an asm file that:
- Has no proper prologue (`addiu $sp, $sp, -XX` in first few instructions)
- Branches to `.L` labels OUTSIDE its own address range (backward branches to the parent)
- Is **contiguous** with the parent (parent_end == fragment_start, or nearly so)
- Has `endlabel` but the function continues in the next asm file

**Important distinction**: A backward branch alone does NOT make a fragment. If the referenced label is far away (many functions between them), it's a **cross-function label reference** — a separate function that jumps into another function's code. These should be handled with `undefined_syms_auto.txt` entries for the `.L` labels, NOT by merging.

The test: `parent_addr + parent_size == fragment_addr` (contiguous). If there's a gap with other functions in between, it's NOT a fragment.

Run this to find genuine fragments:
```python
import os, re
# Build address → (name, size) map
funcs = {}
for fname in sorted(os.listdir('asm/nonmatchings/kernel')):
    if not fname.endswith('.s'): continue
    with open(f'asm/nonmatchings/kernel/{fname}') as f:
        content = f.read()
    m = re.search(r'nonmatching\s+(\w+),\s+0x([0-9A-Fa-f]+)', content)
    if not m: continue
    name = m.group(1)
    addr = int(name.replace('func_',''), 16) if name.startswith('func_') else 0
    if addr: funcs[addr] = (name, int(m.group(2), 16), content)

for addr in sorted(funcs):
    name, size, content = funcs[addr]
    for line in content.split('\n'):
        m2 = re.search(r'\.L([0-9A-Fa-f]+)', line)
        if m2 and 'glabel' not in line:
            la = int(m2.group(1), 16)
            if la < addr:
                # Find the parent whose range includes the target
                parent_addr = max(a for a in funcs if a <= la)
                pname, psize, _ = funcs[parent_addr]
                gap = addr - (parent_addr + psize)
                if gap <= 0:  # contiguous or overlapping
                    print(f'{name} → {pname} (contiguous, total 0x{addr+size-parent_addr:X})')
                else:
                    print(f'{name} → {pname} (GAP 0x{gap:X} — cross-function ref, NOT a fragment)')
                break
```

## Merge process

For each fragment → parent pair:

1. **Read both asm files**: The parent's `.s` file and the fragment's `.s` file

2. **Extract fragment instructions**: Everything from the fragment that's an instruction line (`/* ... */`), label (`.L...:`), or endlabel

3. **Update parent file**:
   - Change size header: `nonmatching func_PARENT, 0xNEW_SIZE` where NEW_SIZE = fragment_end - parent_start
   - Replace `endlabel func_PARENT` with the fragment's instructions followed by `endlabel func_PARENT`
   - IMPORTANT: Change the fragment's `endlabel func_FRAGMENT` to `endlabel func_PARENT`

4. **Remove fragment's INCLUDE_ASM** from the `.c` source file

5. **Add symbol**: `echo "func_FRAGMENT = 0xFRAGMENT_ADDR;" >> undefined_syms_auto.txt`

6. **Add cross-function .L labels**: If the merged function references `.L` labels that are also defined in OTHER functions (same compilation unit), add them to `undefined_syms_auto.txt`:
   ```
   .LXXXXXXXX = 0xXXXXXXXX;
   ```

7. **Build and verify**: `rm -rf build && make RUN_CC_CHECK=0`

8. **Track the merge** in `DECOMPILED_FUNCTIONS.md` under "Fragment Merges Performed"

## Common issues

- **Duplicate .L labels**: When the merged function and another function in the same .c file both define the same .L label, you get "already defined" errors. Add the label to `undefined_syms_auto.txt` to resolve.
- **Chain merges**: Some fragments are parents of other fragments (e.g., A → B → C). Merge inner fragments first, then outer ones.
- **Cross-function label refs vs fragments**: If a function branches to a label 9KB away with dozens of functions between them, that's NOT a fragment — it's a cross-function `.L` label reference. Add the label to `undefined_syms_auto.txt` instead of merging. The key test: is the gap between parent end and fragment start zero (contiguous)?
- **Multi-way merges**: Sometimes A → B → C are all contiguous fragments of one function. Merge B into A first, then C into the enlarged A. Check for intermediate functions (e.g., A → X → B where X is also a fragment).
- **4-byte prologue fragments**: Functions like `func_80008D48` are just `addiu $sp, $sp, -XX` — a single prologue instruction split off. These are already tracked in DECOMPILED_FUNCTIONS.md.

## Arguments

The user may specify:
- A specific fragment name to merge (e.g., `func_800090B4`)
- `all` to merge all identified fragments
- No argument to list available fragments for selection
