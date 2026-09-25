# k65-vcs-ai-example

Atari 2600 (VCS) demo written in **K65** - a custom 6502 assembler with its own, very
non-standard syntax (`a=5 cbg=a`, `{ ... }!=` loops, `x?10 >={ }` conditions).
Do not write DASM/ca65 syntax here. Target: **PAL**, 312 lines/frame, 32K F4 ROM.
The effect: scrolling, sine-wobbled rainbow background (`effects/rainbow.k65`).

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
- `make check` - headless: lines per frame for 8 frames (must be 312) + `bin/frames.png` background colours
- `make clean`

## Rules

- After every change: `make` (expect `All OK.`), then `make check` (expect 312 everywhere).
- Kernel loop per scanline <= 76 cycles; picture kernel <= ~228 `wsync`s; check `bin/demo.lst`.
- New RAM variables: pick free addresses and update the RAM map in `_gamedefs.k65`.
- New files go into `files.lst` with a bank (`core` for effects, `audio` for music), before `main.k65`.
- Keep the style of the user's projects: short register aliases from `_defs.k65`, several statements
  per line, `sync1/sync2/sync3` frame structure, effects as `func` returning via `BreakOnSeq`.
