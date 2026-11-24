# -*- coding: utf-8 -*-
"""工程图交付增强 —— 把「能出图」推到「能交图」的可自动验证部分。

对标 wzyn20051216/solidworks-automation-skill（2230★）的「机械图纸默认底线 5 条」。
底线本身写在 `references/drawing-standards.md`；本模块只做**能机器判的那部分**：

    create_drawing(sw, model_path, out_pdf, ...)   出图 → 插标注 → 导 PDF
    check_drawing(sw, drawing, pdf_path, ...)      视图数/标注数/PDF 大小/图纸属性

## 诚实的边界（不许谎称 verified）

| 项 | 状态 | 说明 |
|---|---|---|
| 视图数 ≥3 | 机器判 | GetViewCount |
| PDF > 阈值 | 机器判 | 回读字节 |
| 自动标注条数 >0 | 机器判 | IView.GetAnnotationCount 增量 |
| 尺寸链完整 | **人判** | 自动标注≠尺寸链，缺定位尺寸看不出来 |
| 孔表/槽表 | **pilot** | 未实现 |
| 标题栏规范 | **pilot** | 模板自带，字段填充未验证 |
| 引线不压线/不跨视图 | **人判** | 无可靠 API 判据 |

`check_drawing` 会把「机器判不了」的项显式标成 `manual`，而不是默认 PASS ——
沿用 verify_gate 的原则：无法验证 ≠ 通过。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 本机实测可用的中文模板（F:\SOLIDWORKS\data\templates 下）
TPL_CANDIDATES = (
    r"F:\SOLIDWORKS\data\templates\gb.drwdot",
    r"F:\SOLIDWORKS\data\templates\iso.drwdot",
    r"F:\SOLIDWORKS\data\templates\ansi.drwdot",
    r"C:\ProgramData\SolidWorks\SOLIDWORKS 2022\templates\Drawing.drwdot",
)

# 中文界面视图名（英文名恒 False，见 pitfalls S9）
VIEWS_CN = (("*等轴测", 0.15, 0.13), ("*前视", 0.06, 0.05), ("*上视", 0.06, 0.19))

MIN_PDF_BYTES = 5000      # 3 视图 + 标注的 PDF 实测 12~13KB，5KB 是安全下限
MIN_VIEWS = 3


def find_template():
    for p in TPL_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def create_drawing(sw, model_path, out_pdf=None, views=VIEWS_CN, tpl=None,
                   annotations=True, ann_types=None, min_pdf_bytes=MIN_PDF_BYTES,
                   force_rebuild=True, keep_open=False):
    r"""模型 → 工程图 → （可选）自动标注 → PDF。

    返回 dict：
        drawing       IDrawingDoc 包装对象（keep_open=True 时仍打开）
        pdf / pdf_bytes
        views_expected / views_made / view_names
        annotations_before / annotations_after / annotations_added
        annotations_rc / annotations_tries
        template / notes / checks

    ★ 三条前置（缺一返回 None 或 0 条，全部本机实测）：
      1. 模型文件必须已在磁盘上，且会话里【打开并激活】
      2. 宿主必须是 IDrawingDoc，不是 IModelDoc2
      3. 视图名必须中文（*等轴测 / *前视 / *上视）

    ★★ 2026-11-21 实测：`ann_types` 默认 None → 用 `V.ANN_WORKING`（=557056）。
       其它任何位组合在本机都是 0 条（见 swlib_v2.insert_model_annotations 的表格）。
    """
    import swlib_v2 as V

    notes = []
    if not os.path.exists(model_path):
        raise RuntimeError("模型文件不存在（工程图必须先有磁盘文件）: %s" % model_path)

    tpl = tpl or find_template()
    if not tpl:
        raise RuntimeError("找不到工程图模板，候选: %s" % (TPL_CANDIDATES,))

    # 1 确保模型在会话里打开并激活（否则 CreateDrawView 恒 False / 标注 0 条）
    try:
        V.open_doc(sw, model_path, doc_type=1 if model_path.lower().endswith(".sldprt") else 2)
    except Exception as e:
        notes.append("模型重开失败（可能已在会话里）: %s" % str(e)[:60])

    # 2 新建工程图
    dw = sw.NewDocument(tpl, 0, 0, 0)
    if dw is None:
        raise RuntimeError("NewDocument 返回 None，模板不可用: %s" % tpl)
    try:
        V.wrap(dw, "IModelDoc2").ForceRebuild3(False)
    except Exception:
        pass

    # 3 插视图
    made, names = 0, []
    for vn, x, y in views:
        v = V.drawing_view(dw, model_path, vn, x, y)
        nm = V.view_name_of(v) if v is not None else None
        if nm:
            made += 1
            names.append(nm)
    if force_rebuild:
        try:
            V.wrap(dw, "IModelDoc2").ForceRebuild3(False)
        except Exception:
            pass

    # 4 自动标注（rc 不可信，回读增量判成败）
    ann_before = V.drawing_annotation_total(dw)
    ann_rc, ann_tries = None, []
    if annotations:
        types = V.ANN_WORKING if ann_types is None else int(ann_types)
        try:
            r = V.insert_model_annotations_checked(dw, option=0, types=types,
                                                   all_views=True)
            ann_rc, ann_tries = r.get("rc"), r.get("tries")
            if not r.get("ok"):
                notes.append(
                    "自动标注未插入（types=%d 试 %d 次，增量 0）—— "
                    "该模型可能无驱动尺寸" % (types, len(ann_tries or [])))
        except Exception as e:
            notes.append("自动标注调用失败: %s" % str(e)[:80])
        try:
            V.wrap(dw, "IModelDoc2").ForceRebuild3(False)
        except Exception:
            pass
    ann_after = V.drawing_annotation_total(dw)

    # 5 导 PDF
    pdf = out_pdf or (os.path.splitext(model_path)[0] + ".pdf")
    os.makedirs(os.path.dirname(os.path.abspath(pdf)), exist_ok=True)
    if os.path.exists(pdf):
        try:
            os.remove(pdf)
        except Exception:
            pass
    try:
        V.wrap(dw, "IModelDoc2").SaveAs3(pdf, 0, 0)
    except Exception as e:
        notes.append("PDF 导出异常: %s" % str(e)[:80])
    pdf_bytes = os.path.getsize(pdf) if os.path.exists(pdf) else 0

    rep = {
        "drawing": dw,
        "template": tpl,
        "pdf": pdf,
        "pdf_bytes": pdf_bytes,
        "sheet": V.sheet_properties(dw),
        "views_expected": len(views),
        "views_made": made,
        "view_names": names,
        "view_count_api": V.drawing_view_count(dw),
        "annotations_before": ann_before,
        "annotations_after": ann_after,
        "annotations_added": (ann_after or 0) - (ann_before or 0),
        "annotations_rc": ann_rc,
        "annotations_tries": ann_tries,
        "notes": notes,
    }
    rep["checks"] = check_drawing(sw, dw, pdf, rep, min_pdf_bytes=min_pdf_bytes)
    rep["status"] = _status(rep["checks"])

    if not keep_open:
        V.close_doc(sw, dw, force=True)
    return rep


def check_drawing(sw, drawing, pdf_path, rep=None, min_pdf_bytes=MIN_PDF_BYTES,
                  min_views=MIN_VIEWS, require_annotations=False):
    """工程图交付的机器判据。

    每项 {"id", "status", "message", "kind"}：
        status  pass / warn / fail / manual
        kind    machine（机器判） / manual（必须人判，不默认 PASS）
    """
    import swlib_v2 as V

    rep = rep or {}
    checks = []

    def add(cid, ok, msg, kind="machine", level="fail"):
        checks.append({"id": cid, "status": ("pass" if ok else level),
                       "message": msg, "kind": kind})

    # ---- 视图数
    n = V.drawing_view_count(drawing)
    if n is None:
        add("views", False, "GetViewCount 取不到（无法验证）", level="fail")
    else:
        add("views", n >= min_views, "%d 个视图（下限 %d）" % (n, min_views))

    # ---- 视图名可读（证明视图真建出来了，不是空图纸）
    names = rep.get("view_names") or []
    if not names:
        names = [V.view_name_of(v) for v in V.drawing_views(drawing)]
        names = [x for x in names if x]
    add("views_named", len(names) >= min_views,
        "%d 个具名视图: %s" % (len(names), ",".join(names[:5])))

    # ---- PDF 字节
    sz = os.path.getsize(pdf_path) if pdf_path and os.path.exists(pdf_path) else 0
    add("pdf_bytes", sz > min_pdf_bytes,
        "%d B（下限 %d B）" % (sz, min_pdf_bytes))

    # ---- 图纸幅面（GetSize 两个 by-ref 出参）
    sh = rep.get("sheet") or {}
    w, h = sh.get("width_mm"), sh.get("height_mm")
    if w and h:
        add("sheet_size", True, "%.1f × %.1f mm（%.2f × %.2f in）"
            % (w, h, w / 25.4, h / 25.4))
    else:
        add("sheet_size", False, "读不到幅面尺寸（ISheet.GetSize 失败）",
            level="warn")

    # ---- 自动标注
    # ★ 判据优先看**增量**，不是总数：本机实测模型自带的标注（孔中心标记等）
    #   会让总数 >0，但 InsertModelAnnotations 本轮一条没插（rc=False、增 0）。
    #   只看总数会把"没插进去"误判成 pass —— 这正是"返回 True ≠ 成功"的同类错误。
    added = rep.get("annotations_added") or 0
    total = rep.get("annotations_after") or 0
    rc = rep.get("annotations_rc")
    if added > 0:
        add("annotations", True, "本轮新增 %d 条（总数 %d，rc=%s）"
            % (added, total, rc))
    elif total > 0:
        add("annotations", False,
            "本轮增 0 条，但总数 %d 条（模型自带，非本轮插入；rc=%s）"
            % (total, rc), level="warn")
    else:
        add("annotations", False, "标注 0 条（rc=%s），模型可能无驱动尺寸" % rc,
            level="warn" if not require_annotations else "fail")

    # ---- 人判项：显式标 manual，绝不默认 PASS
    add("dim_chain", None, "尺寸链完整度须人眼核对（自动标注≠尺寸链）", kind="manual")
    add("hole_table", None, "孔表/槽表未实现（pilot），密集孔须手工补", kind="manual")
    add("title_block", None, "标题栏字段是否填全须人眼核对（模板自带框线）", kind="manual")
    add("no_overlap", None, "引线是否跨视图/压孔/压中心线/侵入标题栏须人眼核对",
        kind="manual")

    # manual 项在 status 里不参与 pass/fail，但会拉低整体到 warn
    for c in checks:
        if c["kind"] == "manual":
            c["status"] = "manual"
    return checks


def _status(checks):
    st = [c["status"] for c in checks]
    if "fail" in st:
        return "fail"
    if "warn" in st or "manual" in st:
        return "warn"
    return "pass"


def render(rep):
    icon = {"pass": "OK  ", "warn": "WARN", "fail": "FAIL", "manual": "MAN "}
    lines = ["=== 工程图交付: %s ===" % os.path.basename(rep.get("pdf") or "")]
    lines.append("  模板: %s" % os.path.basename(rep.get("template") or "-"))
    sh = rep.get("sheet") or {}
    if sh.get("width_mm"):
        lines.append("  幅面: %.1f × %.1f mm（%.2f × %.2f in），比例 %s:%s"
                     % (sh["width_mm"], sh["height_mm"],
                        sh["width_mm"] / 25.4, sh["height_mm"] / 25.4,
                        sh.get("scale_num"), sh.get("scale_den")))
    lines.append("  视图: 期望 %s / 实得 %s  (%s)"
                 % (rep.get("views_expected"), rep.get("views_made"),
                    ",".join(rep.get("view_names") or []) or "-"))
    lines.append("  标注: 前 %s → 后 %s（增 %s）"
                 % (rep.get("annotations_before"), rep.get("annotations_after"),
                    rep.get("annotations_added")))
    for c in rep.get("checks", []):
        lines.append("  [%s] %-14s %s" % (icon.get(c["status"], "?"),
                                          c["id"], c["message"]))
    lines.append("  ---- status: %s ----" % (rep.get("status", "?")).upper())
    for n in rep.get("notes", []):
        lines.append("  · " + n)
    return "\n".join(lines)
