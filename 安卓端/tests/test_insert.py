# -*- coding: utf-8 -*-
"""Task 5 插入截图测试组（SubTask 5.1~5.8）

覆盖「在当前步后插入」（start_insert_capture / _on_screenshot_finished 插入分支）：
- 5.1 中间插入后业务顺序与图步单射
- 5.2 插入确认后 current_step 只前进一格（2.8/B22）与随后走到末尾空位追加
- 5.3 插入→删除新步→再插入的持续一致性
- 5.4 插入截图在途期间删除锚点步（锚点失效场景）
- 5.5 插入截图在途期间 undo_step / go_previous（capture_step 校验丢弃）
- 5.6 插入截图失败后锚点复位，普通截图不误入插入分支
- 5.7 scroll/swipe 测量中点插入的边界行为
- 5.8 插入后草稿落盘 → 续采恢复 → 再次插入/删除
"""
import os
import time

import pytest
from PyQt5.QtTest import QTest

from fakes import FakeAndroidScreenCapture
from helpers import (capture_and_wait, drain_sidebar_thumbs, fill_valid_step,
                     flush_events)
from invariants import assert_all, assert_resume_consistent, assert_transient


class DelayedFakeCapture(FakeAndroidScreenCapture):
    """带 ADB 延迟的桩截图器：后台线程 capture 多耗 delay_s 秒，模拟截图在途"""

    def __init__(self, delay_s=0.3, **kwargs):
        super().__init__(**kwargs)
        self._delay_s = delay_s

    def capture(self, output_path=None):
        time.sleep(self._delay_s)
        return super().capture(output_path)


def insert_capture_and_wait(editor, timeout_ms=10000):
    """发起「在当前步后插入」截图并等待完成（含 800ms 冷却），返回新截图文件名"""
    prev_seq = editor._screenshot_seq
    editor.start_insert_capture()
    if editor._screenshot_seq == prev_seq:
        raise AssertionError("start_insert_capture 未发起截图（前置校验未通过）")
    waited = 0
    while editor._screenshot_in_progress and waited < timeout_ms:
        QTest.qWait(30)
        waited += 30
    flush_events()
    if editor._screenshot_in_progress:
        raise AssertionError(f"插入截图未在 {timeout_ms}ms 内完成")
    return editor._current_screenshot_filename


def wait_inflight_settled(editor, timeout_ms=10000):
    """等待在途截图结果被主线程处理完毕（锚点复位且锁释放）"""
    waited = 0
    while (editor._insert_after_index is not None
           or editor._screenshot_in_progress) and waited < timeout_ms:
        QTest.qWait(30)
        waited += 30
    flush_events()
    if editor._insert_after_index is not None or editor._screenshot_in_progress:
        raise AssertionError("在途截图结果未在超时时间内处理完毕")


def make_three_steps(editor):
    """确认 3 步（意图 S1/S2/S3），返回各步截图文件名快照"""
    for intent in ("S1", "S2", "S3"):
        capture_and_wait(editor)
        fill_valid_step(editor, intent=intent)
        editor.confirm_step()
        flush_events(50)
    return [s["screenshot"] for s in editor.steps_data]


def highlighted_indexes(editor):
    """侧栏中处于高亮（当前步）的条目下标"""
    return [i for i, item in enumerate(editor.sidebar.item_widgets)
            if "#E3F2FD" in item.styleSheet()]


def gui_pngs(editor):
    return sorted(n for n in os.listdir(editor.gui_dir) if n.endswith(".png"))


# ===== SubTask 5.1：中间插入，业务顺序 1-新-2-3 =====

def test_insert_middle_keeps_business_order(editor_factory):
    editor = editor_factory()
    shots = make_three_steps(editor)

    editor.jump_to_step(0)
    new_shot = insert_capture_and_wait(editor)
    # 插入后立即落在空白新步（锚点+1）
    assert editor.current_step == 1
    assert len(editor.steps_data) == 4
    assert editor.steps_data[1]["screenshot"] == new_shot

    fill_valid_step(editor, intent="S-new")
    editor.confirm_step()
    flush_events(50)

    # 业务顺序 1-新-2-3，原三步截图引用各自不变，新步引用新文件
    assert [s["intent"] for s in editor.steps_data] == ["S1", "S-new", "S2", "S3"]
    assert editor.steps_data[0]["screenshot"] == shots[0]
    assert editor.steps_data[2]["screenshot"] == shots[1]
    assert editor.steps_data[3]["screenshot"] == shots[2]
    assert new_shot not in shots
    assert_all(editor)


