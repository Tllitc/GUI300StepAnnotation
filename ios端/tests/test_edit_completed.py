# -*- coding: utf-8 -*-
"""已完成任务再编辑（iOS）回归测试。

覆盖:
  1. 从最终 JSON + coords 重建编辑现场（含旧 coords 无 round 的切分）
  2. 编辑某一轮后只替换该轮，其余轮与顶层字段不变；coords 仍为数组且带 round
  3. 编辑模式不写 draft
  4. 编辑模式直接关闭窗口自动写回
  5. 存在缺项时阻止保存，磁盘 JSON 不变
  6. coords 条目查找已去掉位置回退：框丢失/框与坐标不一致时不载入框、step 漂移按
     center 恢复、写回保留盘上原条目（与 Windows 端 A1-A4、安卓端同口径）
"""

import copy
import json
import os

import pytest

from PyQt5.QtWidgets import QApplication

import annotation_editor as _ae
from annotation_editor import AnnotationEditor
from data_manager import DataManager
from fakes import FakeScreenCapture
from helpers import open_edit_mode
from invariants import (
    assert_edit_writeback_preserved,
    assert_final_json_consistency,
)


GUI_NUMBER = "000001"
GUI_DIR_NAME = f"gui_{GUI_NUMBER}"


# ----------------------------------------------------------------------
# 数据集构造
# ----------------------------------------------------------------------

def _screenshot_names():
    return [f"gui_{GUI_NUMBER}_{i:04d}.png" for i in range(1, 5)]


def _completed_data(names):
    return {
        "platform": "iOS",
        "system": "iOS 17.0",
        "screen_size": [390, 844],
        "task_type": "iOS-社交",
        "messages": [
            {
                "role": "user",
                "instruction": "第一轮指令",
            },
            {
                "role": "assistant",
                "trajectory": [
                    {
                        "step": 0,
                        "intent": "打开设置",
                        "CoT": "",
                        "observation": {
                            "screenshot": names[0],
                            "active_window": "",
                            "ui_tree_segment": "",
                            "note": "round0-step0",
                        },
                        "actions": [
                            {"action": "click", "element": "", "coordinate": [100, 250],
                             "status": "success"}
                        ],
                    },
                    {
                        "step": 1,
                        "intent": "点击搜索",
                        "CoT": "",
                        "observation": {
                            "screenshot": names[1],
                            "active_window": "",
                            "ui_tree_segment": "",
                        },
                        "actions": [
                            {"action": "click", "element": "", "coordinate": [200, 400]}
                        ],
                    },
                ],
            },
            {
                "role": "user",
                "instruction": "第二轮指令",
            },
            {
                "role": "assistant",
                "trajectory": [
                    {
                        "step": 0,
                        "intent": "输入文字",
                        "CoT": "",
                        "observation": {
                            "screenshot": names[2],
                            "active_window": "",
                            "ui_tree_segment": "",
                            "note": "keep-me",
                        },
                        "actions": [
                            {"action": "type", "element": "", "coordinate": [150, 300],
                             "text": "hello", "status": "success"}
                        ],
                    },
                    {
                        "step": 1,
                        "intent": "点击结果",
                        "CoT": "",
                        "observation": {
                            "screenshot": names[3],
                            "active_window": "",
                            "ui_tree_segment": "",
                        },
                        "actions": [
                            {"action": "click", "element": "", "coordinate": [180, 500]}
                        ],
                    },
                ],
            },
        ],
    }


def _coords_entries(with_round):
    entries = [
        {"step": 0, "action": "click", "vertices": [50, 200, 150, 300],
         "center": [100, 250]},
        {"step": 1, "action": "click", "vertices": [150, 350, 250, 450],
         "center": [200, 400]},
        {"step": 0, "action": "type", "vertices": [100, 250, 200, 350],
         "center": [150, 300]},
        {"step": 1, "action": "click", "vertices": [130, 450, 230, 550],
         "center": [180, 500]},
    ]
    if with_round:
        for idx, entry in enumerate(entries):
            entry = dict(entry)
            entry["round"] = 0 if idx < 2 else 1
            entries[idx] = entry
    return entries


def _build_dataset(base_dir, with_round=True):
    gui_dir = os.path.join(base_dir, GUI_DIR_NAME)
    os.makedirs(gui_dir, exist_ok=True)

    names = _screenshot_names()
    fake = FakeScreenCapture()
    for name in names:
        fake.capture(os.path.join(gui_dir, name))

    data = _completed_data(names)
    coords = _coords_entries(with_round)
    with open(os.path.join(gui_dir, f"gui_{GUI_NUMBER}.json"), "w",
              encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(gui_dir, f"gui_{GUI_NUMBER}_coords.json"), "w",
              encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)
    return gui_dir, data, coords


