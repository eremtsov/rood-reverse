/* Link script for the weapon-slots mod.
 * .wswap  : the zero tail of the last sector of BATTLE.PRG
 *           RAM 0x800F5924 .. 0x800F6000 (1756 bytes), file offset 0x8D124.
 * The other output sections are the bodies of functions of BATTLE.PRG that nothing in the
 * game references (jal/j, branches, pointers, lui pairs, name; tools/mod/check_dead.py,
 * tools/mod/run_dead_checks.sh). Each is placed at the start of such a function and may
 * not be larger than it (tools/mod/build_mod.sh checks the sizes and that the bytes it
 * overwrites are the original ones):
 *   .wswap2  func_800B26B8  496 bytes  beginSwap, inSlot
 *   .wA      func_800D197C  412 bytes  wslot_label
 *   .wB      func_800AA108+func_800AA218 (adjacent) 392 bytes  slotMode, button tables
 *   .wC      func_800D155C  284 bytes  assign, label position table
 *   .wD      func_80099854+func_80099900 (adjacent) 268 bytes  nameToAscii
 *   .wE      func_8009BD90  204 bytes  swapAllowed, hint strings
 *   .wF      func_800733F8  140 bytes  startSwap
 *   .wH      func_8007FF8C  116 bytes  drawHint
 * Game symbols are provided by build/mod/syms.ld (generated) + extra_syms.ld. */
ENTRY(wswap_entry)
SECTIONS
{
    . = 0x800F5924;
    .wswap : SUBALIGN(4) {
        *(.text)
        *(.rodata*)
        *(.data*)
        *(.bss*)
        *(COMMON)
    }
    . = 0x800B26B8;
    .wswap2 : SUBALIGN(4) { *(.wswap2) }
    . = 0x800D197C;
    .wA : SUBALIGN(4) { *(.wA) }
    . = 0x800AA108;
    .wB : SUBALIGN(4) { *(.wB) *(.wd2) }
    . = 0x800D155C;
    .wC : SUBALIGN(4) { *(.wC) *(.wd1) }
    . = 0x80099854;
    .wD : SUBALIGN(4) { *(.wD) }
    . = 0x8009BD90;
    .wE : SUBALIGN(4) { *(.wE) *(.wd3) }
    . = 0x800733F8;
    .wF : SUBALIGN(4) { *(.wF) }
    . = 0x8007FF8C;
    .wH : SUBALIGN(4) { *(.wH) }
    /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.gnu.attributes) *(.comment) *(.mdebug*) }
}
