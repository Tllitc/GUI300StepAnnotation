# -*- coding: utf-8 -*-
"""DT-1~DT-9 缺陷回归测试。

这些测试专门验证 spec 中列出的 9 个候选缺陷已被修复。
其中 DT-4/DT-5/DT-7/DT-8/DT-9 已在 test_smoke 中自动覆盖，
本文件重点覆盖 DT-1/DT-2/DT-3/DT-6 以及更极端的边界场景。
"""

import os
import json
import copy

from PyQt5.QtWidgets import QMessageBox

import helpers as H
import invariants as I


# ---------------------------------------------------------------------------
# DT-1：_write_draft_now 在 steps+rounds 皆空时直接 return，删空步骤后旧草稿残留
# ---------------------------------------------------------------------------
class TestDT1:
    def test_delete_all_then_draft_not_revivify(self, editor):
        """DT-1 回归：逐步删空全部步骤后，草稿应被覆盖为 current_steps=[]；
        随后 load_from_draft 不应复活已删步骤。"""
        # 先建 3 步
        H.walk_steps(editor, 3)
        H.flush_draft(editor)
        draft_before = H.read_draft(editor)
        assert len(draft_before["current_steps"]) == 3

        # 逐步删空
        for _ in range(3):
            last = len(editor.steps) - 1
            editor.display_step(last)
            H.delete_current(editor, confirm=True)

        assert len(editor.steps) == 0

        # 立即写草稿
        H.flush_draft(editor)
        draft = H.read_draft(editor)
        assert draft is not None, "草稿文件不应消失"
        # current_steps 应为空（修复后应该是 [] 而不是旧的 3 步）
        assert draft.get("current_steps") == [], (
            f"DT-1 修复未生效：删空后 draft.current_steps 不是空列表，而是 {draft.get('current_steps')!r}"
        )

        # load_from_draft 不应复活步骤
        editor2_draft = copy.deepcopy(draft)
        editor._test_draft_loaded = editor2_draft  # 仅用于诊断

        # 直接用同一个 editor 走 load_from_draft 来验证
        editor.load_from_draft(draft)
        assert len(editor.steps) == 0, (
            f"DT-1: 续采后步骤被复活了 {len(editor.steps)}"
        )
        assert editor.current_step_index == -1

    def test_undo_all_then_draft(self, editor):
        """连续撤销到 steps 空：草稿覆盖正确。"""
        H.walk_steps(editor, 2)
        H.undo(editor, confirm=True)  # 撤 1
        H.undo(editor, confirm=True)  # 撤到 0

        assert len(editor.steps) == 0
        H.flush_draft(editor)
        draft = H.read_draft(editor)
        assert draft.get("current_steps") == []


# ---------------------------------------------------------------------------
# DT-2：save_current_round 内部 _write_draft_now 在 steps 尚未清空时执行，
#       draft 同时包含本轮 rounds 和 current_steps；崩溃续采后同一轮被重复
# ---------------------------------------------------------------------------
class TestDT2:
    def test_answer_draft_no_duplicate_round(self, editor):
        """DT-2 回归：answer 动作触发 save_current_round（把本轮加入 rounds）→
        steps = [] → schedule_draft_save。draft 应该只有 rounds，
        current_steps 应被 steps=[] 覆盖为空列表，而不是同时两者都有。"""
        H.walk_steps(editor, 2)

        # 第 3 步做 answer 动作
        editor.display_step(1)
        H.fill_step(editor, 1, action_chinese="回答并结束", intent=None, text="好的")
        # confirm_button_clicked 里 answer_terminate 走 save_current_step(terminate 分支)
        # 让它触发 save_current_round → steps=[] → schedule_draft_save
        H.confirm(editor)  # 这会走 save_current_step 内部分支

        # 此时：save_current_step 的 answer/terminate 分支调用 save_current_round，
        # 然后 steps = []，再 schedule_draft_save。schedule_draft_save 1s 后才会执行，
        # 我立即调 _write_draft_now 来模拟（跳过防抖）。
        H.flush_draft(editor)

        draft = H.read_draft(editor)
        assert draft is not None
        # rounds 里应有 1 轮（含那 2 步的轨迹）
        assert len(draft["rounds"]) == 1, f"rounds 应为 1，实际 {len(draft['rounds'])}"
        # current_steps 应为 []（因为 steps 已被清空）
        assert draft.get("current_steps") == [], (
            f"DT-2 修复未生效：answer 后 draft.current_steps 应为空（steps 已清），"
            f"但实际有 {len(draft.get('current_steps') or [])} 条"
        )
        # 断言 rounds 和 current_steps 没有"同一轮重复"
        # 比较 rounds[0].trajectory 与 draft.current_steps 的截图文件名集合
        round_shots = {t.get("observation", {}).get("screenshot")
                       for t in draft["rounds"][0].get("trajectory", [])}
        current_shots = {s.get("screenshot_filename") for s in draft.get("current_steps", [])}
        assert not (round_shots & current_shots), (
            f"DT-2: rounds 与 current_steps 出现同轮重复！rounds shots={round_shots} "
            f"current shots={current_shots}"
        )

    def test_terminate_draft_no_duplicate_round(self, editor):
        """DT-2 回归：terminate 动作后的 draft 也不应有同轮重复。"""
        H.walk_steps(editor, 2)
        editor.display_step(1)
        H.fill_step(editor, 1, action_chinese="任务完成", intent=None)
        H.confirm(editor)  # save_current_step(terminate) → save_current_round → steps=[]

        H.flush_draft(editor)
        draft = H.read_draft(editor)
        assert len(draft["rounds"]) == 1
        assert draft.get("current_steps") == []


