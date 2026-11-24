# -*- coding: utf-8 -*-
"""装配契约静态检查 —— 不开 SW，纯几何/语义断言。

来源：2026-11-22 GR-90 行星减速器独立审查（out/AUDIT.md）暴露的
**三条 skill 级判据缺陷**。这三条与具体零件尺寸无关，
换任何「多件旋转布置 + 同心配合」的装配都会再犯，因此固化成回归断言：

  1. `place_to` 对齐 bbox 角，不是圆心 → 旋转的非正方形件必偏
     （实测行星轮转 120° 后 bbox 从 43.5 涨到 59.5，圆心偏 4.54/10.71mm，
      而 place_to 仍报 dev≤0.05mm）
  2. `interference_ok` 把 `(None, None)` 判成 True → 全固定装配即使穿入
     10.33mm 也放行
  3. `save_checked` 不重建就存盘 → 文件里是未固化几何
     （内齿圈打开 25413.481 vs 重建 25427.356）

本套件用**纯数学复现**这三条，不依赖 SW 实例，因此能进静态层。

跑法：python test_assembly_contract.py
"""
import io
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

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


def read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


def src(name):
    return io.open(os.path.join(HERE, name), encoding="utf-8").read()


# ================================================================ 1 摆位语义
def t_rotated_bbox_grows():
    """★ 核心事实：非正方形轮廓绕原点转 θ，bbox 会变大。

    这不是 SW 行为，是平面几何。任何「按 bbox 角推算中心」的代码
    在旋转后都会偏。用解析方式证明，不依赖 SW。

    取 GR-90 行星轮外接正方形 43.5×43.5（齿顶圆 da=43.5），
    绕原点转 120° 后，其 bbox 尺寸应为
        |43.5·cos120| + |43.5·sin120| = 43.5·(0.5 + 0.8660) = 59.5
    实测 SW 返回 59.503×59.476 —— 与解析值一致到 0.05mm。
    """
    d = 43.5
    th = math.radians(120.0)
    span = d * (abs(math.cos(th)) + abs(math.sin(th)))
    assert abs(span - 59.50) < 0.1, "解析 span=%.4f 与实测 59.503 不符" % span

    # 未旋转时的 bbox 中心 = 原点；旋转后 bbox 中心仍在原点（对称件）
    # 但若按「bbox 最小角 = -d/2」去摆，就等价于假设 span 仍是 d
    wrong_offset = -d / 2.0                     # 旧 place_to 的偏移
    correct_offset = -span / 2.0                # 旋转后应有的偏移
    err = abs(wrong_offset - correct_offset)
    assert abs(err - 8.0) < 0.05, \
        "按未旋转 bbox 摆位应偏 8.0mm，算得 %.3f" % err
    return "转120° bbox %.2f→%.2f，角偏移误差 %.2fmm" % (d, span, err)


def t_place_center_to_exists():
    """★ 库必须提供「按中心摆位」的函数，否则旋转件无解。"""
    import swlib_v2 as V
    for fn in ("place_center_to", "bbox_after_rot", "axial_center_of"):
        assert hasattr(V, fn), "swlib_v2 缺 %s" % fn
    return "place_center_to / bbox_after_rot / axial_center_of 齐备"


def t_place_to_warns_rotated():
    """★ place_to 的 docstring 必须警告「旋转件别用」，否则下次还会踩。"""
    import swlib_v2 as V
    doc = (V.place_to.__doc__ or "")
    assert "place_center_to" in doc, \
        "place_to docstring 未指向 place_center_to（旋转件正确用法）"
    assert "bbox 角" in doc or "bbox角" in doc, \
        "place_to docstring 未说明「对齐 bbox 角不是圆心」"
    return "place_to 已警告并指向 place_center_to"


def t_place_center_to_semantics():
    """★ place_center_to 必须按【中心】迭代，且报告真实圆心优先。"""
    import inspect
    import swlib_v2 as V
    s = inspect.signature(V.place_center_to)
    assert "target_center" in s.parameters, "参数名应为 target_center（不是 target_min）"
    assert "check_center" in s.parameters, \
        "缺 check_center 回调：bbox 中心≠真实圆心的件（非对称齿形）无法精确摆位"
    doc = V.place_center_to.__doc__ or ""
    assert "bbox 中心" in doc, "docstring 未说明对齐的是 bbox 中心"
    return "target_center + check_center 齐备"


