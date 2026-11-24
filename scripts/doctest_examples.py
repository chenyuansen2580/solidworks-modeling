# -*- coding: utf-8 -*-
"""验证 SKILL.md 里的示例代码能真跑（不是纸面正确）"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pythoncom          # noqa: E402
import swlib_v2 as V      # noqa: E402

OUT = os.path.join(HERE, "out", "doctest")
os.makedirs(OUT, exist_ok=True)

pythoncom.CoInitialize()
sw = V.connect(version=2022, verbose=False, warn_multi=False, wait_ready=30)

fails = []


def chk(name, fn):
    try:
        fn()
        print("  [OK] %s" % name)
    except Exception as e:
        print("  [XX] %-40s %s" % (name, str(e)[:70]))
        fails.append(name)


# ---------------- 1 快速开始：圆柱
def t_quickstart():
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Front Plane")
        V.circle(skm, 0, 0, 25)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.extrude_checked(m, sk, 50)
    ok, got, dev = V.volume_check(m, 3.14159265 * 25 * 25 * 50)
    assert ok, "体积偏差 %.3f%%" % dev
    V.save_checked(m, os.path.join(OUT, "cyl.SLDPRT"))
    V.close_doc(sw, m, force=True)


# ---------------- 2 旋转示例（SKILL 里的中心线写法）
def t_revolve():
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Front Plane")
        V.L.rect(skm, 0, -25, 25, 25)
        skm.CreateCenterLine(0, -0.03, 0, 0, 0.03, 0)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.revolve_checked(m, sk, 360)
    v = V.volume_mm3(m)
    assert v > 0, "旋转体积 0"
    V.close_doc(sw, m, force=True)


# ---------------- 3 偏移基准面命名（新封装）
def t_offset_named():
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -20, -20, 20, 20)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.extrude_checked(m, sk, 10)
    nm = V.offset_plane_named(m, "Top Plane", 40)
    assert nm, "取不到平面名"
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, nm)
        V.circle(skm, 0, 0, 8)
        sk2 = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.loft_checked(m, [sk, sk2])
    V.close_doc(sw, m, force=True)


# ---------------- 4 faces_of / plane_at / cyl_of（新封装）
def t_faces_api():
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -30, -20, 30, 20)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.extrude_checked(m, sk, 10)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.circle(skm, 0, 0, 6)
        sk2 = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.cut_checked(m, sk2, None)

    # 用零件本身当"组件"喂给 faces_of 不行 —— 需要 IComponent2
    # 这里改用底层：直接验证 plane_at / cyl_of 的纯函数逻辑
    fake = [
        dict(f="P1", plane=True, cyl=False, box=[0, 10, 0, 60, 10, 40],
             dims=[60, 0, 40], n=(0.0, 1.0, 0.0), area=2400),
        dict(f="P2", plane=True, cyl=False, box=[0, 0, 0, 60, 0, 40],
             dims=[60, 0, 40], n=(0.0, 1.0, 0.0), area=2400),
        dict(f="C1", plane=False, cyl=True, box=[-6, 0, -6, 6, 10, 6],
             dims=[12, 10, 12], n=None, area=377),
    ]
    f = V.plane_at(fake, "y", None, 10.0)
    assert f == "P1", "plane_at 挑错: %s" % f
    f = V.plane_at(fake, "y", None, 0.0)
    assert f == "P2", "plane_at 挑错: %s" % f
    f = V.cyl_of(fake, 12.0)
    assert f == "C1", "cyl_of 挑错: %s" % f
    f = V.cyl_of(fake, 99.0)
    assert f is None, "cyl_of 应返回 None"
    V.close_doc(sw, m, force=True)


# ---------------- 5 place_to / all_boxes / max_drift / fix_all
def t_assembly_api():
    # 建两个小件
    paths = []
    for i, (w, h, d) in enumerate(((40, 20, 10), (20, 20, 20))):
        m = V.new_part(sw)
        with V.addtoDB(m) as skm:
            V.L.new_sketch(m, "Top Plane")
            V.L.rect(skm, -w / 2, -h / 2, w / 2, h / 2)
            sk = V.last_sketch_name(m)
            skm.InsertSketch(True)
        V.extrude_checked(m, sk, d)
        p = os.path.join(OUT, "blk%d.SLDPRT" % i)
        V.save_checked(m, p)
        paths.append(p)
        V.close_doc(sw, m, force=True)

    asm = V.new_asm(sw)
    title = V.com_member(V.wrap(asm, "IModelDoc2"), "GetTitle")
    c1 = V.add_component(sw, asm, title, paths[0])
    got = V.place_to(sw, c1, V.rot_z(0), (0, 0, 0))
    assert max(abs(x) for x in got[:3]) < 0.1, "place_to 未收敛 %s" % got
    c2 = V.add_component(sw, asm, title, paths[1])
    V.place_to(sw, c2, V.rot_z(0), (50, 0, 0))

    n = V.fix_all(asm)
    assert n == 2, "fix_all 只固定 %d" % n

    b0 = V.all_boxes(asm)
    assert len(b0) == 2, "all_boxes 返回 %d" % len(b0)
    d = V.max_drift(b0, V.all_boxes(asm))
    assert d < 0.01, "max_drift 应为 0，实得 %.3f" % d

    ok, raw = V.interference_ok(asm)
    assert ok, "干涉检查失败: %s" % (raw,)

    V.save_checked(asm, os.path.join(OUT, "asm2.SLDASM"))
    V.close_doc(sw, asm, force=True)


# ---------------- 6 出图示例（ViewZoomout 那条）
def t_views():
    m = V.open_doc(sw, os.path.join(OUT, "blk0.SLDPRT"), doc_type=1, activate=True)
    d = V.wrap(m, "IModelDoc2")
    hs = set()
    import hashlib
    for v in ("iso", "front", "top", "right"):
        p = os.path.join(OUT, "v_%s.png" % v)
        d.ShowNamedView2(V.VIEW_NAME[v], V.VIEW[v])
        d.ViewZoomtofit2()
        d.ViewZoomout()
        d.GraphicsRedraw2()
        d.SaveAs3(p, 0, 0)
        sz = os.path.getsize(p) if os.path.exists(p) else 0
        assert sz > 1000, "%s 截图 %d B" % (v, sz)
        h = hashlib.md5(open(p, "rb").read()).hexdigest()
        hs.add(h)
    assert len(hs) == 4, "四视图 md5 只有 %d 个不同" % len(hs)
    V.close_doc(sw, m, force=True)


# ---------------- 7 结果自审查（review.run_review）
def t_review_example():
    import review as R
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Front Plane")
        V.circle(skm, 0, 0, 20)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.extrude_checked(m, sk, 40)
    part = os.path.join(OUT, "rev_doc.SLDPRT")
    V.save_checked(m, part)
    rep, path = R.run_review(m, os.path.join(OUT, "review"), basename="rev_doc",
                             expected_outputs=[part], sw=sw)
    assert os.path.exists(path), "报告未落盘"
    assert rep["status"] == R.PASS, "应 pass，实得 %s %s" % (rep["status"], rep["issues"])
    md5s = {v.get("md5") for v in rep["views"].values() if v.get("md5")}
    assert len(md5s) == 4, "四视图 md5 应互异，实得 %d" % len(md5s)
    # to_gate 也能用
    assert R.to_gate(rep).verdict().status == "pass"
    V.close_doc(sw, m, force=True)


# ---------------- 8 by-ref 出参（swlib.call_byref）
def t_byref_example():
    import swlib as L
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -10, -10, 10, 10)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.extrude_checked(m, sk, 10)
    p = os.path.join(OUT, "byref_doc.SLDPRT")
    ret, outs = L.call_byref(m, "SaveAs4", [p, 0, 0], ["i4", "i4"])
    assert ret is True and outs == [0, 0], "合法路径应 (True, [0,0])，实得 %s %s" % (ret, outs)
    # 非法路径必须取回真实错误码（这是 by-ref 真的通了的证据）
    ret2, outs2 = L.call_byref(m, "SaveAs4", [r"Z:\no_dir\x.SLDPRT", 0, 0], ["i4", "i4"])
    assert ret2 is False and outs2[0] == 1, "应 (False, [1,0])，实得 %s %s" % (ret2, outs2)
    # 早绑定拆包
    r, split = L.split_out((True, 0, 0), 2)
    assert r is True and split == [0, 0]
    V.close_doc(sw, m, force=True)


# ---------------- 9 网格导入（mesh_import）
def t_mesh_example():
    import mesh_import as MI
    src = MI.write_test_stl(os.path.join(OUT, "doc_box.stl"), (20, 30, 40))
    pc = MI.precheck_stl(src)
    assert pc["ok"], "生成的 STL 法线应正常: %s" % pc
    rep = MI.import_mesh(sw, src, expect_bbox_mm=(0, 0, 0, 20, 30, 40))
    assert rep["ok"], [c for c in rep["checks"] if c["status"] == "fail"]
    assert rep["bbox_mm"] == [0.0, 0.0, 0.0, 20.0, 30.0, 40.0], rep["bbox_mm"]
    assert rep["mesh_bodies"] >= 1
    V.close_doc(sw, rep["doc"], force=True)


# ---------------- 10 工程图交付（drawing_delivery）
def t_drawing_example():
    import drawing_delivery as DD
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -30, -20, 30, 20)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.extrude_checked(m, sk, 15)
    part = os.path.join(OUT, "doc_dwg.SLDPRT")
    V.save_checked(m, part)
    rep = DD.create_drawing(sw, part, os.path.join(OUT, "doc_dwg.pdf"))
    assert rep["views_made"] >= 3, "应 ≥3 视图，实得 %s" % rep["views_made"]
    assert rep["pdf_bytes"] > DD.MIN_PDF_BYTES, "PDF %d B" % rep["pdf_bytes"]
    manual = [c for c in rep["checks"] if c["kind"] == "manual"]
    assert len(manual) == 4, "应有 4 项人判，实得 %d" % len(manual)
    V.close_doc(sw, m, force=True)


print("=== SKILL.md 示例代码实跑 ===\n")
chk("快速开始（圆柱）", t_quickstart)
chk("旋转（中心线）", t_revolve)
chk("offset_plane_named + 放样", t_offset_named)
chk("plane_at / cyl_of 纯逻辑", t_faces_api)
chk("place_to / fix_all / max_drift / interference_ok", t_assembly_api)
chk("四视图 ViewZoomout + md5 互异", t_views)
chk("结果自审查 run_review", t_review_example)
chk("by-ref 出参 call_byref", t_byref_example)
chk("网格导入 import_mesh", t_mesh_example)
chk("工程图交付 create_drawing", t_drawing_example)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("DOC EXAMPLES PASS")
