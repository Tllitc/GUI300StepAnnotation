# -*- coding: utf-8 -*-
"""异步截图驱动与表单填写助手"""
import copy
import os
import re

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


def distinct_capture_seed(editor, used_shots):
    """把 fake 截图计数器推进到 used_shots 之后，保证下一次 capture 的字节全新。

    FakeAndroidScreenCapture 按 _index 取预生成 PNG（不同底色 + "SHOT N"），
    而**新建的编辑器实例 _index 从 0 重启**，产出的第一张会与准备阶段的第一张
    逐字节相同。做「重截图确实改写了内容」这类断言时必须先推进种子，否则会假失败。

    :param used_shots: 现场已存在的截图张数（即已用掉的 _index 个数）
    """
    fake = getattr(editor, "screen_capture", None)
    if fake is not None and hasattr(fake, "_index"):
        fake._index = max(fake._index, used_shots)
    return used_shots


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


def _wait_until(predicate, timeout_ms=3000, step_ms=30, message=""):
    """轮询驱动事件循环，直到 predicate() 为真；超时抛 AssertionError。"""
    waited = 0
    while waited < timeout_ms:
        flush_events(step_ms)
        waited += step_ms
        if predicate():
            return
    raise AssertionError(f"等待条件超时（{timeout_ms}ms）：{message or predicate}")


# ---------------------------------------------------------------------------
# gui 目录助手
# ---------------------------------------------------------------------------
def gui_dir_of(editor):
    """当前任务目录绝对路径（未完成时可能尚未建目录）。"""
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


# ---------------------------------------------------------------------------
# 多轮 / 编辑模式助手
# ---------------------------------------------------------------------------
def walk_rounds(editor, rounds_spec, finish_action="answer_terminate", modal=None):
    """多轮走步助手：逐轮采集并以 answer 落轮，最后一轮收尾写最终 JSON。

    :param rounds_spec: [(步数, 该轮任务指令, 动作), ...]；动作为 Android
        action_combo 的英文 key（click/scroll/drag/type/...），缺省 "click"。
    :param finish_action: 最后一轮的收尾动作；None 表示不落收尾，留给调用方。
    :param modal: 模态应答控制器；缺省从 editor._test_modal 取（conftest 已注入）。
    :return: 最终 JSON 路径（finish_action 为 None 时返回 None）。

    机制说明：Android 的 answer 分支先同步 _save_current_round_to_list 落轮并
    消费掉当前轮（2.1/B20a 修复后清空序列口径对齐 iOS），再 singleShot(300) 弹
    _start_new_round(from_answer=True) 取新指令。因此本助手必须等 300ms 后续轮
    完成，并预置 modal.input_text 为下一轮指令（同时覆盖 B14 场景）。
    """
    ctrl = modal if modal is not None else getattr(editor, "_test_modal", None)
    assert ctrl is not None, "walk_rounds 需要 modal 夹具（或 editor._test_modal）"
    total = len(rounds_spec)

    for r, spec in enumerate(rounds_spec):
        n_steps = spec[0]
        instruction = spec[1]
        action = spec[2] if len(spec) > 2 else "click"
        is_last = (r == total - 1)

        if not is_last:
            ctrl.input_text = rounds_spec[r + 1][1]
        editor.task_instruction = instruction

        for i in range(n_steps):
            capture_and_wait(editor)
            fill_valid_step(editor, action=action, intent=f"第{r + 1}轮第{i + 1}步")
            editor.confirm_step()
            flush_events(50)
        assert len(editor.steps_data) == n_steps, (
            f"第 {r + 1} 轮走步后 steps_data 长度应为 {n_steps}，"
            f"实际 {len(editor.steps_data)}"
        )

        if is_last:
            break

        # answer 落轮 + 300ms 后续轮对话框
        capture_and_wait(editor)
        fill_valid_step(editor, action="answer", intent=f"第{r + 1}轮回答",
                        text=f"第{r + 1}轮回答")
        editor.confirm_step()
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
    capture_and_wait(editor)
    fill_valid_step(editor, action=finish_action, intent=f"收尾-{finish_action}",
                    text="收尾回答")
    editor.confirm_step()
    flush_events(100)
    if not editor._task_completed:
        raise AssertionError("任务未完成（_finish_task 校验或保存失败）")
    return os.path.join(gui_dir_of(editor), f"gui_{editor.gui_number}.json")


def open_edit_mode(editor, gui_dir, round_index=0):
    """把编辑器切到「编辑已完成任务」态，复用产品入口（不经 QFileDialog）。

    :return: (before_data, before_coords) —— **深拷贝快照**，供
        invariants.assert_edit_writeback_preserved 做 INV-13 比对。传本体则可能
        被 load_from_completed_json 原地污染，导致失真的“零差异”假绿。

    注：Android 的 load_from_completed_json 无返回值，故只断言 _edit_mode 已置位。
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
    drain_sidebar_thumbs(editor)
    return snapshot_data, snapshot_coords
