# -*- coding: utf-8 -*-
"""数据完整性缺陷回归测试组（DI 系列，iOS 端）。

DI 编号 ↔ 缺陷映射（三端共用同一编号，便于交叉对照）::

    DI-1  = B20a  Android 落轮后不清 steps_data → 草稿重建 → 多轮折叠
    DI-2  = B19   Android 续采追问指令取消分支缺失 → 整轮静默丢弃
    DI-3  = B30/B11 编辑模式的重截图/删步/撤销改盘边界
                  （需求变更：产品上**允许**编辑模式重截图与删步，故本组用例
                   断言「允许改盘，但必须原地覆盖同名文件、不越界写盘、
                   不误删他轮引用」，而非早前的「一律拦截」）
    DI-4  = B16/B17 删图只查 steps_data 不查 rounds → 删掉已落轮仍引用的 PNG
    DI-5  = B6    Windows scroll 步拉框顶点永久不进 coords
    DI-6  = B40/B41 编辑写回全量重建 messages / 空 coords 覆盖原文件
    DI-7  = B38/B10 截图序号分配语义与空洞/插入治理
                  （修复仅落 Android：其 get_next_screenshot_number 原按「最小未占用
                   序号」分配，删图/撤销留的空洞会被后续新截图复用（B38）；iOS 本就是
                   磁盘 max+1，且「中间序号空洞永不复用」已由 test_rounds_draft 的 D-8
                   用例钉住。3.2 口径（插入步取 max+1 却落在中间 → 序号/step 顺序倒挂
                   属可接受，INV-11 只钉全局唯一 + 命名合规 + 引用存在）三端一致，
                   本端无新增可变异缺陷，不重复建例，仅登记以保持三端映射表同步）
    DI-8  = B2    singleShot(300) 竞态窗口内重复落轮
    DI-9  = B37   iOS 空现场不删残留草稿 → 续采复活已删步骤
                  （**本端修复**，计划 5.1：_write_draft_now 的空现场分支改为
                   delete_draft；Windows 同分支本就落空草稿（DT-1），Android 已具备
                   同名删草稿分支，两端仅登记）
    DI-10 = B50   iOS save_screenshot(filename=) 无校验 → 路径穿越写出 gui_dir
    DI-11 = B1/B28 answer 后取消新轮不重置工作区
                  （计划 6.2 曾把该场景也记作 DI-3，与 B30 冲突，此处改判 DI-11）
    DI-12 = 计划 1.4 最终 JSON 直接 open(w) 覆盖写、无备份
                  （无对应 Bxx：写盘中途中断会留下半截/空文件，已交付数据不可恢复）
    DI-13 = B3    编辑模式轮次选择摘要撞车 → 改错轮并写回（计划 1.6）
    DI-14 = B15   Windows 摘页只 removeWidget/setParent(None) → 步骤页变游离
                  顶层窗口泄漏（**仅 Windows**：iOS 无 QStackedWidget 步骤页模型，
                  本端不适用，仅登记编号以保持三端映射表同步）
    DI-15 = B14   三端 续轮指令取消后沿用旧 instruction → 新一轮轨迹静默挂到
                  上一条已被消费的指令上（取消即置空 + 落轮前强校验非空，
                  缺指令先弹窗补齐、补齐失败则拒绝落轮并保持现场）
                  （iOS 关闭路径只写草稿、不落轮，故「无人值守静默拒绝」子场景
                   本端不适用，仅 Windows/Android 落地该例）
    DI-16 = B42   落轮时把 steps_data 里的 action 活对象直接放进 rounds → rounds 与
                  本轮数据共享同一个 dict，任何对步骤 action 的原地改写（含嵌套的
                  coordinate 列表）都会回写到已落轮、甚至已交付的轮次上
                  （修复：落轮存 copy.deepcopy 副本；coords 侧无需再包，
                   _build_coords_entry 内的 vertices 由 _valid_vertices 返回 list()
                   副本且只读 action_data）
                  （Windows 落轮侧已对 editor.get_data() 做 deepcopy（DT-4），
                   本缺陷仅 iOS / Android 适用）
    DI-17 = B22   采集中回看历史步、改完确认后 current_step 被无条件推到
                  len(steps_data) → 用户被静默传送到末尾、正在核对的表单被清空
                  （修复：确认后只前进一格——中间历史步落到下一已有步并完整回填
                   现场，仅追加新步/确认末步才进入末尾待截图空位；不采用「原地
                   不动」，因为 go_next 停在末步时靠 confirm_step 进入空位）
                  （计划原将 B22 记作 Android 专属，勘察确认 iOS confirm_step
                   与 _save_current_to_steps 为同形写法，故同批修复；
                   Windows 无 confirm_step 传送语义，本端不适用）
    DI-18 = _finish_task 必填校验拒收早退前不重建侧栏 → 条目数落后于刚落表的
                  当前步、缺填标记停在旧步骤集合上（INV-8 破坏）
                  （修复：弹缺填清单前先 sidebar.rebuild_items()；
                   Windows 拒收分支已重算缺项并刷新条目/看板，本端已具备等价保护）
    DI-19 = B24   live 步豁免截图磁盘存在性校验 → 交付 JSON 引用不存在的 PNG
                  （仅 Android：iOS 校验链无 is_live 豁免，且 _restore_step_to_ui
                   已用 QPixmap.isNull 兼容缺失图，本端不适用，仅登记）
    DI-20 = B23   每张截图无条件覆写顶层 screen_info["screen_size"] → 会话中一次
                  分辨率抖动改写整轮交付尺寸
                  （修复：只由「本轮首张追加截图」定版；
                   Windows 采集分支本就有同形守卫，本缺陷仅 Android / iOS 适用）
    DI-21 = B44   每次截图用唯一临时名（防 QPixmap 缓存串图）却从不回收 →
                  临时目录逐张累积泄漏
                  （修复：下一次截图尾部回收**上一张**临时文件；本次临时文件仍被
                   screenshot_cache 引用（swipe/scroll 测量依赖）不得先删。
                   Android 用固定临时名、逐张覆盖不累积，本端不适用）
    DI-22 = B49   _build_coords_entry 用 action_data["action"] 直接下标 → 磁盘脏数据
                  （缺 action 键 / actions 为空）抛 KeyError 并中断整轮编辑写回
                  （**本端不适用**：iOS _build_coords_entry 一直用
                   action_data.get("action", "")，对磁盘脏数据天然安全；仅登记编号
                   以保持三端映射表同步，不写不可变异的假绿用例）
    DI-23 = B12   Windows get_data 两处坐标污染：无坐标语义豁免名单缺
                  answer_terminate（回答动作交付无意义的 coordinate）+ 裸 except 把
                  解析不了的坐标静默伪造成 [0,0] 写进交付数据
                  （**本端不适用**：iOS 坐标条目同样经 _valid_coord_pair/
                   _valid_vertices 守卫产出，解析不了就不写键；仅登记以保持三端
                   映射表同步）
    DI-24 = B4/B18 + B35   交付的扁平 coords 条目不带 round → 轮内 step 下标每轮都从 0
                  起重编，(step, action) 在多轮间重复，读取只能靠「step 变小则切段」
                  猜测归属；只要有一轮一个坐标步都没有、或多轮 step 同签名，就整段
                  错位把已交付的顶点配到别的轮次上
                  （**本端不适用，且本端就是三端基准**：写侧 _save_all_rounds_to_file
                   与 save_edited_round 一直在序列化边界给写盘副本注入 round（内存
                   rounds[r]["coords"] 不带 round），读侧 _group_coords_into_rounds
                   一直是「任一条目带 round 就逐条目归组 + 段数不匹配时 used 集合
                   逐段选未占用轮次」的口径；Windows/Android 本轮向本端对齐。
                   仅登记以保持三端映射表同步）
    DI-25 = B9    Windows 中途关窗走「保存全部数据」→ 绕过必填校验产出交付 JSON，
                  同一目录既「已完成」又「可续采」
                  （**本端不适用**：iOS closeEvent 的非编辑分支只 _write_draft_now()
                   （annotation_editor.py:3330-3332），本就没有关窗落交付的入口；
                   仅登记以保持三端映射表同步）
    DI-26 = B7+B8 Windows 新任务重置把空草稿写进刚交付的目录（已完成任务重回续采
                  列表）/ 新现场继承上一批数据的「已落盘」标志而跳过草稿落盘
                  （**本端不适用**：iOS _start_new_task 先换 gui_number 再
                   schedule_draft_save（:3309-3317），交付成功即 delete_draft，
                   重置序列不会向旧目录写草稿；_final_data_saved 只由编辑模式
                   save_edited_round 置位（:2819），采集态 closeEvent 不读它（:3325））
    DI-27 = B31   交付 JSON 写盘失败仍弹「任务完成」并清场 → 用户以为数据已交付，
                  实际只剩草稿（甚至草稿也没了），且无人知晓
                  （修复：_save_all_rounds_to_file 返回布尔，失败即 critical 并中止，
                   草稿与定时器原样保留；Android 同批修复，Windows 交付分支已按
                   「filepath 非空才删草稿、否则 critical」具备等价保护）
    DI-28 = B45   删步/撤销不退出 scroll 长滑测量态 → _scroll_measuring 残留为 True，
                  后续截图被当作测量补充图塞进 _scroll_extra_screenshots 而不落进
                  步骤，这些临时 PNG 再无人回收，成为孤儿文件
                  （**本端已具备等价保护、且无可观测面，不建例**：删步两条分支都会
                   先调 _clear_inputs()（_restore_step_to_ui:1728 /
                   _reset_for_next_step:2845），而 _clear_inputs 尾部已成对取消
                   swipe+scroll（:3021-3022），故删步必然退出测量态；:2069 的显式
                   取消只是防御式冗余，单独注掉它后删步现场仍全绿 → 本端任何用例
                   都是不可变异的假绿。Windows 测量态是页内状态、删步即销毁页面；
                   Android 删步已成对取消）

只依赖 conftest 夹具与 helpers/invariants/fakes。
运行（在 ios端 目录）::

    python -m pytest tests/test_data_integrity.py -q
"""

