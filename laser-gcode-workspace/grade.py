#!/usr/bin/env python3
"""Grade each run against its eval assertions. Writes grading.json per run."""
import json, re
from pathlib import Path

BASE = Path("/Users/johnsmacbook/Desktop/xTool/laser-gcode-workspace/iteration-1")

def read_all(d):
    t = ""
    for f in sorted(d.glob("*.gcode")) + sorted(d.glob("*.txt")):
        t += f.read_text(encoding="utf-8", errors="ignore") + "\n"
    return t

def gcode(d):
    for f in sorted(d.glob("*.gcode")):
        return f.read_text(encoding="utf-8", errors="ignore")
    return ""

def first_g0_y(g):
    for line in g.splitlines():
        if line.startswith("G0") and "Y" in line:
            m = re.search(r"Y([-+0-9.]+)", line)
            if m: return float(m.group(1))
    return None

def ng1(g): return sum(1 for l in g.splitlines() if l.startswith("G1"))

def g1_span(g):
    xs = [float(x) for l in g.splitlines() if l.startswith("G1") for x in re.findall(r"X([-+0-9.]+)", l)]
    ys = [float(y) for l in g.splitlines() if l.startswith("G1") for y in re.findall(r"Y([-+0-9.]+)", l)]
    return ((max(xs)-min(xs)) if xs else 0, (max(ys)-min(ys)) if ys else 0)

def maxc(g):
    xs = [float(x) for x in re.findall(r"X([-+0-9.]+)", g)]
    ys = [float(y) for y in re.findall(r"Y([-+0-9.]+)", g)]
    return (max(xs) if xs else 0, max(ys) if ys else 0)

def chk(text, g, d, eid):
    R = []
    def add(name, ok, ev): R.append({"text": name, "passed": bool(ok), "evidence": ev})
    if eid == 1:
        add("生成了一个 .gcode 文件并保存到 outputs 目录", bool(list(d.glob("*.gcode"))), str([f.name for f in d.glob('*.gcode')]))
        add("G 代码包含 GRBL 初始化指令 G21 和 G90", "G21" in g and "G90" in g, "G21/G90")
        add("G 代码包含激光开启 M3 和关闭 M5 指令", "M3" in g and "M5" in g, "M3/M5")
        add("激光功率 S=1000", bool(re.search(r"S1000\b", g)), "S1000")
        add("进给速度 F=500", bool(re.search(r"F500\b", g)), "F500")
        add("切割遍数 passes=2", ("2遍" in text) or ("passes=2" in text.lower()) or ("2 pass" in text.lower()), "passes=2")
        mx, my = maxc(g); add("目标尺寸为 80mm", mx >= 70 and my >= 70, f"max X={mx:.1f} Y={my:.1f}")
        fy = first_g0_y(g); add("Y 轴已翻转：顶部尖角在 Y≈78", fy is not None and fy > 50, f"first G0 Y={fy}")
        add("G 代码沿全部 22 个顶点闭合", ng1(g) >= 20, f"G1 count={ng1(g)}")
        add("包含安全提示", any(k in text for k in ["测试","废料","通风","气泵","test","ventil"]), "safety kw")
    elif eid == 2:
        add("生成了一个 .gcode 文件并保存到 outputs 目录", bool(list(d.glob("*.gcode"))), "file")
        isfill = (ng1(g) > 100) or ("hatch" in text.lower()) or ("扫描" in text)
        add("作业类型为填充雕刻 fill（含 hatch 扫描线）", isfill, f"G1={ng1(g)} hatch={'hatch' in text.lower()}")
        add("使用了亚克力雕刻参数（非切割满功率）", not bool(re.search(r"S1000\b", g)), "no S1000")
        add("激光功率 S≈350", bool(re.search(r"S350\b", g)), "S350")
        add("进给速度 F≈4000", bool(re.search(r"F4000\b", g)), "F4000")
        mx, my = maxc(g); add("目标尺寸为 50mm 见方", 40 <= mx <= 60 and 40 <= my <= 60, f"max X={mx:.1f} Y={my:.1f}")
        add("说明了 hatch 间距含义/取值", any(k in text.lower() for k in ["间距","spacing","行距","0.2","0.15"]), "spacing")
        add("包含亚克力安全提示（通风/不能切透明亚克力）", any(k in text.lower() for k in ["通风","排气","透明","clear","ventil","exhaust","fumes","flammable","unattended"]), "acrylic safety")
    elif eid == 3:
        add("生成了一个 .gcode 文件并保存到 outputs 目录", bool(list(d.glob("*.gcode"))), "file")
        has24 = ("24" in text) and any(k in text for k in ["段","顶点","seg","边"])
        add("用约 24 段顶点近似圆", has24, f"G1={ng1(g)} '24'&seg:{has24}")
        add("使用了皮革切割参数", ("leather" in text.lower()) or ("皮革" in text), "leather")
        add("激光功率 S≈900", bool(re.search(r"S900\b", g)), "S900")
        add("进给速度 F≈800", bool(re.search(r"F800\b", g)), "F800")
        add("切割遍数 passes=1", ("1遍" in text) or ("passes=1" in text.lower()) or ("1 pass" in text.lower()), "passes=1")
        sx, sy = g1_span(g); add("最终圆直径约 40mm", 35 <= sx <= 45 and 35 <= sy <= 45, f"G1 span X={sx:.1f} Y={sy:.1f}")
        add("包含皮革安全提示（通风/测试变黑）", any(k in text for k in ["通风","排气","变黑","焦","ventil"]), "leather safety")
    return R

EVALS = {
    1: "eval-1-maple-leaf-cut",
    2: "eval-2-svg-fill-engrave",
    3: "eval-3-leather-params-and-gcode",
}

def main():
    for eid, dirname in EVALS.items():
        for run in ("with_skill", "without_skill"):
            d = BASE / dirname / run / "run-1" / "outputs"
            if not d.exists():
                print(f"skip {d}"); continue
            text = read_all(d); g = gcode(d)
            res = chk(text, g, d, eid)
            passed = sum(1 for r in res if r["passed"])
            out = {
                "eval_id": eid, "run": run,
                "summary": {"pass_rate": round(passed/len(res), 3),
                            "passed": passed, "failed": len(res) - passed, "total": len(res)},
                "expectations": res,
            }
            (d.parent / "grading.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{dirname}/{run}: {passed}/{len(res)}")

if __name__ == "__main__":
    main()
