# -*- coding: utf-8 -*-
"""数据完整性缺陷回归测试组（DI 系列，Android 端）。

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
                  （修复：Android get_next_screenshot_number 由「最小未占用序号」改为
                   「max(已有序号)+1」，与 Windows/iOS 对齐——删图/撤销留下的空洞不再被
                   后续任意新截图复用，文件名序号与 step 顺序不再彻底脱钩（B38）。
                   采用计划 3.1 的退化方案：允许空洞、不改写已落轮 rounds 的截图引用；
                   3.2 口径：插入步仍取全局 max+1 却落在中间（B10 倒挂属可接受现实），
                   INV-11 只钉「全局唯一 + steps_data 内无重复 + 引用文件存在且命名合规」，
                   「顺序可追溯」的责任交给 step 字段。iOS/Windows 本就是 max+1，无 B38；
                   iOS 的「空洞永不复用」已由 test_rounds_draft 的 D-8 用例钉住，不重复建例）
    DI-8  = B2    singleShot(300) 竞态窗口内重复落轮
    DI-9  = B37   iOS 空现场不删残留草稿 → 续采复活已删步骤
                  （**本端已具备**：_write_draft_now 的空现场分支一直是 delete_draft
                   （annotation_editor.py:2901-2904），iOS 本轮向本端口径对齐；
                   Windows 同分支落空草稿（DT-1），两端仅登记）
    DI-10 = B50   save_screenshot(filename=) 无校验 → 路径穿越写出 gui_dir
    DI-11 = B1/B28 answer 后取消新轮不重置工作区
                  （计划 6.2 曾把该场景也记作 DI-3，与 B30 冲突，此处改判 DI-11）
    DI-12 = 计划 1.4 最终 JSON 直接 open(w) 覆盖写、无备份
                  （无对应 Bxx：写盘中途中断会留下半截/空文件，已交付数据不可恢复）
    DI-13 = B3    编辑模式轮次选择摘要撞车 → 改错轮并写回（计划 1.6）
    DI-14 = B15   Windows 摘页只 removeWidget/setParent(None) → 步骤页变游离
                  顶层窗口泄漏（**仅 Windows**：Android 无 QStackedWidget 步骤页模型，
                  本端不适用，仅登记编号以保持三端映射表同步）
    DI-15 = B14   三端 续轮指令取消后沿用旧 instruction → 新一轮轨迹静默挂到
                  上一条已被消费的指令上（取消即置空 + 落轮前强校验非空，
                  缺指令先弹窗补齐、补齐失败则拒绝落轮并保持现场）
                  （Android 的 closeEvent 也会落轮，其安全网传 prompt_instruction=False
                   走静默拒绝，故「无人值守不得弹模态框」子场景本端适用）
    DI-16 = B42   落轮时把 steps_data 里的 action 活对象直接放进 rounds → rounds 与
                  本轮数据共享同一个 dict，任何对步骤 action 的原地改写（含嵌套的
                  coordinate 列表）都会回写到已落轮、甚至已交付的轮次上
                  （修复：落轮存 copy.deepcopy 副本；coords 侧无需再包，
                   _build_coords_entry 对 vertices 已做 list() 复制且只读 action_data）
                  （Windows 落轮侧已对 editor.get_data() 做 deepcopy（DT-4），
                   本缺陷仅 iOS / Android 适用）
    DI-17 = B22   采集中回看历史步、改完确认后 current_step 被无条件推到
                  len(steps_data) → 用户被静默传送到末尾、正在核对的表单被清空
                  （修复：确认后只前进一格——中间历史步落到下一已有步并完整回填
                   现场，仅追加新步/确认末步才进入末尾待截图空位；不采用「原地
                   不动」，因为 go_next 停在末步时靠 confirm_step 进入空位）
                  （iOS 同形带病，同批修复；Windows 无 confirm_step 传送语义，本端不适用）
    DI-18 = _finish_task 必填校验拒收分支早退前不重建侧栏 → 条目数落后于刚落表的
                  当前步、缺填标记停在旧步骤集合上（INV-8 破坏）
                  （修复：弹缺填清单前先 sidebar.rebuild_items()；
                   Windows 拒收分支已重算缺项并刷新条目/看板，本端已具备等价保护）
    DI-19 = B24   live 步（草稿恢复回来的当前步、结束前刚 append 的当前步）豁免截图
                  磁盘存在性校验 → 交付 JSON 引用不存在的 PNG
                  （修复：取消 validate_step_at 的 is_live 豁免；实时截图一律先落盘
                   成功再置三指针，故正常采集中不会误判）
    DI-20 = B23   每张截图无条件覆写顶层 screen_info["screen_size"] → 会话中一次
                  分辨率抖动改写整轮交付尺寸
                  （修复：只由「本轮首张追加截图」定版，重截/中间插入/历史步覆盖不得
                   覆写，蒙版映射用的 _phone_w/_phone_h 仍逐张跟随；
                   Windows 采集分支本就有同形守卫，本缺陷仅 Android / iOS 适用）
    DI-21 = B44   截图临时文件逐张累积泄漏
                  （仅 iOS：其临时名带唯一后缀；Android 用固定临时名、逐张覆盖不累积，
                   本端不适用，仅登记以保持三端映射表同步）
    DI-22 = B49   _build_coords_entry 用 action_data["action"] 直接下标 → 磁盘脏数据
                  （缺 action 键 / actions 为空）抛 KeyError 并中断整轮编辑写回，
                  用户真正改好的那一步也静默丢失（一步脏数据毁掉一整轮）
                  （修复：isinstance 守卫 + .get("action", "")，与 iOS 安全写法对齐；
                   Windows 的 action 取自页面下拉框 currentText 后经
                   action_type_mapping.get，不对磁盘数据直接下标，本缺陷仅本端适用）
    DI-23 = B12   Windows get_data 两处坐标污染：无坐标语义豁免名单缺
                  answer_terminate（回答动作交付无意义的 coordinate）+ 裸 except 把
                  解析不了的坐标静默伪造成 [0,0] 写进交付数据
                  （**本端不适用**：Android 坐标条目由 _build_coords_entry 经
                   _valid_coord_pair/_valid_vertices 守卫产出，解析不了就不写键，
                   不存在伪造 [0,0] 的路径；仅登记以保持三端映射表同步）
    DI-24 = B4/B18 + B35   交付的扁平 coords 条目不带 round → 轮内 step 下标每轮都从 0
                  起重编，(step, action) 在多轮间重复，读取只能靠「step 变小则切段」
                  猜测归属；只要有一轮一个坐标步都没有、或多轮 step 同签名，就整段
                  错位把已交付的顶点配到别的轮次上（编辑那一轮时拿到别人的拉框）
                  （修复 4.2/B4-B18：只在序列化边界 _save_all_rounds_to_file 与
                   save_edited_round 的写盘副本上注入 round，rounds[r]["coords"]
                   保持不带 round；对齐 iOS 基准口径）
                  （修复 4.3/B35：读侧只要有条目带可用 round 就逐条目按 round 归组，
                   缺失/越界的并入最后一轮；全无 round 且段数≠轮数时逐段选「未占用
                   且轨迹签名匹配」的轮次 + 段内逐条目归入，对不上签名的仍并入
                   最后一轮、绝不丢弃）
    DI-25 = B9    Windows 中途关窗走「保存全部数据」→ 绕过必填校验产出交付 JSON，
                  同一目录既「已完成」又「可续采」
                  （**本端不适用**：Android closeEvent 的非编辑分支只落轮 + 写草稿，
                   :3727-3728 明确注释「中途关闭只写草稿，不写最终 JSON，不删除
                   草稿」，交付件 + 删草稿只在 _finish_task 里成对发生
                   （:3586-3590），本端没有关窗落交付的入口；仅登记以保持三端
                   映射表同步）
    DI-26 = B7+B8 Windows 新任务重置把空草稿写进刚交付的目录（已完成任务重回续采
                  列表）/ 新现场继承上一批数据的「已落盘」标志而跳过草稿落盘
                  （**本端不适用**：Android _start_new_task 先清空现场、后换
                   gui_number（:3686-3701），且注释明示「新 gui 编号暂不写空草稿」
                   （:3702），重置序列不会向刚交付的目录回写草稿；「已落盘」标志
                   _task_completed 在 Yes→新任务分支被显式复位（:3466），closeEvent
                   仅在它为 True 时跳过草稿（:3731-3733），不存在新现场继承旧标志
                   而跳过落盘的路径）
    DI-27 = B31   交付 JSON 写盘失败仍弹「任务完成」并清场 → 用户以为数据已交付，
                  实际只剩草稿（甚至草稿也没了），且无人知晓
                  （**本端修复**，计划 5.7：_save_all_rounds_to_file 返回布尔，
                   _finish_task 失败即 critical 并中止，草稿与定时器原样保留
                   （:3442-3456）；iOS 同批修复，Windows 交付分支已按「filepath
                    非空才删草稿、否则 critical」具备等价保护）
    DI-28 = B45   删步/撤销不退出 scroll 长滑测量态 → _scroll_measuring 残留为 True，
                  后续截图被当作测量补充图塞进 _scroll_extra_screenshots 而不落进
                  步骤，这些临时 PNG 再无人回收，成为孤儿文件
                  （**本端已具备**：delete_current_step 尾部成对取消 swipe+scroll
                   （:2374-2375），其余 6 处状态切换分支同样成对调用；iOS 勘察后
                   发现其删步必经 _clear_inputs（已自带成对取消），显式取消行不可
                   单独观测 → 写用例即是不可变异的假绿，两端均不建例，仅登记以
                   保持三端映射表同步）

只依赖 conftest 夹具与 helpers/invariants/fakes。
运行（在 安卓端 目录）::

    python -m pytest tests/test_data_integrity.py -q
"""

import copy
import json
import os
import shutil

from PyQt5.QtGui import QCloseEvent, QPixmap

