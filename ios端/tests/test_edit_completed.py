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


def _build_dataset(base_dir, with_round=True, with_coords_file=True):
    """with_coords_file=False：只写最终 JSON 与 PNG，不写 coords.json
    （源数据集本就不含 coords.json 的合法场景）。"""
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
    if with_coords_file:
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


def _coords_path(gui_dir):
    return os.path.join(gui_dir, f"gui_{GUI_NUMBER}_coords.json")


def _load_coords(gui_dir):
    with open(_coords_path(gui_dir), "r", encoding="utf-8") as f:
        return json.load(f)


def _record_message_boxes(monkeypatch):
    """记录各级弹窗（在 autouse 的 auto_dialogs 之后打桩，逆序卸载自动还原）。"""
    calls = []

    def _recorder(kind):
        def _record(parent=None, title="", text="", *args, **kwargs):
            calls.append((kind, title, text))
            return None
        return _record

    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(_ae.QMessageBox, kind, _recorder(kind))
    return calls


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


# ----------------------------------------------------------------------
# 7. 已完成轮次编辑：受保护字段（CoT / active_window / ui_tree_segment /
#    element / status）与未知键保留，被编辑字段为新值，原始数据不被污染
# ----------------------------------------------------------------------

def _protected_dataset(base_dir):
    """单轮两步数据集：首步带非空受保护字段与未知键，供编辑保存回归。"""
    gui_dir = os.path.join(base_dir, GUI_DIR_NAME)
    os.makedirs(gui_dir, exist_ok=True)

    names = [f"gui_{GUI_NUMBER}_{i:04d}.png" for i in range(1, 3)]
    fake = FakeScreenCapture()
    for name in names:
        fake.capture(os.path.join(gui_dir, name))

    trajectory = [
        {
            "step": 0,
            "intent": "打开设置",
            "CoT": "下游已填的思维链",
            "unknown_step_key": "保留我",
            "observation": {
                "screenshot": names[0],
                "active_window": "设置主页",
                "ui_tree_segment": {"nodes": ["a", "b"]},
                "unknown_obs_key": 42,
            },
            "actions": [
                {
                    "action": "click",
                    "element": "设置图标",
                    "status": "success",
                    "coordinate": [100, 250],
                    "unknown_action_key": ["x", "y"],
                }
            ],
        },
        {
            "step": 1,
            "intent": "点击搜索",
            "CoT": "第二步思维链",
            "observation": {
                "screenshot": names[1],
                "active_window": "搜索页",
                "ui_tree_segment": {"nodes": ["c"]},
            },
            "actions": [
                {"action": "click", "element": "搜索框", "status": "success",
                 "coordinate": [200, 400]}
            ],
        },
    ]
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
    coords = [
        {"step": 0, "action": "click", "vertices": [50, 200, 150, 300],
         "center": [100, 250]},
        {"step": 1, "action": "click", "vertices": [150, 350, 250, 450],
         "center": [200, 400]},
    ]
    with open(os.path.join(gui_dir, f"gui_{GUI_NUMBER}.json"), "w",
              encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(gui_dir, f"gui_{GUI_NUMBER}_coords.json"), "w",
              encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)
    return gui_dir, data, coords


