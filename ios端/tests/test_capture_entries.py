# -*- coding: utf-8 -*-
"""iOS 截图入口拆分测试组：「给下一步截图」/「重新截图」/ 工具栏与快捷键。

覆盖范围（对应 annotation_editor.py 的入口拆分改动）：
  1. 空列表点「给下一步截图」：首次截图落末位空位，不产生步骤；
  2. 确认首步（游标已在待确认空位）后点「给下一步截图」：已落表步骤不受影响；
  3. 回历史步点「给下一步截图」：旧步现场落表、游标移到待确认空位、无孤儿文件；
  4. 历史步「重新截图」：原地覆盖、文件名/序号/磁盘集合不变、内容更新；
  5. 待确认空位重复截图：两个入口都原地覆盖，磁盘不增文件；
  6. 无截图时「重新截图」退化为首次截图；
  7. 测量态约束：swipe 两个入口都拦截；scroll 只拦截追加、重截走 extra 路径；
  8. 工具栏文案/配色、画布占位文案、Ctrl+Q / Ctrl+S 快捷键路由。

不依赖真机与网络，全部在 offscreen 下运行。异步点统一用 QTest.qWait /
helpers._wait_until 轮询产品状态标记驱动，不写死长 sleep。
运行（cwd 为 ios端）::

    python -m pytest tests/test_capture_entries.py -q
"""

import inspect
import os

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtTest import QTest

from helpers import (
    _wait_until,
    capture,
    confirm,
    distinct_capture_seed,
    draw_rect,
    fill_step,
    walk_steps,
)
from invariants import SCREENSHOT_NAME_RE


# ----------------------------------------------------------------------
# 本文件专用辅助
# ----------------------------------------------------------------------

def _strict_pngs(gui_dir):
    """gui_dir 下当前全部严格命名 PNG 文件名集合（只读快照）。"""
    if not os.path.isdir(gui_dir):
        return set()
    return {f for f in os.listdir(gui_dir) if SCREENSHOT_NAME_RE.match(f)}


def _drive_start_capture(editor):
    """触发「给下一步截图」并等待 50ms 截图回调完成，返回截图文件名。"""
    editor.start_capture()
    _wait_until(
        lambda: not editor._screenshot_in_progress,
        message="start_capture 的截图回调未在超时内完成",
    )
    QTest.qWait(80)  # 等回调里画布/侧栏/草稿事件处理完
    assert editor._current_screenshot_filename, "「给下一步截图」未成功：没有截图文件名"
    return editor._current_screenshot_filename


def _drive_recapture(editor):
    """触发「重新截图」并等待回调完成，返回截图文件名。"""
    editor.recapture_current_step()
    _wait_until(
        lambda: not editor._screenshot_in_progress,
        message="recapture_current_step 的截图回调未在超时内完成",
    )
    QTest.qWait(80)
    assert editor._current_screenshot_filename, "「重新截图」未成功：没有截图文件名"
    return editor._current_screenshot_filename


# ----------------------------------------------------------------------
# 1. 空列表首次「给下一步截图」
# ----------------------------------------------------------------------

def test_start_capture_on_empty_list(editor):
    """空列表点「给下一步截图」：只产生待确认截图，不新增步骤。"""
    assert editor.steps_data == []
    assert editor.current_step == 0

    name = _drive_start_capture(editor)

    assert editor.steps_data == [], (
        f"空列表首次截图不应生成已落表步骤，实际 {len(editor.steps_data)} 条"
    )
    assert editor.current_step == 0, (
        f"空列表首次截图应停在首个待确认位 0，实际 {editor.current_step}"
    )
    assert editor._current_screenshot_filename == name
    pngs = _strict_pngs(editor.gui_dir)
    assert pngs == {name}, f"首次截图应只落 1 个严格命名 PNG，实际 {pngs}"


# ----------------------------------------------------------------------
# 2. 确认首步后「给下一步截图」
# ----------------------------------------------------------------------

