# 钣金与焊件

钣金基体法兰、结构件焊件、角钢型材、切割清单、折弯参数回读

> 这是 `solidworks-modeling` 的子技能。**不独立运行**，由根技能按需求路由调用。

## 入口

- AI 调用：`subskills/solidworks-sheetmetal-weldment/SKILL.md`
- 依赖脚本在根技能 `scripts/` 下，本目录不复制代码

## 状态

`verified` — 本机 SW2022 SP5 实测。

## 能力

- `part.sheetmetal_base_flange`
- `weldment.structural`
- `weldment.cut_list (pilot)`
