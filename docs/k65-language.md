# K65 language - condensed reference

K65 (by KK / Krzysztof Kluczek, devkk.net) is a high-level-looking **assembler** for the 6502.
Every statement maps to one (or a few) 6502 opcodes - there is no hidden code generation,
no expressions evaluated at runtime, no automatic register save. Think "assembly with C-ish
operators". Targets: Atari 2600 (`-system A2600`), Atari 8-bit, C64 (and more via `.nut` scripts).

Sources of truth, in order of reliability:
1. Grammar: `$K65_PATH/src/compiler.inc` (authoritative - the parser is generated from it)
2. Docs: `$K65_PATH/doc/docs/*.md` (= github.com/Krzysiek-K/k65 docs, = devkk.net/wiki/index.php/K65)
3. Examples: `$K65_PATH/examples/a2600-tutorial-0{1,2,3}`, the demos in `../` (sv2019, sv2k21, jp-stream-demo...)

---

## 1. Lexical

- Comments: `// line`, `/* block */`
- Numbers: `123`, `0x7F`, `0b1010`, floats `.5` / `1.25` (floats only meaningful in the evaluator)
- Identifiers: `[a-zA-Z_][a-zA-Z0-9_]*`. `.name` = **local** label/ident (scoped to the section).
- Whitespace/newlines are insignificant; many statements per line is idiomatic:
  `a=anim a<< a&0x30 a?0x30 =={ a=0x10 } y=a`
- `;` is optional (allowed after statements).
- Registers: `a x y s`, flags: `c d i o`(overflow, `v` in branch ops). Upper case also accepted.

## 2. Top-level declarations

```c
var foo = 0x80;            // name for address 0x80 (1 byte)
var bar, baz;              // 0x81, 0x82 (continues after previous var)
var buf[8] = 0x90;         // size 8 -> next var is 0x98
var ptr[2];                // 16-bit pointer (lo, hi)
var dbg ?;                 // '?' = print the address during compile
const K = 5;               // (rarely used) - prefer evaluator constants:
[ SPEED = 3, H = 30 ]      // compile-time constants/variables (floats)
bank core;                 // following code/data goes to bank 'core'
```

**`var` is only an address alias** - it reserves nothing. You maintain the RAM map yourself
(see `_gamedefs.k65`). On the 2600 RAM is `0x80-0xFF` and the stack grows down from `0xFF`.

## 3. Sections

```c
main   { ... }             // entry point (exactly one). Never returns on VCS.
func   name { ... }        // subroutine, RTS appended automatically. Call: just `name` (JSR)
naked  name { ... }        // like func but NO RTS appended
inline name { ... }        // macro, pasted at every use. Call: just `name`
data   name { ... }        // bytes (see 5)
```

- Calling: writing the name of a func emits `JSR name`; of an inline pastes it.
  No parameters - pass via registers/RAM. `return` = RTS, `return_i` = RTI.
- `far name` - call a func that lives in another bank (linker generates bankswitch stub).
  `far goto label` - far jump. Never put `far` inside an inline used from another bank.
- `call addr` = raw `JSR addr`, `goto label` = JMP, `goto (ptr)` = JMP indirect.
  **A `far` call to a function defined later (further down / in a later file) crashes the compiler**
  - define the callee first (order files in files.lst accordingly).
  `goto main` crashes the compiler - put a label (`.full_reset:`) at the top of main and jump to it.
  Jumping into the middle of a loop is fine: `goto fx_enter  { ... fx_enter: ... } always`
  (use a global label if a `far` call sits between the goto and the label).
- A `var` above `0xFF` (e.g. `0x19E`, RAM mirror) is always addressed as absolute (+1 cycle) -
  handy for exact cycle padding.
- Sections are only linked if referenced (dead code is dropped). `-keep name` in files.lst forces it.
- Section options (right after `{`): `align 256`, `align 256+8`, `address 0xF800`, and for
  data also `nocross` (whole block inside one 256-byte page).

## 4. Instructions (register-transfer notation)

`imm` = number / `[expr]` / `&<label` / `&>label`; `mem` = var/label (+/- offset allowed: `ptr+1`).

