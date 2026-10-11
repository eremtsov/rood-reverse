/*
 * Personal mod: weapon slots (L2+R2 overlay); in the default variant also L1/R1 slot
 * cycling, the camera on the right stick, no accidental first-person view and the
 * right stick looking around in first person.
 *
 * Two variants come from this one file (WSWAP_CLASSIC below, one line per branch):
 *   default  (branch wslots)         everything listed here
 *   classic  (branch wslots-classic) only the L2+R2 overlay, the slot buttons, the assign
 *                                    mode and R2+Select; every other input is the game's own
 *
 * This unit is NOT part of the matching decompilation. It is compiled with the
 * BATTLE.PRG toolchain, linked by tools/mod/build_mod.sh and entered through a
 * patched `jal` in vs_battle_exec (the call to vs_main_processPadState). Its
 * functions live in the zero tail of BATTLE.PRG and in functions that nothing in
 * the game references (tools/mod/check_dead.py), see tools/mod/wswap.ld.
 *
 * Controls (field only, never while a menu is open):
 *   R1 / L1                  next / previous assigned weapon slot (slot order)  [default]
 *   L2 + R2 (held)           the L2 overlay shows the weapon of each of the 8 slots
 *   ... + slot button        equip that slot's weapon (Circle, Triangle, Square, Cross,
 *                            D-pad Up, Down, Right, Left = slots 1..8; the D-pad slots
 *                            only react to the physical D-pad, not to the left stick)
 *   ... + Select             assign mode on/off; the next slot button then puts the
 *                            equipped weapon into that slot (moves it, or clears the
 *                            slot if it already was there)
 *   R2 (held) + Select       put the equipped weapon into the first free slot / clear it
 *   right stick X            camera rotation: right = old L1, left = old R1     [default]
 *   right stick Y            nothing in the field (the pad driver's fake R3 is dropped; the
 *                            real R3 button and Start still toggle first person) [default]
 *   first person             the right stick looks around like the left stick; up/down
 *                            (stick and D-pad) are inverted (decomp edit in func_8006EC7C) [default]
 *
 * A swap with the weapon drawn plays the game's own sheathe animation first
 * (func_800734C0, the field sheathe/draw toggle), waits until func_8009E4B0 says the actor is
 * no longer busy, swaps while the world is held (mode 0), then plays the draw animation.
 * With the weapon sheathed the swap is silent. When it is done the name of the
 * new weapon is shown for a moment in the information text box (box 7).
 *
 * Slot of a weapon: vs_main_inventory.weapons[i].gems[3] (unused byte), 1..8, 0 = none.
 * (The first version used 1 = "favourite" on any number of weapons; migrate() gives
 * those weapons distinct slots.)
 *
 * The two `jal func_800C9EB8` in the overlay drawing function func_800C9FE8 are
 * redirected to wslot_label, which returns the original answer unless s_wmode is set.
 *
 * Constant data lives in asm blocks (no compiler-generated .rdata): cc1 would switch
 * sections behind the back of the `.section` directives that place the functions.
 */
#include "common.h"
#include "src/BATTLE/BATTLE.PRG/146C.h"
#include "src/BATTLE/BATTLE.PRG/2842C.h"
#include "src/BATTLE/BATTLE.PRG/30DB0.h"
#include "src/BATTLE/BATTLE.PRG/3A1A0.h"
#include "src/BATTLE/BATTLE.PRG/44F14.h"
#include "src/BATTLE/BATTLE.PRG/4A0A8.h"
#include "src/BATTLE/BATTLE.PRG/5BF94.h"
#include <libetc.h>

extern u_int D_800F196C;
extern int vs_main_processPadState(void);
extern int func_8009E4B0(int);
extern void func_800734C0(void); /* toggle draw/sheathe (the field sheathe button) */
extern void func_80073554(void); /* leave the L2 shortcut mode (6) for the field (1) */
extern void func_8006EC7C(void); /* first person view: look around (D-pad, left stick) */
extern int func_800C9EB8(int);   /* L2 overlay: is this label available? */
extern void func_800C9F98(int xy, int id); /* L2 overlay: the small bullet */
extern u_char D_800EBCE8;        /* L2 overlay slide counter, 10 = hidden, 0 = fully in */
extern void vs_battle_playMenuChangeSfx(void);
extern void vs_battle_playMenuSelectSfx(void);
extern void vs_battle_playMenuLeaveSfx(void);
extern void vs_battle_playInvalidSfx(void);

