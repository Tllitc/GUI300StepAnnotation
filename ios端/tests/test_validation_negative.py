# -*- coding: utf-8 -*-
"""Task10 必填项校验负向测试组。

只走真实产品代码路径（截图/拉框/输入信号/防抖/确认/结束/草稿/续采），
对话框由 conftest.dialogs 自动应答；会触发结束缺项弹窗的用例统一用
实例属性替换 editor._show_validation_fail_dialog，避免 offscreen 模态阻塞。

覆盖：
  - wait/long_press 缺时间、scroll 缺 pixels（0 合法）、swipe 缺终点/
    vertices 非有限、click 缺坐标、system_button 缺选择 -> 判缺且
    action_data/草稿 JSON 不伪造 time/pixels/coordinate/buttons 等默认键
  - live 输入 abc/NaN/Inf 判缺且不抛异常
  - 补填越过 300ms 防抖后侧栏红标消失、缓存清空、看板计数递减
  - 未确认新步计入看板并被 _finish_task 拦截
  - 重截图覆盖清旧坐标并排草稿
  - 磁盘截图丢失进入缺项态、编辑不丢、确认被拦、重截图原地恢复
  - terminate 意图切走还原、不污染他步
  - 显式 0/[0,0]/1.0 历史值不追溯判缺（含旧草稿续采）
  - answer_terminate 缺项对话框文案
"""

import os

import pytest
from PyQt5.QtTest import QTest

from annotation_editor import AnnotationEditor
from data_manager import DataManager
from fakes import FakeScreenCapture
from helpers import (
    _select_action,
    capture,
    draw_rect,
    fill_step,
    finish_task,
    flush_draft,
    walk_steps,
)
from invariants import assert_all, assert_final_json_consistency


# ----------------------------------------------------------------------
# 本文件小助手
# ----------------------------------------------------------------------

def _block_fail_dialog(editor):
    """替换结束缺项弹窗（offscreen 下真实 QDialog.exec_ 会永久阻塞）。

    返回收集 missing_list 的单元素列表。"""
    calls = []
    editor._show_validation_fail_dialog = lambda missing_list: calls.append(missing_list)
    return calls


def _make_resume_editor(dm, dialogs, qapp):
    """照搬 conftest.editor / test_rounds_draft 的真实构造步骤做续采编辑器。"""
    ed = AnnotationEditor(
        data_manager=dm,
        app_name="测试App",
        task_instruction="测试指令",
        screen_info={"screen_size": [390, 844]},
        app_type="iOS",
        udid=None,
        close_callback=None,
    )
    ed.initialize_gui_directory()
    ed.screen_capture = FakeScreenCapture()
    ed._test_dialogs = dialogs
    qapp.processEvents()
    return ed


def _wait_debounce():
    """越过 300ms 校验防抖。"""
    QTest.qWait(350)


# ----------------------------------------------------------------------
# 1. wait / long_press 缺时间
# ----------------------------------------------------------------------

@pytest.mark.parametrize("action", ["wait", "long_press"])
def test_time_action_missing_time_flagged_no_fake_key(editor, action):
    capture(editor)
    fill_step(editor, action=action)          # 合法基线（long_press 含拉框）
    editor.time_input.clear()                  # 再把时间清空 -> 缺时间

    reasons = editor.validate_step_at(editor.current_step)
    assert "缺少等待时间" in reasons

    data = editor._build_action_data()
    assert "time" not in data, "缺时间时 action_data 不得伪造 time 键"

    # 草稿 JSON 同样不得出现 time 键（pending 新步会被实时序列化进草稿）
    flush_draft(editor)
    draft = DataManager.load_draft_from_dir(editor.gui_dir)
    draft_actions = draft["steps_data"][0]["action_data"]
    assert "time" not in draft_actions, "草稿 JSON 不得伪造 time 默认值"

    # 确认被拦截：步骤不落表
    editor.confirm_step()
    assert editor.steps_data == []
    assert editor.current_step == 0


# ----------------------------------------------------------------------
# 2. scroll 缺 pixels（0 合法）
# ----------------------------------------------------------------------

