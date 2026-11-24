# SolidWorks 工程图与出图

零件图/装配图、四视图、PDF/BMP 证据、中文视图名、md5 互异校验、机械图纸底线

> 这是 `solidworks-modeling` 的子技能。**不独立运行**，由根技能按需求路由调用。

## 入口

- AI 调用：`subskills/solidworks-engineering-drawing/SKILL.md`
- 依赖脚本在根技能 `scripts/` 下，本目录不复制代码

## 状态

`verified` — 本机 SW2022 SP5 实测。

## 能力

- `drawing.create` — 3 视图 + PDF（verified）
- `drawing.view_count` — 视图计数/枚举（verified，注意 Sheet1 +1 偏移）
- `drawing.sheet_size` — 图纸幅面读取（verified，走 `ISheet.GetSize` 两个 by-ref 出参）
- `drawing.annotations` — 自动标注（verified，`types` 必须含 32768）
- `drawing.standards_check` — 底线检查机器判部分（verified）
- `drawing.section` — 剖视图（pilot）
- `drawing.hole_table` / `drawing.title_block_fill` — **not_implemented**
- `export.png` / `export.step`

## 底线 5 条

示意图 ≠ 工程图；国标风格；引线不替代尺寸链；密集孔用孔表；交付前目视复核。
详见 `references/drawing-standards.md`。其中「尺寸链/孔表/标题栏/压线」四项无 API 判据，
`check_drawing()` 一律标 `manual`，整体 status 最多 `warn`。

## 三个最容易踩的坑

1. **同一张图纸只能插一次标注** —— 比较不同 `types` 必须每次新建图纸，
   否则测的是"这张图还能不能加"，不是"这个参数行不行"。
2. **`ISheet.GetProperties` 不能按位置取幅面** —— 返回 7 项，真幅面在索引 5/6，
   取 0/1 会得到 0×13000mm。用 `ISheet.GetSize`。
3. **孔表接口不可用** —— 51 组合全 None，与 `ThickenSheet` 同类，别再试。
