# -*- coding: utf-8 -*-
"""「已完成任务可再次编辑」回归测试。

覆盖：从最终 JSON + coords 重建编辑现场、只替换被编辑轮次、编辑模式不写草稿、
关闭窗口自动写回、必填校验阻止保存、旧 coords 无 round 的多轮切分，
以及「coords 的 bbox 必须属于它自己那一步」（INV-14 / hydration 两趟匹配 /
写回守卫）的四个回归场景。
"""

import os
import copy
import json

from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtTest import QTest

import annotation_editor as _ae
import helpers as H
import invariants as I

_SHOT_W, _SHOT_H = 1920, 1080


# ---------------------------------------------------------------------------
# 数据集构造
# ---------------------------------------------------------------------------
def _write_png(path, rgb):
    """写一张真实 PNG：INV-8 断言 trajectory 引用的截图必须存在于磁盘"""
    pm = QPixmap(_SHOT_W, _SHOT_H)
    pm.fill(QColor(*rgb))
    assert pm.save(path, "PNG"), f"测试夹具写入 PNG 失败：{path}"


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
        # 顶点必须与 center / JSON coordinate 满 Product 口径 center = x + w//2
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


def _iter_shots(data):
    """最终 JSON 里被 trajectory 引用到的截图名（去重后稳定排序）"""
    shots = set()
    for message in (data or {}).get("messages", []) or []:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for entry in message.get("trajectory") or []:
            if not isinstance(entry, dict):
                continue
            shot = (entry.get("observation") or {}).get("screenshot")
            if shot:
                shots.add(shot)
    return sorted(shots)