import copy
import json
import os
import shutil

from PyQt5.QtGui import QImage
from PyQt5.QtTest import QTest

import annotation_editor
import fakes
from data_manager import DataManager
from helpers import (
    capture,
    confirm,
    distinct_capture_seed,
    fill_step,
    finish_task,
    finish_task_final,
    flush_draft,
    gui_dir_of,
    gui_number_from_dir,
    open_edit_mode,
    walk_rounds,
    walk_steps,
)
from invariants import (
    assert_all,
    assert_no_files_outside,
    assert_overwrite_in_place,
    assert_round_refs_on_disk,
    assert_sidebar_consistency,
    snapshot_dir,
    snapshot_listing,
)


# ----------------------------------------------------------------------
# 现场准备
# ----------------------------------------------------------------------

def _pngs(gui_dir):
    return sorted(n for n in os.listdir(gui_dir) if n.endswith(".png"))


def _tmp_leftovers(gui_dir):
    """save_screenshot 的原子覆盖会在 gui_dir 内建 .name.tmp，成功后必须消失。"""
    return sorted(n for n in os.listdir(gui_dir) if n.endswith(".tmp"))


def _load_rounds(gui_dir):
    """从最终 JSON 还原「轮次」视图。

    iOS 的最终 JSON **不含 rounds 键**：_save_all_rounds_to_file:3013-3030 把每一轮
    拆成相邻的两条 messages（role=user 携 instruction、role=assistant 携
    trajectory），故此处按配对还原，供「他轮引用必须完好」类断言使用。
    """
    data, error = DataManager.load_json_from_dir(gui_dir)
    assert not error, f"读取最终 JSON 失败：{error}"

    rounds = []
    pending = None
    for msg in data.get("messages") or []:
        role = msg.get("role")
        if role == "user":
            pending = {
                "instruction": msg.get("instruction", ""),
                "trajectory": [],
            }
        elif role == "assistant" and pending is not None:
            pending["trajectory"] = msg.get("trajectory") or []
            rounds.append(pending)
            pending = None
    return rounds


def _prepare_completed_task(editor_factory):
    """单轮已交付任务：2 步 + terminate 收尾 → 3 张截图。

    :return: (gui_dir, gui_number, rounds)
    """
    ed = editor_factory()
    gui_dir = gui_dir_of(ed)
    gui_number = gui_number_from_dir(gui_dir)

    walk_steps(ed, 2, action="click")
    json_path = finish_task_final(ed, action="terminate")
    assert os.path.isfile(json_path), f"收尾后未写出最终 JSON：{json_path}"
    assert len(_pngs(gui_dir)) == 3, (
        f"期望 3 张截图（2 步 + 收尾步），实际 {_pngs(gui_dir)}"
    )
    return gui_dir, gui_number, _load_rounds(gui_dir)


def _prepare_two_round_task(editor_factory):
    """双轮已交付任务：每轮 2 步 + answer/terminate 步 → 共 6 张截图。

    两轮的截图序号全局递增、互不重叠，是「删步不得误删他轮」用例的前提。
    :return: (gui_dir, gui_number, rounds)
    """
    ed = editor_factory()
    gui_dir = gui_dir_of(ed)
    gui_number = gui_number_from_dir(gui_dir)

    json_path = walk_rounds(
        ed, [(2, "第一轮指令"), (2, "第二轮指令")], finish_action="terminate"
    )
    assert os.path.isfile(json_path), f"收尾后未写出最终 JSON：{json_path}"

    rounds = _load_rounds(gui_dir)
    assert len(rounds) == 2, f"期望 2 轮，实际 {len(rounds)}"
    assert len(_pngs(gui_dir)) == 6, (
        f"期望 6 张截图（每轮 3 张），实际 {_pngs(gui_dir)}"
    )
    return gui_dir, gui_number, rounds


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _tamper_final_json(gui_dir, gui_number, mutate):
    """把 mutate 就地应用到已交付的最终 JSON（测试手法，不走产品路径）。

    用 json.dump 直写，使原文件首字节完全可控，便于断言「拒写时原文件不变」。
    :return: 最终 JSON 的路径
    """
    json_path = os.path.join(gui_dir, f"gui_{gui_number}.json")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    mutate(data)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return json_path


# ----------------------------------------------------------------------
# DI-3：编辑模式允许改盘，但改盘必须受控（B30 / B11）
# ----------------------------------------------------------------------

class TestDI3:
    """编辑已完成任务时允许重截图/删步/撤销，但不得越界、不得误删他轮。"""

    def test_recapture_overwrites_in_place(self, editor_factory):
        """DI-3：编辑模式重截图 = 原地覆盖同名文件。

        放开守卫后这是主路径。必须同时满足三条，缺一即为数据破坏：
        ① 文件名不变（否则已交付 JSON 的引用会指向不存在的文件）；
        ② 内容确已改写（否则用户以为重截成功、实际没生效）；
        ③ 不新增文件、不留 .tmp、不产生草稿（编辑模式全程不碰 draft）。
        """
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory)
        parent = os.path.dirname(gui_dir)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=0)
        assert ed2.steps_data, "编辑现场未恢复步骤"

        target = ed2._current_screenshot_filename
        assert target, "编辑现场未恢复当前截图文件名"
        assert ed2._current_screenshot_filepath, "编辑现场未恢复当前截图路径"

        before = snapshot_dir(gui_dir)
        parent_before = snapshot_listing(parent)
        # 新编辑器的 fake 截图计数器从 0 重启，不推进则会产出与准备阶段
        # 第一张逐字节相同的图，「覆盖已生效」断言会假失败
        distinct_capture_seed(ed2, len(before))

        got = capture(ed2)

        assert got == target, (
            f"编辑模式重截图改变了文件名：{target} -> {got}"
            f"（必须复用原序号，否则已交付 JSON 的引用悬空）"
        )
        assert_overwrite_in_place(gui_dir, before, target)
        assert_no_files_outside(parent, parent_before)
        assert not _tmp_leftovers(gui_dir), (
            f"原子覆盖残留临时文件：{_tmp_leftovers(gui_dir)}"
        )
        assert not os.path.isfile(
            os.path.join(gui_dir, f"gui_{gui_number}_draft.json")
        ), "编辑模式重截图后产生了草稿文件（编辑已完成任务不该写 draft）"
        assert not ed2._replacing_screenshot, "重截图结束后替换标记未复位"
        assert not ed2._screenshot_in_progress, "重截图结束后截图锁未复位"

    def test_delete_step_only_affects_edited_round(self, editor_factory):
        """DI-3：编辑模式删步只回收本轮截图，其他已落轮引用必须全在盘上。"""
        gui_dir, gui_number, rounds = _prepare_two_round_task(editor_factory)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=1)
        steps_before = len(ed2.steps_data)
        assert steps_before == 3, f"第 2 轮步骤数异常：{steps_before}"

        removed_name = ed2.steps_data[0]["screenshot"]
        other_refs = {
            traj["observation"]["screenshot"]
            for traj in rounds[0]["trajectory"]
            if traj.get("observation", {}).get("screenshot")
        }
        assert removed_name in _pngs(gui_dir), f"待删截图不在盘上：{removed_name}"
        assert not (other_refs & {removed_name}), (
            "两轮引用了同一张截图，用例前提（序号全局递增不重叠）不成立"
        )

        before = set(_pngs(gui_dir))
        ed2.delete_current_step()
        QTest.qWait(150)

        after = set(_pngs(gui_dir))
        assert len(ed2.steps_data) == steps_before - 1, (
            f"编辑模式删步未生效：仍有 {len(ed2.steps_data)} 步"
        )
        assert removed_name not in after, (
            f"被删步骤的截图未回收（会变成孤儿文件）：{removed_name}"
        )
        assert after == before - {removed_name}, (
            f"删步影响了预期之外的文件：多删 "
            f"{sorted(before - after - {removed_name})}，新增 {sorted(after - before)}"
        )
        # 关键：第 1 轮（未编辑）引用的 3 张截图必须一张不少
        assert_round_refs_on_disk(gui_dir, rounds, skip_round_index=1)
        assert not _tmp_leftovers(gui_dir)

    def test_undo_step_in_edit_mode_is_bounded(self, editor_factory):
        """DI-3：编辑模式撤销只动当前步，且撤销后现场仍自洽。

        两端撤销语义**不同**，不可互抄：iOS undo_last_step 委托
        delete_current_step(confirm_dialog=False)，删的是 current_step（进入
        编辑现场后为 0，即本轮首步）；Android undo_step 才是真的
        steps_data.pop() 弹末步。故此处必须按 current_step 取待删名。
        """
        gui_dir, gui_number, rounds = _prepare_two_round_task(editor_factory)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=1)
        steps_before = len(ed2.steps_data)
        idx = ed2.current_step
        assert 0 <= idx < steps_before, f"编辑现场 current_step 越界：{idx}"
        target_name = ed2.steps_data[idx]["screenshot"]

        before = set(_pngs(gui_dir))
        ed2.undo_last_step()
        QTest.qWait(150)

        after = set(_pngs(gui_dir))
        assert len(ed2.steps_data) == steps_before - 1, (
            f"编辑模式撤销未生效：仍有 {len(ed2.steps_data)} 步"
        )
        assert after <= before, f"撤销凭空新增了文件：{sorted(after - before)}"
        assert target_name not in after, (
            f"被撤销步骤的截图未回收（会变成孤儿文件）：{target_name}"
        )
        assert after == before - {target_name}, (
            f"撤销影响了预期之外的文件：多删 "
            f"{sorted(before - after - {target_name})}，新增 {sorted(after - before)}"
        )
        # 关键：第 1 轮（未编辑）引用的截图必须一张不少
        assert_round_refs_on_disk(gui_dir, rounds, skip_round_index=1)
        assert not _tmp_leftovers(gui_dir)


