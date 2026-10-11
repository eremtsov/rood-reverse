#!/usr/bin/env bash
# Zenith edition of the mod: the same mod on top of "Vagrant Story: Zenith" 1.94 (mod/zenith-edition.md).
#
#   tools/mod/build_zenith.sh ORIGINAL.bin ZENITH.bin VANILLA_MOD.bin OUT.bin
#
#   ORIGINAL.bin     the untouched US image
#   ZENITH.bin       ORIGINAL.bin with zenith_194.ppf applied
#   VANILLA_MOD.bin  the image tools/mod/build_mod.sh builds for this branch (its menu/immediate edits are carried over)
#   OUT.bin          the result (a .cue is written next to it)
#
# Needs a tree in which `make` has run once (build/config/*, build/src/include/lbas.h) and the toolchain of build_mod.sh.
# Steps: check that every range of tools/mod/zenith_bins.txt is unreferenced by every executable of both images
# (tools/mod/check_refs_disc.py; needs the splat output build/src/SLUS_010.40 and build/src/BATTLE of `make`),
# compile src/mod/wswap.c with -DWSWAP_ZENITH=1 (the branch sets it), pack its sections into the unreferenced
# functions of tools/mod/zenith_bins.txt (tools/mod/zenith_pack.py -> tools/mod/wswap-zenith.ld, checked in), link, and
# put everything on the Zenith image with tools/mod/zenith_port.py. Then the behavioural test runs against the new files.
set -euo pipefail
cd "$(dirname "$0")/../.."
[ $# -eq 4 ] || { sed -n '2,12p' "$0"; exit 2; }
ORIG=$(realpath "$1"); ZEN=$(realpath "$2"); MOD=$(realpath "$3"); OUT=$(realpath -m "$4")

B=build
M=$B/mod/zenith
CROSS=mipsel-linux-gnu-
die() { echo "build_zenith: $*" >&2; exit 1; }
grep -q '^#define WSWAP_ZENITH 1' src/mod/wswap.c || die "src/mod/wswap.c does not have '#define WSWAP_ZENITH 1' (use a zenith branch)"
if grep -q '^#define WSWAP_CLASSIC 1' src/mod/wswap.c; then VARIANT=classic; else VARIANT=default; fi
rm -rf "$M"; mkdir -p "$M"

# 0. every range must be unreferenced on the whole disc: SLUS_010.40 is always resident, BATTLE.PRG is resident together with
#    MENU/INITBTL/EFFECT/SCREFF2; the first Zenith build used libcd/libds functions that TITLE.PRG calls (mod/zenith-edition.md)
python3 -I tools/mod/check_refs_disc.py --vanilla "$ORIG" --zenith "$ZEN" --repo . --bins tools/mod/zenith_bins.txt \
    --out "$M/check_refs.txt" >/dev/null || die "a range of tools/mod/zenith_bins.txt fails tools/mod/check_refs_disc.py: see $M/check_refs.txt"
tail -1 "$M/check_refs.txt"

# 1. compile (same compiler and flags as the BATTLE.PRG sources, see the Makefile rule for build/src/mod/wswap.c.o)
cc -E -nostdinc -I include/psx -I src/include -I ./ -D "__attribute__(x)=" -D_LANGUAGE_C src/mod/wswap.c \
    | tools/python/bin/python3 -m tools.etc.vsStringTransformer \
    | tools/old-gcc/2.8.1-psx/cc1 -G0 -O2 -Wall -quiet -fno-builtin -funsigned-char -Wno-unused \
    | tools/python/bin/python3 tools/maspsx/maspsx.py --aspsx-version=2.77 --macro-inc \
    | ${CROSS}as -I include -G0 -no-pad-sections -o "$M/wswap.o"

# 2. game symbols (as in build_mod.sh) and the linker script
sed -nE 's/^[[:space:]]*([A-Za-z_0-9]+)[[:space:]]*=[[:space:]]*(0x[0-9A-Fa-f]+);.*/\1 = \2;/p' \
    config/BATTLE/BATTLE.PRG/symbol_addrs.txt "$B"/config/BATTLE/BATTLE.PRG/undefined_{funcs,syms}_auto.txt \
    config/SLUS_010.40/symbol_addrs.txt "$B"/config/SLUS_010.40/undefined_{funcs,syms}_auto.txt | awk '!seen[$1]++' >"$M/syms.ld"
${CROSS}objdump -h "$M/wswap.o" | awk '$2 ~ /^\./ {print $2, $3}' >"$M/sections.in"
python3 -I tools/mod/zenith_pack.py "$M/sections.in" tools/mod/zenith_bins.txt "$M/wswap-zenith.ld" >"$M/pack.log"
cat "$M/pack.log"
cmp "$M/wswap-zenith.ld" tools/mod/wswap-zenith.ld || die "tools/mod/wswap-zenith.ld is not what the packer produces now: copy $M/wswap-zenith.ld there and review"

# 3. link, one binary per output section
${CROSS}ld -nostdlib --build-id=none -T tools/mod/wswap-zenith.ld -T "$M/syms.ld" -T tools/mod/extra_syms.ld \
    -Map "$M/wswap.map" "$M/wswap.o" -o "$M/wswap.elf" 2>&1 | grep -v 'LOAD segment with RWX\|type changed to PROGBITS' || true
${CROSS}objdump -h "$M/wswap.elf" | awk '$2 ~ /^\.zb_/ {print $2, $3, $4}' >"$M/sections.txt"
while read -r name size vma; do
    ${CROSS}objcopy -O binary -j "$name" "$M/wswap.elf" "$M/${name#.}.bin"
    # every section must fit the range it was packed into (the packer already counted; this is the linker's view)
done <"$M/sections.txt"
${CROSS}nm -n "$M/wswap.elf" | grep -E ' [tTdDbB] ' | grep -v ' [tT] func_\| [tT] vs_' >"$M/nm.txt"
for sym in vs_main_processPadState func_800C9EB8 func_8006EC7C; do grep -h "^$sym = " "$M/syms.ld" tools/mod/extra_syms.ld | head -1; done >"$M/hooksyms.txt"

# 4. the image
python3 -I tools/mod/zenith_port.py --variant "$VARIANT" --original "$ORIG" --zenith "$ZEN" --mod "$MOD" --link "$M" \
    --lbas "$B/src/include/lbas.h" --out "$OUT" --report "$M/report.json"
printf 'FILE "%s" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n' "$(basename "$OUT")" >"${OUT%.bin}.cue"

# 5. the behavioural test on the shipped bytes (a private root: test_wswap.py finds its inputs relative to itself)
R=$M/root
mkdir -p "$R/tools/mod" "$R/src/mod" "$R/build/mod" "$R/build/data/BATTLE"
cp tools/mod/test_wswap.py tools/mod/extra_syms.ld "$R/tools/mod/"
cp src/mod/wswap.c "$R/src/mod/"
cp "$M/syms.ld" "$M/wswap.elf" "$R/build/mod/"
python3 -I - "$R" "$OUT" "$ZEN" "$B/src/include/lbas.h" "$M/report.json" <<'PYEOF'
import json, sys
sys.path.insert(0, 'tools/mod')
import zenith_port as zp
root, out, zen, lbas, rep = sys.argv[1:]
files = zp.load_lbas(lbas)
d, z = zp.Disc(out, files), zp.Disc(zen, files)
open(root + '/build/data/BATTLE/BATTLE.PRG', 'wb').write(d.read('BATTLE_PRG'))
open(root + '/build/data/SLUS_010.40', 'wb').write(d.read('SLUS_010_40'))
open(root + '/build/mod/BATTLE.PRG.pristine', 'wb').write(z.read('BATTLE_PRG'))
open(root + '/build/mod/SLUS_010.40.zenith', 'wb').write(z.read('SLUS_010_40'))
r = json.load(open(rep))
lines = []
for b in r['blobs']:
    p = b.split(); a, e = p[1].split('..')
    lines.append('%s %s %d' % ('BATTLE' if p[0] == 'BATTLE.PRG' else 'SLUS', a, int(e, 16) - int(a, 16)))
for h in r['hooks']:
    lines.append('BATTLE %s 4' % h.split(':')[0])
for x in r['fp'] + r['imm']:
    lines.append('BATTLE %s 1' % x.split(':')[0])
for x in r['ports']:
    lines.append('SLUS 8004EB28 1')
open(root + '/build/mod/zenith_allowed.txt', 'w').write('\n'.join(lines) + '\n')
PYEOF
(cd "$R" && python3 -I tools/mod/test_wswap.py | tail -3)
echo "image: $OUT"
