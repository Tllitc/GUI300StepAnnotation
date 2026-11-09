# -*- coding: utf-8 -*-
"""一致性不变量断言工具（INV-1 ~ INV-10）

assert_all 适用于任务进行中的编辑现场；任务完成后请用 assert_final_json。
"""
import copy
import hashlib
import json
import os
import re

from annotation_editor import StepListItemWidget
from helpers import drain_sidebar_thumbs, flush_events

PNG_NAME_RE = re.compile(r"^gui_(\d{6})_\d{4}\.png$")
SEQ_RE = re.compile(r"^gui_\d{6}_(\d{4})\.png$")


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

    # INV-3 图步单射：当前轮 steps_data 内 + rounds 全体跨轮单射
    assert len(steps_refs) == len(set(steps_refs)), \
        f"steps_data 内截图被多个步骤引用: {steps_refs}"
    for r, rnd in enumerate(editor.rounds):
        refs = _round_screenshots([rnd])
        assert len(refs) == len(set(refs)), f"第 {r} 轮内截图重复引用: {refs}"
    # 跨轮全局单射：同一张截图不得被两轮引用（轮次折叠的直接证据）
    first_round_of = {}
    for r, rnd in enumerate(editor.rounds):
        for fn in _round_screenshots([rnd]):
            assert fn not in first_round_of, (
                f"跨轮截图重复引用: {fn}，首次出现于第 {first_round_of[fn]} 轮，"
                f"再次出现于第 {r} 轮"
            )
            first_round_of[fn] = r
    # steps_data 是「尚未落轮的当前轮」，不得与任何已落轮引用同一批截图
    overlap = sorted(set(steps_refs) & set(first_round_of))
    assert not overlap, f"steps_data 与 rounds 引用同一批截图（轮次折叠）: {overlap}"

    # INV-4 无孤儿 + 磁盘命名规范
    if gui_dir and os.path.isdir(gui_dir):
        disk_pngs = [name for name in os.listdir(gui_dir) if name.endswith(".png")]
        for name in disk_pngs:
            assert PNG_NAME_RE.match(name), f"磁盘截图命名不规范: {name}"
        if not allow_orphans:
            orphans = [name for name in disk_pngs if name not in reachable]
            assert not orphans, f"存在孤儿截图: {orphans}"


def saved_round_screenshots(editor):
    """已落入 rounds 的全部截图名（独立推导基准，不依赖产品重建逻辑）"""
    return set(_round_screenshots(editor.rounds))


