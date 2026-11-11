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
        {"step": 1, "action": "left_click_drag",
         "start_vertices": [10, 20, 40, 60], "start_center": [25, 40],
         "end_vertices": [100, 120, 150, 180], "end_center": [110, 130]},
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
    assert editor.steps[1]["rect_info"] == ((10, 20, 30, 40), (100, 120, 50, 60))
    assert editor.steps[1]["selection_type"] == "drag"

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
    assert saved_coords[-1] == coords[-1]


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


# ---------------------------------------------------------------------------
# 回归：编辑已完成任务 / 草稿续采时，编辑器不采集的下游字段不被空值覆盖
#
# 缺陷背景：这两条路径都会用 StepEditorWidget.get_data() 重建步骤字典——
# ui_tree_segment 没有表单控件、非终止动作的 status 根本不在重建结果里、
# 下游标注附加的未知键更不会被重建。旧实现用新字典整体覆盖原步骤，导致
# 打开并保存一次就把这些字段静默清空。修复后由 _merge_step_with_original
# 做字段级合并，下面三条用例分别从「编辑已完成」「终止动作业务规则」
# 「草稿续采实时重建」三个入口做端到端回归。
# ---------------------------------------------------------------------------
def _regression_single_round(gui_number, action_data, instruction="回归单轮指令"):
    """构造 1 轮最终 JSON 的单步轨迹（macOS 测试不需要真实 PNG 文件）。"""
    shot = f"gui_{gui_number}_0001.png"
    return {
        "platform": "Windows 11",
        "system": "Windows 11",
        "screen_size": [1920, 1080],
        "task_type": "Windows-测试",
        "messages": [
            {"role": "user", "instruction": instruction},
            {"role": "assistant", "trajectory": [{
                "step": 0,
                "intent": "步骤0",
                "CoT": "",
                "observation": {
                    "screenshot": shot,
                    "active_window": "测试App",
                    "ui_tree_segment": "",
                },
                "actions": [action_data],
            }]},
        ],
    }


def _assert_downstream_fields_preserved(step, cot, window, ui_tree):
    """受保护下游字段逐字等于原值（CoT / active_window / ui_tree_segment）。"""
    assert step["CoT"] == cot
    assert step["observation"]["active_window"] == window
    assert step["observation"]["ui_tree_segment"] == ui_tree


def test_edit_completed_intent_only_change_keeps_protected_and_unknown_keys(editor):
    """用例 A：编辑已完成任务只改 intent，下游受保护字段与三层未知键原样保留。

    三个层级的未知键（步骤级 / observation / actions[0]）都不在编辑器重建
    结果里，必须由合并逻辑从原步骤补齐；受保护字段则要逐字等于原值，
    而不是被重建字典的空值或表单回填值覆盖。
    """
    gui = editor.gui_number
    data = _regression_single_round(gui, {
        "action": "left_click",
        "coordinate": [200, 300],
        "element": "",
        "status": "success",
    })
    original_step = data["messages"][1]["trajectory"][0]
    original_step["CoT"] = "下游CoT"
    original_step["observation"]["active_window"] = "下游窗口"
    original_step["observation"]["ui_tree_segment"] = "下游UI树片段"
    original_step["actions"][0]["element"] = "下游元素"
    original_step["actions"][0]["status"] = "success"
    original_step["extra_step_key"] = {"a": 1}
    original_step["observation"]["extra_obs_key"] = "keep"
    original_step["actions"][0]["extra_action_key"] = [1, 2]
    expected_step = copy.deepcopy(original_step)

    coords = [{"step": 0, "action": "left_click",
               "vertices": [100, 200, 300, 400], "center": [200, 300]}]
    gui_dir = _write_dataset(editor, data, coords)
    assert editor.load_from_completed_json(data, coords, 0, gui_dir) is True
    QTest.qWait(50)

    editor.steps[0]["editor"].intent_input.setText("只改意图")
    assert editor.save_edited_round(silent=True) is True

    saved_step = H.read_final_json(editor)["messages"][1]["trajectory"][0]
    assert saved_step["intent"] == "只改意图"
    _assert_downstream_fields_preserved(
        saved_step, "下游CoT", "下游窗口", "下游UI树片段")
    assert saved_step["actions"][0]["element"] == "下游元素"
    assert saved_step["actions"][0]["status"] == "success"
    assert saved_step["extra_step_key"] == {"a": 1}
    assert saved_step["observation"]["extra_obs_key"] == "keep"
    assert saved_step["actions"][0]["extra_action_key"] == [1, 2]
    # 逐字段对照原步骤：三层未知键的值与类型都不被改写
    assert saved_step["extra_step_key"] == expected_step["extra_step_key"]
    assert saved_step["observation"]["extra_obs_key"] \
        == expected_step["observation"]["extra_obs_key"]
    assert saved_step["actions"][0]["extra_action_key"] \
        == expected_step["actions"][0]["extra_action_key"]


