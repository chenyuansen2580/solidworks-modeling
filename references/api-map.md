# API 接口归属与签名速查（本机 SW2022 实测）

> 凭记忆写 COM 接口必翻车。下表全部来自 `grep "def 名" 类型库`。

## ★★ 遇到表里没有的 API：先跑查证工具，别猜

```bash
python scripts/api_lookup.py IFeatureManager HoleWizard5   # 精确签名 + 每参 VT + by-ref
python scripts/api_lookup.py HoleWizard5                   # 自动定位接口
python scripts/api_lookup.py --find HoleWizard             # 模糊搜方法名
python scripts/api_lookup.py --task "画一个渐开线齿轮"      # 中文任务 → 候选能力/方法
python scripts/api_lookup.py --list                        # 列出全部 467 个接口
python scripts/api_lookup.py IDrawingDoc InsertModelAnnotations3 --json
```

它直接读类型库 `%TEMP%\gen_py\3.12\83A33D31-...x0x30x0.py`，输出：
参数个数、每参数 **VT 类型**（I4/R8/BSTR/DISPATCH/SAFEARRAY）、**方向**（in / out(byref)）、
返回值类型、`invoke id`、返回接口名，以及 `capabilities.yaml` / 本文件的旁证命中。

**它已经抓出两条旧文档的错**（2026-11-21）：
- `InsertModelAnnotations3` 是 **6 参**（旧文档写 4 参）
- `LoadFile4` 在 **ISldWorks** 上（不是 IModelDoc2），且第 3 参是 VT_DISPATCH

## 一、接口归属（最容易搞错的）

| API | 真实宿主 | 不在 |
|---|---|---|
| `GetPartBox` / `GetBodies2` | **IPartDoc** | IModelDoc2 |
| `GetBox` | **IAssemblyDoc** / IBody2 | IModelDoc2 |
| `AddComponent5` / `AddMate3/5` / `FixComponent` / `GetComponents` | **IAssemblyDoc** | — |
| `CreateArc2` / `InsertAxis2` | **IModelDoc2** | ISketchManager |
| `CreateLine` / `CreateSpline` / `CreateCircle` / `InsertSketch` | **ISketchManager** | — |
| `GetSketchContourCount` / `GetSketchSegments` | **ISketch** | ISketchManager |
| `GetMathUtility` | **ISldWorks** | — |
| `Volume` | **IMassProperty** propget | — |
| `SetMaterialPropertyValues`（1参） | **IModelDocExtension** | IModelDoc2 |
| `SetMaterialPropertyValues2`（3参） | **IComponent2 / IFace2 / IFeature** | IModelDoc2 |
| `SetDisplayMode` | **IModelDocExtension** | — |
| `CreateMassProperty` | IModelDocExtension（动态层取不到，用 `L.vol`） | — |
| `FeatureByName` | **IPartDoc**（零件）/ IComponent2 / IAssemblyDoc | IModelDoc2 |
| `InsertFeatureShell` | **IModelDoc2** | IModelDocExtension |
| `InsertRefPlane` / `InsertMirrorFeature2` / `InsertRib` | **IFeatureManager** | — |
| `IFace2.GetBox()`（面 bbox，米） | **IFace2** | IBody2（用 GetBodyBox） |
| `ForceRebuild3` | **IModelDoc2** | — |
| `GetModeler` / `GetMathUtility` | **ISldWorks** | IModelDoc2 |
| `GetMotionStudyManager` | **IModelDocExtension** | IModelDoc2 / IAssemblyDoc |
| `AddConfiguration3` | **IModelDoc2** | IConfigurationManager（那个是 AddConfiguration） |
| `GetTitle` | **IModelDoc2** | IAssemblyDoc / IPartDoc |
| `SaveAs2` / `SaveAs3` | **IModelDoc2** | IDrawingDoc / IAssemblyDoc |
| `GetSurface().IsCylinder` | **ISurface 的「属性」** | 不是方法，`()` 调用会报 bool 不可调 |
| `LoadFile4`（网格导入） | **ISldWorks** | IModelDoc2 / IPartDoc |
| `GetViewCount` / `GetViews` / `InsertModelAnnotations3` | **IDrawingDoc** | IModelDoc2 / IView |
| `GetAnnotationCount` | **IView**（也见 IModelDocExtension） | IDrawingDoc |
| `GetMaterialPropertyValues2` / `SetMaterialPropertyValues2` | **IComponent2**（3 参） | IModelDoc2 |
| `GetBodies3` | **IComponent2** | IPartDoc（只有 GetBodies2） |
| `GetMeshBody` / `IsMeshBody` | **IBody2** | IFeature（网格体从 MeshBodyFeature.GetSpecificFeature2 取） |

