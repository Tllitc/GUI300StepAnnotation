# -*- coding: utf-8 -*-
"""重新截图 / scroll extra 截图序号回收测试组（D-5 / D 类缩略图疑点）。

覆盖：
  6.1 历史步“重新截图”：原地覆盖、序号/引用不变、磁盘内容更新、
      其他步不受影响、侧栏缩略图缓存失效后反映新图；
  6.2 scroll 测量 extra 截图：取消路径与真实完成路径的清理、测量标记复位、
      删除 extra 后新普通截图序号回收（D-5 排除/固化）；
  6.3 覆盖一步后全模型/磁盘/最终 JSON 的图-业务位置一一对应。

只依赖 conftest 夹具与 helpers/invariants/fakes，不修改任何产品代码。
运行（在 ios端 目录）::

    python -m pytest tests/test_recapture.py -q
"""

import os

from PyQt5.QtGui import QColor
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QMessageBox

from data_manager import DataManager
from helpers import (
    capture,
    fill_step,
    confirm,
    walk_steps,
    _wait_until,
)
from invariants import (
    assert_all,
    assert_model_consistency,
    assert_disk_consistency,
    assert_measurement_state_reset,
    assert_final_json_consistency,
)
from fakes import _DISTINCT_COLORS


# ----------------------------------------------------------------------
# 本文件本地辅助
# ----------------------------------------------------------------------

def _strict_png_names(gui_dir):
    """gui_dir 下当前全部严格命名 PNG（与 invariants 同口径的本地只读快照）。"""
    from invariants import SCREENSHOT_NAME_RE

    if not os.path.isdir(gui_dir):
        return set()
    return {f for f in os.listdir(gui_dir) if SCREENSHOT_NAME_RE.match(f)}


