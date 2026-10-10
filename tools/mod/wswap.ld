/* Link script for the weapon-swap mod blob.
 * The blob lives in the zero tail of BATTLE.PRG's last sector:
 *   RAM 0x800F5924 .. 0x800F6000 (1756 bytes), file offset 0x8D124.
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
    /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.gnu.attributes) *(.comment) *(.mdebug*) }
}
