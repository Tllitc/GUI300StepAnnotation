# -*- coding: utf-8 -*-
"""answer / answer_terminate 多轮轮询式问答轨迹回归测试。

覆盖：终止类动作必须是末步、answer 落轮前全轮必填校验、answer 落轮与取消新轮
重置、缺指令拒绝落轮、编辑已完成任务时不触发切轮、coords 轮次归属、交付后
阻断采集、只读多轮回看器。
"""

import copy
import glob
import json
import os

from PyQt5.QtTest import QTest

import annotation_editor as _ae
import helpers as H


def _final_json_path(editor):
    return os.path.join(H.gui_dir_of(editor), f"gui_{editor.gui_number}.json")


def _png_set(editor):
    return set(glob.glob(os.path.join(H.gui_dir_of(editor), "*.png")))


# ---------------------------------------------------------------------------
# 1. 终止类动作必须是本轮最后一步
# ---------------------------------------------------------------------------
def test_answer_on_middle_step_rejected(editor):
    """中间步 answer：拦下且不落轮、不清 steps、不写交付 JSON"""
    H.walk_steps(editor, 3)

    editor.display_step(1)
    QTest.qWait(50)
    H.fill_step(editor, 1, action_chinese="回答用户", intent="回答", text="答")
    H.confirm(editor)

    assert len(editor.rounds) == 0
    assert len(editor.steps) == 3
    assert not os.path.exists(_final_json_path(editor))


def test_terminate_on_middle_step_rejected(editor):
    """中间步 terminate：同样拦下"""
    H.walk_steps(editor, 3)

    editor.display_step(1)
    QTest.qWait(50)
    H.fill_step(editor, 1, action_chinese="任务完成", intent=None)
    H.confirm(editor)

    assert len(editor.rounds) == 0
    assert len(editor.steps) == 3
    assert not os.path.exists(_final_json_path(editor))


# ---------------------------------------------------------------------------
# 2. answer 落轮前全轮必填校验
# ---------------------------------------------------------------------------
def test_answer_blocked_by_missing_fields_in_other_step(editor, monkeypatch):
    """其它步骤缺必填项时 answer 不落轮；补齐后可正常落轮"""
    # ValidationFailDialog.exec_() 是模态阻塞，测试中替换为立即返回
    monkeypatch.setattr(_ae.ValidationFailDialog, "exec_", lambda self: 0)

    H.walk_steps(editor, 2)
    editor.steps[0]["editor"].intent_input.clear()

    H.fill_step(editor, 1, action_chinese="回答用户", intent="回答", text="答")
    H.confirm(editor)

    assert len(editor.rounds) == 0
    assert len(editor.steps) == 2

    # 补齐第 0 步的动作描述后再次确认 answer 步
    H.fill_step(editor, 0, action_chinese="左键单击", intent="补齐描述",
                coord_text="250,400")
    editor.display_step(1)
    QTest.qWait(50)
    H.confirm(editor)

    assert len(editor.rounds) == 1
    # 落轮后由 300ms QTimer 弹续轮对话框，驱动事件循环让回调结束，避免残留定时器
    QTest.qWait(500)


# ---------------------------------------------------------------------------
# 3. answer 落轮后取消新轮：重置工作区并清空旧指令
# ---------------------------------------------------------------------------
def test_cancel_next_round_resets_workspace(editor):
    H.walk_steps(editor, 2)

    H.fill_step(editor, 1, action_chinese="回答用户", intent="回答", text="答")
    editor._test_dialogs.input_ok = False
    H.confirm(editor)
    QTest.qWait(500)

    assert len(editor.rounds) == 1
    assert editor.steps == []
    assert editor.current_step_index == -1
    assert editor.task_instruction == ""
    assert editor.stack_widget.count() == 1

    draft = H.read_draft(editor)
    assert draft is not None
    assert draft["current_steps"] == []
    assert len(draft["rounds"]) == 1


# ---------------------------------------------------------------------------
# 4. 缺任务指令拒绝落轮
# ---------------------------------------------------------------------------
def test_missing_instruction_rejects_round(editor):
    H.walk_steps(editor, 1)
    editor.task_instruction = ""

    H.fill_step(editor, 0, action_chinese="回答用户", intent="回答", text="答")
    editor._test_dialogs.input_ok = False
    H.confirm(editor)

    assert len(editor.rounds) == 0
    assert len(editor.steps) == 1
    assert not os.path.exists(_final_json_path(editor))


