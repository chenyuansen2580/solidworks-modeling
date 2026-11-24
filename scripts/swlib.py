# -*- coding: utf-8 -*-
"""SolidWorks 2022 COM 基础库（重建版）。

背景：原 solidworks-cad skill 的 swlib.py 已从磁盘丢失，swlib_v2.py 只保留了
上层封装。本文件按「上层实际调用到的成员」反推重建，接口面刻意收窄，
不做无根据的扩展：

    MM / TLB / TPL_PART / TPL_ASM / BLIND / THROUGH_ALL / MID_PLANE
    wrap / new_part / new_asm
    new_sketch / end_sketch / last_sketch_name / select_sketch
    rect / line / circle
    boss / cut / fillet / chamfer
    vol / bbox6 / bbox

铁律（全部来自 references/pitfalls.md，不要"优化"掉）：
  ★ 单位只在边界换算一次：进 COM 前 *MM，出 COM 后 *1000 或 *1e9
  ★ 建模前必须选中草图，否则 FeatureExtrusion3 静默返回 None
  ★ 圆不是 CreateCircle(cx,cy,r)，第二组是圆周上一点
  ★ 保存/截图必须回读文件大小，0 字节 = 失败
  ★ AddToDB 默认 False，1mm 吸附会毁掉精密草图（用 swlib_v2.addtoDB 上下文）
"""
import math
import os

import pythoncom
import win32com.client

# ---------------------------------------------------------------- 常量
MM = 0.001                      # mm -> m，进 COM 前乘它
TLB = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"     # sldworks.tlb

TPL_DIR = r"C:\ProgramData\SolidWorks\SOLIDWORKS 2022\templates"
TPL_PART = os.path.join(TPL_DIR, "Part.prtdot")
TPL_ASM = os.path.join(TPL_DIR, "AsmEmpty.ASMDOT")

# swEndConditions_e
BLIND = 0
THROUGH_ALL = 1
MID_PLANE = 6

# swStartConditions_e
START_SKETCH_PLANE = 0
START_OFFSET = 3

# 视图 ID（★ 名字在中文版会变，必须传 ID；-1 不切视图）
VIEW = {"iso": 7, "front": 1, "top": 5, "right": 4, "left": 6, "back": 2, "bottom": 3}
VIEW_NAME = {"iso": "*Isometric", "front": "*Front", "top": "*Top", "right": "*Right",
             "left": "*Left", "back": "*Back", "bottom": "*Bottom"}

# 基准面名：中文版是「前视基准面」，英文版是「Front Plane」
PLANE_ALIASES = {
    "Front Plane": ("Front Plane", "前视基准面"),
    "Top Plane": ("Top Plane", "上视基准面"),
    "Right Plane": ("Right Plane", "右视基准面"),
}


def unrealized_itf():
    """pywin32 动态层「找不到成员」的错误码。"""
    return "-2147352573"


# ---------------------------------------------------------------- by-ref 出参
# ★★ 2026-11-21 实测（本机 SW2022 + pywin32 306）：
#   早绑定（gencache 生成的 _ApplyTypes_）**不接受 VARIANT 形式的 by-ref 参数**：
#       d.SaveAs4(path, 0, 0, VARIANT(VT_BYREF|VT_I4, 0), ...)
#       → TypeError: int() argument must be ... not 'VARIANT'
#   原因是 `_ApplyTypes_` 会把 (16387, 3) 这种「VT_I4|VT_BYREF + out」直接当 int
#   解包后传给 InvokeTypes，而 VARIANT 对象不是 int。
#   早绑定下唯一可行的写法是传普通 int（pywin32 自动转 out 参数并**以元组返回**）：
#       d.SaveAs4(path, 0, 0, 0, 0)  →  (True, 0, 0)
#   想真正拿到 by-ref 出参（含错误码），必须**降级到动态绑定**：
#       dyn.Dispatch(m._oleobj_).SaveAs4(path, 0, 0, err, warn)
#       →  err.value == 1（目录不存在）/ 256（扩展名非法）
#   本模块的 byref_* 构造器 + call_byref() 把这个差异包掉。
def variant_vt(v):
    """读 pywin32 VARIANT 的 VT 数值（它不暴露 .vt，只能从 repr 解）。

    repr 形如 `win32com.client.VARIANT(16387, 7)`，16387 = 0x4003 = VT_BYREF|VT_I4。
    读不到返回 None。
    """
    import re
    m = re.search(r"VARIANT\((\d+)", repr(v))
    return int(m.group(1)) if m else None


