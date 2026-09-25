# Atari 2600 (VCS) - condensed hardware notes for K65 coding

## Machine

- CPU 6507 (6502 core, 13 address lines -> 8 KB space, no IRQ/NMI) @ 1.19 MHz (NTSC) / 1.18 MHz (PAL).
- **RAM: 128 bytes** at `0x80-0xFF`, mirrored at `0x180-0x1FF` (stack page). Stack grows down from `0xFF`.
- ROM window: 4 KB at `0xF000-0xFFFF` (mirror of `0x1000`). More ROM = bankswitching.
- TIA (video+audio) registers `0x00-0x3F` (also mirrored at `0x100+`: `gp0h` = `0x11B` forces
  absolute addressing = 1 extra cycle, used for cycle-exact timing).
- RIOT (RAM, I/O, timer) at `0x280-0x297`.
- No frame buffer: the CPU must feed the TIA **every scanline** ("racing the beam").

## Scanline timing

- 1 scanline = **76 CPU cycles** = 228 colour clocks (3 colour clocks per CPU cycle).
- First 68 colour clocks (~22.7 cycles) are HBLANK, then 160 visible pixels.
- `WSYNC` (`wsync` inline = `WSYNC=a`) halts the CPU until the start of the next scanline.
  Writing a colour right after `wsync` with `lda abs,x; sta` (7 cycles) lands inside HBLANK = no tearing.
- `HMOVE` right after `wsync` extends HBLANK by 8 pixels (the "HMOVE bars").

## Frame layout

| | NTSC | PAL/SECAM |
|---|---|---|
| VSYNC | 3 | 3 |
| VBLANK (top) | 37 | 45 |
| Picture | 192 | 228 |
| Overscan (bottom) | 30 | 36 |
| **Total** | **262 @ 60 Hz** | **312 @ 50 Hz** |

Frame handling in this project (`_defs.k65`, PAL, timer driven - measured with `make check`):

```c
inline sync1 { timwait wsync VBLANK=a=2 TIM64T=a=40 }                               // picture end -> overscan (34 lines)
inline sync2 { timwait wsync VSYNC=a=2 wsync wsync a=0 wsync VSYNC=a TIM64T=a=54 }   // VSYNC 3 + VBLANK (45 lines)
inline sync3 { timwait wsync VBLANK=a=0 T1024T=a=18 }                               // picture (230 lines)
```

Usage: `{ sync1 <overscan logic> sync2 <vblank logic> sync3 <kernel> } always`.
The kernel must finish before the picture timer expires (~229 lines after sync3), otherwise
`timwait` sees the underflowed timer and the frame gets ~4 lines longer (rolling picture).
Logic in overscan/vblank must also fit in the timer window (~34 / ~45 lines x 76 cycles).

NTSC variants are commented out in `_defs.k65` (TIM64T 33 / 44, TIM64T 231).

## RIOT timer

Write `TIM1T`/`TIM8T`/`TIM64T`/`T1024T` (`0x294-0x297`) with N; read `INTIM` (`0x284`).
The timer decrements once right after the write, then every 1/8/64/1024 cycles; after reaching 0
it underflows and counts down every cycle from 0xFF. `timwait` = `{ a=INTIM }!=`.
So it hits 0 after ~(N-1)*interval cycles: TIM64T 40 -> 32.8 lines, T1024T 18 -> 229 lines;
the `wsync` after `timwait` rounds up to the next full line (34 / 230 lines as measured).

## TIA write registers (standard name / short alias from `_defs.k65`)

