# Project structure & workflow (based on k65-templates/atarivcs-demo-template)

```
k65-vcs-ai-example/
├── makefile             make / make run / make check / make clean
├── files.lst            K65 response file: system, source files + bank, output
├── system_a2600.nut     linker script (banks, far-call stubs, vectors, binary layout) - project copy
├── _defs.k65            short TIA aliases (cbg, pf0, gp0...), init/wsync/timwait/sync1-3 inlines (PAL)
├── _gamedefs.k65        RAM map comment + shared ZP vars (ptrA-D, tmp1-4, song vars) + 8 banks pre-allocated
├── util.k65             SetHorizPos, BreakOnSeq, FxStart/FxUpdate/FxFadeLevel (button + fades)
├── main.k65             entry point: init, then loops the effects
├── effects/rainbow.k65  rainbow background (bank core)
├── effects/plasma.k65   plasma (bank bank2, called with `far plasma`)
├── effects/eqsine.k65   music-reactive sprite helix (bank bank3, `far eqsine`)
├── music/               tracker-style player (music_player_mini.k65) + song data, in bank "audio"
├── tools/vcs_frame_check.py   headless timing checker + frame renderer (py65 via uv)
├── tools/song_analysis.py     plays the whole song headless, prints per-section audio features
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
| `make check` | build + simulate 300 frames headless, FIRE at 60 and 160: lines per frame + `bin/frames.png` |
| `make clean` | remove build output |

Stella >= 6 removed `-propsfile`, so the template's `_makeprops.sh`/`props.cfg` mechanism was
replaced by passing properties on the command line.

## Demo flow

```c
main {
    init                      // clear ZP RAM + TIA, stack = 0xFF
    seqbrk=a=0xFF             // BreakOnSeq never fires (song loops) - effects end on button
    {
        // rainbow            // effect in the same bank: plain call (currently disabled)
        // far plasma         // effect in another bank: far call (currently disabled)
        far eqsine
    } always
}
```

Effect skeleton (copy for new effects, add the file to `files.lst` before `main.k65`):

```c
func my_effect {
    // one-time setup (colours, RAM vars) - we are called from OVERSCAN
    FxStart                       // fade counter = 0, not exiting
    goto my_effect_enter          // skip sync1: the previous effect returned in overscan,
    {                             //  running sync1 again would give a 346-line frame
        sync1                     // overscan: ~34 lines of free time
            far song_player       // music tick (lives in bank "audio")
            BreakOnSeq            // `return` when song reached seqbrk
            FxUpdate              // FIRE/SELECT edge -> fade out -> `return` when black
        my_effect_enter:          // global label (local labels break across `far`)
                                  // (put it after any heavy overscan work: on the switch frame
                                  //  the previous effect already used most of the overscan)
        sync2                     // vblank: ~45 lines of free time -> per-frame logic
            // FxFadeLevel -> A = 0..7, use as palette page offset
        sync3                     // visible: kernel, max ~228 lines of wsync
    } always
}
```

Fading: colour tables have 8 pages (one per fade level, page f = luminance * f/7) and the kernel
reads them through a pointer (`lda (ptr),y`), so a fade is only a change of the pointer high byte.

## RAM map (`_gamedefs.k65`)

- `0x80-0x84` rainbow effect (`rb_phase`, `rb_wave`, `rb_start`, `rb_ptr`)
- `0x88-0x9E` plasma (`pl_ptr[14]`, phases, zoom, kernel counters)
- `0x80-0xCF` eqsine (`eq_x0/x1/c0/c1/en[16]`), `0xE8-0xEF` eqsine state; during the frame
  eqsine reuses the scratch bytes `0xE1-0xE7` + `0xEE` for scanner/ball/spark kernel parameters
- (`0x80-0xCF` is shared per-effect scratch: every effect initialises what it uses)
- `0xDC-0xDF` `mus_v0 mus_f0 mus_v1 mus_f1`, `0xD3-0xD4` `mus_c0 mus_c1` - last AUDV/AUDF/AUDC
  values written by the music player (global, every frame)
- `0xD5-0xDA` eqsine section state (`eq_mode eq_base eq_gain eq_kick eq_pv0 eq_pv1`)
- `0xD0-0xD2` effect switching (`fx_fade`, `fx_state`, `btn_prev`)
- `0xE0-0xE3` `tmp1..tmp4`, `0xE4-0xE7` `ptrC`, `ptrD`
- `0xF0-0xF3` song position (`songpos_seq/step/tick`, `seqbrk`), `0xF4-0xF7` `ptrA`, `ptrB`
- `0xF8-0xFF` stack
Update the map comment when you claim new addresses - `var` does not allocate anything.

## Music

`music/music_player_mini.k65` plays `music/song_mini_sv18.k65` (4 sequences over 2 TIA channels).
`song_player` is called once per frame (`far`, since it's in bank "audio").
Song loops at sequence 102 (`song_seq_wrap`). `seqbrk=a=0xFF` = the effect never ends.
The player also stores what it writes to AUDVx/AUDFx/AUDCx into `mus_v0/f0/c0/v1/f1/c1` - use them for
music-reactive effects.

### Making effects follow the music (lessons from eqsine)

Raw register values make a monotonous picture: this song's bass sits on 2 AUDF values and the
volume is almost constant, so "pitch -> band, volume -> energy" looked the same all the time. What works:
1. Analyse the song: `uv run --with py65 tools/song_analysis.py bin/demo.bin` (~1 min) prints volume,
   attacks, waveforms and AUDF usage per sequence position (88 frames = 1.76 s each, 102 positions).
2. Choreography: a table `songpos_seq -> mode` (sections: calm / full / breakdown / build-up), each mode
   with its own targets (radius, gain, spin, palette). Glide parameters towards targets, flash on change.
3. Map features to *different* visual parameters: melody pitch -> position (remap the AUDF values the
   song really uses to the full screen range), kick (AUDC 15 attack on ch0) -> global pump + spin jolt,
   hats (AUDC 8) -> small flash.
Song structure (this song): 0-15 calm, 16-23 full, 24-31 breakdown, 32-35 build, 36-43 full, 44-51 calm,
52-59 full, 60-67 breakdown, 68-71 calm, 72-75 build, 76-91 full, 92-101 calm outro.
Note the player uses `ptrA`/`ptrB` as scratch - re-set any effect pointers kept there after it runs.

## Verification workflow (for AI agents without a screen)

1. `make` - must end with `All OK.`; a silent exit 139 after `Compiling file: X` = syntax error in X.
2. `make check` - every frame must be **312** lines (PAL), including the effect switch frames.
3. Look at `bin/frames.png` (Read tool can display it): rendered background of selected frames,
   mid-line COLUBK writes included (pixel = 3*cycle-68), playfield (PF0-2, reflect), players P0/P1
   and missiles M0/M1 (RES/HM/HMOVE/GRP/ENAM/COLUP/NUSIZ size). Not simulated: ball, score mode,
   PF priority, VDEL, sprite copies. TIA writes are timed at the end of the instruction.
   `--press a,b` holds FIRE for 3 frames at those frames, `--show x,y` picks rendered frames.
4. Inspect `bin/demo.lst` to confirm generated 6502 code / cycle counts of the kernel loop.
5. The user runs `make run` for the real picture + sound.
