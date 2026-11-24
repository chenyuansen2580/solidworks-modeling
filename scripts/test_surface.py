# -*- coding: utf-8 -*-
"""曲面 / 焊件实测。ASCII 输出。"""
import math
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import swlib_v2 as V

OUT = os.path.join(HERE, "out", "surface")
os.makedirs(OUT, exist_ok=True)


def test_surface_extrude(sw):
    """开放直线 -> 拉伸曲面：面积 = 长度 x 深度。"""
    m = V.new_part(sw)
    L, D = 80.0, 50.0
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Front Plane")
        V.L.line(skm, -L / 2, 0, L / 2, 0)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.surface_extrude(m, sk, D)
    solid, sheet = V.body_counts(m)
    print("  [surf_extrude] solid=%d sheet=%d" % (solid, sheet))
    assert sheet == 1 and solid == 0, "应为 1 曲面体 0 实体"
    V.save_checked(m, os.path.join(OUT, "surf_extrude.SLDPRT"))
    V.close_doc(sw, m)


def test_surface_planar(sw):
    """闭合圆 -> 平面区域曲面：面积 = pi r^2。"""
    m = V.new_part(sw)
    R = 30.0
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.circle(skm, 0, 0, R)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.surface_planar(m, sk)
    solid, sheet = V.body_counts(m)
    print("  [surf_planar] solid=%d sheet=%d theory_area=%.1f" % (solid, sheet, math.pi * R * R))
    assert sheet == 1 and solid == 0, "应为 1 曲面体 0 实体"
    V.save_checked(m, os.path.join(OUT, "surf_planar.SLDPRT"))
    V.close_doc(sw, m)


def test_weldment(sw):
    """结构件焊件：先探测型材库。"""
    profs = V.find_weldment_profiles()
    print("  [weldment] found %d profile(s)" % len(profs))
    for p in profs[:3]:
        print("     %s" % p)
    if not profs:
        print("  [weldment] SKIP: 本机未装 weldment profiles 库")
        return
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Front Plane")
        V.L.line(skm, 0, 0, 200, 0)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    try:
        V.structural_weldment(m, sk, profs[0])
        solid, sheet = V.body_counts(m)
        print("  [weldment] OK solid=%d sheet=%d vol=%.1f"
              % (solid, sheet, V.volume_mm3(m)))
        V.save_checked(m, os.path.join(OUT, "weldment.SLDPRT"))
    except Exception as e:
        print("  [weldment] FAIL: %s" % str(e)[:120])
    V.close_doc(sw, m)


if __name__ == "__main__":
    sw = V.connect(version=2022)
    test_surface_extrude(sw)
    test_surface_planar(sw)
    test_weldment(sw)
    print(">>> SURFACE PASS")
