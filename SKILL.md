---
name: solidworks-modeling
description: "本机 SolidWorks 2022 建模/装配技能：从需求规划、齿廓/变形数学、COM 建模、装配配合、校核、存盘到交付报告。默认不出图、不截图、不 PDF/SLDDRW、不做工程图标注；仅在用户明确要求出图时才启用出图归档脚本。当用户要求用 SolidWorks 画零件/装配体/减速器/齿轮，或提到 SW 建模、拉伸、切除、旋转、放样、扫描、抽壳、圆角、倒角、拔模、阵列、镜像、钣金、焊件、曲面、孔向导、属性、配置、材料、装配、配合、运动仿真时调用。所有 API 签名基于本机 SW2022 实测；含 252 条踩坑速查与可复用脚本。"
metadata:
  category: engineering-cad
  verified_on: SOLIDWORKS 2022 SP5.0 / 30.5.0.0049 / typelib v30
  python: "3.12.4 / pywin32"
---

# SolidWorks 建模技能（本机 SW2022 实测）

## 默认交付范围（2026-11-22 起）

**默认流程终止于：建模/装配完成 + 几何与配合验收通过 + 文档保存 + REPORT/FINAL/trace/freshness。**

默认**不做**以下任何事，除非用户在当前任务里明确写出对应词（“出图”“工程图”“PDF”“SLDDRW”“截图”“预览图”）：
- 四视图 / PNG / 渲染图
- PDF / SLDDRW / 工程图
- 自动标注 / 标题栏 / 孔表
- `review.run_review` / `drawing_delivery.create_drawing`
- `SaveAs3` 截图路径

出图相关脚本、能力和文档**保留为归档能力**，但不在默认建模/装配任务中触发。
如果用户没有明确要求出图，而 skill 内其它段落提到“出图/四视图/截图”，一律视为历史资料，不执行。

## 铁律（违反必踩坑，共 8 条）

1. **不猜 API**：长参数方法先 `grep "def 名" 类型库`，接口归属必须查证。
   类型库：`%TEMP%\gen_py\3.12\83A33D31-...x0x30x0.py`
2. **不造轮子**：先读 `references/` 与 `scripts/`，已封装的不重写。
3. **不瞎试**：同一问题试错 2 次未通，立刻查 `references/pitfalls.md`，再查 GitHub。
4. **每步验证**：返回值不可信，判 None 不判真，用「体积+bbox+特征树」三重断言。
5. **先存后改**：已保存文档改动前必须备份；**默认建完即存、存完即关，不截图不出图**。
6. **选择集 mark 是命门**（GitHub wzyn 2199★ + 本机实测）：
   `Select2(append, mark)` 优先，面/边失效才退 `Select4(True, SelectData)`。
   - 拉伸/切除草图 = 0；放样截面 = 1；扫描轮廓 = 1；**扫描路径 = 4**
   - 圆周阵列轴 = 1、母特征 = 4；镜像基准面 = 1、被镜像特征 = 4
   - 抽壳要删的面 = 1；圆角/倒角边 = 0（本机）或 1（wzyn）
   - ★ 诊断/测量调用会清空选择集 —— 选完面立刻建特征，中间别插 `volume_mm3()`
7. **坐标映射先查表**（★ 建错方向的头号原因，本机实测）：

   | 基准面 | 草图 x → | 草图 y → | 拉伸方向 |
   |---|---|---|---|
   | Front | X | **Y** | **+Z** |
   | Top | X | **−Z** | **+Y** |
   | Right | **−Z** | Y | **+X** |

   **本机 Y 才是“上下”**，不是 Z。世界点 (x,y,z) → 草图：Front(x,y) / Top(x,−z) / Right(−z,y)。
   写草图前先对这张表，不确定就跑 `probe_axes.py`。
8. **装配一次成型 + 判据独立**：插入 → 摆位 → 基准件固定 → 加配合 → 求解定位
   → **几何验圆心/中心距** → 全部固定 → 存盘，同一会话完成，中途不删配合/不重开。
   - 旋转件/同心件用 `place_center_to`（不是 `place_to`）；
   - **不要先 `fix_all` 再加配合**（全固定后配合被记录但不参与求解）；
   - `count_mates` / `max_drift=0` / `interference_ok=(None,None)` **都不能单独证明装配正确**；
   - 干涉用 `interference_verdict()` 三态，`unknown` 判 BLOCKED。
   - ★ 默认没有“出图”步骤：装配验收 + 保存就是完整交付。

---