| addr | std | alias | bits / meaning |
|---|---|---|---|
| 00 | VSYNC | | bit1: vertical sync on |
| 01 | VBLANK | | bit1: blank beam, bit6: latch inputs, bit7: dump pots |
| 02 | WSYNC | | strobe: wait for end of scanline |
| 04/05 | NUSIZ0/1 | ns0/ns1 | copies/size of player (bits 0-2), missile width (bits 4-5) |
| 06/07 | COLUP0/1 | cp0/cp1 | player/missile colour |
| 08 | COLUPF | cpf | playfield + ball colour |
| 09 | COLUBK | cbg | background colour |
| 0A | CTRLPF | ctpf | bit0 reflect PF, bit1 score mode, bit2 PF priority, bits4-5 ball size |
| 0B/0C | REFP0/1 | rep0/rep1 | bit3 mirror player |
| 0D/0E/0F | PF0/PF1/PF2 | pf0/pf1/pf2 | playfield bits (PF0 bits 4-7 only, PF0/PF2 reversed order) |
| 10-14 | RESP0/1 RESM0/1 RESBL | rp0 rp1 rm0 rm1 rb | strobe: set horizontal position = current beam |
| 15/16 | AUDC0/1 | ac0/ac1 | waveform (0-15) |
| 17/18 | AUDF0/1 | af0/af1 | frequency divider (0-31) |
| 19/1A | AUDV0/1 | av0/av1 | volume (0-15) |
| 1B/1C | GRP0/1 | gp0/gp1 | player 8-bit graphics |
| 1D/1E/1F | ENAM0/1 ENABL | em0 em1 eb | bit1: enable missile/ball |
| 20-24 | HMP0/1 HMM0/1 HMBL | hp0 hp1 hm0 hm1 hb | fine motion, bits 4-7 signed (-8..+7, left positive) |
| 25/26/27 | VDELP0/1 VDELBL | vdp0 vdp1 vdb | vertical delay |
| 28/29 | RESMP0/1 | rmp0/rmp1 | lock missile to player |
| 2A | HMOVE | hmove | strobe: apply fine motion (right after wsync) |
| 2B | HMCLR | hmclr | strobe: clear motion registers |
| 2C | CXCLR | | clear collision latches |

Read: `CXM0P..CXPPMM` (collisions, 0x00-0x07), `INPT4/5` (`0x3C/0x3D`, fire buttons, bit7=0 pressed).
RIOT: `SWCHA 0x280` joysticks (P0 = high nibble: bit7 right, 6 left, 5 down, 4 up, 0 = pressed),
`SWCHB 0x282` console switches (bit0 reset, bit1 select, bit3 colour/BW, bits 6/7 difficulty).

## Colours

A colour byte is `HHHHLLL0`: high nibble = hue, bits 1-3 = luminance (0x0 dark .. 0xE bright), bit0 ignored.

**PAL hues** (this project is PAL; K65 `color()` uses the PAL palette):
`0x0_,0x1_,0xE_,0xF_` grey · `0x2_` gold/yellow · `0x3_` yellow-green · `0x4_` orange ·
`0x5_` green · `0x6_` red · `0x7_` teal · `0x8_` magenta · `0x9_` cyan-blue · `0xA_` purple ·
`0xB_` blue · `0xC_` violet · `0xD_` deep blue.
Smooth PAL rainbow order: `2 4 6 8 A C D B 9 7 5 3` (even hues go warm, odd hues go cool).

**NTSC hues** (approximate): `0x0_` grey, `1` gold, `2` orange, `3` red-orange, `4` red, `5` magenta, `6` purple,
`7` blue-violet, `8` blue, `9` light blue, `A` cyan, `B` teal, `C` green, `D` yellow-green,
`E` olive, `F` brown. NTSC rainbow = hues `1..F` in order.

A PAL-coded ROM shown on NTSC (or vice versa) has wrong colours and rolls - run Stella with `-format PAL`.

## Common kernel techniques

- **Raster colours / rainbow**: `{ wsync cbg=a=Table,x x++ y-- }!=` - one colour per line.
- **Horizontal positioning** (`SetHorizPos` in `util.k65`): A = x position, X = object index
  (0 P0, 1 P1, 2 M0, 3 M1, 4 BL); divide by 15 in a loop, strobe RESPx, put remainder into HMxx,
  then `wsync hmove=a` once for all objects. Must be `nocross` (branch timing).
- **Playfield graphics**: write PF0/PF1/PF2 for the left half, then again mid-line for the right half
  (asymmetric PF, needs exact cycle timing: see `effects/bigtext.k65` in the template with `*10` delay).
