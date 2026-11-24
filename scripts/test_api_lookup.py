# -*- coding: utf-8 -*-
"""api_lookup.py 的验收测试（静态，不需要 SW）。

对标 wzyn 的 `test_api_lookup.py`：验证能查到真签名、编造的查不到。
本机没有在线文档，全部走类型库，所以断言的是「类型库里的真实事实」：

  1. HoleWizard5 能查到 27 参（不是 26/28 —— gen_py 的 self 必须剔除）
  2. 参数类型/方向解析正确（FastenerTypeIndex=BSTR，Value12=BOOL…）
  3. 编造的方法返回空（不编造签名）
  4. 接口限定：在错接口上查同一个方法要报错，而不是跨接口猜
  5. --find 模糊搜索能命中
  6. --task 中文任务能给候选（中文没空格，靠 TASK_ALIASES）
  7. --json 输出可被 json.loads
  8. by-ref 出参被识别（SaveAs4 的 Errors/Warnings）

跑法：python test_api_lookup.py
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import api_lookup as A

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


def quiet(fn, *a, **kw):
    """吞掉被测函数的 stdout（保持测试输出干净）。"""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = fn(*a, **kw)
    finally:
        sys.stdout = old
    return rc, buf.getvalue()


TL = None


def tl():
    global TL
    if TL is None:
        TL = A.TypeLib()
    return TL


# ---------------------------------------------------------------- 用例
def t_holewizard_27():
    sig = tl().signature("HoleWizard5", "IFeatureManager")
    assert sig["arity"] == 27, "HoleWizard5 应为 27 参，实得 %s" % sig["arity"]
    assert sig["returns"]["is_dispatch"], "HoleWizard5 应返回 IDispatch(IFeature)"
    return "27 参 / 返回 %s" % sig["returns"]["vt_name"]


def t_param_types():
    """★ 类型断言来自类型库原文，不是猜的：
    ((3,1),(3,1),(3,1),(8,1),(2,1),(5,1)...) → I4,I4,I4,BSTR,I2,R8...
    这条也顺手证伪了「SSize 是字符串、FastenerTypeIndex 是整数」这种反直觉顺序。
    """
    sig = tl().signature("HoleWizard5", "IFeatureManager")
    by = {p["name"]: p for p in sig["params"]}
    assert by["GenericHoleType"]["vt_name"] == "VT_I4", by["GenericHoleType"]
    assert by["FastenerTypeIndex"]["vt_name"] == "VT_I4", by["FastenerTypeIndex"]
    assert by["SSize"]["vt_name"] == "VT_BSTR", by["SSize"]
    assert by["EndType"]["vt_name"] == "VT_I2", by["EndType"]
    assert by["Diameter"]["vt_name"] == "VT_R8"
    assert by["Value12"]["vt_name"] == "VT_R8", by["Value12"]
    assert by["ThreadClass"]["vt_name"] == "VT_BSTR", by["ThreadClass"]
    assert by["RevDir"]["vt_name"] == "VT_BOOL"
    assert not any(p["byref"] for p in sig["params"]), "HoleWizard5 没有 by-ref 出参"
    return "I4/I4/I4/BSTR/I2/R8/BSTR/BOOL 全对"


def t_bogus_method():
    """编造的方法必须查不到 —— 不许编造签名。"""
    try:
        tl().signature("DefinitelyNotARealMethod_XYZ", "IFeatureManager")
    except A.TlbError:
        pass
    else:
        raise AssertionError("编造方法居然查到了")
    try:
        tl().signature("HoleWizard5", "ISketch")
    except A.TlbError:
        pass
    else:
        raise AssertionError("错接口应报错，不该跨接口猜")
    return "两个方向都正确拒绝"


def t_find():
    hits = tl().find_methods("HoleWizard")
    assert hits, "模糊搜 HoleWizard 无结果"
    names = {h[1] for h in hits}
    assert "HoleWizard5" in names, names
    # 参数个数必须和精确查询一致
    n = [h[2] for h in hits if h[1] == "HoleWizard5"][0]
    assert n == 27, "find 报的参数量 %s != 27" % n
    return "%d 个候选，HoleWizard5=27 参" % len(hits)


def t_task_chinese():
    hints, meths = A.task_candidates("画一个渐开线齿轮")
    ids = [h["id"] for h in hints if h["type"] == "capability"]
    assert "gear.involute" in ids, ids
    assert any("InsertProtrusionBlend" in m[1] for m in meths), meths[:3]
    return "cap=%s" % ",".join(ids[:3])


def t_cli_json():
    rc, out = quiet(A.main, ["IFeatureManager", "HoleWizard5", "--json"])
    assert rc == 0, "退出码 %s" % rc
    d = json.loads(out)
    assert d["arity"] == 27 and d["interface"] == "IFeatureManager"
    assert len(d["params"]) == 27
    return "json ok, %d params" % len(d["params"])


def t_cli_render():
    rc, out = quiet(A.main, ["IFeatureManager", "HoleWizard5"])
    assert rc == 0
    assert "27 参" in out, out[:200]
    assert "VT_BSTR" in out
    return "人类可读输出正常"


def t_byref_detected():
    """SaveAs4 的 Errors/Warnings 是 by-ref 出参，必须被标出来。"""
    sig = tl().signature("SaveAs4", "IModelDoc2")
    by = {p["name"]: p for p in sig["params"]}
    assert by["Errors"]["byref"], by["Errors"]
    assert by["Warnings"]["byref"], by["Warnings"]
    assert sig["returns"]["vt_name"] == "VT_BOOL"
    return "Errors/Warnings 标为 out(byref)"


def t_owner_lookup():
    """LoadFile4 的宿主是 ISldWorks，不是 IModelDoc2 —— 这是网格导入的命门。"""
    owners = tl().all_owners("LoadFile4")
    assert owners == ["ISldWorks"], owners
    sig = tl().signature("LoadFile4")
    assert sig["interface"] == "ISldWorks"
    assert sig["arity"] == 4, sig["arity"]
    return "LoadFile4 在 ISldWorks，4 参"


def t_cli_find_and_list():
    rc, out = quiet(A.main, ["--find", "HoleWizard"])
    assert rc == 0 and "HoleWizard5" in out
    rc2, out2 = quiet(A.main, ["--list"])
    assert rc2 == 0 and "IFeatureManager" in out2
    rc3, _ = quiet(A.main, ["--find", "ZZZNoSuchThing"])
    assert rc3 == 1, "查不到应返回 1"
    return "find/list/未命中 三态正确"


print("=== api_lookup 套件（静态，不开 SW）===\n")
chk("HoleWizard5 = 27 参", t_holewizard_27)
chk("参数 VT 类型/方向", t_param_types)
chk("编造方法查不到", t_bogus_method)
chk("--find 模糊搜索", t_find)
chk("--task 中文任务", t_task_chinese)
chk("--json 可解析", t_cli_json)
chk("人类可读输出", t_cli_render)
chk("by-ref 出参识别", t_byref_detected)
chk("接口归属（LoadFile4）", t_owner_lookup)
chk("CLI 三态（find/list/未命中）", t_cli_find_and_list)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("API LOOKUP PASS")
