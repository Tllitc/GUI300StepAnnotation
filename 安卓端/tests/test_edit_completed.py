# -*- coding: utf-8 -*-
"""编辑已完成任务回归测试（Android）

覆盖：
- 加载已完成 JSON + coords 后重建 steps_data（截图/intent/action_data/vertices）
- 旧 coords 无 round 字段时按 step 回退切分轮次
- 编辑第 r 轮保存后仅该轮变化，coords 仍为 {"version":"3.0","coords":[...]}
- 编辑模式不写 draft、关闭窗口自动写回
- 缺项校验阻止保存且原文件不变
- coords 少条目/step 漂移/center 与坐标值对不上（E 跨端同步：位置回退已删除）
"""
import copy
import json
import os

import pytest
from PyQt5.QtTest import QTest

from annotation_editor import AnnotationEditor
from data_manager import DataManager
from fakes import FakeAndroidScreenCapture
from helpers import flush_events
from invariants import assert_edit_writeback_preserved, assert_final_json

GUI_NUM = "000001"


def _write_png(path, index):
    """用 Fake 截图器的 PNG 渲染器生成合法占位截图"""
    with open(path, "wb") as f:
        f.write(FakeAndroidScreenCapture._render_png(index, 360, 640))


def _build_dataset(base_dir, with_coords_file=True):
    """在 base_dir 下构造两轮已完成数据集（coords 无 round 字段）

    with_coords_file=False 时构造「不含 coords.json」的数据集：不写 coords
    文件、返回空条目列表（默认行为不变），用于缺失合法态回归。

    :return: (gui_dir, data, coords_entries)
    """
    gui_dir = os.path.join(str(base_dir), f"gui_{GUI_NUM}")
    os.makedirs(gui_dir, exist_ok=True)

    rounds = [
        ("第一轮指令", [
            ("r1s0", "click", {"coordinate": [100, 200], "element": "", "x_platform": "android"}),
            ("r1s1", "type", {"coordinate": [150, 250], "text": "abc", "element": "输入框"}),
            ("r1s2", "scroll", {"coordinate": [120, 300], "pixels": -120, "element": ""}),
        ]),
        ("第二轮指令", [
            ("r2s0", "click", {"coordinate": [80, 90], "element": "", "x_platform": "android"}),
            ("r2s1", "answer", {"text": "完成回答", "element": ""}),
        ]),
    ]

    messages = []
    coords_entries = []
    shot_index = 0
    for instruction, steps in rounds:
        messages.append({"role": "user", "instruction": instruction})
        trajectory = []
        for j, (intent, action, extra_action_data) in enumerate(steps):
            action_data = {"action": action}
            action_data.update(extra_action_data)
            shot_index += 1
            filename = f"gui_{GUI_NUM}_{shot_index:04d}.png"
            _write_png(os.path.join(gui_dir, filename), shot_index)
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
                "actions": [dict(action_data)],
            })
            entry = {"step": j, "action": action, "source": "coords-v1"}
            if "coordinate" in action_data:
                entry["vertices"] = [10, 10, 110, 110]
                entry["center"] = list(action_data["coordinate"])
            coords_entries.append(entry)
        messages.append({"role": "assistant", "trajectory": trajectory})

    data = {
        "platform": "Android",
        "system": "Android 13",
        "screen_size": [360, 640],
        "task_type": "Android-社交",
        "extra_meta": {"keep": True},
        "messages": messages,
    }
    with open(os.path.join(gui_dir, f"gui_{GUI_NUM}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if with_coords_file:
        with open(os.path.join(gui_dir, f"gui_{GUI_NUM}_coords.json"), "w", encoding="utf-8") as f:
            json.dump({"version": "3.0", "coords": coords_entries}, f,
                      ensure_ascii=False, indent=2)
    else:
        coords_entries = []
    return gui_dir, data, coords_entries


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _build_raw_dataset(base_dir, steps, coords_entries):
    """单轮数据集：coords 条目由用例逐字给定

    与 _build_dataset 的区别是坐标不被自动派生，用于构造「少一条 scroll 条目」
    「step 编号整体漂移」「center 与坐标值对不上」这类历史交付件。

    :param steps: [(intent, action_data), ...]
    :return: (gui_dir, data, coords_entries)
    """
    gui_dir = os.path.join(str(base_dir), f"gui_{GUI_NUM}")
    os.makedirs(gui_dir, exist_ok=True)

    trajectory = []
    for j, (intent, action_data) in enumerate(steps):
        filename = f"gui_{GUI_NUM}_{j + 1:04d}.png"
        _write_png(os.path.join(gui_dir, filename), j + 1)
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
        "platform": "Android",
        "system": "Android 13",
        "screen_size": [360, 640],
        "task_type": "Android-社交",
        "extra_meta": {"keep": True},
        "messages": [
            {"role": "user", "instruction": "唯一轮指令"},
            {"role": "assistant", "trajectory": trajectory},
        ],
    }
    with open(os.path.join(gui_dir, f"gui_{GUI_NUM}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(gui_dir, f"gui_{GUI_NUM}_coords.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "3.0", "coords": coords_entries}, f,
                  ensure_ascii=False, indent=2)
    return gui_dir, data, coords_entries


def _click_step(intent="点击搜索", coordinate=(100, 200)):
    return intent, {"action": "click", "coordinate": list(coordinate), "element": ""}


def _scroll_step(intent="上滑列表", coordinate=(300, 400)):
    return intent, {"action": "scroll", "coordinate": list(coordinate),
                    "pixels": -120, "element": ""}


def _new_editor(base_dir, gui_dir, data, round_index=0):
    dm = DataManager(base_dir=str(base_dir))
    dm.create_task_directory("Android")
    editor = AnnotationEditor(
        data_manager=dm,
        app_name=os.path.basename(gui_dir),
        task_instruction="",
        screen_info={
            "platform": data.get("platform", "Android"),
            "system": data.get("system", ""),
            "screen_size": data.get("screen_size", [1080, 2400]),
        },
        app_type="",
        serial=None,
        init_window=None,
    )
    editor.screen_capture = FakeAndroidScreenCapture()
    return editor


def _load_editor(base_dir, gui_dir, data, coords_entries, round_index=0):
    editor = _new_editor(base_dir, gui_dir, data)
    editor.load_from_completed_json(data, coords_entries, round_index, gui_dir)
    flush_events(20)
    return editor


def test_load_completed_rebuilds_steps_and_coords_rounds(tmp_path, qapp):
    gui_dir, data, coords_entries = _build_dataset(tmp_path)
    editor = _load_editor(tmp_path, gui_dir, data, coords_entries, round_index=0)
    try:
        assert editor._edit_mode is True
        assert editor.gui_number == GUI_NUM
        assert editor.gui_dir == os.path.normpath(gui_dir)
        assert len(editor.rounds) == 2
        assert editor.rounds[0]["instruction"] == "第一轮指令"
        assert editor.rounds[1]["instruction"] == "第二轮指令"

        # 旧 coords 无 round：按 step 回退切分，条目绝不丢弃
        assert "round" not in editor.rounds[0]["coords"][0]
        assert editor.rounds[0]["coords"] == coords_entries[:3]
        assert editor.rounds[1]["coords"] == coords_entries[3:]
        assert len(editor.rounds[0]["coords"]) + len(editor.rounds[1]["coords"]) == len(coords_entries)

        trajectory = data["messages"][1]["trajectory"]
        assert len(editor.steps_data) == len(trajectory)
        for i, t in enumerate(trajectory):
            step = editor.steps_data[i]
            filename = t["observation"]["screenshot"]
            assert step["screenshot"] == filename
            assert step["screenshot_filepath"] == os.path.join(gui_dir, filename)
            assert step["intent"] == t["intent"]
            assert step["action_data"] == t["actions"][0]
            assert step["vertices"] == coords_entries[i]["vertices"]

        assert "编辑已完成任务" in editor.windowTitle()
        assert "第 1 轮" in editor.status_label.text()
        assert editor.task_instruction == "第一轮指令"
        assert editor._task_completed is False
        assert editor._current_round_saved is True
        assert editor.btn_save_edit.isHidden() is False
    finally:
        editor.close()


def test_assign_coords_misaligned_entries_kept_in_last_round():
    rounds = [
        {"instruction": "r0", "trajectory": [{"step": 0, "actions": [{"action": "click"}]}]},
        {"instruction": "r1", "trajectory": [{"step": 0, "actions": [{"action": "click"}]}]},
    ]
    entries = [
        {"step": 0, "action": "click"},
        {"step": 0, "action": "click"},
        {"step": 9, "action": "swipe"},   # 无法对齐
    ]
    groups = AnnotationEditor._assign_coords_to_rounds(entries, rounds)
    assert sum(len(g) for g in groups) == len(entries), "coords 条目被丢弃"
    assert groups[1][-1] == {"step": 9, "action": "swipe"}


def test_edit_round_two_save_only_replaces_selected_round(tmp_path, qapp, modal):
    gui_dir, data, coords_entries = _build_dataset(tmp_path)
    editor = _load_editor(tmp_path, gui_dir, data, coords_entries, round_index=1)
    try:
        assert len(editor.steps_data) == 2
        assert "第 2 轮" in editor.status_label.text()

        # 编辑第二轮首步的意图、坐标与拉框
        editor.intent_input.setText("修改后的第二轮首步意图")
        editor.coord_x_input.setText("50")
        editor.coord_y_input.setText("60")
        editor._current_vertices = [10, 20, 110, 220]
        editor.confirm_step()
        flush_events()
        assert "已更新第 1 步" in editor.status_label.text()

        assert editor.save_edited_round(False) is True
        flush_events(50)
    finally:
        editor.close()

    json_path = os.path.join(gui_dir, f"gui_{GUI_NUM}.json")
    saved = _read_json(json_path)
    # 顶层字段与未编辑轮次原样保留
    for key in ("platform", "system", "screen_size", "task_type", "extra_meta"):
        assert saved[key] == data[key], f"顶层字段被改动: {key}"
    assert saved["messages"][:3] == data["messages"][:3], "未编辑轮次发生变化"

    traj = saved["messages"][3]["trajectory"]
    assert traj[0]["step"] == 0
    assert traj[0]["intent"] == "修改后的第二轮首步意图"
    assert traj[0]["actions"][0]["coordinate"] == [50, 60]
    # 编辑器未暴露的字段被合并保留（新值优先）
    assert traj[0]["actions"][0]["x_platform"] == "android"
    assert traj[0]["CoT"] == "原始思维链"
    assert traj[0]["observation"]["extra_obs"] == "keep"
    assert traj[1] == data["messages"][3]["trajectory"][1], "未编辑步骤发生变化"

    coords_path = os.path.join(gui_dir, f"gui_{GUI_NUM}_coords.json")
    coord_data = _read_json(coords_path)
    assert isinstance(coord_data, dict)
    assert coord_data.get("version") == "3.0"
    entries = coord_data["coords"]
    assert len(entries) == 5
    # 4.2（B4/B18）写盘副本按所属轮次注入 round；去掉 round 后其余字段逐字段不变
    assert [e.get("round") for e in entries] == [0, 0, 0, 1, 1]
    stripped = [{k: v for k, v in e.items() if k != "round"} for e in entries]
    assert stripped[:3] == coords_entries[:3], "未编辑轮次坐标发生变化"
    assert stripped[3]["step"] == 0
    assert stripped[3]["action"] == "click"
    assert stripped[3]["vertices"] == [10, 20, 110, 220]
    assert stripped[3]["center"] == [50, 60]
    assert stripped[3]["source"] == "coords-v1"


def test_edit_mode_never_writes_draft_and_close_autosaves(tmp_path, qapp):
    gui_dir, data, coords_entries = _build_dataset(tmp_path)
    editor = _load_editor(tmp_path, gui_dir, data, coords_entries, round_index=0)
    draft_path = os.path.join(gui_dir, f"gui_{GUI_NUM}_draft.json")
    try:
        editor.intent_input.setText("草稿隔离意图")
        editor.schedule_draft_save()
        QTest.qWait(1200)
        flush_events()
        assert not os.path.exists(draft_path), "编辑模式不应写草稿"

        editor._write_draft_now()
        assert not os.path.exists(draft_path), "编辑模式立即写草稿入口应直接返回"

        # 关闭窗口自动写回最终 JSON，仍不产生草稿
        editor.close()
        flush_events(50)
        assert not os.path.exists(draft_path), "关闭后不应生成草稿"
    finally:
        try:
            editor.close()
        except Exception:
            pass

    saved = _read_json(os.path.join(gui_dir, f"gui_{GUI_NUM}.json"))
    assert saved["messages"][1]["trajectory"][0]["intent"] == "草稿隔离意图"
    assert saved["messages"][3] == data["messages"][3], "未编辑轮次发生变化"
    assert saved["extra_meta"] == data["extra_meta"]


def test_legacy_coords_missing_scroll_entry_does_not_steal_neighbor_box(tmp_path, qapp, modal):
    """coords 少一条 scroll 条目（B6 遗留形态）：编辑态绝不冒领邻居步的框。

    旧版 _find_coord_entry 在按 step 落空时回退取「该轮第 i 条」，条目数与步数
    一旦错位，下标就漂到别的工作上，写回时污染 bbox 以正确 step 编号落盘。
    现在只按 step 精确匹配，落空才按 center 验证恢复，两者都落空即判「框丢失」。

    与 Windows 端的写回差异：本端 INV-7 要求 coords 每步恰好一条，故 absent 步
    产出由已交付 coordinate 派生的退化点框——它不来自任何邻居的顶点，与「冒领」
    是两回事。
    """
    steps = [_click_step(), _scroll_step()]
    entries = [{"step": 0, "action": "click", "vertices": [40, 140, 160, 260],
                "center": [100, 200], "source": "coords-v1"}]
    gui_dir, data, _ = _build_raw_dataset(tmp_path, steps, entries)
    editor = _load_editor(tmp_path, gui_dir, data, entries, round_index=0)
    try:
        assert len(editor.steps_data) == 2
        assert editor.steps_data[0]["vertices"] == [40, 140, 160, 260]
        assert editor.steps_data[0]["coord_issue"] is None
        # scroll 步：盘上没有属于它的条目 → 框不载入，坐标值仍如实来自 JSON
        assert editor.steps_data[1]["vertices"] is None
        assert editor.steps_data[1]["action_data"]["coordinate"] == [300, 400]
        assert editor.steps_data[1]["coord_issue"] == "absent"
        assert editor.steps_data[1]["orig_coord_entry"] is None
        assert [issue for _i, _a, issue, _d in editor._coord_issues] == ["absent"]
        assert editor._coord_issues[0][0] == 1
        # 不一致必须先被看见：模态框 + 状态栏双通道
        assert any(title == "coords 与坐标值不一致" for title, _t in modal.warnings)
        assert "bbox 与 coordinate 不一致" in editor.status_label.text()
        # 丢框步不得阻塞保存：强迫重拉框会连带改写已交付的 coordinate（同 Windows A6）
        assert editor.validate_step_at(1) == []

        # 一次普通导航不能抹掉标记：标记不属 _collect_step_data 的五个键，
        # 不回贴则落表后被顶掉，写回时「保留盘上原条目」分支随即失效
        editor.jump_to_step(1)
        flush_events()
        editor.jump_to_step(0)
        flush_events()
        assert editor.steps_data[1]["coord_issue"] == "absent"
        assert editor.steps_data[1]["orig_coord_entry"] is None

        assert editor.save_edited_round(False) is True
        flush_events(50)
    finally:
        try:
            editor.close()
        except Exception:
            pass

    _after, saved = assert_edit_writeback_preserved(gui_dir, GUI_NUM, data, entries, 0)
    assert [e["step"] for e in saved] == [0, 1]
    # 唯一真实的 step0 条目逐字段不变
    assert saved[0] == {**entries[0], "round": 0}
    # 未冒领：除 step0 外没有任何条目带着 step0 的顶点
    assert saved[1]["vertices"] == [300, 400, 300, 400]
    assert saved[1]["center"] == [300, 400]
    assert [e for e in saved[1:] if e.get("vertices") == entries[0]["vertices"]] == []
    assert_final_json(gui_dir, GUI_NUM)


def test_legacy_entry_step_drift_recovered_by_center(tmp_path, qapp, modal):
    """step 编号漂移但框本身正确：按 center 恢复匹配必须把框认回来。

    旧交付件里 coords 条目的 step 可能整体错位，但「同 action 且 center == 已交付
    coordinate」是对真实内容的验证，不是对列表位置的猜测，应恢复载入而非判成丢框。

    漂移条目排在同 step 的正确条目之后：_find_coord_entry 不看 action、首个 step
    命中即认领，若排在前面会把正确条目挤掉，真正归属该条目的步骤反而无据可查。

    条目显式带 round=0：INV-13 在缺 round 时靠「step 变小就换轮」分组，而本用例的
    step 恰好故意漂移（0/1/0），不标 round 会被它误读成两轮，与要验的东西无关。
    """
    steps = [_click_step(), _click_step("点击输入框", (60, 500)), _scroll_step()]
    entries = [
        {"step": 0, "action": "click", "round": 0,
         "vertices": [40, 140, 160, 260], "center": [100, 200], "source": "coords-v1"},
        {"step": 1, "action": "click", "round": 0,
         "vertices": [10, 480, 110, 520], "center": [60, 500], "source": "coords-v1"},
        # scroll 的框真实存在，step 却被写成 0（整体漂移）
        {"step": 0, "action": "scroll", "round": 0,
         "vertices": [250, 350, 350, 450], "center": [300, 400], "source": "coords-v1"},
    ]
    gui_dir, data, _ = _build_raw_dataset(tmp_path, steps, entries)
    editor = _load_editor(tmp_path, gui_dir, data, entries, round_index=0)
    try:
        assert editor.steps_data[0]["vertices"] == [40, 140, 160, 260]
        assert editor.steps_data[1]["vertices"] == [10, 480, 110, 520]
        # 漂移条目按 center 被 step 2 认领，不产生任何告警
        assert editor.steps_data[2]["vertices"] == [250, 350, 350, 450]
        assert editor.steps_data[2]["coord_issue"] is None
        assert editor.steps_data[2]["orig_coord_entry"] is None
        assert editor._coord_issues == []
        assert "bbox 与 coordinate 不一致" not in editor.status_label.text()
        assert not any(title == "coords 与坐标值不一致" for title, _t in modal.warnings)

        assert editor.save_edited_round(True) is True
        flush_events(20)
    finally:
        try:
            editor.close()
        except Exception:
            pass

    _after, saved = assert_edit_writeback_preserved(gui_dir, GUI_NUM, data, entries, 0)
    assert len(saved) == 3
    scroll_entry = saved[2]
    # 恢复成功即走正常写回：条目按真实步序重编号，顶点逐字段不变
    assert scroll_entry["step"] == 2 and scroll_entry["action"] == "scroll"
    assert scroll_entry["vertices"] == [250, 350, 350, 450]
    assert scroll_entry["center"] == [300, 400]
    assert_final_json(gui_dir, GUI_NUM)


def test_center_mismatch_not_loaded_and_disk_entry_preserved(tmp_path, qapp, modal):
    """框中心与坐标值对不上：不采信该框，但盘上原条目一个字节都不改。

    「不采信」不等于「丢弃」—— save_edited_round 的保留分支让写回按当前步序原样
    继承该条目，避免采集员只是打开看了一眼就永久丢掉已交付的顶点；validate_step_at
    的窄豁免则保证历史缺陷不阻塞本轮保存（本轮新写的框若不一致仍会走缺项校验）。
    """
    steps = [_click_step(), _scroll_step()]
    click_entry = {"step": 0, "action": "click", "vertices": [40, 140, 160, 260],
                   "center": [100, 200], "source": "coords-v1"}
    # 盘上 bbox 属于别的工作：center [100,200] 与交付 coordinate [300,400] 差数百像素
    bad_scroll = {"step": 1, "action": "scroll", "vertices": [40, 140, 160, 260],
                  "center": [100, 200], "source": "coords-v1"}
    entries = [click_entry, bad_scroll]
    gui_dir, data, _ = _build_raw_dataset(tmp_path, steps, entries)
    editor = _load_editor(tmp_path, gui_dir, data, entries, round_index=0)
    try:
        assert editor.steps_data[0]["coord_issue"] is None
        assert editor.steps_data[1]["vertices"] is None
        assert editor.steps_data[1]["coord_issue"] == "mismatch"
        assert editor.steps_data[1]["orig_coord_entry"] == bad_scroll
        assert [issue for _i, _a, issue, _d in editor._coord_issues] == ["mismatch"]
        assert any(title == "coords 与坐标值不一致" for title, _t in modal.warnings)
        # mismatch 步既不阻塞保存，也不得凭空造出一个冒领来的框
        assert editor.validate_step_at(1) == []

        # 只改第一步的动作描述：不碰 mismatch 步，也不重新拉框
        editor.intent_input.setText("只改动作描述")
        assert editor.save_edited_round(False) is True
        flush_events(50)
    finally:
        try:
            editor.close()
        except Exception:
            pass

    after, saved = assert_edit_writeback_preserved(gui_dir, GUI_NUM, data, entries, 0)
    assert saved[0] == {**click_entry, "round": 0}, "正常条目被连带改写"
    assert saved[1] == {**bad_scroll, "round": 0}, "继承性缺陷条目被改写或丢弃"
    assert after["messages"][1]["trajectory"][0]["intent"] == "只改动作描述"
    assert_final_json(gui_dir, GUI_NUM)


def test_missing_fields_block_save_without_touching_json(tmp_path, qapp, modal):
    gui_dir, data, coords_entries = _build_dataset(tmp_path)
    editor = _load_editor(tmp_path, gui_dir, data, coords_entries, round_index=0)
    json_path = os.path.join(gui_dir, f"gui_{GUI_NUM}.json")
    coords_path = os.path.join(gui_dir, f"gui_{GUI_NUM}_coords.json")
    try:
        # 清空当前步坐标/拉框（截图仍保留）
        editor.clear_annotations()
        editor.confirm_step()
        flush_events()

        assert editor.save_edited_round(False) is False, "缺项时保存未被阻止"
        flush_events()

        # 断言必须放在关闭之前：关闭会自动写回（silent 跳过校验）
        assert _read_json(json_path) == data, "缺项保存时最终 JSON 被改动"
        assert _read_json(coords_path)["coords"] == coords_entries, "缺项保存时坐标被改动"
    finally:
        editor._edit_final_saved = True
        try:
            editor.close()
        except Exception:
            pass


# ----------------------------------------------------------------------
# 9. 已完成轮次编辑：受保护字段（CoT / active_window / ui_tree_segment /
#    element）与未知键保留，被编辑字段为新值，原始数据不被污染；
#    status 为终止类动作专属，非终止新动作不补齐
# ----------------------------------------------------------------------

def _build_protected_dataset(base_dir):
    """单轮两步：首步带非空受保护字段与各层未知键，供编辑保存回归。"""
    gui_dir = os.path.join(str(base_dir), f"gui_{GUI_NUM}")
    os.makedirs(gui_dir, exist_ok=True)

    names = [f"gui_{GUI_NUM}_{i:04d}.png" for i in range(1, 3)]
    for i, name in enumerate(names, start=1):
        _write_png(os.path.join(gui_dir, name), i)

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
                    "coordinate": [100, 200],
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
        "platform": "Android",
        "system": "Android 13",
        "screen_size": [360, 640],
        "task_type": "Android-社交",
        "messages": [
            {"role": "user", "instruction": "唯一轮指令"},
            {"role": "assistant", "trajectory": trajectory},
        ],
    }
    coords_entries = [
        {"step": 0, "action": "click", "vertices": [50, 150, 150, 250],
         "center": [100, 200]},
        {"step": 1, "action": "click", "vertices": [150, 350, 250, 450],
         "center": [200, 400]},
    ]
    with open(os.path.join(gui_dir, f"gui_{GUI_NUM}.json"), "w",
              encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(gui_dir, f"gui_{GUI_NUM}_coords.json"), "w",
              encoding="utf-8") as f:
        json.dump({"version": "3.0", "coords": coords_entries}, f,
                  ensure_ascii=False, indent=2)
    return gui_dir, data, coords_entries