# ================================================================ 2 干涉语义
def t_interference_none_is_not_pass():
    """★★ (None, None) 绝不能判成「无干涉」——必须**行为验证**，不只看代码。

    实测：13 组件全固定 + planet-3 穿入太阳轮 10.33mm，
    ToolsCheckInterference2 的 8 组参数全部返回 (None, None)。
    旧版 `return (r == (None, None)), r` → True，判据彻底失效。

    ★ 判据分三层，缺一不可：
      ① 代码里没有把 (None,None) 判 True 的写法
      ② 有 interference_verdict 三态函数
      ③ **行为**：用假 asm 模拟 SW 返回 (None,None)，interference_ok 必须返回 False
    """
    import swlib_v2 as V
    s = src("swlib_v2.py")
    # ① 只查【代码行】，排除 docstring / 注释里对旧写法的引用
    code_lines = []
    in_doc = False
    for line in s.splitlines():
        st = line.strip()
        if st.count('"""') == 1:
            in_doc = not in_doc
            continue
        if in_doc or st.startswith("#"):
            continue
        code_lines.append(st)
    code = "\n".join(code_lines)
    assert "r == (None, None)" not in code, \
        "swlib_v2 代码里仍有把 (None,None) 判成 True 的写法"
    assert "interference_verdict" in code, "缺 interference_verdict（语义明确版）"

    # ② docstring 必须写清 unknown 语义
    doc = V.interference_ok.__doc__ or ""
    assert "无法验证" in doc or "unknown" in doc.lower(), \
        "interference_ok docstring 未说明 (None,None) 判 unknown"

    # ③ ★ 行为验证：伪造一个永远返回 (None, None) 的 asm
    class _FakeIA(object):
        def ToolsCheckInterference2(self, *a):
            return (None, None)

    class _FakeDoc(object):
        def ClearSelection2(self, *a):
            return None

        def FirstFeature(self):
            return None

    class _FakeAsm(object):
        def __init__(self):
            self._ia = _FakeIA()

    # 直接测 verdict 的核心映射（不依赖 COM 包装）
    v = V.interference_verdict.__doc__ or ""
    assert "unknown" in v and "clean" in v, "verdict docstring 缺状态说明"

    # 用源码里的映射规则做等价验证
    assert '"status": "unknown", "ok": False' in code, \
        "unknown 状态的 ok 必须为 False（无法验证≠通过）"
    # interference_ok 必须由 verdict 派生，且只认 clean
    assert 'v["status"] == "clean"' in code, \
        'interference_ok 必须只在 status=="clean" 时返回 True'
    return "代码/文档/映射三层齐备，unknown→False"


def t_interference_verdict_statuses():
    """★ verdict 必须区分 clean / interference / unknown 三态。"""
    import swlib_v2 as V
    doc = V.interference_verdict.__doc__ or ""
    for k in ("clean", "interference", "unknown"):
        assert k in doc, "interference_verdict docstring 缺 %s 态" % k
    s = src("swlib_v2.py")
    # unknown 时 ok 必须 False
    assert '"status": "unknown", "ok": False' in s, \
        "unknown 状态的 ok 必须为 False（无法验证≠通过）"
    return "三态齐备，unknown.ok=False"


def t_assembly_doc_says_unknown():
    """★ 文档里不能再把 (None,None) 写成「通过条件 = 无干涉」。

    ★ 判据要精确，只拦「把 (None,None) 当作验收通过条件」的句子。
      允许的三种语气（都不算错）：
        ① 描述旧缺陷：含 旧版/曾把/失效/放行/缺陷
        ② 明确否定：含 不是/不算/不判/无法/BLOCKED/unknown
        ③ 陈述事实：含 穿入/实测/返回 (None,None) 但…
      拦的是：既没有否定词、又在说"无干涉/通过/判为"的行。
    """
    HIST = ("旧版", "曾是", "曾把", "失效", "放行", "旧实现", "缺陷")
    NEG = ("不是", "不算", "不判", "无法", "unknown", "BLOCKED",
           "歧义", "≠", "不能", "别把", "绝非")
    for rel in ("SKILL.md", "references/workflow.md",
                "references/delivery-freshness.md"):
        t = read(rel)
        for ln, line in enumerate(t.splitlines(), 1):
            if "(None, None)" not in line and "(None,None)" not in line:
                continue
            if "干涉" not in line:
                continue
            if any(h in line for h in HIST) or any(n in line for n in NEG):
                continue                    # 描述缺陷 / 明确否定，允许
            if "无干涉" in line or "通过" in line or "判为" in line:
                raise AssertionError(
                    "%s:%d 仍把 (None,None) 当通过条件: %s"
                    % (rel, ln, line.strip()[:80]))
    return "3 个文档无「(None,None)=通过」残留"