| 6502 | K65 | notes |
|---|---|---|
| LDA/LDX/LDY | `a=imm` `a=mem` `a=mem,x` `a=mem,y` `a=(zp,x)` `a=(zp),y` / `x=..` / `y=..` | |
| STA/STX/STY | `mem=a` `mem,x=a` `mem,y=a` `(zp),y=a` / `mem=x` / `mem=y` | |
| chain | `cbg=cpf=a=0` | right-to-left: LDA #0, STA cpf, STA cbg |
| TAX TAY TXA TYA TSX TXS | `x=a` `y=a` `a=x` `a=y` `x=s` `s=x` | |
| ADC / SBC | `a+imm` `a+mem,x` ... / `a-...` | **carry is used!** `c- a+1`, `c+ a-1` |
| AND ORA EOR | `a&..` `a\|..` `a^..` | |
| CMP CPX CPY | `a?..` `x?..` `y?..` | sets flags only |
| BIT | `a&?mem` | |
| INC DEC | `mem++` `mem--` `mem,x++` | |
| INX INY DEX DEY | `x++` `y++` `x--` `y--` | |
| ASL LSR ROL ROR | `a<<` `a>>` `a<<<` `a>>>` / `mem<<` ... | `<<<`/`>>>` go through carry |
| SEC CLC SED CLD SEI CLI CLV | `c+` `c-` `d+` `d-` `i+` `i-` `o-` | |
| PHA PLA PHP PLP | `a!!` `a??` `c!!` `c??` | PHP/PLP use any flag letter (`c`,`d`,`i`,`o`) - the word `flag` does NOT work |
| NOP / delay | `*` (2 cyc), `*N` (exactly N cycles, N>=2), `%` (3 cyc) | `*5` = NOP + NOP $80 |
| illegal | `mem=a&x` (SAX) `x&=a-imm` (AXS) `a&.imm` (ANC) `a?--mem` (DCP) `a-++mem` (ISC) | |

`&<label` / `&>label` = low / high byte of an address as immediate:
`ptrA=a=&<Table ptrA+1=a=&>Table`, `a+&>SongPatA` (= `ADC #>SongPatA`).
In data: `&&label` emits a 16-bit little-endian word.

`[expr]` anywhere a number is expected invokes the evaluator: `y=[TEXT_HEIGHT-1]`.

## 5. Control flow (the important, unusual part)

Conditions are **branch operators** that test flags already set by the previous instruction:

| op | 6502 branch taken when | meaning after `a?b` (CMP) |
|---|---|---|
| `==` | BEQ (Z=1) | a == b |
| `!=` | BNE (Z=0) | a != b |
| `>=` | BCS (C=1) | a >= b (unsigned) |
| `<`  | BCC (C=0) | a < b (unsigned) |
| `<0` | BMI (N=1) | negative / bit7 set |
| `>=0`| BPL (N=0) | positive / bit7 clear |
| `>>=`| BVC (V=0) | |
| `<<=`| BVS (V=1) | |
| `c+?` `c-?` `z+?` `z-?` `n+?` `n-?` `v+?` `v-?` | flag set / clear | explicit-flag spelling |

Constructs (`OP` = any branch op above):

```c
OP { ... }                 // IF:  block runs when OP is true (compiles inverted branch over it)
OP { ... } else { ... }    // IF/ELSE
{ ... } OP                 // DO-WHILE: loop back to '{' while OP is true
{ ... } always             // infinite loop (JMP)
{ ... } never              // block executed once (useful with break)
never { ... }              // block skipped (JMP over) - code only reachable via labels
OP goto label              // conditional jump
break / OP break           // jump past the end of the enclosing { } loop
repeat / OP repeat         // jump back to the start of the enclosing loop (continue)
label:  / .local:          // labels
nocross { ... }            // code must not cross a page (stable cycle counts for branches/tables)
```

Typical idioms:

```c
x=10 { wsync x-- }!=                   // wait 10 scanlines
a=INTIM { a=INTIM }!=                  // wait for timer (timwait)
a=cnt a?5 >={ cnt=a=0 }                // if cnt>=5 then cnt=0
y=a a&0x0F ==  { ... } else { ... }
x=0 { a=src,x dst,x=a x++ x?16 }!=     // copy 16 bytes
{ a-15 }>=0                            // divide-by-15 loop (sprite positioning)
```

**Flags are not magic**: `OP` tests whatever the last flag-setting opcode left. Loads,
`x--`, `a&..` set N/Z; `a?..`, shifts, `a+/a-` set C too. Stores (`mem=a`) do not change flags.

## 6. Data blocks

```c
data Name {
    align 256                          // or: nocross / address 0xF100 / align 256+8
    1 2 3 0x40 [2*PI_ISH]              // bytes (values are rounded and & 0xFF)
    &&OtherLabel                       // 16-bit address (lo,hi)
    "TEXT" 0                           // string through current `charset "..."` mapping
    label_inside:                      // extra label inside the block
    for x=0..255 eval [ (sin(x/256*pi*2)*.499+.499)*100 ]  // generated table
    repeat 4 { 1 2 }                   // 1 2 1 2 1 2 1 2
    binary "file.bin"                  // raw file
    code { a=x }                       // assembled code bytes inline in data
    ?                                  // undefined byte (.undef)
}
```

Images (BMP, file name without `.bmp`):
`image "path/file" X0 Y0 <bits><dir> <count><dir> [inv]`
- `<bits><dir>`: how one byte is gathered, starting from MSB: `8>` = 8 pixels to the right,
  `8<` = to the left (handy for PF0/PF2 reversed bit order).
