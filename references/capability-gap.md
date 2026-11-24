# 能力缺口协议

> 机制层第二个门禁。对标 wzyn20051216/solidworks-automation-skill（2230★）的
> `CAPABILITY_GAP`。

## 为什么需要它

**旧行为**：`require_verified()` 直接 `raise RuntimeError("能力 X 等级=pilot，不能用")`。

调用方只知道「不行」，不知道：
- 有没有**近似能力**可以替代
- 该去 COM 上**探测**什么
- 该读哪份**文档**
- **下一步**做什么

结果两种：Agent 卡住，或者绕过门禁硬写然后静默失败。

## 协议

能力不够时不抛裸异常，返回 `CapabilityGap`：

| 字段 | 含义 |
|---|---|
| `requested` | 请求的能力名 |
| `kind` | 缺口类型：`unknown` / `pilot_only` / `not_implemented` / `blocked` |
| `level` / `note` | 当前等级与说明 |
| `alternatives` | **已登记的近似能力**，可直接改用 |
| `probe` | 建议去 COM 探测的 `(接口, 方法)` |
| `doc_hints` | 建议读的文档章节 |
| `next_steps` | 结构化 5 步：查证 → 探测 → 替代 → 最小实现 → 验证登记 |

## 用法

```python
import capability_gap as CG

# ① 软查询：拿 gap 而不是异常
gap = CG.probe_capability("part.hole_wizard")
if gap:
    print(gap.report())
    print(gap.to_json())          # 给 Agent 消费

# ② 硬门禁：verified 放行，否则抛结构化异常
CG.require("part.extrude")        # True
CG.require("part.hole_wizard")    # 抛 CapabilityGapError（带 .gap）

# ③ 候选回退：任一 verified 即过
CG.require_any(["part.hole_wizard", "part.cut_through"])
#   → 返回 "part.cut_through"

# ④ COM 探测（写最小实现阶段用）
CG.com_has(sw, "IFeatureManager", "HoleWizard5")        # True
CG.com_signature(sw, "IFeatureManager", "HoleWizard5")  # 27
CG.probe_all(sw, gap)          # [(接口, 成员, 是否存在)]
```

### 与旧接口的关系

`swlib_v2.require_verified()` 已升级为抛 `CapabilityGapError`，
但它**继承 RuntimeError**，旧的 `except RuntimeError` 仍能捕获 —— 向后兼容。

```python
V.require_verified("part.extrude")      # True
try:
    V.require_verified("part.hole_wizard")
except RuntimeError as e:                # 仍然能捕获
    print(e.gap.to_json())               # 多了结构化信息

V.capability_gap("surface.thicken")      # 软查询，verified 返回 None
```

## 缺口类型的处理方式

| kind | 含义 | Agent 该做什么 |
|---|---|---|
| `unknown` | 完全没登记 | 按 next_steps 查文档 → 探 COM → 最小实现 → 验证后登记 |
| `pilot_only` | 登记了但只到 pilot | 先用 `alternatives` 里的 verified 替代；非要用则人工复核 |
| `not_implemented` | 明确不可用 | 直接用替代方案，别浪费时间 |
| `blocked` | 本机环境不允许 | 用替代方案或换环境 |

## 替代方案表（关键）

**每个 pilot / not_implemented 能力都必须有替代方案** —— 否则 Agent 拿到 gap 会卡住。
这条已写成测试断言 `t_all_pilot_have_alternatives`，缺一个就红。

| 请求 | 替代 | 说明 |
|---|---|---|
| `part.hole_wizard` | `part.cut_through` / `part.cut_blind` | 普通切除，已验证 0.000% |
| `part.thread` | `part.cut_blind` | 螺纹孔用盲孔+装饰螺纹线 |
| `surface.thicken` | `part.extrude` / `part.shell` | 薄壁实体直接拉伸或抽壳 |
| `export.stl` | `export.step` | 先 STEP 再外部转 |
| `asm.mate.axis_concentric` | `asm.mate.concentric` / `asm.mate.plane_coincident` | 面同心代替轴同心 |
| `appearance.render` | `appearance.component` / `material.set` | 组件上色或材料驱动 |
| `appearance.display_color` | `appearance.component` / `material.set` | API 上色本机不可用 |
| `weldment.cut_list` | `weldment.structural` / `props.custom` | 切割清单缺失时手数特征树 |
| `motion.results` / `motion.avi` | `motion.study` | 算例+计算已验证，其余界面做 |
| `export.sldprt_to_web` | `export.step` | 先 STEP 再转 glTF |

## 设计取舍

| 决策 | 理由 |
|---|---|
| **不抛裸异常** | 裸异常只给「不行」，结构化 gap 给「怎么办」 |
| **替代方案必须是 verified** | 否则引导 Agent 踩坑。已写成断言 `t_gap_guides_to_real_verified` |
| **每个 pilot 都要有替代** | 已写成断言，缺一个就红 |
| **next_steps 固定 5 步** | 查证 → 探测 → 替代 → 最小实现 → 验证登记，顺序不能变 |
| **兼容旧 RuntimeError** | 不让已写好的 `except RuntimeError` 失效 |

## 测试

```bash
python scripts/test_capability_gap.py     # 12 项
```

覆盖：
- verified 无 gap / unknown 有完整指引 / pilot 与 not_impl 类型判定
- require 放行 verified / require 抛结构化异常 / require_any 候选回退
- JSON 可序列化 / report 可读
- **★ 所有 pilot/not_impl 都有替代方案**（缺一个就红）
- **★ 替代方案指向真 verified**（防止引导踩坑）
- **真实 COM 探测**：`HoleWizard5` 存在且 27 参、编造方法探测不到

## 与 wzyn 的差异

| 项 | wzyn | 本实现 |
|---|---|---|
| 触发方式 | Execution Core 内部路由 | 调用方显式 `probe_capability` / `require` |
| 替代方案 | 工具组合 + backend fallback | 静态 `ALTERNATIVES` 表 |
| 探测 | signature discovery 运行时跑 | `com_has` / `com_signature` 按需探 |
| 登记 | `capabilities.yaml` | `CAPABILITIES` 字典 + 测试守门 |

**保留核心**：缺口结构化返回、替代方案、探测建议、5 步后续。
**砍掉**：backend router / 自动 fallback 编排 —— 单机 skill 用不上。
