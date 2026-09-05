# tools-patches

`tools/` is gitignored (third-party binaries, built or downloaded per machine),
so local patches to it live here instead — otherwise they are silently lost on
every clean checkout or machine move.

## ido-static-recomp-ecvt-uoptlist.c

Supplies `wrapper_ecvt` / `wrapper_fcvt` in
`tools/ido-static-recomp/libc_impl.c`. IDO's `uopt` calls these to print
float constants; without them, `-Wo,-zdbug:6` (the register-allocation dump
that writes `./uoptlist`) crashes.

**Apply after building ido-static-recomp:**
1. Paste both functions into `tools/ido-static-recomp/libc_impl.c`.
2. Rebuild ido-static-recomp.
3. Verify: compiling any TU with `-Wo,-zdbug:6` produces `./uoptlist` with
   candidate→register colorings.

That dump is the tool for register-allocation near-misses — it shows which
candidate uopt ranked where, so you can target the one priority that decides a
tie instead of sweeping C spellings blindly.
