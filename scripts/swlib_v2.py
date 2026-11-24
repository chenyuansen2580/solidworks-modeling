# -*- coding: utf-8 -*-
"""SolidWorks 2022 增强封装库 v2 —— 在 swlib.py 之上叠加全部实测教训。

设计原则（源自 10+ 个开源项目的共性方法论 + 本机 35 项 verified 实测）：
  1. 连接稳健：GetActiveObject/Dispatch 两级 fallback + 真实往返探测 + 多实例告警
  2. 每步可验：判 None 不判真；void API 用几何变化判据；体积/bbox/特征树三重断言
  3. 命名空间避让：视图切换必须传 ID，不靠名字
  4. 受控截图：激活活动文档 → 切视图 → 缩放 → 截图 → 回读文件大小
  5. 窗口纪律：建完即存、存完即截、截完即关
  6. 选择集 mark 是命门：Select2(append,mark) 优先，面/边退 Select4+SelectData
  7. 坐标契约先查表：本机 Y 才是"上下"；Front(x,y)/Top(x,-z)/Right(-z,y)

模块分区（按行号）：
  连接/自适应 → 验收断言 → 草图选择 → 基础特征 → 更多特征(旋转/放样/扫描/抽壳)
  → 拔模 → 钣金/孔向导/工程图 → 属性/配置/材料 → 曲面 → 焊件 → 运动仿真
  → 能力分级 → 校核/上色 → 装配 → 出图(含 fit 缩放) → 保存

参考：
  references/api-map.md           接口归属与签名（含 REA kit 2164 命令号）
  references/features.md          12 种手法的选择集 mark 与完整参数
  references/pitfalls.md          A~Q 十七章 113 条速查
  references/example_bracket.md   实战：电机支架（坐标契约 + 体积解析）
  references/example_assembly.md  全能力验收：9 零件装配体
  scripts/gearring.py             齿轮整圈齿廓拼接（补 gearmath 只给单齿廓）
  scripts/verify_gate.py          四级交付门禁（BLOCKED>FAIL>WARN>PASS）

已知不可用（本机实测，非用法问题）：
  surface.thicken（ThickenSheet 恒 None）、appearance.display_color（接口抛异常）

依赖：swlib.py（底层）、pywin32；运动仿真需 swmotionstudy.tlb。
"""
import math
import os
import subprocess
import sys
import time

import pythoncom
import win32com.client

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)
import swlib as L          # noqa: E402

MM = L.MM
TLB = L.TLB
wrap = L.wrap

# 视图 ID（★ 不靠名字，名字在中文版会变，且 -1 不切换）
VIEW = {"iso": 7, "front": 1, "top": 5, "right": 4, "left": 6, "back": 2, "bottom": 3}
VIEW_NAME = {"iso": "*Isometric", "front": "*Front", "top": "*Top", "right": "*Right",
             "left": "*Left", "back": "*Back", "bottom": "*Bottom"}
# 中文版名字映射（ShowNamedView2 用 ID 就够，这里仅备用）
VIEW_NAME_CN = {"iso": "*等轴测", "front": "*前视", "top": "*上视", "right": "*右视"}

# 草图名中英文前缀别名（中文版 SW 会显示"草图1"，API 名可能是 "Sketch1"）
SKETCH_PREFIX_ALIASES = {"草图": "Sketch", "Sketch": "草图"}


# ---------------------------------------------------------------- COM 成员自适应
_UNSET = object()


def com_member(obj, name, *args, default=_UNSET):
    """兼容「同一成员可能是属性也可能是方法」的 pywin32 通病。

    ★ 关键（2026-11-18 实测修正）：`RevisionNumber` 在**早绑定**下是方法，
      在**动态绑定**下是属性。旧版先取 getattr 再判断 callable，早绑定时
      拿到的是 bound method 对象而不是值，导致 `rev` 永远非 str。

    正确顺序：
      1. 有 args → 直接调用
      2. 无 args → 尝试调用；若返回的是「仍是 callable 的对象」或抛异常，
         再退回属性值
      3. 调用抛 "找不到成员" → 退回属性

    >>> com_member(sw, "RevisionNumber")          # 早绑定=方法，动态=属性
    '30.5.0.0049'
    >>> com_member(sw, "GetDocumentCount")
    0
    """
    try:
        member = getattr(obj, name)
    except AttributeError:
        if default is not _UNSET:
            return default
        raise

    if args:
        return member(*args)

    # 无参：先试调用（早绑定下属性会被实现为方法）
    if callable(member):
        try:
            val = member()
            # 调用后如果还是个 callable（说明拿到的是包装器），退回原成员
            if not callable(val):
                return val
            return member
        except Exception as exc:
            msg = str(exc)
            if ("-2147352573" in msg or "找不到成员" in msg
                    or "Member not found" in msg):
                return member
            raise
    return member


# COM HRESULT：参数个数漂移（移植自 Millwright/raylanlin 的 com_call）
_BAD_PARAM_COUNT = -2147352562      # DISP_E_BADPARAMCOUNT → 参数太多，减一个再试
_PARAM_NOT_OPTIONAL = -2147352561   # DISP_E_PARAMNOTOPTIONAL → 参数太少，放弃该成员


def com_call_arity(owner, names, args, min_args=1, verify=None):
    """自适应跨版本参数个数漂移：从最长参数往短试，直到成功。

    ★ 场景：同一 API 在 SW2022/2024/2026 可选参数个数不同；
      本地 com_member 只处理属性/方法，不处理 arity。此函数补该缺口。
      （移植自 raylanlin/Millwright `com_call`，Apache-2.0）

    owner  : 宿主对象；names: 候选方法名（版本间改名时逐个试）
    args   : 完整参数列表（会从 len(args) 递减试到 min_args）
    verify : 可选回调 `verify()` —— 有些版本建了特征却返回 None，
             用特征树对比回读确认（配合 assert_feature_created）
    返回 (result, used_name, used_n)；全失败返回 (None, None, 0)。
    """
    names = names if isinstance(names, (list, tuple)) else [names]
    hi = len(args)
    for name in names:
        fn = getattr(owner, name, None)
        if fn is None:
            continue
        for n in range(hi, min_args - 1, -1):
            try:
                made = fn(*args[:n])
            except Exception as e:
                hr = getattr(e, "hresult", None) or getattr(e, "args", [None])[0]
                if hr in (_BAD_PARAM_COUNT, _PARAM_NOT_OPTIONAL):
                    continue
                # 无法识别 HRESULT，字符串兜底
                msg = str(e)
                if "-2147352562" in msg or "参数" in msg or "argument" in msg.lower():
                    continue
                raise
            if made is None and verify is not None:
                made = verify()   # 返回 None 但特征可能已建 → 回读
            if made is not None:
                return made, name, n
    return None, None, 0


def sketch_name_candidates(name):
    """草图名候选：中英文前缀互换，兼容中文版 SW。"""
    name = str(name)
    out = [name]
    for pre, alias in SKETCH_PREFIX_ALIASES.items():
        if name.startswith(pre):
            alt = alias + name[len(pre):]
            if alt not in out:
                out.append(alt)
    return out


# ---------------------------------------------------------------- 连接
def sw_instances():
    """返回正在运行的 SLDWORKS.EXE 进程数。多于 1 会抢 ROT。"""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SLDWORKS.EXE"],
                             capture_output=True, text=True, timeout=10).stdout
        return out.upper().count("SLDWORKS.EXE")
    except Exception:
        return -1


def connect(verbose=True, warn_multi=True, wait_ready=30, version=None):
    """稳健连接：两级 fallback + 往返探测 + 多实例告警 + 等待就绪。

    ★ 踩坑修正（2026-11-18）：`RevisionNumber` 是**属性**不是方法，
      旧版写 `sw.RevisionNumber()` 会 TypeError: 'str' object is not callable。
      统一改用 com_member 自适应。

    ★ 新增 wait_ready（移植自 wzyn skill 的思路）：
      SW 进程存在但 ROT 未注册时，GetObject 会失败；旧版立刻 Dispatch 新实例，
      反而造成双实例抢 ROT。现在先等 wait_ready 秒再决定是否新开。

    version: 传 2022 会拼成 ProgID "SldWorks.Application.30"（年份-2000+8）
    """
    pythoncom.CoInitialize()
    n = sw_instances()
    if warn_multi and n > 1:
        print("[警告] 检测到 %d 个 SLDWORKS.EXE 进程；多实例会抢 ROT 导致 MK_E_UNAVAILABLE" % n)

    prog_id = "SldWorks.Application"
    if version is not None:
        prog_id = "SldWorks.Application.%d" % (int(version) - 2000 + 8)

    raw = None
    mode = ""
    # 1) 先尝试附着已有实例；若进程存在但 ROT 尚未注册，等一会再试
    try:
        raw = win32com.client.GetObject(Class=prog_id)
        mode = "GetObject(已有实例)"
    except Exception:
        if n > 0 and wait_ready > 0:
            deadline = time.time() + wait_ready
            while time.time() < deadline:
                time.sleep(0.5)
                try:
                    raw = win32com.client.GetObject(Class=prog_id)
                    mode = "GetObject(等待就绪 %.0fs)" % (time.time() - (deadline - wait_ready))
                    break
                except Exception:
                    continue
        if raw is None:
            raw = win32com.client.Dispatch(prog_id)
            mode = "Dispatch(启动新实例 %s)" % prog_id

    sw = wrap(raw, "ISldWorks")
    try:
        sw.Visible = True
        sw.UserControl = True
    except Exception:
        pass
    # 2) 真实往返探测：非空不等于可用
    ok = False
    rev = cnt = None
    for _ in range(5):
        try:
            rev = com_member(sw, "RevisionNumber")
            cnt = com_member(sw, "GetDocumentCount")
            if rev is not None and cnt is not None and int(cnt) >= 0:
                ok = True
                break
        except Exception:
            time.sleep(1)
    if not ok:
        raise RuntimeError("SolidWorks COM 空壳代理：往返探测失败")
    if verbose:
        print("[连接] %s  版本=%s  已开文档=%d" % (mode, rev, cnt))
    return sw


def switch_backend_if_needed(sw):
    """若当前无窗口（COM 拉起常见），显式显示。返回是否原本无窗口。"""
    try:
        if not sw.Visible:
            sw.Visible = True
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------- 验收断言
def assert_feature(m, name_or_type, kind="name"):
    """确认特征树里存在指定特征（名字或类型）。"""
    want = name_or_type if kind == "name" else None
    wtype = name_or_type if kind == "type" else None
    names = []
    f = m.FirstFeature()
    while f is not None:
        fe = wrap(f, "IFeature")
        nm = fe.Name
        names.append(nm)
        if (want is not None and nm == want) or \
           (wtype is not None and fe.GetTypeName2() == wtype):
            return True, nm
        f = fe.GetNextFeature()
    raise AssertionError("特征树里找不到 %s=%s；现有=%s" % (kind, name_or_type, names))


def assert_feature_created(m, feature, name=None, rebuild=True):
    """三段式特征判据（移植自 wzyn skill 2199★，SW2026 真机回归）：
       ① 返回值判 None 不判真（SW 失败多返回 None，`if feature:` 是 bug）
       ② 命名 + ForceRebuild3(False) 必须 True
       ③ FeatureByName(name) 回读确认持久化
    返回持久化后的 IFeature。所有 * _checked 函数内部已判 None，这里供额外门禁用。
    """
    if feature is None:
        raise RuntimeError("特征创建失败：API 返回 None")
    fe = wrap(feature, "IFeature")
    if name:
        fe.Name = name
    if rebuild:
        try:
            ok = m.ForceRebuild3(False)
            if not ok:
                raise RuntimeError("特征重建失败: %s" % name)
        except AttributeError:
            pass  # 某些接口无 ForceRebuild3，跳过
    if name:
        persisted = feat_by_name(m, name)
        if persisted is None:
            raise RuntimeError("重建后特征树里找不到: %s" % name)
        return persisted
    return fe


def feature_tree(m):
    out = []
    f = m.FirstFeature()
    while f is not None:
        fe = wrap(f, "IFeature")
        out.append((fe.Name, fe.GetTypeName2()))
        f = fe.GetNextFeature()
    return out


def offset_plane(m, base_plane, distance_mm, name=None):
    """创建偏移基准面，返回其特征对象。

    ★ InsertRefPlane 在 IFeatureManager 上，6 参：
      (FirstConstraint, FirstDistance, SecondConstraint, SecondDistance,
       ThirdConstraint, ThirdDistance)
      单偏移平面：选基准面 → FirstConstraint=8(swRefPlaneDistance), FirstDistance=偏移(m)
    用法：先 SelectByID2 选 base_plane，再调本函数。
    """
    if not m.Extension.SelectByID2(base_plane, "PLANE", 0, 0, 0, False, 0, None, 0):
        # 中文别名
        alias = {"Top Plane": "上视基准面", "Front Plane": "前视基准面",
                 "Right Plane": "右视基准面"}.get(base_plane)
        if not alias or not m.Extension.SelectByID2(alias, "PLANE", 0, 0, 0, False, 0, None, 0):
            raise RuntimeError("offset_plane: 选不中基准面 %s" % base_plane)
    fm = wrap(m.FeatureManager, "IFeatureManager")
    f = fm.InsertRefPlane(8, distance_mm * MM, 0, 0.0, 0, 0.0)  # 8=swRefPlaneDistance
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("offset_plane 返回 None: %s + %s mm" % (base_plane, distance_mm))
    if name:
        wrap(f, "IFeature").Name = name
    return f


def feat_by_name(m, name):
    """按名取特征。★ FeatureByName 在 IPartDoc 上，不在 IModelDoc2（类型库 46202 行）。

    两级回退：IPartDoc.FeatureByName → 遍历特征树按 Name 精确匹配。
    """
    try:
        fe = wrap(m, "IPartDoc").FeatureByName(name)
        if fe is not None:
            return fe
    except Exception:
        pass
    f = m.FirstFeature()
    while f is not None:
        fe = wrap(f, "IFeature")
        if fe.Name == name:
            return fe
        f = fe.GetNextFeature()
    return None


# ---------------------------------------------------------------- 草图选择（5 级回退）
def _select_obj(obj, append=False, mark=0):
    """对象级选择：先 Select2，再 Select4。移植自 wzyn skill。

    ★ 比 SelectByID2 按名称解析稳，但仍需文档已激活（见 PITFALLS D1）。
    """
    if obj is None:
        return False
    for meth in ("Select2", "Select4"):
        fn = getattr(obj, meth, None)
        if not fn:
            continue
        try:
            if meth == "Select2":
                if bool(fn(append, mark)):
                    return True
            else:
                if bool(fn(append, None)):
                    return True
        except Exception:
            continue
    return False


def _as_list(x):
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def last_sketch_name(m):
    """取最后一个草图名。★ 不用 FeatureByPositionReverse（可能返回 Tables 文件夹）。"""
    last = None
    f = m.FirstFeature()
    while f is not None:
        fe = wrap(f, "IFeature")
        if fe.GetTypeName2() == "ProfileFeature":
            last = fe.Name
        f = fe.GetNextFeature()
    return last


