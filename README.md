# laser-gcode

将平面图形（顶点坐标列表或 SVG 矢量文件）转换为可直接上机的 **GRBL 激光 G 代码**，并按材料与激光器额定功率给出切割 / 雕刻 / 填充的功率、速度、遍数，自动换算 `S` 值。

> 本仓库为 **v2 优化版**。相对 v1 修复了 11 类确定性缺陷（含填充带光横穿镂空、SVG `viewBox` 被忽略导致 10 倍尺寸错误、圆弧被静默截断等），材料库由 9 种扩充到 13 种，并新增了可执行的评测套件。变更明细见下方[更新日志](#-v2-更新日志)。

## ✨ 特性

**参数侧**

- **按功率档位换算**：材料库按 5 / 10 / 20 / 40W 档位存「功率% + 速度 + 遍数」，`S = 功率% / 100 × $30`；
  同一份表在所有机器通用（10W 切 3mm 椴木是 `S1000` 两遍，40W 只需 `S700` 一遍），档位越界会 `[warn]` 而不是静默钳制。
- **13 种材料**：椴木 3/6mm、硬木、MDF、深色亚克力、皮革、纸板、纸张、阳极氧化铝（仅标记）、竹板、帆布、毛毡、板岩（仅雕刻）。
- **参数自检**：`--check` 输出实际光功率（`S/$30 × 额定功率`）、刀路包围盒、燃烧长度与预计耗时，不写文件。
- **安全内置**：SKILL.md 与 `references/safety.md` 固化红线（禁止 PVC/ABS/含铬皮革、MDF/皮革/亚克力必须排烟、切割开气泵、无人看护禁止运行）。

**几何侧**

- **三种作业**：矢量切割（`cut`）、轮廓雕刻（`engrave`）、内部 hatch 填充扫描（`fill`）。
- **SVG 完整支持**：`path` / `polygon` / `polyline` / `rect` / `circle` / `ellipse` / `line`；
  路径命令 `M L H V C S Q T A Z`（含相对形式）；`<g transform>` 的 `matrix/translate/scale/rotate/skewX/skewY` 与嵌套分组。
- **坐标系自动处理**：按 SVG `viewBox`（或 `width/height` 换算 mm/cm/in/pt/px）建立源坐标系，映射到 `--target-size`，
  再从图像坐标（原点左上、Y 向下）翻转到机床坐标（原点左下、Y 向上）——不会刻出倒置或 10 倍尺寸的图形。
- **自适应展平**：曲线在映射到 mm 之后按弦高误差（默认 0.02mm）展平；大图不会退化成多边形，小图不浪费点数。
- **填充逐段走位**：每个燃烧段独立 `M5 → G0 → M3 S… → G1`，**绝不会带着激光横穿镂空**；
  扫描线交点按奇偶配对，带孔图形正确跳过孔洞；支持 `--hatch-angle`、`--fill-outline before|after`。
- **越界体检**：`--bed W H` 校验刀路是否超出床身，超出目标矩形 / 出现负坐标 / 宽高比不一致都会 `[warn]`。

## 📦 安装

方式一：导入本仓库的打包文件 `laser-gcode.skill`（ZIP 格式，内含完整技能目录）。

方式二：把 `laser-gcode/` 目录放到你的技能根目录下，例如：

```
~/.agents/skills/laser-gcode/        # DeepSeek Harness
~/.codex/skills/laser-gcode/         # Codex
~/.claude/skills/laser-gcode/        # Claude Code
~/.config/agents/skills/laser-gcode/ # 通用 agents 根目录
```

方式三：直接调用生成器脚本，无需技能框架：

```bash
python3 laser-gcode/scripts/generate_gcode.py --help
python3 laser-gcode/scripts/generate_gcode.py --list-materials
```

依赖：仅需 Python 3.9+ 标准库，无第三方依赖。

## 🚀 快速使用

枫叶切割（10W 机器切 3mm 椴木，80mm 见方）：

```bash
python3 laser-gcode/scripts/generate_gcode.py \
  --vertices "50,2 57,18 71,16 62,35 98,43 78,62 93,68 65,75 68,85 53,80 53,98 47,98 47,80 32,85 35,75 7,68 22,62 2,43 38,35 29,16 43,18 50,2" \
  --job cut --material plywood_3mm --laser-w 10 --target-size 80 80 \
  --output maple_leaf_cut.gcode
```

输出摘要：`S=1000 feed=500 passes=2`，包围盒 `76.8 × 76.8 mm`，预计 1.4 分钟，Y 轴已自动翻转（叶尖朝上）。

上机前先自检（不写文件）：

```bash
python3 laser-gcode/scripts/generate_gcode.py --svg part.svg --job fill \
  --material acrylic_dark_3mm --laser-w 20 --target-size 50 50 --bed 300 300 --check
```

## 📁 结构

```
laser-gcode/
├── SKILL.md                          # 技能主指令（机器确认清单 / 安全红线 / 工作流 / 交付检查）
├── scripts/generate_gcode.py          # 核心生成器（约 1350 行，纯标准库）
├── references/
│   ├── materials.json                # 材料参数库（13 种 × 功率档位）
│   ├── materials.md                  # 材料库说明 + 测试网格方法
│   ├── safety.md                     # 完整安全清单（火灾 / 眼防护 / 材料毒性表）
│   ├── troubleshooting.md            # 现象 → 原因 → 处置排查表
│   └── example-maple-leaf.md         # 完整案例（含输出 G 代码逐行讲解）
└── evals/
    ├── evals.json                    # 13 个评测用例（含可判定的 expectations）
    ├── run_evals.py                  # 可执行评测器（每条期望对应一项机器检查）
    └── assets/                       # 测试图形（viewBox 1000 / 圆弧 / 开放折线 / 变换圆形）
```

## 📊 测试结果

**确定性评测**（`python3 laser-gcode/evals/run_evals.py`，13 个用例 / 48 条期望）：

| 版本 | 通过率 |
|---|---|
| 优化后（本仓库 v2） | **48/48（100%）** |
| v1 生成器脚本 | 20/48（41.7%） |

**端到端 A/B**（4 个真实请求 × 2 个版本，agent 实际执行并交付，20 条期望）：

| 配置 | 通过率 |
|---|---|
| 优化后技能 | **20/20（100%）** |
| v1 技能 | 17/20（85%） |

明细见 `laser-gcode-workspace/iteration-2/`（`benchmark.md`、逐用例 `grading.json` 与产出文件、`deterministic/` 两份评测报告）。
v1 时的 A/B 记录保留在 `laser-gcode-workspace/iteration-1/`（with_skill 100% vs 无技能基线 76.7%）。

值得一提：A/B 中有一个使用 v1 的 agent 自行诊断出「填充带光横穿」缺陷——
五角星图形上量得 **389.2mm 带光直线穿过镂空**（最长 13.1mm，占全部燃烧长度 8.5%），
然后自己写工具把连接线改写成关光走位。v2 把这件事从「靠模型现场发现并救火」变成了脚本的结构性保证。

## 🔧 v2 更新日志

| 编号 | 缺陷（v1） | 后果 | v2 修复 |
|---|---|---|---|
| B1 | SVG 忽略 `viewBox` | 1000 单位画布切出 500mm（10 倍超床身） | 按源坐标系正确映射 |
| B2 | `A`/`S`/`T` 路径命令被静默 `break` | 图形截断成三角形 | 完整支持，无法解析时明确报错 |
| B3 | 填充段落之间保持激光开启 | 凹形图形镂空被烧穿（实测 389mm） | 逐段 `M5 → G0 → M3 S → G1` |
| B4 | `--hatch-spacing 0` 死循环 | 脚本永不返回 | 立即 `[error]` 退出 |
| B5 | JSON 输入绕过顶点数校验 | 2 个顶点也生成「多边形」 | 一并强制 ≥ 3 |
| B6 | `fill` 无视 `--passes` | 摘要报 3 遍、实际 1 遍 | 真正重复整轮 |
| B7 | 开放折线被强制闭合 | 多烧一条线 | 默认保持开放，`--close yes` 才闭合 |
| B8 | 档位静默钳制 | 参数偏离意图而用户不知情 | 越档位 `[warn]` |
| B9 | 不支持 `<circle>` / `<g transform>` | 设计工具导出即失败或错位 | 完整支持 |
| B10 | `--offset` 在 Y 翻转前施加 | 正偏移把工件下移、出现负坐标 | 翻转后施加，可安全居中 |
| B11 | 无床身/包围盒校验、无耗时估计、异常抛 traceback | 超床身刀路直接上机 | `--bed` 校验、`--check` 报告、`[error]` + 退出码 2 |

新增参数：`--frame`、`--normalize auto`、`--fit contain|stretch`、`--bed`、`--check`、`--list-materials`、
`--laser-mode m3|m4`、`--rapid-rate`、`--park/--no-park`、`--flatten-tol`、`--max-points`、`--max-scanlines`、`--close`。

## ⚠️ 已知边界

- 材料参数全部是**起点**：批次、焦距、透镜、气泵都会影响结果，务必先做 5×5 功率×速度测试网格。
  其中竹板 / 帆布 / 毛毡 / 板岩四项是按同类材料类比给出的社区范围值，**未经实测**。
- 二极管激光**不能切金属、不能切透明亚克力**；PVC/ABS/聚碳酸酯/含铬皮革等材料会产生剧毒气体，禁止加工。
- 不支持 `clipPath` / `mask` / `<text>`（文字需先转曲）、不支持 `<use>`/`<symbol>`（需先展开）。
- **不支持刀路裁剪与分块（tiling）**：超出床身的图形只能整体缩放或换机器，不能自动拆成多次装夹。
- 不是切片软件的替代品：不做排版、不支持 Raster/位图雕刻（灰度图像），只处理矢量轮廓与填充。
