# -*- coding: utf-8 -*-
"""工程图交付测试（视图数 / PDF / 标注回读 / 诚实边界）。

对标 wzyn 的「机械图纸默认底线 5 条」中**能机器判**的部分：

  1. 视图数 ≥3 —— 但 GetViewCount() 把 Sheet1 也算一项（3 视图返回 4）
  2. PDF > 5KB
  3. 自动标注回读：InsertModelAnnotations 返回 True 也可能 0 条
  4. 人判项必须显式标 manual，不能默认 pass
  5. 中文视图名（英文名恒 False）
  6. GetViews() 是嵌套元组，必须展平后按 GetName2 过滤

跑法：python test_drawing_delivery.py            静态 + SW
      python test_drawing_delivery.py --static   只跑静态
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import drawing_delivery as DD

OUT = os.path.join(HERE, "out", "dwg")
fails = []


def chk(name, fn):
    try:
        note = fn()
        print("  [OK] %-46s %s" % (name, note or ""))
    except AssertionError as e:
        print("  [XX] %-46s %s" % (name, e))
        fails.append(name)
    except Exception as e:
        print("  [XX] %-46s %s: %s" % (name, type(e).__name__, e))
        fails.append(name)


# ---------------------------------------------------------------- 静态
def t_template_exists():
    """模板必须找得到（中文界面要 gb.drwdot）。"""
    t = DD.find_template()
    assert t and os.path.exists(t), "找不到工程图模板"
    return os.path.basename(t)


def t_manual_items_not_pass():
    """★ 人判项必须标 manual，绝不能默认 pass。

    这是「无法验证 ≠ 通过」原则在工程图上的落地：
    尺寸链/孔表/标题栏/压线 全都没有可靠 API 判据。
    """
    rep = {"views_expected": 3, "views_made": 3,
           "view_names": ["v1", "v2", "v3"], "annotations_after": 2,
           "annotations_added": 2}
    checks = DD.check_drawing(None, None, None, rep=rep, min_pdf_bytes=0)
    manual = [c for c in checks if c["kind"] == "manual"]
    assert len(manual) == 4, "应有 4 项人判，实得 %d" % len(manual)
    for c in manual:
        assert c["status"] == "manual", "%s 应标 manual，实得 %s" % (c["id"], c["status"])
    ids = {c["id"] for c in manual}
    assert ids == {"dim_chain", "hole_table", "title_block", "no_overlap"}, ids
    return "4 项人判全部 manual"


def t_status_aggregation():
    """status 聚合：有 fail→fail；有 manual→warn；全 pass→pass。"""
    assert DD._status([{"status": "pass"}]) == "pass"
    assert DD._status([{"status": "pass"}, {"status": "manual"}]) == "warn"
    assert DD._status([{"status": "pass"}, {"status": "warn"}]) == "warn"
    assert DD._status([{"status": "manual"}, {"status": "fail"}]) == "fail"
    assert DD._status([]) == "pass", "空列表在 _status 层返回 pass（上层另有判据）"
    return "pass/warn/fail 聚合正确"


def t_pdf_threshold():
    """PDF 阈值生效：0 字节判 fail。"""
    rep = {"views_expected": 3, "views_made": 3, "view_names": ["a", "b", "c"],
           "annotations_after": 1}
    checks = DD.check_drawing(None, None, os.path.join(OUT, "nope.pdf"), rep=rep)
    pdf = [c for c in checks if c["id"] == "pdf_bytes"][0]
    assert pdf["status"] == "fail", pdf
    return "缺 PDF → fail"


def t_views_threshold():
    """视图数不足判 fail。"""
    rep = {"views_expected": 3, "views_made": 1, "view_names": ["a"],
           "annotations_after": 0}
    checks = DD.check_drawing(None, None, None, rep=rep)
    v = [c for c in checks if c["id"] == "views_named"][0]
    assert v["status"] == "fail", v
    return "只有 1 视图 → fail"


# ---------------------------------------------------------------- SW
def _make_plate(sw, name="dwg_plate"):
    """造一个 60×40×15 带两个 Ø10 孔的板，存盘。"""
    import swlib_v2 as V
    os.makedirs(OUT, exist_ok=True)
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -30, -20, 30, 20)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.extrude_checked(m, sk, 15)
        V.L.new_sketch(m, "Top Plane")
        V.circle(skm, -15, 0, 5)
        V.circle(skm, 15, 0, 5)
        sk2 = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.cut_checked(m, sk2)
    p = os.path.join(OUT, name + ".SLDPRT")
    V.save_checked(m, p)
    return m, p


def t_create_drawing():
    """★ 端到端：3 视图 + PDF >5KB。"""
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m, part = _make_plate(sw, "dwg_e2e")
    rep = DD.create_drawing(sw, part, os.path.join(OUT, "dwg_e2e.pdf"))
    print("       " + DD.render(rep).replace("\n", "\n       "))
    assert rep["views_made"] >= 3, "应建 ≥3 视图，实得 %s" % rep["views_made"]
    assert rep["pdf_bytes"] > DD.MIN_PDF_BYTES, \
        "PDF 应 >%d B，实得 %d" % (DD.MIN_PDF_BYTES, rep["pdf_bytes"])
    assert rep["status"] in ("pass", "warn"), "status 应为 pass/warn，实得 %s" % rep["status"]
    V.close_doc(sw, m, force=True)
    return "%d 视图 / PDF %d B / %s" % (rep["views_made"], rep["pdf_bytes"],
                                        rep["status"])


def t_viewcount_includes_sheet():
    """★ GetViewCount() 把 Sheet1 也算一项：3 视图 → 4。"""
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m, part = _make_plate(sw, "dwg_count")
    rep = DD.create_drawing(sw, part, os.path.join(OUT, "dwg_count.pdf"),
                            keep_open=True)
    dw = rep["drawing"]
    n = V.drawing_view_count(dw)
    print("       GetViewCount=%s, views_made=%s" % (n, rep["views_made"]))
    assert n == rep["views_made"] + 1, \
        "GetViewCount 应 = 视图数+1（含 Sheet1），实得 %s vs %s" % (n, rep["views_made"])
    V.close_doc(sw, dw, force=True)
    V.close_doc(sw, m, force=True)
    return "GetViewCount=%d = 视图 %d + Sheet1" % (n, rep["views_made"])


def t_getviews_nested():
    """★ GetViews() 返回嵌套元组，展平后第 0 项是 Sheet1。"""
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m, part = _make_plate(sw, "dwg_nested")
    rep = DD.create_drawing(sw, part, os.path.join(OUT, "dwg_nested.pdf"),
                            keep_open=True)
    dw = rep["drawing"]
    raw = V.wrap(dw, "IDrawingDoc").GetViews()
    assert isinstance(raw, tuple) and raw and isinstance(raw[0], tuple), \
        "GetViews 应是嵌套元组，实得 %r" % (type(raw),)
    views = V.drawing_views(dw)
    names = [V.view_name_of(v) for v in views]
    print("       raw 层数=%d, 展平后 %d 项: %s" % (len(raw), len(views), names))
    assert views, "展平后应有视图"
    assert any("Sheet" in (n or "") for n in names), \
        "应含 Sheet1（证明它被算进来了）: %s" % names
    assert len([n for n in names if n and "Sheet" not in n]) >= 3, \
        "应有 ≥3 个模型视图: %s" % names
    V.close_doc(sw, dw, force=True)
    V.close_doc(sw, m, force=True)
    return "%d 项（含 Sheet1）" % len(views)


def t_annotations_zero_is_warn():
    """★ 标注判据看**增量**，不看总数（模型自带标注会污染总数）。

    本机实测：60×40×15 带两孔的板，模型自带 2 条标注（孔中心标记），
    但 InsertModelAnnotations3 本轮 rc=False、增 0 —— 只看总数会误判 pass。
    """
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m, part = _make_plate(sw, "dwg_ann")
    rep = DD.create_drawing(sw, part, os.path.join(OUT, "dwg_ann.pdf"))
    ann = [c for c in rep["checks"] if c["id"] == "annotations"][0]
    print("       before=%s after=%s added=%s rc=%s → %s"
          % (rep["annotations_before"], rep["annotations_after"],
             rep["annotations_added"], rep["annotations_rc"], ann["status"]))
    if rep["annotations_added"] == 0:
        assert ann["status"] == "warn", \
            "增量 0 必须是 warn（即使总数 %s > 0）" % rep["annotations_after"]
        assert "非本轮插入" in ann["message"] or "增 0" in ann["message"], ann["message"]
    else:
        assert ann["status"] == "pass", ann
    V.close_doc(sw, m, force=True)
    return "增 %s / 总 %s → %s" % (rep["annotations_added"],
                                  rep["annotations_after"], ann["status"])


def t_english_view_fails():
    """★ 英文视图名在本机中文界面恒失败（pitfalls S9）。"""
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m, part = _make_plate(sw, "dwg_cn")
    tpl = DD.find_template()
    dw = sw.NewDocument(tpl, 0, 0, 0)
    v_en = V.drawing_view(dw, part, "*Isometric", 0.15, 0.13)
    v_cn = V.drawing_view(dw, part, "*等轴测", 0.15, 0.13)
    print("       英文 *Isometric → %r, 中文 *等轴测 → %r"
          % (v_en, V.view_name_of(v_cn) if v_cn else None))
    assert v_en is None, "英文视图名竟然成功了？pitfalls S9 需复核"
    assert v_cn is not None, "中文视图名应成功"
    V.close_doc(sw, dw, force=True)
    V.close_doc(sw, m, force=True)
    return "英文 None / 中文 %s" % V.view_name_of(v_cn)


def t_no_model_file_fails():
    """模型文件不在磁盘 → 直接抛（工程图必须先有文件）。"""
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    try:
        DD.create_drawing(sw, os.path.join(OUT, "no_such_model.SLDPRT"),
                          os.path.join(OUT, "x.pdf"))
    except RuntimeError as e:
        assert "不存在" in str(e), str(e)[:80]
        return "正确拒绝"
    raise AssertionError("缺模型文件应抛 RuntimeError")


def t_annotation_types_need_32768():
    """★★ 只要 types 含 32768 就成功；不含的一律 0 条。

    ★★★ 每组必须用**全新图纸**：同一张图重复调用不会再加标注（pitfalls T15）。
    这条测试本身就是那个陷阱的回归保护 —— 如果有人把循环改成复用一张图，
    除了第一组之外全部会变成 0，测试立刻红。
    """
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m, part = _make_plate(sw, "dwg_types")
    combos = [(8, False), (524288, False), (32768, True),
              (32768 | 524288, True), (32768 | 8, True)]
    results = []
    for types, expect_ok in combos:
        sw.CloseAllDocuments(True)
        V.open_doc(sw, part, 1)
        dw = sw.NewDocument(DD.find_template(), 0, 0, 0)
        v = V.drawing_view(dw, part, "*前视", 0.06, 0.05)
        V.wrap(dw, "IModelDoc2").ForceRebuild3(False)
        before = V.drawing_annotation_total(dw)
        rc = V.insert_model_annotations(dw, 0, types, True, False, False, False)
        after = V.drawing_annotation_total(dw)
        added = after - before
        results.append((types, added, rc))
        print("       types=%-7d added=%+d rc=%s" % (types, added, rc))
        assert (added > 0) == expect_ok, \
            "types=%d 期望 %s 但 added=%d" % (types, expect_ok, added)
        V.close_doc(sw, dw, force=True)
    # 所有成功的都含 32768
    ok_types = [t for t, a, _ in results if a > 0]
    assert all(t & 32768 for t in ok_types), ok_types
    return "%d/%d 组符合预期，成功者全含 32768" % (len(combos), len(combos))


def t_same_drawing_only_once():
    """★ 陷阱回归：同一张图第二次调用不会再加标注。

    这条**故意**验证"重复调用无效"这个行为本身 —— 它解释了为什么
    参数对比实验必须每次新建图纸。如果哪天 SW 行为变了（第二次也能加），
    这条会红，提醒我们重新审视 T15 的结论。
    """
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m, part = _make_plate(sw, "dwg_once")
    dw = sw.NewDocument(DD.find_template(), 0, 0, 0)
    v = V.drawing_view(dw, part, "*前视", 0.06, 0.05)
    V.wrap(dw, "IModelDoc2").ForceRebuild3(False)
    b0 = V.drawing_annotation_total(dw)
    V.insert_model_annotations(dw, 0, V.ANN_WORKING, True, False, False, False)
    a1 = V.drawing_annotation_total(dw)
    V.insert_model_annotations(dw, 0, V.ANN_WORKING, True, False, False, False)
    a2 = V.drawing_annotation_total(dw)
    print("       before=%s after1=%s after2=%s" % (b0, a1, a2))
    assert a1 > b0, "第一次应插进去"
    assert a2 == a1, "同一张图第二次不该再加（若变了要复核 pitfalls T15）"
    V.close_doc(sw, dw, force=True)
    V.close_doc(sw, m, force=True)
    return "第一次 +%d，第二次 +0（陷阱成立）" % (a1 - b0)


def t_hole_table_unavailable():
    """★ 孔表在本机不可用（51 组合全 None）—— 抽查 3 组确认维持 not_implemented。"""
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m, part = _make_plate(sw, "dwg_hole")
    dw = sw.NewDocument(DD.find_template(), 0, 0, 0)
    v = V.drawing_view(dw, part, "*前视", 0.06, 0.05)
    V.wrap(dw, "IModelDoc2").ForceRebuild3(False)
    nm = V.view_name_of(v)
    iv = V.wrap(v, "IView")
    d = V.wrap(dw, "IModelDoc2")
    V.wrap(dw, "IDrawingDoc").ActivateView(nm)
    sel = d.SelectByID(nm, "DRAWINGVIEW", 0.06, 0.05, 0)
    assert sel, "SelectByID 应能选中视图（证明不是选择集问题）"
    tpl = next((t for t in (
        r"F:\SOLIDWORKS\lang\chinese-simplified\standard hole table--letters.sldholtbt",
        r"F:\SOLIDWORKS\lang\english\standard hole table--letters.sldholtbt",
    ) if os.path.exists(t)), "")
    tries = []
    for anchor in (0, 1):
        try:
            r = iv.InsertHoleTable3(False, 0.15, 0.10, anchor, "A", tpl, 1, 1, None)
        except Exception as e:
            r = "ERR:%s" % str(e)[:30]
        tries.append(r)
    print("       SelectByID=%s  IHT3 → %s" % (sel, tries))
    assert all(r is None for r in tries), \
        "孔表竟然成功了？必须重新评估 not_implemented: %s" % (tries,)
    assert V.drawing_annotation_total(dw) == 0
    V.close_doc(sw, dw, force=True)
    V.close_doc(sw, m, force=True)
    return "选中视图后 2 组仍全 None"


def t_sheet_size_reads_real_mm():
    """★ 幅面必须走 ISheet.GetSize，且数值在合理区间。

    实测 GetProperties 返回 7 项 `(0.0, 13.0, 1.0, 1.0, 1.0, 0.2794, 0.2159)`，
    真幅面在索引 5/6；按位置取 0/1 会得到 **0 × 13000 mm** 这种荒谬值。
    """
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m, part = _make_plate(sw, "dwg_sheet")
    rep = DD.create_drawing(sw, part, os.path.join(OUT, "dwg_sheet.pdf"),
                            keep_open=True)
    sp = V.sheet_properties(rep["drawing"])
    print("       sheet: %.1f × %.1f mm  raw=%s"
          % (sp["width_mm"], sp["height_mm"], sp["raw"]))
    assert sp["width_mm"] and sp["height_mm"], "读不到幅面: %s" % sp
    # 合理区间：A4 210×297 到 A0 841×1189，也容纳 Letter/Legal
    assert 150 < sp["width_mm"] < 1300, "宽度不合理: %s" % sp["width_mm"]
    assert 150 < sp["height_mm"] < 1300, "高度不合理: %s" % sp["height_mm"]
    # 不能是 0（旧 bug 的典型症状）
    assert sp["width_mm"] > 0 and sp["height_mm"] > 0
    # 比例应为正数
    assert sp["scale_num"] and sp["scale_den"], sp
    # 幅面检查项也要进报告
    sz = [c for c in rep["checks"] if c["id"] == "sheet_size"]
    assert sz and sz[0]["status"] == "pass", sz
    V.close_doc(sw, rep["drawing"], force=True)
    V.close_doc(sw, m, force=True)
    return "%.1f × %.1f mm（%.2f × %.2f in）" % (
        sp["width_mm"], sp["height_mm"],
        sp["width_mm"] / 25.4, sp["height_mm"] / 25.4)


def main():
    static_only = "--static" in sys.argv
    print("=== drawing_delivery 套件 ===\n")
    print("-- 静态 --")
    chk("模板可用", t_template_exists)
    chk("★ 人判项标 manual", t_manual_items_not_pass)
    chk("status 聚合", t_status_aggregation)
    chk("PDF 阈值", t_pdf_threshold)
    chk("视图数阈值", t_views_threshold)

    if not static_only:
        print("\n-- 真机（SW2022 工程图）--")
        chk("★ 3 视图 + PDF", t_create_drawing)
        chk("★ GetViewCount 含 Sheet1", t_viewcount_includes_sheet)
        chk("★ GetViews 嵌套元组", t_getviews_nested)
        chk("★ 0 标注 → warn", t_annotations_zero_is_warn)
        chk("★ types 必须含 32768", t_annotation_types_need_32768)
        chk("★ 同一图纸只能插一次", t_same_drawing_only_once)
        chk("★ 幅面走 GetSize", t_sheet_size_reads_real_mm)
        chk("★ 孔表不可用", t_hole_table_unavailable)
        chk("★ 英文视图名恒失败", t_english_view_fails)
        chk("缺模型文件被拒", t_no_model_file_fails)

    print()
    if fails:
        print("失败 %d 项: %s" % (len(fails), fails))
        sys.exit(1)
    print("DRAWING DELIVERY PASS")


if __name__ == "__main__":
    main()