def test_start_capture_after_first_confirm_keeps_committed_step(editor):
    """确认首步后点「给下一步截图」：已落表步骤截图不变，只多一张新图。"""
    capture(editor)
    fill_step(editor, action="click")
    confirm(editor)
    assert len(editor.steps_data) == 1
    assert editor.current_step == 1, "确认首步后游标应位于待确认空位 1"

    first_shot = editor.steps_data[0]["screenshot"]
    pngs_before = _strict_pngs(editor.gui_dir)

    new_name = _drive_start_capture(editor)

    assert len(editor.steps_data) == 1, (
        f"待确认空位截图不应新增已落表步骤，实际 {len(editor.steps_data)} 条"
    )
    assert editor.steps_data[0]["screenshot"] == first_shot, (
        f"首步截图引用被覆盖：{editor.steps_data[0]['screenshot']} != {first_shot}"
    )
    assert editor.current_step == 1, (
        f"截图后游标应仍停在待确认空位 1，实际 {editor.current_step}"
    )
    pngs_after = _strict_pngs(editor.gui_dir)
    added = pngs_after - pngs_before
    assert len(added) == 1, f"应只新增 1 张截图，实际新增 {added}"
    assert os.path.basename(editor._current_screenshot_filename) == added.pop(), (
        "当前截图引用应指向本次新落盘文件"
    )
    assert editor._current_screenshot_filename == new_name


# ----------------------------------------------------------------------
# 3. 回历史步「给下一步截图」
# ----------------------------------------------------------------------

def test_start_capture_from_history_step_appends_pending_slot(editor):
    """回第 1 步点「给下一步截图」：旧步原样保留，游标移到待确认空位，无孤儿。"""
    walk_steps(editor, 2, action="click")
    shots_before = [s["screenshot"] for s in editor.steps_data]
    pngs_before = _strict_pngs(editor.gui_dir)

    editor.display_step(0)
    QTest.qWait(0)
    assert editor.current_step == 0

    _drive_start_capture(editor)

    shots_after = [s["screenshot"] for s in editor.steps_data]
    assert len(editor.steps_data) == 2, (
        f"历史步追加截图不应改变已落表步骤数，实际 {len(editor.steps_data)} 条"
    )
    assert shots_after == shots_before, (
        f"历史步截图引用被改动：{shots_after} != {shots_before}"
    )
    assert editor.current_step == 2, (
        f"截图后游标应移到待确认空位 2，实际 {editor.current_step}"
    )
    pngs_after = _strict_pngs(editor.gui_dir)
    added = pngs_after - pngs_before
    assert len(added) == 1, f"历史步追加应只新增 1 张截图，实际新增 {added}"
    assert added.pop() == editor._current_screenshot_filename, (
        "新增截图文件必须正是当前截图引用，不得产生无主孤儿文件"
    )
    # 新截图的现场不继承历史步的坐标/拉框
    assert editor.coord_x_input.text() == "", "新空位不应残留历史步坐标"
    assert editor._current_vertices is None, "新空位不应残留历史步拉框顶点"


# ----------------------------------------------------------------------
# 4. 历史步「重新截图」
# ----------------------------------------------------------------------

