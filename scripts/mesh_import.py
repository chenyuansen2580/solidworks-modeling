# -*- coding: utf-8 -*-
r"""网格导入（STL/OBJ/GLB）—— 视觉参考件，不是参数化实体。

对标 wzyn20051216/solidworks-automation-skill（2230★）的
`scripts/sw_import_mesh_reference.py`。

## 为什么不能用 OpenDoc6

```python
sw.OpenDoc6("a.stl", 0, ...)        # → 返回 None / 空文档
```
网格文件不是 SolidWorks 原生格式，`OpenDoc6` 走的是"打开文档"路径，
对 STL/OBJ 直接失败（或开出一个空零件）。正确路径是 **`ISldWorks.LoadFile4`**：

```python
sw.LoadFile4(path, "r", <IDispatch>, errors)     # 4 参，Errors 是 by-ref
```

## 三个坑（本机 SW2022 实测）

1. **第 3 参不能传 None** —— `ImportData` 声明为 VT_DISPATCH，
   传 None 报"类型不匹配 (-2147352571)"。必须传一个**空 dispatch VARIANT**
   （`create_empty_dispatch_variant()` 已封装）。
2. **返回 None 也可能是成功** —— 返回值是 IDispatch，导入完成后常返回 None；
   判据必须看**文档是否出现 + bbox 是否合理**，不是看返回值。
3. **Errors 是 by-ref 出参** —— 用 `swlib.call_byref` 才能取回真实错误码。

## 关键认知：网格件不是参数化实体

| 能做什么 | 不能做什么 |
|---|---|
| 当视觉参考（对着建模） | 拉伸/切除/抽壳 |
| 量尺寸（bbox/测量） | 加配合当机构件 |
| 转成曲面做参照面 | 出工程图（无特征树） |
| 导出 STEP（转实体后） | 参数化修改 |

导入的 STL 在 SW 里是**图形体（graphics body）/ 导入实体**，
`body_counts()` 会看到实体，但**特征树里没有可编辑的草图/特征**。
所以本模块一律把它登记为 `import.mesh` = **pilot**，不谎称 verified。

## 用法

```python
import mesh_import as MI

rep = MI.import_mesh(sw, r"D:\ref\part.stl", expect_bbox_mm=(-50,-30,0, 50,30,20))
print(MI.render(rep))
# 导入成功后 bbox 单位是米，本模块已统一成 mm 并校验坐标轴
```

GLB 需先转 OBJ/STL（本机 SW2022 无 glTF 导入器）：
`MI.convert_glb_to_obj(src, dst)` 只做提示，不做转换（无外部依赖）。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 本机 SW2022 实测可导入的网格格式（按可靠性排序）
MESH_EXTS = (".stl", ".obj", ".3mf", ".ply", ".off")
# 明确不可导入，需要外部转换
UNSUPPORTED_EXTS = (".glb", ".gltf", ".fbx", ".dae")

# LoadFile4 的 ArgString（真正的"导入模式"开关，通过 arg= 传入）：
#   "r"  = 读入为图形体（reference geometry，最轻，推荐做参考）★ 默认
#   "s"  = 读入为曲面/实体（尝试缝合，慢且常失败）
#   ""   = 用默认选项
# ★ 本机实测：'r' / 's' / '' 三种都能导入成功、bbox 一致，
#   但无论哪种 GetBodies2 都是 (0,0) —— 网格体只能走 MeshBodyFeature 链。
ARG_REFERENCE = "r"
ARG_SOLID = "s"
ARG_DEFAULT = ""


def create_empty_dispatch_variant():
    """构造 LoadFile4 第 3 参要的「空 IDispatch」。

    ★★ 这是整个网格导入的命门：第 3 参声明为 VT_DISPATCH，
      传 `None` → COM 报"类型不匹配 (-2147352571)"；
      传 `pythoncom.Missing` → 同样失败。
      必须传一个真正的空 IDispatch（VARIANT(VT_DISPATCH, None)）。
    """
    import pythoncom
    import win32com.client
    return win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)


def _norm_ext(path):
    return os.path.splitext(str(path))[1].lower()


def convert_glb_to_obj(src, dst=None):
    """GLB/GLTF 无法直接导入 SW2022，这里只给出可执行的转换路径。

    不偷偷调用外部工具（会引入不可控依赖），只返回命令模板：
        blender --background --python-expr "..."  或
        assimp export in.glb out.obj
    """
    if _norm_ext(src) not in UNSUPPORTED_EXTS:
        return None
    return {
        "src": src,
        "dst": dst or (os.path.splitext(src)[0] + ".obj"),
        "why": "SW2022 无 glTF 导入器（LoadFile4 只认 %s）" % (MESH_EXTS,),
        "commands": [
            "assimp export \"%s\" \"%s\"" % (src, dst or "out.obj"),
            "blender --background --python-expr "
            "\"import bpy;bpy.ops.import_scene.gltf(filepath=r'%s');"
            "bpy.ops.wm.obj_export(filepath=r'%s')\""
            % (src, dst or "out.obj"),
        ],
    }


def mesh_bodies(doc):
    """取导入的网格体（IBody2 列表）。

    ★★ 本机实测（2026-11-21）：网格件**不在** `IPartDoc.GetBodies2()` 里 ——
      它既不算实体（0）也不算曲面体（0），GetBodies2 直接返回 None。
      真正的路径是遍历特征树：

        MeshFeatureContainer（"图形1"）
          └─ MeshBodyFeature（"图形 (闭合) -1"）
               └─ GetSpecificFeature2() → IBody2

      拿到 IBody2 后 `IsMeshBody` 为 True，`GetMeshBody` 才是 IMemoryMesh 之类。
      所以网格导入的判据只能走这条链，不能用 body_counts()。
    """
    import swlib_v2 as V
    out = []
    try:
        f = doc.FirstFeature()
    except Exception:
        return out
    guard = 0
    while f is not None and guard < 500:
        guard += 1
        fe = V.wrap(f, "IFeature")
        try:
            tn = fe.GetTypeName2()
        except Exception:
            tn = ""
        if tn == "MeshFeatureContainer":
            sub = fe.GetFirstSubFeature()
            g2 = 0
            while sub is not None and g2 < 200:
                g2 += 1
                sf = V.wrap(sub, "IFeature")
                try:
                    if sf.GetTypeName2() == "MeshBodyFeature":
                        body = sf.GetSpecificFeature2()
                        if body is not None:
                            out.append(V.wrap(body, "IBody2"))
                except Exception:
                    pass
                try:
                    sub = sf.GetNextSubFeature()
                except Exception:
                    break
        try:
            f = fe.GetNextFeature()
        except Exception:
            break
    return out


def precheck_stl(path, max_bad_ratio=0.02):
    r"""导入前检查 STL 法线，避免 SW 弹模态框把自动化卡死。

    ★★ 2026-11-21 血泪（本机实测）：STL 里若有面法线为 `0 0 0`，
       SW2022 会弹出**模态对话框**「在文件发现面之一有面法线问题，请检查 STL 文件」。
       这个框不点掉，后面所有 COM 调用永远挂住 —— 实测卡了 10 分钟以上，
       只能 taskkill 掉 SLDWORKS.exe。自动化里这是致命的：
       一个坏 STL 就能让整条流水线静默死锁。

    所以导入前必须自己查一遍：
      - 法线向量长度为 0 的面占比 > max_bad_ratio → 直接拒绝导入
      - 二进制 STL 逐面检查；ASCII STL 逐 facet 检查
      - 非 STL 格式（OBJ 等）跳过

    返回 {"ok", "bad", "total", "ratio", "reason"}。
    """
    rep = {"ok": True, "bad": 0, "total": 0, "ratio": 0.0, "reason": ""}
    if _norm_ext(path) != ".stl":
        rep["reason"] = "非 STL，跳过法线预检"
        return rep
    try:
        with open(path, "rb") as f:
            head = f.read(512)
    except Exception as e:
        rep.update(ok=False, reason="读不到文件: %s" % str(e)[:60])
        return rep

    is_ascii = head.lstrip()[:5].lower() == b"solid" and b"facet" in head.lower()
    if not is_ascii:
        # 二进制：84 字节头 + 每面 50 字节，法线在前 12 字节
        import struct
        try:
            with open(path, "rb") as f:
                f.seek(80)
                n = struct.unpack("<I", f.read(4))[0]
                rep["total"] = int(n)
                bad = 0
                for _ in range(n):
                    raw = f.read(50)
                    if len(raw) < 50:
                        break
                    nx, ny, nz = struct.unpack("<3f", raw[:12])
                    if abs(nx) + abs(ny) + abs(nz) < 1e-9:
                        bad += 1
                rep["bad"] = bad
        except Exception as e:
            rep.update(ok=False, reason="二进制 STL 解析失败: %s" % str(e)[:60])
            return rep
    else:
        try:
            txt = open(path, encoding="ascii", errors="replace").read()
        except Exception as e:
            rep.update(ok=False, reason="ASCII STL 读不到: %s" % str(e)[:60])
            return rep
        bad = total = 0
        for line in txt.splitlines():
            s = line.strip().lower()
            if s.startswith("facet normal"):
                total += 1
                parts = s.split()
                try:
                    nx, ny, nz = [float(x) for x in parts[2:5]]
                except Exception:
                    bad += 1
                    continue
                if abs(nx) + abs(ny) + abs(nz) < 1e-9:
                    bad += 1
        rep["total"], rep["bad"] = total, bad

    if rep["total"]:
        rep["ratio"] = round(rep["bad"] / float(rep["total"]), 4)
    if rep["total"] == 0:
        rep.update(ok=False, reason="STL 里一个面都没有")
    elif rep["ratio"] > max_bad_ratio:
        rep.update(ok=False, reason=(
            "法线为 0 的面 %d/%d (%.1f%%)，超过 %.0f%% —— SW 会弹模态框卡死，"
            "先用 repair_stl_normals() 修或换文件"
            % (rep["bad"], rep["total"], rep["ratio"] * 100, max_bad_ratio * 100)))
    return rep


def repair_stl_normals(src, dst=None, binary=False):
    r"""修 STL 法线：把 0 法线按三角面重算，绕向按体心朝外纠正。

    这是 precheck_stl 拒绝导入时的补救路径（不改原文件，另存 dst）。
    返回 (dst_path, stats)。
    """
    dst = dst or (os.path.splitext(src)[0] + "_fixed.stl")
    verts, tris = [], []

    with open(src, "rb") as f:
        head = f.read(512)
    is_ascii = head.lstrip()[:5].lower() == b"solid" and b"facet" in head.lower()
    if is_ascii:
        cur = []
        for line in open(src, encoding="ascii", errors="replace"):
            s = line.strip().lower()
            if s.startswith("vertex"):
                p = [float(x) for x in s.split()[1:4]]
                cur.append(tuple(p))
                if len(cur) == 3:
                    tris.append(tuple(cur))
                    cur = []
    else:
        import struct
        with open(src, "rb") as f:
            f.seek(80)
            n = struct.unpack("<I", f.read(4))[0]
            for _ in range(n):
                raw = f.read(50)
                if len(raw) < 50:
                    break
                pts = struct.unpack("<12f", raw[12:48])
                tris.append((tuple(pts[0:3]), tuple(pts[3:6]), tuple(pts[6:9])))

    if not tris:
        raise RuntimeError("STL 里读不到三角面: %s" % src)

    allp = [p for t in tris for p in t]
    center = (sum(p[0] for p in allp) / len(allp),
              sum(p[1] for p in allp) / len(allp),
              sum(p[2] for p in allp) / len(allp))

    fixed = []
    flipped = 0
    for a, b, c in tris:
        n = _tri_normal(a, b, c)
        fc = ((a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0,
              (a[2] + b[2] + c[2]) / 3.0)
        if ((fc[0] - center[0]) * n[0] + (fc[1] - center[1]) * n[1]
                + (fc[2] - center[2]) * n[2]) < 0:
            b, c = c, b
            n = _tri_normal(a, b, c)
            flipped += 1
        fixed.append((_normalize(n), a, b, c))

    if binary:
        import struct
        with open(dst, "wb") as f:
            f.write(b"\0" * 80)
            f.write(struct.pack("<I", len(fixed)))
            for n, a, b, c in fixed:
                f.write(struct.pack("<3f", *n))
                for p in (a, b, c):
                    f.write(struct.pack("<3f", *p))
                f.write(struct.pack("<H", 0))
    else:
        with open(dst, "w", encoding="ascii", newline="\n") as f:
            f.write("solid repaired\n")
            for n, a, b, c in fixed:
                f.write("facet normal %.6f %.6f %.6f\n  outer loop\n" % n)
                for p in (a, b, c):
                    f.write("    vertex %.6f %.6f %.6f\n" % p)
                f.write("  endloop\nendfacet\n")
            f.write("endsolid repaired\n")
    return dst, {"triangles": len(fixed), "flipped": flipped}


def import_mesh(sw, path, arg=ARG_REFERENCE, expect_bbox_mm=None,
                bbox_tol_mm=0.5, min_volume_mm3=0.0,
                close_after=False, precheck=True, auto_repair=False):
    r"""导入网格文件为参考图形体。

    返回 dict：
        ok / path / arg / errors / doc / title
        bbox_mm（6 项，导入件的包围盒）
        mesh_bodies（网格体个数）
        bodies（(实体, 曲面体)，网格件通常是 (0,0)，仅供参考）
        precheck（法线预检结果）
        checks [{id,status,message}]
        notes

    ★ 判据（不判返回值，判几何）：
      - 导入后活动文档标题变了 / 新文档数 +1
      - bbox 六项非全零且跨度 > 0
      - 给了 expect_bbox_mm 就逐项比对（容差 bbox_tol_mm）
      - 网格体个数 > 0（走 MeshFeatureContainer 链，不用 GetBodies2）

    ★ precheck=True（默认）：导入前查 STL 法线。法线为 0 的面过多时
      **直接拒绝**，因为 SW 会弹模态框把 COM 调用永久挂住。
      auto_repair=True 时改为自动修法线后导入修复件。

    ★ 2026-11-21 清理：删掉 `doc_type` 和 `allow_solid` 两个**假参数** ——
      它们声明了却从未被读取，调用方传了也不起作用，只会误导。
      `arg` 才是真正的导入模式开关（"r" 参考 / "s" 尝试缝合）。
    """
    import swlib_v2 as V

    rep = {"path": path, "arg": arg, "checks": [], "notes": []}

    def add(cid, ok, msg, level="fail"):
        rep["checks"].append({"id": cid, "status": "pass" if ok else level,
                              "message": msg})

    if not os.path.exists(path):
        rep["ok"] = False
        add("file_exists", False, "文件不存在: %s" % path)
        return rep
    add("file_exists", True, "%d B" % os.path.getsize(path))

    ext = _norm_ext(path)
    if ext in UNSUPPORTED_EXTS:
        rep["ok"] = False
        rep["convert"] = convert_glb_to_obj(path)
        add("format", False, "%s 需先转 OBJ/STL（见 convert.commands）" % ext)
        return rep
    if ext not in MESH_EXTS:
        add("format", False, "%s 不在已知网格格式里，仍尝试导入" % ext, level="warn")
    else:
        add("format", True, ext)

    # ---- 法线预检（防模态框卡死）
    if precheck:
        pc = precheck_stl(path)
        rep["precheck"] = pc
        if not pc["ok"]:
            if auto_repair and _norm_ext(path) == ".stl":
                try:
                    fixed, st = repair_stl_normals(path)
                    rep["repaired"] = {"path": fixed, "stats": st}
                    path = fixed
                    rep["path"] = fixed
                    pc2 = precheck_stl(fixed)
                    rep["precheck_after_repair"] = pc2
                    add("precheck", pc2["ok"],
                        "已修法线（翻转 %d 面）→ %s"
                        % (st["flipped"], pc2["reason"] or "通过"))
                    if not pc2["ok"]:
                        rep["ok"] = False
                        return rep
                except Exception as e:
                    rep["ok"] = False
                    add("precheck", False, "自动修复失败: %s" % str(e)[:80])
                    return rep
            else:
                rep["ok"] = False
                add("precheck", False, pc["reason"])
                rep["notes"].append(
                    "SW 遇 0 法线会弹模态框「面法线问题」，COM 调用会永久挂住 —— "
                    "必须先在导入前拦掉，不能靠 try/except 兜")
                return rep
        else:
            add("precheck", True, pc["reason"] or
                "法线正常（%d 面，坏 %d）" % (pc["total"], pc["bad"]))

    # ---- 记录导入前状态
    try:
        n_before = int(sw.GetDocumentCount())
    except Exception:
        n_before = None

    # ---- 调 LoadFile4（第 3 参必须是空 IDispatch，不能 None）
    import swlib as L
    empty = create_empty_dispatch_variant()
    err = L.byref_int(0)
    ret = None
    try:
        ret = sw.LoadFile4(str(path), str(arg), empty, err)
        rep["errors"] = err.value
    except Exception as e:
        # 早绑定下 by-ref VARIANT 不被接受 → 降级动态绑定重试
        try:
            ret, outs = L.call_byref(sw, "LoadFile4",
                                     [str(path), str(arg), empty], ["i4"])
            rep["errors"] = outs[0] if outs else None
            rep["notes"].append("早绑定失败，已降级动态绑定: %s" % str(e)[:60])
        except Exception as e2:
            rep["ok"] = False
            rep["errors"] = None
            add("loadfile4", False, "LoadFile4 抛异常: %s" % str(e2)[:120])
            return rep

    rep["ret"] = repr(ret)[:80] if ret is not None else None
    add("loadfile4", True, "返回 %s, errors=%s" % (rep["ret"], rep.get("errors")))

    # ---- 判据：文档真的出现了
    try:
        n_after = int(sw.GetDocumentCount())
    except Exception:
        n_after = None
    rep["docs_before"], rep["docs_after"] = n_before, n_after
    if n_before is not None and n_after is not None:
        add("doc_created", n_after > n_before,
            "文档数 %s → %s" % (n_before, n_after), level="warn")

    # ---- 取活动文档
    doc = None
    try:
        raw = sw.ActiveDoc
        if raw is not None:
            doc = V.wrap(raw, "IModelDoc2")
    except Exception:
        doc = None
    if doc is None and ret is not None:
        try:
            doc = V.wrap(ret, "IModelDoc2")
        except Exception:
            doc = None
    if doc is None:
        rep["ok"] = False
        add("doc", False, "导入后拿不到活动文档（LoadFile4 未生成文档）")
        return rep
    rep["doc"] = doc
    try:
        rep["title"] = doc.GetTitle()
    except Exception:
        rep["title"] = None
    add("doc", True, "活动文档: %s" % rep["title"])

    # ---- bbox（★ 单位米 → mm，本模块统一）
    bb = None
    try:
        bb = V.L.bbox6(doc)
    except Exception as e:
        add("bbox", False, "取不到 bbox: %s" % str(e)[:80])
    if bb:
        rep["bbox_mm"] = [round(float(x), 3) for x in bb]
        span = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
        add("bbox_nonzero", max(span) > 1e-6,
            "跨度 %.3f / %.3f / %.3f mm" % tuple(span))
        if expect_bbox_mm:
            dev = max(abs(a - b) for a, b in zip(bb, expect_bbox_mm))
            add("bbox_expected", dev <= bbox_tol_mm,
                "最大偏差 %.3f mm（容差 %.3f）" % (dev, bbox_tol_mm))

    # ---- 网格体计数（★ 不走 GetBodies2，走 MeshFeatureContainer 链）
    mb = mesh_bodies(doc)
    rep["mesh_bodies"] = len(mb)
    add("mesh_bodies", len(mb) > 0,
        "%d 个网格体（MeshBodyFeature → IBody2）" % len(mb))

    # ---- 实体/曲面体（网格件通常都是 0，仅作信息）
    try:
        n_solid, n_sheet = V.body_counts(doc)
        rep["bodies"] = (n_solid, n_sheet)
        add("bodies", (n_solid + n_sheet) > 0,
            "%d 实体 / %d 曲面体（网格件为 0 属正常）" % (n_solid, n_sheet),
            level="warn")
    except Exception as e:
        rep["bodies"] = None
        add("bodies", False, "实体数取不到: %s" % str(e)[:80], level="warn")

    # ---- 体积（图形体常为 0，只在明确要求时判）
    if min_volume_mm3:
        try:
            v = V.volume_mm3(doc)
            rep["volume_mm3"] = round(v, 2)
            add("volume", v >= min_volume_mm3,
                "体积 %.2f mm³（下限 %.2f）" % (v, min_volume_mm3))
        except Exception as e:
            add("volume", False, "体积取不到: %s" % str(e)[:80])

    # ---- 诚实声明
    rep["notes"].append(
        "网格导入件不是参数化实体：无草图/特征树，不能拉伸切除、不能加配合当机构件")
    rep["notes"].append(
        "用途限于视觉参考、量尺寸、做参照面；要参数化必须重新建模")
    rep["notes"].append(
        "GetBodies2() 看不到网格体（返回 None），必须走 MeshBodyFeature.GetSpecificFeature2")
    rep["capability"] = "import.mesh"
    rep["level"] = "pilot"

    if close_after:
        try:
            V.close_doc(sw, doc, force=True)
        except Exception:
            pass

    rep["ok"] = all(c["status"] in ("pass", "warn") for c in rep["checks"])
    return rep


def _tri_normal(a, b, c):
    """三角面法线（右手定则，未归一化）。"""
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    return (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)


def _normalize(n):
    m = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5
    return (0.0, 0.0, 0.0) if m < 1e-12 else (n[0] / m, n[1] / m, n[2] / m)


def write_test_stl(path, size_mm=(20.0, 30.0, 40.0), binary=False):
    """生成一个长方体 STL（ASCII 或二进制），用于自测。

    ★★ 2026-11-21 血泪（本机实测）：法线写 `0 0 0` 会让 SW2022 弹出
       **模态对话框**「在文件发现面之一有面法线问题，请检查 STL 文件」，
       对话框不点掉，COM 调用就永远挂着 —— 自动化直接卡死（实测挂 10 分钟+）。
       所以 STL 必须带**真实法线**，且三角面绕向必须朝外（右手定则）。
       本函数：法线由叉积算出并归一化；绕向用「法线·(面心-体心) > 0」自动纠正。

    ★ 生成件的 bbox 精确等于 size_mm，便于断言坐标轴映射。
      单位按 STL 惯例是 mm，SW 导入默认也是 mm（不是米）。
    """
    sx, sy, sz = [float(x) for x in size_mm]
    v = [(0, 0, 0), (sx, 0, 0), (sx, sy, 0), (0, sy, 0),
         (0, 0, sz), (sx, 0, sz), (sx, sy, sz), (0, sy, sz)]
    center = (sx / 2.0, sy / 2.0, sz / 2.0)
    faces = [(0, 3, 2), (0, 2, 1),        # z=0
             (4, 5, 6), (4, 6, 7),        # z=sz
             (0, 1, 5), (0, 5, 4),        # y=0
             (1, 2, 6), (1, 6, 5),        # x=sx
             (2, 3, 7), (2, 7, 6),        # y=sy
             (3, 0, 4), (3, 4, 7)]        # x=0

    tris = []
    for a, b, c in faces:
        pa, pb, pc = v[a], v[b], v[c]
        n = _tri_normal(pa, pb, pc)
        fc = ((pa[0] + pb[0] + pc[0]) / 3.0,
              (pa[1] + pb[1] + pc[1]) / 3.0,
              (pa[2] + pb[2] + pc[2]) / 3.0)
        outward = ((fc[0] - center[0]) * n[0] + (fc[1] - center[1]) * n[1]
                   + (fc[2] - center[2]) * n[2])
        if outward < 0:                    # 绕向朝内 → 翻转
            pb, pc = pc, pb
            n = _tri_normal(pa, pb, pc)
        tris.append((_normalize(n), pa, pb, pc))

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if binary:
        import struct
        with open(path, "wb") as f:
            f.write(b"\0" * 80)
            f.write(struct.pack("<I", len(tris)))
            for n, pa, pb, pc in tris:
                f.write(struct.pack("<3f", *n))
                for p in (pa, pb, pc):
                    f.write(struct.pack("<3f", *[float(x) for x in p]))
                f.write(struct.pack("<H", 0))
        return path
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write("solid testbox\n")
        for n, pa, pb, pc in tris:
            f.write("facet normal %.6f %.6f %.6f\n  outer loop\n" % n)
            for p in (pa, pb, pc):
                f.write("    vertex %.6f %.6f %.6f\n" % p)
            f.write("  endloop\nendfacet\n")
        f.write("endsolid testbox\n")
    return path


def render(rep):
    icon = {"pass": "OK  ", "warn": "WARN", "fail": "FAIL"}
    lines = ["=== 网格导入: %s ===" % os.path.basename(rep.get("path") or "")]
    lines.append("  arg=%s  errors=%s  ret=%s"
                 % (rep.get("arg"), rep.get("errors"), rep.get("ret")))
    lines.append("  文档: %s（%s → %s）"
                 % (rep.get("title"), rep.get("docs_before"), rep.get("docs_after")))
    if rep.get("bbox_mm"):
        b = rep["bbox_mm"]
        lines.append("  bbox: (%.2f, %.2f, %.2f) → (%.2f, %.2f, %.2f) mm"
                     % tuple(b))
        lines.append("  尺寸: %.2f × %.2f × %.2f mm"
                     % (b[3] - b[0], b[4] - b[1], b[5] - b[2]))
    for c in rep.get("checks", []):
        lines.append("  [%s] %-14s %s" % (icon.get(c["status"], "?"),
                                          c["id"], c["message"]))
    lines.append("  ---- ok: %s ----" % rep.get("ok"))
    if rep.get("precheck"):
        pc = rep["precheck"]
        lines.append("  法线预检: %d 面 / 坏 %d（%.1f%%）%s"
                     % (pc["total"], pc["bad"], pc["ratio"] * 100,
                        "" if pc["ok"] else " → 拒绝导入"))
    if rep.get("repaired"):
        lines.append("  已修法线: %s（翻转 %d 面）"
                     % (os.path.basename(rep["repaired"]["path"]),
                        rep["repaired"]["stats"]["flipped"]))
    for n in rep.get("notes", []):
        lines.append("  · " + n)
    if rep.get("convert"):
        lines.append("  ! 需先转换格式:")
        for cmd in rep["convert"]["commands"]:
            lines.append("      " + cmd)
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="网格导入（STL/OBJ → SW 参考图形体）")
    ap.add_argument("path", nargs="?", help="网格文件路径")
    ap.add_argument("--make-stl", metavar="OUT", help="生成测试长方体 STL")
    ap.add_argument("--size", default="20,30,40", help="测试件尺寸 mm，逗号分隔")
    ap.add_argument("--arg", default=ARG_REFERENCE, help="LoadFile4 ArgString（r/s）")
    ap.add_argument("--close", action="store_true", help="导入后关闭文档")
    a = ap.parse_args()

    if a.make_stl:
        sx, sy, sz = [float(x) for x in a.size.split(",")]
        p = write_test_stl(a.make_stl, (sx, sy, sz))
        print("已生成 %s（%.1f × %.1f × %.1f mm）" % (p, sx, sy, sz))
        sys.exit(0)

    if not a.path:
        ap.print_help()
        sys.exit(2)

    import swlib_v2 as V
    sw = V.connect(version=2022)
    rep = import_mesh(sw, a.path, arg=a.arg, close_after=a.close)
    print(render(rep))
    sys.exit(0 if rep.get("ok") else 1)
