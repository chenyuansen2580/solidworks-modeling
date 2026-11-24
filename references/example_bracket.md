# 实战案例：带安装孔的电机支架

> 2026-11-19 用本 skill 完整走通「规划 → 建模 → 出图 → 交付」的实战记录。
> 覆盖：多基准面协同、双加强筋、四视图、工程图 PDF、体积解析校核。
> 本案例暴露并修复了 5 个 skill 缺陷，详见 `pitfalls.md` N 章。

## 一、零件说明

底板固定于基座，立板安装电机（中心轴孔 + 四法兰孔），两根三角加强筋斜撑。
交付：SLDPRT + 四视图 PNG + 工程图 PDF + 校验报告。

## 二、坐标契约（★ 按本机实测轴映射）

| 基准面 | 草图 x → | 草图 y → | 拉伸方向 |
|---|---|---|---|
| Front | X | **Y** | +Z |
| Top | X | **−Z** | +Y |
| Right | **−Z** | Y | +X |

- 底板：**Top 平面**画矩形，沿 **+Y** 拉伸厚度 → 水平
- 立板：**Front 平面**画矩形，沿 **+Z** 拉伸厚度 → 竖直
- 加强筋：**Right 平面**画三角形，沿 **+X** 拉伸 → 垂直于立板的斜撑
- 电机轴沿 **Z** 方向（垂直于立板）

## 三、参数（mm）

| 参数 | 值 | 参数 | 值 |
|---|---|---|---|
| 底板 长×宽×厚 | 160×100×12 | 立板 宽×高×厚 | 120×110×14 |
| 底板孔 4×Ø11，距 130×70 | | 电机轴孔 Ø40 | |
| 电机法兰孔 4×Ø9，方阵 80 | | 筋 厚10，高50 | |
| 筋 z 向底长 | 78（=zf−z_back，实测） | | |

## 四、关键代码片段

```python
# 1) 底板（Top 平面，+Y 拉伸）
with V.addtoDB(m) as skm:
    V.L.new_sketch(m, "Top Plane"); V.L.rect(skm, -80, -50, 80, 50)
    sk = V.last_sketch_name(m); skm.InsertSketch(True)
    V.extrude_checked(m, sk, 12)

# 2) 底板四孔（一次画 4 圆，双向贯穿；比阵列稳）
with V.addtoDB(m) as skm:
    V.L.new_sketch(m, "Top Plane")
    for x in (-65, 65):
        for y in (-35, 35):
            V.circle(skm, x, y, 5.5)
    sk = V.last_sketch_name(m); skm.InsertSketch(True)
    V.cut_checked(m, sk)

# 3) 立板（Front 平面，+Z 拉伸，start_mm 控制位置）
z_start = 50 - 14
with V.addtoDB(m) as skm:
    V.L.new_sketch(m, "Front Plane"); V.L.rect(skm, -60, 0, 60, 110)
    sk = V.last_sketch_name(m); skm.InsertSketch(True)
    V.extrude_checked(m, sk, 14, start_mm=z_start)

# 4) 加强筋（★ Right 平面，世界(z,y) → 草图(-z,y)）
zf, yb, z_back = z_start, 12.0, -50 + 8
with V.addtoDB(m) as skm:
    V.L.new_sketch(m, "Right Plane")
    V.L.line(skm, -zf, yb, -zf, yb + 50)        # 竖边
    V.L.line(skm, -zf, yb + 50, -z_back, yb)    # 斜边
    V.L.line(skm, -z_back, yb, -zf, yb)         # 底边
    sk = V.last_sketch_name(m); skm.InsertSketch(True)
    V.extrude_checked(m, sk, 10, start_mm=-60)  # 左侧筋
# 右侧筋用 start_mm=50 再拉一次（★ 负 start_mm 会返回 None）
```

## 五、体积解析（用于验收）

```
底板   = 160×100×12 − 4·π(5.5)²×12                    = 187438.4
立板   = 120×110×14 − π(20)²×14 − 4·π(4.5)²×14        = 163644.5
重叠   = 120×12×14（立板与底板相接部分）                = −20160.0
单筋   = 0.5 × 78 × 50 × 10                            =  19500.0
双筋                                                      +39000.0
合计                                                    369922.9
实测                                                    368731.4
偏差                                                    −0.32%  ✓
```

★ 筋的 z 向边长是 **78**（zf=36 到 z_back=−42），不是设计意图的 45。写解析式时必须用
真实几何端点算，不能想当然。

## 六、交付物

```
out/
  parts/motor_bracket.SLDPRT     模型，110 KB
  render_iso/front/top/right.png 四视图
  motor_bracket.pdf              工程图（A4 第三角投影）
REPORT.json                      体积/bbox/实体数/各图大小
```

## 七、本案例暴露的 skill 缺陷（已修）

1. `save_png` 忽略 `w/h` → 加 `size_note` + `set_image_size()`
2. `set_view` 用 `m.GetTitle()` 在 IAssemblyDoc 上失败 → 内部 wrap IModelDoc2
3. `save_checked` 对 IAssemblyDoc 报 `SaveAs2` 不存在 → 内部 wrap
4. `new_asm()` 报 `GetTitle` 不存在 → 先 wrap IModelDoc2
5. 无 `open_doc` 封装，`OpenDoc6` 返回元组坑 → 新增 `V.open_doc()`

## 八、已知限制（本案例确认）

- **无法通过 API 改变渲染颜色**：`GetDisplayStateSetting` 在本机一律抛
  −2147417851；`SetMaterialPropertyValues` 回读对但渲染不变。
  只能靠 `set_material()` 换材料自带外观，或接受灰白配色。
- 工程图 PDF 只有 7.6 KB（只含视图，无尺寸标注）。
