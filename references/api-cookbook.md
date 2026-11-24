# API 速查手册（从 SKILL.md 下沉，内容不删）

> 这是 SKILL.md 的**细节层**。主文档只保留"遇到问题读这里"的路由，
> 完整代码块、参数注释和踩坑说明放在本文件。
> 本机 SW2022 SP5 实测。V.xxx 指 scripts/swlib_v2.py 的封装。
## 核心封装（scripts/swlib_v2.py，106 函数）

> 这里只列**每天都在用**的。旋转/放样/扫描/抽壳/圆角/阵列/镜像/拔模/曲面/焊件/
> 运动/齿轮等专业手法 → 见 `references/features.md`（含完整参数与 mark 表）。

**连接与自适应**
```python
V.connect(version=2022, wait_ready=30)    # 两级 fallback + 往返探测
V.com_member(obj, "RevisionNumber")       # 属性/方法自适应（不是方法！）
V.open_doc(sw, path, doc_type=1)          # ★ OpenDoc6 返回元组，内部已处理
V.com_call_arity(fm, "FeatureXxx", args)  # 跨 SW 版本参数个数漂移自适应
```

**草图**（★ 全部内置避坑）
```python
with V.addtoDB(m) as skm:                 # AddToDB=True，关 1mm 吸附
    V.L.new_sketch(m, "Front Plane")
    V.circle(skm, cx, cy, r)              # 传圆周上一点，不是半径
    V.spline(skm, pts)                    # 自动去重 tol=1e-5
    sk = V.last_sketch_name(m)            # 遍历特征树，不用 FeatureByPositionReverse
    skm.InsertSketch(True)
```

**特征**（★ 自动保证草图已选中）
```python
V.extrude_checked(m, sk, depth, start_mm=0)   # 5 级回退选草图，失败抛异常
V.cut_checked(m, sk, depth_mm=None)           # None=双向贯穿；reverse=True 走负法向
V.select_sketch(m, name, verbose=True)        # 单独调用时看走了哪条路径
```

**校核**
```python
V.volume_mm3(m)                       # 单位已统一（IMassProperty vs IBody2 差 1e9）
V.volume_check(m, theory, tag="x")    # 返回 (ok, 实测, 偏差%)
V.verify(m, volume=..., bbox=..., bodies=1)   # 体积按相对%、bbox 按绝对 mm
V.body_counts(m)                      # (实体数, 曲面体数)
V.capability_report()                 # 60 verified + 11 pilot + 5 not_implemented
V.require_verified("part.extrude")    # 交付门禁；非 verified 抛 CapabilityGapError

# 能力不够时：拿结构化缺口，不是裸异常
import capability_gap as CG
gap = CG.probe_capability("part.hole_wizard")
if gap:
    print(gap.report())        # 类型/替代方案/探测建议/5 步后续
    print(gap.to_json())       # 给 Agent 消费
CG.require_any(["part.hole_wizard", "part.cut_through"])   # → "part.cut_through"
CG.com_has(sw, "IFeatureManager", "HoleWizard5")           # True（写最小实现前先探）

# 过程留痕：每步记入参/产出/证据，失败自动定位
import exec_trace as ET
tr = ET.Trace("belt_actuator")
tr.env(sw_version="30.5.0")
with tr.step("P1.extrude", depth=600) as s:
    V.extrude_checked(m, sk, 600)
    s.output("volume", V.volume_mm3(m))
    s.ev("dev_pct", 0.000)
tr.save(r"out\trace.json")
tr.require_ok()                            # 有 fail 就抛（带 fail_at 文件行号）
```

