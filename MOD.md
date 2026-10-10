# Vagrant Story QoL mod

A small quality-of-life mod for **Vagrant Story (USA, SLUS-01040)**, built on the
[rood-reverse](https://github.com/ser-pounce/rood-reverse) decompilation. It was made
for my own play in an emulator. It is not part of rood-reverse and is not intended for
upstream.

## What it changes

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

**Favorite-weapon quick swap.**

- **R2 + Select:** add the equipped weapon to your favorites, or remove it. A different
  sound plays for added and removed.
- **R1 / L1:** switch to the next / previous favorite, in inventory order. Up to 8
  favorites.
- **On screen:** the weapon's name appears in the bottom information bar for about
  2.5 s. With the weapon drawn, Ashley sheathes the old weapon and draws the new one
  using the game's own animations.
- **Safety:** swaps only happen at safe moments: not in menus or cutscenes, not
  mid-attack or during chain-ability timing, and not while something is loading. A press
  at any other time is ignored.
- **Saved with your game:** favorites are stored in an unused byte of the weapon record
  (the 4th gem slot, which no grip uses). Saves from the unmodded game work as they are.

**Camera on the right stick.** In the field, pushing the right stick left/right
rotates the camera, replacing L1/R1. Stick right does what L1 did. The stick no longer
toggles first-person view by accident. Menus still use L1/R1 for paging.

Requires the controller in **analog (DualShock) mode**. In DuckStation use *Analog
Controller* with *Force Analog Mode on Reset*, and plain bindings (L1 = L1, R1 = R1,
right stick = right stick).

## Installing the patch

You need your own dump of **Vagrant Story (USA)** as a single-track `.bin` + `.cue`:

| | SHA-1 |
|---|---|
| Original `.bin` | `38c63db6c49a06b91d87cd5a4e31b1ec68fe212c` |
| Patched `.bin` | `e55a331f6c49c670c752fbc7dc7795cfe1d3810f` |

1. Get `Vagrant Story (USA) - QoL mod v2.xdelta` from the
   [Releases](../../releases) page.
2. Apply it to your `.bin` with any xdelta tool (xdelta UI, Delta Patcher, or
   `xdelta3 -d -s original.bin patch.xdelta patched.bin`).
3. Copy your `.cue` next to the patched `.bin` and edit its `FILE` line to the new name.
4. Use a separate memory card file for the modded image if you want to keep your
   original saves untouched. The mod's save data is compatible either way.

Tested in DuckStation only, not on real hardware.

## Building from source

1. Set up rood-reverse as described in [README.md](README.md): Ubuntu/WSL, the listed
   packages, and your disc at `disks/SLUS-01040.bin`.
2. Check out this branch, then run `tools/mod/build_mod.sh`.
3. The image is written to `build/disks/SLUS-01040.bin` / `.cue`.

The normal `make` check reports mismatches for the modified overlays. That is expected,
and the script carries on past it.

To build the quick swap without the sheathe/draw animation, set `WSWAP_ANIM` to `0` in
`src/mod/wswap.c`. That build fits entirely in free space and overwrites no game code.

## How it was made

- **Base.** Built on noprompt's `decomp/verified-functions` branch
  ([PR #186](https://github.com/ser-pounce/rood-reverse/pull/186)), which has about
  97.5% of the game's code matched as C.
- **Confirm/cancel and field buttons.** These are plain edits to the decompiled C: the
  Circle and Cross masks are swapped (for example `0x20`/`0x40`) at each confirm/cancel
  site, behind `VS_BUTTON_CONFIRM`/`VS_BUTTON_CANCEL` macros in
  `include/psx/libetc.h`.
  - About 170 input sites were classified as confirm, cancel or gameplay first.
  - The rebuilt files differ from the original only in instruction immediates. No code
    moves, so every other file and every disc address stays identical.
- **Weapon swap and camera.** This is new C code in `src/mod/wswap.c`, compiled with the
  same GCC 2.8.1 the game uses and linked against the game's symbols.
  - **Hook:** one patched `jal` in `vs_battle_exec` sends the per-frame call to
    `vs_main_processPadState` through the mod.
  - **Swap sequence:** the mod repeats the equip menu's sequence (`vs_battle_equipWeapon`,
    shield and two-handed handling, weapon model and animation reloads) as a per-frame
    state machine, so it never blocks.
  - **Where the code lives:** most of it sits in the zero-filled tail of `BATTLE.PRG`,
    which the game already loads into RAM. The rest replaces `func_800B26B8`, a helper
    that nothing references: no calls, no pointers, no branches into it, checked across
    every file on the disc (`tools/mod/check_dead.py`).
- **Verification.**
  - Byte diffs against the original: only the intended instructions and regions change,
    and the `BATTLE.PRG` size on disc is unchanged.
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