### 参数签名陷阱（本机实测）

| API | 陷阱 |
|---|---|
| `IAssemblyDoc.GetBox` | 只接受 **1~2** 个位置参数；传 `(0, False)` → TypeError |
| `OpenDoc6` | 早绑定返回**元组** `(doc, errors, warnings)`，必须取 `[0]` |
| `SetMaterialPropertyValues` | **9 元素**数组 + `VARIANT(VT_ARRAY\|VT_R8)`；3 元素或裸 list → 类型不匹配 |
| `ICustomPropertyManager.Get6` | 返回 `(返回码, 值, ...)`，**值在索引 1** |
| `GetMaterialPropertyName2` | 返回 `(材料名, 库名)`，比较取 `[0]` |
| `IModelDocExtension.SetDisplayStateSpecMaterialPropertyValues` | 2 参（setting, 数组）；但 `GetDisplayStateSetting` 本机恒抛异常 → 整条路不可用 |
| `ISurface.IsCylinder` / `IsPlane` | **属性**，不是方法 |

## 二、关键签名

### FeatureExtrusion3（23 参）
```
(Sd, Flip, Dir, T1, T2, D1, D2, Dchk1, Dchk2, Ddir1, Ddir2, Dang1, Dang2,
 OffsetReverse1, OffsetReverse2, TranslateSurface1, TranslateSurface2,
 Merge, UseFeatScope, UseAutoSelect, T0, StartOffset, FlipStartOffset)
```
- **T0 是起始条件枚举**：0=草图面，3=swStartOffset
- 第 22 参才是 StartOffset 距离
- `T1=6` 两侧对称，总厚=D1

### FeatureCut4（27 参）
```
(Sd, Flip, Dir, T1, T2, D1, D2, ..., NormalCut, UseFeatScope, UseAutoSelect,
 AssemblyFeatureScope, AutoSelectComponents, PropagateFeatureToParts,
 T0, StartOffset, FlipStartOffset, OptimizeGeometry)
```
- **`Sd=True` 是单向**！T1=1 只切一半
- 双向贯穿：`Sd=False + T1=T2=1`
- `Dir` 必须 True

### FeatureFillet（7 参，不是 4 参）
```
(Options, R1, Ftyp, OverflowType, Radii, SetBackDistances, PointRadiusArray)
```
后三个传 None。`Options=195` 可用。

### InsertFeatureChamfer（8 参）
```
(Options, Type, Distance, Angle_rad, ...)
```
角度用**弧度**。

### AddMate5（15 参）
```
(MateType, Align, Flip, Distance, DistUpper, DistLower,
 GearNum, GearDen, Angle, AngleUpper, AngleLower,
 ForPositioningOnly, LockRotation, WidthMateOption, ErrorStatus)
```
- **返回元组 `(IMate2, errStatus)`**
- `errStatus=1` 是 NoError，**0 是 ErrorUknown**
- ErrorStatus 出参必须传**普通 int**，VARIANT 会炸

### FeatureCircularPattern5（14 参）
```
(Number, Spacing, FlipDirection, DName, GeometryPattern, EqualSpacing,
 VaryInstance, SyncSubAssemblies, BDir2, BSymmetric,
 Number2, Spacing2, DName2, EqualSpacing2)
```
- 轴 mark=1，被阵列特征 mark=4
- `GeometryPattern=True` 最快最稳
- ★ 第2参 Spacing 传**总角度 2π**（配 EqualSpacing=True），传 2π/n 会返回 None

### FeatureRevolve2（20 参）
```
(SingleDir, IsSolid, IsThin, IsCut, ReverseDir, BothDirUpToSameEntity,
 Dir1Type, Dir2Type, Dir1Angle, Dir2Angle, OffsetReverse1, OffsetReverse2,
 OffsetDistance1, OffsetDistance2, ThinType, ThinThickness1, ThinThickness2,
 Merge, UseFeatScope, UseAutoSelect)
```
- `Dir1Angle` **弧度**；`IsCut=True` 旋转切除；草图须含唯一中心线

### InsertProtrusionBlend2（18 参）/ InsertCutBlend（12 参）
```
Blend2(Closed, KeepTangency, ForceNonRational, TessToleranceFactor,
 StartMatchingType, EndMatchingType, StartTangentLength, EndTangentLength,
 StartTangentDir, EndTangentDir, IsThinBody, Thickness1, Thickness2, ThinType,
 Merge, UseFeatScope, UseAutoSelect, GuideCurveInfluence)
```
- 截面草图逐张 `Select2(True,1)`；参数 0/0/1.0/1.0/True/True 实测通过