# ----------------------------------------------------------------------
# DI-4：删图判定必须计入已落轮 rounds（B16 / B17）
# ----------------------------------------------------------------------

class TestDI4:
    """删图可达集 = steps_data ∪ rounds ∪ 当前在编截图。"""

    def test_guard_considers_landed_rounds(self, editor_factory):
        """DI-4 回归：steps_data 已不含引用、但 rounds 仍引用时，绝不能删盘。

        这正是 B16/B17 的现场：answer 落轮后 steps_data 被清空，或编辑模式下
        steps_data 只装被编辑的那一轮。旧实现只遍历 steps_data，会把已交付、
        且最终 JSON 仍在引用的 PNG 删掉，无备份、不可恢复。
        """
        gui_dir, gui_number, rounds = _prepare_two_round_task(editor_factory)

        ed2 = editor_factory(auto_init=False)
        # 编辑第 2 轮，使第 1 轮成为「未被 steps_data 覆盖的已落轮」
        open_edit_mode(ed2, gui_dir, round_index=1)

        landed = rounds[0]["trajectory"][0]["observation"]["screenshot"]
        target = os.path.join(gui_dir, landed)
        assert os.path.isfile(target), f"前置条件不成立：{landed} 不在盘上"

        ed2.steps_data = []
        ed2._current_screenshot_filename = None
        ed2._current_screenshot_filepath = None
        ed2._delete_file_if_unreferenced(target)

        assert os.path.isfile(target), (
            f"已落轮仍引用的截图被删除：{landed}（B16/B17）"
        )
        assert_round_refs_on_disk(gui_dir, rounds)

    def test_guard_still_recycles_true_orphans(self, editor_factory):
        """正向对照：确实无人引用的文件仍要回收，否则可达集过宽 → 孤儿堆积。"""
        gui_dir, gui_number, rounds = _prepare_two_round_task(editor_factory)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=1)

        referenced = os.path.join(
            gui_dir, rounds[0]["trajectory"][0]["observation"]["screenshot"]
        )
        orphan = os.path.join(gui_dir, f"gui_{gui_number}_9999.png")
        shutil.copy2(referenced, orphan)
        assert os.path.isfile(orphan)

        ed2.steps_data = []
        ed2._current_screenshot_filename = None
        ed2._current_screenshot_filepath = None
        ed2._delete_file_if_unreferenced(orphan)

        assert not os.path.isfile(orphan), (
            "无人引用的截图未被回收 → 可达集判定过宽，会长期堆积孤儿文件"
        )
        assert os.path.isfile(referenced), "误删了仍被引用的截图"


# ----------------------------------------------------------------------
# DI-10：save_screenshot(filename=) 路径穿越（B50）
# ----------------------------------------------------------------------

class TestDI10:
    """filename 来自草稿/已交付 JSON，可被篡改，必须校验后才允许落盘。"""

    ILLEGAL = [
        "..\\..\\evil.png",        # Windows 风格向上穿越
        "../../evil.png",          # POSIX 风格向上穿越
        "..\\evil.png",
        "/tmp/evil.png",           # 绝对路径
        "gui_999999_0001.png",     # 前缀不符：会写到别的任务编号名下
        "notes.txt",               # 后缀不符
        "evil.exe",
        "",                        # 空名
    ]

    def test_illegal_filename_rejected(self, editor_factory):
        ed = editor_factory()
        gui_dir = gui_dir_of(ed)
        gui_number = gui_number_from_dir(gui_dir)
        src = os.path.join(gui_dir, capture(ed))
        assert os.path.isfile(src), "前置条件不成立：源截图不存在"

        parent = os.path.dirname(gui_dir)
        grandparent = os.path.dirname(parent)
        parent_before = snapshot_listing(parent)
        grandparent_before = snapshot_listing(grandparent)
        inside_before = snapshot_listing(gui_dir)

        for evil in self.ILLEGAL:
            got = ed.data_manager.save_screenshot(gui_number, src, filename=evil)
            assert got is None, f"非法文件名未被拒绝：{evil!r} -> {got!r}"

        assert_no_files_outside(parent, parent_before)
        assert_no_files_outside(grandparent, grandparent_before)
        assert snapshot_listing(gui_dir) == inside_before, (
            f"非法文件名仍在 gui_dir 内落了盘："
            f"{sorted(snapshot_listing(gui_dir) - inside_before)}"
        )

    def test_legal_filename_still_overwrites(self, editor_factory):
        """反向对照：合法名必须照常原子覆盖，避免校验过宽把重截图功能打死。"""
        ed = editor_factory()
        gui_dir = gui_dir_of(ed)
        gui_number = gui_number_from_dir(gui_dir)

        # 连续两次 capture 是「同步原地替换」而非追加（_current_screenshot_filepath
        # 非空 → _replacing_screenshot=True），故必须走完整步才能得到两个文件
        walk_steps(ed, 2, action="click")
        name1 = ed.steps_data[0]["screenshot"]
        name2 = ed.steps_data[1]["screenshot"]
        assert name1 != name2, f"两步截图同名，无法做覆盖对照：{name1}"

        src = os.path.join(gui_dir, name2)
        before = snapshot_dir(gui_dir)
        assert before[name1] != before[name2], "两张源图字节相同，对照失效"

        got = ed.data_manager.save_screenshot(gui_number, src, filename=name1)
        assert got == name1, f"合法覆盖被拒：{got!r}"
        assert_overwrite_in_place(gui_dir, before, name1)
        assert snapshot_dir(gui_dir)[name1] == before[name2], (
            "覆盖后的内容应逐字节等于源文件"
        )
        assert not _tmp_leftovers(gui_dir), (
            f"原子覆盖残留临时文件：{_tmp_leftovers(gui_dir)}"
        )

    def test_edit_mode_recapture_with_tampered_name_is_contained(self, editor_factory):
        """端到端：编辑现场文件名被篡改成穿越路径时，重截图不得写出 gui_dir。"""
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory)
        parent = os.path.dirname(gui_dir)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=0)

        parent_before = snapshot_listing(parent)
        inside_before = snapshot_listing(gui_dir)

        ed2._current_screenshot_filename = "..\\..\\evil.png"
        ed2._current_screenshot_filepath = os.path.join(gui_dir, "..\\..\\evil.png")
        ed2.take_screenshot()
        QTest.qWait(400)  # 覆盖 50ms 截图 singleShot 窗口

        assert "失败" in ed2.status_label.text(), (
            f"篡改文件名后重截图应明确报失败，状态栏：{ed2.status_label.text()!r}"
        )
        assert not ed2._screenshot_in_progress, "拒绝落盘后截图锁未复位"
        assert not ed2._replacing_screenshot, "拒绝落盘后替换标记未复位"
        assert_no_files_outside(parent, parent_before)
        assert snapshot_listing(gui_dir) == inside_before, (
            f"篡改文件名后 gui_dir 内出现新文件："
            f"{sorted(snapshot_listing(gui_dir) - inside_before)}"
        )


# ----------------------------------------------------------------------
# DI-12：最终 JSON 写盘原子化 + 编辑写回留 .bak（计划 1.4）
# ----------------------------------------------------------------------

class TestDI12:
    """写盘必须原子化；编辑写回覆盖已交付 JSON 前先留一份 .bak 兜底。"""

    def test_save_json_failure_keeps_original_intact(self, editor_factory):
        """DI-12：序列化中途失败时原文件必须一字不改，且不残留 .tmp。

        直接 open(path,"w") 会先截断原文件，json.dump 抛异常就留下半截文件。
        tmp + os.replace 的失败语义是「原文件保持不动」。
        """
        ed = editor_factory()
        gui_dir = gui_dir_of(ed)
        gui_number = gui_number_from_dir(gui_dir)
        dm = ed.data_manager

        good = {
            "platform": "ios",
            "messages": [{"role": "user", "instruction": "原始指令"}],
        }
        got = dm.save_json_data(good, gui_number)
        assert got and os.path.isfile(got), f"正常写入失败：{got!r}"
        assert os.path.basename(got) == f"gui_{gui_number}.json"
        with open(got, "rb") as f:
            good_bytes = f.read()

        # object() 不可 JSON 序列化：dump 会在写完 tmp 一部分后抛 TypeError
        broken = dict(good)
        broken["poison"] = object()
        assert dm.save_json_data(broken, gui_number) is None, (
            "不可序列化的数据竟然写成功了"
        )

        with open(got, "rb") as f:
            assert f.read() == good_bytes, (
                "写入失败后原 JSON 被截断/改写（非原子写）"
            )
        assert not _tmp_leftovers(gui_dir), (
            f"写入失败残留临时文件：{_tmp_leftovers(gui_dir)}"
        )

    def test_edit_writeback_keeps_bak_of_original(self, editor_factory):
        """DI-12：编辑写回前必须留下原 JSON 的 .bak，写回后不留 .tmp。"""
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory)
        json_path = os.path.join(gui_dir, f"gui_{gui_number}.json")
        bak_path = f"{json_path}.bak"
        with open(json_path, "rb") as f:
            original_bytes = f.read()
        assert not os.path.isfile(bak_path), "准备阶段不该产生 .bak"

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=0)
        assert ed2.save_edited_round(True) is True, "编辑写回失败"
        QTest.qWait(50)

        assert os.path.isfile(bak_path), "编辑写回未生成 .bak 备份"
        with open(bak_path, "rb") as f:
            assert f.read() == original_bytes, (
                ".bak 内容不等于写回前的原 JSON（备份时机错了）"
            )
        assert not _tmp_leftovers(gui_dir), (
            f"写回残留临时文件：{_tmp_leftovers(gui_dir)}"
        )

    def test_bak_is_overwritten_not_accumulated(self, editor_factory):
        """DI-12：连续写回只保留最新一份 .bak（覆盖式，不累积历史副本）。"""
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory)
        json_path = os.path.join(gui_dir, f"gui_{gui_number}.json")
        bak_path = f"{json_path}.bak"

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=0)
        assert ed2.save_edited_round(True) is True
        with open(json_path, "rb") as f:
            after_first = f.read()

        assert ed2.save_edited_round(True) is True
        QTest.qWait(50)

        baks = sorted(n for n in os.listdir(gui_dir) if n.endswith(".bak"))
        assert baks == [f"gui_{gui_number}.json.bak"], f".bak 累积或命名异常：{baks}"
        with open(bak_path, "rb") as f:
            assert f.read() == after_first, ".bak 未随最新一次写回覆盖"
        assert not _tmp_leftovers(gui_dir), (
            f"写回残留临时文件：{_tmp_leftovers(gui_dir)}"
        )


