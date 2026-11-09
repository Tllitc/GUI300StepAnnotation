# -*- coding: utf-8 -*-
"""数据一致性不变量断言（INV-1 ~ INV-10 的测试侧实现）。

这些函数只读取产品对象状态与磁盘文件，绝不修改产品数据；
所有断言失败均以 AssertionError 抛出，并带上下文字段。

约定:
    截图命名正则: ^gui_\\d{6}_\\d{4}\\.png$
    磁盘目录: gui_{gui_number}/
"""

import json
import os
import re

import pytest


SCREENSHOT_NAME_RE = re.compile(r"^gui_\d{6}_\d{4}\.png$")


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _round_referenced_filenames(rounds):
    result = []
    for round_data in rounds or []:
        for traj in round_data.get("trajectory", []):
            obs = traj.get("observation") or {}
            shot = obs.get("screenshot")
            if shot:
                result.append(shot)
    return result


def _step_referenced_filenames(steps):
    return [s.get("screenshot_filename") for s in steps if s.get("screenshot_filename")]


def _all_referenced_filenames(editor):
    names = _step_referenced_filenames(editor.steps)
    names.extend(_round_referenced_filenames(getattr(editor, "rounds", [])))
    return names


def _gui_dir(editor):
    return os.path.join(editor.data_manager.current_dir, f"gui_{editor.gui_number}")


def _strict_named_pngs(editor):
    gui_dir = _gui_dir(editor)
    if not os.path.isdir(gui_dir):
        return set()
    return {f for f in os.listdir(gui_dir) if SCREENSHOT_NAME_RE.match(f)}


# ---------------------------------------------------------------------------
# INV-1 模型一致
# ---------------------------------------------------------------------------
def assert_model(editor):
    """INV-1: steps 连续；每步 screenshot_filename 非空且指向磁盘真实文件；
    若 step["data"] 存在，data["step"] == 当前下标，data.observation.screenshot == screenshot_filename。"""
    seen = {}
    for i, step in enumerate(editor.steps):
        name = step.get("screenshot_filename")
        assert name, f"INV-1: 第 {i} 步 screenshot_filename 为空"
        assert SCREENSHOT_NAME_RE.match(name), f"INV-1: 第 {i} 步截图名不规范: {name!r}"

        # 单射：一个文件最多被一步引用
        assert name not in seen, f"INV-1: 截图 {name} 同时被第 {seen.get(name)} 步和第 {i} 步引用"
        seen[name] = i

        # 文件存在
        path = os.path.join(_gui_dir(editor), name)
        assert os.path.isfile(path), f"INV-1: 第 {i} 步截图在磁盘上缺失：{name}"

        # data 快照一致性
        data = step.get("data")
        if isinstance(data, dict):
            # step 字段
            if "step" in data:
                assert data["step"] == i, f"INV-1: 第 {i} 步 data.step={data['step']} 不一致"
            # observation.screenshot
            obs = data.get("observation") or {}
            shot = obs.get("screenshot")
            assert shot == name, f"INV-1: 第 {i} 步 data.observation.screenshot={shot!r} != {name!r}"

            # actions 是 list 且至少一个
            actions = data.get("actions") or []
            assert isinstance(actions, list) and len(actions) > 0, f"INV-1: 第 {i} 步 data.actions 异常: {actions!r}"


# ---------------------------------------------------------------------------
# INV-2 页序一致
# ---------------------------------------------------------------------------
def assert_stack(editor):
    """INV-2: stack_widget.count() == len(steps)+1，且 widget(i+1) is steps[i]['editor']；
    current_step_index 合法（或为空时 -1）。"""
    assert editor.stack_widget.count() == len(editor.steps) + 1, (
        f"INV-2: stack 页数 {editor.stack_widget.count()} != 步数+1 {len(editor.steps) + 1}"
    )
    for i, step in enumerate(editor.steps):
        w = editor.stack_widget.widget(i + 1)
        assert w is step["editor"], (
            f"INV-2: stack 第 {i + 1} 页不是第 {i} 步的 editor (type={type(w).__name__})"
        )

    total = len(editor.steps)
    if total == 0:
        assert editor.current_step_index == -1, (
            f"INV-2: 无步骤时 current_step_index 应为 -1，实际 {editor.current_step_index}"
        )
    else:
        assert 0 <= editor.current_step_index < total, (
            f"INV-2: current_step_index={editor.current_step_index} 越界（总 {total} 步）"
        )