import annotation_editor
from data_manager import DataManager
from fakes import FakeAndroidScreenCapture
from helpers import (
    capture_and_wait,
    confirm_n_steps,
    distinct_capture_seed,
    drain_sidebar_thumbs,
    fill_valid_step,
    finish_task,
    flush_events,
    gui_dir_of,
    gui_number_from_dir,
    open_edit_mode,
    walk_rounds,
)
from invariants import (
    assert_all,
    assert_no_files_outside,
    assert_overwrite_in_place,
    assert_round_refs_on_disk,
    assert_screenshot_order,
    assert_sidebar,
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

    Android 的最终 JSON **不含 rounds 键**：与 iOS 同构，把每一轮拆成相邻的两条
    messages（role=user 携 instruction、role=assistant 携 trajectory），故此处按
    配对还原，供「他轮引用必须完好」类断言使用。
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


def _round_refs(round_data):
    """取一轮 trajectory 里的截图文件名（按业务顺序）。

    同时适用于内存里的 editor.rounds 项与 _load_rounds 还原出的项。
    """
    return [
        (t.get("observation") or {}).get("screenshot")
        for t in (round_data.get("trajectory") or [])
    ]


# editor_factory 默认指令 / DI-15 及各处「补齐指令」应答所用的新指令
_FIRST_INSTRUCTION = "测试任务指令"
_SECOND_INSTRUCTION = "补齐的第二轮指令"


def _cancelled_at_boundary(editor_factory, modal):
    """走满一轮 → answer 落轮 → 续轮对话框取消，返回已过取消分支的编辑器。

    与 TestDI11._cancelled 同一现场口径：轮次边界上 300ms 后续轮对话框由
    modal.input_ok=False 走取消分支，此时 task_instruction 应已被置空（B14）。
    """
    ed = _round_boundary_scene(editor_factory, modal)
    flush_events(400)
    return ed


def _round_boundary_scene(editor_factory, modal):
    """走满一轮并停在「刚 answer 落轮、新轮对话框尚未弹出」的轮次边界态。

    answer 分支同步落轮后 300ms 才弹 _start_new_round(from_answer=True)，
    这个窗口内 _current_round_saved 仍为 True —— 正是 B20a 写坏草稿的时刻，
    故此处只推进 50ms，把写草稿的时机交给用例控制（崩溃/断电后续采
    读到的就是这一份）。稍后弹出的对话框由 modal.input_ok=False 走取消分支。

    DI-1（B20a）与 DI-2（B19）都从这个边界现场起步。
    """
    modal.input_ok = False
    ed = editor_factory()
    confirm_n_steps(ed, 2, action="click")
    capture_and_wait(ed)
    fill_valid_step(ed, action="answer", text="第一轮回答")
    ed.confirm_step()
    flush_events(50)
    assert len(ed.rounds) == 1, f"answer 后未落轮：rounds={len(ed.rounds)}"
    assert len(_round_refs(ed.rounds[0])) == 3, "第 1 轮应为 2 步 + 1 回答步"
    assert ed._current_round_saved is True, "answer 落轮后轮次标志未置位"
    return ed


def _round_boundary_draft(editor_factory, modal):
    """把轮次边界态落成草稿，返回 (已落轮的编辑器, 草稿, 第 1 轮截图引用)。

    续采用例靠这个现场还原“崩溃在轮次切换等待输入时”的磁盘状态。
    """
    ed = _round_boundary_scene(editor_factory, modal)
    round1_refs = _round_refs(ed.rounds[0])
    ed._write_draft_now()
    flush_events()
    draft = ed.data_manager.load_draft(ed.gui_number)
    assert draft is not None, "轮次边界未落下草稿"
    return ed, draft, round1_refs


def _prepare_completed_task(editor_factory, modal):
    """单轮已交付任务：2 步 + answer_terminate 收尾 → 3 张截图。

    :return: (gui_dir, gui_number, rounds)
    """
    ed = editor_factory()
    gui_dir = gui_dir_of(ed)
    gui_number = gui_number_from_dir(gui_dir)

    confirm_n_steps(ed, 2, action="click")
    finish_task(ed, modal)
    json_path = os.path.join(gui_dir, f"gui_{gui_number}.json")
    assert os.path.isfile(json_path), f"收尾后未写出最终 JSON：{json_path}"
    assert len(_pngs(gui_dir)) == 3, (
        f"期望 3 张截图（2 步 + 收尾步），实际 {_pngs(gui_dir)}"
    )
    return gui_dir, gui_number, _load_rounds(gui_dir)


def _prepare_two_round_task(editor_factory, modal):
    """双轮已交付任务：每轮 2 步 + 回答/收尾步 → 共 6 张截图、2 轮。

    两轮的截图序号全局递增、互不重叠，是「删步不得误删他轮」用例的前提。
    :return: (gui_dir, gui_number, rounds)
    """
    ed = editor_factory()
    gui_dir = gui_dir_of(ed)

    json_path = walk_rounds(
        ed,
        [(2, "第一轮指令"), (2, "第二轮指令")],
        finish_action="answer_terminate",
        modal=modal,
    )
    assert os.path.isfile(json_path), f"收尾后未写出最终 JSON：{json_path}"

    rounds = _load_rounds(gui_dir)
    assert len(rounds) == 2, f"期望 2 轮，实际 {len(rounds)}"
    assert len(_pngs(gui_dir)) == 6, (
        f"期望 6 张截图（每轮 3 张），实际 {_pngs(gui_dir)}"
    )
    gui_number = gui_number_from_dir(gui_dir)
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

    def test_recapture_overwrites_in_place(self, editor_factory, modal):
        """DI-3：编辑模式重截图 = 原地覆盖同名文件。

        放开守卫后这是主路径。必须同时满足三条，缺一即为数据破坏：
        ① 文件名不变（否则已交付 JSON 的引用会指向不存在的文件）；
        ② 内容确已改写（否则用户以为重截成功、实际没生效）；
        ③ 不新增文件、不留 .tmp、不产生草稿（编辑模式重截图不写 draft）。
        """
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory, modal)
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

        got = capture_and_wait(ed2)

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
        assert not ed2._screenshot_in_progress, "重截图结束后截图锁未复位"

    def test_delete_step_only_affects_edited_round(self, editor_factory, modal):
        """DI-3：编辑模式删步只回收本轮截图，其他已落轮引用必须全在盘上。"""
        gui_dir, gui_number, rounds = _prepare_two_round_task(editor_factory, modal)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=1)
        steps_before = len(ed2.steps_data)
        assert steps_before == 3, f"第 2 轮步骤数异常：{steps_before}"

        # 进入编辑现场后 current_step==0，delete_current_step 删的是 steps_data[0]
        assert ed2.current_step == 0, f"编辑现场 current_step 非 0：{ed2.current_step}"
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
        flush_events(150)

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

    def test_undo_step_in_edit_mode_is_bounded(self, editor_factory, modal):
        """DI-3：编辑模式撤销删除末步截图，且不越界、不误删他轮。

        两端撤销语义**不同**，不可互抄：iOS undo_last_step 委托
        delete_current_step，删的是 current_step；Android undo_step 才是真的
        steps_data.pop() 弹**末步**。故此处待删名取 steps_data[-1]。
        """
        gui_dir, gui_number, rounds = _prepare_two_round_task(editor_factory, modal)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=1)
        steps_before = len(ed2.steps_data)
        assert steps_before == 3, f"第 2 轮步骤数异常：{steps_before}"
        target_name = ed2.steps_data[-1]["screenshot"]

        before = set(_pngs(gui_dir))
        ed2.undo_step()
        flush_events(150)

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

    def test_guard_considers_landed_rounds(self, editor_factory, modal):
        """DI-4 回归：steps_data 已不含引用、但 rounds 仍引用时，绝不能删盘。

        这正是 B16/B17 的现场：answer 落轮后 steps_data 被清空，或编辑模式下
        steps_data 只装被编辑的那一轮。旧实现只遍历 steps_data，会把已交付、
        且最终 JSON 仍在引用的 PNG 删掉，无备份、不可恢复。
        """
        gui_dir, gui_number, rounds = _prepare_two_round_task(editor_factory, modal)

        ed2 = editor_factory(auto_init=False)
        # 编辑第 2 轮，使第 1 轮成为「未被 steps_data 覆盖的已落轮」
        open_edit_mode(ed2, gui_dir, round_index=1)

        landed = rounds[0]["trajectory"][0]["observation"]["screenshot"]
        target = os.path.join(gui_dir, landed)
        assert os.path.isfile(target), f"前置条件不成立：{landed} 不在盘上"

        ed2.steps_data = []
        ed2._current_screenshot_filename = None
        ed2._current_screenshot_filepath = None
        ed2._remove_screenshot_if_unreferenced(target)

        assert os.path.isfile(target), (
            f"已落轮仍引用的截图被删除：{landed}（B16/B17）"
        )
        assert_round_refs_on_disk(gui_dir, rounds)

    def test_guard_still_recycles_true_orphans(self, editor_factory, modal):
        """正向对照：确实无人引用的文件仍要回收，否则可达集过宽 → 孤儿堆积。"""
        gui_dir, gui_number, rounds = _prepare_two_round_task(editor_factory, modal)

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
        ed2._remove_screenshot_if_unreferenced(orphan)

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
        src = os.path.join(gui_dir, capture_and_wait(ed))
        assert os.path.isfile(src), "前置条件不成立：源截图不存在"

        parent = os.path.dirname(gui_dir)
        grandparent = os.path.dirname(parent)
        parent_before = snapshot_listing(parent)
        grandparent_before = snapshot_listing(grandparent)
        inside_before = snapshot_listing(gui_dir)

        for evil in self.ILLEGAL:
            got = ed.data_manager.save_screenshot(
                gui_number, ed.app_name, src, filename=evil
            )
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

        # 走两步得到两个不同文件（同步骤重截才是原地覆盖，走步才产生新序号）
        confirm_n_steps(ed, 2, action="click")
        name1 = ed.steps_data[0]["screenshot"]
        name2 = ed.steps_data[1]["screenshot"]
        assert name1 != name2, f"两步截图同名，无法做覆盖对照：{name1}"

        src = os.path.join(gui_dir, name2)
        before = snapshot_dir(gui_dir)
        assert before[name1] != before[name2], "两张源图字节相同，对照失效"

        got = ed.data_manager.save_screenshot(
            gui_number, ed.app_name, src, filename=name1
        )
        assert got == name1, f"合法覆盖被拒：{got!r}"
        assert_overwrite_in_place(gui_dir, before, name1)
        assert snapshot_dir(gui_dir)[name1] == before[name2], (
            "覆盖后的内容应逐字节等于源文件"
        )
        assert not _tmp_leftovers(gui_dir), (
            f"原子覆盖残留临时文件：{_tmp_leftovers(gui_dir)}"
        )

    def test_edit_mode_recapture_with_tampered_name_is_contained(
        self, editor_factory, modal
    ):
        """端到端：编辑现场文件名被篡改成穿越路径时，重截图不得写出 gui_dir。"""
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory, modal)
        parent = os.path.dirname(gui_dir)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=0)

        parent_before = snapshot_listing(parent)
        inside_before = snapshot_listing(gui_dir)

        ed2._current_screenshot_filename = "..\\..\\evil.png"
        ed2._current_screenshot_filepath = os.path.join(gui_dir, "..\\..\\evil.png")
        capture_and_wait(ed2)

        assert "失败" in ed2.status_label.text(), (
            f"篡改文件名后重截图应明确报失败，状态栏：{ed2.status_label.text()!r}"
        )
        assert not ed2._screenshot_in_progress, "拒绝落盘后截图锁未复位"
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
            "platform": "android",
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

    def test_edit_writeback_keeps_bak_of_original(self, editor_factory, modal):
        """DI-12：编辑写回前必须留下原 JSON 的 .bak，写回后不留 .tmp。"""
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory, modal)
        json_path = os.path.join(gui_dir, f"gui_{gui_number}.json")
        bak_path = f"{json_path}.bak"
        with open(json_path, "rb") as f:
            original_bytes = f.read()
        assert not os.path.isfile(bak_path), "准备阶段不该产生 .bak"

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=0)
        assert ed2.save_edited_round(True) is True, "编辑写回失败"
        flush_events(50)

        assert os.path.isfile(bak_path), "编辑写回未生成 .bak 备份"
        with open(bak_path, "rb") as f:
            assert f.read() == original_bytes, (
                ".bak 内容不等于写回前的原 JSON（备份时机错了）"
            )
        assert not _tmp_leftovers(gui_dir), (
            f"写回残留临时文件：{_tmp_leftovers(gui_dir)}"
        )

    def test_bak_is_overwritten_not_accumulated(self, editor_factory, modal):
        """DI-12：连续写回只保留最新一份 .bak（覆盖式，不累积历史副本）。"""
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory, modal)
        json_path = os.path.join(gui_dir, f"gui_{gui_number}.json")
        bak_path = f"{json_path}.bak"

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=0)
        assert ed2.save_edited_round(True) is True
        with open(json_path, "rb") as f:
            after_first = f.read()

        assert ed2.save_edited_round(True) is True
        flush_events(50)

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

    def test_writeback_keeps_extra_fields_and_orphan_message(
        self, editor_factory, modal
    ):
        """DI-6：messages 里的额外字段与非配对消息必须原样保留（B40）。"""
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory, modal)

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
        flush_events(50)

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

    def test_writeback_rejects_non_alternating_messages(self, editor_factory, modal):
        """DI-6：messages 不满足严格交替时必须拒写，不得退化成全量重建。"""
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory, modal)
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
        flush_events(50)

        assert _read_bytes(json_path) == original_bytes, "拒写失败：原 JSON 已被改动"
        assert _read_bytes(coords_path) == original_coords_bytes, (
            "拒写失败：coords 已被改动"
        )
        assert not os.path.isfile(bak_path), "未发生写回却生成了 .bak"
        assert not _tmp_leftovers(gui_dir), (
            f"拒写路径残留临时文件：{_tmp_leftovers(gui_dir)}"
        )

    def test_empty_coords_does_not_overwrite_delivered_file(
        self, editor_factory, modal
    ):
        """DI-6：本轮导出 0 条坐标时，不得用空数组覆盖已交付 coords（B41）。"""
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory, modal)
        coords_path = os.path.join(gui_dir, f"gui_{gui_number}_coords.json")
        assert os.path.isfile(coords_path), "准备阶段未写出 coords，用例失去区分力"
        original_coords_bytes = _read_bytes(coords_path)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=0)
        # Android 的 coords 收集对每个步骤无条件 append，不因缺拉框而跳过：
        # 只有清空本轮步骤才会复现“导出 0 条坐标”；同时必须清掉当前截图
        # 文件名，否则 _save_current_to_steps_for_edit 会把空表单追加回步骤
        assert ed2.steps_data, "编辑现场没有步骤"
        ed2.steps_data = []
        ed2._current_screenshot_filename = None

        assert ed2.save_edited_round(True) is True, "编辑写回失败"
        flush_events(50)

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
    """轮次候选项与下标解析：同指令的多轮不得被折叠成同一个选项。

    Android 的调用点把 rounds 汇成 (instruction, trajectory) 二元组，
    故本组用例一律按二元组形式造数据，与真实现场保持一致。
    """

    def test_choice_items_carry_round_number_and_step_count(self):
        """DI-13 回归：候选项同时带轮次序号与步数，指令完全相同也能区分。"""
        from main import build_round_choices, resolve_round_index

        same = "点击首页搜索框输入关键词后进入结果页并筛选价格从低到高排序"
        rounds = [(same, [{"s": 1}]), (same, [{"s": 1}])]
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
        rounds = [(head + "甲", [{"s": 1}]), (head + "乙", [{"s": 1}])]
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

        rounds = [("第一轮指令", [{"s": 1}]), ("第二轮指令", [{"s": 1}])]
        items, index_by_item = build_round_choices(rounds)
        assert index_by_item is not None

        # 早前实现用 items.index(item) 定位，永远命中第一个同名项，
        # 于是把用户选的第 2 轮改成第 1 轮再写回已交付数据
        assert resolve_round_index(index_by_item, "不存在的候选项") is None
        assert resolve_round_index(index_by_item, None) is None
        assert resolve_round_index(None, items[0]) is None
        assert resolve_round_index({}, items[0]) is None


