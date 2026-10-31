# -*- coding: utf-8 -*-
"""Task 4：删除当前步骤（delete_current_step）数据一致性测试组

覆盖 SubTask 4.1~4.10：
- 4.1  删中间步，后续步前移且不串数据
- 4.2  删首步/末步/唯一一步的定位与引用连续
- 4.3  删空全部步骤回初始空白态、可重新走步
- 4.4  DA-7 窗口竞态：50ms singleShot 触发前删除当前步/前序步
- 4.5  DA-7 后台竞态：ADB 后台线程在途时删除使下标前移且 == capture_step
- 4.6  DA-8：删除处于 scroll 测量中的步骤
- 4.7  DA-8：删除处于 swipe 测量中的步骤
- 4.8  DA-6：answer 收尾一轮后删除新轮步骤，历史轮截图引用不误删
- 4.9  删除确认框选 No：模型/磁盘/草稿均不变
- 4.10 删除后 finish_task：最终 JSON/coords 引用连续无缺失
"""
import copy
import hashlib
import json
import os
import threading
import time

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QMessageBox

from fakes import FakeAndroidScreenCapture
from helpers import (capture_and_wait, confirm_n_steps, fill_valid_step,
                     finish_task, flush_events)
from invariants import assert_all, assert_final_json


# ---------------------------------------------------------------- 工具


class DelayedFakeAndroidScreenCapture(FakeAndroidScreenCapture):
    """可配置延迟的桩截图器：模拟 ADB 后台线程耗时，用于 DA-7 后台竞态"""

    def __init__(self, delay_ms=300, **kwargs):
        super().__init__(**kwargs)
        self.delay_ms = delay_ms
        self.started = threading.Event()

    def capture(self, output_path=None):
        self.started.set()
        time.sleep(self.delay_ms / 1000.0)
        return super().capture(output_path)


def _wait_lock_released(editor, timeout_ms=15000):
    """分片推进事件循环直到截图锁释放（含 800ms 冷却）"""
    waited = 0
    while editor._screenshot_in_progress and waited < timeout_ms:
        QTest.qWait(30)
        waited += 30
    flush_events()
    assert not editor._screenshot_in_progress, "截图锁未在超时内释放"


def _snapshot_steps(editor):
    """提取 steps_data 的可比较字段快照"""
    return copy.deepcopy([
        {k: s.get(k) for k in ("screenshot", "intent", "action_data", "vertices")}
        for s in editor.steps_data
    ])


def _disk_png_hashes(gui_dir):
    return {name: hashlib.sha256(open(os.path.join(gui_dir, name), "rb").read()).hexdigest()
            for name in os.listdir(gui_dir) if name.endswith(".png")}


def _delete_all_steps(editor):
    """逐步删除直到 steps_data 为空（每次删末步）"""
    while editor.steps_data:
        if not (0 <= editor.current_step < len(editor.steps_data)):
            editor.jump_to_step(len(editor.steps_data) - 1)
        editor.delete_current_step()
        flush_events(30)


# ---------------------------------------------------------------- 4.1 删中间步


def test_delete_middle_step_shifts_following(editor_factory, modal):
    """SubTask 4.1：5 步删第 3 步（index 2），后续步前移且数据不串"""
    editor = editor_factory()
    confirm_n_steps(editor, 5)
    before = _snapshot_steps(editor)

    editor.jump_to_step(2)
    editor.delete_current_step()
    flush_events(50)

    assert len(editor.steps_data) == 4
    # 被删步文件已删除
    assert not os.path.isfile(os.path.join(editor.gui_dir, before[2]["screenshot"]))
    # 前两个保持不动，后续步前移且截图/vertices/action_data 不串
    for i in range(4):
        expected = before[i] if i < 2 else before[i + 1]
        got = editor.steps_data[i]
        for key in ("screenshot", "intent", "action_data", "vertices"):
            assert got.get(key) == expected[key], f"第 {i} 步字段 {key} 串位"
    # 删除后定位在被删位置（即原下一步）
    assert editor.current_step == 2
    assert_all(editor)


# ---------------------------------------------------------------- 4.2 删首步/末步/唯一一步


