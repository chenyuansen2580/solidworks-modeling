# -*- coding: utf-8 -*-
"""capabilities.yaml 加载器 —— 能力清单的单一真相源。

## 设计

- 有 pyyaml → 用它解析（完整）
- 没有 pyyaml → 用内置轻量解析器（只解析本仓库用到的子集：
  映射、列表、块标量 |、行内列表 [a, b]）

## 用途

    import capabilities_loader as CL
    caps = CL.load()                  # {id: {level, label, limitations, ...}}
    by_level = CL.by_level()          # {'verified': [...], 'pilot': [...]}
    assert CL.count('verified') == 38

    # swlib_v2 从本加载器构建 CAPABILITIES，不再手写
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
YAML_PATH = os.path.join(os.path.dirname(HERE), "capabilities.yaml")

VERIFIED = "verified"
PILOT = "pilot"
NOT_IMPLEMENTED = "not_implemented"
REFERENCE_ONLY = "reference_only"

try:
    import yaml as _yaml
except ImportError:
    _yaml = None


# ---------------------------------------------------------------- 轻量解析
def _strip_comment(line):
    # 只处理行首 # 和 " # "，不碰字符串里的 #
    s = line.rstrip()
    if s.lstrip().startswith("#"):
        return ""
    i = s.find(" # ")
    return s[:i] if i > 0 else s


def _inline_list(v):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [x.strip().strip('"').strip("'") for x in re.split(r",\s*", inner)]
    return [v.strip('"').strip("'")]


def _mini_yaml(text):
    """解析本仓库 capabilities.yaml 用到的子集。

    支持：
      key: value
      key: [a, b]
      key:
        - item
        - item
      key: |
        line1
        line2
    """
    root = {}
    stack = [(-1, root)]
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = _strip_comment(raw)
        if not line.strip():
            i += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        s = line.strip()

        # 弹出更深的层级
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if s.startswith("- "):
            item = s[2:].strip()
            if isinstance(parent, list):
                if ":" in item:
                    # "- id: xxx" → 新建 dict，后续缩进键属于它
                    k, v = item.split(":", 1)
                    d = {k.strip(): v.strip().strip('"').strip("'")}
                    parent.append(d)
                    stack.append((indent, d))
                else:
                    parent.append(item.strip('"').strip("'"))
            i += 1
            continue

        if ":" not in s:
            i += 1
            continue
        key, val = s.split(":", 1)
        key = key.strip()
        val = val.strip()

        if val == "|":
            # 块标量：收后续缩进行
            block = []
            i += 1
            while i < len(lines):
                nxt = _strip_comment(lines[i])
                if not nxt.strip():
                    block.append("")
                    i += 1
                    continue
                nind = len(nxt) - len(nxt.lstrip(" "))
                if nind <= indent:
                    break
                block.append(nxt.strip())
                i += 1
            parent[key] = "\n".join(block)
            continue

        if val == "":
            # 判断下一行是列表还是映射
            j = i + 1
            kind = {}
            while j < len(lines):
                nxt = _strip_comment(lines[j])
                if not nxt.strip():
                    j += 1
                    continue
                nind = len(nxt) - len(nxt.lstrip(" "))
                if nind <= indent:
                    break
                kind = [] if nxt.strip().startswith("- ") else {}
                break
            parent[key] = kind
            stack.append((indent, parent[key]))
            i += 1
            continue

        if val.startswith("[") and val.endswith("]"):
            parent[key] = _inline_list(val)
        else:
            parent[key] = val.strip('"').strip("'")
        i += 1

    return root


# ---------------------------------------------------------------- 公开 API
def load(path=None, use_cache=True):
    """加载 capabilities.yaml，返回完整 dict。"""
    global _CACHE
    p = path or YAML_PATH
    if use_cache and p == YAML_PATH and _CACHE is not None:
        return _CACHE
    with open(p, encoding="utf-8") as f:
        text = f.read()
    d = _yaml.safe_load(text) if _yaml else _mini_yaml(text)
    if p == YAML_PATH and use_cache:
        _CACHE = d
    return d


_CACHE = None


def capabilities(path=None):
    """返回 {id: capability_dict}。"""
    d = load(path)
    out = {}
    for c in d.get("capabilities", []):
        if isinstance(c, dict) and "id" in c:
            out[c["id"]] = c
    return out


def by_level(path=None):
    """返回 {level: [id, ...]}。"""
    out = {}
    for cid, c in capabilities(path).items():
        lv = c.get("level", REFERENCE_ONLY)
        out.setdefault(lv, []).append(cid)
    for v in out.values():
        v.sort()
    return out


def count(level, path=None):
    return len(by_level(path).get(level, []))


def level_of(cid, path=None):
    c = capabilities(path).get(cid)
    return c.get("level", REFERENCE_ONLY) if c else REFERENCE_ONLY


def limitations_of(cid, path=None):
    c = capabilities(path).get(cid)
    return c.get("limitations", []) if c else []


def to_swlib_table(path=None):
    """转成 swlib_v2.CAPABILITIES 的 (LEVEL, note) 格式。"""
    caps = capabilities(path)
    out = {}
    for cid, c in caps.items():
        lv = c.get("level", REFERENCE_ONLY)
        note = c.get("label", "")
        if c.get("limitations"):
            note += "；" + "；".join(str(x) for x in c["limitations"][:2])
        out[cid] = (lv, note[:120])
    return out


if __name__ == "__main__":
    d = load()
    caps = capabilities()
    bl = by_level()
    print("schema:", d.get("schema_version"))
    print("后端:", len(d.get("backend_catalog", {})))
    print("路由:", len(d.get("operation_routes", [])))
    print("能力总数:", len(caps))
    for lv in (VERIFIED, PILOT, NOT_IMPLEMENTED):
        print("  %-18s %d" % (lv, len(bl.get(lv, []))))
    print("解析器:", "pyyaml" if _yaml else "mini")

    # 无 pyyaml 时也要能解析出相同能力数
    if _yaml:
        mini = _mini_yaml(open(YAML_PATH, encoding="utf-8").read())
        mini_caps = [c for c in mini.get("capabilities", []) if isinstance(c, dict) and "id" in c]
        assert len(mini_caps) == len(caps), \
            "mini 解析器得到 %d，pyyaml 得到 %d" % (len(mini_caps), len(caps))
        print("mini 解析器一致性: OK (%d)" % len(mini_caps))

    # 与 swlib_v2 现有表对齐
    import sys
    sys.path.insert(0, HERE)
    import swlib_v2 as V
    my = to_swlib_table()
    missing = set(V.CAPABILITIES) - set(my)
    extra = set(my) - set(V.CAPABILITIES)
    assert not missing, "yaml 缺少 swlib_v2 的能力: %s" % missing
    assert not extra, "yaml 多了 swlib_v2 没有的能力: %s" % extra
    mismatch = [k for k in V.CAPABILITIES
                if V.CAPABILITIES[k][0] != my[k][0]]
    assert not mismatch, "等级不一致: %s" % mismatch
    print("与 swlib_v2 对齐: OK (%d 项)" % len(my))
    print(">>> CAPABILITIES LOADER PASS")
