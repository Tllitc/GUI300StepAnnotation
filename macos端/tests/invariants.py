# -*- coding: utf-8 -*-
"""数据一致性不变量断言（INV-1 ~ INV-14 的测试侧实现）。

这些函数只读取产品对象状态与磁盘文件，绝不修改产品数据；
所有断言失败均以 AssertionError 抛出，并带上下文字段。

约定:
    截图命名正则: ^gui_\\d{6}_\\d{4}\\.png$
    磁盘目录: gui_{gui_number}/
"""

import hashlib
import json
import math
import os
import re

import pytest


SCREENSHOT_NAME_RE = re.compile(r"^gui_\d{6}_\d{4}\.png$")
# INV-11：从截图名提取 4 位序号
SEQ_RE = re.compile(r"^gui_\d{6}_(\d{4})\.png$")

# INV-8 强断言口径：需要拉框并写入 coords 的动作全集。
# 必须与产品 validate_step_at 的 coord_actions 完全一致（含 scroll）——
# 产品侧 _collect_coords_entries 的 coord_action_types 若缺 scroll（B6），
# 采集与校验会不一致；INV-14（center ↔ coordinate）同样以本集合为适用范围：
# 集合内的动作必须满足「框中心 == 交付坐标值」，集合外的动作不产生 coords 条目。
# 本常量为产品 annotation_editor.COORD_ACTION_TYPES 的镜像（测试侧不引 PyQt5
# 产品模块的惯例），新增动作时产品与本处一并更新。
COORD_ACTION_TYPES = frozenset({
    "left_click", "double_click", "triple_click", "right_click",
    "middle_click", "mouse_move", "left_click_drag", "type", "scroll",
})

# ---------------------------------------------------------------------------
# center ↔ coordinate 判定的纯标准库实现（INV-14 与产品写回守卫共用同一口径）
#
# Windows/根目录版本从 tools.coords_center_repair 导入这几个函数；macos端 不
# 落地该离线修复脚本（用户确认：仅用于修复历史问题数据，与产品代码解耦、不参与
# 打包），故在此内联同一份纯标准库实现，保证 INV-14 判定口径与产品侧漂移一致。
# 常量改动只应在 COORD_CENTER_TOL 这一处。
# ---------------------------------------------------------------------------
# 容差：产品侧 center = x + w // 2，奇数宽高会向下取整，故 1px 内视为一致。
COORD_CENTER_TOL = 1

DRAG_ACTION = "left_click_drag"


def coord_pair(value):
    """[x, y] → (int, int)；不可解析（缺失/非数组/含非数值）返回 None。"""
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    pair = []
    for item in value[:2]:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        if item != item:  # NaN
            return None
        pair.append(int(item))
    return (pair[0], pair[1])


def is_zero_pair(pair):
    """(0, 0) 在交付数据里等价于「没有可用坐标」，不作为比对基准。"""
    return pair is not None and pair[0] == 0 and pair[1] == 0


