# 非拉伸类建模手法（本机 SW2022 实测 + GitHub 三仓库交叉验证）

> 证据来源：本机 `scripts/test_features.py`（6 手法 dev 全 0.0000%）、
> `Nilove2018/solidworks-api-skill`（SW2025 PROVEN）、
> `wzyn20051216/solidworks-automation-skill`（2199★，SW2026 真机回归）、
> `muerus/SolidWorks-Python`、`codestack.net`。
> 目标：任何手法先查本表，别凭记忆写长参数。

## 零、选择集 mark 总表（命门）

| 手法 | 选什么 | 怎么选 | mark |
|---|---|---|---|
| 拉伸/切除 | 草图 | `select_sketch` 5级回退 | 0 |
| 旋转 | 草图（含中心线） | Select2 | 0 |
| 放样 | 每个截面草图 | `Select2(True,1)` 逐张追加 | 1 |
| 扫描 | 轮廓草图 | Select2 | 1 |
| 扫描 | **路径线段** | `Select2(append,4)` | **4** |
| 抽壳 | 要删的面 | `IEntity.Select4(True,SelectData)` | 1 |
| 圆周阵列 | 轴 / 母特征 | SelectByID2("AXIS") / Select2 | 1 / 4 |
| 镜像 | 被镜像特征 / 基准面 | Select2 / SelectByID2 | **1 / 2**（★2026-11-20 纠正，旧写 4/1 是错的） |
| 圆角倒角 | 边 | `IEntity.Select2` | 0（本机）或 1（wzyn） |

★★ **选择集铁律**：`Select2(append, mark)` 优先；面/边 Select2 失效才退 `Select4(True, SelectData)`。
`ISelectData.Mark` 只在阵列方向边用（Select4），**本机 MultiSelect2+ISelectData.Mark 卡死，禁用**。
★★ **顺序铁律**：选完面立刻建特征，中间不能插 `volume_mm3()`/`feature_tree()` 等会清空选择集的诊断调用。

## 一、旋转 revolve（verified，dev 0.0000%）

```python
# ★★ 轮廓「X=半径、Y=轴线」，中心线沿 Y —— 这是本机唯一正确的画法
with V.addtoDB(m) as skm:
    V.L.new_sketch(m, "Front Plane")
    # 阶梯轴：X 是半径方向，Y 是轴线方向
    poly = [(0,0), (R2,0), (R2,L1+L2), (R3,L1+L2), (R3,L), (0,L), (0,0)]
    for i in range(len(poly)-1):
        V.L.line(skm, *poly[i], *poly[i+1])
    skm.CreateCenterLine(0.0, -0.02, 0.0, 0.0, (L+20)*0.001, 0.0)  # ★ 6 参是【米】
    sk = V.last_sketch_name(m); skm.InsertSketch(True)
V.revolve_checked(m, sk, 360.0)                # is_cut=True → 旋转切除
```
- API：`FeatureRevolve2` **20 参**，`Dir1Angle` 是**弧度**（库内已转换）。
- ★★ **轴必须沿草图 Y 方向**。画成「X=轴线、Y=半径」会绕错轴，
  体积偏差可达 **768%**；判据：bbox 的 X/Z 应等于 ±Rmax，Y 等于轴长。
- 坑：轮廓必须全在中心线同一侧；跨轴会自动合并/失败。
- 薄壁回转件（碗/杯）：**画带壁厚的闭合截面一次旋转**，不要 solid+shell（shell 对旋转体端面会被 SW 拒绝）。

## 二、放样 loft（verified，dev 0.0000%）

```python
p2 = V.offset_plane(m, "Top Plane", 40)        # InsertRefPlane(8=Distance) 建平行面
V.loft_checked(m, [s1, s2])                    # 截面逐张 Select2(True,1)
```
- API：`InsertProtrusionBlend2` **18 参**，切除 `InsertCutBlend` **12 参**。
- ★ 截面必须在**平行平面**（两个垂直基准面会返回 None）。选 `offset_plane` 建平行面。
- ★ 逐张 `Select2(True,1)` 追加，**不用 MultiSelect2**（本机卡死）。
- ★ 参数 [PROVEN Nilove]：`Start/EndMatchingType=0, TangentLength=1.0, TangentDir=True`。
- 内外轮廓拆不同草图：外层 loft boss，内层 loft cut。
- 斜槽两端各延长 0.3mm 保证切透。

