# -*- coding: utf-8 -*-
"""齿轮整圈齿廓生成 —— 补 gearmath 只给单齿廓的缺口。

用法：
    from gearring import full_ring
    pts = full_ring(p, g, h)     # 返回整圈闭合点列
"""
import math


def _rot(pts, ang_rad):
    c, s = math.cos(ang_rad), math.sin(ang_rad)
    return [(x * c - y * s, x * s + y * c) for (x, y) in pts]


def full_ring(p, g, half_pts, npts_root=6):
    """把单侧半齿廓拼成整圈齿轮轮廓。

    half_pts : flank() 返回的 h.pts，单侧从齿根到齿顶（角度大约 -7°..-1.6°）
    做法：每个齿 = 左半 + 镜像右半；齿间用齿根圆弧连接；旋转 z 次。

    返回闭合点列（首尾相同）。
    """
    z = int(p.z)
    rf = g.rf
    # 1) 单个齿的完整轮廓（不含齿间圆弧）
    right = [(x, -y) for (x, y) in reversed(half_pts)]
    tooth = [(float(x), float(y)) for (x, y) in (half_pts + right)]

    # 2) 齿的角跨度：首点到末点（镜像后）
    a_start = math.atan2(tooth[0][1], tooth[0][0])
    a_end = math.atan2(tooth[-1][1], tooth[-1][0])
    # 齿间圆弧从 a_end 到下一齿的 a_start + 2π/z
    step = 2 * math.pi / z

    ring = []
    for k in range(z):
        base = k * step
        # 本齿（旋转到第 k 个位置）
        ring.extend(_rot(tooth, base))
        # 齿根圆弧：从本齿末点到下一齿首点
        a0 = a_end + base
        a1 = a_start + base + step
        if a1 <= a0:
            a1 += 2 * math.pi
        for j in range(1, npts_root):
            t = a0 + (a1 - a0) * j / npts_root
            ring.append((rf * math.cos(t), rf * math.sin(t)))

    # 3) 去重 + 闭合
    out = []
    for q in ring:
        if not out or math.hypot(q[0] - out[-1][0], q[1] - out[-1][1]) > 1e-4:
            out.append(q)
    if out[0] != out[-1]:
        out.append(out[0])
    return out


def check_ring(pts, g):
    """自检：点数、半径范围、是否闭合、有无明显自交（角度单调）。"""
    rs = [math.hypot(x, y) for (x, y) in pts]
    return {
        "points": len(pts),
        "r_min": round(min(rs), 3),
        "r_max": round(max(rs), 3),
        "rf_expect": round(g.rf, 3),
        "ra_expect": round(g.ra, 3),
        "closed": pts[0] == pts[-1],
        "r_ok": abs(min(rs) - g.rf) < 0.5 and abs(max(rs) - g.ra) < 0.5,
    }
