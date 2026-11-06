# -*- coding: utf-8 -*-
"""「在原图上重新拉框」回归测试（Windows 端）。

需求：编辑已完成任务时，若只想改某一步的动作拉框而不必重现画面重新截图，
则直接在磁盘已保存的原截图上重新拖框。

核心不变量：磁盘 PNG 存的是**无标记原始截图**，红框是预览时按物理像素重绘的
（build_marked_preview）。因此「重新拉框」只改内存中的 rect_info + 坐标输入，
**不写任何图片文件**——本文件用 snapshot_dir/assert_dir_unchanged 逐字节守住。
"""

import copy
import json
import os

from PyQt5.QtCore import QRect
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtTest import QTest

import annotation_editor as _ae
import helpers as H
import invariants as I


_SHOT_W, _SHOT_H = 1920, 1080


# ---------------------------------------------------------------------------
# 数据集构造（含真实 PNG：重新拉框守卫要求 load_screenshot 能读到磁盘原图）
# ---------------------------------------------------------------------------
def _write_png(path, rgb):
    pm = QPixmap(_SHOT_W, _SHOT_H)
    pm.fill(QColor(*rgb))
    assert pm.save(path, "PNG"), f"测试夹具写入 PNG 失败：{path}"


def _make_dataset(gui_number):
    """2 轮数据集：第 0 轮 = 单框 left_click + 双框 left_click_drag；第 1 轮 = 单框。"""
    shot1 = f"gui_{gui_number}_0001.png"
    shot2 = f"gui_{gui_number}_0002.png"
    shot3 = f"gui_{gui_number}_0003.png"

    def step(step_no, intent, shot, action):
        return {
            "step": step_no,
            "intent": intent,
            "CoT": "",
            "observation": {
                "screenshot": shot,
                "active_window": "测试App",
                "ui_tree_segment": "",
            },
            "actions": [action],
        }

    round0 = [
        step(0, "第一轮点击", shot1, {
            "action": "left_click",
            "coordinate": [200, 300],
            "element": "按钮",
            "status": "success",
        }),
        step(1, "第一轮拖拽", shot2, {
            "action": "left_click_drag",
            "start_coordinate": [25, 40],
            "coordinate": [110, 130],
            "element": "",
            "status": "success",
        }),
    ]
    round1 = [
        step(0, "第二轮点击", shot3, {
            "action": "left_click",
            "coordinate": [600, 700],
            "element": "输入框",
            "status": "success",
        }),
    ]

    data = {
        "platform": "Windows 11",
        "system": "Windows 11",
        "screen_size": [_SHOT_W, _SHOT_H],
        "task_type": "Windows-测试",
        "messages": [
            {"role": "user", "instruction": "第一轮指令"},
            {"role": "assistant", "trajectory": round0},
            {"role": "user", "instruction": "第二轮指令"},
            {"role": "assistant", "trajectory": round1},
        ],
    }

    # coords 条目带 round（4.2/B4 落轮与编辑写回都会在序列化边界注入 round）：
    # INV-13 逐字段比对未编辑轮，夹具若缺 round 则会与写回结果差一个键而假红。
    coords0 = [
        {"step": 0, "action": "left_click", "round": 0,
         "vertices": [100, 200, 300, 400], "center": [200, 300]},
        {"step": 1, "action": "left_click_drag", "round": 0,
         "start_vertices": [10, 20, 40, 60], "start_center": [25, 40],
         "end_vertices": [100, 120, 150, 180], "end_center": [110, 130]},
    ]
    coords1 = [
        {"step": 0, "action": "left_click", "round": 1,
         "vertices": [500, 600, 700, 800], "center": [600, 700]},
    ]
    return data, coords0 + coords1, [shot1, shot2, shot3]