#ifndef WSWAP_CLASSIC
#define WSWAP_CLASSIC 1 /* classic: the overlay and R2+Select only (set by the branch) */
#endif

/* The classic variant is small enough to keep swapAllowed, startSwap, drawHint and the hint strings
 * in the tail of BATTLE.PRG: the unreferenced functions .wE, .wF and .wH stay untouched there. */
#if WSWAP_CLASSIC
#define PLACE_T(sec) __asm__(".text")
#define SEC_WD3 ".rodata.wl3"
#else
#define PLACE_T(sec) __asm__(".section " sec ",\"ax\",@progbits")
#define SEC_WD3 ".wd3"
#endif

/* constant data (asm, see the header comment) */
extern const u_char wl_lab[];        /* per overlay label id: x, y, bullet x, bullet y, width budget, slot */
extern const u_char wl_slotBit[];    /* slot 0..7 -> bit number in the button words */
extern const u_char wl_pal[];        /* small-font palettes, see wslot_label */
extern const u_char wl_hint[];       /* "SELECT: ASSIGN", followed by "ASSIGN: PRESS A SLOT" (game encoding) */
/* wl_lab: positions of the game label sprites (tables at 0x800EBC98..0x800EBCDF in
 * BATTLE.PRG: bullets, labels, label widths) with the overlay fully slid in; the button
 * group (id 0..3) moves with +step, the D-pad group (id 4..7) with -step. Labels of odd
 * id end at x. Native labels are pictures at fixed positions; the mod's text is anchored to
 * the bullets instead: left-aligned (even id) starting at the picture's x, right-aligned (odd
 * id) ending at about the bullet. Fields: x, y of the text, x, y of the bullet, the budget in
 * characters (6 px each), the slot. The budgets are as long as the screen allows (>= 4 px
 * from the screen edge, from any other label, glyph or bullet; text rows [y+1, y+10)):
 *   Triangle 12, Square 17, Circle 10, Cross 19, Up 21, Left 11, Right 17, Down 12.
 * Square is raised 5 px and D-pad Right lowered 6 px (Cross 1 px) so that the centre labels
 * Up, Square, Right and Cross no longer share a text row; the Left label ends at its bullet
 * (the native Left picture ends 14 px behind it). tools/mod/test_wswap.py recomputes all of it.
 * wl_pal: palettes of the game's small font (VRAM clut row y=222, x = 832 + 16 * n):
 * 4 white, 5 yellow, 6 red-orange, 7 dim slate. [0..1] = weapon / equipped, [2..3] the same
 * in assign mode, [4] hint, [5] assign prompt. */
__asm__(".section .wd1,\"a\",@progbits\n"
        ".globl wl_lab\nwl_lab:\n"
        ".byte 242,99,237,101,12,2, 214,108,213,115,17,3, 252,111,247,113,10,1, 223,126,223,127,19,4\n"
        ".byte 94,99,89,101,21,5, 71,112,70,115,11,8, 103,117,98,113,17,7, 81,124,80,127,12,6\n"
        ".text");
__asm__(".section .wd2,\"a\",@progbits\n"
        ".globl wl_slotBit\nwl_slotBit:\n.byte 5,4,7,6,12,14,13,15\n"
        ".globl wl_pal\nwl_pal:\n.byte 4,5,6,5,7,6\n"
        ".text");
/* game encoding: A..Z = 10..35, ':' = 0x9E, ' ' = 0x8F, terminator 0xE7 */
__asm__(".section " SEC_WD3 ",\"a\",@progbits\n"
        ".globl wl_hint\nwl_hint:\n"
        ".byte 28,14,21,14,12,29,0x9E,0x8F,10,28,28,18,16,23,0xE7,0\n"
        ".byte 10,28,28,18,16,23,0x9E,0x8F,25,27,14,28,28,0x8F,10,0x8F,28,21,24,29,0xE7\n"
        ".text");

#define MSG_TICKS 150   /* how long the name stays up (1/60 s units, like the game's) */
#define SHEATHE_TIMEOUT 90
#ifndef WSWAP_ANIM
#define WSWAP_ANIM 1
#endif

