# 故障排查

按“现象 → 原因 → 处置”查。左侧现象是用户的原话，处置是需要执行的动作。

## 机器/程序侧

| 现象 | 可能原因 | 处置 |
|---|---|---|
| 激光完全不出光，机床在跑 | GRBL 未开激光模式 | `$$` 检查 `$32`，发 `$32=1` 后重试 |
| 出光但很弱、调 S 没用 | `$30` 与生成时不一致 | 用实际 `$30` 重新生成：`--grbl-max-s <值>` |
| 一点火就满功率 | 把 `M3 S…` 当成了主轴指令、或用错固件模式 | 确认固件为 GRBL、`$32=1`；必要时试 `--laser-mode m4` |
| 走 G0 时也在烧 | 后处理把 M5 删了，或用了不支持 `S0` 的固件 | 直接用本脚本输出，不要二次手工编辑 |
| 报 `[error] toolpath leaves the target rectangle` | 输入坐标系与 frame 不匹配 | 见下节“坐标与尺寸” |
| 报 `[error] flattened geometry exceeds N points` | 图形过于复杂或展平容差太小 | 增大 `--flatten-tol`（如 0.05），或简化图形 |
| 报 `[error] hatch spacing … needs N scan lines` | 填充间距相对图形太小 | 增大 `--hatch-spacing` |

## 坐标与尺寸

| 现象 | 可能原因 | 处置 |
|---|---|---|
| 刻出来是**镜像/倒置**的 | 输入/输出原点方向不一致 | 图形 Y 向下且机床原点在左下：默认即可；机床原点在左上：`--output-origin top-left`；图形本身 Y 向上：`--input-origin bottom-left` |
| 尺寸大得离谱（比如要 50mm 出来 500mm） | SVG 的 `viewBox` 单位很大而按 100 网格假设缩放 | 已自动按 `viewBox` 处理；若仍不对，用 `--frame x0 y0 w h` 显式声明源坐标系，或 `--normalize auto` |
| 尺寸小得几乎看不见 | 顶点是 0–1 或 0–1000 区间，而默认按 0–100 网格 | `--normalize auto`（按图形包围盒铺满目标尺寸）或 `--frame` |
| 圆变成了椭圆 | 目标尺寸宽高比与图形不一致（`--fit stretch` 默认独立缩放 X/Y） | 用 `--fit contain` 保持比例，或把 `--target-size` 改成与图形同比例 |
| 图形整体偏移 | `--offset` 语义是“从工件原点平移”，且在 Y 翻转之后施加 | 想要右下角起刻：`--offset` 给出相对于工件原点的 X/Y |
| 刻出来少了半截 | 早期版本的静默截断（弧线/平滑曲线） | 已支持 `A/S/T`；若仍缺，检查是否含 `<text>`/`<image>`（会 `[warn]` 提示已跳过） |

## SVG 输入

| 现象 | 可能原因 | 处置 |
|---|---|---|
| `[error] no usable shapes found in SVG` | 图形是 `<text>`、位图描摹或全在 `<defs>` 里 | 在矢量软件里“文字转曲/轮廓化”后另存，或导出为 path |
| `[error] unsupported character(s) …` | path 里含不支持的命令或字符 | 只支持 `M L H V C S Q T A Z`（含相对形式）；重新导出为 SVG 1.1 path |
| 图形位置/大小不对（有 `<g transform>`） | 早期版本忽略 transform | 现支持 `matrix/translate/scale/rotate/skewX/skewY` 及嵌套 `<g>`；若用了 `<use>`/`<symbol>`，先在矢量软件里“展开/展开符号” |
| 只切出一部分 | 图形被 `clipPath`/`mask` 裁过 | 不支持裁剪，按未裁剪形状输出；需要裁剪精度就在导出前完成布尔运算 |
| 圆角矩形切成了直角矩形 | `<rect rx/ry>` 不支持 | 会打印 `[warn]`；在矢量软件里转为 path 后导出 |

## 加工效果

| 现象 | 可能原因 | 处置 |
|---|---|---|
| 切不透 | 功率不足/速度过快/焦距偏/材料批次差异 | 先用 `--check` 看实际光功率，再降速 20% 或加 `--passes` +1；补做测试网格 |
| 边缘焦黑、背面黄 | 功率过高或速度过慢，或缺气泵 | 提速 20–30% 或降功率 10–20%，开气泵 |
| 细部糊在一起 | 功率过高、线距过密 | 降功率、加大 `--hatch-spacing`（如 0.15 → 0.25mm） |
| 填充区域有明显横线/斑马纹 | 线距过大（>0.3mm） | 减小 `--hatch-spacing` 到 0.1–0.15mm，时间会相应变长 |
| 填充跨过了镂空/孔洞 | 早期版本在同一条扫描线上不关激光 | 已修复为逐段 `M5 → G0 → M3 S → G1`；若出现，说明用的是旧脚本 |
| 填充把边缘烧糊、形状外溢 | 填充没有边界约束 | 用 `--fill-outline before` 先描边再填充 |
| 加工时间远超预期 | 填充过密、图形过大 | 看 `--check` 里的 `estimated time`，加大间距或缩小尺寸 |

## 怎么快速确认参数对不对

```bash
# 只出参数与几何报告，不写文件
python3 scripts/generate_gcode.py --svg part.svg --job cut \
  --material plywood_3mm --laser-w 10 --target-size 80 80 --check
```

报告里有实际光功率（`S/$30 × laser_w`）、刀路包围盒、燃烧长度与预计耗时，
以及所有 `[warn]`。先看这份报告，再去机床。
