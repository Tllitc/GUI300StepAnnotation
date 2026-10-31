# -*- coding: utf-8 -*-
"""异步截图驱动与表单填写助手"""
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from annotation_editor import (COORD_ACTIONS, KEY_ACTIONS, START_END_ACTIONS,
                               TEXT_ACTIONS, TIME_ACTIONS)


def flush_events(ms=0):
    """推进事件循环；ms>0 时用 QTest.qWait 等待并处理事件"""
    QApplication.processEvents()
    if ms and ms > 0:
        QTest.qWait(ms)
    QApplication.processEvents()


def capture_and_wait(editor, timeout_ms=10000):
    """触发 take_screenshot 并分片推进事件循环，直到截图锁释放（含 800ms 冷却）

    :return: 本次截图文件名（失败路径为 None 或旧值）
    """
    prev_seq = editor._screenshot_seq
    editor.take_screenshot()
    if editor._screenshot_seq == prev_seq:
        raise AssertionError("take_screenshot 未发起新截图（锁未释放或任务未初始化）")
    waited = 0
    while editor._screenshot_in_progress and waited < timeout_ms:
        QTest.qWait(30)
        waited += 30
    flush_events()
    if editor._screenshot_in_progress:
        raise AssertionError(f"截图未在 {timeout_ms}ms 内完成（含 800ms 冷却）")
    return editor._current_screenshot_filename


def fill_valid_step(editor, action="click", intent=None, text=None, vertices=None):
    """填写表单使 _validate_step 通过

    坐标类动作设置 _current_vertices=[x1,y1,x2,y2] 并填中心点坐标；
    文本/按键/时间/滚动像素按动作类型补必填项。
    """
    idx = editor.action_combo.findData(action)
    assert idx >= 0, f"未知动作: {action}"
    editor.action_combo.setCurrentIndex(idx)
    if intent is not None:
        editor.intent_input.setText(intent)
    elif not editor.intent_input.text().strip():
        editor.intent_input.setText(f"步骤{editor.current_step + 1}-{action}")
    v = list(vertices) if vertices else [100, 200, 300, 400]
    cx = (v[0] + v[2]) // 2
    cy = (v[1] + v[3]) // 2
    if action in COORD_ACTIONS or action in START_END_ACTIONS:
        editor._current_vertices = v
        editor.coord_x_input.setText(str(cx))
        editor.coord_y_input.setText(str(cy))
    else:
        editor._current_vertices = None
    if action in START_END_ACTIONS:
        editor.coord2_x_input.setText(str(cx + 40))
        editor.coord2_y_input.setText(str(cy + 80))
    if action == "scroll":
        editor.pixels_input.setText("120")
    if action in TEXT_ACTIONS:
        editor.text_input.setText(text if text is not None else "测试文本内容")
    if action in KEY_ACTIONS:
        editor.keys_input.setText("ctrl,c")
    if action in TIME_ACTIONS:
        editor.time_input.setText("1.0")
    flush_events()


def confirm_n_steps(editor, n, action="click", **fill_kwargs):
    """标准走步：截图 → 填表单 → 确认，重复 n 次"""
    for _ in range(n):
        capture_and_wait(editor)
        fill_valid_step(editor, action=action, **fill_kwargs)
        editor.confirm_step()
        flush_events(50)


def finish_task(editor, modal, answer_text="任务回答"):
    """以 answer_terminate 动作收尾走 _finish_task；完成框由 modal 应答（默认 No）"""
    capture_and_wait(editor)
    fill_valid_step(editor, action="answer_terminate", text=answer_text)
    editor.confirm_step()
    flush_events(100)
    if not editor._task_completed:
        raise AssertionError("任务未完成（_finish_task 校验或保存失败）")


def drain_sidebar_thumbs(editor, timeout_ms=5000):
    """排空侧栏缩略图懒加载队列"""
    waited = 0
    while editor.sidebar._thumb_queue and waited < timeout_ms:
        QTest.qWait(30)
        waited += 30
    flush_events()