# ----------------------------------------------------------------------
# DI-6：编辑写回不得丢消息 / 不得用空 coords 覆盖原文件（B40 / B41）
# ----------------------------------------------------------------------

class TestDI6:
    """编辑写回只动被编辑轮，其余已交付数据一律原样保留。"""

    def test_writeback_keeps_extra_fields_and_orphan_message(self, editor_factory):
        """DI-6：messages 里的额外字段与非配对消息必须原样保留（B40）。"""
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory)

        orphan = {"role": "user", "instruction": "末尾孤立提问"}

        def mutate(data):
            data["legacy_top_field"] = "顶层附加字段"
            data["messages"][0]["custom_note"] = "用户消息附加字段"
            data["messages"][1]["cot_source"] = "助手消息附加字段"
            # 末尾一条没有配对 assistant 的 user 消息：它不属于任何轮次，
            # 但属于已交付数据，写回不得把它一并删掉
            data["messages"].append(dict(orphan))

        json_path = _tamper_final_json(gui_dir, gui_number, mutate)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=0)
        assert len(ed2.rounds) >= 1, "孤立消息导致轮次解析异常"

        ed2.intent_input.setText("修改后的意图")
        assert ed2.save_edited_round(True) is True, "编辑写回失败"
        QTest.qWait(50)

        with open(json_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        messages = saved["messages"]
        assert saved.get("legacy_top_field") == "顶层附加字段", "顶层额外字段丢失"
        assert len(messages) == 3, f"消息数量变了：{len(messages)} 条"
        assert messages[0].get("custom_note") == "用户消息附加字段", (
            "本轮 user 消息的附加字段被全量重建抹掉"
        )
        assert messages[1].get("cot_source") == "助手消息附加字段", (
            "本轮 assistant 消息的附加字段被全量重建抹掉"
        )
        assert messages[2] == orphan, "末尾孤立 user 消息被丢弃"
        # 同时确保该改的真的改了，上面的“保留”断言才有区分力
        assert messages[1]["trajectory"][0]["intent"] == "修改后的意图", (
            "被编辑轮的修改未写回"
        )

    def test_writeback_rejects_non_alternating_messages(self, editor_factory):
        """DI-6：messages 不满足严格交替时必须拒写，不得退化成全量重建。"""
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory)
        coords_path = os.path.join(gui_dir, f"gui_{gui_number}_coords.json")
        assert os.path.isfile(coords_path), "准备阶段未写出 coords，用例失去区分力"

        def mutate(data):
            # 开头插入一条 system 消息，使 messages[0] 不再是本轮的 user
            data["messages"].insert(0, {"role": "system", "content": "系统提示"})

        json_path = _tamper_final_json(gui_dir, gui_number, mutate)
        original_bytes = _read_bytes(json_path)
        original_coords_bytes = _read_bytes(coords_path)
        bak_path = f"{json_path}.bak"
        assert not os.path.isfile(bak_path)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=0)
        assert ed2.rounds, "插入 system 后轮次解析为空，用例失去区分力"

        ed2.intent_input.setText("不该被写回的意图")
        assert ed2.save_edited_round(True) is False, (
            "messages 结构不匹配时竟然写回成功了"
        )
        QTest.qWait(50)

        assert _read_bytes(json_path) == original_bytes, "拒写失败：原 JSON 已被改动"
        assert _read_bytes(coords_path) == original_coords_bytes, (
            "拒写失败：coords 已被改动"
        )
        assert not os.path.isfile(bak_path), "未发生写回却生成了 .bak"
        assert not _tmp_leftovers(gui_dir), (
            f"拒写路径残留临时文件：{_tmp_leftovers(gui_dir)}"
        )

    def test_empty_coords_does_not_overwrite_delivered_file(self, editor_factory):
        """DI-6：本轮导出 0 条坐标时，不得用空数组覆盖已交付 coords（B41）。"""
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory)
        coords_path = os.path.join(gui_dir, f"gui_{gui_number}_coords.json")
        assert os.path.isfile(coords_path), "准备阶段未写出 coords，用例失去区分力"
        original_coords_bytes = _read_bytes(coords_path)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=0)
        # iOS 的 coords 收集对每个步骤无条件 append，不因缺拉框而跳过：
        # 只有清空本轮步骤才会复现“导出 0 条坐标”
        assert ed2.steps_data, "编辑现场没有步骤"
        ed2.steps_data = []

        assert ed2.save_edited_round(True) is True, "编辑写回失败"
        QTest.qWait(50)

        assert _read_bytes(coords_path) == original_coords_bytes, (
            "0 条坐标时仍把已交付的 coords 文件覆盖了"
        )
        assert not _tmp_leftovers(gui_dir), (
            f"写回残留临时文件：{_tmp_leftovers(gui_dir)}"
        )


# ----------------------------------------------------------------------
# DI-13：编辑模式的轮次候选项必须能唯一区分每一轮（B3 / 计划 1.6）
# ----------------------------------------------------------------------

class TestDI13:
    """轮次候选项与下标解析：同指令的多轮不得被折叠成同一个选项。"""

    def test_choice_items_carry_round_number_and_step_count(self):
        """DI-13 回归：候选项同时带轮次序号与步数，指令完全相同也能区分。"""
        from main import build_round_choices, resolve_round_index

        same = "点击首页搜索框输入关键词后进入结果页并筛选价格从低到高排序"
        rounds = [
            {"instruction": same, "trajectory": [{"s": 1}]},
            {"instruction": same, "trajectory": [{"s": 1}]},
        ]
        items, index_by_item = build_round_choices(rounds)

        assert index_by_item is not None, f"候选项重复，无法唯一区分轮次：{items}"
        assert len(items) == 2 and len(set(items)) == 2
        assert items[0].startswith("第 1 轮") and items[1].startswith("第 2 轮")
        # 步数必须进摘要：只截指令时同指令同轮长会彻底撞车
        assert "1 步" in items[0] and "1 步" in items[1]
        assert resolve_round_index(index_by_item, items[0]) == 0
        assert resolve_round_index(index_by_item, items[1]) == 1

    def test_long_shared_prefix_rounds_are_distinguishable(self):
        """DI-13 回归：指令只在截断窗口之后才不同时，仍必须按各自下标定位。"""
        from main import build_round_choices, resolve_round_index

        head = "打开应用并登录账号进入首页" * 10
        rounds = [
            {"instruction": head + "甲", "trajectory": [{"s": 1}]},
            {"instruction": head + "乙", "trajectory": [{"s": 1}]},
        ]
        items, index_by_item = build_round_choices(rounds)

        # 截断使两轮摘要文本一致 ⇒ 区分力完全来自序号前缀，此处逐轮反查
        assert items[0].split("：", 1)[1] == items[1].split("：", 1)[1], (
            "用例前提已变：摘要不再被截断，反查断言失去区分力"
        )
        assert index_by_item is not None, "截断后摘要撞车，候选项无法区分"
        assert resolve_round_index(index_by_item, items[0]) == 0
        assert resolve_round_index(index_by_item, items[1]) == 1

    def test_unknown_selection_never_falls_back_to_first_round(self):
        """DI-13 回归：定不到下标时必须返回 None 让调用方中止，不得退回第 1 轮。"""
        from main import build_round_choices, resolve_round_index

        rounds = [
            {"instruction": "第一轮指令", "trajectory": [{"s": 1}]},
            {"instruction": "第二轮指令", "trajectory": [{"s": 1}]},
        ]
        items, index_by_item = build_round_choices(rounds)
        assert index_by_item is not None

        # 早前实现用 items.index(choice) 定位，选中项文本对不上就抛异常，
        # 外层兜底会把 round_index 静默留成 0，等于改错轮再写回已交付数据
        assert resolve_round_index(index_by_item, "不存在的候选项") is None
        assert resolve_round_index(index_by_item, None) is None
        assert resolve_round_index(None, items[0]) is None
        assert resolve_round_index({}, items[0]) is None


# ----------------------------------------------------------------------
# DI-11：answer 落轮后取消新轮，工作区必须回到空白起点（B28）
# ----------------------------------------------------------------------

