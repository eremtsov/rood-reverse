#!/usr/bin/env python3
"""Disc-wide check that code ranges of SLUS_010.40 / BATTLE.PRG are unreferenced (docs: mod/zenith-edition.md).

    python3 -I tools/mod/check_refs_disc.py --vanilla VS.bin --zenith ZENITH.bin --repo . \\
        [--bins tools/mod/zenith_bins.txt] [--range START:SIZE ...] [--find] [--out REPORT.txt]

Runs with any Python 3 (Windows or Linux; the images can be on D:\\ / /mnt/d, the repository on \\\\wsl.localhost\\...).
Needs a tree in which `make` has run once (build/src/<file>/**/*.s, build/config/<file>/undefined_funcs_auto.txt; --build
points elsewhere). Takes about half a minute.

Why: the first Zenith build used six "dead" libcd/libds modules of SLUS_010.40 that TITLE.PRG (the FMV player) calls with
`jal` (StSetRing, StUnSetRing, StSetStream, StFreeRing, StGetNext, DsRead2). The checker of that build looked only at
files that are resident together with BATTLE.PRG. SLUS_010.40 is always resident, so every executable of the disc counts.

Code files: every file the decompilation has a splat.yaml for (config/**: SLUS_010.40, BATTLE, MENU, TITLE, ENDING, EFFECT,
GIM), plus every other *.PRG and EFFECT/*.BIN on the disc (load address of their directory's siblings), plus every other
Form 1 file that looks like MIPS code (many `jr ra` and `addiu sp,sp,-N` words; listed in the report, scanned without a
load address). The files are read from the ISO 9660 directory of each image, so the Zenith versions (with their extra code,
caves and sizes) are scanned too. Everything else (ZND/ZUD/MPD/SEQ/STR/XA/...) is data and is not scanned.

For every range [S, E) both images are scanned (every code file, the whole file decoded as instructions) for
  * j / jal whose target lies in [S-4, E) (S-4 is the delay slot of the `jr`/`j` in front of the range),
  * 32-bit aligned words whose value lies in [S-4, E) (also through the KSEG1 mirror 0xA0..),
  * lui + addiu / ori / load / store building an address in [S-4, E), the %hi carry included (the lui register is followed
    for up to 40 instructions until it is overwritten; `addu r,r,x` keeps following it: indexed tables),
  * PC-relative branches (beq/bne/blez/bgtz/bltz/bgez/bltzal/bgezal) into [S-4, E), files decoded at their load address;
from outside the range. A reference from a file whose own load span contains the address is not one into the range (TITLE.PRG
and ENDING.PRG are loaded where BATTLE.PRG is), it is listed as "aliased". And the strict rules:
  * S is a function start (or zero padding behind the previous function) and E is the next function start (or the end of
    the code), function starts from the decompilation (glabel of build/src, symbol_addrs, undefined_funcs_auto, func_ names),
  * the two words in front of S are an unconditional `jr`/`j` and its delay slot (no fall-through into the range; a branch
    onto that delay slot is one of the references above),
  * the bytes of [S-8, E) are identical in the vanilla and the Zenith image (Zenith does not use or patch the range).
A range PASSes when all of that holds. Exit code 1 if any range fails.

--find: list unreferenced functions of SLUS_010.40 and BATTLE.PRG (greatest fixed point: a function is dead when every
reference to it comes from dead functions of the same file; fall-through counts as a reference) grouped into maximal ranges that
satisfy the strict rules; candidates for tools/mod/zenith_bins.txt (each one is then checked like any range).
"""
import argparse
import array
import bisect
import os
import re
import struct
import sys

SEC = 2352
RAM_LO, RAM_HI = 0x8000F800, 0x800F8000     # only targets in SLUS_010.40 and BATTLE.PRG are kept
SLUS, BATTLE = 'SLUS_010.40', 'BATTLE/BATTLE.PRG'
LOADSTORE = {0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x28, 0x29, 0x2A, 0x2B, 0x2E, 0x31, 0x32, 0x39, 0x3A}