# ---------------------------------------------------------------------------
# DT-3：reset_for_new_task 不调度 draft 写盘，上一轮 current_steps 残留
# ---------------------------------------------------------------------------
class TestDT3:
    def test_reset_for_new_task_overwrites_draft(self, editor):
        """DT-3 回归：已有轮次且 steps 非空 → reset_for_new_task → 旧的 current_steps
        不应残留在 draft 中。"""
        # 先造一批步骤、写草稿
        H.walk_steps(editor, 2)
        H.flush_draft(editor)
        draft_before = H.read_draft(editor)
        assert len(draft_before["current_steps"]) == 2

        # 调 reset_for_new_task（产品里 start_new_round / create_new_task 内部会调）
        editor.reset_for_new_task()
        # DT-3 修复后 reset_for_new_task 末尾已直接调 _write_draft_now，
        # 这里不需要再 flush
        draft_after = H.read_draft(editor)
        assert draft_after is not None
        assert draft_after.get("current_steps") == [], (
            f"DT-3 修复未生效：reset_for_new_task 后 current_steps 不是空列表，"
            f"而是 {draft_after.get('current_steps')!r}"
        )


# ---------------------------------------------------------------------------
# DT-4：续采步骤 data 快照陈旧，编辑不进入草稿/最终 JSON
# ---------------------------------------------------------------------------
class TestDT4:
    def test_resume_edit_goes_to_final_json(self, editor):
        """DT-4 回归：续采后编辑某步动作类型/文本 → 最终 JSON 反映修改。"""
        # 造 3 步，普通 confirm（只置 confirmed，不写 data 快照）
        H.walk_steps(editor, 3, intent_template="原始第 {i} 步")

        # 写草稿（走 _write_draft_now）
        H.flush_draft(editor)
        draft_before = H.read_draft(editor)
        # 此时 draft 里 current_steps 的 data 快照应该已经通过 DT-4/DT-5 修复
        # 拿到实时数据（因为 _write_draft_now 一律 get_data），并带 step 字段
        for i, ds in enumerate(draft_before["current_steps"]):
            data = ds["data"]
            assert "step" in data and data["step"] == i, (
                f"DT-5/DT-4: draft steps[{i}].data.step 应为 {i}，实际 {data.get('step')}"
            )
            obs = data.get("observation", {})
            assert obs.get("screenshot") == ds["screenshot_filename"], (
                f"DT-4: data.observation.screenshot 不一致"
            )

        # 关闭并从草稿续采
        editor.cleanup_resources()
        # 重新打开同一个 editor 实例（不新建），load_from_draft 会重置 stack/steps
        editor._is_closing = False  # reset cleanup 标志（用于测试）
        editor.load_from_draft(draft_before)

        # 续采后修改第 2 步（下标 1）的 intent 和坐标
        editor.display_step(1)
        new_intent = "续采后修改的第 2 步"
        editor.steps[1]["editor"].intent_input.setText(new_intent)
        editor.steps[1]["editor"].coord_x_input.setText("555")
        editor.steps[1]["editor"].coord_y_input.setText("666")

        # flush draft → 这里 _write_draft_now 应走实时 get_data
        H.flush_draft(editor)
        draft_after = H.read_draft(editor)
        modified_data = draft_after["current_steps"][1]["data"]
        assert modified_data["intent"] == new_intent, (
            f"DT-4 修复未生效：续采后编辑的 intent 未进入草稿，"
            f"期望 {new_intent!r}，实际 {modified_data.get('intent')!r}"
        )
        # 最终 JSON 也应反映
        json_path = H.finish(editor, action="terminate")
        assert json_path, "最终 JSON 产出失败"
        final = H.read_final_json(editor)
        traj = final["messages"][1]["trajectory"]  # assistant 消息
        assert traj[1]["intent"] == new_intent, (
            f"DT-4: 最终 JSON trajectory[1].intent 未反映编辑，"
            f"期望 {new_intent!r}，实际 {traj[1].get('intent')!r}"
        )


