# -*- coding: utf-8 -*-
"""「已完成任务可再次编辑」回归测试。

覆盖：从最终 JSON + coords 重建编辑现场、只替换被编辑轮次、编辑模式不写草稿、
关闭窗口自动写回、必填校验阻止保存、旧 coords 无 round 的多轮切分。
"""

import os
import copy
import json

import pytest
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtTest import QTest

import annotation_editor as _ae
import helpers as H
import invariants as I


# ---------------------------------------------------------------------------
# 数据集构造
# ---------------------------------------------------------------------------
def _make_dataset(gui_number, with_round_field=False, with_coords_file=True):
    """构造含 2 轮的最终 JSON 与对应 coords 扁平数组。

    第 0 轮：单框 left_click + 双框 left_click_drag；第 1 轮：单框 left_click。
    with_coords_file=False：构造「不含 coords.json」的数据集（返回空条目列表，
    落盘时配合 _write_dataset(write_coords=False) 不写 coords 文件）。
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

    if not with_coords_file:
        return data, []
    return data, coords0 + coords1


def _write_dataset(editor, data, coords, write_coords=True):
    """把最终 JSON 与 coords 写进 editor.data_manager 对应的 gui 目录

    write_coords=False：不写 coords 文件（构造「不含 coords.json」的数据集）。
    """
    gui = editor.gui_number
    gui_dir = os.path.join(editor.data_manager.current_dir, f"gui_{gui}")
    os.makedirs(gui_dir, exist_ok=True)
    with open(os.path.join(gui_dir, f"gui_{gui}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if write_coords:
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


# ---------------------------------------------------------------------------
# 缺失 coords.json 合法态回归（fix-missing-coords-on-edit）
#
# 缺陷背景：不含 coords.json 的数据集打开时被当成「数据不一致」逐步弹 absent
# 告警；保存时又用内存重建的 coords 写盘，生成只含被编辑轮少数条目的部分
# coords.json。修复后：缺失是合法态——打开仅一条信息性提示；保存（含 silent
# 关闭写回）无条件不生成 coords.json，拉框只更新最终 JSON 的 coordinate。
# ---------------------------------------------------------------------------
def _write_dataset_shots(gui_dir, data):
    """补写 trajectory 引用的真实 PNG：截图缺失会另弹告警干扰弹窗计数，
    且「在原图重新拉框」要求 load_screenshot 能读到磁盘原图。"""
    shots = []
    for message in data.get("messages", []):
        if message.get("role") != "assistant":
            continue
        for entry in message.get("trajectory", []):
            shot = (entry.get("observation") or {}).get("screenshot")
            if shot and shot not in shots:
                shots.append(shot)
    for i, name in enumerate(shots):
        pm = QPixmap(1920, 1080)
        pm.fill(QColor((40 * (i + 1)) % 256, 90, 130))
        assert pm.save(os.path.join(gui_dir, name), "PNG"), f"写入 PNG 失败：{name}"


def _record_message_boxes(monkeypatch):
    """记录 QMessageBox.information/warning/critical 调用（dialogs 夹具只应答不记录）"""
    calls = []

    def _make(kind):
        def _recorder(parent=None, title="", text="", *args, **kwargs):
            calls.append((kind, title, text))
            return None
        return _recorder

    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(_ae.QMessageBox, kind, _make(kind))
    return calls


def _coords_path_of(editor, gui_dir):
    return os.path.join(gui_dir, f"gui_{editor.gui_number}_coords.json")


def test_missing_coords_open_single_information_only(editor, monkeypatch):
    """打开不含 coords.json 的多轮数据集：仅一条信息性提示，
    无逐步告警弹窗、无状态栏警告；坐标步按最终 JSON 显示 coordinate。"""
    calls = _record_message_boxes(monkeypatch)
    data, coords = _make_dataset(editor.gui_number, with_coords_file=False)
    gui_dir = _write_dataset(editor, data, coords, write_coords=False)
    _write_dataset_shots(gui_dir, data)

    H.open_edit_mode(editor, gui_dir, 0)

    assert editor._original_coords_exist is False
    assert editor._coord_issues == []
    assert [c for c in calls if c[0] in ("warning", "critical")] == []
    infos = [c for c in calls if c[0] == "information"]
    assert len(infos) == 1
    assert "coords.json" in infos[0][2]
    assert "⚠" not in editor.status_label.text()

    # 坐标步无框预览，coordinate 如实来自最终 JSON；重新拉框入口可用
    assert editor.steps[0]["rect_info"] == ()
    assert editor.steps[0]["coord_issue"] is None
    assert editor.steps[0]["editor"].coord_x_input.text() == "200"
    assert editor.steps[0]["editor"].coord_y_input.text() == "300"
    assert editor.steps[1]["editor"].coord_x_input.text() == "25"
    assert editor.steps[1]["editor"].end_coord_x_input.text() == "110"
    assert editor.relabel_btn.isHidden() is False


def test_missing_coords_text_only_save_no_coords_generated(editor, monkeypatch):
    """仅改文本保存：最终 JSON 更新，gui 目录不生成 coords.json"""
    _record_message_boxes(monkeypatch)
    data, coords = _make_dataset(editor.gui_number, with_coords_file=False)
    gui_dir = _write_dataset(editor, data, coords, write_coords=False)
    _write_dataset_shots(gui_dir, data)
    H.open_edit_mode(editor, gui_dir, 0)

    editor.steps[0]["editor"].intent_input.setText("仅改文本后的意图")
    assert editor.save_edited_round() is True

    # ⚠ silent=False 保存成功后产品会 close() + deleteLater()：此处起不得再推进
    # 事件循环，后续只读纯 Python 属性
    saved = H.read_final_json(editor)
    assert saved["messages"][1]["trajectory"][0]["intent"] == "仅改文本后的意图"
    assert saved["messages"][3] == data["messages"][3]
    assert not os.path.exists(_coords_path_of(editor, gui_dir))


def test_missing_coords_relabel_updates_coordinate_without_coords_file(editor):
    """新拉框后保存：最终 JSON 对应步 coordinate 按新框更新，仍不生成 coords.json"""
    data, coords = _make_dataset(editor.gui_number, with_coords_file=False)
    gui_dir = _write_dataset(editor, data, coords, write_coords=False)
    _write_dataset_shots(gui_dir, data)
    H.open_edit_mode(editor, gui_dir, 0)

    # 走完整 UI 入口在原图上重新拉框：(400, 500, 200, 100) → 中心 (500, 550)
    H.relabel_rect(editor, 0, rect=(400, 500, 200, 100), selection_type="click")
    assert editor.steps[0]["rect_info"] == (400, 500, 200, 100)

    assert editor.save_edited_round(silent=True) is True

    saved = H.read_final_json(editor)
    assert saved["messages"][1]["trajectory"][0]["actions"][0]["coordinate"] == [500, 550]
    assert not os.path.exists(_coords_path_of(editor, gui_dir))


def test_missing_coords_close_silent_writeback(editor):
    """关闭窗口触发 silent=True 写回：最终 JSON 写入，不生成 coords.json"""
    data, coords = _make_dataset(editor.gui_number, with_coords_file=False)
    gui_dir = _write_dataset(editor, data, coords, write_coords=False)
    _write_dataset_shots(gui_dir, data)
    H.open_edit_mode(editor, gui_dir, 0)

    editor.steps[0]["editor"].intent_input.setText("关闭前修改")
    editor.close()
    QTest.qWait(100)

    saved = H.read_final_json(editor)
    assert saved["messages"][1]["trajectory"][0]["intent"] == "关闭前修改"
    assert saved["messages"][3] == data["messages"][3]
    assert not os.path.exists(_coords_path_of(editor, gui_dir))


def test_empty_coords_file_exists_b41_preserved(editor, monkeypatch, capsys):
    """coords.json 存在但内容为 []：按存在处理——打开不弹缺失提示；
    保存收集 0 条时 B41 告警跳过写入，原文件保留。"""
    calls = _record_message_boxes(monkeypatch)
    data, _coords = _make_dataset(editor.gui_number)
    gui_dir = _write_dataset(editor, data, [])  # 盘上写 []：文件存在但内容为空
    _write_dataset_shots(gui_dir, data)
    H.open_edit_mode(editor, gui_dir, 0)

    assert editor._original_coords_exist is True
    # 不弹缺失信息提示；文件存在时的 absent 判定与告警保留不变
    assert [c for c in calls if c[0] == "information"] == []
    assert [issue for _i, _a, issue, _d in editor._coord_issues] == ["absent", "absent"]

    capsys.readouterr()  # 清空打开阶段输出
    assert editor.save_edited_round(silent=True) is True
    out = capsys.readouterr().out
    assert "已跳过 coords 写入以保留原文件" in out

    coords_path = _coords_path_of(editor, gui_dir)
    assert os.path.exists(coords_path)
    with open(coords_path, "r", encoding="utf-8") as f:
        assert json.load(f) == []


# ---------------------------------------------------------------------------
# 动作类型变更时旧动作参数污染回归（_merge_step_with_original）
#
# 缺陷背景：编辑已完成任务等编辑路径中，用户把某步动作类型改掉后（如
# type → left_click），get_data() 已按新动作正确省略无关参数，但合并函数
# 对 actions[0] 内「旧动作有、新动作缺失」的键无条件深拷贝补齐，把旧动作
# 参数键（text/keys/time/pixels/coordinate/start_coordinate）连同旧值复活
# 进交付 JSON。修复后：动作类型变更时不补齐旧动作已知参数键，未知键仍保留，
# 受保护字段空值回退 / 终止动作规则 / 同类型补齐等其余行为一律不变。
# ---------------------------------------------------------------------------
def _rich_step(gui_number, shot, action, intent="保留意图", step_no=0):
    """构造含非空受保护字段与未知键的原始步骤（模拟真实下游标注产物）。"""
    return {
        "step": step_no,
        "intent": intent,
        "CoT": "原始推理链，禁止被空值覆盖",
        "observation": {
            "screenshot": shot,
            "active_window": "原始窗口标题",
            "ui_tree_segment": "<node>原始 UI 树片段</node>",
        },
        "actions": [action],
        "downstream_meta": {"x": 1, "nested": ["a", "b"]},
    }


def _rebuilt_step(action, shot, intent="编辑后的意图"):
    """模拟 StepEditorWidget.get_data() 重建出的步骤字典：只含表单字段，
    CoT / active_window / ui_tree_segment 为空值，非终止动作不带 status。"""
    return {
        "step": 0,
        "intent": intent,
        "CoT": "",
        "observation": {
            "screenshot": shot,
            "active_window": "",
            "ui_tree_segment": "",
        },
        "actions": [action],
    }


def test_merge_type_to_left_click_drops_old_text(editor):
    """type(含 text)→left_click：旧动作的 text 不得被补齐复活。"""
    gui = editor.gui_number
    shot = f"gui_{gui}_0001.png"
    old_step = _rich_step(gui, shot, {
        "action": "type",
        "coordinate": [200, 300],
        "text": "旧输入文本",
        "element": "输入框",
        "status": "success",
    })
    new_step = _rebuilt_step({
        "action": "left_click",
        "coordinate": [200, 300],
        "element": "",
    }, shot)

    merged = editor._merge_step_with_original(new_step, old_step)
    action = merged["actions"][0]
    assert action["action"] == "left_click"
    assert "text" not in action
    assert action["coordinate"] == [200, 300]
    # 非参数键的保留规则不受影响：element 空值回退、status 缺失补齐
    assert action["element"] == "输入框"
    assert action["status"] == "success"


def test_merge_drag_to_left_click_drops_old_start_coordinate(editor):
    """left_click_drag(含 start_coordinate)→left_click：起点坐标不得复活。"""
    gui = editor.gui_number
    shot = f"gui_{gui}_0001.png"
    old_step = _rich_step(gui, shot, {
        "action": "left_click_drag",
        "start_coordinate": [25, 40],
        "coordinate": [110, 130],
        "element": "",
        "status": "success",
    })
    new_step = _rebuilt_step({
        "action": "left_click",
        "coordinate": [110, 130],
        "element": "",
    }, shot)

    merged = editor._merge_step_with_original(new_step, old_step)
    action = merged["actions"][0]
    assert action["action"] == "left_click"
    assert "start_coordinate" not in action
    assert action["coordinate"] == [110, 130]


def test_merge_left_click_to_wait_drops_coordinate_keeps_new_time(editor):
    """left_click(含 coordinate)→wait：旧坐标不得复活，新 time 保留。"""
    gui = editor.gui_number
    shot = f"gui_{gui}_0001.png"
    old_step = _rich_step(gui, shot, {
        "action": "left_click",
        "coordinate": [200, 300],
        "element": "按钮",
        "status": "success",
    })
    new_step = _rebuilt_step({
        "action": "wait",
        "time": 1.5,
        "element": "",
    }, shot)

    merged = editor._merge_step_with_original(new_step, old_step)
    action = merged["actions"][0]
    assert action["action"] == "wait"
    assert "coordinate" not in action
    assert action["time"] == 1.5


def test_merge_scroll_to_left_click_drops_old_pixels(editor):
    """scroll(含 pixels)→left_click：旧滚动像素不得复活。"""
    gui = editor.gui_number
    shot = f"gui_{gui}_0001.png"
    old_step = _rich_step(gui, shot, {
        "action": "scroll",
        "coordinate": [152, 315],
        "pixels": 300,
        "element": "",
        "status": "success",
    })
    new_step = _rebuilt_step({
        "action": "left_click",
        "coordinate": [152, 315],
        "element": "",
    }, shot)

    merged = editor._merge_step_with_original(new_step, old_step)
    action = merged["actions"][0]
    assert action["action"] == "left_click"
    assert "pixels" not in action
    assert action["coordinate"] == [152, 315]


def test_merge_key_to_left_click_drops_old_keys(editor):
    """key(含 keys)→left_click：旧按键组合不得复活。"""
    gui = editor.gui_number
    shot = f"gui_{gui}_0001.png"
    old_step = _rich_step(gui, shot, {
        "action": "key",
        "keys": ["ctrl", "c"],
        "element": "",
        "status": "success",
    })
    new_step = _rebuilt_step({
        "action": "left_click",
        "coordinate": [200, 300],
        "element": "",
    }, shot)

    merged = editor._merge_step_with_original(new_step, old_step)
    action = merged["actions"][0]
    assert action["action"] == "left_click"
    assert "keys" not in action


def test_merge_action_change_keeps_unknown_action_key(editor):
    """动作变更但旧动作含未知键 foo：未知键仍保留，已知参数键不补齐。"""
    gui = editor.gui_number
    shot = f"gui_{gui}_0001.png"
    old_step = _rich_step(gui, shot, {
        "action": "type",
        "coordinate": [200, 300],
        "text": "旧输入文本",
        "foo": "bar",
        "element": "",
        "status": "success",
    })
    new_step = _rebuilt_step({
        "action": "left_click",
        "coordinate": [200, 300],
        "element": "",
    }, shot)

    merged = editor._merge_step_with_original(new_step, old_step)
    action = merged["actions"][0]
    assert action["foo"] == "bar"
    assert "text" not in action


def test_merge_action_change_keeps_protected_empty_fallback(editor):
    """动作变更时受保护字段空值回退规则不变：新值空 → 保留原值。"""
    gui = editor.gui_number
    shot = f"gui_{gui}_0001.png"
    old_step = _rich_step(gui, shot, {
        "action": "left_click",
        "coordinate": [200, 300],
        "element": "原始按钮",
        "status": "success",
    })
    new_step = _rebuilt_step({
        "action": "wait",
        "time": 2.0,
        "element": "",
    }, shot)

    merged = editor._merge_step_with_original(new_step, old_step)
    action = merged["actions"][0]
    # 步骤级 CoT / observation 级受保护字段：空值回退原值
    assert merged["CoT"] == "原始推理链，禁止被空值覆盖"
    assert merged["observation"]["active_window"] == "原始窗口标题"
    assert merged["observation"]["ui_tree_segment"] == "<node>原始 UI 树片段</node>"
    # 非终止动作 element/status：空值回退 / 缺失补齐
    assert action["element"] == "原始按钮"
    assert action["status"] == "success"
    # 步骤级未知键照常保留
    assert merged["downstream_meta"] == {"x": 1, "nested": ["a", "b"]}
    # 但旧动作参数键不补齐
    assert "coordinate" not in action
    assert action["time"] == 2.0


def test_merge_same_action_still_backfills_missing_keys(editor):
    """同动作类型（left_click→left_click）：缺失的参数键与未知键仍照常补齐。"""
    gui = editor.gui_number
    shot = f"gui_{gui}_0001.png"
    old_step = _rich_step(gui, shot, {
        "action": "left_click",
        "coordinate": [200, 300],
        "foo": "bar",
        "element": "按钮",
        "status": "success",
    })
    new_step = _rebuilt_step({
        "action": "left_click",
        "element": "新按钮",
    }, shot)

    merged = editor._merge_step_with_original(new_step, old_step)
    action = merged["actions"][0]
    assert action["action"] == "left_click"
    assert action["coordinate"] == [200, 300]
    assert action["foo"] == "bar"
    assert action["element"] == "新按钮"
    assert action["status"] == "success"


def test_merge_answer_same_serialized_type_backfills_text(editor):
    """旧 answer(含 text)→新 answer（answer_terminate 序列化后同为 answer）：
    视为同类型，text 等缺失键补齐行为不变，终止动作规则照常。"""
    gui = editor.gui_number
    shot = f"gui_{gui}_0001.png"
    old_step = _rich_step(gui, shot, {
        "action": "answer",
        "text": "旧回答文本",
        "element": "残留元素",
        "status": "failed",
    })
    # get_data() 对 answer_terminate 的序列化产物：action="answer"、status="success"
    new_step = _rebuilt_step({
        "action": "answer",
        "element": "",
        "status": "success",
    }, shot)

    merged = editor._merge_step_with_original(new_step, old_step)
    action = merged["actions"][0]
    assert action["action"] == "answer"
    assert action["text"] == "旧回答文本"
    assert action["element"] == ""
    assert action["status"] == "success"


def _prepare_type_step_for_edit(editor):
    """含 type 步骤的单轮已完成 JSON + 匹配 coords + 真实 PNG，走产品入口
    进编辑态（复用既有回归夹具 _regression_single_round / _write_dataset_shots）。"""
    gui = editor.gui_number
    data = _regression_single_round(gui, {
        "action": "type",
        "coordinate": [200, 300],
        "text": "旧输入文本",
        "element": "输入框",
        "status": "success",
    })
    coords = [{"step": 0, "action": "type",
               "vertices": [100, 200, 300, 400], "center": [200, 300]}]
    gui_dir = _write_dataset(editor, data, coords)
    _write_dataset_shots(gui_dir, data)
    H.open_edit_mode(editor, gui_dir, 0)


@pytest.mark.parametrize("silent", [False, True])
def test_edit_completed_change_type_to_click_confirm_then_save(editor, silent):
    """端到端：type 步改为 left_click，确认分支（save_current_step 编辑模式）
    与写回（silent 参数化）都不得把旧 text 带回交付 JSON。"""
    _prepare_type_step_for_edit(editor)

    ed = editor.steps[0]["editor"]
    assert ed.action_type_combo.currentText() == "文本输入"
    assert ed.text_input.toPlainText() == "旧输入文本"

    # 通过编辑器控件改动作类型；坐标框只读，hydration 已回填 (200,300)
    H.fill_step(editor, 0, action_chinese="左键单击", intent="改为点击",
                coord_text="200,300")
    # 文本框仍留着旧文本：get_data() 按新动作省略 text，污染只可能来自合并
    assert ed.text_input.toPlainText() == "旧输入文本"

    H.save_current(editor)  # save_current_step 编辑模式确认分支
    confirmed_action = editor.steps[0]["data"]["actions"][0]
    assert confirmed_action["action"] == "left_click"
    assert "text" not in confirmed_action

    assert editor.save_edited_round(silent=silent) is True

    # ⚠ silent=False 保存成功后产品会 close() + deleteLater()：此处起不得再推进
    # 事件循环，后续只读纯 Python / 磁盘
    saved_action = H.read_final_json(editor)["messages"][1]["trajectory"][0]["actions"][0]
    assert saved_action["action"] == "left_click"
    assert "text" not in saved_action
    assert saved_action["coordinate"] == [200, 300]
    I.assert_final_json(editor, expected_rounds=1)


def test_edit_completed_change_type_to_click_silent_writeback(editor):
    """端到端：不经确认直接 silent 写回（关闭窗口路径），旧 text 同样不得复活。"""
    _prepare_type_step_for_edit(editor)

    H.fill_step(editor, 0, action_chinese="左键单击", intent="改为点击",
                coord_text="200,300")
    assert editor.save_edited_round(silent=True) is True

    saved_action = H.read_final_json(editor)["messages"][1]["trajectory"][0]["actions"][0]
    assert saved_action["action"] == "left_click"
    assert "text" not in saved_action
    assert saved_action["coordinate"] == [200, 300]
    I.assert_final_json(editor, expected_rounds=1)
