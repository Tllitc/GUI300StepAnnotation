# -*- coding: utf-8 -*-
"""Task5 必填项校验负向测试组

覆盖：
- 数据保真：非法数值/坐标解析返回 None、_build_action_data 整键省略
- 双源校验：wait/time、scroll pixels（0/负合法）、swipe/drag 终点与 vertices、
  click 坐标、system_button 缺选择（序列化无伪造默认键）、"abc"/NaN/Inf 不抛异常
- 防抖/缓存：补填后侧栏 ⚠ 消失与看板计数递减、QTimer 300ms 联动、
  导航/删除/插入后下标不错位、jump 同下标不静默
- 结束拦截：未确认新步计入看板且 _finish_task 被拦截、answer_terminate 对话框文案
- 重截图覆盖清旧坐标；time=1.0 / coordinate=[0,0] 旧草稿不判缺
"""
import os

from PyQt5.QtTest import QTest

import annotation_editor
from annotation_editor import ANDROID_ACTIONS, AnnotationEditor
from helpers import (capture_and_wait, confirm_n_steps, fill_valid_step,
                     flush_events)


def _missing_text(editor):
    return editor.sidebar.missing_count_label.text()


def _set_action(editor, action):
    idx = editor.action_combo.findData(action)
    assert idx >= 0
    editor.action_combo.setCurrentIndex(idx)


# ---------- Task1：数据保真（纯解析 / 序列化，无截图） ----------

def test_parse_number_and_coordinate_invalid_return_none(editor_factory):
    editor = editor_factory()
    for bad in ("", "   ", "abc", "nan", "NaN", "inf", "-Inf", "1e9999"):
        assert AnnotationEditor._parse_number(bad) is None, f"非法输入未返回 None: {bad!r}"
    assert AnnotationEditor._parse_number("0") == 0.0
    assert AnnotationEditor._parse_number("-1.5") == -1.5

    editor.coord_x_input.setText("abc")
    editor.coord_y_input.setText("10")
    assert editor._read_coordinate(editor.coord_x_input, editor.coord_y_input) is None
    editor.coord_x_input.setText("")
    editor.coord_y_input.setText("")
    assert editor._read_coordinate(editor.coord_x_input, editor.coord_y_input) is None
    editor.coord_x_input.setText("0")
    editor.coord_y_input.setText("0")
    assert editor._read_coordinate(editor.coord_x_input,
                                   editor.coord_y_input) == [0, 0]


def test_build_action_data_omits_invalid_keys(editor_factory):
    editor = editor_factory()

    _set_action(editor, "click")
    editor._current_vertices = None
    editor.coord_x_input.setText("abc")
    editor.coord_y_input.setText("")
    data = editor._build_action_data()
    assert "coordinate" not in data
    assert data["action"] == "click" and data["element"] == ""

    _set_action(editor, "scroll")
    editor.pixels_input.setText("abc")
    data = editor._build_action_data()
    assert "pixels" not in data and "coordinate" not in data
    editor.pixels_input.setText("-120")
    editor.coord_x_input.setText("0")
    editor.coord_y_input.setText("0")
    data = editor._build_action_data()
    assert data["pixels"] == -120 and data["coordinate"] == [0, 0]

    _set_action(editor, "wait")
    for bad in ("", "nan", "inf"):
        editor.time_input.setText(bad)
        assert "time" not in editor._build_action_data(), f"{bad!r} 不应写入 time"

    _set_action(editor, "swipe")
    editor.coord_x_input.setText("abc")
    editor.coord_y_input.setText("1")
    editor.coord2_x_input.setText("2")
    editor.coord2_y_input.setText("xyz")
    data = editor._build_action_data()
    assert "start_coordinate" not in data and "coordinate" not in data

    # answer_terminate 落盘序列化为 answer
    _set_action(editor, "answer_terminate")
    editor.text_input.setText("结束回答")
    data = editor._build_action_data()
    assert data["action"] == "answer" and data["status"] == "success"
    assert data["text"] == "结束回答"


# ---------- vertices 有限数守卫（含 iOS 嵌套形态） ----------

