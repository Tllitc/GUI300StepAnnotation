# -*- coding: utf-8 -*-
"""Task 7 草稿/多轮/续采交叉测试组（SubTask 7.1~7.5）

覆盖：
- 7.1 删除/插入/撤销后立即 _write_draft_now（不等防抖），草稿与内存逐条一致
- 7.2 answer 收尾一轮后在新一轮变更：历史轮截图不被误删、最终 JSON 归属正确
- 7.3 轮次边界态（_current_round_saved=True 且 steps_data 为空）下 undo/delete 行为定性
- 7.4 高频交替变更序列，每轮后五者一致，结束后最终 JSON 正确
- 7.5 续采完整链路：草稿恢复后继续变更并正常结束，INV-1~10 全绿

说明：
- 新轮指令框由 conftest 的 FakeInputDialog 自动应答（modal 夹具注入，含 x()/y()），
  本组用例通过 modal.input_text / modal.input_ok 定制应答。
- DA-2（undo_step 不清理侧栏缩略图缓存）已修复：undo 后 assert_all（含侧栏
  缩略图缓存校验）可全绿；test_7_x_undo_cleans_sidebar_thumb_cache 固化为回归用例。
"""
import copy
import os

from PyQt5.QtTest import QTest

from helpers import (capture_and_wait, confirm_n_steps, drain_sidebar_thumbs,
                     fill_valid_step, finish_task, flush_events)
from invariants import (assert_all, assert_draft, assert_files,
                        assert_final_json, assert_model,
                        assert_resume_consistent, assert_transient)


def _insert_step_after_current(editor, **fill_kwargs):
    """在当前步后插入并确认一个新步（驱动 start_insert_capture 全链路）"""
    prev_seq = editor._screenshot_seq
    editor.start_insert_capture()
    assert editor._screenshot_seq > prev_seq, "插入截图未发起（前置校验未通过）"
    waited = 0
    while editor._screenshot_in_progress and waited < 10000:
        QTest.qWait(30)
        waited += 30
    flush_events()
    assert editor._screenshot_in_progress is False, "插入截图未在 10s 内完成"
    fill_valid_step(editor, **fill_kwargs)
    editor.confirm_step()
    flush_events(50)


def _goto_fresh_slot(editor):
    """通过 go_next 把 current_step 推进到 len(steps_data) 的新步空位"""
    limit = len(editor.steps_data) + 2
    while editor.current_step < len(editor.steps_data) and limit > 0:
        editor.go_next()
        flush_events()
        limit -= 1
    assert editor.current_step == len(editor.steps_data), \
        f"未能到达新步空位: current={editor.current_step} len={len(editor.steps_data)}"


def _assert_scene_consistency(editor):
    """模型/文件/瞬态/草稿一致性（聚焦本子任务目标的子集；侧栏由 assert_all 用例覆盖）"""
    assert_transient(editor)
    assert_model(editor)
    assert_files(editor)
    assert_draft(editor)


def _gui_pngs(editor):
    return sorted(name for name in os.listdir(editor.gui_dir)
                  if name.endswith(".png"))


def _round_screenshot_refs(rounds):
    refs = []
    for rnd in rounds:
        for t in rnd.get("trajectory") or []:
            fn = (t.get("observation") or {}).get("screenshot")
            if fn:
                refs.append(fn)
    return refs


def test_7_1_mutation_then_write_draft_immediately(editor_factory, modal):
    """SubTask 7.1：删除/插入/撤销后立即 _write_draft_now，草稿与内存一致"""
    editor = editor_factory()
    confirm_n_steps(editor, 3)

    # --- 删除中间步后立即写草稿 ---
    editor.jump_to_step(1)
    flush_events()
    editor.delete_current_step()   # 确认框由 modal 默认应答 Yes
    flush_events()
    assert len(editor.steps_data) == 2
    draft = assert_draft(editor)
    assert draft["current_step_index"] == editor.current_step
    assert_all(editor)

    # --- 插入新步后立即写草稿 ---
    editor.jump_to_step(0)
    flush_events()
    _insert_step_after_current(editor, intent="7.1-插入步")
    assert len(editor.steps_data) == 3
    draft = assert_draft(editor)
    assert draft["current_step_index"] == editor.current_step
    assert_all(editor)

    # --- 撤销末步后立即写草稿（侧栏缓存一致性由 test_7_x 回归用例覆盖） ---
    editor.undo_step()
    flush_events()
    assert len(editor.steps_data) == 2
    draft = assert_draft(editor)
    assert draft["current_step_index"] == editor.current_step
    _assert_scene_consistency(editor)


