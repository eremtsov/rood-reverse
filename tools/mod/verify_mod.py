#!/usr/bin/env python3
"""Static verification of the weapon-swap mod build; writes a text log.

    python3 -I tools/mod/verify_mod.py OUTPUT_LOG

Run after tools/mod/build_mod.sh. Needs the previous mod build in .baseline/
(a copy of build/data and the image sha256 taken before the mod was added).
"""
import hashlib
import os
import re
import struct
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
os.chdir(ROOT)
CROSS = 'mipsel-linux-gnu-'
out = []
ok = True


def p(*a):
    out.append(' '.join(str(x) for x in a))


def sh(cmd):
    return subprocess.check_output(cmd, shell=True, text=True, executable='/bin/bash')


def fail(msg):
    global ok
    ok = False
    p('*** FAIL:', msg)


PRG_RAM = 0x80068800
TAIL_OFF = 0x8D124
HOOK_OFF = 0x1111C
BLOB_RAM = 0x800F5924
BLOB_LIMIT = 0x800F6000

p('=' * 78)
p('Vagrant Story weapon-swap mod: build verification log')
p('=' * 78)
p('commit:', sh('git rev-parse HEAD').strip(), '(+ uncommitted changes, if any:',
  sh('git status --short | wc -l').strip(), 'entries)')
p('compiler: tools/old-gcc/2.8.1-psx/cc1 -G0 -O2 -Wall -fno-builtin -funsigned-char (BATTLE.PRG C flags)')

# ---- blob ---------------------------------------------------------------------
blob = open('build/mod/wswap.bin', 'rb').read()
p()
p('-- 1. blob size')
p('wswap.bin: %d bytes; RAM %08X..%08X; room %d bytes; free %d bytes'
  % (len(blob), BLOB_RAM, BLOB_RAM + len(blob), BLOB_LIMIT - BLOB_RAM, BLOB_LIMIT - BLOB_RAM - len(blob)))
if len(blob) > BLOB_LIMIT - BLOB_RAM:
    fail('blob too big')

nm = sh(CROSS + 'nm -n build/mod/wswap.elf')
syms = {}
for l in nm.splitlines():
    a, t, n = l.split()
    if int(a, 16) >= BLOB_RAM and int(a, 16) < BLOB_LIMIT:
        syms[n] = int(a, 16)
p('blob symbols:', ', '.join('%s=%08X' % kv for kv in sorted(syms.items(), key=lambda kv: kv[1])))
entry = syms['wswap_entry']

# ---- disassembly --------------------------------------------------------------
dis = sh(CROSS + 'objdump -d -j .wswap build/mod/wswap.elf')
p()
p('-- 2. full disassembly of the blob (objdump)')
p(dis)

# ---- jal targets ---------------------------------------------------------------
def load_syms():
    d = {}
    for f in ('config/BATTLE/BATTLE.PRG/symbol_addrs.txt', 'config/SLUS_010.40/symbol_addrs.txt',
              'build/config/BATTLE/BATTLE.PRG/undefined_funcs_auto.txt', 'build/config/SLUS_010.40/undefined_funcs_auto.txt'):
        for l in open(f):
            m = re.match(r'\s*(\w+)\s*=\s*(0x[0-9A-Fa-f]+);', l)
            if m:
                d.setdefault(int(m.group(2), 16), m.group(1))
    return d


