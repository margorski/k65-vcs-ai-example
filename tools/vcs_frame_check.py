#!/usr/bin/env python3
"""Headless Atari 2600 frame checker (no GUI, no Stella needed).

Runs a VCS ROM on a 6502 core (py65), emulating only what matters for
frame timing: WSYNC, VSYNC, VBLANK, COLUBK, the RIOT timer and F8/F6/F4
bankswitching. Prints scanline counts per frame and can render selected frames
to a PNG: background (COLUBK, including mid-scanline writes) and players P0/P1
(RESPx, HMPx+HMOVE, GRPx, COLUPx, NUSIZx size 1x/2x/4x, P0 above P1),
missiles M0/M1 (RESMx, HMMx, ENAMx, width), the ball (RESBL, HMBL, ENABL, width)
and the playfield (PF0-2, reflect, COLUPF).

It does NOT emulate score mode/PF priority/audio/VDEL/sprite copies - it is a timing +
picture sanity check, meant to be run by humans or AI agents after `make`.

Usage (py65 is fetched on the fly by uv):
    uv run --with py65 --with pillow tools/vcs_frame_check.py bin/demo.bin \
        [--frames 8] [--png bin/frames.png] [--show 0,4,7] [--press 60,200]

  --press N,M   hold FIRE for 3 frames starting at frames N, M (tests effect switching)
  --show a,b    frames rendered into the PNG (default: 4 evenly spaced frames)
  --stats       CPU slack per frame phase (timwait polling time: overscan / vblank / picture),
                deepest stack use, and the values of --sample RAM bytes at each picture start
  --sample CF   RAM addresses (hex) sampled when the picture starts (VBLANK off), e.g. how many
                points a time-sliced routine finished in the frame
  --group DB    split the slack stats by the value of this RAM byte at picture start (e.g. a mode)
"""
import argparse
import sys

from py65.devices.mpu6502 import MPU

LINE_CYCLES = 76            # CPU cycles per scanline
HBLANK_CYCLES = 23          # ~68 colour clocks / 3

# PAL palette used by K65 color() (tools/k65/src/coltab_pal.h), index = value>>1
PAL = [
    0x000000, 0x282828, 0x505050, 0x747474, 0x949494, 0xb4b4b4, 0xd0d0d0, 0xececec,
    0x000000, 0x282828, 0x505050, 0x747474, 0x949494, 0xb4b4b4, 0xd0d0d0, 0xececec,
    0x805800, 0x947020, 0xa8843c, 0xbc9c58, 0xccac70, 0xdcc084, 0xecd09c, 0xfce0b0,
    0x445c00, 0x5c7820, 0x74903c, 0x8cac58, 0xa0c070, 0xb0d484, 0xc4e89c, 0xd4fcb0,
    0x703400, 0x885020, 0xa0683c, 0xb48458, 0xc89870, 0xdcac84, 0xecc09c, 0xfcd4b0,
    0x006414, 0x208034, 0x3c9850, 0x58b06c, 0x70c484, 0x84d89c, 0x9ce8b4, 0xb0fcc8,
    0x700014, 0x882034, 0xa03c50, 0xb4586c, 0xc87084, 0xdc849c, 0xec9cb4, 0xfcb0c8,
    0x005c5c, 0x207474, 0x3c8c8c, 0x58a4a4, 0x70b8b8, 0x84c8c8, 0x9cdcdc, 0xb0ecec,
    0x70005c, 0x842074, 0x943c88, 0xa8589c, 0xb470b0, 0xc484c0, 0xd09cd0, 0xe0b0e0,
    0x003c70, 0x1c5888, 0x3874a0, 0x508cb4, 0x68a4c8, 0x7cb8dc, 0x90ccec, 0xa4e0fc,
    0x580070, 0x6c2088, 0x803ca0, 0x9458b4, 0xa470c8, 0xb484dc, 0xc49cec, 0xd4b0fc,
    0x002070, 0x1c3c88, 0x3858a0, 0x5074b4, 0x6888c8, 0x7ca0dc, 0x90b4ec, 0xa4c8fc,
    0x3c0080, 0x542094, 0x6c3ca8, 0x8058bc, 0x9470cc, 0xa884dc, 0xb89cec, 0xc8b0fc,
    0x000088, 0x20209c, 0x3c3cb0, 0x5858c0, 0x7070d0, 0x8484e0, 0x9c9cec, 0xb0b0fc,
    0x000000, 0x282828, 0x505050, 0x747474, 0x949494, 0xb4b4b4, 0xd0d0d0, 0xececec,
    0x000000, 0x282828, 0x505050, 0x747474, 0x949494, 0xb4b4b4, 0xd0d0d0, 0xececec,
]