def test_7_2_answer_round_then_mutate_new_round(editor_factory, modal):
    """SubTask 7.2：answer 收尾一轮 → 新一轮删除/插入/撤销 → 历史轮截图不丢、归属正确"""
    modal.input_text = "第二轮指令"   # _start_new_round 的 QInputDialog 应答
    editor = editor_factory()

    # 第一轮：2 个 click + 1 个 answer 收尾（触发轮次保存 + 300ms 后新轮输入框）
    confirm_n_steps(editor, 2)
    capture_and_wait(editor)
    fill_valid_step(editor, action="answer", text="第一轮回答")
    editor.confirm_step()
    assert editor._current_round_saved is True
    flush_events(400)   # 让 300ms singleShot 触发 _start_new_round（modal 自动应答新指令）

    assert len(editor.rounds) == 1
    assert editor._current_round_saved is False
    assert editor.steps_data == []
    assert editor.task_instruction == "第二轮指令"
    round1_refs = _round_screenshot_refs(editor.rounds)
    assert len(round1_refs) == 3

    # 新一轮走 2 步
    confirm_n_steps(editor, 2)
    round2_shots = [s["screenshot"] for s in editor.steps_data]
    # 序号最小复用不得复用存活的历史轮文件
    assert not (set(round2_shots) & set(round1_refs))

    # 新一轮做删除/插入/撤销
    editor.jump_to_step(0)
    flush_events()
    editor.delete_current_step()
    flush_events()
    assert len(editor.steps_data) == 1
    _insert_step_after_current(editor, intent="第二轮-插入步")
    assert len(editor.steps_data) == 2
    editor.undo_step()
    flush_events()
    assert len(editor.steps_data) == 1

    # 历史 rounds 引用的截图文件不被删除（删除/撤销引用检查仅扫 steps_data 的交叉验证）
    for fn in round1_refs:
        assert os.path.isfile(os.path.join(editor.gui_dir, fn)), \
            f"历史轮截图被误删: {fn}"
    assert len(editor.rounds) == 1
    assert len(editor.rounds[0]["trajectory"]) == 3
    _assert_scene_consistency(editor)

    # 结束任务：最终 JSON 各 round/step 归属正确
    finish_task(editor, modal, answer_text="第二轮回答")
    data = assert_final_json(editor.gui_dir, editor.gui_number)
    assert len(data["messages"]) == 4, "应为两轮"
    r1 = data["messages"][1]["trajectory"]
    r2 = data["messages"][3]["trajectory"]
    assert len(r1) == 3
    assert len(r2) == 2
    assert [s["observation"]["screenshot"] for s in r1] == round1_refs
    assert r1[-1]["actions"][0]["action"] == "answer"
    # 第二轮两步归属：幸存步 + answer_terminate，且不与第一轮串图
    assert r2[0]["observation"]["screenshot"] == round2_shots[1]
    assert r2[-1]["actions"][0]["action"] == "answer"
    assert not ({s["observation"]["screenshot"] for s in r2} & set(round1_refs))


