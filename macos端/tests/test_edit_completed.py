# -*- coding: utf-8 -*-
"""「已完成任务可再次编辑」回归测试。

覆盖：从最终 JSON + coords 重建编辑现场、只替换被编辑轮次、编辑模式不写草稿、
关闭窗口自动写回、必填校验阻止保存、旧 coords 无 round 的多轮切分。
"""

import os
import copy
import json

from PyQt5.QtTest import QTest

import annotation_editor as _ae
import helpers as H


# ---------------------------------------------------------------------------
# 数据集构造
# ---------------------------------------------------------------------------
def _make_dataset(gui_number, with_round_field=False):
    """构造含 2 轮的最终 JSON 与对应 coords 扁平数组。

    第 0 轮：单框 left_click + 双框 left_click_drag；第 1 轮：单框 left_click。
    """
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
        "screen_size": [1920, 1080],
        "task_type": "Windows-测试",
        "messages": [
            {"role": "user", "instruction": "第一轮指令"},
            {"role": "assistant", "trajectory": round0},
            {"role": "user", "instruction": "第二轮指令"},
            {"role": "assistant", "trajectory": round1},
        ],
    }

    coords0 = [
        {"step": 0, "action": "left_click",
         "vertices": [100, 200, 300, 400], "center": [200, 300]},
        # 顶点必须与 center / JSON coordinate 满足 Product 口径 center = x + w//2
        # （INV-14：框中心 == coordinate）。编辑态 hydration 会拒采信不满足
        # 该不变式的条目，数据集本身就得是自洽的交付件
        {"step": 1, "action": "left_click_drag",
         "start_vertices": [10, 20, 40, 60], "start_center": [25, 40],
         "end_vertices": [100, 120, 120, 140], "end_center": [110, 130]},
    ]
    coords1 = [
        {"step": 0, "action": "left_click",
         "vertices": [500, 600, 700, 800], "center": [600, 700]},
    ]
    if with_round_field:
        for entry in coords0:
            entry["round"] = 0
        for entry in coords1:
            entry["round"] = 1

    return data, coords0 + coords1


