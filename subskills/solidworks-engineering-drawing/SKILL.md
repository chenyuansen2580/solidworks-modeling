---
name: solidworks-engineering-drawing
description: "零件图/装配图、四视图、PDF/BMP 证据、中文视图名、md5 互异校验、机械图纸底线（尺寸链/孔表/标题栏/压线）。本机 SW2022 实测，依赖根技能 solidworks-modeling 的脚本。"
metadata:
  parent: solidworks-modeling
  status: verified
  verified_on: "SOLIDWORKS 2022 SP5 (30.5.0.0049)"
---

# SolidWorks 工程图与出图

## 何时调用

用户说：出图 / 工程图 / 四视图 / 渲染图 / PDF / 导出图纸 / 图纸规范 / 能不能制造

## 依赖根技能（不复制代码）

- `swlib_v2.py (drawing_view / view_name_of / drawing_view_count / drawing_views /
  view_annotation_count / insert_model_annotations / set_view / save_png)`
- `drawing_delivery.py (create_drawing / check_drawing / render)`
- `review.py (run_review — 四视图像素判据)`
- `artifact_freshness.py (交付文件新鲜度)`

## 能力边界（★ 诚实分级）

| 项 | 等级 | 说明 |
|---|---|---|
| 3 视图 + PDF | **verified** | 3 视图 PDF 14759 B（含标注），`views_made==3` |
| 视图计数/枚举 | **verified** | `GetViewCount()` 含 Sheet1，3 视图返回 4 |
| 图纸幅面读取 | **verified** | `ISheet.GetSize` 两 by-ref 出参 → 279.4×215.9 mm |
| 自动标注 | **verified** | `types` 含 32768 → rc=True、增量 +1 |
| 四视图 PNG md5 互异 | **verified** | 比 md5 不比大小 |
| 底线检查（机器判部分） | **verified** | 视图数/PDF/幅面/标注增量四项 |
| 剖视图 | **pilot** | 已封装，需先画剖面线 |
| BOM 插表 | **pilot** | 数据能取，位置不可控 |
| 孔表/槽表 | **not_implemented** | 51 组合全 None，接口层不可用 |
| 标题栏字段填充 | **not_implemented** | 模板框线有，字段未填 |

## 机械图纸底线（5 条，详见 `references/drawing-standards.md`）

1. **示意图 ≠ 工程图**：涉及孔/槽/接口必须补外形尺寸、壁厚、孔槽规格和定位
2. **国标风格**：规范图幅/图框/标题栏、仿宋中文、分层线型、中心线/虚线、真实标注实体
3. **引线纪律**：长引线只做局部说明，不能替代尺寸链；不跨视图、不压孔/中心线/尺寸文字、不侵入标题栏
4. **密集孔槽用孔表**：表内写清部位、规格、数量、定位
5. **交付前目视复核**：漏标/重叠/压线/标题栏侵入先返工

★ 第 3、4 条和"尺寸链完整"**没有可靠 API 判据** → `check_drawing()` 标 `manual`，
整体 status 最多 `warn`，**绝不可能是 pass**。

## 工作流

```python
import swlib_v2 as V
import drawing_delivery as DD
import review as R

# 1 模型必须在会话里打开并激活（否则 CreateDrawView 恒 False / 标注 0 条）
# 2 出图 + 自动标注 + 导 PDF（一步到底，含底线检查）
rep = DD.create_drawing(sw, r"out\bracket.SLDPRT", r"out\bracket.pdf")
print(DD.render(rep))
# [OK  ] views / views_named / pdf_bytes
# [WARN] annotations    本轮增 0 条，但总数 2 条（模型自带，非本轮插入）
# [MAN ] dim_chain / hole_table / title_block / no_overlap

# 3 四视图 + 像素判据（防空白图/同图/裁切）
rv, path = R.run_review(m, r"out\review", basename="bracket",
                        expected_outputs=[r"out\bracket.SLDPRT", r"out\bracket.pdf"])

# 4 交付新鲜度
import artifact_freshness as F
base = F.scan(out); ...; F.require_fresh(base, out, [pdf, slddrw])
```

## 关键坑（全部本机实测，详见 `references/pitfalls.md` T 章）

| 坑 | 现象 | 修法 |
|---|---|---|
| 中文视图名 | 英文 `*Isometric` 恒返回 None | 用 `*等轴测/*前视/*上视` |
| `GetViewCount()` | 3 视图返回 **4** | 含 Sheet1，判据 `== views_made + 1` |
| `GetViews()` | 返回**嵌套元组** `((Sheet1, v1, v2),)` | 展平 + `GetName2()` 过滤 Sheet1 |
| `InsertModelAnnotations3` | 是 **6 参**不是 4 参 | 用 `V.insert_model_annotations` |
| `types` 位掩码 | 不含 32768 恒 0 条 | 用 `V.ANN_WORKING`（=32768） |
| **同一图纸只能插一次** | 重复调用不再加标注 | 比较参数须**每次新建图纸** |
| `ISheet.GetProperties` | 7 项，真幅面在索引 5/6 | 改用 `ISheet.GetSize` 两 by-ref 出参 |
| `SaveAs3` 冷启 | rc=1 + 0 字节 | `save_png` 内置 3 次重试 |

## 覆盖能力

- `drawing.create` / `drawing.view_count` / `drawing.sheet_size`
- `drawing.annotations` / `drawing.standards_check`
- `drawing.section`（pilot）
- `export.png` / `export.step`

## 参考

- `references/drawing-standards.md` — **底线 5 条 + 本机实测数据**
- `references/pitfalls.md` T3/T4/T5/T13/T15/T16/T17 章
- `scripts/probe_annotations.py` — 标注 types 与孔表的一次性探针
- `scripts/test_drawing_delivery.py` — 静态 5 + 真机 10 项断言

## 交付门禁

- [ ] 视图数 ≥3（注意 Sheet1 +1 偏移）
- [ ] PDF > 5KB 且是本轮新增（`artifact_freshness`）
- [ ] 四视图 md5 互异 + 非空白（`review.run_review`）
- [ ] 标注增量 >0，否则 WARN 并转人判
- [ ] **人眼**核对：尺寸链、孔槽定位、引线压线、标题栏字段
- [ ] 密集孔写孔表或附 CSV（当前 not_implemented）
- [ ] 无法验证的项目记 `manual`/`BLOCKED`，不写 PASS
