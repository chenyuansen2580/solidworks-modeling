# 工程图底线（机械图纸交付规范，本机 SW2022 实测）

> 对标 wzyn20051216/solidworks-automation-skill（2230★）的「机械图纸默认底线 5 条」。
> **本文档写底线，`scripts/drawing_delivery.py` 只做能机器判的那部分。**
> 判不了的一律显式标 `manual`，绝不默认 PASS。

---

## 一、五条底线

### 1. 「看得懂的示意图」≠「能制造的工程图」

预览图看着像零件，不代表车间能照着做。凡涉及**孔 / 槽 / 接口**，必须补齐：

| 缺什么 | 车间会怎么错 |
|---|---|
| 外形总尺寸 | 下料尺寸靠猜，余量全凭经验 |
| 壁厚 | 用错板料，强度不够 |
| 孔/槽规格（Ø、深、沉孔、螺纹） | 钻错刀具 |
| 孔/槽定位（到边/到中心/孔距） | 装不上，位置全偏 |
| 基准（哪个面是 A 基准） | 无法测量，公差无意义 |

**自检话术**：把图给一个没参与建模的人，问他「这块料下多大、几个孔、孔在哪」——
答不上来就是示意图。

### 2. 国标风格

| 项 | 要求 | 本机做法 |
|---|---|---|
| 图幅/图框 | A0~A4 标准幅面，留装订边 | `gb.drwdot` 模板自带 |
| 标题栏 | 右下角，含件号/名称/材料/比例/日期/设计审核 | 模板自带框线，**字段填充未验证** |
| 字体 | 中文仿宋，数字字母按 GB 长仿宋 | 模板默认（`doc_font` 未改，pilot） |
| 线型分层 | 粗实线（可见轮廓）/ 细实线（尺寸线）/ 虚线（不可见）/ 点划线（中心线） | SW 默认图层，**未自定义** |
| 中心线 | 回转体、孔组必须画 | 自动标注 `swInsertAxes` 可插轴线，但位置不可控（pilot） |
| 虚线 | 不可见轮廓 | 视图属性控制，未端到端验证 |

**结论**：图框/标题栏框线由模板保证（verified），字体与线型的**规范符合性**未验证（pilot）。

### 3. 引线/标注的摆放纪律

- 长引线**只做局部说明**（倒角、表面处理、特殊要求），**不能替代尺寸链**
- 不得跨视图引线
- 不得压孔、压中心线、压尺寸文字
- 不得侵入标题栏区域

**这四条全部无可靠 API 判据** → `drawing_delivery.check_drawing()` 里标 `manual`。
唯一能自动做的是**目视复核预览图**（见第 5 条）。

### 4. 密集孔槽优先用孔表/槽表

同一面上 ≥4 个同类孔时，逐个标注会挤成一团。规范做法是孔表：

| 部位 | 规格 | 数量 | 定位 |
|---|---|---|---|
| 底板 | Ø6.6 通孔 | 8 | 距边 10，孔距 40×60 |

**本机状态**：`bom.table_insert` 与孔表**均未实现**（pilot / not_implemented）。
变通：把孔规格/数量写进**自定义属性**（`props.custom` 已验证），交付时附 CSV。
`references/capability-gap.md` 里有替代路径。

### 5. 交付前必须目视复核

`InsertModelAnnotations3` 返回 `True` 也可能**一条都没插**（本机实测：
`InsertModelAnnotations2` 返回 True、标注数 0，因为模型没有驱动尺寸）。
所以交付前必做：

```python
import review as RV
rep, path = RV.run_review(m, out_dir, basename="bracket",
                          expected_outputs=[part, pdf])
```

`review` 能自动拦掉：空白图、四视图同一张、内容被裁切、PDF 空文件。
**拦不掉**：漏标、标错、重叠、压线、标题栏侵入 —— 这些只能人眼看。

---

## 二、本机实测做法（`drawing_delivery.py`）

```python
import drawing_delivery as DD

rep = DD.create_drawing(sw, r"out\bracket.SLDPRT", r"out\bracket.pdf")
print(DD.render(rep))
# 视图: 期望 3 / 实得 3  (工程图视图1,工程图视图2,工程图视图3)
# 标注: 前 0 → 后 0（增 0）
# [OK  ] views          4 个视图（下限 3）
# [OK  ] views_named    3 个具名视图
# [OK  ] pdf_bytes      7132 B（下限 5000 B）
# [WARN] annotations    标注 0 条（增量 0）
# [MAN ] dim_chain      尺寸链完整度须人眼核对
# [MAN ] hole_table     孔表/槽表未实现（pilot）
# [MAN ] title_block    标题栏字段是否填全须人眼核对
# [MAN ] no_overlap     引线是否跨视图/压孔/侵入标题栏须人眼核对
```

### 关键实测数据（2026-11-21，60×40×15 带两孔板）

