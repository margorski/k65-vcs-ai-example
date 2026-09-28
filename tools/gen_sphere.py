#!/usr/bin/env python3
"""Generate effects/sphere_data.k65 - data banks of the sphere effect.

Sphere (bank5): rotating 30 points per point is too expensive for the 6502, so the rotation
is baked into ROM - packed by symmetry: the point set is symmetric under p -> -p and under
the 180-degree turn about X, so a frame stores one point of each opposite pair (15 x 2 bytes)
and only half a turn (66 frames): frame f + 66 = frame f with the far bits flipped.
Each point = (dx+64 | far bit 7, dy+64), dx in pixels, dy in scanlines.

Vertex shapes (cube, pyramid, diamond) are rotated live on the 6502 (sphere_defs.k65), split
by job into two banks (one copy of every table):
  ROT_BANK    rotation: sin / quarter-square tables, the multiply routine, the *_setup functions
              (write the rotated vertices to zero page, once per frame)
  ENGINE_BANK dot engine: placement tables, the point routines (*_proc: vertex pairs -> band slots),
              the point lists (vertex pairs: (i,i) = the vertex, (i,j) = an edge midpoint), the logos
The placement tables (SphScale, ...) exist twice - ENGINE_BANK and the sphere's bank - at the same
fixed addresses, because sph_place is shared by both banks.

Usage:  python3 tools/gen_sphere.py > effects/sphere_data.k65
"""
import math

NPTS = 30                   # points on the sphere (must match SPH_NPTS)
FRAME_BYTES = 32            # bytes per stored sphere frame - MUST stay 32 (sph_points: frame*32)
FRAMES = 132                # animation frames per turn - must match SPH_FRAMES
SPH_FRAMES_N = FRAMES // 2  # stored sphere frames (the second half turn = far bits flipped)
SPH_BANK = "5"
ROT_BANK = "2"              # rotation of the live shapes (tables + *_setup)
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
# cube, rotated LIVE (cub_setup): vertex = S3 x (+-c0 +- c1 +- c2); ids 0..3 = A B C D, 4..7 = opposites
CUBE_S = [(1, 1, 1), (1, 1, -1), (1, -1, 1), (-1, 1, 1)]
CUBE_V = [tuple(k * S3 * v for v in s) for k in (1, -1) for s in CUBE_S]
CUBE_E = [(i, j) for i in range(8) for j in range(i + 1, 8)
          if sum(a != b for a, b in zip(CUBE_V[i], CUBE_V[j])) == 1]
# pyramid: apex + square base, rotated LIVE (pyr_setup): apex = matrix column 1, base centre = -apex/2,
# corners = centre +- (G0 +- G2), G0/G2 = S3 x columns 0/2 - same tables as the cube (LvSinG)
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
DIA_ZP = (0xE4, 0xEC, 0xEE, 0xF4, 0xF6, 0xD8)  # RAM of T U W -T -U -W (x, y byte), sphere_defs.k65
PYR_ZP = (0xE4, 0xEC, 0xEE, 0xF4, 0xF6)        # apex, +P, +Q, -P, -Q
CUB_ZP = (0xE4, 0xEC, 0xEE, 0xF4) * 2          # A B C D, then the opposites (negated while fetching)

# "G" sin tables of the live shapes (sin x a shape factor): label -> amplitude
G_TABLES = {"LvSinG": CUB_AMP_G, "LvSinD": DIA_AMP_G}