def byref_int(v=0):
    """构造 by-ref int 出参（VT_BYREF | VT_I4）。取回值用 `.value`。"""
    import pythoncom
    import win32com.client
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, int(v))


def byref_double(v=0.0):
    """构造 by-ref double 出参（VT_BYREF | VT_R8）。取回值用 `.value`。"""
    import pythoncom
    import win32com.client
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_R8, float(v))


def byref_bool(v=False):
    """构造 by-ref bool 出参（VT_BYREF | VT_BOOL）。取回值用 `.value`（-1/0）。"""
    import pythoncom
    import win32com.client
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, bool(v))


def byref_str(v=""):
    """构造 by-ref BSTR 出参（VT_BYREF | VT_BSTR）。"""
    import pythoncom
    import win32com.client
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, str(v))


def byref_variant(v=None):
    """构造 by-ref VARIANT 出参（VT_BYREF | VT_VARIANT）。"""
    import pythoncom
    import win32com.client
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, v)


def as_dynamic(obj):
    """把早绑定对象降级为动态绑定对象（by-ref 出参必需）。

    ★ 早绑定 `_ApplyTypes_` 会把 by-ref 参数当 int 解包，VARIANT 直接 TypeError。
      动态绑定走 IDispatch::Invoke，VARIANT 原样传下去，出参才能取回。
    """
    import win32com.client.dynamic as dyn
    raw = getattr(obj, "_oleobj_", obj)
    return dyn.Dispatch(raw)


def call_byref(obj, method, args, out_spec, dynamic=True):
    """调用带 by-ref 出参的 API，返回 (retval, [出参值...])。

    obj       : 早绑定或动态绑定对象
    method    : 方法名
    args      : 入参列表（不含出参位置；按 out_spec 顺序插到末尾）
    out_spec  : 出参类型列表，如 ["i4", "i4"] / ["r8"] / ["bool"]
    dynamic   : True=先降级动态绑定（推荐）；False=用早绑定传普通 0

    ★ 本机实测（SaveAs4）：
        dynamic=True  → 能拿到 err=1/256 这种真实错误码
        dynamic=False → 返回值是元组 (True, 0, 0)，但入参必须传普通 int
    """
    makers = {"i4": byref_int, "r8": byref_double,
              "bool": byref_bool, "str": byref_str, "var": byref_variant}
    if dynamic:
        target = as_dynamic(obj)
        holders = [makers[t]() for t in out_spec]
        ret = getattr(target, method)(*(list(args) + holders))
        return ret, [h.value for h in holders]
    # 早绑定：出参位置传 0/False，pywin32 会把它们并进返回元组
    zeros = {"i4": 0, "r8": 0.0, "bool": False, "str": "", "var": None}
    ret = getattr(obj, method)(*(list(args) + [zeros[t] for t in out_spec]))
    return ret, None


def split_out(ret, n_out):
    """早绑定返回值拆包：`(True, err, warn)` → `(True, [err, warn])`。

    ★ 有些方法返回 (retval, out1, out2)，有些只返回 retval，有些返回短元组 ——
      统一在这里判：
        元组长度 >= 1+n_out → retval = ret[0]，出参 = ret[1:1+n_out]
        元组长度 == 1       → retval = ret[0]，出参全部 None
        标量                → retval = ret，出参全部 None
    """
    if isinstance(ret, (tuple, list)):
        head = ret[0] if ret else None
        if len(ret) >= 1 + n_out:
            return head, list(ret[1:1 + n_out])
        return head, [None] * n_out
    return ret, [None] * n_out