def select_sketch(m, name, mark=0, verbose=False):
    """选中草图，**5 级回退**。移植并改良自 wzyn skill 的 _select_sketch_ref。

    这是本库最有价值的一个函数：`FeatureExtrusion3/Cut4` 之前必须选中草图，
    否则静默返回 None（PITFALLS C1★）。但「选中」有五种可行路径，单靠
    SelectByID2 在某些版本/语言环境下会失败。

    回退顺序（先精确对象，后按名解析）：
      1. FeatureByName(名) → IFeature.Select2
      2. 遍历特征树找 ProfileFeature → Select2
      3. sketch.GetSketchContours() 逐个 Select2
      4. sketch.GetSketchRegions() 逐个 Select2
      5. Extension.SelectByID2(名, "SKETCH") ← 最后手段
    另外自动兼容中英文草图名前缀（草图1 / Sketch1）。

    返回 True 表示选择集非空。
    """
    m.ClearSelection2(True)
    cands = sketch_name_candidates(name) if name else []
    if name:
        cands = [str(name)] + [c for c in cands if c != str(name)]

    # 1) FeatureByName（★ 在 IPartDoc 上，不在 IModelDoc2）
    for cand in cands:
        fe = feat_by_name(m, cand)
        if fe is not None and _select_obj(fe, False, mark):
            if verbose:
                print("      [select_sketch] 路径1 FeatureByName(%s) 命中" % cand)
            return True
        m.ClearSelection2(True)

    # 2) 遍历特征树
    target = last_sketch_name(m) if not name else None
    if name:
        f = m.FirstFeature()
        while f is not None:
            fe = wrap(f, "IFeature")
            if fe.GetTypeName2() == "ProfileFeature" and fe.Name in cands:
                target = fe.Name
                break
            f = fe.GetNextFeature()
    if target:
        fe = feat_by_name(m, target)
        if fe is not None and _select_obj(fe, False, mark):
            if verbose:
                print("      [select_sketch] 路径2 特征树(%s) 命中" % target)
            return True
        m.ClearSelection2(True)

    # 3/4) 通过草图对象的轮廓/区域选择
    try:
        skm = wrap(m.SketchManager, "ISketchManager")
        sk = skm.ActiveSketch
        if sk is not None:
            s = wrap(sk, "ISketch")
            for getter in ("GetSketchContours", "GetSketchRegions"):
                fn = getattr(s, getter, None)
                if not fn:
                    continue
                objs = _as_list(fn())
                n = 0
                for o in objs:
                    if _select_obj(o, append=(n > 0), mark=mark):
                        n += 1
                if n:
                    if verbose:
                        print("      [select_sketch] 路径3/4 %s 命中 %d 个" % (getter, n))
                    return True
                m.ClearSelection2(True)
    except Exception:
        pass

    # 5) SelectByID2（最后手段）
    for cand in cands:
        try:
            if m.Extension.SelectByID2(cand, "SKETCH", 0, 0, 0, False, mark, None, 0):
                if verbose:
                    print("      [select_sketch] 路径5 SelectByID2(%s) 命中" % cand)
                return True
        except Exception:
            continue

    if verbose:
        print("      [select_sketch] !! 5 级回退全部失败: %s" % name)
    return False


def extrude_checked(m, sketch, depth_mm, start_mm=0.0, verbose=False):
    """拉伸：自动保证草图已选中，返回特征或抛异常（不静默失败）。"""
    if not select_sketch(m, sketch, verbose=verbose):
        raise RuntimeError("extrude: 草图选不中 %s" % sketch)
    fm = wrap(m.FeatureManager, "IFeatureManager")
    t0 = 3 if abs(start_mm) > 1e-9 else 0
    f = fm.FeatureExtrusion3(
        True, False, False, 0, 0,
        depth_mm * MM, 0.0,
        False, False, False, False, 0.0, 0.0,
        False, False, False, False,
        True, True, True,
        t0, abs(start_mm) * MM, start_mm < 0)
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("extrude 返回 None（草图不闭合或参数非法）: %s" % sketch)
    return f


def cut_checked(m, sketch, depth_mm=None, reverse=False, verbose=False):
    """切除。自动保证草图已选中。

    depth_mm:
      - None      → 双向贯穿（Sd=False + T1=T2=ThroughAll）
      - 正数      → 单向盲切
    reverse:
      - False     → Dir=True，沿草图【正】法向切
      - True      → Dir=False，沿草图【负】法向切

    ★★ 2026-11-20 实测纠正（旧实现是错的）：
      旧版把 reverse 传给 FeatureCut4 第 2 参 Flip —— 那是
      【保留轮廓/切外侧】(flip side to cut)，不是反向！
      症状：P5 滑台板 4 个沉孔少切 73319，正好 = 整块 − 4 个圆柱。
      方向在第 3 参 Direction：
        Dir=True  切正法向（Top Plane 草图 → +Y）
        Dir=False 切负法向（Top Plane 草图 → −Y）
      Dir=False 在负法向一侧【没有材料】时返回 None，这不是参数错误：
        板向 +Y 拉伸、草图在 y=0 时负法向无材料，只能 Dir=True。
    """
    if not select_sketch(m, sketch, verbose=verbose):
        raise RuntimeError("cut: 草图选不中 %s" % sketch)
    fm = wrap(m.FeatureManager, "IFeatureManager")
    if depth_mm is None:
        sd, t1, t2, d1, d2 = False, 1, 1, 0.02, 0.02
    else:
        sd, t1, t2, d1, d2 = True, 0, 0, depth_mm * MM, 0.0
    f = fm.FeatureCut4(
        sd, False, not bool(reverse), t1, t2, d1, d2,
        False, False, False, False, 0.0, 0.0,
        False, False, False, False,
        False, True, True,
        False, True, False,
        0, 0.0, False, False)
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("cut 返回 None（草图不闭合或参数非法）: %s" % sketch)
    return f


# ---------------------------------------------------------------- 更多特征（旋转/放样/扫描/抽壳/倒圆）
def revolve_checked(m, sketch, angle_deg=360.0, axis=None, is_cut=False,
                    reverse=False, merge=True, verbose=False):
    """旋转凸台/旋转切除（SW2022 FeatureRevolve2，20 参）。

    ★ 草图必须含一条中心线（CreateCenterLine），或 axis 传一条基准轴/直线对象；
      旋转轴没选/没画时 API 静默返回 None。
    axis=None 时默认靠草图里的构造中心线；给了 axis 就选中它（mark 不影响 revolve）。
    angle_deg 按度收参，内部转弧度。is_cut=True 时做旋转切除。
    """
    if not select_sketch(m, sketch, verbose=verbose):
        raise RuntimeError("revolve: 草图选不中 %s" % sketch)
    if axis is not None:
        if not _select_obj(axis, append=True):
            raise RuntimeError("revolve: 旋转轴选不中")
    fm = wrap(m.FeatureManager, "IFeatureManager")
    rad = math.radians(abs(angle_deg))
    f = fm.FeatureRevolve2(
        True,                 # SingleDir=True 单向
        True,                 # IsSolid
        False,                # IsThin
        bool(is_cut),         # IsCut
        bool(reverse),        # ReverseDir
        False,                # BothDirectionUpToSameEntity
        0, 0,                 # Dir1Type=Blind? 0，Dir2Type
        rad, 0.0,             # ★ Dir1Angle 用弧度；Dir2Angle 不用
        False, False, 0.0, 0.0,   # OffsetReverse1/2, OffsetDistance1/2（m）
        0, 0.0, 0.0,          # ThinType, ThinThickness1/2
        bool(merge), True, True)
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("revolve 返回 None（草图缺中心线/轴，或参数非法）: %s" % sketch)
    return f


def _multi_select_features(m, names, first=False):
    """按名多选草图/曲线特征。

    ★ Nilove skill(Nilove2018, PROVEN) + wzyn skill：放样/扫描的截面草图
      用 IFeature.Select2(append=True, mark=1) 逐张追加选，不用 MultiSelect2
      （本机 MultiSelect2 + ISelectData.Mark 实测卡死/找不到成员）。
    first=True 时先清空选择集；后续追加保持 mark=1。
    """
    if first:
        m.ClearSelection2(True)
    n = 0
    for name in names:
        fe = feat_by_name(m, name)
        if fe is None:
            raise RuntimeError("找不到草图/曲线特征: %s" % name)
        if _select_obj(fe, append=(n > 0 or not first), mark=1):
            n += 1
    if n < len(names):
        raise RuntimeError("放样/扫描截面只选中 %s/%s 个: %s" % (n, len(names), names))
    return n


def loft_checked(m, sketches, closed=False, is_cut=False, guides=None,
                 keep_tangency=False, merge=True, verbose=False):
    """放样凸台/切除（SW2022 InsertProtrusionBlend2 / InsertCutBlend4）。

    sketches : 2+ 个闭合草图名，按截面顺序；★ 先用 MultiSelect2 mark=1 全选。
    guides   : 可选引导线草图名（同样 mark=1 追加选择）。
    is_cut   : True 走 InsertCutBlend4，否则 InsertProtrusionBlend2。
    """
    names = list(sketches)
    if len(names) < 2:
        raise ValueError("放样至少需要 2 个截面草图")
    m.ClearSelection2(True)
    _multi_select_features(m, names, first=True)
    if guides:
        _multi_select_features(m, list(guides))   # mark=1 追加
    fm = wrap(m.FeatureManager, "IFeatureManager")
    # ★ 参数值来自 Nilove skill [PROVEN]（SW2025, SW2022 兼容）：
    #   Start/EndMatchingType=0, TangentLength=1.0, TangentDir=True
    if is_cut:
        f = fm.InsertCutBlend(
            bool(closed), bool(keep_tangency), False, 1.0,
            0, 0,                 # StartMatchingType=EndMatchingType=0
            False, 0.0, 0.0, 0,   # IsThinBody, Thickness1/2, ThinType
            True, True)           # UseFeatScope, UseAutoSelect
    else:
        f = fm.InsertProtrusionBlend2(
            bool(closed), bool(keep_tangency), False, 1.0,
            0, 0,                 # Start/EndMatchingType
            1.0, 1.0, True, True, # Start/EndTangentLength + Dir [PROVEN]
            False, 0.0, 0.0, 0,   # IsThinBody, Thickness1/2, ThinType
            bool(merge), True, True, 0)  # Merge, FeatScope, AutoSelect, GuideInfluence
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("loft 返回 None（截面草图不闭合或顺序错误）: %s" % names)
    return f


def sweep_checked(m, profile, path, is_cut=False, twist_deg=0.0,
                  keep_tangency=False, merge=True, verbose=False):
    """扫描凸台/切除（SW2022 InsertProtrusionSwept4 / InsertCutSwept4）。

    ★ 选中方式（wzyn skill 2199★ + 本机实测）：
       profile 整张草图 mark=1，path 线段 mark=4（Select2 即可，无需 SELOBJGROUP）。
    ★★ 几何契约（2026-11-20 本机实测，两个条件缺一即静默返回 None）：
       1) 轮廓所在平面必须【垂直】于路径起点处的切线方向
       2) **轮廓圆心必须精确落在路径起点坐标上**（不是"靠近"，是重合）
          实测：跑道形路径起点 (0,-16)，轮廓圆心放 (0,-16) → OK vol=7848.4
                放 (0,0) → None。这一条比 1) 更常被忽略。
    ★ 闭环路径也支持（跑道形 1111mm 闭环扫描成功，dev −0.09%）；
      官方文档称闭环 twist 须为整圈倍数，但实测 twist=0 亦可通过。
    ★ CreateArc2 参数单位是【米】，而 swlib.line 内部已乘 MM ——
      手写 CreateArc2 时必须自己 ×0.001，否则圆弧画到 480 米外，
      症状：草图看似闭合、端点读数是 480000 而非 480，拉伸/扫描全失败。
    path 可以是草图名（取其所有草图线段），也可以是 IEdge/ISketchSegment 列表。
    """
    if not select_sketch(m, profile, mark=1, verbose=verbose):
        raise RuntimeError("sweep: 轮廓草图选不中 %s" % profile)
    # 取路径线段
    segs = []
    if isinstance(path, str):
        fe = feat_by_name(m, path)
        if fe is None:
            raise RuntimeError("sweep: 路径草图找不到 %s" % path)
        sk = wrap(fe, "IFeature").GetSpecificFeature2()
        if sk is not None:
            segs = list(wrap(sk, "ISketch").GetSketchSegments() or [])
    else:
        segs = list(path)
    if not segs:
        raise RuntimeError("sweep: 路径草图里没有线段: %s" % path)
    for s in segs:
        # ★ wzyn skill(2199★) 权威做法：路径 mark=4，Select2 即可，
        #   全仓库无 SELOBJGROUP（那是老论坛作法，本机实测不需要）。
        if not _select_obj(s, append=True, mark=4):
            raise RuntimeError("sweep: 路径线段选不中（mark=4）")
    fm = wrap(m.FeatureManager, "IFeatureManager")
    if is_cut:
        f = fm.InsertCutSwept4(
            False, 0, 0, bool(keep_tangency),
            0.0, False, False, False, 0, 0, 0, 0,
            math.radians(twist_deg), bool(merge), True, True, False)
    else:
        f = fm.InsertProtrusionSwept4(
            False, 0, 0, bool(keep_tangency), False, 0, 0,
            False, 0.0, 0.0, 0, 0,
            bool(merge), True, True,
            math.radians(twist_deg), True, False, 0.0, 0)
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError(
            "sweep 返回 None。按顺序查：\n"
            "  1) 轮廓圆心是否【精确落在路径起点】上？（最常见的坑）\n"
            "  2) 轮廓平面是否垂直于路径起点切线方向？\n"
            "  3) 手写 CreateArc2 是否漏乘 0.001（米）？\n"
            "  4) 路径线段是否全部选中（mark=4，逐段 append=True）？")
    return f


def shell_checked(m, thickness_mm, faces=None, outward=False, verbose=False):
    """抽壳（IModelDoc2.InsertFeatureShell，2 参；不在 IModelDocExtension）。

    faces: 要删除（开口）的 IEntity/IFace2 列表；None 时封闭抽壳（完全中空）。
    ★ 三个坑：
      1) IFace2 不继承 IEntity.Select2，必须 wrap 成 IEntity 后用 Select4+Mark=1。
      2) 厚度单位毫米，内部 *MM；返回类型是 VT_VOID，成功也返回 None。
      3) 所有诊断/测量必须在选面【之前】完成（它们会清空选择集）。
      4) 旋转体端面抽壳会被 SW 静默拒绝；薄壁回转件优先画带壁厚截面直接 revolve。
    """
    # ★★ 顺序铁律：所有诊断/测量必须在选面【之前】做完。
    #   CreateMassProperty / feature_tree 等调用会清空选择集；
    #   若在 Select4 之后调用它们，InsertFeatureShell 拿到空选择 → 静默失败。
    before = len(feature_tree(m))
    volume_before_shell = volume_mm3(m)

    m.ClearSelection2(True)
    # ★ 官方示例（The CAD Coder / muerus SolidWorks-Python）：面必须用
    #   IFace2→IEntity.Select4(True, SelectData)，Select2 对 IFace2 无效。
    sel_mgr = wrap(m.SelectionManager, "ISelectionMgr")
    sel_data = wrap(sel_mgr.CreateSelectData(), "ISelectData")
    sel_data.Mark = 1
    n = 0
    for f in (faces or []):
        try:
            ent = wrap(f, "IEntity")
        except Exception:
            ent = f
        try:
            ok = bool(ent.Select4(True, sel_data))
        except Exception:
            ok = _select_obj(ent, append=True)
        if ok:
            n += 1
    if faces and n == 0:
        raise RuntimeError("shell: 面选不中（需 IFace2→IEntity.Select4 + Mark=1）")
    # ★ 两个坑（类型库 38716 行实测）：
    #   1) InsertFeatureShell 在 IModelDoc2 上，不在 IModelDocExtension
    #   2) 返回类型是 VT_VOID=(24,0)，成功时也是 None —— 不能靠返回值判成败，
    #      必须查特征树里新增了 Shell 特征。
    doc = wrap(m, "IModelDoc2")
    doc.InsertFeatureShell(thickness_mm * MM, bool(outward))
    m.ClearSelection2(True)
    after = feature_tree(m)
    if len(after) <= before or not any("Shell" in t for _, t in after):
        # 旋转体上某些端面抽壳会被 SW 静默拒绝；给出诊断但用体积二次确认
        vol_after = volume_mm3(m)
        if abs(vol_after - volume_before_shell) > 1e-6:
            return True  # 几何确实变了，特征名可能不同
        raise RuntimeError("shell 未生成特征（厚度过大或面选择非法）: %s" %
                           [t for _, t in after])
    return True


