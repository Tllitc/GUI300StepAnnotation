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


def _build_dataset(base_dir):
    """在 base_dir 下构造两轮已完成数据集（coords 无 round 字段）

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
    with open(os.path.join(gui_dir, f"gui_{GUI_NUM}_coords.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "3.0", "coords": coords_entries}, f,
                  ensure_ascii=False, indent=2)
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