def _write_dataset(editor, data, coords):
    """把最终 JSON 与 coords 写进 editor.data_manager 对应的 gui 目录"""
    gui = editor.gui_number
    gui_dir = os.path.join(editor.data_manager.current_dir, f"gui_{gui}")
    os.makedirs(gui_dir, exist_ok=True)
    with open(os.path.join(gui_dir, f"gui_{gui}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(gui_dir, f"gui_{gui}_coords.json"), "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)
    return gui_dir


def _prepare(editor, round_index, with_round_field=False):
    data, coords = _make_dataset(editor.gui_number, with_round_field=with_round_field)
    gui_dir = _write_dataset(editor, data, coords)
    editor.load_from_completed_json(data, coords, round_index, gui_dir)
    QTest.qWait(50)
    return data, coords, gui_dir


# ---------------------------------------------------------------------------
# 1. 单轮/多轮加载
# ---------------------------------------------------------------------------
def test_load_completed_round0(editor):
    data, coords, gui_dir = _prepare(editor, 0)

    assert editor._edit_mode is True
    assert len(editor.rounds) == 2
    assert editor.rounds[0]["instruction"] == "第一轮指令"
    assert editor.rounds[1]["instruction"] == "第二轮指令"
    assert "编辑已完成任务" in editor.windowTitle()
    assert "编辑已完成任务" in editor.status_label.text()

    assert len(editor.steps) == 2
    assert editor.steps[0]["screenshot_filename"] == f"gui_{editor.gui_number}_0001.png"
    assert editor.steps[0]["data"]["step"] == 0
    assert editor.steps[0]["rect_info"] == (100, 200, 200, 200)
    assert editor.steps[0]["selection_type"] is None

    assert editor.steps[1]["screenshot_filename"] == f"gui_{editor.gui_number}_0002.png"
    assert editor.steps[1]["data"]["step"] == 1
    assert editor.steps[1]["rect_info"] == ((10, 20, 30, 40), (100, 120, 20, 20))
    assert editor.steps[1]["selection_type"] == "drag"
    # hydration 未检出任何 bbox/coordinate 不一致（数据集是自洽交付件）
    assert editor._coord_issues == []

    # 表单回填与 JSON 一致
    assert editor.steps[0]["editor"].intent_input.text() == "第一轮点击"
    assert editor.steps[0]["editor"].coord_x_input.text() == "200"
    assert editor.steps[0]["editor"].coord_y_input.text() == "300"
    assert editor.steps[1]["editor"].end_coord_x_input.text() == "110"

    assert [len(group) for group in editor._coords_rounds] == [2, 1]


def test_load_completed_round1_legacy_coords(editor):
    """旧 coords 无 round 字段：step 回退切分，加载第 1 轮必须对应第 1 轮坐标"""
    data, coords, gui_dir = _prepare(editor, 1)

    assert len(editor.steps) == 1
    assert editor.steps[0]["screenshot_filename"] == f"gui_{editor.gui_number}_0003.png"
    assert editor.steps[0]["rect_info"] == (500, 600, 200, 200)
    assert editor.steps[0]["editor"].coord_x_input.text() == "600"
    assert [len(group) for group in editor._coords_rounds] == [2, 1]


def test_load_completed_round_field_grouping(editor):
    """coords 条目带 round 字段时按 round 分组"""
    data, coords, gui_dir = _prepare(editor, 1, with_round_field=True)
    assert [len(group) for group in editor._coords_rounds] == [2, 1]
    assert editor.steps[0]["rect_info"] == (500, 600, 200, 200)


# ---------------------------------------------------------------------------
# 2. 编辑第 0 轮保存：只替换该轮
# ---------------------------------------------------------------------------
def test_save_edited_round0_only_replaces_round0(editor):
    data, coords, gui_dir = _prepare(editor, 0)
    original = copy.deepcopy(data)

    editor.steps[0]["editor"].intent_input.setText("修改后的意图")
    assert editor.save_edited_round(silent=True) is True

    saved = H.read_final_json(editor)
    assert saved["messages"][0] == original["messages"][0]
    assert saved["messages"][1]["trajectory"][0]["intent"] == "修改后的意图"
    # 未暴露字段（status / element）保留
    assert saved["messages"][1]["trajectory"][0]["actions"][0]["status"] == "success"
    assert saved["messages"][1]["trajectory"][0]["actions"][0]["element"] == "按钮"
    # 其它轮次与顶层字段逐字段不变
    assert saved["messages"][2] == original["messages"][2]
    assert saved["messages"][3] == original["messages"][3]
    for key in ("platform", "system", "screen_size", "task_type"):
        assert saved[key] == original[key]

    saved_coords = H.read_final_coords(editor)
    # 4.2（B4/B18）写盘副本按所属轮次注入 round，其余字段逐字段不变
    assert saved_coords[-1] == {**coords[-1], "round": 1}


# ---------------------------------------------------------------------------
# 3. 编辑模式不写 draft
# ---------------------------------------------------------------------------
def test_edit_mode_never_writes_draft(editor):
    _prepare(editor, 0)

    editor.schedule_draft_save()
    QTest.qWait(1200)
    assert editor.data_manager.load_draft(editor.gui_number) is None

    # 直接调用立即写草稿入口同样被隔离
    editor._write_draft_now()
    assert editor.data_manager.load_draft(editor.gui_number) is None


# ---------------------------------------------------------------------------
# 4. 编辑模式关闭窗口自动写回
# ---------------------------------------------------------------------------
def test_edit_mode_close_writes_back(editor):
    data, coords, gui_dir = _prepare(editor, 0)

    editor.steps[0]["editor"].intent_input.setText("关闭前修改")
    editor.close()
    QTest.qWait(100)

    saved = H.read_final_json(editor)
    assert saved["messages"][1]["trajectory"][0]["intent"] == "关闭前修改"
    assert saved["messages"][3] == data["messages"][3]
    assert editor.data_manager.load_draft(editor.gui_number) is None


# ---------------------------------------------------------------------------
# 5. 缺项阻止保存
# ---------------------------------------------------------------------------
def test_missing_intent_blocks_save(editor, monkeypatch):
    data, coords, gui_dir = _prepare(editor, 0)
    original = copy.deepcopy(data)

    # ValidationFailDialog.exec_() 是模态阻塞，测试中替换为立即返回
    monkeypatch.setattr(_ae.ValidationFailDialog, "exec_", lambda self: 0)

    editor.steps[0]["editor"].intent_input.setText("")
    assert editor.save_edited_round(silent=False) is False

    assert H.read_final_json(editor) == original
    assert len(editor.steps) == 2
