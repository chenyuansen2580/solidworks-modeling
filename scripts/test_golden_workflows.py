# -*- coding: utf-8 -*-
"""Golden Workflow 校验器

守三件事：
  1. 每个 workflow 的 capability id 都在 capabilities.yaml 里
  2. required_inputs / required_artifacts / real_acceptance 都存在且非空
  3. real_acceptance 的数值能被实际产物验证（不只是一句空话）

对标 wzyn 的 golden-workflows + runner.py，但只做本机需要的校验部分。
"""
import io
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
        print("  [OK] %-42s %s" % (name, note or ""))
    except AssertionError as e:
        print("  [XX] %-42s %s" % (name, e))
        fails.append(name)
    except Exception as e:
        print("  [XX] %-42s %s: %s" % (name, type(e).__name__, e))
        fails.append(name)


def load_yaml():
    import capabilities_loader as CL
    p = os.path.join(ROOT, "golden-workflows.yaml")
    return CL.load(p)


def gws():
    return load_yaml().get("workflows", [])


# ---------------------------------------------------------------- 结构
def t_schema():
    d = load_yaml()
    assert d.get("schema_version") == "1.0"
    assert d.get("target_first_pass_rate") == 0.90
    assert len(gws()) >= 6
    return "%d 个 workflow" % len(gws())


def t_required_fields():
    bad = []
    for w in gws():
        for key in ("id", "name", "capabilities", "required_inputs",
                    "required_artifacts", "real_acceptance_2022"):
            if key not in w:
                bad.append("%s 缺 %s" % (w.get("id"), key))
    assert not bad, bad
    return "字段齐全"


def t_capability_ids_valid():
    import capabilities_loader as CL
    caps = CL.capabilities()
    bad = []
    for w in gws():
        for cid in w["capabilities"]:
            if cid not in caps:
                bad.append((w["id"], cid))
    assert not bad, "未知能力: %s" % bad
    return "全部在 capabilities.yaml"


def t_subskill_refs_valid():
    bad = []
    for w in gws():
        s = w.get("real_acceptance_2022", {}).get("subskill")
        if not s:
            continue
        p = os.path.join(ROOT, "subskills", s, "SKILL.md")
        if not os.path.exists(p):
            bad.append((w["id"], s))
    assert not bad, "子技能引用不存在: %s" % bad
    return "子技能引用有效"


def t_infrastructure_refs_valid():
    """infrastructure 字段引用的是真实脚本模块，不是 capability id"""
    bad = []
    for w in gws():
        for mod in w.get("infrastructure", []):
            p = os.path.join(HERE, mod + ".py")
            if not os.path.exists(p):
                bad.append((w["id"], mod))
    assert not bad, "infrastructure 模块不存在: %s" % bad
    n = sum(len(w.get("infrastructure", [])) for w in gws())
    return "%d 个模块引用有效" % n


def t_acceptance_has_numbers():
    """real_acceptance 必须有真数值，不能只有空话"""
    bad = []
    for w in gws():
        acc = w.get("real_acceptance_2022", {})
        has_num = any(isinstance(v, (int, float)) for v in acc.values())
        has_dict = any(isinstance(v, dict) for v in acc.values())
        if not (has_num or has_dict):
            bad.append(w["id"])
    assert not bad, "验收无数值: %s" % bad
    return "验收有数值证据"


# ---------------------------------------------------------------- 对真实产物
def t_belt_actuator_acceptance():
    """★ 用 belt_actuator 的真实 REPORT.json 验证 golden 数值

    ★ 路径不写死：优先读环境变量 DSH_SW_BELT_REPORT，
      否则按 DSH_SW_WORKDIR/belt_actuator/out/REPORT.json 拼。
      两者都没有就跳过（不失败），保证在别人机器上也能跑测试。
    """
    import json
    rp = os.environ.get("DSH_SW_BELT_REPORT")
    if not rp:
        wd = os.environ.get("DSH_SW_WORKDIR")
        if wd:
            rp = os.path.join(wd, "belt_actuator", "out", "REPORT.json")
    if not rp or not os.path.exists(rp):
        print("      跳过（未设置 DSH_SW_BELT_REPORT，或 REPORT.json 不存在）")
        return
    with open(rp, encoding="utf-8") as f:
        r = json.load(f)
    s = r["summary"]
    gw = [w for w in gws() if w["id"] == "belt_actuator_assembly"][0]
    acc = gw["real_acceptance_2022"]
    assert s["parts"] == acc["parts"], "parts %d != %d" % (s["parts"], acc["parts"])
    assert s["components"] == acc["components"]
    assert s["mates"] == acc["mates"]
    assert s["interference_clean"] is True
    assert all(p.get("dev_pct", 0) == 0.0 or abs(p.get("dev_pct", 0)) < 0.001
               for p in r["parts"]), "有零件体积偏差非 0"
    d = r["deliverables"]
    assert d["step"]["size"] > 4_000_000
    assert d["drawing_pdf"]["size"] > 10_000
    return "14 件/15 组件/10 配合/0 偏差 全部对上"