## 三、扫描 sweep（verified，dev 0.0000%）

```python
# 几何契约：轮廓平面【垂直】于路径起始方向，且轮廓过路径起点
# 本机通过配置：路径画在 Front Plane 沿世界 X；轮廓画在 Right Plane（法向 X）
V.sweep_checked(m, profile_sk, path_sk)        # 路径 mark=4
```
- API：`InsertProtrusionSwept4` **20 参**；切除 `InsertCutSwept4`。
- ★ 路径线段 `Select2(append,4)`，**不需要 SELOBJGROUP**（wzyn 全仓库无此作法）。
- ★ 合并失败多为"只接触不重叠"：让新特征与主体重叠 0.2–0.5mm，或留 ≥0.01mm 净间隙。
- 螺旋扫描：路径用 helix 特征 `helix.Select2(False,4)`；`InsertHelix` 返回 void，必须回读特征树按 type=="Helix" 且排除 before 确认。

## 四、抽壳 shell（verified，dev 0.0000%）

```python
# ★ 所有诊断在选面【之前】做完
faces = [V.wrap(f, "IFace2") for f in body.GetFaces()]
top = max(faces, key=lambda f: list(f.GetBox())[5])   # zmax 平面端面
V.shell_checked(m, 2.0, faces=[top])          # 内部 Select4+mark=1
```
- API：`IModelDoc2.InsertFeatureShell(厚度m, outward)`，**不在 IModelDocExtension**，返回 VT_VOID（成功也是 None）。
- ★ 面用 `IFace2→IEntity.Select4(True, SelectData)`，mark=1。
- ★ 旋转体端面抽壳会被 SW 静默拒绝（本机实测）；方块平面端面稳定成功。
- 判据：回读特征树新增 `Shell` 特征，或体积确实变化。

## 五、圆角 fillet / 倒角 chamfer（verified）

```python
V.fillet_checked(m, 5.0, edges=edges)          # FeatureFillet 7 参（本机 SW2022）
V.chamfer_checked(m, 3.0, edges=edges, angle_deg=45)  # 8 参，角度弧度
```
- ★ wzyn 报告说 SW2024/2026 的 `FeatureFillet` 是 **4 参** `(195, r, 0, 0)`；本机 SW2022 是 **7 参**，传 7 参并补 None 已实测通过。**按本机版本走，别照抄 GitHub**。
- 边用 `IEntity.Select2(True,0)`（wzyn 也用 mark=1，本机 0 可行）。
- 坑：外层轮廓先倒圆角再 shell，壁厚更均匀、成功率更高。
- 坑：倒角特征可能生成但体积没变 → 断言体积下降。

## 六、阵列 pattern / 镜像 mirror（均 verified）

```python
V.circular_pattern_checked(m, "切除-拉伸1", "基准轴1", 6)
# 轴 mark=1、母特征 mark=4
# ★ 母特征必须传【切除特征名】——特征树类型名是 ICE，不是 Cut/Extrusion
# ★ 轴必须【垂直于「孔心↔中心」连线】：
#     孔在 (X=25,Y=0) 圆柱轴沿 Z → 用 Top×Right（X 轴），count=6 新增 5 孔
#     用 Front×Top（Z 轴）→ 孔在轴上，只新增 1.34 孔（错）
# ★ count=N 实际新增 N-1 个孔（母特征算第 1 个）

V.mirror_checked(m, "切除-拉伸1", "Right Plane")
# ★★ 2026-11-20 纠正：被镜像特征 mark=1、基准面 mark=2
#    旧版写 mark=4 / mark=1，六种组合实测恒返回 None
#    修正后 Δ = −4000.00 mm³ 精确
```
- 线性阵列（wzyn，SW2026 FeatureLinearPattern4 20参，本机未测）：
  母特征 mark=4、方向1边 mark=1、方向2边 mark=2。
- 镜像 API：`InsertMirrorFeature2(False,False,False,False,0)`。

## 六点五、齿轮整圈齿廓（verified，补 gearmath 缺口）