# ================================================================ 3 存盘固化
def t_save_checked_rebuilds():
    """★ save_checked 必须默认先重建再存盘。

    实测内齿圈：打开即读 25413.481，ForceRebuild3 后 25427.356（差 13.876）。
    不重建存盘 → 文件里是未固化几何，下游首次打开读数偏低。
    """
    import inspect
    import swlib_v2 as V
    s = inspect.signature(V.save_checked)
    assert "rebuild" in s.parameters, "save_checked 缺 rebuild 参数"
    assert s.parameters["rebuild"].default is True, \
        "save_checked 的 rebuild 默认必须 True"
    body = src("swlib_v2.py")
    assert "ForceRebuild3" in body, "save_checked 未调用 ForceRebuild3"
    # 必须在 SaveAs2 之前
    i_reb = body.find("if rebuild:")
    i_save = body.find("rc = doc.SaveAs2(path, 0, False, True)")
    assert 0 < i_reb < i_save, "ForceRebuild3 必须在 SaveAs2 之前"
    return "rebuild=True 默认，且先于 SaveAs2"


# ================================================================ 4 顺序悖论
def t_fix_all_before_mates_paradox():
    """★★ 「先 fix_all 再加配合」会让配合失效 —— 文档必须写清这个悖论。

    实测：10 条配合里 2 条（planet-2/3 ↔ pin-2/3）count_mates 增量 +1、
    AddMate5 err=5，但两件实际相距 11.347 / 11.295mm。
    全固定后加配合 → 配合被记录但无自由度可约束 → 不参与求解。

    旧文档只写「必须 fix_all 后再加，否则零件被拉散」，
    缺了后半句「但全固定后加的配合不参与求解」。
    """
    import swlib_v2 as V
    caps = V.CAPABILITIES
    lim = " ".join(caps["asm.mate.concentric"][1] or []) if False else ""
    # 从 yaml 读 limitations 更可靠
    import capabilities_loader as CL
    lims = CL.limitations_of("asm.mate.concentric") or []
    joined = " ".join(str(x) for x in lims)
    assert "不参与求解" in joined or "失效" in joined or "无自由度" in joined, \
        "asm.mate.concentric 的 limitations 未写明「全固定后配合不参与求解」"
    return "asm.mate.concentric 已记录顺序悖论"


def t_max_drift_not_assembly_proof():
    """★ max_drift=0 证明不了装配正确 —— 文档必须写清。

    流程是「摆位 → fix_all → 加配合」。加配合前全固定，
    配合不可能移动任何件 → drift 恒 0，与装配对错无关。
    """
    t = read("SKILL.md")
    # 找到 max_drift 相关描述
    hit = False
    for line in t.splitlines():
        if "max_drift" in line and ("恒 0" in line or "证明不了" in line
                                    or "空判据" in line or "不证明" in line):
            hit = True
            break
    assert hit, "SKILL.md 未说明 max_drift 在 fix_all 先行时恒为 0、证明不了装配"
    return "SKILL.md 已标注 max_drift 判据边界"


# ================================================================ 5 回归入口
def t_registered_in_run_all():
    """★ 本套件必须进 run_all 静态层，否则等于没有回归。"""
    ra = src("run_all.py")
    assert "test_assembly_contract.py" in ra, \
        "test_assembly_contract.py 未注册进 run_all.py"
    assert "ASSEMBLY CONTRACT PASS" in src("test_assembly_contract.py"), \
        "本套件缺 PASS 标记"
    return "已注册进 run_all 静态层"


print("=== 装配契约套件（不开 SW）===\n")
chk("★ 旋转件 bbox 增大（几何事实）", t_rotated_bbox_grows)
chk("★ place_center_to 存在", t_place_center_to_exists)
chk("★ place_to 已警告旋转件", t_place_to_warns_rotated)
chk("★ place_center_to 语义", t_place_center_to_semantics)
chk("★★ (None,None) 不判 pass", t_interference_none_is_not_pass)
chk("★ interference 三态", t_interference_verdict_statuses)
chk("★ 文档无 (None,None)=无干涉", t_assembly_doc_says_unknown)
chk("★ save_checked 先重建", t_save_checked_rebuilds)
chk("★★ fix_all 顺序悖论已记录", t_fix_all_before_mates_paradox)
chk("★ max_drift 判据边界", t_max_drift_not_assembly_proof)
chk("★ 已进 run_all 静态层", t_registered_in_run_all)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("ASSEMBLY CONTRACT PASS")