**装配**（★ 2026-11-20 新增 12 个封装 + 修 1 个，全部本机实测）
```python
comps = V.comps(asm)                  # {实例名: IComponent2}
V.count_mates(m)                      # 配合是否真建成（唯一可信判据）
V.set_component_color(comp, (0.92, 0.72, 0.30))  # ★ 设完自动回读，偏差>2% 抛异常
V.get_component_color(comp)               # 读回 (r,g,b)；未设色返回 (-1,-1,-1) 哨兵
V.is_unset_color(rgb)                     # 判哨兵：True 表示"还没设过色，继承零件外观"
V.color_dev(got, want)                    # 最大分量偏差 0.0~1.0（回读判据就用它）
V.apply_palette(comps, {k1: (0.92, 0.72, 0.30), k2: (0.20, 0.55, 0.85)})
                                          # 批量上色 + 批量回读 → {"applied": 2, "failed": []}

# 摆位：place_to 对齐 bbox【角】，旋转的非正方形件必偏（pitfalls V1）；
#       旋转件/同心件一律改成 place_center_to，按旋转后的 bbox 中心对齐。
V.place(sw, comp, V.rot_z(90), (x, y, z))       # 直接设组件原点
V.place_to(sw, comp, R, (xmin, ymin, zmin))     # 只适合不旋转的板件/型材
res = V.place_center_to(sw, comp, R, (cx, cy, cz),
                        check_center=lambda c: V.axial_center_of(c, bore_d))
assert res["converged"] and res["dev_mm"] < 0.05
V.rot_x(90) / V.rot_y(90) / V.rot_z(90)         # 三个旋转矩阵构造器

# 回转件的真实圆心：用内孔/外圆圆柱面反推（bbox 中心 ≠ 圆心）
c = V.axial_center_of(comp, 8.1)       # [x,y,z] mm，世界坐标
assert abs(math.hypot(c[0], c[1]) - expect_r) < 0.05

# 固定：★ 不要先 fix_all 再加配合（全固定后配合不参与求解，pitfalls V3）
# 只固定基准件：
doc = V.wrap(asm, "IModelDoc2")
doc.ClearSelection2(True)
V.wrap(comps["housing"], "IComponent2").Select2(False, 0)
V.wrap(asm, "IAssemblyDoc").FixComponent()
doc.ClearSelection2(True)
# ... 加配合，求解器自由定位 ...
V.fix_all(asm)                        # 验收通过后再全部固定

# 挑面：★ IFace2.GetBox() 是【零件局部坐标】，不是世界坐标
F = V.faces_of(comp)                  # [{f, plane, cyl, box, dims, n, area}]
V.plane_at(F, "y", None, 10.0)        # 局部 y=10 的平面（sign=None 不校验朝向）
V.cyl_of(F, 12.0)                     # 恰好两维=Ø12 且面积最大（排除减重孔）

# 漂移检测：★ max_drift=0 在 fix_all 先行时恒为 0，证明不了装配正确（pitfalls V4）
box0 = V.all_boxes(asm)
V.max_drift(box0, V.all_boxes(asm))   # 只证明"配合没引起移动"
V.diff_snapshot(box0, V.all_boxes(asm))   # 逐组件明细 [(名, 偏差)]

# 干涉：三态，unknown 判 BLOCKED（pitfalls V2）
v = V.interference_verdict(asm)       # clean / interference / unknown
assert v["status"] == "clean", v["note"]
ok, raw = V.interference_ok(asm)      # 兼容旧签名；unknown → False
```

★★ **两条判据边界**（2026-11-22 GR-90 审查实证，pitfalls V2/V4）：
- **`(None, None)` 不是"无干涉"**：全固定装配体即使穿入 10.33mm，
  `ToolsCheckInterference2` 8 组参数仍全返回 `(None, None)`。
  它同时表示"真没干涉"和"检查没执行"。现判 `unknown`（BLOCKED）——
  **无法验证 ≠ 通过**。要区分三态用 `interference_verdict()`。
- **`max_drift == 0` 证明不了装配正确**：若流程是「摆位 → `fix_all` → 加配合」，
  加配合前全固定，配合不可能移动任何件 → **漂移恒为 0**，与装配对错无关。
  它只证明"配合没引起移动"。真正的装配验证要用
  `axial_center_of` / `Transform2` 平移量测**圆心是否到位**。

**by-ref 出参**（★ 2026-11-21 新增，`swlib`）
```python
import swlib as L

# ① 构造器（VT_BYREF | 基础类型），取回值用 .value
err = L.byref_int(0); dev = L.byref_double(0.0); flag = L.byref_bool(False)

# ② 调用带出参的 API —— 必须降级动态绑定才拿得到真实值
ret, outs = L.call_byref(m, "SaveAs4", [path, 0, 0], ["i4", "i4"])
# 合法路径 → (True, [0, 0])
# 非法路径 → (False, [1, 0])      错误码 1 = 目录不存在
# 非法扩展 → (False, [256, 0])

# ③ 早绑定只能拿返回元组里的出参（入参传普通 0）
ret, outs = L.call_byref(m, "SaveAs4", [path, 0, 0], ["i4", "i4"], dynamic=False)
r, split = L.split_out(ret, 2)     # (True, 0, 0) → (True, [0, 0])
```
★★ **早绑定 `_ApplyTypes_` 不接受 VARIANT 形式的 by-ref**：
`d.SaveAs4(p, 0, 0, VARIANT(VT_BYREF|VT_I4, 0), ...)` → `TypeError: int() argument ... not 'VARIANT'`。
因为 `(16387, 3)` 被当 int 解包后传给 `InvokeTypes`。要真实出参必须走动态绑定。

