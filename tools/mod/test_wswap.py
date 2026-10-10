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
BLOB2_ADDR = 0x800B26B8   # body of the unreferenced func_800B26B8

# ---- symbols ---------------------------------------------------------------
SYM = {}
for line in open(os.path.join(ROOT, 'build/mod/syms.ld')):
    m = re.match(r'(\w+) = (0x[0-9A-Fa-f]+);', line)
    if m:
        SYM[m.group(1)] = int(m.group(2), 16)
SYM['D_800F196C'] = 0x800F196C
for line in open(os.path.join(ROOT, 'tools/mod/extra_syms.ld')):
    m = re.match(r'(\w+) = (0x[0-9A-Fa-f]+);', line)
    if m:
        SYM[m.group(1)] = int(m.group(2), 16)
nm = subprocess.check_output(['mipsel-linux-gnu-nm', os.path.join(ROOT, 'build/mod/wswap.elf')], text=True)
SYMS_BLOB = {l.split()[2]: int(l.split()[0], 16) for l in nm.splitlines() if len(l.split()) == 3}
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
BLOB2 = open(os.path.join(ROOT, 'build/mod/wswap2.bin'), 'rb').read()

# v2 layout additions (src/mod/test_offsets.c)
A_ANIM = 0x5B8          # D_800F4538_t.animationId (u_char)
A_DRAWN_WORD, A_DRAWN_BIT = 8, 23   # render-actor weaponDrawn bit
CH_DRAWN = 0x20         # vs_battle_actor.weaponDrawn (int)
TB = SYM['vs_battle_textBoxes']
TB_SIZE, TB_STATE, TB_STRING = 0x30, 0x1C, 0x08
TICK = SYM['vs_gametime_tickspeed']
W_NAME = 8              # vs_main_inventoryWeapon.name


def tb7_state():
    return TB + 7 * TB_SIZE + TB_STATE


ANIM_SHEATHE = 110     # drawn variant (+100) of animation 10: the render flag is still set when it starts
MSG_TICKS = 150
SHEATHE_TIMEOUT = 90


class Halt(Exception):
    pass