def test_edit_completed_terminal_step_forces_element_and_status(editor):
    """用例 B：终止类动作保存后 element 强制为空、status 强制 success。

    终止动作不采集元素（历史残留的 element 必须清掉），失败状态也不能带进
    已完成任务交付件；同时 CoT/active_window/ui_tree_segment 仍按保留规则
    沿用原值，不能被终止规则连带清空。
    """
    gui = editor.gui_number
    data = _regression_single_round(gui, {
        "action": "terminate",
        "element": "残留元素",
        "status": "failed",
    })
    terminal_step = data["messages"][1]["trajectory"][0]
    terminal_step["CoT"] = "终止步CoT"
    terminal_step["observation"]["active_window"] = "终止步窗口"
    terminal_step["observation"]["ui_tree_segment"] = "终止步UI树片段"

    # terminate 无坐标，coords 给空数组即可
    gui_dir = _write_dataset(editor, data, [])
    assert editor.load_from_completed_json(data, [], 0, gui_dir) is True
    QTest.qWait(50)
    assert len(editor.steps) == 1

    assert editor.save_edited_round(silent=True) is True

    saved_step = H.read_final_json(editor)["messages"][1]["trajectory"][0]
    assert saved_step["actions"][0]["action"] == "terminate"
    assert saved_step["actions"][0]["element"] == ""
    assert saved_step["actions"][0]["status"] == "success"
    _assert_downstream_fields_preserved(
        saved_step, "终止步CoT", "终止步窗口", "终止步UI树片段")


def test_draft_resume_save_current_step_keeps_protected_fields(editor):
    """用例 C：草稿续采——save_current_step 与 _write_draft_now 两次重建步骤
    字典都不得清空草稿里的 CoT/active_window/ui_tree_segment。

    草稿的 current_steps[].data 是下游字段的唯一载体：确认保存后内存快照要
    保留，_write_draft_now 落盘后的草稿也要保留，否则续采一次就永久丢字段。
    """
    gui = editor.gui_number
    shot = f"gui_{gui}_0001.png"

    draft = {
        "gui_number": gui,
        "app_name": editor.app_name,
        "task_instruction": "续采指令",
        "screen_info": editor.screen_info,
        "app_type": editor.app_type,
        "rounds": [],
        "current_steps": [{
            "screenshot_filename": shot,
            "rect_info": [100, 200, 200, 200],
            "selection_type": None,
            "data": {
                "step": 0,
                "intent": "草稿原始意图",
                "CoT": "草稿CoT",
                "observation": {
                    "screenshot": shot,
                    "active_window": "草稿窗口",
                    "ui_tree_segment": "草稿UI树片段",
                },
                "actions": [{
                    "action": "left_click",
                    "coordinate": [200, 300],
                    "element": "草稿元素",
                    "status": "success",
                }],
            },
        }],
        "coords_entries": [],
        "updated_at": "2026-01-01T00:00:00",
    }
    assert editor.data_manager.save_draft(draft, gui)
    restored = editor.data_manager.load_draft(gui)
    assert restored is not None

    editor.load_from_draft(restored)
    QTest.qWait(100)
    assert len(editor.steps) == 1

    editor.steps[0]["editor"].intent_input.setText("续采后的新意图")
    H.save_current(editor)

    # 内存快照：结构为 {..., "data": {...}}
    saved_step = editor.steps[0]["data"]
    assert saved_step["intent"] == "续采后的新意图"
    _assert_downstream_fields_preserved(
        saved_step, "草稿CoT", "草稿窗口", "草稿UI树片段")

    editor._write_draft_now()
    QTest.qWait(50)

    disk_step = H.read_draft(editor)["current_steps"][0]["data"]
    assert disk_step["intent"] == "续采后的新意图"
    _assert_downstream_fields_preserved(
        disk_step, "草稿CoT", "草稿窗口", "草稿UI树片段")
    # 落草稿后内存快照同样保留
    _assert_downstream_fields_preserved(
        editor.steps[0]["data"], "草稿CoT", "草稿窗口", "草稿UI树片段")