# ---------------------------------------------------------------- 接口包装
def wrap(obj, iface=None):
    """把 COM 对象 cast 到指定接口（早绑定）。

    ★ 正确做法（2026-11-18 实测修正）：
      `win32com.client.CastTo(obj, iface)` 的第二个参数期望 **ProgID/CLSID**，
      传接口名 "ISldWorks" 会得到一个缺 `InvokeTypes` 的残废对象 ——
      任何方法调用都报 `no attribute 'InvokeTypes'`。

      正确路径是 gencache 生成类型库模块 → QueryInterface(IID_IDispatch)
      → 取模块里的同名接口类。这样拿到的是真正带方法表的早绑定对象。

    iface 为 None 时原样返回（调用方已持有可用对象时用）。
    """
    if obj is None:
        return None
    if not iface:
        return obj
    try:
        mod = _typemod()
        cls = getattr(mod, iface, None)
        if cls is None:
            return obj
        return cls(obj._oleobj_.QueryInterface(pythoncom.IID_IDispatch))
    except Exception:
        # cast 失败不掩盖真错误，原样返回让调用方自己暴露问题
        return obj


_TYPEMOD = None


def _typemod():
    """惰性加载 sldworks 类型库模块（gencache 早绑定）。"""
    global _TYPEMOD
    if _TYPEMOD is None:
        import win32com.client.gencache as gencache
        _TYPEMOD = gencache.EnsureModule(TLB, 0, 30, 0)
    return _TYPEMOD


def ext(m):
    """IModelDocExtension —— SelectByID2 / CreateMassProperty / 颜色都在这。"""
    return wrap(m.Extension, "IModelDocExtension")


def part(m):
    """IPartDoc —— GetBodies2 / GetPartBox 在这，不在 IModelDoc2。"""
    return wrap(m, "IPartDoc")


# ---------------------------------------------------------------- 文档
def _activate(sw, title):
    """激活文档并刷新显示。★ 不激活时 SelectByID2 坐标再准也返回 False。"""
    try:
        sw.ActivateDoc3(title, True, 0, 0)
    except Exception:
        pass


def activate_doc(sw, m):
    _activate(sw, m.GetTitle())
    d = wrap(sw.ActiveDoc, "IModelDoc2")
    try:
        d.ViewZoomtofit2()
        d.GraphicsRedraw2()
    except Exception:
        pass
    return d


def new_part(sw, close_all=True):
    """新建零件。close_all=True 先把残留窗关掉（残留窗会占满 8 个名额）。"""
    if close_all:
        try:
            sw.CloseAllDocuments(True)
        except Exception:
            pass
    doc = sw.NewDocument(TPL_PART, 0, 0, 0)
    if doc is None:
        raise RuntimeError("NewDocument 返回 None，模板不可用: %s" % TPL_PART)
    m = wrap(doc, "IModelDoc2")
    _activate(sw, m.GetTitle())
    return m


def new_asm(sw, close_all=True):
    if close_all:
        try:
            sw.CloseAllDocuments(True)
        except Exception:
            pass
    doc = sw.NewDocument(TPL_ASM, 0, 0, 0)
    if doc is None:
        raise RuntimeError("NewDocument 返回 None，模板不可用: %s" % TPL_ASM)
    # ★ GetTitle 在 IModelDoc2 上，不在 IAssemblyDoc（类型库实测）
    title = wrap(doc, "IModelDoc2").GetTitle()
    a = wrap(doc, "IAssemblyDoc")
    _activate(sw, title)
    return a


