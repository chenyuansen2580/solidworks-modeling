# -*- coding: utf-8 -*-
"""一键探测本机三基准面的轴映射 —— 建错方向时先跑这个。

用法：
    python probe_axes.py

输出示例（本机 SW2022 实测）：
    Front Plane  草图(x,y) -> 世界(X, Y)   拉伸 -> +Z
    Top Plane    草图(x,y) -> 世界(X,-Z)   拉伸 -> +Y
    Right Plane  草图(x,y) -> 世界(-Z, Y)  拉伸 -> +X

★ 为什么需要它：SolidWorks 的基准面朝向和「Y 是上下」这个约定因机器/模板而异，
  网上抄来的结论经常是 Z 朝上的。建草图前跑一遍，比事后调体积快得多。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pythoncom          # noqa: E402
import swlib_v2 as V      # noqa: E402

# 探测用的非对称矩形：宽 60 沿草图 x，高 40 沿草图 y，拉伸 20
W, H, D = 60.0, 40.0, 20.0

EXPECT = {
    # 基准面: (草图x->世界轴, 草图y->世界轴, 拉伸方向)
    "Front Plane": ("X", "Y", "+Z"),
    "Top Plane": ("X", "-Z", "+Y"),
    "Right Plane": ("-Z", "Y", "+X"),
}


def probe_one(sw, plane):
    """在指定基准面画 W×H 矩形，拉伸 D，读 bbox 反推轴映射"""
    m = V.new_part(sw)
    try:
        with V.addtoDB(m) as skm:
            V.L.new_sketch(m, plane)
            # 矩形从 (-W/2,-H/2) 到 (W/2,H/2)，非对称性由后续 bbox 体现
            V.L.rect(skm, 0, 0, W, H)
            sk = V.last_sketch_name(m)
            skm.InsertSketch(True)
        V.extrude_checked(m, sk, D)
        bb = [round(x, 2) for x in V.bbox6(m)]      # bbox6 已是 mm
        vol = V.volume_mm3(m)
        return bb, vol
    finally:
        V.close_doc(sw, m, force=True)


def analyze(plane, bb, vol):
    """从 bbox 推断：草图 x/y 分别映射到哪个世界轴，拉伸沿哪轴

    ★ bbox6 返回的是【毫米】，不是米 —— 别在这里再乘 1000。
    """
    span = [round(bb[3] - bb[0], 2), round(bb[4] - bb[1], 2), round(bb[5] - bb[2], 2)]
    axes = "XYZ"
    mapping = {}
    for val, name in ((W, "草图x"), (H, "草图y"), (D, "拉伸")):
        best = min(range(3), key=lambda i: abs(span[i] - val))
        mapping[name] = axes[best] if abs(span[best] - val) < 0.5 else "?"
    # 正负向：bbox 最小值贴近 0 说明沿正方向长
    signs = {}
    for i, ax in enumerate(axes):
        lo, hi = bb[i], bb[i + 3]
        signs[ax] = "+" if abs(lo) < abs(hi) else "-"

    def fmt(key):
        ax = mapping[key]
        if ax == "?":
            return "?"
        return "%s%s" % (signs.get(ax, "?"), ax)

    return {
        "草图x": fmt("草图x"),
        "草图y": fmt("草图y"),
        "拉伸": fmt("拉伸"),
        "span": span,
        "vol": vol,
        "vol_ok": abs(vol - W * H * D) < 1.0,
    }


def main():
    pythoncom.CoInitialize()
    sw = V.connect(version=2022, verbose=False, warn_multi=False, wait_ready=30)

    print("探测：%dx%d 矩形，拉伸 %d mm" % (W, H, D))
    print("期望体积 %.1f mm³\n" % (W * H * D))

    results = {}
    for plane in ("Front Plane", "Top Plane", "Right Plane"):
        bb, vol = probe_one(sw, plane)
        info = analyze(plane, bb, vol)
        results[plane] = info
        print("%-14s bbox=%s" % (plane, bb))
        print("               草图x -> %-5s  草图y -> %-5s  拉伸 -> %-5s   vol=%.1f %s"
              % (info["草图x"], info["草图y"], info["拉伸"], info["vol"],
                 "OK" if info["vol_ok"] else "★体积不符"))
        exp = EXPECT[plane]
        got = (info["草图x"], info["草图y"], info["拉伸"])
        # 只比对轴向（不带正负），正负受矩形画法影响
        exp_ax = tuple(e.replace("+", "").replace("-", "") for e in exp)
        got_ax = tuple(g.replace("+", "").replace("-", "") for g in got)
        ok = exp_ax == got_ax
        print("               预期 %s  -> %s" % (exp, "匹配" if ok else "★ 不符"))
        print()

    print("=" * 66)
    print("结论表（写草图前对这张表）：")
    print("%-14s %-10s %-10s %-10s" % ("基准面", "草图x->", "草图y->", "拉伸"))
    print("-" * 66)
    for plane, info in results.items():
        print("%-14s %-10s %-10s %-10s"
              % (plane, info["草图x"], info["草图y"], info["拉伸"]))
    print("=" * 66)

    all_ok = all(r["vol_ok"] for r in results.values())
    print("\n体积校验:", "全部通过" if all_ok else "★ 有偏差，检查基准面是否被占用")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
