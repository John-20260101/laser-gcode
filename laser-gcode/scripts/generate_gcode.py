#!/usr/bin/env python3
"""Generate GRBL laser G-code from vertex lists or SVG.

Job types: cut (vector), engrave (outline), fill (hatch scan).
Power normalized: S = power_percent/100 * grbl_max_s ($30, default 1000).
"""
from __future__ import annotations
import argparse, json, math, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAT_PATH = HERE.parent / "references" / "materials.json"


def load_materials() -> dict:
    if not MAT_PATH.exists():
        raise FileNotFoundError(f"materials.json not found at {MAT_PATH}")
    return json.loads(MAT_PATH.read_text(encoding="utf-8"))


def pick_tier(materials: dict, material: str, laser_w: float) -> tuple[str, dict]:
    if material not in materials:
        avail = ", ".join(k for k in materials if not k.startswith("_"))
        raise ValueError(f"unknown material '{material}'. Available: {avail}")
    tiers = materials[material]["tiers"]
    keys = sorted(float(k) for k in tiers)
    # choose closest tier at or above laser_w, else highest
    chosen = None
    for k in keys:
        if k >= laser_w:
            chosen = k
            break
    if chosen is None:
        chosen = keys[-1]
    return str(int(chosen)), tiers[str(int(chosen))]


def compute_s(power_percent: float, grbl_max_s: int) -> int:
    return max(0, min(grbl_max_s, round(power_percent / 100.0 * grbl_max_s)))


# ---------------------------------------------------------------------------
# Input loading: vertices (JSON/list) or SVG
# ---------------------------------------------------------------------------
def parse_vertices(text: str) -> list[list[float]]:
    """Accept JSON array of [x,y] or 'x,y x,y ...' or 'x y; x y'."""
    text = text.strip()
    if text.startswith("["):
        return [[float(p[0]), float(p[1])] for p in json.loads(text)]
    nums = re.findall(r"[-+0-9.]+", text)
    if len(nums) % 2 != 0:
        raise ValueError(f"odd number of coordinates: {len(nums)}")
    pts = [[float(nums[i]), float(nums[i + 1])] for i in range(0, len(nums), 2)]
    if len(pts) < 3:
        raise ValueError(f"need >=3 vertices, got {len(pts)}")
    return pts


def load_svg(path: str) -> list[list[list[float]]]:
    """Parse SVG, return list of closed polygons (flattened beziers)."""
    tree = ET.parse(path)
    root = tree.getroot()
    ns = re.match(r"\{.*\}", root.tag)
    ns = ns.group(0) if ns else ""
    polys: list[list[list[float]]] = []
    for el in root.iter():
        tag = el.tag.replace(ns, "")
        if tag == "polygon" or tag == "polyline":
            pts = el.get("points", "")
            p = [[float(a), float(b)] for a, b in re.findall(
                r"([-+0-9.]+)[,\s]+([-+0-9.]+)", pts)]
            if tag == "polygon" and p:
                p.append(p[0])
            if len(p) >= 3:
                polys.append(p)
        elif tag == "rect":
            x, y = float(el.get("x", 0)), float(el.get("y", 0))
            w, h = float(el.get("width", 0)), float(el.get("height", 0))
            polys.append([[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]])
        elif tag == "path":
            d = el.get("d", "")
            for poly in flatten_path(d):
                if len(poly) >= 3:
                    polys.append(poly)
    if not polys:
        raise ValueError(f"no usable shapes found in SVG {path}")
    return polys


def flatten_path(d: str, steps: int = 24) -> list[list[list[float]]]:
    """Flatten SVG path 'd' (M/L/H/V/C/Q/Z) into polylines."""
    cmds = re.findall(r"[MLHVCSQTAZmlhvcsqtaZ]|[-+0-9.]+", d)
    polys, cur, start = [], [0.0, 0.0], None
    i = 0

    def nums(n):
        nonlocal i
        out = []
        for _ in range(n):
            out.append(float(cmds[i])); i += 1
        return out

    while i < len(cmds):
        c = cmds[i]; i += 1
        if c in "Mm":
            x, y = nums(2)
            if c == "m":
                x += cur[0]; y += cur[1]
            cur = [x, y]; start = [x, y]; poly = [list(cur)]
            # subsequent pairs are L
            while i < len(cmds) and not cmds[i].isalpha():
                x, y = nums(2)
                if c == "m":
                    x += cur[0]; y += cur[1]
                cur = [x, y]; poly.append(list(cur))
            polys.append(poly)
        elif c in "Ll":
            while i < len(cmds) and not cmds[i].isalpha():
                x, y = nums(2)
                if c == "l":
                    x += cur[0]; y += cur[1]
                cur = [x, y]; polys[-1].append(list(cur))
        elif c in "Hh":
            while i < len(cmds) and not cmds[i].isalpha():
                x = float(cmds[i]); i += 1
                if c == "h":
                    x += cur[0]
                cur = [x, cur[1]]; polys[-1].append(list(cur))
        elif c in "Vv":
            while i < len(cmds) and not cmds[i].isalpha():
                y = float(cmds[i]); i += 1
                if c == "v":
                    y += cur[1]
                cur = [cur[0], y]; polys[-1].append(list(cur))
        elif c in "Cc":
            while i < len(cmds) and not cmds[i].isalpha():
                x1, y1, x2, y2, x, y = nums(6)
                if c == "c":
                    x1 += cur[0]; y1 += cur[1]; x2 += cur[0]; y2 += cur[1]
                    x += cur[0]; y += cur[1]
                polys[-1] += bezier(cur, [x1, y1], [x2, y2], [x, y], steps)
                cur = [x, y]
        elif c in "Qq":
            while i < len(cmds) and not cmds[i].isalpha():
                x1, y1, x, y = nums(4)
                if c == "q":
                    x1 += cur[0]; y1 += cur[1]; x += cur[0]; y += cur[1]
                polys[-1] += bezier_q(cur, [x1, y1], [x, y], steps)
                cur = [x, y]
        elif c in "Zz":
            if start:
                polys[-1].append(list(start)); cur = list(start)
        else:
            break
    return polys


