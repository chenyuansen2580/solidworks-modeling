# -*- coding: utf-8 -*-
"""行星减速器全部零件的解析几何与理论体积（纯数学，不启动 SolidWorks）。

用途：给 SolidWorks 实测体积提供独立校核基准。
每个零件都给出「从参数直接推导」的体积公式，而不是拿 SW 的结果反推。
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gearmath as GM


# ---------------------------------------------------------------- 多边形工具
def poly_area(pts):
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def arc_pts(r, a0, a1, n=96):
    return [GM.pol(r, a0 + (a1 - a0) * i / n) for i in range(n + 1)]


# ---------------------------------------------------------------- 齿槽轮廓
def gap_polygon(p, g, h, n_arc=96):
    """一个齿槽的「核心」封闭多边形：齿根弧 + 左齿廓 + 齿顶弧 + 右齿廓。

    这个多边形恰好就是从齿坯上要挖掉的材料：
      外齿：边界 = 齿根圆 -> 齿廓 -> 齿顶圆，落在齿坯（圆盘到齿顶圆）之内
      内齿：边界 = 齿根圆(外) -> 齿廓 -> 齿顶圆(内)，正是环上要挖掉的楔形
    不含任何封口延伸段 —— 那部分本来就没有材料。
    """
    dth = 2 * math.pi / p.z
    spc = -math.pi / p.z
    a_l = -h.th_a
    a_r = -dth + h.th_a

    pts = []
    pts += arc_pts(g.rf, spc - h.land_a, spc + h.land_a, n_arc)   # 齿根弧 A->B
    pts += list(h.pts[1:])                                        # 左齿廓 B->齿顶
    pts += arc_pts(g.ra_use, a_l, a_r, n_arc)[1:]                 # 齿顶弧 C->D
    c, s = math.cos(-dth), math.sin(-dth)
    for q in reversed(h.pts[:-1]):                                # 右齿廓 齿顶->齿根
        y = -q[1]
        pts.append((q[0] * c - y * s, q[0] * s + y * c))
    return pts


# ---------------------------------------------------------------- 各零件
def sun_volume(p, g, h):
    """外齿轮：齿坯圆柱 - z 个齿槽 - 内孔。"""
    a_blank = math.pi * g.ra_use ** 2
    a_gap = abs(poly_area(gap_polygon(p, g, h)))
    a_gear = a_blank - p.z * a_gap
    a_bore = math.pi * (p.bore / 2.0) ** 2 if p.bore > 0 else 0.0
    return (a_gear - a_bore) * p.bw, dict(a_blank=a_blank, a_gap=a_gap,
                                          a_gear=a_gear, a_bore=a_bore)


def ring_volume(p, g, h, od):
    """内齿圈：外圆 - 内齿顶孔 - z 个齿槽。

    齿槽多边形本来就落在 r >= ra 的区域（齿顶圆之内没有材料），直接相减即可。
    """
    r_out = od / 2.0
    a_out = math.pi * r_out ** 2
    a_bore = math.pi * g.ra_use ** 2
    gap = gap_polygon(p, g, h)
    a_gap = abs(poly_area(gap))
    rmin = min(math.hypot(*q) for q in gap)
    a_ring = a_out - a_bore - p.z * a_gap
    return a_ring * p.bw, dict(a_out=a_out, a_bore=a_bore, a_gap=a_gap,
                               a_ring=a_ring, gap_rmin=rmin, n_gap_pts=len(gap))


def simple_volume(r_out, r_in, thick):
    return math.pi * (r_out ** 2 - r_in ** 2) * thick


if __name__ == "__main__":
    M = 1.5
    ZS, ZP, ZR = 18, 27, 72
    B = 12.0
    OD_RING = 120.0

    print("=" * 90)
    print("行星减速器 GR-90  i=5  模数 m=%.1f  齿宽 b=%.1f" % (M, B))
    print("=" * 90)

    # ---- 太阳轮
    ps = GM.GearParams(mn=M, z=ZS, bw=B, bore=8.0, npts=24)
    gs = GM.GearGeom(ps)
    hs = GM.flank(ps, gs)
    Vs, ds = sun_volume(ps, gs, hs)
    print("\n[01] 太阳轮 z=%d" % ZS)
    print("     %s" % gs)
    print("     齿坯面积=%.4f  齿槽面积=%.4f  齿形面积=%.4f  内孔面积=%.4f"
          % (ds["a_blank"], ds["a_gap"], ds["a_gear"], ds["a_bore"]))
    print("     理论体积=%.3f mm3" % Vs)
    for w in GM.warnings(ps, gs, hs):
        print("     ! " + w)

    # ---- 行星轮
    pp = GM.GearParams(mn=M, z=ZP, bw=B, bore=8.0, npts=24)
    gp = GM.GearGeom(pp)
    hp = GM.flank(pp, gp)
    Vp, dp = sun_volume(pp, gp, hp)
    print("\n[02] 行星轮 z=%d (x3)" % ZP)
    print("     %s" % gp)
    print("     齿坯面积=%.4f  齿槽面积=%.4f  齿形面积=%.4f  内孔面积=%.4f"
          % (dp["a_blank"], dp["a_gap"], dp["a_gear"], dp["a_bore"]))
    print("     理论体积=%.3f mm3 x3 = %.3f" % (Vp, 3 * Vp))
    for w in GM.warnings(pp, gp, hp):
        print("     ! " + w)

    # ---- 内齿圈
    pr = GM.GearParams(mn=M, z=ZR, bw=B, internal=True, od_int=OD_RING, npts=24)
    gr = GM.GearGeom(pr)
    hr = GM.flank(pr, gr)
    Vr, dr = ring_volume(pr, gr, hr, OD_RING)
    print("\n[03] 内齿圈 z=%d  OD=%.1f" % (ZR, OD_RING))
    print("     %s" % gr)
    print("     外圆面积=%.4f  内孔面积=%.4f  齿槽面积=%.4f  环面积=%.4f"
          % (dr["a_out"], dr["a_bore"], dr["a_gap"], dr["a_ring"]))
    print("     齿槽多边形最小半径=%.4f (应 >= ra=%.4f)"
          % (dr["gap_rmin"], gr.ra_use))
    print("     理论体积=%.3f mm3" % Vr)
    for w in GM.warnings(pr, gr, hr):
        print("     ! " + w)

    # ---- 行星架
    print("\n[04] 行星架")
    plate_out, plate_in, plate_t = 52.0, 12.0, 6.0
    pin_d, pin_l, pin_r = 8.0, 18.0, 33.75
    hub_r, hub_t, hub_bore = 18.0, 14.0, 8.0
    a = M * (ZS + ZP) / 2.0
    V_plate = simple_volume(plate_out, plate_in, plate_t)
    V_pins = 3 * math.pi * (pin_d / 2) ** 2 * pin_l
    V_hub = simple_volume(hub_r, hub_bore / 2.0, hub_t)
    # 销与板/毂重叠扣掉
    V_ov_pin_plate = 3 * math.pi * (pin_d / 2) ** 2 * plate_t
    V_ov_hub_plate = simple_volume(min(hub_r, plate_out), plate_in, plate_t)
    V_carrier = V_plate + V_pins + V_hub - V_ov_pin_plate - V_ov_hub_plate
    print("     板 R%.1f/R%.1f t%.1f = %.3f" % (plate_out, plate_in, plate_t, V_plate))
    print("     销 D%.1f x%.1f x3 @R%.2f = %.3f" % (pin_d, pin_l, pin_r, V_pins))
    print("     毂 R%.1f t%.1f 孔D%.1f = %.3f" % (hub_r, hub_t, hub_bore, V_hub))
    print("     重叠 销-板=%.3f  毂-板=%.3f" % (V_ov_pin_plate, V_ov_hub_plate))
    print("     理论体积=%.3f mm3" % V_carrier)
    print("     中心距 a = %.4f" % a)

    # ---- 汇总
    print("\n" + "=" * 90)
    print("轮系校核")
    print("=" * 90)
    chk = GM.__dict__
    print("  zr = zs + 2*zp : %d == %d + 2*%d = %d  -> %s"
          % (ZR, ZS, ZP, ZS + 2 * ZP, ZR == ZS + 2 * ZP))
    print("  传动比 (齿圈固定) i = 1 + zr/zs = %.4f" % (1 + ZR / float(ZS)))
    print("  装配条件 (zs+zr)/3 = %.4f -> %s"
          % ((ZS + ZR) / 3.0, (ZS + ZR) % 3 == 0))
    print("  邻接条件 2a·sin(60°) = %.4f > 2*ra_p = %.4f -> %s"
          % (2 * a * math.sin(math.pi / 3), 2 * gp.ra_use,
             2 * a * math.sin(math.pi / 3) > 2 * gp.ra_use))
    print("  太阳-行星侧隙  a - rf_p - ra_s = %.4f mm"
          % (a - gp.rf - gs.ra_use))
    print("  行星-齿圈侧隙  rf_r - (a + ra_p) = %.4f mm"
          % (gr.rf - (a + gp.ra_use)))
    print("  行星-齿圈侧隙2 ra_r - (a + rf_p) = %.4f mm"
          % (gr.ra_use - (a + gp.rf)))
    print("\n  体积汇总: 太阳=%.3f 行星x3=%.3f 齿圈=%.3f 行星架=%.3f"
          % (Vs, 3 * Vp, Vr, V_carrier))

    # ---- 真正的验收断言（旧版只打印，数值错了也会正常退出）
    assert ZR == ZS + 2 * ZP, "齿数关系不成立"
    assert abs((1 + ZR / float(ZS)) - 5.0) < 1e-9, "传动比应为 5.0"
    assert (ZS + ZR) % 3 == 0, "装配条件不成立"
    assert 2 * a * math.sin(math.pi / 3) > 2 * gp.ra_use, "邻接条件不成立"
    assert all(v > 0 for v in (Vs, Vp, Vr, V_carrier)), "有零件体积非正"
    assert abs(a - (gs.d + gp.d) / 2.0) < 1e-9, "中心距与分度圆不符"
    print("\n  [PASS] 轮系 4 项约束 + 4 个正体积 + 中心距 全部成立")
    print("PLANETARY VERIFY PASS")
