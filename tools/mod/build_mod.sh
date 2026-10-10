#!/usr/bin/env bash
# Build the personal mod disc image: favourite-weapon quick swap (L1/R1) +
# camera on the right stick, on top of the confirm/cancel-swap commits.
#
#   tools/mod/build_mod.sh
#
# Output: build/disks/SLUS-01040.bin/.cue (750,643,152 bytes), plus
#         build/mod/wswap.{elf,bin,map} and build/mod/BATTLE.PRG.pristine.
#
# Steps: make (its final `check` step fails by design for the modified overlays),
# compile src/mod/wswap.c with the BATTLE.PRG compiler (2.8.1-psx -O2), link it at
# 0x800F5924 against the game symbols, append it to the zero tail of BATTLE.PRG
# (file offset 0x8D124, size stays 579584 = 283 sectors), patch the one `jal` in
# vs_battle_exec, and rebuild the disc image with mkpsxiso.
set -euo pipefail
cd "$(dirname "$0")/../.."

B=build
M=$B/mod
CROSS=mipsel-linux-gnu-

BLOB_RAM=$((0x800F5924))
BLOB_LIMIT=$((0x800F6000))
PRG_PLAIN_SIZE=577828      # 0x8D124, what the toolchain produces
PRG_DISC_SIZE=579584       # 0x8D800, sector-rounded size the game loads
PRG_RAM=$((0x80068800))
HOOK_RAM=$((0x8007991C))   # jal vs_main_processPadState in vs_battle_exec
IMG_SIZE=750643152
PRG=$B/data/BATTLE/BATTLE.PRG

die() { echo "build_mod: $*" >&2; exit 1; }

mkdir -p "$M" "$B/src/mod"

# 1. regular build (the BATTLE.PRG we patch must be a fresh toolchain output)
rm -f "$PRG"
log=$(mktemp)
make -j16 >"$log" 2>&1 || true
bad=$(grep -E '^make.*\*\*\*' "$log" | grep -vE 'check\] Error|Waiting for unfinished' || true)
if [ -n "$bad" ] || [ ! -f "$PRG" ]; then
    cat "$log" >&2
    die "make failed with a real error:
$bad"
fi
echo "make: ok ($(grep -c '✘' "$log") overlays differ from the original, as expected)"
rm -f "$log"
[ "$(stat -c %s "$PRG")" -eq "$PRG_PLAIN_SIZE" ] \
    || die "unexpected $PRG size $(stat -c %s "$PRG") (want $PRG_PLAIN_SIZE)"
cp "$PRG" "$M/BATTLE.PRG.pristine"

# 2. compile the mod with the same compiler/flags as BATTLE.PRG's C files
rm -f "$B/src/mod/wswap.c.o"
make CC1VER=2.8.1-psx ASFLAGS="-I include -G0 -no-pad-sections" "$B/src/mod/wswap.c.o"

# 3. link at 0x800F5924 against the game symbols
# (BATTLE.PRG's own symbols win over SLUS_010.40's when a static name exists in both)
sed -nE 's/^[[:space:]]*([A-Za-z_0-9]+)[[:space:]]*=[[:space:]]*(0x[0-9A-Fa-f]+);.*/\1 = \2;/p' \
    config/BATTLE/BATTLE.PRG/symbol_addrs.txt \
    "$B"/config/BATTLE/BATTLE.PRG/undefined_{funcs,syms}_auto.txt \
    config/SLUS_010.40/symbol_addrs.txt \
    "$B"/config/SLUS_010.40/undefined_{funcs,syms}_auto.txt \
    | awk '!seen[$1]++' >"$M/syms.ld"
${CROSS}ld -nostdlib --build-id=none -T tools/mod/wswap.ld -T "$M/syms.ld" \
    -T tools/mod/extra_syms.ld -Map "$M/wswap.map" "$B/src/mod/wswap.c.o" -o "$M/wswap.elf"
${CROSS}objcopy -O binary "$M/wswap.elf" "$M/wswap.bin"
size=$(stat -c %s "$M/wswap.bin")
room=$((BLOB_LIMIT - BLOB_RAM))
echo "blob: $size bytes of $room available ($((room - size)) free)"
[ "$size" -le "$room" ] || die "blob is $size bytes, only $room fit before 0x800F6000"

# 4. append the blob to BATTLE.PRG and patch the hook
entry=$(${CROSS}nm "$M/wswap.elf" | awk '$3=="wswap_entry"{print $1}')
[ -n "$entry" ] || die "wswap_entry not found"
padstate=$(awk '$1=="vs_main_processPadState"{gsub(/;/,"",$3); print $3}' "$M/syms.ld")
python3 -I - "$PRG" "$M/wswap.bin" "$entry" "$padstate" \
    "$PRG_PLAIN_SIZE" "$PRG_DISC_SIZE" "$((HOOK_RAM - PRG_RAM))" <<'PYEOF'
import struct, sys
prg, blob, entry, padstate, plain, disc, hook = sys.argv[1:]
entry, padstate = int(entry, 16), int(padstate, 16)
plain, disc, hook = int(plain), int(disc), int(hook)
data = bytearray(open(prg, 'rb').read())
assert len(data) == plain, "BATTLE.PRG size"
jal = lambda t: 0x0C000000 | ((t >> 2) & 0x03FFFFFF)
old = struct.unpack_from('<I', data, hook)[0]
assert old == jal(padstate), "hook site is not jal vs_main_processPadState: %08x" % old
blob = open(blob, 'rb').read()
data += blob
data += b'\0' * (disc - len(data))
assert len(data) == disc
struct.pack_into('<I', data, hook, jal(entry))
open(prg, 'wb').write(data)
print("patched hook @0x%X: %08x -> %08x (wswap_entry=0x%08X)" % (hook, old, jal(entry), entry))
PYEOF

# 5. rebuild the disc image (mkpsxiso hangs if an old image is present)
cp -r --update=none data/ "$B"
mkdir -p "$B/disks"
cp --update=none disks/SLUS-01040.xml "$B/disks/SLUS-01040.xml"
rm -f "$B/disks/SLUS-01040.bin" "$B/disks/SLUS-01040.cue"
isolog=$(mktemp)
(cd "$B" && timeout 900 ../tools/mkpsxiso/mkpsxiso disks/SLUS-01040.xml \
    -o disks/SLUS-01040.bin -c disks/SLUS-01040.cue >"$isolog" 2>&1) \
    || { cat "$isolog" >&2; die "mkpsxiso failed"; }
rm -f "$isolog"
img=$(stat -c %s "$B/disks/SLUS-01040.bin")
[ "$img" -eq "$IMG_SIZE" ] || die "image is $img bytes, expected $IMG_SIZE"
echo "image: $B/disks/SLUS-01040.bin ($img bytes)"
