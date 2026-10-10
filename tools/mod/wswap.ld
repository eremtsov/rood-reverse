/* Link script for the weapon-swap mod.
 * .wswap  : the zero tail of the last sector of BATTLE.PRG
 *           RAM 0x800F5924 .. 0x800F6000 (1756 bytes), file offset 0x8D124.
 * .wswap2 : the body of func_800B26B8 (bone-matrix helper, 496 bytes), which nothing in
 *           the game references (jal/j, branches, pointers, lui pairs, name);
 *           RAM 0x800B26B8, file offset 0x49EB8.
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
    .wswap2 : SUBALIGN(4) {
        *(.wswap2)
    }
    /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.gnu.attributes) *(.comment) *(.mdebug*) }
}