names = load_syms()
prg_pristine = open('build/mod/BATTLE.PRG.pristine', 'rb').read()
slus = open('build/data/SLUS_010.40', 'rb').read()
SLUS_RAM = 0x80010000
# SLUS_010.40 on disc has a 0x800-byte PS-X EXE header
slus_hdr = 0x800
p()
p('-- 3. jal / j targets (every call out of the blob)')
insns = re.findall(r'^\s*([0-9a-f]{8}):\s+([0-9a-f]{8})\s', dis, re.M)
targets = {}
for addr, word in insns:
    addr = int(addr, 16)
    w = int(word, 16)
    op = w >> 26
    if op in (2, 3):
        t = (addr & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
        kind = 'jal' if op == 3 else 'j'
        if BLOB_RAM <= t < BLOB_RAM + len(blob):
            if kind == 'jal' and t not in syms.values():
                fail('jal into the middle of the blob at %08X -> %08X' % (addr, t))
            elif kind == 'j' and not (BLOB_RAM <= t < BLOB_RAM + len(blob)):
                fail('j out of the blob')
            continue
        if kind == 'j':
            fail('j leaves the blob at %08X' % addr)
        targets.setdefault(t, []).append(addr)

def word_at(t):
    if PRG_RAM <= t < PRG_RAM + len(prg_pristine):
        return prg_pristine, t - PRG_RAM
    if SLUS_RAM <= t < SLUS_RAM + len(slus) - slus_hdr:
        return slus, t - SLUS_RAM + slus_hdr
    return None, None

for t in sorted(targets):
    img, off = word_at(t)
    nm_ = names.get(t, '?')
    if img is None:
        fail('target %08X is outside BATTLE.PRG and SLUS_010.40' % t)
        continue
    jalw = struct.pack('<I', 0x0C000000 | (t >> 2 & 0x3FFFFFF))
    callers_prg = prg_pristine.count(jalw)
    callers_slus = slus.count(jalw)
    callers_ovl = 0
    for root, _, files in os.walk('build/data'):
        for fn in files:
            if fn.endswith('.PRG') and not root.endswith('BATTLE') or fn == 'INITBTL.PRG':
                callers_ovl += open(os.path.join(root, fn), 'rb').read().count(jalw)
    first = struct.unpack_from('<III', img, off)
    prev = struct.unpack_from('<II', img, off - 8) if off >= 8 else (0, 0)
    # the instruction pair before a function start is normally "jr ra; delay slot" / nop padding
    prev_ret = prev[0] == 0x03E00008 or prev[1] == 0x03E00008 or prev == (0, 0) or True
    p('%08X %-34s called from blob at %s' % (t, nm_, ', '.join('%08X' % a for a in targets[t])))
    p('         existing jal callers in game: BATTLE.PRG=%d SLUS_010.40=%d other overlays=%d; first words %08X %08X %08X; '
      'preceding words %08X %08X' % (callers_prg, callers_slus, callers_ovl, first[0], first[1], first[2], prev[0], prev[1]))
    if nm_ == '?':
        fail('no symbol for %08X' % t)
    m = re.match(r'func_([0-9A-F]{8})$', nm_)
    if m and int(m.group(1), 16) != t:
        fail('name/address mismatch %s %08X' % (nm_, t))
    if callers_prg + callers_slus + callers_ovl == 0:
        fail('%08X is never called as jal elsewhere in the game' % t)

# ---- stack frames ----------------------------------------------------------------
p()
p('-- 4. stack discipline (frame setup / teardown per function)')
cur = None
fr = {}
for addr, word in insns:
    a = int(addr, 16)
    w = int(word, 16)
    for n, v in syms.items():
        if v == a:
            cur = n
    if (w >> 16) == 0x27BD:  # addiu sp,sp,imm
        imm = w & 0xFFFF
        imm = imm - 0x10000 if imm & 0x8000 else imm
        fr.setdefault(cur, []).append(imm)
for n, v in fr.items():
    p('%-14s sp adjustments: %s -> net %d' % (n, v, sum(v)))
    if sum(v) != 0:
        fail('unbalanced stack in %s' % n)
saved = {}
for addr, word in insns:
    w = int(word, 16)
    a = int(addr, 16)
    for n, v in syms.items():
        if v == a:
            cur = n
    if (w >> 26) == 0x2B and ((w >> 21) & 31) == 29:  # sw x, off(sp)
        saved.setdefault(cur, set()).add(((w >> 16) & 31, w & 0xFFFF))
    if (w >> 26) == 0x23 and ((w >> 21) & 31) == 29:  # lw x, off(sp)
        saved.setdefault(cur + '/restore', set()).add(((w >> 16) & 31, w & 0xFFFF))
for n in sorted(saved):
    if n.endswith('/restore'):
        continue
    if saved[n] != saved.get(n + '/restore', set()):
        fail('saved/restored register mismatch in %s: %s vs %s' % (n, saved[n], saved.get(n + '/restore')))
    else:
        p('%-14s saves/restores %s' % (n, ', '.join('r%d@%d' % (r, o) for r, o in sorted(saved[n], key=lambda x: x[1]))))

# ---- hook ----------------------------------------------------------------------------
p()
p('-- 5. hook site')
new_prg = open('build/data/BATTLE/BATTLE.PRG', 'rb').read()
old_w = struct.unpack_from('<I', prg_pristine, HOOK_OFF)[0]
new_w = struct.unpack_from('<I', new_prg, HOOK_OFF)[0]
tgt = lambda w: (0x80000000 | ((w & 0x3FFFFFF) << 2))
p('BATTLE.PRG file offset 0x%X = RAM 0x%08X' % (HOOK_OFF, PRG_RAM + HOOK_OFF))
p('original: %08X = jal %08X (%s)' % (old_w, tgt(old_w), names.get(tgt(old_w))))
p('patched : %08X = jal %08X (wswap_entry @ %08X)' % (new_w, tgt(new_w), entry))
if tgt(new_w) != entry or tgt(old_w) != 0x80043940:
    fail('hook mismatch')
p('delay slot word after the call (unchanged):', '%08X' % struct.unpack_from('<I', new_prg, HOOK_OFF + 4)[0])
p('call site expects v0 = return value (compared with -1): the blob returns what vs_main_processPadState returned (s5 = v0 saved right after the call)')

# ---- file diffs ------------------------------------------------------------------------
p()
p('-- 6. BATTLE.PRG vs previous mod build (.baseline/data/BATTLE/BATTLE.PRG)')
base_prg = open('.baseline/data/BATTLE/BATTLE.PRG', 'rb').read()
p('sizes: previous %d, new %d (on-disc size must be 579584 = 283 sectors: %s)'
  % (len(base_prg), len(new_prg), 'ok' if len(new_prg) == 579584 else 'BAD'))
if len(new_prg) != 579584:
    fail('size')
diffs = [i for i in range(len(base_prg)) if base_prg[i] != new_prg[i]]
head_diffs = sorted(set(i & ~3 for i in diffs))
p('differing bytes inside the old file extent (0..0x%X): %d, in word(s) at offset(s) %s'
  % (len(base_prg), len(diffs), ', '.join('0x%X' % i for i in head_diffs)))
if head_diffs != [HOOK_OFF]:
    fail('unexpected changes inside the old PRG body')
tail = new_prg[len(base_prg):]
p('appended region 0x%X..0x%X (%d bytes): blob %d bytes at start, rest zero: %s'
  % (len(base_prg), len(new_prg), len(tail), len(blob), 'ok' if tail[:len(blob)] == blob and not any(tail[len(blob):]) else 'BAD'))
if tail[:len(blob)] != blob or any(tail[len(blob):]):
    fail('tail content')
if len(base_prg) != TAIL_OFF:
    fail('baseline PRG is not %d bytes' % TAIL_OFF)

p()
p('-- 7. all other files under build/data identical to the previous mod build')
r = subprocess.run('diff -rq .baseline/data build/data', shell=True, text=True, capture_output=True, executable='/bin/bash')
lines = [l for l in r.stdout.splitlines() if l]
p('\n'.join(lines) if lines else '(no differences)')
other = [l for l in lines if 'BATTLE/BATTLE.PRG' not in l]
if other:
    fail('other files differ: %s' % other)

p()
p('-- 8. disc image')
img = 'build/disks/SLUS-01040.bin'
size = os.path.getsize(img)
p('%s: %d bytes (expected 750643152): %s' % (img, size, 'ok' if size == 750643152 else 'BAD'))
if size != 750643152:
    fail('image size')
prev_img = '/mnt/d/Proj/Vagrant story/Vagrant Story Mod/Vagrant Story (USA) [mod].bin'
if os.path.exists(prev_img):
    a = open(img, 'rb')
    b = open(prev_img, 'rb')
    sec = 0
    bad = []
    while True:
        x = a.read(2352)
        y = b.read(2352)
        if not x:
            break
        if x != y:
            bad.append(sec)
        sec += 1
    p('previous mod image [mod].bin: %d of %d sectors differ' % (len(bad), sec))
    # LBA of BATTLE.PRG = 1100, 283 sectors; the file starts at image sector 1100 + 150? (mkpsxiso lba is absolute from the start of the track)
    lo, hi = 1100, 1100 + 283
    inside = [s for s in bad if lo <= s < hi]
    outside = [s for s in bad if not (lo <= s < hi)]
    p('  differing sectors inside BATTLE.PRG extent [%d,%d): %s' % (lo, hi, inside))
    p('  differing sectors outside (directory records etc.): %s' % outside)
    # expected: hook sector (0x1111C/2048 -> 34), tail sector (0x8D124/2048 -> 282), + dir record sector(s)
    exp_in = {1100 + HOOK_OFF // 2048, 1100 + TAIL_OFF // 2048}
    if set(inside) != exp_in:
        fail('unexpected sectors in BATTLE.PRG extent: %s vs %s' % (inside, exp_in))
    # outside sectors must be directory/filesystem metadata only (before the first file at the start of the track data)
    # the only expected one: the ISO directory record of BATTLE.PRG (file length 577828 -> 579584)
    for s in outside:
        a.seek(s * 2352)
        b.seek(s * 2352)
        x, y = a.read(2352), b.read(2352)
        d = [i - 24 for i in range(2352) if x[i] != y[i] and 24 <= i < 24 + 2048]
        p('  sector %d user-data bytes differing (offsets): %s' % (s, d))
        olds = struct.pack('<I', 577828) + struct.pack('>I', 577828)
        news = struct.pack('<I', 579584) + struct.pack('>I', 579584)
        pos = y[24:24 + 2048].find(olds)
        ok_rec = pos >= 0 and x[24 + pos:24 + pos + 8] == news and all(pos - 0 <= i < pos + 8 for i in d)
        p('  -> directory record length field of BATTLE.PRG at offset %d: %s' % (pos, 'ok (only that field changed)' if ok_rec else 'BAD'))
        if not ok_rec:
            fail('unexpected differences in sector %d' % s)
else:
    p('(previous [mod].bin not found, skipped)')

p()
p('-- 9. weapon-hands table used by the blob (mask 0x1D4 >> (category-1)) vs vs_mainMenu_weaponHands in MAINMENU.PRG')
mm = open('build/data/MENU/MAINMENU.PRG', 'rb').read()
tbl = list(mm[0x80102140 - 0x800F9800:0x80102140 - 0x800F9800 + 10])
mask = [(0x1D4 >> i) & 1 for i in range(10)]
p('MAINMENU.PRG table :', tbl)
p('blob mask         :', mask)
if tbl != mask:
    fail('weaponHands mismatch')

p()
p('-- 10. behavioural test of the shipped bytes in a MIPS interpreter (tools/mod/test_wswap.py)')
r = subprocess.run([sys.executable, '-I', 'tools/mod/test_wswap.py'], capture_output=True, text=True)
p(r.stdout.strip())
p(r.stderr.strip())
if r.returncode != 0:
    fail('emulator test')

p()
p('RESULT:', 'ALL CHECKS PASSED' if ok else 'FAILURES PRESENT')
open(sys.argv[1], 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print('\n'.join(l for l in out if 'FAIL' in l or l.startswith('RESULT')))
sys.exit(0 if ok else 1)
