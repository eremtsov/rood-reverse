/*
 * Personal mod: weapon slots (L2+R2 overlay), L1/R1 slot cycling and the camera on
 * the right stick.
 *
 * This unit is NOT part of the matching decompilation. It is compiled with the
 * BATTLE.PRG toolchain, linked by tools/mod/build_mod.sh and entered through a
 * patched `jal` in vs_battle_exec (the call to vs_main_processPadState). Its
 * functions live in the zero tail of BATTLE.PRG and in functions that nothing in
 * the game references (tools/mod/check_dead.py), see tools/mod/wswap.ld.
 *
 * Controls (field only, never while a menu is open):
 *   R1 / L1                  next / previous assigned weapon slot (slot order)
 *   L2 + R2 (held)           the L2 overlay shows the weapon of each of the 8 slots
 *   ... + slot button        equip that slot's weapon (Circle, Triangle, Square, Cross,
 *                            D-pad Up, Down, Right, Left = slots 1..8; the D-pad slots
 *                            only react to the physical D-pad, not to the left stick)
 *   ... + Select             assign mode on/off; the next slot button then puts the
 *                            equipped weapon into that slot (moves it, or clears the
 *                            slot if it already was there)
 *   R2 (held) + Select       put the equipped weapon into the first free slot / clear it
 *   right stick X            camera rotation: right = old L1, left = old R1
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
extern int func_800C9EB8(int);   /* L2 overlay: is this label available? */
extern void func_800C9F98(int xy, int id); /* L2 overlay: the small bullet */
extern u_char D_800EBCE8;        /* L2 overlay slide counter, 10 = hidden, 0 = fully in */
extern u_char D_800EB7B4[];      /* font: advance width per character, 4 bits each */
extern void vs_battle_playMenuChangeSfx(void);
extern void vs_battle_playMenuSelectSfx(void);
extern void vs_battle_playMenuLeaveSfx(void);
extern void vs_battle_playInvalidSfx(void);

/* constant data (asm, see the header comment) */
extern const u_char wl_lab[];        /* per overlay label id: x, y, bullet x, bullet y, width budget, slot */
extern const u_char wl_slotBit[];    /* slot 0..7 -> bit number in the button words */
extern const int wl_col[];           /* label colours, see wslot_label */
extern const char wl_dash[];         /* "--" in the game encoding: the empty slot */
extern const char wl_hint[];         /* "$SELECT: ASSIGN", followed by "$ASSIGN: PRESS A SLOT" */
/* wl_lab: positions of the game label sprites (tables at 0x800EBC98..0x800EBCDF in
 * BATTLE.PRG: bullets, labels, label widths) with the overlay fully slid in; the button
 * group (id 0..3) moves with +step, the D-pad group (id 4..7) with -step. Labels of odd
 * id end at x (the game draws them right-aligned against their button; here 2 px short).
 * The width budgets (pixels) keep neighbouring labels apart.
 * wl_col, as 0xBBGGRR: [0..2] empty / weapon / equipped, [3..5] the same in assign mode
 * (orange, equipped yellow), [6] hint, [7] assign prompt. */
__asm__(".section .wd1,\"a\",@progbits\n"
        ".globl wl_lab\nwl_lab:\n"
        ".byte 242,99,237,101,74,2, 214,113,213,115,54,3, 252,111,247,113,64,1, 223,125,223,127,100,4\n"
        ".byte 94,99,89,101,110,5, 82,112,70,115,76,8, 103,111,98,113,52,7, 81,124,80,127,75,6\n"
        ".text");
__asm__(".section .wd2,\"a\",@progbits\n"
        ".globl wl_slotBit\nwl_slotBit:\n.byte 5,4,7,6,12,14,13,15\n"
        ".globl wl_dash\nwl_dash:\n.byte 0xA7,0xA7,0xE7,0\n"
        ".globl wl_col\n.align 2\nwl_col:\n"
        ".word 0x404040,0x808080,0xF0F080,0x105096,0x188CFF,0x40E0FF,0x6E6E6E,0x188CFF\n"
        ".text");
