#!/usr/bin/env python3
"""Put the mod on top of the "Vagrant Story: Zenith" image (docs: mod/zenith-edition.md).

    python3 -I tools/mod/zenith_port.py --variant default|classic --original VS.bin --zenith ZENITH.bin --mod MOD.bin \\
        --link build/mod/zenith --lbas build/src/include/lbas.h --out OUT.bin

ORIGINAL   the untouched US image (SLUS-01040), MOD the image of the same variant built on the original by tools/mod/build_mod.sh,
ZENITH     the original with zenith_194.ppf applied (any PPF3 applier; the EDC/ECC fields stay as the patch wrote them),
LINK       the output of build_zenith.sh: sections.txt, <section>.bin, nm.txt, hooksyms.txt.
The Zenith image is copied to OUT and these bytes are changed (every other byte is Zenith's, checked by tools/mod/zenith_verify.py):
  * the relocated blob sections in BATTLE.PRG and SLUS_010.40 (each one must overwrite bytes that are original in the Zenith image),
  * the 3-4 patched `jal` (pad read, two label calls, first person), now pointing into the relocated blob,
  * everything else the vanilla mod changes (the first-person pitch words in func_8006EC7C, the button-mask immediates, the menu
    files, MENU7): taken as the byte differences ORIGINAL -> MOD, applied only where Zenith kept the original byte.
    One such byte is also changed by Zenith (BATTLE.PRG 0x800C5D30, the Circle test of the menu at func_800C58F8+0x438): Zenith turned
    it into its own Square test and moved the original test into a code cave in SLUS_010.40 (`j 0x800c5d34` with `andi v0,v0,0x20`
    in the delay slot at 0x8004EB28). The mod's change is applied to the moved copy (0x20 -> 0x40) instead of to the original place.
  * EDC/ECC of every sector that changed are recomputed (Mode 2 Form 1).
"""
import argparse
import json
import re
import shutil
import struct
import sys

SEC = 2352
BASE = 0x80068800          # BATTLE.PRG load address
SB = 0x8000F800            # SLUS_010.40 load address minus its 0x800 header (file offset 0 <-> RAM 0x8000F800)

# ---- EDC / ECC (Mode 2 Form 1) -------------------------------------------------------------------------------------------
EDC_TAB = []
for i in range(256):
    e = i
    for _ in range(8):
        e = (e >> 1) ^ (0xD8018001 if e & 1 else 0)
    EDC_TAB.append(e)
ECC_F = [0] * 256
ECC_B = [0] * 256
for i in range(256):
    j = (i << 1) ^ (0x11D if i & 0x80 else 0)
    ECC_F[i] = j & 0xFF
    ECC_B[i ^ j & 0xFF] = i


def edc(data):
    e = 0
    for b in data:
        e = (e >> 8) ^ EDC_TAB[(e ^ b) & 0xFF]
    return e


