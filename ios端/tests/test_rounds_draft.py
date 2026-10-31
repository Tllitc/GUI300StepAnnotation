# -*- coding: utf-8 -*-
"""多轮（answer 收尾）与草稿交叉测试组（7.1 ~ 7.5）。

只依赖真实产品代码路径（截图/确认/删除/撤销/插入/切轮/草稿/续采/最终落盘），
对话框由 conftest.dialogs 自动应答；异步点一律 helpers._wait_until 轮询驱动。

缺陷编号约定：
    D-6：草稿实时序列化下标可能与 steps_data 错位（current_step 不同步）。
    D-8：delete_current_step 的删图引用检查只查 steps_data，不查历史 rounds。

插入步落表说明：
    插入截图分支自带 rebuild_items；D-2 修复后 confirm_step 仅在侧栏
    条目数不足时补建，插入步走 confirm 或 display_step 导航落表均合法。
    本组沿用“插入后 display_step 导航落表”的编排；7.3 草稿核对只查
    磁盘草稿，不依赖侧栏。
"""

import json
import os

from PyQt5.QtTest import QTest

from annotation_editor import AnnotationEditor
from data_manager import DataManager
from fakes import FakeScreenCapture
from helpers import (
    _wait_until,
    capture,
    confirm,
    fill_step,
    finish_task,
    flush_draft,
    walk_steps,
)
from invariants import (
    assert_all,
    assert_disk_consistency,
    assert_final_json_consistency,
)


# ----------------------------------------------------------------------
# 本文件内小助手
# ----------------------------------------------------------------------

def _round_shot_names(editor, round_index):
    """取某一历史轮 trajectory 引用的全部截图文件名（有序）。"""
    result = []
    for traj in editor.rounds[round_index].get("trajectory", []):
        name = (traj.get("observation") or {}).get("screenshot")
        if name:
            result.append(name)
    return result


def _insert_capture(editor):
    """在当前步之后触发插入截图（真实 start_insert_capture + 50ms QTimer）。

    返回 (新插入步截图文件名, 插入下标)。插入分支已重建侧栏；插入步的
    落表本组统一用 display_step 导航完成（见模块头“插入步落表说明”）。
    """
    anchor = editor.current_step
    editor.start_insert_capture()
    _wait_until(
        lambda: not editor._screenshot_in_progress,
        message="插入截图未在超时内完成",
    )
    QTest.qWait(80)
    assert editor._current_screenshot_filename, "插入截图后当前步没有截图文件名"
    return editor._current_screenshot_filename, anchor + 1


def _land_inserted_step(editor, insert_index):
    """给插入步补标注并通过 display_step 导航落表（真实产品路径）。"""
    fill_step(editor, action="click")
    # 先离开插入步触发 _save_current_to_steps，再回到插入步并确认其已在表内
    editor.display_step(0)
    editor.display_step(insert_index)
    assert editor.steps_data[insert_index]["screenshot"] == (
        editor._current_screenshot_filename
    )


def _load_raw_draft(editor):
    """直接从磁盘读取当前 gui 目录草稿 JSON（不经任何产品侧封装）。"""
    draft = DataManager.load_draft_from_dir(editor.gui_dir)
    assert draft is not None, "草稿文件不存在"
    return draft


def _assert_draft_matches_steps(editor, expected_current=None):
    """7.3/D-6 核心逐条核对：草稿 steps 与 steps_data 条数/顺序/截图完全一致。

    - 每条 screenshot 与模型同位相等、无 screenshot_filepath 键、无重复
    - current_step_index 与编辑器 current_step 相等且落在 [0, len]
    """
    draft = _load_raw_draft(editor)
    draft_steps = draft.get("steps_data", [])
    live_steps = editor.steps_data

    assert len(draft_steps) == len(live_steps), (
        f"草稿步数 {len(draft_steps)} != 模型步数 {len(live_steps)}；"
        f"草稿截图序列={[s.get('screenshot') for s in draft_steps]}"
    )

    seen = set()
    for i, (d, s) in enumerate(zip(draft_steps, live_steps)):
        d_name = d.get("screenshot")
        s_name = s.get("screenshot")
        assert d_name == s_name, (
            f"D-6: 草稿第 {i} 位截图 {d_name!r} != 模型第 {i} 位 {s_name!r}；"
            f"草稿序列={[x.get('screenshot') for x in draft_steps]}，"
            f"模型序列={[x.get('screenshot') for x in live_steps]}"
        )
        assert "screenshot_filepath" not in d, (
            f"草稿第 {i} 位泄漏 screenshot_filepath 绝对路径"
        )
        assert d_name not in seen, f"草稿第 {i} 位截图重复：{d_name}"
        seen.add(d_name)

    idx = draft.get("current_step_index")
    total = len(draft_steps)
    assert 0 <= idx <= total, f"current_step_index={idx} 越界（总步数 {total}）"
    if expected_current is not None:
        assert idx == expected_current, (
            f"草稿 current_step_index={idx} != 期望 {expected_current}"
        )
    # D-6 关键：草稿下标必须与内存 current_step 同步
    assert idx == editor.current_step, (
        f"D-6: 草稿 current_step_index={idx} 与编辑器 current_step="
        f"{editor.current_step} 不同步"
    )
    return draft


