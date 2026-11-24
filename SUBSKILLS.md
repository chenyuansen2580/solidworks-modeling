# SolidWorks Modeling 子技能矩阵

> 组织方式参考 wzyn/solidworks-automation-skill 的 `SUBSKILLS.md`。
> 根技能 `solidworks-modeling` 提供连接、建模 API、门禁和出图；专项工作流放在 `subskills/`。

## 结构

```
solidworks-modeling/
├── SKILL.md                 根入口：铁律 + 核心 API + 路由 + 门禁
├── capabilities.yaml        单一真相源（76 项能力）
├── scripts/                 根技能脚本（不复制到子技能）
├── references/              全局踩坑 / API / workflow / 案例
└── subskills/
    ├── solidworks-engineering-drawing/   工程图与出图
    ├── solidworks-gears/                 渐开线齿轮
    ├── solidworks-sheetmetal-weldment/   钣金与焊件
    └── solidworks-assembly/              装配体与配合
```

每个子技能自包含：

```
subskills/<name>/
├── SKILL.md          AI 调用入口与工作流
├── README.md         人类阅读入口
└── manifest.yaml     索引元数据
```

**子技能只放文档，不复制根技能代码** —— 明确声明依赖 `scripts/` 下哪些脚本。

## 子技能索引

| 子技能 | 状态 | 用途 | 入口 |
|---|---|---|---|
| `solidworks-engineering-drawing` | verified | 零件图/装配图、四视图、PDF、中文视图名、md5 互异 | `subskills/solidworks-engineering-drawing/SKILL.md` |
| `solidworks-gears` | verified | 渐开线直齿轮、整环齿廓、同草图一次拉伸 | `subskills/solidworks-gears/SKILL.md` |
| `solidworks-sheetmetal-weldment` | verified | 钣金基体法兰、结构件焊件、角钢型材、切割清单 | `subskills/solidworks-sheetmetal-weldment/SKILL.md` |
| `solidworks-assembly` | verified | bbox 摆位、固定、配合、漂移检测、干涉 | `subskills/solidworks-assembly/SKILL.md` |

## 推荐路由

```
自然语言需求
  → 根 SKILL.md 判类型
  → 按关键词路由到子技能 SKILL.md
  → 子技能声明依赖根技能 scripts/swlib_v2.py 的哪些函数
  → 执行 → 几何断言 → trace 留痕 → freshness 门禁 → 交付
```

## 什么时候用哪个

### solidworks-engineering-drawing
用户说：**出图 / 工程图 / 四视图 / 渲染图 / PDF / 导出图纸**

关键：中文视图名、IDrawingDoc 宿主、ViewZoomout、md5 互异。

### solidworks-gears
用户说：**齿轮 / 渐开线 / 齿廓 / 齿数 / 模数**

关键：`mn/bw` 参数名、`full_ring` 拼整圈、中心孔同草图一次拉伸。

### solidworks-sheetmetal-weldment
用户说：**钣金 / 折弯 / 焊件 / 角钢 / 型材 / 机架**

关键：FeatureData 路线、焊件三件套、显式 config、切割清单存盘重开。

### solidworks-assembly
用户说：**装配 / 配合 / 摆位 / 干涉 / 装配体**

关键：**装配一次成型**、fix_all、place_to、局部坐标挑面、漂移检测。

## 目录规范

新增子技能时保持：

```
subskills/<name>/
├── SKILL.md         必需：AI 调用入口和工作流
├── README.md        必需：人类阅读入口
└── manifest.yaml    必需：索引元数据
```

可选（需要时再加）：`scripts/`、`references/`、`examples/`。
**默认不建** —— 代码统一放根技能 `scripts/`，避免重复维护。

## 质量门禁

每个子技能必须说明（已全部满足）：

- ✅ 适用场景和不适用场景
- ✅ 推荐调用根技能的哪些脚本
- ✅ 稳定策略和降级策略（能力边界）
- ✅ 输出文件和审查要求（交付门禁）
- ✅ 新踩坑沉淀到根技能 `references/pitfalls.md`（不散落在子技能）

## 约束

1. **子技能不复制根技能代码** —— 只引用
2. **子技能不写数字真相源** —— 等级/数字以 `capabilities.yaml` 为准
3. **子技能不新增独立门禁** —— 统一用 `verify_gate` / `artifact_freshness` / `exec_trace`
4. **新踩坑回写根技能 pitfalls.md** —— 保持单一知识库

## 自检

```bash
python scripts/test_doc_consistency.py     # 包含子技能 manifest 一致性
```