def test_save_edited_round_keeps_protected_fields_and_unknown_keys(tmp_path, qapp):
    gui_dir, data, coords = _protected_dataset(str(tmp_path))
    original_snapshot = copy.deepcopy(data)
    editor = _make_editor(str(tmp_path), qapp)
    try:
        editor.load_from_completed_json(data, coords, 0, gui_dir)

        # 编辑首步：改意图与坐标（动作仍是 click），再确认落表
        editor.intent_input.setText("打开设置-改")
        editor.coord_x_input.setText("111")
        editor.coord_y_input.setText("222")
        editor.confirm_step()
        qapp.processEvents()

        assert editor.save_edited_round(False) is True
        qapp.processEvents()

        # 编辑器内缓存的原始已完成数据不被保存流程污染
        assert editor._completed_json == original_snapshot
    finally:
        _dispose(editor, qapp, allow_write=False)

    saved = _load_json(gui_dir)
    traj = saved["messages"][1]["trajectory"]
    first = traj[0]

    # 受保护字段原样保留
    assert first["CoT"] == "下游已填的思维链"
    assert first["observation"]["active_window"] == "设置主页"
    assert first["observation"]["ui_tree_segment"] == {"nodes": ["a", "b"]}
    assert first["actions"][0]["element"] == "设置图标"
    assert first["actions"][0]["status"] == "success"
    # 未知键（步骤层 / observation 层 / action 层）深拷贝保留
    assert first["unknown_step_key"] == "保留我"
    assert first["observation"]["unknown_obs_key"] == 42
    assert first["actions"][0]["unknown_action_key"] == ["x", "y"]
    # 被编辑字段是新值
    assert first["intent"] == "打开设置-改"
    assert first["actions"][0]["coordinate"] == [111, 222]
    # 未编辑步骤逐字段不变
    assert traj[1] == data["messages"][1]["trajectory"][1]
    # 磁盘上的原始入参 data 也未被原地改写
    assert data == original_snapshot


# ----------------------------------------------------------------------
# 8. 草稿序列化：_serialize_step 全键透传，screenshot_filepath 排除规则不变
# ----------------------------------------------------------------------

def test_serialize_step_passes_through_optional_keys_and_drops_filepath():
    step = {
        "screenshot": "gui_000001_0001.png",
        "screenshot_filepath": os.path.join("C:", "abs", "path",
                                            "gui_000001_0001.png"),
        "intent": "打开设置",
        "action_data": {"action": "click", "coordinate": [1, 2]},
        "vertices": [0, 0, 10, 10],
        "CoT": "草稿思维链",
        "active_window": "设置页",
        "ui_tree_segment": {"nodes": [1]},
        "observation": {
            "active_window": "观察承载窗口",
            "ui_tree_segment": {"nodes": [2]},
        },
    }
    serialized = AnnotationEditor._serialize_step(step)

    # 全键透传（含平铺可选键与 observation dict 两种承载）
    assert serialized["CoT"] == "草稿思维链"
    assert serialized["active_window"] == "设置页"
    assert serialized["ui_tree_segment"] == {"nodes": [1]}
    assert serialized["observation"] == {
        "active_window": "观察承载窗口",
        "ui_tree_segment": {"nodes": [2]},
    }
    assert serialized["action_data"] == step["action_data"]
    # 运行态绝对路径永不落盘
    assert "screenshot_filepath" not in serialized
    assert serialized["screenshot"] == "gui_000001_0001.png"

    # 深拷贝隔离：改返回值不影响入参
    serialized["ui_tree_segment"]["nodes"].append(9)
    serialized["observation"]["ui_tree_segment"]["nodes"].append(9)
    assert step["ui_tree_segment"] == {"nodes": [1]}
    assert step["observation"]["ui_tree_segment"] == {"nodes": [2]}


def test_serialize_step_legacy_shape_stays_identical():
    """无可选键时序列化结果与旧格式逐字一致（仅剔除 screenshot_filepath）。"""
    step = {
        "screenshot": "gui_000001_0001.png",
        "screenshot_filepath": os.path.join("C:", "abs", "gui_000001_0001.png"),
        "intent": "点击",
        "action_data": {"action": "click", "coordinate": [1, 2]},
        "vertices": None,
    }
    serialized = AnnotationEditor._serialize_step(step)
    assert serialized == {
        "screenshot": "gui_000001_0001.png",
        "intent": "点击",
        "action_data": {"action": "click", "coordinate": [1, 2]},
        "vertices": None,
    }
    assert "CoT" not in serialized
    assert "active_window" not in serialized
    assert "ui_tree_segment" not in serialized
    assert "observation" not in serialized


