# -*- coding: utf-8 -*-
"""一次性探针：自动标注类型位掩码 + 孔表为什么插不进去。

不产出交付物，只打印证据。跑法：python probe_annotations.py

## 本探针解决的两个问题（2026-11-21）

### 1 自动标注：找到唯一可用的 types 位掩码

60×40×15 带两孔板，3 视图，逐组实测 `InsertModelAnnotations3`：

| types      | 组成                          | rc    | 标注增量 |
|------------|-------------------------------|-------|----------|
| 8          | swInsertDimensions            | False | 0        |
| 32768      | MarkedForDrawing              | False | 0        |
| 524288     | NotMarkedForDrawing           | False | 0        |
| **557056** | **32768 \\| 524288**          | **True** | **+1** |
| 557064     | 557056 \\| 8                  | False | 0        |
| 557078     | 557056 \\| 2 \\| 4 \\| 16      | False | 0        |

结论：必须**同时**声明两类尺寸，且**不能**叠加其它位。默认值已改为 `ANN_WORKING`。

### 2 孔表：本机 4 轮实测全部 None

试过：`InsertHoleTable3`(9参) / `InsertHoleTable2`(6参) / `InsertHoleTable`(5参)
× 3 个 `.sldholtbt` 模板（中英文 standard / sizes combined）
× anchor 0~3 × tagorder 0~1 × tagtype 0~2 × 5 组坐标（含官方示例的负 y）
× 视图选中方式（`SelectByID` 成功、`GetSelectedObjectsDrawingView2` 拿到对象）
→ **全部返回 None，标注总数恒 0**。

`IModelDoc2.SelectByID` 是能用的（5 参，没有 dispatch 参数，`sel=1` 验证通过）；
`SelectByID2` 在本机早绑定下 Callout 参数恒报"类型不匹配"。
所以孔表失败**不是选择集问题**，是接口层不可用 —— 与 `ThickenSheet` 同类。

## 顺带记录的坑

`AddDimension2` 会弹**尺寸编辑模态框**，不点掉就永久挂死 COM（实测卡 10 分钟+）。
要"带驱动尺寸的模型"，让特征自己产生尺寸（拉伸深度 D1 / 切除深度 D1）即可。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import swlib_v2 as V
import drawing_delivery as DD

OUT = os.path.join(HERE, "out", "probe_ann")
os.makedirs(OUT, exist_ok=True)

HOLE_TPL = (r"F:\SOLIDWORKS\lang\chinese-simplified\standard hole table--letters.sldholtbt",
            r"F:\SOLIDWORKS\lang\chinese-simplified\hole table--sizes combined--letters.sldholtbt",
            r"F:\SOLIDWORKS\lang\english\standard hole table--letters.sldholtbt")


def make_plate(sw, name="ann_plate"):
    """60x40x15 板 + 两个 Ø10 孔。特征自带驱动尺寸（拉伸/切除深度）。"""
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -30, -20, 30, 20)
        sk1 = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.extrude_checked(m, sk1, 15)

        V.L.new_sketch(m, "Top Plane")
        V.circle(skm, -15, 0, 5)
        V.circle(skm, 15, 0, 5)
        sk2 = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.cut_checked(m, sk2)
    p = os.path.join(OUT, name + ".SLDPRT")
    V.save_checked(m, p)
    return m, p


def probe_annotation_types(sw, part):
    """逐组试 types —— ★ 每个组合都必须用**全新图纸**。

    ★★★ 这是本探针最重要的方法论教训：
      同一张图纸上第二次调用 InsertModelAnnotations3 不会再加标注，
      于是"第二次之后的所有 types 都是 0 增量"。我最初在一张图上连试 8 组，
      错误地得出"只有 557056 能用"；改成每组新建图纸后，真相是
      **只要含 32768 位就成功**。
    """
    print("\n=== 1 自动标注 types 位掩码（每组新图纸）===")
    combos = [
        (8, "swInsertDimensions"),
        (32768, "MarkedForDrawing ★"),
        (524288, "NotMarkedForDrawing"),
        (32768 | 524288, "Marked|NotMarked"),
        (32768 | 8, "Marked|dims"),
        (32768 | 2, "Marked|datums"),
        (32768 | 4, "Marked|targets"),
        (32768 | 16, "Marked|counts"),
        (1737215, "全开"),
    ]
    good = []
    for types, label in combos:
        sw.CloseAllDocuments(True)
        try:
            V.open_doc(sw, part, 1)
        except Exception as e:
            print("  open ERR %s" % str(e)[:60])
        dw = sw.NewDocument(DD.find_template(), 0, 0, 0)
        for vn, x, y in (("*等轴测", 0.15, 0.13), ("*前视", 0.06, 0.05),
                         ("*上视", 0.06, 0.19)):
            V.drawing_view(dw, part, vn, x, y)
        V.wrap(dw, "IModelDoc2").ForceRebuild3(False)
        before = V.drawing_annotation_total(dw)
        try:
            rc = V.insert_model_annotations(dw, 0, types, True, False, False, False)
        except Exception as e:
            print("  types=%-9d %-20s ERR %s" % (types, label, str(e)[:50]))
            V.close_doc(sw, dw, force=True)
            continue
        after = V.drawing_annotation_total(dw)
        added = after - before
        print("  types=%-9d %-20s rc=%-6s before=%-2s after=%-2s 增量=%+d"
              % (types, label, rc, before, after, added))
        if added > 0:
            good.append((types, label))
        V.close_doc(sw, dw, force=True)
    has_bit = [t for t, _ in good if t & 32768]
    print("  → 成功的组合都含 32768 位: %s" % (len(has_bit) == len(good)))
    print("  → 可用 types: %s" % ", ".join(str(t) for t, _ in good))
    return good


def probe_hole_table(sw, dw, view):
    """孔表：4 种接口 × 3 模板 × 多组参数。"""
    print("\n=== 2 孔表（预期全部 None）===")
    nm = V.view_name_of(view)
    iv = V.wrap(view, "IView")
    d = V.wrap(dw, "IModelDoc2")

    # 选中视图：SelectByID 可用（5 参，无 dispatch 参数）
    V.wrap(dw, "IDrawingDoc").ActivateView(nm)
    ok = d.SelectByID(nm, "DRAWINGVIEW", 0.06, 0.05, 0)
    sm = V.wrap(dw, "IModelDoc2").SelectionManager
    print("  SelectByID=%s, 选中数=%s" % (ok, sm.GetSelectedObjectCount2(-1)))
    try:
        got = sm.GetSelectedObjectsDrawingView2(1, -1)
        print("  GetSelectedObjectsDrawingView2 → %s"
              % (V.view_name_of(V.wrap(got, "IView")) if got else None))
    except Exception as e:
        print("  GetSelectedObjectsDrawingView2 ERR %s" % str(e)[:60])

    tpl = next((t for t in HOLE_TPL if os.path.exists(t)), "")
    print("  模板: %s" % (os.path.basename(tpl) if tpl else "无"))

    results = []
    # ① InsertHoleTable3（9 参）
    for anchor in (0, 1, 2, 3):
        for tagorder in (0, 1):
            for tagtype in (0, 1):
                for (x, y) in ((0.153, -0.0377), (0.15, 0.15), (0.02, 0.02)):
                    try:
                        r = iv.InsertHoleTable3(False, x, y, anchor, "A", tpl,
                                                tagorder, tagtype, None)
                    except Exception as e:
                        r = "ERR:%s" % str(e)[:40]
                    results.append(("IHT3 a=%d o=%d t=%d" % (anchor, tagorder, tagtype),
                                    r))
    # ② InsertHoleTable2（6 参）
    try:
        results.append(("IHT2", iv.InsertHoleTable2(False, 0.15, 0.10, 0, "A", tpl)))
    except Exception as e:
        results.append(("IHT2", "ERR:%s" % str(e)[:40]))
    # ③ InsertHoleTable（5 参，官方 VBA 形态）
    try:
        results.append(("IHT5", iv.InsertHoleTable(False, 0.15, 0.10, 0, tpl)))
    except Exception as e:
        results.append(("IHT5", "ERR:%s" % str(e)[:40]))
    # ④ InsertTableAnnotation2（7 参，通用表）
    try:
        results.append(("ITA2", V.wrap(dw, "IDrawingDoc").InsertTableAnnotation2(
            False, 0.15, 0.10, 0, "", 3, 4)))
    except Exception as e:
        results.append(("ITA2", "ERR:%s" % str(e)[:40]))

    nones = sum(1 for _, r in results if r is None)
    print("  %d 种组合：None=%d, 非 None=%d"
          % (len(results), nones, len(results) - nones))
    for label, r in results:
        if r is not None:
            print("    非 None: %-24s %r" % (label, r))
    print("  标注总数: %s" % V.drawing_annotation_total(dw))
    print("  → 结论: 孔表接口在本机不可用（与 ThickenSheet 同类）")
    return results


def main():
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    try:
        sw.CloseAllDocuments(True)
    except Exception:
        pass
    m, part = make_plate(sw)
    good = probe_annotation_types(sw, part)

    # 单独建一张干净图纸做孔表
    sw.CloseAllDocuments(True)
    V.open_doc(sw, part, 1)
    dw2 = sw.NewDocument(DD.find_template(), 0, 0, 0)
    v = V.drawing_view(dw2, part, "*前视", 0.06, 0.05)
    V.wrap(dw2, "IModelDoc2").ForceRebuild3(False)
    probe_hole_table(sw, dw2, v)

    pdf = os.path.join(OUT, "probe.pdf")
    V.wrap(dw2, "IModelDoc2").SaveAs3(pdf, 0, 0)
    print("\nPDF: %d B" % (os.path.getsize(pdf) if os.path.exists(pdf) else 0))
    V.close_doc(sw, dw2, force=True)
    V.close_doc(sw, m, force=True)
    print("\n>>> PROBE DONE  可用 types: %s"
          % ", ".join(str(t) for t, _ in good))


if __name__ == "__main__":
    main()