def test_valid_vertices_requires_four_finite_numbers():
    assert AnnotationEditor._valid_vertices([0, 0, 0, 0]) == [0, 0, 0, 0]
    assert AnnotationEditor._valid_vertices([1, 2, 3, -4]) == [1, 2, 3, -4]
    # iOS 嵌套四点：取首点与第三点展平
    assert AnnotationEditor._valid_vertices(
        [[1, 2], [3, 4], [5, 6], [7, 8]]) == [1, 2, 5, 6]
    # 长度不足 / 含非有限数 / 字符串
    assert AnnotationEditor._valid_vertices([1, 2, 3]) is None
    assert AnnotationEditor._valid_vertices([1, 2, 3, "x"]) is None
    assert AnnotationEditor._valid_vertices([1, 2, 3, float("nan")]) is None
    assert AnnotationEditor._valid_vertices([1, 2, 3, float("inf")]) is None
    assert AnnotationEditor._valid_vertices([True, 2, 3, 4]) is None
    # 嵌套形态中任一点畸形也不接受
    assert AnnotationEditor._valid_vertices(
        [[1, 2], [3, 4], [5, "x"], [7, 8]]) is None
    assert AnnotationEditor._valid_coord_pair(["x", 1]) is None
    assert AnnotationEditor._valid_coord_pair([0, float("-inf")]) is None


# ---------- live 源：wait/time ----------

def test_live_wait_time_missing_and_garbage(editor_factory):
    editor = editor_factory()
    capture_and_wait(editor)
    _set_action(editor, "wait")
    flush_events()

    editor.time_input.setText("")
    reasons = editor.validate_step_at(editor.current_step)
    assert any("等待时间" in r for r in reasons)

    for bad in ("abc", "NaN", "inf", "-inf"):
        editor.time_input.setText(bad)
        reasons = editor.validate_step_at(editor.current_step)
        assert any("等待时间" in r for r in reasons), f"{bad!r} 应判缺且不抛异常"

    editor.time_input.setText("1.0")
    assert editor.validate_step_at(editor.current_step) == []


# ---------- live 源：scroll pixels（0/负值合法） ----------

def test_live_scroll_pixels_zero_negative_valid(editor_factory):
    editor = editor_factory()
    capture_and_wait(editor)
    _set_action(editor, "scroll")
    editor._current_vertices = [10, 20, 30, 40]
    editor.coord_x_input.setText("20")
    editor.coord_y_input.setText("30")
    editor.pixels_input.setText("")
    flush_events()

    reasons = editor.validate_step_at(editor.current_step)
    assert any("滚动像素" in r for r in reasons)

    for pixels in ("0", "-120"):
        editor.pixels_input.setText(pixels)
        assert editor.validate_step_at(editor.current_step) == [], \
            f"pixels={pixels} 是合法测量结果"


# ---------- 历史源：scroll pixels 必须为有限整数（小数/布尔判缺） ----------

def test_history_scroll_pixels_must_be_finite_integer(editor_factory):
    editor = editor_factory()
    confirm_n_steps(editor, 1)

    step = editor.steps_data[0]
    step["vertices"] = [0, 0, 10, 10]

    def reasons_for(pixels):
        step["action_data"] = {"action": "scroll", "element": "",
                               "coordinate": [0, 0], "pixels": pixels}
        return editor.validate_step_at(0)

    # 手改历史 JSON 出现小数 / 布尔（True/False 在 Python 中也是 int）/ 缺键 / 字符串：判缺
    for bad in (1.5, -1.5, True, False, None, "120"):
        reasons = reasons_for(bad)
        assert reasons, f"pixels={bad!r} 不应判为合法像素"
        assert any("滚动像素" in r for r in reasons), \
            f"pixels={bad!r} 应判缺且原因提及滚动像素"

    # pixels 键缺失（action_data 不含 pixels）同样判缺
    step["action_data"] = {"action": "scroll", "element": "",
                           "coordinate": [0, 0]}
    reasons = editor.validate_step_at(0)
    assert any("滚动像素" in r for r in reasons)

    # 0 / 正整数 / 负整数均为合法测量结果（coordinate、vertices 已齐全）
    for good in (0, 120, -120):
        assert reasons_for(good) == [], f"pixels={good} 是合法测量结果"


# ---------- live/历史双源：swipe/drag 终点与 vertices ----------

