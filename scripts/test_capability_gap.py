# -*- coding: utf-8 -*-
"""能力缺口协议套件

守两件事：
  1. 不会的能力 → 返回结构化 gap（不是裸异常），带替代方案 + 探测建议 + 后续步骤
  2. gap 里的 probe 建议，能在真实 COM 上验证是否支持

跑法：python test_capability_gap.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import capability_gap as CG   # noqa: E402

fails = []


def chk(name, fn):
    try:
        fn()
        print("  [OK] %s" % name)
    except AssertionError as e:
        print("  [XX] %-44s %s" % (name, e))
        fails.append(name)
    except Exception as e:
        print("  [XX] %-44s %s: %s" % (name, type(e).__name__, e))
        fails.append(name)


# ---------------------------------------------------------------- 纯逻辑
def t_verified_no_gap():
    assert CG.probe_capability("part.extrude") is None, "verified 不该有 gap"
    assert CG.probe_capability("part.revolve") is None
    assert CG.probe_capability("asm.fix") is None


def t_unknown_has_full_guidance():
    g = CG.probe_capability("part.thread")
    assert g.kind == CG.KIND_UNKNOWN
    assert g.alternatives, "unknown 必须给替代方案"
    assert g.probe, "unknown 必须给探测建议"
    assert g.doc_hints, "unknown 必须给文档指引"
    assert len(g.next_steps) == 5, "后续步骤应为 5 步"


def t_pilot_kind():
    g = CG.probe_capability("part.hole_wizard")
    assert g.kind == CG.KIND_PILOT_ONLY, g.kind
    assert any("cut_through" in c for c, _ in g.alternatives), "应建议普通切除替代"


def t_not_impl_kind():
    g = CG.probe_capability("surface.thicken")
    assert g.kind == CG.KIND_NOT_IMPLEMENTED
    assert any("extrude" in c or "shell" in c for c, _ in g.alternatives)


def t_require_passes_verified():
    assert CG.require("part.extrude") is True


def t_require_raises_structured():
    try:
        CG.require("part.hole_wizard")
        raise AssertionError("应抛 CapabilityGapError")
    except CG.CapabilityGapError as e:
        assert e.gap.requested == "part.hole_wizard"
        assert "CAPABILITY_GAP" in str(e)


def t_require_any():
    assert CG.require_any(["part.hole_wizard", "part.cut_through"]) == "part.cut_through"
    try:
        CG.require_any(["part.hole_wizard", "surface.thicken"])
        raise AssertionError("全不可用应抛")
    except CG.CapabilityGapError:
        pass


def t_json_roundtrip():
    g = CG.probe_capability("part.thread")
    d = json.loads(g.to_json())
    assert d["type"] == "CAPABILITY_GAP"
    assert d["requested"] == "part.thread"
    assert isinstance(d["alternatives"], list)
    assert isinstance(d["probe"], list)
    assert len(d["next_steps"]) == 5


def t_report_readable():
    g = CG.probe_capability("export.stl")
    r = g.report()
    for kw in ("CAPABILITY_GAP", "可用替代", "建议探测", "后续步骤"):
        assert kw in r, "报告缺 %s" % kw


def t_all_pilot_have_alternatives():
    """所有 pilot / not_impl 能力都应有替代方案，否则 Agent 会卡住"""
    import swlib_v2 as V
    missing = []
    for name, (lv, note) in V.CAPABILITIES.items():
        if lv in (V.PILOT, V.NOT_IMPLEMENTED):
            g = CG.probe_capability(name)
            if g and not g.alternatives:
                missing.append(name)
    assert not missing, "这些能力缺替代方案: %s" % missing


# ---------------------------------------------------------------- 真实 COM 探测
def t_com_probe_real():
    """真实探测：已验证的 API 应能读到，编造的应读不到"""
    import pythoncom
    import swlib_v2 as V
    pythoncom.CoInitialize()
    sw = V.connect(version=2022, verbose=False, warn_multi=False, wait_ready=30)

    # 真实存在的成员
    assert CG.com_has(sw, "IFeatureManager", "FeatureExtrusion3") or \
           CG.com_has(sw, "IFeatureManager", "HoleWizard5"), "IFeatureManager 应有建模方法"

    # 编造的成员
    assert not CG.com_has(sw, "IFeatureManager", "NoSuchMethodXYZ123"), \
        "编造的方法不该被探测到"

    # arity 探测
    n = CG.com_signature(sw, "IFeatureManager", "HoleWizard5")
    print("      HoleWizard5 参数个数: %s" % n)
    assert n is None or n >= 20, "HoleWizard5 应有 20+ 参数，实得 %s" % n

    # probe_all
    g = CG.probe_capability("part.hole_wizard")
    res = CG.probe_all(sw, g)
    print("      probe_all: %s" % [(i, m, ok) for i, m, ok in res])
    assert len(res) == len(g.probe)


def t_gap_guides_to_real_alternative():
    """★ gap 给的替代方案必须是真的 verified —— 否则引导 Agent 踩坑"""
    import swlib_v2 as V
    bad = []
    for name in ("part.hole_wizard", "surface.thicken", "export.stl",
                 "asm.mate.axis_concentric", "appearance.render"):
        g = CG.probe_capability(name)
        if not g:
            continue
        for cap, why in g.alternatives:
            lv, _ = V.capability(cap)
            if lv != V.VERIFIED and cap not in ("part.hole_wizard",):
                bad.append((name, cap, lv))
    # 允许替代方案本身是 pilot（说明里会标注），但不能全是 pilot
    assert len(bad) <= 2, "替代方案里 verified 太少: %s" % bad


print("=== 能力缺口协议套件 ===\n")
chk("verified 无 gap", t_verified_no_gap)
chk("unknown 有完整指引", t_unknown_has_full_guidance)
chk("pilot 类型判定", t_pilot_kind)
chk("not_impl 类型判定", t_not_impl_kind)
chk("require 放行 verified", t_require_passes_verified)
chk("require 抛结构化异常", t_require_raises_structured)
chk("require_any 候选回退", t_require_any)
chk("JSON 可序列化", t_json_roundtrip)
chk("report 可读", t_report_readable)
chk("★ 所有 pilot/not_impl 都有替代", t_all_pilot_have_alternatives)
chk("★ 替代方案指向真 verified", t_gap_guides_to_real_alternative)
# ★ --offline：跳过真机 COM 探测，静态层不应该启动 SW
if "--offline" in sys.argv:
    print("  [--] 真实 COM 探测        SKIP（--offline，需 SW）")
else:
    chk("真实 COM 探测", t_com_probe_real)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("CAPABILITY GAP PASS")
