# -*- coding: utf-8 -*-
"""能力缺口协议 —— 不会的时候不抛裸异常，返回结构化缺口让调用方继续。

对标 wzyn20051216/solidworks-automation-skill（2230★）的 CAPABILITY_GAP。

## 问题

旧版 `require_verified()` 直接 `raise RuntimeError`，调用方只知道「不行」，
不知道该查什么、有没有替代、能不能现探。结果是：
  - Agent 卡住，或者
  - 绕过门禁硬写，然后静默失败

## 协议

能力查不到时不抛异常，返回 `CapabilityGap`：

    requested     请求的能力名
    kind          缺口类型：unknown / pilot_only / not_implemented / blocked
    alternatives  已登记的近似能力（可直接改用）
    probe         建议去 COM 上探测的 (接口, 方法) 列表
    doc_hints     建议读的文档章节
    next_steps    结构化后续步骤（查证 → 探测 → 最小实现 → 验证 → 登记）

Agent 拿到 gap 后按 next_steps 走，而不是放弃。

## 用法

    import capability_gap as CG

    # ① 软查询：拿 gap 而不是异常
    gap = CG.probe_capability("part.thread")
    if gap:
        print(gap.report())
        for iface, meth in gap.probe:
            print(iface, meth, CG.com_has(sw, iface, meth))

    # ② 硬门禁：verified 才放行，否则抛结构化异常
    CG.require("part.extrude")           # OK
    CG.require("part.hole_wizard")       # 抛 CapabilityGapError，携带 gap

    # ③ 探测 COM 成员，用于「最小实现」阶段
    CG.com_has(m, "IFeatureManager", "InsertThread2")
    CG.com_signature(m, "IFeatureManager", "InsertThread2")
"""
import json
from dataclasses import dataclass, field

# 与 swlib_v2 的等级常量保持一致（不 import 它，避免循环依赖）
VERIFIED = "verified"
PILOT = "pilot"
REFERENCE_ONLY = "reference_only"
NOT_IMPLEMENTED = "not_implemented"

# 缺口类型
KIND_UNKNOWN = "unknown"                    # 完全没登记
KIND_PILOT_ONLY = "pilot_only"              # 登记了但只到 pilot
KIND_NOT_IMPLEMENTED = "not_implemented"    # 明确不可用
KIND_BLOCKED = "blocked"                    # 本机环境不允许

# 近似能力表：请求 A 拿不到时，可用 B/C 组合替代
# 格式：requested -> [(替代能力, 说明)]
ALTERNATIVES = {
    "part.thread": [
        ("part.cut_blind", "螺纹孔可用盲孔 + 装饰螺纹线替代（几何等效）"),
        ("part.hole_wizard", "孔向导 Metric Tap（本机 PILOT，不可用）"),
    ],
    "part.hole_wizard": [
        ("part.cut_through", "普通贯穿切除，已验证 0.000% 精确"),
        ("part.cut_blind", "盲孔切除，可指定深度"),
    ],
    "part.mirror": [
        ("sketch.spline", "对称轮廓可在草图内直接镜像点集"),
    ],
    "surface.thicken": [
        ("part.extrude", "薄壁实体直接用拉伸代替曲面加厚"),
        ("part.shell", "等壁厚结构用抽壳"),
    ],
    "export.stl": [
        ("export.step", "先导 STEP，再用外部工具转 STL"),
    ],
    "drawing.section": [
        ("drawing.create", "先出标准视图，剖视需界面手工补"),
    ],
    "bom.table_insert": [
        ("props.custom", "BOM 数据可从自定义属性聚合，表格自建"),
    ],
    "motion.framerate": [
        ("motion.study", "用默认帧率，只建算例+计算"),
    ],
    "asm.mate.axis_concentric": [
        ("asm.mate.concentric", "用面同心代替轴同心（本机轴配合不建）"),
        ("asm.mate.plane_coincident", "改用基准面重合"),
    ],
    "appearance.render": [
        ("appearance.component", "装配体用组件级上色"),
        ("material.set", "零件用材料驱动外观"),
    ],
    # ---- 2026-11-20 补：以下 5 项原先没给替代，Agent 拿到 gap 会卡住
    "weldment.cut_list": [
        ("weldment.structural", "焊件本身已验证，切割清单缺失时改用 feature_tree 手数 CutListFolder"),
        ("props.custom", "件号/材质/长度写进自定义属性，自建 BOM"),
    ],
    "motion.results": [
        ("motion.study", "算例与计算已验证，速度/加速度需界面读或导 AVI 后分析"),
    ],
    "motion.avi": [
        ("motion.study", "算例与计算已验证，AVI 需界面导出（依赖编解码器）"),
    ],
    "appearance.display_color": [
        ("appearance.component", "装配体组件级上色（9元素 VARIANT），已验证"),
        ("material.set", "零件级用材料驱动，已验证"),
    ],
    "export.sldprt_to_web": [
        ("export.step", "先导 STEP，再用外部工具转 glTF/GLB"),
    ],
    # ---- 2026-11-21 补：6 个缺口新增的能力，非 verified 的要给替代
    "import.mesh": [
        ("import.mesh_precheck", "导入前先跑法线预检，避免 SW 弹模态框挂死"),
        ("part.extrude", "要参数化就别导网格，直接建模"),
    ],
    "drawing.annotations": [
        ("drawing.create", "视图+PDF 已验证；标注改人眼补或手工 InsertModelItems"),
        ("drawing.standards_check", "机器判视图数/PDF/标注增量，人判尺寸链"),
    ],
    "drawing.hole_table": [
        ("props.custom", "孔规格/数量写进自定义属性，交付附 CSV"),
        ("drawing.create", "先出标准视图，孔表需界面手工补"),
    ],
    "drawing.title_block_fill": [
        ("props.custom", "件号/材料/比例写自定义属性，标题栏靠模板链接或手工"),
    ],
}