# ---------------------------------------------------------------------------
# DT-5：普通步骤 data 快照缺 step 字段
# ---------------------------------------------------------------------------
class TestDT5:
    def test_every_final_step_has_step_field(self, editor):
        """DT-5 回归：最终 JSON trajectory 每条都有 step 字段且等于下标。"""
        H.walk_steps(editor, 4, intent_template="第 {i} 步")
        json_path = H.finish(editor, action="terminate")
        final = H.read_final_json(editor)
        traj = final["messages"][1]["trajectory"]
        for i, entry in enumerate(traj):
            assert entry.get("step") == i, (
                f"DT-5: trajectory[{i}].step 应为 {i}，实际 {entry.get('step')}"
            )


# ---------------------------------------------------------------------------
# DT-6：_delete_screenshot_file 不检查 rounds 引用
# ---------------------------------------------------------------------------
class TestDT6:
    def test_delete_doesnt_touch_rounds_referenced(self, editor):
        """DT-6 回归：_delete_screenshot_file 遇到 rounds 已引用的文件应跳过删除。"""
        # 先造一批步骤，存到磁盘
        H.walk_steps(editor, 2)
        H.flush_draft(editor)

        # 取第一个步骤的文件
        filename = editor.steps[0]["screenshot_filename"]
        gui_dir = os.path.join(editor.data_manager.current_dir, f"gui_{editor.gui_number}")
        path = os.path.join(gui_dir, filename)
        assert os.path.isfile(path), "截图必须存在"

        # 手动模拟该文件被 rounds 历史轨迹引用（产品 save_current_round 后就是这种状态）
        editor.rounds.append({
            "instruction": "历史指令",
            "trajectory": [
                {"step": 0, "observation": {"screenshot": filename},
                 "actions": [{"action": "left_click"}]}
            ]
        })

        # 调 _delete_screenshot_file：发现被 rounds 引用，应跳过
        editor._delete_screenshot_file(filename)
        assert os.path.isfile(path), (
            f"DT-6 修复未生效：历史轮次引用的截图 {filename} 被误删"
        )

        # 把 rounds 清掉，再调一次，应真删
        editor.rounds = []
        editor._delete_screenshot_file(filename)
        assert not os.path.isfile(path), (
            f"DT-6: 无 rounds 引用时截图应被删除 {filename}"
        )


