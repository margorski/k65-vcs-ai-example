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
ADDR_PAIRA, ADDR_PAIRB = 0xFBA0, 0xFBD0     # vertex-shape banks: point list (<= 47 points + 0xFF), placed
                                            #  right before SphScale to keep the free space in one block
SHAPE_FRAME = 16                            # max bytes per frame for vertex shapes (<= 8 vertices)

S3 = 1 / math.sqrt(3)
# cube, rotated LIVE (cub_setup): vertex = S3 x (+-c0 +- c1 +- c2); ids 0..3 = A B C D, 4..7 = opposites
CUBE_S = [(1, 1, 1), (1, 1, -1), (1, -1, 1), (-1, 1, 1)]
CUBE_V = [tuple(k * S3 * v for v in s) for k in (1, -1) for s in CUBE_S]
CUBE_E = [(i, j) for i in range(8) for j in range(i + 1, 8)
          if sum(a != b for a, b in zip(CUBE_V[i], CUBE_V[j])) == 1]
# pyramid: apex + square base, rotated LIVE (pyr_setup): apex = matrix column 1, base centre = -apex/2,
# corners = centre +- (G0 +- G2), G0/G2 = 0.62 x columns 0/2 - same tables as the diamond
PYR_V = [(0, 1, 0), (0.62, -0.5, 0.62), (0.62, -0.5, -0.62), (-0.62, -0.5, -0.62), (-0.62, -0.5, 0.62)]
PYR_BASE = [(1, 2), (2, 3), (3, 4), (4, 1)]
PYR_SLANT = [(0, k) for k in range(1, 5)]

# drawn points: (a, b, quarter) - a vertex is (i, i, 0), an edge midpoint (i, j, 0),
# a quarter point (i, j, 1) = 1/4 of the way from i to j (midpoint averaged with i again)
def verts_and_mids(nv, edges):
    return [(i, i, 0) for i in range(nv)] + [(a, b, 0) for a, b in edges]

# diamond: elongated octahedron (apex top/bottom, 4 on the girdle), rotated LIVE on the 6502:
# its vertices are +-(columns of the rotation matrix), so only 3 are computed per frame
# (tip T = column 1, girdle U = 0.62 x column 0, W = 0.62 x column 2); vertex id 3..5 = -(id-3)
DIA_V = [(0, 1, 0), (0.62, 0, 0), (0, 0, 0.62), (0, -1, 0), (-0.62, 0, 0), (0, 0, -0.62)]
DIA_GIRDLE = [(1, 2), (2, 4), (4, 5), (5, 1)]
DIA_SLANT = [(t, g) for t in (0, 3) for g in (1, 2, 4, 5)]
DIA_AMP, DIA_AMP_G = 63, 39     # sin/cos amplitude (unit), girdle 0.62 x unit
DIA_ZP = (0xE4, 0xEC, 0xEE, 0xF4, 0xF6, 0xD8)  # RAM of T U W -T -U -W (x, y byte), sphere_defs.k65
PYR_ZP = (0xE4, 0xEC, 0xEE, 0xF4, 0xF6)        # apex, +P, +Q, -P, -Q
CUB_ZP = (0xE4, 0xEC, 0xEE, 0xF4) * 2          # A B C D, then the opposites (negated while fetching)

# shape name, bank, label suffix, frame stride (16; None = rotated live), vertices, points
SHAPES = [
    ("cube", "bank2", "2", None, CUBE_V, verts_and_mids(8, CUBE_E)),
    ("pyramid", "core", "C", None, PYR_V, verts_and_mids(5, PYR_BASE)       # slant edge: midpoint,
        + [p for a, b in PYR_SLANT for p in ((a, b, 0), (a, b, 1), (b, a, 1))]),  #  1/4 from each end
    ("diamond", "bank7", "7", None, DIA_V, verts_and_mids(6, DIA_GIRDLE)
        + [p for t, g in DIA_SLANT for p in ((t, g, 0), (g, t, 1))]),  # + 1/4 from the girdle to the tip
]

LIVE = {"diamond": (DIA_ZP, "dia", DIA_AMP_G), "pyramid": (PYR_ZP, "pyr", DIA_AMP_G),
        "cube": (CUB_ZP, "cub", round(DIA_AMP * S3))}