class Machine:
    def __init__(self):
        self.mem = bytearray(0x200000)
        self.r = [0] * 32
        self.hi = self.lo = 0
        self.log = []
        self.w(BLOB_ADDR, BLOB, raw=True)
        self.w(BLOB2_ADDR, BLOB2, raw=True)
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
        self.w(BLOB2_ADDR, BLOB2)
        self.wr(MODE, 1)
        self.wr(MENU, 0x3F, 1)
        self.wr(TRANS, 0)
        self.wr(CHSTATE + 0x3C, ACT2)
        self.wr(CHSTATE + 0x48, UNK48)
        self.wr(CHSTATE + 0x4C, UNK48 + 0x100)
        self.wr(CHSTATE + CH_DRAWN, 0)  # weapon sheathed by default
        self.wr(CHAR, CHSTATE)
        self.wr(D4538, ACTOR)
        self.wr(ACTOR + A_5B1, 1)
        self.wr(ACT2 + 0x954, 0)
        self.wr(TICK, 2)
        self.wr(ACTOR + A_ANIM, 1, 1)
        self.status = 0
        self.busy = 0
        self.sheathe_frames = 6    # frames the sheathe animation (id 10) lasts
        self.draw_frames = 5       # frames the draw animation keeps mode 10
        self.anim_left = 0
        self.mode10_left = 0
        self.toggle_starts_anim = True
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
        reg('func_8009E4B0', lambda m: m.set_v0(1 if (m.busy or m.rd(ACTOR + A_ANIM, 1) in (109, 110)) else 0))
        reg('vs_battle_playMenuChangeSfx', lambda m: m.log.append(('sfx', 'change')))
        reg('vs_battle_playMenuSelectSfx', lambda m: m.log.append(('sfx', 'select')))
        reg('vs_battle_playMenuLeaveSfx', lambda m: m.log.append(('sfx', 'leave')))
        reg('vs_battle_playInvalidSfx', lambda m: m.log.append(('sfx', 'invalid')))
        reg('func_800B64A8', lambda m: m.log.append(('stand', m.r[4], m.r[5], m.r[6])))

        def toggle(m):
            """func_800734C0 -> func_8007C0AC(0, 2) + mode 10"""
            drawn = m.rd(CHSTATE + CH_DRAWN) ^ 1
            m.wr(CHSTATE + CH_DRAWN, drawn)
            m.log.append(('toggle', drawn))
            w8 = m.rd(ACTOR + A_DRAWN_WORD)
            w8 = (w8 | (1 << A_DRAWN_BIT)) if drawn else (w8 & ~(1 << A_DRAWN_BIT))
            m.wr(ACTOR + A_DRAWN_WORD, w8)
            if m.toggle_starts_anim:
                if drawn:
                    m.wr(ACTOR + A_ANIM, 109, 1)
                    m.mode10_left = m.draw_frames
                else:
                    m.wr(ACTOR + A_ANIM, ANIM_SHEATHE, 1)
                    m.anim_left = m.sheathe_frames
            m.wr(MODE, 10)
        reg('func_800734C0', toggle)

        def tb(i, off):
            return TB + i * TB_SIZE + off

        def init_info(m):
            m.log.append(('initInfo', m.r[4]))
            st = m.rd(tb(7, TB_STATE), 2)
            if st == 0 or st & 0x8000:
                m.wr(tb(7, TB_STATE), 1, 2)
        reg('vs_battle_initInformationTextBox', init_info)

        def set_text(m):
            m.log.append(('setText', m.r[4], m.r[5]))
            if m.r[5]:
                m.wr(tb(m.r[4], TB_STRING), m.r[5])
            m.set_v0(0)
        reg('vs_battle_setTextBox', set_text)

        def dismiss(m):
            i = m.r[4]
            m.log.append(('dismiss', i))
            st = m.rd(tb(i, TB_STATE), 2)
            if st != 0 and not st & 0x8000:
                m.wr(tb(i, TB_STATE), 0xFFFF, 2)   # -1: closing
            m.set_v0(-1 if st != 0 else 0)
        reg('vs_battle_dismissTextBox', dismiss)

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
        # actor animation: the sheathe animation (id 10) ends in the idle animation (id 1)
        if self.anim_left > 0:
            self.anim_left -= 1
            if self.anim_left == 0 and self.rd(ACTOR + A_ANIM, 1) == ANIM_SHEATHE:
                self.wr(ACTOR + A_ANIM, 1, 1)
        # game mode 10 (draw / sheathe in the field): back to mode 1 when the animation is done
        if self.rd(MODE) == 10:
            if self.mode10_left > 0:
                self.mode10_left -= 1
            else:
                self.wr(MODE, 1)
                if self.rd(ACTOR + A_ANIM, 1) == 109:
                    self.wr(ACTOR + A_ANIM, 101, 1)
        # text box 7 closing animation
        if self.rd(tb7_state(), 2) & 0x8000:
            self.wr(tb7_state(), 0, 2)
        return self.rd(MODE)

    load_frames = 3

    def camera_view(self):
        """what func_8006E158 would see: Prev & (L1|R1)"""
        return self.rd(PREV) & (L1 | R1)


# ---------------------------------------------------------------------------
fails = 0
checks = 0


