# -*- coding: utf-8 -*-
"""Task 3 撤销操作（undo_step）一致性测试组（SubTask 3.1 ~ 3.9）

覆盖 spec「撤销操作（undo_step）一致性」Requirement：
- 3.1 撤销末尾已确认步（3→2）五者一致
- 3.2 DA-2 撤销后立即重截，序号复用，侧栏/画布不得显示旧缓存
- 3.3 DA-3 停在中间步按撤销：记录实际行为，未确认编辑不得静默丢失
- 3.4 DA-4 已截图未确认新步时撤销：末步与在途新图两文件同删的定性
- 3.5 DA-1 swipe 测量中撤销：测量态必须复位
- 3.6 DA-1 scroll 测量中撤销：测量态必须复位
- 3.7 DA-5 逐步撤销至空：草稿同步、续采不复活、可重新走步
- 3.8 截图在途时撤销：DA-7 修复后被拦截，截图正常完成；锁复位后撤销可执行
- 3.9 撤销后 finish_task：最终 JSON/coords 连续无缺失
"""
import os

from PyQt5.QtCore import QRect
from PyQt5.QtGui import QPixmap
from PyQt5.QtTest import QTest

from annotation_editor import StepListItemWidget
from helpers import (capture_and_wait, confirm_n_steps, drain_sidebar_thumbs,
                     fill_valid_step, finish_task, flush_events)
from invariants import (assert_all, assert_draft, assert_files,
                        assert_final_json, assert_model, assert_transient)


def _file_bytes(path):
    with open(path, "rb") as f:
        return f.read()


# ---------- SubTask 3.1：撤销末尾已确认步（3→2） ----------

def test_3_1_undo_last_confirmed_step(editor_factory):
    """撤销末尾已确认步：文件已删、侧栏 2 条、草稿 2 步，assert_all 全绿"""
    editor = editor_factory()
    confirm_n_steps(editor, 3)
    drain_sidebar_thumbs(editor)  # 确保 3 张缩略图均已进 LRU 缓存

    removed_fn = editor.steps_data[2]["screenshot"]
    removed_path = os.path.join(editor.gui_dir, removed_fn)
    keep_fns = [editor.steps_data[0]["screenshot"], editor.steps_data[1]["screenshot"]]

    editor.undo_step()
    flush_events()

    # 模型：弹末步，回到待编辑空位
    assert len(editor.steps_data) == 2
    assert editor.current_step == 2
    assert [s["screenshot"] for s in editor.steps_data] == keep_fns
    # 磁盘：被撤销步文件已删，保留步文件不动
    assert not os.path.exists(removed_path)
    for fn in keep_fns:
        assert os.path.isfile(os.path.join(editor.gui_dir, fn))
    # 侧栏：2 条
    assert len(editor.sidebar.item_widgets) == 2
    # 草稿：主动落盘后 2 步且与内存一致
    draft = assert_draft(editor)
    assert len(draft["steps_data"]) == 2

    assert_all(editor)


# ---------- SubTask 3.2：DA-2 撤销后立即重截，序号复用不得显示旧图 ----------