def fillet_checked(m, radius_mm, edges=None, options=195):
    """圆角：直接委托 swlib.fillet（已实测 7 参），补进 v2 统一入口。"""
    return L.fillet(m, radius_mm, edges=edges, options=options)


def chamfer_checked(m, dist_mm, edges=None, angle_deg=45.0, options=1):
    """倒角：直接委托 swlib.chamfer（已实测 8 参）。"""
    return L.chamfer(m, dist_mm, edges=edges, angle_deg=angle_deg, options=options)


def face_cylinder(m, index=0):
    """返回【零件】里第 index 个圆柱面（IFace2）；找不到返回 None。

    ★★ 坑：`ISurface.IsCylinder` / `IsPlane` 在早绑定下是**属性**，
      写成 `IsCylinder()` 会报 `'bool' object is not callable`。
      一律用 getattr 读属性。

    ★ 与 faces_of() 的分工：
      - 本函数吃【零件】(IPartDoc)，只返回圆柱面，按序号取（给阵列/镜像找轴用）
      - faces_of() 吃【装配组件】(IComponent2)，返回全部面 + bbox/法向/面积
      装配里挑面请用 faces_of + plane_at / cyl_of，别用本函数。
    """
    try:
        body = wrap(wrap(m, "IPartDoc").GetBodies2(0, False)[0], "IBody2")
    except Exception:
        return None
    n = 0
    for f in body.GetFaces():
        f2 = wrap(f, "IFace2")
        try:
            s = f2.GetSurface()
            if getattr(s, "IsCylinder", False) is True:
                if n == index:
                    return f2
                n += 1
        except Exception:
            continue
    return None


def circular_pattern_checked(m, feature_name, axis_name, count, total_angle_deg=360.0,
                             geometry_pattern=True, equal_spacing=True):
    """圆周阵列（SW2022 FeatureCircularPattern5，本机实测通过）。

    ★ 铁律：被阵列特征 mark=4，旋转轴 mark=1；
      间距传【总角度 2π】+ EqualSpacing=True，不是 2π/n（那样返回 None）。

    axis_name:
      - 轴名字符串 → SelectByID2("AXIS")
      - IFace2 圆柱面 / IEntity → 选它后 InsertAxis2 生成临时轴
      - None → 自动用 face_cylinder() 找第一个圆柱面生成轴
    """
    m.ClearSelection2(True)
    fe = feat_by_name(m, feature_name)
    if fe is None or not _select_obj(fe, False, 4):
        raise RuntimeError("阵列：被阵列特征选不中 %s (mark=4)" % feature_name)

    axis_ok = False
    if isinstance(axis_name, str):
        for cand in (axis_name, "Axis1", "基准轴1"):
            try:
                if m.Extension.SelectByID2(cand, "AXIS", 0, 0, 0, True, 1, None, 0):
                    axis_ok = True
                    break
            except Exception:
                continue

    if not axis_ok:
        cyl = axis_name if (axis_name is not None
                            and not isinstance(axis_name, str)) else face_cylinder(m, 0)
        if cyl is None:
            raise RuntimeError("阵列：找不到旋转轴（无轴名且无圆柱面）")
        m.ClearSelection2(True)
        ent = wrap(cyl, "IEntity") if not isinstance(cyl, str) else cyl
        if not _select_obj(ent, append=False):
            raise RuntimeError("阵列：圆柱面选不中，无法生成临时轴")
        m.InsertAxis2(True)
        # InsertAxis2 会清空选择集，重新选特征 + 新轴
        m.ClearSelection2(True)
        fe = feat_by_name(m, feature_name)
        if fe is None or not _select_obj(fe, False, 4):
            raise RuntimeError("阵列：生成轴后特征重选失败")
        new_axis = None
        for nm, tp in reversed(feature_tree(m)):
            if tp in ("RefAxis", "Axis"):
                new_axis = nm
                break
        if new_axis and m.Extension.SelectByID2(new_axis, "AXIS", 0, 0, 0, True, 1, None, 0):
            axis_ok = True

    if not axis_ok:
        raise RuntimeError("阵列：轴选不中 (mark=1)")

    fm = wrap(m.FeatureManager, "IFeatureManager")
    f = fm.FeatureCircularPattern5(
        int(count), 2 * math.pi, False, "",
        bool(geometry_pattern), bool(equal_spacing), False, False,
        False, False, 0, 0.0, "", False)
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("圆周阵列返回 None（mark/总角度错误）: %s" % feature_name)
    return f


def mirror_checked(m, feature_name, plane_name):
    """镜像特征（InsertMirrorFeature2，5 参）。

    ★★ 2026-11-20 实测纠正 mark 体系（旧版写反了，恒返回 None）：
      被镜像特征 mark=**1**，基准面 mark=**2**
      （旧版写 mark=4 / mark=1，六种组合里只有 1/2 能成功）
      验证：矩形板镜像一个 20×20×10 槽 → Δ = −4000.00 mm³，精确。
    """
    m.ClearSelection2(True)
    fe = feat_by_name(m, feature_name)
    if fe is None or not _select_obj(fe, False, 1):
        raise RuntimeError("镜像：被镜像特征选不中 %s (mark=1)" % feature_name)
    ok = m.Extension.SelectByID2(plane_name, "PLANE", 0, 0, 0, True, 2, None, 0)
    if not ok:
        alias = {"Front Plane": "前视基准面", "Top Plane": "上视基准面",
                 "Right Plane": "右视基准面"}.get(plane_name)
        if alias:
            ok = m.Extension.SelectByID2(alias, "PLANE", 0, 0, 0, True, 2, None, 0)
    if not ok:
        raise RuntimeError("镜像：基准面选不中 %s (mark=2)" % plane_name)
    fm = wrap(m.FeatureManager, "IFeatureManager")
    f = fm.InsertMirrorFeature2(False, False, False, False, 0)
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("镜像返回 None: %s / %s" % (feature_name, plane_name))
    return f


# ---------------------------------------------------------------- 拔模（Python 层数学等效）
# 移植自 marinmax720-gif/agent Driver v8：原生 InsertFeatureDraft2 在外部 COM 不可靠，
# 改用「梯形截面拉伸 / 直角梯形旋转」拼出等效几何。★ 生成的是等效几何，非参数化拔模特征。

def draft_extrude(m, bottom_w, bottom_h, height, draft_angle_deg, plane="Top Plane"):
    """棱柱拔模等效：梯形截面一次拉伸。四边对称内缩 offset=H·tan(α)。

    校验：H·tan(α) < min(bottom_w,bottom_h)/2，否则顶部自交。
    返回 (feature, top_w, top_h)。
    """
    offset = height * math.tan(math.radians(draft_angle_deg))
    top_w, top_h = bottom_w - 2 * offset, bottom_h - 2 * offset
    if top_w <= 0 or top_h <= 0:
        raise ValueError("拔模角过大导致顶部自交：offset=%.3f, bottom=(%.1f,%.1f)"
                         % (offset, bottom_w, bottom_h))
    hb_w, hb_h, ht_w, ht_h = bottom_w/2, bottom_h/2, top_w/2, top_h/2
    with addtoDB(m) as skm:
        L.new_sketch(m, plane)
        L.line(skm, -hb_w, -hb_h, hb_w, -hb_h)   # 底边
        L.line(skm, hb_w, -hb_h, ht_w, ht_h)      # 右斜边
        L.line(skm, ht_w, ht_h, -ht_w, ht_h)      # 顶边
        L.line(skm, -ht_w, ht_h, -hb_w, -hb_h)    # 左斜边
        sk = last_sketch_name(m)
        skm.InsertSketch(True)
        f = extrude_checked(m, sk, height)
    return f, top_w, top_h


def draft_cone(m, bottom_r, top_r, height, plane="Front Plane"):
    """回转体拔模等效：直角梯形 + 中心线旋转 360°（圆台）。

    实际拔模角 = atan((bottom_r-top_r)/height)。
    返回 (feature, angle_deg)。
    """
    if bottom_r <= 0 or top_r < 0 or height <= 0:
        raise ValueError("圆台参数非法: r1=%.1f r2=%.1f h=%.1f" % (bottom_r, top_r, height))
    with addtoDB(m) as skm:
        L.new_sketch(m, plane)
        skm.CreateCenterLine(0, -0.005, 0, 0, (height + 5) * MM, 0)  # 轴，米
        L.line(skm, 0, 0, bottom_r, 0)              # 底边
        L.line(skm, bottom_r, 0, top_r, height)     # 斜边（拔模）
        L.line(skm, top_r, height, 0, height)       # 顶边
        sk = last_sketch_name(m)
        skm.InsertSketch(True)
        f = revolve_checked(m, sk, 360.0)
    return f, math.degrees(math.atan((bottom_r - top_r) / height))


def draft_native(m, faces, neutral_plane, angle_deg, reverse=False):
    """真·拔模特征入口（PILOT）：InsertFeatureDraft2。

    ★ 外部 COM 在部分版本返回 None；失败请退回 draft_extrude/draft_cone。
    选择：拔模面 mark=1、中性面 mark=2（wzyn SW_API_REFERENCE）。
    """
    m.ClearSelection2(True)
    for i, face in enumerate(faces or []):
        ent = wrap(face, "IEntity")
        if not _select_obj(ent, append=(i > 0), mark=1):
            raise RuntimeError("拔模面选不中 (mark=1)")
    if neutral_plane is not None:
        # 中性面/基准面 mark=2
        if not m.Extension.SelectByID2(neutral_plane, "PLANE", 0, 0, 0, True, 2, None, 0):
            raise RuntimeError("中性面选不中 (mark=2): %s" % neutral_plane)
    fm = wrap(m.FeatureManager, "IFeatureManager")
    f = fm.InsertFeatureDraft2(
        bool(reverse), 1, False, math.radians(angle_deg), False, 0, 0)
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("InsertFeatureDraft2 返回 None（外部 COM 不可靠，请用等效法）")
    return f


# ---------------------------------------------------------------- 钣金 / 孔向导 / 工程图
def sheetmetal_base_flange(m, sketch, thickness_mm, radius_mm=None,
                           length_mm=None, reverse=False, relief_type=0,
                           relief_ratio=0.5, merge=True):
    """钣金基体法兰（FeatureData 路线，非废弃的长参数接口）。

    ★ wzyn skill(2199★) 实测结论：`InsertSheetMetalBaseFlange2` 是已废弃长参数
      接口，Python IDispatch 下常返回 None。正解：
        CreateDefinition(swFmBaseFlange=34) → IBaseFlangeFeatureData.Initialize
        → 设属性 → CreateFeature
    签名来自本机类型库 23651/3516 行 + wzyn SW2026 验证（SW2022 兼容）。
    sketch 必须是闭合轮廓；厚度/半径/长度单位毫米。
    """
    if not select_sketch(m, sketch):
        raise RuntimeError("base_flange: 草图选不中 %s" % sketch)
    fm = wrap(m.FeatureManager, "IFeatureManager")
    # swFmBaseFlange = 34（swFeatureNameID_e）
    raw = fm.CreateDefinition(34)
    if raw is None:
        raise RuntimeError("base_flange: CreateDefinition(34) 返回 None")
    try:
        fd = raw.QueryInterface(pythoncom.IID_IDispatch)
        fd = win32com.client.Dispatch(fd)
    except Exception:
        fd = raw
    t = thickness_mm * MM
    r = (radius_mm if radius_mm is not None else thickness_mm) * MM
    # Initialize(UseMaterialParams, OverrideBendAllowance, CustomBendAllowance,
    #            OverrideBendRelief, ReliefType, UseReliefRatio, ReliefRatio,
    #            ReliefWidth, ReliefDepth)
    # ★ CustomBendAllowance 是 IDispatch(9,1)，传 None 会报"类型不匹配"，
    #   必须传空 Dispatch VARIANT。
    empty_disp = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    fd.Initialize(False, True, empty_disp, False,
                  int(relief_type), True, float(relief_ratio), 0.0, 0.0)
    for attr, val in (("BendRadius", r), ("Thickness", t),
                      ("ReverseThickness", bool(reverse)),
                      ("D1EndConditionType", 0),
                      ("D1EndConditionDistance", (length_mm or thickness_mm * 10) * MM)):
        try:
            setattr(fd, attr, val)
        except Exception:
            pass
    f = fm.CreateFeature(fd)
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("base_flange 返回 None（草图非闭合或 FeatureData 属性非法）")
    return f


def hole_wizard(m, sketch, hole_type=2, standard="ANSI Inch", fastener="",
                size="", end_type=0, diameter_mm=10.0, depth_mm=None):
    """孔向导（SW2022 HoleWizard5，27 参）。

    签名来自类型库 22526 行。★ 必须在要打孔的面/草图上先选中草图点。
    hole_type(swWzdGeneralHoleTypes_e): 0=CounterBore 1=CounterSink 2=Hole
                                       3=PipeTap 4=Tap 5=Legacy
    end_type(swEndConditions_e): 0=Blind 1=ThroughAll
    ★ StandardIndex 必须是【热身后】的索引，直接传字符串名易失败；
      本函数先尝试按名取索引，失败则回退 0。
    """
    if not select_sketch(m, sketch):
        raise RuntimeError("hole_wizard: 草图选不中 %s" % sketch)
    fm = wrap(m.FeatureManager, "IFeatureManager")
    std_idx = 0
    try:
        names = wrap(m, "IModelDoc2").GetUserPreferenceStringValue(0)  # 占位，索引见下
    except Exception:
        names = None
    d = diameter_mm * MM
    dep = (depth_mm if depth_mm is not None else diameter_mm * 3) * MM
    f = fm.HoleWizard5(
        int(hole_type), int(std_idx), 0, str(size),
        int(end_type), d, dep, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        "", False, True, True,
        False, True, False)
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("hole_wizard 返回 None（标准索引/尺寸非法，先热身后重试）")
    return f


# 自动标注的类型位掩码（swInsertAnnotation_e，本机 SW2022 实测）
ANN_DIM_MARKED = 32768        # swInsertDimensionsMarkedForDrawing  ★ 关键位
ANN_DIM_NOT_MARKED = 524288   # swInsertDimensionsNotMarkedForDrawing
ANN_DIM_BASIC = 8             # swInsertDimensions
ANN_CENTERLINES = 2           # swInsertDatums
ANN_CENTERMARKS = 4           # swInsertDatumTargets
ANN_INSTANCE_COUNTS = 16      # swInsertInstanceCounts
# ★★ 本机实测：**只要含 32768 位就成功**（32768 单独 / |524288 / |8 / |2 / |4 / |16 全部 +1）
#    不含 32768 的一律 0 条（8 单独、524288 单独）
ANN_WORKING = ANN_DIM_MARKED