# live shapes: name, vertices (reference only), points, vertex RAM, code prefix
SHAPES = [
    ("cube", CUBE_V, verts_and_mids(8, CUBE_E), CUB_ZP, "cub"),
    ("pyramid", PYR_V, verts_and_mids(5, PYR_BASE)                     # slant edge: midpoint,
        + [p for a, b in PYR_SLANT for p in ((a, b, 0), (a, b, 1), (b, a, 1))],  #  1/4 from each end
        PYR_ZP, "pyr"),
    ("diamond", DIA_V, verts_and_mids(6, DIA_GIRDLE)
        + [p for t, g in DIA_SLANT for p in ((t, g, 0), (g, t, 1))],  # + 1/4 from the girdle to the tip
        DIA_ZP, "dia"),
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
    print(f"data SphScale{bank} {{\n    address 0x{ADDR_SCALE:04X}\n{rows(scale)}\n}}")
    print(f"data SphLineBand{bank} {{\n    address 0x{ADDR_BAND:04X}\n{rows(line_band)}\n}}")
    print(f"data SphCandBase{bank} {{\n    address 0x{ADDR_CBASE:04X}\n{rows(cbase)}\n}}")
    print(f"data SphCandOff{bank} {{\n    address 0x{ADDR_COFF:04X}\n{rows(coff)}\n}}")
    print(f"data SphLineCand{bank} {{\n    address 0x{ADDR_CAND:04X}\n{rows(line_cand)}\n}}")


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

    print("// GENERATED by tools/gen_sphere.py - do not edit, regenerate instead:")
    print("//   python3 tools/gen_sphere.py > effects/sphere_data.k65")
    print(f"// sphere: {NPTS} points ({len(stored)} stored), {SPH_FRAMES_N} of {FRAMES} frames stored;"
          f" turns X/Y/Z = {TURNS}, radius {RX} px / {RY} lines")
    bank = SPH_BANK
    print(f"\nbank bank{bank};\n")
    print(f"data SphAnim{bank} {{\n    address 0x{ADDR_ANIM:04X}\n{rows(anim, 32)}\n}}")
    emit_tables(bank, *tables)
    # the tables are read through fixed-address vars, so reference their labels once
    # (in a never-executed block) or the linker drops them as unused
    refs = " ".join(f"a={n}{bank}" for n in ("SphAnim", "SphScale", "SphLineBand", "SphCandBase", "SphCandOff", "SphLineCand"))
    print(f"func sph_proc{bank} {{\n    never {{ {refs} }}\n    sph_body\n}}")

    emit_rot()
    print(f"\n// === bank{ENGINE_BANK}: dot engine of the live shapes + logos ===")
    print(f"bank bank{ENGINE_BANK};\n")
    emit_tables(ENGINE_BANK, *tables)
    for i, shape in enumerate(SHAPES):
        emit_live(*shape, first=i == 0)


def emit_rot():
    """Rotation bank: one copy of the sin / quarter-square tables, the multiply routine and the
    *_setup functions of all live shapes. Normal labels - only code in this bank reads them."""
    ang = [2 * math.pi * i / FRAMES for i in range(FRAMES + FRAMES // 4)]   # cos(i) = sin(i + 33)
    print(f"\n// === bank{ROT_BANK}: rotation of the live shapes (once per frame, above the picture) ===")
    print(f"bank bank{ROT_BANK};\n")
    print(f"// sin x {DIA_AMP}, {len(ang)} entries: LvSin+{FRAMES // 4} = cos")
    print(f"data LvSin {{\n{rows([round(DIA_AMP * math.sin(t)) & 0xFF for t in ang])}\n}}")
    for name, amp in G_TABLES.items():
        print(f"// sin x {amp} ({amp / DIA_AMP:.2f} of the unit)")
        print(f"data {name} {{\n{rows([round(amp * math.sin(t)) & 0xFF for t in ang])}\n}}")
    # quarter squares: sq(|a+b|) - sq(|a-b|) = 4ab/126 = a*b*2/63 (double precision, |a|,|b| <= 63)
    print(f"data LvSq {{\n{rows([round(n * n / (4 * DIA_AMP / 2)) for n in range(2 * DIA_AMP + 1)])}\n}}")
    print("func lv_mul {                    // A = tmp1 * tmp2 * 2/63\n    dia_mul\n}")
    for name, _, _, _, prefix in SHAPES:
        print(f"func {prefix}_setup{ROT_BANK} {{                  // {name}: rotate the vertices (top of the picture)"
              f"\n    {prefix}_setup\n}}")


def emit_live(name, verts, pairs, zp, prefix, first):
    """Live vertex shape: no animation frames, the 6502 rotates it ({prefix}_setup in ROT_BANK,
    {prefix}_body here in ENGINE_BANK, both in sphere_defs.k65). Point list = vertex ids:
    ShpPairA = id, ShpPairB = id / 0x80 lone vertex / 0x40 quarter point (= the previous point,
    the midpoint of the same edge, averaged with vertex A once more) / id | 0x20 quarter point
    computed from scratch (pyr_body only). The first shape keeps the placement tables linked."""
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
    pre = prefix.capitalize()
    bank = ENGINE_BANK
    print(f"\n// {name}: {len(pairs)} drawn points, rotation computed at runtime ({prefix}_setup{ROT_BANK})")
    assert len(pairs) < 64
    print(f"data {pre}PairA {{\n{rows(pa)}\n}}")
    print(f"data {pre}PairB {{\n{rows(pb)}\n}}")
    print(f"data {pre}Zp {{ {' '.join(str(z) for z in zp)} }}   // vertex id -> its RAM (x byte, y byte)")
    # the placement tables are read through fixed-address vars (sph_place is shared with the
    # sphere's bank), so reference their labels once or the linker drops them as unused
    refs = " ".join(f"a={n}{bank}" for n in ("SphScale", "SphLineBand", "SphCandBase", "SphCandOff",
                                             "SphLineCand")) if first else ""
    never = f"\n    never {{ {refs} }}" if refs else ""
    print(f"func {prefix}_proc{bank} {{{never}\n    {prefix}_body\n}}")


# Atari "Fuji" logo, flat (z = 0), spinning around the vertical axis at runtime (ENGINE_BANK):
# x = x0 * cos(angle) via quarter squares, y constant. 10 vertices, 3 points per segment.
LOGO_V = [(-0.07, 1.0), (-0.07, -1.0), (0.07, 1.0), (0.07, -1.0),       # centre bar (2 columns)
          (0.26, 1.0), (0.42, -0.25), (1.0, -1.0),                      # right prong
          (-0.26, 1.0), (-0.42, -0.25), (-1.0, -1.0)]                   # left prong
LOGO_SEG = [(0, 1), (2, 3), (4, 5), (5, 6), (7, 8), (8, 9)]
LOGO_W = 1.2                        # logo is wider than the sphere radius
LOGO_BANK = "bank" + ENGINE_BANK

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
    for n, t in (("LogoSq", sq), ("LogoCos", cos), ("LogoX", lx), ("LogoY", ly)):
        print(f"data {n} {{\n{rows(t)}\n}}")
    print(f"""func logo_proc{LOGO_BANK[-1]} {{
    x=sp_frame x?[{FRAMES // 2 + 1}] >={{ a=[{FRAMES}] c+ a-sp_frame x=a }}   // mirror: cos(N-f) = cos(f)
    a=LogoCos,x ptrC=a                              // c = 64*cos(angle)
    a=0 x=sp_shape x?5 =={{ a=[{altair_base}] }} sp_lbase=a       // point set: 4 Atari, 5 Altair
    logo_body
}}""")
    return len(pts)


if __name__ == "__main__":
    main()
    emit_logo()
