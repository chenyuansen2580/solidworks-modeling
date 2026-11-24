# -*- coding: utf-8 -*-
"""端到端装配套件 —— 守 S5/S6/S10/S12 四条组合坑

现有 8 个套件全测【单函数】，而 2026-11-20 那次 11 条坑里有 6 条是
【组合行为】，套件一个都没抓到。本套件专测组合：

  1. bbox 迭代摆位（S6：V.place 设的是原点，非对称件必偏）
  2. 全部 Fix 后加配合，漂移必须为 0（S12：不固定则零件被拉散 135mm）
  3. 干涉检查必须在 IAssemblyDoc 上（S10：IModelDoc2 必抛，误判成有干涉）
  4. 四视图 md5 必须互异（S12：视口锁死时恒为同一张图）
  5. 工程图中文视图名（S9：英文名恒 False）
  6. 存盘 → 重开 → 组件/配合数不变

跑法：python test_assembly.py
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pythoncom          # noqa: E402
import swlib_v2 as V      # noqa: E402

OUT = os.path.join(HERE, "out", "assembly")
os.makedirs(OUT, exist_ok=True)


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


class R(object):
    def __init__(self):
        self.rows = []

    def add(self, name, ok, note=""):
        self.rows.append((name, bool(ok), note))
        print("    [%s] %-30s %s" % ("OK" if ok else "XX", name, note))
        return ok

    def done(self):
        bad = [r for r in self.rows if not r[1]]
        return len(bad) == 0, bad


# ---------------------------------------------------------------- 建 4 个小件
def make_parts(sw):
    """方块 / 圆柱 / 带孔板 / 小轴 —— 覆盖拉伸、旋转、切除、圆角"""
    paths = {}

    # 1) 底板 120x80x10
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -60, -40, 60, 40)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.extrude_checked(m, sk, 10)
    p = os.path.join(OUT, "e2e_base.SLDPRT")
    V.save_checked(m, p)
    paths["base"] = p
    V.close_doc(sw, m, force=True)

    # 2) 立板 80x60x8（带 Ø20 孔）
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Right Plane")
        V.L.rect(skm, -30, -40, 30, 40)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.extrude_checked(m, sk, 8)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Right Plane")
        V.circle(skm, 0, 0, 10)
        sk2 = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.cut_checked(m, sk2, None)
    p = os.path.join(OUT, "e2e_wall.SLDPRT")
    V.save_checked(m, p)
    paths["wall"] = p
    V.close_doc(sw, m, force=True)

    # 3) 圆柱 Ø30 x 40（旋转）
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Front Plane")
        V.L.rect(skm, 0, 0, 15, 40)
        skm.CreateCenterLine(0, -0.005, 0, 0, 0.045, 0)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.revolve_checked(m, sk, 360)
    p = os.path.join(OUT, "e2e_cyl.SLDPRT")
    V.save_checked(m, p)
    paths["cyl"] = p
    V.close_doc(sw, m, force=True)

    # 4) 小轴 Ø20 x 50（旋转 + 圆角）
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Front Plane")
        V.L.rect(skm, 0, 0, 10, 50)
        skm.CreateCenterLine(0, -0.005, 0, 0, 0.055, 0)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.revolve_checked(m, sk, 360)
    p = os.path.join(OUT, "e2e_shaft.SLDPRT")
    V.save_checked(m, p)
    paths["shaft"] = p
    V.close_doc(sw, m, force=True)

    return paths


# ---------------------------------------------------------------- 主流程
def main():
    pythoncom.CoInitialize()
    sw = V.connect(version=2022, verbose=False, warn_multi=False, wait_ready=30)
    r = R()

    print("\n=== 端到端装配套件 ===")

    # ---- 1 建件
    paths = make_parts(sw)
    r.add("1.parts", len(paths) == 4, "%d/4 零件" % len(paths))

    # ---- 2 装配 + bbox 摆位
    asm = V.new_asm(sw)
    doc = V.wrap(asm, "IModelDoc2")
    title = V.com_member(doc, "GetTitle")

    LAYOUT = [
        ("base",  "e2e_base.SLDPRT",  V.rot_z(0),  (0, 0, 0),        (0, 0, 0)),
        ("wall",  "e2e_wall.SLDPRT",  V.rot_z(0),  (0, 10, 0),       (0, 10, -30)),
        ("cyl",   "e2e_cyl.SLDPRT",   V.rot_z(0),  (30, 10, 0),      (30, 10, 0)),
        ("shaft", "e2e_shaft.SLDPRT", V.rot_x(-90), (0, 20, 0),      (0, 20, -10)),
    ]
    comps = {}
    ok_place = 0
    for key, fname, Rm, _unused, tgt in LAYOUT:
        p = os.path.join(OUT, fname)
        try:
            c = V.add_component(sw, asm, title, p)
            got = V.place_to(sw, c, Rm, tgt)
            dev = max(abs(got[i] - tgt[i]) for i in range(3))
            comps[key] = c
            ok_place += 1 if dev < 0.1 else 0
            print("    %-6s -> %s (dev %.2f)" % (key, got, dev))
        except Exception as e:
            print("    %-6s FAIL %s" % (key, str(e)[:50]))
    r.add("2.components", len(comps) == 4, "%d/4 组件" % len(comps))
    r.add("2b.place_to", ok_place == 4, "%d/4 bbox 收敛" % ok_place)
    doc.ForceRebuild3(False)

    # ---- 3 全部 Fix（S12 关键）
    n_fix = V.fix_all(asm)
    r.add("3.fix_all", n_fix == 4, "%d/4 固定" % n_fix)

    # ---- 4 配合（固定状态下漂移必须 0）
    F = {k: V.faces_of(v) for k, v in comps.items()}
    box0 = V.all_boxes(asm)

    def mate(kind, fa, fb, dist=0.0):
        before = V.count_mates(asm)
        doc.ClearSelection2(True)
        if fa is None or fb is None:
            return False, 0, 0.0
        b1 = V.all_boxes(asm)
        ok1 = bool(V.wrap(fa, "IEntity").Select2(False, 0))
        ok2 = bool(V.wrap(fb, "IEntity").Select2(True, 0))
        if not (ok1 and ok2):
            doc.ClearSelection2(True)
            return False, 0, 0.0
        dd = dist / 1000.0
        ia = V.wrap(asm, "IAssemblyDoc")
        try:
            ia.AddMate5(kind, 0, False, dd, dd, dd, 0, 0, 0, 0, 0, 0, False, 0, 0)
        except Exception:
            pass
        after = V.count_mates(asm)
        doc.ClearSelection2(True)
        return after > before, after - before, V.max_drift(b1, V.all_boxes(asm))

    M = []
    # ★ 面法向朝内/朝外不确定（PlaneParams 不保证朝外），所以 sign 传 None，
    #   只按【局部坐标】定位：base 顶面 y=10、wall 底面 y=−40、cyl 底面 y=0。
    M.append(("wall↔base 重合", mate(0,
              V.plane_at(F["wall"], "y", None, -40.0),
              V.plane_at(F["base"], "y", None, 10.0))))
    M.append(("cyl↔base 重合", mate(0,
              V.plane_at(F["cyl"], "y", None, 0.0),
              V.plane_at(F["base"], "y", None, 10.0))))
    M.append(("shaft↔wall 同心", mate(1,
              V.cyl_of(F["shaft"], 20.0), V.cyl_of(F["wall"], 20.0))))
    # 圆柱 Ø30 外圆 ↔ 小轴 Ø20（验证 cyl_of 不会误选到 Ø20 孔）
    M.append(("cyl 外圆可挑", mate(1,
              V.cyl_of(F["cyl"], 30.0), V.cyl_of(F["shaft"], 20.0))))

    ok_m = 0
    for name, (ok, d, drift) in M:
        good = ok and drift < 1.0
        r.add("4." + name, good, "Δ=%d 漂移=%.2f" % (d, drift))
        ok_m += 1 if good else 0
    r.add("4b.mates", ok_m >= 3, "%d/4 一致" % ok_m)

    total_drift = V.max_drift(box0, V.all_boxes(asm))
    r.add("4c.drift", total_drift < 1.0, "总漂移 %.2f mm" % total_drift)

    # ---- 5 干涉（S10：必须在 IAssemblyDoc 上）
    ok_i, raw = V.interference_ok(asm)
    r.add("5.interference", ok_i, str(raw))

    # ---- 6 四视图（S12：md5 必须互异）
    doc.ForceRebuild3(False)
    hashes = {}
    for name in ("iso", "front", "top", "right"):
        p = os.path.join(OUT, "e2e_%s.png" % name)
        if os.path.exists(p):
            os.remove(p)
        doc.ShowNamedView2(V.VIEW_NAME[name], V.VIEW[name])
        doc.ViewZoomtofit2()
        doc.ViewZoomout()
        doc.GraphicsRedraw2()
        doc.SaveAs3(p, 0, 0)
        sz = os.path.getsize(p) if os.path.exists(p) else 0
        hashes[name] = md5(p) if sz > 1000 else None
        print("    view %-6s %7d B" % (name, sz))
    n_uniq = len({h for h in hashes.values() if h})
    r.add("6.views_distinct", n_uniq == 4, "%d 个不同 md5" % n_uniq)

    # ---- 7 存盘（★ 工程图需要模型文件已存在于磁盘）
    asm_path = os.path.join(OUT, "e2e_asm.SLDASM")
    if os.path.exists(asm_path):
        try:
            os.remove(asm_path)
        except Exception:
            pass
    V.save_checked(asm, asm_path)
    n_comp_saved = len(V.comps(asm))
    n_mate_saved = V.count_mates(asm)
    r.add("7.save", os.path.exists(asm_path),
          "%d B 组件 %d 配合 %d" % (os.path.getsize(asm_path),
                                   n_comp_saved, n_mate_saved))

    # ---- 8 工程图（S9：中文视图名 + IDrawingDoc；模型须已在磁盘+激活）
    pdf = os.path.join(OUT, "e2e_drawing.pdf")
    try:
        tpl = None
        for cand in (r"F:\SOLIDWORKS\data\templates\gb.drwdot",
                     r"F:\SOLIDWORKS\data\templates\iso.drwdot"):
            if os.path.exists(cand):
                tpl = cand
                break
        dw = sw.NewDocument(tpl, 0, 0, 0) if tpl else None
        made = 0
        if dw is not None:
            for vn, x, y in (("*等轴测", 0.15, 0.13), ("*前视", 0.06, 0.05)):
                v = V.drawing_view(dw, asm_path, vn, x, y)
                nm = V.view_name_of(v) if v is not None else None
                if nm:
                    made += 1
                    print("    view %-8s -> %s" % (vn, nm))
            dd = V.wrap(dw, "IModelDoc2")
            dd.ForceRebuild3(False)
            if os.path.exists(pdf):
                os.remove(pdf)
            dd.SaveAs3(pdf, 0, 0)
            V.close_doc(sw, dw, force=True)
        psz = os.path.getsize(pdf) if os.path.exists(pdf) else 0
        r.add("8.drawing", made >= 1 and psz > 3000,
              "%d 视图 / PDF %d B" % (made, psz))
    except Exception as e:
        r.add("8.drawing", False, str(e)[:60])

    # ---- 9 重开验证
    V.close_doc(sw, asm, force=True)
    asm2 = V.open_doc(sw, asm_path, doc_type=2, activate=True)
    V.wrap(asm2, "IModelDoc2").ForceRebuild3(False)
    n_comp2 = len(V.comps(asm2))
    n_mate2 = V.count_mates(asm2)
    r.add("9.reopen", n_comp2 == n_comp_saved and n_mate2 == n_mate_saved,
          "组件 %d→%d 配合 %d→%d" % (n_comp_saved, n_comp2,
                                    n_mate_saved, n_mate2))
    V.close_doc(sw, asm2, force=True)

    ok, bad = r.done()
    print("\n" + "=" * 58)
    print("ASSEMBLY", "PASS" if ok else "FAIL")
    for n, _, note in bad:
        print("  XX %-30s %s" % (n, note))
    print("=" * 58)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
