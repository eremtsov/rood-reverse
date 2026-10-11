#!/usr/bin/env bash
# Build the personal mod disc image: weapon slots (L2+R2 overlay, L1/R1 slot cycling) with
# sheathe/draw animations and the weapon-name box, camera on the right stick, on top of the
# confirm/cancel-swap commits.
#
#   tools/mod/build_mod.sh
#
# Output: build/disks/SLUS-01040.bin/.cue (750,643,152 bytes), plus
#         build/mod/wswap.{elf,bin,map}, build/mod/sec_*.bin and
#         build/mod/BATTLE.PRG.pristine.
#
# Steps: make (its final `check` step fails by design for the modified overlays),
# compile src/mod/wswap.c with the BATTLE.PRG compiler (2.8.1-psx -O2), link it
# against the game symbols (tools/mod/wswap.ld) into
#   .wswap  at 0x800F5924: the zero tail of BATTLE.PRG (file offset 0x8D124, 1756 bytes)
#   and the bodies of eight unreferenced functions (list in $DEAD below and in wswap.ld;
#   tools/mod/run_dead_checks.sh proves nothing references them),
# patch all of it into BATTLE.PRG (size stays 579584 = 283 sectors), patch the three `jal`
# (vs_battle_exec -> wswap_entry, the two label calls of the L2 overlay -> wslot_label), and
# rebuild the disc image with mkpsxiso.
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
IMG_SIZE=750643152
PRG=$B/data/BATTLE/BATTLE.PRG
# output section : RAM address : size of the dead range
DEAD="wswap2:800B26B8:496 wA:800D197C:412 wB:800AA108:392 wC:800D155C:284 wD:80099854:268"
# The classic variant (src/mod/wswap.c: #define WSWAP_CLASSIC 1) is smaller: swapAllowed, startSwap and drawHint stay
# in the tail (func_8009BD90, func_800733F8, func_8007FF8C are not touched), and it has no first-person look hook.
# The default variant uses those three and additionally func_80099FA8 and func_800A1B28.
if grep -q '^#define WSWAP_CLASSIC 1' src/mod/wswap.c; then
    CLASSIC=1
else
    CLASSIC=0
    DEAD="$DEAD wE:8009BD90:204 wF:800733F8:140 wH:8007FF8C:116 wX:80099FA8:128 wY:800A1B28:116"
fi

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

# 3. link against the game symbols
# (BATTLE.PRG's own symbols win over SLUS_010.40's when a static name exists in both)
sed -nE 's/^[[:space:]]*([A-Za-z_0-9]+)[[:space:]]*=[[:space:]]*(0x[0-9A-Fa-f]+);.*/\1 = \2;/p' \
    config/BATTLE/BATTLE.PRG/symbol_addrs.txt \
    "$B"/config/BATTLE/BATTLE.PRG/undefined_{funcs,syms}_auto.txt \
    config/SLUS_010.40/symbol_addrs.txt \
    "$B"/config/SLUS_010.40/undefined_{funcs,syms}_auto.txt \
    | awk '!seen[$1]++' >"$M/syms.ld"
${CROSS}ld -nostdlib --build-id=none -T tools/mod/wswap.ld -T "$M/syms.ld" \
    -T tools/mod/extra_syms.ld -Map "$M/wswap.map" "$B/src/mod/wswap.c.o" -o "$M/wswap.elf" 2>&1 \
    | grep -v 'LOAD segment with RWX' || true