/* where each piece of code goes: the tail of BATTLE.PRG (default .text) or one of the
 * unreferenced functions (see tools/mod/wswap.ld) */
#define PLACE(sec) __asm__(".section " sec ",\"ax\",@progbits")
#define UNPLACE() __asm__(".text")
/* Which unreferenced function range holds what (tools/mod/wswap.ld); the classic variant uses fewer. */
#if WSWAP_CLASSIC
#define PLACE_BEGIN() PLACE(".wswap2")   /* beginSwap, inSlot */
#define PLACE_INSLOT() PLACE(".wswap2")
#define PLACE_LABEL() PLACE(".wA")       /* wslot_label */
#define PLACE_START() UNPLACE()          /* startSwap: tail */
#else
#define PLACE_LABEL() PLACE(".wswap2")   /* wslot_label, startSwap */
#define PLACE_START() PLACE(".wswap2")
#define PLACE_BEGIN() PLACE(".wA")       /* beginSwap */
#define PLACE_INSLOT() PLACE(".wY")      /* inSlot: func_800A1B28 */
#endif

/* mod state, lives in the blob's own zero-initialised data */
#if !WSWAP_CLASSIC
static int s_prev;    /* real buttons state of the previous frame */
static int s_cam;     /* camera stick latch: -1, 0, 1 */
static int s_r3;      /* real R3 button (PADj position) of the previous frame */
#endif
static int s_loading; /* swap state machine: 0 idle, 1 waiting for the load queue, 2 sheathing */
#if WSWAP_ANIM
static int s_redraw;  /* draw the weapon again when the swap is done */
static int s_wait;    /* frames left to wait for the sheathe animation */
#endif
static int s_msg;     /* ticks left for the weapon name box, 0 = not ours */
static vs_main_inventoryWeapon* s_w; /* weapon being swapped to */
static int s_wmode;   /* 1: the L2 overlay shows weapons instead of shortcuts */
static int s_assign;  /* 1: the next slot button assigns the equipped weapon */
static int s_raw;     /* physical D-pad bits (12..15) of the previous frame */

/* index of the equipped weapon slot, or -1 */
static int equippedSlot(void)
{
    vs_main_inventoryWeapon* w = vs_main_inventory.weapons;
    int i;
    int cur = -1;

    for (i = 0; i < 8; ++i) {
        if (w[i].isEquipped && w[i].blade) {
            cur = i;
        }
    }
    return cur;
}
UNPLACE();

/* Same sequence as the equip menu (MENU3.PRG _equipWeaponMenu + _loadObjectData),
 * applied to the real actor 0. The load queue is processed by the main loop. */
PLACE_BEGIN();
static void beginSwap(vs_main_inventoryWeapon* w)
{
    vs_main_inventoryBlade* b = &vs_main_inventory.blades[w->blade - 1];
    vs_battle_objectData* q = vs_battle_objectDataSlots;
    int i;
    int cat = b->category;
    int wep = b->wepId;

    for (i = 0; i < 8; ++i) {
        vs_main_inventory.weapons[i].isEquipped = 0;
    }
    w->isEquipped = 1;

    /* two-handed categories (vs_mainMenu_weaponHands) drop the shield */
    if ((0x1D4 >> (cat - 1)) & 1) {
        vs_battle_equipShield(NULL);
        for (i = 0; i < 8; ++i) {
            vs_main_inventory.shields[i].isEquipped = 0;
        }
        func_8009AA84(1);
    }

    vs_battle_equipWeapon(w);

    if (D_800F4538[0]->unk5B1 != cat) {
        func_8009CC20(0, 0);
        q->dataType = 7;
        q->index = 0;
        q->modelId = cat;
        q->actorId = 0;
        ++q;
    }

    func_8009AA84(0);

    if (wep) {
        i = wep >= 96;
        q->dataType = 3;
        q->index = i;
        q->modelId = wep;
        q->unk4 = vs_battle_characterState->unk48[i];
        q->actorId = 0;
        q->unk11 = 240 + i;
        q->material = b->material;
    }

    s_w = w;
    D_800F196C = 0; /* freeze the world like the menu does (case 0 does nothing) */
    s_loading = 1;
}
UNPLACE();

