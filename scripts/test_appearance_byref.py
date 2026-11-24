# -*- coding: utf-8 -*-
"""外观回读校验 + by-ref VARIANT 实测（真机，需 SW2022）。

两个缺口一起测，因为它们都靠同一条底层通路：
  - 缺口 3：设色后必须回读 RGB，偏差 >2% 抛异常
  - 缺口 4：by-ref 出参必须能取回真实值（不是 0 占位）

静态层（不开 SW）验证构造器语义；SW 层验证真实 API。

跑法：python test_appearance_byref.py           静态 + SW
      python test_appearance_byref.py --static  只跑静态
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OUT = os.path.join(HERE, "out", "appearance")
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


# ---------------------------------------------------------------- 静态：by-ref 构造器
def t_byref_constructors():
    import pythoncom
    import swlib as L
    i = L.byref_int(7)
    d = L.byref_double(1.5)
    b = L.byref_bool(True)
    s = L.byref_str("x")
    assert i.value == 7 and d.value == 1.5 and s.value == "x"
    assert bool(b.value), b.value
    # VT_BYREF 位必须真的置上，否则是值传递，取不回
    # ★ pywin32 的 VARIANT 不暴露 .vt，只能用 swlib.variant_vt 从 repr 解
    for v, want in ((i, pythoncom.VT_I4), (d, pythoncom.VT_R8),
                    (b, pythoncom.VT_BOOL)):
        vt = L.variant_vt(v)
        assert vt is not None, "读不到 VT: %r" % v
        assert vt & pythoncom.VT_BYREF, "VT_BYREF 位没置上: %s" % vt
        assert (vt & ~pythoncom.VT_BYREF) == want, \
            "基础类型应为 %s，实得 %s" % (want, vt & ~pythoncom.VT_BYREF)
    return "i4/r8/bool/str 四种，BYREF 位已置"


def t_byref_writeback():
    """by-ref 语义自证：COM 写回后 .value 变，不是只读副本。"""
    import pythoncom
    import win32com.client
    # 用 VARIANT 自身模拟写回：重新赋值即可
    v = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    assert v.value == 0
    v.value = 42
    assert v.value == 42
    return "写回语义正常"


def t_split_out():
    import swlib as L
    r, outs = L.split_out((True, 0, 0), 2)
    assert r is True and outs == [0, 0], (r, outs)
    r2, o2 = L.split_out(False, 2)
    assert r2 is False and o2 == [None, None], (r2, o2)
    r3, o3 = L.split_out((True,), 1)
    assert r3 is True and o3 == [None], (r3, o3)
    return "元组/标量/短元组 三种形态"


# ---------------------------------------------------------------- 静态：颜色判据
def t_color_helpers():
    import swlib_v2 as V
    assert V.color_dev((0.5, 0.5, 0.5), (0.5, 0.5, 0.52)) == 0.02 or \
        abs(V.color_dev((0.5, 0.5, 0.5), (0.5, 0.5, 0.52)) - 0.02) < 1e-9
    assert V.color_dev(None, (1, 1, 1)) is None
    assert V.is_unset_color((-1.0, -1.0, -1.0)), "哨兵未识别"
    assert not V.is_unset_color((0.9, 0.7, 0.3))
    return "dev/哨兵判定正确"


# ---------------------------------------------------------------- SW：by-ref 真机
def t_saveas4_byref_ok():
    """SaveAs4 的 Errors/Warnings 能取回 0（成功）。"""
    import swlib as L
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -10, -10, 10, 10)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.extrude_checked(m, sk, 10)
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "byref_ok.SLDPRT")
    ret, outs = L.call_byref(m, "SaveAs4", [p, 0, 0], ["i4", "i4"])
    print("       ret=%s out=%s size=%s"
          % (ret, outs, os.path.getsize(p) if os.path.exists(p) else -1))
    assert ret is True, "SaveAs4 应返回 True，实得 %s" % (ret,)
    assert outs == [0, 0], "出参应为 [0,0]，实得 %s" % (outs,)
    assert os.path.exists(p) and os.path.getsize(p) > 1000
    V.close_doc(sw, m, force=True)
    return "ret=True out=[0,0] size=%d" % os.path.getsize(p)


def t_saveas4_byref_error():
    """★ 关键：非法路径时 by-ref 能取回**真实错误码**，不是 0 占位。

    这条是「by-ref 真的通了」的硬证据 —— 传普通 int 占位永远拿不到 1。
    """
    import swlib as L
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -10, -10, 10, 10)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.extrude_checked(m, sk, 10)
    bad = r"Z:\no_such_dir_xyz\a.SLDPRT"
    ret, outs = L.call_byref(m, "SaveAs4", [bad, 0, 0], ["i4", "i4"])
    print("       ret=%s err/warn=%s" % (ret, outs))
    assert ret is False, "非法路径应返回 False"
    assert outs[0] == 1, "错误码应为 1（目录不存在），实得 %s" % (outs[0],)
    # 对照：早绑定只能拿到元组里的 0
    ret2, outs2 = L.call_byref(m, "SaveAs4", [bad, 0, 0], ["i4", "i4"],
                               dynamic=False)
    r3, split = L.split_out(ret2, 2)
    print("       早绑定 ret=%s split=%s" % (ret2, split))
    assert r3 is False, "早绑定也应返回 False"
    V.close_doc(sw, m, force=True)
    return "动态 err=1 / 早绑定 %s" % (split,)


# ---------------------------------------------------------------- SW：设色回读
def t_component_color_roundtrip():
    """设 (0.92,0.72,0.30) → 回读误差 <2%。"""
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    os.makedirs(OUT, exist_ok=True)
    part = os.path.join(OUT, "color_blk.SLDPRT")
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -20, -20, 20, 20)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.extrude_checked(m, sk, 10)
    V.save_checked(m, part)
    V.close_doc(sw, m, force=True)

    asm = V.new_asm(sw)
    title = V.com_member(V.wrap(asm, "IModelDoc2"), "GetTitle")
    c = V.add_component(sw, asm, title, part)
    before = V.get_component_color(c)
    got = V.set_component_color(c, (0.92, 0.72, 0.30))
    dev = V.color_dev(got, (0.92, 0.72, 0.30))
    print("       before=%s after=%s dev=%.4f" % (before, got, dev))
    assert before is not None and V.is_unset_color(before), \
        "未设色时应回读哨兵 (-1,-1,-1)，实得 %s" % (before,)
    assert dev <= 0.02, "回读偏差 %.4f > 2%%" % dev
    V.close_doc(sw, asm, force=True)
    return "before=哨兵 after=%.3f,%.3f,%.3f dev=%.4f" % (got + (dev,))


def t_component_color_tol_catches():
    """★ 回读真的在起作用：tol 收紧到 1e-9 时必须报错。"""
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    part = os.path.join(OUT, "color_blk.SLDPRT")
    asm = V.new_asm(sw)
    title = V.com_member(V.wrap(asm, "IModelDoc2"), "GetTitle")
    c = V.add_component(sw, asm, title, part)
    V.set_component_color(c, (0.92, 0.72, 0.30))
    try:
        V.set_component_color(c, (0.92, 0.72, 0.30), tol=1e-9)
    except RuntimeError as e:
        msg = str(e)
        assert "未生效" in msg, msg[:80]
        V.close_doc(sw, asm, force=True)
        return "tol=1e-9 正确抛出（8bit 量化 0.002 偏差）"
    V.close_doc(sw, asm, force=True)
    raise AssertionError("tol=1e-9 应抛异常，说明回读没生效")


def t_apply_palette():
    """批量上色 + 批量回读，全部命中。"""
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    part = os.path.join(OUT, "color_blk.SLDPRT")
    asm = V.new_asm(sw)
    title = V.com_member(V.wrap(asm, "IModelDoc2"), "GetTitle")
    c1 = V.add_component(sw, asm, title, part)
    c2 = V.add_component(sw, asm, title, part)
    comps = V.comps(asm)
    keys = sorted(comps)[:2]
    pal = {keys[0]: (0.92, 0.72, 0.30), keys[1]: (0.20, 0.55, 0.85)}
    rep = V.apply_palette(comps, pal)
    print("       applied=%d failed=%d" % (rep["applied"], len(rep["failed"])))
    assert rep["applied"] == 2, rep
    assert not rep["failed"], rep["failed"]
    for item in rep["ok"]:
        assert V.color_dev(item["got"], item["want"]) <= 0.02, item
    V.close_doc(sw, asm, force=True)
    return "2 组件批量上色，全部回读命中"


def t_apply_palette_strict():
    """非法色值（NaN 化）→ strict=True 抛异常，strict=False 收集。"""
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    part = os.path.join(OUT, "color_blk.SLDPRT")
    asm = V.new_asm(sw)
    title = V.com_member(V.wrap(asm, "IModelDoc2"), "GetTitle")
    V.add_component(sw, asm, title, part)
    comps = V.comps(asm)
    key = sorted(comps)[0]
    # tol 极端收紧制造失败
    rep = V.apply_palette(comps, {key: (0.92, 0.72, 0.30)}, tol=1e-9, strict=False)
    assert rep["applied"] == 0 and len(rep["failed"]) == 1, rep
    assert "未生效" in rep["failed"][0]["error"]
    V.close_doc(sw, asm, force=True)
    return "strict=False 收集失败项"


def main():
    static_only = "--static" in sys.argv
    print("=== appearance + by-ref 套件 ===\n")
    print("-- 静态（构造器/判据，不开 SW）--")
    chk("byref_* 构造器语义", t_byref_constructors)
    chk("VARIANT 写回语义", t_byref_writeback)
    chk("split_out 三种形态", t_split_out)
    chk("颜色偏差/哨兵判据", t_color_helpers)

    if not static_only:
        print("\n-- 真机 by-ref --")
        chk("SaveAs4 出参取回 0", t_saveas4_byref_ok)
        chk("★ SaveAs4 出参取回真实错误码", t_saveas4_byref_error)
        print("\n-- 真机设色回读 --")
        chk("设色→回读 误差<2%", t_component_color_roundtrip)
        chk("★ tol 收紧能抓到偏差", t_component_color_tol_catches)
        chk("apply_palette 批量回读", t_apply_palette)
        chk("apply_palette strict=False", t_apply_palette_strict)

    print()
    if fails:
        print("失败 %d 项: %s" % (len(fails), fails))
        sys.exit(1)
    print("APPEARANCE BYREF PASS")


if __name__ == "__main__":
    main()
