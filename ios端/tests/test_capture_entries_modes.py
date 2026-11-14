# -*- coding: utf-8 -*-
"""截图入口双拆分（给下一步截图 / 重新截图）在编辑已完成任务与草稿续采
两种模式下的回归测试（新采标模式见 test_capture_entries.py）。

覆盖:
  1. 编辑模式「重新截图」：同名原地覆盖、intent 文本保留、不写草稿、
     不提前写回磁盘 JSON
  2. 编辑模式「给下一步截图」-> confirm_step 提交新步进 steps_data ->
     save_edited_round 写回：trajectory/coords 均含新步、原步受保护字段
     不被空值覆盖、磁盘无孤儿截图
  3. 编辑模式「在此步后插入截图」且锚点步截图文件缺失：锚点步文本修改
     保留、coord_issue/orig_coord_entry 不丢
  4. 草稿续采（load_from_draft）：「给下一步截图」追加新文件且游标到
     待确认空位、「重新截图」原地覆盖，行为与新采标一致

数据集构造复用 test_edit_completed 的 _build_dataset/_build_raw_dataset；
截图走 conftest 注入的 FakeScreenCapture + 产品真实 50ms QTimer 链路。
"""

import os

from PyQt5.QtTest import QTest

from data_manager import DataManager
from helpers import (
    _wait_until,
    confirm,
    distinct_capture_seed,
    fill_step,
    flush_draft,
    open_edit_mode,
    walk_steps,
)
from test_edit_completed import (
    GUI_NUMBER,
    _build_dataset,
    _build_raw_dataset,
    _click_step,
    _draft_files,
    _load_coords,
    _load_json,
    _scroll_step,
)


def _capture_done(ed, message):
    """等待真实 take_screenshot -> 50ms QTimer -> _do_screenshot 链路完成。"""
    _wait_until(lambda: not ed._screenshot_in_progress, message=message)
    QTest.qWait(80)


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


# ----------------------------------------------------------------------
# 1. 编辑模式「重新截图」：原地覆盖 + 文本保留 + 不写草稿
# ----------------------------------------------------------------------

def test_edit_mode_recapture_keeps_text_and_writes_no_draft(
        editor_factory, qapp, tmp_path):
    gui_dir, data, _coords = _build_dataset(str(tmp_path), with_round=True)
    ed = editor_factory(auto_init=False)
    open_edit_mode(ed, gui_dir, round_index=0)

    ed.intent_input.setText("打开设置-改")
    # 数据集已占用 SHOT 1~4，推进种子保证重截图字节确实变化
    distinct_capture_seed(ed, 4)
    target = os.path.join(gui_dir, f"gui_{GUI_NUMBER}_0001.png")
    old_bytes = _read_bytes(target)

    ed.recapture_current_step()
    _capture_done(ed, "编辑模式重新截图未在超时内复位")

    # 同名原地覆盖：不新增文件、游标不动
    assert ed._current_screenshot_filename == f"gui_{GUI_NUMBER}_0001.png"
    assert ed.current_step == 0
    assert len(ed.steps_data) == 2
    assert ed.steps_data[0]["screenshot_filepath"] == target
    assert _read_bytes(target) != old_bytes
    assert len([f for f in os.listdir(gui_dir) if f.endswith(".png")]) == 4

    # 替换分支不清表单：文本修改保留，确认后落表
    assert ed.intent_input.text() == "打开设置-改"
    ed.confirm_step()
    qapp.processEvents()
    assert ed.steps_data[0]["intent"] == "打开设置-改"
    assert "已更新第 1 步" in ed.status_label.text()

    # 编辑模式不写草稿；重新截图/确认也不写回磁盘（唯一写回入口是保存修改）
    ed.schedule_draft_save()
    ed._write_draft_now()
    qapp.processEvents()
    assert _draft_files(gui_dir) == []
    assert _load_json(gui_dir) == data

    # 跳过 teardown close 的静默写回（本用例不验证写回）
    ed._final_data_saved = True


# ----------------------------------------------------------------------
# 2. 编辑模式「给下一步截图」-> 确认 -> 保存写回（死胡同修复）
# ----------------------------------------------------------------------

