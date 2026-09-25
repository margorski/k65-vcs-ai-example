# Project structure & workflow (based on k65-templates/atarivcs-demo-template)

```
k65-vcs-ai-example/
├── makefile             make / make run / make check / make clean
├── files.lst            K65 response file: system, source files + bank, output
├── system_a2600.nut     linker script (banks, far-call stubs, vectors, binary layout) - project copy
├── _defs.k65            short TIA aliases (cbg, pf0, gp0...), init/wsync/timwait/sync1-3 inlines (PAL)
├── _gamedefs.k65        RAM map comment + shared ZP vars (ptrA-D, tmp1-4, song vars) + 8 banks pre-allocated
├── util.k65             SetHorizPos (sprite X positioning), BreakOnSeq (end effect at song position)
├── main.k65             entry point: init, then runs effects in sequence
├── effects/rainbow.k65  the rainbow background effect
├── music/               tracker-style player (music_player_mini.k65) + song data, in bank "audio"
├── tools/vcs_frame_check.py   headless timing/colour checker (py65 via uv)
├── docs/                this knowledge base
└── bin/                 build output: demo.bin (32K F4), demo.lst, demo.sym, demo.gmap, frames.png
```

## Build

Requirements: `K65_PATH` env var -> K65 SDK root (here `~/Projects/Programowanie/Demoscene/tools/k65`),
compiler binary at `$K65_PATH/workdir/k65.exe` (it is a Linux ELF despite the name), `stella` in PATH.
`make check` also needs `uv` (fetches py65 + pillow on the fly).

| command | what it does |
|---|---|
| `make` | compile `bin/demo.bin` (only if sources changed) |
| `make run` | build + run in Stella (`-format PAL -bs F4 -pp NO`) |
| `make check` | build + simulate 8 frames headless: prints lines per frame, writes `bin/frames.png` |
| `make clean` | remove build output |

Stella >= 6 removed `-propsfile`, so the template's `_makeprops.sh`/`props.cfg` mechanism was
replaced by passing properties on the command line.

## Demo flow (same pattern as all the user's demos)

```c
main {
    .full_reset:
    init                      // clear ZP RAM + TIA, stack = 0xFF
    {
        seqbrk=a=16           // effect runs until song sequence position >= seqbrk
        effect_one            // each effect = func with its own `{ sync1 .. sync2 .. sync3 .. } always`
        seqbrk=a=32
        effect_two
        goto .full_reset
    } always
}
```

Effect skeleton (copy for new effects, add the file to `files.lst` before `main.k65`):

```c
func my_effect {
    // one-time setup (colours, RAM vars)
    {
        sync1                 // overscan: ~34 lines of free time
            far song_player   // music tick (lives in bank "audio")
            BreakOnSeq        // `return` when song reached seqbrk
        sync2                 // vblank: ~45 lines of free time -> per-frame logic
        sync3                 // visible: kernel, max ~228 lines of wsync
    } always
}
```

## RAM map (`_gamedefs.k65`)

- `0x80-0x82` rainbow effect (`rb_phase`, `rb_wave`, `rb_start`)
- `0xE0-0xE3` `tmp1..tmp4`, `0xE4-0xE7` `ptrC`, `ptrD`
- `0xF0-0xF3` song position (`songpos_seq/step/tick`, `seqbrk`), `0xF4-0xF7` `ptrA`, `ptrB`
- `0xF8-0xFF` stack
Update the map comment when you claim new addresses - `var` does not allocate anything.

## Music

`music/music_player_mini.k65` plays `music/song_mini_sv18.k65` (4 sequences over 2 TIA channels).
`song_player` is called once per frame (`far`, since it's in bank "audio").
Song loops at sequence 102 (`song_seq_wrap`). `seqbrk=a=0xFF` = the effect never ends.

## Verification workflow (for AI agents without a screen)

1. `make` - must end with `All OK.`; a silent exit 139 after `Compiling file: X` = syntax error in X.
2. `make check` - every frame must be **312** lines (PAL). Visible should stay 230.
3. Look at `bin/frames.png` (Read tool can display it): one column per frame = background colour
   of each scanline. Only COLUBK is simulated (no playfield/sprites).
4. Inspect `bin/demo.lst` to confirm generated 6502 code / cycle counts of the kernel loop.
5. The user runs `make run` for the real picture + sound.