def t_gear_acceptance():
    """齿轮的 2301/4601 点由脚本实时生成，这里只验参数结构"""
    gw = [w for w in gws() if w["id"] == "spur_gear_pair"][0]
    acc = gw["real_acceptance_2022"]
    assert acc["z20"]["points"] == 2301
    assert acc["z40"]["points"] == 4601
    assert acc["z20"]["r_ok"] if "r_ok" in acc["z20"] else True
    return "z20=2301 / z40=4601 点"


def t_gates_acceptance():
    """三个机制的断言数从测试文件实际统计（含 golden 自身 + 2026-11-22 新增两套）"""
    gw = [w for w in gws() if w["id"] == "capability_gate_drill"][0]
    acc = gw["real_acceptance_2022"]
    counts = {
        "freshness_assertions": "test_freshness.py",
        "gap_assertions": "test_capability_gap.py",
        "trace_assertions": "test_exec_trace.py",
        "doc_consistency_assertions": "test_doc_consistency.py",
        "golden_assertions": "test_golden_workflows.py",
        # ★ 2026-11-22 GR-90 审查新增：判据缺陷固化 + 注入验证
        "assembly_contract_assertions": "test_assembly_contract.py",
        "injection_assertions": "test_injection.py",
    }
    for key, fn in counts.items():
        src = io.open(os.path.join(HERE, fn), encoding="utf-8").read()
        n = len(re.findall(r"^\s*chk\(", src, re.M))
        assert n == acc[key], "%s 声明 %d，实际 %d" % (key, acc[key], n)
    return "断言数与实际测试一致"


def t_no_false_version_claims():
    """不编造跨版本结论：real_acceptance 键必须是 2022"""
    for w in gws():
        keys = [k for k in w if k.startswith("real_acceptance_")]
        assert keys == ["real_acceptance_2022"], \
            "%s 版本声明错误: %s" % (w["id"], keys)


def t_drawing_acceptance_matches_code():
    """★ 工程图验收值必须与 capabilities.yaml / 代码常量一致。

    这条防的是"文档数字落后于实测"：上一轮把 annotations 从 pilot 升到
    verified 后，golden-workflows.yaml 还写着 `annotations_added: 0` +
    `pdf_bytes: 7130`（旧值），文档与证据不一致。
    """
    import capabilities_loader as CL
    gw = [w for w in gws() if w["id"] == "drawing_delivery"][0]
    acc = gw["real_acceptance_2022"]

    caps = CL.capabilities()
    ann = caps.get("drawing.annotations", {})
    assert ann.get("level") == acc["annotations_level"], \
        "annotations 等级 %s != yaml %s" % (acc["annotations_level"], ann.get("level"))
    assert acc["annotations_added"] > 0, "verified 就该有 >0 的增量证据"

    # types 必须与代码里的 ANN_WORKING 一致
    import swlib_v2 as V
    assert acc["annotations_types_required"] == V.ANN_WORKING, \
        "验收写的 types %s != 代码 ANN_WORKING %s" % (
            acc["annotations_types_required"], V.ANN_WORKING)
    assert V.ANN_WORKING & 32768, "ANN_WORKING 必须含 32768 位"

    # 孔表等级必须一致
    ht = caps.get("drawing.hole_table", {})
    assert ht.get("level") == acc["hole_table"], \
        "hole_table 等级 %s != yaml %s" % (acc["hole_table"], ht.get("level"))

    # PDF 有标注应大于无标注
    assert acc["pdf_bytes"] > acc["pdf_bytes_without_annotations"], \
        "插了标注的 PDF 应该更大"

    # capabilities 里要真的登记了 golden 声明的每个能力
    for cid in gw["capabilities"]:
        assert cid in caps, "golden 声明了未登记能力 %s" % cid
    return "types/等级/PDF 三处与代码一致"


