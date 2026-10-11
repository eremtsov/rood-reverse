# Vagrant Story QoL mod

A quality-of-life mod for **Vagrant Story (USA, SLUS-01040)**, built on the
[rood-reverse](https://github.com/ser-pounce/rood-reverse) decompilation. It was made
for my own play in an emulator. It is not part of rood-reverse and is not intended for
upstream.

## Two variants

| Variant | In short | Branch | Patch |
|---|---|---|---|
| **Default** | Western confirm/cancel, mirrored field buttons, reworked camera and first-person controls, weapon slots | `qol-mod` | `Vagrant Story (USA) - QoL mod v3.xdelta` |
| **Classic buttons** | Every original control kept; only the weapon slots are added | `qol-mod-classic` | `Vagrant Story (USA) - QoL mod v3 (classic buttons).xdelta` |

## Weapon slots (both variants)

Weapon switching works like the L2 shortcut menu. Each of the 8 slots holds one
weapon.

| Input | What it does |
|---|---|
| **Hold L2 + R2** | Opens the L2 shortcut overlay with your weapons in the 8 slots, shown by name |
| ...then **○ △ □ ×** or **↑ ↓ → ←** | Equips the weapon in that slot |
| ...then **Select** | Toggles assign mode (see below) |
| **R2 + Select** | Puts the equipped weapon in the first free slot, or takes it out of its slot |

- **Equipping:** with the weapon drawn, Ashley sheathes the old weapon and draws the
  new one. The new weapon's name appears in the information bar for about 2.5 s.
- **Assign mode:** shown by orange labels and an on-screen prompt. The next slot
  button puts the equipped weapon in that slot. If the weapon was in another slot, it
  moves there; pressing its own slot clears it. Assign mode then turns off.
- **D-pad slots** react only to the real D-pad, so walking with the left stick while
  holding L2 + R2 never triggers them.
- **When swapping is allowed:** only at safe moments. Not in menus or cutscenes, not
  mid-attack or during chain/defense ability timing, and not while something is
  loading.
- **Saved with your game:** slots are stored in an unused byte of each weapon (the 4th
  gem slot, which no grip uses). Saves from the unmodded game work as they are, and
  favorites from v2 move into slots 1, 2, 3, ...
- Holding **L2 alone** still opens the normal shortcuts.

## Default variant: all control changes

### Menus and dialogs
- **Cross confirms, Circle cancels** everywhere: menus, dialogs, the title screen, and
  save/load. The on-screen button icons are swapped to match.
- Battle inputs are not affected: chain and defense abilities, L2 shortcuts and the
  ability assignment menu keep their buttons.

### Field (mirrored to match the menus)

| Button | Weapon sheathed | Weapon drawn |
|---|---|---|
| **Cross** | Draw weapon | Attack |
| **Circle** | Interact with the world | Interact if something is nearby, otherwise sheathe |
| **Square** | Jump (unchanged) | Jump (unchanged) |

### Camera
- **L1 / R1** rotate the camera, inverted compared to the original: L1 turns the way
  R1 used to and vice versa.
- **Right stick left/right** also rotates the camera, in the same direction as the
  matching shoulder button (stick right = R1).
- **Right stick up/down** does nothing in the field. In particular, it no longer drops
  you into first-person view by accident.
- Everything works on a digital pad too: the camera is on L1/R1, and weapons are on
  L2 + R2.

### First-person view
- **Enter and leave** with **R3** (click the right stick) or **Start**.
- **Look around** with the left stick, the D-pad, or the **right stick**.
- **Up/down is inverted.**

### Map screen
- **Panning is inverted on both axes**, for the left stick and the D-pad. Rotation and
  zoom are unchanged.

## Classic-buttons variant

All original controls are kept, including the confirm/cancel buttons, the field
buttons, L1/R1 camera rotation, the right stick and first-person view. It only adds
the **weapon slots** above (L2 + R2, Select assign mode, R2 + Select).

## Installing the patch

You need your own dump of **Vagrant Story (USA)** as a single-track `.bin` + `.cue`.

| File | SHA-1 |
|---|---|
| Original `.bin` | `38c63db6c49a06b91d87cd5a4e31b1ec68fe212c` |
| Patched `.bin`, default (`QoL mod v3.xdelta`) | `1122e397c604a63e45ae1f6e81e3b1b5195738c2` |
| Patched `.bin`, classic buttons (`QoL mod v3 (classic buttons).xdelta`) | `8efcf9f381337192f2d2f8416a0a7ac3fc014dfa` |

1. Get the patch for your variant from the [Releases](../../releases) page.
2. Apply it to your `.bin` with any xdelta tool (xdelta UI, Delta Patcher, or
   `xdelta3 -d -s original.bin patch.xdelta patched.bin`).
3. Copy your `.cue` next to the patched `.bin` and edit its `FILE` line to the new name.
4. In DuckStation, use **Analog Controller** with **Force Analog Mode on Reset** and
   plain bindings (L1 = L1, R1 = R1, right stick = right stick).

The patch only changes game code, so saves from the unmodded game work. Keep a backup
of your memory card anyway. The mod has been tested in DuckStation only, not on real
hardware.

## Building from source

1. Set up rood-reverse as described in [README.md](README.md): Ubuntu/WSL, the listed
   packages, and your disc at `disks/SLUS-01040.bin`.
2. Check out `qol-mod` (default) or `qol-mod-classic`, then run
   `tools/mod/build_mod.sh`.
3. The image is written to `build/disks/SLUS-01040.bin` / `.cue`.

`src/mod/wswap.c` is shared by both variants, and one `#define WSWAP_CLASSIC` line
selects between them. The normal `make` check reports mismatches for the modified
files. That is expected, and the script carries on past it.

## How it was made

- **Base.** Built on noprompt's `decomp/verified-functions` branch
  ([PR #186](https://github.com/ser-pounce/rood-reverse/pull/186)), which has about
  97.5% of the game's code matched as C.
- **Button swaps.** Confirm/cancel and the field buttons are plain edits to the
  decompiled C: the button masks are swapped at each confirm/cancel site, behind
  `VS_BUTTON_CONFIRM`/`VS_BUTTON_CANCEL` macros. The map and first-person inversions
  are a handful of constants. No code moves, so every disc address stays the same.
- **New code.** The weapon slots, quick swap, camera and first-person stick handling
  are new C code in `src/mod/wswap.c`, compiled with the same GCC 2.8.1 the game uses.
  - **Hooks:** one patched call routes the per-frame pad read through the mod. Two
    patched calls in the L2 overlay draw the weapon names in the game's small menu
    font. One patched call adds right-stick look in first person.
  - **Swap sequence:** the swap repeats the equip menu's sequence (stats, shield and
    two-handed handling, weapon model and animation reloads) as a per-frame state
    machine.
  - **Where the code lives:** in the zero-filled tail of `BATTLE.PRG` and in 8 game
    functions that nothing ever reaches. `tools/mod/check_dead.py` proves the last
    point against every file on the disc: no calls, pointers or branches into them,
    and no way to fall through into them.
- **Verification.**
  - Every build is checked byte by byte: only the intended regions change, and file
    sizes and sector checksums (EDC/ECC) stay valid.
  - The shipped machine code also ran in a small MIPS interpreter with the game's
    functions stubbed (`tools/mod/test_wswap.py`, about 400k checks).

The research, code and verification were done with **Claude** (Anthropic), working
from the decompiled source. I chose the design and tested the builds in DuckStation.

## Credits

- ser-pounce and the rood-reverse contributors, for the decompilation and its tooling.
- noprompt, for the 97.5% branch this is built on.
- The tools rood-reverse builds on: splat, maspsx, mkpsxiso, decomp-permuter, m2c,
  xdelta.

Like rood-reverse, this mod is released under CC0. It contains no game data: the patch
only works on your own disc image.
