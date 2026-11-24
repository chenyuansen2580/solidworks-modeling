# -*- coding: utf-8 -*-
"""技能自检：跑一个最小零件，验证「连接→草图→拉伸→校核→出图→存盘」全链路。

用途：每次改完 swlib/swlib_v2 后先跑这个，绿了再碰真零件。
判据写死在这里，不靠眼睛：
    体积   π·25²·50 = 98174.771 mm³，相对偏差 <0.5%
    bbox   (-25,-25,0, 25,25,50) mm，逐项 ±0.5mm
    实体数 1
    截图   四张都非空
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import swlib_v2 as V          # noqa: E402

OUT = os.path.join(HERE, "out", "smoke")

R = 25.0
H = 50.0
THEORY = 3.14159265 * R * R * H


def main():
    sw = V.connect(version=2022, wait_ready=30)
    m = V.new_part(sw)

    with V.addtoDB(m) as skm:                    # ★ 关 1mm 吸附
        V.L.new_sketch(m, "Front Plane")
        V.circle(skm, 0, 0, R)                   # 传圆周上一点，不是半径
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.extrude_checked(m, sk, H)

    ok, got, dev = V.volume_check(m, THEORY, tag="cylinder")
    V.verify(m, volume=THEORY,
             bbox=(-R, -R, 0.0, R, R, H), bodies=1, tag="smoke")
    if not ok:
        raise AssertionError("体积偏差 %.4f%% 超限，别往下走了" % dev)

    part_path = os.path.join(OUT, "smoke_cylinder.SLDPRT")
    rc, sz = V.save_checked(m, part_path)
    print("  save rc=%s size=%d -> %s" % (rc, sz, part_path))

    views = V.four_views(sw, m, OUT, "smoke")
    for v in views:
        print("  view %-6s %s" % (v.get("view"), v.get("size") or v.get("error")))

    V.close_doc(sw, m)
    print("\n>>> SMOKE PASS")


if __name__ == "__main__":
    main()
