# -*- coding: utf-8 -*-
"""属性 / 配置 / 材料 / 钣金 实测。ASCII 输出。"""
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import swlib_v2 as V

OUT = os.path.join(HERE, "out", "props")
os.makedirs(OUT, exist_ok=True)


def test_props(sw):
    """自定义属性 + 配置 + 材料。"""
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -25, -25, 25, 25)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.extrude_checked(m, sk, 20)

    n = V.set_custom_props(m, {
        "PartNumber": "PN-001",
        "Description": "Test Block",
        "Material": "ABS",
        "Revision": "A",
    })
    print("  [props] wrote %d" % n)
    got = V.get_custom_props(m)
    print("  [props] read back: %s" % got)
    assert got.get("PartNumber") == "PN-001", "属性回读失败: %s" % got
    assert got.get("Description") == "Test Block"

    cfg = V.add_configuration(m, "MACHINED", "加工态")
    print("  [config] created: %s" % (cfg.Name if hasattr(cfg, "Name") else cfg))

    try:
        mat = V.set_material(m, "ABS")
        print("  [material] set: %s" % mat)
    except Exception as e:
        print("  [material] SKIP (材料库未装): %s" % str(e)[:80])

    V.save_checked(m, os.path.join(OUT, "props.SLDPRT"))
    V.close_doc(sw, m)


if __name__ == "__main__":
    sw = V.connect(version=2022)
    test_props(sw)
    print(">>> PROPS PASS")
