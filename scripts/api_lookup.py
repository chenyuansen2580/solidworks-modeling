# -*- coding: utf-8 -*-
"""API 查证工具 —— 不猜 API 的执行手段。

对标 wzyn20051216/solidworks-automation-skill（2230★）的 `scripts/sw_api_lookup.py`。
它查官方在线文档 + 本地类型库；本机只有 SW2022，**离线优先**：
类型库 `%TEMP%\\gen_py\\3.12\\83A33D31-...x0x30x0.py` 才是唯一可信来源。

## 为什么需要它

铁律 1 是「不猜 API」。但 `references/api-map.md` 只有 60 来条手写记录，
遇到表里没有的方法（例如 `InsertFeatureDraft2` 到底几参、`SSize` 是 BSTR 还是
VARIANT）就只能翻 6MB 类型库或凭记忆猜 —— 猜错的代价是特征静默返回 None。

本工具把类型库变成可查询的：

    python api_lookup.py IFeatureManager HoleWizard5
    python api_lookup.py HoleWizard5            # 自动定位接口
    python api_lookup.py --find HoleWizard      # 模糊找方法
    python api_lookup.py --task "画一个渐开线齿轮"
    python api_lookup.py IComponent2 GetMaterialPropertyValues2 --json

## 输出内容

- 完整参数名列表 + 参数个数
- 每个参数的 VT 类型（int/double/BSTR/IDispatch/BOOL…）、是否 by-ref（out 参数）
- 返回值类型（含 void）
- 所属 coclass / 是否返回 IDispatch
- 旁证：capabilities.yaml 里有没有同名能力、api-map.md 有没有登记

## 参数

    --version 2022     只做记录，本机类型库就是 2022 SP5（不做跨版本推断）
    --offline          只查本地（默认就是离线；保留开关给将来接在线文档）
    --no-parallel      关闭备用查询（api-map.md 兜底），保留参数以兼容对标工具
    --json             机器可读输出，给 Agent 消费

## 退出码

    0 = 查到；1 = 查不到（不编造签名）
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 本机 SW2022 SP5 的类型库（早绑定缓存）
TLB_GUID = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"
TLB_CACHE_NAME = "83A33D31-27C5-11CE-BFD4-00400513BB57x0x30x0.py"

# COM VARIANT 类型 → 可读名（VT 值见 wtypes / OA 文档）
VT_NAMES = {
    0: "VT_EMPTY", 1: "VT_NULL", 2: "VT_I2", 3: "VT_I4", 4: "VT_R4", 5: "VT_R8",
    6: "VT_CY", 7: "VT_DATE", 8: "VT_BSTR", 9: "VT_DISPATCH", 10: "VT_ERROR",
    11: "VT_BOOL", 12: "VT_VARIANT", 13: "VT_UNKNOWN", 14: "VT_DECIMAL",
    16: "VT_I1", 17: "VT_UI1", 18: "VT_UI2", 19: "VT_UI4", 20: "VT_I8",
    21: "VT_UI8", 22: "VT_INT", 23: "VT_UINT", 24: "VT_VOID", 25: "VT_HRESULT",
    26: "VT_PTR", 27: "VT_SAFEARRAY", 28: "VT_CARRAY", 29: "VT_USERDEFINED",
    30: "VT_LPSTR", 31: "VT_LPWSTR", 36: "VT_RECORD", 37: "VT_INT_PTR",
    38: "VT_UINT_PTR", 63: "VT_FILETIME", 64: "VT_BLOB",
}
# 参数方向位（InvokeTypes 里 (VT | FLAG) 的 FLAG）
FLAG_BYREF = 0x4000        # VT_BYREF
FLAG_OUT = 0x0008          # PARAMFLAG_FOUT 的高位在 16384 区间：16387 = 0x4003
# 实测 InvokeTypes 参数元组：(VT, 方向码)
#   1 = 输入       2 = 可选(缺省 Missing)   3 = 输出(by-ref)
DIR_IN, DIR_OPT, DIR_OUT = 1, 2, 3


class TlbError(RuntimeError):
    pass


def tlb_path():
    """定位本机类型库 .py。先找 %TEMP%\\gen_py\\3.12，再找 gen_py 下任意版本目录。"""
    cands = []
    tmp = os.environ.get("TEMP") or os.environ.get("TMP") or ""
    if tmp:
        base = os.path.join(tmp, "gen_py")
        if os.path.isdir(base):
            for d in sorted(os.listdir(base)):
                p = os.path.join(base, d, TLB_CACHE_NAME)
                if os.path.exists(p):
                    cands.append(p)
    for p in cands:
        return p
    raise TlbError(
        "找不到类型库缓存 %s。先跑一次 connect() 让 gencache 生成：\n"
        "  import swlib_v2 as V; V.connect(version=2022)" % TLB_CACHE_NAME)


class TypeLib(object):
    """把 gen_py 生成的类型库模块当文本索引，按类切块。"""

    def __init__(self, path=None):
        self.path = path or tlb_path()
        with open(self.path, encoding="latin-1") as f:
            self.text = f.read()
        self.classes = self._index_classes()

    def _index_classes(self):
        """{类名: (起始偏移, 结束偏移)}"""
        marks = [(m.start(), m.group(1)) for m in
                 re.finditer(r"^class (\w+)\(DispatchBaseClass\):", self.text, re.M)]
        out = {}
        for i, (pos, name) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(self.text)
            out[name] = (pos, end)
        return out

    def class_names(self):
        return sorted(self.classes)

    def class_body(self, cls):
        if cls not in self.classes:
            raise TlbError("类型库里没有接口 %s" % cls)
        a, b = self.classes[cls]
        return self.text[a:b]

    # ---------------------------------------------------------------- 方法定位
    def find_methods(self, needle, limit=60):
        """模糊找方法：返回 [(接口, 方法名, 参数个数)]。"""
        needle_l = needle.lower()
        out = []
        for cls, (a, b) in self.classes.items():
            body = self.text[a:b]
            for m in re.finditer(r"^\tdef (\w+)\(", body, re.M):
                name = m.group(1)
                if needle_l in name.lower():
                    out.append((cls, name, self._arity(body, m.start())))
                    if len(out) >= limit:
                        return out
        return out

    def locate(self, method, iface=None):
        """定位方法所在接口。给了 iface 就只查它（查不到报错，不跨接口猜）。"""
        if iface:
            body = self.class_body(iface)
            if re.search(r"^\tdef %s\(" % re.escape(method), body, re.M):
                return iface
            raise TlbError("%s 上没有方法 %s（用 --find %s 找它在哪个接口）"
                           % (iface, method, method))
        hits = []
        for cls, (a, b) in self.classes.items():
            body = self.text[a:b]
            if re.search(r"^\tdef %s\(" % re.escape(method), body, re.M):
                hits.append(cls)
        if not hits:
            raise TlbError("类型库里找不到方法 %s（拼写？用 --find 模糊搜）" % method)
        # 优先常用宿主接口
        pref = ["IModelDoc2", "IFeatureManager", "ISldWorks", "IModelDocExtension",
                "IAssemblyDoc", "IPartDoc", "IDrawingDoc", "ISketchManager",
                "IComponent2", "IFeature", "ISketch", "IFace2", "IBody2"]
        for p in pref:
            if p in hits:
                return p
        return hits[0]

    def all_owners(self, method):
        out = []
        for cls, (a, b) in self.classes.items():
            if re.search(r"^\tdef %s\(" % re.escape(method), self.text[a:b], re.M):
                out.append(cls)
        return out

    # ---------------------------------------------------------------- 签名解析
    @staticmethod
    def _raw_params(seg):
        """从 def 段落里取原始参数串（gen_py 里第一个参数恒为 self）。"""
        m = re.search(r"^\tdef \w+\((.*?)\):", seg, re.S | re.M)
        if not m:
            return None
        return m.group(1).replace("\n", " ").replace("\t", " ")

    @staticmethod
    def _param_names(raw):
        """参数名列表。★ gen_py 生成的 def 带 self，必须剔除，否则永远多 1 参。"""
        names = []
        for p in (raw or "").split(","):
            p = p.strip()
            if not p:
                continue
            names.append(p.split("=")[0].strip())
        if names and names[0] == "self":
            names = names[1:]
        return names

    @classmethod
    def _arity(cls, body, start):
        raw = cls._raw_params(body[start:start + 6000])
        if raw is None:
            return None
        return len(cls._param_names(raw))

    def signature(self, method, iface=None):
        """解析一个方法的完整签名。

        返回 dict：
            interface / method / doc / arity / params[{index,name,vt,vt_name,direction,byref}]
            returns{vt, vt_name, is_dispatch} / invoke_id / returns_iface
            implemented_as  "InvokeTypes" | "_ApplyTypes_"
        """
        cls = self.locate(method, iface)
        body = self.class_body(cls)
        m = re.search(r"^\tdef %s\((.*?)\):\n(.*?)(?=^\tdef |\Z)" % re.escape(method),
                      body, re.S | re.M)
        if not m:
            raise TlbError("解析 %s.%s 失败" % (cls, method))
        params_raw = m.group(1).replace("\n", " ").replace("\t", " ")
        body_raw = m.group(2)

        # 参数名：去掉默认值；★ 剔除 gen_py 自动生成的 self
        names = self._param_names(params_raw)

        doc = ""
        dm = re.search(r"^\t\t'(.+?)'$", body_raw, re.M)
        if dm:
            doc = dm.group(1)

        vt_list, ret_vt, invoke_id, impl, returns_iface = [], None, None, "", None

        im = re.search(r"InvokeTypes\((\d+),\s*LCID,\s*1,\s*\((\d+),\s*(\d+)\)", body_raw)
        am = re.search(r"_ApplyTypes_\((\d+),\s*1,\s*\((\d+),\s*(\d+)\)", body_raw)
        src = None
        if im:
            invoke_id = int(im.group(1))
            ret_vt = int(im.group(2))
            impl = "InvokeTypes"
            src = body_raw[im.end():]
        elif am:
            invoke_id = int(am.group(1))
            ret_vt = int(am.group(2))
            impl = "_ApplyTypes_"
            src = body_raw[am.end():]

        # 参数 VT 元组：紧跟返回值后的 ((vt,dir),(vt,dir),...)
        tm = re.search(r"\(\s*\(((?:\s*\(\s*\d+\s*,\s*\d+\s*\)\s*,?)+)\)", src or "")
        if tm:
            for vt, direction in re.findall(r"\(\s*(\d+)\s*,\s*(\d+)\s*\)", tm.group(1)):
                vt_list.append((int(vt), int(direction)))
        if not vt_list:
            # 零参方法：InvokeTypes(..., (),)
            for vt, direction in re.findall(r"\((\d+),\s*(\d+)\)", src or ""):
                vt_list.append((int(vt), int(direction)))
            if len(vt_list) <= 1:
                vt_list = []

        # 返回 IDispatch 时的目标接口（Dispatch(ret, '名', '{IID}')）
        rm = re.search(r"Dispatch\(ret,\s*'[^']*',\s*'(\{[\w\-]+\})'\)", body_raw)
        if rm:
            returns_iface = self._iid_to_iface(rm.group(1))

        params = []
        for i, nm in enumerate(names):
            vt, direction = vt_list[i] if i < len(vt_list) else (0, DIR_IN)
            byref_flag = bool(vt & 0x4000)          # VT_BYREF 位
            arr_flag = bool(vt & 0x2000)            # VT_ARRAY 位
            base_vt = vt & 0x3FFF
            vn = VT_NAMES.get(base_vt, "VT_%d" % base_vt)
            if arr_flag:
                vn = "SAFEARRAY(%s)" % vn
            if byref_flag:
                vn += "*"
            params.append({
                "index": i,
                "name": nm,
                "vt": vt,
                "vt_base": base_vt,
                "vt_name": vn,
                "direction": {DIR_IN: "in", DIR_OPT: "in(optional)",
                              DIR_OUT: "out(byref)"}.get(direction, str(direction)),
                "byref": direction == DIR_OUT or byref_flag,
            })

        return {
            "interface": cls,
            "method": method,
            "doc": doc,
            "arity": len(names),
            "params": params,
            "returns": {
                "vt": ret_vt,
                "vt_name": VT_NAMES.get(ret_vt, "VT_%s" % ret_vt),
                "is_dispatch": ret_vt == 9,
            },
            "returns_iface": returns_iface,
            "invoke_id": invoke_id,
            "implemented_as": impl,
            "typelib": os.path.basename(self.path),
        }


    def _iid_to_iface(self, iid):
        """IID → 接口名（类型库里 CLSID = IID('{...}') 可反查）。"""
        pat = r"class (\w+)\(DispatchBaseClass\):.*?CLSID = IID\('" + re.escape(iid) + r"'\)"
        m = re.search(pat, self.text, re.S)
        return m.group(1) if m else iid


# ---------------------------------------------------------------- 旁证：能力表 / api-map
# 中文任务词 → 能力 id / 类型库方法关键词。中文没有空格，纯分词拿不到，靠这张表兜。
TASK_ALIASES = {
    "齿轮": ["gear.involute", "gear.full_ring", "InsertProtrusionBlend"],
    "渐开线": ["gear.involute", "InsertProtrusionBlend"],
    "齿廓": ["gear.involute", "CreateSpline"],
    "拉伸": ["part.extrude", "FeatureExtrusion3"],
    "凸台": ["part.extrude", "FeatureExtrusion3"],
    "切除": ["part.cut_through", "part.cut_blind", "FeatureCut4"],
    "打孔": ["part.cut_through", "HoleWizard"],
    "孔": ["part.cut_blind", "HoleWizard"],
    "孔向导": ["part.hole_wizard", "HoleWizard5"],
    "旋转": ["part.revolve", "FeatureRevolve2"],
    "放样": ["part.loft", "InsertProtrusionBlend2"],
    "扫描": ["part.sweep", "InsertProtrusionSwept4"],
    "抽壳": ["part.shell", "InsertFeatureShell"],
    "圆角": ["part.fillet", "FeatureFillet"],
    "倒角": ["part.chamfer", "InsertFeatureChamfer"],
    "拔模": ["part.draft_equiv", "InsertFeatureDraft2"],
    "阵列": ["pattern.circular", "FeatureCircularPattern5"],
    "镜像": ["part.mirror", "InsertMirrorFeature2"],
    "钣金": ["part.sheetmetal_base_flange", "InsertSheetMetalBaseFlange"],
    "焊件": ["weldment.structural", "InsertStructuralWeldment5"],
    "曲面": ["surface.extrude", "surface.planar", "surface.revolve"],
    "装配": ["asm.insert", "asm.place", "asm.mate.concentric", "AddMate5"],
    "配合": ["asm.mate.concentric", "asm.mate.distance", "AddMate5"],
    "干涉": ["asm.mate.coincident", "ToolsCheckInterference2"],
    "工程图": ["drawing.create", "CreateDrawViewFromModelView3"],
    "出图": ["drawing.create", "export.png"],
    "标注": ["drawing.create", "InsertModelAnnotations3"],
    "剖视": ["drawing.section", "CreateSectionViewAt5"],
    "属性": ["props.custom", "CustomPropertyManager"],
    "材料": ["material.set", "SetMaterialPropertyName2"],
    "配置": ["config.create", "AddConfiguration3"],
    "颜色": ["appearance.component", "SetMaterialPropertyValues2"],
    "上色": ["appearance.component", "SetMaterialPropertyValues2"],
    "运动": ["motion.study", "CreateMotionStudy"],
    "导入": ["import.mesh", "LoadFile4"],
    "网格": ["import.mesh", "LoadFile4"],
    "stl": ["import.mesh", "export.stl", "LoadFile4"],
    "obj": ["import.mesh", "LoadFile4"],
    "保存": ["export.step", "SaveAs3", "SaveAs4"],
    "视图": ["export.png", "ShowNamedView2"],
    "截图": ["export.png", "SaveAs3"],
}


def _alias_hits(text):
    """中文/英文关键词 → (能力 id 列表, 方法关键词列表)。"""
    low = text.lower()
    caps, meths = [], []
    for k, vs in TASK_ALIASES.items():
        if k in low:
            for v in vs:
                (caps if "." in v else meths).append(v)
    return caps, meths


def capability_hint(task_text=""):
    """在 capabilities.yaml + api-map.md 里找关键词候选（--task 模式用）。"""
    words = [w for w in re.split(r"[\s，。、,;；:：/()（）\"'\-]+", task_text) if len(w) >= 2]
    alias_caps, _ = _alias_hits(task_text)
    out = []
    try:
        import capabilities_loader as CL
        caps = CL.capabilities()
    except Exception:
        caps = {}
    for cid, c in caps.items():
        hay = (cid + " " + str(c.get("label", "")) + " "
               + " ".join(str(x) for x in c.get("limitations", []) or []))
        score = sum(1 for w in words if w and w in hay)
        if cid in alias_caps:
            score += 5                     # 中文别名命中权重最高
        if score:
            out.append({"type": "capability", "id": cid, "score": score,
                        "level": c.get("level", ""),
                        "label": c.get("label", "")})
    map_path = os.path.join(ROOT, "references", "api-map.md")
    if os.path.exists(map_path):
        with open(map_path, encoding="utf-8") as f:
            for line in f:
                if not line.startswith("|"):
                    continue
                score = sum(1 for w in words if w and w in line)
                if score:
                    cells = [c.strip() for c in line.strip().strip("|").split("|")]
                    out.append({"type": "api-map", "score": score,
                                "cells": cells[:3]})
    out.sort(key=lambda x: -x["score"])
    return out[:12]


def task_candidates(task_text):
    """--task 模式：关键词 → 类型库方法候选（按命中排序）。"""
    hints = capability_hint(task_text)
    alias_caps, alias_meths = _alias_hits(task_text)
    keys = set(alias_meths)
    for c in alias_caps:
        keys.add(c.split(".")[-1].replace("_", ""))
    meths = []
    try:
        tl = TypeLib()
        for key in sorted(keys):
            if not key:
                continue
            meths.extend(tl.find_methods(key[:14], limit=6))
    except Exception:
        pass
    seen, uniq = set(), []
    for iface, name, n in meths:
        k = (iface, name)
        if k in seen:
            continue
        seen.add(k)
        uniq.append((iface, name, n))
    return hints, uniq


# ---------------------------------------------------------------- 渲染
def render(sig):
    lines = []
    lines.append("=" * 68)
    lines.append("%s.%s   (%d 参, %s, invoke id %s)"
                 % (sig["interface"], sig["method"], sig["arity"],
                    sig["implemented_as"], sig["invoke_id"]))
    if sig["doc"]:
        lines.append("  " + sig["doc"])
    lines.append("-" * 68)
    lines.append("  %-4s %-22s %-12s %s" % ("#", "参数名", "VT 类型", "方向"))
    for p in sig["params"]:
        lines.append("  %-4d %-22s %-12s %s"
                     % (p["index"], p["name"], p["vt_name"], p["direction"]))
    r = sig["returns"]
    ret = "%s%s" % (r["vt_name"], (" -> %s" % sig["returns_iface"])
                    if sig["returns_iface"] else "")
    lines.append("-" * 68)
    lines.append("  返回: %s%s" % (ret, "  (判 None，不判真)" if r["is_dispatch"] else ""))
    byref = [p["name"] for p in sig["params"] if p["byref"]]
    if byref:
        lines.append("  ★ by-ref 出参: %s  → 用 swlib.byref_* 构造" % ", ".join(byref))
    lines.append("=" * 68)
    return "\n".join(lines)


def _print_hints(hints):
    if not hints:
        return
    print("\n旁证（capabilities.yaml / api-map.md 命中）：")
    for h in hints:
        if h["type"] == "capability":
            print("  [cap %-10s] %-24s %s" % (h["level"], h["id"], h["label"]))
        else:
            print("  [api-map   ] %s" % " | ".join(h["cells"]))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="SolidWorks 类型库 API 查证（离线优先，不猜签名）")
    ap.add_argument("iface", nargs="?", help="接口名，如 IFeatureManager；省略则自动定位")
    ap.add_argument("method", nargs="?", help="方法名，如 HoleWizard5")
    ap.add_argument("--find", metavar="KEY", help="模糊搜方法名，列出 接口/方法/参数个数")
    ap.add_argument("--task", metavar="TEXT", help="按自然语言任务给候选能力/方法")
    ap.add_argument("--list", action="store_true", help="列出类型库里所有接口")
    ap.add_argument("--version", default="2022", help="记录用（本机只有 2022 SP5）")
    ap.add_argument("--offline", action="store_true",
                    help="只查本地类型库（默认行为，保留以兼容对标工具）")
    ap.add_argument("--no-parallel", action="store_true",
                    help="关闭 api-map.md 兜底旁证")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    a = ap.parse_args(argv)

    try:
        tl = TypeLib()
    except TlbError as e:
        print("[ERR] %s" % e)
        return 2

    # ---- --list
    if a.list:
        names = tl.class_names()
        print("类型库 %s：%d 个接口" % (os.path.basename(tl.path), len(names)))
        for i in range(0, len(names), 4):
            print("  " + "".join("%-28s" % n for n in names[i:i + 4]))
        return 0

    # ---- --find
    if a.find:
        hits = tl.find_methods(a.find)
        if not hits:
            print("没找到含 %r 的方法" % a.find)
            return 1
        print("含 %r 的方法 %d 个：" % (a.find, len(hits)))
        for iface, name, n in hits:
            print("  %-24s %-40s %s 参" % (iface, name, n))
        return 0

    # ---- --task
    if a.task:
        hints, meths = task_candidates(a.task)
        print("任务：%s" % a.task)
        print("（版本记录 %s；本机类型库 = 2022 SP5）" % a.version)
        if hints:
            print("\n候选能力 / 已登记 API：")
            for h in hints:
                if h["type"] == "capability":
                    print("  [cap %-10s] %-24s %s" % (h["level"], h["id"], h["label"]))
                else:
                    print("  [api-map   ] %s" % " | ".join(h["cells"]))
        if meths:
            print("\n类型库方法候选：")
            for iface, name, n in meths:
                print("  %-24s %-40s %s 参" % (iface, name, n))
        if not hints and not meths:
            print("\n没命中。改用 --find <关键词> 手搜类型库。")
            return 1
        print("\n下一步：python api_lookup.py %s %s" % (meths[0][0], meths[0][1])
              if meths else "\n下一步：python api_lookup.py <接口> <方法>")
        return 0

    # ---- 单方法
    if not a.method:
        ap.print_help()
        return 2

    iface, method = a.iface, a.method
    # 允许 `api_lookup.py HoleWizard5`（只给一个位置参数）
    if method is None:
        method, iface = iface, None

    try:
        sig = tl.signature(method, iface)
    except TlbError as e:
        print("[ERR] %s" % e)
        owners = tl.all_owners(method)
        if owners:
            print("       它在这几个接口上：%s" % ", ".join(owners))
        return 1

    if a.json:
        d = dict(sig)
        if not a.no_parallel:
            d["hints"] = capability_hint(method)
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0

    print(render(sig))
    if not a.no_parallel:
        _print_hints(capability_hint(method + " " + (sig["doc"] or "")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
