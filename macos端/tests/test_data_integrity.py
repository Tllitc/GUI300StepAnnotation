# -*- coding: utf-8 -*-
"""采标四操作（撤销 / 删除当前步骤 / 在此步骤后插入截图 / 重新截图）数据一致性测试。

关注点：这四个轮内操作是否导致
    JSON 错乱 / 截图错乱 / 命名错乱 / JSON 引用截图错乱 / 顺序错乱。

设计契约（DESIGN-D，非 bug）：
    插入 / 删除只「重编号、不重命名文件」。新截图取磁盘 max+1，
    因此中间插入步的文件序号会「大于」其后步骤——文件名顺序与步骤号顺序
    不一致是预期且正确的。本模块显式锁定该契约：文件名顺序允许与步骤号
    不一致，但每步引用精确、跨轮全局唯一、磁盘无孤儿。
"""

import os

from PyQt5.QtGui import QPixmap
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QMessageBox

import helpers as H
import invariants as I


# ---------------------------------------------------------------------------
# 本模块私有小工具
# ---------------------------------------------------------------------------
def _gui_dir(editor):
    return os.path.join(editor.data_manager.current_dir, f"gui_{editor.gui_number}")


def _disk_files(editor):
    return set(I._strict_named_pngs(editor))


def _shot_numbers(names):
    """gui_XXXXXX_####.png → 末 4 位序号集合"""
    return {int(n[-8:-4]) for n in names}


def _trajectory(final_json):
    return final_json["messages"][1]["trajectory"]


def _trajectories(final_json):
    """按轮顺序取各 assistant 消息的 trajectory 列表（INV-14 需覆盖多轮）。"""
    return [m["trajectory"] for m in final_json["messages"]
            if m["role"] == "assistant"]


def _fill_and_confirm(editor, index, intent):
    """把（通常是插入产生的）未确认步填全并确认，满足 terminate 全量校验。"""
    H.fill_step(editor, index, action_chinese="左键单击", intent=intent,
                coord_text="250,400")
    H.confirm(editor)