def test_edit_mode_capture_next_confirm_then_save_round(
        editor_factory, qapp, tmp_path):
    gui_dir, data, coords = _build_dataset(str(tmp_path), with_round=True)
    ed = editor_factory(auto_init=False)
    open_edit_mode(ed, gui_dir, round_index=0)

    distinct_capture_seed(ed, 4)
    ed.start_capture()
    _capture_done(ed, "编辑模式追加截图未在超时内复位")

    new_name = f"gui_{GUI_NUMBER}_0005.png"
    assert ed._current_screenshot_filename == new_name
    assert os.path.isfile(os.path.join(gui_dir, new_name))
    # 待确认空位：尚未落表，游标停在 len(steps_data)
    assert len(ed.steps_data) == 2
    assert ed.current_step == 2 == len(ed.steps_data)
    assert ed.steps_data[0]["screenshot"] == f"gui_{GUI_NUMBER}_0001.png"

    fill_step(ed, action="click", intent="新增步")
    ed.confirm_step()
    qapp.processEvents()

    # 新步提交进 steps_data，游标留在新步下标；不切轮、不结束任务
    assert len(ed.steps_data) == 3
    assert ed.current_step == 2
    assert ed.steps_data[2]["intent"] == "新增步"
    assert ed.steps_data[2]["screenshot"] == new_name
    assert "已新增第 3 步（编辑模式）" in ed.status_label.text()
    assert ed._missing_live is None
    assert len(ed._missing_cache) == 3
    assert len(ed.sidebar.item_widgets) == 3
    assert len(ed.rounds) == 2
    assert ed._round_transition_pending is False
    assert ed._final_data_saved is False
    assert _draft_files(gui_dir) == []

    assert ed.save_edited_round(False) is True
    qapp.processEvents()

    saved = _load_json(gui_dir)
    traj = saved["messages"][1]["trajectory"]
    assert len(traj) == 3
    assert traj[2]["step"] == 2
    assert traj[2]["intent"] == "新增步"
    assert traj[2]["observation"]["screenshot"] == new_name
    assert traj[2]["actions"][0]["coordinate"] == [100, 250]
    # 原步受保护字段不被空值覆盖；status 为终止类动作专属，
    # type 新动作不含 status 键，旧 status 不被补齐
    assert traj[0]["observation"]["note"] == "round0-step0"
    assert "status" not in traj[0]["actions"][0]
    assert traj[1] == data["messages"][1]["trajectory"][1]
    # 其余轮次逐字不变
    assert saved["messages"][3] == data["messages"][3]

    saved_coords = _load_coords(gui_dir)
    round0 = [e for e in saved_coords if e.get("round") == 0]
    round1 = [e for e in saved_coords if e.get("round") == 1]
    assert len(round0) == 3
    assert len(round1) == 2
    assert round0[2]["step"] == 2
    assert round0[2]["action"] == "click"
    assert round0[2]["vertices"] == [50, 200, 150, 300]
    assert round0[2]["center"] == [100, 250]
    for idx in range(2):
        for key in ("step", "action", "vertices", "center"):
            assert round1[idx][key] == coords[2 + idx][key]

    # 磁盘无孤儿截图：每个 PNG 都被最终 JSON 的 trajectory 引用
    referenced = {
        entry["observation"]["screenshot"]
        for msg in saved["messages"] if msg.get("role") == "assistant"
        for entry in msg.get("trajectory", [])
    }
    on_disk = {f for f in os.listdir(gui_dir) if f.endswith(".png")}
    assert on_disk == referenced
    assert _draft_files(gui_dir) == []


# ----------------------------------------------------------------------
# 3. 编辑模式插入截图：锚点步截图缺失时文本与坐标标记不丢
# ----------------------------------------------------------------------

def test_edit_mode_insert_keeps_missing_anchor_text_and_coord_markers(
        editor_factory, qapp, tmp_path):
    bad_scroll = {"step": 1, "action": "scroll", "vertices": [30, 300, 90, 360],
                  "center": [60, 330], "round": 0, "source": "coords-v1"}
    entries = [
        {"step": 0, "action": "click", "vertices": [40, 140, 160, 260],
         "center": [100, 200], "round": 0},
        bad_scroll,
        {"step": 2, "action": "click", "vertices": [130, 450, 230, 550],
         "center": [180, 500], "round": 0},
    ]
    steps = [
        _click_step("点击搜索", (100, 200)),
        _scroll_step("上滑列表", (300, 400)),
        _click_step("点击结果", (180, 500)),
    ]
    gui_dir, _data = _build_raw_dataset(str(tmp_path), steps, entries)
    ed = editor_factory(auto_init=False)
    open_edit_mode(ed, gui_dir, round_index=0)

    # 载入即判定 mismatch：框不采信，原条目留在 orig_coord_entry
    assert ed.steps_data[1]["coord_issue"] == "mismatch"
    assert ed.steps_data[1]["orig_coord_entry"] == bad_scroll

    # 删除锚点步截图文件 -> 切到锚点步进入“截图缺失”态
    os.remove(os.path.join(gui_dir, f"gui_{GUI_NUMBER}_0002.png"))
    ed.display_step(1)
    qapp.processEvents()
    assert ed._screenshot_missing is True
    assert ed._current_screenshot_filename is None

    ed.intent_input.setText("锚点文本-改")
    ed.start_insert_capture()
    _capture_done(ed, "编辑模式插入截图未在超时内复位")

    assert len(ed.steps_data) == 4
    assert ed.current_step == 2
    assert ed.steps_data[2]["screenshot"] == f"gui_{GUI_NUMBER}_0004.png"
    assert os.path.isfile(os.path.join(gui_dir, f"gui_{GUI_NUMBER}_0004.png"))
    # 锚点步文本修改保留（edit 版落表不因缺图早退）
    assert ed.steps_data[1]["intent"] == "锚点文本-改"
    # coord_issue / orig_coord_entry 不丢，坐标/像素原样
    assert ed.steps_data[1]["coord_issue"] == "mismatch"
    assert ed.steps_data[1]["orig_coord_entry"] == bad_scroll
    assert ed.steps_data[1]["vertices"] is None
    assert ed.steps_data[1]["action_data"]["coordinate"] == [300, 400]
    assert ed.steps_data[1]["action_data"]["pixels"] == -120

    # 跳过 teardown close 的静默写回（插入步未填表单，本用例不验证写回）
    ed._final_data_saved = True