# ----------------------------------------------------------------------
# DI-1：落轮必须消费当前轮（B20a 多轮折叠，Android 独有）
# ----------------------------------------------------------------------

class TestDI1:
    """DI-1 = B20a：落轮后不清 steps_data → 草稿从 rounds[-1] 重建 → 多轮折叠。

    修复前的因果链：
    ① _save_current_round_to_list 只置 _current_round_saved，不清 steps_data；
    ② _write_draft_now 在轮次边界从 rounds[-1] 反推 steps_for_draft，草稿于是
       带上已落轮的全部步骤；
    ③ 续采 load_from_draft 见 steps_data 非空 → _current_round_saved=False、
       返回 False → main 不追问新指令；
    ④ 用户继续截图，新步 append 到复活的旧步之后；
    ⑤ 再落轮 → rounds = [R1(旧步), R2(旧步 + 新步)]：旧轮重复、跨轮截图重复
       引用、R2 还顶着 R1 的 instruction，已交付数据被静默污染。

    三条用例分别钉住 ①②、③、④⑤。
    """

    def test_round_save_consumes_current_steps(self, editor_factory, modal):
        """DI-1 ①②：落轮即消费当前轮，草稿不得从 rounds[-1] 重建。"""
        ed = _round_boundary_scene(editor_factory, modal)

        assert ed.steps_data == [], (
            f"落轮后 steps_data 仍残留 {len(ed.steps_data)} 步：续采会把它们当成"
            "「未结束步骤」复活，再落轮就是 rounds=[R1(旧步), R2(旧步+新步)]"
        )
        assert ed._current_round_saved is True, "用例前提已变：轮次标志被提前复位"

        round1_refs = _round_refs(ed.rounds[0])

        # 轮次边界的草稿就是这个时刻写下的，续采读到的正是它
        ed._write_draft_now()
        flush_events()
        draft = ed.data_manager.load_draft(ed.gui_number)
        assert draft is not None, "轮次边界未写草稿（断点续采会丢已确认轮次）"
        assert draft["steps_data"] == [], (
            "草稿 steps_data 非空：_write_draft_now 仍在轮次边界从 rounds[-1] 重建，"
            "已落轮的步骤被第二次写进草稿"
        )
        assert len(draft["rounds"]) == 1, f"草稿轮次数异常：{len(draft['rounds'])}"
        assert _round_refs(draft["rounds"][0]) == round1_refs, (
            "草稿里第 1 轮的截图引用与内存不一致"
        )

    def test_resume_at_round_boundary_asks_for_new_instruction(
        self, editor_factory, modal
    ):
        """DI-1 ③：轮次边界续采必须追问新指令，且不得复活已落轮步骤。"""
        ed = _round_boundary_scene(editor_factory, modal)
        ed._write_draft_now()
        flush_events()
        draft = ed.data_manager.load_draft(ed.gui_number)
        assert draft is not None, "无可恢复草稿"

        resumed = editor_factory(auto_init=False)
        need_instruction = resumed.load_from_draft(draft)
        flush_events(100)

        assert need_instruction is True, (
            "空当前轮 + 非空历史轮必须返回 True 让上层追问下一条指令；返回 False "
            "时 main 什么都不做，用户会在复活的旧步上继续截图（B20a 折叠入口）"
        )
        assert resumed.steps_data == [], (
            f"续采复活了 {len(resumed.steps_data)} 条已落轮步骤"
        )
        assert len(resumed.rounds) == 1, f"历史轮次未恢复：{len(resumed.rounds)}"
        assert resumed._current_round_saved is True, (
            "轮次边界态未恢复：该标志为 False 会让下一次落轮把历史轮步骤再写一遍"
        )
        assert_all(resumed)

    def test_second_round_does_not_replay_first_round_steps(
        self, editor_factory, modal
    ):
        """DI-1 ④⑤：续采后的第 2 轮只含本轮新步，且顶着自己的新指令。"""
        ed = _round_boundary_scene(editor_factory, modal)
        gui_dir = gui_dir_of(ed)
        ed._write_draft_now()
        flush_events()
        draft = ed.data_manager.load_draft(ed.gui_number)
        round1_refs = _round_refs(ed.rounds[0])

        resumed = editor_factory(auto_init=False)
        need_instruction = resumed.load_from_draft(draft)
        flush_events(100)
        # 复刻 main.ask_next_instruction_after_resume：仅在 load_from_draft 要求追问
        # 时才弹指令框；返回 False 时产品什么都不做，用户直接在复活的 steps_data
        # 上继续截图 —— 那正是折叠发生的现场
        if need_instruction:
            resumed.apply_next_round_instruction("第二轮指令", True)

        confirm_n_steps(resumed, 2, action="click")
        finish_task(resumed, modal, answer_text="第二轮回答")

        rounds = _load_rounds(gui_dir)
        assert len(rounds) == 2, f"最终 JSON 应为 2 轮，实际 {len(rounds)}"
        r1, r2 = rounds
        assert _round_refs(r1) == round1_refs, (
            f"第 1 轮已交付轨迹被改写：{round1_refs} -> {_round_refs(r1)}"
        )
        assert len(r2["trajectory"]) == 3, (
            f"第 2 轮应只含本轮 3 步（2 步 + 收尾），实际 {len(r2['trajectory'])} 步："
            "旧轮步骤被折进了新轮"
        )
        overlap = sorted(set(_round_refs(r2)) & set(round1_refs))
        assert not overlap, f"第 2 轮重复引用了第 1 轮的截图：{overlap}"
        assert r2["instruction"] == "第二轮指令", (
            f"第 2 轮顶着的不是新指令：{r2['instruction']!r}"
        )
        assert len(_pngs(gui_dir)) == 6, (
            f"期望 6 张截图（每轮 3 张），实际 {_pngs(gui_dir)}"
        )
        assert_round_refs_on_disk(gui_dir, rounds)


# ----------------------------------------------------------------------
# DI-2：续采追问指令的取消分支（B19 整轮静默丢弃，Android 独有）
# ----------------------------------------------------------------------