def _make_resume_editor(dm, dialogs, qapp):
    """7.5 本地工厂：照搬 conftest.editor 的真实构造步骤。

    initialize_gui_directory 会先按母目录现状分配一个新 gui 编号（空目录），
    随后 load_from_draft 会把 gui_number/gui_dir 重新指回草稿所在目录，
    遗留的空 gui 目录不参与任何引用/断言。
    """
    ed = AnnotationEditor(
        data_manager=dm,
        app_name="测试App",
        task_instruction="测试指令",
        screen_info={"screen_size": [390, 844]},
        app_type="iOS",
        udid=None,
        close_callback=None,
    )
    ed.initialize_gui_directory()
    ed.screen_capture = FakeScreenCapture()
    ed._test_dialogs = dialogs
    qapp.processEvents()
    return ed


# ----------------------------------------------------------------------
# 7.1 D-8：第二轮变更不得删除/覆盖第一轮历史轮引用的截图
# ----------------------------------------------------------------------

def test_mutate_second_round_keeps_first_round_files_D8(editor, qapp, dialogs):
    """第二轮 删除/撤销/插入 + 序号回落复用，第一轮 rounds 引用文件全部存活。

    D-8 定性（代码分析 + 本实测双重结论：不可达，安全通过，不打 xfail）：
      1. 截图序号 = 磁盘 max+1（data_manager.get_next_screenshot_number），
         中间序号空洞永不复用，只可能在“最大号文件被删”后于顶部回落复用；
      2. 切轮（answer）时 _save_current_round_to_list 已把第一轮 steps_data
         消费进 editor.rounds 并清空 steps_data。第二轮 delete_current_step
         的 path 只能来自第二轮 steps_data（序号严格大于第一轮最大号），
         因此第一轮文件永远不会成为删除目标 —— 引用检查漏查 rounds 的
         防御缺口（annotation_editor.py 1704-1707）在现有 UI 路径下无触发对象；
      3. 第一轮文件删不掉 => 持续占据磁盘序号下限 => 即使第二轮把自己产生
         的更大号文件全部删除使 max 回落，下一个新号也只可能复用“第二轮
         已释放的顶部号”，永远不会落到第一轮存活文件的序号上，故历史轮
         文件既不会被删、也不会被覆盖。
    """
    # ---- 第一轮：3 个 click + 1 个 answer 收尾 -> 磁盘 0001~0004 ----
    walk_steps(editor, 3, action="click")
    capture(editor)
    fill_step(editor, action="answer")
    confirm(editor, wait_answer_round=True)

    assert len(editor.rounds) == 1
    assert editor.steps_data == []
    round1_names = _round_shot_names(editor, 0)
    assert len(round1_names) == 4
    round1_set = set(round1_names)
    gui_dir = editor.gui_dir
    # 切轮后第一轮文件已全部只被 rounds 引用，必须全在磁盘上
    assert_disk_consistency(editor)
    assert all(os.path.isfile(os.path.join(gui_dir, n)) for n in round1_set)

    # ---- 第二轮：先走 2 步（0005、0006），再把两步全部删除 ----
    walk_steps(editor, 2, action="click")
    editor.display_step(0)
    editor.delete_current_step()        # 删 0005（0006 仍被引用，互不误伤）
    assert_all(editor)
    editor.delete_current_step()        # 当前步已是唯一剩余的 0006 -> 删空
    assert editor.steps_data == []

    # 磁盘 max 已回落到第一轮的 0004；第一轮文件一张不少
    assert all(os.path.isfile(os.path.join(gui_dir, n)) for n in round1_set), (
        "D-8: 第二轮删除导致第一轮历史轮引用文件缺失"
    )
    assert_disk_consistency(editor)  # 磁盘仅剩 0001~0004，全部由 rounds 引用

    # ---- 序号回落复用（普通截图路径）：删空后编辑器回到初始空白态，
    #      此时 take_screenshot 走“新序号”分支（非 replacing），磁盘 max
    #      已随第二轮文件删除回落到 0004，故下一号复用刚释放的顶部号 0005；
    #      该号是第二轮自己释放的，不可能命中第一轮仍引用的 0001~0004 ----
    reused = capture(editor)
    assert reused.endswith("_0005.png"), (
        f"序号回落复用未发生在第二轮释放的顶部号：实际 {reused}"
    )
    assert all(os.path.isfile(os.path.join(gui_dir, n)) for n in round1_set), (
        "D-8: 回落复用新截图后第一轮文件缺失（疑似覆盖）"
    )
    fill_step(editor, action="click")
    confirm(editor)                    # 空白态标准追加：模型 +1、侧栏 +1，无幽灵
    assert_all(editor)

    # ---- 插入：锚点第 1 步后插入新步（0006），display_step 导航落表 ----
    editor.display_step(0)
    inserted, ins_idx = _insert_capture(editor)
    assert inserted.endswith("_0006.png")
    _land_inserted_step(editor, ins_idx)   # [0005,0006]
    assert_all(editor)

    # ---- 撤销：撤销刚插入的 0006 步（先回到该步再 undo），释放顶部号 ----
    editor.display_step(ins_idx)
    editor.undo_last_step()               # [0005]
    assert_all(editor)
    assert all(os.path.isfile(os.path.join(gui_dir, n)) for n in round1_set)

    # ---- 撤销释放后序号二次回落：再插入一张，应复用刚释放的 0006。
    #      插入路径自带 rebuild_items，落表仍走 display_step 导航 ----
    editor.display_step(0)
    again, again_idx = _insert_capture(editor)
    assert again.endswith("_0006.png"), f"撤销释放后序号复用异常：{again}"
    _land_inserted_step(editor, again_idx)   # [0005,0006]
    assert_all(editor)
    assert all(os.path.isfile(os.path.join(gui_dir, n)) for n in round1_set)

    # ---- terminate 结束（不继续新任务），两轮合并落盘 ----
    finish_task(editor, continue_new=False)
    qapp.processEvents()

    # 第一轮引用文件最终仍一张不少
    for name in round1_names:
        assert os.path.isfile(os.path.join(gui_dir, name)), (
            f"D-8: 最终落盘后第一轮引用截图缺失：{name}"
        )

    data, coords = assert_final_json_consistency(
        gui_dir, gui_dir=gui_dir, expected_rounds=2
    )
    # round/step 归属：coords 前 4 条属 round 0，其后属 round 1；
    # 第二轮不得引用任何第一轮文件名
    round0_json = [
        (e.get("observation") or {}).get("screenshot")
        for e in data["messages"][1]["trajectory"]
    ]
    round1_json = [
        (e.get("observation") or {}).get("screenshot")
        for e in data["messages"][3]["trajectory"]
    ]
    assert round0_json == round1_names, "第一轮 trajectory 截图序列与内存 rounds 不符"
    assert set(round1_json).isdisjoint(round1_set), (
        f"第二轮截图与第一轮重名：{set(round1_json) & round1_set}"
    )
    assert [c["round"] for c in coords[:4]] == [0] * 4
    assert [c["round"] for c in coords[4:]] == [1] * (len(coords) - 4)
    assert all(c["_version"] == "3.1" for c in coords)