/* the same safety conditions the swap has always had */
PLACE_T(".wE");
static int swapAllowed(void)
{
    return ((vs_battle_screenTransitionStep - 1) >= 2U)
        && (vs_battle_screenTransitionStep != 4) && !(func_800A0BE0(0) & 0x6000)
        && (vs_battle_characterState->unk3C->unk954 == 0) && (func_8009E4B0(0) == 0)
        && (vs_battle_objectDataSlots[0].dataType == 0);
}
UNPLACE();

/* sound, then sheathe first when the weapon is drawn, else swap at once */
PLACE_START();
static void startSwap(vs_main_inventoryWeapon* t)
{
    vs_battle_playMenuChangeSfx();
#if WSWAP_ANIM
    s_redraw = vs_battle_characterState->weaponDrawn & 1;
    if (s_redraw) {
        /* drawn: sheathe first, with the game's own animation */
        func_800734C0();
        D_800F196C = 0;
        s_w = t;
        s_wait = SHEATHE_TIMEOUT;
        s_loading = 2;
    } else
#endif
    {
        beginSwap(t);
    }
}
UNPLACE();

/* weapon whose slot is n (1..8), or NULL */
PLACE_INSLOT();
static vs_main_inventoryWeapon* inSlot(int n)
{
    vs_main_inventoryWeapon* w = vs_main_inventory.weapons;
    int i;

    for (i = 0; i < 8; ++i) {
        if (w[i].blade && (w[i].gems[3] == n)) {
            return &w[i];
        }
    }
    return NULL;
}
UNPLACE();

/* Every weapon must have its own slot. Version 2 marked any number of favourites
 * with 1: the first keeps slot 1, the others get the lowest free slots in inventory
 * order. Values above 8 are garbage. Idempotent, runs every field frame. */
static void migrate(void)
{
    vs_main_inventoryWeapon* w = vs_main_inventory.weapons;
    int i;
    int g;
    int k;

    for (i = 0; i < 8; ++i) {
        g = w[i].gems[3];
        if (g > 8) {
            w[i].gems[3] = 0;
        } else if (g && w[i].blade && (inSlot(g) != &w[i])) {
            /* an earlier weapon holds this slot */
            for (k = 1; inSlot(k); ++k) { }
            w[i].gems[3] = k;
        }
    }
}

/* Put the equipped weapon into slot n; the weapon sitting there loses it. If the
 * equipped weapon already is in slot n, the slot is cleared. n == 0: its own slot
 * (clear) or else the first free one. Returns 1 when something changed. */
PLACE(".wD");
static int assign(int n)
{
    vs_main_inventoryWeapon* w = vs_main_inventory.weapons;
    vs_main_inventoryWeapon* e;
    vs_main_inventoryWeapon* o;
    int cur = equippedSlot();

    if (cur < 0) {
        vs_battle_playInvalidSfx();
        return 0;
    }
    e = &w[cur];
    if (n == 0) {
        n = e->gems[3];
        if (n == 0) {
            for (n = 1; (n < 9) && inSlot(n); ++n) { }
            if (n == 9) {
                vs_battle_playInvalidSfx();
                return 0;
            }
        }
    }
    if (e->gems[3] == n) {
        e->gems[3] = 0;
        vs_battle_playMenuLeaveSfx();
        return 1;
    }
    o = inSlot(n);
    if (o != NULL) {
        o->gems[3] = 0;
    }
    e->gems[3] = n;
    vs_battle_playMenuSelectSfx();
    return 1;
}
UNPLACE();

#if !WSWAP_CLASSIC
/* the next assigned weapon after slot cur (0..9) in direction dir, not the equipped one */
PLACE(".wX"); /* func_80099FA8 */
static vs_main_inventoryWeapon* nextSlot(int cur, int dir)
{
    vs_main_inventoryWeapon* p;
    int j;

    for (j = 8; j != 0; --j) {
        cur = ((cur - 1 + dir) & 7) + 1;
        p = inSlot(cur);
        if (p && !p->isEquipped) {
            return p;
        }
    }
    return NULL;
}
UNPLACE();
#endif

