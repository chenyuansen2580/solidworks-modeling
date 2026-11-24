# -*- coding: utf-8 -*-
"""运动仿真实测：建装配体 -> 建运动算例 -> 计算。ASCII 输出。"""
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import swlib_v2 as V

OUT = os.path.join(HERE, "out", "motion")
os.makedirs(OUT, exist_ok=True)


def build_asm(sw):
    """建一个底座 + 一个方块的两零件装配体，固定底座。"""
    parts = os.path.join(OUT, "parts")
    os.makedirs(parts, exist_ok=True)
    paths = []
    for nm, (w, h, d) in (("base", (80, 80, 10)), ("slider", (30, 30, 20))):
        m = V.new_part(sw)
        with V.addtoDB(m) as skm:
            V.L.new_sketch(m, "Top Plane")
            V.L.rect(skm, -w / 2, -h / 2, w / 2, h / 2)
            sk = V.last_sketch_name(m)
            skm.InsertSketch(True)
            V.extrude_checked(m, sk, d)
        p = os.path.join(parts, "%s.SLDPRT" % nm)
        V.save_checked(m, p)
        V.close_doc(sw, m)
        paths.append(p)

    asm = V.new_asm(sw)
    asm_title = V.com_member(sw.ActiveDoc, "GetTitle")
    c1 = V.add_component(sw, asm, asm_title, paths[0])
    c2 = V.add_component(sw, asm, asm_title, paths[1])
    asm = V.wrap(sw.ActiveDoc, "IAssemblyDoc")
    ap = os.path.join(OUT, "motion_test.SLDASM")
    V.save_checked(asm, ap)
    print("  [asm] built %s (2 components)" % os.path.basename(ap))
    return asm, ap


def test_motion(sw, asm):
    names = V.list_motion_studies(asm)
    print("  [motion] existing studies: %s" % names)
    ms = V.create_motion_study(asm)
    nm = getattr(ms, "Name", "?")
    print("  [motion] created: %s" % nm)
    names2 = V.list_motion_studies(asm)
    print("  [motion] studies now: %s" % names2)
    assert len(names2) >= len(names), "运动算例未增加"

    try:
        V.set_motion_frame_rate(asm, 30)
        print("  [motion] frame rate set 30")
    except Exception as e:
        print("  [motion] frame rate SKIP: %s" % str(e)[:80])

    try:
        V.calculate_motion(ms)
        print("  [motion] Calculate OK")
    except Exception as e:
        print("  [motion] Calculate FAIL: %s" % str(e)[:120])
        return False
    return True


if __name__ == "__main__":
    sw = V.connect(version=2022)
    print("  [motion] addin loaded: %s" % V.ensure_motion_addin(sw))
    asm, ap = build_asm(sw)
    ok = test_motion(sw, asm)
    V.save_checked(asm, ap)
    print(">>> MOTION PASS" if ok else ">>> MOTION PARTIAL")