**出图（归档可选，默认不要调用；只有用户明确要 PDF/工程图/截图时才启用）**
```python
V.set_view(sw, m, "iso")              # 视图 ID：iso=7 front=1 top=5 right=4
V.save_png(sw, m, path, "iso")        # 激活→切视图→截图→回读大小
V.four_views(sw, m, outdir, prefix)   # 四视图
```
★ `SaveAs3` 不支持自定义分辨率，`w/h` 参数无效。
★ **装配体出图**（2026-11-20 修正：原来写 `ViewZoomin()` 是错的）：
```python
d = V.wrap(m, "IModelDoc2")
for v in ("iso", "front", "top", "right"):
    d.ShowNamedView2(V.VIEW_NAME[v], V.VIEW[v])
    d.ViewZoomtofit2()
    d.ViewZoomout()                          # ★ 退一步留边（Zoomin 会放大过头被裁）
    d.GraphicsRedraw2(); d.SaveAs3(path, 0, 0)
```
★ **工程图插视图**：本机 SW 是中文界面，视图名必须中文 + 宿主是 IDrawingDoc：
```python
v = V.drawing_view(dw, model_path, "*等轴测", 0.15, 0.13)   # 不是 *Isometric
V.view_name_of(v)                                          # "工程图视图1"
```
★ 四视图是否真的不同**比 md5 哈希，不比文件大小**。

**交付门禁**（`scripts/verify_gate.py` + `scripts/artifact_freshness.py`）
```python
from verify_gate import Gate, PASS, WARN, FAIL, BLOCKED
import artifact_freshness as F

# ① 几何门禁
g = Gate("part")
g.check("volume", ok, "体积偏差 0.01%")
g.check("visual_review", None, "未目视复核", level=BLOCKED)  # 无法验证≠PASS

# ② 交付新鲜度门禁（★ 2026-11-20 新增，防旧文件冒充本轮成果）
base = F.scan(out_dir); base.save(r".baseline.json")   # 建模前
# ... 建模/导出 ...
rep = F.diff(base, out_dir, paths=deliverables)        # 必须显式传清单
gf = F.to_gate(rep, "freshness")

# ③ 合并：几何 PASS + 新鲜度 FAIL → 整体 FAIL
v = F.merge_gates([g, gf], "delivery").verdict()
# BLOCKED>FAIL>WARN>PASS；空结果一律 BLOCKED
```
★ 新鲜度只证明「文件新增或内容变了」，**不证明几何正确** —— 必须和几何断言、
目视复核一起用。详见 `references/delivery-freshness.md`。

**结果自审查**（`scripts/review.py`，★ 2026-11-21 新增）
```python
import review as R

# ① 全链路：出四视图 + 像素判据 + 交付文件检查 + 写报告
rep, path = R.run_review(m, r"out\review", basename="bracket",
                         expected_outputs=[part, pdf])
print(rep["status"])            # pass / warn / fail
print(rep["issues"])            # ["views_distinct: 4 张图 / 1 个不同 md5", ...]

# ② 只审已有截图（不开 SW，任何机器都能跑）
rv = R.review_images({"iso": p1, "front": p2, "top": p3, "right": p4})

# ③ 转成门禁，和几何断言合并
g = R.to_gate(rep)              # → verify_gate.Gate
```
| 判据 | 拦什么 |
|---|---|
| `views_distinct` | 四视图同一张（视口锁死） |
| `content_*` ≥1% | 空白图 / 模型不在视口 |
| `color_*` ≥6 | 单色块，看不出结构（WARN） |
| `views_not_clipped` | 零件被裁切（WARN） |
| `file_*` >1KB | 交付文件 0 字节/缺失 |
★ **预览非空白 ≠ 模型正确** —— 比例/方位/部件缺失/重叠悬空仍须人眼。

**网格导入**（`scripts/mesh_import.py`，★ 2026-11-21 新增）
```python
import mesh_import as MI

# ① 导入前必须预检法线：0 法线 STL 会让 SW 弹模态框把 COM 永久挂死
MI.precheck_stl(r"D:\ref\part.stl")        # {"ok": False, "reason": "...弹模态框卡死"}

# ② 导入（LoadFile4，第 3 参必须是空 IDispatch，不能 None）
rep = MI.import_mesh(sw, r"D:\ref\part.stl",
                     expect_bbox_mm=(0, 0, 0, 20, 30, 40))
print(MI.render(rep))                      # bbox 偏差 / 网格体数 / 诚实声明

# ③ 法线坏了自动修（按体心朝外纠正绕向）
fixed, stats = MI.repair_stl_normals(src)
```
★ 网格件**不是参数化实体**：无草图/特征树，不能拉伸切除、不能加配合当机构件。
★ `GetBodies2()` 看不到网格体（返回 None），必须走 `MeshBodyFeature.GetSpecificFeature2`。

