# -*- coding: utf-8 -*-
"""交付新鲜度套件 —— 守「旧文件冒充本轮成果」

这是机制层的第一个门禁：不让旧成果混进本轮交付。
对标 wzyn 2230★ 的 artifact_freshness，但只做能落地的最小闭环。

跑法：python test_freshness.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import artifact_freshness as F   # noqa: E402

fails = []


def chk(name, fn):
    try:
        fn()
        print("  [OK] %s" % name)
    except AssertionError as e:
        print("  [XX] %-46s %s" % (name, e))
        fails.append(name)
    except Exception as e:
        print("  [XX] %-46s %s: %s" % (name, type(e).__name__, e))
        fails.append(name)


def mk(root, rel, data=b"x"):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return p


# ---------------------------------------------------------------- 单元场景
def s_new_file():
    """基线后新建文件 → producedThisRun=True"""
    tmp = tempfile.mkdtemp()
    try:
        base = F.scan(tmp)
        p = mk(tmp, "a.SLDPRT", b"new")
        r = F.diff(base, tmp, paths=[p])
        assert r.passed, r.report()
        assert r.items[0].produced_this_run is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def s_mtime_only():
    """只改 mtime → False（时间戳不算新）"""
    tmp = tempfile.mkdtemp()
    try:
        p = mk(tmp, "a.SLDPRT", b"same")
        base = F.scan(tmp)
        st = os.stat(p)
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        r = F.diff(base, tmp, paths=[p])
        assert not r.passed
        assert r.items[0].produced_this_run is False, "只改时间戳不该算新"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def s_content_changed():
    """内容变化 → True"""
    tmp = tempfile.mkdtemp()
    try:
        p = mk(tmp, "a.SLDPRT", b"v1")
        base = F.scan(tmp)
        mk(tmp, "a.SLDPRT", b"v2-different")
        r = F.diff(base, tmp, paths=[p])
        assert r.passed
        assert r.items[0].produced_this_run is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def s_old_file_rejected():
    """旧文件单独交付 → 拒"""
    tmp = tempfile.mkdtemp()
    try:
        p = mk(tmp, "old.SLDPRT", b"old")
        base = F.scan(tmp)
        r = F.diff(base, tmp, paths=[p])
        assert not r.passed, "旧文件不该 PASS"
        assert r.items[0].status == F.FAIL
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def s_new_cannot_mask_old():
    """★ 新文件不能掩盖旧文件"""
    tmp = tempfile.mkdtemp()
    try:
        old = mk(tmp, "old.SLDPRT", b"old")
        base = F.scan(tmp)
        new = mk(tmp, "new.SLDPRT", b"new")
        r = F.diff(base, tmp, paths=[new, old])
        assert not r.passed, "旧文件被新文件掩盖了"
        by = {i.path: i for i in r.items}
        assert by["new.SLDPRT"].produced_this_run is True
        assert by["old.SLDPRT"].produced_this_run is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def s_baseline_missing():
    """基线不完整 → BLOCKED（无法验证≠PASS）"""
    tmp = tempfile.mkdtemp()
    try:
        mk(tmp, "a.SLDPRT")
        bad = F.Baseline("/no/such", complete=False, errors=["root_not_dir"])
        r = F.diff(bad, tmp, paths=[os.path.join(tmp, "a.SLDPRT")])
        assert not r.passed
        assert all(i.status == F.BLOCKED for i in r.items)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def s_no_paths():
    """未声明交付清单 → BLOCKED（不猜）"""
    tmp = tempfile.mkdtemp()
    try:
        base = F.scan(tmp)
        mk(tmp, "a.SLDPRT")
        r = F.diff(base, tmp, paths=None)
        assert not r.passed
        assert any("未指定交付文件清单" in e for e in r.errors)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def s_unsupported_ext():
    """基线未覆盖的扩展名 → BLOCKED"""
    tmp = tempfile.mkdtemp()
    try:
        base = F.scan(tmp)
        p = mk(tmp, "note.txt", b"hi")          # .txt 不在扫描模式里
        r = F.diff(base, tmp, paths=[p])
        assert not r.passed
        assert r.items[0].produced_this_run is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def s_serialize_roundtrip():
    """基线可存盘/加载，跨进程比对"""
    tmp = tempfile.mkdtemp()
    try:
        mk(tmp, "a.SLDPRT", b"data")
        base = F.scan(tmp)
        bp = os.path.join(tmp, ".base.json")
        base.save(bp)
        b2 = F.Baseline.load(bp)
        assert b2.files["a.SLDPRT"].sha256 == base.files["a.SLDPRT"].sha256
        mk(tmp, "a.SLDPRT", b"changed")
        r = F.diff(b2, tmp, paths=[os.path.join(tmp, "a.SLDPRT")])
        assert r.passed, "从磁盘加载的基线应能识别变化"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def s_gate_integration():
    """接入 verify_gate：新鲜度 FAIL 必须让整体不过"""
    tmp = tempfile.mkdtemp()
    try:
        old = mk(tmp, "old.SLDPRT", b"old")
        base = F.scan(tmp)
        rep = F.diff(base, tmp, paths=[old])
        g = F.to_gate(rep, "fresh")
        assert g is not None, "verify_gate 不可用"
        v = g.verdict()
        assert not v.passed, "Gate 应判不过"
        assert v.status == "fail"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def s_merge_geometry_and_freshness():
    """★ 几何 PASS + 新鲜度 FAIL → 整体 FAIL（不能被几何通过掩盖）"""
    tmp = tempfile.mkdtemp()
    try:
        old = mk(tmp, "old.SLDPRT", b"old")
        base = F.scan(tmp)
        rep = F.diff(base, tmp, paths=[old])
        gf = F.to_gate(rep, "fresh")

        from verify_gate import Gate
        geo = Gate("geometry")
        geo.check("volume", True, "体积 dev 0.000%")
        geo.check("bodies", True, "实体数 1")

        merged = F.merge_gates([geo, gf], "delivery")
        v = merged.verdict()
        assert not v.passed, "几何通过 + 旧文件 不该判 PASS"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


print("=== 交付新鲜度套件 ===\n")
chk("新文件 → true", s_new_file)
chk("只改 mtime → false", s_mtime_only)
chk("内容变化 → true", s_content_changed)
chk("旧文件单独交付 → 拒", s_old_file_rejected)
chk("★ 新文件不能掩盖旧文件", s_new_cannot_mask_old)
chk("基线不完整 → BLOCKED", s_baseline_missing)
chk("未声明清单 → BLOCKED", s_no_paths)
chk("不支持扩展名 → BLOCKED", s_unsupported_ext)
chk("基线存盘/加载往返", s_serialize_roundtrip)
chk("接入 verify_gate", s_gate_integration)
chk("★ 几何PASS+新鲜度FAIL → 整体FAIL", s_merge_geometry_and_freshness)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("FRESHNESS PASS")