`gearmath.flank()` 只返回**单侧半齿廓**（55 点，角度 −7.19°..−1.58°），
要整圈必须自己拼。已封装 `scripts/gearring.py`：

```python
import gearmath as G
from gearring import full_ring, check_ring

p = G.GearParams(mn=2.5, z=24, bw=20, bore=10, npts=24)  # ★ 参数是 mn/bw
g = G.GearGeom(p)
h = G.flank(p, g)
ring = full_ring(p, g, list(h.pts), npts_root=6)   # 整圈闭合点列
info = check_ring(ring, g)
assert info["r_ok"]      # r_min==rf(26.875), r_max==ra(32.500)
assert info["closed"]    # 首尾相同

# ★★ 中心孔必须画在【同一草图】，一次拉伸 → solid=1 且带孔
with V.addtoDB(m) as skm:
    V.L.new_sketch(m, "Top Plane")
    V.spline(skm, ring)
    V.circle(skm, 0, 0, 10)          # 中心孔同草图
    sk = V.last_sketch_name(m); skm.InsertSketch(True)
    V.extrude_checked(m, sk, 20)
```
- ★ 实测：z=24 m=2.5 → 2761 点，面积 2792.4 mm²，拉伸体积 dev **0.40%**。
- ★★ **不要先拉伸再加草图切孔**：2761 点样条导致面拓扑异常，`cut` 返回 None。
- ★ 面积校验：应介于 `π·rf²`（2269）与 `π·ra²`（3318）之间。

## 七、拔模 draft（verified 等效法，本地原空白）

来源：`marinmax720-gif/agent` Driver v8 —— 原生 `InsertFeatureDraft2` 外部 COM 不可靠，
改用 Python 数学等效几何。★ 生成的是等效几何，非参数化拔模特征，改尺寸需重跑。

```python
# A. 棱柱拔模：梯形截面拉伸（四边对称内缩 offset=H·tanα）
V.draft_extrude(m, bottom_w=40, bottom_h=40, height=20, draft_angle_deg=5)
#   校验：H·tanα < min(w,h)/2，否则顶部自交抛 ValueError
#   理论体积 = H/3·(A1+A2+√(A1·A2))，实测 dev -0.07%（斜边微圆整，<0.5% 容差）

# B. 回转体拔模：直角梯形 + 中心线旋转（圆台）
V.draft_cone(m, bottom_r=20, top_r=15, height=20)
#   理论体积 = πh/3·(R²+Rr+r²)，实测 dev 0.0000%

# C. 真·拔模特征（PILOT，外部 COM 可能返回 None）
V.draft_native(m, faces=[拔模面...], neutral_plane="Top Plane", angle_deg=5)
#   拔模面 mark=1、中性面 mark=2；失败退回 A/B 等效法
```

原生 `InsertFeatureDraft2` 签名（可选升级）：
```
(ReverseDir, DraftType=1中性面, PropagateToTan, DraftAngle弧度, IsStepDraft, StepDir, StepAngle)
```

## 八、曲面 surface（extrude/planar verified；thicken 不可用）

```python
V.surface_extrude(m, sk, 50)      # FeatureExtruRefSurface 21参 → (0实体,1曲面)
V.surface_planar(m, sk)           # IModelDoc2.InsertPlanarRefSurface（不在 FeatureManager）
V.surface_revolve(m, sk, 360)     # InsertRevolvedRefSurface 4参(弧度,Reverse,Angle2,RevType)
V.surface_thicken(m, face, 2.0, sw=sw)   # ★ GetModeler 在 ISldWorks，须传 sw
V.body_counts(m)                  # (实体数, 曲面体数) —— 唯一可信判据
V.face_cylinder(m, 0)             # 取圆柱面（IsCylinder 是属性不是方法！）
```

★ 这些 API 返回类型都是 **VT_VOID**，成功也是 None —— 必须用 `body_counts()` 对比判成败。
★ `InsertPlanarRefSurface` 在 **IModelDoc2** 上，不在 IFeatureManager（后者只有 InsertFlattenSurface）。
★ `ISurface.IsCylinder` / `IsPlane` 是**属性**，写成 `IsCylinder()` 会报 `'bool' object is not callable`。
★★ **`ThickenSheet` 本机不可用**：平面曲面和拉伸曲面都试过，一律返回 None
  （已试过传面/传体/不同 direction/不同厚度）。要用实体请直接用拉伸。