def _answer_round_then_cancel(editor, dialogs, n_steps=2):
    """走 n_steps 步 + 1 步 answer 落轮 → 续轮对话框点「取消」。

    :return: 已落轮那一轮（含 answer 步自身）各步引用的截图名。

    机制：iOS 的 answer 分支先同步 _save_current_round_to_list（已消费 steps_data），
    再 singleShot(300) 弹 _start_new_round(from_answer=True)，故必须用
    confirm(wait_answer_round=True) 等定时器回调跑完。
    """
    walk_steps(editor, n_steps, action="click")
    # answer 步自身也带截图，confirm 后一并落轮，故轨迹比 walk_steps 多一步
    answer_shot = capture(editor)
    fill_step(editor, action="answer", intent="第一轮回答", text="第一轮回答")
    shots = [step["screenshot"] for step in editor.steps_data] + [answer_shot]

    dialogs.input_ok = False  # 续轮 QInputDialog 走取消分支
    confirm(editor, wait_answer_round=True)
    dialogs.input_ok = True
    return shots


class TestDI11:
    """answer 后取消新轮：只改状态文案不够，必须把界面清成空白起点。"""

    def test_cancel_new_round_clears_canvas_and_form(self, editor, dialogs):
        """DI-11 回归（B28）：取消新轮后画布/表单/测量态均不得残留上一轮内容。"""
        _answer_round_then_cancel(editor, dialogs, n_steps=2)

        assert len(editor.rounds) == 1, (
            f"answer 未落轮，用例前提不成立：{len(editor.rounds)}"
        )
        assert editor.steps_data == [], f"steps_data 未清空：{len(editor.steps_data)}"

        # B28 的核心现场：_save_current_round_to_list 只消费了数据层，
        # 画布上的截图、拉框、表单输入都停在上一轮；用户接着采集就接在陈旧界面上。
        assert editor.canvas.pixmap is None, (
            "取消新轮后画布仍挂着上一轮截图"
        )
        assert editor.canvas._saved_rect is None, "取消新轮后画布残留拉框"
        assert editor.canvas._current_rect is None, "取消新轮后画布残留进行中拉框"
        assert editor.intent_input.text() == "", (
            f"取消新轮后动作描述框残留：{editor.intent_input.text()!r}"
        )
        assert editor.text_input.text() == "", (
            f"取消新轮后文本输入框残留：{editor.text_input.text()!r}"
        )
        assert editor._current_vertices is None, "取消新轮后拉框顶点残留"
        assert editor.screenshot_cache is None, "取消新轮后截图缓存残留"
        assert editor._current_screenshot_filename is None, "取消新轮后当前文件名残留"
        assert editor.action_combo.currentIndex() == 0, (
            f"取消新轮后动作下拉框未回到默认项：{editor.action_combo.currentText()!r}"
        )
        assert editor.step_label.text() == "步骤: 0", (
            f"取消新轮后步骤标签未复位：{editor.step_label.text()!r}"
        )
        assert "已取消新任务" in editor.status_label.text(), (
            f"状态提示未回到可继续采集的口径：{editor.status_label.text()!r}"
        )

        assert_all(editor)

    def test_cancel_new_round_keeps_delivered_round_and_draft(self, editor, dialogs):
        """DI-11 边界回归：重置只清界面，已落轮轨迹、草稿与磁盘截图不得被牵连。"""
        shots = _answer_round_then_cancel(editor, dialogs, n_steps=2)

        assert len(editor.rounds) == 1
        trajectory = editor.rounds[0]["trajectory"]
        assert len(trajectory) == len(shots), (
            f"已交付轮次步数丢失：{len(trajectory)} != {len(shots)}"
        )
        blob = json.dumps(editor.rounds[0], ensure_ascii=False)
        for name in shots:
            assert name in blob, f"已交付轮次不再引用截图 {name}"
            assert os.path.isfile(os.path.join(gui_dir_of(editor), name)), (
                f"重置过程误删了已交付截图：{name}"
            )

        editor._write_draft_now()
        draft_path = os.path.join(gui_dir_of(editor),
                                  f"gui_{editor.gui_number}_draft.json")
        assert os.path.isfile(draft_path), "取消新轮后草稿文件缺失"
        with open(draft_path, "r", encoding="utf-8") as f:
            draft = json.load(f)
        assert draft["steps_data"] == [], (
            f"取消新轮后草稿仍留着上一轮步骤：{draft['steps_data']}"
        )
        assert len(draft["rounds"]) == 1, "草稿 rounds 未同步落盘"

        # 磁盘侧全套：已落轮引用完好 + 无孤儿/无越界产物
        assert_all(editor)

    def test_capture_after_cancel_starts_clean_second_round(self, editor, qapp,
                                                            dialogs):
        """DI-11 后果回归：取消新轮后继续采集应成为干净的下一轮。"""
        shots = _answer_round_then_cancel(editor, dialogs, n_steps=2)
        first_instruction = editor.rounds[0]["instruction"]

        capture(editor)
        assert editor.canvas.pixmap is not None, "取消后重新截图未上画布"
        fill_step(editor, action="click", intent="第二轮第1步")
        confirm(editor)

        assert len(editor.steps_data) == 1, (
            f"新一轮步数异常：{len(editor.steps_data)}"
        )
        new_shot = editor.steps_data[0]["screenshot"]
        assert new_shot not in shots, (
            f"新一轮复用了已交付截图（轮次折叠）：{new_shot}"
        )
        assert len(editor.rounds) == 1, (
            f"新一轮被误落轮：rounds={len(editor.rounds)}"
        )
        assert_all(editor)

        json_path = finish_task_final(editor, action="terminate")
        assert os.path.isfile(json_path), "最终 JSON 产出失败"
        with open(json_path, "r", encoding="utf-8") as f:
            final = json.load(f)
        user_msgs = [m for m in final["messages"] if m.get("role") == "user"]
        assert len(user_msgs) == 2, (
            f"取消新轮后的第二轮未独立落轮：messages 只含 {len(user_msgs)} 轮指令"
        )
        # 2.6（B14）归属断言：取消续轮会清空 task_instruction，第二轮是靠
        # 「弹窗补齐」拿到的新指令落轮的，绝不能继续沿用上一条已被消费掉的指令。
        assert user_msgs[0]["instruction"] == first_instruction, (
            f"第一轮指令被改写：{user_msgs[0]['instruction']!r}"
        )
        assert user_msgs[1]["instruction"] == dialogs.next_instruction, (
            f"第二轮指令不是补齐时输入的新指令：{user_msgs[1]['instruction']!r}"
        )
        assert user_msgs[1]["instruction"] != user_msgs[0]["instruction"], (
            "两轮共用同一条指令 —— 第二轮静默挂到了上一条指令上（B14）"
        )


# ----------------------------------------------------------------------
# DI-8：answer 的 300ms 切轮窗口内不得再启动截图（B2）
# ----------------------------------------------------------------------

def _answer_round_in_window(editor, dialogs, n_steps=2):
    """走 n_steps 步 + 1 步 answer 落轮 → 停在 300ms 切轮窗口内。

    与 DI-11 的 _answer_round_then_cancel 唯一区别是不等定时器跑完：必须停在
    「rounds 已落轮、_start_new_round 尚未进场」的竞态窗口里，否则门闩已清。
    input_ok=False 让切轮走取消分支 —— 窗口内一旦真起了截图，产物绝无轮次认领。
    """
    walk_steps(editor, n_steps, action="click")
    # answer 步自身也带截图（confirm_step 先检查是否已截图）
    capture(editor)
    fill_step(editor, action="answer", intent="第一轮回答", text="第一轮回答")

    dialogs.input_ok = False
    editor.confirm_step()
    QTest.qWait(50)

    assert len(editor.rounds) == 1, (
        f"answer 未落轮，用例前提不成立：rounds={len(editor.rounds)}"
    )
    assert editor.steps_data == [], (
        f"answer 后 steps_data 未清空：{len(editor.steps_data)}"
    )
    assert editor._round_transition_pending is True, (
        "answer 落轮后未升起切轮门闩：300ms 窗口内的截图会落在旧指令的轮次上（B2）"
    )