# ---------------------------------------------------------------------------
# DT-7：重新截图后 selection_type 不归一化、data 不刷新
# ---------------------------------------------------------------------------
class TestDT7:
    def test_recapture_single_becomes_drag(self, editor):
        """DT-7 回归：原为单框 click → 双框 drag 重新截图 → selection_type 归一化为 drag。"""
        H.append_step(editor)
        idx = len(editor.steps) - 1
        H.fill_step(editor, idx, action_chinese="左键单击", intent="测试", coord_text="250,350")
        old_selection = editor.steps[idx]["selection_type"]
        # 默认 Fake 发的是单框，selection_type="click"
        assert old_selection == "click", f"初始 selection_type 应为 click，实际 {old_selection}"

        # 双框重新截图
        H.recapture_drag(editor, idx)

        new_selection = editor.steps[idx]["selection_type"]
        assert new_selection == "drag", (
            f"DT-7 修复未生效：双框重新截图后 selection_type 应为 drag，实际 {new_selection}"
        )
        # 编辑器应已切到"拖拽"动作
        editor_now = editor.steps[idx]["editor"]
        action_cn = editor_now.action_type_combo.currentText()
        assert action_cn == "拖拽", (
            f"DT-7: 双框后编辑器动作类型应为'拖拽'，实际 {action_cn!r}"
        )

    def test_recapture_file_reused(self, editor):
        """INV-6 重申：重新截图必须复用原文件名。"""
        H.append_step(editor)
        idx = len(editor.steps) - 1
        orig_filename = editor.steps[idx]["screenshot_filename"]

        before_files = set(I._strict_named_pngs(editor))
        H.recapture(editor, idx)
        after_files = set(I._strict_named_pngs(editor))

        assert before_files == after_files, "重新截图不应产生新文件"
        assert editor.steps[idx]["screenshot_filename"] == orig_filename


# ---------------------------------------------------------------------------
# DT-8：_check_stack_invariant 只 print 不抛错
# ---------------------------------------------------------------------------
class TestDT8:
    def test_invariant_broken_flag(self, editor):
        """DT-8 回归：_check_stack_invariant 失败时置 _stack_invariant_broken=True。"""
        assert getattr(editor, "_stack_invariant_broken", None) is False

        # 人工打穿 invariant（直接从 stack 里 removeWidget 不走模型）
        H.append_step(editor)
        editor.stack_widget.removeWidget(editor.steps[0]["editor"])
        editor._check_stack_invariant()

        assert editor._stack_invariant_broken is True, (
            "DT-8: invariant 失败后应置 _stack_invariant_broken=True"
        )
        # undo_last_step 应被拦截并弹出 warning
        # （QMessageBox 已被 patch，只会记录调用）
        before = len(editor.steps)
        ctrl = editor._test_dialogs
        ctrl.question_result = QMessageBox.Yes  # 即使返回 Yes 也应在 invariant 检查前被 warning 拦下
        editor.undo_last_step()
        assert len(editor.steps) == before, "DT-8: invariant 被打穿时 undo 应被拦截"
        # 恢复 invariant
        editor.stack_widget.addWidget(editor.steps[0]["editor"])
        editor._check_stack_invariant()
        assert editor._stack_invariant_broken is False


# ---------------------------------------------------------------------------
# DT-9：undo_last_step 无条件删末尾，非末步触发时模型错位
# ---------------------------------------------------------------------------
class TestDT9:
    def test_undo_non_last_step_blocked(self, editor):
        """DT-9 回归：当前停在中间步时调 undo_last_step 应被拦截。"""
        H.walk_steps(editor, 3)
        editor.display_step(0)  # 跳到第 1 步（非末步）

        before_steps = len(editor.steps)
        before_index = editor.current_step_index
        editor.undo_last_step()  # 应被 DT-9 修复拦截

        # 步数不变、当前下标不变
        assert len(editor.steps) == before_steps, (
            f"DT-9 修复未生效：非末步时 undo 不应真执行，步数 {before_steps} → {len(editor.steps)}"
        )
        assert editor.current_step_index == before_index, (
            f"DT-9: 当前步骤下标应保持 {before_index}，实际 {editor.current_step_index}"
        )

    def test_undo_after_jump_to_last_works(self, editor):
        """DT-9 正面：跳到末步后 undo 正常工作。"""
        H.walk_steps(editor, 3)
        editor.display_step(2)  # 末步

        before = len(editor.steps)
        H.undo(editor, confirm=True)
        assert len(editor.steps) == before - 1