## 九、焊件 weldment（verified）

```python
profs = V.find_weldment_profiles()        # 本机：F:\SOLIDWORKS\data\weldment profiles
V.structural_weldment(m, path_sk, profs[0])   # 实测 vol 333751 mm³
V.weldment_cut_list(m)                    # 切割清单
```

★★ **三件套缺一不可**（wzyn 2199★ 实测，本机复现）：
1. 先 `InsertWeldmentFeature()` 建焊件文件夹 —— 没有它整个失败
2. `CreateStructuralMemberGroup()` 建组，设 `.Segments`（**Dispatch SAFEARRAY**）
   与 `.ApplyCornerTreatment`
3. `InsertStructuralWeldment5` 的 `Groups` 参数必须是 **Dispatch SAFEARRAY**，
   **传 None 必返回 None**（这是最容易踩的坑）

`connected`: 0=不连接 1=简单切剪（默认 1）；`allowProtrusion` 默认 False。

## 十、运动仿真 motion（verified，Motion 插件）

类型库：`F:\SOLIDWORKS\swmotionstudy.tlb` IID `{45DB5211-F358-4B5E-A235-E792EB818BAA}` v30
（需单独 `makepy.GenerateFromTypeLibSpec` 生成，不在 sldworks.tlb 里）

```python
V.ensure_motion_addin(sw)                # 插件必须先加载
mgr = V.motion_manager(asm)              # ★ GetMotionStudyManager 在 IModelDocExtension 上
ms = V.create_motion_study(asm)          # 新建；SW 自动命名（中文版"运动算例 1"）
V.list_motion_studies(asm)               # GetMotionStudyNames
V.activate_motion_study(asm, name)       # ActivateMotionStudy
V.calculate_motion(ms)                   # 先 Activate 再 Calculate
V.play_motion(ms, from_start=True)       # Play / PlayFromStart
V.motion_results(ms, t, comp)            # GetLinearVelocity/GetAngularVelocity/...
V.save_motion_avi(ms, "a.avi")           # SaveToAVI(FileName, AVIParameter)
```

关键接口与枚举：
- `IMotionStudyManager`：CreateMotionStudy / GetMotionStudy / GetMotionStudyNames /
  ActivateMotionStudy / DeleteMotionStudy / CreateAVIParameter
- `IMotionStudy`：Activate / Calculate / Play / PlayFromStart / CreateDefinition(Type) /
  CreateFeature / CreateByRotateModel / CreateByExplode / CreateByCollapse / SaveToAVI
- `swMotionStudyType_e`：1=Assembly 2=PhysicalSimulation 4=CosmosMotion 8=Legacy 16=NewCosmos
- 默认已有一个 "Motion Study 1"；新建会追加，不会替换

★ 本机实测：`IMotionStudyProperties` 取不到（SetFrameRate 走不通），帧率设置标 pilot。
★ `Calculate` 需要装配体有可动自由度；全固定的装配体也能算（返回 True 但无运动）。

## 十一、三段式特征判据（移植 wzyn）

```python
V.assert_feature_created(m, f, name="Boss1")
# ① 返回 None 立即抛（判 None 不判真）
# ② 命名 + ForceRebuild3(False) 必须 True
# ③ FeatureByName(name) 回读确认持久化
```

## 十二、GitHub 多仓库能力边界（别照抄错版本）

| 手法 | Nilove(SW2025) | wzyn(SW2026) | 本机(SW2022) |
|---|---|---|---|
| revolve | PROVEN 20参 | verified 20参 | ✓ verified |
| loft | PROVEN InsertProtrusionBlend2 | **blocked**（走 OCP headless） | ✓ verified（原生可用） |
| sweep | PROVEN CreateDefinition+CreateFeature | pilot 仅圆形截面 | ✓ verified InsertProtrusionSwept4 |
| shell | PROVEN mark=1 | 能力 verified 但选面未实现 | ✓ verified（平面端面） |
| fillet | FeatureFillet3 14参 | **FeatureFillet 4参** | 7参（本机实测） |

**结论**：GitHub 上针对 2024/2026 的结论必须本机重测；本表以本机 SW2022 实测为准。