def test_scroll_missing_pixels_flagged_zero_valid(editor):
    capture(editor)
    fill_step(editor, action="scroll")
    editor.pixels_input.clear()

    reasons = editor.validate_step_at(editor.current_step)
    assert "缺少滚动像素" in reasons
    assert "pixels" not in editor._build_action_data()

    # 0 是合法测量结果：补 0 后判过且如实落数据
    editor.pixels_input.setText("0")
    assert editor.validate_step_at(editor.current_step) == []
    assert editor._build_action_data()["pixels"] == 0


# ----------------------------------------------------------------------
# 3. swipe 缺终点 / vertices 非有限 / 全缺时不伪造坐标键
# ----------------------------------------------------------------------

def test_swipe_missing_end_and_bad_vertices(editor):
    capture(editor)
    fill_step(editor, action="swipe")          # 合法基线：起点框+起终点坐标
    assert editor.validate_step_at(editor.current_step) == []

    # 缺终点
    editor.coord2_x_input.clear()
    editor.coord2_y_input.clear()
    reasons = editor.validate_step_at(editor.current_step)
    assert "缺少终点坐标" in reasons
    data = editor._build_action_data()
    assert "coordinate" not in data, "swipe 缺终点时不得伪造终点 coordinate 键"
    assert data.get("start_coordinate")        # 起点仍如实保留

    # 起点一并清空 + 无拉框：起终点坐标键都不得伪造
    editor.coord_x_input.clear()
    editor.coord_y_input.clear()
    editor._current_vertices = None
    reasons = editor.validate_step_at(editor.current_step)
    assert {"缺少起点拉框", "缺少起点坐标", "缺少终点坐标"} <= set(reasons)
    data = editor._build_action_data()
    assert "start_coordinate" not in data
    assert "coordinate" not in data

    # vertices 非有限（UI 正常路径不会产生，直接注入）：判缺且不抛异常
    draw_rect(editor)                          # 重新写起点框/起点坐标
    editor.coord2_x_input.setText("250")
    editor.coord2_y_input.setText("550")
    for bad in (float("nan"), float("inf"), float("-inf")):
        editor._current_vertices = [1, 2, bad, 4]
        reasons = editor.validate_step_at(editor.current_step)
        assert "缺少起点拉框" in reasons, f"非有限 vertices {bad} 未判缺"


# ----------------------------------------------------------------------
# 4. click 缺坐标/拉框
# ----------------------------------------------------------------------

def test_click_missing_coord_flagged_no_fake_key(editor):
    capture(editor)
    fill_step(editor, action="click", rect=None)   # 只选动作不拉框

    reasons = editor.validate_step_at(editor.current_step)
    assert "缺少拉框区域" in reasons
    assert "缺少坐标" in reasons
    assert "coordinate" not in editor._build_action_data()

    editor.confirm_step()
    assert editor.steps_data == []


# ----------------------------------------------------------------------
# 5. system_button 缺选择
# ----------------------------------------------------------------------

def test_system_button_missing_selection(editor):
    capture(editor)
    fill_step(editor, action="system_button")
    # combo 无空项，setCurrentIndex(-1) 使 currentText()=="" 造“未选择”
    editor.button_combo.setCurrentIndex(-1)
    QTest.qWait(0)

    reasons = editor.validate_step_at(editor.current_step)
    assert "缺少系统按钮选择" in reasons
    data = editor._build_action_data()
    assert "buttons" not in data, "未选系统按钮时不得伪造 buttons 键"
    assert data.get("element") == ""

    editor.confirm_step()
    assert editor.steps_data == []