def bezier(p0, p1, p2, p3, steps):
    pts = []
    for k in range(1, steps + 1):
        t = k / steps; mt = 1 - t
        x = mt**3 * p0[0] + 3*mt**2*t*p1[0] + 3*mt*t**2*p2[0] + t**3*p3[0]
        y = mt**3 * p0[1] + 3*mt**2*t*p1[1] + 3*mt*t**2*p2[1] + t**3*p3[1]
        pts.append([x, y])
    return pts


def bezier_q(p0, p1, p2, steps):
    pts = []
    for k in range(1, steps + 1):
        t = k / steps; mt = 1 - t
        x = mt**2 * p0[0] + 2*mt*t*p1[0] + t**2 * p2[0]
        y = mt**2 * p0[1] + 2*mt*t*p1[1] + t**2 * p2[1]
        pts.append([x, y])
    return pts


# ---------------------------------------------------------------------------
# Coordinate transform
# ---------------------------------------------------------------------------
def transform(verts, input_origin, output_origin, target_w, target_h,
              norm=100.0, offset=(0.0, 0.0)):
    """Scale normalized verts to target mm, handle Y orientation, offset."""
    out = []
    for x, y in verts:
        nx = x / norm * target_w + offset[0]
        ny = y / norm * target_h + offset[1]
        if input_origin == "top-left" and output_origin == "bottom-left":
            ny = target_h - ny  # flip Y
        out.append([round(nx, 3), round(ny, 3)])
    return out


# ---------------------------------------------------------------------------
# G-code generation
# ---------------------------------------------------------------------------
def header(comments):
    lines = ["; " + c for c in comments]
    return "\n".join(lines) + "\nG21\nG90\nG17\nM5\n"


def gen_outline(verts, s, feed, passes, label):
    """Cut or engrave a closed polygon outline."""
    if not verts:
        return ""
    out = [f"; --- {label} (S={s}, F={feed}, passes={passes}) ---"]
    out.append(f"G0 X{verts[0][0]:.3f} Y{verts[0][1]:.3f}")
    out.append(f"M3 S{s}")
    out.append(f"G1 F{feed}")
    for p in range(passes):
        for x, y in verts[1:]:
            out.append(f"G1 X{x:.3f} Y{y:.3f}")
        out.append(f"G1 X{verts[0][0]:.3f} Y{verts[0][1]:.3f}")  # close
    out.append("M5")
    return "\n".join(out) + "\n"


def gen_fill(verts, spacing, angle, s, feed):
    """Hatch-fill a closed polygon with boustrophedon scanlines."""
    if len(verts) < 3:
        raise ValueError("fill needs a closed polygon (>=3 vertices)")
    # rotate polygon so we scan horizontally in the rotated frame
    a = math.radians(angle)
    rot = [[x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)]
           for x, y in verts]
    xs = [p[0] for p in rot]; ys = [p[1] for p in rot]
    y0, y1 = min(ys), max(ys)
    out = [f"; --- hatch fill (S={s}, F={feed}, spacing={spacing}mm, angle={angle}deg) ---"]
    n = 0
    y = y0
    while y <= y1 + 1e-9:
        segs = scanline(rot, y)
        segs.sort()
        # pair up
        on = [(segs[i], segs[i + 1]) for i in range(0, len(segs) - 1, 2)]
        if not on:
            y += spacing; n += 1; continue
        fwd = (n % 2 == 0)
        if not fwd:
            on = list(reversed(on))
        first = True
        for xa, xb in on:
            if not fwd:
                xa, xb = xb, xa
            p0 = unrot(xa, y, a); p1 = unrot(xb, y, a)
            if first:
                out.append(f"G0 X{p0[0]:.3f} Y{p0[1]:.3f}")
                out.append(f"M3 S{s}")
                out.append(f"G1 F{feed}")
                first = False
            else:
                out.append(f"G1 X{p0[0]:.3f} Y{p0[1]:.3f}")  # travel off (laser still on but zero-width gap)
            out.append(f"G1 X{p1[0]:.3f} Y{p1[1]:.3f}")
        out.append("M5")
        y += spacing; n += 1
    return "\n".join(out) + "\n" if len(out) > 1 else ""


