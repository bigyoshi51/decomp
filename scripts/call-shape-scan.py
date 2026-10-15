#!/usr/bin/env python3
"""call-shape-scan.py -- flag call-arity / call-shape differences between an
NM build object and the expected/ object, per function.

Usage (run from a 1080 worktree root):
  python3 call-shape-scan.py UNIT [--report report.json] [--max-size N] [FUNC...]
    UNIT = path stem under src/, e.g. game_libs/game_libs_post0b

For every function of UNIT below 100 % in report.json (or the FUNC list), it
disassembles the NM body (build/non_matching/src/UNIT.c.o) and the target
(expected/src/UNIT.c.o), splits each into call sites (jal/jalr), and per site
compares:
  * which $a0-$a3 are written since the previous call (incl. delay slot)
  * call kind (jal vs jalr)
  * whether $v0 is read after the call before being written (callee result use)
It prints functions whose call count matches but some site differs (the
"call-arity" lever class), plus call-count mismatches as a separate tag.
Reloc-blind: only mnemonics and register operands are compared.
"""
import json, re, subprocess, sys, argparse

STORES = {'sb', 'sh', 'sw', 'swl', 'swr', 'swc1', 'sdc1', 'sd', 'sc'}
NODEST = STORES | {'mtc1', 'ctc1', 'mthi', 'mtlo', 'mult', 'multu', 'div', 'divu',
                   'nop', 'break', 'syscall', 'teq', 'tne', 'c.eq.s', 'c.lt.s',
                   'c.le.s', 'c.eq.d', 'c.lt.d', 'c.le.d', 'cache'}
AREGS = ['a0', 'a1', 'a2', 'a3']


def syms(obj):
    d = {}
    for l in subprocess.check_output(['mips-linux-gnu-nm', '-S', obj]).decode().splitlines():
        p = l.split()
        if len(p) == 4 and p[2] in 'tT':
            d[p[3]] = (int(p[0], 16), int(p[1], 16))
    return d


def disasm(obj, off, sz):
    out = subprocess.check_output(['mips-linux-gnu-objdump', '-d', '-M', 'no-aliases', '-z',
                                   '--start-address=%d' % off, '--stop-address=%d' % (off + sz),
                                   obj]).decode()
    ins = []
    for l in out.splitlines():
        m = re.match(r'\s+[0-9a-f]+:\s+[0-9a-f]{8}\s+(\S+)\s*(.*)', l)
        if m:
            ins.append((m.group(1), [x.strip() for x in m.group(2).split(',')] if m.group(2) else []))
    return ins


def regs_in(ops):
    r = set()
    for o in ops:
        r |= set(re.findall(r'\b(zero|at|v[01]|a[0-3]|t[0-9]|s[0-8]|k[01]|gp|sp|fp|ra)\b', o))
    return r


def dest(mn, ops):
    if mn in NODEST or mn.startswith('b') or mn in ('j', 'jr') or not ops:
        return None
    if mn in ('jal', 'jalr'):
        return 'ra'
    return ops[0]


def sites(ins):
    res = []
    written = set()
    i = 0
    while i < len(ins):
        mn, ops = ins[i]
        d = dest(mn, ops)
        if mn in ('jal', 'jalr'):
            if i + 1 < len(ins):
                dd = dest(*ins[i + 1])
                if dd:
                    written.add(dd)
            # v0 read after call before written?
            used = False
            for mn2, ops2 in ins[i + 2:i + 12]:
                srcs = regs_in(ops2[1:] if dest(mn2, ops2) else ops2)
                if 'v0' in srcs:
                    used = True; break
                if dest(mn2, ops2) == 'v0' or mn2 in ('jal', 'jalr'):
                    break
            res.append((mn, tuple(a for a in AREGS if a in written), used))
            written = set()
            i += 2
            continue
        if d:
            written.add(d)
        i += 1
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('unit')
    ap.add_argument('funcs', nargs='*')
    ap.add_argument('--report', default='report.json')
    ap.add_argument('--max-size', type=int, default=100000)
    a = ap.parse_args()
    nm = 'build/non_matching/src/%s.c.o' % a.unit
    ex = 'expected/src/%s.c.o' % a.unit
    want = a.funcs
    pct = {}
    if not want:
        r = json.load(open(a.report))
        for u in r['units']:
            if u['name'].endswith(a.unit):
                for f in u['functions']:
                    p = f.get('fuzzy_match_percent', 0)
                    if p < 100 and int(f.get('size', 0)) <= a.max_size:
                        want.append(f['name']); pct[f['name']] = p
    sn, se = syms(nm), syms(ex)
    for fn in want:
        if fn not in sn or fn not in se:
            continue
        a_ = sites(disasm(nm, *sn[fn])); b_ = sites(disasm(ex, *se[fn]))
        tag = '%s %d %.1f' % (fn, se[fn][1], pct.get(fn, -1))
        if len(a_) != len(b_):
            print('COUNT  %s  nm=%d tgt=%d' % (tag, len(a_), len(b_)))
            continue
        diffs = []
        for k, (x, y) in enumerate(zip(a_, b_)):
            if x != y:
                diffs.append('#%d nm=%s/%s%s tgt=%s/%s%s' % (k, x[0], ''.join(c[1] for c in x[1]) or '-', '+v0' if x[2] else '',
                                                          y[0], ''.join(c[1] for c in y[1]) or '-', '+v0' if y[2] else ''))
        if diffs:
            print('SITE   %s  %s' % (tag, '; '.join(diffs)))


if __name__ == '__main__':
    main()
