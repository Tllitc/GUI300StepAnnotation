# -*- coding: utf-8 -*-
"""answer / answer_terminate 多轮问答轨迹的边界加固 + 只读多轮回看器

覆盖：
- 中间步选 answer / answer_terminate / terminate 必须被拦截（终止类动作只能收尾本轮）
- 交付后禁止继续采集（_task_completed 门闩，截图与确认均不得改动现场）
- RoundPreviewDialog 只读回看：轮次下拉、步骤列表、缩略图、大图预览，且不改动数据
- 正常多轮流程不受上述加固影响（messages 结构、落盘 action 口径）
"""
import copy
import os

import pytest
from PyQt5.QtCore import Qt

from annotation_editor import RoundPreviewDialog
from helpers import (_wait_until, capture_and_wait, confirm_n_steps,
                     fill_valid_step, finish_task, flush_events, walk_rounds)
from invariants import assert_final_json

TERMINAL_ACTIONS = ["answer", "answer_terminate", "terminate"]


def _gui_pngs(editor):
    return sorted(name for name in os.listdir(editor.gui_dir)
                  if name.endswith(".png"))


def _json_path(editor):
    return os.path.join(editor.gui_dir, f"gui_{editor.gui_number}.json")


def _go_to_middle_step_with_action(editor, action):
    """回到中间步（第 2 步）并把动作改成终止类动作"""
    editor.jump_to_step(1)
    flush_events()
    assert editor.current_step == 1
    fill_valid_step(editor, action=action, text="中途回答")


@pytest.mark.parametrize("action", TERMINAL_ACTIONS)
def test_mid_round_terminal_action_is_blocked(editor_factory, modal, action):
    """a/b：中间步的 answer/answer_terminate/terminate 一律拦截，现场零副作用"""
    editor = editor_factory()
    confirm_n_steps(editor, 3)
    assert editor.current_step == 3 and len(editor.steps_data) == 3

    steps_before = copy.deepcopy(editor.steps_data)
    warnings_before = len(modal.warnings)

    _go_to_middle_step_with_action(editor, action)
    editor.confirm_step()
    flush_events(400)   # 若被误放行，answer 的 300ms 切轮会在此触发

    assert len(editor.rounds) == 0, "中间步终止动作不应落轮"
    assert len(editor.steps_data) == 3, "中间步终止动作不应改动步骤数"
    assert editor.steps_data == steps_before, "被拦截后步骤现场仍被改写"
    assert not os.path.exists(_json_path(editor)), "中途被拦截却生成了交付 JSON"

    # 只新增了「终止类动作必须是本轮最后一个步骤」这一条提示
    new_warnings = modal.warnings[warnings_before:]
    assert len(new_warnings) == 1, f"应恰有一条拦截提示，实际 {new_warnings}"
    assert "终止类动作必须是本轮最后一个步骤" in new_warnings[0][1]
    assert "第 2 步" in new_warnings[0][1] and "1 个步骤" in new_warnings[0][1]


def test_terminal_action_allowed_on_last_step(editor_factory, modal):
    """对照：末步（未确认空白位的前一步）选 answer 仍可正常落轮"""
    modal.input_text = "第二轮指令"
    editor = editor_factory()
    confirm_n_steps(editor, 2)
    capture_and_wait(editor)
    fill_valid_step(editor, action="answer", text="第一轮回答")
    editor.confirm_step()
    _wait_until(lambda: len(editor.rounds) == 1, message="末步 answer 未落轮")


def test_capture_and_confirm_blocked_after_delivery(editor_factory, modal):
    """c：任务交付后 take_screenshot / confirm_step 均不得改动现场"""
    editor = editor_factory()
    finish_task(editor, modal)
    assert editor._task_completed is True

    pngs_before = _gui_pngs(editor)
    steps_before = len(editor.steps_data)
    seq_before = editor._screenshot_seq

    editor.take_screenshot()
    editor.confirm_step()
    flush_events(1000)   # 覆盖 50ms 截图延迟 / 800ms 冷却

    assert editor._screenshot_seq == seq_before, "交付后仍发起了新截图"
    assert len(editor.steps_data) == steps_before
    assert _gui_pngs(editor) == pngs_before, "交付后 gui 目录被写入新截图"

    # 切轮门闩放开后（模拟已完成弹窗已关闭的常态），截图入口仍被完成态拦住
    editor._round_transition_pending = False
    editor.take_screenshot()
    flush_events(100)
    assert editor.status_label.text() == "任务已保存，请先选择是否开始新任务"
    assert editor._screenshot_seq == seq_before
    assert _gui_pngs(editor) == pngs_before


