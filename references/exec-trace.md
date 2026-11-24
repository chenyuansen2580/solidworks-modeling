# 执行 Trace

> 机制层第三个门禁。对标 wzyn20051216/solidworks-automation-skill（2230★）的 Execution Trace。

## 为什么需要它

前两个机制管**交付物**（新鲜度）和**能力**（缺口），但**过程没有留痕**：

- 建模跑到第 7 步失败，只知道"失败了"，不知道前 6 步做了什么
- 体积对不上，不知道是哪一步引入的偏差
- 交付报告只有结论，没有「怎么得出的」

结果是**不可审计、不可回放、失败不可定位**。

## 设计

```
Trace
  ├─ env     环境（SW 版本、Python、模板路径）
  ├─ steps   [Step, ...]
  └─ verdict OK / FAIL / BLOCKED

Step
  ├─ seq        序号
  ├─ name       步骤名（如 "P1.extrude"）
  ├─ kind       build / verify / export / gate / note
  ├─ status     ok / fail / skip / blocked
  ├─ t0 / t1    起止时间（相对任务开始）
  ├─ inputs     关键入参
  ├─ outputs    关键产出（实测体积、实体数）
  ├─ evidence   证据（偏差%、bbox、失败位置）
  ├─ error      失败时的异常文本
  └─ duration   耗时
```

## 用法

```python
import exec_trace as ET

tr = ET.Trace("belt_actuator")
tr.env(sw_version="30.5.0", python="3.12.4")

with tr.step("P1.extrude", kind=ET.KIND_BUILD, depth=600) as s:
    V.extrude_checked(m, sk, 600)
    s.output("volume", V.volume_mm3(m))       # 记产出
    s.ev("dev_pct", 0.000)                    # 记证据

with tr.step("P1.verify", kind=ET.KIND_VERIFY) as s:
    ok, got, dev = V.volume_check(m, theory)
    s.output("measured", round(got, 2))
    s.ev("dev_pct", round(dev, 4))
    assert ok                                # 失败自动记 fail

tr.save(r"out\trace.json")
print(tr.report())
tr.require_ok()          # 有 fail 就抛 SystemExit
```

### 报告长什么样

```
=== 执行 Trace: selftest ===
  环境: sw=2022 SP5, python=3.12
  #    步骤                             状态     耗时       证据
  ----------------------------------------------------------------------------
  1    step1                          [OK ]   0.00s dev_pct=0.0
  2    step2                          [OK ]   0.00s bodies=1
  3    note1                          [OK ]   0.00s key=value
  4    step3                          [-- ]   0.00s  | 不需要
  5    step_fail                      [XX ]   0.00s fail_at=exec_trace.py:314 | ValueError: 模拟失败
  ----------------------------------------------------------------------------
  verdict: FAIL   步骤 5  耗时 0.0s
  失败: step_fail
```

**失败步骤带 `fail_at=file:line`** —— 这是定位的关键，不用猜是哪一行崩的。

## 关键设计

| 决策 | 理由 |
|---|---|
| **不自动 hook COM** | 自动 hook 会让日志爆炸且难读；显式声明反而更可读 |
| **异常不吞** | step 记 fail，异常继续向上抛 —— 不能因为记了日志就当没事 |
| **记 `fail_at`** | 从 traceback 取最后一帧，`file:line` 格式 |
| **空 trace = BLOCKED** | 「无法验证 ≠ PASS」 |
| **skip / note 不影响成败** | 跳过的步骤和纯记录不该拖垮整体 |
| **`ev()` 不是 `evidence()`** | `evidence` 是字段名，同名方法会冲突（踩过） |

## 与另外两个机制的关系

| 机制 | 管什么 | 输出 |
|---|---|---|
| **交付新鲜度** | 交付物是不是本轮生成的 | `FreshnessReport` |
| **能力缺口协议** | 不会的时候怎么办 | `CapabilityGap` |
| **执行 Trace** | 每一步做了什么、凭什么过 | `Trace`（steps 列表） |

- `Gate` 判「这一项过没过」—— 结论
- `Trace` 记「这一步做了什么」—— 过程

**三者互补**：Gate 是结论，Trace 是过程，Freshness 是交付物真实性。

## 测试

```bash
python scripts/test_exec_trace.py     # 10 项
```

覆盖：
- 基础记录（inputs/outputs/evidence/seq）
- **★ 失败记录且不吞异常**
- 空 trace → BLOCKED
- skip / note 不影响成败
- summary / verdict
- 序列化往返（存盘 → 加载 → 信息不丢）
- JSON 合法
- `timed` 辅助函数
- `require_ok` 硬门禁
- **★ 真实建模 trace**：拉伸 → 体积校验 → 实体数 → 故意失败，实测
  `volume=98174.77`、`dev=0.0000%`、`fail_at=test_exec_trace.py:211`

## 实际价值

真实建模跑一次 trace，出问题时能立刻回答：

1. **哪一步失败** → `fail_at` 给出文件行号
2. **前一步产出什么** → `outputs` 有体积/实体数
3. **偏差从哪步引入** → 逐 step 的 `dev_pct` 一比就知道
4. **耗时在哪** → `duration` 列

**这就是「可审计」的实际含义**：不是多写日志，是让失败可定位。

## 与 wzyn 的差异

| 项 | wzyn | 本实现 |
|---|---|---|
| 粒度 | Execution Core 内部自动 trace | 调用方显式 `with tr.step()` |
| 存储 | 内部 state + ledger | JSON 文件 |
| 回放 | 有 replay 机制 | 只记录，回放需自己按 steps 重跑 |
| 规模 | 完整 execution core | 单文件 12 KB |

**保留核心**：每步留痕、失败定位、可序列化、空 trace 即 BLOCKED。
**砍掉**：自动 hook、replay 引擎 —— 单机 skill 用不上，显式声明更可控。
