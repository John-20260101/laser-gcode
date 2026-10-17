# 50mm 正方形切割 G 代码（10W 二极管 / 3mm 椴木）

## 1. 文件

**`/Users/johnsmacbook/Desktop/Program/deepseek/laser-gcode-workspace/ab/out/p3-new/square_50mm_plywood3_cut.gcode`**（654 字节）

```gcode
; Job: cut | Material: Plywood / Basswood 3mm | Laser: 10W (tier 10W)
; Power: 100% -> S1000/1000 | Feed: 500 mm/min | Passes: 2
; Target: 50x50 mm | Origin(out): bottom-left | Polygons: 1
; BBox: X25.000..75.000 Y25.000..75.000 (50.00 x 50.00 mm) | Burn: 400.0 mm | Est: 0.8 min
; WARNING: starting parameters - always test on scrap first.
G21
G90
G17
M5
; --- cut poly1 (S=1000, F=500, passes=2) ---
G0 X25.000 Y75.000
M3 S1000
G1 F500
G1 X75.000 Y75.000
G1 X75.000 Y25.000
G1 X25.000 Y25.000
G1 X25.000 Y75.000
M5
G0 X25.000 Y75.000
M3 S1000
G1 F500
G1 X75.000 Y75.000
G1 X75.000 Y25.000
G1 X25.000 Y25.000
G1 X25.000 Y75.000
M5
G0 X25.000 Y25.000
M2
```

因为我先拿 `--check` 跑了一遍参数体检（报告见下），所以这次生成**一条告警都没有**——尺寸、床身、宽高比都在范围内。

## 2. 参数摘要

| 项目 | 值 | 说明 |
|---|---|---|
| 材料 | `plywood_3mm`（Plywood / Basswood 3mm） | 3mm 椴木/胶合板 |
| 激光器额定功率 | 10W | 命中材料库的 **10W 档** |
| 选用档位 | tier 10W → `cut` 块 | 10W 档切 3mm 椴木：满功率、500mm/min、**2 遍** |
| `S` 值 | **`S1000`**（= 100% 占空比） | `$30=1000` 时 S1000 就是满功率；换算成真实光功率 = 1000/1000 × 10W = **10W** |
| 进给速度 | **`F500`**（500 mm/min） | 3mm 椴木用 10W 切穿的速度区间下限，慢才能切透 |
| 遍数 | **2 遍** | 单管 10W 一遍通常切不透 3mm 椴木，第二遍补透 |
| 作业类型 | `cut` 切穿（`M3` 恒定功率） | |
| 目标尺寸 | 50 × 50 mm | `--target-size 50 50` |
| 源坐标系（frame） | `0,0 1000×1000`，来自 SVG 的 `viewBox="0 0 1000 1000"` | 所以 1000 用户单位 → 50mm，即 1 单位 = 0.05mm |
| 实际包围盒 | **X25.000..75.000，Y25.000..75.000（50.00 × 50.00 mm）** | 已用 `--offset 25 25` 把它**居中**放在 100×100 床身里 |
| 燃烧路径 / 空移 | 400.0 mm / 50.0 mm | |
| 预计耗时 | **约 0.8 分钟**（≈48 秒，不含对焦与上下料） | 按 F500 + 空移 3000mm/min 估算 |
| 输出原点 | 左下、Y 向上（标准 CNC） | 图形坐标原点按左上（图像习惯）处理，所以顶边在 `Y=75` |

**命令（可复现）：**

```bash
python3 scripts/generate_gcode.py \
  --svg /Users/johnsmacbook/Desktop/Program/deepseek/laser-gcode-workspace/ab/shared-assets/viewbox_1000.svg \
  --job cut --material plywood_3mm --laser-w 10 \
  --target-size 50 50 --bed 100 100 --offset 25 25 \
  --output .../out/p3-new/square_50mm_plywood3_cut.gcode
```

体检报告原文：

```
[summary] S=1000 feed=500 passes=2 polys=1 spans=0 bbox="X0.000..50.000 Y0.000..50.000 (50.00 x 50.00 mm)" burn=400.0mm est=0.8min
material      : plywood_3mm (Plywood / Basswood 3mm)
laser         : 10W -> tier 10W, using the 'cut' block
power         : 100% -> S1000 of $30=1000 (10.00 W optical at 10W rated)
feed / passes : 500 mm/min / 2
job           : cut (M3 constant)
target size   : 50 x 50 mm, fit=stretch
frame         : 0.0000, 0.0000  1000 x 1000 (SVG viewBox)
paths         : 1 (1 closed)
bbox          : X0.000..50.000 Y0.000..50.000 (50.00 x 50.00 mm)
burn / travel : 400.0 mm / 50.0 mm
estimated time: 0.8 min (feed 500 mm/min, rapid 3000 mm/min)
```

