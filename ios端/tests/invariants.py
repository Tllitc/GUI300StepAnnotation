# -*- coding: utf-8 -*-
"""数据一致性不变量断言（INV-1 ~ INV-13 的测试侧实现）。

这些函数只读取产品对象状态与磁盘文件，绝不修改产品代码/状态。
所有断言失败均以 AssertionError 抛出，并带上下文字段。

约定:
    - 严格截图命名正则：^gui_\\d{6}_\\d{4}\\.png$
    - 模型引用：steps_data 中每步的 screenshot 字段（basename）
    - 轮次引用：editor.rounds[*].trajectory[*].observation.screenshot
"""

import hashlib
import json
import os
import re

from data_manager import DataManager


SCREENSHOT_NAME_RE = re.compile(r"^gui_\d{6}_\d{4}\.png$")
SEQ_RE = re.compile(r"^gui_\d{6}_(\d{4})\.png$")


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


def _step_referenced_filenames(steps):
    """收集 steps_data 引用的截图文件名（有序）。"""
    return [s.get("screenshot") for s in steps or [] if s.get("screenshot")]


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
    - rounds 各轮之间、以及 rounds 与 steps_data 之间截图引用无交集
      （INV-3 跨轮单射：轮次折叠的直接证据）
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

    # INV-3 跨轮单射：一张截图只属于一轮。落轮后 steps_data 会被清空
    # （annotation_editor 的 _save_current_round_to_list），因此 steps_data
    # 与 rounds 出现交集只可能是「已落轮步骤又被当成当前轮」。
    saved_by_round = {}
    for r_idx, rnd in enumerate(getattr(editor, "rounds", []) or []):
        for name in _round_referenced_filenames([rnd]):
            first = saved_by_round.get(name)
            assert first is None, (
                f"INV-3: 跨轮截图重复引用 {name}，首次出现于第 {first} 轮，"
                f"再次出现于第 {r_idx} 轮"
            )
            saved_by_round[name] = r_idx
    overlap = sorted(set(seen) & set(saved_by_round))
    assert not overlap, (
        f"INV-3: steps_data 与 rounds 引用同一批截图（轮次折叠）：{overlap}"
    )


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
      - 同一 trajectory 内截图不重复，且跨轮截图全局唯一
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
    # 跨全部轮次的截图名 -> 首次出现的 (r_idx, s_idx)
    all_seen_shots = {}
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
            # 跨轮全局唯一：轮次折叠会让同一批截图在多个 trajectory 中重复出现
            first_r, first_s = all_seen_shots.get(shot, (None, None))
            assert shot not in all_seen_shots, (
                f"INV-9: 跨轮截图重复 {shot}，首次出现于 round {first_r} "
                f"step {first_s}，再次出现于 round {r_idx} step {s_idx}"
            )
            all_seen_shots[shot] = (r_idx, s_idx)

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
    """采集过程中可反复使用的全套不变量：模型/磁盘/序号/侧栏/草稿/测量状态。

    内部会先 flush 草稿（INV-6 依赖落盘）。不含最终 JSON 断言
    （最终 JSON 只在 terminate 后产出，请用 assert_final_json_consistency）。

    INV-11 在组合入口用 strict_monotonic=False（只保证全局唯一 + 命名合规 +
    引用存在）：插入中间步天然破坏严格递增，严格模式留给专项用例显式调用。
    """
    editor._write_draft_now()
    assert_model_consistency(editor)
    assert_disk_consistency(editor)
    assert_screenshot_order(editor, strict_monotonic=False)
    assert_sidebar_consistency(editor)
    assert_measurement_state_reset(editor)
    assert_draft_consistency(editor)


# ----------------------------------------------------------------------
# INV-11：截图序号可追溯
# ----------------------------------------------------------------------

def _seq_of(name):
    m = SEQ_RE.match(name or "")
    return int(m.group(1)) if m else None


def assert_screenshot_order(editor, strict_monotonic=True, allow_holes=True):
    """INV-11 截图序号：全局唯一、命名合规、（可选）无空洞、（可选）单调递增。

    :param strict_monotonic: True 时断言 steps_data 与各轮 trajectory 的序号
        序列严格递增，且未落轮的 steps_data 序号全部大于已落轮最大序号。
        「插入中间步」场景天然破坏该性质（新图取磁盘 max+1 却插到中间），
        此类用例须显式传 False，只保留「全局唯一 + 命名合规 + 引用存在」。
    :param allow_holes: False 时额外断言 set(nums) == set(range(1, len(nums)+1))。
        删除中间步会留空洞，因此默认允许。
    """
    gui_dir = editor.gui_dir or ""
    step_names = _step_referenced_filenames(editor.steps_data)
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
    _assert_increasing(step_names, "steps_data")
    saved_max = max(
        [_seq_of(n) for names in round_name_lists for n in names] or [0]
    )
    step_min = min([_seq_of(n) for n in step_names] or [saved_max + 1])
    assert step_min > saved_max, (
        f"INV-11: 未落轮步骤序号({step_min}) 未大于已落轮最大序号({saved_max})，"
        f"新轮复用了旧序号"
    )


