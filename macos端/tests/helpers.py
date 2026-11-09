# -*- coding: utf-8 -*-
"""测试驱动助手：走真实产品代码路径驱动编辑器完成场景。

所有异步点（350ms QTimer.singleShot 隐藏窗口 + 弹出截图窗口）通过 QTest.qWait
推进事件循环，禁止写死长 sleep。

FakeScreenshotCaptureWindow 的状态通过"下一次实例类标志"（_next_xxx）预设，
再由 show_capture_window 内部 new 实例后自动读取并在 __init__ 里消耗掉。
"""

import os
import json

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QMessageBox


_STEP_MS = 50
_TIMEOUT_MS = 2000


def _wait_until(predicate, timeout_ms=_TIMEOUT_MS, step_ms=_STEP_MS, message=""):
    waited = 0
    while waited < timeout_ms:
        QTest.qWait(step_ms)
        waited += step_ms
        try:
            if predicate():
                return
        except Exception:
            pass
    raise AssertionError(
        f"等待条件超时（{timeout_ms}ms）：{message or predicate}"
    )


def get_fake_cls(editor):
    """返回 FakeScreenshotCaptureWindow 类（conftest 里已 monkeypatch 进 annotation_editor）。"""
    import annotation_editor as _ae
    return _ae.ScreenshotCaptureWindow


def _reset_fake(editor):
    get_fake_cls(editor).reset_prepare()


# ---------------------------------------------------------------------------
# 截图
# ---------------------------------------------------------------------------
def append_step(editor, rect=(100, 200, 300, 400), selection_type="click"):
    """触发 start_capture → 350ms → show_capture_window → Fake.show →
    capture_completed → on_capture_completed 全链路。返回新建 step 下标。"""
    _reset_fake(editor)
    Fake = get_fake_cls(editor)
    Fake.prepare_single_box(rect=rect, selection_type=selection_type)

    before = len(editor.steps)
    editor.start_capture()

    _wait_until(
        lambda: not editor._capture_in_flight,
        message="_capture_in_flight 未复位"
    )
    QTest.qWait(100)
    assert len(editor.steps) == before + 1
    return len(editor.steps) - 1


def append_step_drag(editor, first=(100, 200, 300, 400), second=(600, 500, 300, 400)):
    _reset_fake(editor)
    Fake = get_fake_cls(editor)
    Fake.prepare_dual_box(first=first, second=second)

    before = len(editor.steps)
    editor.start_capture()

    _wait_until(lambda: not editor._capture_in_flight, message="append drag")
    QTest.qWait(100)
    assert len(editor.steps) == before + 1
    return len(editor.steps) - 1


def insert_step_after(editor, index, rect=(100, 200, 300, 400), selection_type="click"):
    _reset_fake(editor)
    Fake = get_fake_cls(editor)
    Fake.prepare_single_box(rect=rect, selection_type=selection_type)

    editor.display_step(index)
    QTest.qWait(50)

    before = len(editor.steps)
    editor.start_insert_capture()

    _wait_until(lambda: not editor._capture_in_flight, message="insert")
    QTest.qWait(100)
    assert len(editor.steps) == before + 1
    return editor.current_step_index


def recapture(editor, index, rect=(100, 200, 300, 400), selection_type="click"):
    _reset_fake(editor)
    Fake = get_fake_cls(editor)
    Fake.prepare_single_box(rect=rect, selection_type=selection_type)

    editor.display_step(index)
    QTest.qWait(50)
    editor.recapture_current_step()

    _wait_until(lambda: not editor._capture_in_flight, message="recapture")
    QTest.qWait(100)


def recapture_drag(editor, index, first=(100, 200, 300, 400), second=(600, 500, 300, 400)):
    _reset_fake(editor)
    Fake = get_fake_cls(editor)
    Fake.prepare_dual_box(first=first, second=second)

    editor.display_step(index)
    QTest.qWait(50)
    editor.recapture_current_step()

    _wait_until(lambda: not editor._capture_in_flight, message="recapture drag")
    QTest.qWait(100)


def cancel_next_capture(editor):
    """预设下一次截图取消，然后走 append 路径。steps 不应增加。"""
    _reset_fake(editor)
    Fake = get_fake_cls(editor)
    Fake.prepare_cancelled()

    before = len(editor.steps)
    editor.start_capture()
    _wait_until(lambda: not editor._capture_in_flight, message="cancel")
    QTest.qWait(100)
    _reset_fake(editor)
    assert len(editor.steps) == before, f"取消截图后步数变了 {before} → {len(editor.steps)}"


