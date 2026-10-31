# -*- coding: utf-8 -*-
"""一致性不变量断言工具（INV-1 ~ INV-10）

assert_all 适用于任务进行中的编辑现场；任务完成后请用 assert_final_json。
"""
import copy
import json
import os
import re

from annotation_editor import StepListItemWidget
from helpers import drain_sidebar_thumbs, flush_events

PNG_NAME_RE = re.compile(r"^gui_(\d{6})_\d{4}\.png$")


def _step_screenshots(steps):
    return [s.get("screenshot") for s in steps if s.get("screenshot")]


def _round_screenshots(rounds):
    refs = []
    for rnd in rounds:
        for t in rnd.get("trajectory") or []:
            fn = (t.get("observation") or {}).get("screenshot")
            if fn:
                refs.append(fn)
    return refs


def assert_model(editor):
    """INV-1 模型连续：steps_data 下标连续、每步 screenshot 非空"""
    steps = editor.steps_data
    assert isinstance(steps, list)
    assert 0 <= editor.current_step <= len(steps), \
        f"current_step 越界: {editor.current_step} / {len(steps)}"
    for i, step in enumerate(steps):
        fn = step.get("screenshot")
        assert isinstance(fn, str) and fn, f"第 {i} 步 screenshot 为空"
        assert "action_data" in step and "intent" in step, f"第 {i} 步缺字段"


def assert_files(editor, allow_orphans=False):
    """INV-2 引用存在 / INV-3 图步单射 / INV-4 无孤儿 / INV-5 命名规范

    孤儿判定把 steps_data、rounds（trajectory/observation/screenshot）以及
    当前在途未确认截图（_current_screenshot_filename）计入可达集。
    """
    gui_dir = editor.gui_dir
    gui_number = editor.gui_number
    steps_refs = _step_screenshots(editor.steps_data)
    round_refs = _round_screenshots(editor.rounds)
    reachable = set(steps_refs) | set(round_refs)
    if editor._current_screenshot_filename:
        reachable.add(editor._current_screenshot_filename)

    # INV-5 命名规范（引用与磁盘双侧）
    for fn in reachable:
        m = PNG_NAME_RE.match(fn)
        assert m, f"截图命名不规范: {fn}"
        assert m.group(1) == gui_number, f"截图 gui 编号不符: {fn}"

    # INV-2 引用存在
    for fn in sorted(reachable):
        assert os.path.isfile(os.path.join(gui_dir, fn)), f"引用的截图不存在: {fn}"

    # INV-3 图步单射：当前轮 steps_data 内 + 每轮 trajectory 内
    assert len(steps_refs) == len(set(steps_refs)), \
        f"steps_data 内截图被多个步骤引用: {steps_refs}"
    for r, rnd in enumerate(editor.rounds):
        refs = _round_screenshots([rnd])
        assert len(refs) == len(set(refs)), f"第 {r} 轮内截图重复引用: {refs}"

    # INV-4 无孤儿 + 磁盘命名规范
    if gui_dir and os.path.isdir(gui_dir):
        disk_pngs = [name for name in os.listdir(gui_dir) if name.endswith(".png")]
        for name in disk_pngs:
            assert PNG_NAME_RE.match(name), f"磁盘截图命名不规范: {name}"
        if not allow_orphans:
            orphans = [name for name in disk_pngs if name not in reachable]
            assert not orphans, f"存在孤儿截图: {orphans}"