def unrot(x, y, a):
    nx = x * math.cos(a) + y * math.sin(a)
    ny = -x * math.sin(a) + y * math.cos(a)
    return [round(nx, 3), round(ny, 3)]


def scanline(poly, y):
    """Return x-intersections of horizontal line y with polygon edges."""
    xs = []
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        if (y1 <= y < y2) or (y2 <= y < y1):
            t = (y - y1) / (y2 - y1) if y2 != y1 else 0
            xs.append(x1 + t * (x2 - x1))
    return xs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Generate GRBL laser G-code")
    ap.add_argument("--config", help="JSON config file (overrides all flags)")
    ap.add_argument("--vertices", help="vertex list: JSON array or 'x,y x,y ...'")
    ap.add_argument("--svg", help="SVG file path")
    ap.add_argument("--job", choices=["cut", "engrave", "fill"], default="cut")
    ap.add_argument("--material", default="plywood_3mm")
    ap.add_argument("--laser-w", type=float, default=10.0, help="laser rated optical watts")
    ap.add_argument("--grbl-max-s", type=int, default=1000, help="$30 max S value")
    ap.add_argument("--target-size", nargs=2, type=float, default=[100.0, 100.0],
                    metavar=("W_MM", "H_MM"))
    ap.add_argument("--input-origin", choices=["top-left", "bottom-left"], default="top-left")
    ap.add_argument("--output-origin", choices=["bottom-left", "top-left"], default="bottom-left")
    ap.add_argument("--power", type=float, help="override power %%")
    ap.add_argument("--feed", type=float, help="override feed mm/min")
    ap.add_argument("--passes", type=int, help="override passes")
    ap.add_argument("--hatch-spacing", type=float, default=0.2, help="fill line spacing mm")
    ap.add_argument("--hatch-angle", type=float, default=0.0, help="fill angle degrees")
    ap.add_argument("--offset", nargs=2, type=float, default=[0.0, 0.0], metavar=("X", "Y"))
    ap.add_argument("--output", "-o", help="output .gcode path (default: stdout)")
    args = ap.parse_args()

    cfg = {}
    if args.config:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))

    def get(k, d):
        if k in cfg:
            return cfg[k]
        val = getattr(args, k.replace("-", "_"), None)
        return val if val is not None else d

    job = get("job", "cut")
    material = get("material", "plywood_3mm")
    laser_w = float(get("laser_w", 10.0))
    grbl_max_s = int(get("grbl_max_s", 1000))
    tw, th = get("target_size", [100.0, 100.0])
    in_origin = get("input_origin", "top-left")
    out_origin = get("output_origin", "bottom-left")
    spacing = float(get("hatch_spacing", 0.2))
    angle = float(get("hatch_angle", 0.0))
    ox, oy = get("offset", [0.0, 0.0])

    materials = load_materials()
    tier_label, tier = pick_tier(materials, material, laser_w)
    # fill reuses engrave parameters (it is a form of engraving)
    param_key = job if job in tier else "engrave"
    params = tier[param_key]
    if job == "cut" and params.get("passes", 0) == 0:
        raise ValueError(f"material '{material}' does not support cutting")

    power = float(get("power", params["power"]))
    feed = float(get("feed", params["feed"]))
    passes = int(get("passes", params["passes"]))
    s = compute_s(power, grbl_max_s)

    # load geometry
    verts_raw = cfg.get("vertices")
    svg = cfg.get("svg") or args.svg
    if verts_raw is not None:
        polys = [parse_vertices(verts_raw if isinstance(verts_raw, str) else json.dumps(verts_raw))]
    elif svg:
        polys = load_svg(svg)
    elif args.vertices:
        polys = [parse_vertices(args.vertices)]
    else:
        ap.error("provide --vertices, --svg, or a config with vertices/svg")

    # transform each polygon
    polys = [transform(p, in_origin, out_origin, tw, th, 100.0, (ox, oy)) for p in polys]

    mat_name = materials[material]["name"]
    comments = [
        f"Job: {job} | Material: {mat_name} | Laser: {laser_w}W (tier {tier_label}W)",
        f"Power: {power}% -> S{s}/{grbl_max_s} | Feed: {feed} mm/min | Passes: {passes}",
        f"Target: {tw}x{th} mm | Origin(out): {out_origin} | Polygons: {len(polys)}",
        "WARNING: starting parameters - always test on scrap first.",
    ]
    gcode = header(comments)
    for idx, poly in enumerate(polys):
        if job == "fill":
            gcode += gen_fill(poly, spacing, angle, s, feed)
        else:
            gcode += gen_outline(poly, s, feed, passes, f"{job} poly{idx+1}")
    gcode += "M5\nG0 X0 Y0\nM2\n"

    if args.output:
        Path(args.output).write_text(gcode, encoding="utf-8")
        print(f"Wrote {args.output} ({len(gcode)} bytes)", file=sys.stderr)
    else:
        sys.stdout.write(gcode)
    # summary to stderr
    print(f"[summary] S={s} feed={feed} passes={passes} polys={len(polys)}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
