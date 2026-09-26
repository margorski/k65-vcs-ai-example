#!/usr/bin/env python3
"""Generate effects/sphere_data.k65 - precomputed tumbling point sphere + vertex shapes.

The 3D rotation is far too expensive for the 6502 at runtime (6 multiplies per
point), so it is baked into ROM: SPH_FRAMES animation frames of NPTS points,
each point = (dx+64, dy+64), dx in pixels, dy in scanlines (~2 lines per TIA
pixel keeps it round). The frames are split over banks 5-7; every bank also
gets identical lookup tables at fixed addresses and its own copy of the
per-point routine (sph_body, defined in effects/sphere.k65), so the same code
works in any of the banks.

Vertex shapes (cube, ...) store only their rotated vertices per frame (16 bytes,
same rotation as the sphere) plus a list of vertex pairs to draw: (i,i) = the
vertex, (i,j) = the midpoint of an edge (averaged on the 6502).

Usage:  python3 tools/gen_sphere.py > effects/sphere_data.k65
"""
import math

NPTS = 30                   # points on the sphere (CPU budget: ~125 cycles per point per frame)
FRAME_BYTES = 64            # bytes per animation frame - MUST stay 64 (sph_points computes frame*64)
FPB = 44                    # sphere animation frames per bank
BANKS = (5, 6)
SPH_FRAMES_N = FPB * len(BANKS)  # 88 sphere frames (the 6502 maps frame 0..131 -> frame*2/3)
FRAMES = 132                # animation frames of the vertex shapes - must match SPH_FRAMES
RX, RY = 32, 63             # radius in pixels / scanlines (level 0 scale)
TURNS = (1, 2, 1)           # full turns around X, Y, Z per animation loop
SCALES = (1.0, 1.07, 1.14, 1.2)
NB, BAND_H, DOT0 = 15, 11, 6   # kernel: bands, lines per band, first dot line in a band
NLINES = NB * BAND_H           # 165 dot-area lines

ADDR_ANIM, ADDR_SCALE = 0xF100, 0xFC00
# (keep 0xFFC5-0xFFEC free: far-call stubs must sit at the same address in bank4 and here)
ADDR_BAND, ADDR_CBASE, ADDR_COFF, ADDR_CAND = 0xFE00, 0xFEA8, 0xFEE4, 0xFF20
ADDR_PAIRA, ADDR_PAIRB = 0xFA00, 0xFA40     # vertex-shape banks: point list (vertex byte offsets)
SHAPE_FRAME = 16                            # bytes per frame for vertex shapes (<= 8 vertices)

