# -*- coding: utf-8 -*-
"""交付新鲜度门禁 —— 阻止旧文件冒充本轮成果。

移植自 wzyn20051216/solidworks-automation-skill 的 artifact_freshness 思路，
结合本机 verify_gate 四级判定（无法验证 ≠ PASS）。

核心规则：
  1. 执行前对输出区域做 SHA-256 基线（含每张文件的 hash + 大小 + mtime）
  2. 执行后重新扫描，producedThisRun 判定：
       - 新文件（基线里没有，且扫描完整覆盖了它的扩展名/目录）→ True
       - 已记录文件 hash 变化 → True
       - hash 相同但只改了 mtime → False（时间戳不算新）
       - 基线不完整/缺基线/路径不在扫描范围/扩展名不受支持 → None → BLOCKED
  3. 旧文件不能被新文件的通过结果掩盖；逐项判定，逐项汇总

用法：
    from artifact_freshness import ArtifactBaseline
    base = ArtifactBaseline.scan(out_dir)          # 执行前
    ... 建模/导出 ...
    report = base.diff(out_dir)                    # 执行后
    gate = report.to_gate("belt_actuator")
    v = gate.verdict()
    if not v.passed: raise SystemExit(v.reason)

★ 边界：新鲜度只证明「文件新增或内容变了」，不证明几何正确。
  它必须和 verify() / interference_ok() / 目视复核一起用，不能单独当交付判据。
"""
from dataclasses import dataclass, field
import fnmatch
import hashlib
import json
import os
from typing import Iterable

PASS = "pass"
WARN = "warn"
FAIL = "fail"
BLOCKED = "blocked"
_PRIORITY = {PASS: 0, WARN: 1, FAIL: 2, BLOCKED: 3}

# 受支持的文件扩展名（建模交付物）；其它扩展名视为「不受支持」，
# 基线中没记录的这种文件不能证明为新增 → BLOCKED
DEFAULT_SCAN_PATTERNS = (
    "*.SLDPRT", "*.sldprt", "*.SLDASM", "*.sldasm",
    "*.SLDDRW", "*.slddrw", "*.STEP", "*.step", "*.stp",
    "*.PDF", "*.pdf", "*.PNG", "*.png", "*.JPG", "*.jpg",
    "*.JSON", "*.json", "*.STL", "*.stl",
)


def _sha256(path, chunk=65536):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


@dataclass
class FileRecord:
    rel: str
    size: int
    sha256: str
    mtime_ns: int


