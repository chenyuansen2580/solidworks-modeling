# -*- coding: utf-8 -*-
"""执行 Trace 套件

守三件事：
  1. 每步留痕：入参、产出、证据、耗时、失败位置
  2. 失败不吞异常：step 记 fail，异常继续向上抛
  3. 可审计可回放：序列化往返后信息不丢

跑法：python test_exec_trace.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import exec_trace as ET   # noqa: E402

fails = []


def chk(name, fn):
    try:
        fn()
        print("  [OK] %s" % name)
    except AssertionError as e:
        print("  [XX] %-42s %s" % (name, e))
        fails.append(name)
    except Exception as e:
        print("  [XX] %-42s %s: %s" % (name, type(e).__name__, e))
        fails.append(name)


# ---------------------------------------------------------------- 纯逻辑
def t_basic_record():
    tr = ET.Trace("t1")
    tr.env(sw="2022", python="3.12")
    with tr.step("a", depth=10) as s:
        s.output("volume", 1000.0)
        s.ev("dev_pct", 0.0)
    st = tr.steps[0]
    assert st.name == "a" and st.seq == 1
    assert st.inputs == {"depth": 10}
    assert st.outputs["volume"] == 1000.0
    assert st.evidence["dev_pct"] == 0.0
    assert tr.passed


def t_failure_recorded_and_reraised():
    """★ 失败要记录，但异常不能吞"""
    tr = ET.Trace("t2")
    raised = False
    try:
        with tr.step("boom") as s:
            raise ValueError("故意失败")
    except ValueError:
        raised = True
    assert raised, "异常必须继续向上抛"
    st = tr.steps[0]
    assert st.status == ET.FAIL
    assert "故意失败" in st.error
    assert st.evidence.get("fail_at"), "应记录失败源码位置"
    assert not tr.passed


def t_empty_is_blocked():
    """空 trace = 无法验证 ≠ PASS"""
    assert ET.Trace("empty").verdict() == ET.BLOCKED
    assert not ET.Trace("empty").passed


def t_skip_and_note():
    tr = ET.Trace("t3")
    with tr.step("ok1"):
        pass
    tr.note("n1", key="v")
    tr.skip("s1", "不需要")
    by = {s.name: s for s in tr.steps}
    assert by["n1"].kind == ET.KIND_NOTE
    assert by["s1"].status == ET.SKIP
    assert tr.passed, "skip/note 不该让整体失败"


def t_summary_and_verdict():
    tr = ET.Trace("t4")
    with tr.step("a"):
        pass
    with tr.step("b"):
        pass
    sm = tr.summary()
    assert sm["steps"] == 2
    assert sm["verdict"] == ET.OK
    assert sm["by_status"][ET.OK] == 2
    assert sm["failed"] == []


def t_serialize_roundtrip():
    tr = ET.Trace("t5")
    tr.env(sw="2022")
    with tr.step("a", depth=5) as s:
        s.output("vol", 123.0)
        s.ev("dev", 0.01)
    try:
        with tr.step("b"):
            raise RuntimeError("x")
    except RuntimeError:
        pass
    p = os.path.join(tempfile.mkdtemp(), "trace.json")
    tr.save(p)
    assert os.path.getsize(p) > 100
    t2 = ET.Trace.load(p)
    assert len(t2.steps) == 2
    by = {s.name: s for s in t2.steps}
    assert by["a"].inputs["depth"] == 5
    assert by["a"].outputs["vol"] == 123.0
    assert by["b"].status == ET.FAIL
    assert t2.env_info["sw"] == "2022"
    assert t2.verdict() == ET.FAIL


def t_json_valid():
    tr = ET.Trace("t6")
    with tr.step("a") as s:
        s.ev("k", "v")
    d = json.loads(tr.to_json())
    assert d["task"] == "t6"
    assert d["verdict"] == ET.OK
    assert len(d["steps"]) == 1
    assert d["steps"][0]["duration"] >= 0


def t_timed_helper():
    tr = ET.Trace("t7")
    r = ET.timed(tr, "calc", lambda: {"volume": 42.0})
    assert r["volume"] == 42.0
    assert tr.steps[0].outputs["volume"] == 42.0

    def boom():
        raise ValueError("helper fail")
    try:
        ET.timed(tr, "boom", boom)
    except ValueError:
        pass
    assert tr.steps[1].status == ET.FAIL


def t_require_ok():
    tr = ET.Trace("t8")
    with tr.step("a"):
        pass
    assert tr.require_ok() is True

    tr2 = ET.Trace("t9")
    try:
        with tr2.step("bad"):
            raise RuntimeError("x")
    except RuntimeError:
        pass
    try:
        tr2.require_ok()
        raise AssertionError("应抛 SystemExit")
    except SystemExit:
        pass


# ---------------------------------------------------------------- 真实 SW
def t_real_modeling_trace():
    """★ 真实建模：每步记体积，失败能定位到具体步骤"""
    import pythoncom
    import swlib_v2 as V

    pythoncom.CoInitialize()
    sw = V.connect(version=2022, verbose=False, warn_multi=False, wait_ready=30)

    tr = ET.Trace("real_cylinder")
    tr.env(sw=str(V.com_member(sw, "RevisionNumber")), python=sys.version.split()[0])

    m = V.new_part(sw)
    try:
        # ① 拉伸
        with tr.step("extrude", kind=ET.KIND_BUILD, depth=50) as s:
            with V.addtoDB(m) as skm:
                V.L.new_sketch(m, "Front Plane")
                V.circle(skm, 0, 0, 25)
                sk = V.last_sketch_name(m)
                skm.InsertSketch(True)
            V.extrude_checked(m, sk, 50)
            v = V.volume_mm3(m)
            s.output("volume", round(v, 2))

        # ② 体积校验
        with tr.step("verify_volume", kind=ET.KIND_VERIFY) as s:
            theory = 3.14159265358979 * 25 * 25 * 50
            ok, got, dev = V.volume_check(m, theory)
            s.output("measured", round(got, 2))
            s.ev("theory", round(theory, 2))
            s.ev("dev_pct", round(dev, 4))
            assert ok, "体积偏差 %.4f%%" % dev

        # ③ 实体数
        with tr.step("verify_bodies", kind=ET.KIND_VERIFY) as s:
            sol, sh = V.body_counts(m)
            s.ev("solids", sol)
            s.ev("sheets", sh)
            assert sol == 1 and sh == 0

        # ④ 故意失败的步骤（验证 fail_at 能定位）
        try:
            with tr.step("intentional_fail") as s:
                raise RuntimeError("模拟建模失败")
        except RuntimeError:
            pass
    finally:
        V.close_doc(sw, m, force=True)

    assert len(tr.steps) == 4
    by = {s.name: s for s in tr.steps}
    assert by["extrude"].status == ET.OK
    assert by["extrude"].outputs["volume"] > 0
    assert abs(by["verify_volume"].evidence["dev_pct"]) < 0.001
    assert by["verify_bodies"].evidence["solids"] == 1
    assert by["intentional_fail"].status == ET.FAIL
    fail_at = by["intentional_fail"].evidence.get("fail_at", "")
    assert ":" in fail_at, "fail_at 应是 file:line 格式，实得 %r" % fail_at

    # 存盘 + 回读
    p = os.path.join(HERE, "out", "trace", "real_cylinder.json")
    tr.save(p)
    t2 = ET.Trace.load(p)
    assert t2.verdict() == ET.FAIL
    assert t2.steps[0].outputs["volume"] > 0

    print("      真实 trace: 4 步，体积 %.2f，失败定位 %s"
          % (by["extrude"].outputs["volume"],
             by["intentional_fail"].evidence.get("fail_at")))


print("=== 执行 Trace 套件 ===\n")
chk("基础记录", t_basic_record)
chk("★ 失败记录且不吞异常", t_failure_recorded_and_reraised)
chk("空 trace → BLOCKED", t_empty_is_blocked)
chk("skip / note 不影响成败", t_skip_and_note)
chk("summary / verdict", t_summary_and_verdict)
chk("序列化往返", t_serialize_roundtrip)
chk("JSON 合法", t_json_valid)
chk("timed 辅助函数", t_timed_helper)
chk("require_ok 硬门禁", t_require_ok)

# ★ --offline：跳过真机建模那一项，让 Linux/CI（无 SW / 无 pywin32）也能跑
if "--offline" in sys.argv:
    print("  [--] 真实建模 trace    SKIP（--offline，需 SW）")
else:
    chk("★ 真实建模 trace", t_real_modeling_trace)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("EXEC TRACE PASS")