def _expected_draft_steps(editor):
    """按 _write_draft_now 的轮次边界重建逻辑推导草稿应含步骤"""
    if editor._current_round_saved and editor.rounds:
        last = editor.rounds[-1]
        coords_by_step = {c.get("step"): c for c in last.get("coords") or []
                          if isinstance(c, dict)}
        expected = []
        for t in last.get("trajectory") or []:
            obs = t.get("observation") or {}
            actions = t.get("actions") or []
            coord_entry = coords_by_step.get(t.get("step"), {})
            expected.append({
                "screenshot": obs.get("screenshot", ""),
                "intent": t.get("intent", ""),
                "action_data": copy.deepcopy(actions[0]) if actions else {},
                "vertices": copy.deepcopy(coord_entry.get("vertices")),
            })
        return expected
    return [{
        "screenshot": s.get("screenshot", ""),
        "intent": s.get("intent", ""),
        "action_data": copy.deepcopy(s.get("action_data") or {}),
        "vertices": copy.deepcopy(s.get("vertices")),
    } for s in editor.steps_data]


def assert_draft(editor):
    """INV-6 草稿一致：主动 _write_draft_now 后 json.load 逐条比对

    注意：_write_draft_now 内部会 _save_current_to_steps 把在途表单并入
    steps_data，请在稳定检查点（截图已确认或在途截图不存在）调用。
    空现场（无 steps 且无 rounds）产品按设计不写草稿，返回 None。
    """
    editor._write_draft_now()
    flush_events()
    if not editor.steps_data and not editor.rounds:
        return None
    draft = editor.data_manager.load_draft(editor.gui_number)
    assert draft is not None, "草稿未写入或无法解析"
    assert str(draft.get("gui_number")).zfill(6) == editor.gui_number
    expected_steps = _expected_draft_steps(editor)
    got = draft.get("steps_data")
    assert isinstance(got, list)
    assert len(got) == len(expected_steps), \
        f"草稿步数 {len(got)} != 内存 {len(expected_steps)}"
    for i, (g, e) in enumerate(zip(got, expected_steps)):
        assert g.get("screenshot") == e["screenshot"], f"草稿第 {i} 步 screenshot 不一致"
        assert g.get("intent") == e["intent"], f"草稿第 {i} 步 intent 不一致"
        assert g.get("action_data") == e["action_data"], f"草稿第 {i} 步 action_data 不一致"
        assert g.get("vertices") == e["vertices"], f"草稿第 {i} 步 vertices 不一致"
    assert draft.get("rounds") == editor.rounds, "草稿 rounds 与内存不一致"
    idx = draft.get("current_step_index")
    assert isinstance(idx, int) and 0 <= idx <= len(got), \
        f"草稿 current_step_index 非法: {idx}"
    return draft


def assert_sidebar(editor):
    """INV-8 侧栏一致：条目数==len(steps_data)、序号连续、缩略图与文件一致"""
    sidebar = editor.sidebar
    steps = editor.steps_data
    assert len(sidebar.item_widgets) == len(steps), \
        f"侧栏条目数 {len(sidebar.item_widgets)} != 步骤数 {len(steps)}"
    for i, item in enumerate(sidebar.item_widgets):
        assert item.step_index == i, f"条目序号错位: {item.step_index} != {i}"
        assert item.number_label.text() == f"第 {i + 1} 步"
    # 缩略图缓存不得残留已删除文件
    gui_dir = editor.gui_dir or ""
    for key in list(sidebar._thumb_cache.keys()):
        fn = key[0] if key else None
        if fn:
            assert os.path.isfile(os.path.join(gui_dir, fn)), \
                f"缩略图缓存残留已删文件: {fn}"
    # 懒加载排空后逐条比对缩略图像素与步骤文件，防止错位
    drain_sidebar_thumbs(editor)
    for i, item in enumerate(sidebar.item_widgets):
        assert item.thumb_loaded, f"第 {i} 步缩略图未加载"
        step = steps[i]
        fn = step.get("screenshot")
        if not fn or not os.path.isfile(os.path.join(gui_dir, fn)):
            continue
        pixmap = item.thumb_label.pixmap()
        assert pixmap is not None and not pixmap.isNull(), f"第 {i} 步缩略图缺失"
        expected = editor.build_marked_preview(fn, step.get("vertices"),
                                               StepListItemWidget.THUMB_SIZE)
        if expected is not None:
            assert pixmap.toImage() == expected.toImage(), \
                f"第 {i} 步缩略图与文件 {fn} 不一致"


