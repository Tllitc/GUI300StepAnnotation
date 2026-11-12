#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1 JSONL 语义质检（B / C / D 三类），不含格式检查（格式检查见 check_agent_batch2_v1.py）。

检查项（按 assistant 的每一步：intent + tool_call + meta.cot）：
  B1 描述与动作类型不符      intent 说“输入/双击/滚动…”，实际 action 不是对应类型
  B2 口径不统一（低风险）：网址栏输入→open_url/open_app；“点击X app”→open_app；“打开X app”→click；“回到桌面”→open_app/drag
  C1 描述里的值 ≠ 实际输入 text
  C2 描述与 text 一致，但 CoT 写了另一个值
  D  文本脏数据：繁体字 / 零宽字符 / intent 不规范 / type 文本混入指令句 / 任务文本含反引号或换行

不对照截图，只做文本规则比对；C 类中 text 与 CoT 谁是真值需结合截图确认。

用法：
  python3 check_semantic_v1.py [文件或目录 ...] [--out 报告.md] [--json 明细.json]
  不传路径时检查 platforms/*.jsonl。

定位格式：文件名#jsonl 行号 任务(source_json 去前缀) 步序号；
步序号从 0 起（= images 下标），在 messages 中对应第 (步序号 + 1) 条非合成截图的 assistant 消息。
"""
import argparse
import glob
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TC_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
ANALYZE_PREFIX = "分析当前界面："
ZW_RE = re.compile("[\u200b\u200c\u200d\ufeff\u2060]")
TRAD_RE = re.compile(r"[輸鍵點擊開關擇單機]")
NORMAL_INTENT_RE = re.compile(
    r"^(打开|启动)|^(用|使用|通过).{0,25}打开|^(左键|右键|中键|中间)?(单击|点击|双击|三击|三件)"
    r"|^(用|将)?鼠标|^(向|往)(上|下|左|右)")


# 动作词本身残缺/错字：左键单“X”、左间单击、左键打击、反击、单机、键单击 等（重复字如“点击点击”不算）
BROKEN_VERB_RE = re.compile(
    r"(?:左键|右键|中键)(?:单|双|三)(?!击|单击)"      # 漏“击”
    r"|左[间见建健]单击|左键打击|反击(?!败)|单机(?!游戏)"  # 错字
    r"|(?<![左右中])键单击"                       # 漏“左”
)

OBSERVE_RE = re.compile(r"^(检测到|发现|请问|当前界面|当前页面|页面上)")
VERB_START_RE = re.compile(
    r"^(点击|单击|双击|三击|轻点|点按|选择|选中|勾选|取消|输入|填写|键入|粘贴|复制|打开|启动|关闭|滑动|滚动|拖|拖拽|拖动|"
    r"按下|长按|等待|搜索|点赞|收藏|关注|分享|切换|查看|进入|删除|发送|保存|确认|展开|刷新|移动|悬停|下拉|上滑|下滑|"
    r"向|往|将|把|用|使用|通过|在|回到|返回到|返回上|向上|向下|调整|修改|设置|新建|重命名|关闭|添加|截图|录入|等)")
OBJ_TAIL_RE = re.compile(r"(按钮|标签|图标|入口|选项|链接|卡片|控件|输入框|搜索框|页面|栏|小说|帖子|商品|视频|文件|评论|好友|圈子|话题|路线|课程)$")


def is_object_only(it):
    """只写了对象、没有动作词，如“返回按钮”“第一个帖子”“左键“角度”按钮”。"""
    if re.search(r"[点击单]", it[:6]):      # “左键单X”“反击”“点X”等属于措辞笔误，不算缺动作词
        return False
    t = re.sub(r"^(左键|右键|中键)", "", it).strip()
    if VERB_START_RE.match(t):
        return False
    if re.match(r"^[“\"]", t) or re.match(r"^第[一二三四五六七八九十\d]+", t) or OBJ_TAIL_RE.search(t):
        return True
    return bool(re.match(r"^(返回|更多|设置|我的|首页)", t) and OBJ_TAIL_RE.search(t))


FIELD_SUFFIX_RE = re.compile(r"^\s*的?(?:输入框|文本框|搜索框|单元格|按钮|标签|栏|面板|窗口|页面|界面|图标|选项|区域|控件|文件夹|菜单)")


def quoted(t):
    return re.findall(r"[“\"]([^”\"]{1,200})[”\"]", t)


def value_quoted(t):
    """引号内的“值”：排除后面紧跟“输入框/按钮/单元格…”的控件名。"""
    out = []
    for m in re.finditer(r"[“\"]([^”\"]{1,200})[”\"]", t):
        if not FIELD_SUFFIX_RE.match(t[m.end():]):
            out.append(m.group(1))
    return out


def nm(x):
    x = unicodedata.normalize("NFKC", str(x)).lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", x)


def classify(it):
    """intent 期望对应的 action 集合；无法判断返回 None。"""
    if re.match(r"^(按下)?系统按键|^按下系统", it):
        return {"system_button"}
    if re.match(r"^(打开|启动)“[^”]+”\s*(?:app|APP|App|应用)", it):
        return {"open_app"}
    if re.search(r"网址|open_url|浏览器打开", it) and re.match(r"^(用|使用|通过)", it):
        return {"open_url", "open_app"}
    if re.match(r"^(在键盘.{0,4}|)按下", it) or re.match(r"^(使用)?快捷键", it):
        return {"key", "system_button"}
    if re.match(r"^(将|把)?鼠标(移动|悬停)|^移动鼠标", it):
        return {"mouse_move"}
    if re.match(r"^(左键)?双击", it):
        return {"double_click"}
    if re.match(r"^(左键)?三击", it):
        return {"triple_click"}
    if re.match(r"^右键", it):
        return {"right_click"}
    if re.match(r"^中键", it):
        return {"middle_click"}
    if re.match(r"^(左键)?单击|^点击|^轻点|^点按|^(取消)?(选择|选中|勾选)", it):
        return {"click", "left_click"}
    if re.match(r"^长按", it):
        return {"long_press"}
    if re.search(r"拖拽|拖动", it) and re.match(r"^(用鼠标|鼠标|将|把|拖)", it):
        return {"left_click_drag", "drag", "swipe"}
    if re.search(r"滑动", it) and re.match(r"^(向|往)", it):
        return {"swipe"}
    if re.search(r"滚动", it) and re.match(r"^(向|往|将|滚动)", it):
        return {"scroll"}
    if re.match(r"^(在|向|往).{0,25}(?:输入|輸入|填写|键入|粘贴|搜索)", it) or re.match(r"^(?:输入|輸入|填写|键入)", it):
        return {"type"}
    if re.match(r"^(打开|启动)“[^”]+”$", it):
        return {"open_app", "open_url"}
    if re.match(r"^等待", it):
        return {"wait"}
    return None


# --------------------------------------------------------------------- 解析
def parse_steps(rec):
    """返回 (task, [step])，step=dict(i,intent,action,args,cot)。跳过合成截图轮。"""
    msgs = rec["messages"]
    task = msgs[1]["content"]
    if task.startswith("<|image|>"):
        task = task[len("<|image|>"):].lstrip("\n")
    cots = (rec.get("meta") or {}).get("cot") or []
    steps = []
    for m in msgs[2:]:
        if m["role"] != "assistant":
            continue
        c = m["content"]
        head = c.split("<tool_call>")[0].strip()
        tcs = []
        for raw in TC_RE.findall(c):
            try:
                tcs.append(json.loads(raw))
            except Exception:
                pass
        if tcs and tcs[0].get("arguments", {}).get("action") == "screenshot":
            continue
        i = len(steps)
        action, args = ("", {})
        if tcs:
            args = tcs[0].get("arguments", {}) or {}
            action = args.get("action", "")
        steps.append(dict(i=i, intent=head, action=action, args=args,
                          cot=cots[i] if len(cots) > i else ""))
    return task, steps


# --------------------------------------------------------------------- 检查
def check_record(rec):
    """返回 [(类别, 步序号或None, 描述, 附加)]"""
    out = []
    task, steps = parse_steps(rec)
    if "`" in task:
        out.append(("D 任务文本含多余反引号", None, task[-26:].replace("\n", "\\n"), ""))
    if "\n" in re.sub(r"“[^”]{30,}”", "", task.strip(), flags=re.S):
        out.append(("D 任务文本含换行", None, repr(task[-30:]), ""))
    for s in steps:
        a, args = s["action"], s["args"]
        if a in ("terminate", "") and not s["intent"].strip():
            continue
        it = s["intent"]
        if it.startswith(ANALYZE_PREFIX):
            it = it[len(ANALYZE_PREFIX):]
        it = it.strip()
        txt = str(args.get("text", ""))
        i = s["i"]
        if a in ("terminate", "call_user", "answer", ""):
            continue
        # D：字符类
        if ZW_RE.search(txt):
            out.append(("D 零宽字符(type/open 文本)", i, it[:50], ""))
        if ZW_RE.search(it):
            out.append(("D 零宽字符(intent)", i, it[:50], ""))
        if TRAD_RE.search(re.sub(r"“[^”]*”", "", it)):
            out.append(("D 繁体字(intent)", i, it[:50], ""))
        m_bv = BROKEN_VERB_RE.search(re.sub(r"“[^”]*”", "“”", it))
        if m_bv:
            out.append(("D intent 动作词错字/残缺", i, it[:50], a))
        # B
        exp = classify(it)
        if exp and "scroll" in exp and a == "swipe" or exp and "swipe" in exp and a == "scroll":
            exp = None
            skip_unclass = True
        else:
            skip_unclass = False
        if exp and a not in exp:
            if re.match(r"^向.滑动鼠标", it) and a == "scroll":
                pass
            elif re.search(r"(滚动条|滑动条)", it) and a == "left_click_drag":
                pass
            elif re.match(r"^左键双击“WPS", it) and a == "open_app":
                pass
            elif "网址输入框" in it and a in ("open_url", "open_app"):
                out.append(("B2 口径不统一(低风险)", i, it[:50], a))
            elif re.match(r"^点击“[^”]+”\s*(?:app|APP|App|应用)", it) and a == "open_app":
                out.append(("B2 口径不统一(低风险)", i, it[:50], a))
            elif re.match(r"^(打开|启动)“[^”]+”\s*(?:app|APP|App|应用)$", it) and a == "click":
                out.append(("B2 口径不统一(低风险)", i, it[:50], a))
            elif re.search(r"回到桌面", it) and a in ("open_app", "drag", "swipe", "system_button"):
                out.append(("B2 口径不统一(低风险)", i, it[:50], a))
            else:
                out.append(("B1 描述与动作类型不符", i, it[:60], a))
        if exp is None and not skip_unclass and not NORMAL_INTENT_RE.match(it):
            if OBSERVE_RE.match(it):
                out.append(("D intent 是观察/提问而非动作", i, it[:50], a))
            elif is_object_only(it):
                out.append(("D intent 缺动作词(只写了对象)", i, it[:50], a))
        # C
        if a == "type":
            if re.match(r"^在.{1,12}中?输入“.+”$", txt):
                out.append(("D type文本混入指令句", i, it[:40], txt[:30]))
            th_m = re.search(r"【下步思考】：(.*)", s["cot"] or "", re.S)
            th = th_m.group(1) if th_m else ""
            q = [x for x in value_quoted(it) if nm(x)]
            if q and nm(txt) and not any(nm(x) in nm(txt) or nm(txt) in nm(x) for x in q):
                out.append(("C1 描述里的值≠实际text", i, it[:40], txt[:40]))
            elif nm(txt) and s["cot"] and nm(txt) not in nm(th) and nm(txt) not in nm(s["cot"]):
                qs = value_quoted(th)
                if qs and all(nm(x) != nm(txt) and nm(x) not in nm(txt) and nm(txt) not in nm(x) for x in qs):
                    out.append(("C2 CoT写了另一个值", i, it[:36], f"{txt[:30]} ⇢ CoT:{qs[0][:30]}"))
    return out


def task_id(rec):
    sj = (rec.get("meta") or {}).get("source_json", "")
    sj = sj.replace("agent_batch2_origin/", "")
    parts = sj.split("/")
    return "/".join(parts[:-1]) if parts else sj


CATS = ["B1 描述与动作类型不符", "B2 口径不统一(低风险)", "C1 描述里的值≠实际text",
        "C2 CoT写了另一个值", "D 繁体字(intent)", "D 零宽字符(intent)", "D 零宽字符(type/open 文本)",
        "D intent 动作词错字/残缺", "D intent 缺动作词(只写了对象)", "D intent 是观察/提问而非动作", "D type文本混入指令句", "D 任务文本含多余反引号", "D 任务文本含换行"]


def run(paths):
    rows = []  # dict(file,line,task,step,cat,desc,extra,plat)
    stats = {}
    for p in paths:
        name = os.path.basename(p)
        n = 0
        bad_tasks = set()
        for ln, l in enumerate(open(p, encoding="utf-8"), 1):
            if not l.strip():
                continue
            rec = json.loads(l)
            n += 1
            tid = task_id(rec)
            try:
                res = check_record(rec)
            except Exception as e:  # 解析异常不应中断
                res = [("D intent 缺动作词(只写了对象)", None, f"解析异常: {e}", "")]
            for cat, step, desc, extra in res:
                rows.append(dict(file=name, line=ln, task=tid, step=step, cat=cat, desc=desc, extra=extra))
                bad_tasks.add(ln)
        stats[name] = dict(n=n, bad=len(bad_tasks))
    return rows, stats


def esc(s):
    return str(s).replace("|", "\\|").replace("\n", "\\n").replace("\u200b", "⟦ZW⟧").replace("\u200c", "⟦ZW⟧") \
        .replace("\u200d", "⟦ZW⟧").replace("\ufeff", "⟦ZW⟧").replace("\u2060", "⟦ZW⟧")


def short(name):
    return name.replace("agent_batch2_", "").replace("_v1.jsonl", "")


def write_md(rows, stats, out, title="语义问题报告"):
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["cat"]].append(r)
    o = [f"# {title}（B / C / D）\n"]
    total = sum(v["n"] for v in stats.values())
    bad = sum(v["bad"] for v in stats.values())
    o.append(f"范围：{len(stats)} 个文件，共 {total} 条任务；有语义问题的任务 **{bad}** 条。\n")
    o.append("说明：不含格式问题；不对照截图，仅文本规则比对。C 类里 text 与 CoT 谁是真值需看截图确认。\n")
    o.append(f"定位格式：`文件名(去 agent_batch2_ / _v1.jsonl)#jsonl 行号 任务路径 步序号`。"
             f"步序号从 0 起（= images 下标）；任务级问题无步序号。\n")
    o.append("## 一、按文件汇总\n")
    SHORT = ["B1", "B2", "C1", "C2", "D繁体", "D零宽(intent)", "D零宽(text)", "D动作词错字", "D缺动作词", "D观察/提问", "D混入指令", "D反引号", "D换行"]
    o.append("| 文件 | 任务数 | 有问题任务 | " + " | ".join(SHORT) + " |")
    o.append("|---|---:|---:|" + "---:|" * len(CATS))
    for name, st in stats.items():
        cnt = Counter(r["cat"] for r in rows if r["file"] == name)
        o.append(f"| {short(name)} | {st['n']} | {st['bad']} | " + " | ".join(str(cnt[c] or "") for c in CATS) + " |")
    o.append("\n列含义：" + "；".join(f"{a}={c.split(' ', 1)[1]}" for a, c in zip(SHORT, CATS)) + "\n")
    o.append("## 二、各类总数\n\n| 类别 | 数量 |\n|---|---:|")
    for c in CATS:
        o.append(f"| {c} | {len(by_cat[c])} |")
    o.append("")
    heads = {
        "B": ("描述(intent)", "实际动作"), "C1": ("描述(intent)", "实际输入 text"),
        "C2": ("描述(intent)", "text ⇢ CoT 中的值"),
    }
    sec = {"B1": "三、B 描述与动作不匹配", "C1": "四、C 输入值与描述 / CoT 矛盾", "D": "五、D 文本脏数据"}
    printed = set()
    for c in CATS:
        key = c.split(" ")[0]
        if key in sec and key not in printed:
            o.append(f"## {sec[key]}\n")
            printed.add(key)
        elif key == "B2" and "B" not in printed:
            pass
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
        elif c in ("D 任务文本含多余反引号", "D 任务文本含换行"):
            o.append("| 位置 | 任务文本末尾 |\n|---|---|")
        elif c in ("D intent 动作词错字/残缺", "D intent 缺动作词(只写了对象)", "D intent 是观察/提问而非动作"):
            o.append("| 位置 | intent | 动作 |\n|---|---|---|")
        elif c == "D type文本混入指令句":
            o.append("| 位置 | intent | text |\n|---|---|---|")
        else:
            o.append("| 位置 | 内容 |\n|---|---|")
        for r in by_cat[c]:
            pos = f"{short(r['file'])}#{r['line']} {r['task']}" + (f" 步{r['step']}" if r["step"] is not None else "")
            if key in ("B1", "B2", "C1", "C2") or c in ("D intent 动作词错字/残缺", "D intent 缺动作词(只写了对象)", "D intent 是观察/提问而非动作", "D type文本混入指令句"):
                o.append(f"| {pos} | {esc(r['desc'])} | {esc(r['extra'])} |")
            else:
                o.append(f"| {pos} | {esc(r['desc'])} |")
        o.append("")
    Path(out).write_text("\n".join(o) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--title", default="语义问题报告")
    args = ap.parse_args()
    paths = []
    for p in args.paths or [str(HERE / "platforms")]:
        if os.path.isdir(p):
            paths += sorted(glob.glob(os.path.join(p, "*.jsonl")))
        else:
            paths.append(p)
    rows, stats = run(paths)
    cnt = Counter(r["cat"] for r in rows)
    print(f"文件 {len(paths)}，任务 {sum(v['n'] for v in stats.values())}，有问题任务 {sum(v['bad'] for v in stats.values())}")
    for c in CATS:
        print(f"  {c}: {cnt[c]}")
    if args.out:
        write_md(rows, stats, args.out, args.title)
        print("报告:", args.out)
    if args.json:
        Path(args.json).write_text(json.dumps(dict(rows=rows, stats=stats), ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