def test_3_2_undo_then_recapture_reuses_number(editor_factory):
    """撤销末步（文件 N）后立即重新截图：新文件复用序号 N，
    侧栏缩略图/画布必须显示新图而非旧缓存，steps_data 引用正确"""
    editor = editor_factory()
    confirm_n_steps(editor, 3)
    drain_sidebar_thumbs(editor)  # 旧图缩略图进缓存

    last_fn = editor.steps_data[2]["screenshot"]
    last_path = os.path.join(editor.gui_dir, last_fn)
    old_bytes = _file_bytes(last_path)

    editor.undo_step()
    flush_events()
    assert len(editor.steps_data) == 2
    assert not os.path.exists(last_path)

    # 立即重新截图：DataManager 取最小可用序号，复用 N
    new_fn = capture_and_wait(editor)
    assert new_fn == last_fn, f"序号未复用: {new_fn} != {last_fn}"
    new_bytes = _file_bytes(last_path)
    assert new_bytes != old_bytes, "重截后文件内容未变化（非新图）"

    # 画布从磁盘按需重载，应显示新图
    canvas_pixmap = editor.screenshot_canvas._pixmap
    assert canvas_pixmap is not None and not canvas_pixmap.isNull()
    assert canvas_pixmap.toImage() == QPixmap(last_path).toImage(), \
        "画布显示的不是新截图"

    # 用与被撤销步相同的动作/vertices 确认新步（缩略图缓存 key 完全相同）
    fill_valid_step(editor)
    editor.confirm_step()
    flush_events(50)
    assert len(editor.steps_data) == 3
    assert editor.steps_data[2]["screenshot"] == new_fn
    assert editor.steps_data[2]["screenshot_filepath"] == \
        os.path.join(editor.gui_dir, new_fn)

    # DA-2 修复后：侧栏缩略图按新文件内容渲染（缓存已按文件名失效）
    drain_sidebar_thumbs(editor)
    item = editor.sidebar.item_widgets[2]
    assert item.thumb_loaded
    expected = editor.build_marked_preview(
        new_fn, editor.steps_data[2].get("vertices"), StepListItemWidget.THUMB_SIZE)
    assert expected is not None
    thumb = item.thumb_label.pixmap()
    assert thumb is not None and not thumb.isNull()
    assert thumb.toImage() == expected.toImage(), \
        "侧栏缩略图显示了被撤销步的旧图缓存（DA-2 回归）"


# ---------- SubTask 3.3：DA-3 停在中间步按撤销 ----------

def test_3_3_undo_while_standing_on_middle_step(editor_factory):
    """confirm 3 步后 jump_to_step(1) 停在中间步，修改表单（不确认）后 undo_step()，
    记录实际行为并断言：未确认编辑不得静默丢失"""
    editor = editor_factory()
    confirm_n_steps(editor, 3)

    # 跳到中间步（第 2 步），只做表单编辑不确认
    editor.jump_to_step(1)
    flush_events()
    assert editor.current_step == 1
    editor.intent_input.setText("中间步未确认改动")
    flush_events()

    editor.undo_step()
    flush_events()

    # 实际行为记录：undo_step 固定弹末步（steps_data 3→2），current_step 指到末尾
    assert len(editor.steps_data) == 2
    assert editor.current_step == 2
    assert editor.steps_data[0]["intent"] == "步骤1-click"
    # 模型/磁盘/草稿一致（弹末步本身不破坏一致性）
    assert_model(editor)
    assert_files(editor)
    assert_draft(editor)

    # DA-3 修复后：undo_step 开头先 _save_current_to_steps，
    # 停在中间步的未确认编辑落盘保留，不被静默丢弃
    assert editor.steps_data[1]["intent"] == "中间步未确认改动"


# ---------- SubTask 3.4：DA-4 已截图未确认新步时撤销 ----------

def test_3_4_undo_with_unconfirmed_new_screenshot(editor_factory):
    """已截图未确认新步（current_step == len(steps_data)）时 undo_step()：
    定性「末步与当前未保存新图两文件同删」行为，检查无孤儿、无引用悬空"""
    editor = editor_factory()
    confirm_n_steps(editor, 2)
    drain_sidebar_thumbs(editor)

    last_fn = editor.steps_data[1]["screenshot"]
    last_path = os.path.join(editor.gui_dir, last_fn)
    keep_fn = editor.steps_data[0]["screenshot"]

    # 截图但不确认：current_step == len(steps_data)，新图只在三指针上
    new_fn = capture_and_wait(editor)
    new_path = os.path.join(editor.gui_dir, new_fn)
    assert editor.current_step == len(editor.steps_data) == 2
    assert editor._current_screenshot_filename == new_fn

    editor.undo_step()
    flush_events()

    # DA-4 定性：末步与当前未保存新图两个文件同时被删——
    # 新图未被任何步骤引用，同删可避免孤儿，行为符合预期
    assert len(editor.steps_data) == 1
    assert editor.current_step == 1
    assert editor._current_screenshot_filename is None
    assert editor._current_screenshot_filepath is None
    assert not os.path.exists(last_path), "末步文件未删"
    assert not os.path.exists(new_path), "当前未保存新图未删"
    assert os.path.isfile(os.path.join(editor.gui_dir, keep_fn))

    # 无孤儿、无引用悬空
    assert_model(editor)
    assert_files(editor)
    assert_draft(editor)
    assert len(editor.sidebar.item_widgets) == 1

    assert_all(editor)