S3 = 1 / math.sqrt(3)
CUBE_V = [(x * S3, y * S3, z * S3) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
CUBE_E = [(i, j) for i in range(8) for j in range(i + 1, 8)
          if sum(a != b for a, b in zip(CUBE_V[i], CUBE_V[j])) == 1]
# pyramid: apex + square base, all vertices inside the unit sphere (pulse headroom)
PYR_V = [(0, 0.95, 0), (0.6, -0.5, 0.6), (0.6, -0.5, -0.6), (-0.6, -0.5, -0.6), (-0.6, -0.5, 0.6)]
PYR_BASE = [(1, 2), (2, 3), (3, 4), (4, 1)]
PYR_SLANT = [(0, k) for k in range(1, 5)]

# drawn points: (a, b, quarter) - a vertex is (i, i, 0), an edge midpoint (i, j, 0),
# a quarter point (i, j, 1) = 1/4 of the way from i to j (midpoint averaged with i again)
def verts_and_mids(nv, edges):
    return [(i, i, 0) for i in range(nv)] + [(a, b, 0) for a, b in edges]

# diamond: elongated octahedron (apex top/bottom, 4 on the girdle)
DIA_V = [(0, 1, 0), (0, -1, 0), (0.62, 0, 0), (0, 0, 0.62), (-0.62, 0, 0), (0, 0, -0.62)]
DIA_GIRDLE = [(2, 3), (3, 4), (4, 5), (5, 2)]
DIA_SLANT = [(t, g) for t in (0, 1) for g in range(2, 6)]

# shape name, bank, label suffix, vertices, drawn points
SHAPES = [
    ("cube", "bank2", "2", CUBE_V, verts_and_mids(8, CUBE_E)),
    ("pyramid", "core", "C", PYR_V, verts_and_mids(5, PYR_BASE + PYR_SLANT)
        + [(a, b, 1) for a, b in PYR_SLANT] + [(b, a, 1) for a, b in PYR_SLANT]),
    ("diamond", "bank7", "7", DIA_V, verts_and_mids(6, DIA_GIRDLE + DIA_SLANT)
        + [(g, t, 1) for t, g in DIA_SLANT]),       # 1/4 from the girdle toward the tips
]

# slot k = object: 0 P0, 1 P1, 2 M0, 3 M1, 4 BL - draws its dot on band line DOT0+k.
# Depth: P0/M0/BL use the bright band colour (front of the sphere), P1/M1 the dim one (back).
FRONT, BACK = (0, 2, 4), (1, 3)
ROW = 6                        # candidate list row: 5 slots + 0xFF
# Stored value = positioning input A: players land at A+9 (3-cycle preamble on
# their positioning line) and GRP=%11 puts the dot 6 px right -> A = x-15;
# missiles/ball land 1 px left of A -> A = x+1.
SLOT_OFF = (15, 15, -1, -1, -1)
SLOT_BASE = tuple(k * NB for k in range(5))


def fib_sphere(n):
    pts = []
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(n):
        y = 1 - 2 * (i + 0.5) / n
        r = math.sqrt(1 - y * y)
        a = golden * i
        pts.append((r * math.cos(a), y, r * math.sin(a)))
    return pts


def rotate(p, ax, ay, az):
    x, y, z = p
    y, z = y * math.cos(ax) - z * math.sin(ax), y * math.sin(ax) + z * math.cos(ax)
    x, z = x * math.cos(ay) + z * math.sin(ay), -x * math.sin(ay) + z * math.cos(ay)
    x, y = x * math.cos(az) - y * math.sin(az), x * math.sin(az) + y * math.cos(az)
    return x, y, z


def rows(values, per=16):
    out = []
    for i in range(0, len(values), per):
        out.append("    " + " ".join(str(v) for v in values[i:i + per]))
    return "\n".join(out)


def frames_of(points, stride, nframes=FRAMES):
    """Rotated + projected points of every animation frame, stride bytes per frame."""
    out = []
    for f in range(nframes):
        t = 2 * math.pi * f / nframes
        for p in points:
            x, y, z = rotate(p, t * TURNS[0], t * TURNS[1], t * TURNS[2])
            back = 0x80 if z < 0 else 0          # bit 7 of the x byte: point is on the far side
            out.append((round(RX * x) + 64) | back)
            out.append(round(-RY * y) + 64)      # screen y grows downwards
        out += [64] * (stride - 2 * len(points)) # pad: the 6502 addresses frames as frame*stride
    return out


def emit_tables(bank, scale, line_band, cbase, coff, line_cand):
    print(f"data SphScale{bank} {{\n    address 0x{ADDR_SCALE:04X}\n{rows(scale)}\n}}")
    print(f"data SphLineBand{bank} {{\n    address 0x{ADDR_BAND:04X}\n{rows(line_band)}\n}}")
    print(f"data SphCandBase{bank} {{\n    address 0x{ADDR_CBASE:04X}\n{rows(cbase)}\n}}")
    print(f"data SphCandOff{bank} {{\n    address 0x{ADDR_COFF:04X}\n{rows(coff)}\n}}")
    print(f"data SphLineCand{bank} {{\n    address 0x{ADDR_CAND:04X}\n{rows(line_cand)}\n}}")


def main():
    assert 2 * NPTS <= FRAME_BYTES and FPB * FRAME_BYTES <= ADDR_SCALE - ADDR_ANIM
    anim = frames_of(fib_sphere(NPTS), FRAME_BYTES, SPH_FRAMES_N)

    scale = []
    for s in SCALES:
        scale += [round((v - 64) * s) & 0xFF for v in range(128)]

    # dot line of (band b, slot k) = b*BAND_H + DOT0 + k ; map every line to the nearest
    line_band, line_cand = [], []
    for L in range(NLINES):
        best = min(((abs(b * BAND_H + DOT0 + k - L), b, k) for b in range(NB) for k in range(5)))  # nearest slot line
        line_band.append(best[1])
        line_cand.append(best[2] * ROW)

    # candidate slots: rows 0-4 for front points, 5-9 for back points (preferred slot k).
    # Own depth class first (nearest line first), then the other class as a fallback.
    cbase, coff = [], []
    for own, other in ((FRONT, BACK), (BACK, FRONT)):
        for k in range(5):
            order = sorted(own, key=lambda j: (abs(j - k), j)) + sorted(other, key=lambda j: (abs(j - k), j))
            cbase += [SLOT_BASE[j] for j in order] + [0xFF]
            coff += [SLOT_OFF[j] & 0xFF for j in order] + [0]

    print("// GENERATED by tools/gen_sphere.py - do not edit, regenerate instead:")
    print("//   python3 tools/gen_sphere.py > effects/sphere_data.k65")
    print(f"// sphere: {NPTS} points, {SPH_FRAMES_N} frames ({FPB} per bank); shapes: {FRAMES} frames;"
          f" turns X/Y/Z = {TURNS}, radius {RX} px / {RY} lines")
    for i, bank in enumerate(BANKS):
        frames = anim[i * FPB * FRAME_BYTES:(i + 1) * FPB * FRAME_BYTES]
        print(f"\nbank bank{bank};\n")
        print(f"data SphAnim{bank} {{\n    address 0x{ADDR_ANIM:04X}\n{rows(frames, 32)}\n}}")
        emit_tables(bank, scale, line_band, cbase, coff, line_cand)
        # the tables are read through fixed-address vars, so reference their labels once
        # (in a never-executed block) or the linker drops them as unused
        refs = " ".join(f"a={n}{bank}" for n in ("SphAnim", "SphScale", "SphLineBand", "SphCandBase", "SphCandOff", "SphLineCand"))
        print(f"func sph_proc{bank} {{\n    never {{ {refs} }}\n    sph_body\n}}")

    for name, bank_name, bank, verts, pairs in SHAPES:
        assert len(verts) * 2 <= SHAPE_FRAME and len(pairs) < 64
        data = frames_of(verts, SHAPE_FRAME)
        assert len(data) <= ADDR_PAIRA - ADDR_ANIM
        pa = [2 * a for a, b, q in pairs] + [0xFF]
        pb = [2 * b + (0x40 if q else 0) for a, b, q in pairs] + [0xFF]   # bit 6 = quarter point
        print(f"\n// {name}: {len(verts)} vertices, {len(pairs)} drawn points")
        print(f"bank {bank_name};\n")
        print(f"data ShpAnim{bank} {{\n    address 0x{ADDR_ANIM:04X}\n{rows(data, 32)}\n}}")
        print(f"data ShpPairA{bank} {{\n    address 0x{ADDR_PAIRA:04X}\n{rows(pa)}\n}}")
        print(f"data ShpPairB{bank} {{\n    address 0x{ADDR_PAIRB:04X}\n{rows(pb)}\n}}")
        emit_tables(bank, scale, line_band, cbase, coff, line_cand)
        refs = " ".join(f"a={n}{bank}" for n in ("ShpAnim", "ShpPairA", "ShpPairB", "SphScale",
                                                  "SphLineBand", "SphCandBase", "SphCandOff", "SphLineCand"))
        # frame pointer: ShpAnimA + frame*16 ; point index from 0
        print(f"""func shape_proc{bank} {{
    never {{ {refs} }}
    a=sp_frame a<< a<< a<< a<< ptrC=a
    a=sp_frame a>> a>> a>> a>> c- a+&>ShpAnimA ptrC+1=a
    shape_body
}}""")


if __name__ == "__main__":
    main()