def test_save_edited_round_keeps_protected_fields_and_unknown_keys(tmp_path, qapp, modal):
    gui_dir, data, coords_entries = _build_protected_dataset(tmp_path)
    original_snapshot = copy.deepcopy(data)
    editor = _load_editor(tmp_path, gui_dir, data, coords_entries, round_index=0)
    try:
        # 编辑首步：改意图与坐标（动作仍是 click），再确认落表
        editor.intent_input.setText("打开设置-改")
        editor.coord_x_input.setText("111")
        editor.coord_y_input.setText("222")
        editor._current_vertices = [60, 170, 160, 270]
        editor.confirm_step()
        flush_events()

        assert editor.save_edited_round(False) is True
        flush_events(50)

        # 编辑器内缓存的原始已完成数据不被保存流程污染
        assert editor._completed_json == original_snapshot
    finally:
        editor._edit_final_saved = True
        try:
            editor.close()
        except Exception:
            pass

    saved = _read_json(os.path.join(gui_dir, f"gui_{GUI_NUM}.json"))
    traj = saved["messages"][1]["trajectory"]
    first = traj[0]

    # 受保护字段原样保留；status 是终止类动作专属，click 新动作不含
    # status 键，旧 status 不被补齐
    assert first["CoT"] == "下游已填的思维链"
    assert first["observation"]["active_window"] == "设置主页"
    assert first["observation"]["ui_tree_segment"] == {"nodes": ["a", "b"]}
    assert first["actions"][0]["element"] == "设置图标"
    assert "status" not in first["actions"][0]
    # 未知键（步骤层 / observation 层 / action 层）保留
    assert first["unknown_step_key"] == "保留我"
    assert first["observation"]["unknown_obs_key"] == 42
    assert first["actions"][0]["unknown_action_key"] == ["x", "y"]
    # 被编辑字段是新值
    assert first["intent"] == "打开设置-改"
    assert first["actions"][0]["coordinate"] == [111, 222]
    # 未编辑步骤逐字段不变
    assert traj[1] == data["messages"][1]["trajectory"][1]
    # 入参 data 未被原地改写
    assert data == original_snapshot