/* Text in the game's small font (the menu item font: font table 0, glyph cells in VRAM whenever the
 * field runs). s is in the game encoding; at most max characters are drawn, 6 px each (every glyph of
 * the font is 6 px wide; the odd 12 px symbols do not occur in names). flags: bits 0-2 alignment of
 * x (0 left, 3 centre, 6 right: the text ends at x; the value is the pixels per character that the
 * start moves left), bits 3.. the font palette.
 * Blanks: names are terminated by 0xE7 and separate their words with `0xFA n` (vs_char_spacing,
 * n = 6 in all names, the width of a space); prose uses the space glyph 0x8F. Both are drawn as one
 * 0x8F (the font routine draws nothing for it and advances 6 px), which the raw-text font gets wrong
 * in the field. Trailing blanks are dropped. The sprites are linked at vs_scratch.unk8, like
 * vs_battle_renderTextRaw does. */
PLACE(".wC");
static void drawSmall(u_char const* s, int xy, int max, int flags)
{
    u_char const* e = s;
    int n = 0; /* characters that fit */
    int k = 0; /* characters up to the last visible one */
    int x = (short)xy;
    int c;

    while ((n < max) && ((c = *e) != 0xE7)) {
        ++n;
        e += 1 + (c == 0xFA);
        if ((c != 0xFA) && (c != 0x8F)) {
            k = n;
        }
    }
    x -= k * (flags & 7);
    vs_battle_setFontStyle(flags >> 3);
    for (; k != 0; --k) {
        c = *s;
        if (c == 0xFA) {
            c = 0x8F;
            ++s;
        }
        ++s;
        x = vs_battle_printVariableWidthFontChar(
            c, x, (xy >> 16) - 1, (u_long*)((char*)vs_scratch.unk8 - 12));
    }
}
UNPLACE();

/* the line under the overlay: what Select does */
PLACE_T(".wH");
static void drawHint(void)
{
    drawSmall(wl_hint + s_assign * 16, 160 | (142 << 16), 30, 3 | (wl_pal[4 + s_assign] << 3));
}
UNPLACE();

/* Replaces func_800C9EB8 at its two call sites in func_800C9FE8 (the L2 overlay):
 * called once per label, id 4..7 (D-pad group) then 0..3 (button group). Outside the
 * weapon mode it is the original. In weapon mode the label picture is not drawn
 * (return 0): the bullet and the weapon name are drawn here instead. */
PLACE_LABEL();
int wslot_label(int id)
{
    vs_main_inventoryWeapon* w;
    u_char const* t;
    int step;

    if (!s_wmode) {
        return func_800C9EB8(id);
    }
    t = &wl_lab[id * 6];
    w = inSlot(t[5]);
    step = (u_char)vs_battle_rowAnimationSteps[D_800EBCE8];
    if (id >= 4) {
        step = -step;
    }
    func_800C9F98(((t[2] + step) & 0xFFFF) | (t[3] << 16), w ? 0x180 : 0x140);
    if (w) { /* an empty slot shows the bullet only */
        /* odd id: right aligned, the label ends at x */
        drawSmall((u_char*)w->name, ((t[0] + step) & 0xFFFF) | (t[1] << 16), t[4],
            ((id & 1) * 6) | (wl_pal[s_assign * 2 + (w->isEquipped & 1)] << 3));
    }
    if ((id == 4) && (D_800EBCE8 == 0)) {
        drawHint();
    }
    return 0;
}
UNPLACE();

/* L2+R2 held in the shortcut mode (6): Select toggles the assign mode, a slot button
 * assigns or equips. rawNew: D-pad buttons that went down this frame (physical only).
 * All shortcut buttons are hidden from the game's own handler while L2+R2 are held. */
PLACE(".wB");
static void slotMode(int rawNew)
{
    int pressed = vs_main_buttonsPressed.all;
    int ev = (pressed & 0xF0) | rawNew;
    int k;
    vs_main_inventoryWeapon* t;

    vs_main_buttonsPressed.all &= ~(0xF0F0 | PADselect);
    vs_main_buttonRepeat &= ~(0xF0F0 | PADselect);
    if (pressed & PADselect) {
        s_assign ^= 1;
        if (s_assign) {
            vs_battle_playMenuSelectSfx();
        } else {
            vs_battle_playMenuLeaveSfx();
        }
        return;
    }
    for (k = 0; k < 8; ++k) {
        if ((ev >> wl_slotBit[k]) & 1) {
            break;
        }
    }
    if (k == 8) {
        return;
    }
    ++k;
    if (s_assign) {
        if (assign(k)) {
            s_assign = 0;
        }
        return;
    }
    t = inSlot(k);
    if ((t == NULL) || t->isEquipped || !swapAllowed()) {
        vs_battle_playInvalidSfx();
        return;
    }
    func_80073554(); /* the game's own way out of the shortcut mode */
    startSwap(t);
}
UNPLACE();