# ----------------------------------------------------------------------
# 7.2 answer 时取消“新指令”输入框
# ----------------------------------------------------------------------

def test_answer_cancel_instruction_dialog(editor, qapp, dialogs):
    """answer 切轮问答中模拟 QInputDialog 取消（input_ok=False）。

    产品既有语义（读码确认，annotation_editor.py 2294/2315-2319）：
      - 取消时 _save_current_round_to_list 已经执行（在弹输入框之前），
        故当前轮已被消费进 rounds、steps_data 已清空；
      - _start_new_round 走 else 分支，仅置状态文本“已取消新任务”，
        不改 instruction、不重建任何状态、不关闭窗口、不清 rounds。
    本测试固化该语义并核对 steps_data/rounds/草稿/磁盘均不损坏。
    """
    walk_steps(editor, 2, action="click")
    capture(editor)
    fill_step(editor, action="answer")

    dialogs.input_ok = False
    get_text_calls_before = sum(1 for c in dialogs.calls if c[0] == "getText")
    confirm(editor, wait_answer_round=True)
    dialogs.input_ok = True

    # 输入框确实被调用且被“取消”
    get_text_calls = [c for c in dialogs.calls if c[0] == "getText"]
    assert len(get_text_calls) == get_text_calls_before + 1

    # 既有语义：轮次已归档、未开启新一轮、界面停在空白态
    assert len(editor.rounds) == 1
    assert editor.steps_data == []
    assert editor.current_step == 0
    assert editor._current_screenshot_filename is None
    assert "已取消新任务" in editor.status_label.text()
    # 指令保持第一轮指令（未被空串/新值替换）
    assert editor.task_instruction == "测试指令"

    # 模型/磁盘/侧栏/草稿全套不变量：磁盘 0001~0003 仅由 rounds 引用，无孤儿
    assert_all(editor)

    # 草稿内容固化：steps 为空、rounds 1 个、current_step_index=0
    draft = _load_raw_draft(editor)
    assert draft["steps_data"] == []
    assert len(draft["rounds"]) == 1
    assert draft["current_step_index"] == 0
    draft_round0 = [
        (t.get("observation") or {}).get("screenshot")
        for t in draft["rounds"][0]["trajectory"]
    ]
    assert len(draft_round0) == 3
    assert all(
        os.path.isfile(os.path.join(editor.gui_dir, n)) for n in draft_round0
    )


