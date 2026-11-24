# 装配体与配合

bbox 摆位、全部固定、同心/距离/重合配合、漂移检测、干涉检查

> 这是 `solidworks-modeling` 的子技能。**不独立运行**，由根技能按需求路由调用。

## 入口

- AI 调用：`subskills/solidworks-assembly/SKILL.md`
- 依赖脚本在根技能 `scripts/` 下，本目录不复制代码

## 状态

`verified` — 本机 SW2022 SP5 实测。

## 能力

- `asm.insert`
- `asm.place`
- `asm.fix`
- `asm.mate.*`
- `export.step`
