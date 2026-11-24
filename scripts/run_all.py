# -*- coding: utf-8 -*-
"""一键自检。改完库后跑这个。

四种模式（按耗时排序）：
    python run_all.py --static   只跑静态层，不启动 SW（约 2 秒）★ 每次改完先跑这个
    python run_all.py --quick    静态层 + 12 个核心 SW 套件（约 15 分钟）★ 日常够用
    python run_all.py            全量，单 SW 实例（约 20 分钟）
    python run_all.py --cold     全量 + 每套件冷启 SW（排障用）
    python run_all.py smoke draft  只跑指定套件

★ 优化1：默认模式**不在套件之间 kill SW**。首个套件冷启，
  之后自动附着同一实例，省掉 14 次冷启动。
  SW 状态由各 suite 自己的 new_part(close_all=True) 清理，足够隔离。

★ 优化2：静态层不启动 SW，约 2 秒拦掉 80% 的破坏
  （语法错误、函数被删、能力表被改坏、门禁逻辑回归、类型库签名漂移）。

★ 优化3：增量检测。源文件 + 本脚本都没变、且上次全过 → 直接跳过。
  强制重跑用 --force。

★ 2026-11-21 新增 5 套（对标 wzyn 2230★ 的 6 个缺口）：
  静态层 + apilookup（API 查证，纯查类型库）
  SW 层   + review（结果自审查）/ appearance（设色回读+by-ref）/
            drawing（工程图底线）/ mesh（网格导入）
"""
import hashlib
import os
import py_compile
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
STAMP = os.path.join(HERE, ".last_pass")

# 需要 SW 的套件：(名, 脚本, 成功标记, 说明, 是否 quick 必跑)
SW_SUITES = [
    ("smoke",      "smoke_test.py",      "SMOKE PASS",     "圆柱全链路：体积/bbox/四视图", True),
    ("features",   "test_features.py",   "FEATURES PASS",  "旋转/抽壳/放样/扫描/圆角/倒角", True),
    ("draft",      "test_draft.py",      "DRAFT PASS",     "梯形/圆台拔模等效", False),
    ("sheetmetal", "test_sheetmetal.py", "SHEETMETAL PASS", "钣金基体法兰", False),
    ("props",      "test_props.py",      "PROPS PASS",     "属性/配置/材料", False),
    ("surface",    "test_surface.py",    "SURFACE PASS",   "曲面 + 结构件焊件", False),
    ("motion",     "test_motion.py",     "MOTION PASS",    "装配体 + 运动算例 + 计算", False),
    ("assembly",   "test_assembly.py",   "ASSEMBLY PASS",  "端到端：摆位/固定/配合/漂移/出图/重开", True),
    ("doctest",    "doctest_examples.py", "DOC EXAMPLES PASS", "SKILL.md 示例代码实跑", True),
    ("capcheck",   "capcheck.py",        "CAP CHECK PASS",  "能力表抽查：阵列/镜像/孔向导/曲面/焊件", True),
    ("trace",      "test_exec_trace.py", "EXEC TRACE PASS", "执行 Trace：每步留痕+失败定位", True),
    # ★ 2026-11-21 新增 4 套（对标 wzyn 的 6 个缺口）
    # ★ 默认 quick 不出图、不截图：review/drawing 仅显式点名时运行
    ("review",     "test_review.py",     "REVIEW PASS",     "结果自审查（显式：python run_all.py review）", False),
    ("appearance", "test_appearance_byref.py", "APPEARANCE BYREF PASS",
     "设色回读校验 + by-ref VARIANT 出参", True),
    ("drawing",    "test_drawing_delivery.py", "DRAWING DELIVERY PASS",
     "工程图底线（显式：python run_all.py drawing）", False),
    ("mesh",       "test_mesh_import.py", "MESH IMPORT PASS",
     "网格导入：LoadFile4 + 法线预检 + bbox", True),
]

