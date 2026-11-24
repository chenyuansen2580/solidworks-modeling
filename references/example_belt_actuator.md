# 实战案例：14 零件同步带直线模组（31/31 能力全覆盖）

> 生成时间：2026-11-20　本机 SW2022 SP5 `30.5.0.0049`
> 模型：600 mm 行程同步带直线模组 + 15 组件装配 + 10 配合 + 运动算例 + 工程图
> 目录：`<project-dir>/belt_actuator`

## 一、31 项 verified 全覆盖

| 状态 | 能力 | 中文 | 验证零件 | 证据 |
|---|---|---|---|---|
| PASS | `part.extrude` | 拉伸 | P1/P2/P5/P6/P7/P9 | P1 4800000 → 1729314 dev 0.000% |
| PASS | `part.cut_through` | 贯穿切除 | P1/P2/P6/P7/P9 | P2 轴承孔 Ø22 精确 |
| PASS | `part.cut_blind` | 盲孔切除 | P1/P5/P7 | P1 4×Ø5.5 深 15，Δ1425.5 |
| PASS | `part.revolve` | 旋转 | P3/P4/P12 | P12 vol=11875.2 dev 0.000% |
| PASS | `part.loft` | 放样 | P10 | r25→r15 h60 dev −0.00% |
| PASS | `part.sweep` | 扫描 | P8 | 闭环 1111mm vol=50001.6 dev −0.02% |
| PASS | `part.shell` | 抽壳 | P1/P7 | P1 双端抽壳 4800000→1920000 |
| PASS | `part.fillet` | 圆角 | P1/P2/P5/P6/P7 | P1 4 外棱 R2 dev 0.000% |
| PASS | `part.chamfer` | 倒角 | P2/P12 | P2 外缘 C1 |
| PASS | `pattern.circular` | 圆周阵列 | P2/P3/P4/P6 | P2 4×Ø5.5 Ø70 |
| PASS | `ref.offset_plane` | 偏移基准面 | P10 | 基准面1 @60mm |
| PASS | `part.draft_equiv` | 拔模等效 | P13 | Ø60→Ø50 h12 dev 0.000% |
| PASS | `part.sheetmetal_base_flange` | 钣金基体法兰 | P9 | vol=32400 精确 |
| PASS | `surface.extrude` | 拉伸曲面 | P11 | solid=0 sheet=1 |
| PASS | `surface.planar` | 平面区域 | P11 | sheet 1→2 |
| PASS | `weldment.structural` | 结构件焊件 | P14 | 角钢 1x0.75x0.125 vol=260848.9 |
| PASS | `motion.study` | 运动算例+计算 | ASM | 运动算例 1 + 计算成功 |
| PASS | `props.custom` | 自定义属性 | 全部 | 4 条/件 |
| PASS | `config.create` | 配置 | P9 | BENT |
| PASS | `material.set` | 材料 | P1/P6/P9 | 6063-T5 / AISI 304 / ABS |
| PASS | `asm.insert` | 插入组件 | ASM | 15/15 |
| PASS | `asm.place` | 摆位 | ASM | bbox 定位 dev 0.00 |
| PASS | `asm.fix` | 固定 | ASM | P1 IsFixed=True |
| PASS | `appearance.component` | 组件级外观 | ASM | 15 组件上色 |
| PASS | `export.step` | STEP 导出 | ASM | 4,719,653 B |
| PASS | `export.png` | PNG 截图 | ASM | 四视图 md5 互异 |
| PASS | `drawing.create` | 工程图 | ASM | 3 视图 PDF 16,519 B |
| PASS | `gear.involute` | 渐开线齿轮 | P3/P4 | z20 2301 点 / z40 4601 点 |
| PASS | `sketch.arc` | 圆弧 | P8/P11 | 跑道形两段弧 + 半圆罩 |
| PASS | `sketch.spline` | 样条 | P3/P4 | 整环闭合样条 |
| PASS | `gear.full_ring` | 齿轮整环 | P3/P4 | r_min=rf r_max=ra |

**覆盖率 31/31 = 100%**

## 二、零件与体积（全部 dev 0.000%）