class TestDI2:
    """DI-2 = B19：轮次边界追问下一条指令时取消，旧实现什么都不做。

    修复前的因果链：
    ① 续采走到轮次边界，load_from_draft 见当前轮为空就把
       _current_round_saved 置 True；
    ② main.ask_next_instruction_after_resume 只有「接受」分支，取消或留空时
       不复位该标志；
    ③ 用户接着截图标注，_save_current_round_to_list 靠该标志早退，这一步
       永远进不了 rounds；
    ④ 完成时只写历史轮次，新采集的整轮被静默丢弃，界面却一切正常。
    """

    def _resumed_at_boundary(self, editor_factory, modal):
        """返回停在「已追问、待用户应答」边界态的续采编辑器与第 1 轮引用。"""
        _, draft, round1_refs = _round_boundary_draft(editor_factory, modal)
        resumed = editor_factory(auto_init=False)
        assert resumed.load_from_draft(draft) is True, "边界续采未进入追问指令分支"
        flush_events(100)
        return resumed, round1_refs

    def test_cancel_resume_instruction_resets_round_flag(self, editor_factory, modal):
        """DI-2 ②：取消新指令必须复位轮次标志，工作区回到空白可采集态。"""
        resumed, round1_refs = self._resumed_at_boundary(editor_factory, modal)

        accepted = resumed.apply_next_round_instruction("", False)
        flush_events()

        assert accepted is False, "取消应答被当成接受处理"
        assert resumed._current_round_saved is False, (
            "取消追问后 _current_round_saved 仍为 True：后续 "
            "_save_current_round_to_list 会一律早退，用户这一轮采集被静默丢弃"
            "（B19 本体）"
        )
        assert resumed.steps_data == [], "取消后工作区仍残留步骤"
        assert resumed.coords_data == [], "取消后工作区仍残留坐标"
        assert resumed.rounds and _round_refs(resumed.rounds[0]) == round1_refs, (
            "取消新轮不应改动已落轮的历史数据"
        )
        assert "已取消新任务" in resumed.status_label.text(), (
            f"取消后未提示可继续采集：{resumed.status_label.text()!r}"
        )
        assert_all(resumed)

    def test_round_after_cancel_is_saved_and_delivered(self, editor_factory, modal):
        """DI-2 ③④：取消追问后采集的整轮必须落轮并写进最终 JSON。"""
        resumed, round1_refs = self._resumed_at_boundary(editor_factory, modal)
        gui_dir = gui_dir_of(resumed)
        resumed.apply_next_round_instruction("", False)
        flush_events()

        confirm_n_steps(resumed, 2, action="click")
        # 取消时用户没有新指令，直接在采集态落轮 —— B19 的丢弃就发生在这一步。
        # B14 修复后取消分支已把 task_instruction 置空，落轮前会弹补齐框，故这里
        # 放开补齐应答，并把返回值断成 True —— 只有真落轮才算 B19 修好，
        # 若断成「被拒绝也继续」就会退化成假绿。
        modal.input_ok = True
        modal.input_text = _SECOND_INSTRUCTION
        assert resumed._save_current_round_to_list() is True, (
            "取消续采后补齐了指令仍被拒绝落轮（B14 安全网误伤 B19 修复路径）"
        )
        flush_events()

        assert len(resumed.rounds) == 2, (
            f"取消追问后采集的第 2 轮被静默丢弃：rounds 仍只有 {len(resumed.rounds)} 轮"
        )
        assert len(_round_refs(resumed.rounds[1])) == 2, (
            f"第 2 轮应含本轮 2 步，实际 {len(_round_refs(resumed.rounds[1]))} 步"
        )
        # B14 归属断言：本轮必须挂在自己补齐的新指令上，不得沿用第 1 轮已被
        # 消费的指令，否则事后无从分辨哪段轨迹属于哪条指令。
        assert resumed.rounds[1]["instruction"] == _SECOND_INSTRUCTION, (
            f"第 2 轮落到了别的指令上：{resumed.rounds[1]['instruction']!r}"
        )
        assert resumed.rounds[1]["instruction"] != resumed.rounds[0]["instruction"], (
            "两轮共用同一条指令 —— 第 2 轮静默挂到了上一条已被消费的指令上（B14）"
        )

        assert resumed._save_all_rounds_to_file() is True, "最终 JSON 未写入"
        rounds = _load_rounds(gui_dir)
        assert len(rounds) == 2, f"交付数据只剩 {len(rounds)} 轮（应为 2 轮）"
        assert _round_refs(rounds[0]) == round1_refs, "第 1 轮已交付轨迹被改写"
        assert len(_round_refs(rounds[1])) == 2, "第 2 轮交付步骤数异常"
        assert_round_refs_on_disk(gui_dir, rounds)


# ----------------------------------------------------------------------
# DI-11：answer 落轮后取消新轮，工作区必须回到空白起点（B1 / B28）
# ----------------------------------------------------------------------

class TestDI11:
    """DI-11 = B1/B28：answer 已落轮，用户又取消开新轮，不能只改状态文案。

    Android 的关键风险与 Windows/iOS 同族但后果更重：落轮后
    _current_round_saved 为 True，而 _save_current_round_to_list 靠该标志早退。
    取消分支若不复位（Windows B1 / iOS B28 的原始缺陷形态），用户接着采集的
    整轮永远进不了 rounds，界面却一切正常 —— 本组用例把 Android 的正确实现
    （_reset_workspace_after_cancel，亦即 iOS 移植时的口径来源）钉成回归防线。

    注：本组只钉「工作区重置」与「不牵连已交付数据」；取消后 task_instruction
    必须置空、缺指令必须拒绝落轮属计划 2.6（B14），断言落在 TestDI15。
    """

    def _cancelled(self, editor_factory, modal):
        """走满一轮 → answer 落轮 → 续轮对话框取消，返回已过取消分支的编辑器。"""
        ed = _round_boundary_scene(editor_factory, modal)
        # 300ms 后续轮对话框由 modal.input_ok=False 走取消分支
        flush_events(400)
        return ed

    def test_cancel_after_answer_resets_round_flag_and_workspace(self, editor_factory, modal):
        """DI-11 回归：取消新轮必须复位轮次标志并把工作区清成空白起点。"""
        ed = self._cancelled(editor_factory, modal)

        assert len(ed.rounds) == 1, (
            f"answer 未落轮，用例前提不成立：rounds={len(ed.rounds)}"
        )
        # B1/B28 本体：取消分支不复位该标志，后续落轮就一律早退
        assert ed._current_round_saved is False, (
            "取消新轮后 _current_round_saved 仍为 True：_save_current_round_to_list "
            "会一律早退，用户接着采集的整轮被静默丢弃"
        )
        assert ed.steps_data == [], f"取消后仍残留步骤：{len(ed.steps_data)}"
        assert ed.coords_data == [], "取消后仍残留坐标"
        assert ed.current_step == 0, f"取消后步骤序号未复位：{ed.current_step}"
        assert ed._missing_cache == {}, "取消后缺填缓存未失效"
        assert ed._insert_after_index is None, "取消后插入锚点未清空"
        # 界面残留：画布与当前步缓存必须一起清，否则新步接在旧截图上
        assert ed.screenshot_canvas._pixmap is None, "取消后画布仍挂着上一轮截图"
        assert ed.screenshot_cache is None, "取消后截图缓存未释放"
        assert ed._current_screenshot_filename is None, "取消后仍持有当前步截图名"
        assert ed._current_vertices is None, "取消后仍持有上一轮拉框"
        assert "已取消新任务" in ed.status_label.text(), (
            f"取消后未提示可继续采集：{ed.status_label.text()!r}"
        )
        assert_all(ed)

    def test_cancel_keeps_delivered_round_and_draft(self, editor_factory, modal):
        """DI-11 边界回归：重置只清界面，已交付轮次与草稿不得被牵连。"""
        ed = self._cancelled(editor_factory, modal)
        gui_dir = gui_dir_of(ed)
        round1_refs = _round_refs(ed.rounds[0])

        assert len(round1_refs) == 3, f"已交付轮次步数丢失：{len(round1_refs)}"
        for name in round1_refs:
            assert os.path.isfile(os.path.join(gui_dir, name)), (
                f"重置过程误删了已交付截图：{name}"
            )

        ed._write_draft_now()
        flush_events()
        draft = ed.data_manager.load_draft(ed.gui_number)
        assert draft is not None, "取消新轮后草稿未落盘"
        assert draft.get("steps_data") == [], (
            f"取消新轮后草稿仍留着上一轮的步骤：{len(draft.get('steps_data') or [])}"
        )
        assert len(draft.get("rounds") or []) == 1, "草稿 rounds 未同步落盘"

    def test_round_after_cancel_is_delivered(self, editor_factory, modal):
        """DI-11 后果回归：取消新轮后采集的整轮必须真的交付，不与旧界面拼接。"""
        ed = self._cancelled(editor_factory, modal)
        gui_dir = gui_dir_of(ed)
        gui_number = gui_number_from_dir(gui_dir)
        round1_refs = _round_refs(ed.rounds[0])

        confirm_n_steps(ed, 2, action="click")
        # B14：取消新轮后指令已置空，收尾落轮会弹补齐框，这里放开应答补回新指令
        modal.input_ok = True
        modal.input_text = _SECOND_INSTRUCTION
        finish_task(ed, modal)

        rounds = _load_rounds(gui_dir)
        assert len(rounds) == 2, (
            f"取消新轮后采集的第 2 轮被静默丢弃：交付数据只剩 {len(rounds)} 轮"
        )
        # 交付文件里两轮必须各有各的指令（B14 的最终产物口径）
        assert [r["instruction"] for r in rounds] == [
            _FIRST_INSTRUCTION, _SECOND_INSTRUCTION
        ], (f"交付文件里的指令序列错乱：{[r['instruction'] for r in rounds]}")
        round2_refs = _round_refs(rounds[1])
        assert len(round2_refs) == 3, f"第 2 轮应为 2 步 + 收尾步，实际 {len(round2_refs)}"
        overlap = sorted(set(round2_refs) & set(round1_refs))
        assert not overlap, f"第 2 轮重复引用了第 1 轮的截图：{overlap}"
        assert len(_pngs(gui_dir)) == 6, f"期望 6 张截图（每轮 3 张），实际 {_pngs(gui_dir)}"
        assert_round_refs_on_disk(gui_dir, rounds)
        assert os.path.isfile(
            os.path.join(gui_dir, f"gui_{gui_number}.json")
        ), "收尾后未写出最终 JSON"


# ----------------------------------------------------------------------
# DI-8：切轮 300ms 竞态窗口内的采集必须被拦住（B2）
# ----------------------------------------------------------------------

class TestDI8:
    """answer 落轮后的 300ms 切轮窗口内，截图入口必须早退。

    Android 的 answer 分支先同步 _save_current_round_to_list 落轮并清空当前轮，
    再延后 300ms 才弹 _start_new_round(from_answer=True) 取新指令。这 300ms 里
    task_instruction 仍是旧指令，被放行的截图要么用旧指令再凑一轮，要么留下
    无人引用的孤儿 PNG —— 故门闩必须挡在 take_screenshot 第一句。
    """

    def test_take_screenshot_inside_round_window_is_refused(self, editor_factory, modal):
        """DI-8：窗口内 take_screenshot 必须早退，且不得落成孤儿 PNG。"""
        ed = _round_boundary_scene(editor_factory, modal)
        gui_dir = gui_dir_of(ed)
        before = _pngs(gui_dir)
        seq_before = ed._screenshot_seq

        assert ed._round_transition_pending is True, (
            "answer 落轮后未升起切轮门闩：300ms 窗口内的截图会落在旧指令的轮次上（B2）"
        )

        ed.take_screenshot()

        # 即时信号：放行路径会同步置锁并递增截图序号，因此这两条断言不依赖
        # 任何时序就能区分「拦住」与「被放行」
        assert ed._screenshot_in_progress is False, (
            "切轮窗口内 take_screenshot 被放行：截图会落在旧 instruction 刚交付的轮次上（B2）"
        )
        assert ed._screenshot_seq == seq_before, (
            f"切轮窗口内截图序号仍被推进：{seq_before} -> {ed._screenshot_seq}（B2）"
        )
        assert ed.status_label.text() == "轮次切换中，请稍候...", (
            f"切轮窗口内截图未给出拦截提示：{ed.status_label.text()!r}"
        )
        assert ed.steps_data == [], f"切轮窗口内截图污染了步骤：{len(ed.steps_data)}"

        # 让 300ms 切轮回调与截图链路都跑完：被放行那次会真的写盘成孤儿 PNG
        flush_events(600)
        assert _pngs(gui_dir) == before, (
            "切轮窗口内的截图落成了无人引用的孤儿 PNG："
            f"{sorted(set(_pngs(gui_dir)) - set(before))}（B2）"
        )
        assert len(ed.rounds) == 1, f"切轮窗口内的采集多落了一轮：rounds={len(ed.rounds)}"
        assert ed._round_transition_pending is False, "切轮回调进场后门闩未释放"
        assert_all(ed)

    def test_capture_works_after_round_window(self, editor_factory, modal):
        """DI-8 边界：门闩只堵 300ms 窗口，不能把后续采集永久卡死。"""
        ed = _round_boundary_scene(editor_factory, modal)
        flush_events(400)
        assert ed._round_transition_pending is False, (
            "切轮回调已进场，门闩仍未释放：采集入口被永久卡死"
        )

        confirm_n_steps(ed, 1, action="click")
        assert len(ed.steps_data) == 1, (
            f"切轮窗口结束后采集未被放行：steps_data={len(ed.steps_data)}"
        )
        assert len(ed.rounds) == 1, f"窗口后的单步不应落轮：rounds={len(ed.rounds)}"
        assert ed._current_round_saved is False, (
            "切轮后 _current_round_saved 未复位，后续整轮会被静默丢弃"
        )
        assert_all(ed)

    def test_second_round_after_window_uses_new_instruction(self, editor_factory, modal):
        """DI-8 后果：窗口后续采的第 2 轮必须落在新指令上，且不共用第 1 轮截图。"""
        ed = _round_boundary_scene(editor_factory, modal)
        first_instruction = ed.rounds[0]["instruction"]

        modal.input_ok = True          # 300ms 后的续轮对话框接受新指令
        flush_events(400)
        assert ed.task_instruction == modal.input_text, (
            f"续轮后仍沿用旧指令：{ed.task_instruction!r}"
        )

        confirm_n_steps(ed, 2, action="click")
        capture_and_wait(ed)
        fill_valid_step(ed, action="answer", text="第二轮回答")
        modal.input_ok = False         # 第 3 轮对话框走取消，顺带排空定时器
        ed.confirm_step()
        flush_events(500)

        assert len(ed.rounds) == 2, f"期望 2 轮，实际 {len(ed.rounds)}"
        assert ed.rounds[1]["instruction"] == modal.input_text, (
            f"第 2 轮指令错位：{ed.rounds[1]['instruction']!r}"
        )
        assert ed.rounds[1]["instruction"] != first_instruction, (
            "两轮落在同一条旧指令上：切轮窗口内的重复采集没被拦住（B2）"
        )
        overlap = sorted(set(_round_refs(ed.rounds[0])) & set(_round_refs(ed.rounds[1])))
        assert not overlap, f"第 2 轮重复引用了第 1 轮的截图：{overlap}"
        assert_all(ed)


