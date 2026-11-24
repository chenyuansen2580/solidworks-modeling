# -*- coding: utf-8 -*-
"""交付门禁：四级验证状态 + BLOCKED 安全降级。

移植自 wzyn20051216/solidworks-automation-skill (2199★) 的 core/verification.py，
结合本机 solidworks-modeling skill 的三重断言。

核心思想（★ 最重要）：
  「无法验证」绝不等于 PASS。Reviewer 缺失/异常/未知状态/空结果 —— 一律 BLOCKED。
  Tool Success != Task Success：脚本跑通 != 模型合格。

四级优先级：BLOCKED(3) > FAIL(2) > WARN(1) > PASS(0)

用法：
    from verify_gate import Gate, PASS, WARN, FAIL, BLOCKED
    g = Gate("planetary_reducer")
    g.check("volume", ok, "体积偏差 0.01%")
    g.check("interference", has_interference, "有干涉", level=FAIL)
    g.check("visual_review", review_result, "四视图未目视复核", level=BLOCKED)
    verdict = g.verdict()   # 取最严重等级
    if not verdict.passed:
        raise SystemExit(verdict.reason)
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

PASS = "pass"
WARN = "warn"
FAIL = "fail"
BLOCKED = "blocked"

_PRIORITY = {PASS: 0, WARN: 1, FAIL: 2, BLOCKED: 3}

# 历史/别名字符串归一化，未知值安全降级 BLOCKED
_STATUS_MAP = {
    "pass": PASS, "passed": PASS, "ok": PASS, "success": PASS, "true": PASS,
    "warn": WARN, "warning": WARN, "review_required": WARN,
    "fail": FAIL, "failed": FAIL, "error": FAIL, "invalid": FAIL,
    "blocked": BLOCKED, "unsupported": BLOCKED, "unavailable": BLOCKED,
    "manual_required": BLOCKED, "none": BLOCKED, "": BLOCKED,
}

# 这些 severity 的 FAIL 降级为 WARN（信息性/可选，不影响交付）
_NON_BLOCKING_SEVERITY = frozenset(
    {"p2", "low", "info", "informational", "optional", "note", "debug"})


def normalize(value: Any) -> str:
    """任意状态值归一化为四级之一，未知一律 BLOCKED。"""
    if value in _PRIORITY:
        return value
    key = str(value).strip().lower() if value is not None else "none"
    return _STATUS_MAP.get(key, BLOCKED)


def aggregate(statuses: Iterable[str]) -> str:
    """取最严重等级；空集合 → BLOCKED（无法验证≠PASS）。"""
    norm = [normalize(s) for s in statuses]
    if not norm:
        return BLOCKED
    return max(norm, key=lambda s: _PRIORITY[s])


@dataclass
class Check:
    id: str
    status: str
    message: str = ""
    severity: str = ""
    evidence: Any = None


@dataclass
class Verdict:
    status: str
    checks: list = field(default_factory=list)
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.status == PASS

    @property
    def blocked(self) -> bool:
        return self.status == BLOCKED


class Gate:
    """轻量交付门禁。check() 累积检查结果，verdict() 汇总最严重等级。"""

    def __init__(self, name: str = "model"):
        self.name = name
        self.checks: list[Check] = []

    def check(self, cid: str, value: Any, message: str = "",
              level: str = FAIL, severity: str = "", evidence: Any = None) -> str:
        """记录一项检查。

        value: True/PASS → PASS；False → level；None/未知字符串 → BLOCKED。
        level: 该项失败时的等级（默认 FAIL，关键项传 BLOCKED）。
        severity: 非关键 severity 的 FAIL 会降为 WARN。
        """
        if value is True or normalize(value) == PASS:
            status = PASS
        elif value is None:
            status = BLOCKED
        else:
            status = normalize(level)
            if status == FAIL and severity.lower() in _NON_BLOCKING_SEVERITY:
                status = WARN
        c = Check(cid, status, message, severity, evidence)
        self.checks.append(c)
        return status

    def check_callable(self, cid: str, fn: Callable[[], Any], message: str = "",
                       level: str = FAIL) -> str:
        """执行回调做检查；回调抛异常一律 BLOCKED（无法验证≠PASS）。"""
        try:
            result = fn()
            return self.check(cid, result, message, level)
        except Exception as e:
            return self.check(cid, BLOCKED, "%s | %s: %s" % (message, type(e).__name__, e), level)

    def verdict(self) -> Verdict:
        status = aggregate(c.status for c in self.checks)
        reason = ""
        if status != PASS:
            worst = [c for c in self.checks if c.status == status]
            reason = " | ".join("%s: %s" % (c.id, c.message or c.status) for c in worst)
        return Verdict(status, self.checks, reason)

    def report(self) -> str:
        v = self.verdict()
        lines = ["=== 交付门禁: %s ===" % self.name]
        icon = {PASS: "OK  ", WARN: "WARN", FAIL: "FAIL", BLOCKED: "BLK "}
        for c in self.checks:
            lines.append("  [%s] %-20s %s" % (icon[c.status], c.id, c.message))
        lines.append("  ---- verdict: %s ----" % v.status.upper())
        if v.reason:
            lines.append("  " + v.reason)
        return "\n".join(lines)


# ---- 本机常用检查项快捷封装 ----
def standard_part_gate(m, theory_volume, expect_bbox=None, expect_bodies=1,
                       views=None, interference=None, name="part"):
    """零件交付标准门禁：体积+bbox+实体数+四视图+干涉。
    任何一项无法验证（None）→ BLOCKED。
    """
    import swlib_v2 as V
    g = Gate(name)
    vol = V.volume_mm3(m)
    g.check("volume", bool(theory_volume) and abs(vol - theory_volume) / theory_volume < 0.005,
            "体积 dev=%.4f%%" % (abs(vol - theory_volume) / theory_volume * 100 if theory_volume else 0),
            level=FAIL)
    if expect_bbox:
        bb = V.L.bbox6(m)
        dev = max(abs(a - b) for a, b in zip(bb, expect_bbox))
        g.check("bbox", dev < 0.5, "bbox 最大偏差 %.3fmm" % dev, level=FAIL)
    if expect_bodies is not None:
        try:
            n = len(V.wrap(m, "IPartDoc").GetBodies2(0, False) or [])
            g.check("bodies", n == expect_bodies, "实体数 %d" % n, level=FAIL)
        except Exception as e:
            g.check("bodies", None, "实体数无法读取: %s" % e)
    # 四视图：没做目视复核就是 BLOCKED（无法验证≠PASS）
    g.check("visual_review", views if views is not None else None,
            "四视图未做目视复核" if views is None else "", level=BLOCKED)
    if interference is not None:
        g.check("interference", not interference, "存在干涉" if interference else "无干涉", level=FAIL)
    return g


if __name__ == "__main__":
    # 自测：验证 BLOCKED 降级逻辑
    g = Gate("selftest")
    g.check("volume_ok", True, "体积通过")
    g.check("interference", False, "发现干涉", level=FAIL)
    g.check("review_missing", None, "未目视复核", level=BLOCKED)
    g.check("unknown_status", "something_weird", "未知状态", level=FAIL)
    v = g.verdict()
    print(g.report())
    assert v.status == BLOCKED, "未知/空状态必须降级 BLOCKED"
    assert normalize("ok") == PASS and normalize("garbage") == BLOCKED
    assert aggregate([]) == BLOCKED
    assert aggregate([PASS, FAIL, WARN]) == FAIL
    print(">>> GATE SELFTEST PASS")
