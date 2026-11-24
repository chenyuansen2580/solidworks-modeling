# -*- coding: utf-8 -*-
"""补充特征实测：旋转 / 放样 / 扫描 / 抽壳 / 圆角 / 倒角。
每个手法建真实几何，用 体积+bbox+实体数 三重断言，不靠眼睛。
输出全 ASCII，避开 PowerShell 中文乱码。
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import swlib_v2 as V  # noqa: E402

OUT = os.path.join(HERE, "out", "features")
os.makedirs(OUT, exist_ok=True)
RESULTS = {}


def report(tag, m, theory=None, bbox=None, bodies=1, exact=False):
    vol = V.volume_mm3(m)
    bb = V.L.bbox6(m)
    dev = ((vol - theory) / theory * 100) if theory else 0.0
    print("  [%s] vol=%.3f dev=%.4f%% bbox=%s" % (tag, vol, dev, bb))
    if exact and theory is not None:
        V.verify(m, volume=theory, bbox=bbox, bodies=bodies, tag=tag)
    elif theory is None:
        # 非解析几何：只要求有实体、体积为正
        if vol <= 0:
            raise AssertionError("%s: volume<=0" % tag)
        tree = [t for _, t in V.feature_tree(m)]
        print("  [%s] feature types = %s" % (tag, tree))
    RESULTS[tag] = (vol, bb)
    return vol


def test_revolve(sw):
    """Front 面矩形 + 中心线 -> 旋转 360 = R25 H50 圆柱（轴沿 y）。"""
    m = V.new_part(sw)
    R, H = 25.0, 50.0
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Front Plane")
        V.L.rect(skm, 0, -H / 2, R, H / 2)
        skm.CreateCenterLine(0, -0.03, 0, 0, 0.03, 0)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.revolve_checked(m, sk, 360.0)
    report("revolve", m, math.pi * R * R * H,
           (-R, -R, -H / 2, R, R, H / 2), exact=True)
    V.save_checked(m, os.path.join(OUT, "revolve_cyl.SLDPRT"))
    V.close_doc(sw, m)


def test_shell(sw):
    """拉伸方块 -> 顶面开口抽壳 2mm。
    ★ Nilove skill 实测：薄壁回转件优先画带壁厚闭合截面直接 revolve，
      对旋转体端面做 shell 会被 SW 静默拒绝；方块 (平面端面) 才稳定。
    """
    m = V.new_part(sw)
    W, H, T = 50.0, 50.0, 2.0
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -W / 2, -W / 2, W / 2, W / 2)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.extrude_checked(m, sk, H)
    body = V.wrap(V.wrap(m, "IPartDoc").GetBodies2(0, False)[0], "IBody2")
    faces = [V.wrap(f, "IFace2") for f in body.GetFaces()]
    top = max(faces, key=lambda f: list(f.GetBox())[5])  # zmax (Top plane extrude)
    V.shell_checked(m, T, faces=[top])
    theory = W * W * H - (W - 2 * T) * (W - 2 * T) * (H - T)
    report("shell", m, theory, exact=True)
    V.save_checked(m, os.path.join(OUT, "shell_box.SLDPRT"))
    V.close_doc(sw, m)


def test_loft(sw):
    """两个平行平面的圆截面 -> 放样实体。"""
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.circle(skm, 0, 0, 20)
        s1 = V.last_sketch_name(m)
        skm.InsertSketch(True)
    plane2 = V.offset_plane(m, "Top Plane", 40)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, plane2.Name if hasattr(plane2, "Name") else "Plane1")
        V.circle(skm, 0, 0, 10)
        s2 = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.loft_checked(m, [s1, s2])
    report("loft", m)
    V.save_checked(m, os.path.join(OUT, "loft.SLDPRT"))
    V.close_doc(sw, m)


def test_sweep(sw):
    """圆轮廓 + 直线路径 -> 扫描实体。理论体积 π r² L。
    ★ 几何契约：轮廓平面必须【垂直】于路径起始方向：
       路径画在 Front Plane 沿 X（世界 X 方向），轮廓画在 Right Plane（法向 X）。
    """
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Front Plane")
        V.L.line(skm, 0, 0, 100, 0)   # 路径沿世界 X
        path = V.last_sketch_name(m)
        skm.InsertSketch(True)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Right Plane")  # 法向 X，垂直于路径
        V.circle(skm, 0, 0, 5)
        prof = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.sweep_checked(m, prof, path)
    report("sweep", m, math.pi * 5 * 5 * 100, exact=True)
    V.save_checked(m, os.path.join(OUT, "sweep.SLDPRT"))
    V.close_doc(sw, m)


def test_fillet_chamfer(sw):
    """方块 -> 全边圆角 / 倒角，体积应减小且仍为 1 实体。"""
    for tag, fn, arg in (("fillet", V.fillet_checked, 5.0),
                         ("chamfer", V.chamfer_checked, 3.0)):
        m = V.new_part(sw)
        with V.addtoDB(m) as skm:
            V.L.new_sketch(m, "Top Plane")
            V.L.rect(skm, -25, -25, 25, 25)
            sk = V.last_sketch_name(m)
            skm.InsertSketch(True)
            V.extrude_checked(m, sk, 50)
        v0 = V.volume_mm3(m)
        body = V.wrap(V.wrap(m, "IPartDoc").GetBodies2(0, False)[0], "IBody2")
        edges = list(body.GetEdges())
        print("  [%s] raw volume=%.1f edges=%d" % (tag, v0, len(edges)))
        fn(m, arg, edges=edges)
        v1 = V.volume_mm3(m)
        print("  [%s] after=%.1f delta=%.1f" % (tag, v1, v1 - v0))
        if not (0 < v1 < v0):
            raise AssertionError("%s: volume did not decrease" % tag)
        RESULTS[tag] = (v1, V.L.bbox6(m))
        V.save_checked(m, os.path.join(OUT, "%s_box.SLDPRT" % tag))
        V.close_doc(sw, m)


def main():
    sw = V.connect(version=2022, wait_ready=30)
    for name, fn in (("revolve", test_revolve), ("shell", test_shell),
                     ("loft", test_loft), ("sweep", test_sweep),
                     ("fillet/chamfer", test_fillet_chamfer)):
        print("=== %s ===" % name)
        try:
            fn(sw)
        except Exception as e:
            print("  !! FAIL %s: %s" % (name, e))
            raise
    print("\n>>> FEATURES PASS: %s" % ", ".join(sorted(RESULTS)))


if __name__ == "__main__":
    main()
