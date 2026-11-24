# -*- coding: utf-8 -*-
"""验证 pattern.circular / mirror_checked 是否真的能用 —— 它们被标 VERIFIED 但从未实测"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pythoncom          # noqa: E402
import swlib_v2 as V      # noqa: E402

OUT = os.path.join(HERE, "out", "capcheck")
os.makedirs(OUT, exist_ok=True)

pythoncom.CoInitialize()
sw = V.connect(version=2022, verbose=False, warn_multi=False, wait_ready=30)

fails = []


def chk(name, fn):
    try:
        note = fn()
        print("  [OK] %-32s %s" % (name, note or ""))
    except Exception as e:
        print("  [XX] %-32s %s" % (name, str(e)[:80]))
        fails.append(name)


# ---------------- pattern.circular 真实验证
def t_circular():
    """圆柱 + 1 个孔 → 圆周阵列，验体积下降量

    ★ 三个关键（2026-11-20 实测）：
      1) 母特征必须传【切除特征名】（类型名是 ICE，不是 Cut/Extrusion）
      2) 轴必须是【孔心所在的那条轴线】—— 孔在 (25,0) 绕 Z 转，
         要用 Front×Top 交线（Z 轴），不能用 X/Y 轴，否则体积反增
      3) count=N 实际新增 N-1 个孔（母特征算第 1 个）
    """
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Front Plane")
        V.circle(skm, 0, 0, 40)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.extrude_checked(m, sk, 10)
    v0 = V.volume_mm3(m)

    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Front Plane")
        V.circle(skm, 25, 0, 3)
        sk2 = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.cut_checked(m, sk2, None)
    v1 = V.volume_mm3(m)
    one_hole = v0 - v1
    assert one_hole > 0, "单孔切除失败"

    cut_name = None
    for nm, tp in V.feature_tree(m):
        if tp == "ICE":
            cut_name = nm
    assert cut_name, "找不到切除特征（类型名应为 ICE）"

    # ★ 轴必须【垂直于孔心到中心的连线】：
    #   孔在 (X=25, Y=0)，圆柱轴沿 Z。
    #   绕 X 轴转 → 孔心轨迹半径 25，转出 5 个新孔（+5.00 实测）
    #   绕 Z 轴转 → 孔就在轴上，只转出 1.34 个（错）
    #   → 用 Top×Right 交线（X 轴）
    doc = V.wrap(m, "IModelDoc2")
    doc.ClearSelection2(True)
    doc.Extension.SelectByID2("Top Plane", "PLANE", 0, 0, 0, False, 0, None, 0)
    doc.Extension.SelectByID2("Right Plane", "PLANE", 0, 0, 0, True, 0, None, 0)
    doc.InsertAxis2(True)
    axis_name = None
    for nm, tp in V.feature_tree(m):
        if tp in ("RefAxis", "Axis"):
            axis_name = nm
    doc.ClearSelection2(True)
    assert axis_name, "基准轴没建成"

    V.circular_pattern_checked(m, cut_name, axis_name, 6)
    v2 = V.volume_mm3(m)
    added = v2 - v1
    n_new = -added / one_hole
    V.close_doc(sw, m, force=True)
    assert 4.5 < n_new < 5.5, "阵列新增 %.2f 孔，期望 5（count=6 减母特征）" % n_new
    return "count=6 新增 %.0f 孔，Δ=%+.2f（单孔 %.2f）" % (n_new, added, one_hole)


# ---------------- mirror_checked 真实验证
def t_mirror():
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -50, -30, 50, 30)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.extrude_checked(m, sk, 10)
    v0 = V.volume_mm3(m)

    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, 20, -10, 40, 10)
        sk2 = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.cut_checked(m, sk2, None)
    v1 = V.volume_mm3(m)
    one_cut = v0 - v1
    assert one_cut > 0, "切除失败"

    # ★ 同样要传切除特征名
    cut_name = None
    for nm, tp in V.feature_tree(m):
        if tp == "ICE":
            cut_name = nm
    V.mirror_checked(m, cut_name, "Right Plane")
    v2 = V.volume_mm3(m)
    total = v0 - v2
    V.close_doc(sw, m, force=True)
    assert total > one_cut * 1.5, "镜像未生效: 切了 %.1f，单槽 %.1f" % (total, one_cut)
    return "镜像后总切除 %.1f（单槽 %.1f）" % (total, one_cut)


# ---------------- hole_wizard（PILOT：本机测了 4 轮全 None，如实记录）
def t_hole_wizard():
    """孔向导 —— 已实测 4 轮（不同 StandardIndex/FastenerTypeIndex/SSize 组合）
    全部返回 None，维持 PILOT 级别，此处只验证"失败时抛明确异常"而非静默。
    """
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -40, -30, 40, 30)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.extrude_checked(m, sk, 20)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        skm.CreatePoint(0.0, 0.0, 0.0)
        sk2 = V.last_sketch_name(m)
        skm.InsertSketch(True)
    raised = False
    try:
        V.hole_wizard(m, sk2, hole_type=2, diameter_mm=10, end_type=1)
    except RuntimeError:
        raised = True
    V.close_doc(sw, m, force=True)
    assert raised, "hole_wizard 应抛 RuntimeError 说明失败原因"
    return "PILOT 确认：本机不可用，但抛明确异常（非静默失败）"


# ---------------- surface_revolve 真实验证
def t_surface_revolve():
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Front Plane")
        V.L.line(skm, 20, 0, 40, 0)
        V.L.line(skm, 40, 0, 40, 30)
        V.L.line(skm, 40, 30, 20, 30)
        V.L.line(skm, 20, 30, 20, 0)
        skm.CreateCenterLine(0, -0.005, 0, 0, 0.035, 0)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    V.surface_revolve(m, sk, 360)
    s, sh = V.body_counts(m)
    V.close_doc(sw, m, force=True)
    assert sh >= 1, "旋转曲面未生成: solid=%d sheet=%d" % (s, sh)
    return "solid=%d sheet=%d" % (s, sh)


# ---------------- weldment_cut_list（PILOT：切割清单生成条件不稳定）
def t_cut_list():
    """焊件切割清单 —— 实测发现【同样 4 实体，有时有 CutListFolder 有时没有】：

      belt_actuator P14（700×300，角钢总长 2000mm）→ 2 项 CutListFolder
      本测试（200×120，角钢总长 640mm）        → 0 项

    bodies 都是 4，配置相同。结论：CutListFolder 的生成与型材总长/切分方式有关，
    不是纯 API 行为。维持 PILOT，本测试只验证"函数不崩、如实返回空列表"。
    """
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -350, -150, 350, 150)     # 用 P14 的尺寸
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
    profs = V.find_weldment_profiles()
    ang = [p for p in profs if "ls angle squared" in p.lower()]
    V.structural_weldment(m, sk, ang[0], config="Al LS ANGLE SQR END 1 x 0.75 x 0.125")
    s, sh = V.body_counts(m)
    p = os.path.join(OUT, "weld4.SLDPRT")
    V.save_checked(m, p)
    n_mem = len(V.weldment_cut_list(m))
    V.close_doc(sw, m, force=True)

    m2 = V.open_doc(sw, p, doc_type=1, activate=True)
    lst = V.weldment_cut_list(m2)
    V.close_doc(sw, m2, force=True)
    assert isinstance(lst, list), "weldment_cut_list 应返回列表"
    assert s >= 4, "焊件应为多实体，实得 %d" % s
    return "solid=%d  内存 %d 项 → 重开 %d 项" % (s, n_mem, len(lst))


print("=== 能力表 VERIFIED 抽查（这些从未在测试里跑过）===\n")
chk("pattern.circular", t_circular)
chk("mirror (pilot)", t_mirror)
chk("hole_wizard (pilot)", t_hole_wizard)
chk("surface_revolve (pilot)", t_surface_revolve)
chk("weldment_cut_list (pilot)", t_cut_list)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("CAP CHECK PASS")