### InsertProtrusionSwept4（20 参）
```
(Propagate, Alignment, TwistCtrlOption, KeepTangency, BAdvancedSmoothing,
 StartMatchingType, EndMatchingType, IsThinBody, Thickness1, Thickness2,
 ThinType, PathAlign, Merge, UseFeatScope, UseAutoSelect,
 TwistAngle, BMergeSmoothFaces, CircularProfile, CircularProfileDiameter, Direction)
```
- 轮廓 mark=1、路径 mark=4；无需 SELOBJGROUP；TwistAngle 弧度

### InsertFeatureShell（2 参，在 IModelDoc2）
```
(Thickness, Outward)   ← 返回 VT_VOID，成功也返回 None，查特征树判据
```
- 面用 `IEntity.Select4(True, SelectData)` mark=1；所有诊断在选面前做

### InsertRefPlane（6 参）/ InsertMirrorFeature2（5 参）
```
InsertRefPlane(FirstConstraint, FirstDist, SecondConstraint, SecondDist,
 ThirdConstraint, ThirdDist)   # 8=swRefPlaneDistance, 距离单位米
InsertMirrorFeature2(BMirrorBody, BGeometryPattern, BMerge, BKnit, ScopeOptions)
```

### CreateCenterLine（ISketchManager，6 参，单位米）
```
(X1, Y1, Z1, X2, Y2, Z2)   ← 注意是米！旋转轴用
```

### CreateCircle
```
(cx, cy, cz, px, py, pz)     ← 第二组是【圆周上一点】，不是半径
```
圆心偏移时必须传 `(cx+r, cy)`。

### CreateArc2（在 IModelDoc2 上）
```
(cx, cy, cz, sx, sy, sz, ex, ey, ez, direction)
```
- **弧先画，线后画**（端点只向已存在点合并）
- `Create3PointArc` 端点不合并 → 轮廓不闭合

## 三、常用枚举值

| 枚举 | 值 |
|---|---|
| `swStartConditions_e` | 0=SketchPlane, **3=StartOffset** |
| `swEndConditions_e` | 0=Blind, **1=ThroughAll**, 6=MidPlane |
| `swMateType_e` | 0=COINCIDENT, **1=CONCENTRIC**, 5=DISTANCE, **10=GEAR** |
| `swAddMateError_e` | **1=NoError**, 0=ErrorUknown, 4=IncorrectSelections |
| `swMateAlign_e` | 0=ALIGNED, 1=ANTI_ALIGNED, 2=CLOSEST |
| `swDisplayMode_e` | 0=WIREFRAME, 2=HIDDEN, 3=SHADED, **7=SHADED_EDGES** |
| 视图 ID | **iso=7, front=1, top=5, right=4**, left=6, back=2, bottom=3 |

## 四、单位约定

| API | 单位 |
|---|---|
| `GetBox` / `GetPartBox(True)` | **米** |
| `bbox6()`（库封装） | **毫米** |
| `IMassProperty.Volume` | m³（库封装 ×1e9 转 mm³） |
| `IBody2.GetMassProperties(1.0)[3]` | **m³**，必须 ×1e9 |
| `CylinderParams` | **米** |
| 所有建模 API 参数 | **米** |

## 五、查证方法

```python
import win32com.client.gencache as gencache
TLB = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"
_MOD = gencache.EnsureModule(TLB, 0, 30, 0)
print(_MOD.IFeatureManager.FeatureCut3.__doc__)
# 生成文件：%TEMP%\gen_py\3.12\83A33D31-...x0x30x0.py
# 直接 grep "def FeatureCut3" 拿完整参数名列表
```

swconst 枚举需单独生成：
```python
from win32com.client import makepy
makepy.GenerateFromTypeLibSpec(r"F:\SOLIDWORKS\swconst.tlb")
# 生成 ...\4687F359-...x0x30x0.py，含所有枚举值
```

### 外部权威查证源（GitHub，同为 SW2022 SP5.0 实测）
- `ommo-creator/solidworks-2022-rea-ai-kit`：REA 逆向，**2164 命令号 + 12127 方法页 + 889 枚举**，
  经 API 访问 `https://api.github.com/repos/ommo-creator/solidworks-2022-rea-ai-kit/contents/data/<file>`。
  - `data/commands.json`：命令号（可用 `sw.RunCommand(cmdID, 0)` 触发 GUI 命令，比拼参数稳）
  - `data/enums.json`：889 个 swconst 枚举 + 5142 成员
  - `docs/11-feature-matrix.md`：特征方法矩阵（含本机同版本的精确实测值）
  - `docs/03-pitfalls.md`：76 条坑；`docs/04-recipes.md`：R1~R29 通过配方