def insert_model_annotations(drawing, option=0, types=ANN_WORKING, all_views=False,
                             duplicate_dims=False, hidden_feature_dims=False,
                             use_placement_in_sketch=False):
    """工程图自动插入模型标注（IDrawingDoc.InsertModelAnnotations3，**6 参**）。

    ★ 签名来自类型库（api_lookup.py IDrawingDoc InsertModelAnnotations3）：
        (Option, Types, AllViews, DuplicateDims, HiddenFeatureDims, UsePlacementInSketch)
      旧版按 4 参调用 —— 少传两参会被 COM 补 Missing，部分组合下静默不插。

    ★★ 2026-11-21 实测（60×40×15 带两孔板，**每组合都用全新图纸**）：

       | types      | 组成                    | rc    | 增量 |
       |------------|-------------------------|-------|------|
       | 8          | swInsertDimensions      | False | 0    |
       | **32768**  | **MarkedForDrawing**    | **True** | **+1** |
       | 524288     | NotMarkedForDrawing     | False | 0    |
       | 32768\\|524288 | 两者                | True  | +1   |
       | 32768\\|8   | +尺寸                   | True  | +1   |
       | 32768\\|2/4/16 | +中心线/标记/计数    | True  | +1   |

       **结论：只要 types 含 32768 位就成功**；不含的一律 0 条。
       默认值 = `ANN_WORKING` = 32768。

    ★★★ 关键陷阱（差点得出错误结论）：**同一张图纸上重复调用不会再加标注**。
       第一次调 32768 插了 1 条后，后续任何 types 都是"0 增量" ——
       我最初在一张图纸上连着试 8 个组合，于是错误地以为"只有 557056 能用"。
       必须**每个组合都新建图纸**，否则测量的是"这张图还能不能加"而不是"这个参数行不行"。
       同理 `insert_model_annotations_checked` 的重试逻辑也只能用于"换视图再试"，
       不能用于"换参数再试"。

    ★ 前置铁律（REA kit 实测）：模型必须已在会话里【打开】。
    ★ 判据：只能看 `IView.GetAnnotationCount()` / `GetDisplayDimensionCount()`
      的**增量** —— rc=True 也可能 0 条，rc=False 也可能插进去了。
    """
    dd = wrap(drawing, "IDrawingDoc")
    rc = dd.InsertModelAnnotations3(int(option), int(types), bool(all_views),
                                    bool(duplicate_dims),
                                    bool(hidden_feature_dims),
                                    bool(use_placement_in_sketch))
    return bool(rc)


def insert_model_annotations_checked(drawing, option=0, types=ANN_WORKING,
                                     all_views=True, duplicate_dims=False,
                                     hidden_feature_dims=False,
                                     use_placement_in_sketch=False,
                                     retries=2):
    """插标注 + **回读增量**判成败（返回结构化结果，不靠返回值）。

    返回 {"ok", "before", "after", "added", "rc", "types", "tries"}。

    ★★ 重试只用于「换视图再试」，**不能用于换参数再试**：
      同一张图纸上重复调用 InsertModelAnnotations3 不会再加标注（本机实测），
      所以拿一张图连试多个 types 会得出"全都失败"的错误结论。
      要比较不同 types，必须每次新建图纸（见 probe_annotations.py）。
    """
    before = drawing_annotation_total(drawing)
    rep = {"types": int(types), "before": before, "tries": []}
    for attempt in range(max(1, retries)):
        allv = all_views if attempt == 0 else False
        try:
            rc = insert_model_annotations(drawing, option, types, allv,
                                          duplicate_dims, hidden_feature_dims,
                                          use_placement_in_sketch)
        except Exception as e:
            rc = None
            rep["tries"].append({"all_views": allv, "rc": None,
                                 "error": str(e)[:100]})
            continue
        after = drawing_annotation_total(drawing)
        rep["tries"].append({"all_views": allv, "rc": rc, "after": after})
        if after > before:
            rep.update(ok=True, rc=rc, after=after, added=after - before)
            return rep
        # 没插进去 → 逐视图再试
        if allv:
            for iv in drawing_views(drawing):
                try:
                    com_member(wrap(drawing, "IDrawingDoc"), "ActivateView",
                               com_member(iv, "GetName2", default=""))
                    insert_model_annotations(drawing, option, types, False,
                                             duplicate_dims, hidden_feature_dims,
                                             use_placement_in_sketch)
                except Exception:
                    continue
            after = drawing_annotation_total(drawing)
            if after > before:
                rep.update(ok=True, rc=rc, after=after, added=after - before)
                return rep
    rep.update(ok=False, rc=None, after=drawing_annotation_total(drawing),
               added=drawing_annotation_total(drawing) - before)
    return rep


def drawing_view_count(drawing):
    """工程图里视图个数（IDrawingDoc.GetViewCount，0 参 → VT_I4）。"""
    try:
        return int(wrap(drawing, "IDrawingDoc").GetViewCount())
    except Exception:
        return None


def drawing_views(drawing):
    """工程图里所有 IView 列表（IDrawingDoc.GetViews，0 参 → VT_VARIANT）。

    ★ 本机返回是**嵌套元组**：`((Sheet1, 视图1, 视图2, 视图3),)` ——
      外层是"图纸"，内层才是视图；而且第 0 项是 ISheet 不是 IView。
      旧版直接 `for v in arr` 会拿到一个元组，`wrap` 后所有成员都报
      "'tuple' object has no attribute ..."。这里展平并按 GetName2 过滤。
    """
    try:
        arr = wrap(drawing, "IDrawingDoc").GetViews()
    except Exception:
        return []
    flat = []

    def _walk(x, depth=0):
        if depth > 3 or x is None:
            return
        if isinstance(x, (list, tuple)):
            for y in x:
                _walk(y, depth + 1)
            return
        flat.append(x)

    _walk(arr)
    out = []
    for v in flat:
        try:
            iv = wrap(v, "IView")
            if com_member(iv, "GetName2", default=None):
                out.append(iv)
        except Exception:
            continue
    return out


def view_annotation_count(view):
    """某个视图上的标注条数（IView.GetAnnotationCount，0 参 → VT_I4）。

    ★ 这是「自动标注到底插进去没有」的唯一可信判据：
      InsertModelAnnotations3 返回 True 也可能 0 条（模型没打开/尺寸被抑制）。
    """
    try:
        return int(wrap(view, "IView").GetAnnotationCount())
    except Exception:
        return None


def drawing_annotation_total(drawing):
    """全图标注总数（逐视图累加）。"""
    n = 0
    for v in drawing_views(drawing):
        c = view_annotation_count(v)
        if c:
            n += c
    return n


def current_sheet(drawing):
    """当前图纸对象 ISheet（IDrawingDoc.GetCurrentSheet，0 参 → VT_DISPATCH）。"""
    try:
        s = wrap(drawing, "IDrawingDoc").GetCurrentSheet()
        return wrap(s, "ISheet") if s is not None else None
    except Exception:
        return None


def sheet_properties(drawing):
    """图纸幅面 → dict(width_mm, height_mm, paper_size, scale_num, scale_den, raw)。

    ★★ 2026-11-21 实测修正（两次错）：
      ① 旧版直接 `return GetCurrentSheet()` 却叫 sheet_properties —— 名实不符，
         返回的是 ISheet 对象，根本不是属性。
      ② 改成调 `ISheet.GetProperties()` 后按位置取前两项，**取错了**：
         本机返回 7 项 `(0.0, 13.0, 1.0, 1.0, 1.0, 0.2794, 0.2159)`，
         真正幅面在**索引 5/6**（0.2794×0.2159 m = 11×8.5 in = Letter），
         前两项是别的含义。按位置猜索引靠不住。

    ★ 正确做法：用 `ISheet.GetSize(Width, Height)` ——
      签名 `(VT_R8* Width, VT_R8* Height) → VT_I4`，两个 **by-ref 出参**，
      正好用上 `swlib.call_byref`。这是官方语义明确的幅面读取接口。

    `GetProperties` 的 raw 仍保留在返回值里供排查，但不再据此判幅面。
    读不到时返回 None 字段，不抛异常（出图不该因读幅面失败而中断）。
    """
    import swlib as L
    out = {"width_mm": None, "height_mm": None, "paper_size": None,
           "scale_num": None, "scale_den": None, "raw": None}
    sh = current_sheet(drawing)
    if sh is None:
        return out

    # ① 幅面尺寸：GetSize 两个 by-ref 出参（权威）
    try:
        ret, outs = L.call_byref(sh, "GetSize", [], ["r8", "r8"])
        w, h = (outs[0], outs[1]) if outs else (None, None)
        if w and h:
            out["width_mm"] = round(float(w) * 1000.0, 2)
            out["height_mm"] = round(float(h) * 1000.0, 2)
            out["paper_size"] = int(ret) if isinstance(ret, int) else None
    except Exception:
        # 早绑定兜底：出参位置传 0.0，从返回元组拆
        try:
            ret = sh.GetSize(0.0, 0.0)
            r, outs = L.split_out(ret, 2)
            if outs[0] and outs[1]:
                out["width_mm"] = round(float(outs[0]) * 1000.0, 2)
                out["height_mm"] = round(float(outs[1]) * 1000.0, 2)
        except Exception:
            pass

    # ② 比例：GetProperties 的索引 2/3（本机实测稳定）
    try:
        p = sh.GetProperties()
        if isinstance(p, (list, tuple)):
            out["raw"] = [round(float(x), 6) if isinstance(x, (int, float)) else x
                          for x in p]
            if len(p) >= 4:
                out["scale_num"] = float(p[2])
                out["scale_den"] = float(p[3])
    except Exception:
        pass
    return out


def create_section_view_at(drawing, x, y, z, label="A", options=0,
                           excluded=None, depth=0.0):
    """剖视图（IDrawingDoc.CreateSectionViewAt5，7 参）。

    签名来自类型库 16732 行。★ 前置：先在图纸上用 CreateLine 画剖面线，
    再 Select2(False,0) 选中它，最后调本函数；直接调用返回 None。
    x/y/z 是图纸坐标（米）。
    """
    dd = wrap(drawing, "IDrawingDoc")
    view = dd.CreateSectionViewAt5(float(x), float(y), float(z), str(label),
                                   int(options), excluded, float(depth))
    if view is None:
        raise RuntimeError("剖视图返回 None（须先画剖面线并选中）")
    return view


# ---------------------------------------------------------------- 自定义属性 / 配置 / 材料
def set_custom_props(m, props, config=""):
    """批量写自定义属性（ICustomPropertyManager.Add3，4 参）。

    props: {名: 值}；值一律按文本(30)写，数字/日期由调用方格式化。
    ★ 空 config 字符串 = 文件级属性；给配置名 = 配置特定属性。
    ★ 值必须非空，空字符串会被 SW 忽略。
    """
    ext = wrap(m.Extension, "IModelDocExtension")
    mgr = wrap(ext.CustomPropertyManager(str(config)), "ICustomPropertyManager")
    n = 0
    for k, v in (props or {}).items():
        if v is None or str(v) == "":
            continue
        rc = mgr.Add3(str(k), 30, str(v), 1)   # 30=文本, 1=覆盖
        if rc == 0:                             # 0 = 成功
            n += 1
    return n


def get_custom_props(m, config=""):
    """读全部自定义属性 → {名: 值}。

    ★ Get6 返回 (状态码, ValOut, ResolvedValOut, WasResolved, LinkToProperty)，
      属性值在【索引 1】，不是索引 0（索引 0 是返回码，恒为 2）。
    """
    ext = wrap(m.Extension, "IModelDocExtension")
    mgr = wrap(ext.CustomPropertyManager(str(config)), "ICustomPropertyManager")
    out = {}
    try:
        names = list(mgr.GetNames() or [])
    except Exception:
        return out
    for nm in names:
        try:
            r = mgr.Get6(nm, False)
            if isinstance(r, (list, tuple)) and len(r) >= 2:
                out[nm] = r[1]
            else:
                out[nm] = r
        except Exception:
            out[nm] = None
    return out


def add_configuration(m, name, comment="", alternate_name="", options=0):
    """新建配置。

    ★ 接口归属（类型库 35879 行实测）：`AddConfiguration3` 在 **IModelDoc2** 上，
      不在 IConfigurationManager（后者只有 AddConfiguration）。
    """
    doc = wrap(m, "IModelDoc2")
    cfg = doc.AddConfiguration3(str(name), str(comment),
                                str(alternate_name), int(options))
    if cfg is None:
        raise RuntimeError("AddConfiguration3 返回 None: %s" % name)
    return cfg


def set_material(m, material, database="", config=""):
    """设置材料（IPartDoc.SetMaterialPropertyName2，3 参）。

    material: 如 "ABS"、"Plain Carbon Steel"、"1060 Alloy"
    database: 空字符串 = 默认 SolidWorks Materials 库
    ★ 材料写错名不报错但静默不生效 → 用 get_material() 回读确认。
    ★ GetMaterialPropertyName2 返回 (材料名, 库名) 二元组，比较时只取第 1 项。
    """
    pd = wrap(m, "IPartDoc")
    pd.SetMaterialPropertyName2(str(config), str(database), str(material))
    got = get_material(m, config)
    if got != material:
        raise RuntimeError("材料未生效: 期望 %s，实际 %s" % (material, got))
    return got


def get_material(m, config=""):
    """回读材料名（只返回材料名，库名丢弃）。"""
    try:
        pd = wrap(m, "IPartDoc")
        r = pd.GetMaterialPropertyName2(str(config), "")
        if isinstance(r, (list, tuple)) and r:
            return r[0]          # (材料名, 库名) → 取材料名
        return r
    except Exception:
        return None


# ---------------------------------------------------------------- 曲面（焊件前的更易验证项）
def surface_extrude(m, sketch, depth_mm, reverse=False):
    """拉伸曲面（IFeatureManager.FeatureExtruRefSurface，21 参）。

    ★ 只选开放或闭合草图都可；生成的是 sheet body（曲面体），不是实体。
    ★ 返回类型是 VT_VOID=(24,0)，成功也返回 None —— 必须用 body_counts() 判据。
    """
    if not select_sketch(m, sketch):
        raise RuntimeError("surface_extrude: 草图选不中 %s" % sketch)
    fm = wrap(m.FeatureManager, "IFeatureManager")
    before = body_counts(m)
    fm.FeatureExtruRefSurface(
        True, bool(reverse), False, 0, 0,
        depth_mm * MM, 0.0,
        False, False, False, False, 0.0, 0.0,
        False, False, False, False,
        False, False,          # CapEnd1, CapEnd2
        False, True)           # DeleteOriginalFace, KnitResult
    m.ClearSelection2(True)
    after = body_counts(m)
    if after == before:
        raise RuntimeError("surface_extrude 未生成曲面体（草图非法）: %s -> %s"
                           % (before, after))
    return after


def body_counts(m):
    """返回 (实体数, 曲面体数)。判曲面/实体最可靠的判据。"""
    pd = wrap(m, "IPartDoc")
    solid = len(pd.GetBodies2(0, False) or [])   # 0 = swSolidBody
    sheet = len(pd.GetBodies2(1, False) or [])   # 1 = swSheetBody
    return solid, sheet


def surface_revolve(m, sketch, angle_deg=360.0, reverse=False):
    """旋转曲面（InsertRevolvedRefSurface，4 参，在 IFeatureManager）。

    签名来自类型库 23550 行：(Angle弧度, ReverseDir, Angle2, RevType)
    判据同 surface_extrude：靠 body_counts 变化确认。
    """
    if not select_sketch(m, sketch):
        raise RuntimeError("surface_revolve: 草图选不中 %s" % sketch)
    fm = wrap(m.FeatureManager, "IFeatureManager")
    before = body_counts(m)
    fm.InsertRevolvedRefSurface(math.radians(abs(angle_deg)),
                                bool(reverse), 0.0, 0)
    m.ClearSelection2(True)
    after = body_counts(m)
    if after == before:
        raise RuntimeError("surface_revolve 未生成曲面体（缺中心线或轮廓非法）")
    return after