- `<count><dir>`: consecutive bytes: `16v` = 16 bytes going **down** (dy=+1), `30^` = going **up**
  (dy=-1, for kernels that count Y down). (Tutorial comment saying "v = up" is wrong - grammar: `v` is dy=+1.)
- `inv` = dark pixels are 1-bits. `tiles DX DY N` repeats the last image pull N more times shifted by (DX,DY).

Example (PF text, 30 lines, reversed for `y--` kernel):
`data pf1_l { nocross image "data/logo" 4 29 8> 30^ inv }`

## 7. Evaluator (compile time only)

`[ ... ]` - C-like expressions on floats. Top level: `[ H = 30, W = H*2 ]` defines globals.
Inside data: `for x=0..N eval [ expr ]` - `x` (any identifier) is the loop variable.
Statements: `if cond expr`, `if cond a else b`, `while cond expr`, `{ a, b }`, `,` sequences
(value = last), assignments `= += -= *= /= %= |= &= ^= <<= >>=`, `?:`, `?>` (max) `?<` (min),
`pi`, `tab[i]`, `tab[i,j]`. (`evalfunc` exists in the grammar but is a syntax error in SDK 0.2.1 - don't use it.)

Functions: `sin cos asin acos sqrt pow floor ceil round frac min max clamp(x,lo,hi) rnd()`,
`color(r,g,b)` (0..1 floats -> nearest palette value, PAL palette), `color(0xRRGGBB)`,
`print(msg)`, `error(msg)`, `size(section)`, `addbyte(sec,b)`, `index(tab,x[,y])`.

Gotchas: **`<0` and `>=0` are lexed as branch operators even inside `[ ]`** - `q<0 ? ..` crashes
the compiler, write `q < 0` (with spaces). Single letters `a x y s c d i o` (any case) are registers/flags,
never use them as label/var names (`data A {..}` = syntax error). `||` does not parse (the grammar uses `&&` for both levels - avoid logical OR, use `|`
or `?:`). Negative results are fine in data (`& 0xFF` -> two's complement). Constants are floats:
`x/256` is a real division - use `floor()` when you need integers.

## 8. Preprocessor

`#if EXPR` / `#elif` / `#else` / `#endif` (at top level, inside data and inside code),
`#error "msg"`, `#warn "msg"`. `EXPR` = number, evaluator identifier, or `!EXPR`.
Variables can be set from files.lst with a line `DEBUG = 1` (**spaces around `=` required**,
`DEBUG=1` is treated as a file name). `#if` on an undefined name is an error
(`Undeclared eval variable`) - always define the switch (0 or 1).

## 9. files.lst (response file, passed as `k65 @files.lst`)

```
-system A2600            # loads system_a2600.nut (project-local copy wins over SDK workdir)
_defs.k65      core      # <file> <default bank>
music/x.k65    audio
-superchip               # (A2600) enable SC RAM: SCRamWrite=0x1000, SCRamRead=0x1080
-keep name               # force-link an unreferenced section (SDK workdir .nut only)
DEBUG = 1                # compile-time variable (for #if) - spaces around '=' are required
-o bin/demo.bin          # output; also writes .lst (listing), .sym, .gmap
!shell command           # run a command (e.g. emulator) - error if it fails
@other.lst               # include another list
```

Bank names are free-form; the order of **first appearance** defines bank numbers (0,1,...).
`_gamedefs.k65` pre-declares all 8 banks with a dummy data block so numbering is stable.

## 10. Compiler behaviour & debugging

- Success ends with a bank usage table and `All OK.`, exit code 0.
- Undefined label: `Linker: Unknown label 'foo' (line N)`, exit code 1.
- **Syntax errors usually crash the compiler silently** (segfault, exit 139, no message).
  The last `Compiling file: X ...` line tells you which file is broken - bisect by commenting.
  Common causes: unbalanced `{ }`, a bare unknown identifier used as a statement, stray characters,
  `goto main`, `flag!!`. Some errors are reported properly: `Line N: syntax error`.
- On error the Linux build also prints `sh: 1: pause: not found` (it calls Windows `pause`) - harmless.
- `bin/demo.lst` = full listing: every K65 line as a comment followed by generated 6502 asm with
  addresses - the fastest way to verify what your K65 actually compiled to and to count cycles.
- `bin/demo.sym` = symbol addresses (Stella debugger can load it).

## 11. Known bugs (from docs)

- Branch crossing back from the last bank to the previous page can trigger an accidental bankswitch
  (6502 dummy read at 0x1FFx hotspot). Keep code away from the 0xFFF4-0xFFFB area / use `nocross`.
- `far` calls inside inlines break when the inline is expanded in another bank.
- Local labels are not visible across some constructs (e.g. `far` calls).
- Parser can hang/crash on unexpected characters.