def test_delete_first_last_only_step(editor_factory, modal):
    """SubTask 4.2：删除首步/末步/唯一一步，current_step 停留位置正确"""
    # --- 删首步 ---
    ed_first = editor_factory()
    confirm_n_steps(ed_first, 3)
    before = _snapshot_steps(ed_first)
    ed_first.jump_to_step(0)
    ed_first.delete_current_step()
    flush_events(50)
    assert [s["screenshot"] for s in ed_first.steps_data] == \
           [before[1]["screenshot"], before[2]["screenshot"]]
    assert ed_first.current_step == 0
    assert not os.path.isfile(os.path.join(ed_first.gui_dir, before[0]["screenshot"]))
    assert_all(ed_first)

    # --- 删末步 ---
    ed_last = editor_factory()
    confirm_n_steps(ed_last, 3)
    before = _snapshot_steps(ed_last)
    ed_last.jump_to_step(2)
    ed_last.delete_current_step()
    flush_events(50)
    assert [s["screenshot"] for s in ed_last.steps_data] == \
           [before[0]["screenshot"], before[1]["screenshot"]]
    assert ed_last.current_step == 1 == len(ed_last.steps_data) - 1
    assert not os.path.isfile(os.path.join(ed_last.gui_dir, before[2]["screenshot"]))
    assert_all(ed_last)

    # --- 删唯一一步 ---
    ed_only = editor_factory()
    confirm_n_steps(ed_only, 1)
    before = _snapshot_steps(ed_only)
    ed_only.jump_to_step(0)
    ed_only.delete_current_step()
    flush_events(50)
    assert ed_only.steps_data == []
    assert ed_only.current_step == 0
    assert ed_only._current_screenshot_filename is None
    assert not os.path.isfile(os.path.join(ed_only.gui_dir, before[0]["screenshot"]))
    assert_all(ed_only)


# ---------------------------------------------------------------- 4.3 删空全部步骤


def test_delete_all_steps_back_to_blank(editor_factory, modal):
    """SubTask 4.3：删空全部步骤 → 初始空白态 → 可重新截图走步"""
    editor = editor_factory()
    confirm_n_steps(editor, 3)
    _delete_all_steps(editor)

    # 初始空白态
    assert editor.steps_data == []
    assert editor.current_step == 0
    assert editor._current_screenshot_filename is None
    assert editor._current_screenshot_filepath is None
    assert editor._current_vertices is None
    # 磁盘无残留截图
    assert not [n for n in os.listdir(editor.gui_dir) if n.endswith(".png")]
    assert_all(editor)

    # 可重新截图走步，草稿同步一致（含在 assert_all 内）
    confirm_n_steps(editor, 2)
    assert len(editor.steps_data) == 2
    assert_all(editor)


# ---------------------------------------------------------------- 4.4 DA-7 窗口竞态


def test_delete_prev_step_during_screenshot_window(editor_factory, modal):
    """SubTask 4.4a：截图 50ms 窗口内删除前序步被拦截；步骤切走使结果被丢弃；锁复位后可删"""
    editor = editor_factory()
    confirm_n_steps(editor, 3)
    before = _snapshot_steps(editor)

    editor.jump_to_step(1)
    editor.take_screenshot()          # capture_step=1，singleShot 尚未触发
    assert editor._screenshot_in_progress
    editor.jump_to_step(0)            # 切到前序步（同步调用，窗口内）

    # DA-7 修复后：在途删除被拦截，steps_data/磁盘不变、状态栏提示
    editor.delete_current_step()
    assert "截图进行中" in editor.status_label.text()
    assert len(editor.steps_data) == 3
    _wait_lock_released(editor)

    # 截图结果因 capture_step(1) != current_step(0) 被丢弃（既有 L1694 语义），模型/磁盘不变
    assert len(editor.steps_data) == 3
    assert [s["screenshot"] for s in editor.steps_data] == \
           [before[0]["screenshot"], before[1]["screenshot"], before[2]["screenshot"]]

    # 锁复位后删除可正常执行
    editor.delete_current_step()
    flush_events(50)
    assert [s["screenshot"] for s in editor.steps_data] == \
           [before[1]["screenshot"], before[2]["screenshot"]]
    assert editor._current_screenshot_filename == before[1]["screenshot"]
    assert_all(editor)


def test_delete_current_step_during_screenshot_window(editor_factory, modal):
    """SubTask 4.4b：截图 50ms 窗口内删除当前步被拦截（DA-7 修复）；截图完成后可正常删除"""
    editor = editor_factory()
    confirm_n_steps(editor, 3)
    before = _snapshot_steps(editor)

    editor.jump_to_step(1)
    editor.take_screenshot()          # capture_step=1
    assert editor._screenshot_in_progress

    # 在途删除被拦截：模型/磁盘不变、状态栏提示
    editor.delete_current_step()
    assert "截图进行中" in editor.status_label.text()
    assert len(editor.steps_data) == 3
    _wait_lock_released(editor)

    # 截图正常完成写入原步骤（capture_step==current_step==1，重截同名复用），无串图/孤儿
    assert len(editor.steps_data) == 3
    assert [s["screenshot"] for s in editor.steps_data] == \
           [before[0]["screenshot"], before[1]["screenshot"], before[2]["screenshot"]]
    assert editor._current_screenshot_filename == before[1]["screenshot"]

    # 锁复位后删除可正常执行：后续步前移、不串数据
    editor.delete_current_step()
    flush_events(50)
    assert [s["screenshot"] for s in editor.steps_data] == \
           [before[0]["screenshot"], before[2]["screenshot"]]
    assert_all(editor)