def test_swipe_drag_endpoints_and_vertices(editor_factory):
    editor = editor_factory()
    capture_and_wait(editor)
    _set_action(editor, "swipe")
    editor._current_vertices = [0, 0, 100, 200]
    editor.coord_x_input.setText("10")
    editor.coord_y_input.setText("20")
    editor.coord2_x_input.clear()
    editor.coord2_y_input.clear()
    flush_events()

    reasons = editor.validate_step_at(editor.current_step)
    assert any("终点坐标" in r for r in reasons)
    assert not any("起点坐标" in r for r in reasons)

    # vertices 非 4 有限数也要判缺（坐标齐全也不能放行）
    editor.coord2_x_input.setText("30")
    editor.coord2_y_input.setText("40")
    editor._current_vertices = [1, 2, 3]
    reasons = editor.validate_step_at(editor.current_step)
    assert any("拉框区域" in r for r in reasons)
    editor._current_vertices = [1, 2, 3, "x"]
    assert any("拉框区域" in r
               for r in editor.validate_step_at(editor.current_step))

    # 补全后 live 通过并确认，再在历史源上篡改 drag 数据
    editor._current_vertices = [0, 0, 100, 200]
    editor.confirm_step()
    flush_events(850)
    assert len(editor.steps_data) == 1

    step = editor.steps_data[0]
    step["action_data"] = {"action": "drag", "element": "",
                           "start_coordinate": [1, 2]}  # 缺终点
    step["vertices"] = [0, 0, 10, 10]
    reasons = editor.validate_step_at(0)
    assert any("终点坐标" in r for r in reasons)

    step["action_data"]["coordinate"] = "abc"   # 畸形终点
    reasons = editor.validate_step_at(0)
    assert any("终点坐标" in r for r in reasons)

    step["action_data"]["coordinate"] = [3, 4]
    step["vertices"] = [[1, 2], [3, 4], [5, "x"], [7, 8]]  # iOS 嵌套畸形
    reasons = editor.validate_step_at(0)
    assert any("拉框区域" in r for r in reasons)


# ---------- live 源：click 坐标缺失 ----------

def test_live_click_missing_coordinate(editor_factory):
    editor = editor_factory()
    capture_and_wait(editor)
    _set_action(editor, "click")
    editor._current_vertices = None
    editor.coord_x_input.clear()
    editor.coord_y_input.clear()
    flush_events()

    reasons = editor.validate_step_at(editor.current_step)
    assert any("坐标" in r for r in reasons)
    assert any("拉框区域" in r for r in reasons)

    editor._current_vertices = [0, 0, 10, 10]
    editor.coord_x_input.setText("5")
    editor.coord_y_input.setText("5")
    assert editor.validate_step_at(editor.current_step) == []


# ---------- system_button：数据态缺选择判缺且不伪造默认键 ----------

def test_system_button_history_missing_and_no_forged_keys(editor_factory):
    editor = editor_factory()
    confirm_n_steps(editor, 2)
    assert editor.current_step == 2

    # 历史源：篡改第 2 步为 system_button 但无 buttons
    editor.steps_data[1]["action_data"] = {"action": "system_button",
                                           "element": ""}
    reasons = editor.validate_step_at(1)
    assert any("系统按钮" in r for r in reasons)

    # coords 导出对畸形/缺键数据不产生坐标字段、不抛异常
    entry = editor._build_coords_entry(editor.steps_data[1]["action_data"],
                                       editor.steps_data[1].get("vertices"))
    assert entry["action"] == "system_button"
    assert "vertices" not in entry and "center" not in entry
    assert "end_center" not in entry

    # live 源：按钮下拉无占位项，默认 Back 为有效选择，序列化必须带 buttons
    capture_and_wait(editor)
    _set_action(editor, "system_button")
    flush_events()
    assert editor.validate_step_at(editor.current_step) == []
    data = editor._build_action_data()
    assert data["buttons"] == ["Back"]
    assert data["element"] == "系统按钮Back"


# ---------- 防抖补填：侧栏标记消失、看板计数递减 ----------

def test_debounced_refill_clears_marker_and_count(editor_factory):
    editor = editor_factory()
    confirm_n_steps(editor, 3)

    # 把第 2 步篡改为缺时间的 wait（历史源），全量重算后标记+计数
    editor.steps_data[1]["action_data"] = {"action": "wait", "element": ""}
    editor.revalidate_all_missing()
    assert editor.sidebar.item_widgets[1].missing_label.text() == "⚠ 缺项"
    assert _missing_text(editor) == "待完善: 1"

    # 跳回该步（回填后 live 态仍缺时间），补填后直接触发防抖回调
    editor.jump_to_step(1)
    flush_events()
    assert editor.get_cached_missing(1)
    editor.time_input.setText("2.5")
    editor._on_validation_debounced()
    assert editor.get_cached_missing(1) == []
    assert editor.sidebar.item_widgets[1].missing_label.text() == ""
    assert _missing_text(editor) == "待完善: 0"

    # 真实 QTimer 300ms 联动：再次清空，qWait(>=350ms) 后标记自动回来
    editor.time_input.clear()
    assert editor.validation_timer.isActive()
    QTest.qWait(350)
    assert editor.get_cached_missing(1)
    assert editor.sidebar.item_widgets[1].missing_label.text() == "⚠ 缺项"
    assert _missing_text(editor) == "待完善: 1"


# ---------- 删除/插入后缓存下标不错位 ----------

