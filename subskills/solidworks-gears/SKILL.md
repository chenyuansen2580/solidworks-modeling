---
name: solidworks-gears
description: "标准渐开线直齿轮、整圈齿廓拼接、齿根过渡、同草图一次拉伸。本机 SW2022 实测，依赖根技能 solidworks-modeling 的脚本。"
metadata:
  parent: solidworks-modeling
  status: verified
  verified_on: "SOLIDWORKS 2022 SP5 (30.5.0.0049)"
---

# 渐开线齿轮与整环齿廓

## 何时调用

用户说：齿轮 / 渐开线 / 齿廓 / z20 / 模数 / 齿数

## 依赖根技能（不复制代码）

- `gearmath.py (GearParams / GearGeom / flank)`
- `gearring.py (full_ring / check_ring)`
- `swlib_v2.py (spline / extrude_checked)`

## 能力边界

- GearParams 参数名是 mn / bw，不是 m
- gearmath.flank() 只给半齿廓，必须用 gearring.full_ring 拼整圈
- 中心孔必须与齿廓画在同一草图，一次拉伸；分开切孔会返回 None
- 等效渐开线，非真 5M 圆弧齿；不含斜齿/锥齿/变位/修形

## 工作流

1. 用 theory.py 先算解析体积
2. GearParams(mn, z, bw, bore) → GearGeom → flank
3. full_ring 拼整圈 2301/4601 点，check_ring 验 r_min/r_max
4. 同草图画整环样条 + 轴孔 + 减重孔，一次拉伸
5. volume_check 验偏差 <3%

## 覆盖能力

- `gear.involute`
- `gear.full_ring`
- `sketch.spline`

## 参考

- `references/gears.md`
- `references/pitfalls.md 齿轮章节`

## 交付门禁

- 几何断言通过（体积 / bbox / 实体数）
- 过程有 `exec_trace` 留痕
- 交付文件通过 `artifact_freshness` 校验
- 无法验证的项目记 BLOCKED，不写 PASS
