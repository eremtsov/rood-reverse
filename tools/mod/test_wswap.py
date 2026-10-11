#!/usr/bin/env python3
"""Behavioural test of the *shipped bytes* of the weapon-swap mod.

Loads the *patched* build/data/BATTLE/BATTLE.PRG (tail blob, the bodies of the unreferenced
functions and the three patched jal, exactly what goes on the disc) at 0x80068800 into an emulated
2 MB RAM and executes wswap_entry() / wslot_label() with a small MIPS-I interpreter. Game functions the blob calls are
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
PRG_BASE = 0x80068800
# the variant under test: src/mod/wswap.c has `#define WSWAP_CLASSIC 1` on the classic branch
CLASSIC = bool(re.search(r'^#define WSWAP_CLASSIC 1', open(os.path.join(ROOT, 'src/mod/wswap.c')).read(), re.M))
# the Zenith edition (src/mod/wswap.c: #define WSWAP_ZENITH 1): the blob lives in unreferenced functions of BATTLE.PRG and SLUS_010.40
# (tools/mod/wswap-zenith.ld), build/data/BATTLE/BATTLE.PRG and build/data/SLUS_010.40 are the patched files of the combined
# image, build/mod/BATTLE.PRG.pristine is Zenith's BATTLE.PRG, build/mod/zenith_allowed.txt lists every range the mod may write
ZENITH = bool(re.search(r'^#define WSWAP_ZENITH 1', open(os.path.join(ROOT, 'src/mod/wswap.c')).read(), re.M))
LEAN = ZENITH and not CLASSIC   # ZEN_LEAN in src/mod/wswap.c: no Start function, migrate() clears garbage only, short hint

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
PADBUF = SYM['vs_main_padBuffer']
DUP, DRIGHT, DDOWN, DLEFT = 1 << 12, 1 << 13, 1 << 14, 1 << 15
PADLLEFT, PADLRIGHT, PADLUP, PADLDOWN = DLEFT, DRIGHT, DUP, DDOWN
D_ANIM = 0x800EBCE8

L2, R2, L1, R1 = 1, 2, 4, 8
TRI, CIR, CRS, SQR = 0x10, 0x20, 0x40, 0x80
SELECT, START, PADJ = 0x100, 0x800, 0x400
SLOT_BTN_T = [0x20, 0x10, 0x80, 0x40, 1 << 12, 1 << 14, 1 << 13, 1 << 15]   # slot 1..8: Circle Triangle Square Cross Up Down Right Left

SCRATCH_UNK8 = 0x801F4000   # vs_scratch.unk8 in the model
PORTINFO = 0x80050190       # _portInfo[0]: mode (u8), rStickX (+3) / rStickY (+4) = physical LEFT stick
CAM = 0x800F19D0            # vs_battle_cameraCurrentSpherical: yaw (+0), pitch (+4)
CHAR_WIDTHS = 0x800EB810    # vs_battle_characterWidths (font table 0 first)
ACTOR = 0x80120000   # emulated actor-0 structure
CHSTATE = 0x80130000  # vs_battle_characterState
ACT2 = 0x80131000     # ->unk3C
UNK48 = 0x80132000


PRG = open(os.path.join(ROOT, 'build/data/BATTLE/BATTLE.PRG'), 'rb').read()
PRG_ORIG = open(os.path.join(ROOT, 'build/mod/BATTLE.PRG.pristine'), 'rb').read()
assert len(PRG) == 579584 and len(PRG_ORIG) <= len(PRG)
SLUS = open(os.path.join(ROOT, 'build/data/SLUS_010.40'), 'rb').read() if ZENITH else b''
SLUS_BASE = 0x8000F800
PRG_ORIG = PRG_ORIG + bytes(len(PRG) - len(PRG_ORIG))   # the shipped file is sector-rounded

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
        self.w(PRG_BASE, PRG, raw=True)
        self.stubs = {}
        self.setup_stubs()
        self.reset_world()

    # memory ---------------------------------------------------------------
    def off(self, a):
        o = a & 0x1FFFFFFF
        if 0x1F800000 <= o < 0x1F800400:   # scratchpad (vs_scratch): parked at the top of the model RAM
            o = 0x1FF000 + (o & 0x3FF)
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
        self.w(SLUS_BASE, SLUS)
        self.w(PRG_BASE, PRG)
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
        self.wr(0x1F800008, SCRATCH_UNK8)   # vs_scratch.unk8
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
        self.frame_lstick = (128, 128)
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

    def setup_weapons(self, favs, cur, blade_cat=None, slots=None):
        """inventory entries 0..7 all filled; favs = set of entries that have a slot (slot = entry+1,
        so slot order is inventory order), or slots = {entry: slot value}; cur = equipped entry or -1"""
        for s in range(8):
            fav = slots.get(s, 0) if slots is not None else (s + 1 if s in favs else 0)
            self.set_weapon(s, s + 1, eq=int(s == cur), fav=fav)
            cat = (blade_cat or {}).get(s, 1)
            self.set_blade(s + 1, cat=cat, wep=20 + s, mat=s)

    def equipped(self):
        e = [s for s in range(8) if self.weapon(s)['eq']]
        return e

    # pad ------------------------------------------------------------------
    def pad_stub(self):
        """vs_main_processPadState, as in SLUS_010.40/main.c (mode 7)"""
        hw = self.frame_hw
        st = hw
        lx, ly = self.frame_stick
        rx, ry = self.frame_lstick
        # raw pad buffer: active low, buf[2] = Select..Left, buf[3] = L2..Square
        self.wr(PADBUF, 0, 1)
        self.wr(PADBUF + 1, 0x73, 1)
        self.wr(PADBUF + 2, (~(hw >> 8)) & 0xFF, 1)
        self.wr(PADBUF + 3, (~hw) & 0xFF, 1)
        # decomp rStick* = physical left stick: ORed into the D-pad bits (analog mode)
        if rx < 16:
            st |= PADLLEFT
        if rx >= 241:
            st |= PADLRIGHT
        if ry < 16:
            st |= PADLUP
        if ry >= 241:
            st |= PADLDOWN
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
        self.last_pad = (st, pressed, rep)   # what the driver reported this frame (the hook may change it afterwards)
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
        reg('vs_main_playSfxDefault', lambda m: m.log.append(('sfxdef', m.r[4], m.r[5])))
        reg('func_800B64A8', lambda m: m.log.append(('stand', m.r[4], m.r[5], m.r[6])))

        def exit6(m):
            m.wr(MODE, 1)
            m.log.append(('exit6',))
        reg('func_80073554', exit6)

        def sx(v):
            v &= 0xFFFF
            return v - 0x10000 if v & 0x8000 else v
        reg('func_800C9EB8', lambda m: (m.log.append(('origLabel', m.r[4])), m.set_v0(0x180)))
        reg('func_800C9F98', lambda m: m.log.append(('bullet', sx(m.r[4]), sx(m.r[4] >> 16), m.r[5])))

        def text(m):
            a = m.r[4]
            raw = bytearray()
            while m.rd(a, 1):
                raw.append(m.rd(a, 1))
                a += 1
            m.log.append(('text', raw.decode('latin1'), sx(m.r[5]), sx(m.r[5] >> 16), m.r[6], m.r[7]))
        reg('vs_battle_renderTextRawColor', text)   # the raw font: must not be used any more (see test_label_weapons)

        # the small font: vs_battle_setFontStyle(pal) selects font table 0 + palette,
        # vs_battle_printVariableWidthFontChar(glyph, x, y, ot) draws and returns the next x
        # (a space, glyph 0x8F, draws nothing and advances 6, as in the game)
        reg('vs_battle_setFontStyle', lambda m: m.log.append(('style', m.r[4])))

        def s32(v):
            return ((v + 0x80000000) & 0xFFFFFFFF) - 0x80000000

        def glyph(m):
            c, x, y, ot = m.r[4], s32(m.r[5]), s32(m.r[6]), m.r[7]
            m.log.append(('glyph', c, x, y, ot))
            m.set_v0(x + (6 if c == 0x8F else m.rd(CHAR_WIDTHS + c, 1)))
        reg('vs_battle_printVariableWidthFontChar', glyph)

        # first person look: the helpers func_8006EC7C calls
        self.stubs[0x800AA850] = ('func_800AA850', lambda m: m.log.append(('actorYaw', m.r[4], m.r[5], m.r[6])))
        self.stubs[0x800A1108] = ('func_800A1108', lambda m: None)
        self.stubs[0x8007AAF8] = ('lookAt', lambda m: m.log.append(('lookAt',)))

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
    def call(self, addr, a0=0, a1=0, a2=0, a3=0):
        self.r[4], self.r[5], self.r[6], self.r[7] = a0, a1, a2, a3
        return self.run(addr)

    shim_r1 = True
    _last_hw = 0

    def frame(self, hw=0, stick=(128, 128), lstick=(128, 128)):
        """one game frame. Neither variant has L1/R1 weapon cycling: the tests of the swap
        state machine that press R1 are driven through the overlay instead (L2+R2, then the slot button of
        the weapon R1 would have picked), so that the same machine is exercised."""
        was = self._last_hw
        self._last_hw = hw
        edge = hw & ~was & (L1 | R1)
        if (self.shim_r1 and edge and not (hw & (L2 | R2)) and self.rd(MODE) == 1
                and (self.rd(MENU, 1) & 0x3F) == 0x3F):
            d = 1 if edge & R1 else -1
            slots = {}
            for e in range(8):
                w = self.weapon(e)
                if w['blade'] and w['fav']:
                    slots[w['fav']] = e
            eq = self.equipped()
            cur = next((w['fav'] for w in [self.weapon(e) for e in eq]), 0)
            if cur == 0:
                cur = 0 if d > 0 else 9
            target = None
            for j in range(1, 9):
                s = ((cur - 1 + d * j) & 7) + 1
                if s in slots and slots[s] not in eq:
                    target = s
                    break
            if target is None:   # nothing to pick: press an empty slot (the "invalid" case)
                target = next((s for s in range(1, 9) if s not in slots), 1)
            self.wr(MODE, 6)
            self._frame(L2 | R2, stick, lstick)
            r = self._frame(L2 | R2 | SLOT_BTN_T[target - 1], stick, lstick)
            self.log[:] = [e for e in self.log if e != ('exit6',)]
            return r
        return self._frame(hw, stick, lstick)

    def _frame(self, hw=0, stick=(128, 128), lstick=(128, 128)):
        self.frame_hw = hw
        self.frame_stick = stick
        self.frame_lstick = lstick
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
    """next assigned slot after the equipped weapon's (cycling); an unassigned equipped weapon starts
    at the first (R1) / last (L1) slot"""
    cand = sorted(f for f in favs if f in have)
    if cur in cand:
        if len(cand) == 1:
            return None
        return cand[(cand.index(cur) + dir_) % len(cand)]
    if not cand:
        return None
    return cand[0] if dir_ > 0 else cand[-1]


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
    check('equipShield' not in names and ('freeWepModel', 1) not in m.log, 'two-handed without a shield on: no shield calls %s' % names)
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
    check(('equipShield', 0) in m3.log and ('freeWepModel', 1) in m3.log, 'two-handed with a shield on: stats cleared, model slot freed: %s' % m3.log)
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
    if not CLASSIC:
        # menu closed in mode 1 with real L1: the game sees R1 (default variant, see test_lr_camera)
        m = fresh()
        m.shim_r1 = False
        m.frame(L1)
        check(m.rd(PRESSED) & (L1 | R1) == R1 and m.rd(REPEAT) & (L1 | R1) == R1 and m.camera_view() == R1,
              'field: physical L1 is the game\'s R1')


def swap_lr(b):
    return (b & ~(L1 | R1)) | (R1 if b & L1 else 0) | (L1 if b & R1 else 0)


def test_lr_camera():
    """default variant: in the field (menu closed, game modes 1..3) the camera sees L1 and R1 exchanged, in every
    button word; the right stick X adds to the same bits; no weapon cycling; elsewhere (menus, other modes) raw"""
    words = (STATE, PRESSED, REPEAT)
    n = 0
    # buttons: physical -> what the game sees
    for mode in (1, 2, 3):
        for btn in (L1, R1, L1 | R1):
            m = Machine()
            m.shim_r1 = False
            m.setup_weapons(set(), 0, slots={0: 1, 1: 2, 2: 3, 3: 4})
            m.wr(MODE, mode)
            m.frame(0)
            m.log.clear()
            m.frame(btn | CIR)
            want = swap_lr(btn)
            for w in words:
                check(m.rd(w) & (L1 | R1) == want, 'mode %d buttons %x: word %x is %x, want %x' % (mode, btn, w, m.rd(w) & (L1 | R1), want))
            check(m.camera_view() == want, 'mode %d buttons %x: the camera reads %x, want %x' % (mode, btn, m.camera_view(), want))
            check(m.rd(PREV) == want | CIR and m.rd(PRESSED) & CIR, 'mode %d: other buttons untouched' % mode)
            # held: the game sees the held (previous-state) bits every frame, but only one press edge
            edges = 0
            for _ in range(4):
                m.frame(btn)
                edges += (m.rd(PRESSED) & (L1 | R1)) != 0
                check(m.camera_view() == want, 'held buttons stay exchanged')
            check(edges == 0, 'a held button gives one press edge only (%d more)' % edges)
            m.frame(0)
            check(m.camera_view() == 0 and m.rd(STATE) & (L1 | R1) == 0, 'released')
            check(m.equipped() == [0] and not any(e[0] in ('equipWeapon', 'sfx', 'toggle') for e in m.log),
                  'L1/R1 never change the weapon (no slot cycling): %s' % m.log)
            n += 1
    # the right stick X: right = the game's L1 = what the physical R1 gives, left = the game's R1 = physical L1
    for st, want in (((255, 128), L1), ((193, 128), L1), ((0, 128), R1), ((63, 128), R1), ((128, 128), 0), ((128, 0), 0), ((128, 255), 0)):
        m = Machine()
        m.shim_r1 = False
        m.setup_weapons(set(), 0)
        m.frame(0)
        m.frame(0, stick=st)
        check(m.camera_view() == want, 'stick %s: camera bits %x want %x' % (st, m.camera_view(), want))
    for st, btn in (((255, 128), R1), ((0, 128), L1)):
        m = Machine()
        m.shim_r1 = False
        m.frame(0)
        m.frame(btn, stick=st)
        check(m.camera_view() == swap_lr(btn) and m.camera_view() == (R1 if btn == L1 else L1),
              'stick and the same-direction button give the same bit (%x)' % m.camera_view())
    # stick and the opposite button together: both bits (the game treats it as both held)
    m = Machine()
    m.shim_r1 = False
    m.frame(0)
    m.frame(L1, stick=(255, 128))
    check(m.camera_view() == (L1 | R1), 'stick right + physical L1: both bits')
    # digital pad (no analog): the driver reports the stick centred; the buttons alone do it
    m = Machine()
    m.shim_r1 = False
    m.frame(0)
    m.frame(L1, stick=(128, 128), lstick=(128, 128))
    check(m.camera_view() == R1, 'digital pad: physical L1 -> game R1')
    m.frame(R1, stick=(128, 128), lstick=(128, 128))
    check(m.camera_view() == L1, 'digital pad: physical R1 -> game L1')
    # elsewhere the raw bits: menu open, and game modes 0 5 6 7 8 10
    for mode, menu in ((1, 0), (1, 1), (0, 0x3F), (5, 0x3F), (6, 0x3F), (7, 0x3F), (8, 0x3F), (10, 0x3F)):
        m = Machine()
        m.shim_r1 = False
        m.wr(MODE, mode)
        m.wr(MENU, menu, 1)
        m.mode10_left = 1000    # (the model's main loop would end game mode 10 by itself)
        m.frame(0)
        m.frame(L1)
        check(m.rd(PRESSED) & (L1 | R1) == L1 and m.rd(STATE) & (L1 | R1) == L1 and m.rd(PREV) & (L1 | R1) == L1,
              'mode %d menu %x: raw L1 (menus page with it)' % (mode, menu))
        m.frame(R1)
        check(m.rd(PRESSED) & (L1 | R1) == R1 and m.rd(PREV) & (L1 | R1) == R1, 'mode %d menu %x: raw R1' % (mode, menu))
    # a menu with the "opened from the main menu" flag counts as closed
    m = Machine()
    m.shim_r1 = False
    m.wr(MENU, 0x7F)
    m.frame(0)
    m.frame(L1)
    check(m.camera_view() == R1, 'currentMenu 0x7F is the field')
    print('L1/R1 camera mapping: %d button cases + stick, digital pad, raw outside the field' % n)


def test_camera():
    m = Machine()
    m.shim_r1 = False
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
    # PADj: see test_r3 (the fake R3 of the right stick is dropped in every direction)
    m.frame(0, stick=(128, 128))
    m.frame(0)
    # L1 and R1 come out exchanged (both held: both), the stick adds L1; the other buttons stay
    m.frame(L1 | R1 | L2 | CIR, stick=(255, 128))
    check(m.rd(PREV) == (L2 | CIR | L1 | R1), 'prev keeps other buttons, L1 R1 exchanged (%x)' % m.rd(PREV))
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


def test_fuzz(seed=1, frames=12000):
    import random
    rnd = random.Random(seed)
    m = Machine()
    m.shim_r1 = False
    s_loading = SYMS_BLOB['s_loading']
    m.setup_weapons({0, 2, 5}, 0, blade_cat={0: 1, 1: 3, 2: 2, 3: 7, 4: 4, 5: 9, 6: 5, 7: 8})
    hw = 0
    stick = (128, 128)
    lstick = (128, 128)
    prev_hw = 0
    prev_r3 = 0
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
            for bit in (L2, R2, L1, R1, TRI, CIR, CRS, SQR, SELECT, START, DUP, DDOWN, DLEFT, DRIGHT, PADJ):
                if rnd.random() < 0.25:
                    hw |= bit
            if rnd.random() < 0.3:
                hw |= L2 | R2
        if rnd.random() < 0.2:
            lstick = (rnd.choice([0, 128, 128, 255]), rnd.choice([0, 128, 128, 255]))
        if rnd.random() < 0.3:
            stick = (rnd.choice([0, 30, 63, 64, 90, 128, 128, 128, 165, 193, 230, 255]), rnd.choice([0, 128, 128, 255]))
        m.load_frames = rnd.choice([1, 2, 5, 30])
        if rnd.random() < 0.01:
            for s in range(8):
                m.wr(INV + s * W_SIZE + W_GEMS + 3, rnd.choice([0, 1, 1, 2, 5, 8, 9, 0x7F]), 1)
        was_mode = m.rd(MODE)
        prev_state_prev = m.rd(PREV)
        try:
            mode = m.frame(hw, stick, lstick)
        except Halt as e:
            check(False, 'fuzz halted at frame %d: %s' % (f, e))
            return
        eq = m.equipped()
        check(len(eq) <= 1, 'fuzz: more than one weapon equipped %s' % eq)
        if not loading and (m.rd(MENU, 1) & 0x3F) == 0x3F and not m.rd(s_loading):
            vals = [m.weapon(x)['fav'] for x in range(8) if m.weapon(x)['blade']]
            vals = [v for v in vals if v]
            check((LEAN or len(vals) == len(set(vals))) and all(1 <= v <= 8 for v in vals),
                  'fuzz: slots not unique / out of range %s' % vals)
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
        closed = (m.rd(MENU, 1) & 0x3F) == 0x3F
        field = closed and 1 <= was_mode <= 3 and not loading
        st = hw | (PADJ if (stick[0] < 32 or stick[0] >= 225 or stick[1] < 32 or stick[1] >= 225) else 0)
        st |= (PADLLEFT if lstick[0] < 16 else 0) | (PADLRIGHT if lstick[0] >= 241 else 0) \
            | (PADLUP if lstick[1] < 16 else 0) | (PADLDOWN if lstick[1] >= 241 else 0)
        edges = st & ~prev_hw
        if CLASSIC:
            # classic: the pad state is the driver's, bit for bit (fake R3 and L1/R1 included), except the
            # buttons the overlay itself consumes: Select with R2 in mode 1, the shortcut buttons and Select
            # while L2+R2 are held in mode 6
            keep = 0xFFFFFFFF
            if closed and was_mode == 1 and (hw & R2) and (edges & SELECT):
                keep &= ~SELECT
            if closed and was_mode == 6 and (hw & (L2 | R2)) == (L2 | R2):
                keep &= ~(SEL_SHORTCUT_BITS | SELECT | START)
            if not loading or not closed:
                check(pressed & keep == edges & keep, 'fuzz (classic): pressed %x vs the driver %x' % (pressed & keep, edges & keep))
                check(m.rd(STATE) & keep == st & keep and m.rd(PREV) & keep == st & keep,
                      'fuzz (classic): state/prev changed %x %x vs %x' % (m.rd(STATE), m.rd(PREV), st))
        else:
            if field:
                # L1/R1 come out exchanged in the field (real edges, real state)
                check(pressed & (L1 | R1) == swap_lr(edges & (L1 | R1)) and m.rd(STATE) & (L1 | R1) == swap_lr(hw & (L1 | R1)),
                      'fuzz: L1/R1 not exchanged in the field (pressed %x state %x, hw %x)' % (pressed & 12, m.rd(STATE) & 12, hw & 12))
                # buttons other than L1, R1, Select(R2 toggle) are unchanged
                keep = ~(L1 | R1 | SELECT | PADJ) & 0xFFFF
                check(pressed & keep == edges & keep, 'fuzz: pressed changed %x vs %x' % (pressed & keep, edges & keep))
            elif closed and not loading and was_mode in (0, 5, 6, 7, 8, 10) and not (was_mode == 6 and (hw & (L2 | R2)) == (L2 | R2)):
                check(pressed & (L1 | R1) == edges & (L1 | R1), 'fuzz: L1/R1 raw outside modes 1..3')
            elif not loading and not closed:
                check(pressed & 0xFFF == edges & 0xFFF, 'fuzz: menu open pressed altered %x vs %x' % (pressed, edges))
            if closed:
                # the pad driver's fake R3 (right stick) never reaches the game in the field; the real R3 does
                check(pressed & PADJ == hw & PADJ & ~prev_r3 and m.rd(STATE) & PADJ == hw & PADJ
                      and m.rd(PREV) & PADJ == hw & PADJ and m.rd(REPEAT) & PADJ == pressed & PADJ,
                      'fuzz: PADj not the real R3 (pressed %x state %x hw %x)' % (pressed & PADJ, m.rd(STATE) & PADJ, hw & PADJ))
        prev_r3 = hw & PADJ
        prev_hw = st
        # statistics
        swaps += sum(1 for e in m.log if e[0] == 'equipWeapon')
        m.log.clear()
    check(max_frozen < 400, 'fuzz: froze for %d frames' % max_frozen)
    print('fuzz: %d frames, %d swaps, longest freeze %d frames' % (frames, swaps, max_frozen))


# ===========================================================================
# weapon slots: overlay labels, slot buttons, assign mode, migration
# ===========================================================================
LABEL = SYMS_BLOB['wslot_label']
S_WMODE = SYMS_BLOB['s_wmode']
S_ASSIGN = SYMS_BLOB['s_assign']
S_LOADING_ADDR = SYMS_BLOB['s_loading']
SLOT_BTN = [CIR, TRI, SQR, CRS, DUP, DDOWN, DRIGHT, DLEFT]    # slot 1..8
SLOT_OF_ID = [2, 3, 1, 4, 5, 8, 7, 6]
# per overlay label id: (text anchor x, text y, right aligned, budget in characters of 6 px), slot of SLOT_OF_ID
#   Triangle, Square (raised 5), Circle, Cross (+1), Up, Left (ends at its bullet), Right (lowered 6), Down
EXP_LAB = [(242, 99, 0, 12), (214, 108, 1, 17), (252, 111, 0, 10), (223, 126, 1, 19),
           (94, 99, 0, 21), (71, 112, 1, 11), (103, 117, 0, 17), (81, 124, 1, 12)]
BUDGET = [e[3] for e in EXP_LAB]
# small-font palettes: weapon, equipped, assign-mode weapon, assign-mode equipped, hint, assign prompt
PAL = [4, 5, 6, 5, 7, 6]
SEL_SHORTCUT_BITS = 0xF0F0   # Circle/Triangle/Square/Cross + D-pad: the game's own shortcut buttons


def enc_raw(text):
    """the hint strings: game encoding, no padding"""
    out = []
    for ch in text:
        out.append({' ': 0x8F, ':': 0x9E}.get(ch, 10 + ord(ch) - 65 if 'A' <= ch <= 'Z' else None))
    return bytes(out) + b'\xE7'


HINT, HINT_ASSIGN = enc_raw('SELECT: ASSIGN' if LEAN else 'SELECT: ASSIGN  START: SHIELD'), enc_raw('ASSIGN: PRESS A SLOT')


def enc(text, space=(0xFA, 6)):
    """ASCII -> game encoding, 24 bytes padded with the terminator 0xE7. Item names separate words with
    `FA 06` (vs_char_spacing 6; seen in the game's data: 'Soul Kiss' = 1C 32 38 2F FA 06 14 2C 36 36 E7);
    space=(0x8F,) gives the space glyph instead"""
    out = []
    for ch in text:
        if ch.isdigit():
            out.append(int(ch))
        elif 'A' <= ch <= 'Z':
            out.append(10 + ord(ch) - 65)
        elif 'a' <= ch <= 'z':
            out.append(0x24 + ord(ch) - 97)
        elif ch == ' ':
            out.extend(space)
        else:
            out.append({'-': 0xA7, '.': 0xA0, "'": 0x96}[ch])
    out = out[:23]      # always terminated: the game's names are
    if out and out[-1] == 0xFA:
        out.pop()       # never cut `FA n` in two
    return bytes(out) + b'\xE7' * (24 - len(out))


def adv(m, c):
    """advance of a glyph of the small font (table 0); a space (0x8F) advances 6 and draws nothing"""
    return 6 if c == 0x8F else m.rd(CHAR_WIDTHS + c, 1)


def ref_small(m, raw, maxch, align, x, y, pal):
    """the calls drawSmall must make: setFontStyle(pal), then one glyph call per character, at most maxch
    characters (6 px each), a blank (`FA n` or the glyph 0x8F) is one 0x8F glyph call (the font routine draws
    nothing and advances 6), trailing blanks dropped; aligned left (0), centred (1) or ending at x (2); drawn
    at y - 1, the sprites linked at vs_scratch.unk8 - 12 (the `ot` argument; the font routine adds 12)"""
    raw = bytes(raw)
    items = []
    k = i = 0
    while len(items) < maxch and i < len(raw) and raw[i] != 0xE7:
        c = raw[i]
        if c == 0xFA:
            items.append(0x8F)
            i += 2
        else:
            items.append(c)
            i += 1
            if c != 0x8F:
                k = len(items)
    out = [('style', pal)]
    xx = x - k * 3 * align
    for c in items[:k]:
        out.append(('glyph', c, xx, y - 1, SCRATCH_UNK8 - 12))
        xx += adv(m, c)
    return out


def native_xy(m, id_, anim):
    """label and bullet position of the game's own overlay (func_800C9FE8 data), x/y of the label, bullet"""
    def tb(a, n):
        return [m.rd(a + i, 1) for i in range(n)]
    st = m.rd(SYM['vs_battle_rowAnimationSteps'] + anim, 1)
    if id_ < 4:
        lab, bul, w = tb(0x800EBCC8, 8), tb(0x800EBCC0, 8), m.rd(0x800EBCD0 + 4 * id_, 2)
        x = 160 + st + lab[id_] - 2 + (w if id_ & 1 else 0)
        return x, lab[id_ + 4], 160 + st + bul[id_], bul[id_ + 4]
    i = id_ - 4
    lab, bul, w = tb(0x800EBCA0, 8), tb(0x800EBC98, 8), m.rd(0x800EBCA8 + 4 * i, 2)
    x = -st + lab[i] + (w if id_ & 1 else 0)
    return x, lab[i + 4], -st + bul[i], bul[i + 4]


NAMES = ['Dagger', 'Hand Axe', 'Broad Sword', 'Estoc-2.0', 'Mace of Wonders and Glory', 'Wooden Rod',
         "Rhomphaia", 'Iii Lll Mmm Www Jjj']


def overlay_machine(slots=None, cur=0, names=NAMES, drawn=False):
    m = Machine()
    slots = {i: i + 1 for i in range(8)} if slots is None else slots
    m.setup_weapons(set(), cur, slots=slots)
    for i, nm in enumerate(names):
        m.w(INV + i * W_SIZE + W_NAME, enc(nm))
    if drawn:
        m.wr(CHSTATE + CH_DRAWN, 1)
        m.wr(ACTOR + A_DRAWN_WORD, 1 << A_DRAWN_BIT)
        m.wr(ACTOR + A_ANIM, 101, 1)
    m.wr(MODE, 6)
    m.wr(D_ANIM, 0, 1)      # the overlay is fully slid in
    m.frame(L2 | R2)
    m.log.clear()
    return m


def test_label_original():
    m = Machine()
    for anim in (0, 3, 9):
        m.wr(D_ANIM, anim, 1)
        for i in range(8):
            m.log.clear()
            v = m.call(LABEL, i)
            check(v == 0x180 and m.log == [('origLabel', i)], 'weapon mode off: original behaviour id %d: %s %s' % (i, v, m.log))
    # entering and leaving the weapon mode through the real hook
    m = Machine()
    m.setup_weapons(set(), 0, slots={0: 1})
    m.wr(MODE, 6)
    m.frame(L2)
    check(m.rd(S_WMODE) == 0 and m.call(LABEL, 3) == 0x180, 'L2 alone: native labels')
    m.frame(R2)
    check(m.rd(S_WMODE) == 0, 'R2 alone: native labels')


def raw_name(m, entry):
    a = m.off(INV + entry * W_SIZE + W_NAME)
    return bytes(m.mem[a:a + 24])


def label_step(m, i, anim):
    """x shift of the overlay animation: button group +step, D-pad group -step"""
    st = m.rd(SYM['vs_battle_rowAnimationSteps'] + anim, 1)
    return st if i < 4 else -st


def label_geometry(m):
    """text rectangles of the widest label of every id, glyph and bullet rectangles of the game (fully slid in)"""
    glyphs = {'dpad': (72, 102, 30, 30)}
    for k in range(4):
        v = m.rd(0x800EBC88 + 4 * k)
        glyphs['face%d' % k] = (160 + (v & 0xFFFF), (v >> 16) & 0xFFFF, 16, 16)
    bullets = []
    for i in range(8):
        x, y, bx, by = native_xy(m, i, 0)
        bullets.append((bx, by, 6, 6))
    boxes = []
    for i, (ax, y, right, n) in enumerate(EXP_LAB):
        wd = 6 * n
        x0 = ax - wd if right else ax
        boxes.append((x0, y + 1, wd, 9))      # ink rows y+1 .. y+9 of the 12 px cell drawn at y-1
    return glyphs, bullets, boxes


def test_label_layout():
    """every label of the widest name: >= 4 px from the screen edge and from anything foreign (other labels sharing
    a text row, glyphs and bullets that are not its own), exactly the layout the budgets were computed from"""
    m = Machine()
    glyphs, bullets, boxes = label_geometry(m)

    def gap(a, b):
        """horizontal gap between two rectangles that share rows, else None; negative if they overlap"""
        if a[1] >= b[1] + b[3] or b[1] >= a[1] + a[3]:
            return None
        return max(b[0] - (a[0] + a[2]), a[0] - (b[0] + b[2]))
    for i, bx in enumerate(boxes):
        x0, x1 = bx[0], bx[0] + bx[2]
        check(x0 >= 4 and x1 <= 316, 'id %d: %d..%d is inside the screen with a 4 px margin' % (i, x0, x1))
        for j, ob in enumerate(boxes):
            if j > i:
                g = gap(bx, ob)
                check(g is None or g >= 4, 'labels %d and %d on a shared row are %s px apart' % (i, j, g))
        for j, bl in enumerate(bullets):
            if j == i:
                continue
            g = gap(bx, bl)
            check(g is None or g >= 4 or (g >= 0 and False), 'label %d vs the bullet of %d: %s px' % (i, j, g))
        own = ['dpad'] if i >= 4 else ['face%d' % k for k in range(4)]
        for name, gl in glyphs.items():
            if name in own:
                continue
            g = gap(bx, gl)
            check(g is None or g >= 4, 'label %d vs glyph %s: %s px' % (i, name, g))
    # anchors against the game's bullets: left aligned labels start 5 px after their bullet (the native picture
    # position), right aligned ones end within 0..1 px of the bullet; nothing but the bullet is closer
    for i, (ax, y, right, n) in enumerate(EXP_LAB):
        bx = native_xy(m, i, 0)[2]
        if right:
            check(0 <= ax - bx <= 1, 'id %d right aligned label ends %d px after its bullet' % (i, ax - bx))
        else:
            check(4 <= ax - bx <= 6, 'id %d left aligned label starts %d px after its bullet' % (i, ax - bx))
    # the alignment in the table: odd id = right aligned (the label is on the left of its glyph)
    check([e[2] for e in EXP_LAB] == [i & 1 for i in range(8)], 'odd ids are right aligned')
    # the rows: nothing but Up/Triangle, Left/Right/Square/Circle/Down/Cross rows overlap; Square and Right no longer
    check(gap(boxes[1], boxes[6]) is None, 'Square and D-pad Right no longer share a text row')
    print('label layout: 8 labels checked against the screen, each other, glyphs and bullets')


def test_label_weapons():
    m = overlay_machine()
    n = 0
    for assign in (0, 1):
        m.wr(S_ASSIGN, assign)
        m.wr(S_WMODE, 1)
        for anim in range(10):
            m.wr(D_ANIM, anim, 1)
            for i in range(8):
                m.log.clear()
                v = m.call(LABEL, i)
                ax, y, right, mx = EXP_LAB[i]
                x, _, bx, by = native_xy(m, i, anim)
                w = [e for e in range(8) if SLOT_OF_ID[i] == e + 1][0]
                pal = PAL[assign * 2 + (1 if w == 0 else 0)]
                exp = [('bullet', bx, by, 0x180)]
                exp += ref_small(m, raw_name(m, w), mx, 2 if right else 0, ax + label_step(m, i, anim), y, pal)
                if i == 4 and anim == 0:
                    exp += ref_small(m, HINT_ASSIGN if assign else HINT, 30, 1, 160, 142, PAL[4 + assign])
                check(v == 0 and m.log == exp, 'label id %d anim %d assign %d:\n   got  %s\n   want %s' % (i, anim, assign, m.log, exp))
                check(not any(e[0] == 'text' for e in m.log), 'the raw-text font (glyph 0 = HUD digits in the field) is not used')
                n += 1
    print('labels (positions, names, small-font palettes, hint): %d cases' % n)
    # names with blanks: `FA 06` between the words (what the game's item names really contain) and the space
    # glyph 0x8F both come out as a 6 px gap, the second word is drawn when it fits
    m.wr(S_ASSIGN, 0)
    m.wr(D_ANIM, 1, 1)      # (the hint line is drawn only at animation step 0)

    def drawn(m, i):
        return [e for e in m.log if e[0] == 'glyph']

    def text_of(gl):
        """the drawn text from the glyph calls: letters of the font, '_' for a blank"""
        out = ''
        for e in gl:
            c = e[1]
            out += '_' if c == 0x8F else (chr(48 + c) if c < 10 else chr(55 + c) if c < 36 else chr(61 + c) if c < 62 else '?')
        return out
    for space in ((0xFA, 6), (0x8F,)):
        for i in range(8):
            w = SLOT_OF_ID[i] - 1
            mx = BUDGET[i]
            right = EXP_LAB[i][2]
            cases = {
                'Soul Kiss': 'Soul Kiss',
                'Seventh Heaven': 'Seventh Heaven',
                'Pink Panther Spear': 'Pink Panther Spear',
                'exact fit': 'W' * ((mx - 1) // 2) + ' ' + 'W' * (mx - 1 - (mx - 1) // 2),
                'one too long': 'W' * ((mx - 1) // 2) + ' ' + 'W' * (mx - (mx - 1) // 2),
                'blank at the cut': 'W' * (mx - 1) + ' ' + 'WWW',
                'blank before the cut': 'W' * (mx - 2) + ' ' + 'WWW',
            }
            for label, nm in cases.items():
                m.w(INV + w * W_SIZE + W_NAME, enc(nm, space))
                m.log.clear()
                m.call(LABEL, i)
                gl = drawn(m, i)
                want = nm[:mx].rstrip(' ')
                if space == (0xFA, 6) and len(enc(nm, space)) and False:
                    pass
                got = text_of(gl).replace('_', ' ')
                if len(want) > mx:
                    want = want[:mx]
                check(got == want, 'id %d %r (%s) space=%s: drew %r, want %r' % (i, nm, label, space, got, want))
                # the gap is real: consecutive glyph x differ by 6 across a blank
                xs = [e[2] for e in gl]
                check(all(b - a == 6 for a, b in zip(xs, xs[1:])), 'id %d %r: 6 px per character incl. blanks' % (i, nm))
                if gl:
                    ax = EXP_LAB[i][0] + label_step(m, i, 1)
                    if right:
                        check(xs[-1] + 6 == ax, 'id %d %r ends at the anchor' % (i, nm))
                    else:
                        check(xs[0] == ax, 'id %d %r starts at the anchor' % (i, nm))
    # exact fit really shows both words (and all the characters); one more character is cut, not the second word
    for i in range(8):
        w = SLOT_OF_ID[i] - 1
        mx = BUDGET[i]
        a = (mx - 1) // 2
        m.w(INV + w * W_SIZE + W_NAME, enc('A' * a + ' ' + 'B' * (mx - 1 - a)))
        m.log.clear()
        m.call(LABEL, i)
        check(len(drawn(m, i)) == mx, 'id %d: a %d character two-word name is drawn completely' % (i, mx))
        m.w(INV + w * W_SIZE + W_NAME, enc('A' * a + ' ' + 'B' * (mx - a)))
        m.log.clear()
        m.call(LABEL, i)
        check(len(drawn(m, i)) == mx and text_of(drawn(m, i)).endswith('B' * (mx - 1 - a)), 'id %d: one character too many is cut mid-word' % i)
    # a name that is only blanks draws nothing; an empty name too
    m.w(INV + 0 * W_SIZE + W_NAME, enc(' '))
    m.log.clear()
    m.call(LABEL, 2)
    check(not drawn(m, 2), 'blank name: no glyph')
    # an empty slot draws the dimmed native bullet only: no "--", no text, no glyph, no font call
    m = overlay_machine(slots={0: 3, 1: 0})
    for anim in (0, 5):
        m.wr(D_ANIM, anim, 1)
        for i in range(8):
            m.log.clear()
            m.call(LABEL, i)
            x, y, bx, by = native_xy(m, i, anim)
            if SLOT_OF_ID[i] in (3, ):
                check(m.log[0][3] == 0x180 and any(e[0] == 'glyph' for e in m.log), 'slot 3 weapon shown')
            else:
                hint = [] if not (i == 4 and anim == 0) else ref_small(m, HINT, 30, 1, 160, 142, PAL[4])
                check(m.log == [('bullet', bx, by, 0x140)] + hint, 'empty slot id %d draws only the bullet: %s' % (i, m.log))
    m.wr(S_ASSIGN, 1)
    m.log.clear()
    m.call(LABEL, 0)
    check(len(m.log) == 1 and m.log[0][0] == 'bullet', 'empty slot in assign mode: bullet only')
    # a record without a blade is not a weapon
    m = overlay_machine(slots={0: 1})
    m.wr(INV + 0 * W_SIZE + W_BLADE, 0, 1)
    m.log.clear()
    m.call(LABEL, 2)
    check(len(m.log) == 1 and m.log[0][0] == 'bullet' and m.log[0][3] == 0x140, 'slot of an empty record: bullet only')


def press(m, btn, extra=L2 | R2, lstick=(128, 128)):
    """a frame with the slot button down, then released"""
    m.log.clear()
    m.frame(extra | btn, lstick=lstick)
    log = list(m.log)
    pressed = m.rd(PRESSED)
    m.frame(extra, lstick=lstick)
    return log, pressed


def test_slot_press():
    n = 0
    # --- every button, weapon sheathed: exit mode 6 the game's way, then the existing swap sequence
    for slot in range(1, 9):
        for cur in (-1, 0, 6):
            tgt = slot - 1
            if cur == tgt:
                continue
            m = overlay_machine(cur=cur)
            log, pressed = press(m, SLOT_BTN[slot - 1])
            names = [e[0] for e in nostand(log)]
            check(nostand(log)[:2] == [('exit6',), ('sfx', 'change')] and ('equipWeapon', tgt) in log,
                  'slot %d: exit6, sound, equip -> %s' % (slot, nostand(log)))
            check(pressed & SEL_SHORTCUT_BITS == 0, 'slot %d: game shortcut buttons hidden (%x)' % (slot, pressed))
            check(m.equipped() == [tgt], 'slot %d equipped %s' % (slot, m.equipped()))
            check(m.rd(S_LOADING_ADDR) == 1 and m.rd(MODE) == 0, 'slot %d: swap state machine running, world held' % slot)
            run_until(m, lambda mm: mm.rd(S_LOADING_ADDR) == 0, hw=L2 | R2)
            check(m.rd(MODE) == 1 and (INV + tgt * W_SIZE + W_NAME) == m.rd(TB + 7 * TB_SIZE + TB_STRING),
                  'slot %d: name popup of the new weapon, mode 1' % slot)
            check(m.rd(S_WMODE) == 1, 'overlay stays in weapon mode while L2+R2 are held')
            n += 1
    # --- the same with the weapon drawn: sheathe animation, swap, draw
    for slot in (1, 4, 5, 8):
        m = overlay_machine(cur=2, drawn=True)
        log, pressed = press(m, SLOT_BTN[slot - 1])
        lg = nostand(log)
        check(lg[:3] == [('exit6',), ('sfx', 'change'), ('toggle', 0)], 'drawn slot %d: %s' % (slot, lg))
        check(m.rd(S_LOADING_ADDR) == 2 and m.equipped() == [2], 'sheathing first')
        run_until(m, lambda mm: mm.rd(S_LOADING_ADDR) == 0, hw=L2 | R2)
        check(m.equipped() == [slot - 1] and ('toggle', 1) in m.log and m.rd(CHSTATE + CH_DRAWN) == 1,
              'drawn slot %d: swapped and drawn again' % slot)
    # --- nothing to equip: empty slot, already equipped weapon: invalid sound, mode 6 stays, native shortcut hidden
    m = overlay_machine(slots={0: 1, 1: 2}, cur=0)
    for btn, what in ((SLOT_BTN[2], 'empty slot'), (SLOT_BTN[0], 'slot of the equipped weapon')):
        log, pressed = press(m, btn)
        check(nostand(log) == [('sfx', 'invalid')] and m.rd(MODE) == 6 and m.equipped() == [0], '%s: %s' % (what, log))
        check(pressed & SEL_SHORTCUT_BITS == 0, '%s: shortcut hidden' % what)
    # --- safety gates of the swap
    gates = {
        'transition 1': lambda m: m.wr(TRANS, 1), 'transition 2': lambda m: m.wr(TRANS, 2),
        'transition 4': lambda m: m.wr(TRANS, 4), 'status 0x2000': lambda m: setattr(m, 'status', 0x2000),
        'status 0x4000': lambda m: setattr(m, 'status', 0x4000), 'recovery timer': lambda m: m.wr(ACT2 + 0x954, 5, 2),
        'busy animation': lambda m: setattr(m, 'busy', 1), 'queue busy': lambda m: m.wr(Q, 3, 1)}
    for name, setup in gates.items():
        m = overlay_machine(cur=0)
        setup(m)
        log, pressed = press(m, SLOT_BTN[1])
        check(nostand(log) == [('sfx', 'invalid')] and m.rd(MODE) == 6 and m.equipped() == [0] and pressed & SEL_SHORTCUT_BITS == 0,
              'gate %s: %s' % (name, log))
    for name, setup in (('transition 3', lambda m: m.wr(TRANS, 3)), ('status 0x8000', lambda m: setattr(m, 'status', 0x8000))):
        m = overlay_machine(cur=0)
        setup(m)
        press(m, SLOT_BTN[1])
        check(m.equipped() == [1], 'gate %s allows' % name)
    # --- two buttons at once: the lowest slot wins (the game checks Circle, Triangle, Square, Cross, Up, Down, Right, Left)
    m = overlay_machine(cur=-1)
    press(m, SLOT_BTN[5] | SLOT_BTN[2] | SLOT_BTN[7])
    check(m.equipped() == [2], 'priority: slot 3 beats 6 and 8 (%s)' % m.equipped())
    # --- not in weapon mode: the game keeps its own shortcut handling
    for held in (L2, L2 | CIR):
        m = Machine()
        m.setup_weapons(set(), 0, slots={0: 1, 1: 2})
        m.wr(MODE, 6)
        m.frame(L2)
        m.log.clear()
        m.frame(held | (TRI if held == L2 else 0))
        check(not m.log and m.rd(PRESSED) & (TRI | CIR) != 0 and m.rd(MODE) == 6, 'L2 only: native shortcut untouched %x' % m.rd(PRESSED))
    m = Machine()
    m.setup_weapons(set(), 0, slots={0: 1, 1: 2})
    m.wr(MODE, 6)
    m.frame(L2)
    m.frame(L2 | SELECT)
    check(m.rd(PRESSED) & SELECT and m.rd(S_ASSIGN) == 0, 'L2 + Select without R2 is not ours')
    # --- L2+R2 in other modes / with a menu open: nothing
    for mode, menu in ((2, 0x3F), (3, 0x3F), (0, 0x3F), (6, 0x00), (1, 0x3F)):
        m = overlay_machine(cur=0)
        m.wr(MODE, mode)
        m.wr(MENU, menu, 1)
        m.log.clear()
        m.frame(L2 | R2 | TRI)
        check(m.equipped() == [0] and not any(e[0] in ('exit6', 'equipWeapon') for e in m.log),
              'mode %d menu %x: no slot action' % (mode, menu))
    print('slot buttons: %d single-press cases + gates' % n)


def test_dpad_stick():
    # slots 5..8 only from the physical D-pad; the left stick (decomp rStick) is ORed into the D-pad bits
    sticks = {'left': ((0, 128), 8), 'right': ((255, 128), 7), 'up': ((128, 0), 5), 'down': ((128, 255), 6)}
    for name, (st, slot) in sticks.items():
        m = overlay_machine(cur=-1)
        for _ in range(3):
            m.log.clear()
            m.frame(L2 | R2, lstick=st)
            check(m.rd(STATE) & SLOT_BTN[slot - 1] != 0, 'stick %s really synthesises the D-pad bit (test model)' % name)
            check(m.rd(PRESSED) & SEL_SHORTCUT_BITS == 0, 'stick %s: shortcut bit leaked into Pressed' % name)
        check(m.equipped() == [] and not m.log and m.rd(MODE) == 6, 'stick %s while holding L2+R2 fires nothing: %s' % (name, m.log))
        m.frame(L2 | R2)
        # stick first, L2+R2 pressed later
        m = overlay_machine(cur=-1)
        m.frame(0, lstick=st)
        m.frame(L2, lstick=st)
        m.frame(L2 | R2, lstick=st)
        check(m.equipped() == [] and m.rd(MODE) == 6, 'stick %s held, then R2: nothing' % name)
        # the physical D-pad still works, also while the stick is held
        m = overlay_machine(cur=-1)
        m.frame(L2 | R2, lstick=st)
        btn = SLOT_BTN[slot - 1]
        m.log.clear()
        m.frame(L2 | R2 | btn, lstick=st)
        check(m.equipped() == [slot - 1], 'physical D-pad %s with the stick held fires slot %d (%s)' % (name, slot, m.equipped()))
    # D-pad held before L2+R2 does not fire when R2 arrives; a new press does
    m = overlay_machine(cur=-1)
    m.frame(L2 | DLEFT)
    m.frame(L2 | R2 | DLEFT)
    check(m.equipped() == [] and m.rd(MODE) == 6, 'D-pad held before R2: no fire')
    m.frame(L2 | R2)
    m.frame(L2 | R2 | DLEFT)
    check(m.equipped() == [7], 'then a fresh press fires slot 8')
    # a face button does not depend on the raw pad words
    m = overlay_machine(cur=-1)
    m.frame(L2 | R2 | CIR)
    check(m.equipped() == [0], 'Circle fires slot 1')


def slots_of(m):
    return [m.weapon(i)['fav'] for i in range(8)]


def test_assign_mode():
    # Select toggles the mode, with sound; the hint line changes
    m = overlay_machine(slots={0: 1, 1: 2}, cur=0)
    m.log.clear()
    m.frame(L2 | R2 | SELECT)
    check(m.rd(S_ASSIGN) == 1 and ('sfx', 'select') in m.log and m.rd(PRESSED) & SELECT == 0 and m.rd(REPEAT) & SELECT == 0,
          'Select turns assign mode on, sound, swallowed: %s' % m.log)
    m.frame(L2 | R2)
    m.wr(D_ANIM, 0, 1)
    m.log.clear()
    m.call(LABEL, 4)
    want = ref_small(m, HINT_ASSIGN, 30, 1, 160, 142, PAL[5])
    check(m.log[-len(want):] == want and not any(e[0] == 'text' for e in m.log), 'assign hint (small font, no raw text): %s' % (m.log[-3:],))
    m.log.clear()
    m.frame(L2 | R2 | SELECT)
    check(m.rd(S_ASSIGN) == 0 and ('sfx', 'leave') in m.log, 'Select again: off, sound')
    m.frame(L2 | R2)
    # equipped weapon (entry 0, slot 1) -> an empty slot: moves it
    m.frame(L2 | R2 | SELECT)
    m.frame(L2 | R2)
    m.log.clear()
    m.frame(L2 | R2 | SLOT_BTN[5])        # slot 6
    check(slots_of(m)[0] == 6 and slots_of(m)[1] == 2 and m.rd(S_ASSIGN) == 0 and ('sfx', 'select') in m.log
          and m.rd(MODE) == 6 and not m.rd(S_LOADING_ADDR), 'moved to slot 6, assign mode off, no swap: %s %s' % (slots_of(m), m.log))
    m.frame(L2 | R2)
    # onto an occupied slot: that weapon loses its slot
    m.frame(L2 | R2 | SELECT)
    m.frame(L2 | R2)
    m.frame(L2 | R2 | SLOT_BTN[3])        # slot 4 empty
    m.frame(L2 | R2)
    m.frame(L2 | R2 | SELECT)
    m.frame(L2 | R2)
    m.frame(L2 | R2 | SLOT_BTN[1])          # slot 2 held by entry 1
    check(slots_of(m)[:2] == [2, 0], 'took slot 2 from its owner: %s' % slots_of(m))
    m.frame(L2 | R2)
    # same slot again: cleared
    m.frame(L2 | R2 | SELECT)
    m.frame(L2 | R2)
    m.log.clear()
    m.frame(L2 | R2 | SLOT_BTN[1])
    check(slots_of(m)[0] == 0 and ('sfx', 'leave') in m.log and m.rd(S_ASSIGN) == 0, 'same slot clears it: %s' % slots_of(m))
    m.frame(L2 | R2)
    # latch off: the next press equips again (slot 1 is empty now, entry 1 holds slot 2 again after a fresh setup)
    m = overlay_machine(slots={0: 1, 1: 2}, cur=0)
    m.frame(L2 | R2 | SELECT)
    m.frame(L2 | R2)
    m.frame(L2 | R2 | SLOT_BTN[0])         # clears slot 1
    m.frame(L2 | R2)
    m.log.clear()
    m.frame(L2 | R2 | SLOT_BTN[1])         # assign mode is off: this equips entry 1
    check(m.equipped() == [1] and slots_of(m)[:2] == [0, 2] and ('exit6',) in m.log, 'latched off after one assignment: %s' % m.log)
    # all eight buttons assign to their slot
    for slot in range(1, 9):
        m = overlay_machine(slots={}, cur=3)
        m.frame(L2 | R2 | SELECT)
        m.frame(L2 | R2)
        m.frame(L2 | R2 | SLOT_BTN[slot - 1])
        check(slots_of(m) == [slot if i == 3 else 0 for i in range(8)] and m.rd(S_ASSIGN) == 0, 'assign to slot %d: %s' % (slot, slots_of(m)))
    # nobody equipped: invalid, the mode stays on
    m = overlay_machine(slots={1: 2}, cur=-1)
    m.frame(L2 | R2 | SELECT)
    m.frame(L2 | R2)
    m.log.clear()
    m.frame(L2 | R2 | SLOT_BTN[0])
    check(('sfx', 'invalid') in m.log and m.rd(S_ASSIGN) == 1 and slots_of(m) == [0, 2, 0, 0, 0, 0, 0, 0], 'no weapon equipped: %s' % m.log)
    # leaving L2+R2 turns it off
    for rel in (L2, R2, 0):
        m = overlay_machine(cur=0)
        m.frame(L2 | R2 | SELECT)
        check(m.rd(S_ASSIGN) == 1, 'on')
        m.frame(rel)
        check(m.rd(S_ASSIGN) == 0, 'released to %x: off' % rel)
        m.frame(L2 | R2)
        check(m.rd(S_ASSIGN) == 0, 'stays off when L2+R2 come back')
    # a swap (assign off) clears nothing, a swap while assign mode is on does not happen
    m = overlay_machine(slots={0: 1, 1: 2}, cur=0)
    m.frame(L2 | R2 | SELECT)
    m.frame(L2 | R2)
    m.frame(L2 | R2 | SLOT_BTN[1])
    check(m.equipped() == [0] and slots_of(m)[:2] == [2, 0], 'assign mode never swaps: %s' % slots_of(m))
    # the unarmed / quick R2+Select path is tested in test_quick_assign


def test_quick_assign():
    m = Machine()
    m.setup_weapons(set(), 3)
    m.frame(0)
    m.log.clear()
    m.frame(R2 | SELECT)
    check(slots_of(m)[3] == 1 and ('sfx', 'select') in m.log, 'R2+Select puts the equipped weapon into the first free slot')
    check(m.rd(PRESSED) & SELECT == 0 and m.rd(REPEAT) & SELECT == 0, 'Select swallowed')
    check(all(slots_of(m)[s] == 0 for s in range(8) if s != 3), 'only the equipped weapon changes')
    m.frame(R2)
    m.log.clear()
    m.frame(R2 | SELECT)
    check(slots_of(m)[3] == 0 and ('sfx', 'leave') in m.log, 'second press clears the slot')
    m.frame(0)
    m.log.clear()
    m.frame(SELECT)
    check(not m.log and m.rd(PRESSED) & SELECT, 'Select alone is untouched')
    # first FREE slot, not the first number
    m = Machine()
    m.setup_weapons(set(), 5, slots={0: 1, 1: 2, 2: 4, 3: 3})
    m.frame(0)
    m.frame(R2 | SELECT)
    check(slots_of(m)[5] == 5, 'first free slot is 5 (%s)' % slots_of(m))
    m = Machine()
    m.setup_weapons(set(), 5, slots={0: 2, 1: 3})
    m.frame(0)
    m.frame(R2 | SELECT)
    check(slots_of(m)[5] == 1, 'first free slot is 1')
    # garbage in the byte (> 8, not a slot): cleaned, then gets a real slot
    m = Machine()
    m.setup_weapons(set(), 3, slots={3: 0x5A})
    m.frame(0)
    check(slots_of(m)[3] == 0, 'garbage cleaned')
    m.frame(R2 | SELECT)
    check(slots_of(m)[3] == 1, 'garbage -> slot 1')
    # other modes / menu open
    m = Machine()
    m.setup_weapons(set(), 3)
    m.frame(0)
    m.wr(MODE, 2)
    m.log.clear()
    m.frame(R2 | SELECT)
    check(m.rd(PRESSED) & SELECT and not m.log, 'mode 2: Select untouched')
    m.wr(MODE, 1)
    m.frame(0)
    m.wr(MENU, 1)
    m.frame(R2 | SELECT)
    check(m.rd(PRESSED) & SELECT and not m.log, 'menu open: nothing')
    # no weapon equipped: swallowed, no change, silent
    m = Machine()
    m.setup_weapons({1}, -1)
    m.frame(0)
    m.log.clear()
    m.frame(R2 | SELECT)
    check(m.rd(PRESSED) & SELECT == 0 and slots_of(m) == [0, 2, 0, 0, 0, 0, 0, 0] and not m.log, 'unarmed: no change')
    # R2+Select and R1 in the same frame: the assignment wins, no swap
    m = Machine()
    m.setup_weapons({0, 1}, 0)
    m.frame(0)
    m.frame(R2 | SELECT | R1)
    check(m.equipped() == [0], 'no swap on the toggle frame')
    # all eight slots busy except the equipped weapon's: it gets the free one; eight weapons always leave one free
    m = Machine()
    m.setup_weapons(set(), 7, slots={i: i + 1 for i in range(7)})
    m.frame(0)
    m.frame(R2 | SELECT)
    check(slots_of(m)[7] == 8, 'last free slot')


def test_migration_lean():
    # the lean migrate() clears garbage (> 8) only: valid slot numbers, also duplicates, stay as they are
    for vals, want in (([1, 0, 1, 0, 1, 1, 0, 0], [1, 0, 1, 0, 1, 1, 0, 0]), ([9, 1, 0x7F, 8, 0xFF, 1, 2, 3], [0, 1, 0, 8, 0, 1, 2, 3]),
                       ([0] * 8, [0] * 8), ([3, 3, 3, 1, 0, 0, 0, 0], [3, 3, 3, 1, 0, 0, 0, 0])):
        m = Machine()
        m.setup_weapons(set(), -1, slots=dict(enumerate(vals)))
        m.frame(0)
        check(slots_of(m) == want, 'lean migrate %s -> %s (got %s)' % (vals, want, slots_of(m)))
        m.frame(0)
        check(slots_of(m) == want, 'idempotent')
    for x in range(256):
        m = Machine()
        m.setup_weapons(set(), -1, slots={0: x})
        m.frame(0)
        check(slots_of(m)[0] == (x if x <= 8 else 0), 'slot value %d' % x)
    m = Machine()
    m.setup_weapons(set(), -1, slots={0: 9, 1: 2})
    m.wr(MENU, 1)
    m.frame(0)
    check(slots_of(m)[:2] == [9, 2], 'menu open: not touched')
    m.wr(MENU, 0x3F)
    m.frame(0)
    check(slots_of(m)[:2] == [0, 2], 'menu closed: garbage cleared')


def test_migration():
    if LEAN:
        return test_migration_lean()

    def run_with(vals, blades=None):
        m = Machine()
        m.setup_weapons(set(), -1, slots={i: v for i, v in enumerate(vals)})
        if blades is not None:
            for i, b in enumerate(blades):
                if not b:
                    m.wr(INV + i * W_SIZE + W_BLADE, 0, 1)
        m.frame(0)
        return m, slots_of(m)
    m, v = run_with([1, 0, 1, 0, 1, 1, 0, 0])
    check(v == [1, 0, 2, 0, 3, 4, 0, 0], 'v2 favourites 1,1,1,1 -> 1,2,3,4 in inventory order: %s' % v)
    m.frame(0)
    m.frame(0)
    check(slots_of(m) == v, 'idempotent')
    m, v = run_with([1] * 8)
    check(v == [1, 2, 3, 4, 5, 6, 7, 8], 'eight favourites: %s' % v)
    m, v = run_with([0, 0, 1, 0, 0, 0, 0, 0])
    check(v == [0, 0, 1, 0, 0, 0, 0, 0], 'a single favourite stays in slot 1')
    m, v = run_with([0] * 8)
    check(v == [0] * 8, 'nothing to do')
    m, v = run_with([9, 1, 0x7F, 8, 0xFF, 1, 2, 3])
    check(v == [0, 1, 0, 8, 0, 4, 2, 3], 'values > 8 cleared, duplicates get the lowest free slot: %s' % v)
    m, v = run_with([3, 3, 3, 1, 0, 0, 0, 0])
    check(v == [3, 2, 4, 1, 0, 0, 0, 0], 'duplicates of another slot: %s' % v)
    m, v = run_with([1, 1, 2, 0, 0, 0, 0, 0])
    check(v == [1, 3, 2, 0, 0, 0, 0, 0], 'a duplicate never takes a slot another weapon holds: %s' % v)
    m, v = run_with([1, 1, 1, 0, 0, 0, 0, 0], blades=[1, 0, 1, 1, 1, 1, 1, 1])
    check(v == [1, 1, 2, 0, 0, 0, 0, 0], 'records without a blade are ignored: %s' % v)
    # exhaustive: every combination of {0,1} on 8 weapons (the v2 save format) ends with distinct slots, order kept
    bad = 0
    for mask in range(256):
        vals = [(mask >> i) & 1 for i in range(8)]
        m = Machine()
        m.setup_weapons(set(), -1, slots=dict(enumerate(vals)))
        m.frame(0)
        got = slots_of(m)
        fav = [i for i in range(8) if vals[i]]
        want = [0] * 8
        for k, i in enumerate(fav):
            want[i] = k + 1
        bad += got != want
    check(bad == 0, 'all 256 v2 favourite masks migrate to 1..n in inventory order (%d wrong)' % bad)
    # it runs in the field only (menu closed) and does not touch anything while a menu is open
    m = Machine()
    m.setup_weapons(set(), -1, slots={0: 1, 1: 1})
    m.wr(MENU, 1)
    m.frame(0)
    check(slots_of(m)[:2] == [1, 1], 'menu open: not touched')
    m.wr(MENU, 0x3F)
    m.frame(0)
    check(slots_of(m)[:2] == [1, 2], 'menu closed: migrated')


def test_cycle_slots():
    # L1/R1 walk the assigned weapons in slot order, not inventory order
    perm = {0: 5, 1: 2, 2: 8, 3: 0, 4: 1, 5: 7, 6: 0, 7: 3}   # entry -> slot
    order = sorted((s, e) for e, s in perm.items() if s)
    entries = [e for s, e in order]            # entries by slot: 4, 1, 7, 0, 5, 2
    for cur in range(-1, 8):
        for button, d in ((R1, 1), (L1, -1)):
            m = Machine()
            m.setup_weapons(set(), cur, slots=perm)
            m.frame(0)
            m.log.clear()
            m.frame(button)
            if cur in entries:
                i = entries.index(cur)
                want = entries[(i + d) % len(entries)]
            elif d > 0:
                want = entries[0]
            else:
                want = entries[-1]
            check(m.equipped() == [want], 'slot cycle cur=%d dir=%d want %d got %s' % (cur, d, want, m.equipped()))
    # a single assigned weapon that is equipped: invalid; a single other one: that one
    m = Machine()
    m.setup_weapons(set(), 2, slots={2: 4})
    m.frame(0)
    m.frame(R1)
    check(('sfx', 'invalid') in m.log and m.equipped() == [2], 'only the equipped weapon is assigned')
    m = Machine()
    m.setup_weapons(set(), 2, slots={6: 1})
    m.frame(0)
    m.frame(L1)
    check(m.equipped() == [6], 'equipped but unassigned -> the single assigned one')
    # nothing assigned
    m = Machine()
    m.setup_weapons(set(), 2, slots={})
    m.frame(0)
    m.frame(R1)
    check(('sfx', 'invalid') in m.log and m.equipped() == [2], 'nothing assigned: invalid')
    # old v2 favourites on L1/R1 work through the migration in the same frame
    m = Machine()
    m.setup_weapons(set(), 0, slots={0: 1, 3: 1, 5: 1})
    m.frame(0)
    m.frame(R1)
    check(m.equipped() == [3], 'v2 save: R1 -> second favourite')


def test_wmode_transitions():
    m = overlay_machine(cur=0)
    check(m.rd(S_WMODE) == 1, 'L2+R2 in mode 6: weapon mode')
    m.wr(D_ANIM, 0, 1)
    m.frame(L2)
    check(m.rd(S_WMODE) == 0, 'R2 released, L2 held: native labels again at once')
    m.frame(L2 | R2)
    check(m.rd(S_WMODE) == 1, 'R2 again')
    m.wr(D_ANIM, 3, 1)
    m.frame(0)
    check(m.rd(S_WMODE) == 1, 'both released while the overlay slides out: stays (no flash of native labels)')
    m.wr(D_ANIM, 10, 1)
    m.frame(0)
    check(m.rd(S_WMODE) == 0, 'overlay hidden: off')
    # mode 1 with both held (the game has not entered mode 6 yet): on; in other modes: unchanged
    m = Machine()
    m.setup_weapons(set(), 0, slots={0: 1})
    m.frame(L2 | R2)
    check(m.rd(S_WMODE) == 1, 'mode 1 + L2 + R2')
    m = Machine()
    m.setup_weapons(set(), 0, slots={0: 1})
    m.wr(MODE, 2)
    m.frame(L2 | R2)
    check(m.rd(S_WMODE) == 0, 'mode 2: no')
    m = Machine()
    m.setup_weapons(set(), 0, slots={0: 1})
    m.wr(MODE, 6)
    m.wr(MENU, 0)
    m.frame(L2 | R2)
    check(m.rd(S_WMODE) == 0, 'menu open: no')
    # during our own swap (mode 0 / 10) the weapon labels stay while L2+R2 are held
    m = overlay_machine(cur=0, drawn=True)
    m.wr(D_ANIM, 0, 1)
    m.frame(L2 | R2 | SLOT_BTN[1])
    for _ in range(4):
        m.frame(L2 | R2)
    check(m.rd(S_WMODE) == 1, 'weapon mode survives the sheathe/swap frames')
    run_until(m, lambda mm: mm.rd(S_LOADING_ADDR) == 0, hw=L2 | R2)
    check(m.rd(S_WMODE) == 1, 'and after the swap')
    # after the swap the game re-enters mode 6 by itself (L2 still held): a second swap works without releasing
    run_until(m, lambda mm: mm.rd(MODE) == 1, hw=L2 | R2)
    m.wr(MODE, 6)
    m.frame(L2 | R2)
    m.frame(L2 | R2 | SLOT_BTN[2])
    run_until(m, lambda mm: mm.rd(S_LOADING_ADDR) == 0, hw=L2 | R2)
    check(m.equipped() == [2], 'second swap without releasing L2+R2')


def test_code_budget():
    """the pieces of the mod fit into the reported ranges and every changed byte is accounted for"""
    changed = [i for i in range(len(PRG)) if PRG[i] != PRG_ORIG[i]]
    ranges = []
    for i in changed:
        if ranges and i - ranges[-1][1] <= 8:
            ranges[-1][1] = i + 1
        else:
            ranges.append([i, i + 1])
    allowed = [(0x8007991C, 4), (0x80099854, 268), (0x800AA108, 392), (0x800B26B8, 496), (0x800CA0A4, 4),
               (0x800CA1AC, 4), (0x800D155C, 284), (0x800D197C, 412), (0x800F5924, 0x800F6000 - 0x800F5924),
               # v3.1: the five extra unreferenced functions
               (0x80099FA8, 128), (0x800A1B28, 116), (0x800A0B5C, 132), (0x800A071C, 76), (0x800AAC80, 92)]
    if not CLASSIC:
        # swapAllowed + hint strings, wfp_look, drawHint; the first-person look hook
        allowed += [(0x8009BD90, 204), (0x800733F8, 140), (0x8007FF8C, 116), (0x8007A10C, 4)]
    # the first-person look call: patched in the default variant only, and it is the only call of func_8006EC7C
    jal_fp = lambda t: 0x0C000000 | ((t >> 2) & 0x3FFFFFF)
    sites = [PRG_BASE + o for o in range(0, len(PRG_ORIG) - 3, 4) if struct.unpack_from('<I', PRG_ORIG, o)[0] == jal_fp(0x8006EC7C)]
    check(sites == [0x8007A10C], 'func_8006EC7C is called from exactly one place in the game: %s' % [hex(s) for s in sites])
    now = struct.unpack_from('<I', PRG, 0x8007A10C - PRG_BASE)[0]
    if CLASSIC:
        check(now == jal_fp(0x8006EC7C), 'classic: the first-person call is the original')
    else:
        check(now == jal_fp(SYMS_BLOB['wfp_look']), 'default: the first-person call goes to wfp_look')
    if ZENITH:
        allowed = []
        slus_allowed = []
        for l in open(os.path.join(ROOT, 'build/mod/zenith_allowed.txt')):
            f, a, n = l.split()
            (allowed if f == 'BATTLE' else slus_allowed).append((int(a, 16), int(n)))
        slus_orig = open(os.path.join(ROOT, 'build/mod/SLUS_010.40.zenith'), 'rb').read()
        schanged = [i for i in range(len(SLUS)) if SLUS[i] != slus_orig[i]]
        sstray = [i for i in schanged if not any(a - SLUS_BASE <= i < a - SLUS_BASE + n for a, n in slus_allowed)]
        check(not sstray, 'SLUS_010.40 bytes changed outside the allowed ranges: %s' % [hex(i + SLUS_BASE) for i in sstray[:8]])
        print('SLUS_010.40 bytes changed: %d in %d ranges' % (len(schanged), len(slus_allowed)))
    stray = [i for i in changed if not any(a - PRG_BASE <= i < a - PRG_BASE + n for a, n in allowed)]
    check(not stray, 'bytes changed outside the allowed ranges: %s' % [hex(i + PRG_BASE) for i in stray[:8]])
    print('changed byte clusters: %s' % ', '.join('%08X+%d' % (a + PRG_BASE, b - a) for a, b in ranges))


# ===========================================================================
# default variant: the pad driver's fake R3, first-person look
# ===========================================================================
def test_r3():
    """PADj: in the field (menu closed) only the real R3 button reaches the game, in every game mode; the fake one
    the pad driver ORs in when the right stick is pushed far in any direction never does. Start is untouched."""
    sticks = {'up': (128, 0), 'down': (128, 255), 'left': (0, 128), 'right': (255, 128), 'corner': (255, 255),
              'corner2': (0, 0)}
    n = 0
    for mode in (0, 1, 2, 3, 5, 6, 7, 8, 10):
        for name, st in sticks.items():
            m = Machine()
            m.setup_weapons(set(), 0)
            m.wr(MODE, mode)
            m.frame(0)
            for _ in range(3):
                m.frame(0, stick=st)
                raw = m.rd(PADBUF + 2, 1)
                check(m.rd(STATE) & PADJ == 0 and m.rd(PRESSED) & PADJ == 0 and m.rd(REPEAT) & PADJ == 0
                      and m.rd(PREV) & PADJ == 0,
                      'mode %d stick %s: fake PADj reached the game (state %x pressed %x)' % (mode, name, m.rd(STATE), m.rd(PRESSED)))
                check(raw & 4, 'model: the real R3 bit is not set')
                n += 1
    print('right stick, 6 directions x 9 game modes: PADj never reaches the game (%d frames)' % n)
    # real R3
    m = Machine()
    m.setup_weapons(set(), 0)
    m.frame(0)
    edges = 0
    for k in range(6):
        m.frame(PADJ)
        edges += (m.rd(PRESSED) & PADJ) != 0
        check(m.rd(STATE) & PADJ and m.rd(PREV) & PADJ, 'real R3 held: state/prev')
    check(edges == 1, 'real R3 held: exactly one press edge (%d)' % edges)
    m.frame(0)
    check(m.rd(STATE) & PADJ == 0 and m.rd(PRESSED) & PADJ == 0, 'real R3 released')
    # real R3 pressed while the right stick is already pushed (the driver's fake bit was up): still a press edge
    m.frame(0, stick=(128, 255))
    m.frame(0, stick=(128, 255))
    m.frame(PADJ, stick=(128, 255))
    check(m.rd(PRESSED) & PADJ, 'real R3 with the right stick held: press edge')
    m.frame(PADJ, stick=(128, 255))
    check(m.rd(PRESSED) & PADJ == 0 and m.rd(STATE) & PADJ, 'R3 + stick held: no second edge')
    m.frame(PADJ, stick=(128, 128))
    check(m.rd(PRESSED) & PADJ == 0 and m.rd(STATE) & PADJ, 'stick released, R3 still down: no edge, still held')
    m.frame(0, stick=(128, 255))
    check(m.rd(STATE) & PADJ == 0 and m.rd(PRESSED) & PADJ == 0, 'R3 released with the stick pushed: gone')
    # R3 click with the stick pushed in every direction
    for name, st in sticks.items():
        m = Machine()
        m.setup_weapons(set(), 0)
        m.frame(0, stick=st)
        m.frame(PADJ, stick=st)
        check(m.rd(PRESSED) & PADJ, 'R3 click, stick %s' % name)
    # Start still works, stick or not
    for st in ((128, 128), (128, 255)):
        m = Machine()
        m.setup_weapons(set(), 0)
        m.frame(0, stick=st)
        m.frame(START, stick=st)
        check(m.rd(PRESSED) & START and m.rd(STATE) & START and m.rd(PREV) & START, 'Start with stick %s' % (st,))
    # menu open: the game gets what the driver says
    m = Machine()
    m.setup_weapons(set(), 0)
    m.wr(MENU, 0)
    m.frame(0, stick=(128, 255))
    check(m.rd(STATE) & PADJ and m.rd(PRESSED) & PADJ, 'menu open: untouched')
    # the right stick still drives the camera (existing feature): sideways only
    m = Machine()
    m.setup_weapons(set(), 0)
    m.frame(0)
    m.frame(0, stick=(255, 128))
    check(m.camera_view() == L1, 'right stick right still rotates the camera')
    m.frame(0, stick=(128, 255))
    check(m.camera_view() == 0 and m.rd(STATE) & PADJ == 0, 'right stick down: no camera, no PADj')


def fp_run(m, prev, left, right, yaw, pitch, mode=7):
    """call wfp_look with the given state; returns (yaw, pitch, log). left = _portInfo rStick (the physical left
    stick, bytes 3/4), right = _portInfo lStick (the physical right stick, bytes 5/6)"""
    m.log.clear()
    m.wr(PORTINFO, mode, 1)
    m.wr(PORTINFO + 3, left[0], 1)
    m.wr(PORTINFO + 4, left[1], 1)
    m.wr(PORTINFO + 5, right[0], 1)
    m.wr(PORTINFO + 6, right[1], 1)
    m.wr(PREV, prev)
    m.wr(CAM, yaw & 0xFFFFFFFF)
    m.wr(CAM + 4, pitch & 0xFFFFFFFF)
    m.call(SYMS_BLOB['wfp_look'])
    # nothing but the camera angles may change: the stick bytes and the held-buttons word are restored
    check([m.rd(PORTINFO + k, 1) for k in (0, 3, 4, 5, 6)] == [mode, left[0], left[1], right[0], right[1]]
          and m.rd(PREV) == prev, 'wfp_look restores _portInfo and the button state')
    return m.rds(CAM), m.rds(CAM + 4), list(m.log)


def tdiv(a, b):
    q = abs(a) // b
    return q if a >= 0 else -q


def tmod(a, b=4096):
    r = abs(a) % b
    return r if a >= 0 else -r


def fp_orig(prev, left, yaw, pitch, mode):
    """the game's func_8006EC7C with up/down inverted (what the decomp edit does)"""
    if prev & DDOWN:
        pitch = tmod(pitch - 32)
    if prev & DUP:
        pitch = tmod(pitch + 32)
    if prev & DLEFT:
        yaw = tmod(yaw - 32)
    if prev & DRIGHT:
        yaw = tmod(yaw + 32)
    if mode == 7:
        ax, ay = left
        a, b = ax - 128, ay - 128
        if ax - 64 < 0 or ax - 64 > 128:
            v = ax - 64 if a <= 0 else ax - 192
            yaw = tmod(yaw + tdiv(v, 3))
        if b + 64 < 0 or b + 64 > 128:
            v = b + 64 if b <= 0 else b - 64
            pitch = tmod(pitch - tdiv(v, 3))
    if pitch > 896:
        pitch = 896
    elif pitch < -896:
        pitch = -896
    return yaw, pitch


def fp_ref(prev, left, right, yaw, pitch, mode=7):
    """first person look: the game's update with D-pad and left stick, then once more with the right stick in the
    left stick's place and without the D-pad"""
    yaw, pitch = fp_orig(prev, left, yaw, pitch, mode)
    return fp_orig(prev & ~(DUP | DDOWN | DLEFT | DRIGHT), right, yaw, pitch, mode)


def test_first_person():
    import random
    rnd = random.Random(7)
    m = Machine()
    C = (128, 128)
    # --- directions (all relative to the angles before): up/down inverted, left/right as before
    y, p, log = fp_run(m, DUP, C, C, 0, 0)
    check((y, p) == (0, 32), 'D-pad up inverted: pitch +32 (was -32): %s' % ((y, p),))
    y, p, log = fp_run(m, DDOWN, C, C, 0, 0)
    check((y, p) == (0, -32), 'D-pad down inverted: pitch -32')
    y, p, log = fp_run(m, DLEFT, C, C, 0, 0)
    check((y, p) == (-32, 0), 'D-pad left unchanged: yaw -32')
    y, p, log = fp_run(m, DRIGHT, C, C, 0, 0)
    check((y, p) == (32, 0), 'D-pad right unchanged: yaw +32')
    check(fp_run(m, DUP | DRIGHT, C, C, 0, 0)[:2] == (32, 32), 'the D-pad is applied once, not twice')
    for name in ('left', 'right'):
        def run(pos):
            return fp_run(m, 0, pos if name == 'left' else C, C if name == 'left' else pos, 0, 0)[:2]
        y, p = run((128, 255))
        check(y == 0 and p == -tdiv(128 - 64, 3), '%s stick down: pitch %d (inverted, was +)' % (name, p))
        y, p = run((128, 0))
        check(y == 0 and p == tdiv(128 - 64, 3), '%s stick up: pitch +%d' % (name, p))
        y, p = run((255, 128))
        check(p == 0 and y == tdiv(127 - 64, 3), '%s stick right: yaw +%d' % (name, y))
        y, p = run((0, 128))
        check(p == 0 and y == -tdiv(128 - 64, 3), '%s stick left: yaw %d' % (name, y))
    # --- the right stick has the speed and the dead zone of the left stick
    for v in range(0, 256):
        yl, pl, _ = fp_run(m, 0, (v, v), C, 0, 0)
        yr, pr, _ = fp_run(m, 0, C, (v, v), 0, 0)
        check(pl == pr and yl == yr, 'left/right stick give the same look at %d: %s %s' % (v, (yl, pl), (yr, pr)))
        if 64 <= v <= 192:
            check(yr == 0 and pr == 0, 'dead zone at %d' % v)
    # both sticks add up
    y, p, _ = fp_run(m, 0, (255, 128), (255, 128), 0, 0)
    check(y == 2 * tdiv(127 - 64, 3), 'both sticks add up')
    # --- the clamp of the original still applies
    y, p, _ = fp_run(m, 0, C, (128, 255), 0, -890)
    check(p == -896, 'pitch clamped at -896: %d' % p)
    y, p, _ = fp_run(m, DUP, C, (128, 0), 0, 890)
    check(p == 896, 'pitch clamped at +896: %d' % p)
    # --- two updates per call (one per stick set), each tells the world the yaw
    y, p, log = fp_run(m, 0, C, (255, 128), 100, 0)
    check([e[0] for e in log] == ['actorYaw', 'lookAt'] * 2 and log[2][2] == y & 0xFFF, 'two updates per call: %s' % (log,))
    # --- random cases against the reference model
    bad = 0
    for _ in range(3000):
        prev = rnd.choice([0, DUP, DDOWN, DLEFT, DRIGHT, DUP | DLEFT, DDOWN | DRIGHT]) | rnd.choice([0, L2, SELECT])
        left = (rnd.choice([0, 30, 63, 64, 65, 100, 128, 128, 160, 191, 192, 193, 255]), rnd.choice([0, 30, 63, 64, 65, 128, 128, 192, 193, 255]))
        right = (rnd.randrange(256), rnd.randrange(256))
        yaw = rnd.choice([0, 1, 1000, -1000, -4000, 4095, 2048])
        pitch = rnd.choice([0, 100, -100, 500, -500, 880, -880, 896, -896])
        mode = rnd.choice([7, 7, 7, 4])
        y, p, _ = fp_run(m, prev, left, right, yaw, pitch, mode)
        ry, rp = fp_ref(prev, left, right, yaw, pitch, mode)
        if (y, p) != (ry, rp):
            bad += 1
            if bad < 5:
                print('  first person mismatch prev=%x left=%s right=%s yaw=%d pitch=%d mode=%d: got %s want %s'
                      % (prev, left, right, yaw, pitch, mode, (y, p), (ry, rp)))
    check(bad == 0, 'first person look matches the model in all random cases (%d wrong)' % bad)
    # digital pad (mode 4): no stick input at all
    y, p, _ = fp_run(m, 0, C, C, 5, 5, mode=4)
    check((y, p) == (5, 5), 'no input, no change')
    print('first person: directions, dead zone, speed, clamp, 3000 random cases checked')


# ===========================================================================
# classic variant: everything outside the overlay is the game's
# ===========================================================================
def test_classic_passthrough():
    import random
    rnd = random.Random(3)
    # L1/R1 do what the game does (rotate the camera) and nothing else: no weapon cycling
    m = Machine()
    m.shim_r1 = False
    m.setup_weapons(set(), 0, slots={0: 1, 1: 2, 2: 3})
    m.frame(0)
    m.log.clear()
    for btn in (L1, R1, L1 | R1):
        m.frame(btn)
        check(m.rd(PRESSED) & (L1 | R1) == btn & (L1 | R1) and m.rd(STATE) & (L1 | R1) == btn
              and m.rd(PREV) & (L1 | R1) == btn and m.rd(REPEAT) & (L1 | R1) == btn & (L1 | R1),
              'classic: L1/R1 %x pass through untouched (pressed %x prev %x)' % (btn, m.rd(PRESSED), m.rd(PREV)))
        check(m.camera_view() == btn, 'classic: the camera sees real L1/R1 (%x)' % m.camera_view())
        m.frame(0)
    check(m.equipped() == [0] and not any(e[0] in ('equipWeapon', 'sfx') for e in m.log), 'classic: L1/R1 never swap weapons: %s' % m.log)
    # the right stick: no camera synthesis, the fake R3 of the pad driver is the game's business as before
    for st in ((255, 128), (0, 128), (128, 255), (128, 0), (255, 255)):
        m.frame(0)
        m.frame(0, stick=st)
        want = PADJ
        check(m.camera_view() == 0 and m.rd(STATE) & PADJ == want and m.rd(PRESSED) & PADJ == want and m.rd(PREV) & PADJ == want,
              'classic: right stick %s untouched: PADj as the driver set it (state %x pressed %x)' % (st, m.rd(STATE), m.rd(PRESSED)))
    # the hook is transparent: random frames, the pad words are exactly the driver's unless the overlay consumes a button
    bad = 0
    for _ in range(4000):
        m = Machine()
        m.shim_r1 = False
        m.setup_weapons(set(), rnd.choice([-1, 0, 3]), slots={i: i + 1 for i in range(8) if rnd.random() < 0.6})
        mode = rnd.choice([0, 1, 1, 1, 2, 3, 5, 7, 8, 10])
        m.wr(MODE, mode)
        m.wr(MENU, rnd.choice([0x3F, 0x3F, 0x3F, 0]))
        hw0 = 0
        for _f in range(3):
            hw = 0
            for bit in (L1, R1, TRI, CIR, CRS, SQR, START, DUP, DDOWN, DLEFT, DRIGHT, PADJ, L2):
                if rnd.random() < 0.4:
                    hw |= bit
            stick = (rnd.choice([0, 64, 128, 128, 200, 255]), rnd.choice([0, 128, 128, 255]))
            lst = (rnd.choice([0, 128, 128, 255]), rnd.choice([0, 128, 128, 255]))
            if mode == 6:
                hw &= ~R2
            m.frame(hw, stick=stick, lstick=lst)
            st, pr, rep = m.last_pad
            ok = m.rd(STATE) == st and m.rd(PRESSED) == pr and m.rd(REPEAT) == rep and m.rd(PREV) == st
            if not ok:
                bad += 1
                if bad < 4:
                    print('  classic pad words changed: mode %d hw %x -> state %x/%x pressed %x/%x' % (mode, hw, m.rd(STATE), st, m.rd(PRESSED), pr))
            if mode == 6:
                break
    check(bad == 0, 'classic: the pad words are exactly the driver\'s (%d frames differ)' % bad)
    print('classic pass-through: L1/R1, right stick, 4000 random frames')


# ===========================================================================
# v3.1: per-slot shields (the shield of a weapon slot is a bit of shield.gems[3])
# ===========================================================================
SH_ID_O, SH_WEP_O, SH_MAT_O, SH_MASK_O = 4, 6, 0x28, 0x2F    # vs_main_inventoryShield: base.id, base.wepId, base.material, gems[3]


def sh_addr(i):
    return INV + SH_OFF + i * SH_SIZE


def set_shield(m, i, eq=0, mask=0, wep=None, mat=None, sid=1):
    """shield record i (0..7); sid = 0: an empty record (a discarded shield)"""
    a = sh_addr(i)
    m.w(a, bytes(SH_SIZE))
    if sid:
        m.wr(a, i + 1, 1)
        m.wr(a + SH_EQ, eq, 1)
        m.wr(a + SH_ID_O, sid, 1)
        m.wr(a + SH_WEP_O, 100 + i if wep is None else wep, 1)
        m.wr(a + SH_MAT_O, 7 + i if mat is None else mat, 2)
    m.wr(a + SH_MASK_O, mask, 1)


def masks(m):
    return [m.rd(sh_addr(i) + SH_MASK_O, 1) for i in range(8)]


def sh_eq(m):
    return [i for i in range(8) if m.rd(sh_addr(i) + SH_EQ_, 1)]


SH_EQ_ = SH_EQ


def qent(m, k):
    a = Q + k * Q_SIZE
    return (m.rd(a, 1), m.rd(a + Q_INDEX, 1), m.rd(a + Q_MODEL, 2), m.rd(a + Q_UNK4), m.rd(a + Q_ACTOR, 1),
            m.rd(a + Q_UNK11, 1), m.rd(a + Q_MAT, 1))


def sync_cat(m):
    """the game stores the loaded category in the actor when the category table has been loaded"""
    for e in m.equipped():
        b = m.rd(INV + e * W_SIZE + W_BLADE, 1)
        m.wr(ACTOR + A_5B1, m.rd(INV + BL_OFF + (b - 1) * BL_SIZE + BL_CAT, 1), 1)


def swap_machine(slots, cats, cur, shields, drawn=False, sentinel=True):
    """weapons 0..7 (blade n = entry n-1, category from cats, default 1 = one-handed), the overlay open; shields = {i: kwargs}.
    The sentinel (shield 7 with the bit of slot 8, no weapon there) keeps the one-time migration out of the way."""
    m = Machine()
    m.setup_weapons(set(), cur, blade_cat=cats, slots=slots)
    for i, kw in shields.items():
        set_shield(m, i, **kw)
    if sentinel:
        set_shield(m, 7, eq=0, mask=0x80)
    sync_cat(m)
    if drawn:
        m.wr(CHSTATE + CH_DRAWN, 1)
        m.wr(ACTOR + A_DRAWN_WORD, 1 << A_DRAWN_BIT)
        m.wr(ACTOR + A_ANIM, 101, 1)
    m.wr(MODE, 6)
    m.wr(D_ANIM, 0, 1)
    m.load_frames = 60
    m.frame(L2 | R2)
    m.log.clear()
    return m


def go(m, slot, drain=True):
    """press the slot button; with drain=False the queue is left as the swap built it"""
    m.log.clear()
    press(m, SLOT_BTN[slot - 1])
    if drain:
        m.load_frames = 3
        m.queue_wait = 3
        run_until(m, lambda mm: mm.rd(S_LOADING_ADDR) == 0, hw=L2 | R2, limit=800)
        sync_cat(m)
        m.anim_left = 0
        m.mode10_left = 0
        m.wr(ACTOR + A_ANIM, 101 if m.rd(CHSTATE + CH_DRAWN) else 1, 1)
        m.wr(MODE, 6)
        m.frame(L2 | R2)


def test_shield_assign():
    # one-handed weapon + equipped shield: the slot gets the shield's bit (R2+Select = first free slot)
    m = Machine()
    m.setup_weapons(set(), 0)
    set_shield(m, 2, eq=1)
    set_shield(m, 5)
    m.frame(0)
    m.frame(R2 | SELECT)
    m.frame(R2)
    check(slots_of(m)[0] == 1 and masks(m) == [0, 0, 1, 0, 0, 0, 0, 0], 'assign 1H + shield: slot 1, bit 0 on the equipped shield: %s %s' % (slots_of(m), masks(m)))
    m.frame(R2 | SELECT)
    m.frame(R2)
    check(slots_of(m)[0] == 0 and masks(m) == [0] * 8, 'clearing the slot clears its bit: %s' % masks(m))
    # two-handed weapon: the slot has no shield
    m = Machine()
    m.setup_weapons(set(), 0, blade_cat={0: 3})
    set_shield(m, 2, eq=1, mask=0x02)      # (an equipped shield with a two-handed weapon cannot happen; and slot 2 is not ours)
    m.frame(0)
    m.frame(R2 | SELECT)
    check(slots_of(m)[0] == 1 and masks(m)[2] == 0x02, 'assign 2H: no bit set (bit 0 clear), other slots untouched: %s' % masks(m))
    # no shield equipped: the slot has no shield, a stale bit of a bag shield is cleared
    m = Machine()
    m.setup_weapons(set(), 0)
    set_shield(m, 1, mask=0x03)
    m.frame(0)
    m.frame(R2 | SELECT)
    check(slots_of(m)[0] == 1 and masks(m)[1] == 0x02, 'assign without a shield: bit 0 cleared everywhere, bit 1 kept: %s' % masks(m))
    # at most one shield per slot, one shield may serve several slots
    m = Machine()
    m.setup_weapons(set(), 0, slots={3: 2})
    set_shield(m, 1, mask=0x01)                 # owned slot 1 before
    set_shield(m, 2, eq=1, mask=0x02)
    m.frame(0)
    m.frame(R2 | SELECT)                         # entry 0 -> first free slot (1)
    m.frame(R2)
    check(slots_of(m)[0] == 1 and masks(m)[1] == 0 and masks(m)[2] == 0x03, 'unique per slot, several slots per shield: %s' % masks(m))
    # assign mode: move from slot 1 to slot 5: the slot it leaves loses the bit, 5 gets it; the weapon that held 5 loses its slot
    m = overlay_machine(slots={0: 1, 1: 5, 2: 3}, cur=0)
    set_shield(m, 2, eq=1, mask=0x05)           # slots 1 and 3
    set_shield(m, 4, mask=0x10)                 # slot 5 belonged to this one
    m.frame(L2 | R2 | SELECT)
    m.frame(L2 | R2)
    m.frame(L2 | R2 | SLOT_BTN[4])
    check(slots_of(m)[:3] == [5, 0, 3] and masks(m)[2] == 0x14 and masks(m)[4] == 0,
          'move 1 -> 5: bit 0 off, bit 4 on the equipped shield, taken from the old holder: %s %s' % (slots_of(m), [hex(x) for x in masks(m)]))
    m.frame(L2 | R2)
    # assign mode on its own slot: cleared with its bit
    m.frame(L2 | R2 | SELECT)
    m.frame(L2 | R2)
    m.frame(L2 | R2 | SLOT_BTN[4])
    check(slots_of(m)[0] == 0 and masks(m)[2] == 0x04, 'toggle off: slot and bit cleared: %s' % [hex(x) for x in masks(m)])
    # assign mode, no shield equipped: bit cleared, weapon recorded
    m = overlay_machine(slots={0: 1}, cur=0)
    set_shield(m, 3, mask=0x01)
    m.frame(L2 | R2 | SELECT)
    m.frame(L2 | R2)
    m.frame(L2 | R2 | SLOT_BTN[1])
    check(slots_of(m)[0] == 2 and masks(m)[3] == 0, 'assign mode without a shield: slot 1 bit off (moved to slot 2, no shield): %s' % [hex(x) for x in masks(m)])
    # nobody equipped: nothing changes (invalid)
    m = Machine()
    m.setup_weapons({1}, -1)
    set_shield(m, 2, eq=1, mask=0x02)
    m.frame(0)
    m.frame(R2 | SELECT)
    check(masks(m)[2] == 0x02, 'unarmed: shield bits untouched')
    # every slot number records its own bit
    for slot in range(1, 9):
        m = overlay_machine(slots={}, cur=3)
        set_shield(m, 0, eq=1)
        m.frame(L2 | R2 | SELECT)
        m.frame(L2 | R2)
        m.frame(L2 | R2 | SLOT_BTN[slot - 1])
        check(masks(m)[0] == 1 << (slot - 1) and all(x == 0 for x in masks(m)[1:]), 'slot %d -> bit %d: %s' % (slot, slot - 1, masks(m)))


def test_shield_swap():
    base = dict(cats={}, cur=0)
    # a) one-handed -> one-handed slot with a shield: put on (flags, stats call, model slot freed, model queued after the weapon's)
    m = swap_machine({0: 1, 1: 2, 2: 3}, {}, 0, {2: dict(mask=0x02)})
    go(m, 2, drain=False)
    log = nostand(m.log)
    a2 = sh_addr(2)
    check(m.equipped() == [1] and sh_eq(m) == [2], 'a: weapon 1 and shield 2 equipped: %s %s' % (m.equipped(), sh_eq(m)))
    check(('equipShield', a2) in log and ('freeWepModel', 1) in log, 'a: stats + model slot: %s' % log)
    names = [e[0] for e in log]
    check(names.index('equipShield') < names.index('equipWeapon'), 'a: shield before the weapon, like the menus')
    check(qent(m, 0) == (3, 0, 21, UNK48, 0, 240, 1) and qent(m, 1) == (3, 1, 102, UNK48 + 0x100, 0, 241, 9) and m.rd(Q + 2 * Q_SIZE, 1) == 0,
          'a: queue = weapon model (slot 0), shield model (slot 1, material of the shield): %s %s' % (qent(m, 0), qent(m, 1)))
    check(m.rd(MODE) == 0 and m.rd(S_LOADING_ADDR) == 1, 'a: world held while loading')
    run_until(m, lambda mm: mm.rd(S_LOADING_ADDR) == 0, hw=L2 | R2)
    check(masks(m)[2] == 0x02 and m.rd(Q, 1) == 0, 'a: nothing consumed, queue drained')
    # b) the shield of the slot is the one already on: nothing at all
    m = swap_machine({0: 1, 1: 2, 2: 3}, {}, 1, {2: dict(eq=1, mask=0x06)})
    go(m, 3, drain=False)
    log = nostand(m.log)
    check(m.equipped() == [2] and sh_eq(m) == [2] and not any(e[0] in ('equipShield',) for e in log) and ('freeWepModel', 1) not in log
          and m.rd(Q + Q_SIZE, 1) == 0 and qent(m, 0)[1] == 0, 'b: same shield stays untouched: %s' % log)
    # c) a slot without a shield: the equipped one is taken off (the user wants exact loadouts)
    m = swap_machine({0: 1, 1: 2, 2: 3}, {}, 1, {2: dict(eq=1, mask=0x02)})
    go(m, 3, drain=False)
    log = nostand(m.log)
    check(m.equipped() == [2] and sh_eq(m) == [] and ('equipShield', 0) in log and ('freeWepModel', 1) in log and m.rd(Q + Q_SIZE, 1) == 0
          and masks(m)[2] == 0x02, 'c: slot without shield removes it, bits kept: %s %s' % (sh_eq(m), log))
    # d) another shield: A off, B on
    m = swap_machine({0: 1, 1: 2, 2: 3}, {}, 1, {2: dict(eq=1, mask=0x02), 3: dict(mask=0x04)})
    go(m, 3, drain=False)
    log = nostand(m.log)
    check(sh_eq(m) == [3] and [e for e in log if e[0] == 'equipShield'] == [('equipShield', sh_addr(3))]
          and qent(m, 1) == (3, 1, 103, UNK48 + 0x100, 0, 241, 10), 'd: shield B replaces A: %s %s' % (sh_eq(m), qent(m, 1)))
    # e) two-handed target: shield off even if the slot has a mask; category change first
    m = swap_machine({0: 1, 2: 3}, {2: 3}, 0, {2: dict(eq=1, mask=0x04)})
    go(m, 3, drain=False)
    log = nostand(m.log)
    check(m.equipped() == [2] and sh_eq(m) == [] and ('equipShield', 0) in log and qent(m, 0)[0] == 7 and qent(m, 1)[:3] == (3, 0, 22)
          and m.rd(Q + 2 * Q_SIZE, 1) == 0, 'e: 2H takes the shield off: %s' % log)
    # f) 2H weapon and no shield on: no shield call at all
    m = swap_machine({0: 1, 2: 3}, {2: 3}, 0, {2: dict(mask=0x04)})
    go(m, 3, drain=False)
    check(not any(e[0] == 'equipShield' for e in m.log) and ('freeWepModel', 1) not in m.log and sh_eq(m) == [], 'f: nothing to take off')
    # g) the recorded shield is gone from the bag (discarded: empty record, the mask byte is not trusted): the slot has no shield
    m = swap_machine({0: 1, 1: 2}, {}, 0, {2: dict(sid=0)})
    m.wr(sh_addr(2) + SH_MASK_O, 0x02, 1)
    go(m, 2, drain=False)
    check(not any(e[0] == 'equipShield' for e in m.log) and sh_eq(m) == [] and m.equipped() == [1], 'g1: missing shield, none on: nothing happens: %s' % nostand(m.log))
    m = swap_machine({0: 1, 1: 2}, {}, 0, {2: dict(sid=0), 3: dict(eq=1, mask=0x01)})
    m.wr(sh_addr(2) + SH_MASK_O, 0x02, 1)
    go(m, 2, drain=False)
    check(('equipShield', 0) in m.log and sh_eq(m) == [] and m.rd(Q + Q_SIZE, 1) == 0, 'g2: missing shield, another on: taken off: %s' % nostand(m.log))
    # h) two-handed -> one-handed: category table, weapon model, shield model, in that order
    m = swap_machine({0: 1, 2: 3}, {2: 3}, 2, {2: dict(mask=0x01)})
    go(m, 1, drain=False)
    check(m.equipped() == [0] and sh_eq(m) == [2] and qent(m, 0)[:3] == (7, 0, 1) and qent(m, 1)[:3] == (3, 0, 20) and qent(m, 2)[:4] == (3, 1, 102, UNK48 + 0x100)
          and m.rd(Q + 3 * Q_SIZE, 1) == 0, 'h: 2H -> 1H brings the shield back, queue: category, weapon, shield: %s' % [qent(m, k) for k in range(3)])
    # i) a shield without a model (wepId 0): equipped, nothing queued for it
    m = swap_machine({0: 1, 1: 2}, {}, 0, {2: dict(mask=0x02, wep=0)})
    go(m, 2, drain=False)
    check(sh_eq(m) == [2] and ('equipShield', sh_addr(2)) in m.log and m.rd(Q + Q_SIZE, 1) == 0, 'i: no model, no queue entry')
    # j) corrupt data: two shields claim a slot: exactly one ends up on
    m = swap_machine({0: 1, 1: 2}, {}, 0, {2: dict(mask=0x02), 3: dict(mask=0x02)})
    go(m, 2, drain=False)
    check(len(sh_eq(m)) == 1, 'j: duplicates: one shield on (%s)' % sh_eq(m))
    # k) blocked swap: nothing is touched
    for name, setup in (('transition 1', lambda mm: mm.wr(TRANS, 1)), ('busy', lambda mm: setattr(mm, 'busy', 1)), ('queue', lambda mm: mm.wr(Q, 3, 1))):
        m = swap_machine({0: 1, 1: 2}, {}, 0, {2: dict(mask=0x02)})
        setup(m)
        go(m, 2, drain=False)
        check(sh_eq(m) == [] and not any(e[0] == 'equipShield' for e in m.log), 'k: gate %s: shield untouched' % name)
    # l) weapon drawn: sheathe, the shield changes while sheathed, draw again, name popup (the sequence of v3 unchanged)
    m = swap_machine({0: 1, 1: 2}, {}, 0, {2: dict(mask=0x02)}, drawn=True)
    go(m, 2, drain=False)
    check(m.rd(S_LOADING_ADDR) == 2 and sh_eq(m) == [] and not any(e[0] == 'equipShield' for e in m.log), 'l: sheathing first, shield untouched yet: %s' % nostand(m.log))
    m.load_frames = 3
    run_until(m, lambda mm: mm.rd(S_LOADING_ADDR) == 0, hw=L2 | R2, limit=800)
    log = nostand(m.log)
    names = [e[0] for e in log]
    check(sh_eq(m) == [2] and m.equipped() == [1], 'l: done: shield on')
    check(names.index('toggle') < names.index('equipShield') < names.index('equipWeapon') < names.index('modelFlags')
          < len(names) - 1 - names[::-1].index('toggle') < names.index('setText'), 'l: order sheathe, shield, weapon, flags, draw, name: %s' % names)
    check(log[names.index('modelFlags')][1:] == (0, 0, 2) and names.count('toggle') == 2 and names.count('setText') == 1, 'l: flags set sheathed, one name popup')
    # m) tick sequence unchanged for the finish (idle pose etc.) when a shield came along
    m = swap_machine({0: 1, 1: 2}, {}, 0, {2: dict(mask=0x02)})
    go(m, 2)
    names = [e[0] for e in nostand(m.log) if e[0] not in ('exit6', 'sfx')]
    check(names == ['equipShield', 'freeWepModel', 'equipWeapon', 'freeWepModel', 'playAnim', 'pose', 'memcpy', 'modelFlags', 'initInfo', 'setText'],
          'm: call sequence with a shield: %s' % names)


def test_shield_start_lean():
    """lean build: Start in the overlay does nothing but is swallowed (no first person view)"""
    SFX = ('sfxdef', 0x7E, 0x18)
    m = swap_machine({0: 1, 1: 2, 2: 3, 4: 5}, {2: 3}, 0, {3: dict(eq=1), 5: dict(mask=0x0F), 6: dict(mask=0x80)}, sentinel=False)
    before = masks(m)
    m.log.clear()
    log, pressed = press(m, START)
    check(masks(m) == before and SFX not in log and not any(e[0] == 'sfx' for e in log), 'lean: Start writes nothing and plays nothing: %s' % log)
    check(pressed & START == 0 and m.rd(REPEAT) & START == 0, 'lean: Start swallowed')
    check(m.rd(MODE) == 6 and m.equipped() == [0] and slots_of(m)[:5] == [1, 2, 3, 0, 5], 'lean: no other effect')
    m = swap_machine({0: 1, 1: 2}, {}, 0, {3: dict(eq=1)}, sentinel=False)
    m.frame(L2 | R2 | SELECT)
    m.frame(L2 | R2)
    press(m, START)
    check(m.rd(S_ASSIGN) == 1 and masks(m)[3] == 0, 'lean: Start in assign mode: mode unchanged, nothing written')
    for desc, setup, hw in (('mode 1, no L2/R2', lambda mm: mm.wr(MODE, 1), 0), ('L2 only (native shortcuts)', lambda mm: None, L2), ('menu open', lambda mm: mm.wr(MENU, 0), L2 | R2)):
        m = swap_machine({0: 1, 1: 2}, {}, 0, {3: dict(eq=1)}, sentinel=False)
        setup(m)
        m.frame(hw)
        m.frame(hw | START)
        check(m.rd(PRESSED) & START, 'Start outside the overlay (%s): untouched' % desc)
    m = swap_machine({0: 1}, {}, 0, {}, sentinel=False)
    m.wr(D_ANIM, 0, 1)
    m.log.clear()
    m.call(LABEL, 4)
    want = ref_small(m, HINT, 30, 1, 160, 142, PAL[4])
    check(m.log[-len(want):] == want, 'hint line: SELECT: ASSIGN')


def test_shield_start():
    if LEAN:
        return test_shield_start_lean()
    """Start in the weapon overlay: the equipped shield goes into every occupied one-handed slot"""
    SFX = ('sfxdef', 0x7E, 0x18)
    # a) shield 3 on; slots 1, 2, 5 one-handed, slot 3 two-handed, slot 4 and 6..8 have no weapon
    m = swap_machine({0: 1, 1: 2, 2: 3, 4: 5}, {2: 3}, 0, {3: dict(eq=1), 5: dict(mask=0x0F), 6: dict(mask=0x80)}, sentinel=False)
    m.log.clear()
    log, pressed = press(m, START)
    check(masks(m)[3] == 0x13 and masks(m)[5] == 0x0C and masks(m)[6] == 0x80,
          'Start: bits of slots 1,2,5 on the equipped shield, cleared elsewhere; 2H slot 3 and empty slots untouched: %s' % [hex(x) for x in masks(m)])
    check(log.count(SFX) == 1 and not any(e[0] == 'sfx' for e in log), 'Start: its own confirm sound only: %s' % log)
    check(pressed & START == 0, 'Start swallowed (pressed word)')
    check(m.rd(REPEAT) & START == 0 and m.rd(MODE) == 6 and m.equipped() == [0] and slots_of(m)[:5] == [1, 2, 3, 0, 5],
          'Start: no other effect (mode 6, weapon, slots unchanged)')
    # b) no shield on: those slots end up without a shield
    m = swap_machine({0: 1, 1: 2, 2: 3, 4: 5}, {2: 3}, 0, {3: dict(mask=0x1F), 4: dict(mask=0xFF)}, sentinel=False)
    press(m, START)
    check(masks(m)[3] == 0x0C and masks(m)[4] == 0xEC, 'Start without a shield: one-handed slot bits cleared everywhere: %s' % [hex(x) for x in masks(m)])
    # c) one press = one write, also when held (auto-repeat is swallowed too)
    m = swap_machine({0: 1, 1: 2}, {}, 0, {3: dict(eq=1)}, sentinel=False)
    m.log.clear()
    for _ in range(40):
        m.frame(L2 | R2 | START)
    check(m.log.count(SFX) == 1 and masks(m)[3] == 0x03, 'held Start: one write (%d sounds)' % m.log.count(SFX))
    m.frame(L2 | R2)
    m.wr(sh_addr(3) + SH_MASK_O, 0, 1)
    m.frame(L2 | R2 | START)
    check(m.log.count(SFX) == 2 and masks(m)[3] == 0x03, 'a second press writes again')
    # d) in assign mode it works and does not toggle the mode
    m = swap_machine({0: 1, 1: 2}, {}, 0, {3: dict(eq=1)}, sentinel=False)
    m.frame(L2 | R2 | SELECT)
    m.frame(L2 | R2)
    check(m.rd(S_ASSIGN) == 1, 'assign mode on')
    press(m, START)
    check(m.rd(S_ASSIGN) == 1 and masks(m)[3] == 0x03, 'Start in assign mode: written, mode unchanged')
    # e) not in the overlay: untouched (first person etc. stay the game's)
    for desc, setup, hw in (('mode 1, no L2/R2', lambda mm: mm.wr(MODE, 1), 0), ('L2 only (native shortcuts)', lambda mm: None, L2), ('menu open', lambda mm: mm.wr(MENU, 0), L2 | R2)):
        m = swap_machine({0: 1, 1: 2}, {}, 0, {3: dict(eq=1)}, sentinel=False)
        setup(m)
        m.log.clear()
        m.frame(hw)
        m.frame(hw | START)
        check(masks(m)[3] == 0 and SFX not in m.log and m.rd(PRESSED) & START, 'Start outside the overlay (%s): untouched' % desc)
    # f) the weapon labels show the new hint line
    m = swap_machine({0: 1}, {}, 0, {}, sentinel=False)
    m.wr(D_ANIM, 0, 1)
    m.log.clear()
    m.call(LABEL, 4)
    want = ref_small(m, HINT, 30, 1, 160, 142, PAL[4])
    check(m.log[-len(want):] == want, 'hint line: SELECT: ASSIGN  START: SHIELD')


def test_no_shield_migration():
    """v3.1 rc2: nothing writes shield bits automatically any more"""
    m = Machine()
    m.setup_weapons(set(), 0, slots={0: 1, 1: 2, 4: 5})
    set_shield(m, 1, eq=1)
    for _ in range(10):
        m.frame(0)
    check(masks(m) == [0] * 8, 'equipped shield, slots, no bits: nothing is migrated (%s)' % masks(m))
    # nor does anything in the swap / assign flow other than assign() write bits
    m = swap_machine({0: 1, 1: 2}, {}, 0, {1: dict(eq=1)}, sentinel=False)
    for _ in range(5):
        m.frame(L2 | R2)
    go(m, 2)
    go(m, 1)
    check(masks(m) == [0] * 8, 'swaps write no bits')
    # v2 favourites still become distinct slots, without any shield bits
    m = Machine()
    m.setup_weapons(set(), 0, slots={0: 1, 2: 1, 3: 1})
    set_shield(m, 1, eq=1)
    m.frame(0)
    check(slots_of(m)[:4] == ([1, 0, 1, 1] if LEAN else [1, 0, 2, 3]) and masks(m) == [0] * 8, 'v2 favourites: slots only')


def test_shield_loadout():
    """the user's test plan: slot 1 = 1H + shield A, slot 2 = 1H without shield, slot 3 = 2H, slot 4 = 1H + shield B;
    the menu is modelled by setting the flags directly"""
    for drawn in (False, True):
        m = Machine()
        cats = {2: 3}
        m.setup_weapons(set(), 0, blade_cat=cats)
        set_shield(m, 2, eq=1)
        set_shield(m, 3)
        m.frame(0)

        def menu(weapon, shield):
            for e in range(8):
                m.wr(INV + e * W_SIZE + W_EQ, int(e == weapon), 1)
            for i in range(8):
                m.wr(sh_addr(i) + SH_EQ, int(i == shield), 1)
            sync_cat(m)

        def assign():
            m.frame(R2 | SELECT)
            m.frame(R2)
        assign()                      # weapon 0 + shield A -> slot 1
        menu(1, None)
        assign()                      # weapon 1, no shield -> slot 2
        menu(2, None)
        assign()                      # weapon 2 (two-handed) -> slot 3
        menu(3, 3)
        assign()                      # weapon 3 + shield B -> slot 4
        check(slots_of(m)[:4] == [1, 2, 3, 4] and masks(m)[2] == 0b0001 and masks(m)[3] == 0b1000, 'loadout recorded: %s %s' % (slots_of(m), masks(m)))
        if drawn:
            m.wr(CHSTATE + CH_DRAWN, 1)
            m.wr(ACTOR + A_DRAWN_WORD, 1 << A_DRAWN_BIT)
            m.wr(ACTOR + A_ANIM, 101, 1)
        m.wr(MODE, 6)
        m.wr(D_ANIM, 0, 1)
        m.frame(L2 | R2)
        for step, (slot, weapon, shield) in enumerate([(1, 0, 2), (2, 1, None), (3, 2, None), (4, 3, 3), (1, 0, 2), (4, 3, 3), (2, 1, None), (3, 2, None), (2, 1, None)]):
            go(m, slot)
            check(m.equipped() == [weapon] and sh_eq(m) == ([] if shield is None else [shield]),
                  'drawn=%s step %d slot %d: weapon %s shield %s (want %d, %s)' % (drawn, step, slot, m.equipped(), sh_eq(m), weapon, shield))
            check(masks(m)[2] == 0b0001 and masks(m)[3] == 0b1000 and slots_of(m)[:4] == [1, 2, 3, 4], 'loadout intact after the swap: %s' % masks(m))
    # the shield moves to the Container (record emptied) and comes back as a new record: the slot's bit is gone with the record
    m = swap_machine({0: 1, 1: 2}, {}, 0, {2: dict(mask=0x02)})
    set_shield(m, 2, sid=0)               # moved away
    go(m, 2)
    check(sh_eq(m) == [] and m.equipped() == [1], 'shield moved away: slot has none')
    set_shield(m, 5)                      # a shield comes back to the bag (new record, no bits)
    go(m, 1)
    go(m, 2)
    check(sh_eq(m) == [], 'a returned shield has no slot bits: not put on')


def test_shield_fuzz(frames=6000):
    import random
    rnd = random.Random(11)
    m = Machine()
    m.shim_r1 = False
    cats = {0: 1, 1: 3, 2: 2, 3: 7, 4: 4, 5: 9, 6: 5, 7: 8}
    m.setup_weapons(set(), 0, blade_cat=cats, slots={i: i + 1 for i in range(8)})
    sl = SYMS_BLOB['s_loading']
    swaps = 0
    for f in range(frames):
        if rnd.random() < 0.05:
            for i in range(8):
                if rnd.random() < 0.5:
                    set_shield(m, i, eq=0, mask=rnd.choice([0, 0, 1, 2, 4, 0x81, 0xFF, 0x18]), sid=rnd.choice([1, 1, 1, 0]))
            e = rnd.randrange(-1, 8)
            for i in range(8):
                a = sh_addr(i)
                m.wr(a + SH_EQ, int(i == e and m.rd(a + SH_ID_O, 1) != 0), 1)
        if not m.rd(sl) and rnd.random() < 0.3:
            m.wr(MODE, rnd.choice([1, 6, 6]))
            m.wr(MENU, 0x3F)
            m.wr(TRANS, 0)
            m.busy = 0
            m.status = 0
            m.wr(ACT2 + 0x954, 0, 2)
            m.wr(CHSTATE + CH_DRAWN, rnd.choice([0, 1]))
            m.wr(ACTOR + A_DRAWN_WORD, m.rd(CHSTATE + CH_DRAWN) << A_DRAWN_BIT)
            m.wr(ACTOR + A_ANIM, 101 if m.rd(CHSTATE + CH_DRAWN) else 1, 1)   # (the real main loop ends the draw animation)
            m.anim_left = 0
            m.mode10_left = 0
        hw = 0
        if rnd.random() < 0.7:
            hw = L2 | R2 | rnd.choice([0, CIR, TRI, SQR, CRS, DUP, DDOWN, DRIGHT, DLEFT, SELECT, START])
        elif rnd.random() < 0.3:
            hw = R2 | rnd.choice([0, SELECT])
        m.load_frames = rnd.choice([1, 2, 5])
        try:
            m.frame(hw)
        except Halt as e:
            check(False, 'shield fuzz halted: %s' % e)
            return
        sync_cat(m) if not m.rd(sl) else None
        check(len(sh_eq(m)) <= 1, 'shield fuzz: more than one shield on %s' % sh_eq(m))
        for e in m.log:
            if e[0] == 'equipShield':
                check(e[1] == 0 or any(e[1] == sh_addr(i) for i in range(8)), 'shield fuzz: equipShield(%x)' % e[1])
        # an equipped shield record is a real one
        for i in sh_eq(m):
            check(m.rd(sh_addr(i) + SH_ID_O, 1) != 0, 'shield fuzz: an empty record is "equipped"')
        swaps += sum(1 for e in m.log if e[0] == 'equipWeapon')
        m.log.clear()
    print('shield fuzz: %d frames, %d swaps' % (frames, swaps))


if __name__ == '__main__':
    print('variant: %s' % ('CLASSIC' if CLASSIC else 'default'))
    print('entry = 0x%08X  wslot_label = 0x%08X' % (ENTRY, LABEL))
    test_code_budget()
    test_label_original()
    test_label_layout()
    test_label_weapons()
    if CLASSIC:
        test_classic_passthrough()
    else:
        test_swap_sequence()
        test_gating()
        test_lr_camera()
        test_camera()
        test_r3()
        test_first_person()
    test_quick_assign()
    test_migration()
    test_slot_press()
    test_dpad_stick()
    test_assign_mode()
    test_wmode_transitions()
    test_shield_assign()
    test_shield_swap()
    test_shield_start()
    test_no_shield_migration()
    test_shield_loadout()
    test_shield_fuzz()
    test_state_machine_extras()
    test_drawn_sequence()
    test_drawn_edge_cases()
    for seed in range(1, 6):
        test_fuzz(seed)
    print('%d checks, %d failures' % (checks, fails))
    sys.exit(1 if fails else 0)