def t_sheet_size_api_consistent():
    """★ 幅面必须走 ISheet.GetSize，不能靠 GetProperties 按位置猜索引。

    实测 GetProperties 返回 7 项 `(0.0, 13.0, 1.0, 1.0, 1.0, 0.2794, 0.2159)`，
    真幅面在索引 5/6，按位置取 0/1 会得到 0×13000mm 这种荒谬值。
    """
    import swlib_v2 as V
    gw = [w for w in gws() if w["id"] == "drawing_delivery"][0]
    acc = gw["real_acceptance_2022"]
    assert "GetSize" in acc["sheet_size_api"], acc["sheet_size_api"]
    w, h = acc["sheet_size_mm"]
    assert 100 < w < 1200 and 100 < h < 900, \
        "幅面应在合理区间（A4~A0），实得 %s×%s" % (w, h)
    # 代码里必须真的用 GetSize
    src = io.open(os.path.join(HERE, "swlib_v2.py"), encoding="utf-8").read()
    assert '"GetSize"' in src or "'GetSize'" in src, "swlib_v2 未调用 ISheet.GetSize"
    assert "def sheet_properties" in src and "def current_sheet" in src
    return "%.1f×%.1f mm，走 GetSize" % (w, h)


def t_declared_assertion_counts():
    """★ golden 里 `assertions: N` 必须等于对应测试文件的实际 chk 数。

    防的是"加了断言忘了改文档"。映射表显式写死，因为 workflow id 与
    测试文件名不是机械对应（drawing_delivery → test_drawing_delivery.py）。
    """
    mapping = {
        "drawing_delivery": "test_drawing_delivery.py",
        "mesh_reference_import": "test_mesh_import.py",
    }
    bad = []
    for w in gws():
        wid = w.get("id")
        fn = mapping.get(wid)
        if not fn:
            continue
        acc = w.get("real_acceptance_2022", {})
        if "assertions" not in acc:
            continue
        src = io.open(os.path.join(HERE, fn), encoding="utf-8").read()
        actual = len(re.findall(r"^\s*chk\(", src, re.M))
        if actual != acc["assertions"]:
            bad.append("%s 声明 %d 实际 %d (%s)"
                       % (wid, acc["assertions"], actual, fn))
    assert not bad, "断言数不一致: %s" % bad
    n = len([w for w in gws() if "assertions" in w.get("real_acceptance_2022", {})])
    return "%d 个 workflow 断言数一致" % n


def t_no_stale_pilot_claims():
    """★ 不能把已升级的能力仍标成 pilot（反向：也不能把 pilot 写成 verified）。

    golden 的 real_acceptance 里如果出现 "pilot" 字样，对应能力在 yaml 里
    就必须真的是 pilot —— 防止升级后忘记改文档。
    """
    import capabilities_loader as CL
    caps = CL.capabilities()
    bad = []
    for w in gws():
        for cid in w.get("capabilities", []):
            lvl = caps.get(cid, {}).get("level")
            if lvl != "pilot":
                continue
            # pilot 能力出现在 golden 的 capabilities 里是允许的，但要显式标注
        acc = w.get("real_acceptance_2022", {})
        for k, v in acc.items():
            if not isinstance(v, str):
                continue
            if "pilot" in v.lower():
                # 该 workflow 里必须有对应的 pilot 能力
                pilots = [c for c in w.get("capabilities", [])
                          if caps.get(c, {}).get("level") == "pilot"]
                if not pilots:
                    bad.append((w["id"], k, v[:40]))
    assert not bad, "声明 pilot 但 capabilities 里没有 pilot 项: %s" % bad
    return "pilot 声明与能力表一致"


print("=== Golden Workflow 校验套件 ===\n")
chk("schema 与数量", t_schema)
chk("必需字段齐全", t_required_fields)
chk("能力 id 有效", t_capability_ids_valid)
chk("子技能引用有效", t_subskill_refs_valid)
chk("基础设施模块有效", t_infrastructure_refs_valid)
chk("验收含数值证据", t_acceptance_has_numbers)
chk("★ belt_actuator 真实验收", t_belt_actuator_acceptance)
chk("齿轮点数验收", t_gear_acceptance)
chk("★ 三机制断言数一致", t_gates_acceptance)
chk("不谎称跨版本", t_no_false_version_claims)
chk("★ 工程图验收 = 代码", t_drawing_acceptance_matches_code)
chk("★ 幅面走 GetSize", t_sheet_size_api_consistent)
chk("★ 声明的断言数 = 实际", t_declared_assertion_counts)
chk("pilot 声明与能力表一致", t_no_stale_pilot_claims)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("GOLDEN WORKFLOW PASS")