# ----------------------------------------------------------------------
# 10. 草稿路径：平铺键 / observation dict 两种承载的对称往返；无可选键时
#     磁盘结构与旧格式逐字一致
# ----------------------------------------------------------------------

def _draft_payload(steps_data, current_step_index=0):
    return {
        "gui_number": GUI_NUM,
        "app_name": f"gui_{GUI_NUM}",
        "task_instruction": "草稿指令",
        "screen_info": {"platform": "Android", "system": "Android 13",
                        "screen_size": [360, 640]},
        "app_type": "",
        "rounds": [],
        "steps_data": steps_data,
        "current_step_index": current_step_index,
        "updated_at": "2026-11-11T10:00:00",
    }


def _new_draft_editor(base_dir):
    dm = DataManager(base_dir=str(base_dir))
    dm.create_task_directory("Android")
    editor = AnnotationEditor(
        data_manager=dm,
        app_name=f"gui_{GUI_NUM}",
        task_instruction="",
        screen_info={"platform": "Android", "system": "Android 13",
                     "screen_size": [360, 640]},
        app_type="",
        serial=None,
        init_window=None,
    )
    editor.screen_capture = FakeAndroidScreenCapture()
    return editor


def test_draft_optional_keys_round_trip_flat_and_observation(tmp_path, qapp, modal):
    gui_dir = os.path.join(str(tmp_path), f"gui_{GUI_NUM}")
    os.makedirs(gui_dir, exist_ok=True)
    for i in range(1, 3):
        _write_png(os.path.join(gui_dir, f"gui_{GUI_NUM}_{i:04d}.png"), i)

    flat_step = {
        "screenshot": f"gui_{GUI_NUM}_0001.png",
        "intent": "平铺承载步",
        "action_data": {"action": "click", "coordinate": [1, 2],
                        "element": "图标", "status": "success"},
        "vertices": [0, 0, 10, 10],
        "CoT": "平铺 CoT",
        "active_window": "平铺窗口",
        "ui_tree_segment": {"nodes": ["flat"]},
    }
    obs_step = {
        "screenshot": f"gui_{GUI_NUM}_0002.png",
        "intent": "observation 承载步",
        "action_data": {"action": "terminate", "element": "",
                        "status": "success"},
        "vertices": None,
        "observation": {
            "active_window": "dict 窗口",
            "ui_tree_segment": {"nodes": ["obs"]},
        },
    }
    draft = _draft_payload([flat_step, obs_step], current_step_index=1)
    draft_path = os.path.join(gui_dir, f"gui_{GUI_NUM}_draft.json")
    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    # 编辑器 A：续采恢复，验证 load_from_draft 对称恢复两种承载
    editor_a = _new_draft_editor(tmp_path)
    try:
        loaded = editor_a.data_manager.load_draft(GUI_NUM)
        assert loaded is not None
        assert editor_a.load_from_draft(loaded) is False
        flush_events(20)

        restored = editor_a.steps_data
        # 对称恢复：平铺三字段与 observation dict 都在
        assert restored[0]["CoT"] == "平铺 CoT"
        assert restored[0]["active_window"] == "平铺窗口"
        assert restored[0]["ui_tree_segment"] == {"nodes": ["flat"]}
        assert restored[1]["observation"] == {
            "active_window": "dict 窗口",
            "ui_tree_segment": {"nodes": ["obs"]},
        }
        # 运行态绝对路径已重建
        assert restored[0]["screenshot_filepath"] == os.path.join(
            gui_dir, f"gui_{GUI_NUM}_0001.png")
        assert "screenshot_filepath" not in flat_step

        # 冻结表单→steps_data 同步（本用例只验序列化层对称，不验表单），
        # 让 _write_draft_now 按恢复出来的完整 steps_data 原样再写盘；
        # 先停防抖定时器，避免排队的草稿保存随后用空表单覆盖本次结果
        editor_a._save_current_to_steps = lambda: None
        editor_a._edit_mode = False
        editor_a.draft_timer.stop()
        editor_a._write_draft_now()
        flush_events()

        # 断言放在 close() 之前：关闭窗口会触发草稿清理，与序列化对称性无关
        redrafted = _read_json(draft_path)
        redrafted_steps = redrafted["steps_data"]
        assert redrafted_steps[0]["CoT"] == "平铺 CoT"
        assert redrafted_steps[0]["active_window"] == "平铺窗口"
        assert redrafted_steps[0]["ui_tree_segment"] == {"nodes": ["flat"]}
        assert redrafted_steps[1]["observation"] == {
            "active_window": "dict 窗口",
            "ui_tree_segment": {"nodes": ["obs"]},
        }
        # 绝不含运行态绝对路径
        for step in redrafted_steps:
            assert "screenshot_filepath" not in step

        # 编辑器 B：对再写盘的草稿二次续采，字段仍不丢
        editor_b = _new_draft_editor(tmp_path)
        try:
            reloaded = editor_b.data_manager.load_draft(GUI_NUM)
            assert reloaded is not None
            assert editor_b.load_from_draft(reloaded) is False
            flush_events(20)
            again = editor_b.steps_data
            assert again[0]["CoT"] == "平铺 CoT"
            assert again[0]["active_window"] == "平铺窗口"
            assert again[0]["ui_tree_segment"] == {"nodes": ["flat"]}
            assert again[1]["observation"] == {
                "active_window": "dict 窗口",
                "ui_tree_segment": {"nodes": ["obs"]},
            }
        finally:
            try:
                editor_b.close()
            except Exception:
                pass
    finally:
        try:
            editor_a.close()
        except Exception:
            pass