def surface_planar(m, sketch):
    """平面区域曲面（InsertPlanarRefSurface，0 参）。

    ★ 接口归属（类型库 34481/38826 行实测）：在 **IModelDoc2** 上，
      不在 IFeatureManager（后者只有 InsertFlattenSurface）。
    """
    if not select_sketch(m, sketch):
        raise RuntimeError("surface_planar: 草图选不中 %s" % sketch)
    before = body_counts(m)
    wrap(m, "IModelDoc2").InsertPlanarRefSurface()
    m.ClearSelection2(True)
    after = body_counts(m)
    if after == before:
        raise RuntimeError("surface_planar 未生成曲面体（草图非闭合共面）")
    return after


def surface_thicken(m, face_or_body, thickness_mm, direction=0, sw=None):
    """曲面加厚成实体（IModeler.ThickenSheet，3 参）。

    direction: 0=单向 1=反向 2=两侧对称
    ★ 前置：必须先把曲面体/面选进选择集。
    ★ 接口归属（类型库 58445 行）：`GetModeler` 在 **ISldWorks** 上，
      不在 IModelDoc2。传 sw 参数或从全局连接取。
    """
    if sw is None:
        try:
            sw = wrap(win32com.client.GetActiveObject("SldWorks.Application"), "ISldWorks")
        except Exception:
            raise RuntimeError("surface_thicken 需要 ISldWorks，请显式传 sw=")
    mdl = wrap(sw.GetModeler(), "IModeler")
    f = mdl.ThickenSheet(face_or_body, thickness_mm * MM, int(direction))
    if f is None:
        raise RuntimeError("ThickenSheet 返回 None（厚度过大或曲面非法）")
    return f


# ---------------------------------------------------------------- 焊件
def structural_weldment(m, path_sketch, profile_path, segment_groups=None,
                        connected=1, allow_protrusion=False, config="",
                        corner_treatment=True):
    """结构件焊件（InsertStructuralWeldment5，5 参）。

    ★ wzyn skill(2199★) 实测三件套，缺一不可：
      1) 先 `InsertWeldmentFeature()` 建焊件文件夹（没有它整个失败）
      2) `CreateStructuralMemberGroup()` 建组，设 `.Segments`(Dispatch数组)
         与 `.ApplyCornerTreatment`
      3) `Groups` 参数必须是 **Dispatch SAFEARRAY**，传 None 必返回 None
    segment_groups: [[seg1, seg2...], ...] 每个子列表是一组的路径线段；
                    传 None 时自动取 path_sketch 的全部线段作为单组。
    connected: 0=不连接 1=简单切剪（默认 1）
    """
    # 1) 确保焊件文件夹存在
    types = {t for _, t in feature_tree(m)}
    if "WeldmentFeature" not in types:
        fm0 = wrap(m.FeatureManager, "IFeatureManager")
        if fm0.InsertWeldmentFeature() is None:
            raise RuntimeError("weldment: InsertWeldmentFeature 失败")

    # 2) 取路径线段（自动分组时用）
    if segment_groups is None:
        fe = feat_by_name(m, path_sketch)
        if fe is None:
            raise RuntimeError("weldment: 路径草图找不到 %s" % path_sketch)
        sk = wrap(fe, "IFeature").GetSpecificFeature2()
        segs = list(wrap(sk, "ISketch").GetSketchSegments() or []) if sk else []
        if not segs:
            raise RuntimeError("weldment: 路径草图里没有线段")
        segment_groups = [segs]

    # 3) 建组
    fm = wrap(m.FeatureManager, "IFeatureManager")
    groups = []
    for raw in segment_groups:
        segs = tuple(s for s in (raw or []) if s is not None)
        if not segs:
            raise ValueError("weldment: 某组没有路径段")
        g = fm.CreateStructuralMemberGroup()
        if g is None:
            raise RuntimeError("weldment: CreateStructuralMemberGroup 返回 None")
        g = wrap(g, "IStructuralMemberGroup")
        g.Segments = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, list(segs))
        g.ApplyCornerTreatment = bool(corner_treatment)
        if corner_treatment:
            try:
                g.CornerTreatmentType = 1   # swEndConditionMiter
                g.MiterMergeCondition = False
            except Exception:
                pass
        groups.append(g)

    # 4) 建特征（Groups 必须打包成 Dispatch SAFEARRAY）
    m.ClearSelection2(True)
    grp_var = win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, groups)
    f = fm.InsertStructuralWeldment5(
        str(profile_path), int(connected), bool(allow_protrusion),
        grp_var, str(config))
    m.ClearSelection2(True)
    if f is None:
        raise RuntimeError("weldment 返回 None（型材路径/分组非法）")
    return f


def find_weldment_profiles(limit=8):
    """探测本机焊件型材库（.sldlfp），返回候选路径列表。

    ★ 本机实测库在 `F:\\SOLIDWORKS\\data\\weldment profiles\\`（不是 lang 目录）。
      也兼容 Program Files / ProgramData 安装。
    """
    import glob as _glob
    roots = [
        r"F:\SOLIDWORKS\data\weldment profiles",
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\data\weldment profiles",
        r"C:\ProgramData\SolidWorks\SOLIDWORKS 2022\weldment profiles",
    ]
    cands = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            cands.extend(_glob.glob(os.path.join(root, "**", "*.sldlfp"),
                                    recursive=True)[:limit])
        except Exception:
            pass
        if cands:
            break
    return cands


def weldment_cut_list(m):
    """读焊件切割清单（CutListFolder 列表），返回 [(名称, 项目数)]。

    ★★ 2026-11-20 实测纠正：旧版调 `InsertWeldmentCutList2(None)` 必返回 None。
      那个方法是【插入切割清单表格】用的，不是生成切割清单。
      切割清单是 SW 建焊件时自动生成的，但 **内存中不出现**，
      必须【存盘 → 关闭 → 重开】后才在特征树里看到 CutListFolder。

    用法：
        m = V.new_part(sw); ...建焊件...
        V.save_checked(m, path)
        V.close_doc(sw, m)
        m2 = V.open_doc(sw, path, doc_type=1)
        print(V.weldment_cut_list(m2))    # [('切割清单项目1', ...), ...]
    """
    out = []
    for nm, tp in feature_tree(m):
        if tp == "CutListFolder":
            out.append(nm)
    return out


def weldment_cut_list_table(m):
    """在工程图里插入焊件切割清单表格（InsertWeldmentCutList2）。

    ★ 与 weldment_cut_list() 区别：本函数插【表格】，需要焊件已存盘重开。
      返回 Feature 或 None（表格位置不可控，见 pitfalls 已知限制）。
    """
    fm = wrap(m.FeatureManager, "IFeatureManager")
    f = fm.InsertWeldmentCutList2(None)
    return f


# ---------------------------------------------------------------- 运动仿真（Motion 插件）
# 类型库：F:\SOLIDWORKS\swmotionstudy.tlb  IID {45DB5211-F358-4B5E-A235-E792EB818BAA} v30
MOTION_TLB = "{45DB5211-F358-4B5E-A235-E792EB818BAA}"
# swMotionStudyType_e
MS_ASSEMBLY = 1          # 装配体运动（基础）
MS_PHYSICAL = 2          # 物理仿真
MS_COSMOS = 4            # CosmosMotion
MS_LEGACY_COSMOS = 8
MS_NEW_COSMOS = 16


def motion_manager(asm):
    """取运动算例管理器。

    ★ 接口归属（类型库 41044 行实测）：`GetMotionStudyManager` 在
      **IModelDocExtension** 上，不在 IAssemblyDoc。
    ★ Motion 是插件：未加载时返回 None。
    """
    doc = wrap(asm, "IModelDoc2")
    ext = wrap(doc.Extension, "IModelDocExtension")
    mgr = ext.GetMotionStudyManager()
    if mgr is None:
        raise RuntimeError("Motion 插件未加载（GetMotionStudyManager 返回 None）")
    try:
        mod = win32com.client.gencache.EnsureModule(MOTION_TLB, 0, 30, 0)
        mgr = mod.IMotionStudyManager(mgr._oleobj_.QueryInterface(pythoncom.IID_IDispatch))
    except Exception:
        pass
    return mgr


def ensure_motion_addin(sw, quiet=True):
    """确保 Motion 插件已加载。返回 True/False。"""
    try:
        rc = sw.LoadAddIn("")   # 空串 = 用注册表默认；失败再用 GetAddInObject 探测
    except Exception:
        rc = False
    # 探测：能否拿到 addin 对象
    for name in ("SldWorks.MotionStudy", "SWMotionStudy.MotionStudy",
                 "CosmosMotion.CosmosMotion"):
        try:
            if sw.GetAddInObject(name) is not None:
                return True
        except Exception:
            continue
    return bool(rc)


def create_motion_study(asm, name=None):
    """新建运动算例，返回 IMotionStudy。

    ★ 不传 name 时 SW 自动命名（运动算例1/2...）；返回对象 .Name 可读。
    """
    mgr = motion_manager(asm)
    ms = mgr.CreateMotionStudy()
    if ms is None:
        raise RuntimeError("CreateMotionStudy 返回 None")
    try:
        mod = win32com.client.gencache.EnsureModule(MOTION_TLB, 0, 30, 0)
        ms = mod.IMotionStudy(ms._oleobj_.QueryInterface(pythoncom.IID_IDispatch))
    except Exception:
        pass
    if name:
        try:
            ms.Name = str(name)
        except Exception:
            pass
    return ms


def list_motion_studies(asm):
    """列出所有运动算例名。"""
    mgr = motion_manager(asm)
    try:
        return list(mgr.GetMotionStudyNames() or [])
    except Exception:
        return []


def activate_motion_study(asm, name):
    """激活指定运动算例。"""
    mgr = motion_manager(asm)
    ok = mgr.ActivateMotionStudy(str(name))
    if not ok:
        raise RuntimeError("ActivateMotionStudy 失败: %s" % name)
    return True


def calculate_motion(ms):
    """计算运动算例。★ 必须先 Activate，否则算的是别的算例。"""
    ms.Activate()
    ok = ms.Calculate()
    if not ok:
        raise RuntimeError("Motion Calculate 失败（缺马达/配合过约束/时间设置非法）")
    return True


def play_motion(ms, from_start=False):
    """播放运动算例。"""
    ms.Activate()
    return bool(ms.PlayFromStart() if from_start else ms.Play())


def motion_results(ms, time, component):
    """读某时刻某组件的运动结果 → dict。

    返回 {linear_velocity, angular_velocity, linear_acceleration}，
    每项是 IMathVector 或标量，取不到给 None。
    """
    out = {}
    for key, meth in (("linear_velocity", "GetLinearVelocity"),
                      ("angular_velocity", "GetAngularVelocity"),
                      ("linear_acceleration", "GetLinearAcceleration")):
        try:
            out[key] = getattr(ms, meth)(float(time), component)
        except Exception:
            out[key] = None
    return out


def set_motion_frame_rate(asm, fps=30):
    """设运动算例帧率。"""
    mgr = motion_manager(asm)
    props = None
    for meth in ("GetMotionStudyProperties", "MotionStudyProperties"):
        try:
            props = getattr(mgr, meth)
            props = props() if callable(props) else props
            break
        except Exception:
            continue
    if props is None:
        raise RuntimeError("取不到 IMotionStudyProperties")
    return bool(props.SetFrameRate(int(fps)))


def save_motion_avi(ms, path, fps=30, width=1280, height=720):
    """导出运动算例为 AVI（需 IMotionStudyManager.CreateAVIParameter）。

    ★ 依赖编解码器；失败常见原因是路径无权限或 AVI 参数非法。
    """
    param = None
    try:
        asm = wrap(ms, "IMotionStudy")
        mgr = motion_manager(asm)
        param = mgr.CreateAVIParameter()
        for attr, val in (("FramesPerSecond", int(fps)),
                          ("ImageWidth", int(width)),
                          ("ImageHeight", int(height))):
            try:
                setattr(param, attr, val)
            except Exception:
                pass
    except Exception:
        pass
    rc = ms.SaveToAVI(str(path), param)
    sz = os.path.getsize(path) if os.path.exists(path) else 0
    if not rc or sz <= 0:
        raise RuntimeError("SaveToAVI 失败 rc=%s size=%d" % (rc, sz))
    return sz


def set_color(m, rgb, config_opt=1, finish=None):
    """设置零件/装配体显示颜色。

    rgb : (r, g, b)，每个 0.0~1.0
    config_opt : 0=指定配置 1=全部配置 2=当前配置 3=除当前外全部
    finish : 可选 (Ambient, Diffuse, Specular, Shininess, Transparency, Emission)
             默认 (0.2, 0.8, 0.5, 0.3, 0.0, 0.0)

    ★★ 三个坑（本机 SW2022 实测）：
      1) `SetMaterialPropertyValues` 在 **IModelDocExtension** 上是 **3 参**
         (Material_values, Config_opt, Config_names)，不是 1 参。
      2) 材质数组必须是 **9 元素**：R,G,B,Ambient,Diffuse,Specular,Shininess,Transparency,Emission。
         只传 3 个 → 报 "类型不匹配 (-2147352571)"。
      3) 必须用 `VARIANT(VT_ARRAY|VT_R8, [...])` 包装，传裸 list 也会报类型不匹配。
      返回值是 void（None），**不能用返回值判成败**，要用 get_color() 回读。
    """
    r, g, b = [max(0.0, min(1.0, float(c))) for c in rgb]
    rest = list(finish) if finish else [0.2, 0.8, 0.5, 0.3, 0.0, 0.0]
    if len(rest) != 6:
        raise ValueError("finish 必须是 6 个数")
    vals = [r, g, b] + [float(x) for x in rest]
    arr = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, vals)
    ext = wrap(m.Extension, "IModelDocExtension")
    try:
        ext.SetMaterialPropertyValues(arr, int(config_opt), None)
    except Exception as e:
        raise RuntimeError("set_color 失败（数组须 9 元素 + VARIANT R8）: %s" % str(e)[:100])
    got = get_color(m)
    if got is None:
        raise RuntimeError("set_color 后回读失败")
    if abs(got[0] - r) > 0.01 or abs(got[1] - g) > 0.01 or abs(got[2] - b) > 0.01:
        raise RuntimeError("颜色未生效: 期望 %s 实际 %s" % ((r, g, b), got[:3]))
    return got


def get_color(m):
    """读回材质数组前 3 项 (r,g,b)；失败返回 None。"""
    try:
        v = com_member(m, "MaterialPropertyValues")
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            return tuple(float(x) for x in v[:3])
    except Exception:
        pass
    return None


def set_display_color(m, rgb, state_name="AutoColor", entities=None):
    """设置显示颜色 —— ★ 本机 SW2022 + Python 下**不可用**，仅保留供参考。

    结论（2026-11-19 实测，已试遍所有路径）：
      - `SetMaterialPropertyValues`：写入/回读都对，但**渲染颜色不变**（无效）
      - 9 元素 double 数组直传显示状态接口 → "服务器意外情况"
      - CodeStack 官方范式（IAppearanceSetting + RGB整数）：
        前 3 步 CreateDisplayState/ApplyDisplayState 成功，
        **但 `GetDisplayStateSetting(任意值)` 一律抛 -2147417851**
      → 该接口在本机 Python IDispatch 下不可用。请改用
        `set_appearance_by_material()`（换真实材料）或接受默认灰白配色。

    如需彩色渲染图，可行替代：
      1) V.set_material(m, "ABS") 换材料带外观色（会重置自定义色）
      2) 导出后在外部工具（如 PIL）做伪彩/描边
      3) 手工在 SW 界面里设外观后出图
    """
    raise NotImplementedError(
        "GetDisplayStateSetting 在本机 SW2022+Python 下不可用（-2147417851）。"
        "请用 set_material() 换材料，或接受默认配色。详见 references/pitfalls.md N 章。")


