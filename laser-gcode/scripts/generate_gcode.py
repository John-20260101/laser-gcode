#!/usr/bin/env python3
"""Generate GRBL laser G-code from vertex lists or SVG files.

Job types: cut (vector), engrave (outline), fill (hatch scan).

Pipeline:
    1. parse      - vertices or SVG -> subpaths in the source's own units
    2. frame map  - the declared frame (0-100 grid, --frame, or the SVG
                    viewBox/width/height) is mapped onto the target size in mm
    3. flatten    - curves are flattened in mm with a real chord tolerance
    4. emit       - G-code that never rapids with the laser on

Power normalization: S = power_percent / 100 * grbl_max_s (GRBL $30, default 1000).
The material table is keyed by laser wattage tier, so one table serves a 10W and
a 40W machine; see references/materials.md.

Standard library only, and compatible with Python 3.9 (the stock python3 on macOS).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAT_PATH = HERE.parent / "references" / "materials.json"

PARAM_KEYS = ("power", "feed", "passes")
JOB_BLOCKS = ("cut", "engrave", "fill")
EXIT_USER_ERROR = 2

WARNINGS = []


def warn(msg: str) -> None:
    """Record a non-fatal problem; every warning is printed at the end."""
    WARNINGS.append(msg)


class UserError(Exception):
    """Bad input, bad geometry or bad config: reported as [error], no traceback."""


# ---------------------------------------------------------------------------
# Material database
# ---------------------------------------------------------------------------
def validate_materials(data) -> list:
    """Return a list of human-readable schema problems (empty when valid)."""
    problems = []
    if not isinstance(data, dict):
        return ["top level must be a JSON object"]
    for key, entry in data.items():
        if key.startswith("_"):
            continue
        if not isinstance(entry, dict):
            problems.append("%s: entry must be an object" % key)
            continue
        if not isinstance(entry.get("name"), str):
            problems.append("%s.name: required string" % key)
        tiers = entry.get("tiers")
        if not isinstance(tiers, dict) or not tiers:
            problems.append("%s.tiers: required non-empty object" % key)
            continue
        for tkey, tier in tiers.items():
            where = "%s.tiers[%s]" % (key, tkey)
            try:
                float(tkey)
            except (TypeError, ValueError):
                problems.append("%s: tier key must be a number" % where)
                continue
            if not isinstance(tier, dict) or not tier:
                problems.append("%s: must be an object with cut/engrave blocks" % where)
                continue
            for block_name, block in tier.items():
                if block_name not in JOB_BLOCKS:
                    problems.append("%s.%s: unknown job block" % (where, block_name))
                    continue
                if not isinstance(block, dict):
                    problems.append("%s.%s: must be an object" % (where, block_name))
                    continue
                for pk in block:
                    if pk not in PARAM_KEYS:
                        problems.append("%s.%s.%s: unknown parameter" % (where, block_name, pk))
                for pk in PARAM_KEYS:
                    if pk not in block:
                        problems.append("%s.%s: missing '%s'" % (where, block_name, pk))
                power = block.get("power")
                feed = block.get("feed")
                passes = block.get("passes")
                if isinstance(power, bool) or not isinstance(power, (int, float)) or not 0 <= power <= 100:
                    problems.append("%s.%s.power: must be a number 0-100" % (where, block_name))
                if isinstance(feed, bool) or not isinstance(feed, (int, float)) or feed < 0:
                    problems.append("%s.%s.feed: must be a number >= 0" % (where, block_name))
                if isinstance(passes, bool) or not isinstance(passes, int) or passes < 0:
                    problems.append("%s.%s.passes: must be an integer >= 0" % (where, block_name))
            for required in ("cut", "engrave"):
                if required not in tier:
                    problems.append("%s: missing '%s' block (a cut block with passes=0 means "
                                    "'cannot cut')" % (where, required))
    return problems


def load_materials(path=None) -> dict:
    path = Path(path) if path else MAT_PATH
    if not path.exists():
        raise UserError("material database not found at %s" % path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UserError("materials.json is not valid JSON: %s" % exc)
    problems = validate_materials(data)
    if problems:
        raise UserError("materials.json schema problems:\n  - " + "\n  - ".join(problems))
    return data


def material_keys(materials) -> list:
    return sorted(k for k in materials if not k.startswith("_"))


def list_materials(materials) -> str:
    rows = []
    for key in material_keys(materials):
        entry = materials[key]
        tiers = entry["tiers"]
        can_cut = any(t.get("cut", {}).get("passes", 0) > 0 for t in tiers.values())
        rows.append("%-20s %-52s tiers=%-16s cut=%-3s engrave=%s" % (
            key,
            entry.get("name", ""),
            ",".join(sorted(tiers, key=float)),
            "yes" if can_cut else "no",
            "yes" if any("engrave" in t for t in tiers.values()) else "no",
        ))
    return "\n".join(rows)


def pick_tier(materials, material, laser_w):
    """Choose the tier at or above laser_w (else the highest) and explain the choice."""
    if material not in materials or material.startswith("_"):
        raise UserError("unknown material '%s'. Available: %s"
                        % (material, ", ".join(material_keys(materials))))
    tiers = materials[material]["tiers"]
    numeric = sorted((float(k), k) for k in tiers)
    lowest = numeric[0][0]
    highest = numeric[-1][0]
    chosen = None
    for value, raw in numeric:
        if value >= laser_w:
            chosen = (value, raw)
            break
    if chosen is None:
        chosen = numeric[-1]
        warn("laser_w=%gW is above the highest tier for %s (%gW): using the %gW values, so the "
             "delivered optical power will be HIGHER than the table intends. Lower it with "
             "--power/--passes and test on scrap first."
             % (laser_w, material, highest, highest))
    elif chosen[0] > laser_w:
        if laser_w < lowest:
            warn("laser_w=%gW is below the lowest tier for %s (%gW): using the %gW values, so "
                 "expect to need more passes (try --passes N+1) and verify on scrap."
                 % (laser_w, material, lowest, chosen[0]))
        else:
            warn("laser_w=%gW sits between tiers for %s: using the %gW tier (nearest at or "
                 "above). If it under-cuts, override with --power/--passes."
                 % (laser_w, material, chosen[0]))
    value, raw = chosen
    return ("%g" % value), tiers[raw]


def compute_s(power_percent: float, grbl_max_s: int) -> int:
    return int(max(0, min(grbl_max_s, round(power_percent / 100.0 * grbl_max_s))))


# ---------------------------------------------------------------------------
# 2D affine helpers (x' = a*x + c*y + e, y' = b*x + d*y + f)
# ---------------------------------------------------------------------------
IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mat_mul(m, n):
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def mat_apply(m, p):
    a, b, c, d, e, f = m
    return (a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f)


TRANSFORM_RE = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")


def _numbers(text) -> list:
    return [float(v) for v in re.split(r"[\s,]+", str(text).strip()) if v]


def _transform_matrix(name: str, nums: list, source: str):
    if name == "matrix":
        if len(nums) != 6:
            raise UserError("matrix() needs 6 numbers in transform=%r" % source)
        return tuple(nums)
    if name == "translate":
        if len(nums) not in (1, 2):
            raise UserError("translate() needs 1 or 2 numbers in transform=%r" % source)
        return (1.0, 0.0, 0.0, 1.0, nums[0], nums[1] if len(nums) > 1 else 0.0)
    if name == "scale":
        if len(nums) not in (1, 2):
            raise UserError("scale() needs 1 or 2 numbers in transform=%r" % source)
        sy = nums[1] if len(nums) > 1 else nums[0]
        return (nums[0], 0.0, 0.0, sy, 0.0, 0.0)
    if name == "rotate":
        if len(nums) not in (1, 3):
            raise UserError("rotate() needs 1 or 3 numbers in transform=%r" % source)
        angle = math.radians(nums[0])
        rot = (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 0.0, 0.0)
        if len(nums) == 1:
            return rot
        cx, cy = nums[1], nums[2]
        return mat_mul(mat_mul((1.0, 0.0, 0.0, 1.0, cx, cy), rot),
                       (1.0, 0.0, 0.0, 1.0, -cx, -cy))
    if name in ("skewX", "skewY"):
        if len(nums) != 1:
            raise UserError("%s() needs 1 number in transform=%r" % (name, source))
        tangent = math.tan(math.radians(nums[0]))
        if name == "skewX":
            return (1.0, 0.0, tangent, 1.0, 0.0, 0.0)
        return (1.0, tangent, 0.0, 1.0, 0.0, 0.0)
    raise UserError("unsupported SVG transform function %r" % name)


def parse_transform(text) -> tuple:
    if not text or not str(text).strip():
        return IDENT
    text = str(text)
    mat = IDENT
    pos = 0
    for match in TRANSFORM_RE.finditer(text):
        gap = text[pos:match.start()].strip(" ,\t\r\n")
        if gap:
            raise UserError("unsupported SVG transform text %r in transform=%r" % (gap, text))
        mat = mat_mul(mat, _transform_matrix(match.group(1), _numbers(match.group(2)), text))
        pos = match.end()
    tail = text[pos:].strip(" ,\t\r\n")
    if tail:
        raise UserError("unsupported SVG transform text %r in transform=%r" % (tail, text))
    return mat


# ---------------------------------------------------------------------------
# Geometry containers: a subpath is {start, segs, closed}
# segs hold ("L", p0, p1) or ("C", p0, c1, c2, p1)
# ---------------------------------------------------------------------------
def _xform_seg(seg, m):
    if seg[0] == "L":
        return ("L", mat_apply(m, seg[1]), mat_apply(m, seg[2]))
    return ("C", mat_apply(m, seg[1]), mat_apply(m, seg[2]),
            mat_apply(m, seg[3]), mat_apply(m, seg[4]))


def xform_sub(sub, m) -> dict:
    return {"start": mat_apply(m, sub["start"]),
            "segs": [_xform_seg(s, m) for s in sub["segs"]],
            "closed": sub["closed"]}


def sub_bbox(subs):
    xs, ys = [], []
    for sub in subs:
        xs.append(sub["start"][0]); ys.append(sub["start"][1])
        for seg in sub["segs"]:
            end = seg[2] if seg[0] == "L" else seg[4]
            xs.append(end[0]); ys.append(end[1])
    if not xs:
        raise UserError("no geometry found")
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# Vertex input
# ---------------------------------------------------------------------------
def parse_vertices(text) -> list:
    """Accept 'x,y x,y ...', 'x y; x y', or a JSON array of [x, y] pairs."""
    if isinstance(text, (list, tuple)):
        text = json.dumps(text)
    text = str(text).strip()
    if not text:
        raise UserError("--vertices is empty")
    if text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise UserError("cannot parse --vertices JSON: %s" % exc)
        try:
            pts = [(float(p[0]), float(p[1])) for p in data]
        except (TypeError, IndexError, ValueError):
            raise UserError("--vertices JSON must be a list of [x, y] pairs")
    else:
        nums = re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", text)
        if len(nums) % 2 != 0:
            raise UserError("odd number of coordinates (%d) in --vertices; every vertex needs "
                            "an x and a y" % len(nums))
        pts = [(float(nums[i]), float(nums[i + 1])) for i in range(0, len(nums), 2)]
    if len(pts) < 3:
        raise UserError("need at least 3 vertices, got %d" % len(pts))
    segs = [("L", pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    if pts[-1] == pts[0] and len(pts) > 3:
        # a repeated first vertex is a common way to write a closed outline
        segs = segs[:-1]
    return [{"start": pts[0], "segs": segs, "closed": True}]


# ---------------------------------------------------------------------------
# SVG input
# ---------------------------------------------------------------------------
PATH_TOKEN_RE = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
NON_RENDERING = ("defs", "clipPath", "mask", "marker", "symbol", "pattern", "style",
                 "title", "desc")
GEOMETRY_ELEMENTS = ("path", "polygon", "polyline", "rect", "circle", "ellipse", "line")
SKIPPED_GEOMETRY = ("text", "tspan", "image", "use", "foreignObject")
LENGTH_UNITS = {"": 1.0, "px": 1.0, "pt": 96.0 / 72.0, "pc": 16.0,
                "mm": 96.0 / 25.4, "cm": 96.0 / 2.54, "in": 96.0, "q": 96.0 / 101.6}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def parse_length(text):
    """Return a length in user units (px), or None when unknown/unusable."""
    if text is None:
        return None
    match = re.match(r"^\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)\s*([a-zA-Z%]*)\s*$", str(text))
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "%" or unit not in LENGTH_UNITS:
        return None
    return value * LENGTH_UNITS[unit]


def _tokenize_path(d: str) -> list:
    tokens = []
    pos = 0
    for match in PATH_TOKEN_RE.finditer(d):
        gap = d[pos:match.start()].strip(" ,\t\r\n")
        if gap:
            raise UserError("unsupported character(s) %r in SVG path d=%r; supported commands "
                            "are M L H V C S Q T A Z (upper and lower case)"
                            % (gap, d[:80] + ("..." if len(d) > 80 else "")))
        tokens.append(match.group(0))
        pos = match.end()
    tail = d[pos:].strip(" ,\t\r\n")
    if tail:
        raise UserError("unsupported trailing text %r in SVG path d=%r" % (tail, d[:80]))
    return tokens


def arc_to_cubics(p0, rx, ry, phi_deg, large_arc, sweep, p1) -> list:
    """Convert an SVG elliptical arc (endpoint form) to cubic Bezier segments."""
    if p0 == p1:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [("L", p0, p1)]
    phi = math.radians(phi_deg % 360.0)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx2, dy2 = (p0[0] - p1[0]) / 2.0, (p0[1] - p1[1]) / 2.0
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den > 0 else 0.0
    if large_arc == sweep:
        coef = -coef
    cxp = coef * (rx * y1p / ry)
    cyp = -coef * (ry * x1p / rx)
    cx = cos_p * cxp - sin_p * cyp + (p0[0] + p1[0]) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (p0[1] + p1[1]) / 2.0

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        norm = math.hypot(ux, uy) * math.hypot(vx, vy)
        if norm == 0:
            return 0.0
        value = math.acos(max(-1.0, min(1.0, dot / norm)))
        return -value if (ux * vy - uy * vx) < 0 else value

    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    theta1 = angle(1.0, 0.0, ux, uy)
    delta = angle(ux, uy, vx, vy)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi

    count = max(1, int(math.ceil(abs(delta) / (math.pi / 2.0))))
    segs = []
    current = p0

    def point(t):
        return (cx + rx * math.cos(t) * cos_p - ry * math.sin(t) * sin_p,
                cy + rx * math.cos(t) * sin_p + ry * math.sin(t) * cos_p)

    def derivative(t):
        return (-rx * math.sin(t) * cos_p - ry * math.cos(t) * sin_p,
                -rx * math.sin(t) * sin_p + ry * math.cos(t) * cos_p)

    for i in range(count):
        t0 = theta1 + delta * i / count
        t1 = theta1 + delta * (i + 1) / count
        k = 4.0 / 3.0 * math.tan((t1 - t0) / 4.0)
        end = point(t1)
        d0 = derivative(t0)
        d1 = derivative(t1)
        c1 = (current[0] + k * d0[0], current[1] + k * d0[1])
        c2 = (end[0] - k * d1[0], end[1] - k * d1[1])
        segs.append(("C", current, c1, c2, end))
        current = end
    if segs:
        # float drift: pin the last endpoint to the exact arc end
        segs[-1] = ("C", segs[-1][1], segs[-1][2], segs[-1][3], p1)
    return segs


def parse_path(d: str) -> list:
    """Parse SVG path data into subpaths of L/C segments (arcs become cubics)."""
    if not d or not d.strip():
        raise UserError("SVG <path> has an empty d attribute")
    tokens = _tokenize_path(d)
    subs = []
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    segs = []
    started = False
    closed = False
    last_ctrl = None
    last_curve = None
    idx = [0]

    def has_number() -> bool:
        return idx[0] < len(tokens) and not tokens[idx[0]].isalpha()

    def read(n: int, cmd: str) -> list:
        out = []
        for _ in range(n):
            if idx[0] >= len(tokens):
                raise UserError("SVG path command %r ends after %d of %d numbers"
                                % (cmd, len(out), n))
            token = tokens[idx[0]]
            if token.isalpha():
                raise UserError("SVG path command %r needs %d numbers but found command %r"
                                % (cmd, n, token))
            out.append(float(token))
            idx[0] += 1
        return out

    def read_flag(cmd: str) -> float:
        value = read(1, cmd)[0]
        if value not in (0.0, 1.0):
            raise UserError("SVG arc flag for %r must be 0 or 1, got %g" % (cmd, value))
        return value

    def flush():
        nonlocal segs, started, closed
        if started and segs:
            subs.append({"start": start, "segs": segs, "closed": closed})
        segs = []
        started = False
        closed = False

    while idx[0] < len(tokens):
        token = tokens[idx[0]]
        if not token.isalpha():
            raise UserError("SVG path d=%r is missing a command before %r" % (d[:60], token))
        idx[0] += 1
        cmd = token
        upper = cmd.upper()
        rel = cmd.islower()

        if upper == "M":
            flush()
            x, y = read(2, cmd)
            if rel:
                x, y = x + cur[0], y + cur[1]
            cur = (x, y)
            start = (x, y)
            started = True
            last_ctrl = None
            last_curve = None
            while has_number():          # implicit lineto pairs after a moveto
                x, y = read(2, cmd)
                if rel:
                    x, y = x + cur[0], y + cur[1]
                segs.append(("L", cur, (x, y)))
                cur = (x, y)
            continue

        if not started:
            raise UserError("SVG path must begin with M (moveto); found %r" % cmd)

        if upper in ("L", "H", "V"):
            if not has_number():
                raise UserError("SVG path command %r needs coordinates" % cmd)
            while has_number():
                if upper == "L":
                    x, y = read(2, cmd)
                    if rel:
                        x, y = x + cur[0], y + cur[1]
                elif upper == "H":
                    x = read(1, cmd)[0]
                    if rel:
                        x += cur[0]
                    y = cur[1]
                else:
                    y = read(1, cmd)[0]
                    if rel:
                        y += cur[1]
                    x = cur[0]
                segs.append(("L", cur, (x, y)))
                cur = (x, y)
            last_ctrl = None
            last_curve = None
        elif upper in ("C", "S"):
            while has_number():
                if upper == "C":
                    x1, y1, x2, y2, x, y = read(6, cmd)
                    if rel:
                        x1 += cur[0]; y1 += cur[1]; x2 += cur[0]; y2 += cur[1]
                        x += cur[0]; y += cur[1]
                else:
                    x2, y2, x, y = read(4, cmd)
                    if rel:
                        x2 += cur[0]; y2 += cur[1]; x += cur[0]; y += cur[1]
                    if last_curve == "cubic" and last_ctrl is not None:
                        x1 = 2 * cur[0] - last_ctrl[0]
                        y1 = 2 * cur[1] - last_ctrl[1]
                    else:
                        x1, y1 = cur
                segs.append(("C", cur, (x1, y1), (x2, y2), (x, y)))
                last_ctrl = (x2, y2)
                last_curve = "cubic"
                cur = (x, y)
        elif upper in ("Q", "T"):
            while has_number():
                if upper == "Q":
                    qx, qy, x, y = read(4, cmd)
                    if rel:
                        qx += cur[0]; qy += cur[1]; x += cur[0]; y += cur[1]
                else:
                    x, y = read(2, cmd)
                    if rel:
                        x += cur[0]; y += cur[1]
                    if last_curve == "quad" and last_ctrl is not None:
                        qx = 2 * cur[0] - last_ctrl[0]
                        qy = 2 * cur[1] - last_ctrl[1]
                    else:
                        qx, qy = cur
                # elevate the quadratic to a cubic so one flattener handles everything
                c1 = (cur[0] + 2.0 / 3.0 * (qx - cur[0]), cur[1] + 2.0 / 3.0 * (qy - cur[1]))
                c2 = (x + 2.0 / 3.0 * (qx - x), y + 2.0 / 3.0 * (qy - y))
                segs.append(("C", cur, c1, c2, (x, y)))
                last_ctrl = (qx, qy)
                last_curve = "quad"
                cur = (x, y)
        elif upper == "A":
            while has_number():
                rx = read(1, cmd)[0]
                ry = read(1, cmd)[0]
                rot = read(1, cmd)[0]
                large = read_flag(cmd)
                sweep = read_flag(cmd)
                x, y = read(2, cmd)
                if rel:
                    x += cur[0]; y += cur[1]
                for seg in arc_to_cubics(cur, rx, ry, rot, large, sweep, (x, y)):
                    segs.append(seg)
                cur = (x, y)
            last_ctrl = None
            last_curve = None
        elif upper == "Z":
            if segs:
                if cur != start:
                    segs.append(("L", cur, start))
                closed = True
                cur = start
                flush()
                # any command after Z continues from the subpath start point
                start = cur
                started = True
            last_ctrl = None
            last_curve = None
        else:
            raise UserError("unsupported SVG path command %r" % cmd)

    flush()
    return subs


def _points_attr(text, where: str) -> list:
    nums = _numbers(text)
    if len(nums) % 2 != 0:
        raise UserError("%s has an odd number of coordinates" % where)
    pts = [(nums[i], nums[i + 1]) for i in range(0, len(nums), 2)]
    if len(pts) < 2:
        raise UserError("%s needs at least 2 points" % where)
    return pts


def _poly_sub(pts, closed) -> dict:
    segs = [("L", pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    if closed and pts[-1] != pts[0]:
        segs.append(("L", pts[-1], pts[0]))
    return {"start": pts[0], "segs": segs, "closed": closed}


def _ellipse_sub(cx, cy, rx, ry) -> dict:
    k = 0.5522847498307936
    corners = [(cx + rx, cy), (cx, cy + ry), (cx - rx, cy), (cx, cy - ry)]
    ctrl = [(cx + rx, cy + ry * k), (cx + rx * k, cy + ry),
            (cx - rx * k, cy + ry), (cx - rx, cy + ry * k),
            (cx - rx, cy - ry * k), (cx - rx * k, cy - ry),
            (cx + rx * k, cy - ry), (cx + rx, cy - ry * k)]
    segs = []
    current = corners[0]
    for i in range(4):
        end = corners[(i + 1) % 4]
        segs.append(("C", current, ctrl[2 * i], ctrl[2 * i + 1], end))
        current = end
    return {"start": corners[0], "segs": segs, "closed": True}


def _fnum(element, attr, default=0.0) -> float:
    value = element.get(attr)
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(value)
    except ValueError:
        parsed = parse_length(value)
        if parsed is None:
            raise UserError("cannot read <%s %s=%r> as a number"
                            % (_local(element.tag), attr, value))
        return parsed


def _walk_svg(el, parent_mat, subs, skipped):
    tag = _local(el.tag)
    if tag in NON_RENDERING:
        return
    if tag in SKIPPED_GEOMETRY:
        skipped.append(tag)
        return
    mat = mat_mul(parent_mat, parse_transform(el.get("transform")))
    produced = []
    if tag == "path":
        produced = parse_path(el.get("d", ""))
    elif tag in ("polygon", "polyline"):
        pts = _points_attr(el.get("points", ""), "<%s>" % tag)
        produced = [_poly_sub(pts, tag == "polygon")]
    elif tag == "rect":
        x, y = _fnum(el, "x"), _fnum(el, "y")
        w, h = _fnum(el, "width"), _fnum(el, "height")
        if w <= 0 or h <= 0:
            raise UserError("<rect> needs a positive width and height (got %g x %g)" % (w, h))
        if el.get("rx") or el.get("ry"):
            warn("<rect rx/ry> rounded corners are not supported; the radius was ignored")
        produced = [_poly_sub([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)]
    elif tag == "circle":
        r = _fnum(el, "r")
        if r <= 0:
            raise UserError("<circle> needs a positive r (got %g)" % r)
        produced = [_ellipse_sub(_fnum(el, "cx"), _fnum(el, "cy"), r, r)]
    elif tag == "ellipse":
        rx, ry = _fnum(el, "rx"), _fnum(el, "ry")
        if rx <= 0 or ry <= 0:
            raise UserError("<ellipse> needs positive rx and ry (got %g x %g)" % (rx, ry))
        produced = [_ellipse_sub(_fnum(el, "cx"), _fnum(el, "cy"), rx, ry)]
    elif tag == "line":
        x1, y1 = _fnum(el, "x1"), _fnum(el, "y1")
        x2, y2 = _fnum(el, "x2"), _fnum(el, "y2")
        produced = [{"start": (x1, y1), "segs": [("L", (x1, y1), (x2, y2))], "closed": False}]
    for sub in produced:
        if sub["segs"]:
            subs.append(xform_sub(sub, mat))
    for child in el:
        _walk_svg(child, mat, subs, skipped)


def _svg_frame(root, subs):
    view_box = root.get("viewBox")
    if view_box:
        nums = _numbers(view_box)
        if len(nums) != 4 or nums[2] <= 0 or nums[3] <= 0:
            raise UserError("invalid viewBox=%r; expected 'min-x min-y width height'" % view_box)
        return (nums[0], nums[1], nums[2], nums[3])
    width = parse_length(root.get("width"))
    height = parse_length(root.get("height"))
    if width and height and width > 0 and height > 0:
        return (0.0, 0.0, width, height)
    x0, y0, x1, y1 = sub_bbox(subs)
    warn("SVG has no usable viewBox/width/height: fitting the geometry bounding box "
         "(%.3f,%.3f .. %.3f,%.3f user units) onto the target size instead"
         % (x0, y0, x1, y1))
    return (x0, y0, max(x1 - x0, 1e-9), max(y1 - y0, 1e-9))


def load_svg(path) -> tuple:
    """Return (subpaths in user units, frame)."""
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        raise UserError("cannot parse SVG %s: %s" % (path, exc))
    except OSError as exc:
        raise UserError("cannot read SVG %s: %s" % (path, exc))
    subs = []
    skipped = []
    _walk_svg(root, IDENT, subs, skipped, )
    if skipped:
        warn("SVG element(s) %s carry geometry this script cannot convert and were skipped; "
             "convert text/shapes to paths first if you need them cut"
             % ", ".join(sorted(set(skipped))))
    if not subs:
        raise UserError("no usable shapes found in SVG %s. Supported elements: %s"
                        % (path, ", ".join(GEOMETRY_ELEMENTS)))
    return subs, _svg_frame(root, subs)


# ---------------------------------------------------------------------------
# Frame mapping and curve flattening
# ---------------------------------------------------------------------------
def frame_matrix(frame, target, in_origin, out_origin, fit, offset, label="input"):
    fx0, fy0, fw, fh = frame
    tw, th = target
    if fw <= 0 or fh <= 0:
        raise UserError("frame size must be positive (got width=%g height=%g)" % (fw, fh))
    if tw <= 0 or th <= 0:
        raise UserError("--target-size must be positive (got %g %g)" % (tw, th))
    if fit == "contain":
        scale = min(tw / fw, th / fh)
        sx = sy = scale
        pad_x = (tw - fw * scale) / 2.0
        pad_y = (th - fh * scale) / 2.0
    else:
        sx, sy = tw / fw, th / fh
        pad_x = pad_y = 0.0
        if abs(sx - sy) / max(sx, sy) > 0.02:
            warn("target size %gx%g mm does not match the %s frame aspect %gx%g: X and Y are "
                 "scaled differently, so circles become ellipses. Use --fit contain to keep the "
                 "shape, or make the target match the frame." % (tw, th, label, fw, fh))
    flip = (in_origin == "top-left" and out_origin == "bottom-left")
    a = sx
    e = -fx0 * sx + pad_x + offset[0]
    if flip:
        d = -sy
        f = th - pad_y + fy0 * sy + offset[1]
    else:
        d = sy
        f = -fy0 * sy + pad_y + offset[1]
    return (a, 0.0, 0.0, d, e, f)


class PointSink:
    """Collects flattened points, dropping duplicates and enforcing a budget."""

    def __init__(self, limit):
        self.pts = []
        self.limit = limit

    def add(self, p):
        if self.pts:
            last = self.pts[-1]
            if abs(p[0] - last[0]) < 1e-9 and abs(p[1] - last[1]) < 1e-9:
                return
        if len(self.pts) >= self.limit:
            raise UserError("flattened geometry exceeds %d points; increase --flatten-tol or "
                            "simplify the artwork" % self.limit)
        self.pts.append(p)


def _mid(a, b):
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def _point_line_distance(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return abs(dy * (p[0] - a[0]) - dx * (p[1] - a[1])) / length


def _flatten_cubic(p0, p1, p2, p3, tol, depth, sink):
    if depth >= 18 or max(_point_line_distance(p1, p0, p3),
                          _point_line_distance(p2, p0, p3)) <= tol:
        sink.add(p3)
        return
    p01 = _mid(p0, p1); p12 = _mid(p1, p2); p23 = _mid(p2, p3)
    p012 = _mid(p01, p12); p123 = _mid(p12, p23); p0123 = _mid(p012, p123)
    _flatten_cubic(p0, p01, p012, p0123, tol, depth + 1, sink)
    _flatten_cubic(p0123, p123, p23, p3, tol, depth + 1, sink)


def flatten_sub(sub, tol, limit) -> tuple:
    """Return (points, closed). Duplicate points are dropped, so the closing point is implied."""
    sink = PointSink(limit)
    sink.add(sub["start"])
    for seg in sub["segs"]:
        if seg[0] == "L":
            sink.add(seg[2])
        else:
            _flatten_cubic(seg[1], seg[2], seg[3], seg[4], tol, 0, sink)
    pts = sink.pts
    closed = sub["closed"]
    if closed and len(pts) > 2:
        first, last = pts[0], pts[-1]
        if abs(first[0] - last[0]) < 1e-9 and abs(first[1] - last[1]) < 1e-9:
            pts = pts[:-1]
    return pts, closed


# ---------------------------------------------------------------------------
# G-code emission
# ---------------------------------------------------------------------------
class GCodeBuilder:
    """Emits the toolpath body and enforces 'never rapid with the laser on'."""

    def __init__(self, laser_cmd="M3"):
        self.lines = []
        self.laser_cmd = laser_cmd
        self.on = False
        self.pos = None
        self.burn = 0.0
        self.travel = 0.0
        self.bbox = None

    def _touch(self, x, y):
        if self.bbox is None:
            self.bbox = [x, y, x, y]
        else:
            self.bbox[0] = min(self.bbox[0], x)
            self.bbox[1] = min(self.bbox[1], y)
            self.bbox[2] = max(self.bbox[2], x)
            self.bbox[3] = max(self.bbox[3], y)

    def comment(self, text):
        self.lines.append("; " + text)

    def raw(self, line):
        self.lines.append(line)

    def feed(self, feed):
        self.lines.append("G1 F%g" % feed)

    def laser_on(self, s):
        self.lines.append("%s S%d" % (self.laser_cmd, s))
        self.on = True

    def laser_off(self):
        if self.on:
            self.lines.append("M5")
            self.on = False

    def rapid(self, x, y, track=True):
        if self.on:
            raise AssertionError("internal error: rapid move with the laser on")
        if self.pos is not None:
            self.travel += math.hypot(x - self.pos[0], y - self.pos[1])
        self.lines.append("G0 X%.3f Y%.3f" % (x, y))
        self.pos = (x, y)
        if track:
            self._touch(x, y)

    def cut(self, x, y):
        if not self.on:
            raise AssertionError("internal error: cutting move with the laser off")
        self.burn += math.hypot(x - self.pos[0], y - self.pos[1])
        self.lines.append("G1 X%.3f Y%.3f" % (x, y))
        self.pos = (x, y)
        self._touch(x, y)

    def text(self):
        return "\n".join(self.lines) + "\n"


def gen_outline(g, pts, closed, s, feed, passes, label):
    if len(pts) < 2:
        warn("%s has fewer than 2 distinct points after flattening and was skipped" % label)
        return 0
    for _ in range(passes):
        g.rapid(pts[0][0], pts[0][1])
        g.laser_on(s)
        g.feed(feed)
        for point in pts[1:]:
            g.cut(point[0], point[1])
        if closed and pts[-1] != pts[0]:
            g.cut(pts[0][0], pts[0][1])
        g.laser_off()
    return passes


def _rotate(p, a):
    cos_a, sin_a = math.cos(a), math.sin(a)
    return (p[0] * cos_a - p[1] * sin_a, p[0] * sin_a + p[1] * cos_a)


def _unrotate(p, a):
    cos_a, sin_a = math.cos(a), math.sin(a)
    return (p[0] * cos_a + p[1] * sin_a, -p[0] * sin_a + p[1] * cos_a)


def _scanline_xs(poly, y) -> list:
    xs = []
    count = len(poly)
    for i in range(count):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % count]
        if (y1 <= y < y2) or (y2 <= y < y1):
            t = (y - y1) / (y2 - y1)
            xs.append(x1 + t * (x2 - x1))
    return xs


def plan_fill(polys, spacing, angle, max_rows) -> list:
    """Return rows as [(y, [(xa, xb), ...]), ...] in the hatch's rotated frame.

    Intersections from every polygon are merged and paired evenly-odd, so holes and
    multiple islands both hatch correctly.
    """
    if spacing <= 0:
        raise UserError("--hatch-spacing must be greater than 0 (got %g); a zero or negative "
                        "spacing would never terminate" % spacing)
    if max_rows < 1:
        raise UserError("--max-scanlines must be at least 1")
    a = math.radians(angle)
    rotated = [[_rotate(p, a) for p in poly] for poly in polys]
    ys = [p[1] for poly in rotated for p in poly]
    if not ys:
        raise UserError("fill needs closed geometry")
    y0, y1 = min(ys), max(ys)
    needed = int(math.floor((y1 - y0) / spacing)) + 1
    if needed > max_rows:
        raise UserError("hatch spacing %g mm over %g mm of height needs %d scan lines, over the "
                        "--max-scanlines limit of %d; increase the spacing"
                        % (spacing, y1 - y0, needed, max_rows))
    rows = []
    y = y0
    index = 0
    while y <= y1 + 1e-9:
        xs = []
        for poly in rotated:
            xs.extend(_scanline_xs(poly, y))
        xs.sort()
        spans = []
        for i in range(0, len(xs) - 1, 2):
            xa, xb = xs[i], xs[i + 1]
            if abs(xb - xa) < 1e-4:
                continue
            spans.append((xa, xb))
        if index % 2 == 1:                # boustrophedon: snake back the other way
            spans = [(xb, xa) for xa, xb in reversed(spans)]
        rows.append((y, spans))
        y += spacing
        index += 1
    return rows


def gen_fill(g, rows, s, feed, passes, spacing, angle) -> int:
    """Emit the hatch. Every burn span gets its own laser-off rapid, so gaps are never burned."""
    a = math.radians(angle)
    total = sum(len(spans) for _, spans in rows)
    if total == 0:
        warn("hatch fill produced no spans: the geometry may be degenerate")
        return 0
    g.feed(feed)
    for _ in range(passes):
        for y, spans in rows:
            for xa, xb in spans:
                p0 = _unrotate((xa, y), a)
                p1 = _unrotate((xb, y), a)
                g.laser_off()
                g.rapid(p0[0], p0[1])
                g.laser_on(s)
                g.cut(p1[0], p1[1])
    g.laser_off()
    return total


# ---------------------------------------------------------------------------
# Reporting and checks
# ---------------------------------------------------------------------------
def fmt_bbox(bbox) -> str:
    if bbox is None:
        return "n/a"
    return "X%.3f..%.3f Y%.3f..%.3f (%.2f x %.2f mm)" % (
        bbox[0], bbox[2], bbox[1], bbox[3], bbox[2] - bbox[0], bbox[3] - bbox[1])


def check_bounds(g, target, offset, bed):
    if g.bbox is None:
        return
    ox, oy = offset
    tw, th = target
    x0, y0, x1, y1 = g.bbox
    tol = 0.01
    if x0 < ox - tol or y0 < oy - tol or x1 > ox + tw + tol or y1 > oy + th + tol:
        warn("toolpath leaves the target rectangle: bbox %s vs target %.3fx%.3f mm at offset "
             "(%g, %g). Check the input frame (--frame/--normalize, SVG viewBox)."
             % (fmt_bbox(g.bbox), tw, th, ox, oy))
    if x0 < -tol or y0 < -tol:
        warn("toolpath reaches negative machine coordinates (X%.3f Y%.3f); the part may sit "
             "outside the work area" % (x0, y0))
    if bed:
        if x1 > bed[0] + tol or y1 > bed[1] + tol:
            warn("toolpath exceeds the declared bed %.3fx%.3f mm (bbox %s)"
                 % (bed[0], bed[1], fmt_bbox(g.bbox)))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    ap = argparse.ArgumentParser(
        description="Generate GRBL laser G-code from vertices or SVG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n"
               "  python3 scripts/generate_gcode.py --svg logo.svg --job cut \\\n"
               "    --material plywood_3mm --laser-w 10 --target-size 80 80 -o logo.gcode\n")
    ap.add_argument("--config", help="JSON config file (its keys override the flags)")
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
    ap.add_argument("--fill-outline", choices=["none", "before", "after"], default="none",
                    help="also trace each outline around a fill (default none)")
    ap.add_argument("--offset", nargs=2, type=float, default=[0.0, 0.0], metavar=("X", "Y"))
    ap.add_argument("--frame", nargs=4, type=float, metavar=("X0", "Y0", "W", "H"),
                    help="declared input frame in source units (default 0 0 100 100)")
    ap.add_argument("--normalize", choices=["none", "auto"], default="none",
                    help="auto fits the geometry bounding box onto the frame")
    ap.add_argument("--fit", choices=["stretch", "contain"], default="stretch",
                    help="stretch fills the target box (default); contain keeps the aspect")
    ap.add_argument("--close", choices=["auto", "yes", "no"], default="auto",
                    help="auto keeps the source's open/closed state (default)")
    ap.add_argument("--flatten-tol", type=float, default=0.02,
                    help="curve chord tolerance in mm (default 0.02)")
    ap.add_argument("--max-points", type=int, default=200000, help="flattening safety limit")
    ap.add_argument("--max-scanlines", type=int, default=100000, help="fill safety limit")
    ap.add_argument("--laser-mode", choices=["m3", "m4"], default="m3",
                    help="m3 constant power (default) or m4 GRBL dynamic power")
    ap.add_argument("--rapid-rate", type=float, default=3000.0,
                    help="rapid feed mm/min, used only for the time estimate")
    ap.add_argument("--bed", nargs=2, type=float, metavar=("W_MM", "H_MM"),
                    help="machine bed size, checked against the toolpath")
    ap.add_argument("--park", action=argparse.BooleanOptionalAction, default=True,
                    help="park at the work origin when finished (default --park)")
    ap.add_argument("--check", action="store_true",
                    help="report parameters and geometry only, do not emit G-code")
    ap.add_argument("--list-materials", action="store_true",
                    help="print the material table and exit")
    ap.add_argument("--output", "-o", help="output .gcode path (default: stdout)")
    return ap


def run(args) -> int:
    cfg = {}
    if args.config:
        try:
            cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UserError("cannot read --config %s: %s" % (args.config, exc))

    def get(key, default):
        if key in cfg:
            return cfg[key]
        value = getattr(args, key.replace("-", "_"), None)
        return default if value is None else value

    materials = load_materials(cfg.get("materials_file"))

    if get("list_materials", False):
        print(list_materials(materials))
        return 0

    job = get("job", "cut")
    material = get("material", "plywood_3mm")
    laser_w = float(get("laser_w", 10.0))
    grbl_max_s = int(get("grbl_max_s", 1000))
    target = [float(v) for v in get("target_size", [100.0, 100.0])]
    in_origin = get("input_origin", "top-left")
    out_origin = get("output_origin", "bottom-left")
    fit = get("fit", "stretch")
    normalize = get("normalize", "none")
    close_mode = get("close", "auto")
    laser_mode = get("laser_mode", "m3")
    flatten_tol = float(get("flatten_tol", 0.02))
    max_points = int(get("max_points", 200000))
    max_scanlines = int(get("max_scanlines", 100000))
    spacing = float(get("hatch_spacing", 0.2))
    angle = float(get("hatch_angle", 0.0))
    fill_outline = get("fill_outline", "none")
    offset = [float(v) for v in get("offset", [0.0, 0.0])]
    rapid_rate = float(get("rapid_rate", 3000.0))
    bed = get("bed", None)
    bed = [float(v) for v in bed] if bed else None
    frame_arg = get("frame", None)
    power_override = cfg.get("power", args.power)
    feed_override = cfg.get("feed", args.feed)
    passes_override = cfg.get("passes", args.passes)

    if flatten_tol <= 0:
        raise UserError("--flatten-tol must be greater than 0 (got %g)" % flatten_tol)
    if grbl_max_s <= 0:
        raise UserError("--grbl-max-s must be greater than 0 (got %d)" % grbl_max_s)
    if offset[0] < 0 or offset[1] < 0:
        raise UserError("--offset must not be negative; it translates the part from the work "
                        "origin (got %g, %g)" % (offset[0], offset[1]))

    tier_label, tier = pick_tier(materials, material, laser_w)
    param_key = job if job in tier else "engrave"   # a fill is a form of engraving by default
    params = tier[param_key]
    if job == "cut" and params.get("passes", 0) == 0:
        raise UserError("material '%s' does not support cutting (cut.passes=0). Use --job "
                        "engrave to mark it instead." % material)

    power = float(params["power"] if power_override is None else power_override)
    feed = float(params["feed"] if feed_override is None else feed_override)
    passes = int(params["passes"] if passes_override is None else passes_override)
    if passes < 1:
        raise UserError("the '%s' block of material '%s' for job '%s' provides %d passes; "
                        "raise it with --passes" % (param_key, material, job, passes))
    if feed <= 0:
        raise UserError("feed must be greater than 0 (got %g)" % feed)
    if not 0 <= power <= 100:
        raise UserError("power must be between 0 and 100 percent (got %g)" % power)
    s = compute_s(power, grbl_max_s)
    if s == 0:
        warn("computed S=0: the laser would stay off. Raise --power or check the $30 setting.")

    # ---- geometry -------------------------------------------------------
    vertices = cfg.get("vertices", args.vertices)
    svg = cfg.get("svg", args.svg)
    if vertices:
        subs = parse_vertices(vertices)
        pts = [sub["start"] for sub in subs]
        for sub in subs:
            for seg in sub["segs"]:
                pts.append(seg[2] if seg[0] == "L" else seg[4])
        if frame_arg:
            frame = tuple(float(v) for v in frame_arg)
            label = "--frame"
        elif normalize == "auto":
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            frame = (min(xs), min(ys), max(max(xs) - min(xs), 1e-9),
                     max(max(ys) - min(ys), 1e-9))
            label = "vertex bounding box"
        else:
            frame = (0.0, 0.0, 100.0, 100.0)
            label = "0-100 grid"
            outside = [p for p in pts if p[0] < -2 or p[0] > 102 or p[1] < -2 or p[1] > 102]
            if outside:
                warn("%d vertex/vertices fall outside the assumed 0-100 frame (e.g. %.3f, %.3f); "
                     "the part will be clipped or oversized. Use --normalize auto or --frame to "
                     "match your coordinates." % (len(outside), outside[0][0], outside[0][1]))
    elif svg:
        subs, frame = load_svg(svg)
        label = "SVG viewBox"
        if frame_arg:
            frame = tuple(float(v) for v in frame_arg)
            label = "--frame"
        elif normalize == "auto":
            x0, y0, x1, y1 = sub_bbox(subs)
            frame = (x0, y0, max(x1 - x0, 1e-9), max(y1 - y0, 1e-9))
            label = "SVG geometry bounding box"
    else:
        raise UserError("provide --vertices, --svg, or a --config with vertices/svg")

    gx0, gy0, gx1, gy1 = sub_bbox(subs)
    if (gx0 < frame[0] - 0.02 * frame[2] or gy0 < frame[1] - 0.02 * frame[3]
            or gx1 > frame[0] + 1.02 * frame[2] or gy1 > frame[1] + 1.02 * frame[3]):
        warn("geometry (%.3f,%.3f .. %.3f,%.3f) extends outside the %s frame "
             "(%.3f,%.3f %gx%g); part of it may be scaled or placed unexpectedly"
             % (gx0, gy0, gx1, gy1, label, frame[0], frame[1], frame[2], frame[3]))

    matrix = frame_matrix(frame, target, in_origin, out_origin, fit, offset, label)
    subs = [xform_sub(sub, matrix) for sub in subs]

    polys = []
    for sub in subs:
        flat_pts, closed = flatten_sub(sub, flatten_tol, max_points)
        if close_mode == "yes":
            closed = True
        elif close_mode == "no":
            closed = False
        if len(flat_pts) >= 2:
            polys.append((flat_pts, closed))
    if not polys:
        raise UserError("no drawable geometry after flattening; check the frame and target size")

    if job == "fill":
        if any(not closed for _, closed in polys):
            warn("fill was given open path(s); they are treated as closed for hatching. "
                 "Use --job engrave if you want the open path traced instead.")
        rows = plan_fill([list(pts) for pts, _ in polys], spacing, angle, max_scanlines)
        span_total = sum(len(spans) for _, spans in rows)
    else:
        open_paths = sum(1 for _, closed in polys if not closed)
        if open_paths and job == "cut":
            warn("%d open path(s) cannot cut a part out; use --job engrave for open artwork or "
                 "--close yes to force them closed" % open_paths)

    # ---- emit -----------------------------------------------------------
    g = GCodeBuilder("M4" if laser_mode == "m4" else "M3")
    if job == "fill":
        if fill_outline in ("before", "after"):
            outline_params = tier.get("engrave", params)
            outline_power = float(outline_params["power"] if power_override is None else power_override)
            outline_feed = float(outline_params["feed"] if feed_override is None else feed_override)
            outline_s = compute_s(outline_power, grbl_max_s)
        if fill_outline == "before":
            for idx, (pts, _) in enumerate(polys):
                g.comment("--- outline poly%d (S=%d, F=%g) ---" % (idx + 1, outline_s, outline_feed))
                gen_outline(g, pts, True, outline_s, outline_feed, 1, "outline poly%d" % (idx + 1))
        g.comment("--- hatch fill (S=%d, F=%g, spacing=%gmm, angle=%gdeg, spans=%d) ---"
                  % (s, feed, spacing, angle, span_total))
        gen_fill(g, rows, s, feed, passes, spacing, angle)
        if fill_outline == "after":
            for idx, (pts, _) in enumerate(polys):
                g.comment("--- outline poly%d (S=%d, F=%g) ---" % (idx + 1, outline_s, outline_feed))
                gen_outline(g, pts, True, outline_s, outline_feed, 1, "outline poly%d" % (idx + 1))
    else:
        for idx, (pts, closed) in enumerate(polys):
            g.comment("--- %s poly%d (S=%d, F=%g, passes=%d%s) ---"
                      % (job, idx + 1, s, feed, passes, "" if closed else ", open path"))
            gen_outline(g, pts, closed, s, feed, passes, "%s poly%d" % (job, idx + 1))
    g.laser_off()
    if get("park", True):
        # the park move is deliberate and must not pollute the toolpath bounding box
        g.rapid(offset[0], offset[1], track=False)
    g.raw("M2")

    check_bounds(g, target, offset, bed)

    burn_minutes = g.burn / feed
    if rapid_rate > 0:
        burn_minutes += g.travel / rapid_rate

    material_name = materials[material]["name"]
    comments = [
        "Job: %s | Material: %s | Laser: %gW (tier %sW)" % (job, material_name, laser_w, tier_label),
        "Power: %g%% -> S%d/%d | Feed: %g mm/min | Passes: %d" % (power, s, grbl_max_s, feed, passes),
        "Target: %gx%g mm | Origin(out): %s | Polygons: %d"
        % (target[0], target[1], out_origin, len(polys)),
        "BBox: %s | Burn: %.1f mm | Est: %.1f min" % (fmt_bbox(g.bbox), g.burn, burn_minutes),
    ]
    if laser_mode == "m4":
        comments.append("Laser mode M4 (dynamic power): GRBL must have $32=1")
    comments.append("WARNING: starting parameters - always test on scrap first.")
    prelude = ["; " + c for c in comments] + ["G21", "G90", "G17", "M5"]
    gcode = "\n".join(prelude) + "\n" + g.text()

    report = [
        "material      : %s (%s)" % (material, material_name),
        "laser         : %gW -> tier %sW, using the '%s' block" % (laser_w, tier_label, param_key),
        "power         : %g%% -> S%d of $30=%d (%.2f W optical at %gW rated)"
        % (power, s, grbl_max_s, power / 100.0 * laser_w, laser_w),
        "feed / passes : %g mm/min / %d" % (feed, passes),
        "job           : %s (%s)" % (job, "M4 dynamic power" if laser_mode == "m4" else "M3 constant"),
        "target size   : %g x %g mm, fit=%s" % (target[0], target[1], fit),
        "frame         : %.4f, %.4f  %g x %g (%s)" % (frame[0], frame[1], frame[2], frame[3], label),
        "paths         : %d (%d closed)" % (len(polys), sum(1 for _, c in polys if c)),
    ]
    if job == "fill":
        report.append("hatch         : %g mm at %g deg -> %d spans over %d rows"
                      % (spacing, angle, span_total, len(rows)))
    report += [
        "bbox          : %s" % fmt_bbox(g.bbox),
        "burn / travel : %.1f mm / %.1f mm" % (g.burn, g.travel),
        "estimated time: %.1f min (feed %.0f mm/min, rapid %.0f mm/min)"
        % (burn_minutes, feed, rapid_rate),
    ]

    summary = ("[summary] S=%d feed=%g passes=%d polys=%d spans=%d bbox=\"%s\" burn=%.1fmm "
               "est=%.1fmin" % (s, feed, passes, len(polys),
                                span_total if job == "fill" else 0,
                                fmt_bbox(g.bbox), g.burn, burn_minutes))

    if get("check", False):
        print("\n".join(report))
    else:
        output = cfg.get("output", args.output)
        if output:
            Path(output).write_text(gcode, encoding="utf-8")
            print("Wrote %s (%d bytes)" % (output, len(gcode)), file=sys.stderr)
        else:
            sys.stdout.write(gcode)

    for item in WARNINGS:
        print("[warn] " + item, file=sys.stderr)
    print(summary, file=sys.stderr)
    return 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return run(args)
    except UserError as exc:
        print("[error] %s" % exc, file=sys.stderr)
        for item in WARNINGS:
            print("[warn] " + item, file=sys.stderr)
        return EXIT_USER_ERROR
    except OSError as exc:
        print("[error] %s" % exc, file=sys.stderr)
        return EXIT_USER_ERROR
    except (ValueError, KeyError, TypeError, ET.ParseError, argparse.ArgumentError) as exc:
        # never dump a traceback on the user: report it as a clean failure instead
        print("[error] unexpected failure: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        print("[error] this looks like a bug in generate_gcode.py; please report the command "
              "line above together with this message", file=sys.stderr)
        return EXIT_USER_ERROR


if __name__ == "__main__":
    sys.exit(main())