# ---------------------------------------------------------------- 草图
def _select_plane(m, plane):
    """选中基准面。中文版名字不同，两个都试。"""
    cands = PLANE_ALIASES.get(plane, (plane,))
    e = ext(m)
    for name in cands:
        try:
            if e.SelectByID2(name, "PLANE", 0, 0, 0, False, 0, None, 0):
                return name
        except Exception:
            continue
    raise RuntimeError("选不中基准面: %s（候选 %s）" % (plane, cands))


def new_sketch(m, plane="Front Plane"):
    """在指定基准面上开草图，返回 ISketchManager。

    ★ 调用前应处于 with V.addtoDB(m) 里，否则 1mm 吸附会毁掉精密几何。
    """
    m.ClearSelection2(True)
    _select_plane(m, plane)
    skm = wrap(m.SketchManager, "ISketchManager")
    skm.InsertSketch(True)
    skm = wrap(m.SketchManager, "ISketchManager")
    return skm


def last_sketch_name(m):
    """取最后一个草图名。★ 不用 FeatureByPositionReverse(0)，它会返回 Tables 文件夹。"""
    last = None
    f = m.FirstFeature()
    while f is not None:
        fe = wrap(f, "IFeature")
        if fe.GetTypeName2() == "ProfileFeature":
            last = fe.Name
        f = fe.GetNextFeature()
    return last


def end_sketch(m, expect_contours=None):
    """退出草图，返回草图名。expect_contours 给了就顺手做闭合数断言。"""
    skm = wrap(m.SketchManager, "ISketchManager")
    if expect_contours is not None:
        got = sketch_contour_count(m)
        if got != expect_contours:
            raise RuntimeError("草图闭合轮廓数=%s，期望 %d（轮廓不闭合或点重复）"
                               % (got, expect_contours))
    skm.InsertSketch(True)
    name = last_sketch_name(m)
    m.ClearSelection2(True)
    return name


def sketch_contour_count(m):
    sk = wrap(m.SketchManager, "ISketchManager").ActiveSketch
    if sk is None:
        return None
    try:
        return wrap(sk, "ISketch").GetSketchContourCount()
    except Exception:
        return None


def select_sketch(m, name, mark=0):
    """选中草图 —— FeatureExtrusion/Cut 的前置条件（5 级回退的精简版）。

    swlib_v2.select_sketch 是完整版；这里是基库内的兜底，用于 boss/cut 自证。
    """
    if not name:
        return False
    m.ClearSelection2(True)
    try:
        fe = m.FeatureByName(name)
        if fe is not None and bool(wrap(fe, "IFeature").Select2(False, mark)):
            return True
    except Exception:
        pass
    m.ClearSelection2(True)
    try:
        if ext(m).SelectByID2(name, "SKETCH", 0, 0, 0, False, mark, None, 0):
            return True
    except Exception:
        pass
    # 最后：当前活动草图的轮廓
    try:
        skm = wrap(m.SketchManager, "ISketchManager")
        sk = skm.ActiveSketch
        if sk is not None:
            objs = wrap(sk, "ISketch").GetSketchContours()
            n = 0
            for o in (objs or []):
                if bool(o.Select2(n > 0, mark)):
                    n += 1
            if n:
                return True
    except Exception:
        pass
    m.ClearSelection2(True)
    return False


def _opt(pts):
    """点列表拍平成 pywin32 认的 double 数组。"""
    flat = []
    for p in pts:
        flat.extend([float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0])
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, flat)


# ---------------------------------------------------------------- 草图图元（全按毫米收参）
def line(skm, x1, y1, x2, y2):
    """直线，毫米入参。端点不会自动合并，闭合轮廓要按逆时针顺序画。"""
    seg = skm.CreateLine(x1 * MM, y1 * MM, 0.0, x2 * MM, y2 * MM, 0.0)
    if seg is None:
        raise RuntimeError("CreateLine 返回 None: (%s,%s)->(%s,%s)" % (x1, y1, x2, y2))
    return seg