def _expected_draft_steps(editor):
    """按语义独立推导草稿应含步骤。

    不变式：草稿的 steps_data 必须恰好等于「当前尚未落入 rounds 的步骤」，
           且与 rounds 中任何一轮的 trajectory 截图引用无交集。

    注意：这里**刻意不复制**产品 _write_draft_now 的 `rounds[-1]` 重建分支——
    复制产品逻辑会让断言与缺陷同步漂移，无法区分「产品修好了」与「断言跟着一起错」。
    """
    saved_shots = saved_round_screenshots(editor)
    return [{
        "screenshot": s.get("screenshot", ""),
        "intent": s.get("intent", ""),
        "action_data": copy.deepcopy(s.get("action_data") or {}),
        "vertices": copy.deepcopy(s.get("vertices")),
    } for s in editor.steps_data if s.get("screenshot") not in saved_shots]


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
    # 草稿 steps_data 与草稿 rounds 的截图集合必须交集为空：
    # 交集非空即「已落轮的步骤又被当成当前轮写进草稿」——B20a 轮次折叠的直接证据。
    draft_step_shots = {g.get("screenshot") for g in got if g.get("screenshot")}
    draft_round_shots = set(_round_screenshots(draft.get("rounds") or []))
    both = sorted(draft_step_shots & draft_round_shots)
    assert not both, f"草稿 steps_data 与 rounds 引用同一批截图（轮次折叠）: {both}"
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
    # 跨全部轮次的截图名 -> 首次出现的 (round, step)
    all_seen_shots = {}
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
            # 跨轮全局唯一：折叠会让同一批截图在多个 trajectory 中重复出现
            first_r, first_s = all_seen_shots.get(fn, (None, None))
            assert fn not in all_seen_shots, (
                f"跨轮截图重复 {fn}，首次出现于 round {first_r} step {first_s}，"
                f"再次出现于 round {r // 2} step {j}"
            )
            all_seen_shots[fn] = (r // 2, j)
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
    """组合入口：INV-9 + INV-1 + INV-2/3/4/5 + INV-11 + INV-8 + INV-6

    INV-11 在组合入口用 strict_monotonic=False（只保证全局唯一 + 命名合规 +
    引用存在）：「在当前步后插入」天然把磁盘 max+1 的新图放到中间（B10），
    严格递增模式留给专项用例显式调用（见 DI-7：非插入场景必须传 True，
    以便捕获 B38 类「序号与 step 顺序脱钩」的分配缺陷）。
    """
    assert_transient(editor)
    assert_model(editor)
    assert_files(editor, allow_orphans=allow_orphans)
    assert_screenshot_order(editor, strict_monotonic=False)
    assert_sidebar(editor)
    assert_draft(editor)


# ---------------------------------------------------------------------------
# INV-11 截图序号可追溯
# ---------------------------------------------------------------------------
def _seq_of(name):
    m = SEQ_RE.match(name or "")
    return int(m.group(1)) if m else None


def assert_screenshot_order(editor, strict_monotonic=True, allow_holes=True):
    """INV-11 截图序号：全局唯一、命名合规、（可选）无空洞、（可选）单调递增。

    :param strict_monotonic: True 时断言 steps_data 与各轮 trajectory 的序号
        序列严格递增，且轮间不回退、未落轮的 steps_data 序号全部大于已落轮。
        「插入中间步」场景天然破坏该性质（新图取磁盘 max+1 却插到中间），
        此类用例须显式传 False，只保留「全局唯一 + 命名合规 + 引用存在」。
    :param allow_holes: False 时额外断言 set(nums) == set(range(1, len(nums)+1))。
        删除中间步会留空洞，因此默认允许。
    """
    gui_dir = editor.gui_dir or ""
    step_names = _step_screenshots(editor.steps_data)
    round_name_lists = [_round_screenshots([rnd]) for rnd in editor.rounds]

    all_names = list(step_names)
    for names in round_name_lists:
        all_names.extend(names)
    for name in all_names:
        assert SEQ_RE.match(name), f"截图命名不规范: {name}"
        assert os.path.isfile(os.path.join(gui_dir, name)), f"引用的截图不存在: {name}"
    dupes = sorted({n for n in all_names if all_names.count(n) > 1})
    assert not dupes, f"截图序号被多个步骤重复引用: {dupes}"

    nums = [n for n in (_seq_of(x) for x in all_names) if n is not None]
    if not allow_holes and nums:
        assert set(nums) == set(range(1, len(nums) + 1)), \
            f"截图序号存在空洞或不从 1 起: {sorted(nums)}"

    if not strict_monotonic:
        return

    def _assert_increasing(names, where):
        seq = [_seq_of(n) for n in names]
        for i in range(1, len(seq)):
            assert seq[i] > seq[i - 1], (
                f"{where} 截图序号未严格递增: {names[i - 1]} -> {names[i]}"
            )

    for r, names in enumerate(round_name_lists):
        _assert_increasing(names, f"第 {r} 轮")
    _assert_increasing(step_names, "steps_data")
    saved_max = max([_seq_of(n) for names in round_name_lists for n in names] or [0])
    step_min = min([_seq_of(n) for n in step_names] or [saved_max + 1])
    assert step_min > saved_max, (
        f"未落轮步骤序号({step_min}) 未大于已落轮最大序号({saved_max})，"
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
    """INV-12 磁盘零变化：断言编辑模式下不改盘。

    适用于「编辑模式本就不该动盘」的场景（不产生 draft、不动 coords 文件）。
    放开重截图/删步后，这两类操作**必然**改盘，须改用下面的细粒度断言。
    """
    after = snapshot_dir(gui_dir)
    added = sorted(set(after) - set(snapshot))
    removed = sorted(set(snapshot) - set(after))
    changed = sorted(n for n in set(snapshot) & set(after) if snapshot[n] != after[n])
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

    :param rounds: 最终 JSON 还原出的轮次列表（见 test_data_integrity._load_rounds）
    :param skip_round_index: 跳过校验的轮次下标（正在被编辑的那一轮，
        其步骤可能被合法删除）
    """
    missing = []
    for i, round_data in enumerate(rounds or []):
        if i == skip_round_index or not isinstance(round_data, dict):
            continue
        for name in _round_screenshots([round_data]):
            if not os.path.isfile(os.path.join(str(gui_dir), name)):
                missing.append((i, name))
    assert not missing, (
        f"INV-12b: 已落轮引用的截图从磁盘消失（误删他轮数据）：{missing}"
    )


# ---------------------------------------------------------------------------
# INV-13 编辑写回保留未编辑部分
# ---------------------------------------------------------------------------
def _normalize_coords(loaded):
    """兼容三端两种外层结构：纯数组 / {"version":..., "coords":[...]}"""
    if loaded is None:
        return []
    if isinstance(loaded, list):
        return loaded
    if isinstance(loaded, dict):
        return loaded.get("coords") or []
    return []


def coords_by_round(coords):
    """按轮切段：优先用显式 round 字段，缺失时按 step 变小切段"""
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
        elif isinstance(prev_step, int) and isinstance(step, int) and step < prev_step:
            current += 1
        groups.setdefault(current, []).append(entry)
        if isinstance(step, int):
            prev_step = step
    return groups


def assert_edit_writeback_preserved(gui_dir, gui_number, before_data, before_coords,
                                    edited_round_index):
    """INV-13 编辑写回：未编辑的消息与 coords 必须逐字段保留

    :param before_data: 编辑前读到的完整 gui_N.json dict
    :param before_coords: 编辑前的 coords（list 或 {"coords": [...]} 均可）
    :return: (after_data, after_coords)
    """
    gui_dir = str(gui_dir)
    json_path = os.path.join(gui_dir, f"gui_{gui_number}.json")
    coords_path = os.path.join(gui_dir, f"gui_{gui_number}_coords.json")
    assert os.path.isfile(json_path), f"编辑写回后最终 JSON 缺失: {json_path}"
    with open(json_path, encoding="utf-8") as f:
        after = json.load(f)

    before_messages = (before_data or {}).get("messages") or []
    after_messages = after.get("messages") or []
    assert len(after_messages) == len(before_messages), (
        f"messages 条数被改写: {len(before_messages)} -> {len(after_messages)}"
    )
    assert [m.get("role") for m in after_messages] == \
           [m.get("role") for m in before_messages], "messages 角色序列被改写"
    touched = {2 * edited_round_index, 2 * edited_round_index + 1}
    for i, (b, g) in enumerate(zip(before_messages, after_messages)):
        if i in touched:
            continue
        assert g == b, (
            f"messages[{i}]（非编辑轮，role={b.get('role')!r}）被改写或丢失"
        )

    after_coords = None
    if os.path.isfile(coords_path):
        with open(coords_path, encoding="utf-8") as f:
            after_coords = _normalize_coords(json.load(f))
    before_norm = _normalize_coords(before_coords)
    if before_norm:
        assert after_coords, "原 coords 非空但写回后为空（空覆盖）"
        before_groups = coords_by_round(before_norm)
        after_groups = coords_by_round(after_coords)
        for r, entries in before_groups.items():
            if r == edited_round_index:
                continue
            assert after_groups.get(r) == entries, \
                f"未编辑轮 round={r} 的 coords 条目被改写"
    return after, after_coords


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