# ---- disc -------------------------------------------------------------------------------------------------------------------
class Image:
    def __init__(self, path):
        self.path = path
        self.f = open(path, 'rb')
        self.files = {}
        pvd = self.sector(16)
        assert pvd[1:6] == b'CD001', 'no ISO 9660 volume in %s' % path
        root = pvd[156:190]
        self._walk(struct.unpack_from('<I', root, 2)[0], struct.unpack_from('<I', root, 10)[0], '')

    def raw(self, n):
        self.f.seek(n * SEC)
        return self.f.read(SEC)

    def sector(self, n):
        return self.raw(n)[24:2072]

    def _walk(self, lba, size, prefix):
        for k in range((size + 2047) // 2048):
            d = self.sector(lba + k)
            p = 0
            while p < 2048 and d[p]:
                rec = d[p:p + d[p]]
                p += d[p]
                name = rec[33:33 + rec[32]]
                if name in (b'\0', b'\1'):
                    continue
                name = name.decode('ascii', 'replace').split(';')[0]
                elba, esize = struct.unpack_from('<I', rec, 2)[0], struct.unpack_from('<I', rec, 10)[0]
                if rec[25] & 2:
                    self._walk(elba, esize, prefix + name + '/')
                else:
                    self.files[prefix + name] = (elba, esize)

    def form2(self, name):
        return bool(self.raw(self.files[name][0])[18] & 0x20)

    def read(self, name):
        lba, size = self.files[name]
        n = (size + 2047) // 2048
        self.f.seek(lba * SEC)
        blob = self.f.read(n * SEC)
        return b''.join(blob[k * SEC + 24:k * SEC + 2072] for k in range(n))[:size]


# ---- the decompilation: load addresses, code regions, function starts -------------------------------------------------------
def parse_splat(repo):
    """disc path -> {'base': file offset 0 in RAM, 'code': [(lo, hi) file offsets], 'asm': ..., 'src': ..., 'cfg': ...}"""
    out = {}
    for dp, _, names in os.walk(os.path.join(repo, 'config')):
        if 'splat.yaml' not in names:
            continue
        txt = open(os.path.join(dp, 'splat.yaml'), encoding='utf8').read()
        tp = re.search(r'target_path:\s*data/(\S+)', txt).group(1)
        asm = re.search(r'asm_path:\s*(\S+)', txt).group(1)
        src = re.search(r'src_path:\s*(\S+)', txt).group(1)
        m = re.search(r'start:\s*(0x[0-9A-Fa-f]+)\s*\n\s*type:\s*code\s*\n\s*vram:\s*(0x[0-9A-Fa-f]+)', txt)
        seg_start, vram = int(m.group(1), 16), int(m.group(2), 16)
        subs = []
        for mm in re.finditer(r'^\s*- \[(0x[0-9A-Fa-f]+)(?:,\s*([\w.]+))?', txt, re.M):
            subs.append((int(mm.group(1), 16), mm.group(2) or ''))
        for mm in re.finditer(r'^\s*- \{\s*start:\s*(0x[0-9A-Fa-f]+),\s*type:\s*(\w+)', txt, re.M):
            subs.append((int(mm.group(1), 16), mm.group(2)))
        subs.sort()
        code = []
        for i, (o, t) in enumerate(subs):
            if t in ('c', 'asm', 'hasm'):
                hi = subs[i + 1][0] if i + 1 < len(subs) else None
                if code and code[-1][1] == o:
                    code[-1] = (code[-1][0], hi)
                else:
                    code.append((o, hi))
        out[tp] = {'base': vram - seg_start, 'code': code, 'asm': asm, 'src': src,
                   'cfg': os.path.relpath(dp, repo).replace(os.sep, '/')}
    return out


def function_starts(repo, info, build=None):
    """RAM address -> name, inside the code regions of the file"""
    base = info['base']
    inside = lambda a: any(base + lo <= a < (base + hi if hi is not None else 1 << 32) for lo, hi in info['code'])
    starts = {}
    build = build or os.path.join(repo, 'build')
    adir = os.path.join(build, os.path.relpath(info['asm'], 'build'))
    if not os.path.isdir(adir):
        sys.exit('%s not found: run make once (splat writes the assembly of every function there) or pass --build' % adir)
    for dp, _, names in os.walk(adir):
        for n in names:
            if not n.endswith('.s') or n.endswith(('.rodata.s', '.data.s', '.bss.s', '.sbss.s')) or n == 'header.s':
                continue
            lines = open(os.path.join(dp, n), errors='replace').read().split('\n')
            for i, l in enumerate(lines):
                m = re.match(r'\s*glabel\s+(\w+)', l)
                if not m:
                    continue
                for l2 in lines[i + 1:i + 4]:
                    mm = re.match(r'\s*/\*\s*[0-9A-Fa-f]+\s+([0-9A-Fa-f]{8})\s+[0-9A-Fa-f]{8}\s*\*/\s+([a-z.][\w.]*)', l2)
                    if mm:
                        a = int(mm.group(1), 16)
                        if not mm.group(2).startswith('.') and inside(a):
                            starts.setdefault(a, m.group(1))
                        break
    for p in (os.path.join(repo, info['cfg'], 'symbol_addrs.txt'), os.path.join(build, info['cfg'], 'undefined_funcs_auto.txt')):
        if os.path.exists(p):
            for l in open(p, errors='replace'):
                m = re.match(r'\s*(\w+)\s*=\s*(0x[0-9A-Fa-f]+);(.*)', l)
                if m:
                    a = int(m.group(2), 16)
                    if inside(a) and a % 4 == 0:
                        starts.setdefault(a, m.group(1))
    pat = re.compile(r'(?<![A-Za-z0-9_])func_(8[0-9A-Fa-f]{7})(?![A-Za-z0-9_])')
    sdir = os.path.join(repo, info['src'])
    for dp, _, names in os.walk(sdir):
        for n in names:
            if n.endswith(('.c', '.h', '.s')):
                for m in pat.finditer(open(os.path.join(dp, n), errors='replace').read()):
                    a = int(m.group(1), 16)
                    if inside(a) and a % 4 == 0:
                        starts.setdefault(a, 'func_' + m.group(1).upper())
    return starts


# ---- references --------------------------------------------------------------------------------------------------------------
def ram(v):
    if 0xA0000000 <= v < 0xA0200000:
        v -= 0x20000000
    return v if RAM_LO <= v < RAM_HI else None


def scan(data, base):
    """[(target, kind, file offset)] of every j/jal/word/lui-pair/branch target in RAM; base None = load address unknown"""
    n = len(data) & ~3
    words = array.array('I')
    words.frombytes(data[:n])
    if sys.byteorder != 'little':
        words.byteswap()
    out = []
    ap = out.append
    nw = len(words)
    for i, w in enumerate(words):
        op = w >> 26
        if op == 2 or op == 3:
            pc = (base + i * 4) if base is not None else 0x80000000
            ap((((pc + 4) & 0xF0000000) | ((w & 0x03FFFFFF) << 2), 'jal' if op == 3 else 'j', i * 4))
        if (w >> 28) in (8, 0xA):
            t = ram(w)
            if t is not None:
                ap((t, 'word', i * 4))
        if base is not None and (op in (4, 5, 6, 7) or (op == 1 and ((w >> 16) & 31) in (0, 1, 16, 17))):
            s = w & 0xFFFF
            if s & 0x8000:
                s -= 0x10000
            ap(((base + i * 4 + 4 + s * 4) & 0xFFFFFFFF, 'branch', i * 4))
        if op == 0x0F:
            hi = w & 0xFFFF
            if not (0x8000 <= hi <= 0x8021 or 0xA000 <= hi <= 0xA021):
                continue
            reg = (w >> 16) & 31
            if reg == 0:
                continue
            for j in range(i + 1, min(i + 41, nw)):
                w2 = words[j]
                op2 = w2 >> 26
                rs2, rt2, rd2 = (w2 >> 21) & 31, (w2 >> 16) & 31, (w2 >> 11) & 31
                imm = w2 & 0xFFFF
                val = None
                if op2 == 0x09 and rs2 == reg:            # addiu
                    val = ((hi << 16) + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF
                elif op2 == 0x0D and rs2 == reg:          # ori
                    val = (hi << 16) | imm
                elif op2 in LOADSTORE and rs2 == reg:
                    val = ((hi << 16) + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF
                if val is not None:
                    t = ram(val)
                    if t is not None:
                        ap((t, 'lui+%s' % ('addiu' if op2 == 9 else 'ori' if op2 == 0xD else 'ldst'), i * 4))
                # is the register overwritten?
                if op2 == 0:
                    f = w2 & 63
                    if rd2 == reg and f not in (8, 9, 0x18, 0x19, 0x1A, 0x1B, 0x11, 0x13):
                        if f in (0x20, 0x21) and reg in (rs2, rt2):
                            continue                      # addu r, r, x: still the %hi base of an indexed table
                        break
                    if f == 9 and rd2 == reg:
                        break
                elif op2 == 0x0F or op2 in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26):
                    if rt2 == reg:
                        break
                elif op2 == 3 and reg == 31:
                    break
                elif op2 == 0x12 and ((w2 >> 21) & 31) in (0, 2) and rt2 == reg:   # mfc2 / cfc2
                    break
    return out


def is_unc(w):
    """jr rs (rt = rd = shamt = 0) or j"""
    return ((w >> 26) == 0 and (w & 63) == 8 and (w & 0x001FFFC0) == 0) or (w >> 26) == 2


def range_start(vd, vb, a):
    """where a range may start that ends in front of function a: behind the delay slot of the `jr`/`j` in front of it (zero
    padding between that and a is included), None if the code in front may fall through"""
    q = a - 4
    while q > vb and struct.unpack_from('<I', vd, q - vb)[0] == 0:
        q -= 4
    if is_unc(struct.unpack_from('<I', vd, q - vb)[0]) and q + 8 <= a:
        return q + 8                      # jr; nop (the delay slot is the first zero word)
    if is_unc(struct.unpack_from('<I', vd, q - vb - 4)[0]):
        return q + 4                      # jr; <delay slot>
    return None


def is_codelike(data):
    n = len(data) & ~3
    if n < 64:
        return False
    words = array.array('I')
    words.frombytes(data[:n])
    jr = sum(1 for w in words if w == 0x03E00008)
    sp = sum(1 for w in words if (w & 0xFFFF8000) == 0x27BD8000)
    return jr >= 4 and sp >= 4


class Disc:
    """code files of one image, their load addresses and their references"""

    def __init__(self, path, splat, label, sizes=None):
        self.label = label
        self.img = Image(path)
        self.code = {}       # name -> (base or None, data, why)
        self.regions = {}    # name -> [(lo, hi)] file offsets of code (decomp files; bytes behind the vanilla size count as code)
        for name in sorted(self.img.files):
            why, base = None, None
            if name in splat:
                why, base = 'decomp', splat[name]['base']
            elif name.endswith('.PRG') or (name.startswith('EFFECT/') and name.endswith('.BIN')):
                why = 'executable'
                d = os.path.dirname(name)
                sib = [v['base'] for k, v in splat.items() if os.path.dirname(k) == d and k.endswith(name[-4:]) and 'MAINMENU' not in k]
                base = max(set(sib), key=sib.count) if sib else None
            if why is None:
                if self.img.form2(name) or self.img.files[name][1] > 4 << 20:
                    continue
                data = self.img.read(name)
                if not is_codelike(data):
                    continue
                why = 'looks like code'
                self.code[name] = (None, data, why)
                continue
            self.code[name] = (base, self.img.read(name), why)
            if name in splat:
                n = len(self.code[name][1])
                reg = [(lo, hi if hi is not None else n) for lo, hi in splat[name]['code']]
                van = (sizes or {}).get(name, n)
                if n > van:
                    reg.append((van, n))   # Zenith's code behind the end of the original file (BATTLE.PRG tail)
                self.regions[name] = reg
        self.refs = []
        for name, (base, data, why) in self.code.items():
            for t, kind, off in scan(data, base):
                self.refs.append((t, kind, name, off))
        self.refs.sort()
        self.keys = [r[0] for r in self.refs]

    def span(self, name):
        base, data, _ = self.code[name]
        return (base, base + len(data)) if base is not None else None

    def in_code(self, name, off):
        reg = self.regions.get(name)
        return reg is None or any(lo <= off < hi for lo, hi in reg)

    def query(self, lo, hi):
        i = bisect.bisect_left(self.keys, lo)
        j = bisect.bisect_left(self.keys, hi)
        return self.refs[i:j]


# ---- checks ---------------------------------------------------------------------------------------------------------------------
def owner(addr, discs):
    for name in (SLUS, BATTLE):
        s = discs[0].span(name)
        if s[0] <= addr < s[1]:
            return name
    return None


def classify(r, rfile, start, end, disc):
    t, kind, name, off = r
    base = disc.code[name][0]
    src = base + off if base is not None else None
    if name == rfile and src is not None and start <= src < end:
        return 'self'
    if kind != 'word' and not disc.in_code(name, off):
        return 'data-region'            # an instruction pattern in the data part of a decomp file: not executed
    if name != rfile:
        sp = disc.span(name)
        if sp and sp[0] <= t < sp[1]:
            return 'aliased'
    return 'ref'


def fmt_ref(r, disc):
    t, kind, name, off = r
    base = disc.code[name][0]
    return '%-11s %-26s +0x%06X%s -> %08X' % (kind, name, off, ' (RAM %08X)' % (base + off) if base is not None else '', t)


def dis1(w):
    op = w >> 26
    if w == 0:
        return 'nop'
    if op == 0 and (w & 63) == 8:
        return 'jr $%d' % ((w >> 21) & 31)
    if op == 2:
        return 'j 0x%08X' % (0x80000000 | ((w & 0x3FFFFFF) << 2))
    if op == 3:
        return 'jal 0x%08X' % (0x80000000 | ((w & 0x3FFFFFF) << 2))
    return '%08X' % w


def check_range(start, size, discs, fstarts, out):
    """discs = (vanilla, zenith); returns True if the range passes"""
    end = start + size
    rfile = owner(start, discs)
    p = lambda s: out.append(s)
    p('== %08X..%08X (%d bytes) in %s' % (start, end, size, rfile))
    if rfile is None:
        p('   FAIL: not in SLUS_010.40 or BATTLE.PRG')
        return False
    ok = True
    starts = fstarts[rfile]
    bounds = sorted(starts)
    van, zen = discs
    vb, vd, _ = van.code[rfile]
    zb, zd, _ = zen.code[rfile]
    o = start - vb
    # function boundaries
    if start in starts:
        p('   start: function %s' % starts[start])
    else:
        nxt = bounds[bisect.bisect_right(bounds, start)] if bisect.bisect_right(bounds, start) < len(bounds) else None
        if nxt is not None and nxt <= end and not any(vd[o:nxt - vb]):
            p('   start: %d bytes of zero padding in front of function %s' % (nxt - start, starts[nxt]))
        else:
            p('   FAIL start: not a function start (inside %s)' % starts.get(max([a for a in bounds if a < start] or [0]), '?'))
            ok = False
    inner = [a for a in bounds if start < a < end]
    if inner:
        p('   functions inside: %s' % ', '.join('%s@%08X' % (starts[a], a) for a in inner))
    nb = bounds[bisect.bisect_right(bounds, end - 1)] if bisect.bisect_right(bounds, end - 1) < len(bounds) else None
    code_end = max(vb + (hi if hi is not None else len(vd)) for lo, hi in parse_cache['splat'][rfile]['code'])
    if end in starts:
        p('   end: next function %s' % starts[end])
    elif end == code_end:
        p('   end: end of the code')
    else:
        p('   FAIL end: %08X is not a function start (next one: %s)' % (end, '%08X' % nb if nb else '-'))
        ok = False
    # no fall-through into the range
    w1, w2 = struct.unpack_from('<II', vd, o - 8)
    unc = is_unc(w1)
    p('   in front: %08X: %s / %s%s' % (start - 8, dis1(w1), dis1(w2), '' if unc else '   FAIL: may fall through'))
    ok &= unc
    e1, e2 = struct.unpack_from('<II', vd, end - vb - 8)
    p('   last pair: %s / %s%s' % (dis1(e1), dis1(e2), '' if (e1 == 0x03E00008 or (e1 >> 26) == 2) else '   (note: does not end in jr ra / j)'))
    # identical in both images
    if vd[o - 8:end - vb] != zd[o - 8:end - vb]:
        diff = [vb + k for k in range(o - 8, end - vb) if vd[k] != zd[k]]
        p('   FAIL: Zenith changed %d bytes of [S-8, E), first at %08X' % (len(diff), diff[0]))
        ok = False
    else:
        p('   bytes [S-8, E) identical in vanilla and Zenith')
    # references
    for disc in discs:
        refs = disc.query(start - 4, end)
        cls = {'ref': [], 'self': [], 'aliased': [], 'data-region': []}
        for r in refs:
            cls[classify(r, rfile, start, end, disc)].append(r)
        p('   %-7s refs from outside: %d (self %d, aliased %d, instruction patterns in data parts %d)' % (
            disc.label, len(cls['ref']), len(cls['self']), len(cls['aliased']), len(cls['data-region'])))
        for r in cls['ref'][:30]:
            p('      REF  ' + fmt_ref(r, disc))
        for r in cls['data-region'][:6]:
            p('      data  ' + fmt_ref(r, disc))
        for r in cls['aliased'][:6]:
            p('      alias ' + fmt_ref(r, disc))
        if len(cls['aliased']) > 6:
            p('      ... %d more aliased' % (len(cls['aliased']) - 6))
        ok &= not cls['ref']
    p('   RESULT: %s' % ('PASS' if ok else 'FAIL'))
    return ok


# ---- dead-function search --------------------------------------------------------------------------------------------------
def find_dead(rfile, discs, fstarts, out):
    starts = fstarts[rfile]
    van = discs[0]
    vb, vd, _ = van.code[rfile]
    code = parse_cache['splat'][rfile]['code']
    regions = [(vb + lo, vb + (hi if hi is not None else len(vd))) for lo, hi in code]
    bounds = sorted(starts)
    funcs = []
    for i, a in enumerate(bounds):
        reg = [r for r in regions if r[0] <= a < r[1]][0]
        e = min(bounds[i + 1] if i + 1 < len(bounds) else reg[1], reg[1])
        funcs.append((a, e))
    fidx = lambda addr: (lambda k: k if k >= 0 and funcs[k][0] <= addr < funcs[k][1] else None)(bisect.bisect_right(bounds, addr) - 1)
    # edges: for each function, the set of referencing functions (index) or 'ext'
    refby = [set() for _ in funcs]
    for disc in discs:
        b, d, _ = disc.code[rfile]
        for r in disc.query(vb, vb + len(vd)):
            t, kind, name, off = r
            k = fidx(t)
            ks = [k] if k is not None else []
            if k is not None and t == funcs[k][1] - 4 and k + 1 < len(funcs) and funcs[k + 1][0] == funcs[k][1]:
                ks.append(k + 1)                       # onto the last delay slot: falls into the next function
            if not ks:
                continue
            if kind != 'word' and not disc.in_code(name, off):
                continue                               # instruction pattern in a data part
            if name == rfile:
                s = fidx(disc.code[name][0] + off)
                src = s if s is not None else 'ext'
            else:
                sp = disc.span(name)
                if sp and sp[0] <= t < sp[1]:
                    continue                           # aliased (TITLE/ENDING at BATTLE's address)
                src = 'ext'
            for kk in ks:
                if src != kk:
                    refby[kk].add(src)
    # fall-through
    for k in range(len(funcs) - 1):
        a, e = funcs[k]
        if funcs[k + 1][0] != e:
            continue
        if range_start(vd, vb, e) is None:
            refby[k + 1].add(k)           # function k may fall through into k + 1
    dead = set(range(len(funcs)))
    changed = True
    while changed:
        changed = False
        for k in list(dead):
            if any(s == 'ext' or s not in dead for s in refby[k]):
                dead.discard(k)
                changed = True
    # maximal runs of adjacent dead functions; then the strict rules decide where a range may start
    zb, zd, _ = discs[1].code[rfile]
    ranges = []
    k = 0
    while k < len(funcs):
        if k not in dead:
            k += 1
            continue
        j = k
        while j + 1 < len(funcs) and j + 1 in dead and funcs[j + 1][0] == funcs[j][1]:
            j += 1
        # split where Zenith changed bytes, start only behind an unconditional jr/j
        cur = None
        for m in range(k, j + 1):
            a, e = funcs[m]
            rs = range_start(vd, vb, a)
            unc = rs is not None
            if unc and cur is None:
                a = rs
            same = vd[a - vb - 8:e - vb] == zd[a - vb - 8:e - vb]
            if not same:
                if cur:
                    ranges.append(cur)
                cur = None
                continue
            if cur is None:
                if unc:
                    cur = [a, e, [m]]
            else:
                cur[1] = e
                cur[2].append(m)
        if cur:
            ranges.append(cur)
        k = j + 1
    out.append('== dead functions of %s: %d of %d (%d bytes); ranges that satisfy the strict rules: %d (%d bytes)' % (
        rfile, len(dead), len(funcs), sum(funcs[k][1] - funcs[k][0] for k in dead), len(ranges), sum(r[1] - r[0] for r in ranges)))
    for a, e, ms in sorted(ranges, key=lambda r: -(r[1] - r[0])):
        out.append('   %08X %5d  %s' % (a, e - a, '+'.join(starts[funcs[m][0]] for m in ms)))
    return ranges


parse_cache = {}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--vanilla', required=True)
    ap.add_argument('--zenith', required=True)
    ap.add_argument('--repo', required=True, help='the decompilation (config/, src/)')
    ap.add_argument('--build', help='its build directory (default REPO/build): build/src/<file>/**/*.s, build/config/')
    ap.add_argument('--bins', help='zenith_bins.txt: check every range listed there')
    ap.add_argument('--range', action='append', default=[], help='START:SIZE (hex start, decimal or 0x size)')
    ap.add_argument('--find', action='store_true')
    ap.add_argument('--out')
    a = ap.parse_args()
    out = []
    splat = parse_splat(a.repo)
    parse_cache['splat'] = splat
    fstarts = {f: function_starts(a.repo, splat[f], a.build) for f in (SLUS, BATTLE)}
    van = Disc(a.vanilla, splat, 'vanilla')
    discs = (van, Disc(a.zenith, splat, 'Zenith', {n: len(v[1]) for n, v in van.code.items()}))
    for d in discs:
        kinds = {}
        for n, (b, data, why) in d.code.items():
            kinds.setdefault(why, []).append(n)
        out.append('%s: %s; %d code files (%s), %d references into RAM' % (d.label, d.img.path, len(d.code),
                   ', '.join('%s %d' % (k, len(v)) for k, v in sorted(kinds.items())), len(d.refs)))
        for n in kinds.get('looks like code', []) + kinds.get('executable', []):
            out.append('   %-16s %s (load address %s)' % (d.code[n][2], n, '%08X' % d.code[n][0] if d.code[n][0] is not None else 'unknown'))
    missing = [f for f in splat if f not in discs[0].code]
    if missing:
        out.append('decomp files missing on the disc: %s' % missing)
    out.append('function starts: %s' % ', '.join('%s %d' % (f, len(s)) for f, s in fstarts.items()))
    ranges = []
    if a.bins:
        for l in open(a.bins):
            l = l.strip()
            if l and not l.startswith('#'):
                p = l.split(None, 4)
                ranges.append((int(p[1], 16), int(p[2]), p[0] + ' ' + (p[4] if len(p) > 4 else '')))
    for r in a.range:
        s, z = r.split(':')
        ranges.append((int(s, 16), int(z, 0), ''))
    allok = True
    summary = []
    for s, z, note in ranges:
        if note:
            out.append('-- %s' % note)
        ok = check_range(s, z, discs, fstarts, out)
        summary.append('%08X %5d %s  %s' % (s, z, 'PASS' if ok else 'FAIL', note))
        allok &= ok
    if a.find:
        for f in (SLUS, BATTLE):
            find_dead(f, discs, fstarts, out)
    if summary:
        out.append('== summary')
        out.extend('   ' + s for s in summary)
        out.append('ALL PASS' if allok else 'SOME RANGES FAIL')
    text = '\n'.join(out) + '\n'
    if a.out:
        open(a.out, 'w', encoding='utf8').write(text)
    sys.stdout.write(text)
    sys.exit(0 if allok else 1)


if __name__ == '__main__':
    main()