# ---------------------------------------------------------------------------
# INV-3/4/5 文件存在 + 单射 + 无孤儿
# ---------------------------------------------------------------------------
def assert_files(editor, allow_orphans=False):
    """INV-3/4/5: 引用文件在磁盘存在；steps 内单射；磁盘上严格命名的 PNG 要么被 steps 引用要么被 rounds 引用。"""
    gui_dir = _gui_dir(editor)
    assert os.path.isdir(gui_dir), f"INV-3: gui_dir 不存在 {gui_dir}"

    referenced = set(_all_referenced_filenames(editor))

    # 被引用的必须存在
    for name in referenced:
        assert os.path.isfile(os.path.join(gui_dir, name)), (
            f"INV-3: 被引用截图 {name} 在磁盘上缺失"
        )

    # 磁盘上严格命名的 PNG
    on_disk = _strict_named_pngs(editor)

    # 单射（steps 内）
    step_names = _step_referenced_filenames(editor.steps)
    assert len(step_names) == len(set(step_names)), "INV-4: steps 内 screenshot_filename 出现重复"

    # 无孤儿
    orphans = on_disk - referenced
    if not allow_orphans:
        assert not orphans, f"INV-5: 孤儿截图 {sorted(orphans)}"

    # INV-6 内联：命名规范随文件断言一并生效
    # （assert_naming 此前定义了却从未被任何测试调用，属死代码）
    assert_naming(editor)


# ---------------------------------------------------------------------------
# INV-6 命名规范
# ---------------------------------------------------------------------------
def assert_naming(editor):
    """INV-6: 所有截图文件名严格匹配正则。"""
    gui_dir = _gui_dir(editor)
    if not os.path.isdir(gui_dir):
        return
    for f in os.listdir(gui_dir):
        if f.lower().endswith(".png") and f.startswith("gui_"):
            assert SCREENSHOT_NAME_RE.match(f), f"INV-6: 截图命名不规范 {f!r}"


# ---------------------------------------------------------------------------
# INV-7 草稿一致
# ---------------------------------------------------------------------------
def assert_draft(editor):
    """INV-7: 立即 _write_draft_now 后读取草稿文件，断言：
    - JSON 可解析；
    - current_steps 条数/顺序/screenshot_filename/rect_info/selection_type 与内存一致；
    - rounds / coords_entries 与内存一致；
    - draft.current_steps[].data 结构完整，data.step == 下标，data.observation.screenshot == filename。
    """
    # 立即落盘，绕过防抖
    editor._write_draft_now()

    gui_dir = _gui_dir(editor)
    draft_path = os.path.join(gui_dir, f"gui_{editor.gui_number}_draft.json")
    assert os.path.isfile(draft_path), f"INV-7: 草稿文件缺失 {draft_path}"

    with open(draft_path, "r", encoding="utf-8") as f:
        draft = json.load(f)

    # 基本字段
    assert draft.get("gui_number") == editor.gui_number

    # current_steps
    draft_steps = draft.get("current_steps", [])
    assert len(draft_steps) == len(editor.steps), (
        f"INV-7: 草稿 current_steps {len(draft_steps)} != 内存 steps {len(editor.steps)}"
    )

    def _rec_tuple(value):
        # list → tuple（只比较内容，不强制类型一致）
        return value

    for i, (ds, live) in enumerate(zip(draft_steps, editor.steps)):
        assert ds.get("screenshot_filename") == live.get("screenshot_filename"), (
            f"INV-7: 第 {i} 步 draft screenshot_filename={ds.get('screenshot_filename')!r} "
            f"!= live={live.get('screenshot_filename')!r}"
        )

        # selection_type
        assert ds.get("selection_type") == live.get("selection_type"), (
            f"INV-7: 第 {i} 步 draft selection_type={ds.get('selection_type')!r} "
            f"!= live={live.get('selection_type')!r}"
        )

        # rect_info：tuple 递归转 list 存草稿，load 时再转回 tuple；
        # 这里比较值（list/tuple 只要元素一样就 OK）
        assert list(ds.get("rect_info") or []) == list(live.get("rect_info") or ()), (
            f"INV-7: 第 {i} 步 rect_info 不一致"
        )

        # data 结构
        data = ds.get("data")
        assert isinstance(data, dict), f"INV-7: 第 {i} 步 draft 缺少 data 快照"
        assert "step" in data, f"INV-7: 第 {i} 步 data 缺少 step 字段"
        assert data["step"] == i, f"INV-7: 第 {i} 步 data.step={data['step']} != {i}"

        obs = data.get("observation") or {}
        assert obs.get("screenshot") == ds.get("screenshot_filename"), (
            f"INV-7: 第 {i} 步 data.observation.screenshot={obs.get('screenshot')!r} "
            f"!= filename={ds.get('screenshot_filename')!r}"
        )

    # rounds / coords_entries
    assert json.dumps(draft.get("rounds"), ensure_ascii=False, sort_keys=True) == \
        json.dumps(editor.rounds, ensure_ascii=False, sort_keys=True), (
        "INV-7: 草稿 rounds 与内存不一致"
    )
    # coords_entries 是 list，比较长度 + 内容
    dc = draft.get("coords_entries") or []
    lc = editor.all_coords_entries or []
    assert len(dc) == len(lc), (
        f"INV-7: 草稿 coords_entries 条数 {len(dc)} != 内存 {len(lc)}"
    )
    for i, (a, b) in enumerate(zip(dc, lc)):
        assert a == b, f"INV-7: coords_entries[{i}] 不一致"

    return draft