def test_cache_index_alignment_after_delete_and_insert(editor_factory):
    editor = editor_factory()
    confirm_n_steps(editor, 3)
    editor.steps_data[1]["action_data"] = {"action": "wait", "element": ""}
    editor.revalidate_all_missing()
    assert _missing_text(editor) == "待完善: 1"
    assert editor.sidebar.item_widgets[1].missing_label.text() == "⚠ 缺项"

    # 删除缺项步：前移后的两步均合法，缺项标记不得残留在新下标上
    editor.jump_to_step(1)
    flush_events()
    editor.delete_current_step()
    flush_events(80)
    assert len(editor.steps_data) == 2
    assert set(editor._missing_cache.keys()) == {0, 1}
    assert _missing_text(editor) == "待完善: 0"
    assert all(item.missing_label.text() == ""
               for item in editor.sidebar.item_widgets)

    # 在第 1 步后插入空白步：缺项标记必须落在新下标 1，不错位到锚点
    editor.jump_to_step(0)
    flush_events()
    editor.start_insert_capture()
    waited = 0
    while editor._screenshot_in_progress and waited < 10000:
        QTest.qWait(30)
        waited += 30
    flush_events()
    assert editor.current_step == 1 and len(editor.steps_data) == 3
    assert editor.sidebar.item_widgets[0].missing_label.text() == ""
    assert editor.sidebar.item_widgets[1].missing_label.text() == "⚠ 缺项"
    assert editor.sidebar.item_widgets[2].missing_label.text() == ""
    assert _missing_text(editor) == "待完善: 1"

    # 补全插入步（wait 只需时间），确认后计数归零
    fill_valid_step(editor, action="wait")
    editor.confirm_step()
    flush_events(80)
    assert _missing_text(editor) == "待完善: 0"


# ---------- jump 同下标不得静默 return ----------

def test_jump_same_index_recalculates_current(editor_factory):
    editor = editor_factory()
    confirm_n_steps(editor, 2)
    editor.jump_to_step(0)
    flush_events()
    assert editor.get_cached_missing(0) == []

    # 在当前下标清空坐标后再次跳到同一下标：必须重算并落表，不能静默
    editor.coord_x_input.clear()
    editor.coord_y_input.clear()
    editor._current_vertices = None
    editor.jump_to_step(0)
    flush_events()
    assert editor.get_cached_missing(0)
    assert "coordinate" not in editor.steps_data[0]["action_data"]
    assert editor.sidebar.item_widgets[0].missing_label.text() == "⚠ 缺项"


# ---------- 未确认新步计入看板并拦截结束；answer_terminate 文案 ----------

def test_unconfirmed_step_counts_and_finish_blocked(editor_factory, modal,
                                                    monkeypatch):
    editor = editor_factory()
    confirm_n_steps(editor, 1)
    assert editor.current_step == 1

    capture_and_wait(editor)
    _set_action(editor, "answer_terminate")
    editor.text_input.clear()
    flush_events()
    assert editor.current_step == len(editor.steps_data)

    # 未确认新步缺项并入看板计数（有截图才计）
    assert editor.live_missing_reasons()
    assert _missing_text(editor) == "待完善: 1"

    captured = {}

    class FakeValidationFailDialog:
        def __init__(self, entries, parent=None):
            captured["entries"] = list(entries)

        def exec_(self):
            return 0

        def target_index(self):
            return None

    monkeypatch.setattr(annotation_editor, "ValidationFailDialog",
                        FakeValidationFailDialog)
    editor._finish_task()

    # 被拦截：不写完成态 JSON、不标记完成，缺项清单含未确认新步
    json_path = os.path.join(editor.gui_dir, f"gui_{editor.gui_number}.json")
    assert not os.path.exists(json_path)
    assert editor._task_completed is False
    entries = captured["entries"]
    assert entries and entries[-1][0] == 1
    # answer_terminate 在对话框显示“回答并结束”（落盘 action 仍为 answer）
    assert entries[-1][1] == "回答并结束"
    assert any("回答内容" in r for r in entries[-1][2])
    # 动作定义表文案
    assert dict(ANDROID_ACTIONS)["answer_terminate"] == \
        "回答并结束 (answer_terminate)"

    # 补填后可正常结束，完成态 JSON 落盘
    editor.text_input.setText("最终回答")
    editor.confirm_step()
    flush_events(150)
    assert editor._task_completed is True
    assert os.path.exists(json_path)


# ---------- 重截图覆盖：清旧 coordinate/pixels/vertices ----------