# ----------------------------------------------------------------------
# 4. 草稿续采：两个入口行为与新采标一致
# ----------------------------------------------------------------------

def test_draft_resume_capture_entries_match_new_capture(
        editor, editor_factory, qapp, dm):
    gui_dir = editor.gui_dir

    # 第一实例：采 2 步后落草稿，使命结束（防 teardown 写回旧草稿）
    walk_steps(editor, 2, action="click")
    flush_draft(editor)
    editor._draft_discarded = True

    # 第二实例：真实构造 + load_from_draft 指回同一 gui_dir
    ed2 = editor_factory()
    draft = DataManager.load_draft_from_dir(gui_dir)
    assert draft is not None
    assert ed2.load_from_draft(draft) is False
    assert ed2._edit_mode is False
    assert ed2.gui_dir == gui_dir
    assert ed2.gui_number == GUI_NUMBER
    assert len(ed2.steps_data) == 2
    assert ed2.current_step == 1
    assert ed2._current_screenshot_filename == f"gui_{GUI_NUMBER}_0002.png"

    # 给下一步截图：追加新文件，游标到待确认空位（与新采标一致）
    distinct_capture_seed(ed2, 2)
    ed2.start_capture()
    _capture_done(ed2, "草稿续采追加截图未在超时内复位")
    new_name = f"gui_{GUI_NUMBER}_0003.png"
    assert ed2._current_screenshot_filename == new_name
    assert os.path.isfile(os.path.join(gui_dir, new_name))
    assert len(ed2.steps_data) == 2
    assert ed2.current_step == 2 == len(ed2.steps_data)
    assert ed2._capture_append_new_step is False

    # 重新截图（待确认空位）：同名原地覆盖，不新增步
    pending_path = os.path.join(gui_dir, new_name)
    old_bytes = _read_bytes(pending_path)
    ed2.recapture_current_step()
    _capture_done(ed2, "草稿续采待确认位重截图未在超时内复位")
    assert ed2._current_screenshot_filename == new_name
    assert ed2.current_step == 2
    assert len(ed2.steps_data) == 2
    assert _read_bytes(pending_path) != old_bytes

    # 确认新步：同新采标，落表后进入下一空位
    fill_step(ed2, action="click", intent="续采新步")
    confirm(ed2)
    assert len(ed2.steps_data) == 3
    assert ed2.steps_data[2]["intent"] == "续采新步"
    assert ed2.current_step == 3 == len(ed2.steps_data)

    # 重新截图（已落表步）：回到第 1 步原地覆盖
    ed2.display_step(0)
    qapp.processEvents()
    first_path = os.path.join(gui_dir, f"gui_{GUI_NUMBER}_0001.png")
    old_first = _read_bytes(first_path)
    ed2.recapture_current_step()
    _capture_done(ed2, "草稿续采已落表步重截图未在超时内复位")
    assert ed2._current_screenshot_filename == f"gui_{GUI_NUMBER}_0001.png"
    assert ed2.current_step == 0
    assert len(ed2.steps_data) == 3
    assert _read_bytes(first_path) != old_first

    # 非编辑模式：草稿自动保存照常（与新采标一致）
    flush_draft(ed2)
    saved_draft = dm.load_draft(GUI_NUMBER)
    assert saved_draft is not None
    assert len(saved_draft["steps_data"]) == 3
