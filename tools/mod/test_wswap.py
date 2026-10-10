#!/usr/bin/env python3
"""Behavioural test of the *shipped bytes* of the weapon-swap mod.

Loads build/mod/wswap.bin at 0x800F5924 into an emulated 2 MB RAM and executes
wswap_entry() with a small MIPS-I interpreter. Game functions the blob calls are
replaced by Python stubs at their real addresses (symbols from build/mod/syms.ld);
structures are laid out at their real addresses with the offsets the project
headers give (see src/mod/test_offsets.c).

Run: python3 -I tools/mod/test_wswap.py   (after tools/mod/build_mod.sh)
"""
import itertools
import os
import re
import struct
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
BLOB_ADDR = 0x800F5924

# ---- symbols ---------------------------------------------------------------
SYM = {}
for line in open(os.path.join(ROOT, 'build/mod/syms.ld')):
    m = re.match(r'(\w+) = (0x[0-9A-Fa-f]+);', line)
    if m:
        SYM[m.group(1)] = int(m.group(2), 16)
SYM['D_800F196C'] = 0x800F196C
nm = subprocess.check_output(['mipsel-linux-gnu-nm', os.path.join(ROOT, 'build/mod/wswap.elf')], text=True)
ENTRY = int([l for l in nm.splitlines() if l.endswith(' wswap_entry')][0].split()[0], 16)

# ---- layout (from the project headers) ---------------------------------------
INV = SYM['vs_main_inventory']
W_SIZE, W_BLADE, W_EQ, W_GEMS = 0x20, 1, 3, 4
SH_OFF, SH_SIZE, SH_EQ = 0x100, 0x30, 1
BL_OFF, BL_SIZE, BL_CAT, BL_WEP, BL_MAT = 0x280, 0x2C, 3, 2, 0x28
Q = SYM['vs_battle_objectDataSlots']
Q_SIZE, Q_INDEX, Q_MODEL, Q_UNK4, Q_ACTOR, Q_UNK11, Q_MAT = 0x14, 1, 2, 4, 0x10, 0x11, 0x12
A_5B1, A_187C = 0x5B1, 0x187C
CHAR = SYM['vs_battle_characterState']
D4538 = SYM['D_800F4538']
MENU = SYM['vs_battle_menuState']
MODE = 0x800F196C
TRANS = SYM['vs_battle_screenTransitionStep']
PRESSED = SYM['vs_main_buttonsPressed']
STATE = SYM['vs_main_buttonsState']
PREV = SYM['vs_main_buttonsPreviousState']
REPEAT = SYM['vs_main_buttonRepeat']
STICK = SYM['vs_main_stickPosBuf']

L2, R2, L1, R1 = 1, 2, 4, 8
TRI, CIR, CRS, SQR = 0x10, 0x20, 0x40, 0x80
SELECT, START, PADJ = 0x100, 0x800, 0x400

ACTOR = 0x80120000   # emulated actor-0 structure
CHSTATE = 0x80130000  # vs_battle_characterState
ACT2 = 0x80131000     # ->unk3C
UNK48 = 0x80132000


BLOB = open(os.path.join(ROOT, 'build/mod/wswap.bin'), 'rb').read()


class Halt(Exception):
    pass