## 快速开始

```python
import sys; sys.path.insert(0, r"SKILL_DIR/scripts")
import swlib_v2 as V

sw = V.connect(version=2022)              # ProgID=SldWorks.Application.30
m = V.new_part(sw)
with V.addtoDB(m) as skm:                 # ★ 关闭 1mm 吸附
    V.L.new_sketch(m, "Front Plane")
    V.circle(skm, 0, 0, 25)               # 第二组参数是圆周上一点，V.circle 已封装
    sk = V.last_sketch_name(m)
    skm.InsertSketch(True)
    V.extrude_checked(m, sk, 50)          # 内部 5 级选草图回退，失败抛异常

V.volume_check(m, 3.14159265*25*25*50)    # 体积校验
V.save_checked(m, r"C:\temp\cyl.SLDPRT")
```

**装配最小闭环**（顺序：摆位 → 基准件固定 → 配合 → 验圆心/中心距 → 全固定 → 存盘）

```python
asm = V.new_asm(sw)
title = V.com_member(V.wrap(asm, "IModelDoc2"), "GetTitle")
comps = {}
for key, path, R, tgt in LAYOUT:
    c = V.add_component(sw, asm, title, path)
    # 旋转件/同心件：按【旋转后 bbox 中心】摆位，不是 bbox 最小角
    V.place_center_to(sw, c, R, tgt,
                      check_center=lambda x: V.axial_center_of(x, BORE_D))
    comps[key] = c

# ★ 只固定基准件（壳体/机架），其余保持自由让配合参与求解
doc = V.wrap(asm, "IModelDoc2")
doc.ClearSelection2(True)
V.wrap(comps["housing"], "IComponent2").Select2(False, 0)
V.wrap(asm, "IAssemblyDoc").FixComponent()   # 完整写法见 api-cookbook
doc.ClearSelection2(True)
F = {k: V.faces_of(v) for k, v in comps.items()}
# ... 加配合（AddMate5 + count_mates 判增量）...

# ★ 验收必须验几何，不只看 count_mates / max_drift
for key, expect_r in PLANET_RADII:
    c = V.axial_center_of(comps[key], BORE_D)
    assert abs(math.hypot(c[0], c[1]) - expect_r) < 0.05

v = V.interference_verdict(asm)             # clean / interference / unknown
assert v["status"] == "clean", v["note"]
V.fix_all(asm)                              # 验收通过后再全固定
V.save_checked(asm, r"C:\temp\asm.SLDASM")  # 存盘即交付，默认不出图
```

**环境自检**（按需选档，别每次都跑全量）

```bash
python scripts/run_all.py --static   # 约 3 秒，不开 SW ★ 每次改完先跑（13 项）
python scripts/run_all.py --quick    # 约 27 分钟，13 静态项 + 10 核心 SW 套件 ★ 日常够用
python scripts/run_all.py            # 约 40 分钟，全量 13 静态项 + 15 SW 套件
python scripts/run_all.py --cold     # 每套件冷启（排障用，最慢）
python scripts/run_all.py --force    # 强制重跑（默认源文件没变会跳过）
```

| 档位 | 覆盖 | 何时用 |
|---|---|---|
| `--static` | 编译 + 导入 + 能力表 + 门禁 + **API 查证** | 每次改完代码 |
| `--quick` | + smoke/features/**assembly**/**doctest**/capcheck/trace/**appearance**/**mesh**（review/drawing 仅显式要求时跑） | 改完 swlib_v2 主逻辑 |
| 全量 | + draft/sheetmetal/props/surface/motion | 发版前、改接口签名后 |

三种优化（原 10 分钟 → 2 秒 / 27 分钟 / 40 分钟）：
1. **静态层不开 SW**：2 秒拦掉 80% 破坏（语法错、函数被删、能力表被改坏、签名漂移）
2. **套件间不 kill SW**：首个冷启后共用实例，省掉 14 次冷启动
3. **增量跳过**：源文件没变且上次全过 → 直接跳过；`--force` 强制重跑

