# -*- coding: utf-8 -*-
"""结果自审查 —— 「预览非空白 ≠ 模型正确」的结构化判定。

对标 wzyn20051216/solidworks-automation-skill（2230★）`scripts/sw_review.py` 的
`run_review()`。它做四件事：导出四视图 → 检查文件存在与大小 → 逐项 checks →
写 `*_review_report.json`。

## 为什么需要它

已有三机制各管一段：
  - `artifact_freshness` 管「文件是不是本轮生成的」
  - `capability_gap`      管「这个能力到底行不行」
  - `exec_trace`          管「过程怎么走的」
但**没人管「出来的图到底是不是对的」**。`four_views` + `save_png` 只回读文件大小，
一张全白图、四个视图同一张图、零件被裁掉一半 —— 全都"成功返回"。

本模块把目视复核变成可自动执行的门禁：

    rep, path = run_review(m, out_dir, basename="bracket",
                           expected_outputs=[r"out\\bracket.sldprt"])
    print(rep["status"], rep["issues"])
    rep["evaluation"]["checks"]      # 逐项

## 判定项

| check | 判据 | 失败含义 |
|---|---|---|
| `views_present` | 四张 PNG 都存在且 >min_bytes | 截图失败 |
| `views_distinct` | 四视图 **md5 互异** | 视图没真的切（装配体视口锁死） |
| `views_not_blank` | 非背景像素占比 ≥ min_content | 空白图 / 模型不在视口 |
| `views_have_color` | 内容区颜色种类 ≥ min_colors | 单色块，看不出结构 |
| `views_not_clipped` | 内容不顶到四条边 | 零件被裁切（装配体常见） |
| `expected_outputs` | 每个文件存在且 > min_expected_bytes | 交付物缺失/0 字节 |
| `expected_md5` | 给了期望 md5 就比对 | 文件不是期望的那份 |

★ 关键原则：`预览非空白 ≠ 模型正确`。上面这些只能排除「假成功」，
   **比例/方位/部件缺失/重叠悬空仍须人眼确认** —— 报告里会显式写明这一条。

## 用法

    import review as RV
    rep, path = RV.run_review(m, r"out\\review", basename="bracket",
                              expected_outputs=[r"out\\bracket.sldprt"])
    if rep["status"] != "pass":
        print(RV.render(rep))

命令行（对已存在文件做纯像素审查，不开 SW）：

    python review.py --images out\\smoke\\cyl_iso.png out\\smoke\\cyl_front.png
    python review.py --report out\\review\\bracket_review_report.json
"""
import hashlib
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

PASS, WARN, FAIL = "pass", "warn", "fail"

VIEWS = ("iso", "front", "top", "right")

# 像素判据默认值（本机 1400x900 灰度渲染实测）
MIN_CONTENT = 0.010        # 非背景像素占比下限 1%（空白图恒 <0.1%）
MIN_COLORS = 6             # 内容区量化色数下限
CLIP_MARGIN = 0.004        # 内容允许贴边的最小边距（占画幅比例）
MIN_EXPECTED_BYTES = 1024  # 交付文件下限


# ---------------------------------------------------------------- 图像统计
def _pil():
    try:
        from PIL import Image
        return Image
    except Exception as e:
        raise RuntimeError("需要 Pillow 做像素判据: %s" % e)