# ---------- SubTask 3.5：DA-1 swipe 测量中撤销 ----------

def test_3_5_undo_during_swipe_measurement(editor_factory):
    """swipe 测量中（起点已拉框、_swipe_measuring=True）撤销：
    测量标志必须复位、起点数据清空，后续普通拉框走正常分支（不进测量终点分支）

    DA-1 结论：undo_step 虽未直接调用 _cancel_swipe_measurement，但经
    _reset_for_next_step → _clear_inputs（L2399）间接复位，证明安全，固化为回归用例。
    """
    editor = editor_factory()
    confirm_n_steps(editor, 2)
    capture_and_wait(editor)
    fill_valid_step(editor, action="swipe")

    # 进入 swipe 测量态：起点已记录
    editor._start_swipe_measurement()
    assert editor._swipe_measuring is True
    assert editor._swipe_start_vertices == [100, 200, 300, 400]

    editor.undo_step()
    flush_events()

    # 测量态复位、无残留起点
    assert editor._swipe_measuring is False
    assert editor._swipe_start_vertices is None

    # 随后普通拉框走正常分支：重新截图后切到 swipe 拉框，
    # 若 _swipe_measuring 残留，本框会被当作「测量终点」写入 coord2 且
    # _current_vertices 被覆盖为残留起点；正常分支则应填入起点坐标并保留本次拉框
    capture_and_wait(editor)
    editor.action_combo.setCurrentIndex(editor.action_combo.findData("swipe"))
    editor.overlay.resize(360, 640)  # offscreen 下赋予蒙版尺寸，使坐标映射生效
    editor._on_overlay_rect_drawn(QRect(10, 20, 90, 140))
    flush_events()
    # QRect right/bottom 为 left+width-1 / top+height-1：1:1 映射得 [10,20,99,159]
    assert editor._current_vertices == [10, 20, 99, 159]
    assert editor.coord_x_input.text() == "54"
    assert editor.coord_y_input.text() == "89"
    assert not editor.coord2_x_input.text().strip(), "拉框误入测量终点分支"
    assert editor._swipe_measuring is False


# ---------- SubTask 3.6：DA-1 scroll 测量中撤销 ----------

def test_3_6_undo_during_scroll_measurement(editor_factory):
    """scroll 测量中撤销：_scroll_measuring/_scroll_references 等测量态必须复位

    DA-1 结论：undo_step 经 _reset_for_next_step → _clear_inputs（L2400）间接调用
    _cancel_scroll_measurement，证明安全，固化为回归用例。
    注：_scroll_total 按 _cancel_scroll_measurement 契约不复位（保留测量结果语义，
    与 confirm_step 路径一致；_start_scroll_measurement 重新开始时会清零），
    故此处只断言测量态字段，不断言 _scroll_total。
    """
    editor = editor_factory()
    confirm_n_steps(editor, 2)
    capture_and_wait(editor)
    fill_valid_step(editor, action="scroll")

    # 进入 scroll 测量态并模拟已累计一次滚动
    editor._start_scroll_measurement()
    assert editor._scroll_measuring is True
    editor._scroll_total = 350
    editor._scroll_references = [300, 650]

    editor.undo_step()
    flush_events()

    # 测量态复位（对照 _cancel_scroll_measurement 契约）
    assert editor._scroll_measuring is False
    assert editor._scroll_references == []
    assert editor._scroll_start_vertices is None
    assert editor._scroll_resetting is False


# ---------- SubTask 3.7：DA-5 逐步撤销至空 ----------

