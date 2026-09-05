/* LOCAL PATCH to tools/ido-static-recomp/libc_impl.c (tools/ is gitignored).
 * Enables uopt's -Wo,-zdbug:6 regalloc dump (./uoptlist) by supplying the
 * ecvt/fcvt wrappers IDO's uopt calls for float-constant printing.
 * Re-apply after a clean tools/ checkout, then rebuild ido-static-recomp.
 */

/* ecvt(3): convert `number` to a string of `ndigits` significant digits (no
 * decimal point, no sign). decpt = position of the decimal point relative to the
 * start of the string; sign = 1 if negative else 0. Returns the emulated address
 * of the digit string. Implemented via snprintf("%.*e") + parse since glibc
 * dropped ecvt. Used only by uopt's -Wo,-zdbug regalloc dump (float-constant
 * formatting) — never by normal codegen, so it cannot affect compiled output. */
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
    buf = INTBUF_ADDR + 0x300; /* scratch slice, well within INTBUF_SIZE 0x400 */
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

/* fcvt(3): like ecvt but `ndigits` is the count of digits AFTER the decimal
 * point. decpt = number of integer-part digits. (Dump-path only, as above.) */
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
}