def set_appearance_by_material(m, material="ABS"):
    """换真实材料以获得其外观色（本机唯一稳定可用的“上色”途径）。

    ★ 设材料会把之前的自定义颜色重置为白色，所以这是“颜色”的替代方案，
      顺序无关；需彩色时优先直接用材料自带外观。
    """
    return set_material(m, material)


def get_component_color(comp, config_opt=1):
    """读回组件级颜色 (r,g,b)。

    ★ 类型库实测：`IComponent2.GetMaterialPropertyValues2(Config_opt, Config_names)`
      返回 VT_VARIANT 的 9 元素 double 数组（R,G,B,Ambient,Diffuse,Specular,
      Shininess,Transparency,Emission）。只取前 3 项。
    ★ 早绑定下返回可能是 (数组,) 或裸数组，两种都兼容。
    ★ 组件未设过自定义颜色时返回 **(-1.0, -1.0, -1.0)** 哨兵值（本机实测），
      表示"继承零件外观"，不是真颜色。调用方判断"有没有设过色"要看它。
    失败返回 None。
    """
    c2 = wrap(comp, "IComponent2")
    for args in ((int(config_opt), None), (int(config_opt),), ()):
        try:
            v = c2.GetMaterialPropertyValues2(*args)
        except Exception:
            continue
        if isinstance(v, (list, tuple)) and len(v) == 1 and \
                isinstance(v[0], (list, tuple)):
            v = v[0]                       # 拆掉早绑定的外层元组
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            try:
                return tuple(float(x) for x in v[:3])
            except Exception:
                continue
    return None


def color_dev(a, b):
    """两个 RGB 的最大分量偏差（0.0~1.0）。任一为 None 返回 None。"""
    if not a or not b:
        return None
    return max(abs(float(x) - float(y)) for x, y in zip(a[:3], b[:3]))


def is_unset_color(rgb):
    """判断回读值是不是「未设色」哨兵 (-1,-1,-1)。

    ★ 本机实测：组件没设过自定义颜色时 GetMaterialPropertyValues2 返回
      (-1.0, -1.0, -1.0)，语义是"继承零件/装配默认外观"。
      拿它去和期望色比偏差恒为 1.0+，必须单独识别，否则误报"颜色未生效"。
    """
    return bool(rgb) and all(abs(float(x) + 1.0) < 1e-6 for x in rgb[:3])


def set_component_color(comp, rgb, config_opt=1, finish=None,
                        verify=True, tol=0.02, retries=2):
    """设置装配体中**组件级**颜色，设完**立刻回读比对**。

    ★ 三个坑（本机实测）：
      1) `SetMaterialPropertyValues2` 在 **IComponent2** 上，3 参
         (Material_values, Config_opt, Config_names)
      2) 数组必须 **9 元素** + `VARIANT(VT_ARRAY|VT_R8)`，裸 list 报类型不匹配
      3) 返回 None 是正常的（void），**不能用返回值判成败** —— 必须回读

    ★★ 2026-11-21 新增回读（对标 wzyn 的 verify_appearance）：
      设完立刻 `get_component_color()` 比对，任一通道偏差 > tol（默认 2%）抛异常。
      旧版设完就返回，颜色没生效（组件被覆盖/配置不匹配）也无从发现。

    verify=False 可关闭回读（批量上色时想自己聚合错误用）。
    返回回读到的 (r,g,b)。
    """
    r, g, b = [max(0.0, min(1.0, float(c))) for c in rgb]
    rest = list(finish) if finish else [1.0, 0.7, 0.0, 0.4, 0.0, 0.0]
    if len(rest) != 6:
        raise ValueError("finish 必须是 6 个数")
    vals = [r, g, b] + [float(x) for x in rest]
    arr = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, vals)
    c2 = wrap(comp, "IComponent2")
    c2.SetMaterialPropertyValues2(arr, int(config_opt), None)
    if not verify:
        return (r, g, b)
    got = None
    for _ in range(max(1, retries)):
        got = get_component_color(comp, config_opt)
        if got is not None and color_dev(got, (r, g, b)) <= tol:
            return got
        time.sleep(0.1)
    if got is None:
        raise RuntimeError("set_component_color 后回读失败（GetMaterialPropertyValues2 返回空）")
    raise RuntimeError(
        "组件颜色未生效：期望 (%.3f, %.3f, %.3f) 实得 (%.3f, %.3f, %.3f)，"
        "最大偏差 %.3f > tol %.3f"
        % (r, g, b, got[0], got[1], got[2], color_dev(got, (r, g, b)), tol))


def apply_palette(comps, palette, config_opt=1, tol=0.02, strict=True):
    """批量设色 + 批量回读（对标 wzyn 的 apply_component_palette）。

    comps   : {键: IComponent2} 或 [IComponent2, ...]
    palette : {键: (r,g,b)}；列表形式时按索引对应
    strict  : True=任一项失败抛异常；False=收集到 results 里继续

    返回 {"ok": [...], "failed": [{"key","want","got","error"}], "applied": n}
    """
    items = list(comps.items()) if isinstance(comps, dict) else \
        list(enumerate(comps))
    ok, failed = [], []
    for key, comp in items:
        want = palette.get(key) if isinstance(palette, dict) else \
            (palette[key] if isinstance(key, int) and key < len(palette) else None)
        if want is None:
            continue
        try:
            got = set_component_color(comp, want, config_opt=config_opt, tol=tol)
            ok.append({"key": key, "want": tuple(round(float(x), 3) for x in want),
                       "got": tuple(round(float(x), 3) for x in got)})
        except Exception as e:
            failed.append({"key": key,
                           "want": tuple(round(float(x), 3) for x in want),
                           "got": None, "error": str(e)[:140]})
            if strict:
                raise
    return {"ok": ok, "failed": failed, "applied": len(ok)}


def verify(m, volume=None, bbox=None, bodies=None, vol_tol=0.005, bbox_tol=0.5, tag=""):
    """三重断言：体积（材质多少）、bbox（在哪）、实体数（留了什么）。

    volume  : 期望体积 mm³，按【相对偏差】判，阈值 vol_tol（0.005 = 0.5%）
    bbox    : 期望 (xmin,ymin,zmin,xmax,ymax,zmax) mm，按【绝对偏差】判，
              阈值 bbox_tol（单位 mm，默认 0.5mm）
    bodies  : 期望实体数，精确相等
    返回 dict 结果；任一项超出阈值抛 AssertionError。

    ★ 体积是相对、bbox 是绝对 —— 这两个阈值单位不同，别混用。
    """
    rep = {"tag": tag, "checks": []}

    def ck(name, got, want, tol, rel):
        if got is None or want is None:
            rep["checks"].append((name, "SKIP", got, want))
            return
        if rel:
            dev = abs(got - want) / abs(want) if want else abs(got)
            ok = dev <= tol
        else:
            dev = abs(got - want)
            ok = dev <= tol
        rep["checks"].append(
            (name, "PASS" if ok else "FAIL", round(got, 4), round(want, 4)))
        if not ok:
            raise AssertionError(
                "%s %s: got=%s want=%s dev=%.6f (tol=%s%s)"
                % (tag, name, got, want, dev, tol, "%" if rel else "mm"))

    if volume is not None:
        ck("volume", L.vol(m), volume, vol_tol, True)
    if bbox is not None:
        bb = L.bbox6(m)
        for i in range(6):
            ck("bbox[%d]" % i, bb[i], bbox[i], bbox_tol, False)
    if bodies is not None:
        try:
            n = len(wrap(m, "IPartDoc").GetBodies2(0, False) or [])
        except Exception:
            n = -1
        ck("bodies", n, bodies, 0, False)
    for name, status, got, want in rep["checks"]:
        print("  [%s] %-14s got=%-12s want=%s" % (status, name, got, want))
    return rep


# ---------------------------------------------------------------- 能力分级
# 移植自 wzyn skill 的 capabilities.yaml 思路：
# 只有 verified 才能无人值守交付；pilot 需人工复核；其余不进正式流程。
VERIFIED = "verified"           # 本机实测过、有数值证据
PILOT = "pilot"                 # 能用但未充分验证，需人工看
REFERENCE_ONLY = "reference_only"   # 文档写了没证据
NOT_IMPLEMENTED = "not_implemented"

def _load_capabilities():
    """从 capabilities.yaml 加载能力表（单一真相源）。

    ★ 失败时抛 RuntimeError 而不是静默用空表 —— 能力表缺失必须被发现。
    pyyaml 缺失时 capabilities_loader 会用内置 mini 解析器，零第三方依赖。
    """
    import os
    try:
        import capabilities_loader as CL
        return CL.to_swlib_table()
    except Exception as e:
        raise RuntimeError("无法从 capabilities.yaml 加载能力表: %s" % e)


CAPABILITIES = _load_capabilities()


def capability(name):
    """查能力等级。未知能力按 reference_only 处理（不进正式流程）。"""
    return CAPABILITIES.get(name, (REFERENCE_ONLY, "未登记"))


def require_verified(name):
    """交付前门禁：非 verified 直接拒绝。

    ★ 2026-11-20 升级：改为抛 capability_gap.CapabilityGapError，
      携带结构化缺口（替代方案 / 探测建议 / 后续步骤），
      而不是只给一句「不行」。调用方可以 `except e: print(e.gap.to_json())`。

    兼容旧行为：CapabilityGapError 继承 RuntimeError，原来的
    `except RuntimeError` 仍然能捕获。
    """
    level, note = capability(name)
    if level == VERIFIED:
        return True
    try:
        import capability_gap as CG
        raise CG.CapabilityGapError(CG.probe_capability(name))
    except ImportError:
        raise RuntimeError("能力 %s 等级=%s（%s），不能作为无人值守交付"
                           % (name, level, note))


def capability_gap(name):
    """软查询能力缺口：verified 返回 None，否则返回 CapabilityGap。

    用法：
        gap = V.capability_gap("part.hole_wizard")
        if gap:
            print(gap.report())
    """
    try:
        import capability_gap as CG
        return CG.probe_capability(name)
    except ImportError:
        lv, note = capability(name)
        return None if lv == VERIFIED else (lv, note)


def capability_report(names=None):
    """打一张能力清单。"""
    keys = names or sorted(CAPABILITIES)
    by = {}
    for k in keys:
        lv, note = capability(k)
        by.setdefault(lv, []).append((k, note))
    for lv in (VERIFIED, PILOT, REFERENCE_ONLY, NOT_IMPLEMENTED):
        if lv not in by:
            continue
        print("\n[%s] %d 项" % (lv, len(by[lv])))
        for k, note in by[lv]:
            print("  %-32s %s" % (k, note))
    return by


# ---------------------------------------------------------------- 体积读取（单位坑）
def volume_mm3(m):
    """读零件/装配体积，单位 mm³。两条路径自动回退。

    ★ 单位坑实录（2026-11-18 实测）：
      - `IMassProperty.Volume`（经 Extension.CreateMassProperty）→ 已是 mm³
      - `IBody2.GetMassProperties(1.0)[3]` → 是 **m³**，必须 ×1e9
      两者都对，但混用会差 1e9 倍。本函数封装掉这个差异。

    ★ 另一坑：`GetBodies2` 在 **IPartDoc** 上，不在 IModelDoc2 上。
    """
    # 路径1：IMassProperty（零件/装配通用，已是 mm³）
    try:
        mp = wrap(m.Extension.CreateMassProperty(), "IMassProperty")
        v = float(mp.Volume) * 1e9      # m³ -> mm³
        if v > 0:
            return v
    except Exception:
        pass
    # 路径2：逐实体累加（m³ -> mm³）
    try:
        total = 0.0
        for b in (wrap(m, "IPartDoc").GetBodies2(0, False) or []):
            mp = wrap(b, "IBody2").GetMassProperties(1.0)
            if mp:
                total += float(mp[3])
        return total * 1e9
    except Exception:
        return 0.0


def volume_check(m, expect_mm3, tol=0.005, tag=""):
    """体积校验：实测 vs 解析，相对偏差 < tol。返回 (ok, 实测, 偏差%)。"""
    got = volume_mm3(m)
    dev = 100.0 * (got - expect_mm3) / expect_mm3 if expect_mm3 else 0.0
    ok = abs(dev) <= tol * 100
    print("  [%s] %-16s got=%12.3f  theory=%12.3f  dev=%+.4f%%"
          % ("PASS" if ok else "FAIL", tag or "volume", got, expect_mm3, dev))
    return ok, got, dev


# ---------------------------------------------------------------- 装配辅助
def comps(asm):
    """{实例名: IComponent2}。装配脚本里天天要用，收进库避免多处重复。

    ★ 接口归属：`GetComponents` 在 **IAssemblyDoc** 上，不在 IModelDoc2。
      传进来若是 IModelDoc2，先转接口。
    """
    try:
        ad = wrap(asm, "IAssemblyDoc")
        raw = ad.GetComponents(False)
    except Exception:
        raw = None
    out = {}
    for c in (raw or []):
        comp = wrap(c, "IComponent2")
        try:
            out[comp.Name2] = comp
        except Exception:
            try:
                out[comp.Name] = comp
            except Exception:
                continue
    return out


def snapshot(asm):
    """记录所有组件 bbox，用于配合/摆位前后比对。

    ★ 固定组件的 GetBox 偶发返回 None（PITFALLS E10），这里多参数兜底。
    """
    snap = {}
    for nm, comp in comps(asm).items():
        box = None
        for args in ((0, False), (0, True), (1, False)):
            try:
                box = [round(v * 1000.0, 2) for v in comp.GetBox(*args)]
                break
            except Exception:
                continue
        snap[nm] = box
    return snap


def diff_snapshot(before, after):
    """返回 [(组件名, bbox 最大偏差mm)]。dev >= 1mm 说明被移动。"""
    out = []
    for nm, b in before.items():
        a = after.get(nm)
        if b is None or a is None:
            out.append((nm, 999.0))
        else:
            out.append((nm, max(abs(a[i] - b[i]) for i in range(6))))
    return out


def count_mates(m):
    """MateGroup 下配合特征数 —— 判断配合是否真建成的唯一可信判据（PITFALLS E5★）。

    ★ 接口归属：`FirstFeature` 在 **IModelDoc2** 上，不在 IAssemblyDoc。
      传 IAssemblyDoc 进来会报 AttributeError。
    """
    n = 0
    doc = wrap(m, "IModelDoc2")
    f = doc.FirstFeature()
    while f is not None:
        fe = wrap(f, "IFeature")
        if fe.GetTypeName2() == "MateGroup":
            s = fe.GetFirstSubFeature()
            while s is not None:
                n += 1
                s = wrap(s, "IFeature").GetNextSubFeature()
        f = fe.GetNextFeature()
    return n


# ---------------------------------------------------------------- 装配几何（2026-11-20 实战新增）
# 这一组函数在 14 零件同步带模组实战里手写了 5 遍，全部本机实测。

