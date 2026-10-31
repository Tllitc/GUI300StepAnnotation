# -*- coding: utf-8 -*-
"""已完成任务再编辑（iOS）回归测试。

覆盖:
  1. 从最终 JSON + coords 重建编辑现场（含旧 coords 无 round 的切分）
  2. 编辑某一轮后只替换该轮，其余轮与顶层字段不变；coords 仍为数组且带 round
  3. 编辑模式不写 draft
  4. 编辑模式直接关闭窗口自动写回
  5. 存在缺项时阻止保存，磁盘 JSON 不变
"""

import json
import os

import pytest

from PyQt5.QtWidgets import QApplication

from annotation_editor import AnnotationEditor
from data_manager import DataManager
from fakes import FakeScreenCapture


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