# ===========================================================================
# 插入截图
# ===========================================================================
class TestInsertIntegrity:
    def test_insert_middle_then_finish_json_order(self, editor):
        """中间插入 → 最终 trajectory 顺序 = [原0, 新, 原1, 原2]，引用精确。"""
        H.walk_steps(editor, 3)  # intents: 测试第 1/2/3 步，files: 0001/0002/0003
        insert_idx = H.insert_step_after(editor, 0)
        assert insert_idx == 1, f"插入步应位于下标 1，实际 {insert_idx}"
        assert len(editor.steps) == 4
        _fill_and_confirm(editor, insert_idx, "插入步")

        # 结束前捕获内存态：finish 的 terminate 分支会 save_current_round → steps=[]
        # 并销毁控件，故 assert_model/files 与 steps 引用必须在 finish 之前完成
        mem_names = [s["screenshot_filename"] for s in editor.steps]
        I.assert_model(editor)
        I.assert_files(editor)
        # INV-11：中间插入天然破坏序号单调（新图取磁盘 max+1 却插到中间），
        # 只守住「全局唯一 + 命名合规 + 引用存在」。
        I.assert_screenshot_order(editor, strict_monotonic=False)

        json_path = H.finish(editor, action="terminate")
        assert json_path, "最终 JSON 产出失败"

        final = H.read_final_json(editor)
        traj = _trajectory(final)
        intents = [e.get("intent") for e in traj]
        assert len(traj) == 4
        assert intents[:3] == ["测试第 1 步", "插入步", "测试第 2 步"], intents
        # H.finish 把末步转为 terminate，意图固定为「任务已完成」
        assert traj[3]["actions"][0]["action"] == "terminate"
        assert traj[3].get("intent") == "任务已完成", intents

        # 引用精确：trajectory[i].observation.screenshot 精确指向结束前内存第 i 步的文件
        for i, entry in enumerate(traj):
            assert entry["observation"]["screenshot"] == mem_names[i]

        # DESIGN-D：文件名顺序允许与步骤号不一致，但引用必须精确
        file_nums = [n[-8:-4] for n in mem_names]
        assert file_nums == ["0001", "0004", "0002", "0003"], file_nums

        coords = H.read_final_coords(editor)
        I.assert_coords_aligned(editor, final, coords)
        # INV-14：每条 coords 框中心须等于同步的交付 coordinate（冒领不复现）
        I.assert_coords_center_match(coords, _trajectories(final))
        I.assert_final_json(editor, expected_rounds=1)

    def test_insert_after_last_boundary(self, editor):
        """末尾之后插入：新步位于末下标、文件名 = 磁盘 max+1。"""
        H.walk_steps(editor, 3)  # files 0001/0002/0003
        before = _disk_files(editor)
        insert_idx = H.insert_step_after(editor, 2)
        assert insert_idx == 3
        assert len(editor.steps) == 4

        new_name = editor.steps[3]["screenshot_filename"]
        assert new_name == f"gui_{editor.gui_number}_0004.png", new_name
        # 新文件确为磁盘 max+1
        assert _shot_numbers(_disk_files(editor) - before) == {4}

        I.assert_model(editor)
        I.assert_stack(editor)
        I.assert_files(editor)
        I.assert_sidebar(editor)
        I.assert_naming(editor)
        # INV-11：末尾插入保持序号单调、无空洞，可走严格口径
        I.assert_screenshot_order(editor)

    def test_insert_then_delete_inserted(self, editor):
        """插入后再删除该插入步：回到 3 步、插入文件删净、原文件完好。"""
        H.walk_steps(editor, 3)
        orig_files = set(s["screenshot_filename"] for s in editor.steps)
        insert_idx = H.insert_step_after(editor, 0)  # 新步下标 1，file 0004
        assert len(editor.steps) == 4
        inserted_file = editor.steps[insert_idx]["screenshot_filename"]
        assert inserted_file not in orig_files

        editor.display_step(insert_idx)
        H.delete_current(editor, confirm=True)
        assert len(editor.steps) == 3

        disk = set(os.listdir(_gui_dir(editor)))
        assert inserted_file not in disk, f"插入文件未删净：{inserted_file}"
        for f in orig_files:
            assert f in disk, f"原文件被误删：{f}"

        I.assert_model(editor)
        I.assert_files(editor)

        json_path = H.finish(editor, action="terminate")
        assert json_path
        traj = _trajectory(H.read_final_json(editor))
        assert len(traj) == 3
        assert [e.get("intent") for e in traj] == ["测试第 1 步", "测试第 2 步", "任务已完成"]
        I.assert_final_json(editor, expected_rounds=1)

    def test_insert_cancel_no_side_effect(self, editor):
        """插入截图取消：无新步、无新文件、插入锚点复位、瞬态收敛。"""
        H.walk_steps(editor, 2)
        before_files = _disk_files(editor)

        Fake = H.get_fake_cls(editor)
        H._reset_fake(editor)
        Fake.prepare_cancelled()

        editor.display_step(0)
        QTest.qWait(50)
        editor.start_insert_capture()
        H._wait_until(lambda: not editor._capture_in_flight, message="insert cancel")
        QTest.qWait(100)

        assert len(editor.steps) == 2, "取消插入不应增加步骤"
        assert editor._capture_insert_after is None, "取消后插入锚点应复位"
        assert _disk_files(editor) == before_files, "取消插入不应产生新截图文件"
        I.assert_transient_reset(editor)