def faces_of(comp):
    """枚举组件所有面，返回统一结构，供 plane_at / cyl_of 挑面。

    返回 [{f: IFace2, plane: bool, cyl: bool,
           box: [x0,y0,z0,x1,y1,z1] mm, dims: [dx,dy,dz] mm,
           n: (nx,ny,nz) 或 None, area: mm²}]

    ★★ IFace2.GetBox() 与 ISurface.PlaneParams 的法向都是【零件局部坐标】，
       不是装配世界坐标。P6 导轨世界 x=−200..300，面 box 却显示 −250..250。
       所以挑面要用零件自身尺寸给值。
    """
    out = []
    try:
        b = wrap(comp, "IComponent2").GetBody()
        if b is None:
            return out
        for f in wrap(b, "IBody2").GetFaces():
            ff = wrap(f, "IFace2")
            surf = wrap(ff.GetSurface(), "ISurface")
            is_plane = bool(com_member(surf, "IsPlane"))
            is_cyl = bool(com_member(surf, "IsCylinder"))
            box = [round(x * 1000.0, 2) for x in ff.GetBox()]
            dims = [round(box[3] - box[0], 2),
                    round(box[4] - box[1], 2),
                    round(box[5] - box[2], 2)]
            n = None
            if is_plane:
                try:
                    n = tuple(round(x, 3) for x in surf.PlaneParams[0:3])
                except Exception:
                    pass
            try:
                area = ff.GetArea() * 1e6
            except Exception:
                area = 0.0
            out.append(dict(f=ff, plane=is_plane, cyl=is_cyl,
                            box=box, dims=dims, n=n, area=area))
    except Exception:
        pass
    return out


_AXIS_I = {"x": 0, "y": 1, "z": 2}


def plane_at(faces, axis, sign, coord, tol=0.6):
    """按【局部坐标】挑平面：沿 axis 的坐标 ≈ coord，法向沿 ±axis。

    faces 来自 faces_of()。返回 IFace2 或 None。
    用法：plane_at(F["rail"], "y", 1.0, 0.0)   # 导轨底面（局部 y=0，法向 +Y）

    ★★ 2026-11-20 实测：`ISurface.PlaneParams` 的法向【不保证朝外】。
      同一零件的顶面报 +Y、底面也报 +Y（朝内），换个零件又反过来。
      所以：
        - sign 传 1.0 / -1.0 → 按该符号匹配（要求你知道朝向）
        - **sign 传 None → 只校验法向沿该轴，不校验符号**（最稳，推荐）
      e2e 套件实测：立板底面必须用 sign=None 才挑得到。
    """
    ai = _AXIS_I[axis]
    for d in faces:
        if not d["plane"] or d["n"] is None:
            continue
        if abs(abs(d["n"][ai]) - 1.0) > 0.02:
            continue                      # 法向不沿该轴
        if sign is not None and abs(d["n"][ai] - sign) > 0.02:
            continue
        if coord is None:
            return d["f"]
        if (abs(d["box"][ai] - coord) < tol
                or abs(d["box"][ai + 3] - coord) < tol):
            return d["f"]
    return None


def cyl_of(faces, dia, tol=1.0, min_area=200.0):
    """挑圆柱面：恰好两维 ≈ 直径，取面积最大的（排除减重孔）。

    ★ 只判"至少两维接近"会误选减重孔 —— P4 带轮 Ø6 减重孔与 Ø12 轴孔
      在 dims 上都含 15（轴向），实测会挑错。改为必须【恰好两维】匹配，
      再按面积排序：轴孔贯通面积恒大于减重孔。
    """
    cands = []
    for d in faces:
        if not d["cyl"]:
            continue
        if sum(1 for q in d["dims"] if abs(q - dia) < tol) != 2:
            continue
        if d["area"] < min_area:
            continue
        cands.append(d)
    if not cands:
        return None
    cands.sort(key=lambda d: -d["area"])
    return cands[0]["f"]


def all_boxes(asm):
    """{实例名: [x0,y0,z0,x1,y1,z1] mm} —— 漂移检测的基础。

    ★ 与 snapshot() 等价，但 snapshot 有 GetBox 3 级回退（固定组件偶发返回 None）。
      这里直接复用 snapshot，避免两套实现漂移。返回结构一致。
    """
    return snapshot(asm)


def max_drift(before, after):
    """两组 all_boxes 的最大坐标差（mm）。配合后用它判零件有没有被拉走。

    ★ 2026-11-20 实测：不固定组件时加一个平面重合配合，
      p4_pulley 会从 Y −33.9..33.9 漂到 12.7..101.3，总漂移 135 mm。
      固定后漂移恒 0.00 mm。漂移 >1mm 即判该配合与摆放位置不一致。

    ★ 与 diff_snapshot() 的分工：diff_snapshot 返回逐组件明细列表，
      max_drift 只返回全局最大值（判阈值用）。
    """
    worst = 0.0
    for nm, d in diff_snapshot(before, after):
        if d is not None and d > worst:
            worst = d
    return worst


def place_to(sw, comp, R, target_min, iters=5, tol=0.05):
    """迭代把组件 bbox 最小角移到 target_min（mm），返回最终 bbox。

    ★★ V.place() 设的是【组件原点】，不是 bbox 中心。非对称零件（焊件框、
       电机板）按目标坐标手算必偏。这里迭代 3~5 次收敛到 0.05mm。

    ★★ 2026-11-22 实测严重缺陷（GR-90 行星减速器实战，见 pitfalls U13）：
       **本函数对齐的是 bbox 角，不是几何中心。对【要旋转的件】会摆错。**
       非正方形轮廓绕自身原点转 θ 后，bbox 尺寸会变大（实测行星轮
       43.5×43.5 → 转 120° 后 59.5×59.5，+37%），
       此时仍按「未旋转的 bbox 角偏移」摆放，真实圆心必然偏离目标点
       （实测偏 4.54mm / 10.71mm，导致行星轮与太阳轮穿入 10.33mm）。
       而本函数**照样返回 dev≤0.05mm** —— 它只保证 bbox 角到位。

    → **旋转件、同心件、齿轮请用 `place_center_to()`**；
      本函数只适合「不旋转 + 靠角定位」的板件/型材。
    """
    place(sw, comp, R, (0, 0, 0))
    t = [0.0, 0.0, 0.0]
    for _ in range(iters):
        b = [x * 1000.0 for x in comp.GetBox(0, False)]
        d = [target_min[i] - b[i] for i in range(3)]
        if max(abs(x) for x in d) < tol:
            break
        t = [t[i] + d[i] for i in range(3)]
        place(sw, comp, R, t)
    return [round(x * 1000.0, 2) for x in comp.GetBox(0, False)]


def bbox_after_rot(sw, comp, R):
    """把组件摆到原点、套上旋转 R 后，读【旋转后】的真实 bbox（mm）。

    ★ 旋转非正方形轮廓会改变 bbox 尺寸。任何「按 bbox 推算中心」的逻辑
      都必须先拿这个值，不能用未旋转时的尺寸。
    返回 [x0,y0,z0,x1,y1,z1]（mm）。
    """
    place(sw, comp, R, (0, 0, 0))
    return [round(x * 1000.0, 4) for x in comp.GetBox(0, False)]


def place_center_to(sw, comp, R, target_center, iters=6, tol=0.02,
                    check_center=None):
    """把组件【旋转后的 bbox 中心】移到 target_center（mm）。

    ★★ 这是旋转件/同心件的正确摆位函数（2026-11-22 GR-90 实战新增）。
       `place_to` 对齐 bbox 角，转过的非正方形件会偏；本函数对齐中心，
       对「齿轮、法兰、销轴、任何要按圆心定位的件」都成立。

    参数：
      R              3×3 旋转矩阵（rot_z / rot_x / rot_y）
      target_center  目标 bbox 中心 (x, y, z) mm
      check_center   可选回调 fn(comp) -> (cx, cy, cz) mm，
                     ★ 用于「bbox 中心 ≠ 真实圆心」的件（如非对称齿形）：
                     给了它就用真实圆心做迭代判据，比 bbox 中心更准。

    返回 dict：
      bbox      最终 bbox（mm）
      center    最终 bbox 中心（mm）
      real      若给了 check_center，真实圆心（mm），否则 None
      dev_mm    最终与目标的偏差（用 real 优先，否则 center）
      converged dev_mm <= tol
    """
    place(sw, comp, R, (0, 0, 0))
    t = [0.0, 0.0, 0.0]
    b = c = None
    real = None
    dev = None
    for _ in range(iters):
        b = [x * 1000.0 for x in comp.GetBox(0, False)]
        c = [(b[0] + b[3]) / 2.0, (b[1] + b[4]) / 2.0, (b[2] + b[5]) / 2.0]
        real = None
        if check_center is not None:
            try:
                real = [float(x) for x in check_center(comp)]
            except Exception:
                real = None
        ref = real if real is not None else c
        d = [target_center[i] - ref[i] for i in range(3)]
        dev = max(abs(x) for x in d)
        if dev < tol:
            break
        t = [t[i] + d[i] for i in range(3)]
        place(sw, comp, R, t)
    b = [round(x * 1000.0, 4) for x in comp.GetBox(0, False)]
    c = [(b[0] + b[3]) / 2.0, (b[1] + b[4]) / 2.0, (b[2] + b[5]) / 2.0]
    if check_center is not None:
        try:
            real = [round(float(x), 4) for x in check_center(comp)]
        except Exception:
            real = None
    ref = real if real is not None else c
    dev = max(abs(target_center[i] - ref[i]) for i in range(3))
    return {"bbox": [round(x, 2) for x in b],
            "center": [round(x, 3) for x in c],
            "real_center": ([round(x, 3) for x in real]
                            if real is not None else None),
            "dev_mm": round(dev, 4),
            "converged": dev <= tol}


def axial_center_of(comp, dia, tol=1.0):
    """用组件内某个圆柱面（默认内孔）反推【真实回转轴心】的世界坐标（mm）。

    ★ 用途：摆位后验证「圆心真的到位」，而不是只看 bbox。
      bbox 中心对非对称齿形不等于圆心（齿顶/齿根沿周向不均匀）。
      本函数取该圆柱面的 IFace2.GetBox 中心 + 组件变换，得到轴心。

    参数 dia = 圆柱直径（mm）。找不到返回 None。
    """
    faces = faces_of(comp)
    f = cyl_of(faces, dia, tol=tol, min_area=1.0)
    if f is None:
        return None
    try:
        fb = [x * 1000.0 for x in wrap(f, "IFace2").GetBox()]
    except Exception:
        return None
    # 面 box 是【零件局部】坐标；叠加组件变换得到世界坐标
    local = ((fb[0] + fb[3]) / 2.0, (fb[1] + fb[4]) / 2.0, (fb[2] + fb[5]) / 2.0)
    try:
        arr = list(wrap(comp, "IComponent2").Transform2.ArrayData)
    except Exception:
        return [round(x, 4) for x in local]
    R = arr[0:9]
    T = [x * 1000.0 for x in arr[9:12]]
    wx = R[0] * local[0] + R[1] * local[1] + R[2] * local[2] + T[0]
    wy = R[3] * local[0] + R[4] * local[1] + R[5] * local[2] + T[1]
    wz = R[6] * local[0] + R[7] * local[1] + R[8] * local[2] + T[2]
    return [round(wx, 4), round(wy, 4), round(wz, 4)]


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((1, 0, 0), (0, c, -s), (0, s, c))


def rot_y(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, 0, s), (0, 1, 0), (-s, 0, c))


def fix_all(asm):
    """固定装配体全部组件，返回成功个数。

    ★★ 2026-11-20 实测：不固定组件时，单个平面重合配合会让零件在其余
       5 个自由度上乱跑，整个装配散架。必须【先全部 Fix 再加配合】。
       FixComponent 在 IAssemblyDoc 上，需先选中；判据用 IsFixed 属性
       （FixComponent 恒返回 None）。
    """
    doc = wrap(asm, "IModelDoc2")
    ia = wrap(asm, "IAssemblyDoc")
    n = 0
    for k, c in comps(asm).items():
        try:
            if not com_member(c, "IsFixed"):
                doc.ClearSelection2(True)
                wrap(c, "IComponent2").Select2(False, 0)
                ia.FixComponent()
                doc.ClearSelection2(True)
            if com_member(c, "IsFixed"):
                n += 1
        except Exception:
            continue
    return n


def last_refplane_name(m):
    """取特征树里最后一个 RefPlane 的名称。

    ★ offset_plane() 返回的是 CDispatch（特征对象），不能直接当基准面名用。
      建完偏移面后调本函数取名字，再传给 new_sketch。
    """
    last = None
    for nm, tp in feature_tree(m):
        if tp == "RefPlane":
            last = nm
    return last


def offset_plane_named(m, base_plane, distance_mm, name=None):
    """建偏移基准面并返回其【名称】（offset_plane 的实用封装）。

    用法：pname = V.offset_plane_named(m, "Top Plane", 60)
          V.L.new_sketch(m, pname)
    """
    offset_plane(m, base_plane, distance_mm, name=name)
    nm = name or last_refplane_name(m)
    if not nm:
        raise RuntimeError("offset_plane_named: 建了偏移面但取不到名称")
    return nm


def drawing_view(drawing, model_path, view="*等轴测", x=0.15, y=0.13, options=0):
    """在工程图插入模型视图，返回 IView 或 None。

    ★★ 三条铁律（2026-11-20 实测）：
      1. 本机 SW 是【中文界面】，视图名必须中文：
         *等轴测 / *前视 / *上视 / *右视
         英文 *Isometric / *Front 一律返回 False。
      2. 方法在 **IDrawingDoc** 上，不在 IModelDoc2
         （IModelDoc2 上 getattr 直接 AttributeError）。
      3. 装配体必须先在会话里打开并激活，否则返回 False。
    """
    idd = wrap(drawing, "IDrawingDoc")
    try:
        r = idd.CreateDrawViewFromModelView3(model_path, view, x, y, options)
    except Exception:
        return None
    if r in (None, False):
        return None
    try:
        return wrap(r, "IView")
    except Exception:
        return r


def view_name_of(view):
    """读 IView 的名称（"工程图视图1"），用于验证视图真插进去了。"""
    try:
        return com_member(view, "GetName2")
    except Exception:
        return None


# ---------------------------------------------------------------- 草图增强
def sketch_closed_ok(m, expect=1):
    """退出当前草图前检查闭合轮廓数。"""
    sk = wrap(m.SketchManager, "ISketchManager").ActiveSketch
    if sk is None:
        return None
    try:
        return wrap(sk, "ISketch").GetSketchContourCount()
    except Exception:
        return None


def addtoDB(m):
    """上下文管理器：建模期间关闭 1mm 吸附（精密草图必须）。"""
    return _AddToDBCtx(m)


class _AddToDBCtx(object):
    def __init__(self, m):
        self.m = m
        self.skm = wrap(m.SketchManager, "ISketchManager")
        self.old = None

    def __enter__(self):
        try:
            self.old = (self.skm.AddToDB, self.skm.DisplayWhenAdded)
            self.skm.AddToDB = True
            self.skm.DisplayWhenAdded = False
        except Exception:
            self.old = None
        return self.skm

    def __exit__(self, *a):
        if self.old:
            try:
                self.skm.AddToDB, self.skm.DisplayWhenAdded = self.old
            except Exception:
                pass
        return False


def circle(skm, cx, cy, r):
    """★ 正确传半径：CreateCircle 第二组是圆周上一点，不是半径。"""
    return skm.CreateCircle(cx * MM, cy * MM, 0.0, (cx + r) * MM, cy * MM, 0.0)


