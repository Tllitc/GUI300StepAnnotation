# -*- coding: utf-8 -*-
"""iOS 端「在原图上重新拉框」回归测试。

需求：编辑已完成任务时，只想改某一步动作的拉框，不必重现画面重新截图，
直接在**磁盘已保存的原截图**上重新拖框。

核心安全事实（本组用例的立论前提）：磁盘 PNG 存的是**无标记原始截图**，绿色标注框
是预览时由 ScreenshotCanvas.restore_vertices 按图片像素重绘的。因此「重新拉框」
只改内存中的 vertices / 坐标输入，**不写任何图片文件**，必须再点[保存修改]
（save_edited_round）才写 JSON/coords。

覆盖:
  1. 入口按钮仅在编辑态可见（正常采标态保持隐藏）
  2. 正向：重新拉框只改内存 —— PNG 逐字节不变、目录条目集合不变、gui_dir 之外零新增
  3. 写回：save_edited_round 后 JSON coordinate 与 coords vertices/center 均为新值，
     且 INV-13 未编辑轮逐字段保留
  4. 主预览画布按新框重绘（先用产品入口重建旧框基线，避免零缩放假绿）
  5. 弹窗打开即干净背景（canvas._saved_rect is None，落实「直接清空旧框」）
  6. 未拖框点[应用新框]：给提示、不关闭、不改数据
  7. 取消（reject）：vertices / 坐标输入逐字不变，磁盘零变化，引用不复位
  8. 门闩与测量态：打开弹窗即清理 swipe/scroll 测量态，结束后全套状态复位
  9. 守卫：轮次切换中 / 非编辑态 / 截图缺失态 / 截图文件不存在 —— 一律不建弹窗
 10. swipe 步只改起点框，终点 coord2_* 与写回后的 coordinate 保持原值

运行:
    cd ios端 ; python -m pytest tests/test_relabel_on_screenshot.py -q
"""

import json
import os

from PyQt5.QtCore import QRect
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QDialog

from helpers import (
    _wait_until,
    gui_dir_of,
    gui_number_from_dir,
    open_edit_mode,
    walk_rounds,
    walk_steps,
)
from invariants import (
    assert_dir_unchanged,
    assert_edit_writeback_preserved,
    assert_measurement_state_reset,
    assert_no_files_outside,
    coords_by_round,
    snapshot_dir,
    snapshot_listing,
)


# ----------------------------------------------------------------------
# 常量：FakeScreenCapture 固定产出 390x844，与 helpers.draw_rect 默认框对齐
# ----------------------------------------------------------------------

_SHOT_W, _SHOT_H = 390, 844
_OLD_RECT = [50, 200, 150, 300]          # fill_step 默认拉框 → 中心 (100, 250)
_NEW_RECT = [120, 400, 260, 520]         # 重新拉框的新框（宽高 >5px 且全在图内）
_NEW_CENTER = [190, 460]                 # (120+260)//2, (400+520)//2
_SWIPE_END = [250, 550]                  # fill_step swipe 默认 end_rect 中心


# ----------------------------------------------------------------------
# 磁盘读取助手
# ----------------------------------------------------------------------

def _names(gui_dir):
    """gui_dir 下条目名集合（含 .bak / .tmp / draft 等任何意外产物）。"""
    return set(os.listdir(gui_dir))


def _png_bytes(gui_dir):
    """gui_dir 下全部 PNG 的原始字节，用于「图片一个字节都没动」的硬断言。"""
    result = {}
    for name in sorted(os.listdir(gui_dir)):
        if name.lower().endswith(".png"):
            with open(os.path.join(gui_dir, name), "rb") as f:
                result[name] = f.read()
    return result