__asm__(".section .wd3,\"a\",@progbits\n"
        ".globl wl_hint\nwl_hint:\n.asciz \"$SELECT: ASSIGN\"\n.asciz \"$ASSIGN: PRESS A SLOT\"\n"
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

/* mod state, lives in the blob's own zero-initialised data */
static int s_prev;    /* real buttons state of the previous frame */
static int s_cam;     /* camera stick latch: -1, 0, 1 */
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

/* Same sequence as the equip menu (MENU3.PRG _equipWeaponMenu + _loadObjectData),
 * applied to the real actor 0. The load queue is processed by the main loop. */
PLACE(".wswap2");
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
PLACE(".wE");
static int swapAllowed(void)
{
    return ((vs_battle_screenTransitionStep - 1) >= 2U)
        && (vs_battle_screenTransitionStep != 4) && !(func_800A0BE0(0) & 0x6000)
        && (vs_battle_characterState->unk3C->unk954 == 0) && (func_8009E4B0(0) == 0)
        && (vs_battle_objectDataSlots[0].dataType == 0);
}
UNPLACE();

/* sound, then sheathe first when the weapon is drawn, else swap at once */
PLACE(".wF");
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
PLACE(".wswap2");
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
PLACE(".wC");
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

/* the next assigned weapon after slot cur (0..9) in direction dir, not the equipped one */
static vs_main_inventoryWeapon* nextSlot(int cur, int dir)
{
    vs_main_inventoryWeapon* p;
    int j;

    for (j = 1; j <= 8; ++j) {
        p = inSlot(((cur - 1 + dir * j) & 7) + 1);
        if (p && !p->isEquipped) {
            return p;
        }
    }
    return NULL;
}

/* game encoding -> upper case ASCII, as many characters as fit into maxpx pixels */
PLACE(".wD");
static void nameToAscii(char* out, char const* name, int maxpx)
{
    int i;
    int c;
    int n = 0;

    for (i = 0; i < 24; ++i) {
        c = (u_char)name[i];
        if (c < 10) {
            c += '0';
        } else if (c < 0x24) {
            c += 'A' - 10;
        } else if (c < 0x3E) {
            c += 'A' - 0x24;
        } else if (c == 0xA7) {
            c = '-';
        } else if (c == 0xA0) {
            c = '.';
        } else if (c == 0xE7) {
            break;
        } else {
            c = ' ';
        }
        maxpx -= (D_800EB7B4[(c - 0x20) >> 1] >> (((c - 0x20) << 2) & 4)) & 0xF;
        if (maxpx < 0) {
            break;
        }
        out[n++] = c;
    }
    while ((n > 0) && (out[n - 1] == ' ')) {
        --n;
    }
    out[n] = 0;
}
UNPLACE();

/* the line under the overlay: what Select does */
PLACE(".wH");
static void drawHint(void)
{
    vs_battle_renderTextRawColor(
        wl_hint + s_assign * 16, 160 | (142 << 16), wl_col[6 + s_assign], NULL);
}
UNPLACE();

/* Replaces func_800C9EB8 at its two call sites in func_800C9FE8 (the L2 overlay):
 * called once per label, id 4..7 (D-pad group) then 0..3 (button group). Outside the
 * weapon mode it is the original. In weapon mode the label picture is not drawn
 * (return 0): the bullet and the weapon name are drawn here instead. */
PLACE(".wA");
int wslot_label(int id)
{
    char buf[32];
    char* p = buf;
    vs_main_inventoryWeapon* w;
    u_char const* t;
    int step;
    int ci;

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
    if (id & 1) {
        *p++ = '#'; /* right aligned: the label ends at x */
    }
    nameToAscii(p, w ? w->name : wl_dash, t[4]);
    ci = s_assign * 3;
    if (w) {
        ci += 1 + (w->isEquipped & 1);
    }
    vs_battle_renderTextRawColor(
        buf, ((t[0] + step) & 0xFFFF) | (t[1] << 16), wl_col[ci], NULL);
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

    vs_main_buttonsPreviousState = s_prev;
    ret = vs_main_processPadState();
    s_prev = vs_main_buttonsState;

    /* physical D-pad: the pad driver ORs the left stick into the D-pad bits (analog mode) */
    mask = ((~vs_main_padBuffer[0][2] & 0xF0) << 8) & vs_main_buttonsState;
    rawNew = mask & ~s_raw;
    s_raw = mask;

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
        mask |= PADj;
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
    vs_main_buttonsPreviousState = (s_prev & ~mask) | synth;

    return ret;
}