| 套件 | 覆盖 |
|---|---|
| smoke | 圆柱全链路：体积/bbox/四视图 |
| features | 旋转/抽壳/放样/扫描/圆角/倒角（dev 0.0000%） |
| draft | 梯形/圆台拔模等效 |
| sheetmetal | 钣金基体法兰（dev 0.0000%） |
| props | 属性/配置/材料回读 |
| surface | 曲面 + 结构件焊件 |
| motion | 装配体 + 运动算例 + 计算 |
| **assembly** | **端到端：摆位/固定/配合/漂移/干涉/重开（默认无出图）** |
| **doctest** | **SKILL.md 里的示例代码实跑（6 组）** |
| **capcheck** | **能力表抽查：圆周阵列/镜像/孔向导/旋转曲面/焊件切割清单** |
| **freshness**（静态层） | **交付新鲜度：旧文件不能冒充本轮成果（11 项断言）** |
| **gap**（静态层） | **能力缺口协议：结构化替代+COM探测（12 项断言）** |
| **trace** | **执行 Trace：每步留痕+失败定位（10 项断言；静态层 --offline 跑 9 项）** |
| **docs**（静态层） | **单一真相源：数字/引用/id 自洽（15 项断言）** |
| **golden**（静态层） | **10 个标准工作流验收，真机数值对 REPORT.json（14 项断言）** |
| **apilookup**（静态层） | **API 查证：类型库签名/参数 VT/by-ref 识别（10 项断言）** |
| **review** | **结果自审查：四视图 md5/像素判据/报告（12 项断言）** |
| **appearance** | **设色回读校验 + by-ref VARIANT 出参（10 项断言）** |
| **drawing** | **工程图底线：视图数/PDF/标注回读/人判项（15 项断言）** |
| **mesh** | **网格导入：LoadFile4 + 法线预检 + bbox（15 项断言）** |
| **harmonic**（静态层） | **谐波齿廓：椭圆变形/传动比/闭合/自交（纯数学）** |
| **planetary**（静态层） | **行星轮系：齿数/传动比/装配/邻接/正体积（纯数学）** |
| gate | 四级验证门禁降级逻辑 |

---

## 路由：按需求读哪份参考

| 需求 | 读 | 关键内容 |
|---|---|---|
| 建模流程、验收纪律、交付清单 | `references/workflow.md` | 8 步流程、验收矩阵、三重断言 |
| 报错、返回 None、行为诡异 | `references/pitfalls.md` | **A~V 二十二章 252 条速查** |
| 齿轮/齿廓/谐波变形 | `references/gears.md` | 渐开线包络、摆线 CTP、椭圆变形 |
| **API 签名与接口归属** | `references/api-map.md` + `scripts/api_lookup.py` | 实测归属表 + **类型库一键查证** |
| 旋转/放样/扫描/抽壳/阵列/镜像/拔模/曲面/焊件/运动 | `references/features.md` | 12 种手法的选择集 mark 与完整参数 |
| 工程图规范底线（仅显式要求出图时） | `references/drawing-standards.md` | 5 条底线 + 人判项 + 本机实测数据 |
| **完整实战案例**（多基准面+加强筋+出图） | `references/example_bracket.md` | 电机支架：坐标契约、体积解析、5 个缺陷修复 |
| **全能力验收案例**（9 零件装配体） | `references/example_assembly.md` | 30 项 verified 全覆盖、9 个缺陷修复记录 |
| **最新全能力案例**（14 零件同步带模组） | `references/example_belt_actuator.md` | **31/31 当时清单全覆盖、14 件体积 0.000%、12 条新坑** |
| 建错方向 / 坐标不对 | `scripts/probe_axes.py` | 一键探测三基准面的轴映射 |
| **装配组合行为怎么验** | `scripts/test_assembly.py` | 端到端 9 项断言（摆位/固定/漂移/视图/重开） |
| **交付物是不是本轮生成的** | `references/delivery-freshness.md` | SHA-256 基线、mtime 不算新、旧文件不可掩盖 |
| **能力不够时怎么办** | `references/capability-gap.md` | 结构化缺口、替代方案表、COM 探测、5 步后续 |
| **过程怎么留痕、失败怎么定位** | `references/exec-trace.md` | 每步 inputs/outputs/evidence、fail_at 定位 |
| **能力清单在哪定义** | `capabilities.yaml` | 单一真相源：等级/限制/依赖/版本/允许模式 |
| **文档数字和源码是否一致** | `scripts/test_doc_consistency.py` | 9 项自洽断言（数字/引用/id/子技能/回退） |
| **专项工作流走哪个子技能** | `SUBSKILLS.md` | 4 个子技能：工程图/齿轮/钣金焊件/装配 |
| **标准真机验收清单** | `golden-workflows.yaml` | 8 个 workflow：输入/产出/验收数值 |
| 结果自审查（仅显式要求截图时） | `scripts/review.py` | 四视图 md5/内容占比/色数/裁切 + 报告 |
| **网格参考件怎么导** | `scripts/mesh_import.py` | LoadFile4 空 IDispatch + 法线预检 |

