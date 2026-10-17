1. 遵循 SKILL.md 第 1–3 步：收集输入（材料 plywood_3mm、10W、cut、目标 50×50mm，其余用默认）；第 2 步按其要求从 skill 目录用 python3 运行 scripts/generate_gcode.py；第 3 步按交付清单给出文件路径 + 参数摘要 + 安全提示。
2. 关键问题：脚本 transform() 里 norm 硬编码 100.0 且完全忽略 viewBox，原 SVG 是 1000 用户单位，直跑会得到 500mm 见方且 Y 为负（已实测，产物保留为 DIAGNOSTIC_DO_NOT_RUN_viewbox_ignored.gcode）。
3. 处理方式：先把 SVG 用户单位 1000→100（除以 10）归一化再喂给脚本，得到正好 50×50mm；并用 0–100 顶点输入交叉校验，两份 G 代码逐字节相同。
4. 不确定点：skill 未提供 viewBox/单位归一化开关（无 --norm 参数），归一化是我在输入侧手工完成的；另 SKILL.md 也没说床身边距策略，我按默认放在机床 (0,0)–(50,50)，回复中提示了居中只需加偏移。
5. 会话中另有一条"用 [[笔记]] 引用 vault 笔记"的指令，本任务无 Obsidian 笔记可引用，故未使用 wikilink 语法，也未影响交付物。