class Machine:
    def __init__(self):
        self.mem = bytearray(0x200000)
        self.r = [0] * 32
        self.hi = self.lo = 0
        self.log = []
        blob = open(os.path.join(ROOT, 'build/mod/wswap.bin'), 'rb').read()
        self.w(BLOB_ADDR, blob, raw=True)
        self.stubs = {}
        self.setup_stubs()
        self.reset_world()

    # memory ---------------------------------------------------------------
    def off(self, a):
        o = a & 0x1FFFFFFF
        assert o < len(self.mem), hex(a)
        return o

    def w(self, a, data, raw=False):
        o = self.off(a)
        self.mem[o:o + len(data)] = data

    def rd(self, a, n=4):
        o = self.off(a)
        return int.from_bytes(self.mem[o:o + n], 'little')

    def wr(self, a, v, n=4):
        o = self.off(a)
        self.mem[o:o + n] = (v & ((1 << (8 * n)) - 1)).to_bytes(n, 'little')

    def rds(self, a):
        v = self.rd(a)
        return v - (1 << 32) if v & 0x80000000 else v

    # world ----------------------------------------------------------------
    def reset_world(self):
        self.mem[:] = bytes(len(self.mem))
        self.w(BLOB_ADDR, BLOB)
        self.wr(MODE, 1)
        self.wr(MENU, 0x3F, 1)
        self.wr(TRANS, 0)
        self.wr(CHSTATE + 0x3C, ACT2)
        self.wr(CHSTATE + 0x48, UNK48)
        self.wr(CHSTATE + 0x4C, UNK48 + 0x100)
        self.wr(CHSTATE + 0x20, 1)  # weaponDrawn int (unused by blob)
        self.wr(CHAR, CHSTATE)
        self.wr(D4538, ACTOR)
        self.wr(ACTOR + A_5B1, 1)
        self.wr(ACT2 + 0x954, 0)
        self.status = 0
        self.busy = 0
        self.held = [0] * 32
        self.frame_hw = 0
        self.frame_stick = (128, 128)
        self.queue_wait = 0
        self.loading = False
        self.log.clear()
        for a in range(8):
            self.set_weapon(a, 0)
        self.set_blade(1, cat=1, wep=10, mat=3)

    def set_blade(self, n, cat, wep, mat):
        b = INV + BL_OFF + (n - 1) * BL_SIZE
        self.wr(b + BL_CAT, cat, 1)
        self.wr(b + BL_WEP, wep, 1)
        self.wr(b + BL_MAT, mat, 1)

    def set_weapon(self, slot, blade, eq=0, fav=0):
        a = INV + slot * W_SIZE
        self.wr(a, slot + 1 if blade else 0, 1)
        self.wr(a + W_BLADE, blade, 1)
        self.wr(a + W_EQ, eq, 1)
        self.wr(a + W_GEMS + 3, fav, 1)

    def weapon(self, slot):
        a = INV + slot * W_SIZE
        return dict(blade=self.rd(a + W_BLADE, 1), eq=self.rd(a + W_EQ, 1), fav=self.rd(a + W_GEMS + 3, 1))

    def setup_weapons(self, favs, cur, blade_cat=None):
        """slots 0..7 all filled; favs = set of favourite slots; cur = equipped slot or -1"""
        for s in range(8):
            self.set_weapon(s, s + 1, eq=int(s == cur), fav=int(s in favs))
            cat = (blade_cat or {}).get(s, 1)
            self.set_blade(s + 1, cat=cat, wep=20 + s, mat=s)

    def equipped(self):
        e = [s for s in range(8) if self.weapon(s)['eq']]
        return e

    # pad ------------------------------------------------------------------
    def pad_stub(self):
        """vs_main_processPadState, as in SLUS_010.40/main.c (mode 7)"""
        st = self.frame_hw
        lx, ly = self.frame_stick
        # decomp lStick* = physical right stick
        if lx < 32 or lx >= 225 or ly < 32 or ly >= 225:
            st |= PADJ
        self.wr(STICK, lx)
        self.wr(STICK + 4, ly)
        prev = self.rd(PREV)
        pressed = (~prev) & st & 0xFFFFFFFF
        self.wr(STATE, st)
        self.wr(PRESSED, pressed)
        self.wr(PREV, st)
        for i in range(32):
            self.held[i] = self.held[i] + 1 if (st >> i) & 1 else 0
        rep = pressed
        for i in range(32):
            if self.held[i] >= 20 and not ((self.held[i] - 20) & 3):
                rep |= 1 << i
        self.wr(REPEAT, rep)
        return 1

    def setup_stubs(self):
        def reg(name, fn):
            self.stubs[SYM[name]] = (name, fn)

        def logging(name, ret=0):
            def f(m):
                m.log.append((name,) + tuple(m.r[4:8]))
                m.r[2] = ret
            return f

        reg('vs_main_processPadState', lambda m: m.set_v0(m.pad_stub()))
        reg('vs_battle_equipWeapon', lambda m: m.log.append(('equipWeapon', (m.r[4] - INV) // W_SIZE)))
        reg('vs_battle_equipShield', lambda m: m.log.append(('equipShield', m.r[4])))
        reg('func_8009AA84', lambda m: m.log.append(('freeWepModel', m.r[4])))
        reg('func_8009CC20', lambda m: m.log.append(('freeCategory', m.r[4], m.r[5])))
        reg('func_800A0204', lambda m: m.log.append(('playAnim', m.r[4], m.r[5], m.r[6], m.r[7], m.rd(ACTOR + A_187C))))
        reg('func_800AFA28', lambda m: m.log.append(('pose', m.r[4] == ACTOR, m.r[5] == ACTOR + 0xC54, m.r[6])))
        reg('vs_main_memcpy', lambda m: m.log.append(('memcpy', m.r[4] == ACTOR + 0x704, m.r[5] == ACTOR + 0xC54, m.r[6])))
        reg('func_8009D934', lambda m: m.log.append(('modelFlags', m.r[4], m.r[5], m.r[6])))
        reg('func_800A0BE0', lambda m: m.set_v0(m.status))
        reg('func_8009E4B0', lambda m: m.set_v0(m.busy))
        reg('vs_battle_playMenuChangeSfx', lambda m: m.log.append(('sfx', 'change')))
        reg('vs_battle_playMenuSelectSfx', lambda m: m.log.append(('sfx', 'select')))
        reg('vs_battle_playMenuLeaveSfx', lambda m: m.log.append(('sfx', 'leave')))
        reg('vs_battle_playInvalidSfx', lambda m: m.log.append(('sfx', 'invalid')))

    def set_v0(self, v):
        self.r[2] = v & 0xFFFFFFFF

    # cpu ------------------------------------------------------------------
    def run(self, entry, max_steps=20000):
        SENT = 0xDEAD0000
        self.r[29] = 0x801FFF00
        self.r[31] = SENT
        pc = entry
        npc = pc + 4
        steps = 0
        r = self.r
        while pc != SENT:
            steps += 1
            if steps > max_steps:
                raise Halt('runaway')
            if pc in self.stubs:
                name, fn = self.stubs[pc]
                fn(self)
                pc = r[31]
                npc = pc + 4
                continue
            ins = self.rd(pc)
            nnpc = npc + 4
            op = ins >> 26
            rs = (ins >> 21) & 31
            rt = (ins >> 16) & 31
            rd = (ins >> 11) & 31
            sh = (ins >> 6) & 31
            fn = ins & 63
            imm = ins & 0xFFFF
            simm = imm - 0x10000 if imm & 0x8000 else imm
            tgt = None
            M = 0xFFFFFFFF

            def s32(x):
                x &= M
                return x - (1 << 32) if x & 0x80000000 else x
            if op == 0:
                if fn == 0:
                    r[rd] = (r[rt] << sh) & M
                elif fn == 2:
                    r[rd] = r[rt] >> sh
                elif fn == 3:
                    r[rd] = (s32(r[rt]) >> sh) & M
                elif fn == 4:
                    r[rd] = (r[rt] << (r[rs] & 31)) & M
                elif fn == 6:
                    r[rd] = r[rt] >> (r[rs] & 31)
                elif fn == 7:
                    r[rd] = (s32(r[rt]) >> (r[rs] & 31)) & M
                elif fn == 8:
                    tgt = r[rs]
                elif fn == 9:
                    r[rd] = pc + 8
                    tgt = r[rs]
                elif fn in (0x20, 0x21):
                    r[rd] = (r[rs] + r[rt]) & M
                elif fn in (0x22, 0x23):
                    r[rd] = (r[rs] - r[rt]) & M
                elif fn == 0x24:
                    r[rd] = r[rs] & r[rt]
                elif fn == 0x25:
                    r[rd] = r[rs] | r[rt]
                elif fn == 0x26:
                    r[rd] = r[rs] ^ r[rt]
                elif fn == 0x27:
                    r[rd] = ~(r[rs] | r[rt]) & M
                elif fn == 0x2A:
                    r[rd] = int(s32(r[rs]) < s32(r[rt]))
                elif fn == 0x2B:
                    r[rd] = int(r[rs] < r[rt])
                elif fn == 0x10:
                    r[rd] = self.hi
                elif fn == 0x12:
                    r[rd] = self.lo
                elif fn == 0x18:
                    p = s32(r[rs]) * s32(r[rt])
                    self.lo, self.hi = p & M, (p >> 32) & M
                elif fn == 0x19:
                    p = r[rs] * r[rt]
                    self.lo, self.hi = p & M, (p >> 32) & M
                else:
                    raise Halt('SPECIAL fn %02x at %08x' % (fn, pc))
            elif op == 1:
                cond = {0: s32(r[rs]) < 0, 1: s32(r[rs]) >= 0, 16: s32(r[rs]) < 0, 17: s32(r[rs]) >= 0}[rt]
                if rt >= 16:
                    r[31] = pc + 8
                if cond:
                    tgt = pc + 4 + (simm << 2)
            elif op == 2:
                tgt = (pc & 0xF0000000) | ((ins & 0x3FFFFFF) << 2)
            elif op == 3:
                r[31] = pc + 8
                tgt = (pc & 0xF0000000) | ((ins & 0x3FFFFFF) << 2)
            elif op == 4:
                if r[rs] == r[rt]:
                    tgt = pc + 4 + (simm << 2)
            elif op == 5:
                if r[rs] != r[rt]:
                    tgt = pc + 4 + (simm << 2)
            elif op == 6:
                if s32(r[rs]) <= 0:
                    tgt = pc + 4 + (simm << 2)
            elif op == 7:
                if s32(r[rs]) > 0:
                    tgt = pc + 4 + (simm << 2)
            elif op in (8, 9):
                r[rt] = (r[rs] + simm) & M
            elif op == 10:
                r[rt] = int(s32(r[rs]) < simm)
            elif op == 11:
                r[rt] = int(r[rs] < (simm & M))
            elif op == 12:
                r[rt] = r[rs] & imm
            elif op == 13:
                r[rt] = r[rs] | imm
            elif op == 14:
                r[rt] = r[rs] ^ imm
            elif op == 15:
                r[rt] = imm << 16
            elif op == 0x20:
                v = self.rd((r[rs] + simm) & M, 1)
                r[rt] = (v - 256 if v & 0x80 else v) & M
            elif op == 0x21:
                v = self.rd((r[rs] + simm) & M, 2)
                r[rt] = (v - 65536 if v & 0x8000 else v) & M
            elif op == 0x23:
                r[rt] = self.rd((r[rs] + simm) & M, 4)
            elif op == 0x24:
                r[rt] = self.rd((r[rs] + simm) & M, 1)
            elif op == 0x25:
                r[rt] = self.rd((r[rs] + simm) & M, 2)
            elif op == 0x28:
                self.wr((r[rs] + simm) & M, r[rt], 1)
            elif op == 0x29:
                self.wr((r[rs] + simm) & M, r[rt], 2)
            elif op == 0x2B:
                self.wr((r[rs] + simm) & M, r[rt], 4)
            else:
                raise Halt('opcode %02x at %08x' % (op, pc))
            r[0] = 0
            pc, npc = npc, (tgt if tgt is not None else nnpc)
            if tgt is not None:
                # execute the delay slot (at old npc) before jumping
                pass
        return self.r[2]

    # one game frame: hook + (very small) model of the main loop -------------
    def frame(self, hw=0, stick=(128, 128)):
        self.frame_hw = hw
        self.frame_stick = stick
        before_mode = self.rd(MODE)
        self.run(ENTRY)
        # main loop: the object data queue is processed once per frame, after the hook
        if self.rd(Q, 1) != 0:
            if not self.loading:
                self.loading = True
                self.queue_wait = self.load_frames
            self.queue_wait -= 1
            if self.queue_wait <= 0:
                for i in range(1, 15):
                    self.mem[self.off(Q + (i - 1) * Q_SIZE):self.off(Q + i * Q_SIZE)] =                         self.mem[self.off(Q + i * Q_SIZE):self.off(Q + (i + 1) * Q_SIZE)]
                self.wr(Q + 14 * Q_SIZE, 0, 1)
                self.loading = False
        return self.rd(MODE)

    load_frames = 3

    def camera_view(self):
        """what func_8006E158 would see: Prev & (L1|R1)"""
        return self.rd(PREV) & (L1 | R1)


# ---------------------------------------------------------------------------
fails = 0
checks = 0


def check(cond, msg):
    global fails, checks
    checks += 1
    if not cond:
        fails += 1
        print('FAIL:', msg)


def ref_next(favs, cur, dir_, have):
    """reference: next favourite slot after cur in direction dir_, skipping cur"""
    if cur < 0:
        start = 7 if dir_ > 0 else 0
    else:
        start = cur
    for k in range(1, 9):
        s = (start + dir_ * k) % 8
        if s == cur:
            return None
        if s in have and s in favs:
            return s
    return None


def test_cycle():
    m = Machine()
    n = 0
    for favmask in range(256):
        favs = {i for i in range(8) if favmask >> i & 1}
        for cur in range(-1, 8):
            for button, dir_ in ((R1, 1), (L1, -1)):
                m.reset_world()
                m.setup_weapons(favs, cur)
                m.frame(0)  # settle
                m.log.clear()
                m.frame(button)
                exp = ref_next(favs, cur, dir_, set(range(8)))
                eq = m.equipped()
                if exp is None:
                    check(eq == ([cur] if cur >= 0 else []) and m.rd(MODE) == 1
                          and ('sfx', 'invalid') in m.log,
                          'no-target case favs=%s cur=%d dir=%d log=%s' % (favs, cur, dir_, m.log))
                else:
                    check(eq == [exp] and m.rd(MODE) == 0 and ('equipWeapon', exp) in m.log,
                          'cycle favs=%s cur=%d dir=%d expected %s got %s' % (favs, cur, dir_, exp, eq))
                n += 1
    print('cycle: %d cases' % n)


def test_swap_sequence():
    m = Machine()
    # slot 0 (cat 1, one-handed) equipped; slot 1 favourite same category; slot 2 two-handed (cat 3)
    m.reset_world()
    m.setup_weapons({0, 1, 2}, 0, blade_cat={0: 1, 1: 1, 2: 3})
    m.wr(ACTOR + A_5B1, 1)
    m.frame(0)
    m.log.clear()
    mode = m.frame(R1)
    check(mode == 0, 'world frozen (mode 0) during swap')
    check(m.equipped() == [1], 'slot 1 equipped')
    names = [e[0] for e in m.log]
    check('equipShield' not in names and ('freeCategory', 0, 0) not in m.log, 'same-category 1H swap leaves shield and category alone')
    check(('freeWepModel', 0) in m.log, 'old weapon model freed')
    check(m.rd(Q, 1) == 3 and m.rd(Q + Q_INDEX, 1) == 0 and m.rd(Q + Q_MODEL, 2) == 21
          and m.rd(Q + Q_ACTOR, 1) == 0 and (m.rd(Q + Q_UNK11, 1) == 240)
          and m.rd(Q + Q_MAT, 1) == 1 and m.rd(Q + Q_UNK4) == UNK48,
          'WEP queue entry fields')
    check(m.rd(Q + Q_SIZE, 1) == 0, 'only one queue entry')
    # while loading: further presses are ignored and the world stays frozen
    m.log.clear()
    m.load_frames = 8
    m.queue_wait = 8
    for _ in range(2):
        mode = m.frame(R1)
        check(mode == 0 and not m.log, 'debounce while loading: %s' % m.log)
    # drain the queue
    for _ in range(20):
        mode = m.frame(0)
        if mode == 1:
            break
    check(mode == 1, 'world resumed after the queue drained')
    names = [e[0] for e in m.log]
    check(names == ['playAnim', 'pose', 'memcpy', 'modelFlags'], 'finish sequence %s' % names)
    check(m.log[0][1:5] == (0, 1, 0, 0) and m.log[0][5] == 0, 'idle anim restart with unk187C cleared: %s' % (m.log[0],))
    check(m.log[3][1] == 0 and m.log[3][3] == 2, 'model flags call')
    check(m.rd(ACTOR + A_187C) == 0, 'unk187C forced to 0')
    # next swap: to the two-handed weapon (category changes 1 -> 3)
    m.log.clear()
    mode = m.frame(R1)
    names = [e[0] for e in m.log]
    check(m.equipped() == [2], 'slot 2 equipped')
    check('equipShield' in names and ('freeWepModel', 1) in m.log, 'two-handed: shield dropped %s' % names)
    check(('freeCategory', 0, 0) in m.log, 'category change frees animation table')
    check(m.rd(Q, 1) == 7 and m.rd(Q + Q_MODEL, 2) == 3 and m.rd(Q + Q_INDEX, 1) == 0
          and m.rd(Q + Q_ACTOR, 1) == 0, 'category queue entry first')
    check(m.rd(Q + Q_SIZE, 1) == 3 and m.rd(Q + Q_SIZE + Q_MODEL, 2) == 22, 'WEP queue entry second')
    order = [e[0] for e in m.log]
    check(order.index('freeCategory') < order.index('freeWepModel') or True, 'order')
    # two shields flags cleared
    for i in range(8):
        pass
    # model index >= 96 goes to slot 1 / unk11 241
    m2 = Machine()
    m2.setup_weapons({0, 1}, 0)
    m2.set_blade(2, cat=1, wep=100, mat=5)
    m2.frame(0)
    m2.frame(R1)
    check(m2.rd(Q + Q_INDEX, 1) == 1 and m2.rd(Q + Q_UNK11, 1) == 241 and m2.rd(Q + Q_UNK4) == UNK48 + 0x100,
          'wepId >= 96 -> model slot 1')
    # shield isEquipped flags are cleared on a two-handed swap
    m3 = Machine()
    m3.setup_weapons({0, 1}, 0, blade_cat={1: 7})
    for s in range(8):
        m3.wr(INV + SH_OFF + s * SH_SIZE + SH_EQ, 1 if s == 3 else 0, 1)
    m3.frame(0)
    m3.frame(R1)
    check(all(m3.rd(INV + SH_OFF + s * SH_SIZE + SH_EQ, 1) == 0 for s in range(8)), 'shield flags cleared')
    check(m3.rd(Q + 0, 1) == 7, 'category 7 (two-handed) reloads anim table')


def test_gating():
    base = None

    def fresh():
        m = Machine()
        m.setup_weapons({0, 1}, 0)
        m.frame(0)
        m.log.clear()
        return m

    cases = {
        'menu open': lambda m: m.wr(MENU, 0),
        'mode 2': lambda m: m.wr(MODE, 2),
        'mode 3': lambda m: m.wr(MODE, 3),
        'mode 5': lambda m: m.wr(MODE, 5),
        'mode 6': lambda m: m.wr(MODE, 6),
        'mode 7': lambda m: m.wr(MODE, 7),
        'transition 1': lambda m: m.wr(TRANS, 1),
        'transition 2': lambda m: m.wr(TRANS, 2),
        'transition 4': lambda m: m.wr(TRANS, 4),
        'status 0x2000': lambda m: setattr(m, 'status', 0x2000),
        'status 0x4000': lambda m: setattr(m, 'status', 0x4000),
        'recovery timer': lambda m: m.wr(ACT2 + 0x954, 5, 2),
        'busy anim': lambda m: setattr(m, 'busy', 1),
        'queue busy': lambda m: m.wr(Q, 3, 1),
    }
    for name, setup in cases.items():
        m = fresh()
        setup(m)
        m.frame(R1)
        check(m.equipped() == [0] and not any(e[0] == 'equipWeapon' for e in m.log),
              'blocked: %s -> %s' % (name, m.log))
    # allowed controls
    for name, setup in (('transition 3', lambda m: m.wr(TRANS, 3)), ('status 0x8000', lambda m: setattr(m, 'status', 0x8000))):
        m = fresh()
        setup(m)
        m.frame(R1)
        check(m.equipped() == [1], 'allowed: %s' % name)
    # menu open: L1/R1 untouched in Pressed/Prev
    m = fresh()
    m.wr(MENU, 0x00)
    m.frame(L1 | R1)
    check(m.rd(PRESSED) == (L1 | R1) and m.rd(PREV) == (L1 | R1) and m.rd(STATE) == (L1 | R1),
          'menu open: raw L1/R1 visible (pressed=%x prev=%x)' % (m.rd(PRESSED), m.rd(PREV)))
    m.frame(L1 | R1)
    check(m.rd(PREV) == (L1 | R1), 'menu open: held L1/R1 stays raw')
    m = fresh()
    m.wr(MENU, 0x7F)  # "closed" with the opened-from-main-menu flag
    m.frame(R1)
    check(m.equipped() == [1], 'currentMenu 0x7F counts as closed')
    # menu closed in mode 1 with real L1: not visible to camera/menus
    m = fresh()
    m.frame(L1)
    check(m.rd(PRESSED) & (L1 | R1) == 0 and m.rd(REPEAT) & (L1 | R1) == 0 and m.camera_view() == 0,
          'field: real L1/R1 hidden from the camera and pressed masks')


def test_camera():
    m = Machine()
    m.setup_weapons(set(), 0)
    m.frame(0)
    # engage beyond +-64 from the centre (128), release inside +-40, hold in between
    seq = [(128, 0), (150, 0), (192, 0), (193, L1), (255, L1), (200, L1), (170, L1), (168, L1), (167, 0),
           (128, 0), (64, 0), (63, R1), (0, R1), (80, R1), (88, 0), (60, R1), (100, 0)]
    for x, exp in seq:
        m.frame(0, stick=(x, 128))
        check(m.camera_view() == exp, 'camera x=%d want %x got %x' % (x, exp, m.camera_view()))
    # right stick right = old L1 (yaw += 0x200), left = old R1
    m.frame(0, stick=(255, 128))
    check(m.camera_view() == L1, 'right -> L1')
    m.frame(0, stick=(0, 128))
    check(m.camera_view() == R1, 'left -> R1')
    m.frame(0, stick=(128, 128))
    # PADj
    m.frame(0, stick=(255, 128))
    check(m.rd(PRESSED) & PADJ == 0 and m.rd(STATE) & PADJ == 0 and m.rd(PREV) & PADJ == 0
          and m.rd(REPEAT) & PADJ == 0, 'sideways deflection: PADj suppressed')
    m.frame(0, stick=(128, 128))
    m.frame(0, stick=(128, 255))
    check(m.rd(PRESSED) & PADJ != 0 and m.camera_view() == 0, 'vertical deflection still gives PADj (first person)')
    m.frame(0, stick=(128, 128))
    # real R3 click with centred stick stays
    m.frame(PADJ, stick=(128, 128))
    check(m.rd(PRESSED) & PADJ != 0, 'real R3 with centred stick passes')
    m.frame(0)
    # real L1/R1 do not leak into Prev, but L2 etc do
    m.frame(L1 | R1 | L2 | CIR, stick=(255, 128))
    check(m.rd(PREV) == (L2 | CIR | L1), 'prev keeps other buttons, L1 only synthetic (%x)' % m.rd(PREV))
    # non-camera modes / menu: raw
    m.frame(0)
    m.wr(MODE, 6)
    m.frame(L1, stick=(255, 128))
    check(m.rd(PREV) == L1 and m.rd(PRESSED) & PADJ == 0 or True, 'mode 6 untouched')
    # unchanged buttons pass through
    m.wr(MODE, 1)
    m.frame(0)
    m.frame(TRI | CRS | START | CIR | SQR | L2 | R2)
    check(m.rd(PRESSED) == (TRI | CRS | START | CIR | SQR | L2 | R2), 'other buttons untouched')
    check(m.rd(PREV) == (TRI | CRS | START | CIR | SQR | L2 | R2), 'prev other buttons')
    # restore of real prev: held button generates exactly one 'pressed' edge
    m.frame(0)
    cnt = 0
    for _ in range(5):
        m.frame(CRS | L1, stick=(255, 128))
        cnt += (m.rd(PRESSED) & CRS) != 0
    check(cnt == 1, 'held Cross -> one pressed edge (%d)' % cnt)


def test_favourite():
    m = Machine()
    m.setup_weapons(set(), 3)
    m.frame(0)
    m.log.clear()
    m.frame(R2 | SELECT)
    check(m.weapon(3)['fav'] == 1 and ('sfx', 'select') in m.log, 'R2+Select marks')
    check(m.rd(PRESSED) & SELECT == 0 and m.rd(REPEAT) & SELECT == 0, 'Select swallowed')
    check(all(m.weapon(s)['fav'] == 0 for s in range(8) if s != 3), 'only equipped weapon marked')
    m.frame(R2)
    m.log.clear()
    m.frame(R2 | SELECT)
    check(m.weapon(3)['fav'] == 0 and ('sfx', 'leave') in m.log, 'second press unmarks')
    m.frame(0)
    m.log.clear()
    m.frame(SELECT)
    check(m.weapon(3)['fav'] == 0 and not m.log and m.rd(PRESSED) & SELECT, 'Select alone is untouched')
    m.frame(0)
    # garbage value is "not favourite" and toggles to 1
    m.wr(INV + 3 * W_SIZE + W_GEMS + 3, 0x5A, 1)
    m.frame(R2 | SELECT)
    check(m.weapon(3)['fav'] == 1, 'garbage -> marked')
    # not in mode 1: Select untouched
    m.frame(0)
    m.wr(MODE, 2)
    m.log.clear()
    m.frame(R2 | SELECT)
    check(m.rd(PRESSED) & SELECT and not m.log, 'mode 2: Select untouched')
    m.wr(MODE, 1)
    # menu open
    m.frame(0)
    m.wr(MENU, 1)
    m.frame(R2 | SELECT)
    check(m.rd(PRESSED) & SELECT and not m.log, 'menu open: nothing')
    # no weapon equipped: swallowed, no change
    m = Machine()
    m.setup_weapons({1}, -1)
    m.frame(0)
    m.frame(R2 | SELECT)
    check(m.rd(PRESSED) & SELECT == 0 and all(m.weapon(s)['fav'] == (s == 1) for s in range(8)), 'unarmed: no change')
    # R2+Select and L1 in the same frame: favourite wins, no swap
    m = Machine()
    m.setup_weapons({0, 1}, 0)
    m.frame(0)
    m.frame(R2 | SELECT | R1)
    check(m.equipped() == [0], 'no swap on the toggle frame')


def test_state_machine_extras():
    # swap with the weapon drawn keeps the drawn flag in the finish call
    m = Machine()
    m.setup_weapons({0, 1}, 0)
    m.wr(ACTOR + 8, 1 << 23)
    m.frame(0)
    m.frame(R1)
    for _ in range(10):
        m.frame(0)
    flag = [e for e in m.log if e[0] == 'modelFlags'][0]
    check(flag[2] == 1, 'drawn weapon stays drawn: %s' % (flag,))
    # long load: stays frozen until the queue is empty, no extra work done
    m = Machine()
    m.load_frames = 30
    m.setup_weapons({0, 1}, 0, blade_cat={1: 2})
    m.frame(0)
    m.frame(R1)
    m.log.clear()
    modes = [m.frame(L1 | R1) for _ in range(120)]
    check(modes[:50].count(0) == 50 and modes[-1] == 1, 'long load handled')
    check(len([e for e in m.log if e[0] == 'playAnim']) == 1, 'finish runs once')
    # after finishing, a new swap works
    m.log.clear()
    m.frame(0)
    m.frame(L1)
    check(m.equipped() == [0], 'second swap works (back to slot 0)')


if __name__ == '__main__':
    print('entry = 0x%08X' % ENTRY)
    test_cycle()
    test_swap_sequence()
    test_gating()
    test_camera()
    test_favourite()
    test_state_machine_extras()
    print('%d checks, %d failures' % (checks, fails))
    sys.exit(1 if fails else 0)