# ===========================================================================
# 删除当前步骤
# ===========================================================================
class TestDeleteIntegrity:
    def test_delete_first_step(self, editor):
        H.walk_steps(editor, 4)
        first_file = editor.steps[0]["screenshot_filename"]
        editor.display_step(0)
        H.delete_current(editor, confirm=True)
        assert len(editor.steps) == 3
        assert first_file not in set(os.listdir(_gui_dir(editor)))

        I.assert_model(editor)
        I.assert_files(editor)

        json_path = H.finish(editor, action="terminate")
        assert json_path
        traj = _trajectory(H.read_final_json(editor))
        assert [e.get("intent") for e in traj] == ["测试第 2 步", "测试第 3 步", "任务已完成"]
        I.assert_final_json(editor, expected_rounds=1)

    def test_delete_last_step(self, editor):
        H.walk_steps(editor, 4)
        last_file = editor.steps[3]["screenshot_filename"]
        editor.display_step(3)
        H.delete_current(editor, confirm=True)
        assert len(editor.steps) == 3
        assert last_file not in set(os.listdir(_gui_dir(editor)))

        I.assert_model(editor)
        I.assert_files(editor)

        json_path = H.finish(editor, action="terminate")
        assert json_path
        traj = _trajectory(H.read_final_json(editor))
        assert len(traj) == 3
        assert [e.get("intent") for e in traj] == ["测试第 1 步", "测试第 2 步", "任务已完成"]
        I.assert_final_json(editor, expected_rounds=1)

    def test_delete_middle_then_finish_coords(self, editor):
        """中间删除 → 序号 0..3 连续、coords 与轨迹序号/动作对齐。"""
        H.walk_steps(editor, 5)  # 测试第 1..5 步
        deleted_file = editor.steps[2]["screenshot_filename"]
        editor.display_step(2)
        H.delete_current(editor, confirm=True)
        assert len(editor.steps) == 4
        assert deleted_file not in set(os.listdir(_gui_dir(editor)))
        # INV-11：中间删除留空洞属预期，allow_holes 默认放开；序号仍单调
        I.assert_screenshot_order(editor)

        # finish 前捕获内存态（terminate 分支会清空 steps）
        mem_names = [s["screenshot_filename"] for s in editor.steps]

        json_path = H.finish(editor, action="terminate")
        assert json_path
        final = H.read_final_json(editor)
        traj = _trajectory(final)
        # 序号连续
        for i, entry in enumerate(traj):
            assert entry.get("step") == i, f"trajectory[{i}].step={entry.get('step')}"
        assert [e.get("intent") for e in traj] == [
            "测试第 1 步", "测试第 2 步", "测试第 4 步", "任务已完成",
        ]
        # 引用精确
        for i, entry in enumerate(traj):
            assert entry["observation"]["screenshot"] == mem_names[i]

        coords = H.read_final_coords(editor)
        I.assert_coords_aligned(editor, final, coords)
        # INV-14：删除后 coords 与轨迹重编号，框中心仍须逐步对齐
        I.assert_coords_center_match(coords, _trajectories(final))
        I.assert_final_json(editor, expected_rounds=1)

    def test_delete_then_insert(self, editor):
        """删除后再插入 → 全不变式 + JSON 正确。"""
        H.walk_steps(editor, 3)  # 测试第 1/2/3 步
        editor.display_step(1)
        H.delete_current(editor, confirm=True)  # 删 测试第2步 → [T1, T3]
        assert len(editor.steps) == 2

        insert_idx = H.insert_step_after(editor, 0)  # 插入到下标 1 → [T1, IN, T3]
        assert insert_idx == 1
        _fill_and_confirm(editor, insert_idx, "插入步")

        # 全不变式必须在 finish 前校验（terminate 分支会清空 steps 并销毁控件）
        I.assert_model(editor)
        I.assert_stack(editor)
        I.assert_files(editor)
        I.assert_sidebar(editor)

        json_path = H.finish(editor, action="terminate")
        assert json_path
        traj = _trajectory(H.read_final_json(editor))
        assert [e.get("intent") for e in traj] == ["测试第 1 步", "插入步", "任务已完成"]

        I.assert_final_json(editor, expected_rounds=1)


# ===========================================================================
# 重新截图
# ===========================================================================
class TestRecaptureIntegrity:
    def test_recapture_inserted_middle_step(self, editor):
        """对插入的中间步重截图：文件名复用、文件数不变、rect/selection 更新；
        并断言缩略图缓存无「旧 rect 死键」残留（验证 DEFECT-B 修复）。"""
        H.walk_steps(editor, 3)
        insert_idx = H.insert_step_after(editor, 0)
        _fill_and_confirm(editor, insert_idx, "插入步")

        filename = editor.steps[insert_idx]["screenshot_filename"]
        before_files = _disk_files(editor)

        # 先按当前 key 塞入一条缩略图缓存（模拟重截图前该步已缓存）
        sidebar = editor.sidebar
        key_before = sidebar._cache_key(editor.steps[insert_idx])
        sidebar._thumb_cache[key_before] = QPixmap()

        new_rect = (50, 60, 200, 150)
        H.recapture(editor, insert_idx, rect=new_rect)

        # 文件名复用、文件数不变
        assert editor.steps[insert_idx]["screenshot_filename"] == filename
        assert _disk_files(editor) == before_files
        # rect / selection 更新
        assert tuple(editor.steps[insert_idx]["rect_info"]) == new_rect
        assert editor.steps[insert_idx]["selection_type"] == "click"

        # DEFECT-B：旧 rect 死键必须已被清除（remove_thumb_cache_by_filename 按文件名清全部 key）
        assert key_before not in sidebar._thumb_cache, f"DEFECT-B: 旧 rect 死缓存残留 {key_before}"
        stale = [k for k in sidebar._thumb_cache
                 if k[0] == filename and tuple(k[1] or ()) != new_rect]
        assert not stale, f"DEFECT-B: 存在陈旧 rect 缓存键 {stale}"

    def test_recapture_cancel_keeps_step(self, editor):
        """重截图取消：该步 filename/rect/selection 全不变、窗口恢复、瞬态收敛。"""
        H.walk_steps(editor, 2)
        idx = 0
        snap_name = editor.steps[idx]["screenshot_filename"]
        snap_rect = editor.steps[idx]["rect_info"]
        snap_type = editor.steps[idx]["selection_type"]

        Fake = H.get_fake_cls(editor)
        H._reset_fake(editor)
        Fake.prepare_cancelled()

        editor.display_step(idx)
        QTest.qWait(50)
        editor.recapture_current_step()
        H._wait_until(lambda: not editor._capture_in_flight, message="recapture cancel")
        QTest.qWait(100)

        assert editor.steps[idx]["screenshot_filename"] == snap_name
        assert editor.steps[idx]["rect_info"] == snap_rect
        assert editor.steps[idx]["selection_type"] == snap_type
        assert editor._recapture_target_index is None, "HARDENING-C: 取消后目标下标应复位"
        I.assert_transient_reset(editor)

    def test_recapture_single_to_drag_middle(self, editor):
        """中间步单框 → 双框重截图：selection_type=drag、动作下拉=拖拽、文件名复用。"""
        H.walk_steps(editor, 3)
        idx = 1
        filename = editor.steps[idx]["screenshot_filename"]

        H.recapture_drag(editor, idx)

        assert editor.steps[idx]["selection_type"] == "drag"
        assert editor.steps[idx]["editor"].action_type_combo.currentText() == "拖拽"
        assert editor.steps[idx]["screenshot_filename"] == filename, "重截图必须复用文件名"
        assert len(_disk_files(editor)) == 3, "重截图不应产生新文件"