# ---------------------------------------------------------------- 4.5 DA-7 后台竞态


def test_delete_during_background_capture_shifted_index(editor_factory, modal):
    """SubTask 4.5：ADB 后台线程在途时删除当前步被拦截（DA-7 修复）；完成后可正常删除"""
    editor = editor_factory()
    editor.screen_capture = DelayedFakeAndroidScreenCapture(delay_ms=300)
    confirm_n_steps(editor, 3)
    before = _snapshot_steps(editor)

    editor.jump_to_step(1)
    editor.take_screenshot()          # capture_step=1
    # 等待 50ms singleShot 已触发、后台线程已进入 capture（300ms 延迟窗口内）
    deadline = 5000
    waited = 0
    while not editor.screen_capture.started.is_set() and waited < deadline:
        QTest.qWait(20)
        waited += 20
    assert editor.screen_capture.started.is_set(), "后台截图线程未触发"

    # 在途删除被拦截：模型/磁盘不变、状态栏提示，下标不再前移穿透 capture_step 校验
    editor.delete_current_step()
    assert "截图进行中" in editor.status_label.text()
    assert len(editor.steps_data) == 3
    assert editor.current_step == 1
    _wait_lock_released(editor)

    # 截图正常完成写入原步骤（重截同名复用），无串图、无孤儿
    assert len(editor.steps_data) == 3
    assert [s["screenshot"] for s in editor.steps_data] == \
           [before[0]["screenshot"], before[1]["screenshot"], before[2]["screenshot"]]

    # 锁复位后删除可正常执行：后续步前移、不串数据
    editor.delete_current_step()
    flush_events(50)
    assert [s["screenshot"] for s in editor.steps_data] == \
           [before[0]["screenshot"], before[2]["screenshot"]]
    assert_all(editor)


# ---------------------------------------------------------------- 4.6/4.7 DA-8 测量中删除


def test_delete_step_in_scroll_measurement(editor_factory, modal):
    """SubTask 4.6：删除处于 scroll 测量中的步骤 → 测量态复位、随后截图正常写入"""
    editor = editor_factory()
    confirm_n_steps(editor, 3)

    editor.jump_to_step(1)
    editor._current_vertices = [100, 200, 300, 400]
    editor.coord_x_input.setText("200")
    editor.coord_y_input.setText("300")
    editor._start_scroll_measurement()
    assert editor._scroll_measuring is True

    editor.delete_current_step()
    flush_events(50)
    # 测量态复位（INV-9 由 assert_all 复核）
    assert editor._scroll_measuring is False
    assert editor._scroll_start_vertices is None
    assert_all(editor)

    # 随后截图链路正常：确认末步走到末尾新步，截图写入新的当前步
    fill_valid_step(editor, action="click")
    editor.confirm_step()
    flush_events(50)
    assert editor.current_step == len(editor.steps_data)
    name = capture_and_wait(editor)
    assert name and editor._current_screenshot_filename == name
    fill_valid_step(editor, action="click")
    editor.confirm_step()
    flush_events(50)
    assert editor.steps_data[len(editor.steps_data) - 1]["screenshot"] == name
    assert_all(editor)


def test_delete_step_in_swipe_measurement(editor_factory, modal):
    """SubTask 4.7：删除处于 swipe 测量中的步骤 → 测量态复位"""
    editor = editor_factory()
    confirm_n_steps(editor, 3)

    editor.jump_to_step(1)
    editor._current_vertices = [100, 200, 300, 400]
    editor._start_swipe_measurement()
    assert editor._swipe_measuring is True
    assert editor._swipe_start_vertices == [100, 200, 300, 400]

    editor.delete_current_step()
    flush_events(50)
    assert editor._swipe_measuring is False
    assert editor._swipe_start_vertices is None
    assert_all(editor)


# ---------------------------------------------------------------- 4.8 DA-6 跨轮删除