# ----------------------------------------------------------------------
# INV-12：磁盘快照（编辑模式零改盘）
# ----------------------------------------------------------------------

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
    """INV-12 磁盘零变化：断言编辑模式下截图/删步/回退不改盘。

    适用于「编辑模式本就不该动盘」的场景（不产生 draft、不动 coords 文件）。
    放开重截图/删步后，这两类操作**必然**改盘，须改用下面的细粒度断言。
    """
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


# ----------------------------------------------------------------------
# INV-12b：编辑模式「允许改盘」的边界（不新增序号、不越界、不误删他轮）
# ----------------------------------------------------------------------

def assert_overwrite_in_place(gui_dir, snapshot, expect_changed):
    """重截图 = 原地覆盖：文件名集合完全不变，且指定文件内容确已改写。

    :param snapshot: 操作前 snapshot_dir(gui_dir)
    :param expect_changed: 期望内容被改写的文件名（单个或集合）

    抓的是两类真实回归：一是重新截图被分配了新序号（文件名集合膨胀、
    旧图变孤儿），二是覆盖根本没生效（内容未变、用户以为重截成功）。
    """
    if isinstance(expect_changed, str):
        expect_changed = {expect_changed}
    expect_changed = set(expect_changed)

    after = snapshot_dir(gui_dir)
    added = sorted(set(after) - set(snapshot))
    removed = sorted(set(snapshot) - set(after))
    assert not added and not removed, (
        f"INV-12b: 重截图未原地覆盖，文件名集合发生变化：新增 {added}，"
        f"删除 {removed}（重截图必须复用原序号，不得另存新文件、不得留孤儿）"
    )

    missing = sorted(n for n in expect_changed if n not in after)
    assert not missing, f"INV-12b: 期望改写的文件不在盘上：{missing}"
    unchanged = sorted(n for n in expect_changed if snapshot.get(n) == after[n])
    assert not unchanged, (
        f"INV-12b: 重截图未真正改写文件内容（覆盖未生效）：{unchanged}"
    )
    # 只有目标文件该变，其余文件必须逐字节不动
    collateral = sorted(
        n for n in expect_changed.symmetric_difference(set(snapshot))
        if n in after and snapshot[n] != after[n]
    )
    assert not collateral, f"INV-12b: 重截图误改了无关文件：{collateral}"


def snapshot_listing(directory):
    """目录下条目名集合（含子目录），用于断言「gui_dir 之外零新增」。"""
    directory = str(directory)
    if not os.path.isdir(directory):
        return set()
    return set(os.listdir(directory))


def assert_no_files_outside(directory, before_listing):
    """路径穿越护栏：断言 directory 下没有任何新增条目。

    save_screenshot(filename=) 的 filename 来自草稿/已交付 JSON，可被篡改；
    校验失效时会把 PNG 写到 gui 目录之外，属不可逆的越权写盘。
    """
    after = snapshot_listing(directory)
    added = sorted(after - before_listing)
    assert not added, (
        f"INV-12b: 在受控目录之外产生了文件（路径穿越）：{added}"
    )


def assert_round_refs_on_disk(gui_dir, rounds, skip_round_index=None):
    """已落轮引用的截图必须全部在盘上（B16/B17 回归）。

    :param rounds: 最终 JSON 的 rounds 列表
    :param skip_round_index: 跳过校验的轮次下标（正在被编辑的那一轮，
        其步骤可能被合法删除）
    """
    missing = []
    for i, round_data in enumerate(rounds or []):
        if i == skip_round_index or not isinstance(round_data, dict):
            continue
        for name in _round_referenced_filenames([round_data]):
            if not os.path.isfile(os.path.join(str(gui_dir), name)):
                missing.append((i, name))
    assert not missing, (
        f"INV-12b: 已落轮引用的截图从磁盘消失（误删他轮数据）：{missing}"
    )


# ----------------------------------------------------------------------
# INV-13：编辑写回保留未编辑部分
# ----------------------------------------------------------------------

def _normalize_coords(loaded):
    """兼容两种外层结构：纯数组 / {"version":..., "coords":[...]}"""
    if loaded is None:
        return []
    if isinstance(loaded, list):
        return loaded
    if isinstance(loaded, dict):
        return loaded.get("coords") or []
    return []


def coords_by_round(coords):
    """按轮切段：优先用显式 round 字段，缺失时按 step 变小切段。"""
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
    """INV-13 编辑写回：未编辑的消息与 coords 必须逐字段保留。

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
        assert after_coords, "INV-13: 原 coords 非空但写回后为空（空覆盖）"
        before_groups = coords_by_round(before_norm)
        after_groups = coords_by_round(after_coords)
        for r_idx, entries in before_groups.items():
            if r_idx == edited_round_index:
                continue
            assert after_groups.get(r_idx) == entries, (
                f"INV-13: 未编辑轮 round={r_idx} 的 coords 条目被改写"
            )
    return after, after_coords
