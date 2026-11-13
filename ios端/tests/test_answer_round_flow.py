# -*- coding: utf-8 -*-
"""answer 多轮问答流程加固测试组。

覆盖：
  a. 中间步 answer 被拦截（终止类动作必须是本轮最后一步）
  b. 中间步 answer_terminate / terminate 同样被拦截
  c. 交付完成后禁止继续截图/确认
  d. 续采取消后清空上一轮残留指令
  e. 只读多轮回看器 RoundPreviewDialog
  f. 侧栏缩略图缓存键（文件名 + 顶点签名）与过期队列项丢弃

全部走真实产品代码路径，异步点用 helpers._wait_until 轮询驱动。
"""

import copy
import os

import pytest

from PyQt5.QtTest import QTest

from annotation_editor import RoundPreviewDialog
from helpers import (
    _wait_until,
    confirm,
    fill_step,
    flush_draft,
    walk_rounds,
    walk_steps,
)


def _final_json_path(editor):
    return os.path.join(editor.gui_dir, f"gui_{editor.gui_number}.json")


def _final_coords_path(editor):
    return os.path.join(editor.gui_dir, f"gui_{editor.gui_number}_coords.json")


def _png_set(gui_dir):
    return {name for name in os.listdir(gui_dir) if name.lower().endswith(".png")}


# ----------------------------------------------------------------------
# a. 中间步 answer 被拦截
# ----------------------------------------------------------------------

def test_answer_on_middle_step_blocked(editor, qapp):
    """3 步采集后回到第 2 步改成 answer：不得落轮、不得丢后续步骤。"""
    walk_steps(editor, 3, action="click")
    assert len(editor.steps_data) == 3

    editor.display_step(1)
    assert editor.current_step == 1

    fill_step(editor, action="answer", text="中间步回答")
    confirm(editor)

    assert editor.rounds == [], "中间步 answer 不应落轮"
    assert len(editor.steps_data) == 3, "拦截后 steps_data 必须保持原样"
    assert editor.current_step == 1
    assert not os.path.exists(_final_json_path(editor)), "拦截路径不得产出交付 JSON"
    assert not os.path.exists(_final_coords_path(editor))


# ----------------------------------------------------------------------
# b. 中间步 answer_terminate / terminate 同样被拦截
# ----------------------------------------------------------------------

@pytest.mark.parametrize("action", ["answer_terminate", "terminate"])
def test_terminate_like_on_middle_step_blocked(editor, qapp, action):
    walk_steps(editor, 3, action="click")
    editor.display_step(1)
    assert editor.current_step == 1

    fill_step(editor, action=action)
    confirm(editor)

    assert editor.rounds == [], f"中间步 {action} 不应落轮/收尾"
    assert len(editor.steps_data) == 3
    assert editor.current_step == 1
    assert not os.path.exists(_final_json_path(editor))


# ----------------------------------------------------------------------
# c. 交付完成后禁止继续截图/确认
# ----------------------------------------------------------------------

def test_capture_and_confirm_blocked_after_delivery(editor, qapp):
    final_path = walk_rounds(
        editor,
        [(2, "第一轮指令", "click"), (2, "第二轮指令", "click")],
        finish_action="terminate",
    )
    qapp.processEvents()

    assert final_path and os.path.isfile(final_path), "收尾后交付 JSON 未落盘"
    assert editor._final_data_saved is True
    assert editor.rounds and len(editor.rounds) == 2
    assert editor.steps_data == []

    png_before = _png_set(editor.gui_dir)
    steps_before = len(editor.steps_data)

    editor.start_capture()
    assert "任务已保存" in editor.status_label.text()
    QTest.qWait(120)
    editor.confirm_step()
    flush_draft(editor)
    QTest.qWait(120)

    assert len(editor.steps_data) == steps_before, "交付后仍新增了步骤"
    assert _png_set(editor.gui_dir) == png_before, "交付后仍写出了新截图"


# ----------------------------------------------------------------------
# d. 续采取消后清掉上一轮残留指令
# ----------------------------------------------------------------------

def test_reset_workspace_after_cancel_clears_instruction(editor, qapp, dm):
    editor.task_instruction = "旧指令"
    editor.rounds = [{"instruction": "旧指令", "trajectory": []}]

    editor._reset_workspace_after_cancel()
    flush_draft(editor)

    assert editor.task_instruction == ""
    assert editor.steps_data == []
    assert editor.current_step == 0

    draft = dm.load_draft(editor.gui_number)
    assert draft is not None, "取消续采后草稿应仍可读取"
    assert draft.get("task_instruction") == "", "草稿里仍残留上一轮指令"


# ----------------------------------------------------------------------
# e. 只读多轮回看器
# ----------------------------------------------------------------------