# ===== SubTask 5.2：插入确认后只前进一格，随后追加不乱序 =====

def test_insert_confirm_advances_one_then_appends(editor_factory):
    editor = editor_factory()
    shots = make_three_steps(editor)

    editor.jump_to_step(0)
    insert_capture_and_wait(editor)
    fill_valid_step(editor, intent="S-new")
    editor.confirm_step()
    flush_events(50)

    # 2.8（B22）：确认插入步后只前进一格（1 -> 2），不传送到末尾、不清空表单
    assert editor.current_step == 2
    assert len(editor.steps_data) == 4
    # 现场已回填第 3 步：截图指针指向该步自己的图，而不是空位的 None
    assert editor._current_screenshot_filename == editor.steps_data[2]["screenshot"]
    assert editor.intent_input.text() == "S2"
    # 侧栏 4 条目、截图引用无重复、高亮落在前进后的那一步
    assert len(editor.sidebar.item_widgets) == 4
    filenames = [s["screenshot"] for s in editor.steps_data]
    assert len(set(filenames)) == 4
    assert highlighted_indexes(editor) == [2]
    assert_all(editor)

    # 一路 go_next 走到末尾待截图空位（B22 后中间步确认不弹末尾，靠导航走到）
    limit = len(editor.steps_data) + 2
    while editor.current_step < len(editor.steps_data) and limit > 0:
        editor.go_next()
        flush_events()
        limit -= 1
    assert editor.current_step == len(editor.steps_data) == 4

    # 末尾普通截图走追加分支：新步落在末尾，已有顺序与引用不变
    capture_and_wait(editor)
    fill_valid_step(editor, intent="S5")
    editor.confirm_step()
    flush_events(50)
    assert [s["intent"] for s in editor.steps_data] == \
        ["S1", "S-new", "S2", "S3", "S5"]
    assert editor.steps_data[0]["screenshot"] == shots[0]
    assert editor.steps_data[2]["screenshot"] == shots[1]
    assert editor.steps_data[3]["screenshot"] == shots[2]
    assert_all(editor)


# ===== SubTask 5.3：插入→删除新步→再插入，持续一致 =====

def test_insert_then_delete_and_reinsert(editor_factory):
    editor = editor_factory()
    make_three_steps(editor)

    editor.jump_to_step(0)
    insert_capture_and_wait(editor)
    fill_valid_step(editor, intent="S-new")
    editor.confirm_step()
    flush_events(50)
    assert [s["intent"] for s in editor.steps_data] == ["S1", "S-new", "S2", "S3"]
    new_shot = editor.steps_data[1]["screenshot"]

    # 删除插入的新步：模型/磁盘同步移除
    editor.jump_to_step(1)
    editor.delete_current_step()
    flush_events(50)
    assert [s["intent"] for s in editor.steps_data] == ["S1", "S2", "S3"]
    assert not os.path.isfile(os.path.join(editor.gui_dir, new_shot))
    assert_all(editor)

    # 再在第 2 步后插入一步
    editor.jump_to_step(1)
    insert_capture_and_wait(editor)
    fill_valid_step(editor, intent="S-new2")
    editor.confirm_step()
    flush_events(50)
    assert [s["intent"] for s in editor.steps_data] == ["S1", "S2", "S-new2", "S3"]
    assert_all(editor)


# ===== SubTask 5.4：插入截图在途期间删除锚点步 =====

