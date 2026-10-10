/* Not part of the build: struct offsets used by tools/mod/test_wswap.py.
 * make CC1VER=2.8.1-psx build/src/mod/test_offsets.c.o */
#include "common.h"
#include "src/BATTLE/BATTLE.PRG/146C.h"
#include "src/BATTLE/BATTLE.PRG/2842C.h"
#include "src/BATTLE/BATTLE.PRG/30DB0.h"
#include "src/BATTLE/BATTLE.PRG/3A1A0.h"
#include "src/BATTLE/BATTLE.PRG/44F14.h"
#define OFF(t, f) ((int)&((t*)0)->f)
int offsets[] = {
    sizeof(vs_main_inventoryWeapon), OFF(vs_main_inventoryWeapon, blade), OFF(vs_main_inventoryWeapon, isEquipped), OFF(vs_main_inventoryWeapon, gems),
    sizeof(vs_main_inventoryShield), OFF(vs_main_inventoryShield, isEquipped),
    sizeof(vs_main_inventoryBlade), OFF(vs_main_inventoryBlade, category), OFF(vs_main_inventoryBlade, wepId), OFF(vs_main_inventoryBlade, material),
    OFF(vs_main_inventory_t, shields), OFF(vs_main_inventory_t, blades),
    sizeof(vs_battle_objectData), OFF(vs_battle_objectData, index), OFF(vs_battle_objectData, modelId), OFF(vs_battle_objectData, unk4),
    OFF(vs_battle_objectData, actorId), OFF(vs_battle_objectData, unk11), OFF(vs_battle_objectData, material),
    OFF(D_800F4538_t, unk5B1), OFF(D_800F4538_t, unk187C), OFF(D_800F4538_t, unkC54), OFF(D_800F4538_t, unk704),
    sizeof(D_800F4538_unkC54), OFF(D_800F4538_unkC54, unk540),
    OFF(vs_battle_actor, unk3C), OFF(vs_battle_actor, unk48), OFF(vs_battle_actor2, unk954),
    sizeof(vs_main_stickPos),
};