def center_of(vertices):
    """vertices [x1, y1, x2, y2] → 产品口径的框中心 (x1 + w//2, y1 + h//2)。

    中心值一律由 vertices 重算而非直接读条目自带的 center —— center 本身
    也可能被污染，vertices 才是拉框现场的真实记录。
    """
    if not isinstance(vertices, (list, tuple)) or len(vertices) < 4:
        return None
    x1, y1, x2, y2 = (int(vertices[0]), int(vertices[1]),
                      int(vertices[2]), int(vertices[3]))
    return (x1 + (x2 - x1) // 2, y1 + (y2 - y1) // 2)


def _as_int(value):
    """严格整数取值：bool 不是步序，浮点 step 视为不可用。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def step_action(actions):
    """trajectory 条目的 actions → (action, coordinate, start_coordinate)。"""
    if not isinstance(actions, list):
        return None, None, None
    for item in actions:
        if not isinstance(item, dict):
            continue
        return item.get("action"), item.get("coordinate"), item.get("start_coordinate")
    return None, None, None


def step_action_info(step_data):
    """trajectory 条目 → (action, coordinate, start_coordinate)；非对象条目返回空。"""
    if not isinstance(step_data, dict):
        return None, None, None
    return step_action(step_data.get("actions"))


def entry_coordinate_mismatch(entry, coordinate=None, start_coordinate=None,
                              tol=COORD_CENTER_TOL):
    """单条 coords 条目与其所属步骤的坐标值比对。

    :return: (result, detail)
        result=True  不一致（或 center/vertices 不可解析），需要人工处置
        result=False 一致
        result=None  交付侧没有可用坐标值，无从比对（跳过，不算缺陷）
        detail 为可直接展示给人看的差异说明
    """
    if not isinstance(entry, dict):
        return True, "条目不是 JSON 对象"
    action = entry.get("action")
    if action not in COORD_ACTION_TYPES:
        return None, f"动作 {action!r} 无需坐标"

    if action == DRAG_ACTION:
        # (说明, vertices 值, center 值, 该框应对齐的 JSON 坐标)
        axes = (("start_center", entry.get("start_vertices"), start_coordinate,
                 entry.get("start_center")),
                ("end_center", entry.get("end_vertices"), coordinate,
                 entry.get("end_center")))
    else:
        axes = (("center", entry.get("vertices"), coordinate, entry.get("center")),)

    reasons = []
    checked = 0
    for label, vertices_value, coord_value, center_value in axes:
        # 以 vertices 重算为准；vertices 缺失时退回条目自带的 center
        center = center_of(vertices_value) if isinstance(vertices_value, (list, tuple)) \
            else coord_pair(center_value)
        if center is None:
            reasons.append(f"盘上 {label} 无法解析")
            continue
        target = coord_pair(coord_value)
        if target is None or is_zero_pair(target):
            continue
        checked += 1
        dx = abs(center[0] - target[0])
        dy = abs(center[1] - target[1])
        if dx > tol or dy > tol:
            reasons.append(f"盘上 {label}={list(center)} / JSON coordinate={list(target)}"
                           f"（偏差 {dx},{dy}px）")
    if reasons:
        return True, "；".join(reasons)
    if not checked:
        return None, f"{action} 在交付 JSON 中无可用坐标值，跳过比对"
    return False, ""


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
def assert_final_json(editor, expected_rounds=None, fullscreen_refs=None,
                      center_exempt_refs=None):
    """INV-8: 读取 gui_XXXXXX.json 与 gui_XXXXXX_coords.json 并做交叉校验。

    :param fullscreen_refs: 豁免坐标类断言的 (round_idx, step_idx) 集合。
        产品 validate_step_at 对 selection_type == "fullscreen" 豁免坐标要求，
        _collect_coords_entries 也因 rect_info 为空而跳过这类步骤；但最终 JSON
        的 trajectory 条目不携带 selection_type，无法从盘上辨识，故须由调用方
        显式声明。默认 None 表示「本用例无全屏步」，此时坐标类动作必须条条有
        coords 条目。

        该集合同时作为 INV-14（center ↔ coordinate）的豁免位：坐标值不存在或
        盘上条目本身不被采信的步骤，应由用例显式列入而不是靠 INV-14 放过。
        编辑态回归里「hydration 判定 absent（条目根本不存在）后写回仍无条目」
        的步骤属于此类：覆盖层与中心层都要跳过，传 fullscreen_refs={(轮, 步)}。
    :param center_exempt_refs: 只豁免 INV-14（中心层）的 (round_idx, step_idx)。
        「hydration 判定 mismatch 后原样保留盘上条目」（A4）的步骤属于此类：
        条目**必须**存在（覆盖层照常要求，否则丢框会被静默放过），但工具既不
        造假也不丢数据，故意保留的 bbox 中心与已交付 coordinate 不一致，故须由
        用例显式列入中心层豁免位，而不是连同覆盖层一起跳过。
    """
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
    # (round_idx, step_idx, action, screenshot, coordinate, start_coordinate)
    coord_refs = []
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
            action0 = actions[0]
            coord_refs.append((r_idx, s_idx, action0.get("action", ""), shot,
                               coord_pair(action0.get("coordinate")),
                               coord_pair(action0.get("start_coordinate"))))
            total_steps += 1

    _fullscreen = set(fullscreen_refs or ())
    _center_exempt = _fullscreen | set(center_exempt_refs or ())
    if coords is None:
        # 无 coords 文件却存在需要坐标的步骤 —— B6（scroll 顶点丢失）或
        # B41（空 coords 覆盖 / 未写出）的直接证据。
        need = [(r, s, a) for (r, s, a, _shot, _c, _sc) in coord_refs
                if a in COORD_ACTION_TYPES and (r, s) not in _fullscreen]
        assert not need, (
            f"INV-8: coords 文件缺失，但存在 {len(need)} 个需要坐标的步骤：{need}"
        )
    else:
        assert isinstance(coords, list), "INV-8: coords JSON 不是数组"
        assert len(coords) <= total_steps, (
            f"INV-8: coords 条数 {len(coords)} 超过 trajectory 总步数 {total_steps}"
        )
        assert_coords_entry_structure(coords)
        assert_coords_cover_refs(coords, coord_refs, fullscreen_refs=_fullscreen)
        # INV-14：光有「条目存在」不够 —— 条目必须是属于这一步的框。
        # 旧数据的位置冒领正是「覆盖层全绿、bbox 却属于别的步骤」的假绿。
        assert_coords_center_match(coords, trajectories, fullscreen_refs=_center_exempt)

    return data, coords


def _assert_finite_numbers(value, where, expect_len=None):
    """断言 value 是（可选定长的）有限实数数组。"""
    assert isinstance(value, (list, tuple)), f"INV-8: {where} 不是数组：{value!r}"
    if expect_len is not None:
        assert len(value) == expect_len, (
            f"INV-8: {where} 长度应为 {expect_len}，实际 {len(value)}：{value!r}"
        )
    for n in value:
        assert isinstance(n, (int, float)) and not isinstance(n, bool), (
            f"INV-8: {where} 含非数值元素：{value!r}"
        )
        assert math.isfinite(n), f"INV-8: {where} 含非有限数：{value!r}"


def assert_coords_entry_structure(coords, where="coords"):
    """INV-8 强断言（结构层）：每个 coords 条目的键集与数值必须完整。

    - 单框动作：vertices（4 个有限数）+ center（2 个有限数）
    - left_click_drag：start_vertices/start_center/end_vertices/end_center
    """
    for i, entry in enumerate(coords):
        assert isinstance(entry, dict), f"INV-8: {where}[{i}] 不是对象：{entry!r}"
        step = entry.get("step")
        assert isinstance(step, int) and not isinstance(step, bool), (
            f"INV-8: {where}[{i}] step 缺失或非整数：{step!r}"
        )
        assert step >= 0, f"INV-8: {where}[{i}] step 为负：{step}"
        action = entry.get("action")
        assert isinstance(action, str) and action, (
            f"INV-8: {where}[{i}] action 缺失或为空：{action!r}"
        )
        assert action in COORD_ACTION_TYPES, (
            f"INV-8: {where}[{i}] action={action!r} 不在需要坐标的动作集合内"
        )
        if action == "left_click_drag":
            for key in ("start_vertices", "end_vertices"):
                assert key in entry, f"INV-8: {where}[{i}] 拖拽条目缺 {key}"
                _assert_finite_numbers(entry[key], f"{where}[{i}].{key}", expect_len=4)
            for key in ("start_center", "end_center"):
                assert key in entry, f"INV-8: {where}[{i}] 拖拽条目缺 {key}"
                _assert_finite_numbers(entry[key], f"{where}[{i}].{key}", expect_len=2)
        else:
            assert "vertices" in entry, f"INV-8: {where}[{i}] 缺 vertices"
            _assert_finite_numbers(entry["vertices"], f"{where}[{i}].vertices", expect_len=4)
            assert "center" in entry, f"INV-8: {where}[{i}] 缺 center"
            _assert_finite_numbers(entry["center"], f"{where}[{i}].center", expect_len=2)


def assert_coords_cover_refs(coords, coord_refs, fullscreen_refs=None):
    """INV-8 强断言（覆盖层）：每个需要坐标的 (round, step) 都必须有 coords 条目。

    Windows 的 coords 条目**不含 round 字段**（B4，阶段 4.2 修复），无法按
    (round, step) 直接定位；但 all_coords_entries 是按「落轮先后 + 轮内 step
    升序」extend 出来的，故采用有序消费匹配：依次消费期望项，在 coords 中取
    第一个 (step, action) 相同且未被消费的条目。跨轮同名 (step, action) 因此
    不会互相顶替。

    :param coord_refs: [(round_idx, step_idx, action, screenshot,
                         coordinate, start_coordinate), ...]
        后两项仅供 INV-14 使用，本函数不读。
    """
    skip = set(fullscreen_refs or ())
    expected = [
        (r, s, a) for (r, s, a, _shot, _c, _sc) in coord_refs
        if a in COORD_ACTION_TYPES and (r, s) not in skip
    ]
    consumed = [False] * len(coords)
    missing = []
    for (r_idx, s_idx, action) in expected:
        hit = None
        for j, entry in enumerate(coords):
            if consumed[j] or not isinstance(entry, dict):
                continue
            if entry.get("step") == s_idx and entry.get("action") == action:
                hit = j
                break
        if hit is None:
            missing.append((r_idx, s_idx, action))
        else:
            consumed[hit] = True

    if missing:
        hint = ""
        if any(m[2] == "scroll" for m in missing):
            hint = ("；其中 scroll 步缺失即 B6：_collect_coords_entries 的 "
                    "coord_action_types 未包含 scroll，而 validate_step_at 的 "
                    "coord_actions 包含它 —— 用户按要求拉了框，顶点却被静默丢弃"
                    "（阶段 4.1 修复）")
        raise AssertionError(
            f"INV-8: {len(missing)} 个需要坐标的步骤在 coords 中无对应条目："
            f"{missing}{hint}"
        )

    extra = [coords[j] for j in range(len(coords)) if not consumed[j]]
    assert not extra, (
        f"INV-8: coords 中存在 {len(extra)} 条无对应 trajectory 步骤的条目：{extra}"
    )


# ---------------------------------------------------------------------------
# INV-14 coords 框中心 ↔ 交付坐标值
# ---------------------------------------------------------------------------
def assert_coords_center_match(coords, trajectories, fullscreen_refs=None,
                               where="coords"):
    """INV-14: 每条 coords 的框中心必须等于同一步骤的交付 coordinate。

    依据：产品坐标输入框只读，其值只能由 _init_editor_from_capture 以框中心
    派生（x + w // 2）后原样写进 JSON。故对 COORD_ACTION_TYPES 的单框动作恒有
    center == coordinate，left_click_drag 为 start_center == start_coordinate、
    end_center == coordinate；奇数宽高向下取整，容差 COORD_CENTER_TOL（1px）。

    为何需要单独一条不变量：INV-8 的覆盖层只断言「每个需要坐标的步骤都有
    一条 coords」，从不比对中心，因此「hydration 按列表下标冒领别的步骤的
    顶点」污染后的数据会假绿通过 —— 条目 step 编号正确、bbox 却属于别的
    工作（gui_000005 交付时的 4 组重复 bbox 正是这一形态）。

    定位口径：优先用条目 round 字段按 (round, step) 精确索引；旧交付件不含
    round（B4），退回与 assert_coords_cover_refs 相同的有序消费口径（轮次升序
    + 轮内 step 升序，取第一个 (step, action) 相符且未被消费的条目）。

    :param trajectories: 最终 JSON 各 assistant 消息的 trajectory 列表（按轮顺序）
    :param fullscreen_refs: 豁免的 (round_idx, step_idx) 集合，语义与
        assert_final_json 同名参数一致（全屏步 / 故意原样保留的不一致条目）；
        缺条目的步骤不在此重复报错，由 INV-8 覆盖层负责
    """
    skip = set(fullscreen_refs or ())
    by_round_step = {}
    legacy_entries = []
    for entry in coords or []:
        if not isinstance(entry, dict):
            continue
        rnd = entry.get("round")
        step = entry.get("step")
        if (isinstance(rnd, int) and not isinstance(rnd, bool)
                and isinstance(step, int) and not isinstance(step, bool)):
            by_round_step.setdefault((rnd, step), entry)
        else:
            legacy_entries.append(entry)

    consumed = [False] * len(legacy_entries)
    problems = []
    for r_idx, traj in enumerate(trajectories or []):
        for s_idx, step_data in enumerate(traj or []):
            if (r_idx, s_idx) in skip:
                continue
            action, coordinate, start_coordinate = step_action_info(step_data)
            if action not in COORD_ACTION_TYPES:
                continue
            entry = by_round_step.get((r_idx, s_idx))
            if entry is None:
                for j, candidate in enumerate(legacy_entries):
                    if consumed[j] or candidate.get("action") != action:
                        continue
                    if candidate.get("step") == s_idx:
                        entry = candidate
                        consumed[j] = True
                        break
            if entry is None:
                continue
            mismatched, detail = entry_coordinate_mismatch(
                entry, coordinate, start_coordinate, COORD_CENTER_TOL)
            if mismatched:
                problems.append(f"round {r_idx} step {s_idx}（{action}）：{detail}")

    if problems:
        raise AssertionError(
            f"INV-14: {len(problems)} 条 {where} 条目的框中心与交付 coordinate 不一致：\n  "
            + "\n  ".join(problems)
            + "\n典型成因：旧版 load_from_completed_json 的位置回退（按列表下标取条目）"
              "使编辑态步骤冒领了别的步骤的顶点，保存时又按正确 step 编号写盘；"
              "或 B6 遗留（采集层缺 scroll 导致 coords 少条目、下标整体漂移）。"
              "此类数据不会破坏 INV-8 的覆盖断言，必须由本不变量拦截。"
        )


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


# ---------------------------------------------------------------------------
# INV-11 截图序号可追溯
# ---------------------------------------------------------------------------
def _seq_of(name):
    m = SEQ_RE.match(name or "")
    return int(m.group(1)) if m else None


def assert_screenshot_order(editor, strict_monotonic=True, allow_holes=True):
    """INV-11 截图序号：全局唯一、命名合规、（可选）无空洞、（可选）单调递增。

    :param strict_monotonic: True 时断言 steps 与各轮 trajectory 的序号序列严格
        递增，且未落轮的 steps 序号全部大于已落轮最大序号（捕获新轮复用旧序号）。
        「插入中间步」场景天然破坏该性质（新图取磁盘 max+1 却插到中间，见 B10），
        此类用例须显式传 False，只保留「全局唯一 + 命名合规 + 引用存在」。
    :param allow_holes: False 时额外断言 set(nums) == set(range(1, len(nums)+1))。
        删除中间步会留空洞，故默认允许（阶段 3.1 采纳的退化方案）。
    """
    gui_dir = _gui_dir(editor)
    step_names = _step_referenced_filenames(editor.steps)
    rounds = getattr(editor, "rounds", []) or []
    round_name_lists = [_round_referenced_filenames([rnd]) for rnd in rounds]

    all_names = list(step_names)
    for names in round_name_lists:
        all_names.extend(names)
    for name in all_names:
        assert SEQ_RE.match(name), f"INV-11: 截图命名不规范：{name}"
        assert os.path.isfile(os.path.join(gui_dir, name)), (
            f"INV-11: 引用的截图不存在：{name}"
        )
    dupes = sorted({n for n in all_names if all_names.count(n) > 1})
    assert not dupes, f"INV-11: 截图被多个步骤重复引用：{dupes}"

    nums = [n for n in (_seq_of(x) for x in all_names) if n is not None]
    if not allow_holes and nums:
        assert set(nums) == set(range(1, len(nums) + 1)), (
            f"INV-11: 截图序号存在空洞或不从 1 起：{sorted(nums)}"
        )

    if not strict_monotonic:
        return

    def _assert_increasing(names, where):
        seq = [_seq_of(n) for n in names]
        for i in range(1, len(seq)):
            assert seq[i] > seq[i - 1], (
                f"INV-11: {where} 截图序号未严格递增："
                f"{names[i - 1]} -> {names[i]}"
            )

    for r_idx, names in enumerate(round_name_lists):
        _assert_increasing(names, f"第 {r_idx} 轮")
    _assert_increasing(step_names, "steps")
    saved_max = max(
        [_seq_of(n) for names in round_name_lists for n in names] or [0]
    )
    step_min = min([_seq_of(n) for n in step_names] or [saved_max + 1])
    assert step_min > saved_max, (
        f"INV-11: 未落轮步骤序号({step_min}) 未大于已落轮最大序号({saved_max})，"
        f"新轮复用了旧序号"
    )


# ---------------------------------------------------------------------------
# INV-12 磁盘快照（编辑模式零改盘）
# ---------------------------------------------------------------------------
def snapshot_dir(gui_dir):
    """目录快照：文件名 -> (size, sha256)"""
    result = {}
    gui_dir = str(gui_dir)
    if not os.path.isdir(gui_dir):
        return result
    for name in sorted(os.listdir(gui_dir)):
        path = os.path.join(gui_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            blob = f.read()
        result[name] = (len(blob), hashlib.sha256(blob).hexdigest())
    return result


def assert_dir_unchanged(gui_dir, snapshot):
    """INV-12 磁盘零变化：断言编辑模式下截图/删步/回退不改盘（捕获 B30/B11）。"""
    after = snapshot_dir(gui_dir)
    added = sorted(set(after) - set(snapshot))
    removed = sorted(set(snapshot) - set(after))
    changed = sorted(
        n for n in set(snapshot) & set(after) if snapshot[n] != after[n]
    )
    assert not (added or removed or changed), (
        f"INV-12: 编辑模式下磁盘发生变化：新增 {added}，删除 {removed}，"
        f"改写 {changed}"
    )


# ---------------------------------------------------------------------------
# INV-13 编辑写回保留未编辑部分
# ---------------------------------------------------------------------------
def _normalize_coords(loaded):
    """兼容两种外层结构：纯数组（Windows/macOS） / {"version":..., "coords":[...]}（Android）"""
    if loaded is None:
        return []
    if isinstance(loaded, list):
        return loaded
    if isinstance(loaded, dict):
        return loaded.get("coords") or []
    return []


def coords_by_round(coords):
    """按轮切段：优先用显式 round 字段，缺失时按 step 变小切段。

    Windows coords 不写 round（B4，阶段 4.2 修复），故必须保留 step 切段路径
    才能对历史已交付文件做 INV-13 校验。
    """
    groups = {}
    current = 0
    prev_step = None
    for entry in coords or []:
        if not isinstance(entry, dict):
            continue
        rnd = entry.get("round")
        step = entry.get("step")
        if isinstance(rnd, int):
            current = rnd
        elif (isinstance(prev_step, int) and isinstance(step, int)
                and step < prev_step):
            current += 1
        groups.setdefault(current, []).append(entry)
        if isinstance(step, int):
            prev_step = step
    return groups


def assert_edit_writeback_preserved(gui_dir, gui_number, before_data, before_coords,
                                    edited_round_index):
    """INV-13 编辑写回：未编辑的消息与 coords 必须逐字段保留（捕获 B40/B41）。

    :param before_data: 编辑前读到的完整 gui_N.json dict
    :param before_coords: 编辑前的 coords（list 或 {"coords": [...]} 均可）
    :return: (after_data, after_coords)
    """
    gui_dir = str(gui_dir)
    json_path = os.path.join(gui_dir, f"gui_{gui_number}.json")
    coords_path = os.path.join(gui_dir, f"gui_{gui_number}_coords.json")
    assert os.path.isfile(json_path), f"INV-13: 编辑写回后最终 JSON 缺失：{json_path}"
    with open(json_path, "r", encoding="utf-8") as f:
        after = json.load(f)

    before_messages = (before_data or {}).get("messages") or []
    after_messages = after.get("messages") or []
    assert len(after_messages) == len(before_messages), (
        f"INV-13: messages 条数被改写："
        f"{len(before_messages)} -> {len(after_messages)}"
    )
    assert [m.get("role") for m in after_messages] == \
           [m.get("role") for m in before_messages], "INV-13: messages 角色序列被改写"
    touched = {2 * edited_round_index, 2 * edited_round_index + 1}
    for i, (b, g) in enumerate(zip(before_messages, after_messages)):
        if i in touched:
            continue
        assert g == b, (
            f"INV-13: messages[{i}]（非编辑轮，role={b.get('role')!r}）被改写或丢失"
        )

    after_coords = None
    if os.path.isfile(coords_path):
        with open(coords_path, "r", encoding="utf-8") as f:
            after_coords = _normalize_coords(json.load(f))
    before_norm = _normalize_coords(before_coords)
    if before_norm:
        assert after_coords, "INV-13: 原 coords 非空但写回后为空（B41 空覆盖）"
        before_groups = coords_by_round(before_norm)
        after_groups = coords_by_round(after_coords)
        for r_idx, entries in before_groups.items():
            if r_idx == edited_round_index:
                continue
            assert after_groups.get(r_idx) == entries, (
                f"INV-13: 未编辑轮 round={r_idx} 的 coords 条目被改写"
            )
    return after, after_coords


# ---------------------------------------------------------------------------
# 组合入口
# ---------------------------------------------------------------------------
def assert_all(editor, allow_orphans=False, with_draft=True):
    """采集过程中可反复使用的全套不变量（macOS 侧组合入口，对齐 Windows/iOS/Android）。

    内部会先 flush 草稿（INV-7 依赖落盘）。不含最终 JSON 断言（最终 JSON 只在
    terminate 后产出，请用 assert_final_json）。编辑模式下请传 with_draft=False
    （编辑态不写草稿）。

    INV-11 在组合入口用 strict_monotonic=False（只保证全局唯一 + 命名合规 +
    引用存在）：插入中间步天然破坏严格递增，严格模式留给专项用例显式调用。
    """
    editor._write_draft_now()
    assert_model(editor)
    assert_stack(editor)
    assert_files(editor, allow_orphans=allow_orphans)
    assert_naming(editor)
    assert_screenshot_order(editor, strict_monotonic=False)
    assert_sidebar(editor)
    assert_transient_reset(editor)
    if with_draft:
        assert_draft(editor)
