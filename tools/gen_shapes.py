#!/usr/bin/env python3
"""Generate the data of the shapes effect (effects/shapes/): only data, the code is hand-written.

  shape_data.k65    shared tables: placement tables (bank1 + bank5), sin / quarter squares of the
                    live shapes (bank2), the point list of the live shapes (bank1)
  sphere_data.k65   sphere animation (bank5)
  diamond_data.k65  the diamond's own "G" sin table (bank2)
  logo_data.k65     Atari + Altair logo points, cos + quarter squares (bank1)

Sphere (bank5): rotating 30 points per point is too expensive for the 6502, so the rotation
is baked into ROM - packed by symmetry: the point set is symmetric under p -> -p and under
the 180-degree turn about X, so a frame stores one point of each opposite pair (15 x 2 bytes)
and only half a turn (66 frames): frame f + 66 = frame f with the far bits flipped.
Each point = (dx+64 | far bit 7, dy+64), dx in pixels, dy in scanlines.

Vertex shapes (cube, pyramid, diamond) are rotated live on the 6502 (cube.k65, ...), split
by job into two banks (one copy of every table):
  ROT_BANK    rotation: sin / quarter-square tables (+ shape_mul, *_setup in the .k65 files)
  ENGINE_BANK dot engine: placement tables, the point list (vertex pairs: (i,i) = the vertex,
              (i,j) = an edge midpoint) read by shape_live_points, the logos
The placement tables (ShapeScale, ...) exist twice - ENGINE_BANK and the sphere's bank - at the
same fixed addresses, because shape_place is shared by both banks.

Usage:  python3 tools/gen_shapes.py [output dir, default effects/shapes]
"""
import math
import os
import sys

NPTS = 30                   # points on the sphere (must match SPHERE_NPTS)
FRAME_BYTES = 32            # bytes per stored sphere frame - MUST stay 32 (sphere_frame: frame*32)
FRAMES = 132                # animation frames per turn - must match SHAPE_FRAMES
SPH_FRAMES_N = FRAMES // 2  # stored sphere frames (the second half turn = far bits flipped)
SPH_BANK = "5"
ROT_BANK = "2"              # rotation of the live shapes (tables + shape_mul + *_setup)
ENGINE_BANK = "1"           # point routines of the live shapes + logos (+ placement tables)
# sphere points: the (x, y, z) -> (x, -y, -z) orbits of these 7 points and their opposites (28)
# + the X axis pair = 30; found by minimising the 1/distance energy with that symmetry imposed
# (360.17 - as even as the 30-point Fibonacci spiral, 360.22; the optimum is 359.60)
SPH_REPS = [(-0.76974, -0.50409, -0.39165), (-0.2864, 0.69228, -0.66236), (-0.28812, -0.62893, -0.7221),
            (-0.28742, -0.02867, 0.95738), (0.77268, -0.11279, 0.6247), (-0.7402, -0.62886, 0.23801),
            (-0.28702, -0.95558, -0.06705)]
RX, RY = 32, 63             # radius in pixels / scanlines (level 0 scale)
TURNS = (1, 2, 1)           # full turns around X, Y, Z per animation loop
SCALES = (1.0, 1.07, 1.14, 1.2)
NB, BAND_H, DOT0 = 15, 11, 6   # kernel: bands, lines per band, first dot line in a band
NLINES = NB * BAND_H           # 165 dot-area lines

ADDR_ANIM, ADDR_SCALE = 0xF100, 0xFC00
# (keep 0xFFC5-0xFFEC free: far-call stubs must sit at the same address in bank4 and here)
ADDR_BAND, ADDR_CBASE, ADDR_COFF, ADDR_CAND = 0xFE00, 0xFEA8, 0xFEE4, 0xFF20

S3 = 1 / math.sqrt(3)
# cube, rotated LIVE (cube_rotate): vertex = S3 x (+-c0 +- c1 +- c2); ids 0..3 = A B C D, 4..7 = opposites
CUBE_S = [(1, 1, 1), (1, 1, -1), (1, -1, 1), (-1, 1, 1)]
CUBE_V = [tuple(k * S3 * v for v in s) for k in (1, -1) for s in CUBE_S]
CUBE_E = [(i, j) for i in range(8) for j in range(i + 1, 8)
          if sum(a != b for a, b in zip(CUBE_V[i], CUBE_V[j])) == 1]
# pyramid: apex + square base, rotated LIVE (pyramid_rotate): apex = matrix column 1, base centre
# = -apex/2, corners = centre +- (G0 +- G2), G0/G2 = S3 x columns 0/2 - same tables as the cube (ShapeSinG)
PYR_V = [(0, 1, 0), (S3, -0.5, S3), (S3, -0.5, -S3), (-S3, -0.5, -S3), (-S3, -0.5, S3)]
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
CUB_AMP_G = round(DIA_AMP * S3)  # 1/sqrt(3) x unit (cube, pyramid)
# vertex ids of the shared point routine (shape_live_body, shape_live.k65; ShapeZp = their RAM):
# 0..2 rotated vertices, 3..5 derived per phase (prep), 8..11 = ids 0..3 negated while fetching
CUB_IDS = (0, 1, 2, 3, 8, 9, 10, 11)    # A B C D (D = prep), -A -B -C -D (negated while fetching)
PYR_IDS = (0, 1, 2, 3, 4)               # apex, +P, +Q, -P, -Q (-P, -Q = prep)
DIA_IDS = (0, 1, 2, 3, 4, 5)            # T U W, -T -U -W (prep)