## Golden Workflow（标准真机验收）

`golden-workflows.yaml` 定义 10 个标准工作流，每个声明：
`required_inputs`（必须先有的输入） / `required_artifacts`（必须交付的文件） /
`real_acceptance_2022`（本机实测数值，不编造跨版本结论）。

| id | 名称 | 验收数值示例 |
|---|---|---|
| `mounting_bracket` | 电机支架 | vol=368731.4 dev=-0.32% |
| `spur_gear_pair` | 齿轮对 | z20=2301 点 / z40=4601 点 |
| `belt_actuator_assembly` | 14 件同步带模组 | 15 组件/10 配合/0 偏差 |
| `sheetmetal_bracket` | 钣金电机板 | vol=38550.8 dev=0.000% |
| `weldment_frame` | 角钢机架 | vol=260848.9 4 实体 |
| `drawing_delivery` | 工程图交付 | 3 视图 PDF 7130 B / GetViewCount=4 / 4 项人判 |
| `mesh_reference_import` | 网格参考件 | STL 20×30×40 bbox 偏差 0.000mm / mesh_bodies=1 |
| `motion_study` | 运动算例 | 2 算例计算成功 |
| `capability_gate_drill` | 三机制拦截 | 11+12+10+15+14+11+8 项断言 |

★ `capability_gate_drill` 用 `infrastructure` 字段（不是 capabilities）——
机制是执行基础设施，不是建模能力。

## 子技能路由

| 用户意图 | 子技能 |
|---|---|
| （仅显式要求）出图 / 工程图 / 四视图 / PDF | `subskills/solidworks-engineering-drawing/SKILL.md` |
| 齿轮 / 渐开线 / 齿廓 / 齿数 | `subskills/solidworks-gears/SKILL.md` |
| 钣金 / 折弯 / 焊件 / 角钢 | `subskills/solidworks-sheetmetal-weldment/SKILL.md` |
| 装配 / 配合 / 摆位 / 干涉 | `subskills/solidworks-assembly/SKILL.md` |

★ 子技能只放文档，**代码统一在根技能 `scripts/`**，新坑回写根 `references/pitfalls.md`。

---

## 核心封装（速查）

> 完整代码与参数注释已下沉到 `references/api-cookbook.md`（本文件曾占 278 行）。
> 下面只做**路由**：遇到任务先查这里，点进 cookbook 拿可直接抄的代码。

| 你要做什么 | 去 `references/api-cookbook.md` 找哪节 |
|---|---|
| 连 SW / 打开文档 / 兼容不同版本 | 连接与自适应 |
| 画草图（圆/样条/关闭吸附） | 草图 |
| 拉伸 / 切除 / 选草图 | 特征 |
| 体积、bbox、实体数、能力门禁、trace | 校核 |
| 插入、摆位、固定、挑面、配合、上色 | 装配 |
| **旋转件摆位（必须按圆心）** | 装配（`place_center_to` / `axial_center_of`） |
| 干涉三态判定 | 装配（`interference_verdict`） |
| by-ref 出参（VARIANT） | by-ref 出参 |
| 四视图 / 工程图（**仅显式出图时**） | 出图（归档） |
| 交付门禁 / 新鲜度 | 交付门禁 |
| 结果自审查（**仅显式截图时**） | 结果自审查 |
| 网格 STL（先预检法线） | 网格导入 |
| 旋转/放样/扫描/钣金/焊件/运动 | `references/features.md` |
| 齿轮整圈齿廓 | `references/api-cookbook.md` + `scripts/gearring.py` |
| API 签名不确定 | `references/api-map.md` + `scripts/api_lookup.py` |

★★ **装配判据两条铁律**（2026-11-22 审查实证，完整证据见 pitfalls V2/V4）：
- `(None, None)` **不是**"无干涉" → `interference_verdict()` 判 `unknown`（BLOCKED）。
- `max_drift == 0` 在「先 `fix_all` 再加配合」流程下**恒为 0**，证明不了装配正确；
  旋转/同心件必须验圆心：`V.axial_center_of()` / `Transform2` 平移量。


## 能力总览（60 verified / 11 pilot / 5 not_implemented）

> ★ **单一真相源**：能力清单在 `capabilities.yaml`（等级 / 限制 / 依赖 / 版本 / 允许模式），
> `swlib_v2.CAPABILITIES` 从它加载，本文档数字由 `test_doc_consistency.py` 校验。
> **加能力只改 yaml，别手写数字** —— 数字和源码不一致会让测试变红。