# ----------------------------------------------------------------------
# DI-15：取消新轮后不得沿用旧指令，缺指令轮次必须拒绝落轮（B14）
# ----------------------------------------------------------------------

class TestDI15:
    """续轮取消置空指令 + 落轮前强校验非空 + 缺指令拒绝落轮并保持现场。

    Android 比 Windows/iOS 多一个落轮入口：closeEvent 在关窗前也会把当前轮
    落入 rounds，因此本端额外钉「无人值守路径只静默拒绝、不弹模态框」一例。
    """

    def test_cancel_new_round_clears_instruction(self, editor_factory, modal):
        """DI-15 回归（B14）：续轮对话框取消后 task_instruction 必须置空。"""
        ed = _cancelled_at_boundary(editor_factory, modal)

        # 上一轮已随 answer 落入 rounds 并被消费，继续留着旧指令，用户接着采集
        # 的整轮就会被静默挂到上一条指令上 —— 事后无从分辨哪段轨迹属于哪条指令。
        assert ed.task_instruction == "", (
            f"取消续轮后仍沿用已被消费的旧指令：{ed.task_instruction!r}"
        )
        # 置空只针对「当前轮」，已交付轮次里的指令不得被牵连改写
        assert ed.rounds[0]["instruction"] == _FIRST_INSTRUCTION, (
            f"清空当前轮指令时改写了已交付轮次：{ed.rounds[0]['instruction']!r}"
        )
        assert_all(ed)

    def test_empty_instruction_round_is_refused_and_keeps_steps(
        self, editor_factory, modal
    ):
        """DI-15 后果回归：补齐弹窗也取消 → 拒绝落轮，现场与产物都不能动。"""
        ed = _cancelled_at_boundary(editor_factory, modal)
        gui_dir = gui_dir_of(ed)
        gui_number = gui_number_from_dir(gui_dir)

        confirm_n_steps(ed, 2, action="click")
        shots_before = [s["screenshot"] for s in ed.steps_data]
        warnings_before = len(modal.warnings)

        modal.input_ok = False  # 「补齐任务指令」弹窗也取消
        capture_and_wait(ed)
        fill_valid_step(ed, action="answer_terminate", text="第二轮回答")
        ed.confirm_step()
        flush_events(100)

        assert ed._task_completed is False, (
            "缺任务指令却被当成收尾成功：交付文件会缺最后一轮（B14）"
        )
        assert len(ed.rounds) == 1, (
            f"空指令轮被静默落入 rounds：rounds={len(ed.rounds)}"
        )
        assert ed._current_round_saved is False, (
            "拒绝落轮却把轮次标志置位：本轮数据已被消费，补齐后也无法重新落轮"
        )
        # 拒绝落轮必须保持现场：_finish_task 先把收尾步落表（_save_current_to_steps
        # 在守卫之前），故本轮应为「已采集步 + 收尾步」且原步逐项完好；
        # 若调用方照常清空 steps_data/写交付文件，指令错乱就升级成整轮丢失。
        assert len(ed.steps_data) == len(shots_before) + 1, (
            f"拒绝落轮后本轮步数异常：{len(ed.steps_data)} vs {len(shots_before)}"
        )
        assert (
            [s["screenshot"] for s in ed.steps_data[:len(shots_before)]]
            == shots_before
        ), "拒绝落轮时本轮已采集步骤被清空或改写"
        assert not os.path.isfile(
            os.path.join(gui_dir, f"gui_{gui_number}.json")
        ), "缺少任务指令却写出了交付文件（B14）"
        # 「缺少任务指令 - 本轮未落轮」只由 _prompt_missing_instruction 写下，
        # Android 的 FakeInputDialog 不记录调用次数，故用这条状态文案证明
        # 落轮前确实先弹过补齐框（计划 2.6 要求先补再落），而非直接静默拒绝。
        assert "缺少任务指令" in ed.status_label.text(), (
            f"拒绝落轮后未给出可操作的状态提示：{ed.status_label.text()!r}"
        )
        assert len(modal.warnings) == warnings_before + 1, (
            "拒绝落轮未告警（用户会以为已经保存），或重复弹框"
        )
        assert any(title == "缺少任务指令" for title, _ in modal.warnings), (
            f"告警框标题不对，用户无从知道该补指令：{modal.warnings}"
        )
        for name in shots_before:
            assert os.path.isfile(os.path.join(gui_dir, name)), (
                f"拒收过程误删了本轮截图：{name}"
            )
        # 已交付轮次的磁盘引用不受拒收影响。此处不调 assert_all：INV-8 要求侧栏条目
        # 与 steps_data 等长，而 _finish_task 早退（无论校验不通过还是本例的缺指令）
        # 都只把收尾步落表、未建侧栏条目 —— 界面同步缺口与指令归属无关，另案处理。
        assert_round_refs_on_disk(gui_dir, ed.rounds)

    def test_supplemented_instruction_lands_on_new_round(self, editor_factory, modal):
        """DI-15 修复路径：补齐指令后本轮按新指令落轮，两轮指令互不相同。"""
        ed = _cancelled_at_boundary(editor_factory, modal)
        gui_dir = gui_dir_of(ed)
        confirm_n_steps(ed, 2, action="click")

        modal.input_ok = True
        modal.input_text = _SECOND_INSTRUCTION
        finish_task(ed, modal)

        assert len(ed.rounds) == 2, f"补齐后第二轮未落轮：{len(ed.rounds)}"
        assert ed.rounds[1]["instruction"] == _SECOND_INSTRUCTION, (
            f"第二轮落到了别的指令上：{ed.rounds[1]['instruction']!r}"
        )
        rounds = _load_rounds(gui_dir)
        assert [r["instruction"] for r in rounds] == [
            _FIRST_INSTRUCTION, _SECOND_INSTRUCTION
        ], f"交付文件里的指令序列错乱：{[r['instruction'] for r in rounds]}"
        # 交付成功会删草稿（INV-6 不再适用），只核对两轮引用在磁盘上完好
        assert_round_refs_on_disk(gui_dir, ed.rounds)

    def test_close_path_refuses_without_dialog(self, editor_factory, modal):
        """DI-15 边界回归：关闭路径无人值守，缺指令只静默拒绝，不弹模态框。"""
        ed = _cancelled_at_boundary(editor_factory, modal)
        gui_dir = gui_dir_of(ed)
        gui_number = gui_number_from_dir(gui_dir)
        confirm_n_steps(ed, 2, action="click")
        shots_before = [s["screenshot"] for s in ed.steps_data]
        warnings_before = len(modal.warnings)
        questions_before = len(modal.questions)

        # Android 的无人值守落轮入口就是 closeEvent（安全网传 prompt_instruction=False），
        # 故这里构造事件走产品入口，而不是直接调私有落轮函数
        ed.closeEvent(QCloseEvent())
        flush_events()

        assert len(modal.warnings) == warnings_before, (
            "关闭过程中弹出告警框：退出路径可能被模态框卡住（无人值守须静默）"
        )
        assert len(modal.questions) == questions_before, (
            "关闭过程中弹出了确认框：退出路径不得再要求用户应答"
        )
        assert len(ed.rounds) == 1, (
            f"关闭路径用空指令落了轮：rounds={len(ed.rounds)}"
        )
        assert [s["screenshot"] for s in ed.steps_data] == shots_before, (
            "关闭路径拒绝落轮却清空了本轮步骤"
        )
        assert not os.path.isfile(
            os.path.join(gui_dir, f"gui_{gui_number}.json")
        ), "缺指令时仍写出了交付文件（会缺最后一轮）"
        draft = ed.data_manager.load_draft(ed.gui_number)
        assert draft is not None, "关闭路径拒收后草稿未落盘，本轮采集将丢失"
        assert len(draft.get("steps_data") or []) == len(shots_before), (
            f"草稿未保留本轮已采集步骤：{len(draft.get('steps_data') or [])}"
        )
        assert len(draft.get("rounds") or []) == 1, "草稿 rounds 与已落轮数不符"


# ----------------------------------------------------------------------
# DI-16：落轮必须存副本，本轮对步骤 action 的原地改写不得回灌已落轮数据（B42）
# ----------------------------------------------------------------------

