# -*- coding: utf-8 -*-
"""渐开线齿轮几何 —— 齿条刀具包络法。

移植自 Siegfried19/solidworks-gear-generator (MIT) 的 GearMath.cs，
已按本机 SolidWorks 2022 实测数据校核。核心改进相对朴素写法：

  1. 齿根不是"直线到齿根圆"，而是**刀尖圆角在展成运动中的包络**（摆线过渡曲线）。
     这才是真齿轮的齿根形状，也是 GB/ISO 标准齿形的判据。
  2. 根切不是特殊分支，是包络的自然结果：摆线点侵入渐开线时，齿廓在那里截断。
  3. 齿顶变尖时自动把齿顶圆收到尖点半径。
  4. Dedupe 容差 1e-5 mm —— SolidWorks 草图容差约 1e-5 mm，
     比这更近的两点会让 CreateSpline 生成退化曲线并被静默丢弃，轮廓开口子。

所有长度 mm，角度 rad（对外接口用度）。
"""
import math

D2R = math.pi / 180.0


def inv(a):
    """渐开线函数 inv(a) = tan(a) - a"""
    return math.tan(a) - a


def inv_inv(v):
    """inv 的反函数：由 inv(a) 求 a。牛顿迭代。"""
    if v <= 0:
        return 0.0
    a = (3.0 * v) ** (1.0 / 3.0)
    for _ in range(80):
        t = math.tan(a)
        d = t * t
        if d < 1e-12:
            break
        s = (t - a - v) / d
        a -= s
        if abs(s) < 1e-15:
            break
    return a


def pol(r, t):
    return (r * math.cos(t), r * math.sin(t))


class GearParams(object):
    def __init__(self, mn=2.0, z=20, alf_n=20.0, beta=0.0, x=0.0, bw=20.0,
                 ha=1.0, cc=0.25, rho=0.38, bore=12.0, internal=False,
                 od_int=0.0, npts=24):
        self.mn = mn
        self.z = int(z)
        self.alf_n = alf_n
        self.beta = beta
        self.x = x
        self.bw = bw
        self.ha = ha
        self.cc = cc
        self.rho = rho
        self.bore = bore
        self.internal = internal
        self.od_int = od_int
        self.npts = int(npts)

    def clone(self, **kw):
        d = dict(self.__dict__)
        d.update(kw)
        return GearParams(**d)


class GearGeom(object):
    """由参数算出的几何量。"""

    def __init__(self, p):
        b = p.beta * D2R
        an = p.alf_n * D2R
        self.beta_r = b
        self.mt = p.mn / math.cos(b)
        self.alf_t = math.atan(math.tan(an) / math.cos(b))
        self.r = self.mt * p.z / 2.0
        self.rb = self.r * math.cos(self.alf_t)
        self.pb = math.pi * self.mt * math.cos(self.alf_t)
        self.zv = p.z / math.cos(b) ** 3
        self.is_int = p.internal
        if p.internal:
            self.st = self.mt * math.pi / 2.0 - 2.0 * p.x * p.mn * math.tan(self.alf_t)
            self.ra = self.r - (p.ha - p.x) * p.mn
            self.rf = self.r + (p.ha + p.cc + p.x) * p.mn
        else:
            self.st = self.mt * math.pi / 2.0 + 2.0 * p.x * p.mn * math.tan(self.alf_t)
            self.ra = self.r + (p.ha + p.x) * p.mn
            self.rf = self.r - (p.ha + p.cc - p.x) * p.mn
        self.psi = self.st / (2.0 * self.r)

        r_point = self.rb / math.cos(inv_inv(self.psi + inv(self.alf_t)))
        self.pointed = (not p.internal) and (self.ra >= r_point - 1e-9)
        self.ra_use = r_point * 0.999995 if self.pointed else self.ra
        if self.pointed:
            self.ra = self.ra_use
        self.sa = 2.0 * self.ra_use * max(0.0, self.half_ang(self.ra_use))

        sa2 = math.sin(self.alf_t)
        self.z_min = 2.0 * (p.ha - p.x) / (sa2 * sa2)
        self.x_min = p.ha - p.z * sa2 * sa2 / 2.0

        hf = self.st / (2.0 * self.r)
        self.sc = 2.0 * self.r * math.sin(hf)
        self.hc = abs(self.ra_use - self.r * math.cos(hf))

        zp = p.z * inv(self.alf_t) / inv(an)
        self.k = max(2, int(round(zp * p.alf_n / 180.0 + 0.5)))
        self.w = (p.mn * math.cos(an) * (math.pi * (self.k - 0.5) + p.z * inv(self.alf_t))
                  + 2.0 * p.x * p.mn * math.sin(an))

        self.dp = 1.68 * p.mn
        q = self.dp / (p.mn * p.z * math.cos(self.alf_t))
        sh = 2.0 * p.x * math.tan(an) / p.z
        i_m = (inv(self.alf_t) - q + math.pi / (2.0 * p.z) + sh) if p.internal else \
              (inv(self.alf_t) + q - math.pi / (2.0 * p.z) + sh)
        if i_m > 1e-9:
            rm = self.rb / math.cos(inv_inv(i_m))
            base_m = 2 * rm * math.cos(math.pi / (2.0 * p.z)) if p.z % 2 else 2 * rm
            self.m = base_m + (-self.dp if p.internal else self.dp)
        else:
            self.m = float("nan")

    @property
    def d(self):
        return 2 * self.r

    @property
    def da(self):
        return 2 * self.ra

    @property
    def df(self):
        return 2 * self.rf

    @property
    def db(self):
        return 2 * self.rb

    def half_ang(self, th):
        """半径 th 处的半齿角（从齿中心量）。"""
        if th < self.rb:
            th = self.rb
        q = self.rb / th
        if q > 1:
            q = 1.0
        iv = inv(math.acos(q))
        return (self.psi + iv - inv(self.alf_t)) if self.is_int \
            else (self.psi + inv(self.alf_t) - iv)

    def __repr__(self):
        return ("GearGeom d=%.4f da=%.4f df=%.4f db=%.4f st=%.4f zmin=%.3f%s"
                % (self.d, self.da, self.df, self.db, self.st, self.z_min,
                   " POINTED" if self.pointed else ""))


