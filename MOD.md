# Vagrant Story QoL mod

A small quality-of-life mod for **Vagrant Story (USA, SLUS-01040)**, built on the
[rood-reverse](https://github.com/ser-pounce/rood-reverse) decompilation. It was made
for my own play in an emulator. It is not part of rood-reverse and is not intended for
upstream.

It comes in two variants. Both have the same weapon quick swap and right-stick camera.
They differ only in the button layout:

| Variant | Button layout | Branch | Patch file |
|---|---|---|---|
| **Default** | western confirm/cancel (Cross confirms, Circle cancels) and mirrored field buttons | `qol-mod` | `Vagrant Story (USA) - QoL mod v2.xdelta` |
| **Classic buttons** | the original layout (Circle confirms, Cross cancels, original field buttons) | `qol-mod-classic` | `Vagrant Story (USA) - QoL mod v2 (classic buttons).xdelta` |

## What it changes

### Both variants

**Weapon slots.** Eight weapon slots, numbered like the L2 shortcuts: 1 Circle,
2 Triangle, 3 Square, 4 Cross, 5 D-pad Up, 6 Down, 7 Right, 8 Left. A slot holds one
weapon; a weapon sits in at most one slot.

- **Hold L2 + R2** in the field: the L2 shortcut overlay slides in, but each of its eight
  positions shows the name of the weapon in that slot (`--` for an empty slot, the
  equipped weapon highlighted). **Press a slot button** to equip that weapon: Ashley
  sheathes and draws it with the game's own animations and the weapon's name pops up.
  Slots 5 to 8 only react to the physical D-pad, never to the left stick.
- **Select** (while holding L2 + R2): assign mode. A hint line at the bottom shows
  `SELECT: ASSIGN`; after the press the labels turn orange and it reads
  `ASSIGN: PRESS A SLOT`. The next slot button puts the **equipped** weapon into that
  slot (it moves if it was in another slot; pressing the slot it is already in clears
  it), then assign mode switches off. Letting go of L2 or R2 also switches it off.
- **R2 + Select** (without L2): put the equipped weapon into the first free slot, or
  clear its slot.
- **R1 / L1:** switch to the next / previous assigned weapon, in slot order.
- **On screen:** the weapon's name appears in the bottom information bar for about
  2.5 s. With the weapon drawn, Ashley sheathes the old weapon and draws the new one
  using the game's own animations.
- **Safety:** swaps only happen at safe moments: not in menus or cutscenes, not
  mid-attack or during chain-ability timing, and not while something is loading. A press
  at any other time is ignored.
- **Saved with your game:** the slot (1 to 8, 0 = none) is stored in an unused byte of
  the weapon record (the 4th gem slot, which no grip uses). Saves from the unmodded game
  work as they are. A save from the previous version of the mod (several "favorites")
  is converted automatically: the favorites get slots 1, 2, 3 ... in inventory order.

**Camera on the right stick.** In the field, pushing the right stick left/right
rotates the camera, replacing L1/R1. Stick right does what L1 did. The stick no longer
toggles first-person view by accident. Menus still use L1/R1 for paging.

Requires the controller in **analog (DualShock) mode**. In DuckStation use *Analog
Controller* with *Force Analog Mode on Reset*, and plain bindings (L1 = L1, R1 = R1,
right stick = right stick).

### Default variant only (branch `qol-mod`)

**Western confirm/cancel.** In all menus, dialogs, the title screen and save/load
screens, Cross confirms and Circle cancels. The on-screen button icons are swapped to
match. Battle inputs are not affected: chain abilities, defense abilities, L2 shortcuts
and the ability-assignment menu keep their original buttons.

**Mirrored field buttons**, so the field layout agrees with the menus:

| Button | Weapon sheathed | Weapon drawn |
|---|---|---|
| Cross | draw weapon | attack |
| Circle | interact with the world | interact if something is nearby, otherwise sheathe |
| Square | jump (unchanged) | jump (unchanged) |

### Classic variant (branch `qol-mod-classic`)

Every button keeps its original function: menus, dialogs, title and save screens, and
the field and battle controls are exactly as in the unmodded game. Only the weapon quick
swap and the right-stick camera are added. Besides `BATTLE.PRG`, no file on the disc
differs from the original.

## Installing the patch

You need your own dump of **Vagrant Story (USA)** as a single-track `.bin` + `.cue`:

| | SHA-1 |
|---|---|
| Original `.bin` | `38c63db6c49a06b91d87cd5a4e31b1ec68fe212c` |
| Patched `.bin`, default (`QoL mod v2.xdelta`) | `e55a331f6c49c670c752fbc7dc7795cfe1d3810f` |
| Patched `.bin`, classic buttons (`QoL mod v2 (classic buttons).xdelta`) | `80679ddcadd7c3a07483155ec55c392fb5ce4b8f` |

1. Get the patch for the variant you want from the [Releases](../../releases) page:
   `Vagrant Story (USA) - QoL mod v2.xdelta` (default) or
   `Vagrant Story (USA) - QoL mod v2 (classic buttons).xdelta` (original buttons).
2. Apply it to your `.bin` with any xdelta tool (xdelta UI, Delta Patcher, or
   `xdelta3 -d -s original.bin patch.xdelta patched.bin`).
3. Copy your `.cue` next to the patched `.bin` and edit its `FILE` line to the new name.
4. Use a separate memory card file for the modded image if you want to keep your
   original saves untouched. The mod's save data is compatible either way, and the two
   variants share the same save format.

Tested in DuckStation only, not on real hardware.

## Building from source

1. Set up rood-reverse as described in [README.md](README.md): Ubuntu/WSL, the listed
   packages, and your disc at `disks/SLUS-01040.bin`.
2. Check out the branch of the variant you want: `qol-mod` (default) or
   `qol-mod-classic` (classic buttons). Then run `tools/mod/build_mod.sh`.
3. The image is written to `build/disks/SLUS-01040.bin` / `.cue`.

The normal `make` check reports mismatches for the modified overlays on `qol-mod`
(on `qol-mod-classic` only `BATTLE.PRG` is patched, after the normal build). That is
expected, and the script carries on past it.

`qol-mod-classic` is `qol-mod` without the confirm/cancel and field-button commits: the
weapon-swap commits sit directly on the decompilation base, and nothing under
`src/MENU`, `src/TITLE`, `include/psx` or the button checks in `src/BATTLE` is changed.

## How it was made

- **Base.** Built on noprompt's `decomp/verified-functions` branch
  ([PR #186](https://github.com/ser-pounce/rood-reverse/pull/186)), which has about
  97.5% of the game's code matched as C.
- **Confirm/cancel and field buttons (default variant only).** These are plain edits to
  the decompiled C: the Circle and Cross masks are swapped (for example `0x20`/`0x40`)
  at each confirm/cancel site, behind `VS_BUTTON_CONFIRM`/`VS_BUTTON_CANCEL` macros in
  `include/psx/libetc.h`.
  - About 170 input sites were classified as confirm, cancel or gameplay first.
  - The rebuilt files differ from the original only in instruction immediates. No code
    moves, so every other file and every disc address stays identical.
- **Weapon swap and camera (both variants).** This is new C code in `src/mod/wswap.c`,
  compiled with the same GCC 2.8.1 the game uses and linked against the game's symbols.
  - **Hooks:** one patched `jal` in `vs_battle_exec` sends the per-frame call to
    `vs_main_processPadState` through the mod. Two more patched `jal` in the L2 overlay
    drawing function replace the question "is this label available?" with a mod function
    that prints the weapon names (the game's labels are pictures, not text).
  - **Swap sequence:** the mod repeats the equip menu's sequence (`vs_battle_equipWeapon`,
    shield and two-handed handling, weapon model and animation reloads) as a per-frame
    state machine, so it never blocks.
  - **Where the code lives:** the main function and a few helpers sit in the zero-filled
    tail of `BATTLE.PRG`, which the game already loads into RAM. The rest replaces the
    bodies of eight unreferenced functions of `BATTLE.PRG` (`func_800B26B8`,
    `func_800D197C`, `func_800AA108`+`func_800AA218`, `func_800D155C`,
    `func_80099854`+`func_80099900`, `func_8009BD90`, `func_800733F8`, `func_8007FF8C`):
    no calls, no pointers, no branches into them, checked across every file on the disc
    (`tools/mod/check_dead.py`, `tools/mod/run_dead_checks.sh`). The layout is in
    `tools/mod/wswap.ld`.
- **Verification.**
  - Byte diffs against the original: only the intended instructions and regions change,
    and the `BATTLE.PRG` size on disc is unchanged. For the classic variant, the only
    differences from the original disc data are the three hook words, the eight
    unreferenced-function regions listed above and the tail from `0x8D124`; the
    other 5162 files are byte-identical.
  - The shipped machine code also ran in a small MIPS interpreter with the game's
    functions stubbed (`tools/mod/test_wswap.py`).
  - The fuzzed runs passed millions of checks with no failures.

The research, code and verification were done with **Claude** (Anthropic), working
from the decompiled source. I chose the design and tested every build in DuckStation.

## Credits

- ser-pounce and the rood-reverse contributors, for the decompilation and its tooling.
- noprompt, for the 97.5% branch this is built on.
- The tools rood-reverse builds on: splat, maspsx, mkpsxiso, decomp-permuter, m2c,
  xdelta.

Like rood-reverse, this mod is released under CC0. It contains no game data: the patch
only works on your own disc image.
