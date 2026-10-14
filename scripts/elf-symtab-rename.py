#!/usr/bin/env python3
"""Metadata-only ELF32-BE symbol rename (NAME and NAME.NON_MATCHING): appends a new .strtab at the end of the file.
Usage: elf-symtab-rename.py <in.o> <out.o> OLD=NEW ...   (objcopy --redefine-sym rewrites the object; avoid)"""
import struct,sys
src,dst=sys.argv[1],sys.argv[2]
ren=dict(a.split('=') for a in sys.argv[3:])
d=bytearray(open(src,'rb').read())
shoff=struct.unpack_from('>I',d,0x20)[0]; shentsize,shnum,shstrndx=struct.unpack_from('>HHH',d,0x2E)
sh=[list(struct.unpack_from('>IIIIIIIIII',d,shoff+i*shentsize)) for i in range(shnum)]
def nm(off,tab):
    s=tab[4]+off; return d[s:d.index(b'\0',s)].decode()
names=[nm(x[0],sh[shstrndx]) for x in sh]
si=names.index('.symtab'); st=sh[si]; ti=st[6]; strt=sh[ti]
newstr=bytearray(d[strt[4]:strt[4]+strt[5]])
for i in range(st[5]//16):
    o=st[4]+i*16
    name=struct.unpack_from('>I',d,o)[0]; n=nm(name,strt)
    for old,new in ren.items():
        if n in (old, old+'.NON_MATCHING'):
            nn=n.replace(old,new); off=len(newstr); newstr+=nn.encode()+b'\0'
            struct.pack_into('>I',d,o,off); print('rename',n,'->',nn)
# append new strtab at end (aligned 4)
while len(d)%4: d.append(0)
newoff=len(d); d+=newstr
sh[ti][4]=newoff; sh[ti][5]=len(newstr)
struct.pack_into('>IIIIIIIIII',d,shoff+ti*shentsize,*sh[ti])
open(dst,'wb').write(d)