def image_stats(path):
    r"""统计一张 PNG 的内容占比/色数/贴边情况。

    ★ 背景色取「出现最多的量化颜色」，而不是假定纯白 —— 本机渲染背景是
      浅灰渐变，按纯白判会把整张图算成"全是内容"，判据就失效了。
    ★ 色数必须在**原始分辨率**上数：缩小图会把硬边插值成一圈过渡色，
      一块纯色矩形也能数出 6 种颜色，"防单色"就形同虚设。

    返回 dict：w/h/content_ratio/bg/colors/clipped_edges/md5
    """
    Image = _pil()
    im = Image.open(path).convert("RGB")
    w0, h0 = im.size

    try:
        import numpy as np
    except Exception:
        np = None

    if np is not None:
        arr = np.asarray(im, dtype=np.int16)
        q = (arr >> 4)                                  # 量化到 16 级，抗噪声
        packed = (q[:, :, 0].astype(np.int32) * 256
                  + q[:, :, 1].astype(np.int32) * 16 + q[:, :, 2])
        vals, counts = np.unique(packed, return_counts=True)
        bg_q = vals[int(counts.argmax())]
        bg = (((bg_q // 256) % 16) * 16 + 8,
              ((bg_q // 16) % 16) * 16 + 8,
              (bg_q % 16) * 16 + 8)
        diff = (np.abs(arr - np.array(bg, dtype=np.int16)).sum(axis=2))
        mask = diff > 36
        content = int(mask.sum())
        colors = int(np.unique(packed[mask]).size) if content else 0
        edge_counts = {
            "left": int(mask[:, :2].any(axis=1).sum()),
            "right": int(mask[:, -2:].any(axis=1).sum()),
            "top": int(mask[:2, :].any(axis=0).sum()),
            "bottom": int(mask[-2:, :].any(axis=0).sum()),
        }
    else:
        px = list(im.getdata())
        from collections import Counter

        def qz(c):
            return (c[0] >> 4, c[1] >> 4, c[2] >> 4)

        hist = Counter(qz(c) for c in px)
        bq = hist.most_common(1)[0][0]
        bg = (bq[0] * 16 + 8, bq[1] * 16 + 8, bq[2] * 16 + 8)
        content = 0
        cols = set()
        edge_counts = {"left": 0, "right": 0, "top": 0, "bottom": 0}
        w, h = im.size
        for i, c in enumerate(px):
            if (abs(c[0] - bg[0]) + abs(c[1] - bg[1]) + abs(c[2] - bg[2])) <= 36:
                continue
            content += 1
            cols.add(qz(c))
            y, x = divmod(i, w)
            if x <= 1:
                edge_counts["left"] += 1
            if x >= w - 2:
                edge_counts["right"] += 1
            if y <= 1:
                edge_counts["top"] += 1
            if y >= h - 2:
                edge_counts["bottom"] += 1
        colors = len(cols)

    total = float(w0 * h0) or 1.0
    # 贴边判定：某条边上内容像素数占该边长度 > 1%
    clipped = [k for k, v in edge_counts.items()
               if v > (h0 if k in ("left", "right") else w0) * 0.01]

    return {
        "path": path,
        "w": int(w0), "h": int(h0),
        "content_ratio": round(float(content) / total, 4),
        "colors": int(colors),
        "bg": [int(c) for c in bg],
        "clipped_edges": clipped,
        "bytes": os.path.getsize(path) if os.path.exists(path) else 0,
        "md5": md5(path),
    }


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(65536), b""):
            h.update(blk)
    return h.hexdigest()


# ---------------------------------------------------------------- 报告骨架
class Review(object):
    """累积检查项 → status / checks / issues / views。"""

    def __init__(self, basename="model"):
        self.basename = basename
        self.checks = []
        self.issues = []
        self.views = {}
        self.notes = []

    def check(self, cid, ok, message="", level=FAIL, evidence=None):
        st = PASS if ok else level
        self.checks.append({"id": cid, "status": st, "message": message,
                            "evidence": evidence})
        if st != PASS:
            self.issues.append("%s: %s" % (cid, message or st))
        return st

    def status(self):
        if any(c["status"] == FAIL for c in self.checks):
            return FAIL
        if any(c["status"] == WARN for c in self.checks):
            return WARN
        if not self.checks:
            return FAIL        # 空结果 = 无法验证 ≠ 通过
        return PASS

    def to_dict(self):
        return {
            "task": self.basename,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "status": self.status(),
            "checks": self.checks,
            "issues": self.issues,
            "views": self.views,
            "notes": self.notes,
            # 兼容 wzyn 的报告字段名
            "evaluation": {
                "status": self.status(),
                "issues": list(self.issues),
                "checks": list(self.checks),
            },
        }


def render(rep):
    lines = ["=== 结果自审查: %s ===" % rep.get("task", "")]
    icon = {PASS: "OK  ", WARN: "WARN", FAIL: "FAIL"}
    for c in rep.get("checks", []):
        lines.append("  [%s] %-20s %s" % (icon.get(c["status"], "?"),
                                          c["id"], c.get("message", "")))
    v = rep.get("views", {})
    if v:
        lines.append("  -- 视图 --")
        for k in VIEWS:
            d = v.get(k) or {}
            if d.get("error"):
                lines.append("    %-6s ERROR %s" % (k, d["error"]))
            else:
                lines.append("    %-6s %5dx%-5d 内容%5.2f%% 色数%3d md5=%s"
                             % (k, d.get("w", 0), d.get("h", 0),
                                d.get("content_ratio", 0) * 100,
                                d.get("colors", 0), (d.get("md5") or "")[:8]))
    lines.append("  ---- status: %s ----" % rep.get("status", "?").upper())
    for i in rep.get("issues", []):
        lines.append("  ! " + i)
    for n in rep.get("notes", []):
        lines.append("  · " + n)
    return "\n".join(lines)


# ---------------------------------------------------------------- 视图审查
def review_images(paths, min_content=MIN_CONTENT, min_colors=MIN_COLORS,
                  min_bytes=1000, expect_distinct=True):
    """纯像素审查（不开 SW）。paths 是 {名: 路径} 或路径列表。

    返回 Review。这一层可以在任何机器上跑，用于复查历史截图。
    """
    if isinstance(paths, (list, tuple)):
        paths = {("v%d" % i): p for i, p in enumerate(paths)}
    rv = Review("images")
    ok_all = True
    for name, p in paths.items():
        if not os.path.exists(p):
            rv.views[name] = {"path": p, "error": "文件不存在"}
            rv.check("view_%s" % name, False, "文件不存在: %s" % p)
            ok_all = False
            continue
        sz = os.path.getsize(p)
        if sz < min_bytes:
            rv.views[name] = {"path": p, "error": "过小 %d B" % sz}
            rv.check("view_%s" % name, False, "截图过小 %d B" % sz)
            ok_all = False
            continue
        st = image_stats(p)
        rv.views[name] = st
        rv.check("content_%s" % name, st["content_ratio"] >= min_content,
                 "内容占比 %.2f%%（下限 %.2f%%%s）"
                 % (st["content_ratio"] * 100, min_content * 100,
                    "" if st["content_ratio"] >= min_content else "，判为空白图"))
        rv.check("color_%s" % name, st["colors"] >= min_colors,
                 "色数 %d（下限 %d%s）"
                 % (st["colors"], min_colors,
                    "" if st["colors"] >= min_colors else "，判为单色块"),
                 level=WARN)
    if expect_distinct and len(rv.views) > 1:
        hashes = [v.get("md5") for v in rv.views.values() if v.get("md5")]
        uniq = len(set(hashes))
        rv.check("views_distinct", uniq == len(hashes),
                 "%d 张图 / %d 个不同 md5%s"
                 % (len(hashes), uniq,
                    "" if uniq == len(hashes) else "，视图没真的切"),
                 evidence={"md5": hashes})
    return rv


def review_files(expected_outputs, min_expected_bytes=MIN_EXPECTED_BYTES,
                 expected_md5=None, rv=None):
    """交付文件存在性/大小/md5 审查。"""
    rv = rv or Review("files")
    if not expected_outputs:
        rv.check("expected_outputs", False,
                 "未声明交付清单（无法验证 ≠ 通过）")
        return rv
    for p in expected_outputs:
        p = os.path.abspath(p)
        if not os.path.exists(p):
            rv.check("file_%s" % os.path.basename(p), False, "缺失: %s" % p)
            continue
        sz = os.path.getsize(p)
        rv.check("file_%s" % os.path.basename(p), sz > min_expected_bytes,
                 "%d B%s" % (sz, "" if sz > min_expected_bytes
                             else " ≤ %d B，判为空文件" % min_expected_bytes),
                 evidence={"size": sz})
        if expected_md5 and p in expected_md5:
            got = md5(p)
            rv.check("md5_%s" % os.path.basename(p), got == expected_md5[p],
                     "md5 不符 期望 %s 实得 %s" % (expected_md5[p][:8], got[:8]))
    return rv


# ---------------------------------------------------------------- 主入口
def run_review(model, out_dir, basename="model", expected_outputs=None,
               sw=None, views=VIEWS, min_bytes=1000, min_content=MIN_CONTENT,
               min_colors=MIN_COLORS, min_expected_bytes=MIN_EXPECTED_BYTES,
               expected_md5=None, use_trace=True, connect_version=2022):
    """四视图 + 文件 + 像素判据一次跑完，写 `<basename>_review_report.json`。

    model            : IModelDoc2（零件/装配体）
    out_dir          : 报告与 PNG 的输出目录
    basename         : 报告与文件名前缀
    expected_outputs : 交付文件清单（缺失/0 字节即 FAIL）
    sw               : 可传已连接的 ISldWorks；不传则内部 connect
    use_trace        : 用 exec_trace 记录每一步（默认开）

    返回 (report_dict, report_path)
    """
    import swlib_v2 as V

    os.makedirs(out_dir, exist_ok=True)
    rv = Review(basename)
    tr = None
    if use_trace:
        try:
            import exec_trace as ET
            tr = ET.Trace("review:" + basename)
            tr.env(python=sys.version.split()[0])
        except Exception:
            tr = None

    # ---- 1 四视图
    if sw is None:
        sw = V.connect(version=connect_version, verbose=False)
    for name in views:
        p = os.path.join(out_dir, "%s_%s.png" % (basename, name))
        try:
            if tr:
                with tr.step("view." + name, kind="export") as s:
                    info = V.save_png(sw, model, p, name, min_bytes=min_bytes)
                    s.output("size", info["size"])
            else:
                V.save_png(sw, model, p, name, min_bytes=min_bytes)
            rv.views[name] = {"path": p}          # ★ 成功也要登记，否则下面 ok_views 恒空
        except Exception as e:
            rv.views[name] = {"path": p, "error": str(e)[:120]}
            rv.check("view_%s" % name, False, "截图失败: %s" % str(e)[:80])

    # ---- 2 像素判据（对成功的图）
    ok_views = {k: v["path"] for k, v in rv.views.items()
                if not v.get("error") and os.path.exists(v["path"])}
    if ok_views:
        sub = review_images(ok_views, min_content=min_content,
                            min_colors=min_colors, min_bytes=min_bytes,
                            expect_distinct=len(ok_views) > 1)
        for k, v in sub.views.items():
            rv.views.setdefault(k, {}).update(v)
        rv.checks.extend(sub.checks)
        rv.issues.extend(sub.issues)

    # 缺视图也算失败（少一张就不能目视复核）
    missing = [k for k in views if k not in ok_views]
    if missing:
        rv.check("views_present", False, "缺视图: %s" % ",".join(missing))
    else:
        rv.check("views_present", True, "%d 视图齐" % len(ok_views))

    # ---- 3 裁切检查（装配体常见：边缘零件被切掉）
    clipped = [k for k, v in rv.views.items() if v.get("clipped_edges")]
    rv.check("views_not_clipped", not clipped,
             "无裁切" if not clipped
             else "内容顶到画幅边: %s（零件被裁切）" % ",".join(clipped),
             level=WARN)

    # ---- 4 交付文件
    sub = review_files(expected_outputs, min_expected_bytes=min_expected_bytes,
                       expected_md5=expected_md5, rv=Review(basename))
    rv.checks.extend(sub.checks)
    rv.issues.extend(sub.issues)

    # ---- 5 诚实的边界说明（不许把"图非空白"说成"模型正确"）
    rv.notes.append("预览非空白 ≠ 模型正确：比例/方位/部件缺失/重叠悬空须人眼复核")
    rv.notes.append("像素判据只排除空白图/同图/裁切，不判断几何是否可制造")

    rep = rv.to_dict()

    # ---- 6 trace + 报告落盘
    if tr:
        tr.note("verdict", status=rep["status"], issues=len(rep["issues"]))
        try:
            tr.save(os.path.join(out_dir, "%s_trace.json" % basename))
        except Exception:
            pass
        rep["trace"] = "%s_trace.json" % basename

    path = os.path.join(out_dir, "%s_review_report.json" % basename)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    rep["report_path"] = path
    return rep, path


def to_gate(rep, name="review"):
    """把审查结果转成 verify_gate.Gate，便于和几何门禁合并。"""
    from verify_gate import Gate, PASS as GP, WARN as GW, FAIL as GF
    g = Gate(name)
    lvl = {PASS: GP, WARN: GW, FAIL: GF}
    for c in rep.get("checks", []):
        g.check(c["id"], c["status"] == PASS, c.get("message", ""),
                level=lvl.get(c["status"], GF))
    if not rep.get("checks"):
        g.check("review_missing", None, "没有任何审查项")
    return g


# ---------------------------------------------------------------- CLI
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="结果自审查（像素判据 + 报告）")
    ap.add_argument("--images", nargs="+", help="要审查的 PNG 列表")
    ap.add_argument("--report", help="读已有 *_review_report.json 并重印")
    ap.add_argument("--out", default="out/review", help="报告输出目录")
    ap.add_argument("--basename", default="images")
    ap.add_argument("--min-content", type=float, default=MIN_CONTENT)
    a = ap.parse_args(argv)

    if a.report:
        with open(a.report, encoding="utf-8") as f:
            rep = json.load(f)
        print(render(rep))
        return 0 if rep.get("status") == PASS else 1

    if not a.images:
        ap.print_help()
        return 2

    rv = review_images(a.images, min_content=a.min_content)
    rep = rv.to_dict()
    rep["task"] = a.basename
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "%s_review_report.json" % a.basename)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(render(rep))
    print("\n报告: %s" % path)
    return 0 if rep["status"] == PASS else 1


if __name__ == "__main__":
    sys.exit(main())