- `wzyn20051216/solidworks-automation-skill`（2199★）：capabilities.yaml 能力分级 + verification 四级门禁。

### 精度 / 材料 / 公差（REA kit 实测补充）
```python
# 高精度体积：GetMassProperties2(1, False) 精度 ~1e-20（比 GetMassProperties 高）
mp = body.GetMassProperties2(1, False)   # → (status, [Xc,Yc,Zc,Vol,Area,Mass,...])

# 材料密度（kg 单位，注意不是 g/cm³）
part.SetMaterialPropertyName2(config, "SolidWorks Materials.sldmat", "ABS")  # 密度 0.936
# 常见：ABS=0.936, PE=0.924 kg/...；材料属性在 MateGroup 的 MaterialDislim 子节点

# 公差：IDimension.SetToleranceType(2=双边) + SetToleranceValues(上偏差, 下偏差)
dim.SetToleranceType(2)
dim.SetToleranceValues(0.0002, -0.0001)   # 单位米；Full Name 形如 'D1@草图1@零件.SLDPRT'
```
- `FeatureFillet3` 在本机 SW2022 是 **14 参**，`Options=2`(UniformRadius) 才生效，后 7 参补 None；
  `Options=195` 是组合位掩码（Propagate1+UniformRadius2+...）。
- 配合 `AddMate5` 的 `[out] status` 即便返回 None，配合也可能已建成 → 回读 `GetMateGroup()` 确认。

## 六、零参数方法陷阱（comtypes/pywin32 共性）
`CloseDoc / InsertSketch / ClearSelection2 / ShowNamedView2 / ViewZoomtofit2` 等
在 comtypes 动态层若 `len(argtypes)==0` 会被跳过而不报错 → 表现为"调用没生效"。
pywin32 早绑定一般正常，但遇到"调用静默无效果"时优先怀疑此类，改用带占位参数或换接口。

## 七、by-ref 出参（★ 2026-11-21 实测，两条通路差异）

| API | 出参 | 早绑定写法 | 动态绑定写法 |
|---|---|---|---|
| `IModelDoc2.SaveAs4` | Errors, Warnings | `d.SaveAs4(p,0,0,0,0)` → `(True,0,0)` | `call_byref` → `err.value` |
| `ISldWorks.LoadFile4` | Errors | 同左 | 同左 |

```python
import swlib as L
# ① 早绑定：VARIANT 会 TypeError，只能传普通 0，出参从返回元组拆
ret = d.SaveAs4(path, 0, 0, 0, 0)      # (True, 0, 0)
r, outs = L.split_out(ret, 2)          # (True, [0, 0])

# ② 动态绑定：能拿真实错误码
ret, outs = L.call_byref(m, "SaveAs4", [path, 0, 0], ["i4", "i4"])
# 目录不存在 → (False, [1, 0])；扩展名非法 → (False, [256, 0])
```

★ 早绑定 `_ApplyTypes_` 把 `(16387, 3)` 当 int 解包传给 `InvokeTypes`，
VARIANT 对象不是 int → `TypeError: int() argument ... not 'VARIANT'`。
★ pywin32 的 VARIANT 不暴露 `.vt`，用 `L.variant_vt(v)` 从 repr 解。

## 八、工程图计数/枚举（★ 2026-11-21 实测）

```python
V.drawing_view_count(dw)     # GetViewCount() → 4（3 视图 + Sheet1）
V.drawing_views(dw)          # GetViews() 嵌套元组展平，过滤掉 Sheet1
V.view_annotation_count(v)   # IView.GetAnnotationCount() → 该视图标注条数
V.drawing_annotation_total(dw)  # 全图累加
V.insert_model_annotations(dw, 0, 8, True, False, False, False)  # ★ 6 参
```

| 坑 | 表现 |
|---|---|
| `GetViewCount()` 含 Sheet1 | 3 视图返回 4，判据要 `== views_made + 1` |
| `GetViews()` 嵌套元组 | `((Sheet1, v1, v2, v3),)`，直接迭代拿到元组 |
| `InsertModelAnnotations2` 返回 True 但 0 条 | 判据只能看 `GetAnnotationCount` 增量 |