def test_draft_without_optional_keys_keeps_legacy_shape(tmp_path, qapp, modal):
    gui_dir = os.path.join(str(tmp_path), f"gui_{GUI_NUM}")
    os.makedirs(gui_dir, exist_ok=True)
    _write_png(os.path.join(gui_dir, f"gui_{GUI_NUM}_0001.png"), 1)

    legacy_step = {
        "screenshot": f"gui_{GUI_NUM}_0001.png",
        "intent": "旧格式步",
        "action_data": {"action": "click", "coordinate": [1, 2]},
        "vertices": None,
    }
    draft = _draft_payload([legacy_step])
    draft_path = os.path.join(gui_dir, f"gui_{GUI_NUM}_draft.json")
    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    editor = _new_draft_editor(tmp_path)
    try:
        loaded = editor.data_manager.load_draft(GUI_NUM)
        assert loaded is not None
        assert editor.load_from_draft(loaded) is False
        flush_events(20)

        # 恢复后仍是旧四键结构（加运行态 filepath 共五键），不凭空补可选键
        restored = editor.steps_data[0]
        assert set(restored.keys()) == {
            "screenshot", "screenshot_filepath", "intent",
            "action_data", "vertices"}

        # 冻结表单同步，按恢复现场原样再写盘；先停防抖定时器，避免排队的
        # 草稿保存随后用空表单覆盖本次序列化结果
        editor._save_current_to_steps = lambda: None
        editor._edit_mode = False
        editor.draft_timer.stop()
        editor._write_draft_now()
        flush_events()

        # 断言放在 close() 之前：关闭窗口会触发草稿清理，与序列化对称性无关
        redrafted = _read_json(draft_path)
        # 磁盘上的步骤条目与旧格式逐字一致
        assert redrafted["steps_data"] == [legacy_step]
        for step in redrafted["steps_data"]:
            assert "CoT" not in step
            assert "active_window" not in step
            assert "ui_tree_segment" not in step
            assert "observation" not in step
    finally:
        try:
            editor.close()
        except Exception:
            pass