def test_insert_inflight_delete_anchor_step(editor_factory):
    """SubTask 5.4：插入截图在途期间删除锚点步被拦截（DA-7 修复），插入正常完成"""
    editor = editor_factory()
    editor.screen_capture = DelayedFakeCapture(delay_s=0.3)
    make_three_steps(editor)

    editor.jump_to_step(0)
    editor.start_insert_capture()
    assert editor._insert_after_index == 0
    flush_events(100)  # 50ms singleShot 已触发，后台线程截图在途（300ms 延迟）

    # 在途期间删除锚点步被拦截：模型/磁盘不变、状态栏提示
    editor.delete_current_step()
    assert "截图进行中" in editor.status_label.text()
    assert len(editor.steps_data) == 3
    wait_inflight_settled(editor)

    # 插入正常完成在锚点后：步骤数+1、落在新插入空白步
    assert len(editor.steps_data) == 4
    assert editor.current_step == 1
    fill_valid_step(editor, intent="S-new")
    editor.confirm_step()
    flush_events(50)
    assert [s["intent"] for s in editor.steps_data] == ["S1", "S-new", "S2", "S3"]
    assert_transient(editor)
    assert_all(editor)


# ===== SubTask 5.5：插入截图在途期间 undo / 导航 =====

def test_insert_inflight_undo_intercepted(editor_factory):
    """5.5 undo 子场景：插入截图在途期间撤销被拦截（DA-7 修复），插入正常完成"""
    editor = editor_factory()
    editor.screen_capture = DelayedFakeCapture(delay_s=0.3)
    shots = make_three_steps(editor)

    editor.jump_to_step(0)
    editor.start_insert_capture()
    assert editor._insert_after_index == 0
    flush_events(100)  # 后台截图在途

    # 在途期间撤销被拦截：模型/磁盘不变、状态栏提示
    editor.undo_step()
    assert "截图进行中" in editor.status_label.text()
    assert len(editor.steps_data) == 3
    wait_inflight_settled(editor)

    # 插入正常完成在锚点后
    assert len(editor.steps_data) == 4
    assert editor.current_step == 1
    fill_valid_step(editor, intent="S-new")
    editor.confirm_step()
    flush_events(50)
    assert [s["intent"] for s in editor.steps_data] == ["S1", "S-new", "S2", "S3"]
    assert editor.steps_data[0]["screenshot"] == shots[0]
    assert editor.steps_data[2]["screenshot"] == shots[1]
    assert editor.steps_data[3]["screenshot"] == shots[2]
    assert_transient(editor)
    assert_all(editor)


def test_insert_confirm_then_undo_cleans_thumb_cache(editor_factory):
    """5.5 DA-2 回归：插入确认后撤销末步，undo 清理侧栏缩略图缓存，assert_all 全绿"""
    editor = editor_factory()
    make_three_steps(editor)

    editor.jump_to_step(0)
    insert_capture_and_wait(editor)
    fill_valid_step(editor, intent="S-new")
    editor.confirm_step()
    flush_events(50)
    assert [s["intent"] for s in editor.steps_data] == ["S1", "S-new", "S2", "S3"]
    drain_sidebar_thumbs(editor)  # 末步缩略图入缓存
    last_fn = editor.steps_data[-1]["screenshot"]

    editor.undo_step()  # 弹末步
    flush_events()
    assert [s["intent"] for s in editor.steps_data] == ["S1", "S-new", "S2"]
    # 缩略图缓存无已删文件残留
    stale = [k for k in editor.sidebar._thumb_cache if k and k[0] == last_fn]
    assert not stale
    assert_all(editor)


def test_insert_inflight_go_previous_discards_capture(editor_factory):
    editor = editor_factory()
    editor.screen_capture = DelayedFakeCapture(delay_s=0.3)
    shots = make_three_steps(editor)

    editor.jump_to_step(1)
    editor.start_insert_capture()
    assert editor._insert_after_index == 1
    flush_events(100)  # 后台截图在途

    # 导航切换到第 1 步（index 0）
    editor.go_previous()
    assert editor.current_step == 0
    wait_inflight_settled(editor)

    # capture_step(1) != current_step(0) → 结果丢弃、锚点复位、模型与磁盘不变
    assert [s["intent"] for s in editor.steps_data] == ["S1", "S2", "S3"]
    assert [s["screenshot"] for s in editor.steps_data] == shots
    assert_transient(editor)
    assert_all(editor)
    assert gui_pngs(editor) == sorted(shots)


