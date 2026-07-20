#!/usr/bin/env python3
"""Check whether a .ply is a SplatAgent-loadable INRIA 3DGS file.

The backend loader (backend/splat/model.py) needs binary little-endian PLY with
vertex props: x,y,z, f_dc_0..2, opacity, scale_0..2, rot_0..3, and an f_rest
count of exactly 0, 9, 24, or 45 (SH degree 0-3). Mesh PLYs and COLMAP seed
clouds (input.ply) fail. This reads only the header — no full download/parse.

Usage:
    python examples/check_ply.py path/to/scene.ply
    # remote, header only (cheap):
    curl -sL -r 0-6000 "<url>" | python examples/check_ply.py -
"""
import sys

REQUIRED = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2",
            "opacity", "scale_0", "scale_1", "scale_2",
            "rot_0", "rot_1", "rot_2", "rot_3"]
VALID_FREST = {0: "deg 0", 9: "deg 1", 24: "deg 2", 45: "deg 3"}


def read_header(stream) -> list[str]:
    raw = bytearray()
    while b"end_header" not in raw:
        chunk = stream.read(1)
        if not chunk:
            break
        raw += chunk
        if len(raw) > 200_000:  # runaway guard
            break
    return raw.decode("latin-1").splitlines()


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else "-"
    stream = sys.stdin.buffer if src == "-" else open(src, "rb")
    lines = read_header(stream)

    if not lines or not lines[0].startswith("ply"):
        print("FAIL: not a PLY file"); return 1

    fmt = next((l for l in lines if l.startswith("format")), "")
    props = [l.split()[-1] for l in lines if l.startswith("property")]
    count = next((l.split()[-1] for l in lines if l.startswith("element vertex")), "?")

    missing = [p for p in REQUIRED if p not in props]
    frest = sum(1 for p in props if p.startswith("f_rest_"))

    print(f"vertices:   {count}")
    print(f"format:     {fmt.replace('format ', '') or '?'}")
    print(f"f_rest:     {frest}  ({VALID_FREST.get(frest, 'INVALID')})")

    ok = True
    if "binary_little_endian" not in fmt:
        print("FAIL: must be binary_little_endian"); ok = False
    if missing:
        print(f"FAIL: missing splat fields: {missing}"); ok = False
    if frest not in VALID_FREST:
        print(f"FAIL: f_rest count {frest} not in {sorted(VALID_FREST)}"); ok = False

    print("\n" + ("OK — this will load and the agent can edit it." if ok
                  else "NOT loadable (see FAIL lines above)."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