def spline(skm, pts, rot_deg=0.0, mirror=False, tol=1e-5):
    """画样条，自动去重连续重合点（<tol），避免退化被静默丢弃。"""
    clean = []
    for p in pts:
        if not clean or math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > tol:
            clean.append(p)
    if len(clean) < 2:
        raise ValueError("样条点数不足")
    c, s = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    pd = []
    seq = list(reversed(clean)) if mirror else clean
    for q in seq:
        y = -q[1] if mirror else q[1]
        pd.extend([(q[0] * c - y * s) * MM, (q[0] * s + y * c) * MM, 0.0])
    import win32com.client as w
    arr = w.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, pd)
    seg = skm.CreateSpline(arr)
    if seg is None:
        raise RuntimeError("CreateSpline 返回 None（点距过小或轮廓非法）")
    return seg


# ---------------------------------------------------------------- 受控视图与截图
def zoom_to_box(d, p1, p2):
    """按两个世界坐标角点框选缩放（米）。装配体留白多时最有效。

    ★ 本机实测：`ViewZoomtofit2` / `ViewZoomAtPoint2` 对装配体时常不理想，
      `ViewZoomTo2(x1,y1,z1, x2,y2,z2)` 能精确框住目标区域。
    """
    d.ViewZoomTo2(float(p1[0]), float(p1[1]), float(p1[2]),
                  float(p2[0]), float(p2[1]), float(p2[2]))


def zoom_to_model(sw, m, margin=0.15):
    """按模型 bbox 自动框选，留 margin 边距。装配体出图推荐用它。"""
    bb = L.bbox6(m)                       # mm
    span = max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])
    pad = span * margin
    p1 = ((bb[0] - pad) * MM, (bb[1] - pad) * MM, (bb[2] - pad) * MM)
    p2 = ((bb[3] + pad) * MM, (bb[4] + pad) * MM, (bb[5] + pad) * MM)
    d = wrap(sw.ActiveDoc, "IModelDoc2")
    zoom_to_box(d, p1, p2)
    d.GraphicsRedraw2()
    return p1, p2


def set_view(sw, m, which="iso", zoom_factor=1.0):
    """切视图 —— 必须传视图 ID，名字在中文版会变且 -1 不切换。

    ★ GetTitle 在 IModelDoc2 上；传进来若是 IAssemblyDoc/IPartDoc 会报错。
    ★ 装配体想要"占满画面"，用 `fit=True` 走 zoom_to_model() 框选，
      单纯 ViewZoomtofit2 对装配体常留大片空白。
    """
    if which not in VIEW:
        raise ValueError("未知视图 %r，可选: %s" % (which, ", ".join(VIEW)))
    title = com_member(wrap(m, "IModelDoc2"), "GetTitle")
    sw.ActivateDoc3(title, True, 0, 0)          # ★ 导的是活动文档
    d = wrap(sw.ActiveDoc, "IModelDoc2")
    d.ShowNamedView2(VIEW_NAME[which], VIEW[which])
    d.ViewZoomtofit2()
    d.ClearSelection2(True)
    d.GraphicsRedraw2()
    return d


def save_png(sw, m, path, which="iso", w=1400, h=900, min_bytes=1000,
             fit=False, margin=0.15, retries=3):
    """切视图→截图→回读大小；0 字节或过小视为失败。

    ★ 本机实测：`SaveAs3` 不支持指定像素尺寸，w/h 无法生效（保留仅作记录）。
    ★ 装配体出图传 `fit=True`：用 bbox 框选（margin 控制留白），
      比 ViewZoomtofit2 更紧凑，能显著提升画面占比。
    ★★ 冷启/刚建完特征后第一次 `SaveAs3` 会返回 rc=1 + 0 字节（2026-11-21 实测）：
       SW 视口还没画完，重切视图 + `GraphicsRedraw2` + 短暂等待后重试即可成功。
       旧版直接抛异常，于是 review/four_views 把"冷启抖动"误判成"截图失败"。
       现在内置 retries 次重试，全部失败才抛。
    """
    d = set_view(sw, m, which)
    if fit:
        try:
            zoom_to_model(sw, m, margin=margin)
        except Exception:
            pass
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    rc, sz = None, 0
    for attempt in range(max(1, int(retries))):
        rc = d.SaveAs3(path, 0, 0)
        sz = os.path.getsize(path) if os.path.exists(path) else 0
        if sz >= min_bytes:
            break
        # 抖动重试：重切视图 + 重绘 + 让 SW 喘口气
        try:
            d.ShowNamedView2(VIEW_NAME[which], VIEW[which])
            d.ViewZoomtofit2()
            d.GraphicsRedraw2()
        except Exception:
            pass
        time.sleep(0.6 * (attempt + 1))
    if sz < min_bytes:
        raise RuntimeError("截图失败/空白: %s rc=%s size=%d（已重试 %d 次）"
                           % (path, rc, sz, retries))
    return dict(path=path, rc=rc, size=sz, view=which, fit=fit,
                size_note="SaveAs3 不支持自定义分辨率，w/h 未生效")


def set_image_size(m, width=1600, height=1000):
    """设置工程图/模型导出图片的目标分辨率。

    ★ 通过 IModelDocExtension.SetUserPreferenceInteger 设置
      swUserPreferenceIntegerValue_e.swExportPngWidth / swExportPngHeight。
      SaveAs3 之后再导出 PNG 就会用这个尺寸。
    """
    ext = wrap(m.Extension, "IModelDocExtension")
    ok = 0
    # swUserPreferenceIntegerValue_e: swExportPngWidth=?, 用名字探测
    for name, val in (("swExportPngWidth", int(width)),
                      ("swExportPngHeight", int(height))):
        try:
            import win32com.client.gencache as _g
            sc = _g.EnsureModule("{4687F359-55D0-4CD3-B6CF-2EB42C11F989}", 0, 30, 0)
            pid = getattr(sc, name, None)
            if pid is None:
                continue
            ext.SetUserPreferenceInteger(pid, 0, val)
            ok += 1
        except Exception:
            continue
    return ok


def four_views(sw, m, outdir, prefix, min_bytes=1000):
    """导出四视图并回读，用于目视自审查。"""
    os.makedirs(outdir, exist_ok=True)
    out = []
    for name in ("iso", "front", "top", "right"):
        p = os.path.join(outdir, "%s_%s.png" % (prefix, name))
        try:
            out.append(save_png(sw, m, p, name, min_bytes=min_bytes))
        except Exception as e:
            out.append(dict(path=p, error=str(e)[:100]))
    return out


# ---------------------------------------------------------------- 保存/关闭
def open_doc(sw, path, doc_type=1, activate=True):
    """打开文档并返回 IModelDoc2。

    ★ `OpenDoc6` 早绑定返回**元组** `(retval, errors, warnings)`，
      直接当对象用会报 `'tuple' object has no attribute ...`。
    doc_type: 1=零件 2=装配 3=工程图
    """
    r = sw.OpenDoc6(str(path), int(doc_type), 0, "", 0, 0)
    if isinstance(r, (tuple, list)):
        doc = r[0] if r else None
        errs = r[1] if len(r) > 1 else 0
        warns = r[2] if len(r) > 2 else 0
        if errs:
            raise RuntimeError("OpenDoc6 失败 errors=%s warnings=%s: %s"
                               % (errs, warns, path))
    else:
        doc = r
    if doc is None:
        raise RuntimeError("OpenDoc6 返回 None: %s" % path)
    m = wrap(doc, "IModelDoc2")
    if activate:
        sw.ActivateDoc3(com_member(m, "GetTitle"), True, 0, 0)
        m = wrap(sw.ActiveDoc, "IModelDoc2")
    return m


def save_checked(m, path, rebuild=True):
    """保存并回读；返回 (rc, size)，0字节抛异常。

    ★ SaveAs2 在 IModelDoc2 上；传进来的是 IAssemblyDoc/IPartDoc 时先转接口。

    ★★ 2026-11-22 实测（GR-90 实战，pitfalls U15）：
       不重建就存盘，文件里留下的是**上次显示的细分几何**，不是最终 B-rep。
       重开时先读到旧状态：内齿圈打开即读 25413.481 mm³，
       ForceRebuild3 后变 25427.356 mm³（差 13.876 mm³）。
       含样条轮廓的件（齿轮）都有此现象，齿数越多越明显。
       → 默认 rebuild=True，存盘前先 ForceRebuild3(False) 固化几何。
       ★ 想复现"未重建"现象时传 rebuild=False。
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = wrap(m, "IModelDoc2")
    if rebuild:
        try:
            doc.ForceRebuild3(False)
        except Exception:
            pass
    rc = doc.SaveAs2(path, 0, False, True)
    sz = os.path.getsize(path) if os.path.exists(path) else 0
    if sz <= 0:
        raise RuntimeError("保存失败/0字节: %s rc=%s" % (path, rc))
    return rc, sz


def close_doc(sw, m, force=False):
    """窗口纪律：存完即关，避免残留窗占满 8 个名额。"""
    try:
        title = m.GetTitle()
        sw.CloseDoc(title)
    except Exception:
        pass


def new_part(sw, close_all=True):
    return L.new_part(sw, close_all)


def new_asm(sw, close_all=True):
    return L.new_asm(sw, close_all)


# ---------------------------------------------------------------- 装配增强
def add_component(sw, asm, asm_title, path):
    """AddComponent5 前置：先 OpenDoc6；插入后重新激活装配体。"""
    sw.OpenDoc6(path, 1, 0, "", 0, 0)
    c = asm.AddComponent5(path, 0, "", False, "", 0, 0, 0)
    sw.ActivateDoc3(asm_title, True, 0, 0)
    if c is None:
        raise RuntimeError("AddComponent5 返回 None: %s（零件未载入？）" % path)
    return c


def place(sw, comp, R, t_mm):
    """ComposeTransform：R 是旋转矩阵行向量，t 是绝对平移(mm)。"""
    import win32com.client as w
    mu = wrap(sw.GetMathUtility(), "IMathUtility")
    V8 = lambda l: w.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(x) for x in l])
    vec = lambda l: wrap(mu.CreateVector(V8(l)), "IMathVector")
    mt = mu.ComposeTransform(vec(R[0]), vec(R[1]), vec(R[2]),
                             vec([x * MM for x in t_mm]), 1.0)
    wrap(comp, "IComponent2").Transform2 = mt


def rot_z(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def check_interference(asm):
    """干涉检查。返回 (None, None) = 无干涉。

    ★★ 2026-11-20 实测纠正：`ToolsCheckInterference2` 在 **IAssemblyDoc** 上。
      旧版直接 `asm.ToolsCheckInterference2(...)` —— 传进来的若是 IModelDoc2
      就必抛 −2147352571「类型不匹配」，被 except 包成 ("ERROR", ...)，
      于是**误判成"有干涉"**。现在强制先 wrap 成 IAssemblyDoc。
    """
    try:
        ia = wrap(asm, "IAssemblyDoc")
    except Exception:
        ia = asm
    last = None
    for num in (1, 0):
        try:
            return ia.ToolsCheckInterference2(num, None, False)
        except Exception as e:
            last = e
    return ("ERROR", str(last)[:80] if last else "ToolsCheckInterference2 unavailable")


def interference_verdict(asm, unfix_first=False):
    """干涉检查的**语义明确版** —— 区分「无干涉」/「有干涉」/「无法判定」。

    ★★ 2026-11-22 实测（GR-90 实战，见 pitfalls U14）：
       `ToolsCheckInterference2` 对**全固定组件**的装配体，
       即使存在 10.33mm 的实体穿入，**8 组参数全部返回 `(None, None)`**。
       也就是说 `(None, None)` 同时表示：
         ① 真的没干涉
         ② 检查根本没跑（全固定时常见）
       两者不可区分。旧 `interference_ok()` 把 `(None,None)` 直接判成
       `True`，于是**判据彻底失效**，把穿入 10mm 的装配判成"干涉干净"。

    → 本函数把 `(None, None)` 判为 **unknown（BLOCKED）**，不是 pass。
      按 verify_gate 原则：「无法验证 ≠ 通过」。

    参数：
      unfix_first=True 时先临时解除固定再查，查完恢复（提高检出率）。
                      ★ 但这会改动装配状态，调用方需知道。

    返回 dict：
      status     "clean" / "interference" / "unknown"
      ok         True 仅当 status == "clean"（unknown 不算 ok）
      raw        SW 原始返回值
      attempts   尝试过的参数组合与结果
      note       人可读说明
    """
    ia = wrap(asm, "IAssemblyDoc")
    doc = wrap(asm, "IModelDoc2")
    attempts = []

    def _try():
        for num in (1, 0):
            for use_sel in (False, True):
                try:
                    r = ia.ToolsCheckInterference2(num, None, use_sel)
                except Exception as e:
                    attempts.append({"num": num, "use_sel": use_sel,
                                     "exc": str(e)[:60]})
                    continue
                attempts.append({"num": num, "use_sel": use_sel,
                                 "ret": repr(r)[:80]})
                if r not in (None, (None, None)) and r != (None, None):
                    return r
        return None

    restored = []
    if unfix_first:
        try:
            for nm, c in comps(asm).items():
                if com_member(c, "IsFixed"):
                    doc.ClearSelection2(True)
                    wrap(c, "IComponent2").Select2(False, 0)
                    ia.UnfixComponent()
                    doc.ClearSelection2(True)
                    restored.append(c)
        except Exception:
            pass

    raw = _try()

    if unfix_first and restored:
        for c in restored:
            try:
                doc.ClearSelection2(True)
                wrap(c, "IComponent2").Select2(False, 0)
                ia.FixComponent()
                doc.ClearSelection2(True)
            except Exception:
                pass

    if raw is None:
        return {"status": "unknown", "ok": False, "raw": "(None, None)",
                "attempts": attempts,
                "note": "SW 未返回可用结果：无法区分「无干涉」与「检查未执行」。"
                        "按「无法验证≠通过」判 unknown。"
                        "建议用几何解析判据交叉验证（中心距/穿入深度）。"}
    if isinstance(raw, tuple) and len(raw) >= 2 and raw[0] is None and raw[1] is None:
        return {"status": "unknown", "ok": False, "raw": repr(raw)[:80],
                "attempts": attempts,
                "note": "SW 返回 (None, None)：语义歧义，判 unknown 不判 pass"}
    if isinstance(raw, tuple) and any(x is not None for x in raw):
        return {"status": "interference", "ok": False, "raw": repr(raw)[:120],
                "attempts": attempts,
                "note": "SW 报告存在干涉体，需逐一排查"}
    return {"status": "unknown", "ok": False, "raw": repr(raw)[:120],
            "attempts": attempts,
            "note": "未识别的返回形态，判 unknown"}


def interference_ok(asm):
    """干涉检查的布尔版：返回 (ok, raw)。

    ★★ 2026-11-22 语义修正（GR-90 实战，pitfalls U14）：
       旧版 `return (r == (None, None)), r` —— 把「SW 没返回结果」
       当成了「无干涉」。实测全固定装配体即使穿入 10.33mm，
       `ToolsCheckInterference2` 仍返回 `(None, None)`，旧判据直接放行。

       现在：**只有明确拿到「无干涉体」的证据才判 True**；
       `(None, None)` 一律判 False（无法验证 ≠ 通过）。

    用法：
        ok, raw = V.interference_ok(asm)
        assert ok, "无法确认无干涉: %s" % (raw,)
        # 需要区分 clean/unknown 用 V.interference_verdict(asm)["status"]
    """
    v = interference_verdict(asm)
    return (v["status"] == "clean"), (v["status"], v["raw"])


# ---------------------------------------------------------------- 底层透传
boss = L.boss
cut = L.cut
fillet = L.fillet
chamfer = L.chamfer
vol = L.vol
bbox6 = L.bbox6
bbox = L.bbox