# ----------------------------------------------------------------------
# 11. 落轮透传：_save_current_round_to_list 的 .get 三字段透传
# ----------------------------------------------------------------------

def test_save_current_round_to_list_passes_optional_fields_through(tmp_path, qapp, modal):
    gui_dir = os.path.join(str(tmp_path), f"gui_{GUI_NUM}")
    os.makedirs(gui_dir, exist_ok=True)
    for i in range(1, 3):
        _write_png(os.path.join(gui_dir, f"gui_{GUI_NUM}_{i:04d}.png"), i)

    editor = _new_draft_editor(tmp_path)
    try:
        editor.task_instruction = "落轮指令"
        editor.rounds = []
        editor.steps_data = [
            {
                "screenshot": f"gui_{GUI_NUM}_0001.png",
                "screenshot_filepath": os.path.join(
                    gui_dir, f"gui_{GUI_NUM}_0001.png"),
                "intent": "平铺透传步",
                "action_data": {"action": "click", "coordinate": [1, 2],
                                "element": "图标", "status": "success"},
                "vertices": [0, 0, 10, 10],
                "CoT": "落轮思维链",
                "active_window": "平铺窗口",
                "ui_tree_segment": {"nodes": ["t"]},
            },
            {
                "screenshot": f"gui_{GUI_NUM}_0002.png",
                "screenshot_filepath": os.path.join(
                    gui_dir, f"gui_{GUI_NUM}_0002.png"),
                "intent": "observation 承载步",
                "action_data": {"action": "terminate", "element": "",
                                "status": "success"},
                "vertices": None,
                "observation": {
                    "active_window": "dict 窗口",
                    "ui_tree_segment": {"nodes": ["o"]},
                },
            },
        ]
        editor._current_round_saved = False
        # 落轮尾部会写草稿，属正常路径
        assert editor._save_current_round_to_list(False) is True

        assert len(editor.rounds) == 1
        traj = editor.rounds[0]["trajectory"]
        assert traj[0]["CoT"] == "落轮思维链"
        assert traj[0]["observation"]["active_window"] == "平铺窗口"
        assert traj[0]["observation"]["ui_tree_segment"] == {"nodes": ["t"]}
        assert traj[1]["CoT"] == ""
        assert traj[1]["observation"]["active_window"] == "dict 窗口"
        assert traj[1]["observation"]["ui_tree_segment"] == {"nodes": ["o"]}
        for entry in traj:
            assert set(entry.keys()) == {"step", "intent", "CoT",
                                         "observation", "actions"}
            assert set(entry["observation"].keys()) == {
                "screenshot", "active_window", "ui_tree_segment"}
        assert editor.steps_data == []
    finally:
        try:
            editor.close()
        except Exception:
            pass