# ----------------------------------------------------------------------
# 9. 落轮透传：_save_current_round_to_list 的 .get 三字段透传
# ----------------------------------------------------------------------

def _bare_editor():
    """绕过 QWidget 初始化的裸实例，仅用于不依赖 UI 状态的纯数据方法。"""
    return AnnotationEditor.__new__(AnnotationEditor)


def test_save_current_round_to_list_passes_optional_fields_through(tmp_path, qapp):
    gui_dir, _data, _coords = _protected_dataset(str(tmp_path))
    editor = _make_editor(str(tmp_path), qapp)
    try:
        editor.task_instruction = "落轮指令"
        editor.rounds = []
        editor.steps_data = [
            {
                "screenshot": "gui_000001_0001.png",
                "screenshot_filepath": os.path.join(
                    gui_dir, "gui_000001_0001.png"),
                "intent": "带透传字段的步",
                "action_data": {"action": "click", "coordinate": [1, 2],
                                "element": "图标", "status": "success"},
                "vertices": [0, 0, 10, 10],
                "CoT": "落轮思维链",
                "active_window": "平铺窗口",
                "ui_tree_segment": {"nodes": ["t"]},
            },
            {
                "screenshot": "gui_000001_0002.png",
                "screenshot_filepath": os.path.join(
                    gui_dir, "gui_000001_0002.png"),
                "intent": "observation 承载的步",
                "action_data": {"action": "terminate", "element": "",
                                "status": "success"},
                "vertices": None,
                "observation": {
                    "active_window": "dict 窗口",
                    "ui_tree_segment": {"nodes": ["o"]},
                },
            },
        ]
        # 落轮尾部会立即写草稿，编辑模式下直接短路，不产生磁盘文件
        editor._edit_mode = True

        assert editor._save_current_round_to_list(False) is True

        assert len(editor.rounds) == 1
        traj = editor.rounds[0]["trajectory"]
        assert traj[0]["CoT"] == "落轮思维链"
        assert traj[0]["observation"]["active_window"] == "平铺窗口"
        assert traj[0]["observation"]["ui_tree_segment"] == {"nodes": ["t"]}
        assert traj[1]["CoT"] == ""
        assert traj[1]["observation"]["active_window"] == "dict 窗口"
        assert traj[1]["observation"]["ui_tree_segment"] == {"nodes": ["o"]}
        # 结构固定，不引入额外键
        for entry in traj:
            assert set(entry.keys()) == {"step", "intent", "CoT",
                                         "observation", "actions"}
            assert set(entry["observation"].keys()) == {
                "screenshot", "active_window", "ui_tree_segment"}
        assert editor.steps_data == []
    finally:
        _dispose(editor, qapp, allow_write=False)


def test_save_current_round_to_list_defaults_to_empty_strings(tmp_path, qapp):
    editor = _make_editor(str(tmp_path), qapp)
    try:
        editor.task_instruction = "无透传字段指令"
        editor.rounds = []
        editor.steps_data = [
            {
                "screenshot": "gui_000001_0001.png",
                "screenshot_filepath": "",
                "intent": "裸步",
                "action_data": {"action": "click", "coordinate": [1, 2]},
                "vertices": None,
            },
        ]
        editor._edit_mode = True

        assert editor._save_current_round_to_list(False) is True

        entry = editor.rounds[0]["trajectory"][0]
        assert entry["CoT"] == ""
        assert entry["observation"]["active_window"] == ""
        assert entry["observation"]["ui_tree_segment"] == ""
        assert set(entry.keys()) == {"step", "intent", "CoT",
                                     "observation", "actions"}
    finally:
        _dispose(editor, qapp, allow_write=False)


# ----------------------------------------------------------------------
# 10. 终止类专项：terminate / answer 编辑保存后 element==""、status=="success"，
#     步骤级三字段仍保留
# ----------------------------------------------------------------------

