# 实战案例：9 零件工艺演示装配体

> 生成时间：2026-11-19  本机 SW2022 SP5
> 模型：9 零件装配体 + 运动算例 + 工程图

## 一、30 项 verified 覆盖

| 状态 | 能力 | 中文 | 验证零件 | 证据 |
|---|---|---|---|---|
| ✅ PASS | `part.extrude` | 拉伸 | P1/P2/P3/P4/P5/P6/P9 | vol=160850 dev=-0.000% |
| ✅ PASS | `part.cut_through` | 贯穿切除 | P1/P2/P3/P4/P6/P9 | 1 孔 Δ-2124 |
| ✅ PASS | `part.cut_blind` | 盲孔切除 | P4 | 4×Ø7 深 11 |
| ✅ PASS | `part.revolve` | 旋转 | P5 | vol=84258 dev=-0.000% |
| ✅ PASS | `part.loft` | 放样 | P6 | r25->r15 h60 vol=76966 |
| ✅ PASS | `part.sweep` | 扫描 | P7 | R6 管 vol=20678 |
| ✅ PASS | `part.shell` | 抽壳 | P3 | 1072908 -> 156280 |
| ✅ PASS | `part.fillet` | 圆角 | P2/P3/P5 | 边 4:6 R1 Δ-15.9 |
| ✅ PASS | `part.chamfer` | 倒角 | P5/P9 | 外缘 C1.5 |
| ✅ PASS | `pattern.circular` | 圆周阵列 | P9 | 6×阵列 Δ-10619 (158726->148107) |
| ✅ PASS | `ref.offset_plane` | 偏移基准面 | P6 | plane=基准面1 |
| ✅ PASS | `part.draft_equiv` | 拔模等效 | P3 | dev=-0.044% top=111.6 |
| ✅ PASS | `part.sheetmetal_base_flange` | 钣金基体法兰 | P2 | dev=0.000% (115200/115200) |
| ✅ PASS | `surface.extrude` | 拉伸曲面 | P8 | 拉伸曲面 solid=0 sheet=1 |
| ✅ PASS | `surface.planar` | 平面区域曲面 | P8 | sheet=2 |
| ✅ PASS | `weldment.structural` | 结构件焊件 | P1 | al ls angle squared ends.sldlfp |
| ✅ PASS | `motion.study` | 运动算例+计算 | ASM | ['Motion Study 1'] -> ['Motion Study 1', '运动算例 1'] |
| ✅ PASS | `props.custom` | 自定义属性 | P1 | 4 条 |
| ✅ PASS | `config.create` | 配置 | P2 | WELDED |
| ✅ PASS | `material.set` | 材料 | P3 | ABS |
| ✅ PASS | `asm.insert` | 插入组件 | ASM | 9/9 组件 |
| ✅ PASS | `asm.place` | 摆位 | ASM | 9 组件摆位 |
| ✅ PASS | `asm.fix` | 固定 | ASM | P1 固定 |
| ✅ PASS | `appearance.component` | 组件级外观 | ASM | 9 组件上色 |
| ✅ PASS | `export.step` | STEP 导出 | ASM | 1873926 B |
| ✅ PASS | `export.png` | PNG 截图 | ASM | 四视图 {'iso': 9027, 'front': 9027, 'top': 9027, 'right': 9027} |
| ✅ PASS | `drawing.create` | 工程图 | ASM | 15704 B |
| ✅ PASS | `gear.involute` | 渐开线齿轮 | P4 | z=24 pts=2761 r=26.88..32.50 |
| ✅ PASS | `sketch.arc` | 圆弧 | P7 | R40 圆弧 |
| ✅ PASS | `sketch.spline` | 样条 | P4/P8 | 2761 点闭合 |

## 二、结果统计

| 项 | 数量 |
|---|---|
| 通过 PASS | **30** |
| 失败 FAIL | 0 |
| 总计 | 30 |

覆盖率 **100.0%**

## 三、pilot 探针

| 状态 | 能力 | 说明 |
|---|---|---|
| ⚠️ SKIP | `surface.thicken` 曲面加厚 | SKIP：ThickenSheet 本机一律返回 None |

## 四、交付物

```
out/
  parts/                9 个 SLDPRT
  demo_assembly.SLDASM  装配体（9 组件）
  demo_assembly.STEP    STEP 导出
  render/asm_*.png      四视图（fit 模式）
  drawing/*.pdf         工程图
```

## 五、本次实战修复的 skill 缺陷

| 缺陷 | 修复 |
|---|---|
| `bbox6` 对装配体传参过多 TypeError | 改为 1 参调用 + 回退 |
| `comps()` 用 IModelDoc2 调 GetComponents | 先 wrap IAssemblyDoc |
| `set_view` 用 m.GetTitle() 在装配体报错 | 内部 wrap IModelDoc2 |
| `save_png` 忽略 w/h，装配体留白巨大 | 新增 `fit=True` + `zoom_to_model()` |
| `surface_thicken` 调 IModelDoc2.GetModeler | 改 ISldWorks.GetModeler + sw 参数 |
| `circular_pattern_checked` 找轴失败 | 自动用 `face_cylinder()` 生成临时轴 |
| `ISurface.IsCylinder` 当方法调用报错 | 改属性读取，新增 `face_cylinder()` |
| 新增 `set_component_color()` | 组件上色 9 元素 VARIANT 封装 |
| **新增 `gearring.py`** | 整圈齿廓拼接（gearmath 只给单齿廓） |

## 六、关键教训

1. **旋转轴必须沿草图 Y 方向**：轮廓画成「X=半径、Y=轴线」，
   画在 X 方向会绕错轴，体积偏差 768%。
2. **齿轮孔必须画在同一草图**：外齿廓 + 内圆同草图一次拉伸，
   分开切孔会因齿廓样条拓扑异常而 cut 返回 None。
3. **装配体出图必须用 fit 模式**：`ViewZoomtofit2` 留白巨大，
   `ViewZoomTo2(bbox 角点)` 才能让模型占满画面。
4. **四视图「文件大小相同」不等于视图相同**：要比对 md5 哈希。
