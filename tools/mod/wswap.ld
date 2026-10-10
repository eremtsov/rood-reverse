/* Link script for the weapon-swap mod.
 * .wswap  : the zero tail of the last sector of BATTLE.PRG
 *           RAM 0x800F5924 .. 0x800F6000 (1756 bytes), file offset 0x8D124.
 * .wswap2 : the body of func_800E1EAC (enemy "wander" movement, 1280 bytes), which
 *           nothing in the game references; RAM 0x800E1EAC, file offset 0x796AC.
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
    . = 0x800E1EAC;
    .wswap2 : SUBALIGN(4) {
        *(.wswap2)
    }
    /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.gnu.attributes) *(.comment) *(.mdebug*) }
}