@dataclass
class Baseline:
    root: str
    files: dict = field(default_factory=dict)   # rel -> FileRecord
    patterns: tuple = DEFAULT_SCAN_PATTERNS
    complete: bool = True
    errors: list = field(default_factory=list)

    # ---- 序列化，便于执行前后跨进程比对
    def to_dict(self):
        return {
            "root": self.root,
            "patterns": list(self.patterns),
            "complete": self.complete,
            "errors": self.errors,
            "files": {k: {"size": v.size, "sha256": v.sha256,
                          "mtime_ns": v.mtime_ns}
                      for k, v in self.files.items()},
        }

    @staticmethod
    def from_dict(d):
        b = Baseline(d["root"], patterns=tuple(d.get("patterns", DEFAULT_SCAN_PATTERNS)),
                     complete=bool(d.get("complete", True)),
                     errors=list(d.get("errors", [])))
        for k, v in d.get("files", {}).items():
            b.files[k] = FileRecord(k, v["size"], v["sha256"], v.get("mtime_ns", 0))
        return b

    def save(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    @staticmethod
    def load(path):
        with open(path, encoding="utf-8") as f:
            return Baseline.from_dict(json.load(f))


def scan(root, patterns=DEFAULT_SCAN_PATTERNS, baseline=None):
    """扫描目录，生成 Baseline。

    baseline 非空时只保留其已记录的文件（用于「执行后」比对），
    并额外记录是否存在基线未覆盖的新文件。
    """
    b = Baseline(os.path.abspath(root), patterns=tuple(patterns))
    if not os.path.isdir(root):
        b.complete = False
        b.errors.append("root_not_dir: %s" % root)
        return b
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if not any(fnmatch.fnmatch(fn, p) for p in patterns):
                continue                       # 不受支持的扩展名，跳过
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            try:
                st = os.stat(full)
                b.files[rel] = FileRecord(rel, st.st_size, _sha256(full), st.st_mtime_ns)
            except Exception as e:
                b.complete = False
                b.errors.append("scan_error: %s: %s" % (rel, e))
    return b


@dataclass
class FreshnessItem:
    path: str
    produced_this_run: bool or None     # True / False / None(待复核)
    reason: str
    status: str                          # PASS / FAIL / BLOCKED


@dataclass
class FreshnessReport:
    items: list = field(default_factory=list)
    baseline_complete: bool = True
    errors: list = field(default_factory=list)

    @property
    def passed(self):
        return (self.baseline_complete and bool(self.items)
                and all(i.status == PASS for i in self.items))

    def to_dict(self):
        return {
            "baseline_complete": self.baseline_complete,
            "errors": self.errors,
            "items": [{"path": i.path, "producedThisRun": i.produced_this_run,
                       "reason": i.reason, "status": i.status}
                      for i in self.items],
            "verdict": PASS if self.passed else BLOCKED,
        }

    def report(self):
        lines = ["=== 交付新鲜度门禁 ==="]
        lines.append("  基线完整: %s" % ("是" if self.baseline_complete else "★ 否"))
        for e in self.errors:
            lines.append("  基线错误: %s" % e)
        for i in self.items:
            flag = {PASS: "OK ", FAIL: "OLD", BLOCKED: "BLK"}[i.status]
            val = {True: "true", False: "false", None: "null"}[i.produced_this_run]
            lines.append("  [%s] producedThisRun=%-5s %-40s %s"
                         % (flag, val, i.path, i.reason))
        lines.append("  ---- verdict: %s ----" % ("PASS" if self.passed else "BLOCKED"))
        return "\n".join(lines)


def diff(before: Baseline, root, paths: Iterable[str] = None,
         patterns=DEFAULT_SCAN_PATTERNS) -> FreshnessReport:
    """比对基线与当前输出。

    paths: 要判定的【本轮交付文件】（相对 root 或绝对路径）。
           ★ 必须显式传，否则会把目录里所有历史文件都判成 OLD，噪声淹没结论。
           传 None 仅在「输出目录本来就该是空的」场景下有意义。
    """
    after = scan(root, patterns=patterns)
    rep = FreshnessReport()
    rep.baseline_complete = bool(before.complete and after.complete)
    rep.errors = list(before.errors) + list(after.errors)

    if paths is None:
        rep.errors.append("未指定交付文件清单（paths=None）—— 无法判定，不自动交付")
        rep.baseline_complete = False
        return rep

    targets = []
    for p in paths:
        ap = os.path.abspath(p)
        if ap.startswith(os.path.abspath(root)):
            rel = os.path.relpath(ap, root).replace("\\", "/")
        else:
            rel = str(p).replace("\\", "/")
        targets.append(rel)

    for rel in targets:
        cur = after.files.get(rel)
        old = before.files.get(rel)
        # 路径不在扫描范围内 / 扩展名不受支持 → 无法证明新增
        if cur is None:
            rep.items.append(FreshnessItem(rel, None,
                             "文件不在完整扫描范围内（或不支持的扩展名）", BLOCKED))
            continue
        if not rep.baseline_complete:
            rep.items.append(FreshnessItem(rel, None, "基线/当前扫描不完整", BLOCKED))
            continue
        if old is None:
            # 基线完整覆盖了该扩展名与目录，基线里没有 → 新增
            supported = any(fnmatch.fnmatch(os.path.basename(rel), p) for p in before.patterns)
            if supported:
                rep.items.append(FreshnessItem(rel, True, "本轮新增", PASS))
            else:
                rep.items.append(FreshnessItem(rel, None, "基线未覆盖该扩展名", BLOCKED))
            continue
        if old.sha256 != cur.sha256:
            rep.items.append(FreshnessItem(rel, True,
                             "SHA-256 变化 %s→%s" % (old.sha256[:8], cur.sha256[:8]), PASS))
        else:
            rep.items.append(FreshnessItem(rel, False,
                             "内容与基线相同（仅 mtime 变化也不算新）", FAIL))
    return rep


def require_fresh(before: Baseline, root, paths, patterns=DEFAULT_SCAN_PATTERNS):
    """硬门禁：任一交付文件非本轮新增/变化就抛 SystemExit。"""
    rep = diff(before, root, paths, patterns)
    print(rep.report())
    if not rep.passed:
        raise SystemExit(rep.report())
    return rep


def to_gate(report, name="artifacts"):
    """把 FreshnessReport 转成 verify_gate.Gate，并入统一四级判定。

    用法：
        from verify_gate import Gate
        g = V.standard_part_gate(...)          # 几何门禁
        g2 = to_gate(rep, "belt_actuator")     # 新鲜度门禁
        # 合并：任一门禁 BLOCKED 就 BLOCKED
    """
    try:
        from verify_gate import Gate, FAIL as GF, BLOCKED as GB
    except Exception:
        return None
    g = Gate(name)
    if not report.baseline_complete:
        g.check("baseline_complete", None,
                "基线不完整: %s" % ("; ".join(report.errors) or "未知"), level=GB)
    if not report.items:
        g.check("artifacts_declared", None, "未声明任何交付文件", level=GB)
    for it in report.items:
        if it.status == PASS:
            g.check(it.path, True, it.reason)
        elif it.status == FAIL:
            g.check(it.path, False, it.reason, level=GF)
        else:
            g.check(it.path, None, it.reason, level=GB)
    return g


def merge_gates(gates, name="delivery"):
    """合并多个 Gate：任一 BLOCKED/FAIL 即整体不过。

    ★ 这是「旧文件不能被新文件掩盖」的最终落点：
      几何门禁 PASS + 新鲜度门禁 FAIL → 整体 FAIL。
    """
    try:
        from verify_gate import Gate
    except Exception:
        return None
    out = Gate(name)
    for g in gates:
        if g is None:
            out.check("gate_missing", None, "某个门禁未构建", level="blocked")
            continue
        for c in g.checks:
            out.checks.append(c)
    return out


if __name__ == "__main__":
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="freshness_")
    try:
        # 场景 1: 新文件 → PASS
        base = scan(tmp)
        with open(os.path.join(tmp, "new.SLDPRT"), "wb") as f:
            f.write(b"new")
        r = diff(base, tmp)
        assert r.passed and r.items[0].produced_this_run is True

        # 场景 2: 内容未变只改 mtime → FAIL
        base2 = scan(tmp)
        os.utime(os.path.join(tmp, "new.SLDPRT"), ns=(base2.files["new.SLDPRT"].mtime_ns + 10**9,
                                                     base2.files["new.SLDPRT"].mtime_ns + 10**9))
        r2 = diff(base2, tmp)
        assert not r2.passed and r2.items[0].produced_this_run is False

        # 场景 3: 内容变化 → PASS
        with open(os.path.join(tmp, "new.SLDPRT"), "wb") as f:
            f.write(b"changed")
        r3 = diff(base2, tmp)
        assert r3.passed and r3.items[0].produced_this_run is True

        # 场景 4: 基线目录不存在 → BLOCKED
        bad = Baseline("/no/such/dir", complete=False, errors=["root_not_dir"])
        r4 = diff(bad, tmp)
        assert not r4.passed and all(i.status == BLOCKED for i in r4.items)

        # 场景 5: 序列化往返
        p = os.path.join(tmp, ".baseline.json")
        base3 = scan(tmp)
        base3.save(p)
        b4 = Baseline.load(p)
        assert b4.files["new.SLDPRT"].sha256 == base3.files["new.SLDPRT"].sha256

        print(">>> FRESHNESS SELFTEST PASS")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