def rect(skm, x1, y1, x2, y2):
    """矩形 = 四条线。★ 不用 CreateCornerRectangle（AddToDB=True 下偶发不生成）。"""
    p = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    segs = [line(skm, p[i][0], p[i][1], p[(i + 1) % 4][0], p[(i + 1) % 4][1])
            for i in range(4)]
    return segs


def circle(skm, cx, cy, r):
    """圆。★ CreateCircle 第二组是【圆周上一点】，不是半径。"""
    seg = skm.CreateCircle(cx * MM, cy * MM, 0.0, (cx + r) * MM, cy * MM, 0.0)
    if seg is None:
        raise RuntimeError("CreateCircle 返回 None: c=(%s,%s) r=%s" % (cx, cy, r))
    return seg


def spline(skm, pts):
    """样条。先去重（<1e-5mm 的连续点会退化成退化曲线被静默丢弃）。"""
    clean = []
    for p in pts:
        if not clean or math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 1e-5:
            clean.append((p[0], p[1], 0.0))
    if len(clean) < 2:
        raise ValueError("样条点数不足")
    seg = skm.CreateSpline(_opt(clean))
    if seg is None:
        raise RuntimeError("CreateSpline 返回 None（点距过小或轮廓非法）")
    return seg


# ---------------------------------------------------------------- 特征
def boss(m, sketch, depth_mm, start_mm=0.0, flip=False):
    """拉伸凸台。depth/start 单位毫米；start_mm 非 0 时走 swStartOffset。"""
    if not select_sketch(m, sketch):
        raise RuntimeError("boss: 草图选不中 %s（这是 FeatureExtrusion3 返回 None 的头号原因）" % sketch)
    fm = wrap(m.FeatureManager, "IFeatureManager")
    t0 = START_OFFSET if abs(start_mm) > 1e-9 else START_SKETCH_PLANE
    f = fm.FeatureExtrusion3(
        True, False, bool(flip),
        BLIND, 0,
        depth_mm * MM, 0.0,
        False, False, False, False,
        0.0, 0.0,
        False, False, False, False,
        True, True, True,
        t0, abs(start_mm) * MM, start_mm < 0)
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("boss 返回 None（草图不闭合或参数非法）: %s" % sketch)
    return f


def cut(m, sketch, through=True, depth_mm=None):
    """切除。through=True 双向贯穿（★ Sd=True 是单向，只切一半）。"""
    if not select_sketch(m, sketch):
        raise RuntimeError("cut: 草图选不中 %s" % sketch)
    fm = wrap(m.FeatureManager, "IFeatureManager")
    if through:
        sd, t1, t2, d1, d2 = False, THROUGH_ALL, THROUGH_ALL, 0.02, 0.02
    else:
        sd, t1, t2, d1, d2 = True, BLIND, BLIND, (depth_mm or 0.0) * MM, 0.0
    f = fm.FeatureCut4(
        sd, False, True, t1, t2, d1, d2,
        False, False, False, False, 0.0, 0.0,
        False, False, False, False,
        False, True, True,
        False, True, False,
        0, 0.0, False, False)
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("cut 返回 None（草图不闭合或参数非法）: %s" % sketch)
    return f


def _select_edges(edges, mark=0):
    """逐条选边，★ 首条 append=False 清空、其余 append=True 追加。

    坑（2026-11-20 实测）：循环里一律 Select2(False,0) 会每次替换选择集，
    最终只有最后一条边进选择集 —— 圆角/倒角看起来"成功"，实际只倒了一条。
    P2 端盖实测：4 条外框边期望切 199.5，实际只切 50.0（= 100×0.5，正是 1 条边）。
    """
    m_sel = 0
    ok = 0
    for e in (edges or []):
        try:
            append = (ok > 0)
            if wrap(e, "IEntity").Select2(append, mark):
                ok += 1
        except Exception:
            continue
    return ok


