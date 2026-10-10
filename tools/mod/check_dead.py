#!/usr/bin/env python3
"""Prove that nothing references an address range of BATTLE.PRG (default: func_800E1EAC).

    python3 -I tools/mod/check_dead.py [START SIZE [NAME]]   (hex start, decimal/hex size)

Scans EVERY file under data/ (the original game files; 5163 of them) for
  * j / jal whose target lies in the range,
  * lui + (addiu | ori | load | store) pairs that build an address in the range
    (the destination register is followed until it is overwritten),
  * raw 32-bit words (4-aligned and unaligned) equal to an address in the range
    (function pointer tables, jump tables, scripts).
References coming from the range itself are ignored. The result is classified:
  * a "real" reference is an aligned one found in a file that can be resident together
    with BATTLE.PRG: BATTLE.PRG itself, SLUS_010.40, INITBTL.PRG, MENU/*.PRG,
    GIM/SCREFF2.PRG, EFFECT/*.BIN.
    (TITLE.PRG and ENDING.PRG are loaded at the same address as BATTLE.PRG and never
    run together with it; every other file is data: video, audio, maps, models.)
and, added after func_800E1EAC turned out to be live (it was reached by a PC-relative
tail branch, `bgez $zero, func_800E1EAC` in func_800DB5B8, invisible to the scans above):
  * PC-relative branches (beq/bne/blez/bgtz/bltz/bgez/bltzal/bgezal, including the
    "b" idioms `beq $zero,$zero` / `bgez $zero`) whose target lies in the range, from
    every co-resident file decoded at its load address (BATTLE.PRG: its code part),
  * fall-through from the preceding function (it must end in `jr ra`+delay slot or `j`),
  * with NAME: the name of the function must not occur anywhere else in src/ (C, headers,
    assembly) and in build/src/ outside the function's own generated .s file.
Exit code 0 when there is no real reference. Takes a few minutes.
"""
import array
import os
import re
import struct
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
BASE = 0x80068800
start = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x800B26B8
size = int(sys.argv[2], 0) if len(sys.argv) > 2 else 496
fname = sys.argv[3] if len(sys.argv) > 3 else None
end = start + size

CO_RESIDENT = lambda rel: (rel in ('BATTLE/BATTLE.PRG', 'SLUS_010.40', 'BATTLE/INITBTL.PRG', 'GIM/SCREFF2.PRG')
                           or (rel.startswith('MENU/') and rel.endswith('.PRG'))
                           or (rel.startswith('EFFECT/') and rel.endswith('.BIN')))

LOADSTORE = (0x08, 0x09, 0x0D, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x28, 0x29, 0x2A, 0x2B, 0x2E)
hits = []
nfiles = 0
for dirpath, _, names in os.walk(os.path.join(ROOT, 'data')):
    for name in sorted(names):
        path = os.path.join(dirpath, name)
        rel = os.path.relpath(path, os.path.join(ROOT, 'data')).replace(os.sep, '/')
        data = open(path, 'rb').read()
        nfiles += 1
        n = len(data) & ~3
        words = array.array('I')
        words.frombytes(data[:n])
        if sys.byteorder != 'little':
            words.byteswap()
        inside = lambda off: rel == 'BATTLE/BATTLE.PRG' and start <= BASE + off < end
        for i, w in enumerate(words):
            op = w >> 26
            if op == 2 or op == 3:
                t = 0x80000000 | ((w & 0x03FFFFFF) << 2)
                if start <= t < end and not inside(i * 4):
                    hits.append(('jal' if op == 3 else 'j', rel, i * 4, t))
            elif start <= w < end:
                if not inside(i * 4):
                    hits.append(('word', rel, i * 4, w))
            elif op == 0x0F and 0x800E <= (w & 0xFFFF) <= 0x8010:
                hi = w & 0xFFFF
                reg = (w >> 16) & 31
                for j in range(1, 40):
                    if i + j >= len(words):
                        break
                    w2 = words[i + j]
                    op2 = w2 >> 26
                    rs2, rt2, rd2 = (w2 >> 21) & 31, (w2 >> 16) & 31, (w2 >> 11) & 31
                    if op2 in LOADSTORE and rs2 == reg:
                        imm = w2 & 0xFFFF
                        simm = imm - 0x10000 if imm & 0x8000 else imm
                        val = ((hi << 16) | imm) if op2 == 0x0D else (((hi << 16) + simm) & 0xFFFFFFFF)
                        if start <= val < end and not inside(i * 4):
                            hits.append(('lui', rel, i * 4, val))
                    # stop following the register once it is overwritten
                    if op2 == 0 and rd2 == reg and (w2 & 63) not in (8, 0x18, 0x19, 0x1A, 0x1B):
                        break
                    if op2 != 0 and op2 not in (4, 5, 6, 7, 1, 2, 3, 0x28, 0x29, 0x2A, 0x2B, 0x2E) and rt2 == reg:
                        break
        # unaligned raw words
        for m in re.finditer(rb'(?=[\x00-\xff]{2}[\x0e-\x0f]\x80)', data):
            k = m.start()
            if k % 4:
                v = struct.unpack_from('<I', data, k)[0]
                if start <= v < end:
                    hits.append(('word-unaligned', rel, k, v))