# frame pointer code: ptrC = ShpAnimA + frame*stride
PTR_CODE = {
    16: """    a=sp_frame a<< a<< a<< a<< ptrC=a
    a=sp_frame a>> a>> a>> a>> c- a+&>ShpAnimA ptrC+1=a""",
}

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

    for name, bank_name, bank, stride, verts, pairs in SHAPES:
        if stride is None:
            emit_live(name, bank_name, bank, pairs, *LIVE[name], (scale, line_band, cbase, coff, line_cand))
            continue
        assert len(verts) * 2 <= stride and len(pairs) < 48
        data = frames_of(verts, stride)
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
        # frame pointer: ShpAnimA + frame*stride ; point index from 0
        print(f"""func shape_proc{bank} {{
    never {{ {refs} }}
{PTR_CODE[stride]}
    shape_body
}}""")


ADDR_LV = 0xF000    # live shapes' tables (LvSin, LvSinG, LvSq) + the multiply routine (LvMul): fixed,
                    # same in every live-shape bank; at the bank start, so the rest stays whole


def emit_live(name, bank_name, bank, pairs, zp, prefix, amp_g, tables):
    """Live vertex shape: no animation frames, the 6502 rotates it ({prefix}_setup / {prefix}_body
    in sphere_defs.k65). Point list = vertex ids: ShpPairA = id, ShpPairB = id / 0x80 lone vertex /
    0x40 quarter point (= the previous point, the midpoint of the same edge, averaged with vertex A
    once more) / id | 0x20 quarter point computed from scratch (pyr_body only)."""
    pa, pb = [], []
    for i, (a, b, q) in enumerate(pairs):
        pa.append(a)
        if not q:
            pb.append(0x80 if a == b else b)
        elif i and set(pairs[i - 1][:2]) == {a, b} and not pairs[i - 1][2]:
            pb.append(0x40)
        else:
            assert prefix == "pyr"
            pb.append(0x20 | b)
    pa.append(0xFF)
    pb.append(0xFF)
    ang = [2 * math.pi * i / FRAMES for i in range(FRAMES + FRAMES // 4)]   # cos(i) = sin(i + 33)
    lv = [[round(DIA_AMP * math.sin(t)) & 0xFF for t in ang],
          [round(amp_g * math.sin(t)) & 0xFF for t in ang],
          # quarter squares: sq(|a+b|) - sq(|a-b|) = 4ab/126 = a*b*2/63 (double precision, |a|,|b| <= 63)
          [round(n * n / (4 * DIA_AMP / 2)) for n in range(2 * DIA_AMP + 1)]]
    print(f"\n// {name}: {len(pairs)} drawn points, rotation computed at runtime ({prefix}_setup)")
    print(f"bank {bank_name};\n")
    print(f"data ShpPairA{bank} {{\n    address 0x{ADDR_PAIRA:04X}\n{rows(pa)}\n}}")
    print(f"data ShpPairB{bank} {{\n    address 0x{ADDR_PAIRB:04X}\n{rows(pb)}\n}}")
    addr = ADDR_LV
    for n, t in zip(("LvSin", "LvSinG", "LvSq"), lv):
        print(f"data {n}{bank} {{\n    address 0x{addr:04X}\n{rows(t)}\n}}")
        addr += len(t)
    print(f"func lv_mul{bank} {{\n    address 0x{addr:04X}\n    dia_mul\n}}   // = LvMul (call LvMul)")
    zpname = prefix.capitalize() + "Zp"
    print(f"data {zpname} {{ {' '.join(str(z) for z in zp)} }}   // vertex id -> its RAM (x byte, y byte)")
    emit_tables(bank, *tables)
    refs = " ".join(f"a={n}{bank}" for n in ("ShpPairA", "ShpPairB", "LvSin", "LvSinG", "LvSq", "lv_mul",
                                              "SphScale", "SphLineBand", "SphCandBase",
                                              "SphCandOff", "SphLineCand"))
    print(f"""func {prefix}_setup{bank} {{                  // rotate the vertices (top of the picture)
    {prefix}_setup
}}
func shape_proc{bank} {{
    never {{ {refs} }}
    {prefix}_body
}}""")


# Atari "Fuji" logo, flat (z = 0), spinning around the vertical axis at runtime (bank7):
# x = x0 * cos(angle) via quarter squares, y constant. 10 vertices, 3 points per segment.
LOGO_V = [(-0.07, 1.0), (-0.07, -1.0), (0.07, 1.0), (0.07, -1.0),       # centre bar (2 columns)
          (0.26, 1.0), (0.42, -0.25), (1.0, -1.0),                      # right prong
          (-0.26, 1.0), (-0.42, -0.25), (-1.0, -1.0)]                   # left prong
LOGO_SEG = [(0, 1), (2, 3), (4, 5), (5, 6), (7, 8), (8, 9)]
LOGO_W = 1.2                        # logo is wider than the sphere radius
LOGO_BANK = "bank7"

# Altair logo (demogroup): centrelines of its 6 strokes in the 96x96 source png
# (sv2019/gfx/altair-logo.png), sampled evenly; image px -> units: centre (44,44), 33 px = 1
ALTAIR_STROKES = [((36, 16), (7, 76)), ((36, 16), (57.5, 63)), ((50, 15), (80, 74)),
                  ((25, 74), (80, 74)), ((36, 47), (25, 74)), ((36, 47), (42.5, 63))]


def altair_points(n=30):
    lens = [math.dist(a, b) for a, b in ALTAIR_STROKES]
    tot, pts = sum(lens), []
    for (a, b), l in zip(ALTAIR_STROKES, lens):
        k = max(2, round(n * l / tot))
        pts += [(a[0] + (b[0] - a[0]) * i / (k - 1), a[1] + (b[1] - a[1]) * i / (k - 1)) for i in range(k)]
    out = []
    for p in pts:                                   # drop duplicates at shared joints
        if all(math.dist(p, q) > 3 for q in out):
            out.append(p)
    return [((x - 44) / 33, (44 - y) / 33) for x, y in out]


def emit_logo():
    pts = list(LOGO_V)
    for a, b in LOGO_SEG:
        (ax, ay), (bx, by) = LOGO_V[a], LOGO_V[b]
        pts += [(ax + (bx - ax) * t, ay + (by - ay) * t) for t in (0.25, 0.5, 0.75)]
    alt = altair_points()
    # two point sets, each ended by LogoY = 0xFF: Atari at index 0, Altair after it
    lx = ([round(RX * LOGO_W * x) & 0xFF for x, y in pts] + [0]
          + [round(RX * x) & 0xFF for x, y in alt] + [0])           # signed pixels
    ly = ([round(-RY * y) + 64 for x, y in pts] + [0xFF]
          + [round(-RY * y) + 64 for x, y in alt] + [0xFF])         # y byte (offset + 64)
    altair_base = len(pts) + 1
    assert all(abs(((v ^ 0x80) - 0x80)) <= 40 for v in lx)          # quarter squares: |x0 +- 64| <= 104
    # cos(f) = cos(FRAMES - f): half a table, the 6502 mirrors the index
    cos = [round(64 * math.cos(2 * math.pi * f / FRAMES)) & 0xFF for f in range(FRAMES // 2 + 1)]
    sq = [n * n // 128 for n in range(105)]                         # quarter squares: diff = x0*c/32
    print(f"\n// logos: Atari {len(pts)} points, Altair {len(alt)} points (from index {altair_base}),"
          f" spin computed at runtime")
    print(f"bank {LOGO_BANK};\n")
    # fixed addresses (F740-F8xx), so that big contiguous blocks stay free for the code
    print(f"data LogoSq {{\n    address 0xF740\n{rows(sq)}\n}}")
    print(f"data LogoCos {{\n    address 0xF7B0\n{rows(cos)}\n}}")
    print(f"data LogoX {{\n    address 0xF800\n{rows(lx)}\n}}")
    print(f"data LogoY {{\n    address 0xF840\n{rows(ly)}\n}}")
    print(f"""func logo_proc7 {{
    x=sp_frame x?[{FRAMES // 2 + 1}] >={{ a=[{FRAMES}] c+ a-sp_frame x=a }}   // mirror: cos(N-f) = cos(f)
    a=LogoCos,x ptrC=a                              // c = 64*cos(angle)
    a=0 x=sp_shape x?5 =={{ a=[{altair_base}] }} sp_lbase=a       // point set: 4 Atari, 5 Altair
    logo_body
}}""")
    return len(pts)


if __name__ == "__main__":
    main()
    emit_logo()