# ===========================================================================
# 撤销
# ===========================================================================
class TestUndoIntegrity:
    def test_undo_after_insert(self, editor):
        """插入后跳到末步撤销：末步移除、其文件删除、剩 3 步、引用连续。"""
        H.walk_steps(editor, 3)
        insert_idx = H.insert_step_after(editor, 0)  # [T1, IN, T2, T3]，共 4 步
        assert len(editor.steps) == 4
        last_file = editor.steps[3]["screenshot_filename"]

        editor.display_step(3)
        H.undo(editor, confirm=True)
        assert len(editor.steps) == 3
        assert last_file not in set(os.listdir(_gui_dir(editor)))

        I.assert_model(editor)
        I.assert_files(editor)

    def test_undo_then_finish(self, editor):
        """撤销后再结束：最终 JSON 少一步且顺序正确。"""
        H.walk_steps(editor, 4)  # 测试第 1..4 步
        editor.display_step(3)
        H.undo(editor, confirm=True)  # 撤掉末步（测试第 4 步）
        assert len(editor.steps) == 3

        json_path = H.finish(editor, action="terminate")
        assert json_path
        traj = _trajectory(H.read_final_json(editor))
        assert [e.get("intent") for e in traj] == ["测试第 1 步", "测试第 2 步", "任务已完成"]
        I.assert_final_json(editor, expected_rounds=1)