class TestDI8:
    """B2：answer 落轮后到 _start_new_round 进场之间有 300ms 窗口，
    期间 task_instruction 仍是旧指令、rounds 已消费上一轮，截图入口必须早退。"""

    def test_take_screenshot_inside_round_window_is_refused(self, editor, dialogs):
        """DI-8 回归（B2）：窗口内 take_screenshot 不得起摄，也不得落孤儿 PNG。"""
        _answer_round_in_window(editor, dialogs)
        gui_dir = gui_dir_of(editor)
        before = snapshot_listing(gui_dir)

        editor.take_screenshot()

        # take_screenshot 一旦被放行会同步把该标志置 True，是不依赖时序的即时信号
        assert editor._screenshot_in_progress is False, (
            "切轮窗口内 take_screenshot 被放行：截图会落在旧指令刚交付的轮次上（B2）"
        )
        assert editor._current_screenshot_filename is None, (
            "切轮窗口内截图已占用当前步文件名（B2）"
        )
        assert editor.status_label.text() == "轮次切换中，请稍候...", (
            f"窗口内截图未给出等待口径：{editor.status_label.text()!r}"
        )
        assert editor.steps_data == [], (
            f"切轮窗口内凭空多出了步骤：{len(editor.steps_data)}"
        )

        QTest.qWait(600)  # 让 300ms 切轮回调与迟到的 50ms 截图链路都跑完
        assert snapshot_listing(gui_dir) == before, (
            f"切轮窗口内的截图落成了无人引用的孤儿 PNG："
            f"{set(snapshot_listing(gui_dir)) - set(before)}（B2）"
        )
        assert editor.steps_data == [], (
            f"切轮窗口内的截图最终追加成了步骤：{len(editor.steps_data)}"
        )
        assert len(editor.rounds) == 1, (
            f"切轮窗口内多落了一轮：rounds={len(editor.rounds)}"
        )
        assert editor._round_transition_pending is False, (
            "切轮回调进场后门闩未释放，截图入口被永久堵死"
        )
        assert_all(editor)

    def test_capture_works_after_round_window(self, editor, dialogs):
        """DI-8 边界回归：门闩只堵 300ms 窗口，不能把后续截图永久卡死。"""
        _answer_round_in_window(editor, dialogs)

        QTest.qWait(400)  # 等切轮回调进场并释放门闩
        assert editor._round_transition_pending is False, (
            "切轮回调结束后门闩未复位，截图入口被永久堵死"
        )

        walk_steps(editor, 1, action="click")
        assert len(editor.steps_data) == 1, (
            f"窗口后新截图未落地：steps_data={len(editor.steps_data)}"
        )
        assert len(editor.rounds) == 1, (
            f"正常采集被误判为重复落轮：rounds={len(editor.rounds)}"
        )
        assert_all(editor)

    def test_second_round_after_window_uses_new_instruction(self, editor, dialogs):
        """DI-8 后果回归：窗口被拦住后两轮各自带自己的指令，不出现同指令重复落轮。"""
        _answer_round_in_window(editor, dialogs)
        first_instruction = editor.rounds[0]["instruction"]

        dialogs.input_ok = True  # 切轮回调接受新指令
        QTest.qWait(400)
        assert len(editor.rounds) == 1, (
            f"切轮阶段就多落了一轮：rounds={len(editor.rounds)}"
        )

        walk_steps(editor, 1, action="click")
        capture(editor)
        fill_step(editor, action="answer", intent="第二轮回答", text="第二轮回答")
        dialogs.input_ok = False  # 第 2 轮answer 后走取消分支，把定时器排空
        confirm(editor, wait_answer_round=True)

        assert len(editor.rounds) == 2, (
            f"第二轮未独立落轮：rounds={len(editor.rounds)}"
        )
        assert editor.rounds[1]["instruction"] == dialogs.next_instruction, (
            f"第二轮沿用了旧指令（轮次折叠/指令错乱）：{editor.rounds[1]['instruction']!r}"
        )
        assert editor.rounds[1]["instruction"] != first_instruction, (
            "两轮落在同一条旧指令上：切轮窗口内的重复采集没被拦住（B2）"
        )
        assert_all(editor)


# ----------------------------------------------------------------------
# DI-15：取消新轮后不得沿用旧指令，缺指令轮次必须拒绝落轮（B14）
# ----------------------------------------------------------------------

_FIRST_INSTRUCTION = "测试指令"


class TestDI15:
    """续轮取消置空指令 + 落轮前强校验非空 + 缺指令拒绝落轮并保持现场。

    iOS 的 closeEvent 只写草稿、不落轮，不存在「无人值守路径用空指令落轮」
    的入口，故 Windows/Android 的关闭路径静默拒绝用例本端不适用、未移植。
    """

    def test_cancel_new_round_clears_instruction(self, editor, dialogs):
        """DI-15 回归（B14）：续轮对话框取消后 task_instruction 必须置空。"""
        _answer_round_then_cancel(editor, dialogs, n_steps=2)

        # 上一轮已随 answer 落入 rounds 并被消费，继续留着旧指令，用户接着采集
        # 的整轮就会被静默挂到上一条指令上 —— 事后无从分辨哪段轨迹属于哪条指令。
        assert editor.task_instruction == "", (
            f"取消续轮后仍沿用已被消费的旧指令：{editor.task_instruction!r}"
        )
        # 置空只针对「当前轮」，已交付轮次里的指令不得被牵连改写
        assert editor.rounds[0]["instruction"] == _FIRST_INSTRUCTION, (
            f"清空当前轮指令时改写了已交付轮次：{editor.rounds[0]['instruction']!r}"
        )

    def test_empty_instruction_round_is_refused_and_keeps_steps(self, editor, dialogs):
        """DI-15 后果回归：补齐弹窗也取消 → 拒绝落轮，现场与产物都不能动。"""
        _answer_round_then_cancel(editor, dialogs, n_steps=2)

        capture(editor)
        fill_step(editor, action="click", intent="第二轮第1步")
        confirm(editor)
        shots_before = [step["screenshot"] for step in editor.steps_data]
        getText_before = sum(1 for c in dialogs.calls if c[0] == "getText")

        dialogs.input_ok = False  # 「补齐任务指令」弹窗也取消
        json_path = finish_task_final(editor, action="terminate")

        assert not os.path.isfile(json_path), (
            f"缺少任务指令却写出了交付文件（B14）：{json_path}"
        )
        assert len(editor.rounds) == 1, (
            f"空指令轮被静默落入 rounds：rounds={len(editor.rounds)}"
        )
        # 拒绝落轮必须保持现场：_finish_task 先把收尾步落表（_save_current_to_steps
        # 在守卫之前），故本轮应为「已采集步 + 收尾步」且原步逐项完好；
        # 若调用方照常清空 steps_data/升门闩，指令错乱就升级成整轮丢失。
        assert len(editor.steps_data) == len(shots_before) + 1, (
            f"拒绝落轮后本轮步数异常：{len(editor.steps_data)} vs {len(shots_before)}"
        )
        assert (
            [s["screenshot"] for s in editor.steps_data[:len(shots_before)]]
            == shots_before
        ), "拒绝落轮时本轮已采集步骤被清空或改写"
        assert sum(1 for c in dialogs.calls
                   if c[0] == "getText") == getText_before + 1, (
            "落轮被拒前未弹窗要求补齐本轮任务指令（计划 2.6 要求先补再落）"
        )
        assert "缺少任务指令" in editor.status_label.text(), (
            f"拒绝落轮后未给出可操作的状态提示：{editor.status_label.text()!r}"
        )
        gui_dir = gui_dir_of(editor)
        for name in shots_before:
            assert os.path.isfile(os.path.join(gui_dir, name)), (
                f"拒收过程误删了本轮截图：{name}"
            )
        # 已交付轮次的磁盘引用不受拒收影响。此处不调 assert_all：INV-8 要求侧栏条目
        # 与 steps_data 等长，而 _finish_task 早退（无论校验不通过还是本例的缺指令）
        # 都只把收尾步落表、未建侧栏条目 —— 界面同步缺口与指令归属无关，另案处理。
        assert_round_refs_on_disk(gui_dir, editor.rounds)

    def test_supplemented_instruction_lands_on_new_round(self, editor, dialogs):
        """DI-15 修复路径：补齐指令后本轮按新指令落轮，两轮指令互不相同。"""
        _answer_round_then_cancel(editor, dialogs, n_steps=2)
        walk_steps(editor, 1, action="click")

        dialogs.next_instruction = "补齐的第二轮指令"
        json_path = finish_task_final(editor, action="terminate")
        assert os.path.isfile(json_path), "补齐任务指令后最终 JSON 未产出"

        assert len(editor.rounds) == 2, f"补齐后第二轮未落轮：{len(editor.rounds)}"
        assert editor.rounds[1]["instruction"] == "补齐的第二轮指令", (
            f"第二轮落到了别的指令上：{editor.rounds[1]['instruction']!r}"
        )
        with open(json_path, "r", encoding="utf-8") as f:
            final = json.load(f)
        instructions = [m["instruction"] for m in final["messages"]
                        if m.get("role") == "user"]
        assert instructions == [_FIRST_INSTRUCTION, "补齐的第二轮指令"], (
            f"交付文件里的指令序列错乱：{instructions}"
        )
        # 交付成功会删草稿（INV-6 不再适用），只核对两轮引用在磁盘上完好
        assert_round_refs_on_disk(gui_dir_of(editor), editor.rounds)


# ----------------------------------------------------------------------
# DI-16：落轮必须存副本，本轮对步骤 action 的原地改写不得回灌已落轮数据（B42）
# ----------------------------------------------------------------------

