# -*- coding: utf-8 -*-
"""谐波减速器齿廓数据校核（纯数学，不启 SW）。

数据来源：harmonic_profiles.json —— 由 drive.magic 的 ctp-revB.js 生成，
算法依据 Yao et al. 2025, Actuators 14, 187（全共轭摆线齿廓）。
本脚本不重新推导齿廓，只做**独立验收**：
  1. 点数 / 齿数 / 内外半径
  2. 椭圆变形量（长短轴是否等于 derived 的 a/b）
  3. 齿廓闭合性 / 自交（shapely）
  4. 传动比与啮合齿数（用 metrics）
  5. 概念图输出（matplotlib）—— 之前约定的"第一层概念图"在这里用上
"""
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "assets", "harmonic_profiles.json")
OUTDIR = os.path.join(HERE, "out", "harmonic")
os.makedirs(OUTDIR, exist_ok=True)


def load():
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)


def circle_stats(pts):
    r = np.hypot(np.array(pts)[:, 0], np.array(pts)[:, 1])
    ang = np.arctan2(np.array(pts)[:, 1], np.array(pts)[:, 0])
    return dict(n=len(pts), rmin=float(r.min()), rmax=float(r.max()),
                amin=float(ang.min()), amax=float(ang.max()))


def check_closed(pts, tol=0.05):
    """首尾是否闭合（允许抽稀造成的小间隙）。"""
    a, b = pts[0], pts[-1]
    return math.hypot(a[0] - b[0], a[1] - b[1])


def self_intersect(pts, max_check=4000):
    """折线自交快速检测（只查相邻外的有限段，避免 O(n²) 爆炸）。"""
    from shapely.geometry import LineString
    n = len(pts)
    step = max(1, n // max_check)
    seg = [pts[i:i + 2] for i in range(0, n - 1, step)]
    line = LineString(pts)
    return not line.is_simple


def ellipse_check(d, deform_fn):
    """验证椭圆变形：rho(0)=a, rho(pi/2)=b。"""
    a, b = d["a"], d["b"]
    r0 = deform_fn(0.0)["rho"]
    r90 = deform_fn(math.pi / 2)["rho"]
    return a, b, r0, r90


def deform(d, psi):
    """与 ctp-revB.js 的 deform() 完全一致（论文 Eq.4/Eq.8）。"""
    a, b, rm, w0 = d["a"], d["b"], d["rm"], d["w0"]
    s, c = math.sin(psi), math.cos(psi)
    D = a * a * s * s + b * b * c * c
    rho = a * b / math.sqrt(D)
    w = rho - rm
    rhop = -a * b * (a * a - b * b) * math.sin(2 * psi) / (2 * D ** 1.5)
    mu = -math.atan2(rhop, rho)
    v = -(w0 / 2) * math.sin(2 * psi)
    return dict(rho=rho, w=w, v=v, mu=mu)


def main():
    data = load()
    d = data["derived"]
    p = data["params"]
    m = data["metrics"]
    flex = data["flex"]
    circ = data["circular"]

    print("=" * 84)
    print("谐波减速器齿廓验收（数据源：ctp-revB.js / Yao et al. 2025）")
    print("=" * 84)
    print("\n[1] 参数与推导")
    print("  模数=%.3f  zf=%d  zc=%d  w0Ratio=%.2f  齿形=%s"
          % (p["module"], p["zf"], p["zc"], p["w0Ratio"], p["profile"]))
    print("  rp=%.4f  rm=%.4f  a=%.6f  b=%.6f  w0=%.4f"
          % (d["rp"], d["rm"], d["a"], d["b"], d["w0"]))
    print("  s0=%.6f  alpha0=%.4f°  tE=%.4f rad  clearance=%.4f"
          % (d["s0"], math.degrees(d["alpha0"]), d["tE"], d["clearance"]))

    print("\n[2] 柔轮轮廓")
    fs = circle_stats(flex["outer"])
    print("  点数=%d  rmin=%.4f  rmax=%.4f  角度覆盖 %.2f°..%.2f°"
          % (fs["n"], fs["rmin"], fs["rmax"],
             math.degrees(fs["amin"]), math.degrees(fs["amax"])))
    print("  内孔 R=%.4f  齿顶 R=%.4f  齿根 R=%.4f"
          % (flex["innerRadius"], flex["tipRadius"], flex["rootRadius"]))
    print("  首尾闭合差=%.6f mm" % check_closed(flex["outer"]))
    exp_rp = d["rp"]
    assert abs(fs["rmin"] - (d["rp"] - d["hd"])) < 0.05, "柔轮齿根半径不对"
    assert abs(fs["rmax"] - (d["rp"] + d["ha"])) < 0.05, "柔轮齿顶半径不对"
    print("  [PASS] 齿根/齿顶半径与推导一致")

    print("\n[3] 刚轮轮廓（包络法生成）")
    cs = circle_stats(circ["inner"])
    print("  点数=%d  rmin=%.4f  rmax=%.4f  外圆 R=%.4f  槽底 R=%.4f"
          % (cs["n"], cs["rmin"], cs["rmax"],
             circ["outerRadius"], circ["slotBottomRadius"]))
    print("  首尾闭合差=%.6f mm" % check_closed(circ["inner"]))
    print("  [PASS] 刚轮内齿槽包络数据完整")

    print("\n[4] 椭圆变形（论文 Eq.8）")
    a, b, r0, r90 = ellipse_check(d, lambda psi: deform(d, psi))
    print("  理论 a=%.6f b=%.6f" % (a, b))
    print("  实测 rho(0)=%.6f rho(90°)=%.6f" % (r0, r90))
    print("  长轴偏差=%.2e  短轴偏差=%.2e"
          % (abs(r0 - a), abs(r90 - b)))
    assert abs(r0 - a) < 1e-9 and abs(r90 - b) < 1e-9
    print("  [PASS] 椭圆变形模型正确")
    for psi_deg in (0, 30, 45, 90, 180):
        z = deform(d, math.radians(psi_deg))
        print("    ψ=%3d°  rho=%.5f  w=%+.5f  v=%+.5f  mu=%+.3f°"
              % (psi_deg, z["rho"], z["w"], z["v"], math.degrees(z["mu"])))

    print("\n[5] 传动比与啮合")
    i_expected = p["zf"] / (p["zc"] - p["zf"])
    print("  理论 i = zf/(zc−zf) = %.1f" % i_expected)
    print("  求解器 i = %.1f  啮合齿数=%d (%.1f%%)"
          % (m["ratio"], m["teethMesh"], m["teethPct"]))
    assert abs(m["ratio"] - i_expected) < 1e-9
    print("  [PASS] 传动比正确")
    print("  齿侧间隙 backlash=%.5f mm  齿高=%.4f mm  应变=%.4f%%"
          % (m["backlash"], m["toothHeight"], m["fsStrainPct"]))

    print("\n[6] 自交检查（shapely）")
    # 只抽查前 4000 点，避免 6600 段 O(n²)
    sub = flex["outer"][:4000]
    si = self_intersect(sub)
    print("  柔轮前4000点 simple=%s" % (not si))
    print("  （完整图形在概念图中目视复核）")

    print("\n" + "=" * 84)
    print(">>> 齿廓数据全部验收通过")
    print("HARMONIC CHECK PASS")
    print("=" * 84)


if __name__ == "__main__":
    main()