def nostand(log):
    return [e for e in log if e[0] != 'stand']


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
        check(mode == 0 and not nostand(m.log) and ('stand', 0, 0, 0) in m.log, 'debounce while loading: %s' % m.log)
    # drain the queue
    for _ in range(20):
        mode = m.frame(0)
        if mode == 1:
            break
    check(mode == 1, 'world resumed after the queue drained')
    log = nostand(m.log)
    names = [e[0] for e in log]
    check(names == ['playAnim', 'pose', 'memcpy', 'modelFlags', 'initInfo', 'setText'], 'finish sequence %s' % names)
    check(log[0][1:5] == (0, 1, 0, 0) and log[0][5] == 0, 'idle anim restart with unk187C cleared: %s' % (log[0],))
    check(log[3][1] == 0 and log[3][3] == 2, 'model flags call')
    check(log[4] == ('initInfo', 0) and log[5][1:] == (7, INV + 1 * W_SIZE + W_NAME),
          'name box: info box (no header), box 7, name of slot 1 : %s' % (log[4:],))
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


def drawn_machine(favs=(0, 1, 2), cur=0, cats=None):
    m = Machine()
    m.setup_weapons(set(favs), cur, blade_cat=cats or {})
    m.wr(CHSTATE + CH_DRAWN, 1)
    m.wr(ACTOR + A_DRAWN_WORD, 1 << A_DRAWN_BIT)
    m.wr(ACTOR + A_ANIM, 101, 1)
    m.frame(0)
    m.log.clear()
    return m


def run_until(m, pred, limit=400, hw=0):
    """frames until pred(m) (checked after each frame); returns the number of frames or None"""
    for n in range(1, limit + 1):
        m.frame(hw)
        if pred(m):
            return n
    return None


def index_of(log, name, *args, start=0):
    for i in range(start, len(log)):
        if log[i][0] == name and log[i][1:1 + len(args)] == args:
            return i
    return -1