def test_7_3_round_boundary_state_undo_delete(editor_factory, modal):
    """SubTask 7.3：轮次边界态（_current_round_saved=True 且 steps_data 为空）

    undo_step 在 steps_data 为空时应直接返回无副作用；
    delete_current_step 无当前步应提示后返回；两者均不得触碰历史轮数据。
    """
    modal.input_ok = False   # answer 后取消新轮指令输入 → 走 from_answer 取消分支
    editor = editor_factory()

    # 构造：第一轮 2 个 click + answer 收尾 → 取消新轮 → steps_data 空、rounds 非空
    confirm_n_steps(editor, 2)
    capture_and_wait(editor)
    fill_valid_step(editor, action="answer", text="边界回答")
    editor.confirm_step()
    flush_events(400)   # _start_new_round(from_answer=True) 取消分支：工作区清空
    assert editor.steps_data == [] and len(editor.rounds) == 1
    assert editor._current_round_saved is False   # 取消分支已复位

    # 写草稿：steps_data 为空 + rounds 非空 → 草稿 steps_data 应为空
    editor._write_draft_now()
    flush_events()
    draft = editor.data_manager.load_draft(editor.gui_number)
    assert draft is not None
    assert draft["steps_data"] == []
    assert len(draft["rounds"]) == 1

    # 新编辑器续采：恢复到轮次边界态（_current_round_saved=True 且 steps_data 为空）
    resumed = editor_factory(auto_init=False)
    need_instruction = resumed.load_from_draft(draft)
    flush_events(100)
    assert need_instruction is True, "空当前轮 + 非空历史轮应要求追问新指令"
    assert resumed._current_round_saved is True
    assert resumed.steps_data == [] and len(resumed.rounds) == 1

    files_before = _gui_pngs(resumed)
    rounds_snapshot = copy.deepcopy(resumed.rounds)

    # 边界态 undo：steps_data 为空 → 直接返回，无副作用
    resumed.undo_step()
    flush_events()
    assert "没有可撤销" in resumed.status_label.text()

    # 边界态 delete：无当前步 → 提示后返回
    resumed.delete_current_step()
    flush_events()
    assert any("没有可删除" in text for _, text in modal.infos)

    # 定性结论：历史轮数据与磁盘文件零副作用、边界态保持
    assert resumed.steps_data == []
    assert resumed.rounds == rounds_snapshot
    assert _gui_pngs(resumed) == files_before
    assert resumed._current_round_saved is True
    assert_all(resumed)


def test_7_4_high_frequency_mutation_loop(editor_factory, modal):
    """SubTask 7.4：高频交替变更序列，每轮后 assert_all，结束后 assert_final_json

    DA-2 修复后：undo 清理侧栏缩略图缓存，每轮 assert_all（含 INV-8）全绿。
    """
    editor = editor_factory()
    confirm_n_steps(editor, 3)
    assert_all(editor)

    for i in range(6):
        # 截图 → 填步 → confirm（新步空位追加）
        capture_and_wait(editor)
        fill_valid_step(editor, intent=f"循环{i}-追加")
        editor.confirm_step()
        flush_events(50)
        # jump 中间步 → 删除
        mid = len(editor.steps_data) // 2
        editor.jump_to_step(mid)
        flush_events()
        editor.delete_current_step()
        flush_events()
        # 在当前步后插入 → 确认
        _insert_step_after_current(editor, intent=f"循环{i}-插入")
        # 确保被撤销步骤缩略图已入缓存（缺陷复现确定性）
        drain_sidebar_thumbs(editor)
        # 撤销（弹末步）
        editor.undo_step()
        flush_events()
        # 导航：跳首步后逐步 go_next 回到新步空位
        editor.jump_to_step(0)
        flush_events()
        _goto_fresh_slot(editor)
        # 每轮后五者收敛一致
        assert_all(editor)
        assert len(editor.steps_data) == 3

    # 结束后 finish_task：最终 JSON 正确
    finish_task(editor, modal, answer_text="循环结束")
    data = assert_final_json(editor.gui_dir, editor.gui_number)
    traj = data["messages"][1]["trajectory"]
    assert len(traj) == 4
    assert traj[-1]["actions"][0]["action"] == "answer"