# ---------------------------------------------------------------------------
# coords 与轨迹对齐（INV-8 强化子断言）
# ---------------------------------------------------------------------------
def assert_coords_aligned(editor, data, coords):
    """校验 coords 与最终 JSON 各轮 trajectory 的「序号 / 顺序 / 动作」精确对齐。

    coords 是扁平数组且不含 round 字段（_collect_coords_entries 未写 round），
    仅对部分动作类型收集（terminate/answer 等无 coords 条目属正常）。

    - 单轮：coords 的 step 索引必须严格递增、落在轨迹范围内，且每条 action
      与 trajectory[step].actions[0].action 一致（顺序错乱/序号错位/动作错配都会被抓）。
    - 多轮：step 下降沿切分在「轮末为 answer/terminate」时会与轮数不一致，故改用
      产品同款 _group_coords_by_round 对齐后逐条校验 (step, action)，绝不丢弃条目。
    """
    if coords is None:
        return
    assert isinstance(coords, list), "coords JSON 不是数组"

    messages = data.get("messages", [])
    trajectories = [
        m.get("trajectory") for m in messages
        if m.get("role") == "assistant" and isinstance(m.get("trajectory"), list)
    ]
    assert trajectories, "最终 JSON 无 assistant 轨迹，无法对齐 coords"

    def _action_of(traj_entry):
        acts = traj_entry.get("actions") or []
        if acts and isinstance(acts[0], dict):
            return acts[0].get("action")
        return None

    def _check_entry(entry, traj, where):
        step = entry.get("step") if isinstance(entry, dict) else None
        assert isinstance(step, int) and not isinstance(step, bool), \
            f"{where}: coords.step 非法 {step!r}"
        assert 0 <= step < len(traj), \
            f"{where}: coords.step={step} 越界（轨迹长 {len(traj)}）"
        expected = _action_of(traj[step])
        got = entry.get("action")
        assert got == expected, \
            f"{where}: coords action={got!r} 与轨迹 step{step} action={expected!r} 不一致"
        return step

    if len(trajectories) == 1:
        traj = trajectories[0]
        prev = None
        for k, entry in enumerate(coords):
            step = _check_entry(entry, traj, f"coords[{k}]")
            if prev is not None:
                assert step > prev, \
                    f"coords 顺序错乱：coords[{k}].step={step} 未严格大于前一条 {prev}"
            prev = step
        return

    # 多轮：借用产品分组逻辑，保证与产品写读 coords 完全同口径
    rounds_like = [{"trajectory": t} for t in trajectories]
    groups = editor._group_coords_by_round(rounds_like, coords)
    assert len(groups) == len(trajectories), \
        f"coords 分组数 {len(groups)} != 轮次数 {len(trajectories)}"
    grouped_total = sum(len(g) for g in groups)
    assert grouped_total == len(coords), \
        f"coords 分组丢失条目：{grouped_total} != {len(coords)}"
    for r, group in enumerate(groups):
        traj = trajectories[r]
        for entry in group:
            _check_entry(entry, traj, f"round{r} coords")


