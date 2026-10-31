# -*- coding: utf-8 -*-
"""测试驱动助手：以“真实产品代码路径”驱动编辑器走完整采标流程。

所有异步点（take_screenshot 的 50ms QTimer、answer 切轮的 300ms QTimer）
均通过 QTest.qWait + 轮询产品状态标记驱动事件循环，禁止写死长 sleep。

典型用法::

    from helpers import capture, fill_step, confirm, walk_steps, finish_task

    walk_steps(editor, 3, action="click")
    finish_task(editor)            # 自动答 No（不继续新任务）
"""

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QMessageBox


# 单次事件循环推进步长 / 总超时（毫秒）
_STEP_MS = 80
_TIMEOUT_MS = 1000


def _wait_until(predicate, timeout_ms=_TIMEOUT_MS, step_ms=_STEP_MS, message=""):
    """轮询驱动事件循环，直到 predicate() 为真；超时抛 AssertionError。"""
    waited = 0
    while waited < timeout_ms:
        QTest.qWait(step_ms)
        waited += step_ms
        if predicate():
            return
    raise AssertionError(
        f"等待条件超时（{timeout_ms}ms）：{message or predicate}"
    )


# ----------------------------------------------------------------------
# 截图
# ----------------------------------------------------------------------

def capture(editor):
    """触发真实 take_screenshot -> 50ms QTimer -> _do_screenshot 全链路。

    等待 _screenshot_in_progress 复位后返回当前截图文件名。
    """
    editor.take_screenshot()
    _wait_until(
        lambda: not editor._screenshot_in_progress,
        message="_screenshot_in_progress 未在超时内复位",
    )
    # 再推进一拍，确保成功回调里的画布/侧栏更新事件处理完
    QTest.qWait(_STEP_MS)
    assert editor._current_screenshot_filename, "截图未成功：当前步骤没有截图文件名"
    return editor._current_screenshot_filename


# ----------------------------------------------------------------------
# 拉框
# ----------------------------------------------------------------------

def draw_rect(editor, left=50, top=200, right=150, bottom=300):
    """走真实信号路径发射 rect_drawn（等价于鼠标在画布上拉框）。

    同步触发 editor.on_rect_drawn：普通动作会写 _current_vertices
    并把中心坐标填入 coord_x/y_input。
    """
    editor.canvas.rect_drawn.emit(int(left), int(top), int(right), int(bottom))
    QTest.qWait(0)
    return editor._current_vertices


# ----------------------------------------------------------------------
# 动作表单填写
# ----------------------------------------------------------------------

def _select_action(editor, action):
    index = editor.action_combo.findData(action)
    assert index >= 0, f"动作类型 {action!r} 不在 action_combo 中"
    editor.action_combo.setCurrentIndex(index)
    QTest.qWait(0)