def assert_transient(editor):
    """INV-9 瞬态复位"""
    assert editor._screenshot_in_progress is False, "截图锁未释放"
    assert editor._insert_after_index is None, \
        f"插入锚点残留: {editor._insert_after_index}"
    assert editor._swipe_measuring is False, "swipe 测量态残留"
    assert editor._scroll_measuring is False, "scroll 测量态残留"


def assert_final_json(gui_dir, gui_number):
    """INV-7 最终 JSON/coords：step 连续、截图存在且按业务顺序、coords 对齐

    :return: 解析后的主 JSON dict
    """
    gui_dir = str(gui_dir)
    json_path = os.path.join(gui_dir, f"gui_{gui_number}.json")
    coords_path = os.path.join(gui_dir, f"gui_{gui_number}_coords.json")
    assert os.path.isfile(json_path), f"最终 JSON 缺失: {json_path}"
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    messages = data.get("messages") or []
    assert len(messages) >= 2 and len(messages) % 2 == 0, "messages 结构异常"

    flat_steps = []
    for r in range(0, len(messages), 2):
        user_msg, asst_msg = messages[r], messages[r + 1]
        assert user_msg.get("role") == "user"
        assert asst_msg.get("role") == "assistant"
        trajectory = asst_msg.get("trajectory") or []
        seen = set()
        for j, step in enumerate(trajectory):
            assert step.get("step") == j, \
                f"第 {r // 2} 轮 step 不连续: {step.get('step')} != {j}"
            fn = (step.get("observation") or {}).get("screenshot")
            assert fn, f"第 {r // 2} 轮第 {j} 步 screenshot 为空"
            m = PNG_NAME_RE.match(fn)
            assert m and m.group(1) == gui_number, f"截图命名不规范: {fn}"
            assert os.path.isfile(os.path.join(gui_dir, fn)), f"截图文件不存在: {fn}"
            assert fn not in seen, f"第 {r // 2} 轮截图重复引用: {fn}"
            seen.add(fn)
            assert step.get("actions"), f"第 {r // 2} 轮第 {j} 步 actions 为空"
        flat_steps.extend(trajectory)

    assert os.path.isfile(coords_path), f"coords JSON 缺失: {coords_path}"
    with open(coords_path, encoding="utf-8") as f:
        coords = json.load(f).get("coords") or []
    assert len(coords) == len(flat_steps), \
        f"coords 条数 {len(coords)} != trajectory 步数 {len(flat_steps)}"
    for entry, step in zip(coords, flat_steps):
        assert entry.get("step") == step.get("step"), \
            f"coords step 未对齐: {entry.get('step')} != {step.get('step')}"
        assert entry.get("action") == step["actions"][0].get("action"), \
            f"coords action 未对齐: {entry.get('action')}"
    return data


def assert_all(editor, allow_orphans=False):
    """组合入口：INV-9 + INV-1 + INV-2/3/4/5 + INV-8 + INV-6"""
    assert_transient(editor)
    assert_model(editor)
    assert_files(editor, allow_orphans=allow_orphans)
    assert_sidebar(editor)
    assert_draft(editor)


def assert_resume_consistent(editor, factory):
    """INV-10 续采一致：写草稿 → 新编辑器 load_from_draft → 全套断言

    :param factory: editor_factory（auto_init=False 构造空白编辑器）
    :return: (resumed_editor, need_new_instruction)
    """
    editor._write_draft_now()
    flush_events()
    draft = editor.data_manager.load_draft(editor.gui_number)
    assert draft is not None, "无可恢复草稿"
    resumed = factory(auto_init=False)
    need_instruction = resumed.load_from_draft(draft)
    flush_events(100)
    assert resumed.gui_number == editor.gui_number
    assert_all(resumed)
    return resumed, need_instruction
