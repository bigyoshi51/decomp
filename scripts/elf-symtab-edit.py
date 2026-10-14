#!/usr/bin/env python3
"""Metadata-only ELF32-BE symtab edit: set value/size of NAME (and NAME.NON_MATCHING).
Usage: elf-symtab-edit.py <in.o> <out.o> NAME:VALUE:SIZE ...   (empty VALUE = keep)
Use with elf-symtab-rename.py when a boundary fix moves a head by a word; verify .text + objdump -r unchanged."""
import struct,sys
src,dst=sys.argv[1],sys.argv[2]
edits={}
for a in sys.argv[3:]:
    n,v,sz=a.split(':'); edits[n]=(int(v,0) if v else None,int(sz,0))
d=bytearray(open(src,'rb').read())
shoff=struct.unpack_from('>I',d,0x20)[0]; shentsize,shnum,shstrndx=struct.unpack_from('>HHH',d,0x2E)
sh=[struct.unpack_from('>IIIIIIIIII',d,shoff+i*shentsize) for i in range(shnum)]
def nm(off,tab):
    s=tab[4]+off; return d[s:d.index(b'\0',s)].decode()
names=[nm(x[0],sh[shstrndx]) for x in sh]
st=sh[names.index('.symtab')]; strt=sh[st[6]]
done=set()
for i in range(st[5]//16):
    o=st[4]+i*16
    name,val,size,info,other,shndx=struct.unpack_from('>IIIBBH',d,o)
    n=nm(name,strt)
    for base in edits:
        if n in (base, base+'.NON_MATCHING'):
            v,sz=edits[base]
            if v is not None: val=v
            struct.pack_into('>IIIBBH',d,o,name,val,sz,info,other,shndx); done.add(n); print('edit',n,hex(val),hex(sz))
open(dst,'wb').write(d)
print(len(done))
