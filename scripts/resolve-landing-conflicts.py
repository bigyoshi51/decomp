#!/usr/bin/env python3
"""Resolve the recurring cherry-pick conflicts of the 1080 landing ritual (agent branch -> agent-d).

Usage: resolve-landing-conflicts.py <conflicted file>...   (run inside the landing worktree, then
       `git add` the files and `git -c core.editor=true cherry-pick --continue`)
Rules:
  Makefile   - post1b2c REPLACE_FUNC_BODY hunk: keep ours, append theirs' missing name=$(VAR) tokens
             - C_FILES filter-out hunk: union of both token lists (order: ours, then theirs' extras)
             - any other hunk: keep both sides (ours then theirs) -- donor blocks stack
  undefined_syms_auto.txt - union by symbol name; names listed in $DROP_PINS (comma-separated)
             are dropped (e.g. an agent's pins for a donor TU that main landed under other names)
Anything else -> exit 2 (resolve by hand). Companion of scripts/land-agent-wave.sh.
"""
import os
import re,sys
DROP=set(x for x in os.environ.get('DROP_PINS','').split(',') if x)
def hunks(lines):
    out=[];i=0;cur=[]
    while i<len(lines):
        l=lines[i]
        if l.startswith('<<<<<<< '):
            ours=[];theirs=[];i+=1
            while not lines[i].startswith('======='): ours.append(lines[i]);i+=1
            i+=1
            while not lines[i].startswith('>>>>>>> '): theirs.append(lines[i]);i+=1
            out.append(('c',ours,theirs))
        else: out.append(('l',l))
        i+=1
    return out
def resolve_makefile(ours,theirs):
    if any('REPLACE_FUNC_BODY' in l and 'post1b2c' in l for l in ours+theirs):
        have=set(t for l in ours for t in re.findall(r'\S+=\$\([A-Z0-9_]+\)',l))
        add=[t for l in theirs for t in re.findall(r'\S+=\$\([A-Z0-9_]+\)',l) if t not in have]
        res=ours[:]; 
        if add: res[-1]=res[-1].rstrip('\n')+' '+' '.join(add)+'\n'
        return res
    if any(l.startswith('C_FILES   := $(filter-out') for l in ours):
        o=ours[0]; t=theirs[0]
        oh,osh=o.split(',$(shell',1); th,_=t.split(',$(shell',1)
        otoks=oh.split(); ttoks=th.split()
        add=[x for x in ttoks if x not in otoks]
        return [' '.join(otoks+add)+',$(shell'+osh]
    # same target-specific variable line on both sides (REPLACE_FUNC_BODY, SUFFIX, clip...):
    # merge tokens instead of stacking two assignments; clip lines take ours (re-probed later)
    def key(l):
        m=re.match(r'^(.*?:\s*[A-Z_]+\s*[:+]?=)', l)
        return m.group(1) if m else None
    if len(ours)==len(theirs) and ours and all(key(a) and key(a)==key(b) for a,b in zip(ours,theirs)):
        res=[]
        for a,b in zip(ours,theirs):
            if 'CLIP_KEEP_ALIGN' in a: res.append(a); continue
            k=key(a); at=a[len(k):].split(); bt=b[len(k):].split()
            res.append(k+' '+' '.join(at+[t for t in bt if t not in at])+'\n')
        return res
    return ours+theirs
def resolve_syms(ours,theirs):
    seen=set(re.match(r'\s*(\S+)\s*=',l).group(1) for l in ours if '=' in l)
    res=ours[:]
    for l in theirs:
        m=re.match(r'\s*(\S+)\s*=',l)
        if not m: continue
        n=m.group(1)
        if n in DROP or n in seen: continue
        seen.add(n); res.append(l)
    return res
for path in sys.argv[1:]:
    if path.endswith('.o'):
        print('skip binary (regenerate via the unit route):', path); continue
    lines=open(path).read().splitlines(keepends=True)
    out=[]
    for h in hunks(lines):
        if h[0]=='l': out.append(h[1]); continue
        _,o,t=h
        if path=='Makefile': out+=resolve_makefile(o,t)
        elif path=='undefined_syms_auto.txt': out+=resolve_syms(o,t)
        else: print('!! cannot resolve',path); sys.exit(2)
    if path=='Makefile':
        # post-pass: a unit's clip / REPLACE_FUNC_BODY := line must exist once; keep the LAST
        def key(l):
            m=re.match(r'^(.*?:\s*[A-Z_]+\s*[:+]?=)', l); return m.group(1) if m else None
        idx={}
        for i,l in enumerate(out):
            k=key(l)
            if k and ('CLIP_KEEP_ALIGN' in k or 'REPLACE_FUNC_BODY :=' in k): idx.setdefault(k,[]).append(i)
        kill=set(i for v in idx.values() if len(v)>1 for i in v[:-1])
        if kill: print('dropped duplicate assignment lines:', len(kill))
        out=[l for i,l in enumerate(out) if i not in kill]
    open(path,'w').write(''.join(out)); print('resolved',path)
