# -*- coding: utf-8 -*-
"""结果自审查测试 —— 像素判据（静态）+ 真机四视图（SW）。

静态层用 Pillow 合成图，不需要 SW，0.5 秒跑完：
  - 空白图 → FAIL（内容占比不足）
  - 四张同图 → FAIL（md5 不互异）
  - 单色块 → WARN（色数不足）
  - 缺文件 / 0 字节 → FAIL
  - 正常图 → PASS

SW 层（本机 SW2022 才跑）：
  - 圆柱 → run_review status=pass，四视图 md5 互异，报告落盘
  - 空零件（无实体） → status=fail（内容占比不足）
  - expected_outputs 缺文件 → status=fail

跑法：python test_review.py          静态 + SW
      python test_review.py --static  只跑静态
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import review as RV

OUT = os.path.join(HERE, "out", "review")
fails = []


def chk(name, fn):
    try:
        note = fn()
        print("  [OK] %-44s %s" % (name, note or ""))
    except AssertionError as e:
        print("  [XX] %-44s %s" % (name, e))
        fails.append(name)
    except Exception as e:
        print("  [XX] %-44s %s: %s" % (name, type(e).__name__, e))
        fails.append(name)


# ---------------------------------------------------------------- 合成图
def _mk(dirname, name, kind):
    from PIL import Image, ImageDraw
    p = os.path.join(dirname, name)
    im = Image.new("RGB", (600, 400), (245, 245, 245))
    d = ImageDraw.Draw(im)
    if kind == "blank":
        pass
    elif kind == "shape":
        # 真机渲染是多色阶的（实测 19~58 色），合成图也要有层次，否则测不出"防单色"
        for i in range(24):
            t = i / 24.0
            d.ellipse((150 + t * 12, 100 + t * 8, 450 - t * 12, 300 - t * 8),
                      fill=(int(90 + t * 120), int(130 + t * 90), int(190 - t * 60)))
        d.ellipse((150, 100, 450, 300), outline=(40, 60, 90), width=4)
        d.line((150, 200, 450, 200), fill=(200, 200, 210), width=2)
        d.rectangle((180, 130, 240, 170), fill=(230, 200, 120), outline=(120, 90, 30))
    elif kind == "solid":
        d.rectangle((100, 80, 500, 320), fill=(120, 120, 120))
    elif kind == "clipped":
        d.rectangle((0, 0, 600, 400), fill=(245, 245, 245))
        d.rectangle((0, 0, 599, 399), outline=(30, 30, 30), width=6)
        d.rectangle((0, 0, 300, 200), fill=(90, 130, 190))
    im.save(p)
    return p


# ---------------------------------------------------------------- 静态用例
def t_blank_fails():
    d = tempfile.mkdtemp()
    p = _mk(d, "blank.png", "blank")
    rv = RV.review_images({"iso": p})
    assert rv.status() == RV.FAIL, "空白图应 FAIL，实得 %s" % rv.status()
    assert any("空白图" in i for i in rv.issues), rv.issues
    return "空白图 → FAIL"


def t_identical_fails():
    d = tempfile.mkdtemp()
    same = _mk(d, "a.png", "shape")
    paths = {}
    for i, k in enumerate(("iso", "front", "top", "right")):
        q = os.path.join(d, "%s.png" % k)
        with open(same, "rb") as f:
            data = f.read()
        with open(q, "wb") as f:
            f.write(data)
        paths[k] = q
    rv = RV.review_images(paths)
    assert rv.status() == RV.FAIL, "四张同图应 FAIL，实得 %s" % rv.status()
    assert any("views_distinct" in i for i in rv.issues), rv.issues
    return "四张同图 → FAIL（md5 不互异）"


def t_single_color_warns():
    d = tempfile.mkdtemp()
    p = _mk(d, "solid.png", "solid")
    rv = RV.review_images({"iso": p})
    st = [c["status"] for c in rv.checks if c["id"].startswith("color_")]
    assert st and st[0] == RV.WARN, "单色块应 WARN，实得 %s" % st
    return "单色块 → WARN"


def t_good_passes():
    d = tempfile.mkdtemp()
    paths = {}
    for i, k in enumerate(("iso", "front", "top", "right")):
        p = _mk(d, "%s.png" % k, "shape")
        # 轻微差异，模拟不同视图
        from PIL import Image
        im = Image.open(p)
        im = im.rotate(i * 3, fillcolor=(245, 245, 245))
        im.save(p)
        paths[k] = p
    rv = RV.review_images(paths)
    assert rv.status() == RV.PASS, "正常图应 PASS，实得 %s %s" % (rv.status(), rv.issues)
    return "四视图正常 → PASS"


def t_missing_file_fails():
    d = tempfile.mkdtemp()
    rv = RV.review_files([os.path.join(d, "nope.SLDPRT")])
    assert rv.status() == RV.FAIL
    empty = os.path.join(d, "empty.SLDPRT")
    open(empty, "wb").close()
    rv2 = RV.review_files([empty])
    assert rv2.status() == RV.FAIL, "0 字节应 FAIL"
    return "缺失/0 字节 → FAIL"


def t_no_expected_fails():
    rv = RV.review_files(None)
    assert rv.status() == RV.FAIL, "未声明交付清单必须 FAIL（无法验证≠通过）"
    return "未声明清单 → FAIL"


def t_clip_detected():
    d = tempfile.mkdtemp()
    p = _mk(d, "clip.png", "clipped")
    st = RV.image_stats(p)
    assert st["clipped_edges"], "贴边图应检测出 clipped_edges"
    return "贴边 → %s" % ",".join(st["clipped_edges"])


def t_gate_conversion():
    d = tempfile.mkdtemp()
    p = _mk(d, "blank.png", "blank")
    rep = RV.review_images({"iso": p}).to_dict()
    g = RV.to_gate(rep)
    assert g.verdict().status == "fail", g.verdict().status
    return "FAIL 报告 → gate fail"


def t_report_schema():
    d = tempfile.mkdtemp()
    paths = {k: _mk(d, "%s.png" % k, "shape") for k in ("iso", "front")}
    rep = RV.review_images(paths).to_dict()
    for k in ("status", "checks", "issues", "views", "evaluation"):
        assert k in rep, "报告缺 %s" % k
    assert rep["evaluation"]["status"] == rep["status"]
    assert json.dumps(rep, ensure_ascii=False)
    return "status/checks/issues/views/evaluation 齐"


# ---------------------------------------------------------------- SW 用例
def t_sw_cylinder_pass():
    """真机：圆柱四视图 → pass，md5 互异，报告落盘。"""
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Front Plane")
        V.circle(skm, 0, 0, 25)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.extrude_checked(m, sk, 50)
    os.makedirs(OUT, exist_ok=True)
    part = os.path.join(OUT, "rev_cyl.SLDPRT")
    V.save_checked(m, part)
    rep, path = RV.run_review(m, OUT, basename="rev_cyl",
                              expected_outputs=[part], sw=sw)
    print("       " + RV.render(rep).replace("\n", "\n       "))
    assert os.path.exists(path), "报告未落盘"
    assert rep["status"] == RV.PASS, "圆柱应 pass，实得 %s %s" % (rep["status"], rep["issues"])
    md5s = {v.get("md5") for v in rep["views"].values() if v.get("md5")}
    assert len(md5s) == 4, "四视图 md5 应互异，实得 %d" % len(md5s)
    V.close_doc(sw, m, force=True)
    return "status=pass / 4 个不同 md5 / %s" % os.path.basename(path)


def t_sw_empty_fails():
    """空零件（无实体）→ 内容占比不足 → fail。"""
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m = V.new_part(sw)
    rep, _ = RV.run_review(m, OUT, basename="rev_empty", sw=sw,
                           expected_outputs=[], use_trace=False)
    assert rep["status"] == RV.FAIL, "空模型应 fail，实得 %s" % rep["status"]
    V.close_doc(sw, m, force=True)
    return "空模型 → fail"


def t_sw_missing_output_fails():
    """交付文件不存在 → fail（几何再好也不能交付）。"""
    import swlib_v2 as V
    sw = V.connect(version=2022, wait_ready=30, verbose=False)
    m = V.new_part(sw)
    with V.addtoDB(m) as skm:
        V.L.new_sketch(m, "Top Plane")
        V.L.rect(skm, -20, -20, 20, 20)
        sk = V.last_sketch_name(m)
        skm.InsertSketch(True)
        V.extrude_checked(m, sk, 20)
    rep, _ = RV.run_review(m, OUT, basename="rev_missing", sw=sw, use_trace=False,
                           expected_outputs=[os.path.join(OUT, "no_such_file.SLDPRT")])
    assert rep["status"] == RV.FAIL, "缺交付文件应 fail"
    assert any("no_such_file" in i for i in rep["issues"]), rep["issues"]
    V.close_doc(sw, m, force=True)
    return "缺交付文件 → fail"


def main():
    static_only = "--static" in sys.argv
    print("=== review 套件 ===\n")
    print("-- 静态（像素判据，不开 SW）--")
    chk("空白图 → FAIL", t_blank_fails)
    chk("四张同图 → FAIL", t_identical_fails)
    chk("单色块 → WARN", t_single_color_warns)
    chk("正常四视图 → PASS", t_good_passes)
    chk("缺失/0 字节 → FAIL", t_missing_file_fails)
    chk("未声明清单 → FAIL", t_no_expected_fails)
    chk("贴边裁切可检测", t_clip_detected)
    chk("报告转 verify_gate", t_gate_conversion)
    chk("报告字段完整", t_report_schema)

    if not static_only:
        print("\n-- 真机（SW2022 四视图）--")
        chk("圆柱 run_review → pass", t_sw_cylinder_pass)
        chk("空模型 → fail", t_sw_empty_fails)
        chk("缺交付文件 → fail", t_sw_missing_output_fails)

    print()
    if fails:
        print("失败 %d 项: %s" % (len(fails), fails))
        sys.exit(1)
    print("REVIEW PASS")


if __name__ == "__main__":
    main()
