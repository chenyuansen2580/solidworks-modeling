# -*- coding: utf-8 -*-
r"""网格导入测试（STL → SW 参考图形体）。

对标 wzyn 的 `test_import_mesh_reference.py`。核心断言：

  - STL 长方体 20×30×40 导入后 bbox 精确等于 (0,0,0, 20,30,40) mm
  - 网格体必须走 MeshBodyFeature 链才数得到（GetBodies2 看不到）
  - 第 3 参传 None 会失败，必须传空 IDispatch（这条是"坑"的实证）
  - GLB 给出转换命令而不是硬失败
  - 网格件明确不是参数化实体（特征树里没有可编辑草图/特征）

跑法：python test_mesh_import.py            静态 + SW
      python test_mesh_import.py --static   只跑静态
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mesh_import as MI

OUT = os.path.join(HERE, "out", "mesh")
fails = []


def chk(name, fn):
    try:
        note = fn()
        print("  [OK] %-46s %s" % (name, note or ""))
    except AssertionError as e:
        print("  [XX] %-46s %s" % (name, e))
        fails.append(name)
    except Exception as e:
        print("  [XX] %-46s %s: %s" % (name, type(e).__name__, e))
        fails.append(name)


# ---------------------------------------------------------------- 静态
def t_stl_writer():
    """生成的 STL 必须是合法 ASCII，bbox 精确等于给尺寸，法线非零且朝外。

    ★ 法线必须非零：SW2022 遇 0 法线会弹模态框把 COM 挂死（见 mesh_import 注释）。
    """
    p = MI.write_test_stl(os.path.join(OUT, "static_box.stl"), (20, 30, 40))
    txt = open(p, encoding="ascii").read()
    assert txt.startswith("solid "), "ASCII STL 应以 solid 开头"
    assert txt.count("vertex") == 36, "12 三角形 × 3 顶点 = 36，实得 %d" % \
        txt.count("vertex")
    xs = [float(l.split()[1]) for l in txt.splitlines() if "vertex" in l]
    ys = [float(l.split()[2]) for l in txt.splitlines() if "vertex" in l]
    zs = [float(l.split()[3]) for l in txt.splitlines() if "vertex" in l]
    assert (min(xs), max(xs)) == (0.0, 20.0), (min(xs), max(xs))
    assert (min(ys), max(ys)) == (0.0, 30.0), (min(ys), max(ys))
    assert (min(zs), max(zs)) == (0.0, 40.0), (min(zs), max(zs))
    # 法线：12 条，全部单位向量，无 0 法线
    normals = []
    for line in txt.splitlines():
        if line.startswith("facet normal"):
            n = [float(x) for x in line.split()[2:5]]
            normals.append(n)
    assert len(normals) == 12, len(normals)
    for n in normals:
        mag = sum(x * x for x in n) ** 0.5
        assert abs(mag - 1.0) < 1e-4, "法线未归一化: %s" % (n,)
    return "36 顶点 / 12 条单位法线 / bbox 0..20,0..30,0..40"


def t_precheck_good():
    """正常 STL 预检通过。"""
    p = MI.write_test_stl(os.path.join(OUT, "pre_good.stl"), (10, 10, 10))
    pc = MI.precheck_stl(p)
    assert pc["ok"], pc
    assert pc["total"] == 12 and pc["bad"] == 0, pc
    return "%d 面 / 坏 0" % pc["total"]


def t_precheck_bad_rejected():
    """★ 0 法线 STL 必须被预检拦下（否则 SW 弹框卡死）。"""
    p = os.path.join(OUT, "pre_bad.stl")
    os.makedirs(OUT, exist_ok=True)
    with open(p, "w", encoding="ascii", newline="\n") as f:
        f.write("solid bad\n")
        for _ in range(12):
            f.write("facet normal 0 0 0\n  outer loop\n")
            f.write("    vertex 0 0 0\n    vertex 10 0 0\n    vertex 0 10 0\n")
            f.write("  endloop\nendfacet\n")
        f.write("endsolid bad\n")
    pc = MI.precheck_stl(p)
    assert not pc["ok"], "0 法线必须被拒"
    assert pc["bad"] == 12 and pc["total"] == 12, pc
    assert "模态框" in pc["reason"], pc["reason"]
    # import_mesh 层面也要拒绝（sw=None 也不会走到 COM）
    rep = MI.import_mesh(None, p)
    assert rep["ok"] is False, rep
    assert any(c["id"] == "precheck" and c["status"] == "fail"
               for c in rep["checks"]), rep["checks"]
    return "12/12 坏法线 → 拒绝"


def t_repair_normals():
    """repair_stl_normals 能把 0 法线修成真法线。"""
    bad = os.path.join(OUT, "pre_bad.stl")
    fixed, st = MI.repair_stl_normals(bad, os.path.join(OUT, "pre_bad_fixed.stl"))
    pc = MI.precheck_stl(fixed)
    assert pc["ok"], pc
    assert st["triangles"] == 12, st
    return "修 %d 面，翻转 %d 面，预检通过" % (st["triangles"], st["flipped"])


def t_binary_stl_precheck():
    """二进制 STL 也要能预检。"""
    good = MI.write_test_stl(os.path.join(OUT, "pre_bin.stl"), (5, 5, 5),
                             binary=True)
    pc = MI.precheck_stl(good)
    assert pc["ok"] and pc["total"] == 12, pc
    return "%d B / %d 面" % (os.path.getsize(good), pc["total"])


def t_stl_binary():
    p = MI.write_test_stl(os.path.join(OUT, "static_box_bin.stl"), (10, 10, 10),
                          binary=True)
    sz = os.path.getsize(p)
    assert sz == 84 + 50 * 12, "二进制 STL 大小应为 84+50*12=%d，实得 %d" % (684, sz)
    return "%d B" % sz


def t_dispatch_variant():
    """第 3 参必须是真正的空 IDispatch，不是 None。

    ★ pywin32 的 repr 是 `VARIANT(9, None)`，9 = VT_DISPATCH；
      不暴露 .vt，只能靠 swlib.variant_vt 从 repr 解。
    """
    import pythoncom
    import swlib as L
    v = MI.create_empty_dispatch_variant()
    assert v is not None, "构造器返回 None"
    vt = L.variant_vt(v)
    assert vt == pythoncom.VT_DISPATCH, \
        "应为 VT_DISPATCH(%d)，实得 %s（%r）" % (pythoncom.VT_DISPATCH, vt, v)
    assert v.value is None, "空 dispatch 的 value 应为 None"
    return "%r → VT_DISPATCH" % v


def t_glb_conversion():
    """GLB 不给硬失败，给可执行转换命令。"""
    c = MI.convert_glb_to_obj(r"D:\ref\part.glb")
    assert c and c["commands"], c
    assert any("assimp" in x for x in c["commands"]), c["commands"]
    assert MI.convert_glb_to_obj(r"D:\ref\part.stl") is None, "STL 不该要转换"
    return "%d 条命令" % len(c["commands"])


def t_unsupported_rejected():
    """GLB 直接 import_mesh → ok=False 且带 convert。"""
    p = os.path.join(OUT, "fake.glb")
    os.makedirs(OUT, exist_ok=True)
    open(p, "wb").close()
    rep = MI.import_mesh(None, p)          # sw 不用，格式检查在前
    assert rep["ok"] is False
    assert rep.get("convert"), rep
    return "GLB 拦下并给转换路径"


def t_missing_file():
    rep = MI.import_mesh(None, os.path.join(OUT, "no_such.stl"))
    assert rep["ok"] is False
    assert any(c["id"] == "file_exists" and c["status"] == "fail"
               for c in rep["checks"])
    return "缺文件正确失败"


# ---------------------------------------------------------------- SW
def _sw():
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    try:
        sw.CloseAllDocuments(True)
    except Exception:
        pass
    return sw


def t_import_bbox_exact():
    """★ 核心：20×30×40 STL 导入后 bbox 精确等于 (0,0,0,20,30,40) mm。"""
    sw = _sw()
    p = MI.write_test_stl(os.path.join(OUT, "box20x30x40.stl"), (20, 30, 40))
    rep = MI.import_mesh(sw, p, expect_bbox_mm=(0, 0, 0, 20, 30, 40),
                         bbox_tol_mm=0.5)
    print("       " + MI.render(rep).replace("\n", "\n       "))
    assert rep["ok"], "导入应成功: %s" % [c for c in rep["checks"]
                                          if c["status"] == "fail"]
    b = rep["bbox_mm"]
    assert b == [0.0, 0.0, 0.0, 20.0, 30.0, 40.0], "bbox 应为精确值，实得 %s" % (b,)
    assert rep["mesh_bodies"] >= 1, "网格体数应 ≥1，实得 %s" % rep["mesh_bodies"]
    return "bbox=(0,0,0,20,30,40) mesh_bodies=%d" % rep["mesh_bodies"]


def t_getbodies_invisible():
    """★ 坑的实证：GetBodies2 看不到网格体，必须走 MeshBodyFeature 链。"""
    import swlib_v2 as V
    sw = _sw()
    p = os.path.join(OUT, "box20x30x40.stl")
    rep = MI.import_mesh(sw, p)
    doc = rep["doc"]
    n_solid, n_sheet = V.body_counts(doc)
    assert (n_solid, n_sheet) == (0, 0), \
        "网格件在 GetBodies2 里应为 (0,0)，实得 %s" % ((n_solid, n_sheet),)
    assert rep["mesh_bodies"] >= 1, "但 MeshBodyFeature 链应数得到"
    return "GetBodies2=(0,0) 而 mesh_bodies=%d" % rep["mesh_bodies"]


def t_no_parametric_tree():
    """网格件特征树里没有可编辑的草图/拉伸特征。"""
    import swlib_v2 as V
    sw = _sw()
    p = os.path.join(OUT, "box20x30x40.stl")
    rep = MI.import_mesh(sw, p)
    tree = V.feature_tree(rep["doc"])
    types = {t for _, t in tree}
    assert "MeshFeatureContainer" in types or "MeshBodyFeatureFolder" in types, \
        "应出现网格容器，实得 %s" % sorted(types)[:12]
    assert "ProfileFeature" not in types, "不该有草图（那才是参数化）"
    assert "Extrusion" not in types, "不该有拉伸特征"
    return "有 Mesh 容器，无 ProfileFeature/Extrusion"


def t_none_importdata_fails():
    """★ 坑的实证：第 3 参传 None 会失败（对照 create_empty_dispatch_variant）。"""
    import swlib as L
    sw = _sw()
    p = os.path.join(OUT, "box20x30x40.stl")
    failed = False
    try:
        err = L.byref_int(0)
        sw.LoadFile4(p, "r", None, err)
    except Exception as e:
        failed = True
        print("       None → %s" % str(e)[:90])
    assert failed, "传 None 竟然成功了？那说明坑记录有误，必须复核"
    # 对照：空 dispatch 能成
    rep = MI.import_mesh(sw, p)
    assert rep["ok"], "空 dispatch 应成功"
    return "None 失败 / 空 dispatch 成功"


def t_obj_import():
    """OBJ 也能导入（本机 SW2022 支持）。"""
    sw = _sw()
    obj = os.path.join(OUT, "box.obj")
    with open(obj, "w", encoding="ascii", newline="\n") as f:
        f.write("v 0 0 0\nv 12 0 0\nv 12 8 0\nv 0 8 0\n")
        f.write("v 0 0 6\nv 12 0 6\nv 12 8 6\nv 0 8 6\n")
        f.write("f 1 2 3\nf 1 3 4\nf 5 6 7\nf 5 7 8\n")
        f.write("f 1 2 6\nf 1 6 5\nf 2 3 7\nf 2 7 6\n")
        f.write("f 3 4 8\nf 3 8 7\nf 4 1 5\nf 4 5 8\n")
    rep = MI.import_mesh(sw, obj, expect_bbox_mm=(0, 0, 0, 12, 8, 6),
                         bbox_tol_mm=0.5)
    print("       " + MI.render(rep).replace("\n", "\n       "))
    assert rep["ok"], [c for c in rep["checks"] if c["status"] == "fail"]
    assert rep["bbox_mm"] == [0.0, 0.0, 0.0, 12.0, 8.0, 6.0], rep["bbox_mm"]
    return "OBJ 12×8×6 bbox 精确"


def t_arg_modes():
    """★ arg 是真正的导入模式开关：'r' / 's' / '' 三种都能导入且 bbox 一致。

    2026-11-21 清理掉 `doc_type` / `allow_solid` 两个假参数后，
    确认唯一有效的模式开关是 `arg`（LoadFile4 的 ArgString）。
    三种模式 GetBodies2 都是 (0,0) —— 网格体只能走 MeshBodyFeature 链。
    """
    sw = _sw()
    p = MI.write_test_stl(os.path.join(OUT, "arg_modes.stl"), (20, 30, 40))
    results = []
    for arg in (MI.ARG_REFERENCE, MI.ARG_SOLID, MI.ARG_DEFAULT):
        rep = MI.import_mesh(sw, p, arg=arg, expect_bbox_mm=(0, 0, 0, 20, 30, 40))
        results.append((arg, rep["ok"], tuple(rep["bbox_mm"]),
                        rep["mesh_bodies"]))
        print("       arg=%-3r ok=%s bbox=%s mesh_bodies=%s"
              % (arg, rep["ok"], rep["bbox_mm"], rep["mesh_bodies"]))
        assert rep["ok"], "arg=%r 导入失败" % arg
        assert tuple(rep["bbox_mm"]) == (0.0, 0.0, 0.0, 20.0, 30.0, 40.0), \
            "arg=%r bbox 不对: %s" % (arg, rep["bbox_mm"])
        assert rep["mesh_bodies"] >= 1
    # 三种模式结果必须一致（证明 arg 只影响内部表示，不影响几何）
    assert len({r[2] for r in results}) == 1, "三种 arg 的 bbox 不一致"
    return "3 种 arg 全部 bbox 精确、mesh_bodies≥1"


def t_no_fake_params():
    """★ import_mesh 不能有声明却不用的假参数。

    `doc_type` / `allow_solid` 曾经声明了但从未被读取，调用方传了也不起作用。
    这类"假接口"比缺接口更坏 —— 它让人以为能控制行为。

    ★ 判据只看**函数签名和可执行代码**，不看 docstring ——
      清理记录里会提到这两个名字，那是说明不是引用。
    """
    import inspect
    params = list(inspect.signature(MI.import_mesh).parameters)
    for bad in ("doc_type", "allow_solid"):
        assert bad not in params, "假参数 %s 又回来了" % bad
    assert "arg" in params, "真正的模式开关 arg 不能丢"

    # 剥掉 docstring 后再查代码里有没有读取这两个名字
    src = open(MI.__file__, encoding="utf-8").read()
    start = src.find("def import_mesh")
    end = src.find("\ndef ", start + 10)
    body = src[start:end if end > 0 else len(src)]
    # 去掉三引号 docstring（r"""...""" 或 """..."""）
    import re
    body = re.sub(r'r?""".*?"""', "", body, flags=re.S)
    body = re.sub(r"#.*", "", body)          # 去掉行注释
    for bad in ("doc_type", "allow_solid"):
        assert bad not in body, "import_mesh 代码里仍引用 %s" % bad
    return "假参数已清除，arg 保留"


def main():
    static_only = "--static" in sys.argv
    print("=== mesh_import 套件 ===\n")
    print("-- 静态 --")
    chk("ASCII STL 生成（含真法线）", t_stl_writer)
    chk("二进制 STL 生成", t_stl_binary)
    chk("★ 法线预检（正常）", t_precheck_good)
    chk("★ 0 法线被拦下（防模态框卡死）", t_precheck_bad_rejected)
    chk("法线自动修复", t_repair_normals)
    chk("二进制 STL 预检", t_binary_stl_precheck)
    chk("空 dispatch VARIANT", t_dispatch_variant)
    chk("GLB 转换命令", t_glb_conversion)
    chk("GLB 被拦下", t_unsupported_rejected)
    chk("缺文件失败", t_missing_file)
    chk("★ 无假参数", t_no_fake_params)

    if not static_only:
        print("\n-- 真机（SW2022 LoadFile4）--")
        chk("★ STL 导入 bbox 精确", t_import_bbox_exact)
        chk("★ GetBodies2 看不到网格体", t_getbodies_invisible)
        chk("无参数化特征树", t_no_parametric_tree)
        chk("★ 第 3 参 None 会失败", t_none_importdata_fails)
        chk("★ arg 三种模式", t_arg_modes)
        chk("OBJ 导入", t_obj_import)

    print()
    if fails:
        print("失败 %d 项: %s" % (len(fails), fails))
        sys.exit(1)
    print("MESH IMPORT PASS")


if __name__ == "__main__":
    main()