# ===========================================================================
# 组合序列 + 崩溃续采
# ===========================================================================
class TestCombinedSequence:
    def test_interleaved_ops_then_finish(self, editor):
        """交错执行四种操作后结束：全不变式 + 轨迹顺序 + coords 对齐 + 文件名全局唯一 + 无孤儿。"""
        H.walk_steps(editor, 5)  # 测试第 1..5 步，files 0001..0005

        # 1) 在下标 1 之后插入
        ins = H.insert_step_after(editor, 1)
        assert ins == 2
        _fill_and_confirm(editor, ins, "插入步")

        # 2) 重截图首步（换 rect）
        H.recapture(editor, 0, rect=(10, 20, 30, 40))

        # 3) 删除下标 3（原 测试第3步）
        editor.display_step(3)
        H.delete_current(editor, confirm=True)
        assert len(editor.steps) == 5

        # 4) 跳末步撤销
        editor.display_step(len(editor.steps) - 1)
        H.undo(editor, confirm=True)
        assert len(editor.steps) == 4

        # 全不变式 + 内存态必须在 finish 前校验/捕获（terminate 分支清空 steps、销毁控件）
        mem_names = [s["screenshot_filename"] for s in editor.steps]
        I.assert_model(editor)
        I.assert_stack(editor)
        I.assert_files(editor)
        I.assert_sidebar(editor)
        I.assert_naming(editor)
        # INV-11：交错含中间插入，破坏单调，仅守唯一 + 合规 + 引用存在
        I.assert_screenshot_order(editor, strict_monotonic=False)

        # 结束后校验
        json_path = H.finish(editor, action="terminate")
        assert json_path
        final = H.read_final_json(editor)
        traj = _trajectory(final)
        assert [e.get("intent") for e in traj] == [
            "测试第 1 步", "测试第 2 步", "插入步", "任务已完成",
        ]
        for i, entry in enumerate(traj):
            assert entry["observation"]["screenshot"] == mem_names[i]

        # 文件名全局唯一（单轮内不重复）
        names = [e["observation"]["screenshot"] for e in traj]
        assert len(names) == len(set(names))

        coords = H.read_final_coords(editor)
        I.assert_coords_aligned(editor, final, coords)
        # INV-14：交错操作后中心-坐标一致性仍须逐步成立
        I.assert_coords_center_match(coords, _trajectories(final))
        I.assert_final_json(editor, expected_rounds=1)

    def test_ops_then_crash_resume(self, editor):
        """插入 + 删除后 flush draft，再 load_from_draft 续采 → 保序，最终 JSON 与内存顺序一致。"""
        H.walk_steps(editor, 3)  # T1,T2,T3
        ins = H.insert_step_after(editor, 0)  # [T1, IN, T2, T3]，IN 下标 1
        _fill_and_confirm(editor, ins, "插入步")

        editor.display_step(2)  # 删 T2
        H.delete_current(editor, confirm=True)
        assert len(editor.steps) == 3  # [T1, IN, T3]

        mem_order = [s["screenshot_filename"] for s in editor.steps]
        mem_intents = [s["editor"].intent_input.text() for s in editor.steps]

        H.flush_draft(editor)
        draft = H.read_draft(editor)
        editor.load_from_draft(draft)
        assert len(editor.steps) == 3
        assert [s["screenshot_filename"] for s in editor.steps] == mem_order, "续采后顺序应保序"

        json_path = H.finish(editor, action="terminate")
        assert json_path
        traj = _trajectory(H.read_final_json(editor))
        assert [e["observation"]["screenshot"] for e in traj] == mem_order
        # 末步被 H.finish 转为 terminate，意图固定为「任务已完成」；其余步保序
        assert [e.get("intent") for e in traj][:-1] == mem_intents[:-1]
        assert traj[-1]["actions"][0]["action"] == "terminate"
        I.assert_final_json(editor, expected_rounds=1)


# ===========================================================================
# 多轮跨轮唯一
# ===========================================================================
class TestMultiRoundIntegrity:
    def test_round2_insert_delete_global_unique(self, editor):
        """第 1 轮正常，第 2 轮插入 + 删除 → 跨轮截图全局唯一 + 每轮轨迹顺序正确。"""
        # 第 1 轮：2 步
        H.walk_steps(editor, 2, intent_template="R1第{i}步")
        editor.save_current_round()
        # 走正规切轮入口 reset_for_new_task（生产环境 start_new_round/create_new_task
        # 均经此路径），同步销毁上一轮的 stack 步骤页；若只手动 steps=[] 会留下孤儿页，
        # 令 stack 位置与 steps 下标错位，后续删除的 _drop_stack_page 会误杀活跃编辑器。
        editor.reset_for_new_task()
        assert len(editor.rounds) == 1

        # 第 2 轮：3 步 → 插入 → 删除
        H.walk_steps(editor, 3, intent_template="R2第{i}步")
        ins = H.insert_step_after(editor, 0)
        _fill_and_confirm(editor, ins, "R2插入")
        editor.display_step(2)
        H.delete_current(editor, confirm=True)
        assert len(editor.steps) == 3

        editor.save_current_round()
        editor.reset_for_new_task()
        assert len(editor.rounds) == 2

        # 直接结束（steps 已空）
        old_q = editor._test_dialogs.question_result
        editor._test_dialogs.question_result = QMessageBox.No
        try:
            editor.finish_all_annotation()
        finally:
            editor._test_dialogs.question_result = old_q

        # INV-8 跨轮全局唯一 + 每轮顺序 + coords 对齐
        I.assert_final_json(editor, expected_rounds=2)

        final = H.read_final_json(editor)
        trajectories = [m["trajectory"] for m in final["messages"] if m["role"] == "assistant"]
        assert [len(t) for t in trajectories] == [2, 3], [len(t) for t in trajectories]

        all_shots = [e["observation"]["screenshot"] for t in trajectories for e in t]
        assert len(all_shots) == len(set(all_shots)), f"跨轮截图重名：{all_shots}"

        # 第 2 轮轨迹顺序：[R2第1步, R2插入, R2第3步]
        r2_intents = [e.get("intent") for e in trajectories[1]]
        assert r2_intents == ["R2第1步", "R2插入", "R2第3步"], r2_intents

        # INV-14：多轮按 round 字段精确索引，各轮中心-坐标逐条对齐
        coords = H.read_final_coords(editor)
        I.assert_coords_center_match(coords, trajectories, where="多轮 coords")
