#!/usr/bin/env python3
"""Deterministic regression harness for the laser-gcode skill.

Every eval in evals.json carries human-readable `expectations`; this runner maps each
expectation, in order, to an executable check so the two can never drift apart.

    python3 evals/run_evals.py                     # run everything against this skill
    python3 evals/run_evals.py --only 4,5 -v        # a subset, with evidence
    python3 evals/run_evals.py --baseline DIR       # same checks against an older copy

Exit code is non-zero when any expectation fails. Standard library only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
SCRIPT = "scripts/generate_gcode.py"


# ---------------------------------------------------------------------------
# G-code inspection
# ---------------------------------------------------------------------------
class Toolpath:
    """Parsed view of a G-code file: moves plus the laser state at each move."""

    def __init__(self, text):
        self.text = text
        self.moves = []          # (code, laser_on, x, y)
        self.arms = 0            # M3/M4 occurrences
        self.offs = 0            # M5 occurrences
        laser = False
        x = y = None
        for line in text.splitlines():
            body = line.split(";")[0].strip()
            if not body:
                continue
            if re.match(r"^M[34]\b", body):
                laser = True
                self.arms += 1
                continue
            if body.startswith("M5"):
                laser = False
                self.offs += 1
                continue
            match = re.match(r"^G([012])\b(.*)$", body)
            if not match:
                continue
            code = match.group(1)
            rest = match.group(2)
            if "X" not in rest and "Y" not in rest:
                continue
            nx = _axis(rest, "X", x)
            ny = _axis(rest, "Y", y)
            self.moves.append((code, laser, nx, ny))
            x, y = nx, ny

    @property
    def burns(self):
        return [m for m in self.moves if m[0] == "1" and m[1]]

    @property
    def laser_on_rapids(self):
        return [m for m in self.moves if m[0] == "0" and m[1]]

    @property
    def unarmed_burns(self):
        return [m for m in self.moves if m[0] == "1" and not m[1]]

    def burn_bbox(self):
        pts = [(m[2], m[3]) for m in self.burns]
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    def burn_span_count(self):
        """Number of contiguous burn segments (a new one starts after every M5/rapid)."""
        spans = 0
        previous_burn = False
        for code, laser, _x, _y in self.moves:
            burning = (code == "1" and laser)
            if burning and not previous_burn:
                spans += 1
            previous_burn = burning
        return spans

    def burn_rows(self):
        """Distinct Y values used by burn moves (i.e. how many hatch rows exist)."""
        return len(set(round(m[3], 4) for m in self.burns))


def _axis(text, letter, default):
    match = re.search(letter + r"(-?[0-9.]+)", text)
    return float(match.group(1)) if match else default


# ---------------------------------------------------------------------------
# Run plumbing
# ---------------------------------------------------------------------------
class Run:
    def __init__(self, name, args, expect_exit, timeout, workdir):
        self.name = name
        self.args = args
        self.expect_exit = expect_exit
        self.output = Path(workdir) / ("%s.gcode" % name)
        self.timeout = timeout
        self.returncode = None
        self.stdout = ""
        self.stderr = ""
        self.seconds = 0.0
        self.timed_out = False

    def execute(self, python, script):
        started = time.time()
        try:
            proc = subprocess.run([python, str(script)] + self.args + ["-o", str(self.output)],
                                  capture_output=True, text=True, timeout=self.timeout)
            self.returncode = proc.returncode
            self.stdout = proc.stdout
            self.stderr = proc.stderr
        except subprocess.TimeoutExpired:
            self.timed_out = True
            self.returncode = None
        self.seconds = time.time() - started
        return self

    @property
    def gcode(self):
        if self.output.exists():
            return self.output.read_text(encoding="utf-8", errors="replace")
        return ""

    @property
    def toolpath(self):
        return Toolpath(self.gcode)

    def summary(self):
        match = re.search(r"^\[summary\] (.*)$", self.stderr, re.M)
        if not match:
            return {}
        out = {}
        for key, value in re.findall(r"(\w+)=(\"[^\"]*\"|\S+)", match.group(1)):
            out[key] = value.strip('"')
        return out

    def warnings(self):
        return [line[len("[warn] "):] for line in self.stderr.splitlines()
                if line.startswith("[warn] ")]

    def errors(self):
        return [line[len("[error] "):] for line in self.stderr.splitlines()
                if line.startswith("[error] ")]


def _fmt_bbox(bbox):
    """bbox is (xmin, ymin, xmax, ymax); print it as X..Y ranges."""
    if bbox is None:
        return "no burn moves"
    return "X%.3f..%.3f Y%.3f..%.3f" % (bbox[0], bbox[2], bbox[1], bbox[3])


def _within(bbox, bounds, tol=0.01):
    return (bbox is not None and bbox[0] >= bounds[0] - tol and bbox[1] >= bounds[1] - tol
            and bbox[2] <= bounds[2] + tol and bbox[3] <= bounds[3] + tol)


# ---------------------------------------------------------------------------
# The checks: one callable per expectation, in the same order as evals.json
# ---------------------------------------------------------------------------
def c_exit_ok(run):
    return run.returncode == 0 and not run.timed_out, "exit=%s timeout=%s" % (run.returncode, run.timed_out)


def c_file_written(run):
    return run.output.exists() and run.output.stat().st_size > 0, str(run.output)


def c_summary_has(run, **expected):
    summary = run.summary()
    bad = []
    for key, value in expected.items():
        if summary.get(key) != str(value):
            bad.append("%s=%r (want %r)" % (key, summary.get(key), value))
    return not bad, "; ".join(bad) or "summary=%s" % summary


def c_gcode_contains(run, *needles):
    missing = [n for n in needles if n not in run.gcode]
    return not missing, ("missing %s" % missing) if missing else "all present"


def c_gcode_lacks(run, *needles):
    found = [n for n in needles if n in run.gcode]
    return not found, ("found %s" % found) if found else "none present"


def c_stderr_contains(run, *needles):
    missing = [n for n in needles if n not in run.stderr]
    return not missing, ("missing %s; stderr=%r" % (missing, run.stderr.strip()[:160])) if missing else "ok"


def c_stderr_lacks(run, *needles):
    found = [n for n in needles if n in run.stderr]
    return not found, ("found %s" % found) if found else "none present"


def c_no_laser_on_rapid(run):
    bad = run.toolpath.laser_on_rapids
    return not bad, ("%d laser-on rapid(s), first at %s" % (len(bad), bad[0][2:])) if bad else "clean"


def c_burn_within(run, bounds):
    bbox = run.toolpath.burn_bbox()
    return _within(bbox, bounds), _fmt_bbox(bbox)


def c_burn_bbox_near(run, expected, tol=0.5):
    bbox = run.toolpath.burn_bbox()
    if bbox is None:
        return False, "no burn moves"
    deltas = [abs(a - b) for a, b in zip(bbox, expected)]
    return max(deltas) <= tol, "%s vs %s (max delta %.3f)" % (_fmt_bbox(bbox), expected, max(deltas))


def c_burn_moves(run, count=None, minimum=None, maximum=None):
    total = len(run.toolpath.burns)
    if total == 0:
        return False, "no burn moves"
    if count is not None and total != count:
        return False, "%d burn moves (want %d)" % (total, count)
    if minimum is not None and total < minimum:
        return False, "%d burn moves (want >= %d)" % (total, minimum)
    if maximum is not None and total > maximum:
        return False, "%d burn moves (want <= %d)" % (total, maximum)
    return True, "%d burn moves" % total


def c_span_segmentation(run):
    """Multi-span rows must each get their own laser arm, so arms > distinct rows."""
    tp = run.toolpath
    rows = tp.burn_rows()
    arms = tp.arms
    return arms > rows, "arms=%d rows=%d spans=%d" % (arms, rows, tp.burn_span_count())


def c_no_unarmed_burns(run):
    bad = run.toolpath.unarmed_burns
    return not bad, ("%d G1 with the laser off" % len(bad)) if bad else "every burn is armed"


def c_no_repeated_points(run):
    burns = run.toolpath.burns
    repeats = 0
    previous = None
    for _, _, x, y in burns:
        if previous is not None and abs(x - previous[0]) < 1e-6 and abs(y - previous[1]) < 1e-6:
            repeats += 1
        previous = (x, y)
    return repeats == 0, "%d zero-length burn move(s)" % repeats


def c_y_flipped(run, threshold):
    bbox = run.toolpath.burn_bbox()
    return bbox is not None and bbox[3] > threshold, _fmt_bbox(bbox)


def c_fast(run, seconds):
    return run.seconds < seconds, "%.2fs (limit %ss)" % (run.seconds, seconds)


def c_nonzero_exit(run):
    return run.returncode not in (0, None), "exit=%s" % run.returncode


def path_endpoints(run):
    """(start, end) of the first burn: start is where the approach rapid parked."""
    moves = run.toolpath.moves
    burns = run.toolpath.burns
    if not burns:
        return None, None
    first_index = next(i for i, m in enumerate(moves) if m[0] == "1" and m[1])
    if first_index == 0:
        start = (burns[0][2], burns[0][3])
    else:
        start = (moves[first_index - 1][2], moves[first_index - 1][3])
    return start, (burns[-1][2], burns[-1][3])


def c_closed_loop(run):
    start, end = path_endpoints(run)
    if start is None:
        return False, "no burn moves"
    gap = math.hypot(end[0] - start[0], end[1] - start[1])
    return gap < 0.01, "loop start %s end %s (gap %.3f)" % (start, end, gap)


def c_path_open(run):
    start, end = path_endpoints(run)
    if start is None:
        return False, "no burn moves"
    gap = math.hypot(end[0] - start[0], end[1] - start[1])
    return gap > 0.01, "start %s end %s (gap %.3f)" % (start, end, gap)


def c_no_negative(run):
    bad = [m for m in run.toolpath.moves if m[2] < -0.01 or m[3] < -0.01]
    return not bad, ("%d move(s) below zero, first %s" % (len(bad), bad[0][2:])) if bad else "all >= 0"


def c_min_y(run, minimum):
    bbox = run.toolpath.burn_bbox()
    return bbox is not None and bbox[1] >= minimum, _fmt_bbox(bbox)


def c_square_bbox(run, tol=0.1):
    bbox = run.toolpath.burn_bbox()
    if bbox is None:
        return False, "no burn moves"
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    return abs(w - h) <= tol, "w=%.3f h=%.3f" % (w, h)


def c_bbox_size(run, expected, tol=0.5):
    bbox = run.toolpath.burn_bbox()
    if bbox is None:
        return False, "no burn moves"
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    return abs(w - expected) <= tol and abs(h - expected) <= tol, "w=%.2f h=%.2f (want %.1f)" % (w, h, expected)


# ---------------------------------------------------------------------------
# Harness definition: eval id -> runs + one check per expectation
# ---------------------------------------------------------------------------
LEAF = ("50,2 57,18 71,16 62,35 98,43 78,62 93,68 65,75 68,85 53,80 53,98 47,98 47,80 "
        "32,85 35,75 7,68 22,62 2,43 38,35 29,16 43,18 50,2")
CIRCLE24 = " ".join("%.4f,%.4f" % (50 + 48 * math.cos(2 * math.pi * i / 24),
                                   50 + 48 * math.sin(2 * math.pi * i / 24)) for i in range(24))
SQUARE = "0,0 100,0 100,100 0,100"


def build_harness(skill_dir):
    asset = lambda name: str(Path(skill_dir) / "evals" / "assets" / name)
    return {
        1: {
            "runs": {"main": ["--vertices", LEAF, "--job", "cut", "--material", "plywood_3mm",
                              "--laser-w", "10", "--target-size", "80", "80"]},
            "checks": [
                lambda ctx: (c_exit_ok(ctx.main)[0] and c_file_written(ctx.main)[0],
                             "exit=%s file=%s" % (ctx.main.returncode, ctx.main.output.exists())),
                lambda ctx: c_summary_has(ctx.main, S=1000, feed=500, passes=2),
                lambda ctx: c_gcode_contains(ctx.main, "G21", "G90", "M3 S1000", "G1 F500", "M5", "M2"),
                lambda ctx: (c_y_flipped(ctx.main, 78.0)[0] and c_burn_within(ctx.main, (0, 0, 80, 80))[0],
                             "%s" % _fmt_bbox(ctx.main.toolpath.burn_bbox())),
                lambda ctx: c_no_laser_on_rapid(ctx.main),
                lambda ctx: c_no_repeated_points(ctx.main),
            ],
        },
        2: {
            "runs": {"main": ["--svg", asset("star_logo.svg"), "--job", "fill",
                              "--material", "acrylic_dark_3mm", "--laser-w", "20",
                              "--target-size", "50", "50"]},
            "checks": [
                lambda ctx: (c_exit_ok(ctx.main)[0] and c_summary_has(ctx.main, S=350)[0]
                             and c_gcode_contains(ctx.main, "; Job: fill")[0],
                             "exit=%s summary=%s" % (ctx.main.returncode, ctx.main.summary())),
                lambda ctx: (c_gcode_contains(ctx.main, "hatch fill")[0]
                             and int(ctx.main.summary().get("spans", 0)) > 100,
                             "spans=%s" % ctx.main.summary().get("spans")),
                lambda ctx: c_no_laser_on_rapid(ctx.main),
                lambda ctx: c_burn_within(ctx.main, (0, 0, 50, 50)),
            ],
        },
        3: {
            "runs": {"main": ["--vertices", CIRCLE24, "--job", "cut", "--material", "leather_2mm",
                              "--laser-w", "20", "--target-size", "40", "40"]},
            "checks": [
                lambda ctx: (c_exit_ok(ctx.main)[0] and "leather" in ctx.main.gcode.lower()
                             and "tier 20W" in ctx.main.gcode,
                             "exit=%s header=%r" % (ctx.main.returncode,
                                                    ctx.main.gcode.splitlines()[:1])),
                lambda ctx: c_summary_has(ctx.main, S=900, feed=800, passes=1),
                lambda ctx: (c_burn_within(ctx.main, (0, 0, 40, 40))[0] and c_closed_loop(ctx.main)[0],
                             "%s closed=%s" % (_fmt_bbox(ctx.main.toolpath.burn_bbox()),
                                               c_closed_loop(ctx.main)[1])),
                lambda ctx: c_no_laser_on_rapid(ctx.main),
            ],
        },
        4: {
            "runs": {"main": ["--svg", asset("viewbox_1000.svg"), "--job", "cut",
                              "--material", "plywood_3mm", "--laser-w", "10",
                              "--target-size", "50", "50"]},
            "checks": [
                lambda ctx: c_exit_ok(ctx.main),
                lambda ctx: c_burn_within(ctx.main, (0, 0, 50, 50)),
                lambda ctx: c_bbox_size(ctx.main, 50.0, tol=0.5),
                lambda ctx: c_stderr_lacks(ctx.main, "leaves the target rectangle"),
            ],
        },
        5: {
            "runs": {"main": ["--svg", asset("star_logo.svg"), "--job", "fill",
                              "--material", "paper", "--laser-w", "10",
                              "--target-size", "40", "40", "--hatch-spacing", "1"]},
            "checks": [
                lambda ctx: c_exit_ok(ctx.main),
                lambda ctx: c_no_laser_on_rapid(ctx.main),
                lambda ctx: c_no_unarmed_burns(ctx.main),
                lambda ctx: c_span_segmentation(ctx.main),
            ],
        },
        6: {
            "runs": {"main": ["--vertices", SQUARE, "--job", "fill", "--hatch-spacing", "0"]},
            "expect_nonzero": ["main"],
            "checks": [
                lambda ctx: c_nonzero_exit(ctx.main),
                lambda ctx: c_stderr_contains(ctx.main, "[error]", "hatch-spacing"),
                lambda ctx: c_fast(ctx.main, 2.0),
                lambda ctx: (not ctx.main.output.exists(), "output file exists" if ctx.main.output.exists()
                             else "no file written"),
            ],
        },
        7: {
            "runs": {"main": ["--vertices", "[[0,0],[10,10]]", "--job", "cut"]},
            "expect_nonzero": ["main"],
            "checks": [
                lambda ctx: c_nonzero_exit(ctx.main),
                lambda ctx: c_stderr_contains(ctx.main, "[error]", "at least 3 vertices"),
                lambda ctx: (not ctx.main.output.exists(), "output file exists" if ctx.main.output.exists()
                             else "no file written"),
            ],
        },
        8: {
            "runs": {"main": ["--svg", asset("arc_shape.svg"), "--job", "cut",
                              "--material", "plywood_3mm", "--laser-w", "10",
                              "--target-size", "100", "100"]},
            "checks": [
                lambda ctx: c_exit_ok(ctx.main),
                lambda ctx: (lambda b: (b is not None and b[2] > 88.0, _fmt_bbox(b)))(
                    ctx.main.toolpath.burn_bbox()),
                lambda ctx: c_burn_moves(ctx.main, minimum=8),
                lambda ctx: c_no_laser_on_rapid(ctx.main),
            ],
        },
        9: {
            "runs": {"main": ["--svg", asset("open_polyline.svg"), "--job", "engrave",
                              "--material", "paper", "--laser-w", "10", "--target-size", "100", "100"],
                     "close": ["--svg", asset("open_polyline.svg"), "--job", "engrave",
                               "--material", "paper", "--laser-w", "10", "--target-size", "100", "100",
                               "--close", "yes"],
                     "cut": ["--svg", asset("open_polyline.svg"), "--job", "cut",
                             "--material", "plywood_3mm", "--laser-w", "10", "--target-size", "100", "100"]},
            "checks": [
                lambda ctx: (c_burn_moves(ctx.main, count=2)[0] and c_path_open(ctx.main)[0],
                             "%s; %s" % (c_burn_moves(ctx.main, count=2)[1], c_path_open(ctx.main)[1])),
                lambda ctx: c_burn_moves(ctx.close, count=3),
                lambda ctx: c_stderr_contains(ctx.cut, "open path"),
            ],
        },
        10: {
            "runs": {"high": ["--vertices", SQUARE, "--job", "cut", "--material", "plywood_3mm",
                              "--laser-w", "60"],
                     "low": ["--vertices", SQUARE, "--job", "cut", "--material", "mdf_3mm",
                             "--laser-w", "5"]},
            "checks": [
                lambda ctx: c_stderr_contains(ctx.high, "[warn]", "above the highest tier"),
                lambda ctx: c_stderr_contains(ctx.low, "[warn]", "below the lowest tier"),
                lambda ctx: (c_exit_ok(ctx.high)[0] and c_exit_ok(ctx.low)[0]
                             and c_file_written(ctx.high)[0] and c_file_written(ctx.low)[0],
                             "high=%s low=%s" % (ctx.high.returncode, ctx.low.returncode)),
            ],
        },
        11: {
            "runs": {"stretch": ["--svg", asset("viewbox_1000.svg"), "--job", "cut",
                                 "--material", "plywood_3mm", "--laser-w", "10",
                                 "--target-size", "100", "50"],
                     "contain": ["--svg", asset("viewbox_1000.svg"), "--job", "cut",
                                 "--material", "plywood_3mm", "--laser-w", "10",
                                 "--target-size", "100", "50", "--fit", "contain"]},
            "checks": [
                lambda ctx: c_stderr_contains(ctx.stretch, "aspect"),
                lambda ctx: (c_stderr_lacks(ctx.contain, "aspect")[0] and c_square_bbox(ctx.contain)[0],
                             "%s; %s" % (c_stderr_lacks(ctx.contain, "aspect")[1],
                                         c_square_bbox(ctx.contain)[1])),
                lambda ctx: (c_exit_ok(ctx.stretch)[0] and c_exit_ok(ctx.contain)[0],
                             "stretch=%s contain=%s" % (ctx.stretch.returncode, ctx.contain.returncode)),
            ],
        },
        12: {
            "runs": {"main": ["--vertices", SQUARE, "--job", "engrave", "--material", "paper",
                              "--laser-w", "10", "--target-size", "100", "100",
                              "--offset", "0", "10"]},
            "checks": [
                lambda ctx: c_min_y(ctx.main, 9.9),
                lambda ctx: c_no_negative(ctx.main),
                lambda ctx: (c_exit_ok(ctx.main)[0]
                             and c_stderr_lacks(ctx.main, "negative machine coordinates")[0],
                             "exit=%s warns=%s" % (ctx.main.returncode, ctx.main.warnings())),
            ],
        },
        13: {
            "runs": {"main": ["--svg", asset("circle_transform.svg"), "--job", "cut",
                              "--material", "plywood_3mm", "--laser-w", "10",
                              "--target-size", "100", "100"]},
            "checks": [
                lambda ctx: c_exit_ok(ctx.main),
                lambda ctx: c_burn_bbox_near(ctx.main, (25.0, 35.0, 65.0, 75.0), tol=0.5),
                lambda ctx: c_burn_moves(ctx.main, minimum=16),
            ],
        },
    }


class Context:
    def __init__(self, runs):
        self._runs = runs

    def __getattr__(self, name):
        try:
            return self._runs[name]
        except KeyError:
            raise AttributeError(name)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def load_evals(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["evals"]


def run_suite(skill_dir, only=None, verbose=False, python=sys.executable, timeout=60):
    evals = load_evals(Path(skill_dir) / "evals" / "evals.json")
    harness = build_harness(skill_dir)
    script = Path(skill_dir) / SCRIPT
    if not script.exists():
        raise SystemExit("[error] %s not found" % script)

    results = []
    for spec in evals:
        eid = spec["id"]
        if only and eid not in only:
            continue
        if eid not in harness:
            raise SystemExit("[error] eval %d has no harness entry" % eid)
        expectations = spec.get("expectations", [])
        checks = harness[eid]["checks"]
        if len(expectations) != len(checks):
            raise SystemExit("[error] eval %d: %d expectations vs %d checks"
                             % (eid, len(expectations), len(checks)))

        workdir = tempfile.mkdtemp(prefix="laser-gcode-eval%d-" % eid)
        expect_nonzero = set(harness[eid].get("expect_nonzero", []))
        runs = {}
        try:
            for name, args in harness[eid]["runs"].items():
                run = Run(name, list(args), 0 if name not in expect_nonzero else None,
                          timeout, workdir)
                runs[name] = run.execute(python, script)
            ctx = Context(runs)
            outcomes = []
            for index, (statement, check) in enumerate(zip(expectations, checks)):
                try:
                    passed, evidence = check(ctx)
                except Exception as exc:                       # a broken check is a failure
                    passed, evidence = False, "check raised %s: %s" % (type(exc).__name__, exc)
                outcomes.append({"text": statement, "passed": bool(passed), "evidence": evidence})
            results.append({"eval_id": eid, "eval_name": spec.get("name", str(eid)),
                            "outcomes": outcomes})
            if verbose:
                print("\n[eval %d] %s" % (eid, spec.get("name")))
                for outcome in outcomes:
                    print("   %s %s\n        %s" % ("PASS" if outcome["passed"] else "FAIL",
                                                    outcome["text"], outcome["evidence"]))
                for name, run in runs.items():
                    if run.stderr.strip():
                        print("   [%s stderr] %s" % (name, run.stderr.strip().replace("\n", " | ")[:400]))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    return results


def summarize(results):
    total = passed = 0
    for entry in results:
        for outcome in entry["outcomes"]:
            total += 1
            passed += 1 if outcome["passed"] else 0
    return passed, total


def print_table(results):
    for entry in results:
        ok = sum(1 for o in entry["outcomes"] if o["passed"])
        total = len(entry["outcomes"])
        flag = "ok  " if ok == total else "FAIL"
        print("%s eval %-2d %-34s %d/%d" % (flag, entry["eval_id"], entry["eval_name"], ok, total))
        for outcome in entry["outcomes"]:
            if not outcome["passed"]:
                print("        x %s\n          %s" % (outcome["text"], outcome["evidence"]))


def write_report(results, path):
    passed, total = summarize(results)
    report = {"skill_dir": str(SKILL_DIR), "passed": passed, "total": total,
              "pass_rate": round(passed / total, 4) if total else 0.0, "results": results}
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser(description="Run the laser-gcode regression evals")
    ap.add_argument("--skill-dir", default=str(SKILL_DIR))
    ap.add_argument("--only", help="comma separated eval ids")
    ap.add_argument("--baseline", help="also run the same checks against another skill copy")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--report", help="write a JSON report to this path")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    only = {int(v) for v in args.only.split(",")} if args.only else None
    print("== %s ==" % args.skill_dir)
    results = run_suite(args.skill_dir, only=only, verbose=args.verbose, timeout=args.timeout)
    print_table(results)
    passed, total = summarize(results)
    print("\nTOTAL %d/%d expectations passed (%.0f%%)"
          % (passed, total, 100.0 * passed / total if total else 0.0))

    if args.report:
        write_report(results, args.report)
        print("report written to %s" % args.report)

    if args.baseline:
        print("\n== baseline: %s ==" % args.baseline)
        base_results = run_suite(args.baseline, only=only, verbose=False, timeout=args.timeout)
        print_table(base_results)
        base_passed, base_total = summarize(base_results)
        print("\nBASELINE %d/%d expectations passed" % (base_passed, base_total))
        print("\n== per-eval delta (new - baseline) ==")
        base_by_id = {e["eval_id"]: e for e in base_results}
        for entry in results:
            other = base_by_id.get(entry["eval_id"])
            if not other:
                continue
            new_ok = sum(1 for o in entry["outcomes"] if o["passed"])
            old_ok = sum(1 for o in other["outcomes"] if o["passed"])
            print("  eval %-2d %-34s baseline %d/%d -> new %d/%d %s"
                  % (entry["eval_id"], entry["eval_name"], old_ok, len(other["outcomes"]),
                     new_ok, len(entry["outcomes"]),
                     "" if new_ok >= old_ok else "<-- REGRESSION"))

    return 1 if passed < total else 0


if __name__ == "__main__":
    sys.exit(main())
