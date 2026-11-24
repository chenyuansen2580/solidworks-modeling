# 交付新鲜度门禁

> 机制层第一个门禁。对标 wzyn20051216/solidworks-automation-skill（2230★）的
> `artifact_freshness`，只做能落地的最小闭环。

## 为什么需要它

**问题**：`REPORT.json` 只是汇总，不检查文件是不是本轮生成的。
上一轮的 14 件零件混进本轮交付，报告照样写着"14 件全部 0.000%"。

**这是「假成功」最常见的形态**：几何断言全过，但交付物是旧的。

## 判定规则

执行前记录 SHA-256 基线，执行后比对：

| producedThisRun | 证据 | 交付判断 |
|---|---|---|
| `true` | 基线里没有该文件（且基线完整覆盖其目录/扩展名） | 可进入后续检查 |
| `true` | 已记录文件 SHA-256 变化 | 可进入后续检查 |
| `false` | 内容与基线相同 | **拒绝作为本轮交付** |
| `false` | 只改了 mtime | **拒绝**（时间戳不算新） |
| `null` | 无基线 / 基线不完整 / 路径不在扫描范围 / 扩展名不支持 | **BLOCKED 待复核** |

**旧文件不能被新文件的通过结果掩盖**：逐项判定，任一项 FAIL 即整体 FAIL。

## 用法

```python
import artifact_freshness as F

# 1. 建模前打基线
base = F.scan(r"D:\proj\out")
base.save(r"D:\proj\.baseline.json")

# 2. ... 建模 / 导出 ...

# 3. 交付前硬门禁（任一文件非新增即抛 SystemExit）
F.require_fresh(base, r"D:\proj\out", paths=[
    r"D:\proj\out\parts\P1.SLDPRT",
    r"D:\proj\out\asm.SLDASM",
])
```

**跨进程**（推荐，建模脚本和校验脚本分开跑）：
```python
base = F.Baseline.load(r"D:\proj\.baseline.json")
rep = F.diff(base, out_dir, paths=deliverables)
```

**并入统一门禁**：
```python
from verify_gate import Gate
geo = Gate("geometry")
geo.check("volume", True, "dev 0.000%")

gf = F.to_gate(rep, "freshness")
merged = F.merge_gates([geo, gf], "delivery")
v = merged.verdict()      # 几何 PASS + 新鲜度 FAIL → FAIL
```

## 设计取舍

| 决策 | 理由 |
|---|---|
| **必须显式传 `paths`** | 传 None 会把目录里所有历史文件判成 OLD，噪声淹没结论。改为直接 BLOCKED 并报错 |
| **mtime 不算新** | 只改时间戳是伪造新鲜度最省事的方式 |
| **重新生成完全相同的字节也算旧** | SHA-256 无法区分，建议每轮用独立输出目录 |
| **基线不完整一律 BLOCKED** | 「无法验证 ≠ PASS」——这是 `verify_gate` 的核心思想 |
| **不支持的扩展名 → BLOCKED** | `.txt` 不在扫描模式里，不能凭"基线里没有"就断言它是新增 |

## 边界（重要）

**新鲜度只证明「文件新增或内容变了」，不证明：**

- 几何尺寸正确 → 用 `V.verify()` / `V.volume_check()`
- STEP 能被原生打开 → 需回读
- 工程图满足制造要求 → 需人工复核
- 装配无干涉 → 用 `V.interference_ok()`

**它必须和几何断言、目视复核一起用，不能单独当交付判据。**

## 测试

```bash
python scripts/test_freshness.py          # 11 项单元场景
python scripts/integrate_freshness.py     # 5 项真实项目集成
```

单元场景覆盖：
- 新文件 → true / 只改 mtime → false / 内容变化 → true
- 旧文件单独交付 → 拒
- **新文件不能掩盖旧文件**
- 基线不完整 → BLOCKED / 未声明清单 → BLOCKED / 不支持扩展名 → BLOCKED
- 基线存盘加载往返
- 接入 `verify_gate` / **几何 PASS + 新鲜度 FAIL → 整体 FAIL**

真实集成（belt_actuator）实测：
- 17 个上一轮交付文件 → **全部 OLD，拒绝**
- 新增 1 个 + 旧 13 个 → **整体 BLOCKED**
- 几何 PASS + 新鲜度 BLOCKED → **合并 FAIL**

## 与 wzyn 的差异

| 项 | wzyn（2230★） | 本实现 |
|---|---|---|
| 规模 | 完整 worker/ledger/queue 体系 | 单文件 300 行 |
| 基线来源 | worker 生成，执行器自报不可覆盖 | 调用方显式 `scan()` |
| 范围控制 | 扫描根 + 类型 + 完整性标记 + 截断标记 | 目录 + 扩展名模式 |
| 集成 | 内置在 CAD Studio 队列 | 可选并入 `verify_gate.Gate` |
| 测试 | 独立 pytest + 真机 live 脚本 | 11 单元 + 5 真实场景 |

**保留的核心**：SHA-256 基线、mtime 不算新、旧文件不可被掩盖、基线不完整即 BLOCKED。
**砍掉的**：worker/queue/ledger 那套多进程编排——单机 skill 用不上。
