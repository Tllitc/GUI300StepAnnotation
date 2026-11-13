# -*- coding: utf-8 -*-
"""测试驱动助手：走真实产品代码路径驱动编辑器完成场景。

所有异步点（350ms QTimer.singleShot 隐藏窗口 + 弹出截图窗口）通过 QTest.qWait
推进事件循环，禁止写死长 sleep。

FakeScreenshotCaptureWindow 的状态通过"下一次实例类标志"（_next_xxx）预设，
再由 show_capture_window 内部 new 实例后自动读取并在 __init__ 里消耗掉。
"""

import copy
import json
import os
import re

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QMessageBox


_STEP_MS = 50
_TIMEOUT_MS = 2000

# 动作简写 → 产品下拉框中文标签（action_type_mapping 的反向子集）。
# 传入不在此表中的值时直接当作中文标签使用，便于写 scroll / 拖拽 等专项用例。
_ACTION_CN = {
    "click": "左键单击",
    "double_click": "双击",
    "triple_click": "三击",
    "right_click": "右键单击",
    "middle_click": "中键单击",
    "drag": "拖拽",
    "move": "鼠标移动",
    "scroll": "滚动",
    "type": "文本输入",
    "key": "按键组合",
    "wait": "等待",
    "answer": "回答用户",
    "answer_terminate": "回答并结束",
    "terminate": "任务完成",
}


def _resolve_action(action):
    return _ACTION_CN.get(action, action)


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
# 在原图上重新拉框（编辑已完成任务）
# ---------------------------------------------------------------------------
def relabel_rect(editor, index, rect=(100, 200, 300, 400), selection_type="click"):
    """走完整 UI 入口在该步磁盘原图上重新拉一个单框。

    与 recapture 的差异：不隐藏主窗口、不重新抓屏，ScreenshotCaptureWindow
    以 background_pixmap=磁盘原图 构造，因此不新增/不覆盖任何 PNG。
    """
    _reset_fake(editor)
    Fake = get_fake_cls(editor)
    Fake.prepare_single_box(rect=rect, selection_type=selection_type)

    editor.display_step(index)
    QTest.qWait(50)
    editor.relabel_current_step()

    _wait_until(lambda: not editor._capture_in_flight, message="relabel")
    QTest.qWait(100)


def relabel_drag(editor, index, first=(100, 200, 300, 400), second=(600, 500, 300, 400)):
    """在原图上重新拉双框（拖拽），selection_type 应归一化为 "drag"。"""
    _reset_fake(editor)
    Fake = get_fake_cls(editor)
    Fake.prepare_dual_box(first=first, second=second)

    editor.display_step(index)
    QTest.qWait(50)
    editor.relabel_current_step()

    _wait_until(lambda: not editor._capture_in_flight, message="relabel drag")
    QTest.qWait(100)


def relabel_cancelled(editor, index):
    """预设下一次重新拉框为取消（Esc / 背景模式空选区），标注应逐字不变。"""
    _reset_fake(editor)
    Fake = get_fake_cls(editor)
    Fake.prepare_cancelled()

    editor.display_step(index)
    QTest.qWait(50)
    editor.relabel_current_step()

    _wait_until(lambda: not editor._capture_in_flight, message="relabel cancelled")
    QTest.qWait(100)


def relabel_backgrounds(editor):
    """返回自上次 _reset_fake 以来每次构造弹窗时收到的 background_pixmap 列表。"""
    return list(get_fake_cls(editor).background_history)


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
        # 产品侧坐标框只读，值只能由 _init_editor_from_capture 按 x + w//2 /
        # y + h//2 从框中心派生。setReadOnly 只挡用户输入、挡不住代码 setText，
        # 在这里覆写就会造出「框中心 ≠ 交付 coordinate」这种真实采集不可能出现
        # 的数据（正是 INV-14 要拦的形态），故改为断言期望值等于派生值。
        x, y = [v.strip() for v in coord_text.split(",")]
        assert ed.coord_x_input.text() == x, (
            f"coord_text 与框派生的 X 不一致：期望 {x!r}，实际 {ed.coord_x_input.text()!r}"
            "（rect_info 决定派生值，勿在夹具里手工造坐标）"
        )
        assert ed.coord_y_input.text() == y, (
            f"coord_text 与框派生的 Y 不一致：期望 {y!r}，实际 {ed.coord_y_input.text()!r}"
        )
    if end_coord_text is not None:
        ex, ey = [v.strip() for v in end_coord_text.split(",")]
        assert ed.end_coord_x_input.text() == ex, (
            f"end_coord_text 与终点框派生的 X 不一致：期望 {ex!r}，"
            f"实际 {ed.end_coord_x_input.text()!r}"
        )
        assert ed.end_coord_y_input.text() == ey, (
            f"end_coord_text 与终点框派生的 Y 不一致：期望 {ey!r}，"
            f"实际 {ed.end_coord_y_input.text()!r}"
        )

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
                  # Fake 默认单框 (100, 200, 300, 400) 的派生中心 = (250, 400)
                  coord_text="250,400")
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


