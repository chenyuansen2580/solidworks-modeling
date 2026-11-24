# -*- coding: utf-8 -*-
"""钣金 / 孔向导实测。ASCII 输出。"""
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import swlib_v2 as V

OUT = os.path.join(HERE, "out", "sheetmetal")
os.makedirs(OUT, exist_ok=True)


def test_base_flange(sw):
    """100x60 矩形草图 -> 基体法兰 t=2, 理论体积 = 100*60*2 = 12000 mm³。"""
    m = V.new_part(sw)
    W, H, T = 100.0, 60.0, 2.0
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, 0, 0, W, H)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
        f = V.sheetmetal_base_flange(m, sk, T, radius_mm=T,
                                     length_mm=T * 20)
    vol = V.volume_mm3(m)
    theory = W * H * T
    dev = (vol - theory) / theory * 100
    print("  [base_flange] vol=%.1f theory=%.1f dev=%.4f%%" % (vol, theory, dev))
    V.verify(m, volume=theory, bodies=1, tag="base_flange", vol_tol=0.02)
    V.save_checked(m, os.path.join(OUT, "base_flange.SLDPRT"))
    V.close_doc(sw, m)


if __name__ == "__main__":
    sw = V.connect(version=2022)
    test_base_flange(sw)
    print(">>> SHEETMETAL PASS")