# ----------------------------------------------------------------------
# 7.3 D-6：删除中间步 / 插入 / 撤销后“立即”落草稿，逐条核对下标不错位
# ----------------------------------------------------------------------

def test_draft_immediately_after_mutations_D6(editor, qapp, dialogs):
    """每次变更后立即 _write_draft_now（不等 1000ms 防抖），核对草稿 JSON。

    D-6 定性（不可达，安全通过，不打 xfail）：
    _write_draft_now 仅在 i == current_step 且当前步有截图时用
    _collect_step_data() 实时替换该位，且仅当 current_step >= len(steps_data)
    时才 append 未入表新步。全部会移动 current_step 的产品路径都与
    steps_data 原子对齐：
      - display_step：current_step 置为已存在下标，steps_data 不动；
      - 插入截图：steps_data.insert(idx) 与 current_step=idx 同一次回调完成；
      - delete_current_step：先 del 再把 current_step 夹紧到现存步并恢复 UI；
      - confirm_step：current_step=len(steps_data)，恰好走 append 分支。
    故实时收集到的截图必然属于它被写入的那一位，不存在串下标。
    （本组草稿断言本身不含侧栏；D-2 修复后插入步 confirm 也不再产生重复项。）
    """
    walk_steps(editor, 4, action="click")  # 0001~0004
    base_names = [s["screenshot"] for s in editor.steps_data]
    assert base_names[-1].endswith("_0004.png")

    # ---- (a) 删除中间步：先 display 到第 2 步（变更后立即落盘）----
    editor.display_step(1)
    flush_draft(editor)
    _assert_draft_matches_steps(editor, expected_current=1)

    editor.delete_current_step()           # 删 0002；剩余 [0001,0003,0004]
    flush_draft(editor)
    _assert_draft_matches_steps(
        editor, expected_current=editor.current_step
    )
    draft = _load_raw_draft(editor)
    assert [s["screenshot"] for s in draft["steps_data"]] == [
        base_names[0], base_names[2], base_names[3]
    ]

    # ---- (b) 插入：锚点第 1 步后插入（新文件 0005），插入回调后立即落盘 ----
    editor.display_step(0)
    inserted, ins_idx = _insert_capture(editor)   # -> [0001,0005,0003,0004]
    assert inserted.endswith("_0005.png")
    flush_draft(editor)
    _assert_draft_matches_steps(
        editor, expected_current=editor.current_step
    )
    draft = _load_raw_draft(editor)
    assert [s["screenshot"] for s in draft["steps_data"]] == [
        base_names[0], inserted, base_names[2], base_names[3]
    ], "D-6: 插入后草稿顺序/下标与模型不一致"

    # 插入步补标注并经 display_step 导航落表，再立即核对草稿
    _land_inserted_step(editor, ins_idx)
    flush_draft(editor)
    _assert_draft_matches_steps(editor, expected_current=ins_idx)

    # ---- (c) 撤销：导航到中间步（0003）后撤销，立即落盘 ----
    editor.display_step(2)
    flush_draft(editor)
    _assert_draft_matches_steps(editor, expected_current=2)
    editor.undo_last_step()                # 删 0003 -> [0001,0005,0004]
    flush_draft(editor)
    _assert_draft_matches_steps(
        editor, expected_current=editor.current_step
    )
    draft = _load_raw_draft(editor)
    names = [s["screenshot"] for s in draft["steps_data"]]
    assert names == [base_names[0], inserted, base_names[3]], (
        f"D-6: 撤销后草稿序列异常：{names}"
    )
    assert all("screenshot_filepath" not in s for s in draft["steps_data"])

    # 最终正常收尾：模型/磁盘/侧栏/草稿 + 最终 JSON 全部一致
    assert_all(editor)
    finish_task(editor, continue_new=False)
    qapp.processEvents()
    assert_final_json_consistency(
        editor.gui_dir, gui_dir=editor.gui_dir, expected_rounds=1
    )