# live shapes (SHAPE_CUBE, SHAPE_PYRAMID, SHAPE_DIAMOND in this order): name, vertices (reference
# only), points, shape vertex index -> shape_live_body vertex id
SHAPES = [
    ("cube", CUBE_V, verts_and_mids(8, CUBE_E), CUB_IDS),
    ("pyramid", PYR_V, verts_and_mids(5, PYR_BASE)                     # slant edge: midpoint,
        + [p for a, b in PYR_SLANT for p in ((a, b, 0), (a, b, 1), (b, a, 1))],  #  1/4 from each end
        PYR_IDS),
    ("diamond", DIA_V, verts_and_mids(6, DIA_GIRDLE)
        + [p for t, g in DIA_SLANT for p in ((t, g, 0), (g, t, 1))],  # + 1/4 from the girdle to the tip
        DIA_IDS),
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


def sym_sphere():
    """Stored sphere points: the X axis point + each rep and its (x, -y, -z) turn (15);
    the 6502 adds the opposite of each."""
    pts = [(1.0, 0.0, 0.0)]
    for x, y, z in SPH_REPS:
        pts += [(x, y, z), (x, -y, -z)]
    return [tuple(c / math.dist(p, (0, 0, 0)) for c in p) for p in pts]


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


def frames_of(points, stride, nframes, per_turn=FRAMES):
    """Rotated + projected points of animation frames 0..nframes-1, stride bytes per frame."""
    out = []
    for f in range(nframes):
        t = 2 * math.pi * f / per_turn
        for p in points:
            x, y, z = rotate(p, t * TURNS[0], t * TURNS[1], t * TURNS[2])
            back = 0x80 if z < 0 else 0          # bit 7 of the x byte: point is on the far side
            out.append((round(RX * x) + 64) | back)
            out.append(round(-RY * y) + 64)      # screen y grows downwards
        out += [64] * (stride - 2 * len(points)) # pad: the 6502 addresses frames as frame*stride
    return out


def emit_tables(bank, scale, line_band, cbase, coff, line_cand):
    """placement tables (shape_place) at their fixed addresses, label suffix = bank"""
    return "\n".join([
        f"data ShapeScale{bank} {{\n    address 0x{ADDR_SCALE:04X}\n{rows(scale)}\n}}",
        f"data ShapeLineBand{bank} {{\n    address 0x{ADDR_BAND:04X}\n{rows(line_band)}\n}}",
        f"data ShapeCandBase{bank} {{\n    address 0x{ADDR_CBASE:04X}\n{rows(cbase)}\n}}",
        f"data ShapeCandOff{bank} {{\n    address 0x{ADDR_COFF:04X}\n{rows(coff)}\n}}",
        f"data ShapeLineCand{bank} {{\n    address 0x{ADDR_CAND:04X}\n{rows(line_cand)}\n}}"])


def point_bytes(p, f):
    x, y, z = rotate(p, *(2 * math.pi * f / FRAMES * k for k in TURNS))
    return (round(RX * x) + 64) | (0x80 if z < 0 else 0), round(-RY * y) + 64


def check_sphere_symmetry(stored):
    """frame f + 66 must be frame f (stored points + their opposites) with z negated, i.e. the far
    bits flipped (R(f+66) = Rz(180) R(f) Rx(180), and the set is closed under Rx(180) and p -> -p)"""
    full = stored + [tuple(-c for c in p) for p in stored]
    for f in range(SPH_FRAMES_N):
        a = [rotate(p, *(2 * math.pi * f / FRAMES * k for k in TURNS)) for p in full]
        b = [rotate(p, *(2 * math.pi * (f + SPH_FRAMES_N) / FRAMES * k for k in TURNS)) for p in full]
        for x, y, z in b:
            assert min(math.dist((x, y, -z), q) for q in a) < 1e-6, f


def main():
    stored = sym_sphere()
    assert 2 * len(stored) == NPTS and 2 * len(stored) <= FRAME_BYTES
    check_sphere_symmetry(stored)
    anim = frames_of(stored, FRAME_BYTES, SPH_FRAMES_N)
    assert len(anim) <= ADDR_SCALE - ADDR_ANIM

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
    tables = (scale, line_band, cbase, coff, line_cand)

    sphere = [f"// sphere: {NPTS} points ({len(stored)} stored), {SPH_FRAMES_N} of {FRAMES} frames stored;"
              f" turns X/Y/Z = {TURNS}, radius {RX} px / {RY} lines",
              f"bank bank{SPH_BANK};\n",
              f"data SphereAnim {{\n    address 0x{ADDR_ANIM:04X}\n{rows(anim, 32)}\n}}"]
    ang = [2 * math.pi * i / FRAMES for i in range(FRAMES + FRAMES // 4)]   # cos(i) = sin(i + 33)
    sin = lambda amp: rows([round(amp * math.sin(t)) & 0xFF for t in ang])
    shared = [f"// === bank{SPH_BANK}: placement tables of the sphere (shape_place runs there too) ===",
              f"bank bank{SPH_BANK};\n", emit_tables(SPH_BANK, *tables),
              f"\n// === bank{ROT_BANK}: rotation of the live shapes (once per frame, above the picture) ===",
              f"bank bank{ROT_BANK};\n",
              f"// sin x {DIA_AMP}, {len(ang)} entries: ShapeSin+{FRAMES // 4} = cos",
              f"data ShapeSin {{\n{sin(DIA_AMP)}\n}}",
              f"// sin x {CUB_AMP_G} (1/sqrt(3) of the unit: cube, pyramid)",
              f"data ShapeSinG {{\n{sin(CUB_AMP_G)}\n}}",
              "// quarter squares: sq(|a+b|) - sq(|a-b|) = 4ab/126 = a*b*2/63 (|a|,|b| <= 63)",
              f"data ShapeSq {{\n{rows([round(n * n / (4 * DIA_AMP / 2)) for n in range(2 * DIA_AMP + 1)])}\n}}",
              f"\n// === bank{ENGINE_BANK}: dot engine of the live shapes + logos ===",
              f"bank bank{ENGINE_BANK};\n", emit_tables(ENGINE_BANK, *tables), emit_live()]
    diamond = [f"bank bank{ROT_BANK};\n",
               f"// sin x {DIA_AMP_G} (0.62 of the unit: the girdle), {len(ang)} entries: DiamondSin+{FRAMES // 4} = cos",
               f"data DiamondSin {{\n{sin(DIA_AMP_G)}\n}}"]
    return {"shape_data.k65": shared, "sphere_data.k65": sphere, "diamond_data.k65": diamond}


def point_list(pairs, ids):
    """(a, b, quarter) points -> ShapePairA / ShapePairB entries (see shape_live.k65)"""
    pa, pb = [], []
    for i, (a, b, q) in enumerate(pairs):
        pa.append(ids[a])
        if not q:
            pb.append(0x80 if a == b else ids[b])               # lone vertex / edge midpoint
        elif i and set(pairs[i - 1][:2]) == {a, b} and not pairs[i - 1][2]:
            pb.append(0x40)                                     # quarter point after its midpoint
        else:
            pb.append(0x20 | ids[b])                            # quarter point from scratch
    return pa + [0xFF], pb + [0xFF]


def emit_live():
    """One point list for all live shapes (each ended by 0xFF; <SHAPE>_I0 = its first entry:
    shape_i starts there, ShapeI0 in shapes.k65)."""
    pa, pb, starts = [], [], []
    for name, verts, pairs, ids in SHAPES:
        assert all(v < 0x20 for v in ids)
        starts.append((name, len(pa), len(pairs)))
        a, b = point_list(pairs, ids)
        pa += a
        pb += b
    assert len(pa) <= 256
    out = [""] + [f"// {name}: {n} drawn points from entry {start}" for name, start, n in starts]
    out.append("[ " + ", ".join(f"{name.upper()}_I0 = {start}" for name, start, _ in starts) + " ]")
    out.append(f"data ShapePairA {{\n{rows(pa)}\n}}")
    out.append(f"data ShapePairB {{\n{rows(pb)}\n}}")
    return "\n".join(out)


# Atari "Fuji" logo, flat (z = 0), spinning around the vertical axis at runtime (logo.k65):
# x = x0 * cos(angle) via quarter squares, y constant. 10 vertices, 3 points per segment.
LOGO_V = [(-0.07, 1.0), (-0.07, -1.0), (0.07, 1.0), (0.07, -1.0),       # centre bar (2 columns)
          (0.26, 1.0), (0.42, -0.25), (1.0, -1.0),                      # right prong
          (-0.26, 1.0), (-0.42, -0.25), (-1.0, -1.0)]                   # left prong
LOGO_SEG = [(0, 1), (2, 3), (4, 5), (5, 6), (7, 8), (8, 9)]
LOGO_W = 1.2                        # logo is wider than the sphere radius

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
    return [f"// Atari {len(pts)} points, Altair {len(alt)} points (from index {altair_base}), spin computed at runtime",
            f"bank bank{ENGINE_BANK};\n",
            f"[ LOGO_ALTAIR_BASE = {altair_base}, LOGO_COS_N = {FRAMES // 2 + 1} ]   // logo_points"] + [
            f"data {n} {{\n{rows(t)}\n}}" for n, t in (("LogoSq", sq), ("LogoCos", cos), ("LogoX", lx), ("LogoY", ly))]


if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else "effects/shapes"
    files = main()
    files["logo_data.k65"] = emit_logo()
    for name, parts in files.items():
        with open(os.path.join(outdir, name), "w") as f:
            f.write("// GENERATED by tools/gen_shapes.py - do not edit, regenerate instead:\n"
                    "//   python3 tools/gen_shapes.py\n" + "\n".join(parts) + "\n")
        print("wrote", os.path.join(outdir, name))