${CROSS}objcopy -O binary -j .wswap "$M/wswap.elf" "$M/wswap.bin"
size=$(stat -c %s "$M/wswap.bin")
room=$((BLOB_LIMIT - BLOB_RAM))
echo "tail blob: $size bytes of $room available ($((room - size)) free)"
[ "$size" -le "$room" ] || die "tail blob is $size bytes, only $room fit before 0x800F6000"
for d in $DEAD; do
    sec=${d%%:*}; rest=${d#*:}; ram=${rest%%:*}; dsize=${rest#*:}
    ${CROSS}objcopy -O binary -j ".$sec" "$M/wswap.elf" "$M/sec_$sec.bin"
    s=$(stat -c %s "$M/sec_$sec.bin")
    echo "dead range .$sec @0x$ram: $s bytes of $dsize available ($((dsize - s)) free)"
    [ "$s" -le "$dsize" ] || die ".$sec is $s bytes, only $dsize fit"
done

# 4. patch BATTLE.PRG: tail blob, the dead function bodies and the three hooks
entry=$(${CROSS}nm "$M/wswap.elf" | awk '$3=="wswap_entry"{print $1}')
label=$(${CROSS}nm "$M/wswap.elf" | awk '$3=="wslot_label"{print $1}')
[ -n "$entry" ] && [ -n "$label" ] || die "wswap_entry / wslot_label not found"
padstate=$(awk '$1=="vs_main_processPadState"{gsub(/;/,"",$3); print $3}' "$M/syms.ld")
labelorig=$(awk '$1=="func_800C9EB8"{gsub(/;/,"",$3); print $3}' "$M/syms.ld")
fp=0; fporig=$(awk '$1=="func_8006EC7C"{gsub(/;/,"",$3); print $3}' "$M/syms.ld" tools/mod/extra_syms.ld)
if [ "$CLASSIC" = 0 ]; then
    fp=$(${CROSS}nm "$M/wswap.elf" | awk '$3=="wfp_look"{print $1}')
    [ -n "$fp" ] || die "wfp_look not found"
fi
python3 -I - "$PRG" "$M" "$entry" "$label" "$padstate" "$labelorig" \
    "$PRG_PLAIN_SIZE" "$PRG_DISC_SIZE" "$PRG_RAM" "$DEAD" data/BATTLE/BATTLE.PRG "$fp" "$fporig" <<'PYEOF'
import struct, sys
prg, mdir, entry, label, padstate, labelorig, plain, disc, base, dead, orig, fp, fporig = sys.argv[1:]
entry, label, padstate, labelorig = int(entry, 16), int(label, 16), int(padstate, 16), int(labelorig, 16)
fp, fporig = int(fp, 16), int(fporig, 16)
plain, disc, base = int(plain), int(disc), int(base)
data = bytearray(open(prg, 'rb').read())
assert len(data) == plain, "BATTLE.PRG size"
original = open(orig, 'rb').read()
jal = lambda t: 0x0C000000 | ((t >> 2) & 0x03FFFFFF)
# hooks: (RAM address, original target, new target)
hooks = [(0x8007991C, padstate, entry),     # vs_battle_exec: jal vs_main_processPadState
         (0x800CA0A4, labelorig, label),    # func_800C9FE8: jal func_800C9EB8 (D-pad group)
         (0x800CA1AC, labelorig, label)]    # func_800C9FE8: jal func_800C9EB8 (button group)
if fp:                                      # default variant: right stick looks around in first person
    hooks.append((0x8007A10C, fporig, fp))  # vs_battle_exec: jal func_8006EC7C
for ram, old_t, new_t in hooks:
    off = ram - base
    old = struct.unpack_from('<I', data, off)[0]
    assert old == jal(old_t), "hook site %08X is not jal %08X: %08x" % (ram, old_t, old)
    assert data[off:off + 4] == original[off:off + 4]
# dead function bodies: they must still be the original code
for d in dead.split():
    sec, ram, size = d.split(':')
    ram, size = int(ram, 16), int(size)
    off = ram - base
    blob = open('%s/sec_%s.bin' % (mdir, sec), 'rb').read()
    assert len(blob) <= size
    assert bytes(data[off:off + size]) == original[off:off + size], ".%s: bytes at %08X differ from the original" % (sec, ram)
    data[off:off + len(blob)] = blob
    print("patched .%s @0x%X (RAM %08X): %d bytes" % (sec, off, ram, len(blob)))
blob = open('%s/wswap.bin' % mdir, 'rb').read()
data += blob
data += b'\0' * (disc - len(data))
assert len(data) == disc
for ram, old_t, new_t in hooks:
    off = ram - base
    struct.pack_into('<I', data, off, jal(new_t))
    print("patched hook @0x%X: %08x -> %08x" % (off, jal(old_t), jal(new_t)))
open(prg, 'wb').write(data)
print("wswap_entry=0x%08X wslot_label=0x%08X" % (entry, label))
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