# ---------------------------------------------------------------------------
# 5. 编辑已完成任务：answer 步确认不触发切轮
# ---------------------------------------------------------------------------
def _make_completed_dataset(gui_number):
    """第 0 轮 = 单击 + 回答用户；第 1 轮 = 单击"""
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
        step(1, "第一轮回答", shot2, {
            "action": "answer",
            "text": "好的",
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
        "platform": "macOS",
        "system": "macOS",
        "screen_size": [1920, 1080],
        "task_type": "macOS-测试",
        "messages": [
            {"role": "user", "instruction": "第一轮指令"},
            {"role": "assistant", "trajectory": round0},
            {"role": "user", "instruction": "第二轮指令"},
            {"role": "assistant", "trajectory": round1},
        ],
    }

    coords = [
        {"step": 0, "action": "left_click",
         "vertices": [100, 200, 300, 400], "center": [200, 300], "round": 0},
        {"step": 0, "action": "left_click",
         "vertices": [500, 600, 700, 800], "center": [600, 700], "round": 1},
    ]
    return data, coords


def test_edit_mode_answer_step_does_not_start_new_round(editor, editor_factory):
    data, coords = _make_completed_dataset(editor.gui_number)
    gui_dir = H.gui_dir_of(editor)
    os.makedirs(gui_dir, exist_ok=True)
    with open(os.path.join(gui_dir, f"gui_{editor.gui_number}.json"),
              "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(gui_dir, f"gui_{editor.gui_number}_coords.json"),
              "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)

    # 编辑模式由主窗口新建编辑器进入（与产品路径一致）
    edit_editor = editor_factory()
    H.open_edit_mode(edit_editor, gui_dir, round_index=0)

    assert len(edit_editor.rounds) == 2
    assert len(edit_editor.steps) == 2

    get_text_before = sum(1 for call in edit_editor._test_dialogs.calls
                          if call[0] == "getText")
    edit_editor.display_step(1)
    QTest.qWait(50)
    edit_editor.steps[1]["editor"].intent_input.setText("改过的回答描述")
    H.confirm(edit_editor)

    assert len(edit_editor.rounds) == 2, "编辑模式下 answer 步不得触发落轮切轮"
    assert len(edit_editor.steps) == 2, "编辑模式下 steps 不得被清空"
    assert edit_editor.steps[1]["data"]["intent"] == "改过的回答描述"
    get_text_after = sum(1 for call in edit_editor._test_dialogs.calls
                         if call[0] == "getText")
    assert get_text_after == get_text_before, "编辑模式不应弹出「新任务指令」输入"


# ---------------------------------------------------------------------------
# 6. coords 轮次归属
# ---------------------------------------------------------------------------
def test_coords_entries_carry_round_index(editor):
    H.walk_rounds(editor, [(2, "第一轮指令"), (2, "第二轮指令")])

    coords = H.read_final_coords(editor)
    assert coords, "最终 coords 文件应有条目"

    clicks = [entry for entry in coords if entry.get("action") == "left_click"]
    assert len(clicks) == 2, f"两轮各 1 个 click 条目，实际 {len(clicks)}"
    assert all("round" in entry for entry in coords)

    # 每轮只有 step 0 是坐标步：两轮同 step 的条目 round 分别为 0 / 1
    assert {entry["step"] for entry in clicks} == {0}
    assert sorted(entry["round"] for entry in clicks) == [0, 1]


# ---------------------------------------------------------------------------
# 7. 交付后阻断采集
# ---------------------------------------------------------------------------
def test_capture_blocked_after_delivery(editor, monkeypatch):
    # 不真正返回初始化菜单（会 close/deleteLater 销毁窗口），仅保留守卫断言现场
    monkeypatch.setattr(editor, "_return_to_init_menu", lambda: None)

    json_path = H.finish(editor, action="terminate")
    assert json_path, "收尾未写出交付 JSON"
    assert editor._final_data_saved is True

    png_before = _png_set(editor)
    steps_before = len(editor.steps)

    editor.start_capture()
    QTest.qWait(600)

    assert len(editor.steps) == steps_before == 0
    assert _png_set(editor) == png_before, "交付后仍新增了截图文件"
    assert editor.status_label.text() == "任务已保存，请先选择是否开始新任务"


# ---------------------------------------------------------------------------
# 8. 只读多轮回看器
# ---------------------------------------------------------------------------
def test_round_preview_dialog_readonly(editor, monkeypatch):
    # 收尾会返回初始化菜单（close/deleteLater 销毁窗口），此处保留实例以校验回看器只读
    monkeypatch.setattr(editor, "_return_to_init_menu", lambda: None)
    H.walk_rounds(editor, [(2, "第一轮指令"), (2, "第二轮指令")])
    assert len(editor.rounds) == 2

    rounds_before = copy.deepcopy(editor.rounds)
    coords_before = copy.deepcopy(editor.all_coords_entries)
    steps_before = [copy.deepcopy({k: v for k, v in step.items() if k != "editor"})
                    for step in editor.steps]
    editor_ids = [id(step["editor"]) for step in editor.steps]

    dlg = _ae.RoundPreviewDialog(editor)
    try:
        assert dlg.round_combo.count() == 2

        # 第 1 轮
        _wait_thumbs(dlg)
        assert dlg.list_widget.count() == len(editor.rounds[0]["trajectory"])
        assert not dlg.list_widget.item(0).icon().isNull(), "缩略图未生成"

        # 切到第 2 轮
        dlg.round_combo.setCurrentIndex(1)
        _wait_thumbs(dlg)
        assert dlg.list_widget.count() == len(editor.rounds[1]["trajectory"])

        dlg.list_widget.setCurrentRow(0)
        QTest.qWait(100)
        pixmap = dlg.preview_label.pixmap()
        assert pixmap is not None and not pixmap.isNull(), "大图预览为空"

        # 只读：rounds / coords / steps 完全未变
        assert editor.rounds == rounds_before
        assert editor.all_coords_entries == coords_before
        assert [copy.deepcopy({k: v for k, v in step.items() if k != "editor"})
                for step in editor.steps] == steps_before
        assert [id(step["editor"]) for step in editor.steps] == editor_ids
    finally:
        dlg.close()
        dlg.deleteLater()
        QTest.qWait(50)


def _wait_thumbs(dlg):
    """等待缩略图批量加载完成（_pending_items 清空且至少有一项）"""
    assert dlg.list_widget.count() > 0
    H._wait_until(
        lambda: not dlg._pending_items,
        message="缩略图批量加载未完成"
    )
    QTest.qWait(50)