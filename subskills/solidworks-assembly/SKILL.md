---
name: solidworks-assembly
description: "组件摆位（旋转件按圆心）、基准件固定、配合真生效验证、干涉三态判定、存盘。本机 SW2022 实测，依赖根技能 solidworks-modeling 的脚本。"
metadata:
  parent: solidworks-modeling
  status: verified
  verified_on: "SOLIDWORKS 2022 SP5 (30.5.0.0049)"
---

# 装配体与配合

## 何时调用

用户说：装配 / 配合 / 摆位 / 干涉 / 装配体

## 依赖根技能（不复制代码）

- `swlib_v2.py`：`place_center_to` / `axial_center_of` / `bbox_after_rot` /
  `fix_all` / `faces_of` / `plane_at` / `cyl_of` / `interference_verdict`
- `test_assembly_contract.py`（11 条静态断言，判据缺陷防回归）
- `test_assembly.py`（端到端，默认无出图）

## ★ 铁律（2026-11-22 审查后更新）

1. **旋转件/同心件用 `place_center_to`，不是 `place_to`。**
   `place_to` 对齐 bbox 角；非正方形转 120° 后 bbox 从 43.5 涨到 59.5，
   圆心必偏（实测偏 4.54 / 10.71mm，而 `place_to` 仍报 dev≤0.005）。
2. **不要先 `fix_all` 再加配合。** 全固定后配合被记录但不参与求解：
   实测 10 条配合里 2 条 `count_mates` 增量 +1、两件却相距 11.35mm。
   正确：只固定基准件 → 加配合 → 求解定位 → 验几何 → 最后全固定。
3. **`max_drift=0` 证明不了装配正确。** 配合前全固定时漂移恒 0。
4. **干涉用 `interference_verdict()` 三态**：`unknown` 判 BLOCKED。
   `(None,None)` 不是"无干涉"——全固定装配穿入 10.33mm 也返回它。
5. `IFace2.GetBox()` 是零件局部坐标；挑面用 `faces_of` + `plane_at(cyl_of)`。

## 工作流

1. 插组件；旋转件用 `place_center_to(..., check_center=axial_center_of)` 按圆心摆位
2. 只固定基准件（壳体/机架），其余自由
3. `faces_of` + `plane_at/cyl_of` 挑面（sign=None 最稳）
4. 加配合；每条后 `count_mates` 判增量 **+ `axial_center_of` 验圆心到位**
5. `interference_verdict()` 必须 `status=="clean"`；unknown 不许写 pass
6. 验收通过 → `fix_all` → `save_checked`（默认先重建再存盘）→ 交付

## 覆盖能力

- `asm.insert` / `asm.place` / `asm.place_center` / `asm.fix`
- `asm.mate.*` / `asm.interference_verdict` / `export.step`

## 参考

- `references/pitfalls.md` V1~V5（判据失效）、S5/S6/S12（摆位与视口）
- `references/api-cookbook.md` 装配节（完整代码）
- `references/example_belt_actuator.md`（历史案例）

## 交付门禁

- 圆心/中心距验到位（±0.05mm），不是只看 bbox
- 配合真生效：几何距离验证，不是只看 `count_mates`
- 干涉 `status=="clean"`，unknown 记 BLOCKED
- 过程有 `exec_trace` 留痕；交付文件通过 `artifact_freshness`
- 默认无出图：视图/PDF 只在用户显式要求时做
