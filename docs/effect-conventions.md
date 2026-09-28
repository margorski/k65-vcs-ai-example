# Effect conventions: banks, RAM, timing, naming

Rules for adding or changing an effect without breaking the others. Background: `project-structure.md`
(build, effect skeleton, verification), `k65-language.md` (syntax, compiler gotchas).

## 1. Bank manifest

F4 cartridge: 8 banks of 4 KB, all mapped at F000-FFFF, **only one visible at a time**.
Numbers from `make report` (commit ae733a3) - re-run it, they change with every edit.

| bank | contents | used | free (largest block) |
|---|---|---|---|
| core  | main, music player + song, util (fx switching), rainbow (disabled) | 2593 | 1503 (1170) |
| bank1 | shapes: dot engine - `shape_live_points`, logos, point list, placement tables (FC00-FFC4) | 2730 | 1366 (1325) |
| bank2 | shapes: rotation - `*_setup`, `shape_mul` + shared `shape_angles(_g)` / `shape_col1`, sin / square tables; plasma (disabled) | 1971 | 2125 (2115) |
| bank3 | eqsine (disabled) | 19 | 4077 |
| bank4 | shapes: effect + kernel (`shapes`), `ShapeLum` (F400-F5FF) | 1909 | 2187 (1227) |
| bank5 | shapes: sphere - animation (F100), `sphere_points`, placement tables (FC00-FFC4) | 3274 | 822 (533) |
| bank6 | free | 19 | 4077 |
| bank7 | free | 19 | 4077 |

Every bank also holds the reset stub + vectors (FFF4-FFFF area) and the far-call stubs it needs.
Disabled effects cost nothing: the linker drops every section nothing references, so an effect that
is commented out in `main.k65` can stay in `files.lst` (it keeps compiling).

## 2. Placing code and data

- **Hot data lives in the bank of the code that reads it.** Code can read only its own bank (and RAM).
  Per-point / per-line tables go next to their loop; data other banks need goes through RAM.
- **Far calls are coarse: once per frame or per phase, never per point / per line.** A `far` call
  costs ~32 cycles (stub: `BIT` bank select, `JSR`, `BIT` back, `RTS`) and **4 bytes of stack**.
- **Stack budget: F8-FF = 8 bytes**, and it is already exceeded on purpose: main -> `far shapes` ->
  `far pyramid_setup` -> `call shape_col1` -> `call shape_mul` = 12 bytes (F4-F7 = ptrA/ptrB, free
  at that moment - the rotation keeps its scratch elsewhere). Adding a call level anywhere needs a
  check of what lives below F4 (`make stats` prints the deepest SP).
- **Avoid code shared by several banks.** An `inline` expanded in two banks needs its tables in both
  banks at the SAME fixed address (`var Name = 0x....` in the code, `data Name5 { address ... }` in
  each bank, kept linked by a `never { a=Name5 }` reference). The shapes do this only for the
  placement tables (bank1 + bank5). `make report` lists every copied section.
- **A function must fit into ONE contiguous free block** (`make report`: largest free block). Put big
  tables at fixed addresses at the start or end of a bank so the free space stays in one piece.
- **Reserved addresses:** FFC5-FFEC in bank5 (and the same range in bank4) for the pinned far stub of
  `sphere_points` (`FIXED_STUBS` in `system_a2600.nut`: bank5 is nearly full, a stub placed by the
  allocator could split its last free block); the hotspots FFF4-FFFB must never be read by accident
  (keep code away, use `nocross`). Other far stubs are placed by the linker at an address free in
  BOTH banks - keep some space free in every bank.
- **File order in `files.lst`:** definitions (`var`, `[ ]` constants, inlines) before their users;
  a `far` call to a function defined LATER crashes the compiler, and an inline that calls a later
  func must write `call name`. Label names are global across banks (the same name twice = crash).
  Order per effect: defs -> generated data -> shared code -> parts -> the effect's entry file,
  all before `main.k65`.

## 3. RAM contract

128 bytes, 80-FF. `var` allocates nothing - the map comment in `_gamedefs.k65` is the allocation.

