#!/usr/bin/env python3
"""List candidate dead functions of BATTLE.PRG in one pass (then confirm each with check_dead.py).

    python3 -I tools/mod/find_dead.py [MIN_SIZE]

Candidate ranges are exactly [function start, next function start), the starts being the functions known to the
decompilation (see function_starts(): func_XXXXXXXX names in src/BATTLE/BATTLE.PRG, type:func symbols, auto-undefined
functions). The guessed `jr ra` boundaries of the old version are gone: func_800D9910 was one of them and turned out to
be the second half of func_800D98E8.

A range is a candidate when, in every file that can be resident together with BATTLE.PRG (BATTLE.PRG, SLUS_010.40,
INITBTL.PRG, MENU/*.PRG, GIM/SCREFF2.PRG, EFFECT/*.BIN):
  * nothing outside it has a j/jal, an aligned raw word, a lui+addiu/ori/load/store pair or a PC-relative branch
    to any address inside it,
  * nothing at all (also from the preceding function) refers to the delay slot of the `jr ra` / `j` before it,
  * the last two words before it are `jr ra` (or `j`) + delay slot.
This is the same test as check_dead.py, run for every function at once.
"""
import array
import bisect
import os
import re
import struct
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
BASE = 0x80068800
CODE_END = BASE + 0x7F984
min_size = int(sys.argv[1], 0) if len(sys.argv) > 1 else 64

def function_starts():
    """same definition as check_dead.py: func_XXXXXXXX names in src/BATTLE/BATTLE.PRG, type:func symbols, auto-undefined functions"""
    starts = {}
    for l in open(os.path.join(ROOT, 'config/BATTLE/BATTLE.PRG/symbol_addrs.txt')):
        m = re.match(r'\s*(\w+)\s*=\s*(0x[0-9A-Fa-f]+);\s*(.*)', l)
        if m and 'type:func' in m.group(3) and BASE <= int(m.group(2), 16) < CODE_END:
            starts.setdefault(int(m.group(2), 16), m.group(1))
    for l in open(os.path.join(ROOT, 'build/config/BATTLE/BATTLE.PRG/undefined_funcs_auto.txt')):
        m = re.match(r'\s*(\w+)\s*=\s*(0x[0-9A-Fa-f]+);', l)
        if m and BASE <= int(m.group(2), 16) < CODE_END:
            starts.setdefault(int(m.group(2), 16), m.group(1))
    pat = re.compile(r'(?<![A-Za-z0-9_])func_(8[0-9A-Fa-f]{7})(?![A-Za-z0-9_])')
    for dp, _, names in os.walk(os.path.join(ROOT, 'src/BATTLE/BATTLE.PRG')):
        for n in names:
            if n.endswith(('.c', '.h', '.s')):
                for m in pat.finditer(open(os.path.join(dp, n), errors='replace').read()):
                    a = int(m.group(1), 16)
                    if BASE <= a < CODE_END and a % 4 == 0:
                        starts.setdefault(a, 'func_' + m.group(1).upper())
    return starts


allsyms = function_starts()
funcsyms = dict(allsyms)
bounds = sorted(allsyms)
ranges = []
for s in sorted(funcsyms):
    i = bisect.bisect_right(bounds, s)
    e = bounds[i] if i < len(bounds) else CODE_END
    ranges.append((s, e, funcsyms[s]))
print('%d function symbols' % len(ranges), file=sys.stderr)
starts_arr = [r[0] for r in ranges]
start_index = {r[0]: i for i, r in enumerate(ranges)}


def func_of(addr):
    i = bisect.bisect_right(starts_arr, addr) - 1
    if i < 0:
        return None
    s, e, n = ranges[i]
    return i if s <= addr < e else None


refs = {i: [] for i in range(len(ranges))}


def note(t, kind, rel, off, src_f):
    f = func_of(t)
    if f is not None and src_f != f:
        refs[f].append((kind, rel, off, t))
    d = start_index.get(t + 4)     # the delay slot in front of a candidate
    if d is not None:
        refs[d].append((kind + '->delay slot', rel, off, t))


CO = []
for dp, _, names in os.walk(os.path.join(ROOT, 'data')):
    for n in names:
        rel = os.path.relpath(os.path.join(dp, n), os.path.join(ROOT, 'data')).replace(os.sep, '/')
        if (rel in ('BATTLE/BATTLE.PRG', 'SLUS_010.40', 'BATTLE/INITBTL.PRG', 'GIM/SCREFF2.PRG')
                or (rel.startswith('MENU/') and rel.endswith('.PRG'))
                or (rel.startswith('EFFECT/') and rel.endswith('.BIN'))):
            CO.append(rel)


def load_base(rel):
    if rel == 'BATTLE/BATTLE.PRG':
        return BASE, 0x7F984
    if rel == 'SLUS_010.40':
        return 0x80010000 - 0x800, None
    if rel in ('BATTLE/INITBTL.PRG', 'GIM/SCREFF2.PRG', 'MENU/MAINMENU.PRG') or rel.startswith('EFFECT/'):
        return 0x800F9800, None
    return 0x80102800, None


LOADSTORE = (0x08, 0x09, 0x0D, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x28, 0x29, 0x2A, 0x2B, 0x2E)
for rel in sorted(CO):
    data = open(os.path.join(ROOT, 'data', rel), 'rb').read()
    base, limit = load_base(rel)
    n = len(data) & ~3
    words = array.array('I')
    words.frombytes(data[:n])
    code_n = (limit or len(data)) // 4
    for i, w in enumerate(words):
        src = base + i * 4
        src_f = func_of(src) if rel == 'BATTLE/BATTLE.PRG' else None
        op = w >> 26
        iscode = i < code_n
        if BASE <= w < CODE_END + 4 and (w & 3) == 0:
            note(w, 'word', rel, i * 4, src_f)
        if iscode and (op == 2 or op == 3):
            t = 0x80000000 | ((w & 0x03FFFFFF) << 2)
            if BASE <= t < CODE_END:
                note(t, 'jal' if op == 3 else 'j', rel, i * 4, src_f)
        elif iscode and (op in (4, 5, 6, 7) or (op == 1 and ((w >> 16) & 31) in (0, 1, 16, 17))):
            simm = w & 0xFFFF
            if simm & 0x8000:
                simm -= 0x10000
            t = src + 4 + simm * 4
            if BASE <= t < CODE_END:
                note(t, 'branch', rel, i * 4, src_f)
        elif iscode and op == 0x0F and 0x8006 <= (w & 0xFFFF) <= 0x800F:
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
                    if BASE <= val < CODE_END:
                        note(val, 'lui', rel, i * 4, src_f)
                if op2 == 0 and rd2 == reg and (w2 & 63) not in (8, 0x18, 0x19, 0x1A, 0x1B):
                    break
                if op2 != 0 and op2 not in (4, 5, 6, 7, 1, 2, 3, 0x28, 0x29, 0x2A, 0x2B, 0x2E) and rt2 == reg:
                    break

prg = open(os.path.join(ROOT, 'data/BATTLE/BATTLE.PRG'), 'rb').read()
out = []
for i, (s, e, n) in enumerate(ranges):
    size = e - s
    if size < min_size or refs[i]:
        continue
    pw = struct.unpack_from('<II', prg, s - BASE - 8)
    if not (pw[0] == 0x03E00008 or (pw[0] >> 26) == 2):
        continue
    out.append((s, size, n))
for s, size, n in out:
    print('%08X %5d %s' % (s, size, n))
print('%d candidates >= %d bytes, %d bytes total' % (len(out), min_size, sum(o[1] for o in out)), file=sys.stderr)