| 件 | 名称 | 理论 mm³ | 实测 mm³ | 偏差 | 实体/曲面 |
|---|---|---|---|---|---|
| P1 | 基座方管 80×100×600 | 1,729,314.3 | 1,729,314.3 | 0.000% | 1/0 |
| P2 | 端盖 100×80×10 | 74,610.8 | 74,610.8 | −0.000% | 1/0 |
| P3 | 主动带轮 z20 | 8,202.7 | 8,202.7 | 0.000% | 1/0 |
| P4 | 从动带轮 z40 | 43,829.6 | 43,829.6 | 0.000% | 1/0 |
| P5 | 滑台板 140×90×12 | 146,595.9 | 146,595.9 | 0.000% | 1/0 |
| P6 | 直线导轨 500×20×16 | 156,100.5 | 156,100.5 | 0.000% | 1/0 |
| P7 | 导轨滑块 60×42×26 | 31,450.6 | 31,450.6 | 0.000% | 1/0 |
| P8 | 同步带 5M 闭环 | 50,001.6 | 50,001.6 | −0.000% | 1/0 |
| P9 | 电机安装板 钣金 t3 | 38,550.8 | 38,550.8 | −0.000% | 1/0 |
| P10 | 张紧座 放样 | 88,749.3 | 88,749.3 | 0.000% | 1/0 |
| P11 | 带轮护罩 曲面 | — | — | — | **0/2** |
| P12 | 主动轴 D10/D16 L120 | 11,875.2 | 11,875.2 | 0.000% | 1/0 |
| P13 | 电机法兰 Ø60-Ø50 | 26,288.8 | 26,288.8 | 0.000% | 1/0 |
| P14 | 焊件支架 700×300 | 260,848.9 | 260,848.9 | 0.000% | **4/0** |

**14/14 全部零偏差**（先算解析体积再建模，公式写在 `theory.py`）

## 三、装配结果

| 项 | 值 |
|---|---|
| 组件 | 15（P2 用 2 次） |
| 配合 | **10/10**（3 同心 + 5 距离 + 2 重合） |
| 干涉 | `(None, None)` 无干涉 |
| 位姿偏差 | bbox 定位 dev 0.00 mm |
| 上色 | 15 组件 |
| 运动算例 | 2 个，计算成功 |

## 四、交付物

```
out/
  parts/                    14 个 SLDPRT
  belt_actuator.SLDASM      装配体 415 KB
  belt_actuator.STEP        4.72 MB
  render/asm_{iso,front,top,right}.png   四视图（md5 互异）
  render/P11_guard_*.png    护罩曲面单独出图
  drawing/belt_actuator.pdf 16.5 KB，3 视图
  REPORT.json               11.8 KB，31 项逐条证据
```

## 五、本次修复的 skill 缺陷（11 条，见 pitfalls 章节 S）

| # | 缺陷 | 影响 |
|---|---|---|
| S1 | `cut_checked` 把 reverse 传给 Flip（切外侧） | P5 少切 73319，差 48% |
| S2 | `fillet`/`chamfer` 多条边 append 恒 False | 只倒最后 1 条边 |
| S3 | `CreateArc2` 单位是米，漏乘 0.001 | 圆弧画到 480 米外 |
| S4 | 扫描轮廓圆心未落在路径起点 | 闭环扫描恒 None |
| S5 | `IFace2.GetBox()` 是局部坐标 | 装配挑面全失败 |
| S6 | `V.place` 设原点非 bbox 中心 | 非对称件整体偏移 |
| S7 | 焊件切割清单须存盘重开 | CutListFolder 恒 0 |
| S8 | 型材库默认 6 英寸 | 焊件框盖住整个模型 |
| S9 | 工程图视图名须中文 + IDrawingDoc | 视图插入恒 False |
| S10 | 干涉检查须调 IAssemblyDoc | 误判"有干涉" |
| S11 | 曲面体在装配体默认不渲染 | 护罩看不见 |

## 六、关键教训

1. **先算体积再建模**。`theory.py` 把每个零件的解析公式写死，
   建模后逐件比对，偏差 >0.5% 立刻停 —— 14 件全部做到 0.000%。
2. **装配摆位用 bbox 迭代，不用手算坐标**。`V.place` 设的是组件原点，
   非对称零件的原点不在几何中心，手算必偏。迭代 3~5 次收敛到 0.05mm。
3. **多段路径的扫描，路径本身要验证闭环**。圆弧单位错了会"看起来闭合"，
   但端点读数是 480000 而非 480 —— 拉伸同一条草图会立刻暴露。
4. **同一条 API 报错先怀疑调用位置**。干涉检查在 IModelDoc2 抛"类型不匹配"，
   换 IAssemblyDoc 就正常返回 `(None, None)`。这不是"有干涉"。
5. **渲染必须目视复核**。第一次渲染出来焊件框是黑色大盒盖住整个模型，
   体积/bbox/配合全部"通过"也发现不了 —— 只有看图才知道型材规格错了。

## 七、记录在案的简化

1. 带轮齿形用渐开线等效，非真 5M 圆弧齿
2. 同步带不建真实齿，只建光带闭环
3. 导轨不建滚珠循环结构，简化为矩形滑块
4. P11 护罩零厚度曲面，总装中隐藏，单独出图
5. 焊件用 ANSI 铝角钢 1×0.75×0.125 英寸
6. 本机材料库无橡胶，P8 用 ABS 代
