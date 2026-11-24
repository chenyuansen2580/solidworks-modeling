# -*- coding: utf-8 -*-
"""执行 Trace —— 结构化记录每一步，可审计、可回放、可定位失败点。

对标 wzyn20051216/solidworks-automation-skill（2230★）的 Execution Trace。

## 问题

前两个机制管「交付物」（新鲜度）和「能力」（缺口），但**过程没有留痕**：

  - 建模跑到第 7 步失败，只知道"失败了"，不知道前 6 步做了什么
  - 体积对不上，不知道是哪一步引入的偏差
  - 交付报告只有结论，没有「怎么得出的」

结果是**不可审计、不可回放、失败不可定位**。

## 设计

一次任务 = 一个 `Trace`，内含若干 `Step`：

    Trace
      ├─ meta: 任务名 / 开始时间 / 环境（SW 版本、Python、模板路径）
      ├─ steps: [Step, ...]
      └─ verdict: PASS / FAIL / BLOCKED

    Step
      ├─ seq        序号（从 1 开始）
      ├─ name       步骤名（如 "P1.extrude"）
      ├─ kind       build / verify / export / gate / note
      ├─ status     ok / fail / skip / blocked
      ├─ t0/t1      起止时间（相对任务开始，秒）
      ├─ inputs     关键入参（体积期望、深度…）
      ├─ outputs    关键产出（实测体积、实体数…）
      ├─ evidence   证据（偏差百分比、bbox、文件大小）
      ├─ error      失败时的异常文本
      └─ duration   耗时

## 用法

    import exec_trace as ET

    tr = ET.Trace("belt_actuator")
    tr.env(sw_version="30.5.0", python="3.12.4")

    with tr.step("P1.extrude", inputs={"depth": 600}) as s:
        V.extrude_checked(m, sk, 600)
        s.output("volume", V.volume_mm3(m))
        s.ev("dev_pct", 0.000)

    # 失败自动记录，不吞异常
    with tr.step("P1.shell") as s:
        V.shell_checked(m, 10.0, faces=[f])
        # 抛异常 → step 记 fail，异常继续向上抛

    tr.save(r"out\trace.json")
    print(tr.report())
    tr.require_ok()          # 有 fail 就抛

## 与 verify_gate 的关系

  - `Gate` 判「这一项过没过」
  - `Trace` 记「这一步做了什么、凭什么过」
  - 两者互补：Gate 是结论，Trace 是过程

## 边界

Trace 只记录**调用方显式声明的**步骤和证据，不自动 hook COM。
自动 hook 会让日志爆炸且难以理解，显式声明反而更可读。
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
import json
import os
import time
import traceback

OK = "ok"
FAIL = "fail"
SKIP = "skip"
BLOCKED = "blocked"

KIND_BUILD = "build"
KIND_VERIFY = "verify"
KIND_EXPORT = "export"
KIND_GATE = "gate"
KIND_NOTE = "note"


@dataclass
class Step:
    seq: int
    name: str
    kind: str = KIND_BUILD
    status: str = OK
    t0: float = 0.0
    t1: float = 0.0
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    error: str = ""

    @property
    def duration(self):
        return round(self.t1 - self.t0, 3)

    def output(self, key, value):
        self.outputs[key] = value
        return value

    def ev(self, key, value):
        """记一条证据（ev = evidence 的缩写，避免和字段名冲突）。"""
        self.evidence[key] = value
        return value

    def to_dict(self):
        d = asdict(self)
        d["duration"] = self.duration
        return d


class StepCtx:
    """with 块上下文：成功记 ok，异常记 fail 并继续抛。"""

    def __init__(self, trace, step):
        self.trace = trace
        self.step = step

    def __enter__(self):
        self.step.t0 = time.time() - self.trace._t_start
        return self.step

    def __exit__(self, exc_type, exc, tb):
        self.step.t1 = time.time() - self.trace._t_start
        if exc_type is not None:
            self.step.status = FAIL
            self.step.error = "%s: %s" % (exc_type.__name__, exc)
            # 记最后一帧位置，方便定位
            frames = traceback.extract_tb(tb)
            if frames:
                f = frames[-1]
                self.step.evidence["fail_at"] = "%s:%d" % (
                    os.path.basename(f.filename), f.lineno)
        self.trace.steps.append(self.step)
        return False          # 不吞异常


class Trace:
    def __init__(self, name="task"):
        self.name = name
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.env_info = {}
        self.steps = []
        self._t_start = time.time()
        self._seq = 0

    # ---- 环境
    def env(self, **kwargs):
        self.env_info.update(kwargs)
        return self

    # ---- 步骤
    def step(self, name, kind=KIND_BUILD, **inputs):
        self._seq += 1
        st = Step(seq=self._seq, name=name, kind=kind, inputs=dict(inputs))
        return StepCtx(self, st)

    def note(self, name, **data):
        """记一条纯记录（不计入成败）。"""
        self._seq += 1
        now = time.time() - self._t_start
        st = Step(seq=self._seq, name=name, kind=KIND_NOTE,
                  t0=now, t1=now, evidence=dict(data))
        self.steps.append(st)
        return st

    def skip(self, name, reason=""):
        self._seq += 1
        now = time.time() - self._t_start
        st = Step(seq=self._seq, name=name, status=SKIP,
                  t0=now, t1=now, error=reason)
        self.steps.append(st)
        return st

    # ---- 汇总
    @property
    def failed(self):
        return [s for s in self.steps if s.status == FAIL]

    @property
    def passed(self):
        return not self.failed and bool(self.steps)

    def verdict(self):
        if not self.steps:
            return BLOCKED               # 空 trace = 无法验证
        if self.failed:
            return FAIL
        return OK

    def summary(self):
        by_status = {}
        for s in self.steps:
            by_status[s.status] = by_status.get(s.status, 0) + 1
        return {
            "task": self.name,
            "verdict": self.verdict(),
            "steps": len(self.steps),
            "by_status": by_status,
            "failed": [s.name for s in self.failed],
            "elapsed": round(time.time() - self._t_start, 2),
        }

    def to_dict(self):
        return {
            "task": self.name,
            "started_at": self.started_at,
            "elapsed": round(time.time() - self._t_start, 2),
            "env": self.env_info,
            "verdict": self.verdict(),
            "steps": [s.to_dict() for s in self.steps],
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def save(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(self.to_json())
        return path

    @staticmethod
    def load(path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        tr = Trace(d.get("task", "task"))
        tr.started_at = d.get("started_at", "")
        tr.env_info = d.get("env", {})
        for sd in d.get("steps", []):
            st = Step(seq=sd["seq"], name=sd["name"],
                      kind=sd.get("kind", KIND_BUILD),
                      status=sd.get("status", OK),
                      t0=sd.get("t0", 0.0), t1=sd.get("t1", 0.0),
                      inputs=sd.get("inputs", {}),
                      outputs=sd.get("outputs", {}),
                      evidence=sd.get("evidence", {}),
                      error=sd.get("error", ""))
            tr.steps.append(st)
        tr._seq = max([s.seq for s in tr.steps] or [0])
        return tr

    def report(self):
        sm = self.summary()
        lines = ["=== 执行 Trace: %s ===" % self.name]
        if self.env_info:
            lines.append("  环境: " + ", ".join("%s=%s" % (k, v)
                                               for k, v in self.env_info.items()))
        lines.append("  %-4s %-30s %-6s %-8s %s"
                     % ("#", "步骤", "状态", "耗时", "证据"))
        lines.append("  " + "-" * 76)
        icon = {OK: "OK ", FAIL: "XX ", SKIP: "-- ", BLOCKED: "BLK"}
        for s in self.steps:
            ev = ", ".join("%s=%s" % (k, v) for k, v in s.evidence.items())
            if s.error:
                ev = (ev + " | " + s.error)[:44]
            lines.append("  %-4d %-30s [%s] %6.2fs %s"
                         % (s.seq, s.name[:30], icon[s.status], s.duration, ev))
        lines.append("  " + "-" * 76)
        lines.append("  verdict: %s   步骤 %d  耗时 %.1fs"
                     % (sm["verdict"].upper(), sm["steps"], sm["elapsed"]))
        if sm["failed"]:
            lines.append("  失败: %s" % ", ".join(sm["failed"]))
        return "\n".join(lines)

    def require_ok(self):
        """有失败就抛 SystemExit（携带完整 trace）。"""
        if not self.passed:
            print(self.report())
            raise SystemExit("执行 Trace 有失败步骤: %s"
                             % ", ".join(s.name for s in self.failed))
        return True


# ---------------------------------------------------------------- 便捷包装
def timed(trace, name, fn, kind=KIND_BUILD, **inputs):
    """包一个函数调用：自动记 step，成功记返回值，失败记异常并继续抛。"""
    with trace.step(name, kind=kind, **inputs) as s:
        r = fn()
        if isinstance(r, dict):
            s.outputs.update(r)
        elif r is not None:
            s.outputs["result"] = r
        return r


if __name__ == "__main__":
    import tempfile

    tr = Trace("selftest")
    tr.env(sw="2022 SP5", python="3.12")

    with tr.step("step1", kind=KIND_BUILD, depth=10) as s:
        s.output("volume", 1000.0)
        s.ev("dev_pct", 0.0)

    with tr.step("step2", kind=KIND_VERIFY) as s:
        s.ev("bodies", 1)

    tr.note("note1", key="value")
    tr.skip("step3", "不需要")

    # 故意失败
    try:
        with tr.step("step_fail") as s:
            raise ValueError("模拟失败")
    except ValueError:
        pass

    assert len(tr.steps) == 5
    by_name = {s.name: s for s in tr.steps}
    assert by_name["step_fail"].status == FAIL, by_name["step_fail"].status
    assert "模拟失败" in by_name["step_fail"].error
    assert by_name["step_fail"].evidence.get("fail_at"), "应记录失败位置"
    assert by_name["step3"].status == SKIP
    assert by_name["note1"].kind == KIND_NOTE
    assert tr.verdict() == FAIL
    assert not tr.passed

    print(tr.report())
    print()

    # 序列化往返
    tmp = os.path.join(tempfile.mkdtemp(), "t.json")
    tr.save(tmp)
    t2 = Trace.load(tmp)
    assert len(t2.steps) == 5
    assert {s.name: s for s in t2.steps}["step_fail"].status == FAIL
    assert t2.verdict() == FAIL

    # 空 trace → BLOCKED
    assert Trace("empty").verdict() == BLOCKED

    # 全成功 → OK
    tr2 = Trace("ok")
    with tr2.step("a") as s:
        pass
    assert tr2.passed and tr2.verdict() == OK

    print(">>> EXEC TRACE SELFTEST PASS")