class TestDI16:
    """rounds 与 steps_data 不得共享同一个 action dict（B42）。

    全仓核实现今没有「落轮之后再原地改写步骤 action」的产品链路，所以本缺陷是**潜伏**
    的别名缺陷；用例因此钉的是隔离不变量，而不是复现某条具体路径：先攥住 steps_data 里
    那个活 action dict（连同它嵌套的 coordinate 列表）的引用，走产品 answer 入口落轮，
    再原地改写这些引用 —— 已落轮的 rounds 项、coords 项与随后的写盘产物都必须保持
    落轮当时的样子。去掉落轮侧的 deepcopy，两条断言都会立刻失败（变异 Q 已验证）。
    """

    def test_landed_action_is_a_copy(self, editor_factory, modal):
        """DI-16 回归（B42）：落轮存的是副本，原地改写步骤 action 不回灌 rounds。"""
        modal.input_ok = False
        ed = editor_factory()
        confirm_n_steps(ed, 2, action="click")

        live_step = ed.steps_data[0]
        live_action = live_step["action_data"]
        live_coordinate = live_action["coordinate"]
        pristine_action = copy.deepcopy(live_action)
        pristine_vertices = list(live_step["vertices"])

        capture_and_wait(ed)
        fill_valid_step(ed, action="answer", text="第一轮回答")
        ed.confirm_step()
        flush_events(50)
        assert len(ed.rounds) == 1, f"answer 后未落轮：rounds={len(ed.rounds)}"

        landed_action = ed.rounds[0]["trajectory"][0]["actions"][0]
        assert landed_action is not live_action, (
            "落轮把 steps_data 里的活 action 对象直接放进 rounds，"
            "rounds 与本轮数据共享同一个 dict（B42）"
        )
        assert landed_action["coordinate"] is not live_coordinate, (
            "action 落轮只做了浅拷贝，嵌套的 coordinate 列表仍与本轮共享（B42）"
        )

        # 原地改写探针：键值改写、新增键、动嵌套列表，模拟任何「已落轮之后仍在改
        # 本轮步骤 action」的路径；浅拷贝也挡不住第三、四项
        live_action["action"] = "__polluted__"
        live_action["text"] = "污染文本"
        live_coordinate[0] = 777777
        live_step["vertices"].append(999999)

        assert ed.rounds[0]["trajectory"][0]["actions"][0] == pristine_action, (
            f"对步骤 action 的原地改写回灌到了已落轮数据（B42）："
            f"{ed.rounds[0]['trajectory'][0]['actions'][0]}"
        )
        landed_coords = ed.rounds[0]["coords"][0]
        assert landed_coords["vertices"] == pristine_vertices, (
            f"coords 顶点被本轮的拉框改写串台（B42）：{landed_coords['vertices']}"
        )
        assert landed_coords["center"] == pristine_action["coordinate"], (
            f"coords 中心点被本轮的坐标改写串台（B42）：{landed_coords['center']}"
        )

        # 轮次边界的取消分支会重建草稿，改写同样不得顺着 rounds 漏到盘上
        flush_events(400)
        draft = ed.data_manager.load_draft(ed.gui_number)
        assert draft is not None, "轮次边界未落下草稿"
        draft_rounds = draft.get("rounds") or []
        assert len(draft_rounds) == 1, f"草稿轮次数异常：{len(draft_rounds)}"
        assert draft_rounds[0]["trajectory"][0]["actions"][0] == pristine_action, (
            f"草稿里的已落轮 action 被本轮的原地改写污染（B42）："
            f"{draft_rounds[0]['trajectory'][0]['actions'][0]}"
        )
        assert_all(ed)

    def test_in_place_action_edit_does_not_reach_delivered_json(
        self, editor_factory, modal
    ):
        """DI-16 后果回归：改写探针后继续第二轮并交付，首轮交付数据逐字段不变。"""
        modal.input_ok = False
        ed = editor_factory()
        gui_dir = gui_dir_of(ed)
        confirm_n_steps(ed, 2, action="click")

        live_action = ed.steps_data[0]["action_data"]
        pristine_action = copy.deepcopy(live_action)

        capture_and_wait(ed)
        fill_valid_step(ed, action="answer", text="第一轮回答")
        ed.confirm_step()
        modal.input_ok = True
        modal.input_text = _SECOND_INSTRUCTION
        flush_events(400)
        assert len(ed.rounds) == 1, f"answer 后未落轮：rounds={len(ed.rounds)}"
        assert ed.task_instruction == _SECOND_INSTRUCTION, (
            f"续轮未切到新指令，第二轮会挂到第一条指令上：{ed.task_instruction!r}"
        )

        # 落轮之后原地改写本轮步骤的 action：早前 rounds 与 steps_data 共享对象，
        # 于是这种改写会顺着 rounds 一路写进交付文件，已交付数据被静默改掉
        live_action["action"] = "__polluted__"
        live_action["coordinate"][0] = 777777

        confirm_n_steps(ed, 2, action="click")
        finish_task(ed, modal)

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
            _FIRST_INSTRUCTION, _SECOND_INSTRUCTION
        ], f"交付文件里的指令序列错乱：{[r['instruction'] for r in rounds]}"
        # 交付成功会删草稿（INV-6 不再适用），只核对两轮引用在磁盘上完好
        assert_round_refs_on_disk(gui_dir, ed.rounds)


# ----------------------------------------------------------------------
# DI-17：采集中回看历史步、确认后只前进一格，不得把用户传送到末尾（B22）
# ----------------------------------------------------------------------

def _highlighted_indexes(editor):
    """侧栏蓝底高亮条目下标 = 侧栏认得的「当前正在编辑第几步」。"""
    return [i for i, item in enumerate(editor.sidebar.item_widgets)
            if "#E3F2FD" in item.styleSheet()]


class TestDI17:
    """confirm_step 之后游标只前进一格（B22）。

    计划 2.8 原写「默认保持原值」，勘察后否决：go_next 停在最后一步时是委托
    confirm_step 来进入末尾待截图空位的（见 go_next 的 else 分支），历史步确认若完全
    不推进，末步就再也进不了空位、无法续采。最终口径是「中间历史步 → 前进一格并完整
    回填现场；追加新步/确认末步 → 进入空位」，两条用例分头钉住这两个方向：
      test_1 中间步确认后不传送、表单/截图/高亮/草稿一致（还原「无条件推到末尾」即失败）
      test_2 从中间步确认后仍能一路走到空位并正常追加（改成「完全不推进」即失败）
    """

    def test_confirm_history_step_advances_one_not_to_end(self, editor_factory, modal):
        """DI-17 回归（B22）：改完中间历史步确认后只前进一格，不传送末尾、不清表单。"""
        modal.input_ok = False  # 本用例不该弹输入框，万一弹出按取消处理
        ed = editor_factory()
        confirm_n_steps(ed, 3, action="click")
        assert len(ed.steps_data) == 3, f"用例前提不成立：{len(ed.steps_data)} 步"
        original_intents = [s["intent"] for s in ed.steps_data]
        original_shots = [s["screenshot"] for s in ed.steps_data]
        neighbours_before = copy.deepcopy([ed.steps_data[0], ed.steps_data[2]])

        # 回看中间第 2 步（下标 1），改完 intent 再确认
        ed.jump_to_step(1)
        assert ed.current_step == 1
        fill_valid_step(ed, action="click", intent="改过的第2步")
        ed.confirm_step()
        flush_events(50)

        # 改动原地落表：既没多落一步，也没挪动相邻步
        assert ed.steps_data[1]["intent"] == "改过的第2步"
        assert len(ed.steps_data) == 3, (
            f"确认历史步时 steps_data 被追加（B22）：{len(ed.steps_data)}"
        )
        assert copy.deepcopy([ed.steps_data[0], ed.steps_data[2]]) == neighbours_before, (
            "确认中间步时挪动或覆盖了相邻步骤"
        )

        # 核心：游标只前进一格、仍停在已有步上，而不是被推到 len(steps_data)
        assert ed.current_step == 2, (
            f"确认后游标被静默传送到末尾（B22）：current_step={ed.current_step}，"
            f"len(steps_data)={len(ed.steps_data)}"
        )
        # 现场完整回填：表单与截图三指针都是第 3 步的，不必重新截图即可接着核对
        assert ed.intent_input.text() == original_intents[2], (
            f"确认后表单被清空或串步（B22）：{ed.intent_input.text()!r}"
        )
        assert ed._current_screenshot_filename == original_shots[2], (
            "确认后未把第 3 步的截图引回复现，等于强制用户重新截图（B22）"
        )
        assert _highlighted_indexes(ed) == [2], (
            f"侧栏高亮与游标不同步（B22）：{_highlighted_indexes(ed)}"
        )
        assert "已更新第 2 步" in ed.status_label.text(), (
            f"确认历史步后的状态提示未反映「已更新 + 可继续编辑」：{ed.status_label.text()}"
        )

        ed._write_draft_now()
        flush_events()
        draft = ed.data_manager.load_draft(ed.gui_number)
        assert draft is not None, "确认后草稿未落盘"
        draft_steps = draft.get("steps_data") or []
        assert [s.get("intent") for s in draft_steps] == [
            original_intents[0], "改过的第2步", original_intents[2]
        ], f"草稿里的步骤序列被打乱（B22）：{[s.get('intent') for s in draft_steps]}"
        assert draft.get("current_step_index") == 2, (
            f"草稿游标与内存不同步（B22）：{draft.get('current_step_index')}"
        )
        assert_all(ed)

    def test_confirm_from_history_step_still_reaches_empty_slot(
        self, editor_factory, modal
    ):
        """DI-17 反向回归：从中间步确认后仍能一路走到末尾空位并正常追加新步。

        钉住修复的另一个方向：若把「前进一格」做成「原地不动」，go_next 停在末步时
        靠 confirm_step 进入空位的链路就断了，用户再也无法续采（采集死锁）。
        """
        modal.input_ok = False
        ed = editor_factory()
        confirm_n_steps(ed, 3, action="click")
        original_intents = [s["intent"] for s in ed.steps_data]

        ed.jump_to_step(0)
        fill_valid_step(ed, action="click", intent="改过的第1步")
        ed.confirm_step()
        flush_events(50)
        assert ed.current_step == 1

        limit = len(ed.steps_data) + 2
        while ed.current_step < len(ed.steps_data) and limit > 0:
            ed.go_next()
            flush_events()
            limit -= 1
        assert ed.current_step == len(ed.steps_data) == 3, (
            f"从历史步出发走不到末尾待截图空位（B22 反向）："
            f"current_step={ed.current_step}, len={len(ed.steps_data)}"
        )
        assert ed._current_screenshot_filename is None, "末尾空位应为未截图的新步现场"

        capture_and_wait(ed)
        fill_valid_step(ed, action="click", intent="第4步")
        ed.confirm_step()
        flush_events(50)
        assert [s["intent"] for s in ed.steps_data] == [
            "改过的第1步", original_intents[1], original_intents[2], "第4步"
        ], "末尾追加的新步覆盖或插进了历史步（B22 反向）"
        assert ed.current_step == 4
        assert_all(ed)


# ----------------------------------------------------------------------
# DI-7：截图序号分配必须全局递增，空洞不得复用（B38 / B10）
# ----------------------------------------------------------------------

def _shot_seq(name):
    """取 gui_编号_NNNN.png 里的序号；命名不合规直接失败，避免用例静默放行。"""
    digits = os.path.splitext(name or "")[0].rsplit("_", 1)[-1]
    assert digits.isdigit(), f"截图命名不合规，无法追溯顺序: {name}"
    return int(digits)