- **Two-line kernel**: update different registers on alternate lines to fit the 76-cycle budget.
- Tables indexed per line should be `align 256` or `nocross` so `abs,x` never takes +1 cycle.
- Use `*N` for exact delays, `%` for a 3-cycle nop, `gp0h`/`cp0h` (TIA mirrors) for +1 cycle writes.
  Same trick for RAM: `var v_h = 0x100 + v` reads RAM through its mirror as absolute (+1 cycle),
  e.g. `x?pl_end_h` = CPX abs (4 cycles) instead of CPX zp (3) to hit an exact line length.
- **Chunky 2D colour grid / plasma** (`effects/plasma.k65`): rewrite COLUBK mid-line.
  `lda (ptr_i),y` + `sta COLUBK` = 8 cycles = 24 px per cell -> 7 cells per line (~53 visible cycles).
  A write lands at pixel ~ 3*cycle - 68 (cycle counted from the end of WSYNC).
  Keep `ptr_lo + Y <= 255` so `(zp),y` never crosses a page (constant 5 cycles).
  Shifting every second line by 4 cycles (12 px) = brick dithering, doubles perceived resolution.
  A 2-line kernel can end line B without WSYNC if it is exactly 76 cycles (branch lands at cycle 0).
- **Sprite multiplexing** (`effects/eqsine.k65`): split the screen into slots; per slot spend
  1 line per object on `PosObject` (A = x 0..159, X = object; `c+ wsync { a-15 }>= a^7 a<<x4
  hp0h,x=a rp0,x=a`, inside `nocross`), then `wsync hmove=a`, then draw. 14-line slots
  (2 pos + 1 hmove + 10 draw + 1 clear) x 16 = 224 lines -> 32 objects from P0+P1.
  Don't write HMxx within 24 cycles after HMOVE. HMOVE blanks the first 8 pixels of its line
  (the "comb"): invisible on black, ugly on a coloured background - hide it with a black playfield
  frame: `pf0=a=0x30 ctpf=a=1 cpf=a=0` (PF0 bits 4-5 = pixels 0-7, reflected -> also 152-159),
  zero kernel cost, players are drawn over the playfield. P0 always has priority over P1 - assign
  the "front" object to P0 per slot for 3D depth. Colour bit0 is ignored by TIA - usable as a flag.
- **Ball with a black PF frame**: the ball shares COLUPF with the playfield. On the ball's lines
  switch the frame off (PF0 = 0x02: frame bits clear, and the same byte written to ENABL enables
  the ball) so COLUPF can hold the ball colour; lines without HMOVE don't need the frame.
- **Many missiles from two**: position M0/M1 once at the top, then move them per slot with HMMx on
  the slot's HMOVE (-8..+7 px per slot) and switch ENAMx per slot -> 32 sparks. HMMx ignores bits
  0-3 and ENAMx uses only bit 1, so one table byte can hold both the move and the enable.
- **Music reactivity**: TIA gives no spectrum, but the player knows what it plays: copy AUDVx/AUDFx
  to RAM each frame. AUDF (pitch divider) -> band, AUDV -> energy (spread to neighbours, decay per
  frame), a jump of the summed volume -> beat trigger.
- **Fades**: put 8 luminance-scaled copies of a colour table in consecutive pages and select the page
  via the pointer high byte - zero extra kernel cost.

## Bankswitching (as done by K65 `system_a2600.nut`)

- Each `bank` is 4 KB mapped at `0xF000`. 1 bank = 4K, 2 = F8 (8K), 3-4 = F6 (16K), 5-8 = F4 (32K).
- Hotspots: bank n selected by touching `__banksel_<bank>` (0x1FF8, 0x1FF9, 0x1FF6, ... see .nut).
- The linker puts a reset stub + vectors in every bank, so power-on bank does not matter.
- `far func` generates `__far_<from>_<to>__func` stubs (BIT hotspot, JSR, BIT back, RTS).
- This project pre-allocates 8 banks -> 32 KB F4 ROM (`-bs F4` in Stella).