STATIC_SUITES = [
    ("gate", "verify_gate.py", "GATE SELFTEST PASS", "四级验证门禁降级逻辑", ()),
    ("freshness", "test_freshness.py", "FRESHNESS PASS", "交付新鲜度：旧文件不能冒充本轮成果", ()),
    ("gap", "test_capability_gap.py", "CAPABILITY GAP PASS", "能力缺口协议：结构化替代+探测", ("--offline",)),
    ("docs", "test_doc_consistency.py", "DOC CONSISTENCY PASS", "单一真相源：数字/引用/id 自洽", ()),
    ("golden", "test_golden_workflows.py", "GOLDEN WORKFLOW PASS", "10 个标准真机工作流验收", ()),
    ("apilookup", "test_api_lookup.py", "API LOOKUP PASS", "API 查证：类型库签名/参类型/by-ref", ()),
    ("harmonic", "check_harmonic.py", "HARMONIC CHECK PASS", "谐波齿廓校核（纯数学）", ()),
    ("planetary", "verify_all.py", "PLANETARY VERIFY PASS", "行星轮系校核（纯数学）", ()),
    # ★ 2026-11-22 新增：GR-90 审查暴露的三条 skill 级判据缺陷（纯数学，不开 SW）
    ("asmcontract", "test_assembly_contract.py", "ASSEMBLY CONTRACT PASS",
     "装配契约：旋转件摆位/干涉三态/存盘固化/fix_all 悖论", ()),
    ("injection", "test_injection.py", "INJECTION VERIFY PASS",
     "注入错误验证：每条新断言都证明能抓错", ()),
    # ★ 离线 trace：跳过真机建模项，Linux/CI 也能完整回归
    ("trace", "test_exec_trace.py", "EXEC TRACE PASS", "执行 Trace（离线部分）", ("--offline",)),
]


def kill_sw():
    try:
        subprocess.run(["taskkill", "/F", "/IM", "SLDWORKS.exe"],
                       capture_output=True, timeout=20)
    except Exception:
        pass
    time.sleep(1.5)


def sw_running():
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe"],
                           capture_output=True, text=True, timeout=20)
        return "SLDWORKS.exe" in (r.stdout or "")
    except Exception:
        return False


def run_script(script, marker, timeout=600, args=()):
    path = os.path.join(HERE, script)
    if not os.path.exists(path):
        return False, "脚本不存在"
    try:
        r = subprocess.run([PY, path] + list(args), capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=HERE)
    except subprocess.TimeoutExpired:
        return False, "超时 %ds" % timeout
    out = (r.stdout or "") + (r.stderr or "")
    if marker in out:
        return True, ""
    lines = [l for l in out.strip().splitlines() if l.strip()]
    return False, lines[-1][:150] if lines else "无输出"


# ---------------- 增量检测 ----------------
def source_digest():
    """对全部 .py 源文件取哈希，用于判断是否需要重跑。"""
    h = hashlib.sha256()
    for f in sorted(os.listdir(HERE)):
        if f.endswith(".py"):
            p = os.path.join(HERE, f)
            h.update(f.encode())
            h.update(str(os.path.getmtime(p)).encode())
    return h.hexdigest()[:16]


def unchanged_since_pass():
    """上次全过后源文件是否没变。"""
    if not os.path.exists(STAMP):
        return False
    try:
        return open(STAMP).read().strip() == source_digest()
    except Exception:
        return False


