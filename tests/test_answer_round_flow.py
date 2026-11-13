# -*- coding: utf-8 -*-
"""answer（回答用户）/ answer_terminate（回答并结束）多轮流程回归。

覆盖：
1. 终止类动作必须是本轮最后一步（中间步拦截）
2. answer 落轮前的全轮必填校验（缺项不落轮、不清空现场）
3. 交付完成后阻断后续采集，直到用户明确选择是否开始新任务
4. 取消下一条指令时清空已消费的旧指令并重置工作区
5. 只读多轮回看器 RoundPreviewDialog
"""

import copy
import os

from PyQt5.QtTest import QTest

import annotation_editor as _ae
import helpers as H


def _pngs_in(gui_dir):
    return sorted(n for n in os.listdir(gui_dir) if n.endswith(".png"))


def _wait_thumbnails(dlg, timeout_ms=2000, step_ms=50):
    """等待对话框批量缩略图生成完毕（或超时）"""
    waited = 0
    while waited < timeout_ms:
        QTest.qWait(step_ms)
        waited += step_ms
        if dlg.list_widget.count() > 0:
            first = dlg.list_widget.item(0)
            if first is not None and not first.icon().isNull():
                return
    raise AssertionError("等待缩略图生成超时")


class TestTerminateOnlyLastStep:
    """终止类动作必须是本轮最后一步。"""

    def test_answer_in_middle_step_is_blocked(self, editor):
        H.walk_steps(editor, 3)
        editor.display_step(1)
        H.fill_step(editor, 1, action_chinese="回答用户", intent="回答", text="答")

        H.confirm(editor)

        assert len(editor.rounds) == 0, "中间步 answer 不应落轮"
        assert len(editor.steps) == 3, f"拦截后 steps 不应变化：{len(editor.steps)}"
        assert "最后" in editor.status_label.text(), (
            f"拦截提示未说明「最后一步」：{editor.status_label.text()!r}"
        )

    def test_terminate_in_middle_step_is_blocked(self, editor):
        H.walk_steps(editor, 3)
        editor.display_step(1)
        H.fill_step(editor, 1, action_chinese="任务完成", intent=None)

        H.confirm(editor)

        assert len(editor.rounds) == 0, "中间步 terminate 不应落轮"
        assert len(editor.steps) == 3, f"拦截后 steps 不应变化：{len(editor.steps)}"
        json_path = os.path.join(
            H.gui_dir_of(editor), f"gui_{editor.gui_number}.json"
        )
        assert not os.path.exists(json_path), f"中间步 terminate 不应产出交付件：{json_path}"
        assert "最后" in editor.status_label.text()


class TestAnswerFullRoundValidation:
    """answer 落轮前必须通过全轮必填校验。"""

    def test_missing_intent_blocks_round_then_succeeds_when_fixed(
            self, editor, monkeypatch):
        # ValidationFailDialog.exec_() 是模态阻塞，测试中替换为立即返回
        monkeypatch.setattr(_ae.ValidationFailDialog, "exec_", lambda self: 0)

        H.walk_steps(editor, 2)
        editor.display_step(0)
        editor.steps[0]["editor"].intent_input.clear()
        editor.display_step(1)
        H.fill_step(editor, 1, action_chinese="回答用户", intent="回答", text="答")

        H.confirm(editor)

        assert len(editor.rounds) == 0, "全轮缺项时 answer 不得落轮"
        assert len(editor.steps) == 2, f"缺项时不得清空 steps：{len(editor.steps)}"

        # 补回缺失的动作描述后再次确认，应正常落轮
        editor.display_step(0)
        editor.steps[0]["editor"].intent_input.setText("补回的动作描述")
        H.fill_step(editor, 1, action_chinese="回答用户", intent="回答", text="答")
        H.confirm(editor)

        assert len(editor.rounds) == 1, "补齐后 answer 应正常落轮"
        QTest.qWait(500)  # 等 300ms 切轮回调跑完，避免残留定时器
        assert len(editor.rounds) == 1


class TestBlockedAfterDelivery:
    """交付完成后必须走完「是否开始新任务」，期间禁止继续采集。"""

    def test_capture_and_confirm_are_blocked_after_finish(self, editor, monkeypatch):
        # 交付路径默认会 close()+deleteLater() 销毁编辑器；置空「返回主菜单」
        # 以保留窗口，才能验证交付后的入口守卫
        monkeypatch.setattr(editor, "_return_to_init_menu", lambda: None)
        H.walk_steps(editor, 1)
        json_path = H.finish(editor, action="answer")
        assert json_path is not None, "交付 JSON 未产出"
        assert editor._final_data_saved is True

        gui_dir = H.gui_dir_of(editor)
        pngs_before = _pngs_in(gui_dir)

        editor.start_capture()
        QTest.qWait(500)

        assert editor.steps == [], f"交付后仍能继续采集：{len(editor.steps)} 步"
        assert _pngs_in(gui_dir) == pngs_before, "交付后仍产生了新的截图文件"

        editor.confirm_button_clicked()
        QTest.qWait(100)
        assert editor.steps == []


class TestCancelNextRoundInstruction:
    """取消下一条指令：清空旧指令并重置工作区。"""

    def test_cancel_clears_instruction_and_resets(self, editor):
        editor.task_instruction = "第一轮指令"
        editor.rounds = [{"instruction": "第一轮指令", "trajectory": []}]

        editor.cancel_next_round_instruction()

        assert editor.task_instruction == ""
        assert editor.steps == []
        assert editor.current_step_index == -1
        draft = H.read_draft(editor)
        assert draft is not None
        assert (draft.get("task_instruction") or "") == ""


class TestRoundPreviewDialog:
    """只读多轮回看器：轮次下拉、条目重建、预览、只读性。"""

    def test_preview_rounds_is_read_only(self, editor, monkeypatch):
        # 保留交付后的编辑器实例（默认会 close+deleteLater），以便构造回看器
        monkeypatch.setattr(editor, "_return_to_init_menu", lambda: None)
        H.walk_rounds(
            editor,
            [(2, "第一轮", "click"), (2, "第二轮", "click")],
            finish_action="answer",
        )
        assert len(editor.rounds) == 2

        rounds_snapshot = copy.deepcopy(editor.rounds)
        steps_count = len(editor.steps)
        current_index = editor.current_step_index

        dlg = _ae.RoundPreviewDialog(editor)
        try:
            assert dlg.round_combo.count() == 2, (
                f"轮次下拉数量应为 2，实际 {dlg.round_combo.count()}"
            )

            dlg._on_round_changed(0)
            assert dlg.list_widget.count() == len(editor.rounds[0]["trajectory"]), (
                f"第一轮条目数不符：{dlg.list_widget.count()}"
            )
            _wait_thumbnails(dlg)

            dlg.list_widget.setCurrentRow(0)
            pixmap = dlg.preview_label.pixmap()
            assert pixmap is not None and not pixmap.isNull(), "大图预览未渲染"

            # 切换轮次：旧条目必须被完全替换，不能残留
            dlg.round_combo.setCurrentIndex(1)
            assert dlg.list_widget.count() == len(editor.rounds[1]["trajectory"]), (
                f"第二轮条目数不符：{dlg.list_widget.count()}"
            )
            assert dlg.step_count_label.text() == (
                f"步数：{len(editor.rounds[1]['trajectory'])}"
            )
        finally:
            dlg.close()

        assert editor.rounds == rounds_snapshot, "回看修改了 rounds"
        assert len(editor.steps) == steps_count, "回看修改了 steps"
        assert editor.current_step_index == current_index, "回看修改了当前步骤下标"