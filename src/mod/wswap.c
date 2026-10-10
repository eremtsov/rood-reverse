/*
 * Personal mod: favourite-weapon quick swap on L1/R1 + camera on the right stick.
 *
 * This unit is NOT part of the matching decompilation. It is compiled with the
 * BATTLE.PRG toolchain, linked by tools/mod/build_mod.sh and entered through a
 * patched `jal` in vs_battle_exec (the call to vs_main_processPadState).
 *
 * Controls (field only, never while a menu is open):
 *   R1 / L1            next / previous favourite weapon (cycle, slot order)
 *   R2 (held) + Select toggle favourite mark on the equipped weapon
 *   right stick X      camera rotation: right = old L1, left = old R1
 *
 * A swap with the weapon drawn plays the game's own sheathe animation first
 * (func_800734C0, the field sheathe/draw toggle), waits until func_8009E4B0 says the actor is
 * no longer busy, swaps while the world is held (mode 0), then plays the draw animation.
 * With the weapon sheathed the swap is silent. When it is done the name of the
 * new weapon is shown for a moment in the information text box (box 7).
 *
 * Favourite mark: vs_main_inventory.weapons[i].gems[3] == 1 (unused byte).
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
extern void vs_battle_playMenuChangeSfx(void);
extern void vs_battle_playMenuSelectSfx(void);
extern void vs_battle_playMenuLeaveSfx(void);
extern void vs_battle_playInvalidSfx(void);

#define MSG_TICKS 150   /* how long the name stays up (1/60 s units, like the game's) */
#define SHEATHE_TIMEOUT 90
#ifndef WSWAP_ANIM
#define WSWAP_ANIM 1
#endif

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
__asm__(".section .wswap2,\"ax\",@progbits");
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
__asm__(".text");

int wswap_entry(void)
{
    int ret;
    int pressed;
    int mask;
    int synth;
    int dx;
    int cur;
    int dir;
    int k;
    int j;
    int s;
    vs_main_inventoryWeapon* w;
    D_800F4538_t* a;
    vs_battle_textBox* box;

    vs_main_buttonsPreviousState = s_prev;
    ret = vs_main_processPadState();
    s_prev = vs_main_buttonsState;

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

    if (((vs_battle_menuState.currentMenu & 0x3F) != 0x3F)
        || ((u_int)(D_800F196C - 1) >= 3)) {
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

    if (D_800F196C == 1) {
        cur = equippedSlot();
        w = vs_main_inventory.weapons;

        if ((vs_main_buttonsState & PADR2) && (pressed & PADselect)) {
            if (cur >= 0) {
                if (w[cur].gems[3] == 1) {
                    w[cur].gems[3] = 0;
                    vs_battle_playMenuLeaveSfx();
                } else {
                    w[cur].gems[3] = 1;
                    vs_battle_playMenuSelectSfx();
                }
            }
            vs_main_buttonsPressed.all &= ~PADselect;
            vs_main_buttonRepeat &= ~PADselect;
        } else if ((pressed & (PADL1 | PADR1))
                   && ((vs_battle_screenTransitionStep - 1) >= 2U)
                   && (vs_battle_screenTransitionStep != 4)
                   && !(func_800A0BE0(0) & 0x6000)
                   && (vs_battle_characterState->unk3C->unk954 == 0)
                   && (func_8009E4B0(0) == 0)
                   && (vs_battle_objectDataSlots[0].dataType == 0)) {
            dir = (pressed & PADR1) ? 1 : -1;
            k = cur;
            if (cur < 0) {
                k = (dir > 0) ? 7 : 0;
            }
            s = -1;
            for (j = 1; j <= 8; ++j) {
                int t = (k + dir * j) & 7;
                if (t == cur) {
                    break;
                }
                if (w[t].blade && (w[t].gems[3] == 1)) {
                    s = t;
                    break;
                }
            }
            if (s < 0) {
                vs_battle_playInvalidSfx();
            } else {
                vs_battle_playMenuChangeSfx();
#if WSWAP_ANIM
                s_redraw = vs_battle_characterState->weaponDrawn & 1;
                if (s_redraw) {
                    /* drawn: sheathe first, with the game's own animation */
                    func_800734C0();
                    D_800F196C = 0;
                    s_w = &w[s];
                    s_wait = SHEATHE_TIMEOUT;
                    s_loading = 2;
                } else
#endif
                {
                    beginSwap(&w[s]);
                }
            }
        }
    }

    vs_main_buttonsPressed.all &= ~mask;
    vs_main_buttonRepeat &= ~mask;
    vs_main_buttonsState &= ~mask;
    vs_main_buttonsPreviousState = (s_prev & ~mask) | synth;

    return ret;
}