def test_save_current_round_to_list_defaults_to_empty_strings(tmp_path, qapp, modal):
    gui_dir = os.path.join(str(tmp_path), f"gui_{GUI_NUM}")
    os.makedirs(gui_dir, exist_ok=True)
    _write_png(os.path.join(gui_dir, f"gui_{GUI_NUM}_0001.png"), 1)

    editor = _new_draft_editor(tmp_path)
    try:
        editor.task_instruction = "无透传字段指令"
        editor.rounds = []
        editor.steps_data = [
            {
                "screenshot": f"gui_{GUI_NUM}_0001.png",
                "screenshot_filepath": os.path.join(
                    gui_dir, f"gui_{GUI_NUM}_0001.png"),
                "intent": "裸步",
                "action_data": {"action": "click", "coordinate": [1, 2]},
                "vertices": None,
            },
        ]
        editor._current_round_saved = False
        assert editor._save_current_round_to_list(False) is True

        entry = editor.rounds[0]["trajectory"][0]
        assert entry["CoT"] == ""
        assert entry["observation"]["active_window"] == ""
        assert entry["observation"]["ui_tree_segment"] == ""
        assert set(entry.keys()) == {"step", "intent", "CoT",
                                     "observation", "actions"}
    finally:
        try:
            editor.close()
        except Exception:
            pass


# ----------------------------------------------------------------------
# 12. 终止类专项：terminate / answer 编辑保存后 element==""、status=="success"，
#     步骤级三字段仍保留
# ----------------------------------------------------------------------

def _build_terminate_dataset(base_dir):
    gui_dir = os.path.join(str(base_dir), f"gui_{GUI_NUM}")
    os.makedirs(gui_dir, exist_ok=True)

    names = [f"gui_{GUI_NUM}_{i:04d}.png" for i in range(1, 3)]
    for i, name in enumerate(names, start=1):
        _write_png(os.path.join(gui_dir, name), i)

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
        "platform": "Android",
        "system": "Android 13",
        "screen_size": [360, 640],
        "task_type": "Android-社交",
        "messages": [
            {"role": "user", "instruction": "终止类轮次"},
            {"role": "assistant", "trajectory": trajectory},
        ],
    }
    coords_entries = [
        {"step": 0, "action": "terminate"},
        {"step": 1, "action": "answer", "center": [0, 0]},
    ]
    with open(os.path.join(gui_dir, f"gui_{GUI_NUM}.json"), "w",
              encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(gui_dir, f"gui_{GUI_NUM}_coords.json"), "w",
              encoding="utf-8") as f:
        json.dump({"version": "3.0", "coords": coords_entries}, f,
                  ensure_ascii=False, indent=2)
    return gui_dir, data, coords_entries


def test_terminate_and_answer_keep_empty_element_success_status(tmp_path, qapp, modal):
    gui_dir, data, coords_entries = _build_terminate_dataset(tmp_path)
    editor = _load_editor(tmp_path, gui_dir, data, coords_entries, round_index=0)
    try:
        # 首步 terminate：仅改意图后确认，动作仍为 terminate
        assert editor.action_combo.currentData() == "terminate"
        editor.intent_input.setText("任务收尾-改")
        editor.confirm_step()
        flush_events()

        # 第二步 answer：改回答文本
        editor.jump_to_step(1)
        flush_events()
        assert editor.action_combo.currentData() == "answer"
        editor.text_input.setText("更新后的答案")
        editor.confirm_step()
        flush_events()

        assert editor.save_edited_round(False) is True
        flush_events(50)
    finally:
        editor._edit_final_saved = True
        try:
            editor.close()
        except Exception:
            pass

    traj = _read_json(os.path.join(gui_dir, f"gui_{GUI_NUM}.json"))[
        "messages"][1]["trajectory"]
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
# 13. _merge_missing_keys 直接单测：空值回退 / 非空覆盖 / 非原地 /
#     深拷贝隔离 / actions 超长下标保留
# ----------------------------------------------------------------------