# ----------------------------------------------------------------------
# 6. live 非法输入（abc/NaN/Inf）判缺且不抛异常
# ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "action,field,bad_value,expected_reason",
    [
        ("click", "coord_x_input", "abc", "缺少坐标"),
        ("click", "coord_x_input", "nan", "缺少坐标"),
        ("click", "coord_x_input", "inf", "缺少坐标"),
        ("wait", "time_input", "abc", "缺少等待时间"),
        ("wait", "time_input", "nan", "缺少等待时间"),
        ("wait", "time_input", "inf", "缺少等待时间"),
        ("scroll", "pixels_input", "abc", "缺少滚动像素"),
        ("scroll", "pixels_input", "nan", "缺少滚动像素"),
        ("scroll", "pixels_input", "inf", "缺少滚动像素"),
    ],
)
def test_live_non_finite_inputs_flagged_without_raising(
    editor, action, field, bad_value, expected_reason
):
    capture(editor)
    fill_step(editor, action=action)
    getattr(editor, field).setText(bad_value)

    try:
        reasons = editor.validate_step_at(editor.current_step)
    except Exception as exc:  # noqa: BLE001 - 校验对非法输入必须吞掉解析异常
        pytest.fail(f"非法输入 {bad_value!r} 导致校验抛异常：{exc}")
    assert expected_reason in reasons


# ----------------------------------------------------------------------
# 7. 补填越过防抖：侧栏红标消失、缓存清空、看板计数递减
# ----------------------------------------------------------------------

def test_fill_after_debounce_clears_marker_and_count(editor):
    # 落表一个合法 wait 步，再回看它清空时间 -> 已落表步红标 + 看板 1
    capture(editor)
    fill_step(editor, action="wait", time_value="2.0")
    editor.confirm_step()
    assert len(editor.steps_data) == 1

    editor.display_step(0)
    editor.time_input.clear()
    _wait_debounce()

    item = editor.sidebar.item_widgets[0]
    assert editor.get_cached_missing(0)
    assert not item.missing_label.isHidden()
    assert editor.sidebar.missing_count_label.text() == "缺填项：1"

    # 补填后防抖重算：红标隐藏、缓存清空、看板归零
    editor.time_input.setText("3.0")
    _wait_debounce()
    assert editor.get_cached_missing(0) == []
    assert item.missing_label.isHidden()
    assert editor.sidebar.missing_count_label.text() == "缺填项：0"


def test_pending_live_slot_decrements_after_fill(editor):
    # 未确认新步不建侧栏条目，只占看板计数槽；补填后槽位置空
    walk_steps(editor, 1, action="click")
    capture(editor)
    # intent 输入产生真实 textChanged 信号，驱动 300ms 防抖刷新看板
    fill_step(editor, action="click", rect=None, intent="待标注")
    _wait_debounce()
    assert editor.sidebar.missing_count_label.text() == "缺填项：1"
    assert len(editor.sidebar.item_widgets) == 1

    draw_rect(editor)
    _wait_debounce()
    assert editor.sidebar.missing_count_label.text() == "缺填项：0"


# ----------------------------------------------------------------------
# 8. 未确认新步计入看板并被结束拦截
# ----------------------------------------------------------------------

def test_pending_new_step_blocks_finish(editor, qapp):
    walk_steps(editor, 1, action="click")
    capture(editor)
    # intent 输入产生真实 textChanged 信号，驱动 300ms 防抖刷新看板
    fill_step(editor, action="click", rect=None, intent="待标注")
    _wait_debounce()
    assert editor.sidebar.missing_count_label.text() == "缺填项：1"

    calls = _block_fail_dialog(editor)
    editor._finish_task()

    assert calls, "存在缺填项时结束任务必须弹窗拦截"
    missing_list = calls[0]
    assert [item[0] for item in missing_list] == [1]
    assert editor.rounds == []
    final_json = os.path.join(editor.gui_dir, f"gui_{editor.gui_number}.json")
    assert not os.path.exists(final_json), "被拦截时不得产出最终 JSON"


# ----------------------------------------------------------------------
# 9. 重截图覆盖：清旧坐标/vertices，序号不变，草稿同步
# ----------------------------------------------------------------------