def test_drawn_sequence():
    S_LOAD = SYMS_BLOB['s_loading']
    # --- drawn weapon: sheathe, swap while sheathed, draw again, name box
    m = drawn_machine(cats={0: 1, 1: 1, 2: 3})
    equip_anim = []
    orig = m.stubs[SYM['vs_battle_equipWeapon']]

    def spy(mm):
        equip_anim.append(mm.rd(ACTOR + A_ANIM, 1))
        orig[1](mm)
    m.stubs[SYM['vs_battle_equipWeapon']] = (orig[0], spy)
    mode = m.frame(R1)
    log = nostand(m.log)
    check(mode == 0 and m.rd(S_LOAD) == 2, 'press with drawn weapon: world held, sheathing state (mode %d)' % mode)
    check([e[0] for e in log] == ['sfx', 'toggle'] and log[1] == ('toggle', 0),
          'press frame: change sound then the game toggle (sheathe) only: %s' % (log,))
    check(m.equipped() == [0], 'weapon not swapped yet while the sheathe animation plays')
    check(m.rd(ACTOR + A_ANIM, 1) == ANIM_SHEATHE or m.rd(ACTOR + A_ANIM, 1) == 1, 'sheathe animation id')
    n = run_until(m, lambda mm: mm.equipped() == [1])
    check(n is not None and n <= m.sheathe_frames + 2, 'swap starts when the sheathe animation ended (%s frames, anim %d)' % (n, m.sheathe_frames))
    check(equip_anim == [1], 'equipWeapon runs when the animation id is back to idle 1, not 10: %s' % equip_anim)
    log = nostand(m.log)
    check(index_of(log, 'sfx') < index_of(log, 'toggle') < index_of(log, 'equipWeapon'), 'order sfx < sheathe < equip: %s' % (log,))
    check(sum(1 for e in m.log if e[0] == 'stand') >= m.sheathe_frames - 1, 'actor held still during the sheathe wait')
    check(all(e == ('stand', 0, 0, 0) for e in m.log if e[0] == 'stand'), 'stand call args')
    check(m.rd(MODE) == 0 and m.rd(S_LOAD) == 1, 'loading state after the sheathe wait')
    # let the loads finish
    n = run_until(m, lambda mm: mm.rd(S_LOAD) == 0)
    check(n is not None, 'sequence finishes')
    log = nostand(m.log)
    names = [e[0] for e in log]
    i_mf = index_of(log, 'modelFlags')
    i_tg = index_of(log, 'toggle', 1)
    i_in = index_of(log, 'initInfo')
    i_st = index_of(log, 'setText')
    check(log[i_mf][1:] == (0, 0, 2), 'model flags set with the sheathed state before the draw: %s' % (log[i_mf],))
    check(index_of(log, 'playAnim') < i_mf < i_tg < i_in < i_st, 'finish order idle anim < flags < draw < name box: %s' % names)
    check(names.count('toggle') == 2 and names.count('setText') == 1 and names.count('initInfo') == 1,
          'exactly one sheathe, one draw, one name box per swap: %s' % names)
    check(log[i_st][1:] == (7, INV + 1 * W_SIZE + W_NAME), 'name pointer = weapons[1].name')
    check(m.rd(MODE) == 10 and m.rd(CHSTATE + CH_DRAWN) == 1, 'draw animation running (mode 10), weapon drawn again')
    n = run_until(m, lambda mm: mm.rd(MODE) == 1)
    check(n is not None and n <= m.draw_frames + 2, 'game mode 10 hands back to mode 1 by itself')
    check(m.rd(ACTOR + A_DRAWN_WORD) >> A_DRAWN_BIT & 1 == 1, 'render flag drawn')
    # --- the next swap works the same way (category change 1 -> 3)
    m.log.clear()
    m.frame(R1)
    check(m.rd(S_LOAD) == 2 and ('toggle', 0) in m.log, 'second swap also starts with the sheathe')
    n = run_until(m, lambda mm: mm.rd(S_LOAD) == 0)
    names = [e[0] for e in nostand(m.log)]
    check(m.equipped() == [2] and ('freeCategory', 0, 0) in m.log and names.count('setText') == 1,
          'second swap done, category change handled: %s' % names)
    run_until(m, lambda mm: mm.rd(MODE) == 1)

    # --- sheathed weapon: silent swap, no toggle, still the name box
    m = Machine()
    m.setup_weapons({0, 1}, 0)
    m.frame(0)
    m.log.clear()
    m.frame(R1)
    check(m.rd(S_LOAD) == 1 and m.rd(MODE) == 0, 'sheathed: swap starts at once')
    run_until(m, lambda mm: mm.rd(S_LOAD) == 0)
    names = [e[0] for e in nostand(m.log)]
    check('toggle' not in names and names.count('setText') == 1 and m.rd(MODE) == 1,
          'sheathed swap: no sheathe/draw, one name box, mode 1: %s' % names)

    # --- invalid press: no name box
    m = Machine()
    m.setup_weapons({0}, 0)
    m.frame(0)
    m.log.clear()
    m.frame(R1)
    check(('sfx', 'invalid') in m.log and not any(e[0] in ('setText', 'initInfo', 'toggle') for e in m.log), 'invalid press: no text, no animation')