def _terminate_dataset(base_dir):
    gui_dir = os.path.join(base_dir, GUI_DIR_NAME)
    os.makedirs(gui_dir, exist_ok=True)

    names = [f"gui_{GUI_NUMBER}_{i:04d}.png" for i in range(1, 3)]
    fake = FakeScreenCapture()
    for name in names:
        fake.capture(os.path.join(gui_dir, name))

    trajectory = [
        {
            "step": 0,
            "intent": "任务收尾",
            "CoT": "终止步思维链",
            "observation": {
                "screenshot": names[0],
                "active_window": "终态窗口",
                "ui_tree_segment": {"nodes": ["term"]},
            },
            "actions": [
                {"action": "terminate", "element": "", "status": "success"}
            ],
        },
        {
            "step": 1,
            "intent": "回答问题",
            "CoT": "回答步思维链",
            "observation": {
                "screenshot": names[1],
                "active_window": "问答窗口",
                "ui_tree_segment": {"nodes": ["ans"]},
            },
            "actions": [
                {"action": "answer", "text": "最终答案", "element": "",
                 "status": "success"}
            ],
        },
    ]
    data = {
        "platform": "iOS",
        "system": "iOS 17.0",
        "screen_size": [390, 844],
        "task_type": "iOS-社交",
        "messages": [
            {"role": "user", "instruction": "终止类轮次"},
            {"role": "assistant", "trajectory": trajectory},
        ],
    }
    coords = [
        {"step": 0, "action": "terminate"},
        {"step": 1, "action": "answer", "center": [0, 0]},
    ]
    with open(os.path.join(gui_dir, f"gui_{GUI_NUMBER}.json"), "w",
              encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(gui_dir, f"gui_{GUI_NUMBER}_coords.json"), "w",
              encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)
    return gui_dir, data, coords


def test_terminate_and_answer_keep_empty_element_success_status(tmp_path, qapp):
    gui_dir, data, coords = _terminate_dataset(str(tmp_path))
    editor = _make_editor(str(tmp_path), qapp)
    try:
        editor.load_from_completed_json(data, coords, 0, gui_dir)

        # 首步 terminate：仅改意图后确认，动作仍为 terminate
        assert (editor.action_combo.currentData()
                or editor.action_combo.currentText()) in (
            "terminate", "任务完成 (terminate)")
        editor.intent_input.setText("任务收尾-改")
        editor.confirm_step()
        qapp.processEvents()

        # 第二步 answer：改回答文本
        editor.jump_to_step(1)
        qapp.processEvents()
        editor.text_input.setText("更新后的答案")
        editor.confirm_step()
        qapp.processEvents()

        assert editor.save_edited_round(False) is True
        qapp.processEvents()
    finally:
        _dispose(editor, qapp, allow_write=False)

    traj = _load_json(gui_dir)["messages"][1]["trajectory"]
    term_action = traj[0]["actions"][0]
    ans_action = traj[1]["actions"][0]
    assert term_action["action"] == "terminate"
    assert term_action["element"] == ""
    assert term_action["status"] == "success"
    assert ans_action["action"] == "answer"
    assert ans_action["element"] == ""
    assert ans_action["status"] == "success"
    assert ans_action["text"] == "更新后的答案"
    # 步骤级三字段仍保留
    assert traj[0]["CoT"] == "终止步思维链"
    assert traj[0]["observation"]["active_window"] == "终态窗口"
    assert traj[0]["observation"]["ui_tree_segment"] == {"nodes": ["term"]}
    assert traj[1]["CoT"] == "回答步思维链"
    assert traj[1]["observation"]["active_window"] == "问答窗口"
    assert traj[1]["observation"]["ui_tree_segment"] == {"nodes": ["ans"]}


# ----------------------------------------------------------------------
# 11. _merge_original_missing 直接单测：空值回退 / 非空覆盖 / 非原地 /
#     深拷贝隔离 / actions 超长下标保留
# ----------------------------------------------------------------------