def _prepare(editor, round_index=0):
    """写 JSON + coords + 3 张真实 PNG，再走产品入口进入编辑态。"""
    gui = editor.gui_number
    gui_dir = os.path.join(editor.data_manager.current_dir, f"gui_{gui}")
    os.makedirs(gui_dir, exist_ok=True)

    data, coords, shots = _make_dataset(gui)
    with open(os.path.join(gui_dir, f"gui_{gui}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(gui_dir, f"gui_{gui}_coords.json"), "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)
    for i, name in enumerate(shots):
        _write_png(os.path.join(gui_dir, name), ((40 * (i + 1)) % 256, 90, 130))

    before_data, before_coords = H.open_edit_mode(editor, gui_dir, round_index)
    return {
        "gui_dir": gui_dir,
        "shots": shots,
        "before_data": before_data,
        "before_coords": before_coords,
    }


def _names(gui_dir):
    return sorted(os.listdir(gui_dir))


def _bytes_of(gui_dir, name):
    with open(os.path.join(gui_dir, name), "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1. 入口可见性
# ---------------------------------------------------------------------------
def test_relabel_button_only_visible_in_edit_mode(editor_factory, dm):
    """按钮初始 hide()，仅编辑已完成任务时显示"""
    ed = editor_factory(dm=dm)
    assert ed.relabel_btn.isHidden() is True

    _prepare(ed, 0)
    assert ed.relabel_btn.isHidden() is False


# ---------------------------------------------------------------------------
# 2. 正向：只改内存标注，磁盘零变化
# ---------------------------------------------------------------------------
def test_relabel_updates_rect_only(editor):
    ctx = _prepare(editor, 0)
    gui_dir, shot1 = ctx["gui_dir"], ctx["shots"][0]

    png_before = _bytes_of(gui_dir, shot1)
    names_before = _names(gui_dir)
    snapshot = I.snapshot_dir(gui_dir)

    new_rect = (400, 300, 200, 100)
    H.relabel_rect(editor, 0, rect=new_rect, selection_type="click")

    # 弹窗背景必须是磁盘原图（而不是新抓的屏幕）
    backgrounds = H.relabel_backgrounds(editor)
    assert len(backgrounds) == 1, f"应只弹一次窗，实际 {len(backgrounds)}"
    assert backgrounds[0] is not None and not backgrounds[0].isNull(), \
        "重新拉框弹窗未拿到磁盘原图"
    assert (backgrounds[0].width(), backgrounds[0].height()) == (_SHOT_W, _SHOT_H)

    # 内存标注已更新，坐标输入 = 新框中心
    assert editor.steps[0]["rect_info"] == new_rect
    assert editor.steps[0]["selection_type"] == "click"
    assert editor.steps[0]["editor"].coord_x_input.text() == "500"
    assert editor.steps[0]["editor"].coord_y_input.text() == "350"
    # 旧快照被丢弃，写回走实时 editor.get_data()
    assert "data" not in editor.steps[0]

    # 磁盘零变化：PNG 字节完全不变、无新增/删除文件、无 .tmp、无 draft
    assert _bytes_of(gui_dir, shot1) == png_before, "原截图 PNG 被改写"
    assert _names(gui_dir) == names_before, \
        f"目录文件集合变了：{names_before} → {_names(gui_dir)}"
    I.assert_dir_unchanged(gui_dir, snapshot)
    assert not [n for n in names_before if n.endswith(".tmp")], "残留 .tmp 文件"
    assert not [n for n in _names(gui_dir) if "draft" in n], "编辑模式产出了 draft"
    assert editor.data_manager.load_draft(editor.gui_number) is None

    # 未点「保存修改」前，最终 JSON / coords 仍是原值
    assert H.read_final_json(editor) == ctx["before_data"]
    assert H.read_final_coords(editor) == ctx["before_coords"]

    assert "已在原图上重新拉框" in editor.status_label.text()


# ---------------------------------------------------------------------------
# 3. 写回：save_edited_round 后 JSON / coords 带出新坐标
# ---------------------------------------------------------------------------
def test_relabel_writeback_to_json_and_coords(editor, monkeypatch):
    ctx = _prepare(editor, 0)
    gui_dir = ctx["gui_dir"]

    # ValidationFailDialog.exec_() 是模态阻塞，测试中替换为立即返回（防挂死）
    monkeypatch.setattr(_ae.ValidationFailDialog, "exec_", lambda self: 0)

    new_rect = (400, 300, 200, 100)
    H.relabel_rect(editor, 0, rect=new_rect, selection_type="click")
    assert editor.save_edited_round(silent=True) is True

    saved_coords = H.read_final_coords(editor)
    step0 = [e for e in saved_coords if e.get("round") == 0 and e.get("step") == 0]
    assert len(step0) == 1, f"第 0 轮 step0 坐标条目异常：{saved_coords}"
    assert step0[0]["vertices"] == [400, 300, 600, 400]
    assert step0[0]["center"] == [500, 350]

    saved = H.read_final_json(editor)
    action0 = saved["messages"][1]["trajectory"][0]["actions"][0]
    assert action0["coordinate"] == [500, 350]
    # 未暴露字段与其它轮次原样保留（INV-13）
    assert action0["status"] == "success"
    assert action0["element"] == "按钮"
    I.assert_edit_writeback_preserved(
        gui_dir, editor.gui_number,
        ctx["before_data"], ctx["before_coords"], 0
    )
    # 写回只动 JSON/coords/.bak，绝不动 PNG
    assert set(_names(gui_dir)) - {
        f"gui_{editor.gui_number}.json",
        f"gui_{editor.gui_number}_coords.json",
        f"gui_{editor.gui_number}.json.bak",
    } == set(ctx["shots"])


# ---------------------------------------------------------------------------
# 4. 预览已按新框从磁盘原图重绘
# ---------------------------------------------------------------------------
def test_relabel_preview_refreshed(editor):
    ctx = _prepare(editor, 0)
    shot1 = ctx["shots"][0]
    editor.show()
    QTest.qWait(100)

    new_rect = (300, 200, 400, 250)
    H.relabel_rect(editor, 0, rect=new_rect, selection_type="click")

    step_editor = editor.steps[0]["editor"]
    assert step_editor.preview_meta == (shot1, new_rect, "click")
    pixmap = step_editor.screenshot_label.pixmap()
    assert pixmap is not None and not pixmap.isNull(), "预览未重建"


# ---------------------------------------------------------------------------
# 5. 双框 → 自动切「拖拽」并归一化 selection_type
# ---------------------------------------------------------------------------
def test_relabel_dual_box_switches_to_drag(editor):
    _prepare(editor, 0)

    first = (200, 150, 80, 60)
    second = (700, 600, 120, 90)
    H.relabel_drag(editor, 0, first=first, second=second)

    assert editor.steps[0]["rect_info"] == (first, second)
    assert editor.steps[0]["selection_type"] == "drag"
    step_editor = editor.steps[0]["editor"]
    assert step_editor.action_type_combo.currentText() == "拖拽"
    assert step_editor.coord_x_input.text() == "240"
    assert step_editor.coord_y_input.text() == "180"
    assert step_editor.end_coord_x_input.text() == "760"
    assert step_editor.end_coord_y_input.text() == "645"


# ---------------------------------------------------------------------------
# 6. 门闩复位与瞬态收敛
# ---------------------------------------------------------------------------
def test_relabel_gate_released_and_state_reset(editor):
    _prepare(editor, 0)
    editor.show()
    QTest.qWait(100)

    H.relabel_rect(editor, 0, rect=(400, 300, 200, 100))

    assert editor._capture_in_flight is False
    assert editor.relabel_window is None
    assert editor._relabel_step_index is None
    I.assert_transient_reset(editor)


# ---------------------------------------------------------------------------
# 7. 负向：取消 → 标注逐字不变、零写盘
# ---------------------------------------------------------------------------
def test_relabel_cancelled_keeps_annotation(editor):
    ctx = _prepare(editor, 0)
    gui_dir = ctx["gui_dir"]
    snapshot = I.snapshot_dir(gui_dir)

    rect_before = copy.deepcopy(editor.steps[0]["rect_info"])
    type_before = editor.steps[0]["selection_type"]
    ed0 = editor.steps[0]["editor"]
    text_before = (ed0.coord_x_input.text(), ed0.coord_y_input.text())

    H.relabel_cancelled(editor, 0)

    assert editor.steps[0]["rect_info"] == rect_before
    assert editor.steps[0]["selection_type"] == type_before
    assert (ed0.coord_x_input.text(), ed0.coord_y_input.text()) == text_before
    I.assert_dir_unchanged(gui_dir, snapshot)
    assert editor._capture_in_flight is False
    assert "重新拉框已取消" in editor.status_label.text()


# ---------------------------------------------------------------------------
# 8. 负向：空选区绝不误判为「全屏截图」
# ---------------------------------------------------------------------------
def test_relabel_empty_selection_never_becomes_fullscreen(editor):
    _prepare(editor, 0)

    rect_before = copy.deepcopy(editor.steps[0]["rect_info"])
    editor._capture_in_flight = True
    editor._relabel_step_index = 0
    # 直接模拟弹窗在空选区下发出的信号（背景模式改发 cancelled，这里用最坏值兜底）
    editor.on_relabel_completed(None, None, (), "fullscreen")

    assert editor._capture_in_flight is False, "空选区路径泄漏门闩"
    assert editor._relabel_step_index is None
    assert editor.steps[0]["rect_info"] == rect_before
    assert editor.steps[0]["selection_type"] != "fullscreen"
    assert "重新拉框已取消" in editor.status_label.text()


def test_background_mode_empty_selection_emits_cancelled(qapp):
    """W1 单元：背景图模式下空选区 confirm 发 cancelled，而不是 fullscreen"""
    from screenshot_capture import ScreenshotCaptureWindow

    pm = QPixmap(_SHOT_W, _SHOT_H)
    pm.fill(QColor(30, 60, 90))
    win = ScreenshotCaptureWindow(background_pixmap=pm)
    try:
        got = []
        win.capture_completed.connect(lambda o, m, r, t: got.append((r, t)))
        win.confirm_selection()
        assert got == [((), "cancelled")], f"背景模式空选区未取消：{got}"
    finally:
        win.close()
        win.deleteLater()


# ---------------------------------------------------------------------------
# 9. 负向：轮次切换中早退
# ---------------------------------------------------------------------------
def test_relabel_blocked_during_round_transition(editor):
    _prepare(editor, 0)
    H.get_fake_cls(editor).reset_prepare()

    rect_before = copy.deepcopy(editor.steps[0]["rect_info"])
    editor._round_transition_pending = True
    try:
        editor.relabel_current_step()
        QTest.qWait(100)
    finally:
        editor._round_transition_pending = False

    assert editor.relabel_window is None, "轮次切换中仍创建了弹窗"
    assert H.relabel_backgrounds(editor) == []
    assert editor._capture_in_flight is False
    assert editor.steps[0]["rect_info"] == rect_before
    assert "轮次切换中" in editor.status_label.text()


# ---------------------------------------------------------------------------
# 10. 负向：截图文件缺失早退
# ---------------------------------------------------------------------------
def test_relabel_missing_screenshot_file(editor):
    _prepare(editor, 0)
    H.get_fake_cls(editor).reset_prepare()

    rect_before = copy.deepcopy(editor.steps[0]["rect_info"])
    editor.steps[0]["screenshot_filename"] = f"gui_{editor.gui_number}_9999.png"
    editor.relabel_current_step()
    QTest.qWait(100)

    assert editor.relabel_window is None, "截图缺失仍创建了弹窗"
    assert H.relabel_backgrounds(editor) == []
    assert editor._capture_in_flight is False
    assert editor.steps[0]["rect_info"] == rect_before
    assert "截图文件缺失" in editor.status_label.text()


def test_relabel_requires_edit_mode(editor_factory, dm):
    """非编辑态（正常采标）点按钮不应弹窗"""
    ed = editor_factory(dm=dm)
    H.get_fake_cls(ed).reset_prepare()
    ed.relabel_current_step()
    QTest.qWait(100)
    assert ed.relabel_window is None
    assert H.relabel_backgrounds(ed) == []
    assert ed._capture_in_flight is False


# ---------------------------------------------------------------------------
# 10.1 负向：采集在途时静默拦截（DI-8/B2 共用门闩）
# ---------------------------------------------------------------------------
def test_relabel_blocked_while_capture_in_flight(editor):
    """截图在途时不弹窗，且早退路径不得复位他人在途的门闩"""
    _prepare(editor, 0)
    H.get_fake_cls(editor).reset_prepare()

    rect_before = copy.deepcopy(editor.steps[0]["rect_info"])
    editor._capture_in_flight = True
    try:
        editor.relabel_current_step()
        QTest.qWait(100)

        assert editor.relabel_window is None, "采集在途时仍创建了弹窗"
        assert H.relabel_backgrounds(editor) == []
        assert editor._capture_in_flight is True, "早退路径复位了别人的在途门闩"
        assert editor.steps[0]["rect_info"] == rect_before

        # 门闩释放后同一入口立即可用（不残留死锁）
        editor._capture_in_flight = False
        H.relabel_rect(editor, 0, rect=(400, 300, 200, 100))
    finally:
        editor._capture_in_flight = False

    assert editor.steps[0]["rect_info"] == (400, 300, 200, 100)
    assert editor._capture_in_flight is False


# ---------------------------------------------------------------------------
# 11. 拖拽步只重画起点框，终点坐标保持原值
# ---------------------------------------------------------------------------
def test_relabel_drag_step_keeps_end_coordinate(editor):
    ctx = _prepare(editor, 0)
    gui_dir = ctx["gui_dir"]
    snapshot = I.snapshot_dir(gui_dir)

    step_editor = editor.steps[1]["editor"]
    assert step_editor.end_coord_x_input.text() == "110"
    assert step_editor.end_coord_y_input.text() == "130"

    H.relabel_rect(editor, 1, rect=(600, 400, 100, 80), selection_type="click")

    assert editor.steps[1]["rect_info"] == (600, 400, 100, 80)
    assert step_editor.coord_x_input.text() == "650"
    assert step_editor.coord_y_input.text() == "440"
    # 终点保持原值，状态栏明确提示
    assert step_editor.end_coord_x_input.text() == "110"
    assert step_editor.end_coord_y_input.text() == "130"
    I.assert_dir_unchanged(gui_dir, snapshot)


# ---------------------------------------------------------------------------
# 12. W1 单元：背景图模式的几何与坐标口径
# ---------------------------------------------------------------------------
def test_background_mode_geometry_and_scale_factor(qapp):
    """窗口尺寸严格等于缩放显示图，scale_factor 把显示坐标反算回原图像素"""
    from screenshot_capture import ScreenshotCaptureWindow

    pm = QPixmap(_SHOT_W, _SHOT_H)
    pm.fill(QColor(30, 60, 90))
    win = ScreenshotCaptureWindow(background_pixmap=pm)
    try:
        assert win.background_pixmap is pm
        assert win.full_pixmap is not None and not win.full_pixmap.isNull()
        assert win.width() == win.full_pixmap.width()
        assert win.height() == win.full_pixmap.height()
        # 逻辑坐标系与显示图一致，offset 恒为 0
        assert win.screen_geometry.x() == 0
        assert win.screen_geometry.y() == 0
        assert (win.screen_geometry.width(), win.screen_geometry.height()) == \
               (win.full_pixmap.width(), win.full_pixmap.height())
        # 显示图不得放大超过原图
        assert win.full_pixmap.width() <= _SHOT_W
        assert abs(win.full_pixmap.width() * win.scale_factor - _SHOT_W) < 1.0

        display_rect = (100, 80, 200, 150)
        win.handle_selection(QRect(*display_rect), "drag")
        got = []
        win.capture_completed.connect(
            lambda o, m, r, t: got.append((o, m, r, t))
        )
        win.confirm_selection()

        assert len(got) == 1
        orig, marked, rect_info, selection = got[0]
        sf = win.scale_factor
        assert rect_info == tuple(int(v * sf) for v in display_rect)
        assert selection == "drag"
        # 反算回原图像素后必须落在原图范围内
        assert 0 <= rect_info[0] < _SHOT_W
        assert 0 <= rect_info[1] < _SHOT_H
        assert rect_info[0] + rect_info[2] <= _SHOT_W + 1
        assert rect_info[1] + rect_info[3] <= _SHOT_H + 1
        assert orig is not None and not orig.isNull()
        assert marked is not None and not marked.isNull()
    finally:
        win.close()
        win.deleteLater()
