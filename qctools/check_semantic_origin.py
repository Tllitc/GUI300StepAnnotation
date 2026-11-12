#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原始标注数据语义质检（B / C / D 三类）：直接检查 agent_batch2_origin 下的 gui_XXXXXX.json，不需要先转 jsonl。

规则与 check_semantic_v1.py 完全一致（本脚本把每个 gui json 转成等价的 v1 记录后复用其 check_record），
检查项见 check_semantic_v1.py 的说明：
  B1 描述与动作类型不符 / B2 口径不统一(低风险) / C1 描述值≠text / C2 CoT 写了另一个值 / D 文本脏数据
不含格式检查（格式检查见 check_batch2_all.py），不对照截图，只做文本规则比对。

用法：
  python3 check_semantic_origin.py [目录或 json 文件 ...] [--out 报告.md] [--json 明细.json] [--title 标题]
  不传路径时检查整个 agent_batch2_origin/。

示例：
  python3 check_semantic_origin.py agent_batch2_origin/20261029
  python3 check_semantic_origin.py agent_batch2_origin/20261029 --out 语义问题报告_20261029.md --json 明细_20261029.json
  python3 check_semantic_origin.py agent_batch2_origin/20261029/Macos agent_batch2_origin/20261110

定位格式：批次/平台/分类/软件/gui_XXXXXX 步序号(截图文件名)。
步序号从 0 起，按整条轨迹（含追问后的后续片段）连续编号，与 step_N.png 的 N 一致；任务级问题无步序号。
多轮任务（含追问的第 2 条及之后的用户指令）只做任务文本的反引号/换行检查。
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_semantic_v1 as C  # noqa: E402

TASK_JSON_RE = re.compile(r"^gui_\d{6}\.json$")
DEFAULT_ROOT = HERE / "agent_batch2_origin"


def find_task_jsons(root):
    root = Path(root)
    if root.is_file():
        return [root]
    out = []
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            if TASK_JSON_RE.match(fn):
                out.append(Path(dp) / fn)
    return sorted(out)


def to_pseudo_record(data):
    """gui json -> 等价 v1 记录（只保留语义检查需要的字段）。
    返回 (rec, shots, extra_tasks)：shots[i] 是第 i 个被检查步骤的截图文件名；
    extra_tasks 是第 2 条及之后的用户指令。"""
    tasks, steps, cots, shots = [], [], [], []
    for seg in data.get("messages", []):
        role = seg.get("role")
        if role == "user":
            tasks.append(seg.get("instruction", "") or "")
        elif role == "assistant":
            for st in seg.get("trajectory", []) or []:
                acts = st.get("actions") or []
                first = acts[0] if acts else {}
                if first.get("action") == "screenshot":      # 与 v1 解析一致：合成截图步不计入
                    continue
                args = {k: v for k, v in first.items() if k != "element"}
                if "action" in args and args["action"] == "answer":
                    args["action"] = "call_user"
                tc = json.dumps({"name": "computer", "arguments": args}, ensure_ascii=False)
                content = (st.get("intent", "") or "") + ("\n<tool_call>\n" + tc + "\n</tool_call>" if acts else "")
                steps.append({"role": "assistant", "content": content})
                cots.append(st.get("CoT", "") or "")
                shots.append((st.get("observation") or {}).get("screenshot", ""))
    msgs = [{"role": "system", "content": ""}, {"role": "user", "content": tasks[0] if tasks else ""}] + steps
    return {"messages": msgs, "meta": {"cot": cots}}, shots, tasks[1:]


def group_key(path, root):
    """汇总分组：相对输入根目录的第一级目录（根为 agent_batch2_origin 时取 批次/平台）。"""
    try:
        rel = Path(path).relative_to(root)
    except ValueError:
        return Path(path).parent.name
    parts = rel.parts
    if len(parts) <= 1:
        return Path(root).name if Path(root).is_dir() else "(files)"
    if re.match(r"^\d{8}$", parts[0]) and len(parts) > 2:
        return f"{parts[0]}/{parts[1]}"
    if re.match(r"^\d{8}$", Path(root).name):
        return f"{Path(root).name}/{parts[0]}"
    return parts[0]


def task_label(path, root):
    root = Path(root)
    base = root.parent if root.is_dir() else root.parent.parent
    try:
        return str(Path(path).parent.relative_to(base)).replace(os.sep, "/")
    except ValueError:
        return str(Path(path).parent)


def run(inputs):
    rows, stats, failed = [], {}, []
    seen = set()
    for inp in inputs:
        root = Path(inp).resolve()
        for fp in find_task_jsons(root):
            if fp in seen:
                continue
            seen.add(fp)
            g = group_key(fp, root)
            st = stats.setdefault(g, dict(n=0, bad=0))
            st["n"] += 1
            tid = task_label(fp, root)
            try:
                data = json.load(open(fp, encoding="utf-8"))
                rec, shots, extra_tasks = to_pseudo_record(data)
                res = C.check_record(rec)
                for t in extra_tasks:
                    res += [r for r in C.check_record({"messages": [{"role": "system", "content": ""},
                                                                      {"role": "user", "content": t}],
                                                        "meta": {}}) if r[1] is None]
            except Exception as e:
                failed.append((str(fp), str(e)))
                continue
            for cat, step, desc, extra in res:
                shot = shots[step] if step is not None and step < len(shots) else ""
                rows.append(dict(group=g, task=tid, step=step, shot=shot, cat=cat, desc=desc, extra=extra))
            if res:
                st["bad"] += 1
    return rows, stats, failed