# ===== SubTask 5.6：插入截图失败后锚点复位，普通截图走追加分支 =====

def test_insert_capture_failure_resets_anchor(editor_factory):
    editor = editor_factory()
    shots = make_three_steps(editor)

    editor.jump_to_step(0)
    editor.screen_capture.fail_next()
    insert_capture_and_wait(editor)

    # 失败路径：锚点复位、锁释放、模型与磁盘保持原样
    assert editor._insert_after_index is None
    assert editor._screenshot_in_progress is False
    assert [s["screenshot"] for s in editor.steps_data] == shots
    assert_transient(editor)
    assert_all(editor)

    # 确认当前（第 1 步）表单：2.8（B22）后只前进一格，不再传送到末尾
    editor.confirm_step()
    flush_events(50)
    assert editor.current_step == 1
    assert len(editor.steps_data) == 3

    # 走到末尾待截图空位后，普通截图走追加分支，不误入插入分支
    limit = len(editor.steps_data) + 2
    while editor.current_step < len(editor.steps_data) and limit > 0:
        editor.go_next()
        flush_events()
        limit -= 1
    assert editor.current_step == len(editor.steps_data) == 3

    capture_and_wait(editor)
    fill_valid_step(editor, intent="S4")
    editor.confirm_step()
    flush_events(50)
    assert [s["intent"] for s in editor.steps_data] == ["S1", "S2", "S3", "S4"]
    assert [s["screenshot"] for s in editor.steps_data[:3]] == shots
    assert_all(editor)


# ===== SubTask 5.7：scroll/swipe 测量中点插入 =====

@pytest.mark.parametrize("measure", ["swipe", "scroll"])
def test_insert_during_measurement_safely_degrades(editor_factory, measure):
    editor = editor_factory()
    make_three_steps(editor)

    editor.jump_to_step(0)
    # 先置测量态（jump_to_step 已把第 1 步 vertices/坐标回填表单）
    if measure == "swipe":
        editor._start_swipe_measurement()
        assert editor._swipe_measuring is True
    else:
        editor._start_scroll_measurement()
        assert editor._scroll_measuring is True

    # 测量中点插入：未被拦截，插入链走完后测量态被插入分支安全复位
    insert_capture_and_wait(editor)
    assert len(editor.steps_data) == 4
    assert editor.current_step == 1

    fill_valid_step(editor, intent="S-new")
    editor.confirm_step()
    flush_events(50)

    # 无半插入残留：业务顺序完整，INV-9 测量态复位
    assert [s["intent"] for s in editor.steps_data] == ["S1", "S-new", "S2", "S3"]
    assert_all(editor)


# ===== SubTask 5.8：插入后草稿落盘 → 续采恢复 → 再次插入/删除 =====

def test_insert_then_resume_from_draft_and_mutate_again(editor_factory):
    editor = editor_factory()
    make_three_steps(editor)

    editor.jump_to_step(0)
    insert_capture_and_wait(editor)
    fill_valid_step(editor, intent="S-new")
    editor.confirm_step()
    flush_events(50)
    assert [s["intent"] for s in editor.steps_data] == ["S1", "S-new", "S2", "S3"]
    assert_all(editor)

    # 草稿落盘 → 新编辑器 load_from_draft 恢复（INV-10）
    resumed, need_instruction = assert_resume_consistent(editor, editor_factory)
    assert need_instruction is False
    assert [s["intent"] for s in resumed.steps_data] == ["S1", "S-new", "S2", "S3"]

    # 恢复后再次插入（在 S-new 后）
    resumed.jump_to_step(1)
    insert_capture_and_wait(resumed)
    fill_valid_step(resumed, intent="S-new2")
    resumed.confirm_step()
    flush_events(50)
    assert [s["intent"] for s in resumed.steps_data] == \
        ["S1", "S-new", "S-new2", "S2", "S3"]
    assert_all(resumed)

    # 恢复后再删除新插入步
    resumed.jump_to_step(2)
    resumed.delete_current_step()
    flush_events(50)
    assert [s["intent"] for s in resumed.steps_data] == ["S1", "S-new", "S2", "S3"]
    assert_all(resumed)