# ---------------------------------------------------------------------------
# 多轮交叉
# ---------------------------------------------------------------------------
class TestMultiRound:
    def test_two_rounds_then_finish(self, editor):
        """两轮采标 → 最终 JSON 含两组 trajectory。

        简化版：不依赖 show_new_task_dialog 弹窗交互，
        手动调 save_current_round + start_new_round（后者内部调 reset_for_new_task）。
        """
        # 第一轮：2 步普通
        H.walk_steps(editor, 2)

        # 手动 save_current_round（把这 2 步加到 rounds）
        editor.save_current_round()
        # 手动清 steps（模拟 answer/terminate 后的状态）
        editor.steps = []
        editor.current_step_index = -1

        assert len(editor.rounds) == 1
        assert len(editor.rounds[0]["trajectory"]) == 2
        # trajectory 每条都应有 step 字段
        for i, entry in enumerate(editor.rounds[0]["trajectory"]):
            assert entry.get("step") == i

        # 第二轮：1 步普通 → save_current_round
        H.append_step(editor)
        idx = len(editor.steps) - 1
        H.fill_step(editor, idx, action_chinese="左键单击",
                    intent="第二轮第 1 步", coord_text="400,500")
        H.confirm(editor)   # confirm_button_clicked 普通确认
        editor.save_current_round()

        assert len(editor.rounds) == 2
        assert len(editor.rounds[1]["trajectory"]) == 1

        # 把第二轮的 steps 清掉，然后直接 finish 手动调用 finish_all_annotation
        # （show_new_task_dialog 会弹窗，patch 成 No）
        editor.steps = []
        old_q = editor._test_dialogs.question_result
        editor._test_dialogs.question_result = QMessageBox.No
        try:
            editor.finish_all_annotation()
        finally:
            editor._test_dialogs.question_result = old_q

        final = H.read_final_json(editor)
        assert final is not None
        messages = final["messages"]
        # 应两轮：每轮 user + assistant
        assert len(messages) == 4, f"两轮应有 4 条 messages，实际 {len(messages)}"
        trajectories = [m["trajectory"] for m in messages if m["role"] == "assistant"]
        assert len(trajectories) == 2
        assert len(trajectories[0]) == 2
        assert len(trajectories[1]) == 1


# ---------------------------------------------------------------------------
# 续采后再操作
# ---------------------------------------------------------------------------
class TestResumeThenMutate:
    def test_resume_then_delete(self, editor):
        """续采后删除 → 最终产物正确。"""
        H.walk_steps(editor, 3)
        H.flush_draft(editor)
        draft = H.read_draft(editor)

        editor.load_from_draft(draft)
        assert len(editor.steps) == 3

        editor.display_step(1)
        H.delete_current(editor, confirm=True)

        assert len(editor.steps) == 2
        I.assert_model(editor)
        I.assert_stack(editor)
        I.assert_files(editor)

        json_path = H.finish(editor, action="terminate")
        assert json_path


# 注意：这个导入必须在 class 外面
from PyQt5.QtTest import QTest