def test_recapture_history_step_overwrites_in_place(editor):
    """历史步「重新截图」：文件名/序号/磁盘集合不变，内容更新，旁步不受影响。"""
    walk_steps(editor, 2, action="click")
    editor.display_step(0)
    QTest.qWait(0)
    assert editor.current_step == 0

    target = editor.steps_data[0]
    old_name = target["screenshot"]
    old_path = target["screenshot_filepath"]
    other_name = editor.steps_data[1]["screenshot"]
    pngs_before = _strict_pngs(editor.gui_dir)
    old_idx = editor.screen_capture.classify(old_path)
    assert old_idx is not None, "截图前应能从磁盘识别第 1 步截图内容"

    # 推进桩计数器，保证新截图与准备阶段任何一张的颜色都不同
    distinct_capture_seed(editor, 2)

    new_name = _drive_recapture(editor)

    assert new_name == old_name, (
        f"重新截图必须原地覆盖，文件名不应变化：{new_name} != {old_name}"
    )
    assert editor.steps_data[0]["screenshot"] == old_name, "重新截图不应重建步骤条目"
    assert os.path.basename(old_name) == "gui_000001_0001.png", (
        f"重新截图不应改变序号：{old_name}"
    )
    pngs_after = _strict_pngs(editor.gui_dir)
    assert pngs_after == pngs_before, (
        f"重新截图不应增删磁盘文件：{pngs_after} != {pngs_before}"
    )
    new_idx = editor.screen_capture.classify(old_path)
    assert new_idx == 2, f"重新截图后磁盘内容应为新截图（序号 2），实际序号 {new_idx}"
    assert new_idx != old_idx, "重新截图后文件内容必须确实更新"
    # 旧拉框/坐标不匹配新图，应被清空；旁步未受影响
    assert editor.coord_x_input.text() == "", "重新截图后应清空旧坐标"
    assert editor._current_vertices is None, "重新截图后应清空旧拉框顶点"
    assert editor.steps_data[1]["screenshot"] == other_name, "重新截图波及了第 2 步"


# ----------------------------------------------------------------------
# 5. 待确认空位重复截图：原地覆盖
# ----------------------------------------------------------------------

def test_pending_slot_repeated_capture_overwrites(editor):
    """待确认空位重复截图：两个入口都原地覆盖，磁盘文件数/步骤数不变。"""
    capture(editor)
    fill_step(editor, action="click")
    confirm(editor)
    assert len(editor.steps_data) == 1
    assert editor.current_step == 1

    _drive_start_capture(editor)
    count_after_first = len(_strict_pngs(editor.gui_dir))

    _drive_start_capture(editor)
    assert len(_strict_pngs(editor.gui_dir)) == count_after_first, (
        "待确认空位再次「给下一步截图」应原地覆盖，不应新增文件"
    )

    _drive_recapture(editor)
    assert len(_strict_pngs(editor.gui_dir)) == count_after_first, (
        "待确认空位「重新截图」应原地覆盖，不应新增文件"
    )

    assert len(editor.steps_data) == 1, "重复截图不应新增已落表步骤"
    assert editor.current_step == 1, (
        f"重复截图后游标应仍在待确认空位 1，实际 {editor.current_step}"
    )


# ----------------------------------------------------------------------
# 6. 无截图时「重新截图」退化
# ----------------------------------------------------------------------

def test_recapture_without_capture_falls_back_to_first(editor):
    """全新编辑器直接「重新截图」：退化为首次截图，无异常、状态复位。"""
    assert editor.steps_data == []
    assert editor._current_screenshot_filename is None

    name = _drive_recapture(editor)

    assert name == "gui_000001_0001.png"
    assert editor.steps_data == [], "首次退化截图不应落表步骤"
    assert editor.current_step == 0
    assert editor._screenshot_in_progress is False, "截图完成标记未复位"
    assert _strict_pngs(editor.gui_dir) == {name}


# ----------------------------------------------------------------------
# 7. 测量态约束
# ----------------------------------------------------------------------

def test_entries_blocked_during_swipe_measurement(editor):
    """swipe 测量中：两个截图入口都直接拦截，不发起截图、不改文件。"""
    capture(editor)
    draw_rect(editor, 50, 200, 150, 300)
    editor._start_swipe_measurement()
    QTest.qWait(0)
    assert editor._swipe_measuring is True

    pngs_before = _strict_pngs(editor.gui_dir)
    name_before = editor._current_screenshot_filename

    editor.start_capture()
    editor.recapture_current_step()
    QTest.qWait(80)  # 确认没有延迟截图回调产生副作用

    assert _strict_pngs(editor.gui_dir) == pngs_before, (
        "swipe 测量中截图入口应被拦截，磁盘不应变化"
    )
    assert editor._current_screenshot_filename == name_before, (
        "swipe 测量中截图入口应被拦截，当前截图引用不应变化"
    )
    assert editor._screenshot_in_progress is False, "拦截后不应进入截图进行中态"
    assert editor._capture_append_new_step is False, "拦截后不应残留追加标记"

    editor._cancel_swipe_measurement()
    QTest.qWait(0)