def ecc_block(src, major_count, minor_count, major_mult, minor_inc):
    size = major_count * minor_count
    out = bytearray(major_count * 2)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            t = src[index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = ECC_F[a]
        a = ECC_B[ECC_F[a] ^ b]
        out[major] = a
        out[major + major_count] = a ^ b
    return bytes(out)


def fix_form1(sec):
    sec = bytearray(sec)
    assert not (sec[18] & 0x20), "Form 2 sector"
    sec[2072:2076] = edc(sec[16:2072]).to_bytes(4, 'little')
    buf = bytearray(sec[12:2340])
    buf[0:4] = b"\0\0\0\0"
    p = ecc_block(bytes(buf[:2064]), 86, 24, 2, 86)
    q = ecc_block(bytes(buf[:2064]) + p, 52, 43, 86, 88)
    sec[2076:2248] = p
    sec[2248:2352] = q
    return bytes(sec)


# ---- files ------------------------------------------------------------------------------------------------------------------
def load_lbas(path):
    lba, size = {}, {}
    for line in open(path, encoding='utf8'):
        m = re.match(r'#define VS_(\w+)_LBA (\d+)', line)
        if m:
            lba[m.group(1)] = int(m.group(2))
        m = re.match(r'#define VS_(\w+)_SIZE (\d+)', line)
        if m:
            size[m.group(1)] = int(m.group(2))
    return {k: (lba[k], size.get(k, 2048)) for k in lba}


class Disc:
    def __init__(self, path, files):
        self.path, self.files = path, files
        self.starts = sorted((v[0], v[0] + (v[1] + 2047) // 2048, k) for k, v in files.items())

    def file_of(self, sector):
        import bisect
        i = bisect.bisect_right([s[0] for s in self.starts], sector) - 1
        if i >= 0 and self.starts[i][0] <= sector < self.starts[i][1]:
            return self.starts[i][2]
        return None

    def read(self, name):
        lba, size = self.files[name]
        out = bytearray()
        with open(self.path, 'rb') as f:
            f.seek(lba * SEC)
            for _ in range((size + 2047) // 2048):
                out += f.read(SEC)[24:2072]
        return bytes(out)

    def sector(self, n):
        with open(self.path, 'rb') as f:
            f.seek(n * SEC)
            return f.read(SEC)


def image_diff(a, b):
    """sector -> list of user-data offsets (0..2047) whose bytes differ"""
    out = {}
    with open(a, 'rb') as fa, open(b, 'rb') as fb:
        n = 0
        while True:
            x, y = fa.read(SEC * 2048), fb.read(SEC * 2048)
            if not x:
                break
            if x != y:
                for s in range(0, len(x), SEC):
                    if x[s:s + SEC] != y[s:s + SEC]:
                        d = [k - 24 for k in range(24, 2072) if x[s + k] != y[s + k]]
                        if d:
                            out[n + s // SEC] = d
            n += len(x) // SEC
    return out


def jal(t):
    return 0x0C000000 | ((t >> 2) & 0x03FFFFFF)


# build_mod.sh DEAD list + tail: where the vanilla mod keeps its code (replaced here)
OLD_RANGES = [(0x800F5924, 0x800F6000), (0x800B26B8, 496), (0x800D197C, 412), (0x800AA108, 392), (0x800D155C, 284), (0x80099854, 268),
              (0x8009BD90, 204), (0x800733F8, 140), (0x8007FF8C, 116), (0x80099FA8, 128), (0x800A1B28, 116), (0x800A0B5C, 132),
              (0x800A071C, 76), (0x800AAC80, 92)]
OLD = [(a, b if b > 0x80000000 else a + b) for a, b in OLD_RANGES]
HOOKS = {0x8007991C: ('vs_main_processPadState', 'wswap_entry'), 0x800CA0A4: ('func_800C9EB8', 'wslot_label'),
         0x800CA1AC: ('func_800C9EB8', 'wslot_label'), 0x8007A10C: ('func_8006EC7C', 'wfp_look')}
FPF = (0x8006EC7C, 0x8006EC7C + 660)
# Zenith's copy of the Circle test of func_800C58F8: SLUS_010.40 0x8004EB28 (see the docstring)
PORT_SRC, PORT_DST = 0x800C5D30, 0x8004EB28


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--variant', required=True, choices=('default', 'classic'))
    ap.add_argument('--original', required=True)
    ap.add_argument('--zenith', required=True)
    ap.add_argument('--mod', required=True)
    ap.add_argument('--link', required=True)
    ap.add_argument('--lbas', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--report')
    a = ap.parse_args()
    v = a.variant
    files = load_lbas(a.lbas)
    orig, zen, mod = Disc(a.original, files), Disc(a.zenith, files), Disc(a.mod, files)
    secs = []
    for l in open(a.link + '/sections.txt'):
        name, size, vma = l.split()
        data = open('%s/%s.bin' % (a.link, name[1:]), 'rb').read()
        assert len(data) == int(size, 16)
        secs.append((int(vma, 16), data, name))
    nm = {}
    for l in open(a.link + '/nm.txt'):
        p = l.split()
        if len(p) == 3:
            nm[p[2]] = int(p[0], 16)
    hs = {}
    for l in open(a.link + '/hooksyms.txt'):
        m = re.match(r'(\w+) = (0x[0-9A-Fa-f]+);', l)
        if m:
            hs[m.group(1)] = int(m.group(2), 16)

    o_prg, z_prg, m_prg = orig.read('BATTLE_PRG'), zen.read('BATTLE_PRG'), mod.read('BATTLE_PRG')
    o_slus, z_slus = orig.read('SLUS_010_40'), zen.read('SLUS_010_40')
    n_prg, n_slus = bytearray(z_prg), bytearray(z_slus)
    rep = {'variant': v, 'hooks': [], 'fp': [], 'imm': [], 'blobs': [], 'menu': [], 'ports': []}

    # --- the vanilla mod's own changes of BATTLE.PRG outside the code it relocates
    extra = []
    for i in range(len(o_prg)):
        if o_prg[i] != m_prg[i]:
            ad = BASE + i
            if any(s <= ad < e for s, e in OLD) or any(h <= ad < h + 4 for h in HOOKS):
                continue
            extra.append(i)
    clashes = []
    for i in extra:
        ad = BASE + i
        kind = 'fp' if FPF[0] <= ad < FPF[1] else 'imm'
        if kind == 'imm' and not (0x80079000 <= ad < 0x800CA000):
            sys.exit('unexpected change of the vanilla mod at %08X' % ad)
        if z_prg[i] != o_prg[i]:
            clashes.append((ad, o_prg[i], z_prg[i], m_prg[i]))
            continue
        n_prg[i] = m_prg[i]
        rep[kind].append('%08X: %02X -> %02X' % (ad, o_prg[i], m_prg[i]))
    for ad, o, z, m in clashes:
        if ad != PORT_SRC:
            sys.exit('same-byte clash %08X: original %02X Zenith %02X mod %02X (not handled)' % (ad, o, z, m))
        cave = PORT_DST - SB
        if struct.unpack_from('<II', z_slus, cave - 4) != (0x08000000 | ((0x800C5D34 >> 2) & 0x3FFFFFF), 0x30420020):
            sys.exit('Zenith code cave for 0x800C5D30 not found in SLUS_010.40 (another Zenith version?)')
        if z_slus[cave] != 0x20 or m != 0x40:
            sys.exit('unexpected bytes at the Zenith cave')
        n_slus[cave] = m
        rep['ports'].append('BATTLE.PRG %08X (%02X -> %02X in the vanilla mod) is Zenith\'s Square test (%02X); the original test moved to SLUS_010.40 %08X: 20 -> 40'
                            % (ad, o, m, z, PORT_DST))

    # --- hooks
    for ad, (old_sym, new_sym) in HOOKS.items():
        if v == 'classic' and new_sym == 'wfp_look':
            continue
        off = ad - BASE
        w = struct.unpack_from('<I', z_prg, off)[0]
        if not (w == jal(hs[old_sym]) == struct.unpack_from('<I', o_prg, off)[0]):
            sys.exit('hook site %08X is not jal %s in the Zenith image: %08x' % (ad, old_sym, w))
        struct.pack_into('<I', n_prg, off, jal(nm[new_sym]))
        rep['hooks'].append('%08X: jal %08X (%s) -> jal %08X (%s)' % (ad, hs[old_sym], old_sym, nm[new_sym], new_sym))

    # --- relocated sections
    for vma, data, name in secs:
        if 0x80068800 <= vma and vma + len(data) <= 0x800F6000:
            off = vma - BASE
            if o_prg[off:off + len(data)] != z_prg[off:off + len(data)]:
                sys.exit('%s: Zenith changed the bytes at %08X' % (name, vma))
            n_prg[off:off + len(data)] = data
            rep['blobs'].append('BATTLE.PRG %08X..%08X %d bytes %s' % (vma, vma + len(data), len(data), name))
        else:
            off = vma - SB
            if not (0 <= off and off + len(data) <= len(z_slus)) or o_slus[off:off + len(data)] != z_slus[off:off + len(data)]:
                sys.exit('%s: SLUS_010.40 bytes differ at %08X' % (name, vma))
            n_slus[off:off + len(data)] = data
            rep['blobs'].append('SLUS_010.40 %08X..%08X %d bytes %s' % (vma, vma + len(data), len(data), name))

    # --- the other files of the vanilla mod (menus, MENU7) and the ISO directory
    other = {}
    d = image_diff(a.original, a.mod)
    for sec, offs in d.items():
        f = orig.file_of(sec)
        if f == 'BATTLE_PRG':
            continue
        so, sm, sz = orig.sector(sec), mod.sector(sec), zen.sector(sec)
        if f is None:
            if sec != 192 or any(sm[24 + o] != sz[24 + o] for o in offs):
                sys.exit('sector %d (system area) differs between the mod and Zenith' % sec)
            continue          # the BATTLE.PRG size in the ISO directory: Zenith and the mod both write 579584
        for o in offs:
            if sz[24 + o] != so[24 + o]:
                sys.exit('same-byte clash in %s sector %d offset 0x%X: original %02X Zenith %02X mod %02X' % (f, sec, o, so[24 + o], sz[24 + o], sm[24 + o]))
            other.setdefault(sec, {})[o] = sm[24 + o]
        rep['menu'].append('%s (LBA %d): %s' % (f, sec, ' '.join('0x%X:%02X->%02X' % (o, so[24 + o], sm[24 + o]) for o in offs)))

    # --- write
    shutil.copyfile(a.zenith, a.out)
    changed = []
    with open(a.out, 'r+b') as f:
        def put(name, new, old):
            lba, size = files[name]
            for k in range((size + 2047) // 2048):
                x, y = old[k * 2048:(k + 1) * 2048], new[k * 2048:(k + 1) * 2048]
                if x != y:
                    f.seek((lba + k) * SEC)
                    s = bytearray(f.read(SEC))
                    assert s[24:2072] == x
                    s[24:2072] = y
                    f.seek((lba + k) * SEC)
                    f.write(fix_form1(bytes(s)))
                    changed.append(lba + k)
        put('BATTLE_PRG', bytes(n_prg), z_prg)
        put('SLUS_010_40', bytes(n_slus), z_slus)
        for sec, ch in other.items():
            f.seek(sec * SEC)
            s = bytearray(f.read(SEC))
            for o, b in ch.items():
                s[24 + o] = b
            f.seek(sec * SEC)
            f.write(fix_form1(bytes(s)))
            changed.append(sec)
    rep['sectors_written'] = sorted(changed)
    if a.report:
        json.dump(rep, open(a.report, 'w'), indent=1)
    print('%s: %d sectors rewritten (EDC/ECC recomputed) -> %s' % (v, len(changed), a.out))
    for k in ('hooks', 'fp', 'imm', 'ports', 'blobs'):
        print('  %s: %d' % (k, len(rep[k])))


if __name__ == '__main__':
    main()