# ---- PC-relative branches ---------------------------------------------------------
# load addresses of the files that can be resident together with BATTLE.PRG
def load_base(rel):
    if rel == 'BATTLE/BATTLE.PRG':
        return BASE, 0x7F984          # code part only (data starts at file offset 0x7F984)
    if rel == 'SLUS_010.40':
        return 0x80010000 - 0x800, None
    if rel in ('BATTLE/INITBTL.PRG', 'GIM/SCREFF2.PRG', 'MENU/MAINMENU.PRG') or (rel.startswith('EFFECT/') and rel.endswith('.BIN')):
        return 0x800F9800, None
    if rel.startswith('MENU/') and rel.endswith('.PRG'):
        return 0x80102800, None
    return None, None

branch_hits = []
nbr = 0
for dirpath, _, names in os.walk(os.path.join(ROOT, 'data')):
    for name in sorted(names):
        rel = os.path.relpath(os.path.join(dirpath, name), os.path.join(ROOT, 'data')).replace(os.sep, '/')
        base, limit = load_base(rel)
        if base is None:
            continue
        data = open(os.path.join(dirpath, name), 'rb').read()
        n = min(len(data), limit or len(data)) & ~3
        words = array.array('I')
        words.frombytes(data[:n])
        if sys.byteorder != 'little':
            words.byteswap()
        nbr += 1
        for i, w in enumerate(words):
            op = w >> 26
            if op in (4, 5, 6, 7) or (op == 1 and ((w >> 16) & 31) in (0, 1, 16, 17)):
                simm = w & 0xFFFF
                if simm & 0x8000:
                    simm -= 0x10000
                src = base + i * 4
                t = src + 4 + simm * 4
                if start <= t < end and not (start <= src < end):
                    branch_hits.append((rel, i * 4, src, t))
print('branch scan: %d co-resident files decoded at their load addresses' % nbr)
print('PC-relative branches into the range from outside it: %d' % len(branch_hits))
for h in branch_hits[:20]:
    print('   BRANCH %-24s +0x%06X (RAM %08X) -> %08X' % h)

# ---- fall-through from the previous function ------------------------------------------
prg = open(os.path.join(ROOT, 'data/BATTLE/BATTLE.PRG'), 'rb').read()
fallthrough = False
if BASE <= start < BASE + 0x7F984:
    pw = struct.unpack_from('<II', prg, start - BASE - 8)
    ends = pw[0] == 0x03E00008 or (pw[0] >> 26) == 2
    print('previous function ends with "%08X %08X": %s' % (pw[0], pw[1], 'jr ra / j + delay slot (no fall-through)' if ends else 'MAY FALL THROUGH'))
    fallthrough = not ends

# ---- name occurrences --------------------------------------------------------------------
name_extra = []
if fname:
    pat = re.compile(r'(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])' % re.escape(fname))
    for sub in ('src', 'build/src'):
        for dirpath, _, names in os.walk(os.path.join(ROOT, sub)):
            for nm_ in names:
                if not nm_.endswith(('.c', '.h', '.s', '.inc')):
                    continue
                path = os.path.join(dirpath, nm_)
                if sub == 'build/src' and nm_ == fname + '.s':
                    continue
                text = open(path, errors='replace').read()
                c = len(pat.findall(text))
                if c and not (sub == 'src' and nm_.endswith('.c') and c == 1):
                    name_extra.append((os.path.relpath(path, ROOT), c))
    print('occurrences of the name "%s" other than its one definition: %s' % (fname, name_extra or 'none'))

print('scanned %d files for references into 0x%08X..0x%08X (%d bytes)' % (nfiles, start, end, size))
# an unaligned match can only be a coincidence of neighbouring bytes (tables of pointers are 4-aligned)
real = [h for h in hits if CO_RESIDENT(h[1]) and h[0] != 'word-unaligned']
noise = [h for h in hits if not (CO_RESIDENT(h[1]) and h[0] != 'word-unaligned')]
print('references from co-resident code/data files: %d' % len(real))
for h in real:
    print('   REAL  %-14s %-28s +0x%06X -> 0x%08X' % h)
print('references that cannot be calls or pointers (unaligned matches, files that never run together with BATTLE.PRG: overlays at the same address, video, audio, maps...): %d' % len(noise))
for h in noise[:12]:
    print('   noise %-14s %-28s +0x%06X -> 0x%08X' % h)
if len(noise) > 12:
    print('   ... and %d more (all in non-code files)' % (len(noise) - 12))
by_ext = {}
for kind, rel, off, val in noise:
    key = os.path.splitext(rel)[1] or rel
    e = by_ext.setdefault(key, [0, 0, 0])
    e[0] += 1
    e[1] += (val % 4 == 0)
    e[2] += (val == start)
print('noise by file type [hits, with a 4-aligned value, equal to the exact entry 0x%08X]:' % start)
for key, e in sorted(by_ext.items()):
    print('   %-8s %s' % (key, e))
bad = bool(real or branch_hits or fallthrough or name_extra)
print('RESULT:', 'NO REFERENCES (range is dead)' if not bad else 'REFERENCED')
sys.exit(1 if bad else 0)
