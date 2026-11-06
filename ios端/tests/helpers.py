# -*- coding: utf-8 -*-
"""测试驱动助手：以“真实产品代码路径”驱动编辑器走完整采标流程。

所有异步点（take_screenshot 的 50ms QTimer、answer 切轮的 300ms QTimer）
均通过 QTest.qWait + 轮询产品状态标记驱动事件循环，禁止写死长 sleep。

典型用法::

    from helpers import capture, fill_step, confirm, walk_steps, finish_task

    walk_steps(editor, 3, action="click")
    finish_task(editor)            # 自动答 No（不继续新任务）

    from helpers import walk_rounds, open_edit_mode

    walk_rounds(editor, [(3, "指令A", "click"), (2, "指令B", "click")])
"""

import copy
import os
import re

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


def distinct_capture_seed(editor, used_shots):
    """把 fake 截图计数器推进到 used_shots 之后，保证下一次 capture 的字节全新。

    FakeScreenCapture 按 call_count 取底色并绘制 "SHOT N"，因此**新建的编辑器
    实例计数器从 0 重启**，产出的第一张会与准备阶段的第一张逐字节相同。做
    「重截图确实改写了内容」这类断言时必须先推进种子，否则会假失败。

    :param used_shots: 现场已存在的截图张数（即已用掉的 call_count 个数）
    """
    fake = getattr(editor, "screen_capture", None)
    if fake is not None and hasattr(fake, "call_count"):
        fake.call_count = max(fake.call_count, used_shots)
    return used_shots


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


# ----------------------------------------------------------------------
# gui 目录助手
# ----------------------------------------------------------------------

def gui_dir_of(editor):
    """当前任务目录绝对路径（产品在各处自行赋值，取属性即可）。"""
    gui_dir = editor.gui_dir
    if not gui_dir:
        gui_dir = os.path.join(editor.data_manager.current_dir,
                               f"gui_{editor.gui_number}")
    return gui_dir


def gui_number_from_dir(path):
    """从 gui_xxxxxx 目录名（或含该层的完整路径）提取 6 位编号。"""
    name = os.path.basename(os.path.normpath(str(path)))
    match = re.fullmatch(r"gui_(\d{6})", name)
    assert match, f"不是 gui_xxxxxx 形式的任务目录：{path}"
    return match.group(1)


# ----------------------------------------------------------------------
# 多轮 / 编辑模式助手
# ----------------------------------------------------------------------

def walk_rounds(editor, rounds_spec, finish_action="terminate"):
    """多轮走步助手：逐轮采集并以 answer 落轮，最后一轮收尾写最终 JSON。

    :param rounds_spec: [(步数, 该轮任务指令, 动作), ...]；动作为 iOS action_combo
        的英文 key（click/scroll/drag/type/...），缺省 "click"。
    :param finish_action: 最后一轮的收尾动作；None 表示不落收尾，留给调用方。
    :return: 最终 JSON 路径（finish_action 为 None 时返回 None）。

    机制说明：iOS 的 answer 分支（confirm_step:1766）先同步 _save_current_round_to_list
    （内部已清空 steps_data），再 singleShot(300) 弹 _start_new_round(from_answer=True)
    并从 QInputDialog.getText 取新指令，故必须在第 r 轮落轮**之前**把
    dialogs.next_instruction 预置为第 r+1 轮指令；这同时覆盖 B14（取消新轮后沿用
    旧指令）类场景。
    """
    ctrl = getattr(editor, "_test_dialogs", None)
    total = len(rounds_spec)

    for r, spec in enumerate(rounds_spec):
        n_steps = spec[0]
        instruction = spec[1]
        action = spec[2] if len(spec) > 2 else "click"
        is_last = (r == total - 1)

        if ctrl is not None and not is_last:
            ctrl.next_instruction = rounds_spec[r + 1][1]
        editor.task_instruction = instruction

        for i in range(n_steps):
            capture(editor)
            fill_step(editor, action=action, intent=f"第{r + 1}轮第{i + 1}步")
            confirm(editor)
        assert len(editor.steps_data) == n_steps, (
            f"第 {r + 1} 轮走步后 steps_data 长度应为 {n_steps}，"
            f"实际 {len(editor.steps_data)}"
        )

        if is_last:
            break

        # answer 落轮 + 300ms 后续轮对话框
        capture(editor)
        fill_step(editor, action="answer", intent=f"第{r + 1}轮回答",
                  text=f"第{r + 1}轮回答")
        confirm(editor)
        expected_rounds = r + 1
        expected_instruction = rounds_spec[r + 1][1]
        _wait_until(lambda: len(editor.rounds) == expected_rounds,
                    message=f"第 {expected_rounds} 轮未落轮")
        _wait_until(lambda: editor.task_instruction == expected_instruction,
                    message=f"续轮后任务指令未切换为第 {r + 2} 轮："
                            f"{editor.task_instruction!r}")
        assert editor.steps_data == [], (
            f"第 {r + 1} 轮续轮后 steps_data 未清空：{len(editor.steps_data)}"
        )

    if finish_action is None:
        return None
    return finish_task_final(editor, finish_action)


def finish_task_final(editor, action="terminate"):
    """按指定动作收尾当前轮（terminate / answer_terminate），返回最终 JSON 路径。

    与 finish_task 的区别：动作可选、且默认答 No（不继续新任务）。
    """
    ctrl = getattr(editor, "_test_dialogs", None)
    previous = None
    if ctrl is not None:
        previous = ctrl.question_result
        ctrl.question_result = QMessageBox.No
    try:
        if editor._current_screenshot_filename is None:
            capture(editor)
        fill_step(editor, action=action, intent=f"收尾-{action}")
        editor.confirm_step()
        _wait_until(lambda: editor._final_data_saved or bool(editor.rounds),
                    message="收尾后未落轮/未写盘")
        QTest.qWait(_STEP_MS)
    finally:
        if ctrl is not None and previous is not None:
            ctrl.question_result = previous
    return os.path.join(gui_dir_of(editor), f"gui_{editor.gui_number}.json")


def open_edit_mode(editor, gui_dir, round_index=0):
    """把编辑器切到「编辑已完成任务」态，复用产品入口（不经 QFileDialog）。

    :return: (before_data, before_coords) —— **深拷贝快照**，供
        invariants.assert_edit_writeback_preserved 做 INV-13 比对。传本体则可能
        被 load_from_completed_json 原地污染，导致失真的“零差异”假绿。

    注：iOS 的 load_from_completed_json 无返回值，故只断言 _edit_mode 已置位。
    """
    from data_manager import DataManager

    data, error = DataManager.load_json_from_dir(gui_dir)
    assert not error, f"读取已完成任务失败：{error}"
    coords_entries, coords_error = DataManager.load_coords_from_dir(gui_dir)
    if coords_error:
        coords_entries = []

    snapshot_data = copy.deepcopy(data)
    snapshot_coords = copy.deepcopy(coords_entries)

    editor.load_from_completed_json(data, coords_entries, round_index, gui_dir)
    assert editor._edit_mode, "载入后未进入编辑模式"
    QTest.qWait(_STEP_MS)
    return snapshot_data, snapshot_coords