def _write_dataset(editor, data, coords, write_coords=True):
    """把最终 JSON、coords 与其引用的截图写进 editor.data_manager 对应的 gui 目录

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
    for i, name in enumerate(_iter_shots(data)):
        _write_png(os.path.join(gui_dir, name), ((40 * (i + 1)) % 256, 90, 130))
    return gui_dir


def _single_round_data(gui_number, step_specs, instruction="单轮测试指令", shot_start=1):
    """构造 1 轮的最终 JSON：step_specs = [(action, actions[0] 的附加字段), ...]

    截图自 shot_start 起顺序编号（多轮拼接时由调用方传入偏移，INV-8 要求截图
    跨轮全局唯一）。坐标值只写在 JSON 的 actions[0] 里 ——
    编辑态的坐标输入框只读，其值由 hydration 从 JSON 回填，因此构造「框与坐标值
    对不上」这类盘上数据时，唯一诚实的入口就是直接写 JSON。
    :return: (data, [截图名, ...])
    """
    shots = [f"gui_{gui_number}_{shot_start + i:04d}.png" for i in range(len(step_specs))]
    trajectory = []
    for i, (action, extra) in enumerate(step_specs):
        action_data = {"action": action, "element": "", "status": "success"}
        action_data.update(extra)
        trajectory.append({
            "step": i,
            "intent": f"步骤{i}",
            "CoT": "",
            "observation": {
                "screenshot": shots[i],
                "active_window": "测试App",
                "ui_tree_segment": "",
            },
            "actions": [action_data],
        })
    data = {
        "platform": "Windows 11",
        "system": "Windows 11",
        "screen_size": [1920, 1080],
        "task_type": "Windows-测试",
        "messages": [
            {"role": "user", "instruction": instruction},
            {"role": "assistant", "trajectory": trajectory},
        ],
    }
    return data, shots


def _prepare_dataset(editor, data, coords, round_index=0):
    """落盘自定义数据集后走产品入口进编辑态，返回 (gui_dir, before_data, before_coords)"""
    gui_dir = _write_dataset(editor, data, coords)
    before_data, before_coords = H.open_edit_mode(editor, gui_dir, round_index)
    return gui_dir, before_data, before_coords


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
# 6. coords 的 bbox 必须属于它自己那一步（INV-14 / hydration 两趟匹配 / 写回守卫）
# ---------------------------------------------------------------------------
def test_legacy_coords_missing_scroll_entry_does_not_steal_neighbor_box(editor):
    """B6 遗留交付件（coords 少 scroll 条目）：编辑态绝不冒领邻居步的框。

    旧版 _find_coord_entry 在按 step 落空时回退取「列表第 i 条」，条目数与步数
    一旦错位，下标就漂到别的工作上，写回时污染 bbox 以正确 step 编号落盘
    （gui_000005 交付时的 4 组重复 bbox 正是这一形态）。现在只按 step 精确匹配，
    落空才按 center 验证恢复，两者都落空就判定「框丢失」而不是猜位置。

    INV-8 / INV-14 的传参约定：写回后 scroll 步在 coords 中确实没有条目（工具
    不凭空造框，也没有盘上原条目可继承），故该步以 fullscreen_refs={(0, 1)}
    同时豁免覆盖层与中心层。
    """
    gui = editor.gui_number
    data, _shots = _single_round_data(gui, [
        ("left_click", {"coordinate": [200, 300], "element": "按钮"}),
        ("scroll", {"coordinate": [152, 315], "direction": "down"}),
    ])
    coords = [{"step": 0, "action": "left_click",
               "vertices": [100, 200, 300, 400], "center": [200, 300]}]
    gui_dir, before_data, before_coords = _prepare_dataset(editor, data, coords)

    assert len(editor.steps) == 2
    assert editor.steps[0]["rect_info"] == (100, 200, 200, 200)
    assert editor.steps[0]["coord_issue"] is None
    # scroll 步：盘上没有属于它的条目 → 框不载入，但坐标值仍如实来自 JSON
    assert editor.steps[1]["rect_info"] == ()
    assert editor.steps[1]["coord_issue"] == "absent"
    # 绝不能退回 "fullscreen"：validate_step_at 的全屏豁免会把丢框变成静默缺陷
    assert editor.steps[1]["selection_type"] != "fullscreen"
    assert editor.steps[1]["orig_coord_entry"] is None
    assert [issue for _i, _a, issue, _d in editor._coord_issues] == ["absent"]
    assert "⚠ 检测到 1 个步骤" in editor.status_label.text()

    assert editor.save_edited_round(silent=True) is True

    saved_coords = H.read_final_coords(editor)
    # 既没有凭空多出第二组顶点，也没有把唯一真实的 step0 条目弄丢
    assert saved_coords == [{**coords[0], "round": 0}]
    saved = H.read_final_json(editor)
    assert saved["messages"][1]["trajectory"][1]["actions"][0]["coordinate"] == [152, 315]

    I.assert_edit_writeback_preserved(gui_dir, gui, before_data, before_coords, 0)
    I.assert_final_json(editor, expected_rounds=1, fullscreen_refs={(0, 1)})


def test_legacy_entry_step_drift_recovered_by_center(editor):
    """step 编号漂移但框本身正确：按 center 恢复匹配必须把框认回来。

    旧交付件里 coords 条目的 step 可能整体错位（B6 少条目后再被位置回退写盘），
    但「同 action 且框中心 == 已交付 coordinate」是对真实内容的验证，不是对列表
    位置的猜测，应当恢复载入而不是判成丢框。

    漂移条目排在同 step 的正确条目之后：_find_coord_entry 不看 action、首个 step
    命中即认领，若排在前面会把正确条目挤掉，真正归属该条目的步骤反而无据可查。
    """
    gui = editor.gui_number
    data, _shots = _single_round_data(gui, [
        ("left_click", {"coordinate": [200, 300]}),
        ("left_click", {"coordinate": [600, 700]}),
        ("scroll", {"coordinate": [152, 315], "direction": "down"}),
    ])
    coords = [
        {"step": 0, "action": "left_click",
         "vertices": [100, 200, 300, 400], "center": [200, 300]},
        {"step": 1, "action": "left_click",
         "vertices": [500, 600, 700, 800], "center": [600, 700]},
        # scroll 的框真实存在，step 却被写成 1（整体漂移）
        {"step": 1, "action": "scroll",
         "vertices": [120, 308, 184, 323], "center": [152, 315]},
    ]
    gui_dir, before_data, before_coords = _prepare_dataset(editor, data, coords)

    assert editor.steps[0]["rect_info"] == (100, 200, 200, 200)
    assert editor.steps[1]["rect_info"] == (500, 600, 200, 200)
    # 漂移条目按 center 被 step 2 认领，不产生任何告警
    assert editor.steps[2]["rect_info"] == (120, 308, 64, 15)
    assert editor.steps[2]["coord_issue"] is None
    assert editor.steps[2]["orig_coord_entry"] is None
    assert editor._coord_issues == []
    assert editor.steps[2]["editor"].coord_x_input.text() == "152"

    assert editor.save_edited_round(silent=True) is True

    saved_coords = H.read_final_coords(editor)
    assert len(saved_coords) == 3
    scroll_entry = saved_coords[-1]
    # 恢复成功即走正常写回：条目按真实步序重编号，顶点逐字段不变
    assert scroll_entry["step"] == 2 and scroll_entry["action"] == "scroll"
    assert scroll_entry["vertices"] == [120, 308, 184, 323]
    assert scroll_entry["center"] == [152, 315]

    I.assert_edit_writeback_preserved(gui_dir, gui, before_data, before_coords, 0)
    I.assert_final_json(editor, expected_rounds=1)


def test_center_mismatch_not_loaded_and_disk_entry_preserved(editor):
    """框中心与坐标值对不上：不采信该框，但盘上原条目一个字节都不改。

    「不采信」不等于「丢弃」—— A4 让写回按当前步序原样继承该条目，避免采集员
    只是打开看了一眼就永久丢掉已交付的顶点；A5 的审计把这类继承条目列为豁免，
    所以保存不会被历史缺陷阻塞（本轮新写的框若不一致仍会被拒，见下一用例）。

    INV-8 / INV-14 的传参约定：mismatch 步的条目**必须**仍在盘上（覆盖层照常
    要求，否则丢框会被静默放过），只是中心与坐标值故意保持不一致，故用
    center_exempt_refs={(0, 1)} 只豁免中心层。
    """
    gui = editor.gui_number
    data, shots0 = _single_round_data(gui, [
        ("left_click", {"coordinate": [200, 300], "element": "按钮"}),
        ("scroll", {"coordinate": [152, 315], "direction": "down"}),
    ], instruction="第一轮指令")
    data1, _shots1 = _single_round_data(
        gui, [("left_click", {"coordinate": [600, 700], "element": "输入框"})],
        instruction="第二轮指令", shot_start=len(shots0) + 1)
    data["messages"].extend(data1["messages"])

    click_entry = {"step": 0, "action": "left_click", "round": 0,
                   "vertices": [100, 200, 300, 400], "center": [200, 300]}
    # 盘上 bbox 属于别的工作：中心 (530, 607) 与交付 coordinate [152, 315] 差数百像素
    bad_scroll = {"step": 1, "action": "scroll", "round": 0,
                  "vertices": [500, 600, 560, 615], "center": [530, 607]}
    round1_entry = {"step": 0, "action": "left_click", "round": 1,
                    "vertices": [500, 600, 700, 800], "center": [600, 700]}
    coords = [click_entry, copy.deepcopy(bad_scroll), round1_entry]
    gui_dir, before_data, before_coords = _prepare_dataset(editor, data, coords, 0)

    assert editor.steps[0]["coord_issue"] is None
    assert editor.steps[1]["rect_info"] == ()
    assert editor.steps[1]["coord_issue"] == "mismatch"
    assert editor.steps[1]["selection_type"] != "fullscreen"
    assert editor.steps[1]["orig_coord_entry"] == bad_scroll
    assert [issue for _i, _a, issue, _d in editor._coord_issues] == ["mismatch"]

    editor.steps[0]["editor"].intent_input.setText("只改第一轮的动作描述")
    assert editor.save_edited_round() is True

    # ⚠ silent=False 保存成功后产品会 close() + deleteLater()：此处起不得再推进
    # 事件循环，后续只读纯 Python 属性（目录/编号已缓存在局部变量）
    saved_coords = H.read_final_coords(editor)
    by_key = {(e["round"], e["step"]): e for e in saved_coords}
    assert by_key[(0, 1)] == bad_scroll, "继承性缺陷条目被改写或丢弃"
    assert by_key[(0, 0)] == click_entry
    assert by_key[(1, 0)] == round1_entry

    saved = H.read_final_json(editor)
    assert saved["messages"][1]["trajectory"][0]["intent"] == "只改第一轮的动作描述"
    assert saved["messages"][3] == before_data["messages"][3]

    I.assert_edit_writeback_preserved(gui_dir, gui, before_data, before_coords, 0)
    I.assert_final_json(editor, expected_rounds=2, center_exempt_refs={(0, 1)})


def test_writeback_guard_rejects_inconsistent_fresh_box(editor, capsys):
    """本轮新写的框与坐标值对不上 → 写回整体中止，磁盘连 .bak 都不生成。

    直接改 steps[i]["rect_info"] 而不更新只读的坐标输入框，等价于重现「位置冒领」
    之后的现场：内存 bbox 是错的、JSON coordinate 是对的。守卫必须在改内存和写盘
    之前拦住（先验后改），否则错误 bbox 会以正确 step 编号落进已交付数据 ——
    正是本次事故的写回环节。

    INV-8 / INV-14 的传参约定：中止是零副作用的，盘上仍是自洽交付件，故本用例
    不做任何豁免，结尾的 assert_final_json 会实打实跑一遍 INV-14。
    """
    gui = editor.gui_number
    data, _shots = _single_round_data(gui, [
        ("left_click", {"coordinate": [200, 300], "element": "按钮"}),
    ])
    coords = [{"step": 0, "action": "left_click",
               "vertices": [100, 200, 300, 400], "center": [200, 300]}]
    gui_dir, _before_data, _before_coords = _prepare_dataset(editor, data, coords)
    assert editor._coord_issues == []
    snap = I.snapshot_dir(gui_dir)

    editor.steps[0]["rect_info"] = (900, 700, 64, 15)
    assert editor.save_edited_round(silent=True) is False
    out = capsys.readouterr().out
    assert "编辑写回中止" in out
    assert "coords 与坐标值不一致" in out

    I.assert_dir_unchanged(gui_dir, snap)
    # 中止必须零副作用：本轮轨迹与该轮 coords 都保持载入时的原值
    assert editor.rounds[0]["trajectory"][0]["actions"][0]["coordinate"] == [200, 300]
    assert editor._coords_rounds[0] == coords

    # 非 silent 路径同样拒绝（弹窗不阻塞，conftest 已桩化），磁盘依旧零变化
    assert editor.save_edited_round(silent=False) is False
    assert not [n for n in os.listdir(gui_dir) if n.endswith(".bak")]
    I.assert_dir_unchanged(gui_dir, snap)

    I.assert_final_json(editor, expected_rounds=1)


# ---------------------------------------------------------------------------
# 字段级防御性合并回归（_merge_step_with_original）
#
# 缺陷背景：编辑已完成任务 / 草稿续采时，StepEditorWidget.get_data() 重建的
# 步骤字典只携带表单上有的字段，ui_tree_segment 无表单控件必然丢失，
# element/CoT/active_window 被用户清空时也会产出空值。旧实现以新字典整体
# 覆盖原步骤，会把下游标注字段与未知键静默清空。新实现改为字段级合并：
# 受保护字段空值回退原值、终止动作强制 element=""/status="success"、
# original 独有键深拷贝保留，且全程不原地修改入参。
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


def _write_rich_dataset(editor):
    """单轮富字段数据集 + 匹配 coords + 真实 PNG（INV-8 需要截图存在）。"""
    gui = editor.gui_number
    shot = f"gui_{gui}_0001.png"
    original_step = _rich_step(gui, shot, {
        "action": "left_click",
        "coordinate": [200, 300],
        "element": "原始按钮",
        "status": "success",
    })
    data = {
        "platform": "Windows 11",
        "system": "Windows 11",
        "screen_size": [1920, 1080],
        "task_type": "Windows-测试",
        "messages": [
            {"role": "user", "instruction": "第一轮指令"},
            {"role": "assistant", "trajectory": [original_step]},
        ],
    }
    coords = [
        {"step": 0, "action": "left_click",
         "vertices": [100, 200, 300, 400], "center": [200, 300]},
    ]
    gui_dir = _write_dataset(editor, data, coords)
    _write_png(os.path.join(gui_dir, shot), (10, 20, 30))
    return data, coords, gui_dir, original_step, shot


def test_edit_completed_preserves_protected_fields_and_unknown_keys(editor):
    """编辑已完成任务保存后：受保护字段与未知键逐字保留，被编辑字段为新值，
    且内存中的原始已完成数据（跨样本载体 _completed_json）不被污染。"""
    data, coords, gui_dir, original_step, shot = _write_rich_dataset(editor)
    source_snapshot = copy.deepcopy(data)
    editor.load_from_completed_json(data, coords, 0, gui_dir)
    QTest.qWait(50)

    assert len(editor.steps) == 1
    ed = editor.steps[0]["editor"]
    # 只改普通字段（意图、动作目标文本），并把带表单的受保护/准保护字段清空，
    # 模拟用户清空输入框后保存；ui_tree_segment 无表单，get_data() 必然丢。
    ed.intent_input.setText("编辑后的新意图")
    ed.cot_input.clear()
    ed.active_window_input.clear()
    ed.element_input.clear()
    QTest.qWait(20)

    assert editor.save_edited_round(silent=True) is True

    saved = H.read_final_json(editor)
    saved_step = saved["messages"][1]["trajectory"][0]

    # 受保护字段：空值回退到原始值，逐字保留
    assert saved_step["CoT"] == "原始推理链，禁止被空值覆盖"
    assert saved_step["observation"]["active_window"] == "原始窗口标题"
    assert saved_step["observation"]["ui_tree_segment"] == "<node>原始 UI 树片段</node>"
    assert saved_step["actions"][0]["element"] == "原始按钮"
    assert saved_step["actions"][0]["status"] == "success"
    # 原始步骤独有的未知键深拷贝保留
    assert saved_step["downstream_meta"] == {"x": 1, "nested": ["a", "b"]}
    # 截图键始终以 get_data() 的新值为准
    assert saved_step["observation"]["screenshot"] == shot
    # 被编辑的普通字段采用新值
    assert saved_step["intent"] == "编辑后的新意图"

    # 跨样本防护：内存中的已完成 JSON 与入参数据源都不被写回流程污染
    assert editor._completed_json == source_snapshot
    assert data == source_snapshot


def test_edit_completed_non_empty_protected_value_overrides(editor):
    """受保护字段填入新的非空值时应正常覆盖（只有空值才回退）。"""
    data, coords, gui_dir, original_step, shot = _write_rich_dataset(editor)
    editor.load_from_completed_json(data, coords, 0, gui_dir)
    QTest.qWait(50)

    ed = editor.steps[0]["editor"]
    ed.cot_input.setText("编辑后的新推理链")
    ed.active_window_input.setText("编辑后的新窗口")
    ed.element_input.setText("编辑后的新元素")
    QTest.qWait(20)

    assert editor.save_edited_round(silent=True) is True
    saved_step = H.read_final_json(editor)["messages"][1]["trajectory"][0]

    assert saved_step["CoT"] == "编辑后的新推理链"
    assert saved_step["observation"]["active_window"] == "编辑后的新窗口"
    assert saved_step["actions"][0]["element"] == "编辑后的新元素"
    # 无表单的 ui_tree_segment 仍回退原值
    assert saved_step["observation"]["ui_tree_segment"] == "<node>原始 UI 树片段</node>"
    # 未知键依旧保留
    assert saved_step["downstream_meta"] == {"x": 1, "nested": ["a", "b"]}


def test_draft_resume_edit_preserves_protected_fields(editor):
    """草稿续采：load_from_draft 恢复带非空受保护字段的步骤，编辑保存并
    再落草稿后，受保护字段不被 get_data() 的空值覆盖，动作类型为新值。"""
    gui = editor.gui_number
    gui_dir = os.path.join(editor.data_manager.current_dir, f"gui_{gui}")
    os.makedirs(gui_dir, exist_ok=True)
    shot = f"gui_{gui}_0001.png"
    _write_png(os.path.join(gui_dir, shot), (10, 20, 30))

    rich_data = _rich_step(gui, shot, {
        "action": "left_click",
        "coordinate": [200, 300],
        "element": "原始按钮",
        "status": "success",
    })
    draft = {
        "gui_number": gui,
        "app_name": editor.app_name,
        "task_instruction": "续采指令",
        "screen_info": editor.screen_info,
        "app_type": editor.app_type,
        "rounds": [{"instruction": "续采指令", "trajectory": []}],
        "current_steps": [{
            "screenshot_filename": shot,
            "rect_info": [100, 200, 200, 200],
            "selection_type": None,
            "data": rich_data,
        }],
        "coords_entries": [],
        "updated_at": "2026-01-01T00:00:00",
    }

    editor.load_from_draft(copy.deepcopy(draft))
    QTest.qWait(100)
    assert len(editor.steps) == 1

    # 切换动作类型（left_click → right_click）并改意图；坐标框只读，沿用原框
    # 派生的 (200,300)。注意不能走 recapture：其回调会 pop 掉 step["data"]，
    # 而那份快照正是字段级合并的回退原值来源。
    H.fill_step(editor, 0, action_chinese="右键单击", intent="续采编辑意图",
                coord_text="200,300")
    # 主动清空带表单的受保护字段，制造空值回退场景
    ed = editor.steps[0]["editor"]
    ed.cot_input.clear()
    ed.active_window_input.clear()
    ed.element_input.clear()

    H.save_current(editor)
    saved_step = editor.steps[0]["data"]

    # 受保护字段回退到草稿原值
    assert saved_step["CoT"] == "原始推理链，禁止被空值覆盖"
    assert saved_step["observation"]["active_window"] == "原始窗口标题"
    assert saved_step["observation"]["ui_tree_segment"] == "<node>原始 UI 树片段</node>"
    assert saved_step["actions"][0]["element"] == "原始按钮"
    assert saved_step["actions"][0]["status"] == "success"
    assert saved_step["downstream_meta"] == {"x": 1, "nested": ["a", "b"]}
    # 动作类型采用新值，坐标沿用原框派生值
    assert saved_step["actions"][0]["action"] == "right_click"
    assert saved_step["actions"][0]["coordinate"] == [200, 300]
    assert saved_step["intent"] == "续采编辑意图"

    # 再触发草稿落盘，磁盘草稿同样保留受保护字段
    H.flush_draft(editor)
    disk_draft = H.read_draft(editor)
    disk_step = disk_draft["current_steps"][0]["data"]
    assert disk_step["CoT"] == "原始推理链，禁止被空值覆盖"
    assert disk_step["observation"]["ui_tree_segment"] == "<node>原始 UI 树片段</node>"
    assert disk_step["actions"][0]["action"] == "right_click"
    assert disk_step["downstream_meta"] == {"x": 1, "nested": ["a", "b"]}


def test_terminal_action_forces_empty_element_and_success_status(editor):
    """终止类动作（terminate）编辑保存后强制 element=""/status="success"，
    同时 CoT/active_window/ui_tree_segment 仍按保留规则不丢。"""
    gui = editor.gui_number
    shot = f"gui_{gui}_0001.png"
    terminal_step = _rich_step(gui, shot, {
        "action": "terminate",
        "element": "历史遗留的非空元素",
        "status": "failed",
    })
    data = {
        "platform": "Windows 11",
        "system": "Windows 11",
        "screen_size": [1920, 1080],
        "task_type": "Windows-测试",
        "messages": [
            {"role": "user", "instruction": "第一轮指令"},
            {"role": "assistant", "trajectory": [terminal_step]},
        ],
    }
    # terminate 无坐标，coords 给空数组即可
    gui_dir = _write_dataset(editor, data, [])
    _write_png(os.path.join(gui_dir, shot), (10, 20, 30))
    editor.load_from_completed_json(data, [], 0, gui_dir)
    QTest.qWait(50)

    assert len(editor.steps) == 1
    assert editor.save_edited_round(silent=True) is True

    saved_action = H.read_final_json(editor)["messages"][1]["trajectory"][0]
    assert saved_action["actions"][0]["action"] == "terminate"
    assert saved_action["actions"][0]["element"] == ""
    assert saved_action["actions"][0]["status"] == "success"
    # 终止动作的强制规则不影响其余受保护字段的保留
    assert saved_action["CoT"] == "原始推理链，禁止被空值覆盖"
    assert saved_action["observation"]["active_window"] == "原始窗口标题"
    assert saved_action["observation"]["ui_tree_segment"] == "<node>原始 UI 树片段</node>"
    assert saved_action["downstream_meta"] == {"x": 1, "nested": ["a", "b"]}


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
    data, _shots = _single_round_data(gui, [
        ("left_click", {"coordinate": [200, 300]}),
    ])
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
    _prepare_dataset(editor, data, coords)

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
    data, _shots = _single_round_data(gui, [("terminate", {})])
    terminal_step = data["messages"][1]["trajectory"][0]
    terminal_step["CoT"] = "终止步CoT"
    terminal_step["observation"]["active_window"] = "终止步窗口"
    terminal_step["observation"]["ui_tree_segment"] = "终止步UI树片段"
    terminal_step["actions"][0]["element"] = "残留元素"
    terminal_step["actions"][0]["status"] = "failed"

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
    gui_dir = os.path.join(editor.data_manager.current_dir, f"gui_{gui}")
    os.makedirs(gui_dir, exist_ok=True)
    shot = f"gui_{gui}_0001.png"
    _write_png(os.path.join(gui_dir, shot), (10, 20, 30))

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
    H.open_edit_mode(editor, gui_dir, 0)

    # 走完整 UI 入口在原图上重新拉框：(400, 500, 200, 100) → 中心 (500, 550)
    H.relabel_rect(editor, 0, rect=(400, 500, 200, 100), selection_type="click")
    assert editor.steps[0]["rect_info"] == (400, 500, 200, 100)

    assert editor.save_edited_round(silent=True) is True

    saved = H.read_final_json(editor)
    assert saved["messages"][1]["trajectory"][0]["actions"][0]["coordinate"] == [500, 550]
    assert not os.path.exists(_coords_path_of(editor, gui_dir))


def test_missing_coords_close_silent_writeback(editor):
    """silent=True 关闭写回：返回 True，最终 JSON 写入，不生成 coords.json"""
    data, coords = _make_dataset(editor.gui_number, with_coords_file=False)
    gui_dir = _write_dataset(editor, data, coords, write_coords=False)
    H.open_edit_mode(editor, gui_dir, 0)

    editor.steps[0]["editor"].intent_input.setText("关闭前修改")
    assert editor.save_edited_round(silent=True) is True

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