def test_scroll_blocks_append_but_recapture_goes_extra(editor):
    """scroll 测量中：追加入口拦截；重截放行并走既有 extra 截图路径。"""
    capture(editor)
    draw_rect(editor, 50, 200, 150, 300)
    editor._start_scroll_measurement()
    QTest.qWait(0)
    assert editor._scroll_measuring is True
    assert editor._scroll_preserve_screenshot is True

    pngs_before = _strict_pngs(editor.gui_dir)
    name_before = editor._current_screenshot_filename
    steps_before = [s["screenshot"] for s in editor.steps_data]

    # 追加入口被拦截
    editor.start_capture()
    QTest.qWait(80)
    assert _strict_pngs(editor.gui_dir) == pngs_before, (
        "scroll 测量中「给下一步截图」应被拦截，磁盘不应变化"
    )

    # 重截入口放行：新图登记为 extra，不顶替当前步截图
    extra_before = len(editor._scroll_extra_screenshots)
    _drive_recapture(editor)
    assert len(editor._scroll_extra_screenshots) == extra_before + 1, (
        "scroll 测量中「重新截图」应产生 1 张 extra 截图"
    )
    assert editor._current_screenshot_filename == name_before, (
        "scroll extra 截图不应顶替当前步骤截图引用"
    )
    assert [s["screenshot"] for s in editor.steps_data] == steps_before, (
        "scroll 测量中截图不应改变已落表步骤"
    )

    editor._cancel_scroll_measurement()
    QTest.qWait(0)
    assert editor._scroll_extra_screenshots == [], "取消测量后 extra 列表应清空"


# ----------------------------------------------------------------------
# 8. 工具栏与快捷键
# ----------------------------------------------------------------------

def test_toolbar_and_shortcuts(editor, editor_factory, monkeypatch):
    """两个按钮的文案/配色、画布占位文案与 Ctrl+Q / Ctrl+S 路由。"""
    assert editor.btn_recapture.text() == "重新截图"
    assert "#FF9800" in editor.btn_recapture.styleSheet(), "「重新截图」应为橙色"
    assert editor.btn_capture_next.text() == "给下一步截图 (Ctrl+Q)"
    assert "#2196F3" in editor.btn_capture_next.styleSheet(), (
        "「给下一步截图」应为蓝色"
    )
    assert not hasattr(editor, "btn_screenshot"), "通用「截图」按钮应已被移除"

    # 初始状态栏文案只在建目录前保留，用未初始化目录的实例读取真实文案
    fresh = editor_factory(auto_init=False)
    assert "给下一步截图" in fresh.status_label.text(), (
        f"初始状态栏文案应提示「给下一步截图」，实际 {fresh.status_label.text()!r}"
    )
    canvas_src = inspect.getsource(type(editor.canvas).paintEvent)
    assert "给下一步截图" in canvas_src, "画布空态占位文案应提示「给下一步截图」"

    calls = []
    monkeypatch.setattr(editor, "start_capture", lambda: calls.append("start_capture"))
    monkeypatch.setattr(editor, "go_next", lambda: calls.append("go_next"))

    editor.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Q, Qt.ControlModifier))
    assert calls == ["start_capture"], (
        f"Ctrl+Q 应路由到 start_capture，实际调用 {calls}"
    )
    editor.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_S, Qt.ControlModifier))
    assert calls == ["start_capture", "go_next"], (
        f"Ctrl+S 应路由到 go_next，实际调用 {calls}"
    )