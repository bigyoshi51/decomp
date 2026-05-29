#!/usr/bin/env python3
"""Patch ido-static-recomp's libc_impl.c to implement ecvt/fcvt, which unlocks
IDO's `-Wo,-zdbug:5/6` register-allocation dump (writes ./uoptlist).

WHY: the regalloc dump formats float constants via ecvt(3). decompals'
ido-static-recomp ships ecvt/fcvt as `assert(0)` stubs, so the dump crashes
(`uopt: libc_impl.c: wrapper_ecvt: Assertion '0' failed`). This implements them
(snprintf-parse → INTBUF scratch → MEM macros). It is CODEGEN-SAFE: ecvt/fcvt are
only ever called by the -zdbug dump path, never by normal compilation.

`tools/` is gitignored (per-machine build), so this patch is lost on a clean
toolchain checkout. Re-run this script + rebuild to restore the dump:

    python3 scripts/patch-ido-ecvt-dump.py tools/ido-static-recomp/libc_impl.c
    (cd tools/ido-static-recomp && make VERSION=7.1 -j4)

Idempotent: skips if already patched. See
docs/IDO_CODEGEN.md#feedback-ido-regalloc-renumber-matching-techniques.
"""

# ruff: noqa: E501  (embeds verbatim long C source lines)
import sys

STUBS = """uint32_t wrapper_ecvt(uint8_t* mem, double number, int ndigits, uint32_t decpt_addr, uint32_t sign_addr) {
    assert(0);
}

uint32_t wrapper_fcvt(uint8_t* mem, double number, int ndigits, uint32_t decpt_addr, uint32_t sign_addr) {
    assert(0);
}"""

IMPL = r"""/* ecvt(3): `number` -> string of `ndigits` significant digits (no point/sign);
 * *decpt = decimal-point position; *sign = 1 if negative. Returns the emulated
 * address of the digit string. snprintf("%.*e")-parse since glibc dropped ecvt.
 * Dump-path only (uopt -Wo,-zdbug float formatting) -> cannot affect codegen. */
uint32_t wrapper_ecvt(uint8_t* mem, double number, int ndigits, uint32_t decpt_addr, uint32_t sign_addr) {
    char tmp[80];
    char digits[64];
    int sign = 0;
    int exp = 0;
    int di = 0;
    int decpt;
    char* p;
    uint32_t buf;
    int i;

    if (signbit(number)) {
        sign = 1;
        number = -number;
    }
    if (ndigits < 1) {
        ndigits = 1;
    }
    if (ndigits > 40) {
        ndigits = 40;
    }
    if (!isfinite(number)) {
        digits[0] = '0';
        digits[1] = '\0';
        di = 1;
        decpt = 0;
    } else {
        snprintf(tmp, sizeof(tmp), "%.*e", ndigits - 1, number); /* "d.ddde+xx" */
        p = tmp;
        digits[di++] = *p++; /* leading digit */
        if (*p == '.') {
            p++;
            while (*p != '\0' && *p != 'e' && *p != 'E') {
                digits[di++] = *p++;
            }
        }
        if (*p == 'e' || *p == 'E') {
            exp = (int)strtol(p + 1, NULL, 10);
        }
        digits[di] = '\0';
        decpt = (number == 0.0) ? 1 : exp + 1;
    }
    buf = INTBUF_ADDR + 0x300; /* scratch slice within INTBUF_SIZE 0x400 */
    for (i = 0; i <= di; i++) {
        MEM_S8(buf + i) = digits[i];
    }
    if (decpt_addr != 0) {
        MEM_S32(decpt_addr) = decpt;
    }
    if (sign_addr != 0) {
        MEM_S32(sign_addr) = sign;
    }
    return buf;
}

/* fcvt(3): like ecvt but `ndigits` = digits AFTER the decimal point; decpt =
 * count of integer-part digits. (Dump-path only, as above.) */
uint32_t wrapper_fcvt(uint8_t* mem, double number, int ndigits, uint32_t decpt_addr, uint32_t sign_addr) {
    char tmp[160];
    char digits[160];
    int sign = 0;
    int decpt = 0;
    int di = 0;
    char* p;
    uint32_t buf;
    int i;

    if (signbit(number)) {
        sign = 1;
        number = -number;
    }
    if (ndigits < 0) {
        ndigits = 0;
    }
    if (ndigits > 80) {
        ndigits = 80;
    }
    if (!isfinite(number)) {
        digits[0] = '0';
        digits[1] = '\0';
        di = 1;
        decpt = 0;
    } else {
        snprintf(tmp, sizeof(tmp), "%.*f", ndigits, number); /* "ddd.ddd" */
        p = tmp;
        while (*p != '\0' && *p != '.') {
            digits[di++] = *p++;
            decpt++;
        }
        if (*p == '.') {
            p++;
            while (*p != '\0') {
                digits[di++] = *p++;
            }
        }
        digits[di] = '\0';
    }
    buf = INTBUF_ADDR + 0x340; /* separate scratch slice from ecvt */
    for (i = 0; i <= di; i++) {
        MEM_S8(buf + i) = digits[i];
    }
    if (decpt_addr != 0) {
        MEM_S32(decpt_addr) = decpt;
    }
    if (sign_addr != 0) {
        MEM_S32(sign_addr) = sign;
    }
    return buf;
}"""


def main():
    if len(sys.argv) != 2:
        print("usage: patch-ido-ecvt-dump.py <path/to/libc_impl.c>", file=sys.stderr)
        return 2
    path = sys.argv[1]
    src = open(path).read()
    if "buf = INTBUF_ADDR + 0x300;" in src:
        print(f"already patched: {path}")
        return 0
    if STUBS not in src:
        print(
            f"ERROR: ecvt/fcvt assert(0) stubs not found verbatim in {path}.\n"
            f"  The upstream source may have changed — patch by hand "
            f"(replace the two `wrapper_ecvt`/`wrapper_fcvt` stubs).",
            file=sys.stderr,
        )
        return 1
    open(path, "w").write(src.replace(STUBS, IMPL))
    print(
        f"patched {path}\n  now rebuild: (cd {path.rsplit('/', 1)[0]} && make VERSION=7.1 -j4)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
