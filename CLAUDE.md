# k65-vcs-ai-example

Atari 2600 (VCS) demo written in **K65** - a custom 6502 assembler with its own, very
non-standard syntax (`a=5 cbg=a`, `{ ... }!=` loops, `x?10 >={ }` conditions).
Do not write DASM/ca65 syntax here. Target: **PAL**, 312 lines/frame, 32K F4 ROM.
Effects (FIRE or SELECT switches, with fade out/in). **Currently only eqsine is enabled** -
rainbow and plasma are commented out in `main.k65` (code kept, the linker drops unreferenced sections):
- `effects/rainbow.k65` (bank core) - scrolling, sine-wobbled rainbow background
- `effects/plasma.k65` (bank bank2) - 7x113 sum-of-sines plasma raced with mid-line COLUBK writes
- `effects/eqsine.k65` (bank bank3) - music-reactive double helix: 32 orbs from 2 multiplexed sprites;
  section choreography (table from `tools/song_analysis.py`), melody pitch -> bulge position,
  kick -> pump/spin/flash (reads `mus_*` copies of AUDV/AUDF/AUDC written by the player),
  section-coloured flashing background, playfield scanner line (speed per section, hops on kicks)

## Knowledge base - read before editing K65 code

- `docs/k65-language.md` - K65 syntax cheat sheet (verified against the compiler), gotchas, error behaviour
- `docs/atari2600-vcs.md` - VCS hardware: timing, TIA/RIOT registers, PAL/NTSC colours, kernel tricks
- `docs/project-structure.md` - files, build, demo/effect skeleton, RAM map, verification workflow

Authoritative sources when in doubt: grammar `$K65_PATH/src/compiler.inc`, docs `$K65_PATH/doc/docs/`,
examples `$K65_PATH/examples/a2600-tutorial-0*`, the user's demos in `../` (sv2019, sv2k21, jp-stream-demo),
template `../../k65-templates/atarivcs-demo-template`. If K65 syntax is unclear - ask the user.

## Commands

- `make` - build `bin/demo.bin` (needs `K65_PATH`; compiler = `$K65_PATH/workdir/k65.exe`, a Linux ELF)
- `make run` - build and start Stella (GUI - only the user can see it)
- `make check` - headless: 300 frames, FIRE at 60 and 160 (all 3 effects), every frame must be 312 lines,
  `bin/frames.png` = rendered frames (background incl. mid-line COLUBK + players P0/P1) - look at it.
  Custom: `uv run --with py65 --with pillow tools/vcs_frame_check.py bin/demo.bin --frames N --press a,b --show x,y --png out.png`
- `uv run --with py65 tools/song_analysis.py bin/demo.bin` - per-section audio features of the song
- `make clean`

## Rules

- After every change: `make` (expect `All OK.`), then `make check` (expect 312 everywhere).
- Kernel loop per scanline <= 76 cycles; picture kernel <= ~228 `wsync`s; check `bin/demo.lst`.
  Cycle-counted kernels (plasma) must stay inside `nocross` and keep their cycle comments correct.
- Effects start with `FxStart` + `goto <name>_enter` (label just before `sync2`) and call `FxUpdate`
  in overscan - otherwise the switch frame gets a double overscan (346 lines).
- CPU budget: overscan ~2500 cycles (music player runs there), vblank ~3400. If `make check` shows
  top/bottom > 45/34 lines, move work between overscan and vblank or split it (see eqsine EQ_SPLIT).
- New RAM variables: pick free addresses and update the RAM map in `_gamedefs.k65`.
  `0x80-0xCF` is per-effect scratch (only one effect runs at a time) - initialise it on effect start.
- New files go into `files.lst` with a bank (`core` for effects, `audio` for music), before `main.k65`.
- Keep the style of the user's projects: short register aliases from `_defs.k65`, several statements
  per line, `sync1/sync2/sync3` frame structure, effects as `func` returning via `BreakOnSeq`.