def fill_step(
    editor,
    action="click",
    rect=(50, 200, 150, 300),
    text=None,
    time_value=None,
    pixels=None,
    end_rect=None,
    intent=None,
):
    """选择动作并按各动作的必填口径填写表单，使 live 校验通过。

    参数:
        action:      click/long_press/swipe/drag/scroll/type/wait/
                     answer/answer_terminate/open_app/open_url/
                     system_button/terminate
        rect:        拉框 (l, t, r, b)；坐标类动作必填，None 表示不拉框
        text:        文本类动作内容，默认按动作给合法值
        time_value:  时间类动作秒数字符串，默认 "1.0"
        pixels:      scroll 像素字符串（跳过测量直接填，readOnly 也可 setText）
        end_rect:    swipe/drag 终点框（默认给右下方另一框）
        intent:      动作描述（iOS 口径不校验，可选）
    """
    _select_action(editor, action)

    if intent is not None:
        editor.intent_input.setText(intent)

    # ---- 坐标类（含 type / scroll / long_press）----
    coord_actions = {"click", "long_press", "swipe", "drag", "scroll", "type"}
    if action in coord_actions and rect is not None:
        draw_rect(editor, *rect)

    # ---- swipe / drag：再拉一个终点框，直接写两组坐标+起点 vertices ----
    if action in {"swipe", "drag"}:
        if end_rect is None:
            end_rect = (200, 500, 300, 600)
        l2, t2, r2, b2 = end_rect
        editor.coord2_x_input.setText(str((l2 + r2) // 2))
        editor.coord2_y_input.setText(str((t2 + b2) // 2))
        # validate_step_at 对 swipe 只要求 vertices（起点框）+ 起点 + 终点坐标，
        # 起点框已由 draw_rect 写入 _current_vertices / coord_x/y。

    # ---- scroll：像素必填（0 也是合法测量结果）----
    if action == "scroll":
        editor.pixels_input.setText("300" if pixels is None else str(pixels))

    # ---- 文本类 ----
    if action in {"type", "answer", "answer_terminate", "open_app", "open_url"}:
        if text is None:
            text = {
                "type": "测试文本",
                "answer": "回答内容",
                "answer_terminate": "最终回答",
                "open_app": "设置",
                "open_url": "https://example.com",
            }[action]
        editor.text_input.setText(text)

    # ---- 时间类（live 校验看输入框文本，必须显式填）----
    if action in {"long_press", "wait"}:
        editor.time_input.setText("1.0" if time_value is None else str(time_value))

    # ---- system_button：下拉框默认有合法选项（Back 等），live 校验读 combo，
    #      _build_action_data 仅在选中 SYSTEM_BUTTONS 内有效值时写 buttons ----

    # ---- terminate：无参数，切动作时产品自动把 intent 置为“任务完成” ----

    QTest.qWait(0)
    return action


# ----------------------------------------------------------------------
# 确认 / 走步
# ----------------------------------------------------------------------

def confirm(editor, wait_answer_round=False):
    """确认当前步（真实 confirm_step）并处理事件循环。

    wait_answer_round=True 时额外等待 answer 之后 300ms 的
    _start_new_round 定时器（QInputDialog 已被 dialogs fixture 接管）。
    """
    editor.confirm_step()
    QTest.qWait(_STEP_MS)
    if wait_answer_round:
        _wait_until(
            lambda: not editor._screenshot_in_progress,
            message="answer 切轮等待异常",
        )
        # 300ms 定时器 + 新轮重置事件
        QTest.qWait(400)


def walk_steps(editor, n, action="click", **fill_kw):
    """连续完成 n 步：每步 截图 -> 填表单 -> 确认。返回 steps_data。"""
    for _ in range(n):
        capture(editor)
        fill_step(editor, action=action, **fill_kw)
        confirm(editor)
    assert len(editor.steps_data) == n, (
        f"walk_steps 后 steps_data 长度应为 {n}，实际 {len(editor.steps_data)}"
    )
    return editor.steps_data


def flush_draft(editor):
    """立即把草稿落盘（跳过防抖定时器）。"""
    editor._write_draft_now()
    QTest.qWait(0)


def finish_task(editor, continue_new=False):
    """结束任务：临时把“是否继续新任务”问答置为 No/Yes 后触发真实 _finish_task。

    必须在调用前已完成 terminate 步的截图与动作选择，或在内部完成；
    本助手自行处理：截图（若缺）-> 选 terminate -> confirm。
    """
    ctrl = getattr(editor, "_test_dialogs", None)
    previous = None
    if ctrl is not None:
        previous = ctrl.question_result
        ctrl.question_result = QMessageBox.Yes if continue_new else QMessageBox.No

    try:
        # terminate 步同样要求先截图（confirm_step 先检查截图）
        if editor._current_screenshot_filename is None:
            capture(editor)
        fill_step(editor, action="terminate")
        editor.confirm_step()          # terminate -> _finish_task
        QTest.qWait(_STEP_MS)
    finally:
        if ctrl is not None and previous is not None:
            ctrl.question_result = previous