# TIA write registers recorded for analysis/rendering
TRACKED = {0x00, 0x01, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0D, 0x0E, 0x0F,
           0x10, 0x11, 0x12, 0x13, 0x14, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F,
           0x20, 0x21, 0x22, 0x23, 0x24, 0x2A, 0x2B}

# bankswitch schemes by ROM size: (first hotspot, bank count)
SCHEMES = {2048: None, 4096: None, 8192: (0x1FF8, 2), 16384: (0x1FF6, 4), 32768: (0x1FF4, 8)}


class VCS:
    def __init__(self, rom):
        if len(rom) not in SCHEMES:
            sys.exit(f"unsupported ROM size {len(rom)}")
        self.rom = rom
        self.scheme = SCHEMES[len(rom)]
        self.bank = self.scheme[1] - 1 if self.scheme else 0
        self.ram = bytearray(128)
        self.mpu = None
        self.op_len = 0     # cycle length of the instruction being executed
        self.wsync = False
        self.timer_start = 0
        self.timer_value = 0
        self.timer_shift = 10
        self.events = []    # (cycle, register, value) for VSYNC/VBLANK/COLUBK
        self.frame = 0      # counted on VSYNC rising edges
        self.vsync = False
        self.pressed = set()  # frames with FIRE held
        # --stats: timwait slack per phase, stack depth, RAM samples at picture start
        self.pc = 0         # address of the instruction being executed
        self.phase = "?"    # overscan / vblank / picture
        self.phase_waits = 0
        self.slack = {}     # phase label -> [slack cycles], negative = overrun
        self.min_sp = 0xFF
        self.min_sp_at = None
        self.sample = []    # RAM addresses to sample
        self.samples = []   # one tuple per picture start
        self.group = None   # RAM address: slack stats split by its value
        self.group_key = ""

    # --- py65 memory interface ---
    def __len__(self):
        return 0x10000

    def cycles(self):
        # py65 adds an instruction's cycles only after executing it; TIA/RIOT accesses
        # happen on the instruction's last cycle, so report the end of the current instruction
        return self.mpu.processorCycles + self.op_len if self.mpu else 0

    def _hotspot(self, a):
        if self.scheme:
            first, count = self.scheme
            if first <= a < first + count:
                self.bank = a - first

    def __getitem__(self, addr):
        a = addr & 0x1FFF
        if a & 0x1000:
            self._hotspot(a)
            if len(self.rom) == 2048:
                return self.rom[a & 0x7FF]
            return self.rom[self.bank * 4096 + (a & 0xFFF)]
        if not a & 0x80:                        # TIA read
            if (a & 0x0F) == 0x0C:              # INPT4: bit7 = 0 when FIRE pressed
                return 0x00 if self.frame in self.pressed else 0x80
            return 0x80 if (a & 0x0F) == 0x0D else 0x00
        if not a & 0x200:                       # RAM
            return self.ram[a & 0x7F]
        reg = a & 0x07                          # RIOT
        if reg == 0:
            return 0xFF                         # SWCHA: no joystick input
        if reg == 2:
            return 0x0B                         # SWCHB: colour, no switches
        if reg in (4, 6):
            value = self._intim()
            self._timwait_read(value)
            return value
        return 0

    def _set_phase(self, phase):
        self.phase, self.phase_waits, self.wait_start = phase, 0, None

    def _underflowed(self):
        return self.cycles() - self.timer_start > self.timer_value << self.timer_shift

    def _is_timwait(self, pc):
        """LDA INTIM (abs or zp) followed by BNE back to it = a timwait polling loop"""
        rd = lambda a: self.rom[self.bank * 4096 + (a & 0xFFF)] if len(self.rom) > 2048 else self.rom[a & 0x7FF]
        n = {0xAD: 3, 0xA5: 2}.get(rd(pc))
        if not n or rd(pc + n) != 0xD0:
            return False
        off = rd(pc + n + 1)
        return pc + n + 2 + (off - 256 if off & 0x80 else off) == pc

    def _timwait_read(self, value):
        """a timwait loop read the timer: its first read starts the wait, the 0 ends it"""
        if not self._is_timwait(self.pc):
            return
        start = getattr(self, "wait_start", None)
        if start is None or start[0] != self.pc:
            start = (self.pc, self.cycles(), self._underflowed())
            self.wait_start = start
        if value == 0 or start[2]:                  # done (or started too late = overrun)
            self.phase_waits += 1
            label = self.phase + (str(self.phase_waits) if self.phase == "picture" else "") + self.group_key
            slack = -1 if start[2] else self.cycles() - start[1]
            if self.frame > 2:                      # skip the start-up frames
                self.slack.setdefault(label, []).append(slack)
            self.wait_start = None

    def __setitem__(self, addr, value):
        a = addr & 0x1FFF
        if a & 0x1000:
            self._hotspot(a)
            return
        if not a & 0x80:                        # TIA write
            reg = a & 0x3F
            if reg == 0x02:
                self.wsync = True
            elif reg in TRACKED:
                self.events.append((self.cycles(), reg, value))
                if reg == 0x00:
                    if value & 2 and not self.vsync:
                        self.frame += 1
                        self._set_phase("vblank")
                    self.vsync = bool(value & 2)
                elif reg == 0x01:
                    if value & 2:
                        if self.phase == "picture":
                            self._set_phase("overscan")
                    elif self.phase != "picture":
                        self._set_phase("picture")
                        self.samples.append(tuple(self.ram[a & 0x7F] for a in self.sample))
                        if self.group is not None:
                            self.group_key = f" [{self.ram[self.group & 0x7F]}]"
            return
        if not a & 0x200:
            self.ram[a & 0x7F] = value
            return
        if a & 0x14 == 0x14:                    # TIM1T/TIM8T/TIM64T/T1024T
            self.timer_value = value
            self.timer_start = self.cycles()
            self.timer_shift = (0, 3, 6, 10)[a & 3]

    def _intim(self):
        elapsed = self.cycles() - self.timer_start
        ticks = (elapsed - 1) >> self.timer_shift if elapsed > 0 else -1
        value = self.timer_value - 1 - ticks
        if value >= 0:
            return value
        # after underflow the timer counts down once per cycle
        underflow_at = self.timer_start + 1 + (self.timer_value << self.timer_shift)
        return (0xFF - (self.cycles() - underflow_at)) & 0xFF

    def run(self, max_cycles):
        self.mpu = MPU(memory=self, pc=None)
        self.mpu.reset()
        self.mpu.pc = self.mpu.WordAt(0xFFFC)
        while self.mpu.processorCycles < max_cycles:
            pc = self.mpu.pc
            op = self.rom[(pc & 0x7FF) if len(self.rom) == 2048 else self.bank * 4096 + (pc & 0xFFF)]
            self.op_len = self.mpu.cycletime[op]
            self.pc = pc
            self.mpu.step()
            if self.mpu.sp < self.min_sp:
                self.min_sp, self.min_sp_at = self.mpu.sp, (self.bank, pc, self.frame)
            self.op_len = 0
            if self.wsync:
                self.wsync = False
                c = self.mpu.processorCycles
                self.mpu.processorCycles = -(-c // LINE_CYCLES) * LINE_CYCLES


def analyse(events, total_cycles):
    """Split the event log into frames (VSYNC rising edges) and measure them."""
    frames = []
    vsync_on = False
    for cyc, reg, val in events:
        if reg == 0x00:
            on = bool(val & 2)
            if on and not vsync_on:
                frames.append({"start": cyc, "vsync_end": None, "vis": []})
            elif not on and vsync_on and frames:
                frames[-1]["vsync_end"] = cyc
            vsync_on = on
        elif reg == 0x01 and frames:
            frames[-1]["vis"].append((cyc, not (val & 2)))
    for i, f in enumerate(frames):
        end = frames[i + 1]["start"] if i + 1 < len(frames) else None
        f["end"] = end
        f["lines"] = round((end - f["start"]) / LINE_CYCLES) if end else None
        vis_start = next((c for c, on in f["vis"] if on), None)
        vis_end = next((c for c, on in f["vis"] if not on and vis_start and c > vis_start), None)
        f["vis_start"], f["vis_end"] = vis_start, vis_end
    return [f for f in frames if f["end"]]


def timeline(events, reg):
    """[(cycle, value)] of all writes to one TIA register."""
    return [(c, v) for c, r, v in events if r == reg]


def value_at(tl, cycles, t, default=0):
    import bisect
    i = bisect.bisect_right(cycles, t) - 1
    return tl[i][1] if i >= 0 else default


def object_positions(events):
    """Per object (P0, P1, M0, M1, BL): [(cycle, x)] - RESxx sets the position, HMOVE applies HMxx."""
    pos = [0, 0, 0, 0, 0]
    hm = [0, 0, 0, 0, 0]
    out = [[(0, 0)] for _ in range(5)]
    for c, r, v in events:
        if 0x10 <= r <= 0x14:
            o = r - 0x10
            cc = (c - (c // LINE_CYCLES) * LINE_CYCLES) * 3         # colour clock at the end of the STA
            off = 5 if o < 2 else 4                                   # players +5, missiles/ball +4
            pos[o] = (cc - 68 + off) % 160 if cc >= 68 else off - 2  # (classic PosObject -> pixel = A)
            out[o].append((c, pos[o]))
        elif 0x20 <= r <= 0x24:
            hm[r - 0x20] = v
        elif r == 0x2B:
            hm = [0, 0, 0, 0, 0]
        elif r == 0x2A:
            for o in range(5):
                m = hm[o] >> 4
                m = m - 16 if m >= 8 else m
                pos[o] = (pos[o] - m) % 160
                out[o].append((c, pos[o]))
    return out


def render_frame(events, first_line, height):
    """Pixel colours of `height` lines starting at absolute line `first_line`.
    A write lands on the pixel the beam is at during the last cycle of the STA
    (3 colour clocks per CPU cycle, 68 clocks of HBLANK)."""
    import bisect
    colubk = timeline(events, 0x09)
    cycles = [c for c, _ in colubk]
    rows = []
    for y in range(height):
        line_start = (first_line + y) * LINE_CYCLES
        i = bisect.bisect_right(cycles, line_start) - 1
        col = colubk[i][1] if i >= 0 else 0
        row = [col] * 160
        i += 1
        while i < len(colubk) and colubk[i][0] < line_start + LINE_CYCLES:
            px = (colubk[i][0] - line_start) * 3 - 68            # event cycle = end of the STA
            col = colubk[i][1]
            for x in range(max(px, 0), 160):
                row[x] = col
            i += 1
        rows.append(row)

    tl = {r: timeline(events, r) for r in TRACKED}
    tc = {r: [c for c, _ in tl[r]] for r in TRACKED}

    def reg(r, t):
        return value_at(tl[r], tc[r], t)

    # playfield (behind all objects): 40 PF pixels of 4 px, right half repeated or reflected
    for y in range(height):
        line_start = (first_line + y) * LINE_CYCLES
        for k in range(40):
            t = line_start + (k * 4 + 68) // 3
            i = k if k < 20 else (39 - k if reg(0x0A, t) & 1 else k - 20)
            if i < 4:
                bit = reg(0x0D, t) >> (4 + i) & 1
            elif i < 12:
                bit = reg(0x0E, t) >> (11 - i) & 1
            else:
                bit = reg(0x0F, t) >> (i - 12) & 1
            if bit:
                col = reg(0x08, t)
                for x in range(k * 4, k * 4 + 4):
                    rows[y][x] = col

    positions = object_positions(events)

    # ball: same layer and colour as the playfield, width from CTRLPF bits 4-5
    bl, blc = positions[4], [c for c, _ in positions[4]]
    for y in range(height):
        line_start = (first_line + y) * LINE_CYCLES
        x0 = value_at(bl, blc, line_start + LINE_CYCLES)
        t = line_start + (x0 + 68) // 3
        if reg(0x1F, t) & 2:
            for k in range(1 << ((reg(0x0A, t) >> 4) & 3)):
                rows[y][(x0 + k) % 160] = reg(0x08, t)

    # objects, lowest priority first: M1, P1, M0, P0 (P0/M0 above P1/M1)
    for o in (3, 1, 2, 0):
        p = o & 1                                                  # colour/NUSIZ of player 0 or 1
        pl, plc = positions[o], [c for c, _ in positions[o]]
        for y in range(height):
            line_start = (first_line + y) * LINE_CYCLES
            x0 = value_at(pl, plc, line_start + LINE_CYCLES)
            t = line_start + (x0 + 68) // 3                          # beam reaches the object
            nus = reg(0x04 + p, t)
            c = reg(0x06 + p, t)
            if o < 2:
                g = reg(0x1B + p, t)
                w = {5: 2, 7: 4}.get(nus & 7, 1)
                for bit in range(8):
                    if g & (0x80 >> bit):
                        for k in range(w):
                            rows[y][(x0 + bit * w + k) % 160] = c
            elif reg(0x1D + p, t) & 2:
                for k in range(1 << ((nus >> 4) & 3)):
                    rows[y][(x0 + k) % 160] = c
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rom")
    ap.add_argument("--frames", type=int, default=8, help="frames to simulate (default 8)")
    ap.add_argument("--png", help="render background of selected frames to this PNG")
    ap.add_argument("--show", help="comma separated frame numbers to render (default: 4 evenly spaced)")
    ap.add_argument("--press", default="", help="comma separated frames where FIRE is pressed (held 3 frames)")
    ap.add_argument("--expect", type=int, default=312, help="expected lines per frame (PAL 312, NTSC 262)")
    ap.add_argument("--stats", action="store_true", help="CPU slack per phase, stack depth, RAM samples")
    ap.add_argument("--sample", default="", help="comma separated RAM addresses (hex) sampled at picture start")
    ap.add_argument("--group", help="RAM address (hex): split the slack stats by its value")
    args = ap.parse_args()

    rom = open(args.rom, "rb").read()
    vcs = VCS(rom)
    for f in filter(None, args.press.split(",")):
        vcs.pressed.update(range(int(f), int(f) + 3))
    vcs.sample = [int(a, 16) for a in filter(None, args.sample.split(","))]
    vcs.group = int(args.group, 16) if args.group else None
    vcs.run((args.frames + 2) * 330 * LINE_CYCLES)
    frames = analyse(vcs.events, vcs.mpu.processorCycles)[: args.frames]
    if not frames:
        sys.exit("no complete frames found (VSYNC never toggled?)")

    L = LINE_CYCLES
    bad = 0
    verbose = len(frames) <= 16
    print("frame  lines  vsync  top(vblank)  visible  bottom(overscan)")
    for i, f in enumerate(frames):
        vsync = round((f["vsync_end"] - f["start"]) / L) if f["vsync_end"] else 0
        top = round((f["vis_start"] - f["vsync_end"]) / L) if f["vis_start"] and f["vsync_end"] else "?"
        vis = round((f["vis_end"] - f["vis_start"]) / L) if f["vis_end"] and f["vis_start"] else "?"
        bot = round((f["end"] - f["vis_end"]) / L) if f["vis_end"] else "?"
        wrong = f["lines"] != args.expect
        bad += wrong
        if verbose or wrong:
            flag = "   <-- expected %d" % args.expect if wrong else ""
            print(f"{i:5}  {f['lines']:5}  {vsync:5}  {top!s:>11}  {vis!s:>7}  {bot!s:>16}{flag}")
    if not verbose:
        print(f"  ... {len(frames)} frames simulated, {len(frames) - bad} with {args.expect} lines, {bad} wrong")

    if args.stats or vcs.sample or args.group:
        print("\nCPU slack = cycles spent polling the timer at the end of a phase (frames 3+):")
        print("  phase              waits    min    avg   overruns")
        for label in sorted(vcs.slack):
            v = vcs.slack[label]
            ok = [x for x in v if x >= 0]
            print(f"  {label:16} {len(v):7} {min(ok) if ok else '-':>6} {sum(ok) // max(len(ok), 1):>6} {len(v) - len(ok):>8}")
        slot, pc, frame = vcs.min_sp_at or (0, 0, 0)
        # K65 system_a2600.nut writes an 8-bank image as banks 4 5 2 3 0 1 6 7 (F4 hotspot order)
        bank = [4, 5, 2, 3, 0, 1, 6, 7][slot] if len(rom) == 32768 else slot
        print(f"deepest stack: SP = ${vcs.min_sp:02X} ({0xFF - vcs.min_sp} bytes used)"
              f" at ${pc:04X} in bank {bank}, frame {frame}")
        from collections import Counter
        for k, a in enumerate(vcs.sample):
            c = Counter(s[k] for s in vcs.samples[3:])
            print(f"RAM ${a:02X} at picture start: " + ", ".join(f"{v}: {n}x" for v, n in sorted(c.items())))

    if args.png:
        from PIL import Image
        if args.show:
            show = [int(v) for v in args.show.split(",")]
        else:
            n = min(4, len(frames))
            show = [round(k * (len(frames) - 1) / max(n - 1, 1)) for k in range(n)]
        show = [i for i in show if 0 <= i < len(frames) and frames[i]["vis_end"]]
        height = max(round((frames[i]["vis_end"] - frames[i]["vis_start"]) / L) for i in show)
        gap = 4
        img = Image.new("RGB", (len(show) * (320 + gap) - gap, height), (40, 40, 40))
        for k, fi in enumerate(show):
            f = frames[fi]
            rows = render_frame(vcs.events, -(-f["vis_start"] // L), height)
            for y, row in enumerate(rows):
                for x, c in enumerate(row):
                    rgb = PAL[(c >> 1) & 0x7F]
                    px = (rgb >> 16, (rgb >> 8) & 0xFF, rgb & 0xFF)
                    img.putpixel((k * (320 + gap) + 2 * x, y), px)       # TIA pixels are ~2:1 wide
                    img.putpixel((k * (320 + gap) + 2 * x + 1, y), px)
        img.save(args.png)
        print(f"frames {show} rendered to {args.png}")

    sys.exit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