# ---------------- 静态层 ----------------
def layer_static():
    """编译 + 能力表 + 门禁自测。约 2 秒，★ 无 SW / 无 pywin32 也能跑。

    离线回退（来自远端 d8b315f，2026-11-21）：无 pywin32 / 非 Windows 时
    不 import swlib_v2（它顶层要 pythoncom），直接读 capabilities.yaml 统计
    等级并标注 `源=yaml 离线`。这样 Linux / CI 上也有完整静态回归结论。
    """
    ok = True
    py_files = [os.path.join(HERE, f) for f in os.listdir(HERE)
                if f.endswith(".py")]
    bad = []
    for f in py_files:
        try:
            py_compile.compile(f, doraise=True)
        except py_compile.PyCompileError as e:
            bad.append("%s: %s" % (os.path.basename(f), str(e)[:80]))
    if bad:
        print("  [compile]  FAIL (%d 个文件)" % len(bad))
        for b in bad:
            print("             " + b)
        ok = False
    else:
        print("  [compile]  PASS (%d 文件)" % len(py_files))

    try:
        sys.path.insert(0, HERE)
        import io
        import contextlib
        src = "swlib_v2"
        try:
            import swlib_v2 as V
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rep = V.capability_report()
            nv = len(rep.get("verified", []))
            np_ = len(rep.get("pilot", []))
            nn = len(rep.get("not_implemented", []))
        except ImportError:
            # ★ 离线回退：swlib_v2 顶层 import pythoncom 失败时直接读 yaml
            import capabilities_loader as CL
            bl = CL.by_level()
            nv = len(bl.get(CL.VERIFIED, []))
            np_ = len(bl.get(CL.PILOT, []))
            nn = len(bl.get(CL.NOT_IMPLEMENTED, []))
            src = "yaml 离线"
        if nv < 32:
            print("  [caps]     FAIL verified 掉到 %d！" % nv)
            ok = False
        else:
            print("  [caps]     PASS (%d verified / %d pilot / %d not_impl，源=%s)"
                  % (nv, np_, nn, src))
    except Exception as e:
        print("  [caps]     FAIL %s" % str(e)[:120])
        ok = False

    ok2 = True
    for name, script, marker, desc, sargs in STATIC_SUITES:
        ok_s, err = run_script(script, marker, timeout=120, args=sargs)
        print("  [%-10s] %s  %s%s"
              % (name, "PASS" if ok_s else "FAIL", desc,
                 "" if ok_s else "  <- " + err))
        if not ok_s:
            ok2 = False
    return ok and ok2


# ---------------- SW 层 ----------------
def layer_sw(suites, cold=False):
    results = []
    if cold:
        kill_sw()
    elif not sw_running():
        print("  (SW 未运行，首个套件冷启动 ~30s，之后共用同一实例)")

    for i, (name, script, marker, desc, _q) in enumerate(suites):
        if cold:
            kill_sw()
        print("  [%-11s] %-34s ... " % (name, desc), end="", flush=True)
        t0 = time.time()
        ok, err = run_script(script, marker)
        dt = time.time() - t0
        print("%-4s %5.1fs%s" % ("PASS" if ok else "FAIL", dt,
                                 "" if ok else "  " + err))
        results.append((name, ok, err))
        if not ok and not cold and i < len(suites) - 1:
            print("             (失败后重启 SW 再继续)")
            kill_sw()
    return results


def main():
    args = [a.lower() for a in sys.argv[1:]]
    static_only = "--static" in args
    quick = "--quick" in args
    cold = "--cold" in args
    force = "--force" in args
    want = [a for a in args if not a.startswith("--")]

    # 增量跳过
    if not force and not want and not static_only and unchanged_since_pass():
        print("源文件自上次全过后未改动，跳过回归（要强制重跑加 --force）")
        return 0

    print("=" * 62)
    print("  静态层（不启动 SW）")
    print("=" * 62)
    static_ok = layer_static()

    if static_only:
        print("\n>>> STATIC %s" % ("PASS" if static_ok else "FAIL"))
        return 0 if static_ok else 1

    if quick:
        sw_suites = [s for s in SW_SUITES if s[4]]
        mode_desc = "quick 模式，约 27 min"
    else:
        sw_suites = [s for s in SW_SUITES if not want or s[0] in want]
        mode_desc = "冷启模式，约 10 min" if cold else "共用单实例，约 6.5 min"

    if not sw_suites:
        print("\n未知套件：%s" % ", ".join(want))
        print("可选：%s" % ", ".join(s[0] for s in SW_SUITES + STATIC_SUITES))
        return 2

    print("\n" + "=" * 62)
    print("  SW 层（%s）" % mode_desc)
    print("=" * 62)
    results = layer_sw(sw_suites, cold=cold)

    if not cold:
        kill_sw()

    print("\n" + "=" * 62)
    passed = sum(1 for _, ok, _ in results if ok) + (1 if static_ok else 0)
    total = len(results) + 1
    print("  %d/%d 通过" % (passed, total))
    for name, ok, err in results:
        if not ok:
            print("  FAIL %s: %s" % (name, err))
    if not static_ok:
        print("  FAIL static")

    if passed == total:
        # 只有全量跑完才记 stamp，quick 不记（否则会误跳过）
        if not quick:
            open(STAMP, "w").write(source_digest())
        print("  >>> ALL PASS")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