def test_3_7_undo_to_empty_draft_and_resume(editor_factory):
    """逐步撤销至空：草稿同步为空、续采不复活已删步骤、可重新截图走步"""
    editor = editor_factory()
    confirm_n_steps(editor, 2)
    # 造出含 2 步的草稿文件（模拟崩溃前最后一次落盘）
    editor._write_draft_now()
    flush_events()
    assert editor.data_manager.load_draft(editor.gui_number) is not None

    # 逐步撤销至空
    editor.undo_step()
    editor.undo_step()
    # 让防抖 draft_timer 触发：DA-5 修复后空现场 _write_draft_now 删除残留草稿
    flush_events(1200)
    assert len(editor.steps_data) == 0
    assert editor.current_step == 0

    # 空现场一致性
    assert_transient(editor)
    assert_model(editor)
    assert_files(editor)
    assert_draft(editor)  # 空现场按设计不写草稿，返回 None
    assert len(editor.sidebar.item_widgets) == 0

    # 捕获「撤销清空时刻」的草稿快照，供续采复活判定
    stale_draft = editor.data_manager.load_draft(editor.gui_number)

    # 撤销清空后可重新截图走步
    capture_and_wait(editor)
    fill_valid_step(editor)
    editor.confirm_step()
    flush_events(50)
    assert len(editor.steps_data) == 1
    assert_model(editor)
    assert_files(editor)

    # DA-5 修复后：清空时刻草稿文件已删除，续采不得复活已删步骤
    assert stale_draft is None or not stale_draft.get("steps_data")
    resumed = editor_factory(auto_init=False)
    resumed.load_from_draft(stale_draft)
    flush_events(100)
    assert len(resumed.steps_data) == 0, "续采复活了已撤销的步骤"


# ---------- SubTask 3.8：截图在途时撤销 ----------

def test_3_8_undo_while_screenshot_in_flight(editor_factory):
    """take_screenshot() 后立即（不等完成）undo_step()：

    DA-7 修复后：截图在途时撤销被拦截（状态栏提示、模型/磁盘不变）；
    在途截图正常完成写入当前步；锁复位后 undo 可正常执行。
    """
    editor = editor_factory()
    confirm_n_steps(editor, 2)
    keep_fns = [s["screenshot"] for s in editor.steps_data]

    editor.take_screenshot()
    assert editor._screenshot_in_progress is True

    # 截图在途（50ms singleShot 未触发）立即撤销 → 被拦截，无副作用
    editor.undo_step()
    assert "截图进行中" in editor.status_label.text()
    assert len(editor.steps_data) == 2
    assert [s["screenshot"] for s in editor.steps_data] == keep_fns

    # 推进事件循环直到截图锁复位（含 800ms 冷却）：截图正常完成写入当前步
    waited = 0
    while editor._screenshot_in_progress and waited < 15000:
        QTest.qWait(30)
        waited += 30
    flush_events()
    assert editor._screenshot_in_progress is False
    assert editor._insert_after_index is None
    assert len(editor.steps_data) == 2  # 写入的是未确认新步空位，不新增步骤
    new_fn = editor._current_screenshot_filename
    assert new_fn and new_fn not in keep_fns
    assert os.path.isfile(os.path.join(editor.gui_dir, new_fn))

    # 锁复位后 undo 正常执行：弹末步，未确认新图一并删除（DA-4 语义）
    editor.undo_step()
    flush_events()
    assert len(editor.steps_data) == 1
    assert editor.steps_data[0]["screenshot"] == keep_fns[0]
    assert not os.path.exists(os.path.join(editor.gui_dir, keep_fns[1]))
    assert not os.path.exists(os.path.join(editor.gui_dir, new_fn))

    # 模型/磁盘/草稿/侧栏/瞬态全一致
    assert_all(editor)
    assert len(editor.sidebar.item_widgets) == 1


# ---------- SubTask 3.9：撤销后 finish_task 结束 ----------

def test_3_9_finish_task_after_undo(editor_factory, modal):
    """撤销末步后重新走步并 finish_task：最终 JSON/coords 引用连续无缺失"""
    editor = editor_factory()
    confirm_n_steps(editor, 3)
    removed_fn = editor.steps_data[2]["screenshot"]
    removed_path = os.path.join(editor.gui_dir, removed_fn)

    editor.undo_step()
    flush_events()
    assert len(editor.steps_data) == 2
    assert not os.path.exists(removed_path)

    # 以 answer_terminate 收尾（完成框答 No）；新截图复用被撤销步的序号
    finish_task(editor, modal)
    flush_events(100)

    data = assert_final_json(editor.gui_dir, editor.gui_number)
    traj = data["messages"][1]["trajectory"]
    assert len(traj) == 3  # 撤销后 2 步 + answer_terminate 步
    # 序号复用：收尾步截图与被撤销步同名，但内容已是新图（assert_final_json 已校验存在性与唯一性）
    assert traj[2]["observation"]["screenshot"] == removed_fn
    assert editor._task_completed is True