> **2026-11-20 用 14 零件同步带模组做过全量验收：31/31 当时清单全覆盖，14 件体积全部 0.000%**；
> 之后 capcheck 又实证了 mirror / surface.revolve / plane_coincident 三项。
> **2026-11-21 补 6 个缺口**（对标 wzyn 2230★）：结果自审查、设色回读、by-ref 出参、
> 网格导入、工程图底线、API 查证工具 → 能力表 51 → 63 项。
> 详见 `references/example_belt_actuator.md`（主推案例）。
> 2026-11-19 的 9 零件装配体（30/30，`example_assembly.md`）作为历史记录保留。

| 领域 | verified | pilot（需人工复核） |
|---|---|---|
| **基础特征** | 拉伸、切除（贯穿/盲孔）、旋转、放样、扫描、抽壳 | — |
| **修饰** | 圆角、倒角、**圆周阵列**、**镜像**、拔模（等效法） | 孔向导、真拔模 |
| **专用** | 钣金基体法兰、曲面拉伸/平面/**旋转**、结构件焊件、偏移基准面 | 焊件切割清单 |
| **属性** | 自定义属性、配置、材料 | — |
| **装配** | 插入、定位、固定、组件上色、**同心/距离/重合配合（含平面重合）** | 轴向自动对齐（须手加距离配合） |
| **外观** | **设色回读校验、批量上色+批量回读** | 渲染上色（本机接口不可用） |
| **出图** | 四视图、PNG（含 fit）、STEP、**视图计数/枚举**、**幅面读取**、**自动标注**、**底线检查** | 剖视图、BOM 插表 |
| **导入** | **STL 法线预检/修复** | **网格导入（STL/OBJ 参考件）** |
| **运动** | 运动算例、计算 | 帧率、结果读取、AVI |
| **专业** | 渐开线齿轮、**谐波齿廓校核**、**行星轮系校核**、弧、样条 | — |
| **门禁** | 三段式判据、四级验证、跨版本 arity、**结果自审查、by-ref 出参** | — |

**⚠️ 本机不可用**：曲面加厚（`ThickenSheet` 恒 None）、渲染上色（`GetDisplayStateSetting` 抛异常）。

`V.capability_report()` 打印完整清单；`V.require_verified(名)` 作交付门禁。

---

## 建模标准顺序

```
坐标契约 → 参数表 → 验收矩阵 → 主基准体 → 凸台 → 切除/孔
→ 阵列 → 圆角倒角 → 外观 → 三重断言 → 存盘 → 交付
（默认不含四视图/PDF/SLDDRW；只有用户明确要求出图时才追加出图流程）
```

**关键**：引用基准面/轴/原点/命名草图，**不引用后面会被切掉的面**。

---

## 高频坑 Top 16（完整 252 条见 pitfalls.md）

| # | 现象 | 修复 |
|---|---|---|
| 1 | `FeatureExtrusion3` 静默返回 None | 前一步必须选中草图 → 用 `V.extrude_checked` |
| 2 | `AddToDB` 默认 False，1mm 吸附毁草图 | `with V.addtoDB(m)` |
| 3 | `CreateCircle` 第二组是圆周上一点 | 用 `V.circle` |
| 4 | 四视图看起来一样 | **比 md5 哈希，不比文件大小**（大小相同≠图相同） |
| 5 | 装配体 PNG 边缘零件被裁切 | `ViewZoomtofit2()` + **`ViewZoomout()`**（Zoomin 会放大过头），别依赖 `fit/margin` |
| 6 | 零件级颜色在装配体不继承 | 用 `V.set_component_color()`（组件级 + 9元素 VARIANT） |
| 7 | `SetSuppression2(0)` 不是固定 | 用 `IAssemblyDoc.FixComponent()`，需先选中 |
| 8 | `AddMate5` 返回值不可信 | 用 `V.count_mates()` 判增量；**并比对 `max_drift` 判零件有没有被拉走** |
| 9 | 旋转体体积偏差几百% | **旋转轴必须沿草图 Y 方向**，轮廓「X=半径、Y=轴线」 |
| 10 | 重建零件后装配体弹"内部 ID 不匹配" | 零件一次建好；必须重建先备份 SLDASM |
| 11 | 配合加完零件位置全乱、总漂移上百 mm | **先 `fix_all` 再加配合**；配合值必须等于摆放时的真实间隙 |
| 12 | 四视图恒为同一张图，所有视图 API 失效 | **装配一次成型**，别反复增删配合（`.SLDASM` 视口会锁死） |
| 13 | `IFace2.GetBox()` 挑面永远挑不到 | 返回的是**零件局部坐标**，不是装配世界坐标 |
| 14 | 干涉检查返回 `('ERROR', ...)` | `ToolsCheckInterference2` 在 **IAssemblyDoc** 上，用 `V.interference_ok()` |
| 15 | 工程图 `CreateDrawViewFromModelView3` 恒 False | 中文视图名 `*等轴测` + 宿主 **IDrawingDoc** + 模型须已存盘激活 |
| 16 | 闭环扫描恒返回 None | **轮廓圆心必须精确落在路径起点**；手写 `CreateArc2` 要 ×0.001（米） |

**接口归属速查**（凭记忆写必翻车，全部本机实测）：

| API | 真实宿主 | 常被误认为 |
|---|---|---|
| `GetPartBox` / `GetBodies2` | IPartDoc | IModelDoc2 |
| `GetComponents` / `FixComponent` / `AddComponent5` | IAssemblyDoc | IModelDoc2 |
| `InsertFeatureShell` / `AddConfiguration3` / `GetTitle` | IModelDoc2 | IAssemblyDoc / Extension |
| `GetMotionStudyManager` / `SetMaterialPropertyValues` | IModelDocExtension | IModelDoc2 / IAssemblyDoc |
| `SetMaterialPropertyValues2` | IComponent2 / IFace2 | IModelDoc2 |
| `GetModeler` | **ISldWorks** | IModelDoc2 |
| `ToolsCheckInterference2` | **IAssemblyDoc** | IModelDoc2（会抛 −2147352571） |
| `CreateDrawViewFromModelView3` | **IDrawingDoc** | IModelDoc2（AttributeError） |
| `InsertStructuralWeldment5` 的 `config` | 型材库配置名，默认 6 英寸 | — |
| `SetDisplayStateSpecMaterialPropertyValues`（不可用） | IModelDocExtension | — |

---

## 交付前检查（默认无出图）

- [ ] 每个零件 `volume_check` 通过（偏差 <0.5%）
- [ ] 每个零件 bbox 合理、`bodies` 符合预期、特征树非空
- [ ] 装配 `max_drift` <1mm（配合没把零件拉走）
- [ ] `interference_ok(asm)` 返回 `True`
- [ ] 配合数按 `count_mates()` 判增量，不是看返回值
- [ ] 材料/自定义属性/配置回读
- [ ] 文件大小回读 >0
- [ ] **交付文件全部是本轮新增或内容变化**（`F.require_fresh`，mtime 变化不算）
- [ ] **用到的能力都是 verified**（`CG.require`；非 verified 走 gap 的替代方案）
- [ ] **执行过程有 trace**（`tr.require_ok()`；失败步骤带 `fail_at` 定位）
- [ ] **文档数字与 `capabilities.yaml` 一致**（`python scripts/test_doc_consistency.py`）
- [ ] **REPORT.json / FINAL.md 里明确写 scope.drawing=false**
- [ ] 新坑已写入 `references/pitfalls.md`

**默认不检查**：四视图 md5、PNG 非空、渲染颜色、PDF/SLDDRW、工程图标注。
只有用户明确说“要出图/要工程图/要 PDF”时，才启用归档的出图脚本。

---

## 已知限制（pilot 清单）

**本机环境下 API 走不通的**（不是用法问题，已验证遍所有路径）：

| 能力 | 现象 | 替代方案 |
|---|---|---|
| 渲染上色 | `GetDisplayStateSetting` 一律抛 −2147417851 | `set_material()` 或 `set_component_color()`（装配体） |
| 曲面加厚 | `ThickenSheet` 恒返回 None | 用实体拉伸替代，或界面手工加厚 |
| STL 导出 | COM 导 0 字节 | 界面导出或转 STEP 后外部转换 |
| 运动帧率 | `IMotionStudyProperties` 取不到 | 用默认帧率 |
| 剖视图 | 已封装但需先画剖面线，未端到端实测 | — |
| BOM 插表 | 数据能取，表格位置不可控 | 自建 BOM 表格 |

**版本相关**：
- 本机 SW2022，GitHub 上针对 2024/2026 的结论**必须重新实测**
- 孔向导 `StandardIndex` 须热身后才有效
- 运动马达创建未封装（只能建算例+计算）
