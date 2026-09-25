#!/usr/bin/env python3
"""Song analysis for music-reactive effects.

Runs the ROM headless (py65, via vcs_frame_check.VCS) for a whole song, logs
AUDC/AUDF/AUDV of both channels + song position every frame, and prints
per sequence position: average volume, note attacks, waveforms (AUDC) and
the AUDF values used. This is how the section table (EqSongMode) and the
melody pitch map (EqAudfSlot) in effects/eqsine.k65 were derived - rerun it
after changing the song.

    uv run --with py65 tools/song_analysis.py bin/demo.bin [--frames 10500]

AUDC hints: 8 = white noise (hats/snare), 15 = low noise (kick), 1/7 = tones.
"""
import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import vcs_frame_check as v  # noqa: E402

SONGPOS_SEQ = 0x70           # RAM 0xF0 (songpos_seq) as index into VCS.ram


class Recorder(v.VCS):
    def __init__(self, rom):
        super().__init__(rom)
        self.aud = [0] * 6       # AUDC0 AUDC1 AUDF0 AUDF1 AUDV0 AUDV1
        self.log = []

    def __setitem__(self, addr, value):
        a = addr & 0x1FFF
        if not a & 0x1000 and not a & 0x80:
            r = a & 0x3F
            if 0x15 <= r <= 0x1A:
                self.aud[r - 0x15] = value
            if r == 0 and value & 2 and not self.vsync:
                self.log.append(self.aud[:] + [self.ram[SONGPOS_SEQ]])
        super().__setitem__(addr, value)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rom")
    ap.add_argument("--frames", type=int, default=10500, help="frames to simulate (default ~3.5 min)")
    args = ap.parse_args()

    rec = Recorder(open(args.rom, "rb").read())
    rec.run(args.frames * 312 * v.LINE_CYCLES)
    log = rec.log
    seqs = [f[6] for f in log]
    end = next((i for i in range(1, len(seqs)) if seqs[i] < seqs[i - 1]), len(seqs))
    log = log[:end]
    print(f"song: {end} frames = {end / 50:.1f} s, sequence positions {min(seqs)}..{max(seqs[:end])}")

    for ch in (0, 1):
        used = collections.Counter(f[2 + ch] & 31 for f in log if f[4 + ch] & 15)
        print(f"ch{ch} AUDF used (value:frames): " + " ".join(f"{k}:{n}" for k, n in sorted(used.items())))

    per = collections.defaultdict(list)
    for f in log:
        per[f[6]].append(f)
    print("\nseq frames  vol0 vol1  attacks0 attacks1  waveforms0 (AUDC:frames)   waveforms1")
    for s in sorted(per):
        fr = per[s]
        n = len(fr)
        vol = [sum(f[4 + c] & 15 for f in fr) / n for c in (0, 1)]
        att = [sum(1 for a, b in zip(fr, fr[1:]) if (b[4 + c] & 15) - (a[4 + c] & 15) >= 4) for c in (0, 1)]
        wav = [collections.Counter(f[c] & 15 for f in fr if f[4 + c] & 15).most_common(3) for c in (0, 1)]
        w = ["".join(f"{k}:{m} " for k, m in wav[c]) for c in (0, 1)]
        print(f"{s:3} {n:6} {vol[0]:5.1f} {vol[1]:4.1f} {att[0]:9} {att[1]:8}  {w[0]:26} {w[1]}")


if __name__ == "__main__":
    main()
