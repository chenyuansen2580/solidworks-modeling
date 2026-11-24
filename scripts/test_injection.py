# -*- coding: utf-8 -*-
"""注入错误验证器 —— 证明新断言**真的能抓错**，不是永远通过的空检查。

做法：对每个断言，临时把源码/文档改成错误形态 → 跑断言 → 必须变红 →
还原 → 再跑 → 必须变绿。任何一步不符合就报 FAIL。

★ 只读校验，还原用内存快照，不改工作树（异常时也保证还原）。

跑法：python test_injection.py
"""
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

fails = []


def _read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


def _write(rel, text):
    p = os.path.join(ROOT, rel)
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def run_suite(script):
    """跑一个套件，返回 (是否通过, 输出)。"""
    r = subprocess.run([PY, os.path.join(HERE, script)],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180,
                       cwd=HERE)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0, out


def chk(name, rel, mutate, script, must_fail_on=None):
    """注入一个错误，确认套件变红；还原后确认变绿。

    mutate(text) -> 新文本（必须真的改变了内容）
    must_fail_on: 期望输出里出现的失败断言名片段（可选）
    """
    orig = _read(rel)
    try:
        bad = mutate(orig)
        if bad == orig:
            print("  [XX] %-44s 注入无效（文本没变化）" % name)
            fails.append(name)
            return
        _write(rel, bad)
        ok, out = run_suite(script)
        if ok:
            print("  [XX] %-44s 注入错误后仍 PASS —— 断言是空检查！" % name)
            fails.append(name)
            return
        if must_fail_on and must_fail_on not in out:
            print("  [XX] %-44s 变红了但失败原因不是预期项 (%s)"
                  % (name, must_fail_on))
            fails.append(name)
            return
    finally:
        _write(rel, orig)

    ok2, out2 = run_suite(script)
    if not ok2:
        print("  [XX] %-44s 还原后仍 FAIL（还原失败）" % name)
        fails.append(name)
        return
    print("  [OK] %-44s 注入→红，还原→绿" % name)


def main():
    print("=== 注入错误验证（证明断言能抓错）===\n")

    # ---- 1 干涉语义：把 (None,None) 判回 True
    def m1(t):
        return t.replace(
            'return (v["status"] == "clean"), (v["status"], v["raw"])',
            'return (True), (v["status"], v["raw"])')

    chk("★ 干涉 unknown 判回 pass", "scripts/swlib_v2.py", m1,
                "test_assembly_contract.py", "(None,None) 不判 pass")

    # ---- 2 save_checked 去掉 rebuild
    def m2(t):
        return t.replace("def save_checked(m, path, rebuild=True):",
                         "def save_checked(m, path, rebuild=False):")

    chk("★ save_checked 默认不重建", "scripts/swlib_v2.py", m2,
                "test_assembly_contract.py", "save_checked 先重建")

    # ---- 3 place_to docstring 去掉警告
    def m3(t):
        i = t.find("def place_to(")
        j = t.find("place(sw, comp, R, (0, 0, 0))", i)
        head = t[:i]
        body = t[j:]
        return head + "def place_to(sw, comp, R, target_min, iters=5, tol=0.05):\n" + body

    chk("★ place_to 警告被删", "scripts/swlib_v2.py", m3,
                "test_assembly_contract.py", "place_to 已警告旋转件")

    # ---- 4 fix_all 悖论从 yaml 删除
    def m4(t):
        return t.replace(
            "★★ 但【全固定后加的配合不参与求解】：无自由度可约束，配合被记录但不起作用。实测 10 条配合里 2 条（planet-2/3↔pin-2/3）count_mates 增量 +1、AddMate5 err=5，两件实际相距 11.35/11.30mm。正确顺序是「只固定基准件 → 加配合 → 求解定位 → 再全部 fix_all」",
            "必须 fix_all 后再加")

    chk("★ fix_all 悖论从 yaml 删", "capabilities.yaml", m4,
                "test_assembly_contract.py", "fix_all 顺序悖论已记录")

    # ---- 5 max_drift 说明从 SKILL.md 删除
    def m5(t):
        return t.replace(
            "- `max_drift == 0` 在「先 `fix_all` 再加配合」流程下**恒为 0**，证明不了装配正确；",
            "- max_drift 用来检测漂移，")

    chk("★ max_drift 说明被删", "SKILL.md", m5,
                "test_assembly_contract.py", "max_drift 判据边界")

    # ---- 6 能力数字写错（验证 doc_consistency 的能力数字断言）
    def m6(t):
        return t.replace("60 verified / 11 pilot / 5 not_implemented",
                         "59 verified / 11 pilot / 5 not_implemented", 1)

    chk("★ SKILL 能力数字写错", "SKILL.md", m6,
                "test_doc_consistency.py", "能力数字 = yaml")

    # ---- 7 踩坑条数写错
    def m7(t):
        return t.replace("252 条踩坑速查", "250 条踩坑速查", 1)

    chk("★ 踩坑条数写错", "SKILL.md", m7,
                "test_doc_consistency.py", "踩坑条数 = 实际")

    # ---- 8 yaml 能力等级被改成非法值（验证 mini 解析/等级一致性）
    def m8(t):
        return t.replace("  - id: asm.place_center\n    label: 按圆心摆位（旋转件）\n    level: verified",
                         "  - id: asm.place_center\n    label: 按圆心摆位（旋转件）\n    level: pilot", 1)

    chk("★ 能力等级被降级（文档未同步）", "capabilities.yaml", m8,
                "test_doc_consistency.py", "能力 id 三处一致")

    print()
    if fails:
        print("失败 %d 项: %s" % (len(fails), fails))
        sys.exit(1)
    print("INJECTION VERIFY PASS（每条断言都验证过能抓错）")


if __name__ == "__main__":
    main()