# ---------------------------------------------------------------------------
# 多轮 / 编辑模式助手（T9）
# ---------------------------------------------------------------------------
def gui_dir_of(editor):
    """当前任务目录绝对路径（未完成时也可能尚未建目录）。

    命名避开 open_edit_mode 的 gui_dir 形参，防止同名遮蔽。
    """
    return os.path.join(editor.data_manager.current_dir, f"gui_{editor.gui_number}")


def gui_number_from_dir(path):
    """从 gui_xxxxxx 目录名（或含该层的完整路径）提取 6 位编号。"""
    name = os.path.basename(os.path.normpath(str(path)))
    match = re.fullmatch(r"gui_(\d{6})", name)
    assert match, f"不是 gui_xxxxxx 形式的任务目录：{path}"
    return match.group(1)


def walk_rounds(editor, rounds_spec, finish_action="terminate"):
    """多轮走步助手：逐轮采集并以 answer 落轮，最后一轮收尾写最终 JSON。

    :param rounds_spec: [(步数, 该轮任务指令, 动作), ...]。动作可用英文简写
        （click/drag/scroll/...）或直接给中文标签，缺省 "click"。
    :param finish_action: 最后一轮的结束动作（None 表示不落收尾，留给调用方）。
    :return: 最终 JSON 路径（finish_action 为 None 时返回 None）。

    机制说明：Windows 的 answer 分支（save_current_step）会 save_current_round
    → 清空 steps → singleShot(300) 弹续轮对话框并从 QInputDialog.getText 取新
    指令，故必须在第 r 轮落轮**之前**把 dialogs.next_instruction 预置为第 r+1 轮
    指令，才能同时覆盖 B14（取消新轮后沿用旧指令）类场景。
    """
    ctrl = getattr(editor, "_test_dialogs", None)
    total = len(rounds_spec)
    for r, spec in enumerate(rounds_spec):
        n_steps = spec[0]
        instruction = spec[1]
        action_cn = _resolve_action(spec[2] if len(spec) > 2 else "click")
        is_last = (r == total - 1)

        if ctrl is not None and not is_last:
            ctrl.next_instruction = rounds_spec[r + 1][1]
        editor.task_instruction = instruction

        walk_steps(editor, n_steps, action_chinese=action_cn,
                   intent_template=f"第{r + 1}轮第{{i}}步")

        if not is_last:
            last_idx = len(editor.steps) - 1
            fill_step(editor, last_idx, action_chinese="回答用户",
                      intent=f"第{r + 1}轮回答", text=f"第{r + 1}轮回答")
            confirm(editor)
            # answer 分支：save_current_round（同步）+ singleShot(300) start_new_round
            # （异步）。task_instruction 的切换发生在 300ms 之后的对话框回调里，
            # 故必须用 _wait_until 驱动事件循环等待，直接 assert 必然过早失败。
            # lambda 前先绑定局部量，避免闭包按引用捕获循环变量 r。
            expected_rounds = r + 1
            expected_instruction = rounds_spec[r + 1][1]
            _wait_until(lambda: len(editor.rounds) == expected_rounds,
                        message=f"第 {expected_rounds} 轮未落轮")
            _wait_until(lambda: editor.task_instruction == expected_instruction,
                        message=f"续轮后任务指令未切换为第 {r + 2} 轮："
                                f"{editor.task_instruction!r}")
            assert len(editor.steps) == 0, (
                f"第 {expected_rounds} 轮续轮后 steps 未清空：{len(editor.steps)}"
            )

    if finish_action is None:
        return None
    return finish(editor, action=finish_action)


def open_edit_mode(editor, gui_dir, round_index=0):
    """把编辑器切到「编辑已完成任务」态，复用产品入口（不经 QFileDialog）。

    :return: (before_data, before_coords) —— **深拷贝快照**，供
        invariants.assert_edit_writeback_preserved 做 INV-13 比对。传本体则可能
        被 load_from_completed_json 原地污染，导致失真的“零差异”假绿。

    ⚠️ editor 必须是**未走过 finish()/收尾路径的活实例**：Windows 的
    show_new_task_dialog 选 No 后会 finish_all_annotation(close_after_save=False)
    → _return_to_init_menu → close() + deleteLater()，编辑器 C++ 对象被销毁，
    再调本函数会在 load_from_completed_json 里抛 RuntimeError。产品上编辑已完成
    任务本就是 main 新建 AnnotationEditor，故测试应同样用 editor_factory 造新实例。
    """
    from data_manager import DataManager

    data, error = DataManager.load_json_from_dir(gui_dir)
    assert not error, f"读取已完成任务失败：{error}"
    coords_entries, coords_error = DataManager.load_coords_from_dir(gui_dir)
    if coords_error:
        coords_entries = []

    snapshot_data = copy.deepcopy(data)
    snapshot_coords = copy.deepcopy(coords_entries)

    ok = editor.load_from_completed_json(data, coords_entries, round_index, gui_dir)
    assert ok, "load_from_completed_json 返回 False，编辑现场未建立"
    assert editor._edit_mode, "载入后未进入编辑模式"
    QTest.qWait(100)
    return snapshot_data, snapshot_coords
