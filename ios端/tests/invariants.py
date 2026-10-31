# -*- coding: utf-8 -*-
"""数据一致性不变量断言（INV-1 ~ INV-10 的测试侧实现）。

这些函数只读取产品对象状态与磁盘文件，绝不修改产品代码/状态。
所有断言失败均以 AssertionError 抛出，并带上下文字段。

约定:
    - 严格截图命名正则：^gui_\\d{6}_\\d{4}\\.png$
    - 模型引用：steps_data 中每步的 screenshot 字段（basename）
    - 轮次引用：editor.rounds[*].trajectory[*].observation.screenshot
"""

import json
import os
import re

from data_manager import DataManager


SCREENSHOT_NAME_RE = re.compile(r"^gui_\d{6}_\d{4}\.png$")


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------

def _round_referenced_filenames(rounds):
    """收集 rounds 全部 trajectory 引用到的截图文件名（有序）。"""
    result = []
    for round_data in rounds or []:
        for traj in round_data.get("trajectory", []):
            obs = traj.get("observation") or {}
            name = obs.get("screenshot")
            if name:
                result.append(name)
    return result


def _all_referenced_filenames(editor, include_rounds=True):
    """模型内（steps_data + 可选 rounds）引用到的全部截图文件名。"""
    names = [s.get("screenshot") for s in editor.steps_data if s.get("screenshot")]
    if include_rounds:
        names.extend(_round_referenced_filenames(getattr(editor, "rounds", [])))
    return names


def _strict_named_pngs(gui_dir):
    """gui_dir 下所有匹配严格命名正则的 PNG 文件名集合。"""
    if not os.path.isdir(gui_dir):
        return set()
    return {f for f in os.listdir(gui_dir) if SCREENSHOT_NAME_RE.match(f)}


# ----------------------------------------------------------------------
# INV-1 / INV-3：模型自洽 + 截图单射
# ----------------------------------------------------------------------

def assert_model_consistency(editor):
    """steps_data 模型一致性：

    - 每步 screenshot 非空（INV-1）
    - screenshot_filepath 的 basename 与 screenshot 一致（INV-1）
    - screenshot 集合在 steps_data 内无重复（INV-3 单射：一步一图）
    """
    seen = {}
    for index, step in enumerate(editor.steps_data):
        name = step.get("screenshot")
        assert name, f"INV-1: 第 {index} 步 screenshot 为空"
        filepath = step.get("screenshot_filepath") or ""
        assert os.path.basename(filepath) == name, (
            f"INV-1: 第 {index} 步 screenshot_filepath({filepath}) "
            f"与 screenshot({name}) 不一致"
        )
        assert name not in seen, (
            f"INV-3: 截图 {name} 同时被第 {seen.get(name)} 步和第 {index} 步引用"
        )
        seen[name] = index


# ----------------------------------------------------------------------
# INV-2 / INV-4 / INV-5：磁盘一致性、无孤儿、命名规范
# ----------------------------------------------------------------------

def assert_disk_consistency(editor, referenced_filenames=None, allow_orphans=False):
    """磁盘与引用一致性：

    - 被引用文件必须真实存在于 gui_dir（INV-2）
    - 目录内所有严格命名 PNG 必须被模型/轮次引用（INV-4，无孤儿截图）
    - 严格命名正则校验（INV-5）
    - screenshot_filepath 指向的文件存在（INV-2）

    referenced_filenames 为 None 时自动收集 steps_data + rounds 的引用。
    """
    gui_dir = editor.gui_dir
    assert gui_dir and os.path.isdir(gui_dir), f"INV-2: gui_dir 不存在：{gui_dir}"

    if referenced_filenames is None:
        referenced_filenames = _all_referenced_filenames(editor)
    referenced_set = set(referenced_filenames)

    # INV-1/INV-2：模型引用的文件必须在磁盘上
    for name in referenced_set:
        assert SCREENSHOT_NAME_RE.match(name), (
            f"INV-5: 引用截图名不符合规范：{name!r}"
        )
        assert os.path.isfile(os.path.join(gui_dir, name)), (
            f"INV-2: 被引用截图在磁盘上缺失：{name}"
        )

    # steps_data 的绝对路径也要落地
    for index, step in enumerate(editor.steps_data):
        filepath = step.get("screenshot_filepath") or ""
        if filepath:
            assert os.path.isfile(filepath), (
                f"INV-2: 第 {index} 步 screenshot_filepath 指向文件不存在：{filepath}"
            )

    # INV-4：严格命名 PNG 集合 ⊆ 引用集合（不允许孤儿；scroll extra 等
    # 在正常结束后应已被删除）
    on_disk = _strict_named_pngs(gui_dir)
    orphans = on_disk - referenced_set
    if not allow_orphans:
        assert not orphans, f"INV-4: 发现无引用孤儿截图：{sorted(orphans)}"

    # INV-5：目录内任何 gui_ 前缀 PNG 都必须满足严格命名（捕获 001/补零缺失等）
    for f in os.listdir(gui_dir):
        if f.lower().endswith(".png") and f.startswith("gui_"):
            assert SCREENSHOT_NAME_RE.match(f), (
                f"INV-5: 磁盘截图命名不符合 ^gui_\\\\d{{6}}_\\\\d{{4}}.png$：{f}"
            )

    return on_disk