def test_round_preview_dialog_is_readonly(editor_factory, modal):
    """d：只读多轮回看器 —— 轮次/列表/缩略图/大图可用，且不改动数据"""
    editor = editor_factory()
    walk_rounds(editor, [(2, "第一轮：浏览商品"), (3, "第二轮：加入购物车并下单")],
                finish_action="answer_terminate", modal=modal)
    assert len(editor.rounds) == 2

    rounds_before = copy.deepcopy(editor.rounds)
    steps_before = copy.deepcopy(editor.steps_data)
    coords_before = copy.deepcopy(editor.coords_data)
    sidebar_cache = editor.sidebar._thumb_cache

    dialog = RoundPreviewDialog(editor)
    try:
        assert dialog.round_combo.count() == 2
        # 下拉首项格式：第 N 轮 · 指令前 30 字
        assert dialog.round_combo.itemText(0).startswith("第 1 轮 · 第一轮：浏览商品")
        assert dialog.round_combo.itemData(0, Qt.ToolTipRole) == "第一轮：浏览商品"

        # 首轮：列表条目数 == trajectory 步数，缩略图就绪后自动选中第 1 项
        first_round_steps = len(editor.rounds[0]["trajectory"])
        assert dialog.step_list.count() == first_round_steps
        assert dialog.round_count_label.text() == f"该轮共 {first_round_steps} 步"
        _wait_until(lambda: dialog.step_list.currentRow() == 0,
                    timeout_ms=5000, message="首轮缩略图生成后未自动选中首项")
        assert not dialog.step_list.item(0).icon().isNull()
        pixmap = dialog.preview_label.pixmap()
        assert pixmap is not None and not pixmap.isNull(), "首轮大图预览为空"

        # 切换轮次：列表按新轮 trajectory 重建
        dialog.round_combo.setCurrentIndex(1)
        second_round_steps = len(editor.rounds[1]["trajectory"])
        assert dialog.step_list.count() == second_round_steps
        assert dialog.round_count_label.text() == f"该轮共 {second_round_steps} 步"
        _wait_until(lambda: dialog.step_list.currentRow() == 0,
                    timeout_ms=5000, message="第二轮缩略图生成后未自动选中首项")

        # 选中第 2 项：大图预览按该步截图重新生成
        dialog.step_list.setCurrentRow(1)
        flush_events(50)
        pixmap = dialog.preview_label.pixmap()
        assert pixmap is not None and not pixmap.isNull(), "选中条目后大图预览为空"
        assert dialog.step_list.item(0).text().startswith("第 1 步 · ")
    finally:
        dialog.close()

    # 只读：轮次/步骤/坐标零改动，且未复用侧栏缩略图缓存
    assert editor.rounds == rounds_before
    assert editor.steps_data == steps_before
    assert editor.coords_data == coords_before
    assert editor.sidebar._thumb_cache is sidebar_cache
    assert dialog._thumb_cache is not sidebar_cache


def test_normal_multi_round_flow_unaffected(editor_factory, modal):
    """e：正常两轮问答流程的 messages 结构与此前一致"""
    editor = editor_factory()
    walk_rounds(editor, [(2, "第一轮指令"), (2, "第二轮指令")],
                finish_action="answer_terminate", modal=modal)

    data = assert_final_json(editor.gui_dir, editor.gui_number)
    messages = data["messages"]
    assert len(messages) == 4, "两轮问答应为 4 条 message"
    assert [m["role"] for m in messages] == ["user", "assistant",
                                             "user", "assistant"]
    assert messages[0]["instruction"] == "第一轮指令"
    assert messages[2]["instruction"] == "第二轮指令"

    traj1 = messages[1]["trajectory"]
    traj2 = messages[3]["trajectory"]
    # 每轮 = 采集步 + 一次 answer 收尾
    assert len(traj1) == 3 and len(traj2) == 3
    assert traj1[-1]["actions"][0]["action"] == "answer"
    # 最后一轮的 answer_terminate 落盘口径不变：action=answer + status=success
    assert traj2[-1]["actions"][0]["action"] == "answer"
    assert traj2[-1]["actions"][0]["status"] == "success"
    assert editor._task_completed is True