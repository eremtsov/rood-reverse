#!/usr/bin/env python3
"""Check a combined image against the Zenith image it was made from (tools/mod/zenith_port.py, mod/zenith-edition.md).

    python3 -I tools/mod/zenith_verify.py --variant V --original ORIG.bin --zenith ZEN.bin --mod MOD.bin --combined OUT.bin \\
        --ppf zenith_194.ppf --report build/mod/zenith/report.json --lbas build/src/include/lbas.h

 * every byte that differs between the combined and the Zenith image is one of the mod (relocated sections and hooks listed in
   the report, the first-person / button-immediate bytes, the bytes the vanilla mod changes in the other files),
 * every byte that the PPF writes is the same in the combined image (except the one ported byte and the EDC/ECC fields of the
   sectors that were rewritten),
 * EDC and ECC are valid in every rewritten sector, the image size is unchanged.
"""
import argparse
import json
import struct
import sys

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zenith_port as zp

ap = argparse.ArgumentParser()
for k in ('variant', 'original', 'zenith', 'mod', 'combined', 'ppf', 'report', 'lbas'):
    ap.add_argument('--' + k, required=True)
a = ap.parse_args()
files = zp.load_lbas(a.lbas)
disc = zp.Disc(a.zenith, files)
rep = json.load(open(a.report))
SEC = zp.SEC

assert os.path.getsize(a.combined) == os.path.getsize(a.zenith)
allowed = set()


def allow(name, ram, n):
    base = zp.BASE if name == 'BATTLE_PRG' else zp.SB
    lba = files[name][0]
    for k in range(n):
        o = ram - base + k
        allowed.add((lba + o // 2048, o % 2048))


for b in rep['blobs']:
    p = b.split()
    s, e = p[1].split('..')
    allow('BATTLE_PRG' if p[0] == 'BATTLE.PRG' else 'SLUS_010_40', int(s, 16), int(e, 16) - int(s, 16))
for h in rep['hooks']:
    allow('BATTLE_PRG', int(h.split(':')[0], 16), 4)
for x in rep['fp'] + rep['imm']:
    allow('BATTLE_PRG', int(x.split(':')[0], 16), 1)
if rep['ports']:
    allow('SLUS_010_40', zp.PORT_DST, 1)
orig = zp.Disc(a.original, files)
for sec, offs in zp.image_diff(a.original, a.mod).items():
    f = orig.file_of(sec)
    if f not in (None, 'BATTLE_PRG'):
        for o in offs:
            allowed.add((sec, o))

changed, bad = [], []
with open(a.combined, 'rb') as fc, open(a.zenith, 'rb') as fz:
    n = 0
    while True:
        x, y = fc.read(SEC * 2048), fz.read(SEC * 2048)
        if not x:
            break
        if x != y:
            for s in range(0, len(x), SEC):
                if x[s:s + SEC] != y[s:s + SEC]:
                    sec = n + s // SEC
                    changed.append(sec)
                    assert x[s:s + 24] == y[s:s + 24], 'header differs in sector %d' % sec
                    for k in range(24, 2072):
                        if x[s + k] != y[s + k] and (sec, k - 24) not in allowed:
                            bad.append((sec, k - 24))
        n += len(x) // SEC
print('sectors that differ from the Zenith image: %d; bytes outside the mod\'s own set: %d' % (len(changed), len(bad)))
assert not bad, bad[:10]
# EDC/ECC
ok = 0
with open(a.combined, 'rb') as fc:
    for sec in changed:
        fc.seek(sec * SEC)
        s = fc.read(SEC)
        assert zp.fix_form1(s) == s, 'EDC/ECC wrong in sector %d' % sec
        ok += 1
print('EDC/ECC valid in all %d rewritten sectors' % ok)
# the PPF bytes
p = open(a.ppf, 'rb').read()
assert p[:5] == b'PPF30' and p[56] == 0 and p[57] == 0 and p[58] == 0
pos, nb, skipped = 60, 0, 0
ported = {(files['SLUS_010_40'][0] + (zp.PORT_DST - zp.SB) // 2048) * SEC + 24 + (zp.PORT_DST - zp.SB) % 2048}
chs = set(changed)
with open(a.combined, 'rb') as fc:
    while pos < len(p) and p[pos:pos + 18] != b'@BEGIN_FILE_ID.DIZ':
        off = struct.unpack('<Q', p[pos:pos + 8])[0]
        n = p[pos + 8]
        d = p[pos + 9:pos + 9 + n]
        pos += 9 + n
        for k, b in enumerate(d):
            o = off + k
            sec, ins = divmod(o, SEC)
            if sec in chs and not (24 <= ins < 2072):
                continue
            if rep['ports'] and o in ported:
                skipped += 1
                continue
            fc.seek(o)
            if fc.read(1)[0] != b:
                sys.exit('PPF byte at image offset %d is not preserved' % o)
            nb += 1
print('%d PPF bytes preserved (%d deliberately ported)' % (nb, skipped))
print('OK')