#if !WSWAP_CLASSIC
/* First-person view (func_8006EC7C, called from vs_battle_exec at 0x8007A10C in game mode 7):
 * the right stick looks around as well, at the speed of the left stick, up/down inverted like
 * the edited left stick/D-pad code of the original. The original then clamps the pitch. */
PLACE(".wF"); /* func_800733F8 */
void wfp_look(void)
{
    portInfo_t* p = _portInfo;
    int prev = vs_main_buttonsPreviousState;
    int x = p->rStickX; /* decomp rStick = physical left stick: the one the original reads */
    int y = p->rStickY;

    func_8006EC7C(); /* D-pad and left stick, as in the game */
    /* the same update once more with the right stick (decomp lStick) in the left stick's place and
     * without the D-pad (it has been applied), so that both sticks add up, same speed and dead zone */
    p->rStickX = p->lStickX;
    p->rStickY = p->lStickY;
    vs_main_buttonsPreviousState = prev & ~(PADLup | PADLright | PADLdown | PADLleft);
    func_8006EC7C();
    p->rStickX = x;
    p->rStickY = y;
    vs_main_buttonsPreviousState = prev;
}
UNPLACE();
#endif

int wswap_entry(void)
{
    int ret;
    int pressed;
    int mask;
    int synth;
    int dx;
    int cur;
    int dir;
    int rawNew;
    int mode;
    int both;
    vs_main_inventoryWeapon* w;
    D_800F4538_t* a;
    vs_battle_textBox* box;

#if !WSWAP_CLASSIC
    vs_main_buttonsPreviousState = s_prev;
#endif
    ret = vs_main_processPadState();
#if !WSWAP_CLASSIC
    s_prev = vs_main_buttonsState;
#endif

    /* physical D-pad: the pad driver ORs the left stick into the D-pad bits (analog mode) */
    mask = ((~vs_main_padBuffer[0][2] & 0xF0) << 8) & vs_main_buttonsState;
    rawNew = mask & ~s_raw;
    s_raw = mask;

#if !WSWAP_CLASSIC
    /* PADj (R3): the pad driver also sets it when the right stick is pushed far in any direction
     * (first person view by accident). In the field only the real R3 button counts, taken from
     * the raw pad word (byte 2, bit 2, active low), with its own press edge. */
    dx = (~vs_main_padBuffer[0][2] & 4) << 8;
    if ((vs_battle_menuState.currentMenu & 0x3F) == 0x3F) {
        pressed = dx & ~s_r3;
        vs_main_buttonsState = (vs_main_buttonsState & ~PADj) | dx;
        vs_main_buttonsPressed.all = (vs_main_buttonsPressed.all & ~PADj) | pressed;
        vs_main_buttonRepeat = (vs_main_buttonRepeat & ~PADj) | pressed;
        vs_main_buttonsPreviousState = (vs_main_buttonsPreviousState & ~PADj) | dx;
    }
    s_r3 = dx;
#endif

    /* weapon name box: ours only while box 7 still points at an inventory name */
    if (s_msg) {
        box = &vs_battle_textBoxes[7];
        if ((u_int)(box->string - (char*)vs_main_inventory.weapons) >= 8 * 0x20) {
            s_msg = 0; /* the game took the box over */
        } else if (((vs_battle_menuState.currentMenu & 0x3F) != 0x3F)
                   || ((s_msg -= vs_gametime_tickspeed) <= 0)) {
            vs_battle_dismissTextBox(7);
            s_msg = 0;
        }
    }

    if (s_loading) {
        a = D_800F4538[0];
#if WSWAP_ANIM
        if (D_800F196C == 0) {
            func_800B64A8(0, 0, 0); /* stand still, as the game does while (un)sheathing */
        } else if (s_loading == 2) {
            s_loading = 0; /* something else took over the world: give up */
            return ret;
        }
        if (s_loading == 2) {
            if ((func_8009E4B0(0) == 0) || (--s_wait <= 0)) {
                beginSwap(s_w);
            }
            return ret;
        }
#endif
        if (vs_battle_objectDataSlots[0].dataType != 0) {
            return ret;
        }
        /* queue drained: restart the idle animation on the (possibly new)
         * category animation table and refresh the pose and the model flags,
         * as func_800FA2CC does after the menu changed the weapon */
        a->unk187C = 0;
        func_800A0204(0, 1, 0, 0);
        func_800AFA28(a, &a->unkC54, 1);
        vs_main_memcpy(&a->unk704, &a->unkC54, sizeof a->unk704);
        a->unkC54.unk540 = 0;
        func_8009D934(0, a->unk0.weaponDrawn, 2);
        if (D_800F196C == 0) {
#if WSWAP_ANIM
            if (s_redraw) {
                func_800734C0(); /* draw animation of the new weapon, mode 10 */
            } else
#endif
            {
                D_800F196C = 1;
            }
            box = &vs_battle_textBoxes[7];
            if ((box->state == 0) || s_msg) {
                vs_battle_initInformationTextBox(informationTextBoxHeaderNone);
                vs_battle_setTextBox(7, s_w->name);
                s_msg = MSG_TICKS;
            }
        }
        s_loading = 0;
    }

    /* L2+R2: the overlay shows weapons. The mode stays on until the overlay is hidden
     * again, so that the game's own labels do not flash while it slides out. */
    mode = D_800F196C;
    both = (vs_main_buttonsState & (PADL2 | PADR2)) == (PADL2 | PADR2);
    if (both) {
        if (((vs_battle_menuState.currentMenu & 0x3F) == 0x3F) && ((mode == 1) || (mode == 6))) {
            s_wmode = 1;
        }
    } else {
        s_assign = 0;
        if ((vs_main_buttonsState & PADL2) || (D_800EBCE8 == 10)) {
            s_wmode = 0;
        }
    }

    if ((vs_battle_menuState.currentMenu & 0x3F) != 0x3F) {
        return ret;
    }
    migrate();
    if (mode == 6) {
        if (both) {
            slotMode(rawNew);
        }
        return ret;
    }
#if WSWAP_CLASSIC
    /* classic: R2 + Select is the only extra input outside the overlay; L1/R1, the sticks and
     * everything else stay exactly as the game handles them */
    if ((mode == 1) && (vs_main_buttonsState & PADR2)
        && (vs_main_buttonsPressed.all & PADselect)) {
        if (equippedSlot() >= 0) {
            assign(0);
        }
        vs_main_buttonsPressed.all &= ~PADselect;
        vs_main_buttonRepeat &= ~PADselect;
    }
    return ret;
#else
    if ((u_int)(mode - 1) >= 3) {
        return ret;
    }

    dx = vs_main_stickPosBuf.lStickX - 128;
    if (dx > 64) {
        s_cam = 1;
    } else if (dx < -64) {
        s_cam = -1;
    } else if ((u_int)(dx + 40) < 80) {
        s_cam = 0;
    }

    pressed = vs_main_buttonsPressed.all;
    mask = PADL1 | PADR1;
    synth = 0;
    if (s_cam) {
        synth = (s_cam > 0) ? PADL1 : PADR1;
    }

    if (mode == 1) {
        cur = equippedSlot();
        w = vs_main_inventory.weapons;

        if ((vs_main_buttonsState & PADR2) && (pressed & PADselect)) {
            if (cur >= 0) {
                assign(0);
            }
            vs_main_buttonsPressed.all &= ~PADselect;
            vs_main_buttonRepeat &= ~PADselect;
        } else if ((pressed & (PADL1 | PADR1)) && swapAllowed()) {
            dir = (pressed & PADR1) ? 1 : -1;
            cur = (cur >= 0) ? w[cur].gems[3] : 0;
            if (cur == 0) {
                cur = (dir > 0) ? 0 : 9;
            }
            w = nextSlot(cur, dir);
            if (w == NULL) {
                vs_battle_playInvalidSfx();
            } else {
                startSwap(w);
            }
        }
    }

    vs_main_buttonsPressed.all &= ~mask;
    vs_main_buttonRepeat &= ~mask;
    vs_main_buttonsState &= ~mask;
    vs_main_buttonsPreviousState = (vs_main_buttonsPreviousState & ~mask) | synth;

    return ret;
#endif
}