# ---------------------------------------------------------------------------
# 多轮截图全局递增：复刻老样本 gui_000003 的 4 轮场景，锁死截图序号按磁盘
# max+1 全局递增、跨轮不回退到 0001、跨轮无同名覆盖（INV-8 跨轮唯一）
# ---------------------------------------------------------------------------
class TestMultiRoundGlobalShots:
    def test_four_rounds_screenshots_globally_unique(self, editor):
        """同一 gui 任务连续 4 轮（2/3/2/1 步，共 8 步、8 张截图）：
        前 3 轮以 answer 动作续轮，第 4 轮 terminate 结束。
        最终截图序号必须跨轮接续为 0001~0008，磁盘 PNG 与 JSON 引用集合完全相等。"""
        step_counts = [2, 3, 2, 1]
        dialogs = editor._test_dialogs

        for r, n_steps in enumerate(step_counts):
            # 预设本轮 answer 续轮弹窗里输入的下一轮 instruction
            # （第 4 轮不再续轮，用不到，但赋值无害）
            dialogs.getText_result_text = f"第{r + 2}轮指令"
            # 首轮 instruction 直接在 editor 上设置（构造时的默认指令会被覆盖）
            editor.task_instruction = f"第{r + 1}轮指令"

            H.walk_steps(
                editor, n_steps,
                action_chinese="左键单击",
                intent_template=f"第{r + 1}轮第{{i}}步",
            )

            if r < 3:
                # 前 3 轮：末步 answer 动作 → save_current_round → 清空 steps →
                # 300ms QTimer 后 start_new_round 弹 QInputDialog 取下一轮 instruction
                last_idx = len(editor.steps) - 1
                H.fill_step(editor, last_idx, action_chinese="回答用户",
                            intent=None, text=f"第{r + 1}轮回答")
                H.confirm(editor)
                # 等 300ms singleShot(start_new_round) + getText + reset_for_new_task
                QTest.qWait(500)
                assert len(editor.rounds) == r + 1, (
                    f"第 {r + 1} 轮 answer 后续轮未完成，rounds={len(editor.rounds)}"
                )
                assert len(editor.steps) == 0, (
                    f"第 {r + 1} 轮续轮后 steps 未清空：{len(editor.steps)}"
                )
                assert editor.task_instruction == f"第{r + 2}轮指令"

        # 第 4 轮（当前）1 步以 terminate 成功结束：H.finish 内部填"任务完成"、
        # confirm 后等 300ms show_new_task_dialog，question 应答 No →
        # finish_all_annotation(close_after_save=False) 产出最终 JSON
        json_path = H.finish(editor, action="terminate")
        assert json_path, "最终 JSON 产出失败"

        # 增强后的 INV-8：含跨轮截图全局唯一断言
        I.assert_final_json(editor, expected_rounds=4)

        # ---- 直接读最终 JSON 做专项断言 ----
        gui_dir = os.path.join(editor.data_manager.current_dir,
                               f"gui_{editor.gui_number}")
        with open(os.path.join(gui_dir, f"gui_{editor.gui_number}.json"),
                  "r", encoding="utf-8") as f:
            final = json.load(f)

        messages = final["messages"]
        # messages 长度 8，role 严格 user/assistant 交替
        assert len(messages) == 8, f"4 轮应有 8 条 messages，实际 {len(messages)}"
        for i, msg in enumerate(messages):
            expected_role = "user" if i % 2 == 0 else "assistant"
            assert msg.get("role") == expected_role, (
                f"messages[{i}] role={msg.get('role')!r}，应为 {expected_role!r}"
            )

        # 每轮 instruction 不同
        for r in range(4):
            assert messages[r * 2].get("instruction") == f"第{r + 1}轮指令"

        trajectories = [messages[i]["trajectory"] for i in range(1, 8, 2)]
        # 4 个 assistant 消息 trajectory 长度 2/3/2/1，step 从 0 连续
        assert [len(t) for t in trajectories] == [2, 3, 2, 1], (
            f"各轮 trajectory 长度应为 [2, 3, 2, 1]，实际 {[len(t) for t in trajectories]}"
        )
        for r, traj in enumerate(trajectories):
            for s_idx, entry in enumerate(traj):
                assert entry.get("step") == s_idx, (
                    f"round {r} step {s_idx} 的 step 字段={entry.get('step')}"
                )

        # 按轮次/步次顺序收集全部截图名：共 8 个，全局互不重复
        all_shots = []
        for traj in trajectories:
            for entry in traj:
                shot = (entry.get("observation") or {}).get("screenshot")
                assert shot, f"round 内存在缺 screenshot 的 step"
                all_shots.append(shot)
        assert len(all_shots) == 8
        assert len(set(all_shots)) == 8, f"8 张截图中存在重名：{all_shots}"

        # 末尾 4 位数字严格单调递增且为 [1..8]，跨轮绝不回到 0001
        numbers = [int(name[-8:-4]) for name in all_shots]
        assert numbers == [1, 2, 3, 4, 5, 6, 7, 8], (
            f"跨轮截图序号必须全局接续 [1..8]，实际 {numbers}，截图={all_shots}"
        )
        assert all_shots[0] == f"gui_{editor.gui_number}_0001.png"

        # 磁盘实际 PNG（只统计 gui_XXXXXX_####.png）与 JSON 引用集合完全相等：
        # 无悬空引用、无孤儿文件
        referenced = set(all_shots)
        on_disk = set(I._strict_named_pngs(editor))
        assert on_disk == referenced, (
            f"磁盘 PNG 与 JSON 引用不一致："
            f"悬空引用={sorted(referenced - on_disk)}，"
            f"孤儿文件={sorted(on_disk - referenced)}"
        )
