# -*- coding: utf-8 -*-
"""真实项目集成：给 belt_actuator 加交付新鲜度门禁

验证三件事：
  1. 上一轮已存在的 14 件零件 → 全部判 OLD（不能冒充本轮成果）
  2. 新导出一个文件 → 判 true
  3. 几何 PASS + 旧文件 → 整体 FAIL

跑法：python integrate_freshness.py [项目目录]
默认用环境变量 BELT_ACTUATOR_DIR，其次用脚本所在盘的 belt_actuator 目录。
找不到时直接跳过（不算失败），避免换机器后硬报错。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import artifact_freshness as F   # noqa: E402
from verify_gate import Gate     # noqa: E402

PROJ = (sys.argv[1] if len(sys.argv) > 1
        else os.environ.get("BELT_ACTUATOR_DIR")
        or os.path.join(os.path.splitdrive(HERE)[0] + os.sep, "yysls", "belt_actuator"))
OUT = os.path.join(PROJ, "out")
BASE_FILE = os.path.join(PROJ, ".baseline.json")

if not os.path.isdir(OUT):
    print("跳过：找不到 belt_actuator 输出目录 %s" % OUT)
    print("用法：python integrate_freshness.py <项目目录>")
    sys.exit(0)

# 本轮声明要交付的文件（从 REPORT.json 读，模拟真实流程）
import json
rep_path = os.path.join(OUT, "REPORT.json")
if os.path.exists(rep_path):
    with open(rep_path, encoding="utf-8") as f:
        report = json.load(f)
    parts = [p["file"] for p in report.get("parts", [])]
    deliverables = [os.path.join(OUT, "parts", p) for p in parts]
    deliverables += [
        os.path.join(OUT, "belt_actuator.SLDASM"),
        os.path.join(OUT, "belt_actuator.STEP"),
        os.path.join(OUT, "drawing", "belt_actuator.pdf"),
    ]
else:
    deliverables = []

deliverables = [p for p in deliverables if os.path.exists(p)]
print("本轮声明交付 %d 个文件" % len(deliverables))
print()

# ---- 场景 1: 用当前状态当基线，然后立即判定 → 应全部 OLD
print("=== 场景 1: 无任何新产出 ===")
base = F.scan(OUT)
base.save(BASE_FILE)
rep1 = F.diff(base, OUT, paths=deliverables)
print("  verdict=%s" % ("PASS" if rep1.passed else "BLOCKED"))
old_cnt = sum(1 for i in rep1.items if i.produced_this_run is False)
print("  OLD 文件 %d / %d" % (old_cnt, len(rep1.items)))
assert not rep1.passed, "无新产出不该 PASS"
assert old_cnt == len(rep1.items), "全部应为 OLD"
print("  -> 正确拒绝：上一轮的零件不能当本轮成果")
print()

# ---- 场景 2: 新写一个文件（模拟本轮真实产出）
print("=== 场景 2: 本轮新增 1 个文件 ===")
newp = os.path.join(OUT, "parts", "P15_test.SLDPRT")
with open(newp, "wb") as f:
    f.write(b"simulated new part")
rep2 = F.diff(base, OUT, paths=[newp])
print("  verdict=%s  producedThisRun=%s"
      % ("PASS" if rep2.passed else "BLOCKED",
         rep2.items[0].produced_this_run))
assert rep2.passed
print("  -> 正确接受：新文件")
print()

# ---- 场景 3: 新文件 + 旧零件混在一起
print("=== 场景 3: 新文件 + 13 个旧零件 ===")
rep3 = F.diff(base, OUT, paths=[newp] + deliverables[:13])
n_new = sum(1 for i in rep3.items if i.produced_this_run is True)
n_old = sum(1 for i in rep3.items if i.produced_this_run is False)
print("  verdict=%s  新增 %d / 旧 %d" % ("PASS" if rep3.passed else "BLOCKED", n_new, n_old))
assert not rep3.passed, "旧文件不能被掩盖"
print("  -> 正确拒绝：13 个旧零件拖垮整体")
print()

# ---- 场景 4: 几何门禁 + 新鲜度门禁合并
print("=== 场景 4: 几何 PASS + 新鲜度 FAIL ===")
geo = Gate("geometry")
geo.check("volume", True, "P1 dev 0.000%")
geo.check("bodies", True, "14 件实体数正确")
geo.check("interference", True, "无干涉")
gf = F.to_gate(rep3, "freshness")
merged = F.merge_gates([geo, gf], "belt_actuator_delivery")
v = merged.verdict()
print("  几何: %s" % ("PASS" if geo.verdict().passed else "FAIL"))
print("  新鲜度: %s" % ("PASS" if rep3.passed else "BLOCKED"))
print("  合并: %s" % v.status.upper())
assert not v.passed, "几何通过不能掩盖旧文件"
print("  -> 正确：整体 BLOCKED")
print()

os.remove(newp)

# ---- 场景 5: 从磁盘加载基线（跨进程）
print("=== 场景 5: 基线持久化后跨进程比对 ===")
b2 = F.Baseline.load(BASE_FILE)
print("  加载基线 %d 个文件" % len(b2.files))
rep5 = F.diff(b2, OUT, paths=deliverables[:3])
print("  verdict=%s（应 BLOCKED，因为都是旧文件）"
      % ("PASS" if rep5.passed else "BLOCKED"))
assert not rep5.passed
print()

print(">>> 真实项目集成验证通过")
print()
print("提示：真实建模流程应这样做——")
print("  1. base = F.scan(OUT); base.save(BASE_FILE)   # 建模前")
print("  2. ... 建模/导出 ...")
print("  3. F.require_fresh(base, OUT, paths=deliverables)   # 交付前硬门禁")