class TestDI7:
    """序号分配语义（B38）与插入倒挂的可接受边界（B10）。

    计划 3.1 默认采用退化方案「允许空洞、保证递增唯一」，因此两条用例分别钉住：
      test_1 删中间步形成空洞后，新截图必须取 max+1，绝不回填被删序号（变异 S 可证牙齿）
      test_2 空洞之上再做中间插入，新图仍取 max+1；序号与 step 顺序倒挂属计划 3.2
             已接受的现实，此时严格递增断言不成立，但唯一性/命名/引用存在必须完好
    """

    def test_deleted_middle_hole_is_never_reused(self, editor_factory, modal):
        """DI-7 回归（B38）：删中间步留下的序号空洞，不得被后续新截图复用。"""
        modal.input_ok = False  # 本用例不该弹输入框，万一弹出按取消处理
        ed = editor_factory()
        confirm_n_steps(ed, 3, action="click")
        shots = [s["screenshot"] for s in ed.steps_data]
        assert [_shot_seq(n) for n in shots] == [1, 2, 3], (
            f"用例前提不成立：三步截图序号应连续递增，实际 {shots}"
        )

        # 删中间第 2 步：steps_data 少一步，0002 文件被回收，盘上留下序号空洞
        ed.jump_to_step(1)
        ed.delete_current_step()
        flush_events(50)
        assert len(ed.steps_data) == 2, f"删步未生效：{len(ed.steps_data)} 步"
        assert not os.path.isfile(os.path.join(ed.gui_dir, shots[1])), (
            "用例前提不成立：被删步骤的截图仍在盘上，空洞没形成"
        )

        # 一路走到末尾待截图空位后续采
        limit = len(ed.steps_data) + 2
        while ed.current_step < len(ed.steps_data) and limit > 0:
            ed.go_next()
            flush_events()
            limit -= 1
        assert ed.current_step == len(ed.steps_data) == 2, (
            f"用例前提不成立：走不到末尾空位 current_step={ed.current_step}"
        )

        capture_and_wait(ed)
        fill_valid_step(ed, action="click", intent="续采的第3步")
        ed.confirm_step()
        flush_events(50)

        # 核心：新截图取 max(剩余)+1 = 0004；改回「最小未占用序号」即复用 0002
        new_shot = ed.steps_data[2]["screenshot"]
        assert _shot_seq(new_shot) == 4, (
            f"新截图复用了被删序号空洞（B38）：被删的是 {shots[1]}，"
            f"新图却落到 {new_shot}，期望全局 max+1 即 0004"
        )
        assert _shot_seq(new_shot) > max(_shot_seq(n) for n in shots if n != shots[1]), (
            f"新截图序号未大于盘上已有最大序号（B38）：{new_shot}"
        )
        # 引用序列 [1,3,4] 仍严格递增，只是中间留洞（3.1 退化方案的口径）
        assert_screenshot_order(ed, strict_monotonic=True, allow_holes=True)
        assert_all(ed)

    def test_insert_after_hole_keeps_global_unique_numbering(self, editor_factory, modal):
        """DI-7 口径（B10）：空洞后插入中间步仍取全局 max+1，倒挂可接受但唯一性必须完好。"""
        modal.input_ok = False
        ed = editor_factory()
        confirm_n_steps(ed, 3, action="click")
        shots = [s["screenshot"] for s in ed.steps_data]
        intents = [s["intent"] for s in ed.steps_data]

        ed.jump_to_step(1)
        ed.delete_current_step()
        flush_events(50)
        assert not os.path.isfile(os.path.join(ed.gui_dir, shots[1])), (
            "用例前提不成立：未形成序号空洞"
        )

        # 在第 1 步后插入新步：新图取全局 max+1（0004），而不是回填空洞 0002
        ed.jump_to_step(0)
        ed.start_insert_capture()
        waited = 0
        while ed._screenshot_in_progress and waited < 10000:
            flush_events(30)
            waited += 30
        flush_events()
        assert not ed._screenshot_in_progress, "插入截图未在超时内完成"
        assert len(ed.steps_data) == 3, f"插入未落新步：{len(ed.steps_data)} 步"
        inserted = ed.steps_data[1]["screenshot"]
        assert _shot_seq(inserted) == 4, (
            f"插入步未取全局 max+1（B38/B10）：期望 0004，实际 {inserted}，"
            f"被删的空洞序号是 {shots[1]}"
        )
        fill_valid_step(ed, action="click", intent="插入的新步")
        ed.confirm_step()
        flush_events(50)

        # 业务顺序 1-新-3，文件名序号 [1,4,3] 倒挂：计划 3.2 明确接受该现实，
        # 「顺序可追溯」由 steps_data 的位置承担（落轮时按 enumerate 下标生成 step 字段），
        # 故只放宽严格递增，不放宽唯一性
        seqs = [_shot_seq(s["screenshot"]) for s in ed.steps_data]
        assert seqs == [1, 4, 3], f"插入位置或截图引用被挪动（B10）：{seqs}"
        assert [s["intent"] for s in ed.steps_data] == [
            intents[0], "插入的新步", intents[2]
        ], (
            f"插入后业务顺序被打乱（B10）：{[s['intent'] for s in ed.steps_data]}"
        )
        assert_screenshot_order(ed, strict_monotonic=False, allow_holes=True)
        assert_all(ed)


# ----------------------------------------------------------------------
# DI-18：_finish_task 拒收早退前未同步侧栏
# ----------------------------------------------------------------------

class TestDI18:
    """DI-18：_finish_task 先把「已截图未填写」的当前步落表，再因缺项拒收 return。

    修复前的因果链：
    ① _save_current_to_steps 见 current_step == len(steps_data) 且已有截图 → append，
       steps_data 比侧栏条目多出一条；
    ② 随后的必填校验命中该新步 → 走拒收分支直接 return，不重建侧栏；
    ③ 侧栏条目数落后于模型、缺填标记停在旧步骤集合上（INV-8 破坏），用户看不到
       刚被拦下的那一步，也就无法按清单跳转去补填。
    修复：弹清单前 sidebar.rebuild_items()（内部重算缺项缓存与条目标记）。
    """

    def test_reject_path_rebuilds_sidebar(self, editor_factory, modal):
        ed = editor_factory()
        confirm_n_steps(ed, 2, action="click")

        capture_and_wait(ed)   # 第 3 步只截图、不填表 → 结束校验必然拒收
        ed._finish_task()
        flush_events(100)

        assert len(ed.steps_data) == 3, (
            f"用例前提不成立：拒收前当前步未落表，steps_data={len(ed.steps_data)}"
        )
        assert not ed._task_completed, "必填项缺失却被判定为已结束"
        assert_sidebar(ed)


# ----------------------------------------------------------------------
# DI-19：live 步豁免截图磁盘存在性校验（B24）
# ----------------------------------------------------------------------

class TestDI19:
    """DI-19 = B24：validate_step_at 对 live 步跳过磁盘存在性 → 交付悬空截图引用。

    草稿恢复回来的当前步、以及 _finish_task 里刚 append 的当前步，其截图引用来自
    磁盘而非本次实时拍摄；一旦 PNG 不在（被外部删除、被旧清理逻辑误删），旧校验
    给出「通过」，交付 JSON 便引用不存在的文件，下游读取直接崩。
    修复：取消 is_live 豁免；实时截图一律先落盘成功再置三指针，故正常采集中不会误判。
    """

    def _resumed_at_step0(self, editor_factory, modal):
        """采 2 步落草稿 → 新编辑器续采 → 回到第 0 步（成为 live 步）。"""
        ed = editor_factory()
        confirm_n_steps(ed, 2, action="click")
        ed._write_draft_now()
        flush_events()
        draft = ed.data_manager.load_draft(ed.gui_number)
        assert draft is not None, "用例前提不成立：草稿未落盘"

        resumed = editor_factory(auto_init=False)
        resumed.load_from_draft(draft)
        flush_events(100)
        resumed.jump_to_step(0)
        flush_events(50)
        assert resumed.current_step == 0, "用例前提不成立：未能停在第 0 步"
        assert resumed._current_screenshot_filename, (
            "用例前提不成立：第 0 步未进入 live 态（旧实现正是在该态豁免磁盘校验）"
        )
        return resumed

    def test_live_step_still_checks_png_on_disk(self, editor_factory, modal):
        resumed = self._resumed_at_step0(editor_factory, modal)
        filename = resumed._current_screenshot_filename
        os.remove(os.path.join(resumed.gui_dir, filename))

        reasons = resumed.validate_step_at(0)
        assert any("截图文件缺失" in r for r in reasons), (
            f"live 步（草稿恢复回来的当前步）未校验 PNG 存在性（B24）：{reasons}"
        )

    def test_finish_task_blocks_dangling_screenshot(self, editor_factory, modal):
        resumed = self._resumed_at_step0(editor_factory, modal)
        filename = resumed._current_screenshot_filename
        os.remove(os.path.join(resumed.gui_dir, filename))

        resumed._finish_task()
        flush_events(100)

        final_json = os.path.join(resumed.gui_dir, f"gui_{resumed.gui_number}.json")
        assert not os.path.exists(final_json), (
            f"当前步截图文件已不存在却仍完成交付（B24）：{final_json} "
            f"引用了缺失的 {filename}"
        )


# ----------------------------------------------------------------------
# DI-20：顶层 screen_size 被每张截图覆写（B23）
# ----------------------------------------------------------------------

def _png_size(path):
    pixmap = QPixmap(path)
    assert not pixmap.isNull(), f"截图文件无法加载：{path}"
    return pixmap.width(), pixmap.height()


class TestDI20:
    """DI-20 = B23：顶层 screen_info["screen_size"] 被每张截图无条件覆写。

    采集会话中设备分辨率抖动（重连、旋转、换设备）时，第 2 张起的截图尺寸会覆盖
    整轮交付尺寸；而本轮首张截图才是与各步轨迹对应的尺寸口径。
    修复：只由「本轮首张追加截图」定版；蒙版坐标映射用的 _phone_w/_phone_h 仍逐张
    跟随实际截图，两者必须各断言一次，防止「不覆写」被误做成「不更新蒙版」。
    """

    def test_mid_session_resolution_change_keeps_screen_size(self, editor_factory, modal):
        ed = editor_factory()
        capture_and_wait(ed)
        fill_valid_step(ed, action="click", intent="第1步")
        ed.confirm_step()
        flush_events(50)

        assert ed.screen_info["screen_size"] == [360, 640], (
            f"用例前提不成立：本轮首张截图未按实际尺寸定版："
            f"{ed.screen_info['screen_size']}"
        )

        # 模拟会话中设备分辨率抖动：第 2 张截图换成 480x960
        ed.screen_capture = FakeAndroidScreenCapture(count=8, width=480, height=960)
        capture_and_wait(ed)
        flush_events(50)

        second = os.path.join(ed.gui_dir, ed._current_screenshot_filename)
        assert _png_size(second) == (480, 960), (
            f"用例前提不成立：第 2 张截图未按新分辨率落盘：{_png_size(second)}"
        )
        assert (ed._phone_w, ed._phone_h) == (480, 960), (
            f"蒙版映射尺寸未跟随实际截图（修复做过头）："
            f"{ed._phone_w}x{ed._phone_h}"
        )
        assert ed.screen_info["screen_size"] == [360, 640], (
            f"中途一张截图覆写了整轮交付尺寸（B23）：{ed.screen_info['screen_size']}"
        )


# ----------------------------------------------------------------------
# DI-22：一步脏 action 不得中断整轮编辑写回（B49）
# ----------------------------------------------------------------------

def _read_coords_entries(gui_dir, gui_number):
    """读回已交付 coords 文件的条目列表，兼容 Android 的 {"version","coords"} 外层。"""
    path = os.path.join(gui_dir, f"gui_{gui_number}_coords.json")
    assert os.path.isfile(path), f"coords 文件不存在：{path}"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        entries = data.get("coords")
        assert isinstance(entries, list), f"coords 外层结构异常：{data!r}"
        return entries
    assert isinstance(data, list), f"coords 外层结构异常：{data!r}"
    return data


