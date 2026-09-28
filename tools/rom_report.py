#!/usr/bin/env python3
"""ROM usage report of a K65 build (reads bin/demo.gmap, bin/demo.sym, bin/demo.bin).

Per bank: used / free bytes and the largest contiguous free block (a function must fit in ONE
block), optionally the sections with their sizes; then the sections whose bytes appear in more
than one bank (the same table or code copied into several banks).

Usage:  python3 tools/rom_report.py [bin/demo] [--sections] [--min-dup 16]
"""
import argparse
import hashlib
import re
from collections import defaultdict

# system_a2600.nut link_write_binary: 8-bank ROM image = banks 4 5 2 3 0 1 6 7 (F4 hotspot order)
F4_IMAGE_ORDER = [4, 5, 2, 3, 0, 1, 6, 7]


def parse_gmap(path):
    """-> {bank name: (list of (address, size, short name), free map string)}"""
    banks = {}
    for block in re.split(r"(?=^Bank \d+:)", open(path).read(), flags=re.M):
        m = re.match(r"Bank (\d+): (\w+)", block)
        if not m:
            continue
        cells = [["?"] * 64 for _ in range(64)]        # 64 rows of 64 bytes = 4 KB
        for addr, row in re.findall(r"^\$([0-9A-F]{4}):  (.*)$", block, re.M):
            cells[(int(addr, 16) - 0xF000) // 64] = list(row.ljust(64, "?")[:64])
        s = "".join("".join(r) for r in cells)
        sections, i = [], 0
        while i < len(s):
            if s[i] == "[":
                j = s.index("]", i)
                sections.append((0xF000 + i, j - i + 1, s[i + 1:j].rstrip("-")))
                i = j + 1
            else:
                i += 1
        banks[m.group(2)] = (int(m.group(1)), sections, s)
    return banks


def parse_sym(path):
    """-> {address: [names]}"""
    by_addr = defaultdict(list)
    for line in open(path):
        parts = line.split()
        if len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{4}", parts[1]):
            by_addr[int(parts[1], 16)].append(parts[0])
    return by_addr


def full_name(short, addr, syms):
    names = [n for n in syms.get(addr, []) if n.startswith(short)] or syms.get(addr, []) or [short]
    return names[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", nargs="?", default="bin/demo", help="build output without extension")
    ap.add_argument("--sections", action="store_true", help="list the sections of every bank")
    ap.add_argument("--min-dup", type=int, default=16, help="smallest section reported as a copy")
    args = ap.parse_args()

    banks = parse_gmap(args.base + ".gmap")
    syms = parse_sym(args.base + ".sym")
    rom = open(args.base + ".bin", "rb").read()

    print("bank    num  used  free  largest free block")
    total_free = 0
    for name, (num, sections, s) in banks.items():
        free = s.count("?")
        total_free += free
        best, start = (0, 0), None
        for i, c in enumerate(s + "x"):
            if c == "?" and start is None:
                start = i
            elif c != "?" and start is not None:
                best = max(best, (i - start, start))
                start = None
        print(f"{name:7} {num:3}  {4096 - free:4}  {free:4}  {best[0]:4} @ ${0xF000 + best[1]:04X}")
    print(f"total free: {total_free} bytes")

    if args.sections:
        for name, (num, sections, _) in banks.items():
            print(f"\n{name}:")
            for addr, size, short in sections:
                print(f"  ${addr:04X} {size:5}  {full_name(short, addr, syms)}")

    copies = defaultdict(list)                     # content hash -> [(bank, addr, size, name)]
    for name, (num, sections, _) in banks.items():
        for addr, size, short in sections:
            if size < args.min_dup:
                continue
            slot = F4_IMAGE_ORDER.index(num) if len(rom) == 32768 else num
            data = rom[slot * 4096 + addr - 0xF000:][:size]
            copies[hashlib.sha1(data).hexdigest()].append((name, addr, size, full_name(short, addr, syms)))
    dups = [v for v in copies.values() if len({b for b, *_ in v}) > 1]
    print("\nsame bytes in several banks:" if dups else "\nno section is copied between banks")
    wasted = 0
    for v in sorted(dups, key=lambda v: -v[0][2] * (len(v) - 1)):
        size = v[0][2]
        wasted += size * (len(v) - 1)
        print(f"  {size:5} B x{len(v)}: " + ", ".join(f"{n} ({b} ${a:04X})" for b, a, _, n in v))
    if dups:
        print(f"  -> {wasted} bytes in extra copies")


if __name__ == "__main__":
    main()
