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
    open(path,'w').write(''.join(out)); print('resolved',path)