def test_recapture_overwrite_clears_coords_and_drafts(editor):
    walk_steps(editor, 2, action="click")
    editor.display_step(1)
    old_name = editor.steps_data[1]["screenshot"]
    old_path = editor.steps_data[1]["screenshot_filepath"]
    assert editor.steps_data[1]["action_data"].get("coordinate")

    capture(editor)  # 已有截图 -> 原地覆盖分支

    # 序号/文件名复用，旧拉框与坐标被清空
    assert editor._current_screenshot_filename == old_name
    assert os.path.isfile(old_path)
    assert editor.coord_x_input.text() == ""
    assert editor.coord_y_input.text() == ""
    assert editor._current_vertices is None
    reasons = editor.validate_step_at(1)
    assert {"缺少拉框区域", "缺少坐标"} <= set(reasons)

    # 草稿实时序列化当前编辑位：清旧坐标必须同步排到草稿
    flush_draft(editor)
    draft = DataManager.load_draft_from_dir(editor.gui_dir)
    draft_step = draft["steps_data"][1]
    assert draft_step["screenshot"] == old_name
    assert "coordinate" not in draft_step["action_data"]
    assert draft_step["vertices"] is None

    # 真实用户路径：新图上重新拉框标注后恢复全绿，全套不变量成立
    fill_step(editor, action="click")
    editor.display_step(0)
    editor.display_step(1)
    assert editor.validate_step_at(1) == []
    assert_all(editor)


# ----------------------------------------------------------------------
# 10. 磁盘截图丢失：缺项态 + 编辑不丢 + 确认拦截 + 原地重截恢复
# ----------------------------------------------------------------------

def test_lost_screenshot_file_missing_state_and_recover(editor):
    walk_steps(editor, 2, action="click", intent="描述A")
    editor.display_step(0)
    target = editor.steps_data[1]
    lost_name = target["screenshot"]
    lost_path = target["screenshot_filepath"]
    os.remove(lost_path)

    # 重新切到该步：磁盘文件丢失 -> 明确的截图缺失态
    editor.display_step(1)
    assert editor._screenshot_missing is True
    assert editor._current_screenshot_filename is None
    reasons = editor.validate_step_at(1)
    assert "截图文件缺失，请重新截图" in reasons

    # 编辑内容不丢：动作/坐标/意图字段照常恢复
    assert editor.action_combo.currentData() == "click"
    assert editor.coord_x_input.text() == "100"
    assert editor.coord_y_input.text() == "250"
    assert editor.intent_input.text() == "描述A"
    # 模型引用不被缺失态覆盖
    assert editor.steps_data[1]["screenshot"] == lost_name

    # 确认被拦回，不新增步骤
    editor.confirm_step()
    assert len(editor.steps_data) == 2

    # 缺失态重截图：序号原地复用、文件重生、缺项解除（坐标需重新标注）
    capture(editor)
    assert editor._screenshot_missing is False
    assert editor._current_screenshot_filename == lost_name
    assert os.path.isfile(lost_path)

    fill_step(editor, action="click", intent="描述A")
    assert editor.validate_step_at(1) == []
    assert_all(editor)


# ----------------------------------------------------------------------
# 11. terminate 意图备份/还原，不污染他步
# ----------------------------------------------------------------------

def test_terminate_intent_restore_no_pollution(editor):
    capture(editor)
    editor.intent_input.setText("原始意图")

    _select_action(editor, "terminate")
    assert editor.intent_input.text() == "任务完成"
    assert editor._pre_terminate_intent == "原始意图"

    _select_action(editor, "click")
    assert editor.intent_input.text() == "原始意图", "切离 terminate 必须还原进入前意图"

    draw_rect(editor)
    editor.confirm_step()
    assert editor.steps_data[0]["intent"] == "原始意图"
    assert "任务完成" not in editor.steps_data[0]["intent"]


# ----------------------------------------------------------------------
# 12. 显式 0/[0,0]/1.0 历史值不追溯判缺（含旧草稿续采）
# ----------------------------------------------------------------------

