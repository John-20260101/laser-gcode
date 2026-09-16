# laser-gcode

将平面图形（顶点坐标列表或 SVG 矢量文件）转换为适合 **GRBL 激光雕刻机**的 G 代码，并自动给出匹配材料与机器功率的切割/雕刻参数。

## ✨ 特性

- **三种作业**：矢量切割（`cut`）、轮廓雕刻（`engrave`）、内部 hatch 填充扫描（`fill`）
- **内置材料参数库**：椴木 / 硬木 / MDF / 深色亚克力 / 皮革 / 纸板 / 纸张 / 阳极氧化铝，按激光器功率档位（5/10/20/40W）给出功率% + 速度 + 遍数
- **功率自动换算**：`S = 功率%/100 × $30`，同一份材料库可在不同功率机器通用
- **坐标系自动处理**：图像左上角原点（Y 向下）↔ CNC 左下角原点（Y 向上）自动翻转，避免刻出倒置图形
- **双输入**：顶点坐标列表（灵活格式）或 SVG 文件（支持 polygon/polyline/rect/path，贝塞尔自动展平）

## 📦 安装

将 `laser-gcode.skill` 导入 Cursor / Claude Code 即可。或在 Cursor 中通过 skill 安装功能加载本仓库的 `laser-gcode/` 目录。

## 🚀 快速使用

以枫叶切割为例（10W 机器切 3mm 椴木，80mm 见方）：

```bash
python3 laser-gcode/scripts/generate_gcode.py \
  --vertices "50,2 57,18 71,16 62,35 98,43 78,62 93,68 65,75 68,85 53,80 53,98 47,98 47,80 32,85 35,75 7,68 22,62 2,43 38,35 29,16 43,18 50,2" \
  --job cut --material plywood_3mm --laser-w 10 --target-size 80 80 \
  --output maple_leaf_cut.gcode
```

输出：`S1000 / F500 mm/min / 2 passes`，Y 轴已自动翻转（叶尖朝上）。

## 📁 结构

```
laser-gcode/
├── SKILL.md                  # skill 主指令（含枫叶完整案例）
├── scripts/generate_gcode.py # 核心生成器
├── references/
│   ├── materials.json        # 材料参数库（按功率档位）
│   └── materials.md          # 材料库说明 + 安全须知
└── evals/                    # 测试用例
```

## ⚠️ 安全须知

所有参数均为**起点**，受材料批次、焦距、气泵影响，务必先在废料上做小测试网格再正式加工。
MDF/皮革/亚克力加工时必须通风；二极管激光不能切金属与透明亚克力。

## 📊 测试结果

带 skill 通过率 **100%** vs 无 skill baseline **76.7%**（3 个用例，详见 `laser-gcode-workspace/iteration-1/benchmark.md`）。
skill 的核心价值：按功率档位给准确参数 + Y 轴自动翻转。