def test_round_preview_dialog_read_only(editor, qapp):
    walk_rounds(
        editor,
        [(2, "轮次一指令", "click"), (2, "轮次二指令", "click")],
        finish_action="terminate",
    )
    qapp.processEvents()
    assert len(editor.rounds) == 2
    assert editor.view_rounds_btn.isEnabled(), "有轮次时回看入口应可用"

    rounds_before = copy.deepcopy(editor.rounds)
    steps_before = copy.deepcopy(editor.steps_data)
    coords_before = copy.deepcopy(editor._coords_rounds)

    dialog = RoundPreviewDialog(editor)
    try:
        assert dialog.windowTitle() == "已完成轮次回看"
        assert dialog.round_combo.count() == 2

        # 默认展示第 1 轮
        assert dialog.list_widget.count() == len(editor.rounds[0]["trajectory"])
        _wait_until(lambda: not dialog._pending, message="第 1 轮缩略图未生成完毕")
        first_icon = dialog.list_widget.item(0).icon()
        assert first_icon is not None and not first_icon.isNull()

        # 切换轮次：列表条数跟随该轮 trajectory
        dialog.round_combo.setCurrentIndex(1)
        QTest.qWait(50)
        assert dialog.list_widget.count() == len(editor.rounds[1]["trajectory"])
        _wait_until(lambda: not dialog._pending, message="第 2 轮缩略图未生成完毕")

        dialog.list_widget.setCurrentRow(0)
        QTest.qWait(20)
        pixmap = dialog.preview_label.pixmap()
        assert pixmap is not None and not pixmap.isNull(), "大图预览为空"

        # 切回第 1 轮同样可预览
        dialog.round_combo.setCurrentIndex(0)
        QTest.qWait(50)
        _wait_until(lambda: not dialog._pending, message="第 1 轮缩略图未生成完毕")
        dialog.list_widget.setCurrentRow(0)
        QTest.qWait(20)
        pixmap = dialog.preview_label.pixmap()
        assert pixmap is not None and not pixmap.isNull()
    finally:
        dialog.close()

    # 只读：不修改 rounds / steps_data / coords 分组
    assert editor.rounds == rounds_before
    assert editor.steps_data == steps_before
    assert editor._coords_rounds == coords_before


# ----------------------------------------------------------------------
# f. 侧栏缩略图缓存键 + 陈旧队列项
# ----------------------------------------------------------------------

def test_sidebar_thumb_cache_key_and_stale_queue(editor, qapp):
    """文件名相同、框不同：必须重新生成缩略图，旧签名项不得写缓存。"""
    walk_steps(editor, 1, action="click")
    editor.display_step(0)
    sidebar = editor.sidebar
    filename = editor.steps_data[0]["screenshot"]
    old_vertices = copy.deepcopy(editor.steps_data[0]["vertices"])
    old_sig = sidebar._vertices_signature(old_vertices)
    old_key = (filename, old_sig)

    _wait_until(
        lambda: sidebar._get_cached_thumb(old_key) is not None,
        message="初始缩略图未进入缓存",
    )
    old_pixmap = sidebar._get_cached_thumb(old_key)

    # 重拉框：文件名不变、顶点变化
    new_vertices = [20, 40, 120, 140]
    assert new_vertices != old_vertices
    editor.steps_data[0]["vertices"] = new_vertices
    new_sig = sidebar._vertices_signature(new_vertices)
    new_key = (filename, new_sig)
    assert new_key != old_key

    sidebar.ensure_current_thumb()
    # 模拟队列里残留的旧签名项（应在批次执行时被丢弃）
    sidebar._thumb_queue.insert(0, (0, filename, old_sig))
    sidebar._thumb_queued.add(0)
    sidebar._thumb_timer.start(10)

    _wait_until(
        lambda: sidebar._get_cached_thumb(new_key) is not None,
        message="新顶点签名的缩略图未进入缓存",
    )
    new_pixmap = sidebar._get_cached_thumb(new_key)
    assert new_pixmap is not None and not new_pixmap.isNull()

    _wait_until(
        lambda: not sidebar._thumb_queue and not sidebar._thumb_queued,
        message="缩略图队列未清空",
    )
    # 旧签名键不得继续作为命中项（同文件只保留最新签名）
    assert sidebar._get_cached_thumb(old_key) is None, "陈旧签名的缓存仍可命中"
    if old_pixmap is not None and new_pixmap is not None:
        assert old_pixmap.cacheKey() != new_pixmap.cacheKey()

    # 条目上显示的也必须是新图
    shown = sidebar.item_widgets[0].thumb_label.pixmap()
    assert shown is not None and not shown.isNull()
    assert shown.cacheKey() == new_pixmap.cacheKey()