def _read_json(gui_dir, gui_number):
    path = os.path.join(gui_dir, f"gui_{gui_number}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_coords(gui_dir, gui_number):
    path = os.path.join(gui_dir, f"gui_{gui_number}_coords.json")
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    return loaded if isinstance(loaded, list) else (loaded.get("coords") or [])


def _trajectory(data, round_index):
    """最终 JSON 中第 round_index 轮的 trajectory（messages 严格交替）。"""
    messages = data.get("messages") or []
    idx = 2 * round_index + 1
    assert idx < len(messages), f"messages 不足以容纳第 {round_index} 轮：{len(messages)}"
    return messages[idx].get("trajectory") or []


def _coord_entry(coords, round_index, step):
    for entry in coords_by_round(coords).get(round_index, []):
        if entry.get("step") == step:
            return entry
    return None


def _draft_names(gui_dir):
    return {n for n in _names(gui_dir) if n.endswith("_draft.json")}


# ----------------------------------------------------------------------
# 现场构造助手：都走真实产品链路（采集 -> 收尾写盘 -> 载入编辑态）
# ----------------------------------------------------------------------

def _prepare_single_round(editor_factory):
    """单轮 2 步 click + terminate 收尾的已交付任务。:return (gui_dir, gui_number)

    必须走 walk_rounds 而非裸 finish_task_final：后者的 terminate 步不拉框，
    steps_data[0]["vertices"] 会是 None，重新拉框用例的前提就不成立了。
    """
    ed = editor_factory()
    gui_dir = gui_dir_of(ed)
    json_path = walk_rounds(ed, [(2, "测试指令")], finish_action="terminate")
    assert os.path.isfile(json_path), f"收尾后未写出最终 JSON：{json_path}"
    return gui_dir, gui_number_from_dir(gui_dir)


def _prepare_two_round(editor_factory):
    """双轮任务（每轮 2 步 + answer 步）：供 INV-13「未编辑轮逐字段保留」使用。"""
    ed = editor_factory()
    gui_dir = gui_dir_of(ed)
    json_path = walk_rounds(
        ed, [(2, "第一轮指令"), (2, "第二轮指令")], finish_action="terminate"
    )
    assert os.path.isfile(json_path), f"收尾后未写出最终 JSON：{json_path}"
    return gui_dir, gui_number_from_dir(gui_dir)


def _prepare_swipe_task(editor_factory):
    """单轮 2 步 swipe（含终点坐标）已交付任务。"""
    ed = editor_factory()
    gui_dir = gui_dir_of(ed)
    json_path = walk_rounds(
        ed, [(2, "测试指令", "swipe")], finish_action="terminate"
    )
    assert os.path.isfile(json_path), f"收尾后未写出最终 JSON：{json_path}"
    return gui_dir, gui_number_from_dir(gui_dir)


def _open_edit(editor_factory, gui_dir, round_index=0):
    """复用产品入口进入编辑态。

    :return: (editor, before_data, before_coords)

    `_final_data_saved = True` 是**必须**的：iOS 的 closeEvent 在
    `_edit_mode and not _final_data_saved` 时会自动静默写回，而 conftest
    teardown 统一 close()，不阻断就会在断言之后改盘，污染「零改盘」判定。
    """
    editor = editor_factory(auto_init=False)
    before_data, before_coords = open_edit_mode(editor, gui_dir, round_index=round_index)
    editor._final_data_saved = True
    return editor, before_data, before_coords


def _open_dialog(editor):
    """走真实入口 relabel_current_step 打开弹窗，返回弹窗实例。"""
    editor.relabel_current_step()
    QTest.qWait(50)
    dialog = editor._relabel_dialog
    assert dialog is not None, "relabel_current_step 未打开重新拉框弹窗"
    return dialog


def _apply_rect(editor, dialog, rect):
    """在弹窗画布上拖出新框并点[应用新框]（信号路径与鼠标拖框等价）。"""
    dialog.canvas.rect_drawn.emit(*[int(v) for v in rect])
    QTest.qWait(0)
    dialog.apply()
    QTest.qWait(0)
    return editor._current_vertices


# ----------------------------------------------------------------------
# 画布几何助手
# ----------------------------------------------------------------------

def _settle_canvas(editor, qapp):
    """建立真实窗口几何并等画布完成缩放。

    offscreen 下未 show 的窗口子控件尺寸可能为 0，使 ScreenshotCanvas._scale_pixmap
    的 ratio=0、scaled_pixmap 宽度为 0，于是 restore_vertices 还原出的矩形退化成
    零尺寸 —— 旧框与新框的 QRect 会**完全相等**，「预览已刷新」断言失去区分力。
    """
    editor.show()
    qapp.processEvents()
    canvas = editor.canvas
    _wait_until(
        lambda: canvas.scaled_pixmap is not None and canvas.scaled_pixmap.width() > 0,
        timeout_ms=2000,
        message="画布未完成缩放（scaled_pixmap 宽度为 0）",
    )
    return canvas


def _canvas_rect_for(canvas, vertices):
    """按 restore_vertices 的同一公式推算期望矩形（用画布自身的 scale/offset）。"""
    scale = canvas.scaled_pixmap.width() / canvas.pixmap.width()
    left = int(vertices[0] * scale) + canvas._offset_x
    top = int(vertices[1] * scale) + canvas._offset_y
    right = int(vertices[2] * scale) + canvas._offset_x
    bottom = int(vertices[3] * scale) + canvas._offset_y
    return QRect(left, top, right - left, bottom - top)


# ----------------------------------------------------------------------
# 1. 入口按钮显隐
# ----------------------------------------------------------------------

def test_relabel_button_only_visible_in_edit_mode(editor_factory):
    """正常采标态按钮隐藏（hide()），仅在载入已完成任务后可见。

    offscreen 下顶层窗口未映射，isVisible() 恒 False，故一律用 isHidden() 判显隐。
    """
    ed = editor_factory()
    assert ed.btn_relabel.isHidden(), "正常采标态下[在原图上重新拉框]不应可见"

    gui_dir, _ = _prepare_single_round(editor_factory)
    editor, _, _ = _open_edit(editor_factory, gui_dir)
    assert not editor.btn_relabel.isHidden(), "编辑态下[在原图上重新拉框]应显示"


# ----------------------------------------------------------------------
# 2. 正向：只改内存，不写任何图片文件
# ----------------------------------------------------------------------

def test_relabel_updates_vertices_only(editor_factory):
    gui_dir, gui_number = _prepare_single_round(editor_factory)
    editor, _, _ = _open_edit(editor_factory, gui_dir)
    assert editor._current_vertices == _OLD_RECT, (
        "前提失真：编辑现场未还原出旧框"
    )
    filename_before = editor.steps_data[0]["screenshot"]

    dir_snapshot = snapshot_dir(gui_dir)
    names_before = _names(gui_dir)
    pngs_before = _png_bytes(gui_dir)
    parent_listing = snapshot_listing(os.path.dirname(gui_dir))

    dialog = _open_dialog(editor)
    _apply_rect(editor, dialog, _NEW_RECT)

    # 内存态更新
    assert editor._current_vertices == _NEW_RECT
    assert editor.steps_data[0]["vertices"] == _NEW_RECT, "重新拉框未落 steps_data"
    assert editor.steps_data[0]["screenshot"] == filename_before, "截图文件名被改写"
    assert editor.coord_x_input.text() == str(_NEW_CENTER[0])
    assert editor.coord_y_input.text() == str(_NEW_CENTER[1])
    assert editor._relabel_dialog is None, "apply 路径未复位弹窗引用"
    status = editor.status_label.text()
    assert "已在原图上重新拉框" in status, f"状态栏未提示重新拉框结果：{status}"
    assert "请点击[保存修改]写回" in status, f"状态栏未提示需再保存：{status}"

    # 磁盘零变化：PNG 逐字节相同 + 目录条目集合等值 + gui_dir 之外零新增
    assert _png_bytes(gui_dir) == pngs_before, "重新拉框改写了 PNG 文件内容"
    assert _names(gui_dir) == names_before, (
        f"重新拉框产生了意外文件：{sorted(_names(gui_dir) ^ names_before)}"
    )
    assert_dir_unchanged(gui_dir, dir_snapshot)
    assert not _draft_names(gui_dir), "编辑模式不应产生 draft 文件"
    assert_no_files_outside(os.path.dirname(gui_dir), parent_listing)

    # 未写回：JSON/coords 仍是采集时的原值
    entry = _coord_entry(_read_coords(gui_dir, gui_number), 0, 0)
    assert entry["center"] == [100, 250], "未点[保存修改]却已改 coords"


# ----------------------------------------------------------------------
# 3. 写回 JSON / coords
# ----------------------------------------------------------------------

def test_relabel_writeback_to_json_and_coords(editor_factory):
    gui_dir, gui_number = _prepare_two_round(editor_factory)
    editor, before_data, before_coords = _open_edit(editor_factory, gui_dir)
    pngs_before = _png_bytes(gui_dir)
    names_before = _names(gui_dir)
    assert not os.path.isfile(
        os.path.join(gui_dir, f"gui_{gui_number}.json.bak")
    ), "前提失真：写回前不应已存在 .bak"

    dialog = _open_dialog(editor)
    _apply_rect(editor, dialog, _NEW_RECT)

    assert editor.save_edited_round(silent=True) is True, "编辑写回失败"

    # 写回只新增 .bak（安全网），不新增 PNG、不留 .tmp
    assert _names(gui_dir) - names_before == {f"gui_{gui_number}.json.bak"}, (
        f"写回产生了预期外文件：{sorted(_names(gui_dir) - names_before)}"
    )
    assert _png_bytes(gui_dir) == pngs_before, "写回改写了 PNG 文件内容"
    assert not {n for n in _names(gui_dir) if n.endswith(".tmp")}, "残留 .tmp 文件"

    # JSON：被编辑轮第 1 步坐标为新中心，其余步保持原值
    traj = _trajectory(_read_json(gui_dir, gui_number), 0)
    assert traj[0]["actions"][0]["coordinate"] == _NEW_CENTER, "JSON 坐标未写回新值"
    assert traj[0]["observation"]["screenshot"] == editor.steps_data[0]["screenshot"]
    assert traj[1]["actions"][0]["coordinate"] == [100, 250], "未操作的步骤坐标被误改"

    # coords：vertices 与 center 均为新值
    entry = _coord_entry(_read_coords(gui_dir, gui_number), 0, 0)
    assert entry["vertices"] == _NEW_RECT, "coords vertices 未写回新框"
    assert entry["center"] == _NEW_CENTER, "coords center 未写回新框中心"

    # INV-13：其余轮次 / 未暴露字段原样保留
    assert_edit_writeback_preserved(
        gui_dir, gui_number, before_data, before_coords, 0
    )


# ----------------------------------------------------------------------
# 4. 主预览画布重绘
# ----------------------------------------------------------------------

def test_relabel_preview_refreshed(editor_factory, qapp):
    gui_dir, _ = _prepare_single_round(editor_factory)
    editor, _, _ = _open_edit(editor_factory, gui_dir)
    canvas = _settle_canvas(editor, qapp)

    # open_edit_mode 时窗口尚未建立真实几何，用产品入口重建旧框基线
    editor.display_step(0)
    old_baseline = canvas._saved_rect
    assert old_baseline is not None, "前提失真：主画布未还原旧标注框"
    assert old_baseline == _canvas_rect_for(canvas, _OLD_RECT)
    assert old_baseline.width() > 0, "画布缩放比为 0，断言将失去区分力"

    dialog = _open_dialog(editor)
    # 打开弹窗前 relabel_current_step 会补回旧框，保证取消时显示也原样
    assert canvas._saved_rect == old_baseline, "打开弹窗时旧框显示被破坏"

    _apply_rect(editor, dialog, _NEW_RECT)

    assert canvas._saved_rect == _canvas_rect_for(canvas, _NEW_RECT), (
        "主画布未按新框重绘"
    )
    assert canvas._saved_rect != old_baseline, "主画布仍停留在旧框"
    assert canvas._saved_rect.width() > 0 and canvas._saved_rect.height() > 0


# ----------------------------------------------------------------------
# 5. 弹窗打开即干净背景
# ----------------------------------------------------------------------

def test_relabel_dialog_opens_clean(editor_factory):
    gui_dir, _ = _prepare_single_round(editor_factory)
    editor, _, _ = _open_edit(editor_factory, gui_dir)

    dialog = _open_dialog(editor)

    # 只喂背景图，绝不 restore_vertices → 打开即无旧框（「直接清空旧框」约定）
    assert dialog.canvas._saved_rect is None, "弹窗叠加了旧标注框"
    assert dialog.canvas._current_rect is None
    assert dialog.canvas.pixmap is not None, "弹窗未加载磁盘原截图"
    assert dialog.canvas.pixmap.width() == _SHOT_W
    assert dialog.canvas.pixmap.height() == _SHOT_H
    assert dialog._rect is None
    assert not dialog.isModal(), "弹窗应为非模态（可回到主界面微调）"


# ----------------------------------------------------------------------
# 6. 未拖框就点[应用新框]
# ----------------------------------------------------------------------

def test_relabel_apply_without_rect_keeps_dialog(editor_factory):
    gui_dir, _ = _prepare_single_round(editor_factory)
    editor, _, _ = _open_edit(editor_factory, gui_dir)
    dir_snapshot = snapshot_dir(gui_dir)

    dialog = _open_dialog(editor)
    dialog.apply()
    QTest.qWait(0)

    assert dialog._rect is None
    assert dialog.result() != int(QDialog.Accepted), "无新框时不应 accept"
    assert dialog.hint_label.text(), "无新框时缺少红字提示"
    assert editor._relabel_dialog is dialog, "无新框时不应复位弹窗引用"
    assert editor._current_vertices == _OLD_RECT, "无新框点应用改动了标注数据"
    assert editor.steps_data[0]["vertices"] == _OLD_RECT
    assert_dir_unchanged(gui_dir, dir_snapshot)

    # 补拖一个框后即可正常应用
    _apply_rect(editor, dialog, _NEW_RECT)
    assert editor._current_vertices == _NEW_RECT
    assert editor._relabel_dialog is None


# ----------------------------------------------------------------------
# 7. 取消保留原框
# ----------------------------------------------------------------------

def test_relabel_cancelled_keeps_annotation(editor_factory):
    gui_dir, _ = _prepare_single_round(editor_factory)
    editor, _, _ = _open_edit(editor_factory, gui_dir)
    dir_snapshot = snapshot_dir(gui_dir)
    pngs_before = _png_bytes(gui_dir)

    dialog = _open_dialog(editor)
    # 即便在弹窗里拖了新框，只要不点[应用新框]，一切原样保留
    dialog.canvas.rect_drawn.emit(*_NEW_RECT)
    QTest.qWait(0)
    dialog.reject()
    QTest.qWait(0)

    assert editor._current_vertices == _OLD_RECT, "取消后标注框被改写"
    assert editor.steps_data[0]["vertices"] == _OLD_RECT, "取消后落表被改写"
    assert editor.coord_x_input.text() == "100", "取消后坐标输入被改写"
    assert editor.coord_y_input.text() == "250", "取消后坐标输入被改写"
    assert editor._relabel_dialog is dialog, (
        "取消路径不复位引用，由 closeEvent 兜底关闭"
    )
    assert_dir_unchanged(gui_dir, dir_snapshot)
    assert _png_bytes(gui_dir) == pngs_before


# ----------------------------------------------------------------------
# 8. 门闩与测量态复位
# ----------------------------------------------------------------------

def test_relabel_gate_released_and_state_reset(editor_factory):
    gui_dir, _ = _prepare_swipe_task(editor_factory)
    editor, _, _ = _open_edit(editor_factory, gui_dir)
    assert editor._screenshot_in_progress is False

    # 人为进入 swipe 测量态：重新拉框必须先清理，避免拖框被当成滑动终点
    editor._swipe_measuring = True
    editor._swipe_start_vertices = [60, 70, 80, 90]

    dialog = _open_dialog(editor)
    assert editor._swipe_measuring is False, "打开弹窗未取消 swipe 测量态"
    assert editor._swipe_start_vertices is None
    assert editor._scroll_measuring is False

    _apply_rect(editor, dialog, _NEW_RECT)

    assert editor._screenshot_in_progress is False, "重新拉框泄漏了采集门闩"
    assert_measurement_state_reset(editor)
    # 复用同一门闩而非新增并行标志（DI-8 / B2 不变量）
    assert not hasattr(editor, "_relabel_in_progress"), "不应新增并行门闩标志"


# ----------------------------------------------------------------------
# 9. 守卫：四种情况都不得建弹窗
# ----------------------------------------------------------------------

def test_relabel_blocked_during_round_transition(editor_factory):
    gui_dir, _ = _prepare_single_round(editor_factory)
    editor, _, _ = _open_edit(editor_factory, gui_dir)

    editor._round_transition_pending = True
    editor.relabel_current_step()
    QTest.qWait(50)
    assert editor._relabel_dialog is None, "轮次切换中不应打开重新拉框弹窗"
    assert "轮次切换中" in editor.status_label.text()
    assert editor._screenshot_in_progress is False, "守卫早退不应占用门闩"

    # 放行后可正常打开
    editor._round_transition_pending = False
    _open_dialog(editor)


def test_relabel_requires_edit_mode(editor_factory):
    """正常采标态没有可重画的已交付步骤，入口必须静默拦截。"""
    ed = editor_factory()
    walk_steps(ed, 1)
    ed.relabel_current_step()
    QTest.qWait(50)
    assert ed._relabel_dialog is None, "非编辑态不应打开重新拉框弹窗"


def test_relabel_blocked_when_screenshot_missing(editor_factory):
    gui_dir, _ = _prepare_single_round(editor_factory)
    editor, _, _ = _open_edit(editor_factory, gui_dir)

    editor._screenshot_missing = True
    editor.relabel_current_step()
    QTest.qWait(50)
    assert editor._relabel_dialog is None, "截图缺失态不应打开弹窗"
    assert "截图缺失" in editor.status_label.text()


def test_relabel_blocked_while_screenshot_in_progress(editor_factory):
    """截图在途时静默拦截：与所有采集入口共用 _screenshot_in_progress 门闩。"""
    gui_dir, _ = _prepare_single_round(editor_factory)
    editor, _, _ = _open_edit(editor_factory, gui_dir)
    assert editor._current_vertices == _OLD_RECT, (
        "前提失真：编辑现场未还原出旧框"
    )

    editor._screenshot_in_progress = True
    try:
        editor.relabel_current_step()
        QTest.qWait(50)
        assert editor._relabel_dialog is None, "截图在途时不应打开重新拉框弹窗"
        assert editor._screenshot_in_progress is True, "早退路径复位了别人的在途门闩"
        assert editor._current_vertices == _OLD_RECT, "在途拦截仍改写了标注框"

        # 门闩释放后同一入口立即可用（不残留死锁）
        editor._screenshot_in_progress = False
        _open_dialog(editor)
    finally:
        editor._screenshot_in_progress = False


def test_relabel_missing_screenshot_file(editor_factory):
    """filename 指向不存在的 PNG 且无磁盘回退路径时，早退并提示。"""
    gui_dir, _ = _prepare_single_round(editor_factory)
    editor, _, _ = _open_edit(editor_factory, gui_dir)
    dialog_snapshot = snapshot_dir(gui_dir)

    editor._screenshot_missing = False
    editor._current_screenshot_filename = "gui_999999_9999.png"
    editor.screenshot_cache = os.path.join(gui_dir, "gui_999999_9999.png")

    editor.relabel_current_step()
    QTest.qWait(50)
    assert editor._relabel_dialog is None, "截图文件缺失时不应打开弹窗"
    assert "截图文件缺失" in editor.status_label.text()
    assert_dir_unchanged(gui_dir, dialog_snapshot)


# ----------------------------------------------------------------------
# 10. swipe 步只改起点，终点保持
# ----------------------------------------------------------------------

def test_relabel_swipe_step_keeps_coord2(editor_factory):
    gui_dir, gui_number = _prepare_swipe_task(editor_factory)
    editor, _, _ = _open_edit(editor_factory, gui_dir)
    assert editor.coord2_x_input.text() == str(_SWIPE_END[0]), (
        "前提失真：swipe 步终点未还原到 coord2_x_input"
    )
    pngs_before = _png_bytes(gui_dir)

    dialog = _open_dialog(editor)
    _apply_rect(editor, dialog, _NEW_RECT)

    assert editor._current_vertices == _NEW_RECT, "起点框未更新"
    assert editor.steps_data[0]["vertices"] == _NEW_RECT
    assert editor.coord_x_input.text() == str(_NEW_CENTER[0])
    assert editor.coord_y_input.text() == str(_NEW_CENTER[1])
    # 终点逐字不变
    assert editor.coord2_x_input.text() == str(_SWIPE_END[0])
    assert editor.coord2_y_input.text() == str(_SWIPE_END[1])
    status = editor.status_label.text()
    assert "仅更新起点" in status, f"状态栏未提示滑动/滚动只改起点：{status}"
    assert _png_bytes(gui_dir) == pngs_before

    # 写回后：起点为新值，终点仍为原值
    assert editor.save_edited_round(silent=True) is True
    act = _trajectory(_read_json(gui_dir, gui_number), 0)[0]["actions"][0]
    assert act["start_coordinate"] == _NEW_CENTER, "swipe 起点未写回新值"
    assert act["coordinate"] == _SWIPE_END, "swipe 终点被误改"

    entry = _coord_entry(_read_coords(gui_dir, gui_number), 0, 0)
    assert entry["vertices"] == _NEW_RECT
    assert entry["center"] == _NEW_CENTER
    assert entry["end_center"] == _SWIPE_END, "coords 终点中心被误改"