def write_md(rows, stats, failed, out, title):
    esc = C.esc
    cats = C.CATS
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["cat"]].append(r)
    total = sum(v["n"] for v in stats.values())
    bad = sum(v["bad"] for v in stats.values())
    o = [f"# {title}（B / C / D）\n",
         f"范围：{len(stats)} 个分组，共 {total} 条任务；有语义问题的任务 **{bad}** 条。\n",
         "说明：不含格式问题；不对照截图，仅文本规则比对。C 类里 text 与 CoT 谁是真值需看截图确认。\n",
         "定位格式：`批次/平台/分类/软件/gui_XXXXXX 步序号(截图文件名)`。步序号从 0 起，按整条轨迹连续编号；任务级问题无步序号。\n"]
    if failed:
        o.append(f"解析失败 {len(failed)} 个文件（未参与检查）：" + "；".join(f"`{p}`" for p, _ in failed[:20]) + "\n")
    short = ["B1", "B2", "C1", "C2", "D繁体", "D零宽(intent)", "D零宽(text)", "D动作词错字", "D缺动作词",
             "D观察/提问", "D混入指令", "D反引号", "D换行"]
    o.append("## 一、按分组汇总\n")
    o.append("| 分组 | 任务数 | 有问题任务 | " + " | ".join(short) + " |")
    o.append("|---|---:|---:|" + "---:|" * len(cats))
    for g, st in sorted(stats.items()):
        cnt = Counter(r["cat"] for r in rows if r["group"] == g)
        o.append(f"| {g} | {st['n']} | {st['bad']} | " + " | ".join(str(cnt[c] or "") for c in cats) + " |")
    o.append("\n列含义：" + "；".join(f"{a}={c.split(' ', 1)[1]}" for a, c in zip(short, cats)) + "\n")
    o.append("## 二、各类总数\n\n| 类别 | 数量 |\n|---|---:|")
    for c in cats:
        o.append(f"| {c} | {len(by_cat[c])} |")
    o.append("")
    sec = {"B1": "三、B 描述与动作不匹配", "C1": "四、C 输入值与描述 / CoT 矛盾", "D": "五、D 文本脏数据"}
    printed = set()
    task_level = ("D 任务文本含多余反引号", "D 任务文本含换行")
    three_col = ("D intent 动作词错字/残缺", "D intent 缺动作词(只写了对象)", "D intent 是观察/提问而非动作", "D type文本混入指令句")
    for c in cats:
        key = c.split(" ")[0]
        if key in sec and key not in printed:
            o.append(f"## {sec[key]}\n")
            printed.add(key)
        o.append(f"### {c}（{len(by_cat[c])}）\n")
        if not by_cat[c]:
            o.append("无。\n")
            continue
        if key in ("B1", "B2"):
            o.append("| 位置 | 描述(intent) | 实际动作 |\n|---|---|---|")
        elif key == "C1":
            o.append("| 位置 | 描述(intent) | 实际输入 text |\n|---|---|---|")
        elif key == "C2":
            o.append("| 位置 | 描述(intent) | text ⇢ CoT 中的值 |\n|---|---|---|")
        elif c in task_level:
            o.append("| 位置 | 任务文本末尾 |\n|---|---|")
        elif c in three_col:
            o.append("| 位置 | intent | " + ("text" if c == "D type文本混入指令句" else "动作") + " |\n|---|---|---|")
        else:
            o.append("| 位置 | 内容 |\n|---|---|")
        for r in by_cat[c]:
            pos = r["task"] + (f" 步{r['step']}({r['shot']})" if r["step"] is not None else "")
            if c in task_level or not (key in ("B1", "B2", "C1", "C2") or c in three_col):
                o.append(f"| {pos} | {esc(r['desc'])} |")
            else:
                o.append(f"| {pos} | {esc(r['desc'])} | {esc(r['extra'])} |")
        o.append("")
    Path(out).write_text("\n".join(o) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="原始标注数据（gui_XXXXXX.json）语义质检")
    ap.add_argument("paths", nargs="*", help="目录或 gui json 文件，默认 agent_batch2_origin/")
    ap.add_argument("--out", default=None, help="输出 md 报告")
    ap.add_argument("--json", default=None, help="输出 json 明细")
    ap.add_argument("--title", default="原始数据语义问题报告")
    args = ap.parse_args()
    inputs = args.paths or [str(DEFAULT_ROOT)]
    for p in inputs:
        if not os.path.exists(p):
            print(f"[ERROR] 路径不存在: {p}")
            sys.exit(1)
    rows, stats, failed = run(inputs)
    cnt = Counter(r["cat"] for r in rows)
    print(f"分组 {len(stats)}，任务 {sum(v['n'] for v in stats.values())}，"
          f"有问题任务 {sum(v['bad'] for v in stats.values())}，解析失败 {len(failed)}")
    for c in C.CATS:
        print(f"  {c}: {cnt[c]}")
    for p, e in failed[:10]:
        print(f"  [解析失败] {p}: {e}")
    if args.out:
        write_md(rows, stats, failed, args.out, args.title)
        print("报告:", args.out)
    if args.json:
        Path(args.json).write_text(json.dumps(dict(rows=rows, stats=stats, failed=failed), ensure_ascii=False),
                                   encoding="utf-8")
        print("明细:", args.json)


if __name__ == "__main__":
    main()