class TestDI16:
    """rounds 与 steps_data 不得共享同一个 action dict（B42）。

    全仓核实现今没有「落轮之后再原地改写步骤 action」的产品链路，所以本缺陷是**潜伏**
    的别名缺陷；用例因此钉的是隔离不变量，而不是复现某条具体路径：先攥住 steps_data 里
    那个活 action dict（连同它嵌套的 coordinate 列表）的引用，走产品 answer 入口落轮，
    再原地改写这些引用 —— 已落轮的 rounds 项、coords 项与随后的落盘产物都必须保持
    落轮当时的样子。去掉落轮侧的 deepcopy，同一性断言会立刻失败（变异 Q 已验证）。
    """

    def test_landed_action_is_a_copy(self, editor, dialogs):
        """DI-16 回归（B42）：落轮存的是副本，原地改写步骤 action 不回灌 rounds。"""
        walk_steps(editor, 2, action="click")

        live_step = editor.steps_data[0]
        live_action = live_step["action_data"]
        live_coordinate = live_action["coordinate"]
        pristine_action = copy.deepcopy(live_action)
        pristine_vertices = list(live_step["vertices"])

        capture(editor)
        fill_step(editor, action="answer", intent="第一轮回答", text="第一轮回答")
        dialogs.input_ok = False  # 续轮 QInputDialog 走取消分支，只核对内存与草稿
        confirm(editor, wait_answer_round=True)
        dialogs.input_ok = True
        assert len(editor.rounds) == 1, (
            f"answer 后未落轮，用例前提不成立：{len(editor.rounds)}"
        )

        landed_action = editor.rounds[0]["trajectory"][0]["actions"][0]
        assert landed_action is not live_action, (
            "落轮把 steps_data 里的活 action 对象直接放进 rounds，"
            "rounds 与本轮数据共享同一个 dict（B42）"
        )
        assert landed_action["coordinate"] is not live_coordinate, (
            "action 落轮只做了浅拷贝，嵌套的 coordinate 列表仍与本轮共享（B42）"
        )

        # 原地改写探针：键值改写、新增键、动嵌套列表，模拟任何「已落轮之后仍在改
        # 本轮步骤 action」的路径；浅拷贝也挡不住后三项
        live_action["action"] = "__polluted__"
        live_action["text"] = "污染文本"
        live_coordinate[0] = 777777
        live_step["vertices"].append(999999)

        assert editor.rounds[0]["trajectory"][0]["actions"][0] == pristine_action, (
            f"对步骤 action 的原地改写回灌到了已落轮数据（B42）："
            f"{editor.rounds[0]['trajectory'][0]['actions'][0]}"
        )
        landed_coords = editor.rounds[0]["coords"][0]
        assert landed_coords["vertices"] == pristine_vertices, (
            f"coords 顶点被本轮的拉框改写串台（B42）：{landed_coords['vertices']}"
        )
        assert landed_coords["center"] == pristine_action["coordinate"], (
            f"coords 中心点被本轮的坐标改写串台（B42）：{landed_coords['center']}"
        )

        # 改写之后再落一次草稿：已落轮数据不得顺着 rounds 漏到盘上
        editor._write_draft_now()
        draft_path = os.path.join(gui_dir_of(editor),
                                  f"gui_{editor.gui_number}_draft.json")
        assert os.path.isfile(draft_path), "落轮后草稿文件缺失"
        with open(draft_path, "r", encoding="utf-8") as f:
            draft = json.load(f)
        draft_rounds = draft.get("rounds") or []
        assert len(draft_rounds) == 1, f"草稿轮次数异常：{len(draft_rounds)}"
        assert draft_rounds[0]["trajectory"][0]["actions"][0] == pristine_action, (
            f"草稿里的已落轮 action 被本轮的原地改写污染（B42）："
            f"{draft_rounds[0]['trajectory'][0]['actions'][0]}"
        )
        assert_all(editor)

    def test_in_place_action_edit_does_not_reach_delivered_json(self, editor, dialogs):
        """DI-16 后果回归：改写探针后继续第二轮并交付，首轮交付数据逐字段不变。"""
        gui_dir = gui_dir_of(editor)
        walk_steps(editor, 2, action="click")

        live_action = editor.steps_data[0]["action_data"]
        pristine_action = copy.deepcopy(live_action)

        capture(editor)
        fill_step(editor, action="answer", intent="第一轮回答", text="第一轮回答")
        dialogs.next_instruction = "补齐的第二轮指令"
        confirm(editor, wait_answer_round=True)

        assert len(editor.rounds) == 1, f"answer 后未落轮：{len(editor.rounds)}"
        assert editor.task_instruction == "补齐的第二轮指令", (
            f"续轮未切到新指令，第二轮会挂到第一条指令上：{editor.task_instruction!r}"
        )

        # 落轮之后原地改写本轮步骤的 action：早前 rounds 与 steps_data 共享对象，
        # 于是这种改写会顺着 rounds 一路写进交付文件，已交付数据被静默改掉
        live_action["action"] = "__polluted__"
        live_action["coordinate"][0] = 777777

        walk_steps(editor, 2, action="click")
        json_path = finish_task_final(editor, action="terminate")
        assert os.path.isfile(json_path), "第二轮收尾后最终 JSON 未产出"

        rounds = _load_rounds(gui_dir)
        assert len(rounds) == 2, f"交付文件轮次数异常：{len(rounds)}"
        assert rounds[0]["trajectory"][0]["actions"][0] == pristine_action, (
            f"已交付的首轮 action 被后续的原地改写污染（B42）："
            f"{rounds[0]['trajectory'][0]['actions'][0]}"
        )
        assert "__polluted__" not in json.dumps(rounds[0], ensure_ascii=False), (
            "污染探针泄漏进了交付 JSON 的首轮（B42）"
        )
        assert [r["instruction"] for r in rounds] == [
            _FIRST_INSTRUCTION, "补齐的第二轮指令"
        ], f"交付文件里的指令序列错乱：{[r['instruction'] for r in rounds]}"
        # 交付成功会删草稿（INV-6 不再适用），只核对两轮引用在磁盘上完好
        assert_round_refs_on_disk(gui_dir, editor.rounds)


# ----------------------------------------------------------------------
# DI-17：采集中回看历史步、确认后只前进一格，不得把用户传送末尾（B22）
# ----------------------------------------------------------------------

def _highlighted_indexes(editor):
    """侧栏蓝底高亮条目下标 = 侧栏认得的「当前正在编辑第几步」。"""
    return [i for i, item in enumerate(editor.sidebar.item_widgets)
            if "#e3f2fd" in item.styleSheet()]


class TestDI17:
    """confirm_step 之后游标只前进一格（B22，Android 同批移植）。

    计划 2.8 原写「默认保持原值」，勘察后否决：go_next 停在最后一步时是委托
    confirm_step 来进入末尾待截图空位的（见 go_next 的 else 分支），历史步确认若完全
    不推进，末步就再也进不了空位、无法续采。最终口径是「中间历史步 → 前进一格并完整
    回填现场；追加新步/确认末步 → 进入空位」，两条用例分头钉住这两个方向：
      test_1 中间步确认后不传送、表单/截图/高亮/草稿一致（还原「无条件推到末尾」即失败）
      test_2 从中间步确认后仍能一路走到空位并正常追加（改成「完全不推进」即失败）
    """

    def test_confirm_history_step_advances_one_not_to_end(self, editor, dialogs):
        """DI-17 回归（B22）：改完中间历史步确认后只前进一格，不传送末尾、不清表单。"""
        intents = ["第1步", "第2步", "第3步"]
        for intent in intents:
            capture(editor)
            fill_step(editor, action="click", intent=intent)
            confirm(editor)
        assert len(editor.steps_data) == 3, f"用例前提不成立：{len(editor.steps_data)} 步"
        original_shots = [s["screenshot"] for s in editor.steps_data]
        neighbours_before = copy.deepcopy([editor.steps_data[0], editor.steps_data[2]])

        # 回看中间第 2 步（下标 1），改完 intent 再确认
        editor.jump_to_step(1)
        assert editor.current_step == 1
        fill_step(editor, action="click", intent="改过的第2步")
        confirm(editor)

        # 改动原地落表：既没多落一步，也没挪动相邻步
        assert editor.steps_data[1]["intent"] == "改过的第2步"
        assert len(editor.steps_data) == 3, (
            f"确认历史步时 steps_data 被追加（B22）：{len(editor.steps_data)}"
        )
        assert copy.deepcopy(
            [editor.steps_data[0], editor.steps_data[2]]
        ) == neighbours_before, "确认中间步时挪动或覆盖了相邻步骤"

        # 核心：游标只前进一格、仍停在已有步上，而不是被推到 len(steps_data)
        assert editor.current_step == 2, (
            f"确认后游标被静默传送到末尾（B22）：current_step={editor.current_step}，"
            f"len(steps_data)={len(editor.steps_data)}"
        )
        # 现场完整回填：表单与截图指针都是第 3 步的，不必重新截图即可接着核对
        assert editor.intent_input.text() == intents[2], (
            f"确认后表单被清空或串步（B22）：{editor.intent_input.text()!r}"
        )
        assert editor._current_screenshot_filename == original_shots[2], (
            "确认后未把第 3 步的截图引回复现，等于强制用户重新截图（B22）"
        )
        assert _highlighted_indexes(editor) == [2], (
            f"侧栏高亮与游标不同步（B22）：{_highlighted_indexes(editor)}"
        )
        assert "已更新第 2 步" in editor.status_label.text(), (
            f"确认历史步后的状态提示未反映「已更新 + 可继续编辑」："
            f"{editor.status_label.text()}"
        )

        editor._write_draft_now()
        QTest.qWait(50)
        draft = DataManager.load_draft_from_dir(gui_dir_of(editor))
        assert draft is not None, "确认后草稿未落盘"
        draft_steps = draft.get("steps_data") or []
        assert [s.get("intent") for s in draft_steps] == [
            intents[0], "改过的第2步", intents[2]
        ], f"草稿里的步骤序列被打乱（B22）：{[s.get('intent') for s in draft_steps]}"
        assert draft.get("current_step_index") == 2, (
            f"草稿游标与内存不同步（B22）：{draft.get('current_step_index')}"
        )
        assert_all(editor)

    def test_confirm_from_history_step_still_reaches_empty_slot(self, editor, dialogs):
        """DI-17 反向回归：从中间步确认后仍能一路走到末尾空位并正常追加新步。

        钉住修复的另一个方向：若把「前进一格」做成「原地不动」，go_next 停在末步时
        靠 confirm_step 进入空位的链路就断了，用户再也无法续采（采集死锁）。
        """
        intents = ["第1步", "第2步", "第3步"]
        for intent in intents:
            capture(editor)
            fill_step(editor, action="click", intent=intent)
            confirm(editor)

        editor.jump_to_step(0)
        fill_step(editor, action="click", intent="改过的第1步")
        confirm(editor)
        assert editor.current_step == 1

        limit = len(editor.steps_data) + 2
        while editor.current_step < len(editor.steps_data) and limit > 0:
            editor.go_next()
            QTest.qWait(50)
            limit -= 1
        assert editor.current_step == len(editor.steps_data) == 3, (
            f"从历史步出发走不到末尾待截图空位（B22 反向）："
            f"current_step={editor.current_step}, len={len(editor.steps_data)}"
        )
        assert editor._current_screenshot_filename is None, (
            "末尾空位应为未截图的新步现场"
        )

        capture(editor)
        fill_step(editor, action="click", intent="第4步")
        confirm(editor)
        assert [s["intent"] for s in editor.steps_data] == [
            "改过的第1步", intents[1], intents[2], "第4步"
        ], "末尾追加的新步覆盖或插进了历史步（B22 反向）"
        assert editor.current_step == 4
        assert_all(editor)