# 缺口时的建议探测点（接口, 方法/属性）
PROBE_HINTS = {
    "part.thread": [("IFeatureManager", "InsertThread2"),
                    ("IFeatureManager", "InsertCosmeticThread3")],
    "part.hole_wizard": [("IFeatureManager", "HoleWizard5"),
                         ("IWizardHoleFeatureData2", "InitializeHole")],
    "surface.thicken": [("IModelDoc2", "InsertBndryCtrl"),
                        ("IFeatureManager", "InsertNetBlend")],
    "export.stl": [("IModelDocExtension", "SaveAs3")],
    "drawing.section": [("IDrawingDoc", "CreateSectionViewAt5")],
    "bom.table_insert": [("IView", "InsertBomTable4")],
}

# 缺口时建议读的文档
DOC_HINTS = {
    "part.thread": ["references/api-map.md", "references/features.md"],
    "part.hole_wizard": ["references/pitfalls.md 章节 S15"],
    "surface.thicken": ["references/pitfalls.md 已知限制"],
    "export.stl": ["references/pitfalls.md 已知限制"],
    "drawing.section": ["references/features.md 工程图"],
    "asm.mate.axis_concentric": ["references/pitfalls.md 章节 E"],
}

NEXT_STEPS = [
    "1. 查 references/ 里有没有现成做法（先查再写）",
    "2. 用 com_has / com_signature 探测本机 COM 是否支持",
    "3. 不支持 → 用 ALTERNATIVES 里的近似能力组合",
    "4. 支持 → 写最小实现，用 verify() / volume_check() 验证",
    "5. 验证通过后登记到 CAPABILITIES，等级按证据定（不许直接标 verified）",
]


