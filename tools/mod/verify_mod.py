#!/usr/bin/env python3
"""Static verification of the weapon-swap mod build; writes a text log.

    python3 -I tools/mod/verify_mod.py OUTPUT_LOG

Run after tools/mod/build_mod.sh. Needs
  .baseline/data          a copy of build/data from a plain `make` before the weapon mod
                          (on qol-mod-classic that is the unmodified decompilation build)
and, if present,
  .baseline_v1/BATTLE.PRG the BATTLE.PRG of a previous release ([mod-weapons]; qol-mod only)
  previous mod images in the directory named by $VS_MOD_IMG_DIR.
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
PRG_SIZE = 579584
HOOK_OFF = 0x1111C
BLOB_RAM = 0x800F5924
BLOB_LIMIT = 0x800F6000
DEAD_RAM = 0x800B26B8
DEAD_OFF = DEAD_RAM - PRG_RAM
DEAD_SIZE = 496
IMG_DIR = os.path.join(os.environ.get('VS_MOD_IMG_DIR', ''), '')

p('=' * 78)
p('Vagrant Story weapon-swap mod v2: build verification log')
p('=' * 78)
p('commit:', sh('git rev-parse HEAD').strip(), '(+ uncommitted changes, if any:',
  sh('git status --short | wc -l').strip(), 'entries)')
p('compiler: tools/old-gcc/2.8.1-psx/cc1 -G0 -O2 -Wall -fno-builtin -funsigned-char (BATTLE.PRG C flags)')

# ---- blobs --------------------------------------------------------------------
blob = open('build/mod/wswap.bin', 'rb').read()
blob2 = open('build/mod/wswap2.bin', 'rb').read()
p()
p('-- 1. blob sizes')
p('wswap.bin  (tail of BATTLE.PRG): %d bytes; RAM %08X..%08X; room %d bytes; free %d bytes'
  % (len(blob), BLOB_RAM, BLOB_RAM + len(blob), BLOB_LIMIT - BLOB_RAM, BLOB_LIMIT - BLOB_RAM - len(blob)))
p('wswap2.bin (func_800B26B8 body): %d bytes; RAM %08X..%08X; room %d bytes; free %d bytes'
  % (len(blob2), DEAD_RAM, DEAD_RAM + len(blob2), DEAD_SIZE, DEAD_SIZE - len(blob2)))
if len(blob) > BLOB_LIMIT - BLOB_RAM:
    fail('tail blob too big')
if len(blob2) > DEAD_SIZE:
    fail('func_800B26B8 blob too big')

nm = sh(CROSS + 'nm -n build/mod/wswap.elf')
syms = {}
for l in nm.splitlines():
    f = l.split()
    if len(f) != 3:
        continue
    a, t, n = f
    a = int(a, 16)
    if BLOB_RAM <= a < BLOB_LIMIT or DEAD_RAM <= a < DEAD_RAM + DEAD_SIZE:
        syms[n] = a
p('blob symbols:', ', '.join('%s=%08X' % kv for kv in sorted(syms.items(), key=lambda kv: kv[1])))
entry = syms['wswap_entry']
if syms['beginSwap'] != DEAD_RAM:
    fail('beginSwap is not at the entry of func_800B26B8')

def in_blob(t):
    return BLOB_RAM <= t < BLOB_RAM + len(blob) or DEAD_RAM <= t < DEAD_RAM + len(blob2)

# ---- disassembly --------------------------------------------------------------
dis = sh(CROSS + 'objdump -d -j .wswap -j .wswap2 build/mod/wswap.elf')
p()
p('-- 2. full disassembly of both blobs (objdump)')
p(dis)

# ---- jal targets ---------------------------------------------------------------
def load_syms():
    d = {}
    for f in ('config/BATTLE/BATTLE.PRG/symbol_addrs.txt', 'config/SLUS_010.40/symbol_addrs.txt',
              'build/config/BATTLE/BATTLE.PRG/undefined_funcs_auto.txt', 'build/config/SLUS_010.40/undefined_funcs_auto.txt',
              'tools/mod/extra_syms.ld'):
        for l in open(f):
            m = re.match(r'\s*(\w+)\s*=\s*(0x[0-9A-Fa-f]+);', l)
            if m:
                d.setdefault(int(m.group(2), 16), m.group(1))
    return d


names = load_syms()
prg_pristine = open('build/mod/BATTLE.PRG.pristine', 'rb').read()
slus = open('build/data/SLUS_010.40', 'rb').read()
SLUS_RAM = 0x80010000
slus_hdr = 0x800  # SLUS_010.40 on disc has a 0x800-byte PS-X EXE header
p()
p('-- 3. jal / j targets (every call out of the blobs)')
insns = re.findall(r'^\s*([0-9a-f]{8}):\s+([0-9a-f]{8})\s', dis, re.M)
targets = {}
for addr, word in insns:
    addr = int(addr, 16)
    w = int(word, 16)
    op = w >> 26
    if op in (2, 3):
        t = (addr & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
        kind = 'jal' if op == 3 else 'j'
        if in_blob(t):
            if kind == 'jal' and t not in syms.values():
                fail('jal into the middle of the blob at %08X -> %08X' % (addr, t))
            elif kind == 'j' and (addr >= DEAD_RAM) != (t >= DEAD_RAM):
                fail('j between the two blobs at %08X' % addr)
            continue
        if kind == 'j':
            fail('j leaves the blob at %08X' % addr)
        targets.setdefault(t, []).append(addr)
p('internal jal targets (inside the blobs): %s' % ', '.join(
    sorted('%s=%08X' % (n, a) for n, a in syms.items() if n in ('equippedSlot', 'beginSwap'))))

def word_at(t):
    if PRG_RAM <= t < PRG_RAM + len(prg_pristine):
        return prg_pristine, t - PRG_RAM
    if SLUS_RAM <= t < SLUS_RAM + len(slus) - slus_hdr:
        return slus, t - SLUS_RAM + slus_hdr
    return None, None

ovl_cache = []
for root, _, files in os.walk('build/data'):
    for fn in files:
        if (fn.endswith('.PRG') and not root.endswith('BATTLE')) or fn == 'INITBTL.PRG':
            ovl_cache.append(open(os.path.join(root, fn), 'rb').read())

for t in sorted(targets):
    img, off = word_at(t)
    nm_ = names.get(t, '?')
    if img is None:
        fail('target %08X is outside BATTLE.PRG and SLUS_010.40' % t)
        continue
    jalw = struct.pack('<I', 0x0C000000 | (t >> 2 & 0x3FFFFFF))
    callers_prg = prg_pristine.count(jalw)
    callers_slus = slus.count(jalw)
    callers_ovl = sum(o.count(jalw) for o in ovl_cache)
    first = struct.unpack_from('<III', img, off)
    prev = struct.unpack_from('<II', img, off - 8) if off >= 8 else (0, 0)
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
    # a function entry: previous function ends with jr ra (+ delay slot) or the entry follows padding
    if not (prev[0] == 0x03E00008 or prev[1] == 0x03E00008 or prev == (0, 0)):
        p('         note: the words before %08X are not "jr ra" (%08X %08X); entry is still a jal target elsewhere' % (t, prev[0], prev[1]))

# ---- stack frames ----------------------------------------------------------------
p()
p('-- 4. stack discipline (frame setup / teardown per function)')
by_addr = sorted((a, n) for n, a in syms.items() if n in ('equippedSlot', 'beginSwap', 'wswap_entry'))


def func_of(a):
    cur = None
    for fa, fn in by_addr:
        if (fa >= DEAD_RAM and fa < DEAD_RAM + DEAD_SIZE) == (a >= DEAD_RAM and a < DEAD_RAM + DEAD_SIZE) and fa <= a:
            cur = fn
    return cur


fr = {}
saved = {}
for addr, word in insns:
    a = int(addr, 16)
    w = int(word, 16)
    cur = func_of(a)
    if (w >> 16) == 0x27BD:  # addiu sp,sp,imm
        imm = w & 0xFFFF
        imm = imm - 0x10000 if imm & 0x8000 else imm
        fr.setdefault(cur, []).append(imm)
    if (w >> 26) == 0x2B and ((w >> 21) & 31) == 29:  # sw x, off(sp)
        saved.setdefault(cur, set()).add(((w >> 16) & 31, w & 0xFFFF))
    if (w >> 26) == 0x23 and ((w >> 21) & 31) == 29:  # lw x, off(sp)
        saved.setdefault(cur + '/restore', set()).add(((w >> 16) & 31, w & 0xFFFF))
for n, v in fr.items():
    p('%-14s sp adjustments: %s -> net %d' % (n, v, sum(v)))
    if sum(v) != 0:
        fail('unbalanced stack in %s' % n)
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
def runs(a, b):
    """merged differing byte ranges between two equally long buffers"""
    res = []
    i = 0
    n = len(a)
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and (a[j] != b[j] or (j + 1 < n and a[j + 1] != b[j + 1])):
                j += 1
            res.append((i, j))
            i = j
        else:
            i += 1
    return res


p()
p('-- 6. BATTLE.PRG')
if len(new_prg) != PRG_SIZE:
    fail('size %d' % len(new_prg))
p('on-disc size %d (579584 = 283 sectors): %s' % (len(new_prg), 'ok' if len(new_prg) == PRG_SIZE else 'BAD'))
base_prg = open('.baseline/data/BATTLE/BATTLE.PRG', 'rb').read()
HAVE_V1 = os.path.exists('.baseline_v1/BATTLE.PRG')
v1_prg = open('.baseline_v1/BATTLE.PRG', 'rb').read() if HAVE_V1 else b''
p('(a) against the build before the weapon mod (.baseline, %d bytes):' % len(base_prg))
if len(base_prg) != TAIL_OFF:
    fail('baseline PRG is not %d bytes' % TAIL_OFF)
diffs = [i for i in range(len(base_prg)) if base_prg[i] != new_prg[i]]
head = sorted(set(i & ~3 for i in diffs))
inword = [i for i in head if i != HOOK_OFF and not (DEAD_OFF <= i < DEAD_OFF + len(blob2))]
p('    differing bytes inside the old file extent: %d' % len(diffs))
p('    hook word at 0x%X: %s' % (HOOK_OFF, 'differs' if HOOK_OFF in head else 'same'))
p('    func_800B26B8 body 0x%X..0x%X (%d bytes): %d bytes differ from the original function'
  % (DEAD_OFF, DEAD_OFF + len(blob2), len(blob2), sum(1 for i in diffs if DEAD_OFF <= i < DEAD_OFF + len(blob2))))
if inword:
    fail('unexpected changes inside the old PRG body at %s' % ', '.join('0x%X' % i for i in inword))
if new_prg[DEAD_OFF:DEAD_OFF + len(blob2)] != blob2:
    fail('func_800B26B8 region does not hold wswap2.bin')
if new_prg[DEAD_OFF + len(blob2):DEAD_OFF + DEAD_SIZE] != base_prg[DEAD_OFF + len(blob2):DEAD_OFF + DEAD_SIZE]:
    fail('rest of func_800B26B8 changed')
tail = new_prg[len(base_prg):]
tail_ok = tail[:len(blob)] == blob and not any(tail[len(blob):])
p('    appended region 0x%X..0x%X (%d bytes): blob %d bytes at start, rest zero: %s'
  % (len(base_prg), len(new_prg), len(tail), len(blob), 'ok' if tail_ok else 'BAD'))
if not tail_ok:
    fail('tail content')

p('(b) against the previous release ([mod-weapons], .baseline_v1/BATTLE.PRG, %d bytes): every changed byte range' % len(v1_prg))
if not HAVE_V1:
    p('    (.baseline_v1/BATTLE.PRG not present, skipped)')
elif len(v1_prg) != PRG_SIZE:
    fail('v1 PRG size')
changed_bytes = [i for i in range(PRG_SIZE) if v1_prg[i] != new_prg[i]] if HAVE_V1 else []
allowed = [('hook word', HOOK_OFF, HOOK_OFF + 4), ('func_800B26B8 body', DEAD_OFF, DEAD_OFF + DEAD_SIZE),
           ('tail of the last sector', TAIL_OFF, PRG_SIZE)]
changed = []
for name, lo, hi in allowed:
    sel = [i for i in changed_bytes if lo <= i < hi]
    if sel:
        p('    %-24s allowed 0x%06X..0x%06X; %d differing bytes, first 0x%06X (RAM %08X), last 0x%06X (RAM %08X)'
          % (name, lo, hi, len(sel), sel[0], PRG_RAM + sel[0], sel[-1], PRG_RAM + sel[-1]))
        changed.append((sel[0], sel[-1] + 1))
stray = [i for i in changed_bytes if not any(lo <= i < hi for _, lo, hi in allowed)]
p('    differing bytes outside those three regions: %d' % len(stray))
if stray:
    fail('unexpected changes vs previous release at %s' % ', '.join('0x%X' % i for i in stray[:10]))
if HAVE_V1 and not changed:
    fail('no changes vs previous release?')

p()
p('-- 7. all other files under build/data identical to the build before the weapon mod')
r = subprocess.run('diff -rq -x "*.elf" .baseline/data build/data', shell=True, text=True, capture_output=True, executable='/bin/bash')
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
p('sha256:', hashlib.sha256(open(img, 'rb').read()).hexdigest())
LBA = 1100  # BATTLE.PRG
exp_sectors = set()
for a, b in changed:
    for s in range(a // 2048, (b - 1) // 2048 + 1):
        exp_sectors.add(LBA + s)
for name in ('[mod-weapons]', '[mod]'):
    prev_img = IMG_DIR + 'Vagrant Story (USA) %s.bin' % name
    if not os.path.exists(prev_img):
        p('(%s image not found, skipped)' % name)
        continue
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
    inside = [s for s in bad if LBA <= s < LBA + 283]
    outside = [s for s in bad if not (LBA <= s < LBA + 283)]
    p('against %s: %d of %d sectors differ; inside BATTLE.PRG [%d,%d): %s; outside: %s'
      % (name, len(bad), sec, LBA, LBA + 283, inside, outside))
    if name == '[mod-weapons]' and HAVE_V1:
        p('  expected sectors from the byte ranges in section 6(b): %s' % sorted(exp_sectors))
        if set(bad) != exp_sectors:
            fail('image differs from [mod-weapons] in unexpected sectors')

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
p('-- 10. func_800B26B8 is unreferenced (tools/mod/check_dead.py, scans every file of data/)')
if os.environ.get('SKIP_DEAD_SCAN'):
    p('(skipped by SKIP_DEAD_SCAN)')
else:
    r = subprocess.run([sys.executable, '-I', 'tools/mod/check_dead.py', '800B26B8', '496', 'func_800B26B8'], capture_output=True, text=True)
    p(r.stdout.strip())
    p(r.stderr.strip())
    if r.returncode != 0:
        fail('func_800B26B8 is referenced')

p()
p('-- 11. behavioural test of the shipped bytes in a MIPS interpreter (tools/mod/test_wswap.py)')
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