def test_7_5_resume_full_chain(editor_factory, modal):
    """SubTask 7.5：走步+删除+插入+撤销 → 草稿 → 新编辑器续采 → 继续变更 → 结束

    第一台编辑器 undo 后聚焦草稿/文件/模型一致性（侧栏缓存回归由 test_7_x 覆盖）；
    续采编辑器侧栏为全新实例，可做全量 assert_all。
    """
    editor = editor_factory()

    # 走 3 步（含 1 次删除 + 1 次插入 + 1 次撤销）
    confirm_n_steps(editor, 3)                       # [s0, s1, s2]
    editor.jump_to_step(1)
    flush_events()
    editor.delete_current_step()                     # [s0, s2]
    flush_events()
    assert len(editor.steps_data) == 2
    _insert_step_after_current(editor, intent="续采前插入")   # [s0, s2, ins]
    assert len(editor.steps_data) == 3
    editor.undo_step()                               # 弹末步 → [s0, s2]
    flush_events()
    assert len(editor.steps_data) == 2
    capture_and_wait(editor)                         # 再补 1 步 → [s0, s2, n3]
    fill_valid_step(editor, intent="续采前第三步")
    editor.confirm_step()
    flush_events(50)
    assert len(editor.steps_data) == 3
    _assert_scene_consistency(editor)

    # 写草稿 → 新编辑器 load_from_draft（同 tmp_path 新 DataManager + 同 modal 应答）
    resumed, need_instruction = assert_resume_consistent(editor, editor_factory)
    assert need_instruction is False
    assert resumed is not editor
    assert resumed.data_manager is not editor.data_manager
    assert resumed.data_manager.base_dir == editor.data_manager.base_dir
    assert len(resumed.steps_data) == 3

    # 续采后继续走 2 步（先推进到新步空位，避免覆盖末步）
    _goto_fresh_slot(resumed)
    confirm_n_steps(resumed, 2)
    assert len(resumed.steps_data) == 5
    # 再做 1 次删除
    resumed.jump_to_step(1)
    flush_events()
    resumed.delete_current_step()
    flush_events()
    assert len(resumed.steps_data) == 4
    assert_all(resumed)

    # 结束任务：INV-1~10 全绿，最终 JSON/coords 引用连续无缺失
    _goto_fresh_slot(resumed)
    finish_task(resumed, modal, answer_text="续采完成")
    data = assert_final_json(resumed.gui_dir, resumed.gui_number)
    assert len(data["messages"]) == 2, "单轮任务"
    traj = data["messages"][1]["trajectory"]
    assert len(traj) == 5
    assert traj[-1]["actions"][0]["action"] == "answer"
    shots = [s["observation"]["screenshot"] for s in traj]
    assert len(shots) == len(set(shots)), "最终 JSON 截图引用不得重复"
    for fn in shots:
        assert os.path.isfile(os.path.join(resumed.gui_dir, fn))


def test_7_x_undo_cleans_sidebar_thumb_cache(editor_factory, modal):
    """DA-2 回归：undo_step 应清理被撤销步骤的侧栏缩略图缓存

    走 2 步并排空缩略图懒加载 → undo 末步（文件被删）→
    侧栏缓存无该文件名条目；重新截图复用同一序号后缩略图与新文件一致。
    """
    editor = editor_factory()
    confirm_n_steps(editor, 2)
    drain_sidebar_thumbs(editor)   # 确保末步缩略图已入缓存
    last_fn = editor.steps_data[-1]["screenshot"]

    editor.undo_step()
    flush_events()

    stale = [k for k in editor.sidebar._thumb_cache if k and k[0] == last_fn]
    assert not stale, f"undo 后缩略图缓存残留已删文件: {last_fn}"

    # 序号复用重截：缩略图必须是新图而非缓存旧图
    capture_and_wait(editor)
    assert editor._current_screenshot_filename == last_fn, "最小可用序号应复用空洞"
    fill_valid_step(editor, intent="撤销后重截")
    editor.confirm_step()
    flush_events(50)
    drain_sidebar_thumbs(editor)
    # 重截确认后的新步在 index 1（弹末步后追加回原位）
    item = editor.sidebar.item_widgets[1]
    expected = editor.build_marked_preview(last_fn, editor.steps_data[1].get("vertices"),
                                           item.THUMB_SIZE)
    assert item.thumb_label.pixmap().toImage() == expected.toImage(), \
        "序号复用后缩略图显示旧图（DA-2 回归）"