class Half(object):
    def __init__(self):
        self.pts = []       # 齿根圆起点 -> 过渡曲线 -> 渐开线 -> 齿顶圆
        self.land_a = 0.0   # 齿根平底半角
        self.rc = 0.0       # 实际刀尖/过渡圆角半径
        self.r_form = 0.0   # 有效渐开线起始半径
        self.undercut = False
        self.th_a = 0.0     # 齿顶半角


def dedupe(pts, tol=1e-5):
    """去掉连续重合点，保留靠前的。tol 单位 mm。"""
    i = len(pts) - 1
    while i > 0:
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        if math.hypot(dx, dy) < tol:
            del pts[i]
        i -= 1
    if len(pts) < 3:
        raise ValueError("齿廓点数不足 (%d)，参数可能不合理" % len(pts))


def _troch(u, cx, cy, rc, zeta, r):
    """刀尖圆角在展成运动中的包络点（齿中心坐标系）。"""
    wx = cx + u
    wy = cy
    L = math.hypot(wx, wy)
    if L < 1e-9:
        L = 1e-9
    px = wx + rc * wx / L
    py = wy + rc * wy / L
    f = u / r
    ax = px * math.cos(f) + (py - r) * math.sin(f)
    ay = -px * math.sin(f) + (py - r) * math.cos(f)
    return (ax * math.cos(zeta) - ay * math.sin(zeta),
            ax * math.sin(zeta) + ay * math.cos(zeta))


def flank_external(p, g):
    """外齿轮：齿条刀具包络（渐开线 + 真实摆线过渡曲线）。"""
    h = Half()
    at, r, rb, m = g.alf_t, g.r, g.rb, p.mn
    a0 = math.pi * g.mt / 4.0 - p.x * m * math.tan(at)
    hh = (p.ha + p.cc - p.x) * m
    r_lim = (a0 - hh * math.tan(at)) * math.cos(at) / (1.0 - math.sin(at))
    if r_lim < 0:
        r_lim = 0.0
    rc = max(0.0, min(p.rho * m, r_lim))
    cy = hh - rc
    cx = a0 - cy * math.tan(at) - rc / math.cos(at)
    if cx < 0:
        cx = 0.0
    h.rc = rc
    h.land_a = cx / r
    zeta = math.pi / 2.0 - math.pi / p.z

    h.pts.append(pol(g.rf, -math.pi / p.z + h.land_a))

    u_end = cy / math.tan(at) - cx
    n_out = max(8, p.npts)
    nt = max(60, n_out)
    keep = max(1, int(round(float(nt) / n_out)))
    r_j = g.rf

    for j in range(nt + 1):
        u = -cx + (u_end + cx) * j / nt
        pt = _troch(u, cx, cy, rc, zeta, r)
        rr = math.hypot(pt[0], pt[1])
        if rr >= g.ra_use:
            r_j = rr
            break
        if rr > rb:
            th = -math.atan2(pt[1], pt[0])
            if th < g.half_ang(rr) - 1e-9:
                h.pts.append(pt)
                r_j = rr
                h.undercut = True
                break
        if j % keep == 0 or j == nt:
            h.pts.append(pt)
        r_j = rr
    if r_j < rb:
        r_j = rb
    if r_j > g.ra_use:
        r_j = g.ra_use
    h.r_form = r_j

    a_s = math.acos(min(1.0, rb / r_j))
    a_e = math.acos(min(1.0, rb / g.ra_use))
    if a_e > a_s + 1e-6:
        for i in range(1, p.npts + 1):
            ay = a_s + (a_e - a_s) * i / p.npts
            h.pts.append(pol(rb / math.cos(ay), -g.half_ang(rb / math.cos(ay))))
    h.th_a = max(0.0, g.half_ang(g.ra_use))
    dedupe(h.pts)
    h.pts[-1] = pol(g.ra_use, -h.th_a)
    return h