# ----------------------------------------------------------------------
# DI-18：_finish_task 拒收早退前未同步侧栏
# ----------------------------------------------------------------------

class TestDI18:
    """DI-18：_finish_task 先把「已截图未填写」的当前步落表，再因缺项拒收 return。

    修复前的因果链：
    ① _save_current_to_steps 见 current_step == len(steps_data) 且已有截图 → append；
    ② 必填校验命中该新步 → _show_validation_fail_dialog 后直接 return，不重建侧栏；
    ③ 侧栏条目数落后于模型、缺填标记停在旧步骤集合上（INV-8 破坏），用户看不到
       刚被拦下的那一步，无法按清单跳转补填。
    修复：弹清单前 sidebar.rebuild_items()。
    """

    def test_reject_path_rebuilds_sidebar(self, editor, dialogs, monkeypatch):
        # 缺项清单为真模态框，offscreen 下会阻塞；与 Android 夹具同口径桩掉
        monkeypatch.setattr(annotation_editor.ValidationFailDialog, "exec_", lambda self: 0)

        for intent in ("第1步", "第2步"):
            capture(editor)
            fill_step(editor, action="click", intent=intent)
            confirm(editor)

        capture(editor)   # 第 3 步只截图、不填表 → 结束校验必然拒收
        editor._finish_task()
        QTest.qWait(100)

        assert len(editor.steps_data) == 3, (
            f"用例前提不成立：拒收前当前步未落表，steps_data={len(editor.steps_data)}"
        )
        assert not editor.rounds, "必填项缺失却被判定为已落轮"
        final_json = os.path.join(
            gui_dir_of(editor), f"gui_{editor.gui_number}.json"
        )
        assert not os.path.exists(final_json), f"校验拒收却仍写出了交付文件：{final_json}"
        assert_sidebar_consistency(editor)


# ----------------------------------------------------------------------
# DI-20：顶层 screen_size 被每张截图覆写（B23）
# ----------------------------------------------------------------------

def _png_size(path):
    image = QImage(path)
    assert not image.isNull(), f"截图文件无法加载：{path}"
    return image.width(), image.height()


class TestDI20:
    """DI-20 = B23：顶层 screen_info["screen_size"] 被每张截图无条件覆写。

    采集会话中设备分辨率抖动（重连、旋转、换设备）时，第 2 张起的截图尺寸会覆盖
    整轮交付尺寸；而本轮首张截图才是与各步轨迹对应的尺寸口径。
    修复：只由「本轮首张追加截图」定版，重截/中间插入/历史步覆盖不得覆写。
    本例把首张截图做成 400x900（与夹具默认 390x844 不同），以区分「真的定版过」
    与「从未改写过」。
    """

    def test_mid_session_resolution_change_keeps_screen_size(
        self, editor, dialogs, monkeypatch
    ):
        monkeypatch.setattr(fakes, "DEFAULT_WIDTH", 400)
        monkeypatch.setattr(fakes, "DEFAULT_HEIGHT", 900)
        capture(editor)
        fill_step(editor, action="click", intent="第1步")
        confirm(editor)

        assert editor.screen_info["screen_size"] == [400, 900], (
            f"用例前提不成立：本轮首张截图未按实际尺寸定版："
            f"{editor.screen_info['screen_size']}"
        )

        # 模拟会话中设备分辨率抖动：第 2 张截图变成 500x1000
        monkeypatch.setattr(fakes, "DEFAULT_WIDTH", 500)
        monkeypatch.setattr(fakes, "DEFAULT_HEIGHT", 1000)
        capture(editor)

        second = os.path.join(editor.gui_dir, editor._current_screenshot_filename)
        assert _png_size(second) == (500, 1000), (
            f"用例前提不成立：第 2 张截图未按新分辨率落盘：{_png_size(second)}"
        )
        assert editor.screen_info["screen_size"] == [400, 900], (
            f"中途一张截图覆写了整轮交付尺寸（B23）：{editor.screen_info['screen_size']}"
        )


# ----------------------------------------------------------------------
# DI-21：唯一名截图临时文件逐张累积泄漏（B44，仅 iOS）
# ----------------------------------------------------------------------

class TestDI21:
    """DI-21 = B44：每次截图用唯一临时名（防 QPixmap 缓存串图）却从不回收。

    临时文件在下一次截图后即失去所有引用，长会话会在临时目录逐张净增。
    修复：在下一次截图尾部回收**上一张**临时文件；本次临时文件仍被
    screenshot_cache 引用（swipe/scroll 测量入口依赖），不得提前删除。
    故本例同时钉住两个方向，防止修复做成「成功后立即删本次临时文件」。
    """

    def test_previous_tmp_capture_is_recycled(self, editor, dialogs):
        capture(editor)
        first_tmp = editor._last_capture_tmp_path
        assert first_tmp and os.path.isfile(first_tmp), (
            f"用例前提不成立：首次截图未留下临时文件：{first_tmp}"
        )

        capture(editor)
        second_tmp = editor._last_capture_tmp_path
        assert second_tmp and second_tmp != first_tmp, (
            f"用例前提不成立：临时名未逐张唯一：{first_tmp} -> {second_tmp}"
        )

        assert not os.path.isfile(first_tmp), (
            f"上一张截图的临时文件未被回收（B44）：{first_tmp} 仍在临时目录，"
            f"长会话会逐张累积泄漏"
        )
        assert os.path.isfile(second_tmp), (
            f"本次截图的临时文件被提前删除（B44 反向）：{second_tmp}，"
            f"swipe/scroll 测量入口依赖 screenshot_cache 指向该文件"
        )
        assert editor.screenshot_cache == second_tmp, (
            f"截图缓存未指向本次临时文件：{editor.screenshot_cache}"
        )


# ----------------------------------------------------------------------
# DI-9：撤销清空全部步骤后必须删掉磁盘残留草稿（B37）
# ----------------------------------------------------------------------

class TestDI9:
    """DI-9 = B37：空现场只 return → 已删步骤下次续采整批复活。"""

    def test_undo_to_empty_removes_draft(self, editor, dialogs):
        walk_steps(editor, 2)
        flush_draft(editor)
        gui_dir = gui_dir_of(editor)
        draft_path = os.path.join(
            gui_dir, f"gui_{editor.gui_number}_draft.json"
        )
        assert os.path.isfile(draft_path), (
            f"用例前提不成立：走两步后草稿未落盘：{draft_path}"
        )

        # 撤销走真实 undo_last_step（弹确认框后委托 delete_current_step）；
        # 走步结束后 current_step 停在末尾空位，须先跳回最后一个已落表步
        while editor.steps_data:
            editor.jump_to_step(len(editor.steps_data) - 1)
            before = len(editor.steps_data)
            editor.undo_last_step()
            QTest.qWait(0)
            assert len(editor.steps_data) == before - 1, (
                f"用例前提不成立：撤销未删除步骤（{before} -> "
                f"{len(editor.steps_data)}）"
            )
        assert editor.rounds == [], "用例前提不成立：撤销过程意外落了轮"

        flush_draft(editor)

        assert not os.path.isfile(draft_path), (
            f"撤销清空后残留草稿仍在（B37）：{draft_path}，"
            f"下次续采 load_from_draft 会把已删步骤整批复活"
        )
        assert DataManager.load_draft_from_dir(gui_dir) is None, (
            "任务目录内仍能读到草稿，续采列表仍会把该目录标成可续采"
        )


# ----------------------------------------------------------------------
# DI-27：交付 JSON 写盘失败绝不弹「任务完成」（B31）
# ----------------------------------------------------------------------

class TestDI27:
    """DI-27 = B31：写盘失败后谎报「已保存」= 用户以为已交付、实际只剩草稿。"""

    def test_write_failure_does_not_claim_success(self, editor, dialogs,
                                                  monkeypatch):
        walk_steps(editor, 2)
        gui_dir = gui_dir_of(editor)
        json_path = os.path.join(gui_dir, f"gui_{editor.gui_number}.json")
        draft_path = os.path.join(
            gui_dir, f"gui_{editor.gui_number}_draft.json"
        )

        # 模拟写盘失败（磁盘满/权限/占用都以 None 为返回口径）
        monkeypatch.setattr(
            editor.data_manager, "save_json_data", lambda *a, **k: None
        )
        dialogs.calls.clear()

        finish_task(editor)

        assert not any(
            call[0] == "question" and call[1] == "任务完成"
            for call in dialogs.calls
        ), (
            f"交付 JSON 未写成却弹了「任务完成」（B31）：{dialogs.calls}"
        )
        assert not os.path.isfile(json_path), (
            f"save_json_data 已返回 None，目录里却出现了交付件：{json_path}"
        )
        # 失败即中止：草稿与定时器原样保留，下次开屏仍可续采
        assert os.path.isfile(draft_path), (
            f"写盘失败时把续采草稿一并弄丢了（B31）：{draft_path}"
        )
        assert editor._draft_discarded is False, "写盘失败却把草稿标记成已丢弃"
        assert DataManager.load_draft_from_dir(gui_dir) is not None, (
            "磁盘草稿读不出来，该任务已从续采列表静默消失"
        )