def test_legacy_explicit_zeros_not_retroactively_flagged(editor, dm, dialogs, qapp):
    walk_steps(editor, 3, action="click")
    names = [s["screenshot"] for s in editor.steps_data]

    def _path(name):
        return os.path.join(editor.gui_dir, name)

    # 手工构造“老版本产出”的显式 0/[0,0]/1.0 数据
    legacy_steps = [
        {
            "screenshot": names[0],
            "screenshot_filepath": _path(names[0]),
            "intent": "",
            "action_data": {"action": "wait", "element": "", "time": 1.0},
            "vertices": None,
        },
        {
            "screenshot": names[1],
            "screenshot_filepath": _path(names[1]),
            "intent": "",
            "action_data": {"action": "click", "element": "", "coordinate": [0, 0]},
            "vertices": [0, 0, 0, 0],
        },
        {
            "screenshot": names[2],
            "screenshot_filepath": _path(names[2]),
            "intent": "",
            "action_data": {
                "action": "scroll",
                "element": "",
                "coordinate": [0, 0],
                "pixels": 0,
            },
            "vertices": [0, 0, 0, 0],
        },
    ]

    # 历史口径直接校验（current_step 离开这些下标，强制走 steps_data 分支）
    editor.steps_data = legacy_steps
    editor.current_step = len(legacy_steps)
    editor._current_screenshot_filename = None
    for i in range(3):
        assert editor.validate_step_at(i) == [], f"第 {i} 步显式旧值被追溯判缺"

    # 旧草稿落盘 -> 续采打开仍不判缺，且数值原样保留
    draft = {
        "gui_number": editor.gui_number,
        "app_name": editor.app_name,
        "task_instruction": editor.task_instruction,
        "screen_info": editor.screen_info,
        "app_type": editor.app_type,
        "rounds": [],
        "steps_data": [editor._serialize_step(s) for s in legacy_steps],
        "current_step_index": 0,
    }
    assert dm.save_draft(draft, editor.gui_number)

    resume = _make_resume_editor(dm, dialogs, qapp)
    try:
        loaded = DataManager.load_draft_from_dir(editor.gui_dir)
        assert resume.load_from_draft(loaded) is False
        for i in range(3):
            assert resume.validate_step_at(i) == [], f"续采后第 {i} 步被追溯判缺"
        assert resume.sidebar.missing_count_label.text() == "缺填项：0"
        assert resume.steps_data[0]["action_data"]["time"] == 1.0
        assert resume.steps_data[1]["action_data"]["coordinate"] == [0, 0]
        assert resume.steps_data[2]["action_data"]["pixels"] == 0
    finally:
        resume.close()
        resume.deleteLater()
        qapp.processEvents()


# ----------------------------------------------------------------------
# 13. answer_terminate 缺项对话框文案与落盘 action 映射
# ----------------------------------------------------------------------

def test_answer_terminate_missing_label_and_action_mapping(editor):
    walk_steps(editor, 1, action="click")
    capture(editor)
    fill_step(editor, action="answer_terminate", text="   ")  # 空白回答 -> 缺项

    calls = _block_fail_dialog(editor)
    editor._finish_task()

    assert calls
    missing_list = calls[0]
    assert [item[0] for item in missing_list] == [1]
    assert missing_list[0][1] == "回答并结束 (answer+terminate)"
    # 落盘模型里 action 仍映射为 answer + status success
    assert editor.steps_data[1]["action_data"]["action"] == "answer"
    assert editor.steps_data[1]["action_data"]["status"] == "success"
    assert editor.rounds == []


# ----------------------------------------------------------------------
# 14. 代表性合法流程（含 0 像素/系统按钮）全套不变量 + 最终 JSON
# ----------------------------------------------------------------------

def test_representative_valid_flow_invariants(editor, qapp):
    capture(editor)
    fill_step(editor, action="click")
    editor.confirm_step()

    capture(editor)
    fill_step(editor, action="wait", time_value="1.0")
    editor.confirm_step()

    capture(editor)
    fill_step(editor, action="scroll", pixels=0)
    editor.confirm_step()

    capture(editor)
    fill_step(editor, action="system_button")
    editor.confirm_step()

    assert_all(editor)

    finish_task(editor, continue_new=False)
    qapp.processEvents()

    assert_final_json_consistency(
        editor,
        expected_rounds=1,
    )