@dataclass
class CapabilityGap:
    requested: str
    kind: str
    level: str = ""
    note: str = ""
    alternatives: list = field(default_factory=list)
    probe: list = field(default_factory=list)
    doc_hints: list = field(default_factory=list)
    next_steps: list = field(default_factory=lambda: list(NEXT_STEPS))

    def to_dict(self):
        return {
            "type": "CAPABILITY_GAP",
            "requested": self.requested,
            "kind": self.kind,
            "level": self.level,
            "note": self.note,
            "alternatives": [{"capability": c, "why": w} for c, w in self.alternatives],
            "probe": [{"interface": i, "member": m} for i, m in self.probe],
            "doc_hints": self.doc_hints,
            "next_steps": self.next_steps,
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def report(self):
        lines = ["=== CAPABILITY_GAP: %s ===" % self.requested]
        lines.append("  类型: %s   等级: %s" % (self.kind, self.level or "-"))
        if self.note:
            lines.append("  说明: %s" % self.note)
        if self.alternatives:
            lines.append("  可用替代:")
            for c, w in self.alternatives:
                lines.append("    - %-28s %s" % (c, w))
        if self.probe:
            lines.append("  建议探测:")
            for i, m in self.probe:
                lines.append("    - %s.%s" % (i, m))
        if self.doc_hints:
            lines.append("  建议阅读: %s" % ", ".join(self.doc_hints))
        lines.append("  后续步骤:")
        for s in self.next_steps:
            lines.append("    " + s)
        return "\n".join(lines)


class CapabilityGapError(RuntimeError):
    """硬门禁失败时抛出，携带完整 gap，调用方可直接 .gap.to_json()。"""

    def __init__(self, gap):
        self.gap = gap
        super().__init__(gap.report())


# ---------------------------------------------------------------- 查询
def _caps():
    """延迟导入 CAPABILITIES，避免循环依赖。"""
    try:
        import swlib_v2 as V
        return V.CAPABILITIES, V.capability
    except Exception:
        return {}, None


def probe_capability(name):
    """软查询：返回 CapabilityGap 或 None（None = verified，可直接用）。"""
    caps, cap_fn = _caps()
    if cap_fn is not None:
        level, note = cap_fn(name)
    else:
        level, note = REFERENCE_ONLY, "CAPABILITIES 不可用"

    if level == VERIFIED:
        return None

    if name not in caps:
        kind = KIND_UNKNOWN
    elif level == PILOT:
        kind = KIND_PILOT_ONLY
    elif level == NOT_IMPLEMENTED:
        kind = KIND_NOT_IMPLEMENTED
    else:
        kind = KIND_BLOCKED

    return CapabilityGap(
        requested=name,
        kind=kind,
        level=level,
        note=note,
        alternatives=list(ALTERNATIVES.get(name, [])),
        probe=list(PROBE_HINTS.get(name, [])),
        doc_hints=list(DOC_HINTS.get(name, [])),
    )


def require(name):
    """硬门禁：verified 返回 True；否则抛 CapabilityGapError（带结构化 gap）。"""
    gap = probe_capability(name)
    if gap is None:
        return True
    raise CapabilityGapError(gap)


def require_any(names):
    """任一 verified 即通过，返回命中的那个名字。"""
    for n in names:
        if probe_capability(n) is None:
            return n
    gaps = [probe_capability(n) for n in names]
    raise CapabilityGapError(CapabilityGap(
        requested=" | ".join(names),
        kind=KIND_UNKNOWN,
        note="候选能力全部未达 verified",
        alternatives=[(g.requested, g.note) for g in gaps if g],
        doc_hints=["references/pitfalls.md"],
    ))


# ---------------------------------------------------------------- COM 探测
def com_has(obj, iface, member):
    """探测 COM 对象（或其接口）上有没有某个成员。返回 True/False。

    obj 可以是 IModelDoc2 / IFeatureManager 等已 wrap 的对象，
    也可以传 sw，此时 iface 会先被 wrap。
    """
    try:
        import swlib_v2 as V
        target = V.wrap(obj, iface) if iface else obj
    except Exception:
        target = obj
    if target is None:
        return False
    try:
        getattr(target, member)
        return True
    except Exception:
        return False


def com_signature(obj, iface, member):
    """读 COM 成员的参数个数；读不到返回 None。用于跨版本 arity 探测。"""
    try:
        import inspect
        import swlib_v2 as V
        target = V.wrap(obj, iface) if iface else obj
        fn = getattr(target, member, None)
        if fn is None:
            return None
        return len(inspect.signature(fn).parameters)
    except Exception:
        return None


def probe_all(sw, gap):
    """按 gap.probe 逐项探测，返回 [(接口, 成员, 是否存在)]。"""
    out = []
    for iface, member in gap.probe:
        out.append((iface, member, com_has(sw, iface, member)))
    return out


# ---------------------------------------------------------------- 自测
if __name__ == "__main__":
    # ① verified 能力 → 无 gap
    assert probe_capability("part.extrude") is None

    # ② 未登记能力 → unknown，带 next_steps
    g = probe_capability("part.thread")
    assert g is not None and g.kind == KIND_UNKNOWN
    assert g.alternatives, "unknown 应给替代方案"
    assert g.probe, "unknown 应给探测建议"
    assert len(g.next_steps) == 5

    # ③ pilot 能力 → pilot_only
    g2 = probe_capability("part.hole_wizard")
    assert g2.kind == KIND_PILOT_ONLY
    assert any("cut_through" in c for c, _ in g2.alternatives)

    # ④ 明确不可用 → not_implemented
    g3 = probe_capability("surface.thicken")
    assert g3.kind == KIND_NOT_IMPLEMENTED

    # ⑤ 硬门禁：verified 放行
    assert require("part.extrude") is True

    # ⑥ 硬门禁：非 verified 抛结构化异常
    try:
        require("part.hole_wizard")
        raise AssertionError("应抛 CapabilityGapError")
    except CapabilityGapError as e:
        assert e.gap.requested == "part.hole_wizard"
        d = e.gap.to_dict()
        assert d["type"] == "CAPABILITY_GAP"
        assert d["kind"] == "pilot_only"

    # ⑦ require_any：任一可用即过
    assert require_any(["part.hole_wizard", "part.cut_through"]) == "part.cut_through"

    # ⑦b require_any 全不可用
    try:
        require_any(["part.hole_wizard", "surface.thicken"])
        raise AssertionError("应抛")
    except CapabilityGapError:
        pass

    # ⑧ JSON 可序列化
    s = g.to_json()
    assert json.loads(s)["requested"] == "part.thread"

    # ⑨ report 可读
    r = g.report()
    assert "CAPABILITY_GAP" in r and "后续步骤" in r

    print(g.report())
    print()
    print(">>> CAPABILITY GAP SELFTEST PASS")
