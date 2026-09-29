.syntax unified
.arch armv7-a
.thumb
.section .text,"ax",%progbits
.balign 4
.global patch_entry_new
.global patch_entry_existing
.global patch_common
.type patch_entry_new,%function
.thumb_func
patch_entry_new:
    mov r2, r10
    b.n .Lcommon
.type patch_entry_existing,%function
.thumb_func
patch_entry_existing:
    mov r2, r9
    b.n .Lcommon
.type patch_common,%function
.thumb_func
patch_common:
.Lcommon:
    push.w {r4-r11, lr}
    sub sp, #12
    mov r4, r0
    mov r5, r1
    mov r6, r0
    movs r3, #0
    mov r8, r3
    mov r9, r3
    mov r10, r3
    mov r11, r3
.Lpic:
    adr r7, .Lpic
    ldr r3, .Lcf_delta
    add r7, r3
    ldr r3, [r7]
    cmp r3, #0
    beq .Lfinish
    ldr r3, [r7, #0x14]
    cmp r3, #0
    beq .Lfinish
    ldr r3, [r7, #0xb8]
    cmp r3, #0
    beq .Lfinish

    cmp.w r4, #1440
    bne .Lbuild
    movw r3, #542
    cmp r5, r3
    bne .Lbuild
    mov r0, r2
    adr r1, .Ltype
    blx cf_dict_get_cstr
    mov r1, sp
    blx alt_cf_int64
    cbz r0, .Lbuild
    ldr r0, [sp]
    cmp r0, #111
    bne .Lbuild
    ldr r0, [sp, #4]
    cbnz r0, .Lbuild
    movw r6, #480
    mov r11, r6
.Lbuild:
    mov r0, r4
    mov r1, r5
    blx rect_dict
    mov r8, r0
    mov r0, r6
    mov r1, r5
    blx rect_dict
    mov r9, r0
    cmp.w r8, #0
    beq .Lcleanup
    cmp.w r9, #0
    beq .Lcleanup
    cmp.w r11, #0
    beq .Lattach
    mov r0, r9
    adr r1, .Lorigin
    mov r2, r11
    movs r3, #0
    blx set_i64
    cbz r0, .Lcleanup
.Lattach:
    mov r0, r8
    adr r1, .Lsafe
    mov r2, r9
    blx cf_dict_set_cstr_obj
    cbz r0, .Lcleanup
    mov r0, r9
    ldr r3, [r7]
    blx r3
    movs r3, #0
    mov r9, r3
    movs r0, #0
    movs r1, #0
    movs r2, #0
    movs r3, #0
    ldr r6, [r7, #0xb8]
    blx r6
    mov r10, r0
    cbz r0, .Lcleanup
    mov r1, r8
    ldr r3, [r7, #0x14]
    blx r3
    cmp.w r11, #0
    beq .Lcleanup
    adr r0, .Llog
    blx altscreen_log
.Lcleanup:
    cmp.w r9, #0
    beq .Louter
    mov r0, r9
    ldr r3, [r7]
    blx r3
.Louter:
    cmp.w r8, #0
    beq .Lfinish
    mov r0, r8
    ldr r3, [r7]
    blx r3
.Lfinish:
    mov r0, r10
    add sp, #12
    pop.w {r4-r11, pc}
.balign 4
.Lcf_delta:
    .word 0x8879c - (0x265a8 + .Lpic - patch_entry_new)
.Ltype:
    .asciz "type"
.balign 4
.Lorigin:
    .asciz "originXPixels"
.balign 4
.Lsafe:
    .asciz "safeArea"
.balign 4
.Llog:
    .asciz "NAV_SAFE_V20 x=480 y=0 w=480 h=542"
.balign 4
.size patch_entry_new, .-patch_entry_new
