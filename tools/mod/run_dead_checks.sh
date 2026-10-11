#!/usr/bin/env bash
# Run the strict dead-code checker (check_dead.py, ~20 s) on every function range the weapon-slots
# mod overwrites. Needs `make` to have extracted data/ and built build/src. Exit 1 if one fails.
cd "$(dirname "$0")/../.."
out=$(mktemp -d)
run() { # start size name
    python3 -I tools/mod/check_dead.py "$1" "$2" "$3" > "$out/$3.log" 2>&1
    echo "$3 $1 $2 exit=$?" >> "$out/summary.txt"
}
run 800B26B8 496 func_800B26B8 &
run 800D197C 412 func_800D197C &
run 800AA108 392 func_800AA108 &   # func_800AA108 + func_800AA218 (adjacent)
run 800D155C 284 func_800D155C &
run 80099854 268 func_80099854 &    # func_80099854 + func_80099900 (adjacent)
# the default variant also uses these four (the classic one does not: #define WSWAP_CLASSIC 1)
if ! grep -q '^#define WSWAP_CLASSIC 1' src/mod/wswap.c; then
    run 8009BD90 204 func_8009BD90 &
    run 800733F8 140 func_800733F8 &
    run 8007FF8C 116 func_8007FF8C &
    run 800D9910 604 func_800D9910 &
fi
wait
sort "$out/summary.txt"
grep -h RESULT "$out"/*.log | sort | uniq -c
grep -q "exit=[^0]" "$out/summary.txt" && { echo "SOME RANGE IS REFERENCED"; exit 1; }
echo "all ranges dead"
echo "logs in $out"