def test_merge_protected_empty_values_fall_back_to_original():
    editor = _bare_editor()
    old = {
        "CoT": "原 CoT",
        "observation": {
            "active_window": "原窗口",
            "ui_tree_segment": {"nodes": [1]},
        },
        "actions": [
            {"element": "原元素", "status": "原状态", "action": "click"},
        ],
    }
    new = {
        "CoT": "",
        "observation": {
            "active_window": None,
            "ui_tree_segment": {},
        },
        "actions": [
            {"element": "", "status": "", "action": "click"},
        ],
    }
    merged = editor._merge_original_missing(
        new, old, AnnotationEditor._PROTECTED_STEP_KEYS)

    assert merged["CoT"] == "原 CoT"
    assert merged["observation"]["active_window"] == "原窗口"
    assert merged["observation"]["ui_tree_segment"] == {"nodes": [1]}
    assert merged["actions"][0]["element"] == "原元素"
    assert merged["actions"][0]["status"] == "原状态"


def test_merge_protected_non_empty_values_override():
    editor = _bare_editor()
    old = {
        "CoT": "原 CoT",
        "observation": {
            "active_window": "原窗口",
            "ui_tree_segment": {"nodes": [1]},
        },
        "actions": [
            {"element": "原元素", "status": "原状态",
             "action": "click", "coordinate": [1, 1]},
        ],
    }
    new = {
        "CoT": "新 CoT",
        "observation": {
            "active_window": "新窗口",
            "ui_tree_segment": {"nodes": [2]},
        },
        "actions": [
            {"element": "新元素", "status": "新状态",
             "action": "click", "coordinate": [2, 2]},
        ],
    }
    merged = editor._merge_original_missing(
        new, old, AnnotationEditor._PROTECTED_STEP_KEYS)

    assert merged["CoT"] == "新 CoT"
    assert merged["observation"]["active_window"] == "新窗口"
    assert merged["observation"]["ui_tree_segment"] == {"nodes": [2]}
    assert merged["actions"][0]["element"] == "新元素"
    assert merged["actions"][0]["status"] == "新状态"
    assert merged["actions"][0]["coordinate"] == [2, 2]


def test_merge_does_not_mutate_inputs_and_deep_copies():
    editor = _bare_editor()
    old = {
        "CoT": "原 CoT",
        "unknown": {"nested": [1, 2]},
        "observation": {"active_window": "原窗口",
                        "ui_tree_segment": {"nodes": [1]}},
        "actions": [
            {"element": "原元素", "status": "s", "action": "click",
             "extra": {"k": ["v"]}},
            {"element": "超长下标元素", "status": "s2", "action": "scroll"},
        ],
    }
    old_snapshot = copy.deepcopy(old)
    new = {
        "CoT": "",
        "observation": {"active_window": "", "ui_tree_segment": ""},
        "actions": [
            {"element": "", "status": "", "action": "click"},
        ],
    }
    new_snapshot = copy.deepcopy(new)

    merged = editor._merge_original_missing(
        new, old, AnnotationEditor._PROTECTED_STEP_KEYS)

    # 入参原样不动
    assert old == old_snapshot
    assert new == new_snapshot

    # old 有 new 无的键深拷贝保留
    assert merged["unknown"] == {"nested": [1, 2]}
    # actions 超长下标元素深拷贝保留
    assert len(merged["actions"]) == 2
    assert merged["actions"][1] == {
        "element": "超长下标元素", "status": "s2", "action": "scroll"}

    # 深拷贝隔离：改 merged 不回写 old/new
    merged["unknown"]["nested"].append(3)
    merged["observation"]["ui_tree_segment"]["nodes"].append(9)
    merged["actions"][0]["extra"]["k"].append("mutated")
    merged["actions"][1]["element"] = "被改了"
    assert old["unknown"] == {"nested": [1, 2]}
    assert old["observation"]["ui_tree_segment"] == {"nodes": [1]}
    assert old["actions"][0]["extra"] == {"k": ["v"]}
    assert old["actions"][1]["element"] == "超长下标元素"
    assert new == new_snapshot