def test_delete_in_new_round_keeps_history_round_files(editor_factory, modal):
    """SubTask 4.8：answer 收尾一轮 → 新轮走步 → 删除新轮步骤，历史 rounds 截图文件不丢"""
    editor = editor_factory()
    confirm_n_steps(editor, 2)
    # 第 3 步以 answer 收尾轮 1，flush 300ms 让 _start_new_round 执行
    capture_and_wait(editor)
    fill_valid_step(editor, action="answer")
    editor.confirm_step()
    flush_events(400)
    assert len(editor.rounds) == 1
    assert editor.steps_data == [] and editor._current_round_saved is False

    round1_refs = [t["observation"]["screenshot"]
                   for t in editor.rounds[0]["trajectory"]]
    assert len(round1_refs) == 3

    # 新一轮走 2 步后删除新轮第 1 步
    confirm_n_steps(editor, 2)
    editor.jump_to_step(0)
    editor.delete_current_step()
    flush_events(50)

    # 历史轮引用的截图文件仍存在、未被误删（DA-6 引用检查未覆盖 rounds 的交叉验证）
    for fn in round1_refs:
        assert os.path.isfile(os.path.join(editor.gui_dir, fn)), f"历史轮截图被误删: {fn}"
    assert len(editor.steps_data) == 1
    assert_all(editor)


# ---------------------------------------------------------------- 4.9 确认框选 No


def test_delete_cancelled_by_modal_no(editor_factory, modal):
    """SubTask 4.9：删除确认框选 No → steps_data、磁盘文件哈希、草稿均不变"""
    editor = editor_factory()
    confirm_n_steps(editor, 3)
    editor.jump_to_step(1)
    flush_events(50)

    steps_before = _snapshot_steps(editor)
    hashes_before = _disk_png_hashes(editor.gui_dir)
    editor._write_draft_now()
    flush_events()
    draft_path = os.path.join(editor.gui_dir, f"gui_{editor.gui_number}_draft.json")
    with open(draft_path, encoding="utf-8") as f:
        draft_before = json.load(f)

    modal.question_reply = QMessageBox.No
    editor.delete_current_step()
    flush_events(50)

    assert modal.questions, "删除确认框未弹出"
    assert _snapshot_steps(editor) == steps_before
    assert editor.current_step == 1
    assert _disk_png_hashes(editor.gui_dir) == hashes_before
    editor._write_draft_now()
    flush_events()
    with open(draft_path, encoding="utf-8") as f:
        draft_after = json.load(f)
    draft_before.pop("updated_at", None)
    draft_after.pop("updated_at", None)
    assert draft_after == draft_before
    assert_all(editor)


# ---------------------------------------------------------------- 4.10 删除后结束任务


def test_delete_then_finish_task_final_json(editor_factory, modal):
    """SubTask 4.10：删除中间步后 finish_task，最终 JSON/coords 引用连续无缺失"""
    editor = editor_factory()
    confirm_n_steps(editor, 4)
    before = _snapshot_steps(editor)
    # 被删步文件内容哈希（安卓端序号复用空洞，answer 新截图可能取同名，需按内容区分）
    with open(os.path.join(editor.gui_dir, before[1]["screenshot"]), "rb") as f:
        deleted_hash = hashlib.sha256(f.read()).hexdigest()

    editor.jump_to_step(1)
    editor.delete_current_step()
    flush_events(50)
    assert len(editor.steps_data) == 3
    assert_all(editor)

    # 走到末尾新步再收尾，避免 finish_task 的截图落到中间步变成重截
    editor.jump_to_step(len(editor.steps_data) - 1)
    fill_valid_step(editor, action="click")
    editor.confirm_step()
    flush_events(50)
    assert editor.current_step == len(editor.steps_data)
    finish_task(editor, modal)
    flush_events(100)

    data = assert_final_json(editor.gui_dir, editor.gui_number)
    traj = data["messages"][1]["trajectory"]
    assert len(traj) == 4  # 3 步保留 + answer 收尾步
    # 保留步骤的截图引用与原第 0/2/3 步一致（顺序前移，不串）
    kept = [before[0]["screenshot"], before[2]["screenshot"], before[3]["screenshot"]]
    assert [t["observation"]["screenshot"] for t in traj[:3]] == kept
    # 被删步的原始截图内容不出现在最终产物引用中（允许序号复用，按内容判定）
    for t in traj:
        fn = t["observation"]["screenshot"]
        with open(os.path.join(editor.gui_dir, fn), "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() != deleted_hash, \
                f"最终 JSON 仍引用被删步截图内容: {fn}"