**工程图交付**（`scripts/drawing_delivery.py`，★ 2026-11-21 新增）
```python
import drawing_delivery as DD

rep = DD.create_drawing(sw, r"out\bracket.SLDPRT", r"out\bracket.pdf")
print(DD.render(rep))
# 幅面: 279.4 × 215.9 mm（11.00 × 8.50 in），比例 1.0:1.0
# 视图: 期望 3 / 实得 3  (工程图视图1,工程图视图2,工程图视图3)
# 标注: 前 2 → 后 3（增 1）
# [OK  ] views / views_named / pdf_bytes / sheet_size / annotations
# [MAN ] dim_chain / hole_table / title_block / no_overlap  ← 人判，绝不默认 pass

# 单独读幅面（走 ISheet.GetSize 两个 by-ref 出参）
V.sheet_properties(dw)   # {'width_mm': 279.4, 'height_mm': 215.9, 'paper_size': 0, ...}
```
★ 底线 5 条见 `references/drawing-standards.md`。机器能判视图数/PDF/幅面/标注增量，
**尺寸链、孔表、标题栏字段、压线** 一律 `manual`。
★ `types` 必须含 **32768**（`V.ANN_WORKING`）；同一图纸只能插一次标注，
比较参数须每次新建图纸。孔表 51 组合全 None，维持 not_implemented。

**API 查证**（`scripts/api_lookup.py`，★ 2026-11-21 新增 —— 铁律 1 的执行手段）
```bash
python scripts/api_lookup.py IFeatureManager HoleWizard5   # 27 参 + 每参 VT + by-ref
python scripts/api_lookup.py HoleWizard5                   # 自动定位接口
python scripts/api_lookup.py --find HoleWizard             # 模糊搜
python scripts/api_lookup.py --task "画一个渐开线齿轮"      # 中文任务 → 候选能力/方法
python scripts/api_lookup.py IDrawingDoc InsertModelAnnotations3 --json
```
★ 它直接证明了两条旧文档的错：`InsertModelAnnotations3` 是 **6 参**不是 4 参；
`LoadFile4` 在 **ISldWorks** 上不是 IModelDoc2。

**专业手法**（详见 `references/features.md`）
```python
V.revolve_checked(m, sk, 360)             # ★ 轮廓「X=半径、Y=轴线」，中心线沿 Y
V.loft_checked(m, [s1, s2])               # 平行截面，逐张 Select2(mark=1)
V.sweep_checked(m, prof, path)            # ★ 轮廓圆心必须精确落在路径起点
V.shell_checked(m, 2.0, faces=[face])     # 测量必须在选面【之前】做
V.fillet_checked(m, 5.0, edges=edges)     # ★ 多条边 append 逐次递增
V.chamfer_checked(m, 3.0, edges=edges)
V.circular_pattern_checked(m, feat, axis, 8)  # ★ 轴垂直于孔心连线；母特征传 ICE 名
V.mirror_checked(m, feat, "Right Plane")      # ★ 特征 mark=1 面 mark=2
V.draft_extrude(m, 40, 40, 20, 5)         # 棱柱拔模等效，dev -0.07%
V.draft_cone(m, 20, 15, 20)               # 圆台拔模，dev 0.0000%
V.sheetmetal_base_flange(m, sk, 2.0, radius_mm=2.0, length_mm=40)
V.surface_extrude(m, sk, 50)              # → (0实体, 1曲面)
V.surface_planar(m, sk) / V.surface_revolve(m, sk, 360)
V.structural_weldment(m, sk, prof, config="Al LS ANGLE SQR END 1 x 0.75 x 0.125")
V.weldment_cut_list(m)                    # 读 CutListFolder（存盘重开后才非空）
V.hole_wizard(...)                        # PILOT：本机不可用，用普通切除替代
V.motion_manager(asm) / V.create_motion_study(asm) / V.calculate_motion(ms)
```

**齿轮整圈齿廓**（`scripts/gearring.py`）
```python
import gearmath as G
from gearring import full_ring, check_ring
p = G.GearParams(mn=2.5, z=24, bw=20, bore=10)   # ★ 参数名是 mn/bw，不是 m
g = G.GearGeom(p)
ring = full_ring(p, g, list(G.flank(p, g).pts))   # 整圈闭合点列（2761 点）
assert check_ring(ring, g)["r_ok"]
# ★ 中心孔必须和齿廓画在同一草图，一次拉伸 → solid=1
```

---