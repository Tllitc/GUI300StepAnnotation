# -*- coding: utf-8 -*-
"""冒烟测试：追加 3 步 → terminate 结束 → 断言最终 JSON/coords/截图全产出。"""

import os
import json

import helpers as H
import invariants as I


def test_smoke_three_steps(editor):
    """最基本的 3 步 → terminate → 全链路落盘。"""
    # 追加 3 步
    H.walk_steps(editor, 3, action_chinese="左键单击",
                 intent_template="测试第 {i} 步")

    I.assert_model(editor)
    I.assert_stack(editor)
    I.assert_files(editor)
    I.assert_sidebar(editor)
    I.assert_transient_reset(editor)

    # 结束任务
    json_path = H.finish(editor, action="terminate")
    assert json_path is not None and os.path.isfile(json_path), "最终 JSON 产出失败"

    I.assert_final_json(editor, expected_rounds=1)


def test_recapture_shortcut_ctrl_r(editor_factory, monkeypatch):
    """Ctrl+R 窗口快捷键触发 recapture_current_step。"""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    import annotation_editor as ae

    calls = []
    monkeypatch.setattr(ae.AnnotationEditor, "recapture_current_step",
                        lambda self: calls.append(1))
    editor = editor_factory()
    sc = editor.recapture_shortcut
    assert sc.key().toString() == "Ctrl+R"
    assert sc.context() == Qt.WindowShortcut
    editor.show()
    editor.activateWindow()
    QTest.qWait(20)
    QTest.keyClick(editor, Qt.Key_R, Qt.ControlModifier)
    assert calls == [1], "Ctrl+R 未触发 recapture_current_step"


def test_undo_last_step_basic(editor):
    """撤销末尾一步：3→2，文件删除，侧栏减少，当前下标正确。"""
    H.walk_steps(editor, 3, action_chinese="左键单击")
    before_filenames = [s["screenshot_filename"] for s in editor.steps]
    before_gui_files = set(I._strict_named_pngs(editor))

    old_index = editor.current_step_index
    assert old_index == 2  # 现在停在最后一步（walk_steps 最后 confirm 后未跳）

    H.undo(editor, confirm=True)

    assert len(editor.steps) == 2
    assert editor.current_step_index == 1
    # 最后那步的文件应从磁盘删除
    remaining_files = set(I._strict_named_pngs(editor))
    expected_deleted = before_filenames[-1]
    assert expected_deleted not in remaining_files, f"撤销后截图 {expected_deleted} 未删除"

    I.assert_model(editor)
    I.assert_stack(editor)
    I.assert_files(editor)
    I.assert_sidebar(editor)
    I.assert_transient_reset(editor)
    H.flush_draft(editor)
    I.assert_draft(editor)


def test_delete_middle_step(editor):
    """5 步删第 3 步（下标 2）：后续前移 + 重编号 + 侧栏重建。"""
    H.walk_steps(editor, 5, action_chinese="左键单击")

    # 跳到第 3 步（下标 2）
    editor.display_step(2)
    H.delete_current(editor, confirm=True)

    assert len(editor.steps) == 4
    # 原第 4、5 步（下标 3、4）现在应在下标 2、3
    assert editor.steps[3]["editor"].step_number_label.text() == "3", (
        f"重编号失败: text={editor.steps[3]['editor'].step_number_label.text()!r}"
    )

    I.assert_model(editor)
    I.assert_stack(editor)
    I.assert_files(editor)
    I.assert_sidebar(editor)
    H.flush_draft(editor)
    I.assert_draft(editor)
    I.assert_transient_reset(editor)


def test_insert_after_first(editor):
    """第 1 步后插入：业务顺序 1-新-2-3；stack 重排正确；文件取 max+1。"""
    H.walk_steps(editor, 3, action_chinese="左键单击")
    old_last_file = editor.steps[2]["screenshot_filename"]  # 假设 gui_000001_0003.png

    H.insert_step_after(editor, 0)
    # 现在新步在下标 1，下标 2 是原第 2 步，下标 3 是原第 3 步
    assert editor.steps[3]["screenshot_filename"] == old_last_file

    I.assert_model(editor)
    I.assert_stack(editor)
    I.assert_files(editor)
    I.assert_sidebar(editor)
    H.flush_draft(editor)
    I.assert_draft(editor)
    I.assert_transient_reset(editor)


def test_recapture_single(editor):
    """重新截图：文件名复用、文件数不变、内容变更。"""
    H.walk_steps(editor, 3, action_chinese="左键单击")
    before_files = set(I._strict_named_pngs(editor))
    target_filename = editor.steps[1]["screenshot_filename"]

    H.recapture(editor, 1, rect=(200, 300, 500, 600))
    # 文件数不变
    after_files = set(I._strict_named_pngs(editor))
    assert before_files == after_files, "重新截图不应产生新文件"
    # 文件名不变
    assert editor.steps[1]["screenshot_filename"] == target_filename

    I.assert_model(editor)
    I.assert_stack(editor)
    I.assert_files(editor)
    I.assert_transient_reset(editor)


def test_cancel_capture(editor):
    """取消截图：steps 不增、窗口恢复、无副作用。"""
    before = len(editor.steps)
    H.cancel_next_capture(editor)
    assert len(editor.steps) == before
    I.assert_transient_reset(editor)