| 项 | 值 | 说明 |
|---|---|---|
| `GetViewCount()` | **4** | 3 个模型视图 + 1 个 Sheet1（图纸本身也算一项！） |
| `GetViews()` 返回 | `((Sheet1, 视图1, 视图2, 视图3),)` | **嵌套元组**，第 0 项是 ISheet 不是 IView |
| `GetName2()` | `工程图视图1/2/3` | 中文界面 |
| PDF 字节（无标注） | 7130 | 3 视图 |
| PDF 字节（有标注） | **14759** | 插进 1 条尺寸后翻倍 |
| `InsertModelAnnotations3(0, 32768, True, ...)` | **True** | ★ 增量 +1 |
| `InsertModelAnnotations3(0, 8, ...)` | False | 增量 0（不含 32768 位） |
| `InsertHoleTable3`（51 组合） | **全部 None** | 接口不可用 |

### 四条踩过的坑

1. **`GetViews()` 是嵌套元组** —— 直接 `for v in arr` 拿到的是元组，
   `wrap(v,'IView')` 后所有成员报 `'tuple' object has no attribute`。
   必须先展平，再用 `GetName2()` 过滤掉 Sheet1。

2. **`GetViewCount()` 把图纸算进去** —— 3 视图返回 4。判据用 `>=3` 时要知道这个偏移，
   否则「只有 1 个视图」也会因为 +1 通过。

3. **`InsertModelAnnotations3` 6 参，`types` 必须含 32768** ——
   旧文档写 4 参（`Option, Types, AllViews, DuplicateDims`）是错的。用 `api_lookup.py` 查：

   ```bash
   python api_lookup.py IDrawingDoc InsertModelAnnotations3
   # → (Option, Types, AllViews, DuplicateDims, HiddenFeatureDims, UsePlacementInSketch)
   ```

   **返回 True 不代表插进去**：唯一可信判据是 `IView.GetAnnotationCount()` 的**增量**。

4. **★★ 同一张图纸只能插一次标注** —— 这是本轮最贵的教训。
   在一张图上连试 8 组 `types`，得到"只有 32768|524288 能用"的结论；
   改成**每组新建图纸**后真相是"只要含 32768 就成功"。
   第一次成功插入后，这张图的"可导入尺寸"已被消费，
   后续调用测的是"这张图还能不能加"，不是"这个参数行不行"。

### 孔表：51 组合实测全部失败

`InsertHoleTable3`(9参) / `InsertHoleTable2`(6参) / `InsertHoleTable`(5参) /
`InsertTableAnnotation2`(7参) × 3 个 `.sldholtbt` 模板 × anchor 0~3 × tagorder 0~1
× tagtype 0~2 × 5 组坐标 → **全部 None，标注总数恒 0**。

已排除选择集问题：`SelectByID` 选中成功（`sel=1`）、
`GetSelectedObjectsDrawingView2` 能拿到 IView 对象。
结论：接口层不可用，与 `ThickenSheet` 同类。维持 `not_implemented`。

★ 顺带：`SelectByID2` 的 Callout 参数（第 8 位 VT_DISPATCH）在本机早绑定下
恒报"类型不匹配"；改用 `IModelDoc2.SelectByID`（5 参，无 dispatch 参数）可正常选中。

---

## 三、能力等级（诚实标注）

| 能力 id | 等级 | 依据 |
|---|---|---|
| `drawing.create` | verified | 3 视图 + PDF 14759 B，`views_made==3` |
| `drawing.view_count` | verified | `GetViewCount()` 返回 4（含 Sheet1），多次一致 |
| `drawing.annotations` | **verified** | `types` 含 32768 → rc=True、增量 +1、PDF 7130→14759 |
| `drawing.standards_check` | verified | 4 项人判全标 manual，status 聚合正确 |
| `drawing.section` | pilot | 已封装，需先画剖面线，未端到端实测 |
| `bom.table_insert` | pilot | 数据能取，位置不可控 |
| `drawing.hole_table` | **not_implemented** | 51 组合全 None，接口层不可用 |
| `drawing.title_block_fill` | **not_implemented** | 模板框线有，字段未填 |

**绝不写**：`drawing.hole_table` 可用。它是 not_implemented —— 与 `ThickenSheet` 同类，
接口层不可用，不是用法问题。

---

## 四、交付清单（工程图部分）

- [ ] 视图数 ≥3（`drawing_view_count() >= 3`，注意 Sheet1 偏移）
- [ ] 每个视图 `GetName2()` 非空
- [ ] PDF > 5KB 且非本轮之前的旧文件（`artifact_freshness`）
- [ ] 自动标注条数 >0（`drawing_annotation_total()`），否则 WARN 并转人判
- [ ] 四视图 PNG md5 互异 + 非空白（`review.run_review`）
- [ ] **人眼**核对：尺寸链、孔槽定位、引线压线、标题栏字段
- [ ] 密集孔写孔表或附 CSV（当前 pilot）
- [ ] 用到的能力都是 verified，pilot 项在报告里显式声明
