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
  section-coloured flashing background, playfield scanner line (speed per section, hops on kicks),
  ball = karaoke ball bouncing on the scanner, M0/M1 = spark bursts on kicks.
  The eqsine kernel is 228 lines (limit ~229) and slot line 3 is nearly full - always re-run `make check`.
- `effects/sphere*.k65` (bank4 + data banks 5, 2, 1) - tumbling 3D point objects (`tools/gen_sphere.py` ->
  `effects/sphere_data.k65`, GENERATED - regenerate, don't edit); runtime scales the points (hat pulse), sorts
  them into 15 bands x 5 objects (P0 P1 M0 M1 BL); kick = speed surge.
  Depth: far-side points (bit 7 of the x byte) prefer P1/M1 = dim colour. CPU is tight: point processing is
  split between the idle lines BELOW the objects (next frame; the picture timer is re-armed as TIM64T
  there, the 30 lines ABOVE run sph_music + the live rotation), overscan and vblank (adaptive: stops when
  the RIOT timer runs low, next phase continues) - measure the slack (see docs/project-structure.md) after changes.
  File order in files.lst matters: sphere_defs -> sphere_data -> sphere (far call to a later function crashes K65).
  Shapes per mood (SphModeShape): calm cube, full pyramid (both bank2), breakdown diamond (bank1), build-up sphere
  (bank5). Sphere = precomputed, packed by symmetry: 15 stored points (+ their opposites), 66 frames (frame f+66 =
  f with far bits flipped). Cube, pyramid and diamond are rotated LIVE (cub_/pyr_/dia_setup: rotation matrix by
  quarter-square multiplies above the picture, 3 vertices kept in RAM E4-E5/EC-EF, the rest derived per point
  phase; banks 1 and 2 have the sin tables + the multiply routine at the same fixed address F000-F1E6, called as
  `call LvMul`); points = vertex pairs (midpoints / quarter points).
  Transitions: implosion (into calm moods) / explosion (into energetic ones).
  Logos (bank1): Altair (first verse, grey) and Atari (from song sequence SPH_LOGO_SEQ = 44, red); flat,
  spun around Y at runtime (x = x0*cos via quarter squares), fed through the same sph_place.
  Banks: core = main + music, bank1 diamond + logos, bank2 cube + pyramid (+ plasma if re-enabled - check
  space), bank3 eqsine, bank4 sphere kernel, bank5 sphere data; **bank6 and bank7 are free** (4 KB each).
  Far stub of sph_proc5 is pinned in system_a2600.nut (FIXED_STUBS) at FFC5.
  A bank's code needs CONTIGUOUS free blocks - place big tables at fixed addresses to keep blocks whole.
Enabled in main.k65: sphere -> eqsine.

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
- New files go into `files.lst` with a bank (free: `bank6`, `bank7`; music is in `core`), before `main.k65`.
- Keep the style of the user's projects: short register aliases from `_defs.k65`, several statements
  per line, `sync1/sync2/sync3` frame structure, effects as `func` returning via `BreakOnSeq`.