def fillet(m, radius_mm, edges=None, options=195):
    """圆角。★ SW2022 是 7 参（GitHub 流传的 4 参是 SW2024+）。

    edges 为 None 时不会自动全选 —— 传 IEdge 列表，内部负责 wrap 成 IEntity 再选。
    ★ 多条边必须逐条追加选中（首条 append=False，其余 True），否则只倒最后一条。
    """
    m.ClearSelection2(True)
    n = _select_edges(edges, mark=0)
    if n == 0:
        raise RuntimeError("圆角选择集为空（IEdge 不继承 IEntity，必须 wrap）")
    fm = wrap(m.FeatureManager, "IFeatureManager")
    f = fm.FeatureFillet(int(options), radius_mm * MM, 0, 0,
                         win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                                 [radius_mm * MM]), None, None)
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("圆角失败（半径过大或边不相邻）")
    return f


def chamfer(m, dist_mm, edges=None, angle_deg=45.0, options=1):
    """倒角。角度用弧度。

    ★ 多条边必须逐条追加选中（首条 append=False，其余 True），否则只倒最后一条。
    """
    m.ClearSelection2(True)
    n = _select_edges(edges, mark=0)
    if n == 0:
        raise RuntimeError("倒角选择集为空")
    fm = wrap(m.FeatureManager, "IFeatureManager")
    f = fm.InsertFeatureChamfer(int(options), 1, dist_mm * MM,
                                math.radians(angle_deg), 0.0, 0.0, 0.0, 0.0)
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("倒角失败")
    return f


# ---------------------------------------------------------------- 测量（单位坑都在这）
def vol(m):
    """体积 mm³。两条路径：IMassProperty(m³) 优先，退化到逐实体累加。"""
    try:
        mp = wrap(ext(m).CreateMassProperty(), "IMassProperty")
        v = float(mp.Volume)
        if v > 0:
            return v * 1e9
    except Exception:
        pass
    total = 0.0
    try:
        for b in (part(m).GetBodies2(0, False) or []):
            mp = wrap(b, "IBody2").GetMassProperties(1.0)
            if mp:
                total += float(mp[3])
    except Exception:
        pass
    return total * 1e9


def bbox6(m):
    """包围盒 6 项 mm，(xmin,ymin,zmin,xmax,ymax,zmax)。COM 原始值是米。

    ★ 三种宿主参数签名不同（本机实测）：
        IPartDoc.GetPartBox(True)          -> 零件，1 参
        IAssemblyDoc.GetBox(...)           -> 装配，只接受 1~2 个位置参数
        IModelDoc2.Extension 无统一入口
      装配必须用 1 参调用，传 (0, False) 会 TypeError。
    """
    arr = None
    # 1) 零件
    try:
        arr = part(m).GetPartBox(True)
    except Exception:
        arr = None
    # 2) 装配：先试 1 参，再试 0 参
    if arr is None:
        for call in (lambda a: a.GetBox(0), lambda a: a.GetBox()):
            try:
                arr = call(wrap(m, "IAssemblyDoc"))
                if arr is not None:
                    break
            except Exception:
                continue
    if arr is None:
        raise RuntimeError("取不到 bbox（GetPartBox/GetBox 都返回 None）")
    return tuple(round(float(x) * 1000.0, 4) for x in list(arr)[:6])


def bbox(m):
    """bbox 的易读形式，日志里直接打印用。"""
    return bbox6(m)


# ---------------------------------------------------------------- 存盘
def save(m, path):
    """保存并回读大小。0 字节一律当失败。"""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    rc = m.SaveAs2(path, 0, False, True)
    sz = os.path.getsize(path) if os.path.exists(path) else 0
    if sz <= 0:
        raise RuntimeError("保存失败/0 字节: %s rc=%s" % (path, rc))
    return sz


def close(sw, m, force=False):
    try:
        sw.CloseDoc(m.GetTitle())
    except Exception:
        pass