def test_merge_non_dict_falls_back_to_new_value():
    editor = _bare_editor()
    # 标量场景：以新值为准（深拷贝）
    assert editor._merge_original_missing("新", "旧") == "新"
    assert editor._merge_original_missing(None, "旧") is None
    # 空 list / 空 dict 的受保护空值判定
    assert AnnotationEditor._is_empty_protected_value(None) is True
    assert AnnotationEditor._is_empty_protected_value("") is True
    assert AnnotationEditor._is_empty_protected_value({}) is True
    assert AnnotationEditor._is_empty_protected_value([]) is True
    assert AnnotationEditor._is_empty_protected_value(0) is False
    assert AnnotationEditor._is_empty_protected_value("x") is False
    assert AnnotationEditor._is_empty_protected_value({"a": 1}) is False


# ----------------------------------------------------------------------
# 12. 草稿往返：_write_draft_now -> data_manager.load_draft 保留三字段；
#     无可选键时磁盘结构不新增键（与修复前逐字一致）
# ----------------------------------------------------------------------

def _new_draft_editor(base_dir, qapp):
    """构造非编辑态编辑器，仅供草稿写盘/读盘（不初始化新任务目录）。"""
    editor = _make_editor(base_dir, qapp)
    editor.gui_number = GUI_NUMBER
    editor.gui_dir = os.path.join(base_dir, GUI_DIR_NAME)
    return editor


def test_draft_optional_keys_round_trip_flat_and_observation(tmp_path, qapp):
    """草稿写盘/读盘对称保留 CoT / active_window / ui_tree_segment。

    编辑已完成轮次时这三字段来自下游 JSON；草稿序列化一旦丢弃它们，断点续采
    后再次保存就会用空值覆盖下游结果，正是本次修复要堵住的数据丢失路径。
    """
    gui_dir = os.path.join(str(tmp_path), GUI_DIR_NAME)
    os.makedirs(gui_dir, exist_ok=True)

    flat_step = {
        "screenshot": "gui_000001_0001.png",
        "screenshot_filepath": os.path.join(gui_dir, "gui_000001_0001.png"),
        "intent": "平铺承载步",
        "action_data": {"action": "click", "coordinate": [1, 2],
                        "element": "图标", "status": "success"},
        "vertices": [0, 0, 10, 10],
        "CoT": "平铺 CoT",
        "active_window": "平铺窗口",
        "ui_tree_segment": {"nodes": ["flat"]},
    }
    obs_step = {
        "screenshot": "gui_000001_0002.png",
        "screenshot_filepath": os.path.join(gui_dir, "gui_000001_0002.png"),
        "intent": "observation 承载步",
        "action_data": {"action": "terminate", "element": "",
                        "status": "success"},
        "vertices": None,
        "observation": {
            "active_window": "dict 窗口",
            "ui_tree_segment": {"nodes": ["obs"]},
        },
    }

    editor = _new_draft_editor(str(tmp_path), qapp)
    try:
        editor.task_instruction = "草稿指令"
        editor.steps_data = [copy.deepcopy(flat_step), copy.deepcopy(obs_step)]
        # 无当前截图：_write_draft_now 全量按 steps_data 序列化，不掺入空表单
        editor._current_screenshot_filename = None
        editor.draft_timer.stop()

        editor._write_draft_now()
        qapp.processEvents()

        draft = editor.data_manager.load_draft(GUI_NUMBER)
        assert draft is not None
        written = draft["steps_data"]
        # 平铺三字段与 observation dict 两种承载都原样落盘
        assert written[0]["CoT"] == "平铺 CoT"
        assert written[0]["active_window"] == "平铺窗口"
        assert written[0]["ui_tree_segment"] == {"nodes": ["flat"]}
        assert written[1]["observation"] == {
            "active_window": "dict 窗口",
            "ui_tree_segment": {"nodes": ["obs"]},
        }
        # 运行态绝对路径永不落盘
        for step in written:
            assert "screenshot_filepath" not in step
    finally:
        _dispose(editor, qapp, allow_write=False)