# ----------------------------------------------------------------------
# INV-6：草稿一致性
# ----------------------------------------------------------------------

def assert_draft_consistency(editor):
    """flush 草稿后读取 gui 目录下 *_draft.json 并校验（INV-6）。

    - 草稿步数与 steps_data 相同（新步正在编辑时允许 +1 的产品行为，
      本断言只在“当前步已落表”的稳定点调用）
    - 逐位 screenshot 相等
    - 草稿步不含 screenshot_filepath 绝对路径键
    - current_step_index 落在合法区间
    - rounds 与内存一致（JSON 可序列化结构）
    """
    draft = DataManager.load_draft_from_dir(editor.gui_dir)
    assert draft is not None, "INV-6: 草稿文件不存在"

    draft_steps = draft.get("steps_data", [])
    live_steps = editor.steps_data
    assert len(draft_steps) == len(live_steps), (
        f"INV-6: 草稿步数 {len(draft_steps)} != 模型步数 {len(live_steps)}"
    )

    for i, (d, s) in enumerate(zip(draft_steps, live_steps)):
        assert d.get("screenshot") == s.get("screenshot"), (
            f"INV-6: 第 {i} 步草稿截图 {d.get('screenshot')!r} "
            f"!= 模型 {s.get('screenshot')!r}"
        )
        assert "screenshot_filepath" not in d, (
            f"INV-6: 第 {i} 步草稿泄漏了 screenshot_filepath 绝对路径"
        )

    idx = draft.get("current_step_index", 0)
    total = len(draft_steps)
    if total:
        # current_step == total 是产品的正常稳定态：表示“下一步尚未截图”
        # （confirm_step 后 current_step=len(steps_data)，见 _save_current_to_steps
        # 的 append 分支）。续采 load_from_draft 会将其夹紧到 total-1。
        assert 0 <= idx <= total, (
            f"INV-6: current_step_index={idx} 越界（总步数 {total}）"
        )
    else:
        assert idx == 0, f"INV-6: 无步骤时 current_step_index 应为 0，实际 {idx}"

    assert json.loads(json.dumps(draft.get("rounds", []), ensure_ascii=False)) == (
        json.loads(json.dumps(getattr(editor, "rounds", []), ensure_ascii=False))
    ), "INV-6: 草稿 rounds 与内存 rounds 不一致"

    return draft


# ----------------------------------------------------------------------
# INV-8：侧栏一致性
# ----------------------------------------------------------------------

def assert_sidebar_consistency(editor):
    """侧栏条目与 steps_data 一一对应（INV-8）。

    - item_widgets 数量 == steps_data 数量
    - 各条目 _index == 列表位置
    """
    items = editor.sidebar.item_widgets
    steps = editor.steps_data
    assert len(items) == len(steps), (
        f"INV-8: 侧栏条目数 {len(items)} != 模型步数 {len(steps)}"
    )
    for pos, item in enumerate(items):
        assert item._index == pos, (
            f"INV-8: 侧栏位置 {pos} 的条目 _index={item._index}"
        )


# ----------------------------------------------------------------------
# INV-9 / INV-10：最终 JSON / coords 一致性
# ----------------------------------------------------------------------

