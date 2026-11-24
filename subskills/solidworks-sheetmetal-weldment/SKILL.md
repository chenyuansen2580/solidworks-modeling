---
name: solidworks-sheetmetal-weldment
description: "钣金基体法兰、结构件焊件、角钢型材、切割清单、折弯参数回读。本机 SW2022 实测，依赖根技能 solidworks-modeling 的脚本。"
metadata:
  parent: solidworks-modeling
  status: verified
  verified_on: "SOLIDWORKS 2022 SP5 (30.5.0.0049)"
---

# 钣金与焊件

## 何时调用

用户说：钣金 / 折弯 / 焊件 / 角钢 / 型材 / 机架

## 依赖根技能（不复制代码）

- `swlib_v2.py (sheetmetal_base_flange / structural_weldment / weldment_cut_list)`

## 能力边界

- 钣金必须走 FeatureData 路线，长参数接口 InsertSheetMetalBaseFlange2 已废弃
- 焊件三件套缺一不可：InsertWeldmentFeature + group + Groups SAFEARRAY
- 型材默认配置是 6 英寸，必须显式指定 config（如 1x0.75x0.125）
- 切割清单生成条件与型材总长有关，不稳定，维持 pilot

## 工作流

1. 选型材并查配置名（find_weldment_profiles + open_doc.GetConfigurationNames）
2. 路径草图 → structural_weldment(config=...)
3. body_counts 验多实体，体积校验
4. 存盘重开后读 weldment_cut_list（内存中不出现）

## 覆盖能力

- `part.sheetmetal_base_flange`
- `weldment.structural`
- `weldment.cut_list (pilot)`

## 参考

- `references/features.md 钣金/焊件章节`
- `references/pitfalls.md S8/S14 章`

## 交付门禁

- 几何断言通过（体积 / bbox / 实体数）
- 过程有 `exec_trace` 留痕
- 交付文件通过 `artifact_freshness` 校验
- 无法验证的项目记 BLOCKED，不写 PASS