| bytes | owner | lifetime / who may write |
|---|---|---|
| F8-FF | stack | always (8 bytes, see above) |
| F0-F3 | song position (`songpos_seq/step/tick`, `seqbrk`) | global - only the player / main |
| D0-D2 | effect switching (`fx_fade`, `fx_state`, `btn_prev`) | global - only util.k65 |
| D3-D4, DC-DF | `mus_c0/c1`, `mus_v0/f0/v1/f1`: the player's last AUDC/AUDV/AUDF | written by the player every overscan; read-only for effects, except: after an effect has read them in a frame (or if it never reads them) it may use them as scratch until the next player call - the shapes use D3-D4 (rotation angles) after `shape_music`, and DD / DF |
| E0-E3 | `tmp1..tmp4` | scratch, inside one routine / one phase |
| E4-E7 | `ptrC`, `ptrD` | effect-owned (shapes keep vertices / the scale pointer there) |
| F4-F7 | `ptrA`, `ptrB` | scratch - **the music player overwrites them in overscan** |
| 80-CF | per-effect | effect-owned while it runs; **initialise on effect start** |
| D5-DB, E8-EF | per-effect | effect-owned while it runs (eqsine and shapes both use them) |

Lifetimes to state for every variable (in its comment):
- **frame**: kept from frame to frame (e.g. `shape_frame`, `shape_pv0`) - must not be scratch anywhere;
- **phase**: kept between two player calls (overscan, vblank, picture) - may live in `ptrA/B`,
  `DD/DF`, but must be rebuilt at the start of each phase (e.g. the shapes' derived vertices v3-v5);
- **scratch**: inside one routine.
The same byte can have several owners in different parts of the frame (shapes: E6 = `ptrD` during
the points, `cube_t2` in the rotation above the picture) - write both into the comments.

## 4. Timing budget (PAL, `_defs.k65`)

| phase | timer | CPU time | runs |
|---|---|---|---|
| overscan | `TIM64T 40` | ~2500 cycles | `far song_player`, `FxUpdate`, effect work |
| vblank | `TIM64T 54` | ~3400 cycles | effect per-frame logic |
| picture | `T1024T 18` | ~229 lines of `wsync` | kernel; lines without output are free CPU time |

- Every phase must end with slack > ~100 cycles (`make stats`: min slack, overruns must be 0);
  an overrun can make `timwait` miss the 0 and add 15-25 lines.
- Heavy work that does not fit: split it over phases and **time-slice it on the RIOT timer** (shapes:
  `a=INTIM a?shape_tmin <{ goto .done }` before every point, the next phase continues from the saved
  index). Blank picture lines can be used the same way with `TIM64T` instead of counted lines.
- The effect switch frame: the effect is entered from the previous effect's overscan -> start with
  `goto <name>_enter` just before `sync2` (skeleton in `project-structure.md`), otherwise 346 lines.

## 5. Naming

- An effect = `effects/<effect>/` (or one file for a small effect), entry `func <effect>`, called from
  `main.k65` with `far <effect>`.
- Shared code of the effect: files `<prefix>_*.k65`, names `<prefix>_*` (code, vars), `<Prefix>*`
  (tables), `<PREFIX>_*` (constants). Parts of the effect (shapes: sphere, cube, ...): their own file
  and their own prefix (`cube_*`, `Cube*`, `CUBE_*`).
- K65 style of the project: short register aliases from `_defs.k65`, several statements per line,
  `sync1/sync2/sync3` frame structure.
- Generated files end in `_data.k65`, start with a `GENERATED by tools/... - do not edit` header and
  contain only data (code stays hand-written).

## 6. Checklists

**New effect**
1. Files + `files.lst` lines (bank per file, before `main.k65`, order as in section 2); pick banks
   from the manifest (bank3, bank6, bank7 are free).
2. Skeleton from `project-structure.md` (`FxStart`, `goto <name>_enter`, `FxUpdate` in overscan).
3. Claim RAM: update the map comment in `_gamedefs.k65` + section 3; initialise 80-CF on start.
4. `far <name>` in `main.k65`.
5. Verify: `make` (`All OK.`), `make check` (312 lines everywhere, look at `bin/frames.png`),
   `make stats` if the effect is time-sliced or heavy, `make report` (free space, no new copies).
6. Update this manifest and `CLAUDE.md`.

**New live shape (shapes effect)**
1. `effects/shapes/<shape>.k65`: `<shape>_rotate` (writes vertices v0..v2 in the rotation bank, uses
   `shape_math`), `func <shape>_setup`, optionally `<shape>_prep` (derived vertices v3..v5 per phase).
2. `tools/gen_shapes.py`: its vertices, point list and vertex id map in `SHAPES` (-> `<SHAPE>_I0`);
   regenerate with `python3 tools/gen_shapes.py`.
3. `shape_defs.k65`: a `SHAPE_<NAME>` id (+ `ShapeModeShape` if a mood should use it);
   `shapes.k65`: the setup dispatch and `ShapeI0`; `shape_live.k65`: the prep dispatch.
4. Verify as above; `make stats` splits the slack by shape (`shape_cur`).