def assert_final_json_consistency(editor_or_guidir, gui_dir=None, expected_rounds=None):
    """读取 gui_XXXXXX.json 与 gui_XXXXXX_coords.json 做交叉校验（INV-9/10）。

    参数可传 editor（自动取 editor.gui_dir / editor.gui_number / editor.rounds）
    或直接传 gui_dir 路径。

    校验内容:
      - 两个文件存在
      - messages 严格按 user / assistant(trajectory) 交替
      - 每个 trajectory 的 step 从 0 连续递增
      - observation.screenshot 文件存在且严格命名
      - 同一 trajectory 内截图不重复
      - coords 条目数 == 全部 trajectory 步数总和
      - coords 按 (round, step) 与 trajectory 对齐，action 相等
      - coords 的 round 连续、step 在轮内连续
      - expected_rounds 给定时，轮次数一致
    返回 (json_data, coords_data)。
    """
    if gui_dir is None:
        gui_dir = editor_or_guidir.gui_dir
    gui_number = os.path.basename(os.path.normpath(gui_dir)).replace("gui_", "")

    json_path = os.path.join(gui_dir, f"gui_{gui_number}.json")
    coords_path = os.path.join(gui_dir, f"gui_{gui_number}_coords.json")
    assert os.path.isfile(json_path), f"INV-9: 主 JSON 不存在：{json_path}"
    assert os.path.isfile(coords_path), f"INV-10: coords JSON 不存在：{coords_path}"

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    with open(coords_path, "r", encoding="utf-8") as f:
        coords = json.load(f)

    messages = data.get("messages", [])
    assert messages, "INV-9: messages 为空"

    # 抽出 assistant trajectory，同时检查 user/assistant 交替
    trajectories = []
    for i, msg in enumerate(messages):
        role = msg.get("role")
        expected_role = "user" if i % 2 == 0 else "assistant"
        assert role == expected_role, (
            f"INV-9: messages[{i}] role={role!r}，应为 {expected_role!r}"
        )
        if role == "assistant":
            traj = msg.get("trajectory")
            assert isinstance(traj, list), f"INV-9: messages[{i}] 缺少 trajectory 列表"
            trajectories.append(traj)

    if expected_rounds is not None:
        assert len(trajectories) == expected_rounds, (
            f"INV-9: trajectory 轮数 {len(trajectories)} != 预期 {expected_rounds}"
        )

    total_steps = 0
    paired_refs = []  # (round_idx, step_idx, action, screenshot)
    for r_idx, traj in enumerate(trajectories):
        seen_shots = set()
        for s_idx, entry in enumerate(traj):
            assert entry.get("step") == s_idx, (
                f"INV-9: round {r_idx} 第 {s_idx} 项 step 字段={entry.get('step')}"
            )
            obs = entry.get("observation") or {}
            shot = obs.get("screenshot")
            assert shot, f"INV-9: round {r_idx} step {s_idx} 缺 screenshot"
            assert SCREENSHOT_NAME_RE.match(shot), (
                f"INV-9: 截图命名不规范：{shot!r}"
            )
            assert os.path.isfile(os.path.join(gui_dir, shot)), (
                f"INV-9: 最终 JSON 引用截图缺失：{shot}"
            )
            assert shot not in seen_shots, (
                f"INV-9: round {r_idx} 内截图重复：{shot}"
            )
            seen_shots.add(shot)

            actions = entry.get("actions") or []
            assert actions, f"INV-9: round {r_idx} step {s_idx} actions 为空"
            paired_refs.append((r_idx, s_idx, actions[0].get("action", ""), shot))
            total_steps += 1

    assert isinstance(coords, list), "INV-10: coords JSON 不是数组"
    assert len(coords) == total_steps, (
        f"INV-10: coords 条目数 {len(coords)} != trajectory 总步数 {total_steps}"
    )

    for i, (coord, ref) in enumerate(zip(coords, paired_refs)):
        r_idx, s_idx, action, _shot = ref
        assert coord.get("round") == r_idx, (
            f"INV-10: coords[{i}] round={coord.get('round')} != {r_idx}"
        )
        assert coord.get("step") == s_idx, (
            f"INV-10: coords[{i}] step={coord.get('step')} != {s_idx}"
        )
        assert coord.get("action") == action, (
            f"INV-10: coords[{i}] action={coord.get('action')!r} "
            f"!= trajectory action {action!r}"
        )
        assert coord.get("_version") == "3.1", (
            f"INV-10: coords[{i}] _version={coord.get('_version')!r}，应为 '3.1'"
        )

    return data, coords


# ----------------------------------------------------------------------
# 测量状态复位
# ----------------------------------------------------------------------

def assert_measurement_state_reset(editor):
    """所有测量/插入/截图临时状态已复位，且 scroll extra 截图已从磁盘清除。"""
    assert editor._screenshot_in_progress is False, "截图进行中标记未复位"
    assert editor._capture_insert_after is None, "插入截图锚点未复位"
    assert editor._replacing_screenshot is False, "替换截图标记未复位"
    assert editor._swipe_measuring is False, "swipe 测量状态未复位"
    assert editor._scroll_measuring is False, "scroll 测量状态未复位"
    assert editor._scroll_preserve_screenshot is False, "scroll 保留首图标记未复位"
    assert editor._scroll_extra_screenshots == [], (
        f"scroll extra 截图列表未清空：{editor._scroll_extra_screenshots}"
    )
    for path in editor._scroll_extra_screenshots:
        assert not os.path.exists(path), f"scroll extra 截图残留磁盘：{path}"


# ----------------------------------------------------------------------
# 组合断言（final json 需任务结束后单独调用）
# ----------------------------------------------------------------------

def assert_all(editor):
    """采集过程中可反复使用的全套不变量：模型/磁盘/侧栏/草稿/测量状态。

    内部会先 flush 草稿（INV-6 依赖落盘）。不含最终 JSON 断言
    （最终 JSON 只在 terminate 后产出，请用 assert_final_json_consistency）。
    """
    editor._write_draft_now()
    assert_model_consistency(editor)
    assert_disk_consistency(editor)
    assert_sidebar_consistency(editor)
    assert_measurement_state_reset(editor)
    assert_draft_consistency(editor)