# ---------------------------------------------------------------------------
# INV-8 最终产物一致
# ---------------------------------------------------------------------------
def assert_final_json(editor, expected_rounds=None):
    """INV-8: 读取 gui_XXXXXX.json 与 gui_XXXXXX_coords.json 并做交叉校验。"""
    gui_dir = _gui_dir(editor)
    json_path = os.path.join(gui_dir, f"gui_{editor.gui_number}.json")
    coords_path = os.path.join(gui_dir, f"gui_{editor.gui_number}_coords.json")

    assert os.path.isfile(json_path), f"INV-8: 最终 JSON 缺失 {json_path}"

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    coords = None
    if os.path.isfile(coords_path):
        with open(coords_path, "r", encoding="utf-8") as f:
            coords = json.load(f)

    messages = data.get("messages", [])
    assert messages, "INV-8: messages 为空"

    trajectories = []
    for i, msg in enumerate(messages):
        role = msg.get("role")
        expected_role = "user" if i % 2 == 0 else "assistant"
        assert role == expected_role, (
            f"INV-8: messages[{i}] role={role!r}，应为 {expected_role!r}"
        )
        if role == "assistant":
            traj = msg.get("trajectory")
            assert isinstance(traj, list), f"INV-8: messages[{i}] 缺少 trajectory"
            trajectories.append(traj)

    if expected_rounds is not None:
        assert len(trajectories) == expected_rounds, (
            f"INV-8: 轮次数 {len(trajectories)} != {expected_rounds}"
        )

    total_steps = 0
    coord_refs = []  # (round_idx, step_idx, action, screenshot)
    # 跨全部轮次的截图名 -> 首次出现的 (r_idx, s_idx)
    all_seen_shots = {}
    for r_idx, traj in enumerate(trajectories):
        seen_shots = set()
        for s_idx, entry in enumerate(traj):
            # step 字段
            assert entry.get("step") == s_idx, (
                f"INV-8: round {r_idx} step {s_idx} step 字段={entry.get('step')}"
            )

            obs = entry.get("observation") or {}
            shot = obs.get("screenshot")
            assert shot, f"INV-8: round {r_idx} step {s_idx} 缺 screenshot"
            assert SCREENSHOT_NAME_RE.match(shot), f"INV-8: 截图命名不规范 {shot!r}"
            assert os.path.isfile(os.path.join(gui_dir, shot)), (
                f"INV-8: 最终 JSON 引用截图缺失 {shot}"
            )
            assert shot not in seen_shots, f"INV-8: round {r_idx} 内截图重复 {shot}"
            seen_shots.add(shot)

            # 跨轮全局唯一：老版本每轮截图序号从 0001 重新计数，
            # 会导致跨轮同名覆盖、同一批步骤重复出现在多个 trajectory
            first_r, first_s = all_seen_shots.get(shot, (None, None))
            assert shot not in all_seen_shots, (
                f"INV-8: 跨轮截图重复 {shot}，首次出现于 round {first_r} step {first_s}，"
                f"再次出现于 round {r_idx} step {s_idx}"
            )
            all_seen_shots[shot] = (r_idx, s_idx)

            actions = entry.get("actions") or []
            assert actions, f"INV-8: round {r_idx} step {s_idx} actions 为空"
            coord_refs.append((r_idx, s_idx, actions[0].get("action", ""), shot))
            total_steps += 1

    if coords is not None:
        assert isinstance(coords, list), "INV-8: coords JSON 不是数组"
        # coords 只对部分动作类型收集，条数不超过轨迹总步数
        assert len(coords) <= total_steps, (
            f"INV-8: coords 条数 {len(coords)} 超过轨迹总步数 {total_steps}"
        )
        # 强断言：coords 与各轮 trajectory 的序号/顺序/动作精确对齐
        assert_coords_aligned(editor, data, coords)

    return data, coords


# ---------------------------------------------------------------------------
# INV-9 侧栏一致
# ---------------------------------------------------------------------------
def assert_sidebar(editor):
    """INV-9: len(item_widgets) == len(steps)；条目 step_index 与列表位置一一对应；
    计数标签与模型一致。"""
    items = editor.sidebar.item_widgets
    steps = editor.steps
    assert len(items) == len(steps), (
        f"INV-9: 侧栏条目数 {len(items)} != 步数 {len(steps)}"
    )
    for i, item in enumerate(items):
        assert item.step_index == i, (
            f"INV-9: 侧栏位置 {i} 的条目 step_index={item.step_index}"
        )


# ---------------------------------------------------------------------------
# INV-10 瞬态状态收敛
# ---------------------------------------------------------------------------
def assert_transient_reset(editor):
    """INV-10: _capture_in_flight=False、_capture_insert_after=None、主窗口可见且不透明。"""
    assert editor._capture_in_flight is False, "INV-10: _capture_in_flight 未复位"
    assert editor._capture_insert_after is None, "INV-10: _capture_insert_after 未复位"
    # 主窗口可见且完全不透明
    assert editor.windowOpacity() == 1.0, f"INV-10: windowOpacity={editor.windowOpacity()} != 1.0"
    assert editor.isVisible(), "INV-10: 主窗口不可见"