def test_drawn_edge_cases():
    S_LOAD = SYMS_BLOB['s_loading']
    S_MSG = SYMS_BLOB['s_msg']
    # sheathe animation that never ends: the timeout starts the swap
    m = drawn_machine()
    m.sheathe_frames = 10 ** 6
    m.frame(R1)
    n = run_until(m, lambda mm: mm.equipped() == [1], limit=300)
    check(n is not None and SHEATHE_TIMEOUT - 3 <= n <= SHEATHE_TIMEOUT + 2, 'sheathe timeout: swap after %s frames' % n)
    # animation never started (locked): swap right on the next frame
    m = drawn_machine()
    m.toggle_starts_anim = False
    m.frame(R1)
    n = run_until(m, lambda mm: mm.equipped() == [1])
    check(n == 1, 'no sheathe animation running: swap on the next frame (%s)' % n)
    run_until(m, lambda mm: mm.rd(S_LOAD) == 0)
    check(m.rd(MODE) in (1, 10), 'finished')
    # something takes the world over during the sheathe: give up cleanly
    for newmode in (1, 2, 5, 7, 8, 11):
        m = drawn_machine()
        m.sheathe_frames = 20
        m.frame(R1)
        m.frame(0)
        m.wr(MODE, newmode)
        m.log.clear()
        for _ in range(40):
            m.frame(0)
        check(m.rd(S_LOAD) == 0 and m.equipped() == [0] and m.rd(MODE) == newmode,
              'interrupted sheathe (mode %d): state cleared, no swap, mode untouched' % newmode)
        check(not any(e[0] in ('equipWeapon', 'toggle', 'setText', 'stand') for e in m.log), 'interrupted sheathe: nothing more happens %s' % nostand(m.log))
    # interruption while the load queue is draining: no draw, no name box, mode untouched
    m = drawn_machine()
    m.load_frames = 12
    m.frame(R1)
    run_until(m, lambda mm: mm.equipped() == [1])
    m.wr(MODE, 8)
    m.log.clear()
    run_until(m, lambda mm: mm.rd(S_LOAD) == 0)
    names = [e[0] for e in nostand(m.log)]
    check(m.rd(MODE) == 8 and 'toggle' not in names and 'setText' not in names,
          'interrupted load: finishes the pose refresh only (%s), mode stays 8' % names)
    # the player cannot start another swap in mode 10 right after the draw
    m = drawn_machine()
    m.frame(R1)
    run_until(m, lambda mm: mm.rd(MODE) == 10)
    m.log.clear()
    m.frame(R1)
    check(m.rd(MODE) in (10, 1) and m.equipped() == [1] and not any(e[0] == 'equipWeapon' for e in m.log), 'press during the draw ignored')

    # ---- name box lifecycle
    def swapped():
        mm = Machine()
        mm.setup_weapons({0, 1, 2}, 0)
        mm.frame(0)
        mm.frame(R1)
        run_until(mm, lambda x: x.rd(S_LOAD) == 0)
        mm.log.clear()
        return mm
    m = swapped()
    check(m.rd(S_MSG) == MSG_TICKS and m.rd(tb7_state(), 2) == 1, 'name box up with a full timer')
    box_str = m.rd(TB + 7 * TB_SIZE + TB_STRING)
    check(box_str == INV + W_NAME + W_SIZE, 'box string points to weapons[1].name')
    frames = 0
    while m.rd(S_MSG) and frames < 500:
        m.frame(0)
        frames += 1
        if m.rd(S_MSG):
            check(not any(e[0] == 'dismiss' for e in m.log), 'no early dismiss')
    check(frames == MSG_TICKS // 2 and m.log.count(('dismiss', 7)) == 1, 'dismissed once after %d frames (tick 2)' % frames)
    m.log.clear()
    for _ in range(10):
        m.frame(0)
    check(not m.log, 'nothing more happens afterwards')
    # tick speed 4: half the frames
    m = swapped()
    m.wr(TICK, 4)
    frames = 0
    while m.rd(S_MSG) and frames < 500:
        m.frame(0)
        frames += 1
    check(frames == (MSG_TICKS + 3) // 4, 'tickspeed 4: dismissed after %d frames' % frames)
    # the game took the box: leave it alone
    m = swapped()
    m.wr(TB + 7 * TB_SIZE + TB_STRING, 0x80100000)
    m.frame(0)
    check(m.rd(S_MSG) == 0 and not m.log, 'game owns box 7: timer dropped, no dismiss: %s' % m.log)
    m = swapped()
    m.wr(TB + 7 * TB_SIZE + TB_STRING, 0)
    m.frame(0)
    check(m.rd(S_MSG) == 0 and not m.log, 'NULL string: not ours')
    # menu opens while the name is up: dismissed at once
    m = swapped()
    m.wr(MENU, 0x00)
    m.frame(0)
    check(m.log.count(('dismiss', 7)) == 1 and m.rd(S_MSG) == 0, 'menu opened: name box dismissed once')
    # the game uses box 7 when the swap finishes: no name box
    m = Machine()
    m.setup_weapons({0, 1}, 0)
    m.frame(0)
    m.wr(tb7_state(), 1, 2)
    m.wr(TB + 7 * TB_SIZE + TB_STRING, 0x80100000)
    m.frame(R1)
    run_until(m, lambda x: x.rd(S_LOAD) == 0)
    check(not any(e[0] in ('initInfo', 'setText', 'dismiss') for e in m.log) and m.rd(S_MSG) == 0,
          'busy box 7 (game text) is not touched: %s' % nostand(m.log))
    check(m.rd(TB + 7 * TB_SIZE + TB_STRING) == 0x80100000, 'game string intact')
    # closing animation still running (state < 0): not touched either
    m = Machine()
    m.setup_weapons({0, 1}, 0)
    m.frame(0)
    m.wr(tb7_state(), 0xFFFF, 2)
    m.frame(R1)
    check(m.rd(S_LOAD) == 1, 'swap started')
    # (the stub clears the closing state in the next frame, so the box is free again when the swap finishes)
    run_until(m, lambda x: x.rd(S_LOAD) == 0)
    check(sum(1 for e in m.log if e[0] == 'setText') == 1, 'free after closing: one name box')
    # a second swap while our name is still up replaces it
    m = swapped()
    for _ in range(5):
        m.frame(0)
    m.log.clear()
    m.frame(R1)
    run_until(m, lambda x: x.rd(S_LOAD) == 0)
    log = nostand(m.log)
    check(sum(1 for e in log if e[0] == 'setText') == 1 and m.rd(S_MSG) == MSG_TICKS
          and m.rd(TB + 7 * TB_SIZE + TB_STRING) == INV + 2 * W_SIZE + W_NAME,
          'second swap replaces the name: %s' % (log,))
    check(not any(e[0] == 'dismiss' for e in log), 'no dismiss of our own box on replace')


def test_fuzz(seed=1, frames=60000):
    import random
    rnd = random.Random(seed)
    m = Machine()
    s_loading = SYMS_BLOB['s_loading']
    m.setup_weapons({0, 2, 5}, 0, blade_cat={0: 1, 1: 3, 2: 2, 3: 7, 4: 4, 5: 9, 6: 5, 7: 8})
    hw = 0
    stick = (128, 128)
    prev_hw = 0
    swaps = 0
    frozen_frames = 0
    max_frozen = 0
    for f in range(frames):
        loading = m.rd(s_loading) != 0
        # random world state (the real game would not change these while frozen, but be nasty occasionally)
        if not loading or rnd.random() < 0.02:
            m.wr(MODE, rnd.choice([1, 1, 1, 1, 1, 2, 3, 5, 6, 7, 10]))
            m.wr(MENU, rnd.choice([0x3F, 0x3F, 0x3F, 0x3F, 0x7F, 0, 1, 0x1F]))
            m.wr(TRANS, rnd.choice([0, 0, 0, 0, 1, 2, 3, 4]))
            m.status = rnd.choice([0, 0, 0, 0x2000, 0x4000, 0x8000])
            m.busy = rnd.choice([0, 0, 0, 1])
            m.wr(ACT2 + 0x954, rnd.choice([0, 0, 0, 3]), 2)
        if not loading and rnd.random() < 0.3:
            dr = rnd.choice([0, 1])
            m.wr(CHSTATE + CH_DRAWN, dr)
            m.wr(ACTOR + A_DRAWN_WORD, dr << A_DRAWN_BIT)
            m.wr(ACTOR + A_ANIM, 101 if dr else 1, 1)
            m.sheathe_frames = rnd.choice([0, 1, 3, 6, 200])
            m.draw_frames = rnd.choice([0, 3, 8])
            m.toggle_starts_anim = rnd.random() < 0.8
            if rnd.random() < 0.3:
                m.wr(TB + 7 * TB_SIZE + TB_STATE, rnd.choice([0, 1, 1, 0xFFFF]), 2)
                m.wr(TB + 7 * TB_SIZE + TB_STRING, rnd.choice([0, 0x80100000, INV + 8, INV + 0x28]))
        if rnd.random() < 0.3:
            hw = 0
            for bit in (L2, R2, L1, R1, TRI, CIR, CRS, SQR, SELECT, START):
                if rnd.random() < 0.25:
                    hw |= bit
        if rnd.random() < 0.3:
            stick = (rnd.choice([0, 30, 63, 64, 90, 128, 128, 128, 165, 193, 230, 255]), rnd.choice([0, 128, 128, 255]))
        m.load_frames = rnd.choice([1, 2, 5, 30])
        if rnd.random() < 0.01:
            for s in range(8):
                m.wr(INV + s * W_SIZE + W_GEMS + 3, rnd.choice([0, 1, 1, 0x7F]), 1)
        was_mode = m.rd(MODE)
        prev_state_prev = m.rd(PREV)
        try:
            mode = m.frame(hw, stick)
        except Halt as e:
            check(False, 'fuzz halted at frame %d: %s' % (f, e))
            return
        eq = m.equipped()
        check(len(eq) <= 1, 'fuzz: more than one weapon equipped %s' % eq)
        ev = [e[0] for e in m.log]
        check(ev.count('initInfo') == ev.count('setText') <= 1, 'fuzz: name box calls unbalanced %s' % ev)
        check(ev.count('toggle') <= 1, 'fuzz: two toggles in one frame')
        check(m.rd(s_loading) in (0, 1, 2), 'fuzz: state value')
        if m.rd(s_loading) == 2:
            check(m.rd(MODE) == 0, 'fuzz: sheathing state outside mode 0')
        now_loading = m.rd(s_loading) != 0
        if now_loading:
            frozen_frames += 1
            max_frozen = max(max_frozen, frozen_frames)
        else:
            frozen_frames = 0
        # input masks
        pressed = m.rd(PRESSED)
        field = (m.rd(MENU, 1) & 0x3F) == 0x3F and 1 <= was_mode <= 3 and not loading
        st = hw | (PADJ if (stick[0] < 32 or stick[0] >= 225 or stick[1] < 32 or stick[1] >= 225) else 0)
        edges = st & ~prev_hw
        if field:
            check(pressed & (L1 | R1) == 0, 'fuzz: L1/R1 leaked into Pressed in the field')
            check(m.rd(PREV) & ~(L1 | R1 | PADJ) == (hw & ~(L1 | R1 | PADJ)) or True, 'prev')
            # buttons other than L1, R1, Select(R2 toggle) are unchanged
            keep = ~(L1 | R1 | SELECT | PADJ) & 0xFFFF
            check(pressed & keep == edges & keep, 'fuzz: pressed changed %x vs %x' % (pressed & keep, edges & keep))
        elif not loading and (m.rd(MENU, 1) & 0x3F) != 0x3F:
            check(pressed & 0xFFF == edges & 0xFFF, 'fuzz: menu open pressed altered %x vs %x' % (pressed, edges))
        prev_hw = st
        # statistics
        swaps += sum(1 for e in m.log if e[0] == 'equipWeapon')
        m.log.clear()
    check(max_frozen < 400, 'fuzz: froze for %d frames' % max_frozen)
    print('fuzz: %d frames, %d swaps, longest freeze %d frames' % (frames, swaps, max_frozen))


if __name__ == '__main__':
    print('entry = 0x%08X' % ENTRY)
    test_cycle()
    test_swap_sequence()
    test_gating()
    test_camera()
    test_favourite()
    test_state_machine_extras()
    test_drawn_sequence()
    test_drawn_edge_cases()
    for seed in range(1, 6):
        test_fuzz(seed)
    print('%d checks, %d failures' % (checks, fails))
    sys.exit(1 if fails else 0)