# ----------------------------------------------------------------------
# 7.4 高频交替变更：删除 -> 插入 -> 截图(替换) -> 导航 -> 撤销
# ----------------------------------------------------------------------

def test_high_frequency_alternating_mutations(editor, qapp, dialogs):
    """3 轮以上高频交替序列，每一小步后跑全套不变量，结束后验最终 JSON。

    插入步用 display_step 导航落表，随后撤销的就是
    刚插入的新步；序列在每轮后净删 1 步，三轮中步数 4->3->2->1。
    """
    walk_steps(editor, 4, action="click")

    for iteration in range(3):
        n_before = len(editor.steps_data)
        assert n_before >= 2, f"第 {iteration} 轮开始时步数不足以支撑序列"

        # 1) 删除第 2 步（净 -1）
        editor.display_step(1)
        editor.delete_current_step()
        assert_all(editor)

        # 2) 在第 1 步后插入新截图步（净 +1），导航落表
        editor.display_step(0)
        inserted, ins_idx = _insert_capture(editor)
        _land_inserted_step(editor, ins_idx)
        assert_all(editor)

        # 3) 回到插入步再截一张：同步骤重新截图 => 原地覆盖（文件名不变）
        editor.display_step(ins_idx)
        replaced = capture(editor)
        assert replaced == inserted, (
            f"同步骤重新截图应原地覆盖、序号不变：{replaced} != {inserted}"
        )
        assert_all(editor)

        # 4) display_step 来回导航
        editor.display_step(0)
        assert_all(editor)
        editor.display_step(len(editor.steps_data) - 1)
        assert_all(editor)

        # 5) 撤销当前（末位）刚插入的步（净 -1）
        editor.undo_last_step()
        assert_all(editor)
        assert len(editor.steps_data) == n_before - 1

    assert len(editor.steps_data) == 1
    # terminate 收尾：最终 JSON 与磁盘一致
    finish_task(editor, continue_new=False)
    qapp.processEvents()
    assert_final_json_consistency(
        editor.gui_dir, gui_dir=editor.gui_dir, expected_rounds=1
    )


# ----------------------------------------------------------------------
# 7.5 完整续采链路：混合变更 -> 草稿 -> 第二实例 load_from_draft
#     -> 继续变更 -> answer 进第二轮 -> terminate
# ----------------------------------------------------------------------