def _pix_top_center_rgb(pixmap):
    """取 pixmap 顶部正中像素 RGB（避开居中文案与侧栏缩略图红框标注区）。

    缩略图为 390x844 等比缩放（约 52x112）并在 QLabel 中居中，左上角可能是
    label 底色而非图像，故统一采样图像自身的“顶部正中”。
    """
    if pixmap is None or pixmap.isNull():
        return None
    image = pixmap.toImage()
    rgb = QColor(image.pixel(max(0, image.width() // 2), 3))
    return rgb.red(), rgb.green(), rgb.blue()


def _expected_color(shot_idx):
    """按 FakeScreenCapture 序号（0-based）推预期底色。"""
    return _DISTINCT_COLORS[shot_idx % len(_DISTINCT_COLORS)]


def _wait_thumbs_loaded(editor):
    """等待侧栏缩略图懒加载队列为空（不使用固定 sleep）。"""
    _wait_until(
        lambda: not editor.sidebar._thumb_queue and not editor.sidebar._thumb_queued,
        message="侧栏缩略图懒加载队列未清空",
    )
    QTest.qWait(20)


def _cached_thumb_for(editor, filename):
    """按文件名从侧栏 LRU 缓存取缩略图（缓存键为 (文件名, 顶点签名)）。"""
    for key, pixmap in editor.sidebar._thumb_cache.items():
        if isinstance(key, tuple) and key[0] == filename:
            return pixmap
    return None


def _select_scroll_action(editor):
    """切到 scroll 动作（动作表单随产品逻辑显隐，测量按钮可见）。"""
    index = editor.action_combo.findData("scroll")
    assert index >= 0, "动作类型 'scroll' 不在 action_combo 中"
    editor.action_combo.setCurrentIndex(index)
    QTest.qWait(0)


def _start_scroll_measurement(editor, rect=(60, 300, 160, 380)):
    """scroll 步真实测量入口：选 scroll -> 首图拉框 -> 点“开始测量滚动”。"""
    _select_scroll_action(editor)
    # scroll 属于坐标动作：首图必须先拉参照物框（产品据此取首参照物 Y）
    editor.canvas.rect_drawn.emit(int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
    QTest.qWait(0)
    # offscreen 下顶层窗口未映射，isVisible() 恒为 False；用 isHidden() 判控件显隐
    assert not editor.btn_scroll_measure.isHidden(), "scroll 测量按钮应当可见"
    editor.btn_scroll_measure.click()
    QTest.qWait(0)
    assert editor._scroll_measuring is True, "点击开始测量后未进入 scroll 测量态"
    assert editor._scroll_preserve_screenshot is True


def _capture_extra_for_scroll(editor, ref_rect):
    """测量期间“滚动后重新截图 + 同参照物拉框”：产出 1 张 extra 并登记参照物。"""
    n_before = len(editor._scroll_extra_screenshots)
    capture(editor)
    assert len(editor._scroll_extra_screenshots) == n_before + 1, (
        "测量期间截图应被登记为 extra（不占当前步）"
    )
    extra_path = editor._scroll_extra_screenshots[-1]
    assert os.path.isfile(extra_path), f"extra 截图未落盘：{extra_path}"
    # 拉框走测量分支：只登记参照物 Y，不改当前步截图引用/vertices
    editor.canvas.rect_drawn.emit(
        int(ref_rect[0]), int(ref_rect[1]), int(ref_rect[2]), int(ref_rect[3])
    )
    QTest.qWait(0)
    return extra_path


# ----------------------------------------------------------------------
# 6.1 历史步重新截图：序号不变、内容更新、旁步不受影响、缩略图反映新图
# ----------------------------------------------------------------------

def test_recapture_shortcut_ctrl_r(editor_factory, monkeypatch):
    """Ctrl+R 经 keyPressEvent 触发 recapture_current_step。"""
    from PyQt5.QtCore import Qt
    import annotation_editor as ae

    calls = []
    monkeypatch.setattr(ae.AnnotationEditor, "recapture_current_step",
                        lambda self: calls.append(1))
    editor = editor_factory()
    QTest.keyClick(editor, Qt.Key_R, Qt.ControlModifier)
    assert calls == [1], "Ctrl+R 未触发 recapture_current_step"


def test_recapture_history_step_keeps_number_updates_content(editor, qapp):
    """display_step 回历史步后走真实“截图”入口重新截图（替换截图分支）。"""
    walk_steps(editor, 3, action="click")

    # 回到第 2 步（index=1）
    editor.display_step(1)
    assert editor.current_step == 1

    target = editor.steps_data[1]
    target_name = target["screenshot"]
    target_path = target["screenshot_filepath"]
    assert target_name == "gui_000001_0002.png", f"第 2 步文件名异常：{target_name}"

    other_names = [editor.steps_data[i]["screenshot"] for i in (0, 2)]
    other_idxs = [
        editor.screen_capture.classify(editor.steps_data[i]["screenshot_filepath"])
        for i in (0, 2)
    ]
    old_idx = editor.screen_capture.classify(target_path)
    assert old_idx == 1, f"替换前第 2 步图应反查截图序号 1，实际 {old_idx}"

    # 让侧栏缩略图懒加载完成，拿到替换前旧缩略图像素
    _wait_thumbs_loaded(editor)
    old_thumb_pixel = _pix_top_center_rgb(
        editor.sidebar.item_widgets[1].thumb_label.pixmap()
    )
    assert old_thumb_pixel == _expected_color(old_idx)
    assert _cached_thumb_for(editor, target_name) is not None, (
        "替换前缩略图应已被 LRU 缓存"
    )

    # ---- 走真实“重新截图”入口：历史步已有 _current_screenshot_filepath，
    #      take_screenshot 置 _replacing_screenshot，_do_screenshot 原地覆盖 ----
    calls_before = editor.screen_capture.call_count
    new_name = capture(editor)
    assert editor.screen_capture.call_count == calls_before + 1
    new_idx = calls_before  # 第 N 次成功截图（0-based）

    # 文件名/序号保持不变
    assert new_name == target_name == "gui_000001_0002.png"
    assert editor._current_screenshot_filename == target_name
    assert editor._current_screenshot_filepath == target_path

    # 磁盘内容已更新为新截图（同路径读回底色变为新序号底色）
    assert editor.screen_capture.classify(target_path) == new_idx
    assert new_idx > old_idx

    # 画布显示的是新截图
    canvas_pm = editor.canvas.pixmap
    assert canvas_pm is not None and not canvas_pm.isNull()
    assert _pix_top_center_rgb(canvas_pm) == _expected_color(new_idx)

    # steps_data 引用文件名/路径不变（重新截图不重建条目）
    assert editor.steps_data[1]["screenshot"] == target_name
    assert editor.steps_data[1]["screenshot_filepath"] == target_path

    # 草稿落盘后引用仍是原文件名
    editor._write_draft_now()
    draft = DataManager.load_draft_from_dir(editor.gui_dir)
    draft_names = [s.get("screenshot") for s in draft.get("steps_data", [])]
    assert draft_names == [editor.steps_data[i]["screenshot"] for i in range(3)]
    assert draft_names[1] == target_name

    # 其他两步磁盘内容未变
    for pos, i in enumerate((0, 2)):
        assert editor.steps_data[i]["screenshot"] == other_names[pos]
        assert (
            editor.screen_capture.classify(editor.steps_data[i]["screenshot_filepath"])
            == other_idxs[pos]
        )

    # 磁盘没有多出新序号文件，也没有 .tmp 残留
    pngs = _strict_png_names(editor.gui_dir)
    assert pngs == {editor.steps_data[i]["screenshot"] for i in range(3)}
    leftovers = [f for f in os.listdir(editor.gui_dir) if f.endswith(".tmp")]
    assert leftovers == [], f"覆盖后残留临时文件：{leftovers}"

    # ---- 侧栏缩略图：D 类疑点（缓存未失效显旧图）----
    # 产品在覆盖成功后按文件名移除 LRU 缓存并主动走 ensure_current_thumb
    # 重新加载当前步缩略图，因此这里不固化“缓存此刻必须为空”的时序断言
    # （异步重载可能已把新图放回缓存）；真正的不变量是“显示的缩略图反映新图”
    editor.sidebar.ensure_current_thumb()
    _wait_thumbs_loaded(editor)
    new_thumb_pm = editor.sidebar.item_widgets[1].thumb_label.pixmap()
    assert new_thumb_pm is not None and not new_thumb_pm.isNull()
    assert _pix_top_center_rgb(new_thumb_pm) == _expected_color(new_idx), (
        f"刷新后侧栏缩略图仍为旧内容：{_pix_top_center_rgb(new_thumb_pm)} "
        f"!= {_expected_color(new_idx)}"
    )
    # 重载完成后若缓存重新填充，其内容也必须是新图而非旧图
    cached_pm = _cached_thumb_for(editor, target_name)
    if cached_pm is not None:
        assert _pix_top_center_rgb(cached_pm) == _expected_color(new_idx), (
            "缩略图缓存中仍是旧内容"
        )

    assert_all(editor)


# ----------------------------------------------------------------------
# 6.2 scroll extra 清理与序号回收（D-5）
# ----------------------------------------------------------------------

def test_scroll_extra_cleanup_number_reuse_D5(editor, qapp):
    """scroll 测量 extra：取消路径 + 真实完成路径均清理，随后序号回收、引用唯一。"""
    # ================= 阶段 A：取消路径 =================
    walk_steps(editor, 1, action="click")

    # 第 2 步：scroll，进入真实测量并产出 2 张 extra
    capture(editor)
    first_name = editor._current_screenshot_filename
    first_path = editor._current_screenshot_filepath
    first_idx = editor.screen_capture.classify(first_path)
    assert first_name == "gui_000001_0002.png"

    _start_scroll_measurement(editor)
    calls_after_first = editor.screen_capture.call_count

    extra1 = _capture_extra_for_scroll(editor, (60, 260, 160, 340))
    extra2 = _capture_extra_for_scroll(editor, (60, 220, 160, 300))
    assert os.path.basename(extra1) == "gui_000001_0003.png"
    assert os.path.basename(extra2) == "gui_000001_0004.png"
    # extra 不占当前步：当前步仍引用首图，首图未被顶替/覆盖
    assert editor._current_screenshot_filename == first_name
    assert editor.screen_capture.classify(first_path) == first_idx

    pngs_during = _strict_png_names(editor.gui_dir)
    assert {os.path.basename(extra1), os.path.basename(extra2)} <= pngs_during

    # ---- 真实取消入口 ----
    editor._cancel_scroll_measurement()

    # extra 文件已删除、列表清空、测量标记复位
    assert not os.path.exists(extra1), "取消测量后 extra1 仍残留磁盘"
    assert not os.path.exists(extra2), "取消测量后 extra2 仍残留磁盘"
    assert editor._scroll_extra_screenshots == []
    assert_measurement_state_reset(editor)
    # 首图内容/引用不变，画布恢复首图
    assert editor._current_screenshot_filename == first_name
    assert editor.screen_capture.classify(first_path) == first_idx
    assert editor.canvas.pixmap is not None and not editor.canvas.pixmap.isNull()

    # 取消会清空 pixels_input；按真实用户路径重新填像素后确认 scroll 步
    editor.pixels_input.setText("300")
    confirm(editor)
    assert len(editor.steps_data) == 2
    assert editor.steps_data[1]["screenshot"] == first_name

    # ---- 序号回收：磁盘 max 已回落到 0002，下一张普通截图复用 0003 ----
    next_num = editor.data_manager.get_next_screenshot_number(editor.gui_number)
    assert next_num == 3, f"extra 删除后下一个截图序号应回落到 3，实际 {next_num}"

    reused_name = capture(editor)
    reused_idx = editor.screen_capture.call_count - 1
    assert reused_name == "gui_000001_0003.png", (
        f"extra 删除后新普通截图应回收序号 0003，实际 {reused_name}"
    )
    # 新截图没有串入 extra 分支：测量标记全复位、extra 列表仍为空
    assert editor._scroll_extra_screenshots == []
    assert editor._scroll_preserve_screenshot is False
    assert editor._replacing_screenshot is False
    assert editor._current_screenshot_filename == reused_name
    reused_path = os.path.join(editor.gui_dir, reused_name)
    # 回收的是被取消 extra 用过的序号，但磁盘内容是本次新截图
    assert editor.screen_capture.classify(reused_path) == reused_idx
    assert reused_idx > calls_after_first

    fill_step(editor, action="click")
    confirm(editor)
    assert len(editor.steps_data) == 3

    # 引用唯一、无孤儿、无 tmp、命名规范
    names = [s["screenshot"] for s in editor.steps_data]
    assert len(set(names)) == len(names), f"截图引用不唯一：{names}"
    assert_disk_consistency(editor)
    leftovers = [f for f in os.listdir(editor.gui_dir) if f.endswith(".tmp")]
    assert leftovers == [], f"序号回收后残留临时文件：{leftovers}"

    # ================= 阶段 B：真实完成路径（再走一个 scroll 步）=================
    capture(editor)
    f2_name = editor._current_screenshot_filename
    f2_path = editor._current_screenshot_filepath
    f2_idx = editor.screen_capture.classify(f2_path)
    assert f2_name == "gui_000001_0004.png"

    _start_scroll_measurement(editor)
    extra3 = _capture_extra_for_scroll(editor, (60, 250, 160, 330))
    assert os.path.basename(extra3) == "gui_000001_0005.png"
    assert len(editor._scroll_references) >= 2

    # 真实“完成测量”按钮
    assert not editor.btn_scroll_finish.isHidden()
    editor.btn_scroll_finish.click()
    QTest.qWait(0)

    # 产品逻辑：完成测量同样删除全部 extra，仅保留首图作为步骤截图
    assert not os.path.exists(extra3), "完成测量后 extra3 仍残留磁盘"
    assert editor._scroll_extra_screenshots == []
    assert_measurement_state_reset(editor)
    assert editor._current_screenshot_filename == f2_name
    assert editor.screen_capture.classify(f2_path) == f2_idx
    # 累计像素已计算（参照物 Y 单调上移，diff 为负；只要求非空整数串）
    pixels_text = editor.pixels_input.text().strip()
    assert pixels_text != "", "完成测量后滚动像素未回填"
    int(pixels_text)

    confirm(editor)
    assert len(editor.steps_data) == 4
    assert editor.steps_data[3]["screenshot"] == f2_name

    # 完成路径后序号同样回收到 0005
    assert editor.data_manager.get_next_screenshot_number(editor.gui_number) == 5
    assert_disk_consistency(editor)
    assert_all(editor)

    # 目录内不应有任何 extra 命名残留或隐藏 tmp
    all_files = os.listdir(editor.gui_dir)
    assert not [f for f in all_files if f.endswith(".tmp")]
    png_final = _strict_png_names(editor.gui_dir)
    assert png_final == {s["screenshot"] for s in editor.steps_data}


# ----------------------------------------------------------------------
# 6.3 覆盖不影响其他步：全模型图-位映射单射 + 最终 JSON 引用正确
# ----------------------------------------------------------------------

def test_overwrite_does_not_affect_other_steps(editor, qapp):
    """覆盖第 2 步截图后，每步图内容与其业务位置一一对应；finish 后最终 JSON 正确。"""
    walk_steps(editor, 3, action="click")
    editor.display_step(1)

    target_name = editor.steps_data[1]["screenshot"]
    target_path = editor.steps_data[1]["screenshot_filepath"]

    # 覆盖前每步图反查 == 业务位置（截图序号 0/1/2）
    for i, step in enumerate(editor.steps_data):
        assert editor.screen_capture.classify(step["screenshot_filepath"]) == i

    # 走真实重新截图入口覆盖第 2 步
    new_capture_idx = editor.screen_capture.call_count
    capture(editor)
    # 覆盖分支会清空与旧图匹配的拉框/坐标（旧标注不能继承到新图），
    # 按真实用户路径在新图上重新拉框标注后再继续，否则结束校验将按缺填项拦截
    fill_step(editor, action="click")
    assert editor.steps_data[1]["screenshot"] == target_name
    assert editor.screen_capture.classify(target_path) == new_capture_idx

    # 覆盖后逐位核对：第 2 步为新序号，其余步仍是 0/2
    expected = [0, new_capture_idx, 2]
    for i, step in enumerate(editor.steps_data):
        idx = editor.screen_capture.classify(step["screenshot_filepath"])
        assert idx == expected[i], (
            f"覆盖后第 {i} 步图反查序号 {idx} != 预期 {expected[i]}（图-业务位置错位）"
        )

    # 文件名单射 + 磁盘无孤儿/无 tmp
    assert_model_consistency(editor)
    assert_disk_consistency(editor)
    assert not [f for f in os.listdir(editor.gui_dir) if f.endswith(".tmp")]

    # 覆盖只复用 0002：其后通过真实“插入截图”入口在末步后补一张，
    # 新截图序号应顺延为 0004（证明覆盖没有抬高/打乱序号序列）
    editor.display_step(2)
    calls_before_insert = editor.screen_capture.call_count
    editor.start_insert_capture()
    _wait_until(
        lambda: not editor._screenshot_in_progress,
        message="插入截图未在超时内完成",
    )
    QTest.qWait(40)
    assert len(editor.steps_data) == 4
    inserted_name = editor.steps_data[3]["screenshot"]
    assert inserted_name == "gui_000001_0004.png", (
        f"覆盖只复用 0002，追加截图应顺延为 0004，实际 {inserted_name}"
    )
    assert editor.screen_capture.classify(
        editor.steps_data[3]["screenshot_filepath"]
    ) == calls_before_insert

    # 最终映射：[0, 覆盖新序号, 2, 追加序号]
    expected_final = [0, new_capture_idx, 2, calls_before_insert]
    for i, step in enumerate(editor.steps_data):
        assert editor.screen_capture.classify(step["screenshot_filepath"]) == (
            expected_final[i]
        ), f"追加截图后第 {i} 步图-业务位置错位"
    assert_model_consistency(editor)
    assert_disk_consistency(editor)
    assert_all(editor)

    # ---- 结束任务：插入步（末位）直接改填 terminate 并 confirm，
    #      走真实 _finish_task；不新增截图，最终 4 张图、4 条 trajectory ----
    # conftest 对 question 默认答 Yes（会走“继续新任务”），这里临时答 No
    ctrl = editor._test_dialogs
    previous_answer = ctrl.question_result
    ctrl.question_result = QMessageBox.No
    try:
        fill_step(editor, action="terminate")
        editor.confirm_step()
        _wait_until(
            lambda: editor._draft_discarded is True,
            message="terminate 后草稿未按最终任务路径删除",
        )
    finally:
        ctrl.question_result = previous_answer

    data, coords = assert_final_json_consistency(editor, expected_rounds=1)

    # 最终 JSON trajectory 的截图顺序与业务位置严格对应
    traj_shots = [
        entry["observation"]["screenshot"]
        for entry in data["messages"][1]["trajectory"]
    ]
    assert traj_shots == [
        "gui_000001_0001.png",
        "gui_000001_0002.png",
        "gui_000001_0003.png",
        "gui_000001_0004.png",
    ], f"最终 trajectory 截图序列异常：{traj_shots}"
    assert len(coords) == 4
    assert [c["action"] for c in coords] == ["click", "click", "click", "terminate"]

    gui_dir = editor.gui_dir
    # 覆盖步（trajectory index 1）引用仍是 0002，磁盘内容为覆盖后的新图
    assert traj_shots[1] == target_name
    assert editor.screen_capture.classify(
        os.path.join(gui_dir, target_name)
    ) == new_capture_idx
    # 旁步内容未被覆盖波及
    assert editor.screen_capture.classify(
        os.path.join(gui_dir, "gui_000001_0001.png")
    ) == 0
    assert editor.screen_capture.classify(
        os.path.join(gui_dir, "gui_000001_0003.png")
    ) == 2
    assert editor.screen_capture.classify(
        os.path.join(gui_dir, "gui_000001_0004.png")
    ) == calls_before_insert
