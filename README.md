# SolidWorks Modeling Skill

本机 SolidWorks 2022 全流程建模技能：需求规划 → 数学/齿廓 → COM 建模 → 装配配合 → 运动仿真 → 校核出图。

> 所有 API 签名、接口归属、参数顺序均基于 **SOLIDWORKS 2022 SP5 (30.5.0.0049)** 本机类型库实测。
> **不照抄 GitHub 上针对 SW2024/2026 的结论**。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![SolidWorks](https://img.shields.io/badge/SolidWorks-2022%20SP5-blue.svg)](SKILL.md)

## 环境要求

| 项 | 要求 | 说明 |
|---|---|---|
| 系统 | Windows 10/11 x64 | 原生 SLDPRT/SLDASM/SLDDRW 依赖 COM |
| CAD | SOLIDWORKS 2022 SP5 | ProgID `SldWorks.Application.30` |
| Python | 3.12 x64 + pywin32 | `pip install pywin32`；3.13 也可跑 |
| pyyaml | 可选 | 没有时 capabilities_loader 用内置 mini 解析器 |

## 能做什么

**建模（50 项 verified / 11 pilot / 5 not_implemented）**

- 基础特征：拉伸、切除（贯穿/盲孔）、旋转、放样、扫描、抽壳
- 修饰：圆角、倒角、圆周阵列、镜像、拔模等效
- 专用：钣金基体法兰、曲面（拉伸/平面/旋转）、结构件焊件、偏移基准面
- 专业：渐开线齿轮整环齿廓、谐波变形、样条
- 装配：bbox 摆位、固定、同心/距离/重合配合、干涉检查
- 出图：四视图、工程图、PDF、STEP、视图计数、图纸底线检查
- 外观：设色回读校验、批量上色
- 导入：STL/OBJ 网格参考件（含法线预检）

**四个机制（防假成功）**

- **交付新鲜度**：SHA-256 基线，旧文件不能冒充本轮成果
- **能力缺口**：不会的能力返回结构化替代方案 + 探测建议
- **执行 Trace**：每步留痕，失败带 `fail_at` 源码定位
- **结果自审查**：四视图 md5 + 像素判据，拦空白图/同图/裁切/0 字节

## 快速开始

```python
import sys; sys.path.insert(0, r"<SKILL_DIR>/scripts")
import swlib_v2 as V

sw = V.connect(version=2022)
m = V.new_part(sw)
with V.addtoDB(m) as skm:                 # 关 1mm 吸附
    V.L.new_sketch(m, "Front Plane")
    V.circle(skm, 0, 0, 25)               # 传圆周上一点，不是半径
    sk = V.last_sketch_name(m)
    skm.InsertSketch(True)
    V.extrude_checked(m, sk, 50)
V.volume_check(m, 3.14159265*25*25*50)
V.save_checked(m, r"C:\temp\cyl.SLDPRT")
```

## 自检

```bash
python scripts/run_all.py --static   # 约 3 秒，不开 SW ★ 每次改完先跑（11 项）
python scripts/run_all.py --quick    # 约 27 分钟，日常够用（11 静态 + 10 SW）
python scripts/run_all.py            # 约 40 分钟，全量（11 静态 + 15 SW）
python scripts/run_all.py --force    # 强制重跑
```

| 层 | 套件 |
|---|---|
| 静态 | compile / caps / gate / freshness / gap / docs / golden / apilookup / harmonic / planetary / trace(离线) |
| SW | smoke / features / draft / sheetmetal / props / surface / motion / assembly / doctest / capcheck / trace / review / appearance / drawing / mesh |

## 子技能

| 子技能 | 用途 |
|---|---|
| `solidworks-engineering-drawing` | 出图 / 四视图 / PDF |
| `solidworks-gears` | 齿轮 / 渐开线 / 齿廓 |
| `solidworks-sheetmetal-weldment` | 钣金 / 焊件 / 角钢 |
| `solidworks-assembly` | 装配 / 配合 / 干涉 |

详见 [SUBSKILLS.md](SUBSKILLS.md)。子技能只放文档，代码统一在根 `scripts/`。

## 单一真相源

- **[capabilities.yaml](capabilities.yaml)** — 76 项能力：等级 / 限制 / 依赖 / 版本 / 允许模式
- **[golden-workflows.yaml](golden-workflows.yaml)** — 9 个标准真机工作流：输入 / 产出 / 验收数值

代码从 yaml 加载，文档数字由 `test_doc_consistency.py` 校验，手写数字会红。

## 目录结构

```
SKILL.md                  主入口：8 条铁律 + 核心 API + 路由 + 门禁
SUBSKILLS.md              子技能矩阵
capabilities.yaml         能力清单（单一真相源）
golden-workflows.yaml     标准真机验收工作流
references/              12 个参考文档（211 条踩坑 / API / 图纸底线 / 案例 / 四机制）
scripts/                  41 个脚本（120+ 函数核心库 + 24 套件 + 四机制）
subskills/                4 个子技能 × 3 文件
assets/harmonic_profiles.json  谐波齿廓点集
```

## 八条铁律

1. **不猜 API** — 长参数方法先 python scripts/api_lookup.py 接口 方法
2. **不造轮子** — 先读 references/ 和 scripts/
3. **不瞎试** — 同一问题 2 次未通就查 pitfalls，再查 GitHub
4. **每步验证** — 判 None 不判真，体积+bbox+实体数三重断言
5. **先存后改** — 已保存文档改动前备份
6. **选择集 mark** — Select2(append, mark) 优先
7. **坐标映射** — 本机 Y 是上下，不是 Z
8. **装配一次成型** — 插入→摆位→固定→配合→出图→存盘，同一会话

## 已知限制

| 能力 | 现象 | 替代 |
|---|---|---|
| 孔向导 | 4 轮实测全 None | 普通贯穿/盲孔切除 |
| 曲面加厚 | ThickenSheet 恒 None | 实体拉伸或抽壳 |
| API 上色 | GetDisplayStateSetting 抛异常 | set_material / set_component_color |
| STL 导出 | COM 导 0 字节 | 先 STEP 再外部转 |
| 运动帧率 | 接口取不到 | 默认帧率 |

## License

MIT