def test_recapture_clears_old_coordinate_fields(editor_factory):
    editor = editor_factory()
    capture_and_wait(editor)
    fill_valid_step(editor, action="scroll")
    editor.confirm_step()
    flush_events(850)
    step = editor.steps_data[0]
    assert step["action_data"].get("coordinate")
    assert isinstance(step["action_data"].get("pixels"), int)
    assert step["vertices"]

    editor.jump_to_step(0)
    flush_events()
    capture_and_wait(editor)

    data = editor.steps_data[0]["action_data"]
    assert "coordinate" not in data
    assert "pixels" not in data
    assert editor.steps_data[0]["vertices"] is None
    assert editor.coord_x_input.text() == ""
    assert editor.coord_y_input.text() == ""
    assert editor.pixels_input.text() == ""
    assert editor._current_vertices is None
    # 缺项被重算并体现在侧栏/缓存
    assert editor.get_cached_missing(0)
    assert editor.sidebar.item_widgets[0].missing_label.text() == "⚠ 缺项"


# ---------- 旧草稿：显式 0 / [0,0] / 1.0 是合法用户数据 ----------

def test_legacy_draft_explicit_zero_values_not_missing(editor_factory):
    editor = editor_factory()
    # 第 1 步 wait time=1.0
    capture_and_wait(editor)
    fill_valid_step(editor, action="wait")
    editor.confirm_step()
    flush_events(850)
    # 第 2 步 click coordinate=[0,0]、vertices 全 0
    capture_and_wait(editor)
    fill_valid_step(editor, action="click", vertices=[0, 0, 0, 0])
    editor.confirm_step()
    flush_events(80)

    editor._write_draft_now()
    flush_events()
    draft = editor.data_manager.load_draft(editor.gui_number)
    assert draft is not None
    # 强制写为历史版本可能产出的显式 0 值
    draft["current_step_index"] = 0
    draft["steps_data"][0]["action_data"]["time"] = 1.0
    draft["steps_data"][1]["action_data"]["coordinate"] = [0, 0]
    draft["steps_data"][1]["vertices"] = [0, 0, 0, 0]
    editor.data_manager.save_draft(draft, editor.gui_number)

    resumed = editor_factory(auto_init=False)
    resumed.load_from_draft(draft)
    flush_events(100)

    assert resumed.validate_step_at(0) == []
    assert resumed.validate_step_at(1) == []
    assert _missing_text(resumed) == "待完善: 0"
    assert all(not item.missing_label.text()
               for item in resumed.sidebar.item_widgets)
    # 表单回填保留显式 0 值，不残留也不误清空
    assert resumed.time_input.text() == "1.0"
    resumed.jump_to_step(1)
    flush_events()
    assert resumed.coord_x_input.text() == "0"
    assert resumed.coord_y_input.text() == "0"
    assert resumed._current_vertices == [0, 0, 0, 0]
    assert resumed.validate_step_at(1) == []


# ---------- 畸形历史数据：不抛异常且判缺 ----------

def test_malformed_history_data_does_not_raise(editor_factory):
    editor = editor_factory()
    confirm_n_steps(editor, 1)

    step = editor.steps_data[0]
    step["screenshot"] = 12345  # 非字符串
    step["vertices"] = ["a", "b", "c", "d"]
    step["action_data"] = {
        "action": "scroll",
        "element": "",
        "coordinate": "abc",
        "pixels": "xx",
    }
    # 越界下标返回空列表
    assert editor.validate_step_at(99) == []
    reasons = editor.validate_step_at(0)
    assert any("截图" in r for r in reasons)
    assert any("滚动像素" in r for r in reasons)

    # NaN/Inf（JSON 落不了盘，但内存态可能被外部污染）同样不抛
    # 取回真实截图文件名后再塞数值畸形
    filenames = [n for n in os.listdir(editor.gui_dir) if n.endswith(".png")]
    assert filenames
    step["screenshot"] = filenames[0]
    step["action_data"]["pixels"] = float("nan")
    step["action_data"]["coordinate"] = [float("inf"), 1]
    step["vertices"] = [1, 2, float("-inf"), 4]
    reasons = editor.validate_step_at(0)
    assert any("滚动像素" in r for r in reasons)
    assert any("坐标" in r for r in reasons)
    assert any("拉框区域" in r for r in reasons)

    # 回填与 coords 导出对全面畸形数据不抛异常
    editor._restore_action_ui({"action": "swipe", "start_coordinate": None,
                               "coordinate": (), "text": 123,
                               "keys": "not-a-list", "time": {},
                               "pixels": object(), "buttons": "Back"})
    entry = editor._build_coords_entry(step["action_data"], step["vertices"])
    assert entry["action"] == "scroll"
    assert "vertices" not in entry and "center" not in entry