def test_draft_without_optional_keys_keeps_legacy_shape(tmp_path, qapp):
    """条目本身不带可选键时，写盘结果不新增这些键（与修复前逐字一致）。"""
    gui_dir = os.path.join(str(tmp_path), GUI_DIR_NAME)
    os.makedirs(gui_dir, exist_ok=True)

    legacy_step = {
        "screenshot": "gui_000001_0001.png",
        "intent": "旧格式步",
        "action_data": {"action": "click", "coordinate": [1, 2]},
        "vertices": None,
    }

    editor = _new_draft_editor(str(tmp_path), qapp)
    try:
        editor.task_instruction = "旧格式草稿"
        editor.steps_data = [copy.deepcopy(legacy_step)]
        editor._current_screenshot_filename = None
        editor.draft_timer.stop()

        editor._write_draft_now()
        qapp.processEvents()

        draft = editor.data_manager.load_draft(GUI_NUMBER)
        assert draft is not None
        assert draft["steps_data"] == [legacy_step]
        for step in draft["steps_data"]:
            assert "CoT" not in step
            assert "active_window" not in step
            assert "ui_tree_segment" not in step
            assert "observation" not in step
    finally:
        _dispose(editor, qapp, allow_write=False)


# ----------------------------------------------------------------------
# 13. 源数据集不含 coords.json：不逐步告警、不生成文件，拉框只更新最终 JSON
# ----------------------------------------------------------------------

_MISSING_COORDS_INFO = (
    "该数据集不含 coords.json：编辑只更新最终 JSON，不会生成 coords.json；"
    "拉框仅更新最终 JSON 的 coordinate。"
)


def test_missing_coords_open_single_information_only(tmp_path, qapp, monkeypatch):
    """缺失是合法态：只弹一条 information，不判 absent/mismatch、不追加状态栏告警。"""
    calls = _record_message_boxes(monkeypatch)
    gui_dir, _data, _coords = _build_dataset(str(tmp_path), with_coords_file=False)
    editor = _make_editor(str(tmp_path), qapp)
    try:
        open_edit_mode(editor, gui_dir, 0)

        assert editor._original_coords_exist is False
        assert editor._coord_issues == []
        assert [c for c in calls if c[0] in ("warning", "critical")] == []
        infos = [c for c in calls if c[0] == "information"]
        assert len(infos) == 1
        assert infos[0][2] == _MISSING_COORDS_INFO
        assert "⚠" not in editor.status_label.text()

        # 无框可载入：coordinate 如实来自最终 JSON，且允许在原图重新拉框
        assert [s["vertices"] for s in editor.steps_data] == [None, None]
        assert [s["coord_issue"] for s in editor.steps_data] == [None, None]
        assert editor.steps_data[0]["action_data"]["coordinate"] == [100, 250]
        assert editor.steps_data[1]["action_data"]["coordinate"] == [200, 400]
        assert editor.coord_x_input.text() == "100"
        assert editor.coord_y_input.text() == "250"
        # 无框不阻塞编辑：只豁免「框」这一项，坐标照常校验
        assert editor.validate_step_at(0) == []
        assert editor.validate_step_at(1) == []
    finally:
        _dispose(editor, qapp, allow_write=False)


def test_missing_coords_text_only_save_no_coords_generated(tmp_path, qapp, monkeypatch):
    """仅改文本后正常保存：最终 JSON 更新，绝不凭空生成 coords.json。"""
    calls = _record_message_boxes(monkeypatch)
    gui_dir, data, _coords = _build_dataset(str(tmp_path), with_coords_file=False)
    editor = _make_editor(str(tmp_path), qapp)
    try:
        open_edit_mode(editor, gui_dir, 0)
        editor.intent_input.setText("打开设置-仅改文本")

        assert editor.save_edited_round(False) is True
        qapp.processEvents()
        assert [c for c in calls if c[0] in ("warning", "critical")] == []
    finally:
        _dispose(editor, qapp, allow_write=False)

    saved = _load_json(gui_dir)
    traj = saved["messages"][1]["trajectory"]
    assert traj[0]["intent"] == "打开设置-仅改文本"
    assert traj[0]["actions"][0]["coordinate"] == [100, 250]
    assert traj[1] == data["messages"][1]["trajectory"][1]
    assert saved["messages"][3] == data["messages"][3]
    assert not os.path.exists(_coords_path(gui_dir))