## 3. 图形为什么是 50mm——你那个 1000 的关键点

你的 SVG 里同时写了两个数字：

```xml
<svg width="100" height="100" viewBox="0 0 1000 1000">
  <rect x="0" y="0" width="1000" height="1000" .../>
```

- `viewBox="0 0 1000 1000"` 定义的是**用户坐标空间**，里面那个 `<rect>` 从 (0,0) 画到 (1000,1000)，也就是铺满整个画布。
- `width/height` 是「这个 viewBox 渲染出来有多宽」，单位按 1 单位 = 1px = 1/96 英寸算，所以它约等于 26.46mm × 26.46mm——**这是 Illustrator 的画板物理尺寸，跟切割尺寸无关**。
- 生成器按 SVG 标准优先级取 **viewBox 作为源坐标系**，于是 `1000 × 1000` 单位被等比映射到你的目标 50mm：**1 用户单位 = 0.05mm**，正方形正好 50 × 50 mm。

这正是**必须**让它吃 viewBox 的原因：如果误用 `width/height`（100×100 当框架），同样的 50mm 目标会算出 **500 × 500 mm** 的刀路——直接把 100mm 的床身跑穿、撞限位。所以拿到 Illustrator 导出的 SVG 时，检查 viewBox 是第一件事。

另外，`.svg` 文件里那句注释 `otherwise a 50mm target turns into 500mm of travel` 说的就是这件事，我这边已经按 viewBox 处理，不存在这个问题。

## 4. 安全提示（3mm 椴木，请务必看完）

1. **人不能离开机器。** 木材/胶合板是明火级别风险，火焰常从工件**背面**先起，正面看不出来。旁边常备灭火器或湿毛巾，手能立刻断电。
2. **垫板别用木板/纸板**，用蜂窝板或金属垫板——垫板自己会被点着。
3. **必须排烟**：椴木/胶合板的胶层烟大，要排到**室外**，不是「开个窗」。
4. **护目镜 + 外罩**，不要直视光斑（含工件反射的散射光）；普通墨镜不防 445nm 蓝光，反而更危险。
5. **切割必开气泵**：能显著减少焦边和明火；不吹气会黑边、复燃概率更高。
6. **换材料/换镜头/换高度都要重新对焦**——焦距偏差是「参数不准」的头号原因。
7. **工件必须夹紧**：50mm 小方片尤其容易在切透瞬间移动，移位会撞喷嘴、反光。
8. 加工完**再盯 1–2 分钟**，碳化边缘可能延迟冒烟复燃。

## 5. 上机前必做：测试网格 + 机床检查

**这份参数是起点，不是终点。** 同批废料先切一组 5×5 的小方片矩阵（比如 10mm 方片，间距 5mm）：

- 功率列：`S900 / S950 / S1000`
- 速度行：`F300 / F400 / F500 / F600 / F700`
- 遍数：1 遍 / 2 遍各标几片

挑出「背面能看到完整切缝、边缘微黄不发黑、指甲推得动」的那一档。如果 2 遍 `S1000 F500` 还切不透，按这个顺序调：
① 重新对焦 → ② 确认气泵风量 → ③降到 `F400` → ④再加到 3 遍（3 遍比提速更容易切透，但碳化更重）。

**上机前用 `$$` 确认两项：**

- `$32=1`（激光模式，**必须**；否则 S 值不会调制激光，会一直满功率或不出光）
- `$30=1000`（S 的上限，本文件按 `$30=1000` 生成；若你的机器是 `$30=255`，需要重新生成，不能直接跑）

本文件用 `M3`（恒定功率）而不是 `M4` 动态功率，所以**不依赖 `$32=1` 也能跑**；如果你已经开了 `$32=1` 并希望拐角不过烧，可以改用 `--laser-mode m4` 重新生成。

## 6. 其他可能想改的地方

| 想要的效果 | 怎么改 |
|---|---|
| 不居中，从工件原点(0,0)起切 | 去掉 `--offset 25 25` |
| 想留 5mm 边距 | `--offset 5 5` |
| 正方形被拉成长方形（一般不会） | 加 `--fit contain` 保持宽高比 |
| 一次切不穿想更激进 | `--passes 3` 或 `--feed 400`（先试后者） |
| 机器 $30 不是 1000 | 加 `--grbl-max-s <你的值>` 重新生成 |
| 顺便在方片上刻字/刻线 | 用 `--job engrave`（10W 档：`S400 F5000`，1 遍） |

需要我按你的实际 `$30`/`$32` 或调整居中位置重新出一版，把 `$$` 的输出发我就行。