def _make_editor(base_dir, qapp):
    ed = AnnotationEditor(
        data_manager=DataManager(base_dir=base_dir),
        app_name=GUI_DIR_NAME,
        task_instruction="",
        screen_info={"screen_size": [390, 844]},
        app_type="",
        udid=None,
        close_callback=None,
    )
    ed.screen_capture = FakeScreenCapture()
    qapp.processEvents()
    return ed


def _dispose(editor, qapp, allow_write=True):
    """测试清理：默认标记已落盘，避免 closeEvent 静默改写数据。"""
    if not allow_write:
        editor._final_data_saved = True
    editor.close()
    editor.deleteLater()
    qapp.processEvents()


def _load_json(gui_dir):
    path = os.path.join(gui_dir, f"gui_{GUI_NUMBER}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_coords(gui_dir):
    path = os.path.join(gui_dir, f"gui_{GUI_NUMBER}_coords.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _draft_files(gui_dir):
    return [f for f in os.listdir(gui_dir) if f.endswith("_draft.json")]


# ----------------------------------------------------------------------
# 1. 加载重建
# ----------------------------------------------------------------------

def test_load_from_completed_json_restores_steps_and_old_coords(tmp_path, qapp):
    gui_dir, data, coords = _build_dataset(str(tmp_path), with_round=False)
    editor = _make_editor(str(tmp_path), qapp)
    try:
        editor.load_from_completed_json(data, coords, 1, gui_dir)

        assert editor._edit_mode is True
        assert editor.gui_dir == gui_dir
        assert editor.gui_number == GUI_NUMBER
        assert len(editor.rounds) == 2
        assert editor.rounds[0]["instruction"] == "第一轮指令"
        assert editor.rounds[1]["instruction"] == "第二轮指令"

        assert len(editor.steps_data) == 2
        step0, step1 = editor.steps_data
        assert step0["screenshot"] == "gui_000001_0003.png"
        assert step0["intent"] == "输入文字"
        assert step0["action_data"]["action"] == "type"
        assert step0["action_data"]["text"] == "hello"
        assert step0["vertices"] == [100, 250, 200, 350]

        assert step1["screenshot"] == "gui_000001_0004.png"
        assert step1["intent"] == "点击结果"
        assert step1["vertices"] == [130, 450, 230, 550]

        # 旧 coords 无 round：按 step 回退切分，第二轮正确归属
        assert len(editor._coords_rounds[0]) == 2
        assert editor._coords_rounds[1][0]["action"] == "type"
        assert editor._coords_rounds[1][1]["vertices"] == [130, 450, 230, 550]

        assert "编辑已完成任务" in editor.windowTitle()
        assert "编辑已完成任务" in editor.status_label.text()
    finally:
        _dispose(editor, qapp, allow_write=False)


# ----------------------------------------------------------------------
# 2. 只替换选中轮次，顶层字段与 coords 格式保持
# ----------------------------------------------------------------------

def test_save_edited_round_only_replaces_selected_round(tmp_path, qapp):
    gui_dir, data, coords = _build_dataset(str(tmp_path), with_round=True)
    editor = _make_editor(str(tmp_path), qapp)
    editor.load_from_completed_json(data, coords, 1, gui_dir)

    editor.intent_input.setText("输入文字-修改")
    editor.text_input.setText("hello2")

    assert editor.save_edited_round(False) is True
    qapp.processEvents()

    saved = _load_json(gui_dir)
    assert saved["platform"] == data["platform"]
    assert saved["system"] == data["system"]
    assert saved["screen_size"] == data["screen_size"]
    assert saved["task_type"] == data["task_type"]

    # 第一轮 messages 逐字段不变
    assert saved["messages"][0] == data["messages"][0]
    assert saved["messages"][1] == data["messages"][1]

    # 第二轮指令不变，trajectory 被更新
    assert saved["messages"][2] == data["messages"][2]
    traj = saved["messages"][3]["trajectory"]
    assert traj[0]["intent"] == "输入文字-修改"
    assert traj[0]["actions"][0]["text"] == "hello2"
    # 未暴露字段保留
    assert traj[0]["observation"]["note"] == "keep-me"
    assert traj[0]["actions"][0]["status"] == "success"
    assert traj[1] == data["messages"][3]["trajectory"][1]

    # coords 仍为数组，每条带 round；未编辑轮数值不变
    saved_coords = _load_coords(gui_dir)
    assert isinstance(saved_coords, list)
    assert all(entry["round"] == (0 if i < 2 else 1)
               for i, entry in enumerate(saved_coords))
    for idx in range(2):
        for key in ("step", "action", "vertices", "center"):
            assert saved_coords[idx][key] == coords[idx][key]
    assert saved_coords[2]["action"] == "type"
    assert saved_coords[2]["vertices"] == [100, 250, 200, 350]
    assert all(entry["_version"] == "3.1" for entry in saved_coords)

    _dispose(editor, qapp)


# ----------------------------------------------------------------------
# 3. 编辑模式不写 draft
# ----------------------------------------------------------------------

def test_edit_mode_does_not_write_draft(tmp_path, qapp):
    gui_dir, data, coords = _build_dataset(str(tmp_path), with_round=True)
    editor = _make_editor(str(tmp_path), qapp)
    try:
        editor.load_from_completed_json(data, coords, 0, gui_dir)
        editor._write_draft_now()
        editor.schedule_draft_save()
        qapp.processEvents()
        assert _draft_files(gui_dir) == []
    finally:
        _dispose(editor, qapp, allow_write=False)


# ----------------------------------------------------------------------
# 4. 编辑模式关闭窗口自动写回
# ----------------------------------------------------------------------

def test_edit_mode_close_writes_back_changes(tmp_path, qapp):
    gui_dir, data, coords = _build_dataset(str(tmp_path), with_round=True)
    editor = _make_editor(str(tmp_path), qapp)
    editor.load_from_completed_json(data, coords, 1, gui_dir)

    editor.intent_input.setText("关闭前修改")
    editor.close()
    qapp.processEvents()

    saved = _load_json(gui_dir)
    assert saved["messages"][3]["trajectory"][0]["intent"] == "关闭前修改"
    assert saved["messages"][1] == data["messages"][1]
    assert _draft_files(gui_dir) == []

    editor.deleteLater()
    qapp.processEvents()


# ----------------------------------------------------------------------
# 5. 缺项阻止保存且不修改磁盘
# ----------------------------------------------------------------------

def test_missing_fields_block_save_and_keep_json(tmp_path, qapp):
    gui_dir, data, coords = _build_dataset(str(tmp_path), with_round=True)
    editor = _make_editor(str(tmp_path), qapp)
    editor.load_from_completed_json(data, coords, 1, gui_dir)

    dialog_calls = []
    editor._show_validation_fail_dialog = lambda missing: dialog_calls.append(missing)

    # 当前步是 type，清空文本 -> 缺少输入文本
    editor.text_input.setText("")
    assert editor.save_edited_round(False) is False
    assert dialog_calls, "缺项时应弹出缺项清单"
    assert any("缺少输入文本" in "；".join(reasons)
               for _idx, _label, reasons in dialog_calls[0])

    assert _load_json(gui_dir) == data
    assert _load_coords(gui_dir) == coords

    _dispose(editor, qapp, allow_write=False)


# ----------------------------------------------------------------------
# 6. coords 条目查找：位置冒领已根治
# ----------------------------------------------------------------------

@pytest.fixture
def coord_warnings(auto_dialogs, monkeypatch):
    """记录 hydration 的汇总告警。

    conftest 的 auto_dialogs 把 QMessageBox.warning 换成不记录的桩，这里覆盖成
    记录器；显式依赖 auto_dialogs 保证实例化顺序（它先 patch、本夹具后覆盖），
    monkeypatch 逆序卸载会自动还原。
    """
    recorded = []

    def _record(parent=None, title="", text="", *args, **kwargs):
        recorded.append((title, text))
        return None

    monkeypatch.setattr(_ae.QMessageBox, "warning", _record)
    return recorded


def _click_step(intent="点击搜索", coordinate=(100, 200)):
    return intent, {"action": "click", "coordinate": list(coordinate), "element": ""}


def _scroll_step(intent="上滑列表", coordinate=(300, 400)):
    return intent, {"action": "scroll", "coordinate": list(coordinate),
                    "pixels": -120, "element": ""}


def _build_raw_dataset(base_dir, steps, coords_entries):
    """构造单轮已完成任务；coords 逐字写盘，不由轨迹自动派生（模拟历史交付件）。

    :param steps: [(intent, action_data), ...]
    :param coords_entries: 盘上 coords 条目原样内容
    :return: (gui_dir, data)
    """
    gui_dir = os.path.join(base_dir, GUI_DIR_NAME)
    os.makedirs(gui_dir, exist_ok=True)

    fake = FakeScreenCapture()
    trajectory = []
    for j, (intent, action_data) in enumerate(steps):
        filename = f"gui_{GUI_NUMBER}_{j + 1:04d}.png"
        fake.capture(os.path.join(gui_dir, filename))
        trajectory.append({
            "step": j,
            "intent": intent,
            "CoT": "原始思维链",
            "observation": {
                "screenshot": filename,
                "active_window": "",
                "ui_tree_segment": "",
                "extra_obs": "keep",
            },
            "actions": [copy.deepcopy(action_data)],
        })

    data = {
        "platform": "iOS",
        "system": "iOS 17.0",
        "screen_size": [390, 844],
        "task_type": "iOS-社交",
        "messages": [
            {"role": "user", "instruction": "唯一轮指令"},
            {"role": "assistant", "trajectory": trajectory},
        ],
    }
    with open(os.path.join(gui_dir, f"gui_{GUI_NUMBER}.json"), "w",
              encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(gui_dir, f"gui_{GUI_NUMBER}_coords.json"), "w",
              encoding="utf-8") as f:
        json.dump(coords_entries, f, ensure_ascii=False, indent=2)
    return gui_dir, data


def test_legacy_coords_missing_scroll_entry_does_not_steal_neighbor_box(
        tmp_path, qapp, coord_warnings):
    """coords 少一条 scroll 条目时重开编辑：绝不按下标冒领邻居的框。

    该步没有可继承的盘上条目，写回落为「step/action/center」三键条目（iOS 端不
    伪造 vertices，与安卓端 INV-7 下的退化点框不同）；盘上 bbox 未被本轮改写由
    INV-13（assert_edit_writeback_preserved）与下方逐字段断言共同担保。
    """
    click_entry = {"step": 0, "action": "click", "vertices": [40, 140, 160, 260],
                   "center": [100, 200], "source": "coords-v1"}
    gui_dir, _data = _build_raw_dataset(
        str(tmp_path), [_click_step(), _scroll_step()], [click_entry])
    editor = _make_editor(str(tmp_path), qapp)
    try:
        before_data, before_coords = open_edit_mode(editor, gui_dir, 0)

        assert editor.steps_data[0]["vertices"] == [40, 140, 160, 260]
        assert editor.steps_data[0]["coord_issue"] is None
        assert editor.steps_data[1]["vertices"] is None
        assert editor.steps_data[1]["coord_issue"] == "absent"
        assert editor.steps_data[1]["orig_coord_entry"] is None
        assert editor.steps_data[1]["action_data"]["coordinate"] == [300, 400]

        assert len(editor._coord_issues) == 1
        assert editor._coord_issues[0][0] == 1
        assert editor._coord_issues[0][2] == "absent"
        assert any(title == "coords 与坐标值不一致"
                   for title, _text in coord_warnings)
        # 状态栏告警必须在任何跳转之前读：jump_to_step 会覆盖状态文本
        assert "bbox 与 coordinate 不一致" in editor.status_label.text()
        # absent 不阻塞继续编辑：只豁免「框」这一项，坐标/像素照常校验
        assert editor.validate_step_at(1) == []

        # 导航一次也不得抹掉标记：这两个键不在 _collect_step_data 里，靠回贴保住
        editor.jump_to_step(1)
        editor.jump_to_step(0)
        assert editor.steps_data[1]["coord_issue"] == "absent"
        assert editor.steps_data[1]["vertices"] is None

        assert editor.save_edited_round(False) is True
        assert_final_json_consistency(editor, gui_dir, expected_rounds=1)
    finally:
        _dispose(editor, qapp, allow_write=False)

    saved = _load_coords(gui_dir)
    assert [e["step"] for e in saved] == [0, 1]
    # step0 条目逐字段不变（含 source），没有被重编号或改写
    assert saved[0] == {**click_entry, "round": 0, "_version": "3.1"}
    # scroll 步无框可载入 → 不产出任何顶点，更没有第二组冒领来的顶点
    assert "vertices" not in saved[1]
    assert saved[1]["center"] == [300, 400]
    assert [e for e in saved if e.get("vertices") == click_entry["vertices"]] == [saved[0]]

    after, _after_coords = assert_edit_writeback_preserved(
        gui_dir, GUI_NUMBER, before_data, before_coords, 0)
    assert after["messages"][1]["trajectory"][1]["observation"]["extra_obs"] == "keep"


def test_legacy_entry_step_drift_recovered_by_center(tmp_path, qapp, coord_warnings):
    """条目 step 编号整体写歪但框本身正确：按 center 精确恢复，不报不一致。

    scroll 条目的 step 被写成 1（与 click 条目同号），按 step 查找落空后只能在
    未认领条目里验证 action + center，命中真实内容而不是列表位置。
    """
    entries = [
        {"step": 0, "action": "click", "vertices": [40, 140, 160, 260],
         "center": [100, 200], "round": 0},
        {"step": 1, "action": "click", "vertices": [20, 470, 100, 530],
         "center": [60, 500], "round": 0},
        {"step": 1, "action": "scroll", "vertices": [250, 350, 350, 450],
         "center": [300, 400], "round": 0},
    ]
    steps = [
        _click_step("点击搜索", (100, 200)),
        _click_step("点击输入框", (60, 500)),
        _scroll_step("上滑列表", (300, 400)),
    ]
    gui_dir, _data = _build_raw_dataset(str(tmp_path), steps, entries)
    editor = _make_editor(str(tmp_path), qapp)
    try:
        before_data, before_coords = open_edit_mode(editor, gui_dir, 0)

        assert editor.steps_data[0]["vertices"] == [40, 140, 160, 260]
        assert editor.steps_data[1]["vertices"] == [20, 470, 100, 530]
        # 漂移条目经 center 验证后正常载入，一步都没丢框
        assert editor.steps_data[2]["vertices"] == [250, 350, 350, 450]
        assert [s["coord_issue"] for s in editor.steps_data] == [None, None, None]
        assert editor._coord_issues == []
        assert coord_warnings == []
        assert "不一致" not in editor.status_label.text()

        assert editor.save_edited_round(False) is True
        assert_final_json_consistency(editor, gui_dir, expected_rounds=1)
    finally:
        _dispose(editor, qapp, allow_write=False)

    saved = _load_coords(gui_dir)
    assert [e["step"] for e in saved] == [0, 1, 2]
    assert saved[0]["vertices"] == [40, 140, 160, 260]
    assert saved[1]["vertices"] == [20, 470, 100, 530]
    # 恢复来的框以正确步序落盘：条目本身无多余键可比对整字典
    assert saved[2]["action"] == "scroll"
    assert saved[2]["vertices"] == [250, 350, 350, 450]
    assert saved[2]["center"] == [300, 400]

    assert_edit_writeback_preserved(
        gui_dir, GUI_NUMBER, before_data, before_coords, 0)


def test_center_mismatch_not_loaded_and_disk_entry_preserved(
        tmp_path, qapp, coord_warnings):
    """条目 step 对得上但 center 与坐标值差 >1px：不采信该框，原条目原样保留。

    「打开看一眼就保存」不得改变已交付 bbox——污染条目既不写回也不丢弃。
    """
    click_entry = {"step": 0, "action": "click", "vertices": [40, 140, 160, 260],
                   "center": [100, 200], "source": "coords-v1"}
    bad_scroll = {"step": 1, "action": "scroll", "vertices": [30, 300, 90, 360],
                  "center": [60, 330], "source": "coords-v1"}
    gui_dir, _data = _build_raw_dataset(
        str(tmp_path), [_click_step(), _scroll_step()], [click_entry, bad_scroll])
    editor = _make_editor(str(tmp_path), qapp)
    try:
        before_data, before_coords = open_edit_mode(editor, gui_dir, 0)

        assert editor.steps_data[0]["vertices"] == [40, 140, 160, 260]
        assert editor.steps_data[1]["vertices"] is None
        assert editor.steps_data[1]["coord_issue"] == "mismatch"
        assert editor.steps_data[1]["orig_coord_entry"] == bad_scroll
        assert len(editor._coord_issues) == 1
        assert editor._coord_issues[0][2] == "mismatch"
        assert any(title == "coords 与坐标值不一致"
                   for title, _text in coord_warnings)
        assert editor.validate_step_at(1) == []

        editor.intent_input.setText("只改动作描述")
        assert editor.save_edited_round(False) is True
        assert_final_json_consistency(editor, gui_dir, expected_rounds=1)
    finally:
        _dispose(editor, qapp, allow_write=False)

    saved = _load_coords(gui_dir)
    assert saved[0] == {**click_entry, "round": 0, "_version": "3.1"}
    # 污染条目按当前步序重编号后逐字段原样保留（不伪造新框、不静默丢数据）
    assert saved[1] == {**bad_scroll, "round": 0, "_version": "3.1"}

    after, _after_coords = assert_edit_writeback_preserved(
        gui_dir, GUI_NUMBER, before_data, before_coords, 0)
    assert after["messages"][1]["trajectory"][0]["intent"] == "只改动作描述"
    assert after["messages"][1]["trajectory"][1]["actions"][0]["coordinate"] == [300, 400]
    assert after["messages"][1]["trajectory"][1]["actions"][0]["pixels"] == -120