def test_missing_coords_relabel_updates_coordinate_without_coords_file(tmp_path, qapp):
    """新拉框只更新最终 JSON 的 coordinate，仍不生成 coords.json。"""
    gui_dir, data, _coords = _build_dataset(str(tmp_path), with_coords_file=False)
    editor = _make_editor(str(tmp_path), qapp)
    try:
        open_edit_mode(editor, gui_dir, 0)

        # 走真实[重新拉框]入口：在原图上拖出新框并应用（不重新截图、不覆盖 PNG）
        editor.relabel_current_step()
        qapp.processEvents()
        dialog = editor._relabel_dialog
        assert dialog is not None, "不含 coords.json 时同样应允许重新拉框"
        dialog.canvas.rect_drawn.emit(400, 500, 600, 700)
        qapp.processEvents()
        dialog.apply()
        qapp.processEvents()

        assert editor._current_vertices == [400, 500, 600, 700]
        assert editor.save_edited_round(True) is True
        qapp.processEvents()
    finally:
        _dispose(editor, qapp, allow_write=False)

    traj = _load_json(gui_dir)["messages"][1]["trajectory"]
    assert traj[0]["actions"][0]["coordinate"] == [500, 600]
    assert traj[1] == data["messages"][1]["trajectory"][1]
    assert not os.path.exists(_coords_path(gui_dir))


def test_missing_coords_close_silent_writeback(tmp_path, qapp):
    """直接关闭窗口走静默写回：同口径只更新最终 JSON，不生成 coords.json。"""
    gui_dir, data, _coords = _build_dataset(str(tmp_path), with_coords_file=False)
    editor = _make_editor(str(tmp_path), qapp)
    open_edit_mode(editor, gui_dir, 1)

    editor.intent_input.setText("关闭前修改")
    editor.close()
    qapp.processEvents()

    saved = _load_json(gui_dir)
    assert saved["messages"][3]["trajectory"][0]["intent"] == "关闭前修改"
    assert saved["messages"][1] == data["messages"][1]
    assert not os.path.exists(_coords_path(gui_dir))

    editor.deleteLater()
    qapp.processEvents()


def test_empty_coords_file_exists_b41_preserved(tmp_path, qapp, monkeypatch, capsys):
    """空数组 coords 文件按「存在」处理：照常判 absent/告警；B41 保留原文件。"""
    calls = _record_message_boxes(monkeypatch)
    gui_dir, _data = _build_raw_dataset(
        str(tmp_path), [_click_step(), _click_step("点击结果", (180, 500))], [])
    editor = _make_editor(str(tmp_path), qapp)
    try:
        open_edit_mode(editor, gui_dir, 0)

        assert editor._original_coords_exist is True
        assert [c for c in calls if c[0] == "information"] == []
        assert [issue[2] for issue in editor._coord_issues] == ["absent", "absent"]
        assert any(title == "coords 与坐标值不一致"
                   for kind, title, _text in calls if kind == "warning")

        # 删空本轮步骤 → 写回收集 0 条坐标：告警并跳过写入，原文件逐字保留
        editor.delete_current_step(confirm_dialog=False)
        editor.delete_current_step(confirm_dialog=False)
        assert editor.steps_data == []
        capsys.readouterr()
        assert editor.save_edited_round(True) is True
        assert "已跳过 coords 写入以保留原文件" in capsys.readouterr().out
    finally:
        _dispose(editor, qapp, allow_write=False)

    assert _load_coords(gui_dir) == []