def _bare_editor():
    """绕过 QWidget 初始化的裸实例，仅用于不依赖 UI 状态的纯数据方法。"""
    return AnnotationEditor.__new__(AnnotationEditor)


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
    merged = editor._merge_missing_keys(
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
    merged = editor._merge_missing_keys(
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

    merged = editor._merge_missing_keys(
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
    assert editor._merge_missing_keys("新", "旧") == "新"
    assert editor._merge_missing_keys(None, "旧") is None
    # 空 list / 空 dict 的受保护空值判定
    assert AnnotationEditor._is_empty_protected_value(None) is True
    assert AnnotationEditor._is_empty_protected_value("") is True
    assert AnnotationEditor._is_empty_protected_value({}) is True
    assert AnnotationEditor._is_empty_protected_value([]) is True
    assert AnnotationEditor._is_empty_protected_value(0) is False
    assert AnnotationEditor._is_empty_protected_value("x") is False
    assert AnnotationEditor._is_empty_protected_value({"a": 1}) is False


# ---------------------------------------------------------------------------
# 源数据集不含 coords.json：缺失是合法状态（与 Windows 参考实现同口径）
# ---------------------------------------------------------------------------

def test_missing_coords_open_single_information_only(tmp_path, qapp, modal, monkeypatch):
    """无 coords.json：打开只提示一次 information，不注册 absent/mismatch、
    不弹逐步告警、不追加状态栏告警；坐标步按最终 JSON 显示 coordinate。"""
    import annotation_editor

    criticals = []
    monkeypatch.setattr(
        annotation_editor.QMessageBox, "critical",
        lambda *a, **k: criticals.append(a[1:3]),
    )

    gui_dir, data, coords_entries = _build_dataset(tmp_path, with_coords_file=False)
    assert coords_entries == []
    assert not os.path.exists(os.path.join(gui_dir, f"gui_{GUI_NUM}_coords.json"))
    editor = _load_editor(tmp_path, gui_dir, data, coords_entries, round_index=0)
    try:
        assert editor._original_coords_exist is False
        assert editor._coord_issues == []
        assert criticals == []
        assert modal.warnings == []
        assert len(modal.infos) == 1
        title, text = modal.infos[0]
        assert title == "数据集不含 coords.json"
        assert "不会生成 coords.json" in text
        assert "拉框仅更新最终 JSON 的 coordinate" in text
        assert "⚠" not in editor.status_label.text()
        # 坐标步无框预览、不带历史缺陷标记，coordinate 按最终 JSON 回填表单
        assert editor.steps_data[0]["vertices"] is None
        assert editor.steps_data[0]["coord_issue"] is None
        assert editor.steps_data[0]["action_data"]["coordinate"] == [100, 200]
        assert editor.coord_x_input.text() == "100"
        assert editor.coord_y_input.text() == "200"
        assert editor.btn_relabel.isHidden() is False
        # 缺失合法态：无框不算缺项，不阻塞保存
        assert editor.validate_step_at(0) == []
    finally:
        editor._edit_final_saved = True
        editor.close()
        flush_events(50)


def test_missing_coords_text_only_save_no_coords_generated(tmp_path, qapp, modal):
    """无 coords.json：仅改文本保存 → 最终 JSON 更新，绝不生成 coords.json。"""
    gui_dir, data, coords_entries = _build_dataset(tmp_path, with_coords_file=False)
    editor = _load_editor(tmp_path, gui_dir, data, coords_entries, round_index=0)
    json_path = os.path.join(gui_dir, f"gui_{GUI_NUM}.json")
    coords_path = os.path.join(gui_dir, f"gui_{GUI_NUM}_coords.json")
    try:
        editor.intent_input.setText("仅改文本后的意图")
        assert editor.save_edited_round(False) is True
        flush_events(50)
    finally:
        editor._edit_final_saved = True
        try:
            editor.close()
        except Exception:
            pass
        flush_events(50)

    saved = _read_json(json_path)
    assert saved["messages"][1]["trajectory"][0]["intent"] == "仅改文本后的意图"
    # 未编辑轮原样保留
    assert saved["messages"][3] == data["messages"][3]
    assert not os.path.exists(coords_path)


def test_missing_coords_relabel_updates_coordinate_without_coords_file(tmp_path, qapp, modal):
    """无 coords.json：新拉框保存 → 最终 JSON coordinate 更新为新框中心，
    仍不生成 coords.json。"""
    gui_dir, data, coords_entries = _build_dataset(tmp_path, with_coords_file=False)
    editor = _load_editor(tmp_path, gui_dir, data, coords_entries, round_index=0)
    json_path = os.path.join(gui_dir, f"gui_{GUI_NUM}.json")
    coords_path = os.path.join(gui_dir, f"gui_{GUI_NUM}_coords.json")
    try:
        assert editor.steps_data[0]["action_data"]["coordinate"] == [100, 200]
        # 重新拉框确认回调（与拉框弹窗 rect_drawn → apply 的信号路径等价）：
        # 新框 [100, 200, 300, 400]，中心 (200, 300)
        editor._on_relabel_rect(100, 200, 300, 400)
        flush_events()
        assert editor._current_vertices == [100, 200, 300, 400]
        assert editor.coord_x_input.text() == "200"
        assert editor.coord_y_input.text() == "300"
        assert editor.save_edited_round(True) is True
        flush_events(50)
    finally:
        editor._edit_final_saved = True
        try:
            editor.close()
        except Exception:
            pass
        flush_events(50)

    saved = _read_json(json_path)
    assert saved["messages"][1]["trajectory"][0]["actions"][0]["coordinate"] == [200, 300]
    assert not os.path.exists(coords_path)


def test_missing_coords_close_silent_writeback(tmp_path, qapp, modal):
    """无 coords.json：关闭自动静默写回（closeEvent → save_edited_round(silent=True)）
    同样只更新最终 JSON，不生成 coords.json。"""
    gui_dir, data, coords_entries = _build_dataset(tmp_path, with_coords_file=False)
    editor = _load_editor(tmp_path, gui_dir, data, coords_entries, round_index=0)
    json_path = os.path.join(gui_dir, f"gui_{GUI_NUM}.json")
    coords_path = os.path.join(gui_dir, f"gui_{GUI_NUM}_coords.json")
    editor.intent_input.setText("关闭前的修改")
    editor.close()
    flush_events(50)

    saved = _read_json(json_path)
    assert saved["messages"][1]["trajectory"][0]["intent"] == "关闭前的修改"
    assert saved["messages"][3] == data["messages"][3]
    assert not os.path.exists(coords_path)


def test_empty_coords_file_exists_b41_preserved(tmp_path, qapp, modal, capsys):
    """[] 空文件按存在处理：不弹缺失提示、absent 告警口径不变；
    收集到 0 条坐标时 B41 跳过写盘，保留原文件。"""
    gui_dir, data, coords_entries = _build_dataset(tmp_path)
    coords_path = os.path.join(gui_dir, f"gui_{GUI_NUM}_coords.json")
    with open(coords_path, "w", encoding="utf-8") as f:
        json.dump([], f)
    editor = _load_editor(tmp_path, gui_dir, data, [], round_index=0)
    try:
        assert editor._original_coords_exist is True
        assert modal.infos == []
        assert [issue for _, _, issue, _ in editor._coord_issues] == [
            "absent", "absent", "absent"]
        assert any(title == "coords 与坐标值不一致" for title, _ in modal.warnings)

        capsys.readouterr()
        # 本端 coords 收集对每步无条件 append（INV-7）：清空本轮步骤才能
        # 复现「导出 0 条坐标」；同时清掉当前截图文件名，避免空表单被追加回步骤
        editor.steps_data = []
        editor._current_screenshot_filename = None
        assert editor.save_edited_round(True) is True
        flush_events(50)
        out = capsys.readouterr().out
        assert "已跳过 coords 写入以保留原文件" in out
        assert os.path.exists(coords_path)
        assert _read_json(coords_path) == []
    finally:
        editor._edit_final_saved = True
        try:
            editor.close()
        except Exception:
            pass
        flush_events(50)


# ----------------------------------------------------------------------
# 14. 动作类型变更：旧动作参数键（coordinate/start_coordinate/text/keys/
#     time/pixels/buttons）不得被合并复活；未知键与受保护字段空值回退不受影响
# ----------------------------------------------------------------------

def _merge_traj_pair(new_action, old_action):
    """按 save_edited_round 的实际调用形态合并：new_traj 整体 vs original。

    步骤级周边字段取「新值为空 / 旧值非空」形态，顺带回归受保护字段回退。
    """
    editor = _bare_editor()
    old = {
        "step": 0,
        "intent": "旧意图",
        "CoT": "下游已填的思维链",
        "observation": {
            "screenshot": "gui_000001_0001.png",
            "active_window": "旧窗口",
            "ui_tree_segment": {"nodes": ["old"]},
        },
        "actions": [copy.deepcopy(old_action)],
    }
    new = {
        "step": 0,
        "intent": "新意图",
        "CoT": "",
        "observation": {
            "screenshot": "gui_000001_0001.png",
            "active_window": "",
            "ui_tree_segment": "",
        },
        "actions": [copy.deepcopy(new_action)],
    }
    return editor._merge_missing_keys(
        new, old, AnnotationEditor._PROTECTED_STEP_KEYS)


@pytest.mark.parametrize(
    "old_action, new_action, stale_key",
    [
        ({"action": "type", "coordinate": [150, 250], "text": "abc"},
         {"action": "click", "coordinate": [160, 310]}, "text"),
        ({"action": "swipe", "start_coordinate": [10, 20],
          "coordinate": [30, 40]},
         {"action": "click", "coordinate": [50, 60]}, "start_coordinate"),
        ({"action": "drag", "start_coordinate": [10, 20],
          "coordinate": [30, 40]},
         {"action": "click", "coordinate": [50, 60]}, "start_coordinate"),
        ({"action": "click", "coordinate": [100, 250]},
         {"action": "wait", "time": 1.5}, "coordinate"),
        ({"action": "scroll", "coordinate": [120, 300], "pixels": -120},
         {"action": "click", "coordinate": [310, 410]}, "pixels"),
        ({"action": "system_button", "buttons": ["Home"]},
         {"action": "click", "coordinate": [5, 6]}, "buttons"),
        ({"action": "key", "keys": ["ctrl", "a"]},
         {"action": "click", "coordinate": [7, 8]}, "keys"),
    ],
    ids=["type->click", "swipe->click", "drag->click", "click->wait",
         "scroll->click", "system_button->click", "key->click"],
)
def test_merge_action_change_drops_stale_param_keys(
        old_action, new_action, stale_key):
    """动作类型变更后，旧动作的参数键不得补进新动作（新动作自身参数照常）。"""
    merged = _merge_traj_pair(new_action, old_action)
    action = merged["actions"][0]
    assert action["action"] == new_action["action"]
    assert stale_key not in action
    for key, value in new_action.items():
        assert action[key] == value


def test_merge_action_change_keeps_unknown_action_keys():
    """动作变更只跳参数键：旧动作里的未知键仍深拷贝保留。"""
    merged = _merge_traj_pair(
        {"action": "click", "coordinate": [160, 310]},
        {"action": "type", "coordinate": [150, 250],
         "text": "abc", "foo": "bar"},
    )
    action = merged["actions"][0]
    assert "text" not in action
    assert action["foo"] == "bar"


def test_merge_action_change_keeps_protected_fallback():
    """动作变更时受保护字段空值回退规则不变（CoT/observation/element）；
    status 为终止类动作专属，新动作非终止且无 status 键时不补齐。"""
    merged = _merge_traj_pair(
        {"action": "click", "coordinate": [160, 310], "element": ""},
        {"action": "type", "coordinate": [150, 250], "text": "abc",
         "element": "输入框", "status": "success"},
    )
    action = merged["actions"][0]
    assert "text" not in action
    assert action["element"] == "输入框"
    assert "status" not in action
    assert merged["CoT"] == "下游已填的思维链"
    assert merged["observation"]["active_window"] == "旧窗口"
    assert merged["observation"]["ui_tree_segment"] == {"nodes": ["old"]}


def test_merge_same_action_still_fills_missing_keys():
    """同动作类型：缺失的参数键与未知键仍照常补齐（跳过只针对动作变更）。"""
    merged = _merge_traj_pair(
        {"action": "click", "element": ""},
        {"action": "click", "coordinate": [1, 2], "foo": "bar"},
    )
    action = merged["actions"][0]
    assert action["coordinate"] == [1, 2]
    assert action["foo"] == "bar"

    merged = _merge_traj_pair(
        {"action": "type", "coordinate": [3, 4]},
        {"action": "type", "coordinate": [3, 4], "text": "旧文本"},
    )
    assert merged["actions"][0]["text"] == "旧文本"


def test_merge_answer_terminate_serialized_as_same_type():
    """answer_terminate 序列化为 answer：旧 answer→新 answer 视为同类型。"""
    merged = _merge_traj_pair(
        {"action": "answer", "text": "新答案",
         "element": "", "status": "success"},
        {"action": "answer", "text": "旧答案", "ans_extra": 7},
    )
    action = merged["actions"][0]
    assert action["text"] == "新答案"
    assert action["status"] == "success"
    assert action["ans_extra"] == 7

    # 新 answer 缺 text 时旧值照常补齐（同类型行为不变）
    merged = _merge_traj_pair(
        {"action": "answer", "element": "", "status": "success"},
        {"action": "answer", "text": "旧答案"},
    )
    assert merged["actions"][0]["text"] == "旧答案"


def test_merge_terminate_to_click_drops_status():
    """回归：terminate 改为 click 后，旧 status 不得经缺失键补齐复活。

    新动作取 _build_action_data 产物形态（action/element/coordinate，
    无 status 键）；status 是终止类动作专属，click 结果不应含该键。
    """
    merged = _merge_traj_pair(
        {"action": "click", "element": "", "coordinate": [160, 310]},
        {"action": "terminate", "element": "", "status": "success"},
    )
    action = merged["actions"][0]
    assert action["action"] == "click"
    assert "status" not in action
    assert action["coordinate"] == [160, 310]


@pytest.mark.parametrize("silent", [False, True], ids=["normal", "silent"])
def test_save_edited_round_type_to_click_drops_stale_text(
        tmp_path, qapp, modal, silent):
    """端到端：type 步改为 click 保存后，交付 JSON 不得复活旧 text。"""
    gui_dir, data, coords_entries = _build_dataset(tmp_path)
    editor = _load_editor(tmp_path, gui_dir, data, coords_entries, round_index=0)
    json_path = os.path.join(gui_dir, f"gui_{GUI_NUM}.json")
    try:
        editor.jump_to_step(1)
        flush_events()
        assert editor.steps_data[1]["action_data"]["action"] == "type"
        assert editor.steps_data[1]["action_data"]["text"] == "abc"

        # 动作改为 click 并给合法坐标（vertices 沿用原步载入的拉框）
        editor.action_combo.setCurrentIndex(
            editor.action_combo.findData("click"))
        editor.coord_x_input.setText("160")
        editor.coord_y_input.setText("310")
        editor.confirm_step()
        flush_events()

        assert editor.save_edited_round(silent) is True
        flush_events(50)
    finally:
        editor._edit_final_saved = True
        try:
            editor.close()
        except Exception:
            pass
        flush_events(50)

    saved = _read_json(json_path)
    action = saved["messages"][1]["trajectory"][1]["actions"][0]
    assert action["action"] == "click"
    assert "text" not in action
    assert action["coordinate"] == [160, 310]
    # 未编辑轮不受影响
    assert saved["messages"][3] == data["messages"][3]


def test_save_edited_round_terminate_to_click_drops_status(tmp_path, qapp, modal):
    """端到端：terminate 步改为 click（重新拉框填坐标）保存后，
    交付 JSON 该步 actions[0] 不得含 status 键。"""
    gui_dir, data, coords_entries = _build_terminate_dataset(tmp_path)
    editor = _load_editor(tmp_path, gui_dir, data, coords_entries, round_index=0)
    json_path = os.path.join(gui_dir, f"gui_{GUI_NUM}.json")
    try:
        assert editor.steps_data[0]["action_data"]["action"] == "terminate"
        assert editor.steps_data[0]["action_data"]["status"] == "success"

        # 动作改为 click；terminate 原无拉框，走真实[重新拉框]入口的
        # 落表回调，提供 vertices 与坐标（新框中心 150,250）
        editor.action_combo.setCurrentIndex(
            editor.action_combo.findData("click"))
        editor._on_relabel_rect(100, 200, 200, 300)
        flush_events()
        editor.confirm_step()
        flush_events()

        assert editor.save_edited_round(False) is True
        flush_events(50)
    finally:
        editor._edit_final_saved = True
        try:
            editor.close()
        except Exception:
            pass
        flush_events(50)

    saved = _read_json(json_path)
    action = saved["messages"][1]["trajectory"][0]["actions"][0]
    assert action["action"] == "click"
    assert "status" not in action
    assert action["coordinate"] == [150, 250]
    # 同轮 answer 步不受影响（终止类 status 保留）
    assert saved["messages"][1]["trajectory"][1] == data["messages"][1]["trajectory"][1]
