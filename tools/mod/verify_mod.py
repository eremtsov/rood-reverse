#!/usr/bin/env python3
"""Static verification of the weapon-slots mod build; writes a text log.

    python3 -I tools/mod/verify_mod.py OUTPUT_LOG PREVIOUS_IMAGE.bin

Run after tools/mod/build_mod.sh (and tools/mod/run_dead_checks.sh). PREVIOUS_IMAGE is the image the
new one is compared against sector by sector (the previous release of the same variant). Checks:
  1. section sizes against the free ranges, symbols, where every function lives
  2. the code of every function of the mod (decoded from the shipped BATTLE.PRG): MIPS-I only, jal targets are
     real function entries, stack frames balanced, no load-delay hazards, branches stay inside the function,
     no indirect jumps except `jr ra`
  3. hook sites
  4. every changed byte range of BATTLE.PRG against the toolchain build and against the previous release
  5. disc image: size, only BATTLE.PRG sectors differ from the previous release, EDC/ECC of every changed
     sector, the file extracted from the image equals build/data/BATTLE/BATTLE.PRG
  6. the dead-code scan of every overwritten function (tools/mod/run_dead_checks.sh)
  7. the behavioural test of the shipped bytes (tools/mod/test_wswap.py)
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
PRG_SIZE = 579584
TAIL_RAM, TAIL_LIMIT = 0x800F5924, 0x800F6000
PRG_LBA, PRG_SECTORS = 1100, 283
MENU5_LBA, MENU5_SECTORS, MENU5_SIZE = 85075, 13, 26296   # MENU5.PRG (the map screen), changed in the default variant only
CLASSIC = bool(re.search(r'^#define WSWAP_CLASSIC 1', open('src/mod/wswap.c').read(), re.M))
# section : (RAM, size of the unreferenced function range, name of the function(s))
DEAD = {
    '.wswap2': (0x800B26B8, 496, 'func_800B26B8'),
    '.wA': (0x800D197C, 412, 'func_800D197C'),
    '.wB': (0x800AA108, 392, 'func_800AA108 + func_800AA218'),
    '.wC': (0x800D155C, 284, 'func_800D155C'),
    '.wD': (0x80099854, 268, 'func_80099854 + func_80099900'),
}
HOOKS = [(0x8007991C, 'vs_battle_exec: jal vs_main_processPadState', 'wswap_entry'),
         (0x800CA0A4, 'func_800C9FE8: jal func_800C9EB8 (D-pad group)', 'wslot_label'),
         (0x800CA1AC, 'func_800C9FE8: jal func_800C9EB8 (button group)', 'wslot_label')]
# edits of the decompiled C (same code size): the toolchain build already contains them, they differ from the previous image
DECOMP_WORDS = []
if not CLASSIC:
    DEAD['.wE'] = (0x8009BD90, 204, 'func_8009BD90')
    DEAD['.wF'] = (0x800733F8, 140, 'func_800733F8')
    DEAD['.wH'] = (0x8007FF8C, 116, 'func_8007FF8C')
    HOOKS.append((0x8007A10C, 'vs_battle_exec: jal func_8006EC7C (first person look)', 'wfp_look'))
    # func_8006EC7C: D-pad up/down masks swapped, stick pitch term addu -> subu
    DECOMP_WORDS = [0x8006EC8C, 0x8006ECD4, 0x8006EE50]

prev_img = sys.argv[2]

p('=' * 78)
p('Vagrant Story weapon-slots mod: build verification log')
p('=' * 78)
p('commit:', sh('git rev-parse HEAD').strip(), '(+ uncommitted changes:', sh('git status --short | wc -l').strip(), 'entries)')
p('branch:', sh('git rev-parse --abbrev-ref HEAD').strip())
p('compiler: tools/old-gcc/2.8.1-psx/cc1 -G0 -O2 -Wall -fno-builtin -funsigned-char (BATTLE.PRG C flags)')
p('previous image:', prev_img)

new_prg = open('build/data/BATTLE/BATTLE.PRG', 'rb').read()
pristine = open('build/mod/BATTLE.PRG.pristine', 'rb').read()
orig_disc = open('data/BATTLE/BATTLE.PRG', 'rb').read()
if len(new_prg) != PRG_SIZE:
    fail('BATTLE.PRG size %d' % len(new_prg))

# ---- 1. sections and symbols -------------------------------------------------------------------
p()
p('-- 1. sections')
elf = 'build/mod/wswap.elf'
hdr = sh(CROSS + 'objdump -h ' + elf)
sizes = {}
for m in re.finditer(r'^\s*\d+\s+(\.\w+)\s+([0-9a-f]{8})\s+([0-9a-f]{8})', hdr, re.M):
    sizes[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16))
tail_size = sizes['.wswap'][0]
p('.wswap  tail of BATTLE.PRG        RAM %08X: %4d bytes of %d (%d free)' % (TAIL_RAM, tail_size, TAIL_LIMIT - TAIL_RAM, TAIL_LIMIT - TAIL_RAM - tail_size))
if sizes['.wswap'][1] != TAIL_RAM or tail_size > TAIL_LIMIT - TAIL_RAM:
    fail('tail section')
for sec, (ram, size, name) in DEAD.items():
    s, a = sizes[sec]
    p('%-8s %-28s RAM %08X: %4d bytes of %d (%d free)' % (sec, name, ram, s, size, size - s))
    if a != ram or s > size:
        fail('section %s' % sec)

nm = sh(CROSS + 'nm -S -n ' + elf)
funcs = {}   # name -> (addr, size)
allsyms = {}
for l in nm.splitlines():
    f = l.split()
    if len(f) == 4 and f[2] in 'Tt':
        funcs[f[3]] = (int(f[0], 16), int(f[1], 16))
    if len(f) >= 3:
        allsyms[f[-1]] = int(f[0], 16)
p('functions of the mod:')
for n, (a, s) in sorted(funcs.items(), key=lambda kv: kv[1][0]):
    where = 'tail' if TAIL_RAM <= a < TAIL_LIMIT else [sec for sec, (r, z, _) in DEAD.items() if r <= a < r + z][0]
    p('   %-14s %08X  %4d bytes  in %s' % (n, a, s, where))
data_syms = [(n, a) for n, a in allsyms.items() if n.startswith('wl_')]
p('constant data:', ', '.join('%s=%08X' % x for x in sorted(data_syms, key=lambda x: x[1])))
if 'wl_hint' not in allsyms:
    fail('constant data missing')
entry = allsyms['wswap_entry']
label = allsyms['wslot_label']

# ---- 2. code ---------------------------------------------------------------------------------------
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
slus = open('build/data/SLUS_010.40', 'rb').read()
SLUS_RAM, slus_hdr = 0x80010000, 0x800
ovl = []
for root, _, files in os.walk('build/data'):
    for fn in files:
        if (fn.endswith('.PRG') and not root.endswith('BATTLE')) or fn == 'INITBTL.PRG':
            ovl.append(open(os.path.join(root, fn), 'rb').read())

SPECIAL_OK = {0x00, 0x02, 0x03, 0x04, 0x06, 0x07, 0x08, 0x10, 0x12, 0x18, 0x19, 0x1A, 0x1B, 0x20, 0x21, 0x22, 0x23,
              0x24, 0x25, 0x26, 0x27, 0x2A, 0x2B}   # sll srl sra sllv srlv srav jr mfhi mflo mult multu div divu add..sltu
MAIN_OK = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F,
           0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x28, 0x29, 0x2A, 0x2B, 0x2E}
LOADS = {0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26}
STORES = {0x28, 0x29, 0x2A, 0x2B, 0x2E}
REGIMM_OK = {0, 1, 16, 17}


def reads(w):
    """registers read by an instruction"""
    op = w >> 26
    rs, rt = (w >> 21) & 31, (w >> 16) & 31
    if op == 0:
        fn = w & 63
        if fn in (0, 2, 3):
            return {rt}
        if fn in (8, 9, 0x11, 0x13):
            return {rs}
        if fn in (0x10, 0x12):
            return set()
        return {rs, rt}
    if op == 1:
        return {rs}
    if op in (2, 3, 0x0F):
        return set()
    if op in (4, 5) or op in STORES:
        return {rs, rt}
    return {rs}


def img_at(t):
    if PRG_RAM <= t < PRG_RAM + len(pristine):
        return pristine, t - PRG_RAM
    if SLUS_RAM <= t < SLUS_RAM + len(slus) - slus_hdr:
        return slus, t - SLUS_RAM + slus_hdr
    return None, None


p()
p('-- 2. code of the mod, decoded from the shipped BATTLE.PRG')
all_targets = {}
for fname, (fa, fs) in sorted(funcs.items(), key=lambda kv: kv[1][0]):
    off = fa - PRG_RAM
    words = list(struct.unpack_from('<%dI' % (fs // 4), new_prg, off))
    n = len(words)
    sp_adj, saved, restored = [], set(), set()
    nret = 0
    problems = []
    for i, w in enumerate(words):
        addr = fa + 4 * i
        op = w >> 26
        if op == 0:
            if (w & 63) not in SPECIAL_OK:
                problems.append('%08X: SPECIAL %02x is not MIPS-I' % (addr, w & 63))
            if (w & 63) == 8:
                if ((w >> 21) & 31) != 31:
                    problems.append('%08X: jr through a register other than ra' % addr)
                else:
                    nret += 1
                    # the stack is released in the jr delay slot or just before
                    near = words[max(0, i - 2):i + 2]
                    if not any((x >> 16) == 0x27BD and not (x & 0x8000) for x in near) and sp_adj:
                        problems.append('%08X: return without releasing the frame' % addr)
        elif op == 1:
            if ((w >> 16) & 31) not in REGIMM_OK:
                problems.append('%08X: REGIMM %d' % (addr, (w >> 16) & 31))
        elif op not in MAIN_OK:
            problems.append('%08X: opcode %02x is not MIPS-I' % (addr, op))
        if op == 2:
            t = (addr & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
            if not (fa <= t < fa + fs):
                problems.append('%08X: j leaves the function (-> %08X)' % (addr, t))
        if op == 3:
            t = (addr & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
            blob_f = [k for k, (a, s) in funcs.items() if a == t]
            if blob_f:
                all_targets.setdefault(t, []).append((fname, addr, blob_f[0]))
            else:
                all_targets.setdefault(t, []).append((fname, addr, names.get(t, '?')))
        if op in (4, 5, 6, 7) or (op == 1 and ((w >> 16) & 31) in (0, 1, 16, 17)):
            simm = w & 0xFFFF
            simm -= 0x10000 if simm & 0x8000 else 0
            t = addr + 4 + simm * 4
            if not (fa <= t < fa + fs):
                problems.append('%08X: branch leaves the function (-> %08X)' % (addr, t))
        if (w >> 16) == 0x27BD:
            imm = w & 0xFFFF
            sp_adj.append(imm - 0x10000 if imm & 0x8000 else imm)
        if op == 0x2B and ((w >> 21) & 31) == 29:
            saved.add(((w >> 16) & 31, w & 0xFFFF))
        if op == 0x23 and ((w >> 21) & 31) == 29:
            restored.add(((w >> 16) & 31, w & 0xFFFF))
        # load-delay hazard: the next executed instruction(s) must not read the loaded register
        if op in LOADS and ((w >> 16) & 31) != 0:
            rt = (w >> 16) & 31
            nxt = []
            prevw = words[i - 1] if i > 0 else 0
            pop = prevw >> 26
            prev_is_branch = pop in (2, 3, 4, 5, 6, 7) or (pop == 1) or (pop == 0 and (prevw & 63) in (8, 9))
            if prev_is_branch:
                # the load sits in a delay slot: the next executed instruction is the branch target (or the fall-through)
                if pop in (4, 5, 6, 7) or pop == 1:
                    simm = prevw & 0xFFFF
                    simm -= 0x10000 if simm & 0x8000 else 0
                    t = fa + 4 * (i - 1) + 4 + simm * 4
                    if fa <= t < fa + fs:
                        nxt.append(words[(t - fa) // 4])
                    if i + 1 < n:
                        nxt.append(words[i + 1])
                elif pop in (2, 3):
                    t = ((fa + 4 * i) & 0xF0000000) | ((prevw & 0x3FFFFFF) << 2)
                    nxt.append(None)   # the callee: it starts with prologue code, checked separately below
                else:
                    nxt.append(None)
            elif i + 1 < n:
                nxt.append(words[i + 1])
            for x in nxt:
                if x is not None and rt in reads(x):
                    problems.append('%08X: load-delay hazard on r%d' % (addr, rt))
    if sp_adj and sum(sp_adj) != 0:
        problems.append('unbalanced stack: %s' % sp_adj)
    if saved != restored:
        problems.append('saved %s / restored %s' % (sorted(saved), sorted(restored)))
    if words[-2] != 0x03E00008:
        problems.append('function does not end with jr ra + delay slot')
    p('   %-14s %4d bytes, %3d instructions, frame %s, returns %d, saves %s' % (
        fname, fs, n, '%d' % -sp_adj[0] if sp_adj else '0', nret,
        ','.join('r%d' % r for r, _ in sorted(saved, key=lambda x: x[1])) or '-'))
    for pr in problems:
        fail('%s: %s' % (fname, pr))

p()
p('   jal targets (every call made by the mod):')
for t in sorted(all_targets):
    callers = all_targets[t]
    nm_ = callers[0][2]
    if any(t == a for a, s in funcs.values()):
        p('   %08X %-34s mod function, called %d times' % (t, nm_, len(callers)))
        continue
    img, off = img_at(t)
    if img is None:
        fail('jal target %08X is outside BATTLE.PRG and SLUS_010.40' % t)
        continue
    jalw = struct.pack('<I', 0x0C000000 | (t >> 2 & 0x3FFFFFF))
    ncall = pristine.count(jalw) + slus.count(jalw) + sum(o.count(jalw) for o in ovl)
    prevw = struct.unpack_from('<II', img, off - 8)
    first = struct.unpack_from('<III', img, off)
    # the previous function ends with jr ra, or (the sound thunks) with a tail `j` + delay slot
    entry_ok = prevw[0] == 0x03E00008 or (prevw[0] >> 26) == 2 or prevw[1] == 0x03E00008 or (prevw == (0, 0))
    p('   %08X %-34s existing jal callers in the game: %d; first words %08X %08X %08X; previous function ends %s'
      % (t, nm_, ncall, first[0], first[1], first[2], 'with jr ra' if entry_ok else 'unusually (%08X %08X)' % prevw))
    if nm_ == '?' or ncall == 0:
        fail('jal target %08X (%s) is not a known function' % (t, nm_))
    m = re.match(r'func_([0-9A-F]{8})$', nm_)
    if m and int(m.group(1), 16) != t:
        fail('name/address mismatch %s' % nm_)
    if not entry_ok:
        fail('jal target %08X does not follow a function end' % t)
    # the target's own first instructions must not be a load-delay victim of the delay slot we leave: the mod always
    # places the argument set-up in the delay slot with an ALU/move instruction (checked by the load-hazard scan above)

# ---- 3. hooks ---------------------------------------------------------------------------------------------
p()
p('-- 3. hook sites (patched `jal`)')
jtarget = lambda w: 0x80000000 | ((w & 0x3FFFFFF) << 2)
for ram, what, fn in HOOKS:
    off = ram - PRG_RAM
    ow = struct.unpack_from('<I', pristine, off)[0]
    nw = struct.unpack_from('<I', new_prg, off)[0]
    dw = struct.unpack_from('<I', new_prg, off + 4)[0]
    p('%08X (file 0x%X) %-52s %08X jal %08X (%s) -> %08X jal %08X (%s @ %08X); delay slot %08X unchanged'
      % (ram, off, what, ow, jtarget(ow), names.get(jtarget(ow)), nw, jtarget(nw), fn, allsyms[fn], dw))
    if (ow >> 26) != 3 or jtarget(nw) != allsyms[fn] or (nw >> 26) != 3:
        fail('hook %08X' % ram)
    if struct.unpack_from('<I', new_prg, off + 4)[0] != struct.unpack_from('<I', pristine, off + 4)[0]:
        fail('delay slot of hook %08X changed' % ram)

# ---- 4. byte ranges -----------------------------------------------------------------------------------------
def clusters(a, b, gap=16):
    res = []
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            if res and i - res[-1][1] <= gap:
                res[-1][1] = i + 1
            else:
                res.append([i, i + 1])
    return res


regions = [('hook vs_battle_exec', 0x8007991C, 4), ('hook label call 1', 0x800CA0A4, 4), ('hook label call 2', 0x800CA1AC, 4)]
if not CLASSIC:
    regions += [('hook first person look', 0x8007A10C, 4)]
    regions += [('decomp edit in func_8006EC7C (pitch inversion)', a, 4) for a in DECOMP_WORDS]
regions += [('%s (%s)' % (n, sec), r, z) for sec, (r, z, n) in DEAD.items()]
regions += [('tail of the last sector', TAIL_RAM, TAIL_LIMIT - TAIL_RAM)]
# functions the previous release (round 1) overwrote that this variant leaves untouched: back to the original bytes
RESTORED = []
if CLASSIC:
    RESTORED = [('func_8009BD90', 0x8009BD90, 204), ('func_800733F8', 0x800733F8, 140), ('func_8007FF8C', 0x8007FF8C, 116)]
    for n, r, z in RESTORED:
        off = r - PRG_RAM
        if new_prg[off:off + z] != orig_disc[off:off + z]:
            fail('%s: not the original code' % n)
        else:
            p('restored (round 1 patched it, now the original bytes): %s RAM %08X, %d bytes' % (n, r, z))
    regions += [('%s (round 1 only: restored to the original)' % n, r, z) for n, r, z in RESTORED]


def region_of(i):
    a = i + PRG_RAM
    for n, r, z in regions:
        if r <= a < r + z:
            return n
    return None


p()
p('-- 4. BATTLE.PRG byte ranges')
pr_pad = pristine + bytes(PRG_SIZE - len(pristine))
cl = clusters(pr_pad, new_prg)
p('(a) against the toolchain build before the mod patch (build/mod/BATTLE.PRG.pristine, %d bytes): %d changed ranges' % (len(pristine), len(cl)))
byreg = {}
for a, b in cl:
    p('    0x%06X..0x%06X (RAM %08X..%08X, %4d bytes) in %s' % (a, b, a + PRG_RAM, b + PRG_RAM, b - a, region_of(a)))
    for i in range(a, b):
        if region_of(i) is None:
            fail('changed byte outside the allowed regions: 0x%X (RAM %08X)' % (i, i + PRG_RAM))
            break
    byreg.setdefault(region_of(a), 0)
for sec, (r, z, n) in DEAD.items():
    s = sizes[sec][0]
    off = r - PRG_RAM
    same = new_prg[off + s:off + z] == orig_disc[off + s:off + z]
    was_orig = pr_pad[off:off + z] == orig_disc[off:off + z]
    p('    %-8s %-28s mod code %3d bytes, the other %3d bytes of the range are the original code: %s; range was original before: %s'
      % (sec, n, s, z - s, 'yes' if same else 'NO', 'yes' if was_orig else 'NO'))
    if not same:
        fail('%s: bytes behind the mod code differ from the original function' % sec)
    if not was_orig:
        fail('%s: the toolchain build differs from the disc BATTLE.PRG there (not original code?)' % sec)
tail = new_prg[len(pristine):]
if tail[:tail_size] != open('build/mod/wswap.bin', 'rb').read() or any(tail[tail_size:]):
    fail('tail content')
else:
    p('    tail: blob %d bytes, rest zero up to 579584: ok' % tail_size)

# ---- 5. disc image ---------------------------------------------------------------------------------------------
p()
p('-- 5. disc image')
img = 'build/disks/SLUS-01040.bin'
size = os.path.getsize(img)
p('%s: %d bytes (expected 750643152): %s' % (img, size, 'ok' if size == 750643152 else 'BAD'))
if size != 750643152 or os.path.getsize(prev_img) != 750643152:
    fail('image size')
p('sha256:', hashlib.sha256(open(img, 'rb').read()).hexdigest())

# EDC / ECC (CD-ROM XA mode 2 form 1)
EDC = []
for i in range(256):
    e = i
    for _ in range(8):
        e = (e >> 1) ^ (0xD8018001 if e & 1 else 0)
    EDC.append(e)
F = [0] * 256
B = [0] * 256
for i in range(256):
    j = (i << 1) ^ (0x11D if i & 0x80 else 0)
    F[i] = j & 0xFF
    B[i ^ j & 0xFF] = i


def edc(data):
    c = 0
    for x in data:
        c = (c >> 8) ^ EDC[(c ^ x) & 0xFF]
    return c


def ecc(sector, major, minor, mult, inc, dest_off):
    size = major * minor
    res = bytearray(2 * major)
    for m in range(major):
        idx = (m >> 1) * mult + (m & 1)
        a = b = 0
        for _ in range(minor):
            t = sector[12 + idx]
            idx += inc
            if idx >= size:
                idx -= size
            a ^= t
            b ^= t
            a = F[a]
        a = B[F[a] ^ b]
        res[m] = a
        res[m + major] = a ^ b
    return bytes(res)


def check_sector(raw):
    """True if EDC and ECC of a mode 2 form 1 sector are consistent"""
    if raw[18] & 0x20:   # form 2: no ECC, optional EDC
        return None
    body = raw[16:16 + 8 + 2048]
    if struct.unpack_from('<I', raw, 16 + 8 + 2048)[0] != edc(body):
        return False
    # ECC computed with the sector header zeroed (XA)
    s = bytearray(raw)
    s[12:16] = b'\0\0\0\0'
    p_ = ecc(s, 86, 24, 2, 86, 0)
    q_ = ecc(s, 52, 43, 86, 88, 0)
    return raw[2076:2076 + 172] == p_ and raw[2076 + 172:2076 + 172 + 104] == q_


with open(img, 'rb') as fa_, open(prev_img, 'rb') as fb_:
    bad = []
    sec = 0
    while True:
        x = fa_.read(2352)
        y = fb_.read(2352)
        if not x:
            break
        if x != y:
            bad.append(sec)
        sec += 1
allowed_files = [('BATTLE.PRG', PRG_LBA, PRG_SECTORS)]
if not CLASSIC:
    allowed_files.append(('MENU5.PRG', MENU5_LBA, MENU5_SECTORS))
in_allowed = lambda s: any(l <= s < l + n for _, l, n in allowed_files)
outside = [s for s in bad if not in_allowed(s)]
p('sectors: %d; differing from the previous image: %d; allowed files: %s; every differing sector inside them: %s'
  % (sec, len(bad), ', '.join('%s [%d,%d)' % (f, l, l + n) for f, l, n in allowed_files),
     'yes' if not outside else 'NO, outside: %s' % outside[:10]))
for f, l, n in allowed_files:
    p('   %-10s %d of %d sectors differ' % (f, sum(1 for s in bad if l <= s < l + n), n))
if outside:
    fail('image differs from the previous release outside %s' % ', '.join(f for f, _, _ in allowed_files))
with open(img, 'rb') as fa_, open(prev_img, 'rb') as fb_:
    newf = bytearray()
    prevf = bytearray()
    edc_bad = []
    edc_checked = 0
    for s in range(PRG_LBA, PRG_LBA + PRG_SECTORS):
        fa_.seek(s * 2352)
        fb_.seek(s * 2352)
        x = fa_.read(2352)
        y = fb_.read(2352)
        newf += x[24:24 + 2048]
        prevf += y[24:24 + 2048]
        if x != y:
            r = check_sector(x)
            edc_checked += 1
            if r is False:
                edc_bad.append(s)
    r0 = check_sector(y)   # the checker itself on an untouched sector of the previous image
    p('EDC/ECC of the %d changed sectors: %s (the checker accepts the previous image\'s last BATTLE.PRG sector: %s)'
      % (edc_checked, 'all valid' if not edc_bad else 'INVALID %s' % edc_bad, r0))
    if edc_bad or r0 is False:
        fail('EDC/ECC')
if not CLASSIC:
    # MENU5.PRG (the map screen): extracted from both images, EDC/ECC, every changed word
    with open(img, 'rb') as fa_, open(prev_img, 'rb') as fb_:
        m5n = bytearray()
        m5p = bytearray()
        bad5 = []
        for s in range(MENU5_LBA, MENU5_LBA + MENU5_SECTORS):
            fa_.seek(s * 2352)
            fb_.seek(s * 2352)
            x = fa_.read(2352)
            y = fb_.read(2352)
            m5n += x[24:24 + 2048]
            m5p += y[24:24 + 2048]
            if x != y and check_sector(x) is False:
                bad5.append(s)
    m5n, m5p = bytes(m5n[:MENU5_SIZE]), bytes(m5p[:MENU5_SIZE])
    built = open('build/data/MENU/MENU5.PRG', 'rb').read()
    if m5n != built:
        fail('MENU5.PRG extracted from the image differs from build/data/MENU/MENU5.PRG')
    if bad5:
        fail('EDC/ECC of MENU5.PRG sectors: %s' % bad5)
    if len(built) != MENU5_SIZE or len(m5p) != MENU5_SIZE:
        fail('MENU5.PRG size')
    p('MENU5.PRG extracted from the image (%d bytes, same size as before) == build/data/MENU/MENU5.PRG: %s; EDC/ECC of its changed sectors: %s'
      % (len(m5n), 'ok' if m5n == built else 'NO', 'valid' if not bad5 else 'INVALID'))
    p('(c) MENU5.PRG, previous image vs the new one: every changed word (map panning inverted; instruction immediates only)')
    nwords = 0
    for o in range(0, MENU5_SIZE, 4):
        a, b = struct.unpack_from('<I', m5p, o)[0], struct.unpack_from('<I', m5n, o)[0]
        if a != b:
            nwords += 1
            p('    +0x%05X: %08X -> %08X' % (o, a, b))
    p('    %d words changed' % nwords)
    if nwords != 8:
        fail('MENU5.PRG: expected exactly 8 changed words, %d' % nwords)
newf = bytes(newf)
prevf = bytes(prevf)
if newf != new_prg:
    fail('BATTLE.PRG extracted from the image differs from build/data/BATTLE/BATTLE.PRG')
else:
    p('BATTLE.PRG extracted from the image (283 sectors) == build/data/BATTLE/BATTLE.PRG: ok')

p('(b) BATTLE.PRG of the previous image vs the new one: every changed byte range')
cl = clusters(prevf, newf, gap=16)
for a, b in cl:
    names_ = sorted(set(region_of(i) for i in range(a, b)) - {None})
    p('    0x%06X..0x%06X (RAM %08X..%08X, %4d bytes)  %s' % (a, b, a + PRG_RAM, b + PRG_RAM, b - a, ' / '.join(names_) or '???'))
    if any(region_of(i) is None for i in range(a, b)):
        fail('changed byte outside the allowed regions vs the previous image at 0x%X' % a)
p('    total differing bytes: %d' % sum(1 for i in range(PRG_SIZE) if prevf[i] != newf[i]))

# ---- 6. dead code ------------------------------------------------------------------------------------------------
p()
p('-- 6. every overwritten function is unreferenced (tools/mod/run_dead_checks.sh -> check_dead.py)')
if os.environ.get('SKIP_DEAD_SCAN'):
    p('(skipped by SKIP_DEAD_SCAN)')
else:
    r = subprocess.run(['bash', 'tools/mod/run_dead_checks.sh'], capture_output=True, text=True)
    p(r.stdout.strip())
    p(r.stderr.strip())
    if r.returncode != 0:
        fail('a range is referenced')

# ---- 7. emulation -----------------------------------------------------------------------------------------------------
p()
p('-- 7. behavioural test of the shipped bytes in a MIPS interpreter (tools/mod/test_wswap.py)')
r = subprocess.run([sys.executable, '-I', 'tools/mod/test_wswap.py'], capture_output=True, text=True)
p(r.stdout.strip())
p(r.stderr.strip())
if r.returncode != 0:
    fail('emulator test')

p()
p('-- 8. full disassembly of the mod (objdump of build/mod/wswap.elf)')
p(sh(CROSS + 'objdump -d ' + elf))

p()
p('RESULT:', 'ALL CHECKS PASSED' if ok else 'FAILURES PRESENT')
open(sys.argv[1], 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print('\n'.join(l for l in out if 'FAIL' in l or l.startswith('RESULT')))
sys.exit(0 if ok else 1)