def test_full_resume_link_after_mixed_mutations(editor, qapp, dialogs, dm):
    gui_dir = editor.gui_dir

    # ---- 第一实例：第一轮内 走步 + 删除 + 插入 + 撤销 混合序列 ----
    walk_steps(editor, 3, action="click")      # 0001,0002,0003
    editor.display_step(1)
    editor.delete_current_step()               # 删 0002 -> [1,3]
    assert_all(editor)

    editor.display_step(0)
    inserted, ins_idx = _insert_capture(editor)   # 0004 -> [1,4,3]
    assert inserted == "gui_000001_0004.png"
    _land_inserted_step(editor, ins_idx)
    assert_all(editor)

    editor.display_step(2)
    editor.undo_last_step()                    # 删 0003 -> [1,4]
    assert_all(editor)

    flush_draft(editor)
    draft_snapshot = _load_raw_draft(editor)
    assert [s["screenshot"] for s in draft_snapshot["steps_data"]] == [
        "gui_000001_0001.png", inserted
    ]
    assert draft_snapshot["rounds"] == []

    # 第一实例使命结束：防止其 fixture 回收时 closeEvent 把旧草稿写回
    # （第二实例最终落盘会删除草稿；此处仅切换运行时标记，不改产品代码）
    editor._draft_discarded = True

    # ---- 第二实例：同 dm、真实构造、load_from_draft 指回同一 gui_dir ----
    ed2 = _make_resume_editor(dm, dialogs, qapp)
    try:
        draft = DataManager.load_draft_from_dir(gui_dir)
        need_instruction = ed2.load_from_draft(draft)
        assert need_instruction is False  # 当前轮仍有步，不应追问新指令
        assert ed2.gui_dir == gui_dir
        assert [s["screenshot"] for s in ed2.steps_data] == [
            "gui_000001_0001.png", inserted
        ]
        assert_all(ed2)

        # 继续变更：插入一步（0005），导航落表后直接删除该步（释放顶部号）
        ed2.display_step(0)
        new_shot, new_idx = _insert_capture(ed2)      # [1,5,4]
        assert new_shot.endswith("_0005.png")
        _land_inserted_step(ed2, new_idx)
        ed2.display_step(new_idx)
        ed2.delete_current_step()                     # 删 0005 -> [1,4]
        assert_all(ed2)

        # 顶部号回落后，在第一轮末尾“插入”一个 answer 步：锚点取当前末位步
        # （0004），插入位置 = 锚点+1，故 answer 成为新一轮收尾步；插入走
        # 新序号分支，复用刚释放的顶部号 0005；插入路径自带 rebuild_items。
        # 当前 UI 已停在新插入步，直接把它落表为 answer 再确认即可切轮。
        ed2.display_step(len(ed2.steps_data) - 1)
        ans_shot, ans_idx = _insert_capture(ed2)      # [1,4,5]
        assert ans_shot.endswith("_0005.png"), (
            f"续采实例序号回落复用异常：{ans_shot}"
        )
        assert ans_idx == 2
        fill_step(ed2, action="answer")
        # answer 分支在创建侧栏条目之前 return，落表用导航完成
        ed2.display_step(0)
        ed2.display_step(ans_idx)
        assert ed2.steps_data[ans_idx]["screenshot"] == ans_shot
        confirm(ed2, wait_answer_round=True)          # answer 切轮
        assert_all(ed2)
        assert len(ed2.rounds) == 1
        assert ed2.steps_data == []
        assert ed2.task_instruction == "第二轮新指令"

        # 第二轮再走 2 个 click（0006、0007）
        walk_steps(ed2, 2, action="click")
        assert_all(ed2)

        # terminate 结束（0008），两轮合并
        finish_task(ed2, continue_new=False)
        qapp.processEvents()
    finally:
        ed2.close()
        ed2.deleteLater()
        qapp.processEvents()

    # ---- 全量交叉校验：2 轮；所有引用截图可达、无孤儿 ----
    data, coords = assert_final_json_consistency(
        gui_dir, gui_dir=gui_dir, expected_rounds=2
    )
    round0_shots = [
        (e.get("observation") or {}).get("screenshot")
        for e in data["messages"][1]["trajectory"]
    ]
    round1_shots = [
        (e.get("observation") or {}).get("screenshot")
        for e in data["messages"][3]["trajectory"]
    ]
    # 第一轮（续采前的 1,4 + 续采后插入切轮复用的 5）共 3 步；
    # 第二轮两个 click（0006、0007）+ terminate（0008）共 3 步
    assert round0_shots == [
        "gui_000001_0001.png",
        inserted,
        "gui_000001_0005.png",
    ]
    assert round1_shots == [
        "gui_000001_0006.png",
        "gui_000001_0007.png",
        "gui_000001_0008.png",
    ]
    assert set(round0_shots).isdisjoint(round1_shots)
    # coords 的 round/step 归属连续
    assert [(c["round"], c["step"]) for c in coords] == [
        (0, 0), (0, 1), (0, 2),
        (1, 0), (1, 1), (1, 2),
    ]
    assert all(c["_version"] == "3.1" for c in coords)

    # 所有严格命名 PNG 恰好是两轮引用集合，无孤儿、无缺失
    referenced = set(round0_shots) | set(round1_shots)
    on_disk = {f for f in os.listdir(gui_dir) if f.endswith(".png")}
    assert on_disk == referenced, (
        f"磁盘文件集合与引用集合不一致：多余={on_disk - referenced}，"
        f"缺失={referenced - on_disk}"
    )
    # 草稿已清理
    assert not [f for f in os.listdir(gui_dir) if f.endswith("_draft.json")]
    # 最终 JSON 结构可序列化留证
    json.loads(json.dumps(data, ensure_ascii=False))
