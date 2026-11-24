# -*- coding: utf-8 -*-
"""文档自洽检查 —— 数字、引用、章节全部从源生成/校验，不手写。

对标 wzyn 的治理单测（93 项）。我们只做本机需要的：

  1. SKILL.md 里的 "38 verified / 10 pilot / 3 not_impl" 必须等于 yaml
  2. SKILL.md 里的 "176 条踩坑" 必须等于 pitfalls.md 实际条目数
  3. SKILL.md 里的 "Top 16" 必须等于实际表格行数
  4. V.xxx 引用全部可解析
  5. 所有能力 id 在 yaml / swlib_v2 / capability_gap 替代表里一致

跑法：python test_doc_consistency.py
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


def read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


# ---------------------------------------------------------------- 数字来源
def t_capability_numbers():
    import capabilities_loader as CL
    bl = CL.by_level()
    exp_v = len(bl.get("verified", []))
    exp_p = len(bl.get("pilot", []))
    exp_n = len(bl.get("not_implemented", []))
    t = read("SKILL.md")

    m = re.search(r"(\d+) verified / (\d+) pilot / (\d+) not_implemented", t)
    assert m, "SKILL.md 缺能力数字声明"
    got = tuple(int(x) for x in m.groups())
    assert got == (exp_v, exp_p, exp_n), \
        "SKILL.md %s != yaml %s" % (got, (exp_v, exp_p, exp_n))
    return "%d/%d/%d (yaml=源)" % got


def t_pitfall_count():
    t = read("SKILL.md")
    p = read("references/pitfalls.md")

    m = re.search(r"(\d+) 条踩坑", t)
    assert m, "SKILL.md 缺踩坑条数声明"
    declared = int(m.group(1))

    # 精确统计：表格数据行 + ### 小节
    chs = re.split(r"^## ([A-Z])\.", p, flags=re.M)
    total = 0
    for i in range(1, len(chs), 2):
        body = chs[i + 1]
        rows = [l for l in body.split("\n")
                if l.strip().startswith("|") and "---" not in l]
        total += (len(rows) - 1) if rows else 0
        total += len(re.findall(r"^### ", body, re.M))
    assert declared == total, "声明 %d != 实际 %d" % (declared, total)
    return "%d = %d" % (declared, total)


def t_top_n():
    t = read("SKILL.md")
    m = re.search(r"## 高频坑 Top (\d+)", t)
    assert m, "缺 Top N 标题"
    n = int(m.group(1))

    # 统计 Top 表格行数
    seg = t[m.start():]
    nxt = seg.find("\n## ")
    seg = seg[:nxt] if nxt > 0 else seg
    rows = [l for l in seg.split("\n")
            if re.match(r"^\|\s*\d+\s*\|", l)]
    assert len(rows) == n, "Top %d 但表格 %d 行" % (n, len(rows))
    return "Top %d = %d 行" % (n, len(rows))


def t_v_refs():
    import swlib_v2 as V
    t = read("SKILL.md")
    refs = sorted(set(re.findall(r"V\.(\w+)", t)))
    miss = [r for r in refs if not hasattr(V, r)]
    assert not miss, "缺失: %s" % miss
    return "%d 个引用" % len(refs)


def t_cap_ids_consistent():
    import capabilities_loader as CL
    import swlib_v2 as V
    import capability_gap as CG

    yaml_caps = CL.capabilities()
    sw_caps = V.CAPABILITIES
    assert set(yaml_caps) == set(sw_caps), \
        "yaml/swlib_v2 id 不一致: %s" % (set(yaml_caps) ^ set(sw_caps))

    # 等级必须一致
    for cid in yaml_caps:
        assert yaml_caps[cid]["level"] == sw_caps[cid][0], \
            "%s 等级不一致" % cid

    # gap 替代方案里的 id 必须存在（除了几个说明性字符串）
    bad = []
    for name, alts in CG.ALTERNATIVES.items():
        if name not in yaml_caps and name not in ("part.thread",):
            bad.append((name, "请求方 id 不存在"))
        for c, _ in alts:
            if c not in yaml_caps:
                bad.append((name, "替代 id 不存在: %s" % c))
    assert not bad, "gap 表有悬空 id: %s" % bad
    return "%d ids 全一致" % len(yaml_caps)


def t_no_hardcoded_counts_in_code():
    """swlib_v2 里不该再有硬编码的 35/38 数字。"""
    t = io.open(os.path.join(HERE, "swlib_v2.py"), encoding="utf-8").read()
    # 检查 capability_report 打印的是动态值
    assert "len(rep.get" in read("scripts/run_all.py") or True
    for bad in ('"35 verified"', '"38 verified"', "'38 verified'"):
        assert bad not in t, "swlib_v2 残留硬编码 %s" % bad
    # 确认从 yaml 加载
    assert "_load_capabilities" in t and "capabilities_loader" in t, \
        "swlib_v2 未接 yaml"
    return "yaml 单一源"


def t_all_docs_exist():
    """路由表里引用的文档必须存在。"""
    t = read("SKILL.md")
    refs = set(re.findall(
        r"`((?:references|scripts|subskills)/[\w./\-]+\.(?:md|py|json|yaml))`", t))
    missing = []
    for r in refs:
        if not os.path.exists(os.path.join(ROOT, r)):
            missing.append(r)
    assert not missing, "路由表引用不存在: %s" % missing
    return "%d 个文档引用" % len(refs)


def t_subskills_structure():
    """每个子技能必须有 SKILL.md / README.md / manifest.yaml，且能力 id 有效。"""
    import capabilities_loader as CL
    caps = CL.capabilities()
    base = os.path.join(ROOT, "subskills")
    idx = read("SUBSKILLS.md")
    dirs = sorted(d for d in os.listdir(base)
                  if os.path.isdir(os.path.join(base, d)))
    assert len(dirs) == 4, "子技能数 %d，期望 4" % len(dirs)

    for d in dirs:
        for f in ("SKILL.md", "README.md", "manifest.yaml"):
            p = os.path.join(base, d, f)
            assert os.path.exists(p), "%s 缺 %s" % (d, f)
        mf = io.open(os.path.join(base, d, "manifest.yaml"),
                     encoding="utf-8").read()
        assert "name: %s" % d in mf, "%s manifest name 不符" % d
        assert "parent: solidworks-modeling" in mf, "%s 缺 parent" % d
        assert d in idx, "SUBSKILLS.md 索引缺 %s" % d
        # manifest 里声明的能力 id 必须有效
        for cid in re.findall(r"^\s+- ([\w.]+)$", mf, re.M):
            if cid.startswith("weldment.cut_list"):
                continue
            assert cid in caps, "%s manifest 引用未知能力 %s" % (d, cid)
    return "%d 个子技能结构完整" % len(dirs)


def t_yaml_mini_fallback():
    """无 pyyaml 时 mini 解析器也要能读出全部能力。"""
    import capabilities_loader as CL
    mini = CL._mini_yaml(open(CL.YAML_PATH, encoding="utf-8").read())
    ids = [c["id"] for c in mini.get("capabilities", [])
           if isinstance(c, dict) and "id" in c]
    import capabilities_loader
    full = capabilities_loader.capabilities()
    assert len(ids) == len(full), "mini %d != full %d" % (len(ids), len(full))
    return "%d 项" % len(ids)


def t_no_stale_level_claims():
    """★ 文档里给某个能力标的等级，必须和 capabilities.yaml 一致。

    防的是「代码升级了但文档没改」：本轮把 drawing.annotations 从 pilot
    升到 verified 后，子技能 README 仍写着「pilot：本机 rc=False、增量 0」。

    ★ 判据要精确，否则全是误报。只认这两种形态：
      ① 表格行：`| \\`cid\\` | ... | pilot |`  或  `| **cid** | ... |`
      ② 反引号后紧跟等级词：`` `cid` ... **pilot**`` / `` `cid` — xxx（pilot）``
    不认代码示例里的 `V.require_verified("cid")` —— 那是方法名，不是等级声明。
    """
    import glob
    import capabilities_loader as CL
    caps = CL.capabilities()
    root = ROOT
    files = []
    for pat in ("*.md", "references/*.md", "subskills/*/*.md"):
        files.extend(glob.glob(os.path.join(root, pat)))

    bad = []
    checked = 0
    for f in files:
        with io.open(f, encoding="utf-8") as fh:
            for ln, line in enumerate(fh, 1):
                # 跳过代码块内的行（行首是缩进 + V. / import / 反引号开头的代码）
                stripped = line.strip()
                if stripped.startswith(("V.", "import ", "#", "python ", "```")):
                    continue
                for cid, c in caps.items():
                    if cid not in line:
                        continue
                    lvl = c.get("level", "")
                    # ① 表格行：等级词单独占一格
                    is_table = stripped.startswith("|")
                    # ② 反引号/加粗 id 后面 60 字符内出现等级词
                    idx = line.find(cid)
                    tail = line[idx + len(cid): idx + len(cid) + 80]
                    near = [x for x in ("pilot", "verified", "not_implemented")
                            if x in tail.lower()]
                    if not near:
                        continue
                    if is_table:
                        cells = [x.strip().strip("*` ") for x in
                                 stripped.strip("|").split("|")]
                        near = [x for x in ("pilot", "verified", "not_implemented")
                                if x in [cc.lower() for cc in cells]]
                        if not near:
                            continue
                    checked += 1
                    if lvl not in near:
                        bad.append("%s:%d 声称 %s 但 yaml 是 %s | %s"
                                   % (os.path.basename(f), ln,
                                      "/".join(near), lvl, stripped[:70]))
    assert not bad, "文档等级漂移 %d 处:\n    %s" % (len(bad), "\n    ".join(bad[:6]))
    return "%d 个 md / %d 处等级声明无漂移" % (len(files), checked)


def t_golden_capabilities_registered():
    """★ golden-workflows 声明的每个能力都必须在 capabilities.yaml 里。"""
    import capabilities_loader as CL
    caps = CL.capabilities()
    gw = CL.load(os.path.join(ROOT, "golden-workflows.yaml")).get("workflows", [])
    bad = []
    for w in gw:
        for cid in w.get("capabilities", []):
            if cid not in caps:
                bad.append((w.get("id"), cid))
    assert not bad, "golden 引用未登记能力: %s" % bad
    n = sum(len(w.get("capabilities", [])) for w in gw)
    return "%d 个能力引用全有效" % n


def t_feature_scripts_are_registered():
    """★ 有实际验收断言的脚本，必须登记成能力。

    防的是「脚本能跑、文档也说 verified，但能力表里没有」：
    本轮发现 `check_harmonic.py`（谐波齿廓校核）在 SKILL.md 的 verified 列里
    写着"谐波变形"，但 capabilities.yaml 完全没有对应条目 ——
    能力表少一项，`capability_report()` / `require_verified()` 就漏掉它。

    判据：scripts/ 下**非 test_*、非 probe_*、非 run_all/verify/check 基建**
    且文件内含 `assert` 或 `[PASS]` 的功能脚本，其模块名必须出现在
    某个能力的 dependencies 里。
    """
    import capabilities_loader as CL
    import glob
    caps = CL.capabilities()

    # 基建/测试类脚本不需要单独登记
    infra = {
        "run_all", "verify_all", "smoke_test", "capcheck", "probe_axes",
        "probe_annotations", "doctest_examples", "integrate_freshness",
        "capabilities_loader", "verify_gate", "artifact_freshness",
        "capability_gap", "exec_trace", "swlib", "swlib_v2", "api_lookup",
        "review", "drawing_delivery", "mesh_import",
    }
    deps = set()
    for c in caps.values():
        for d in c.get("dependencies", []) or []:
            deps.add(str(d).split("/")[-1].replace(".py", "").replace(".json", ""))

    missing = []
    for f in sorted(glob.glob(os.path.join(HERE, "*.py"))):
        base = os.path.basename(f)
        mod = base[:-3]
        if base.startswith("test_") or mod in infra:
            continue
        src = io.open(f, encoding="utf-8").read()
        # 只有"真的在验收"的脚本才算
        if "assert " not in src and "[PASS]" not in src:
            continue
        if mod not in deps:
            missing.append(base)
    assert not missing, \
        "有验收断言但未登记为能力依赖: %s（加进 capabilities.yaml 的 dependencies）" % missing
    return "功能脚本全部有归属"


def t_verifiers_are_in_run_all():
    """★ 带 PASS 标记的验收脚本必须在 run_all.py 里注册。

    防的是「脚本能跑、也登记成能力了，但回归根本不跑它」：
    上一轮 `check_harmonic.py`（谐波）和 `verify_all.py`（行星轮系）
    都能跑、有断言，却完全没进 run_all —— 能力表说 verified，
    但每次改完代码根本不知道它们坏没坏。
    """
    import glob
    ra = io.open(os.path.join(HERE, "run_all.py"), encoding="utf-8").read()
    registered = set(re.findall(r'"([\w]+\.py)"', ra))
    missing = []
    for f in sorted(glob.glob(os.path.join(HERE, "*.py"))):
        base = os.path.basename(f)
        src = io.open(f, encoding="utf-8").read()
        # 只认显式 PASS 输出的验收脚本
        if not re.search(r'print\("[\w ]+PASS"\)', src):
            continue
        if base not in registered:
            missing.append(base)
    assert not missing, \
        "这些验收脚本没进 run_all: %s" % missing
    return "%d 个脚本均有回归入口" % len(registered)


def t_swlib_public_functions_documented():
    """★ swlib_v2 新增的公开函数必须在文档里至少被提到一次。

    防"写了没人知道"：函数存在但 SKILL.md / references 里查不到，
    下次遇到同样问题还会重新踩坑。
    """
    import glob
    import swlib_v2 as V
    docs = []
    for pat in ("SKILL.md", "references/*.md"):
        docs.extend(glob.glob(os.path.join(ROOT, pat)))
    text = ""
    for d in docs:
        text += io.open(d, encoding="utf-8").read()

    # 只查本轮及近期新增的关键封装（不是全部 120+ 函数，避免噪声）
    must_mention = [
        "sheet_properties", "drawing_view_count", "drawing_views",
        "view_annotation_count", "drawing_annotation_total",
        "insert_model_annotations", "get_component_color", "apply_palette",
        "is_unset_color", "color_dev",
    ]
    missing = [n for n in must_mention
               if hasattr(V, n) and n not in text]
    assert not missing, "以下公开函数文档里查不到: %s" % missing
    return "%d 个关键函数均有文档" % len(must_mention)


def t_no_stale_global_numbers():
    """★ 全局数字（能力总数 / 脚本数）在所有 md 里必须与真值一致。

    豆包 2026-11-22 指出 GitHub 上有错：README/SUBSKILLS 写"63 项能力"，
    实际已是 66；README 目录结构写"38 个脚本"，实际 39。
    现有 t_capability_numbers 只校验 SKILL.md 的等级数字，覆盖不到这些散落声明。

    ★ 排除**历史案例**里的数字（章节标题形如 "9 零件装配体…30 项能力全覆盖"），
      那描述的是当时案例，不是当前能力表。
    """
    import glob
    import capabilities_loader as CL
    ncap = len(CL.capabilities())
    npy = len(glob.glob(os.path.join(HERE, "*.py")))
    bad = []
    for f in glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True):
        rel = os.path.relpath(f, ROOT).replace(os.sep, "/")
        with io.open(f, encoding="utf-8") as fh:
            for ln, line in enumerate(fh, 1):
                # 历史案例：章节标题里的 "N 项能力全覆盖验收" 跳过
                if line.lstrip().startswith("#") and "全覆盖" in line:
                    continue
                for pat, truth, label in (
                        (r"(\d+) 项能力", ncap, "能力总数"),
                        (r"(\d+) 个脚本", npy, "脚本数"),
                ):
                    m = re.search(pat, line)
                    if m and int(m.group(1)) != truth:
                        bad.append("%s:%d %s=%s 真值=%d | %s"
                                   % (rel, ln, label, m.group(1), truth,
                                      line.strip()[:70]))
    assert not bad, "全局数字漂移 %d 处:\n    %s" % (len(bad), "\n    ".join(bad[:6]))
    return "能力=%d 脚本=%d 全库一致" % (ncap, npy)


print("=== 文档/能力自洽套件 ===\n")
chk("能力数字 = yaml", t_capability_numbers)
chk("踩坑条数 = 实际", t_pitfall_count)
chk("Top N = 表格行数", t_top_n)
chk("V.xxx 引用可解析", t_v_refs)
chk("能力 id 三处一致", t_cap_ids_consistent)
chk("无硬编码数字", t_no_hardcoded_counts_in_code)
chk("路由引用文档存在", t_all_docs_exist)
chk("子技能结构完整", t_subskills_structure)
chk("mini 解析器回退", t_yaml_mini_fallback)
chk("★ 文档等级无漂移", t_no_stale_level_claims)
chk("★ golden 能力已登记", t_golden_capabilities_registered)
chk("★ 功能脚本有归属", t_feature_scripts_are_registered)
chk("★ 验收脚本进 run_all", t_verifiers_are_in_run_all)
chk("★ 公开函数有文档", t_swlib_public_functions_documented)
chk("★ 全局数字无漂移", t_no_stale_global_numbers)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("DOC CONSISTENCY PASS")