class TestDI22:
    """DI-22 = B49：交付 JSON 里的 action 脏（缺 action 键 / actions 为空）时，
    编辑写回必须整轮成功。

    _build_coords_entry 处在整轮落盘（save_edited_round / _save_current_round_to_list）
    的逐步循环里，旧写法用 action_data["action"] 直接下标，一步脏数据抛 KeyError 就
    中断整轮写回——连用户真正改好的那一步也存不进去。
    产品路径可达：load_from_completed_json 用 copy.deepcopy(actions[0]) 原样取磁盘
    action，不经任何键校验或规范化（iOS 端同功能一直是 .get("action", "")）。
    """

    def test_action_missing_key_does_not_abort_writeback(self, editor_factory, modal):
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory, modal)

        def mutate(data):
            # 历史数据里某步的 action 缺 "action" 键（外部工具产出 / 早期版本写入）。
            # 必须是第 2 步：载入后 current_step=0，第 0 步会被表单落表覆盖掉脏数据
            action = data["messages"][1]["trajectory"][1]["actions"][0]
            action.pop("action", None)

        json_path = _tamper_final_json(gui_dir, gui_number, mutate)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=0)
        assert len(ed2.steps_data) == 3, f"编辑现场步数异常：{ed2.steps_data}"
        assert "action" not in ed2.steps_data[1]["action_data"], (
            "用例前提不成立：脏 action 键在载入时已被补全，检验不到崩溃路径"
        )

        ed2.intent_input.setText("修复后仍应写回的意图")
        assert ed2.save_edited_round(True) is True, (
            "含脏 action 键的轮次编辑写回被中断（B49）"
        )
        flush_events(50)

        with open(json_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        traj = saved["messages"][1]["trajectory"]
        assert traj[0]["intent"] == "修复后仍应写回的意图", (
            "写回被中断后，用户的修改静默丢失"
        )
        assert "action" not in traj[1]["actions"][0], (
            f"写回时给用户数据凭空补了 action 键：{traj[1]['actions'][0]}"
        )
        assert not _tmp_leftovers(gui_dir), (
            f"写回残留临时文件：{_tmp_leftovers(gui_dir)}"
        )

    def test_empty_actions_still_writes_all_coords(self, editor_factory, modal):
        """某步 actions 为空 → 载入后 action_data 为空 dict，同样曾抛 KeyError。"""
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory, modal)

        def mutate(data):
            data["messages"][1]["trajectory"][1]["actions"] = []

        _tamper_final_json(gui_dir, gui_number, mutate)

        ed2 = editor_factory(auto_init=False)
        open_edit_mode(ed2, gui_dir, round_index=0)
        assert ed2.steps_data[1]["action_data"] == {}, (
            f"用例前提不成立：空 actions 未被载入为空 action_data："
            f"{ed2.steps_data[1]['action_data']}"
        )

        assert ed2.save_edited_round(True) is True, (
            "含空 actions 的轮次编辑写回被中断（B49）"
        )
        flush_events(50)

        entries = _read_coords_entries(gui_dir, gui_number)
        assert len(entries) == len(ed2.steps_data), (
            f"一步脏数据毁掉整轮 coords：{entries}"
        )
        assert [e.get("step") for e in entries] == list(range(len(entries))), (
            f"coords 步序不连续：{entries}"
        )
        assert entries[1].get("action") == "", (
            f"脏步的 action 应落为空串而不是被丢弃或伪造：{entries[1]}"
        )
        assert not _tmp_leftovers(gui_dir), (
            f"写回残留临时文件：{_tmp_leftovers(gui_dir)}"
        )


# ----------------------------------------------------------------------
# DI-24：交付 coords 必须能判定归属轮次（B4/B18 + B35，计划 4.2/4.3）
# ----------------------------------------------------------------------

_LEGACY_VERTICES = {
    0: [10, 20, 110, 120],
    1: [20, 30, 120, 130],
    2: [200, 300, 320, 420],
}


def _build_legacy_coords_dataset(gui_dir, gui_number):
    """落盘一份「旧格式 coords（条目不带 round）」的三轮已交付任务。

    刻意造出「靠 step 变小切段」必然失效的两个条件：
    ① 第 3 轮只有 answer 步（无坐标语义），于是扁平 coords 只切出 2 段却有 3 轮；
    ② 第 1 轮与第 2 轮的 (step, action) 签名重复（都是 step 0 的 click）。
    每步都产出一条 coords 条目（含 answer 步），与产品落盘口径一致。
    """
    rounds_spec = [
        ("第1轮指令", [(0, "click"), (1, "click")]),
        ("第2轮指令", [(0, "click")]),
        ("第3轮指令", [(0, "answer")]),
    ]

    messages = []
    coords_entries = []
    shot_index = 0
    vertices_index = 0
    for instruction, steps in rounds_spec:
        messages.append({"role": "user", "instruction": instruction})
        trajectory = []
        for step_no, action in steps:
            shot_index += 1
            filename = f"gui_{gui_number}_{shot_index:04d}.png"
            with open(os.path.join(gui_dir, filename), "wb") as f:
                f.write(FakeAndroidScreenCapture._render_png(shot_index, 360, 640))
            action_data = {"action": action}
            if action == "answer":
                action_data["text"] = "回答"
            else:
                action_data["coordinate"] = [30 + vertices_index, 40]
            trajectory.append({
                "step": step_no,
                "intent": f"第{step_no}步",
                "CoT": "",
                "observation": {
                    "screenshot": filename,
                    "active_window": "",
                    "ui_tree_segment": "",
                },
                "actions": [action_data],
            })
            entry = {"step": step_no, "action": action}
            if action != "answer":
                entry["vertices"] = list(_LEGACY_VERTICES[vertices_index])
                entry["center"] = [30 + vertices_index, 40]
                vertices_index += 1
            coords_entries.append(entry)
        messages.append({"role": "assistant", "trajectory": trajectory})

    data = {
        "platform": "Android",
        "system": "Android 13",
        "screen_size": [360, 640],
        "task_type": "Android-测试",
        "messages": messages,
    }
    with open(os.path.join(gui_dir, f"gui_{gui_number}.json"), "w",
              encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(gui_dir, f"gui_{gui_number}_coords.json"), "w",
              encoding="utf-8") as f:
        json.dump({"version": "3.0", "coords": coords_entries}, f,
                  ensure_ascii=False, indent=2)
    return coords_entries


class TestDI24:
    """coords 条目不带 round 时，多轮交付的顶点会被静默配到别的轮次上。"""

    def test_delivered_coords_carry_round_index(self, editor_factory, modal):
        """两轮采集收尾：交付 coords 每条都带 round，且能在所属轮的轨迹里对上。"""
        gui_dir, gui_number, rounds = _prepare_two_round_task(editor_factory, modal)

        entries = _read_coords_entries(gui_dir, gui_number)
        assert len(entries) == 6, f"期望 6 条 coords（每轮 3 步）：{entries}"
        # 轮内 step 每轮都从 0 起重编：扁平文件里 step 必然重复，没 round 就无从判归属
        assert [e["step"] for e in entries] == [0, 1, 2, 0, 1, 2], (
            f"交付 coords 的 step 序列异常：{entries}"
        )
        rounds_seen = set()
        for entry in entries:
            round_index = entry.get("round")
            assert isinstance(round_index, int) and not isinstance(round_index, bool), (
                f"交付 coords 条目缺 round，无法判定归属轮次（B4/B18）：{entry}"
            )
            trajectory = rounds[round_index]["trajectory"]
            matched = [
                t for t in trajectory
                if t.get("step") == entry["step"]
                and (t.get("actions") or [{}])[0].get("action") == entry["action"]
            ]
            assert matched, (
                f"coords 条目的 round 与所属轮轨迹对不上（B4/B18）：{entry}"
            )
            rounds_seen.add(round_index)
        assert rounds_seen == {0, 1}, f"coords 未覆盖全部轮次：{rounds_seen}"

    def test_legacy_coords_without_round_align_by_trajectory(
        self, editor_factory, modal
    ):
        """旧格式（无 round）+ 段数≠轮数：逐段选未占用轮次，第 2 轮拿到自己的顶点。

        旧写法把 (step, action) 用 setdefault 映射到首个命中的轮次：两条
        (0, click) 全挤进第 1 轮，于是第 2 轮一条坐标都拿不到——编辑它时拉框
        全空，用户只能重新拉框并把错配顶点写回交付数据。
        """
        gui_dir, gui_number, _ = _prepare_completed_task(editor_factory, modal)
        coords_entries = _build_legacy_coords_dataset(gui_dir, gui_number)

        ed = editor_factory(auto_init=False)
        open_edit_mode(ed, gui_dir, round_index=1)

        groups = ed._coords_rounds
        assert [len(g) for g in groups] == [2, 1, 1], (
            f"旧格式 coords 归轮错配（B35）：{[len(g) for g in groups]}"
        )
        assert sum(len(g) for g in groups) == len(coords_entries), "coords 条目被丢弃"
        assert len(ed.steps_data) == 1
        assert ed.steps_data[0]["vertices"] == _LEGACY_VERTICES[2], (
            f"第 2 轮拿到的是别的轮次的拉框（B35）：{ed.steps_data[0]['vertices']}"
        )
        assert groups[1][0]["vertices"] == _LEGACY_VERTICES[2], (
            f"第 2 轮的坐标条目不是它自己的顶点（B35）：{groups[1][0]}"
        )


# ----------------------------------------------------------------------
# DI-27：交付 JSON 写盘失败绝不弹「任务完成」（B31）
# ----------------------------------------------------------------------

class TestDI27:
    """DI-27 = B31：写盘失败后谎报「已保存到 gui_N/」= 用户以为已交付、实际只剩草稿。

    Android 的完成框是实例化 QMessageBox + exec_（已由 modal 夹具计数），失败分支
    改走 QMessageBox.critical；conftest 未拦截 critical（offscreen 下会真模态阻塞），
    故本例就地把它换成记录器：既防阻塞，也能正向断言「写盘失败必须明确报错」。
    """

    def test_write_failure_does_not_claim_success(self, editor_factory, modal,
                                                 monkeypatch):
        ed = editor_factory()
        gui_dir = gui_dir_of(ed)
        json_path = os.path.join(gui_dir, f"gui_{ed.gui_number}.json")
        draft_path = os.path.join(
            gui_dir, f"gui_{ed.gui_number}_draft.json"
        )

        # 只走两步、不落轮也不收尾，把落轮 + 写交付件都留给 _finish_task
        walk_rounds(ed, [(2, "第一轮指令")], finish_action=None, modal=modal)
        ed._write_draft_now()
        assert os.path.isfile(draft_path), (
            f"用例前提不成立：走两步后草稿未落盘：{draft_path}"
        )

        # 模拟写盘失败（磁盘满 / 权限 / 占用都以 None 为返回口径）
        monkeypatch.setattr(
            ed.data_manager, "save_json_data", lambda *a, **k: None
        )
        critical_calls = []

        def fake_critical(parent=None, title="", text="", *args, **kwargs):
            critical_calls.append((title, text))

        monkeypatch.setattr(
            annotation_editor.QMessageBox, "critical", fake_critical
        )
        finish_boxes = []

        def fake_exec(box):
            finish_boxes.append(box.windowTitle())
            return modal.finish_reply

        monkeypatch.setattr(annotation_editor.QMessageBox, "exec_", fake_exec)

        # 走产品入口：确认 answer_terminate 步触发 _finish_task
        capture_and_wait(ed)
        fill_valid_step(ed, action="answer_terminate", intent="收尾",
                        text="收尾回答")
        ed.confirm_step()
        flush_events(100)

        assert "任务完成" not in finish_boxes, (
            f"交付 JSON 未写成却弹了「任务完成」（B31）：{finish_boxes}"
        )
        assert critical_calls and critical_calls[0][0] == "保存失败", (
            f"写盘失败没有明确报错，用户无从知晓数据未交付（B31）："
            f"{critical_calls}／弹窗 {finish_boxes}"
        )
        assert not os.path.isfile(json_path), (
            f"save_json_data 已返回 None，目录里却出现了交付件：{json_path}"
        )
        assert ed._task_completed is False, (
            "写盘失败却把任务标记成已完成，closeEvent 会据此跳过草稿落盘（B31）"
        )
        # 失败即中止：草稿原样保留，下次开屏仍可续采
        assert os.path.isfile(draft_path), (
            f"写盘失败时把续采草稿一并弄丢了（B31）：{draft_path}"
        )
        draft, _err = DataManager.load_draft_from_dir(gui_dir)
        assert draft is not None, (
            "磁盘草稿读不出来，该任务已从续采列表静默消失"
        )
