# -*- coding: utf-8 -*-
"""拔模等效手法实测：梯形拉伸 + 圆台旋转。ASCII 输出。"""
import math
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import swlib_v2 as V

OUT = os.path.join(HERE, "out", "draft")
os.makedirs(OUT, exist_ok=True)


def test_draft_extrude(sw):
    """底 40x40，高 20，拔模 5° → 棱台体积。
    棱台体积 = H/3*(A1+A2+sqrt(A1*A2))，A1=bottom², A2=top²。
    """
    m = V.new_part(sw)
    bw, bh, h, ang = 40.0, 40.0, 20.0, 5.0
    f, tw, th = V.draft_extrude(m, bw, bh, h, ang)
    off = h * math.tan(math.radians(ang))
    assert abs(tw - (bw - 2*off)) < 1e-6
    a1, a2 = bw * bh, tw * th
    theory = h / 3 * (a1 + a2 + math.sqrt(a1 * a2))
    V.volume_check(m, theory, tag="draft_extrude")
    print("  [draft_extrude] top=%.3f theory=%.1f got=%.1f"
          % (tw, theory, V.volume_mm3(m)))
    V.save_checked(m, os.path.join(OUT, "draft_extrude.SLDPRT"))
    V.close_doc(sw, m)


def test_draft_cone(sw):
    """底 r20 顶 r15 高 20 → 圆台体积 = πh/3(R²+Rr+r²)。"""
    m = V.new_part(sw)
    r1, r2, h = 20.0, 15.0, 20.0
    f, ang = V.draft_cone(m, r1, r2, h)
    theory = math.pi * h / 3 * (r1*r1 + r1*r2 + r2*r2)
    V.volume_check(m, theory, tag="draft_cone")
    print("  [draft_cone] angle=%.3f deg theory=%.1f got=%.1f"
          % (ang, theory, V.volume_mm3(m)))
    V.save_checked(m, os.path.join(OUT, "draft_cone.SLDPRT"))
    V.close_doc(sw, m)


if __name__ == "__main__":
    sw = V.connect(version=2022)
    test_draft_extrude(sw)
    test_draft_cone(sw)
    print(">>> DRAFT PASS")