# ---------------------------------------------------------------------------
# 变更操作
# ---------------------------------------------------------------------------
def undo(editor, confirm=True):
    ctrl = getattr(editor, "_test_dialogs", None)
    if ctrl is not None:
        old = ctrl.question_result
        ctrl.question_result = QMessageBox.Yes if confirm else QMessageBox.No
    before = len(editor.steps)
    editor.undo_last_step()
    QTest.qWait(100)
    if ctrl is not None:
        ctrl.question_result = old
    return len(editor.steps)


def delete_current(editor, confirm=True):
    ctrl = getattr(editor, "_test_dialogs", None)
    if ctrl is not None:
        old = ctrl.question_result
        ctrl.question_result = QMessageBox.Yes if confirm else QMessageBox.No
    editor.delete_current_step()
    QTest.qWait(100)
    if ctrl is not None:
        ctrl.question_result = old


# ---------------------------------------------------------------------------
# 表单填写 / 确认
# ---------------------------------------------------------------------------
def fill_step(editor, index, action_chinese="左键单击", intent="测试动作",
              coord_text=None, end_coord_text=None, text=None,
              pixels=None, time_value=None):
    editor.display_step(index)
    QTest.qWait(20)

    step = editor.steps[index]
    ed = step["editor"]

    idx = ed.action_type_combo.findText(action_chinese)
    assert idx >= 0, f"动作类型 {action_chinese!r} 不在下拉框中"
    ed.action_type_combo.setCurrentIndex(idx)
    QTest.qWait(10)

    action_key = ed.action_type_mapping.get(action_chinese, action_chinese)
    if intent is not None and action_key != "terminate":
        ed.intent_input.setText(intent)

    if coord_text is not None:
        x, y = coord_text.split(",")
        ed.coord_x_input.setText(x)
        ed.coord_y_input.setText(y)
    if end_coord_text is not None:
        ex, ey = end_coord_text.split(",")
        ed.end_coord_x_input.setText(ex)
        ed.end_coord_y_input.setText(ey)

    if action_key in ("type", "answer", "answer_terminate", "open_app", "open_url"):
        ed.text_input.setPlainText(text or "测试文本")
    if action_key == "wait":
        ed.wait_time_input.setText(time_value or "1.5")
    if action_key == "scroll":
        ed.pixels_input.setText(pixels or "300")

    QTest.qWait(20)


def confirm(editor):
    editor.confirm_button_clicked()
    QTest.qWait(100)


def save_current(editor):
    editor.save_current_step()
    QTest.qWait(200)


def finish(editor, action="terminate", text=None, intent=None):
    if len(editor.steps) == 0:
        append_step(editor)

    last_idx = len(editor.steps) - 1
    if action == "terminate":
        fill_step(editor, last_idx, action_chinese="任务完成", intent=None)
    elif action == "answer":
        fill_step(editor, last_idx, action_chinese="回答并结束",
                  intent=intent or "回答", text=text or "好的")
    else:
        fill_step(editor, last_idx, action_chinese=action, intent=intent or "动作")

    ctrl = getattr(editor, "_test_dialogs", None)
    old_question = None
    if ctrl is not None:
        old_question = ctrl.question_result
        ctrl.question_result = QMessageBox.No   # show_new_task_dialog 不继续新任务

    try:
        editor.confirm_button_clicked()
        QTest.qWait(500)  # save_current_step (300ms QTimer) + show_new_task_dialog + finish_all_annotation
    finally:
        if ctrl is not None and old_question is not None:
            ctrl.question_result = old_question

    gui_dir = os.path.join(editor.data_manager.current_dir, f"gui_{editor.gui_number}")
    json_path = os.path.join(gui_dir, f"gui_{editor.gui_number}.json")
    return json_path if os.path.exists(json_path) else None


def walk_steps(editor, n, action_chinese="左键单击", intent_template="测试第 {i} 步"):
    for i in range(n):
        append_step(editor)
        fill_step(editor, i, action_chinese=action_chinese,
                  intent=intent_template.format(i=i + 1),
                  coord_text="250,350")
        confirm(editor)
    assert len(editor.steps) == n
    return editor.steps


def flush_draft(editor):
    editor._write_draft_now()
    QTest.qWait(50)


def read_draft(editor):
    return editor.data_manager.load_draft(editor.gui_number)


def read_final_json(editor):
    return editor.data_manager.load_json_data(editor.gui_number)


def read_final_coords(editor):
    path = os.path.join(editor.data_manager.current_dir,
                        f"gui_{editor.gui_number}",
                        f"gui_{editor.gui_number}_coords.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def reload_from_draft(editor, draft):
    editor.load_from_draft(draft)
    QTest.qWait(100)