def _fl_pt(g, ay):
    return pol(g.rb / math.cos(ay), -g.half_ang(g.rb / math.cos(ay)))


def _fil_cen(g, ay, rc):
    A = _fl_pt(g, ay)
    B = _fl_pt(g, max(1e-4, ay - 1e-4))
    tx, ty = A[0] - B[0], A[1] - B[1]
    L = math.hypot(tx, ty)
    if L < 1e-9:
        L = 1e-9
    tx /= L
    ty /= L
    c1 = (A[0] + ty * rc, A[1] - tx * rc)
    c2 = (A[0] - ty * rc, A[1] + tx * rc)
    a_a = math.atan2(A[1], A[0])
    return c1 if math.atan2(c1[1], c1[0]) < a_a else c2


def flank_internal(p, g):
    """内齿圈：渐开线 + 与齿根相切的过渡圆弧。"""
    h = Half()
    rb = g.rb
    space_at_rf = (2 * math.pi / p.z - 2 * g.half_ang(g.rf)) * g.rf
    rc = min(p.rho * p.mn, (g.rf - g.ra_use) * 0.35)
    rc = min(rc, max(0.02 * p.mn, space_at_rf * 0.28))
    h.rc = rc

    lo = math.acos(min(1.0, rb / max(rb * 1.0001, g.ra_use)))
    hi = math.acos(min(1.0, rb / g.rf))
    a_j = hi
    for _ in range(60):
        mid = (lo + hi) / 2.0
        c = _fil_cen(g, mid, rc)
        if math.hypot(c[0], c[1]) > (g.rf - rc):
            hi = mid
        else:
            lo = mid
        a_j = mid
    cen = _fil_cen(g, a_j, rc)
    tc = math.atan2(cen[1], cen[0])
    h.land_a = max(0.0, math.pi / p.z + tc)
    h.r_form = g.rb / math.cos(a_j)

    h.pts.append(pol(g.rf, tc))

    A = _fl_pt(g, a_j)
    a0 = math.atan2(cen[1], cen[0])
    a1 = math.atan2(A[1] - cen[1], A[0] - cen[0])
    da = a1 - a0
    while da > math.pi:
        da -= 2 * math.pi
    while da < -math.pi:
        da += 2 * math.pi
    nf = max(4, p.npts // 4)
    for i in range(1, nf + 1):
        a = a0 + da * i / nf
        h.pts.append((cen[0] + rc * math.cos(a), cen[1] + rc * math.sin(a)))
    a_t = math.acos(min(1.0, rb / max(rb * 1.0001, g.ra_use)))
    for i in range(1, p.npts + 1):
        h.pts.append(_fl_pt(g, a_j + (a_t - a_j) * i / p.npts))

    h.th_a = max(0.0, g.half_ang(g.ra_use))
    dedupe(h.pts)
    h.pts[-1] = pol(g.ra_use, -h.th_a)
    return h


def flank(p, g):
    return flank_internal(p, g) if p.internal else flank_external(p, g)


def warnings(p, g, h):
    s = []
    if not p.internal:
        if p.z < g.z_min - 1e-9:
            s.append("根切：齿数 %d < 不根切最小齿数 %.2f，齿根已切去一段渐开线；取 x >= %.3f 可避免"
                     % (p.z, g.z_min, g.x_min))
        if g.pointed:
            s.append("齿顶变尖，齿顶圆已收到 da = %.4f mm" % g.da)
        elif g.sa < 0.25 * p.mn:
            s.append("齿顶厚 %.3f mm < 0.25mn，建议减小变位" % g.sa)
        if h is not None and h.rc < p.rho * p.mn - 1e-6:
            s.append("刀尖圆角由 %.3f 限制到 %.3f mm（刀顶需保留平顶）"
                     % (p.rho * p.mn, h.rc))
        if p.bore > 0 and p.bore / 2 > g.rf * 0.7:
            s.append("内孔偏大，孔壁到齿根仅 %.3f mm" % (g.rf - p.bore / 2))
    else:
        z_lim = 2.0 * p.ha / (1.0 - math.cos(g.alf_t))
        if g.ra <= g.rb + 1e-9:
            s.append("【严重】齿顶圆 %.3f 落到基圆 %.3f 之内，齿顶段不是渐开线；需 z >= %d"
                     % (g.da, g.db, math.ceil(z_lim)))
        elif g.ra - g.rb < 0.5 * p.mn:
            s.append("齿顶圆距基圆仅 %.3f mm，偏紧（z >= %d 才宽裕）"
                     % (g.ra - g.rb, math.ceil(z_lim)))
        if g.sa < 0.25 * p.mn:
            s.append("内齿齿顶厚仅 %.3f mm，偏薄" % g.sa)
    return s
