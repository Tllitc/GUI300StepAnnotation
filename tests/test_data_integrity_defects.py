# -*- coding: utf-8 -*-
"""数据完整性缺陷回归测试组（DI 系列，Windows 端）。

DI 编号 ↔ 缺陷映射（三端共用同一编号，便于交叉对照）::

    DI-1  = B20a  Android 落轮后不清 steps_data → 草稿重建 → 多轮折叠
    DI-2  = B19   Android 续采追问指令取消分支缺失 → 整轮静默丢弃
    DI-3  = B30/B11 编辑模式的重截图/删步/撤销改盘边界
                  （需求变更：产品上**允许**编辑模式重截图与删步，故对应用例
                   断言「允许改盘，但必须原地覆盖同名文件、不越界写盘、
                   不误删他轮引用」，而非「一律拦截」）
                  （本端改盘面：recapture_current_step → on_recapture_completed 以
                   当前步的 screenshot_filename 调 save_screenshot_overwrite 原地覆盖
                   （annotation_editor.py:1704-1710），删步经 _delete_screenshot_file
                   查 rounds 后才 os.remove（:2011-2032）；用例见 TestDI3）
    DI-4  = B16/B17 删图只查 steps_data 不查 rounds → 删掉已落轮仍引用的 PNG
                  （**本端等价保护即既有 DT-6**：_delete_screenshot_file 删除前逐轮
                   扫 trajectory 引用，命中则跳过（annotation_editor.py:2020-2026），
                   回归用例已在 tests/test_dt_defects.py:225（TestDT6 双向断言：
                   被引用不删 / 无引用须删）；同一防线不重复建例，仅登记编号以保持
                   三端映射表同步）
    DI-5  = B6    Windows scroll 步拉框顶点永久不进 coords
                  （修复：校验层与 coords 采集层改为共用模块级 COORD_ACTION_TYPES，
                   口径与 invariants.COORD_ACTION_TYPES 钉住，不再两处各自列举）
    DI-6  = B40/B41 编辑写回全量重建 messages / 空 coords 覆盖原文件
    DI-7  = B38/B10 截图序号分配语义与空洞/插入治理
                  （修复仅落 Android：Windows get_next_screenshot_number 本就返回
                   磁盘 max+1，无 B38 类空洞复用；B10 倒挂由 INV-11 口径接受（assert_all
                   传 strict_monotonic=False），本端无新增可变异缺陷，仅登记以保持
                   三端映射表同步）
    DI-8  = B2    singleShot(300) 竞态窗口内重复落轮
    DI-9  = B37   iOS 空现场不删残留草稿 → 续采复活已删步骤
                  （**本端已具备等价保护**：Windows _write_draft_now 走 DT-1 口径，
                   steps 与 rounds 皆空但 gui_number 仍在时照样落一份空草稿覆盖磁盘
                   残留（annotation_editor.py:2634-2636），已删步骤不会借草稿复活；
                   仅登记编号以保持三端映射表同步）
    DI-10 = B50   save_screenshot(filename=) 无校验 → 路径穿越写出 gui_dir
                  （**本端已具备等价保护**：Windows 唯一的按名写盘入口是
                   save_screenshot_overwrite，其开头即做 basename 归一 + `gui_{编号}_`
                   前缀 + png/jpg 后缀三重校验，不通过直接返回 None（data_manager.py
                   :161-170），调用方据此报「保存截图失败！」；校验失效即为越界写盘，
                   故回归用例并入本端 TestDI3，不单建同名类）
    DI-11 = B1/B28 answer 后取消新轮不重置工作区
    DI-12 = 计划 1.4 最终 JSON 直接 open(w) 覆盖写、无备份
                  （无对应 Bxx：写盘中途中断会留下半截/空文件，已交付数据不可恢复）
    DI-13 = B3    编辑模式轮次选择摘要撞车 → 改错轮并写回（计划 1.6）
    DI-14 = B15   Windows 摘页只 removeWidget/setParent(None) → 步骤页变游离
                  顶层窗口泄漏（仅 Windows：iOS/Android 无 QStackedWidget 步骤页模型）
    DI-15 = B14   三端 续轮指令取消后沿用旧 instruction → 新一轮轨迹静默挂到
                  上一条已被消费的指令上（取消即置空 + 落轮前强校验非空，
                  缺指令先弹窗补齐、补齐失败则拒绝落轮并保持现场）
    DI-16 = B42   落轮时把本轮的 action 活对象直接放进 rounds → rounds 与 steps_data
                  共享同一个 dict，原地改写会回写到已落轮数据
                  （**本端不适用**：Windows save_current_round 是轮次结束时唯一落盘点，
                   其中 step_data = copy.deepcopy(editor.get_data())（DT-4），且
                   _collect_coords_entries 产生的条目全为新建字面量列表，已具备
                   等价保护；仅登记编号以保持三端映射表同步，不写无法变异的假绿用例）
    DI-17 = B22   采集中回看历史步、确认后 current_step 被推到 len(steps_data)
                  → 用户被传送到末尾、表单被清空（Android/iOS 同形带病已修）
                  （**本端不适用**：Windows 用 QStackedWidget 每步一页 +
                   current_step_index，无 confirm_step 的「确认后新建空步」传送
                   语义，display_step 才是唯一导航入口；仅登记编号以保持三端
                   映射表同步，不写无法变异的假绿用例）
    DI-18 = 计划 3.x _finish_task 校验拒收后 return 早退，却已把未落表的当前步
                  追加进模型而侧栏未同步 → 侧栏与模型步数错位
                  （**本端已具备等价保护**：拒收分支在弹缺失清单前先调
                   revalidate_all_missing() + refresh_step_item() + refresh_dashboard()
                   （annotation_editor.py:2415-2421），静默关闭路径同样调
                   revalidate_all_missing()（:3056-3059）；且 Windows 的当前步在确认
                   时即成页，不存在「拒收时模型刚被追加一步」的时序；仅登记编号）
    DI-19 = B24   草稿恢复的 live 步豁免磁盘 PNG 存在性校验 → 引用已缺失截图的
                  数据被放行交付（仅 Android：其 validate_step_at 原有 `elif not
                   is_live` 豁免，已改为无条件校验）
                  （**本端不适用**：Windows validate_step_at（:1462）只校验 intent /
                   坐标 / key / wait / 文本，全函数没有截图存在性条目，因而不存在
                   「豁免」形态；缺失截图的防线是草稿恢复后（:2744-2749）与编辑
                   加载后（:2978-2983）的「截图文件缺失」弹窗；仅登记编号）
    DI-20 = B23   每张截图都把 screen_info["screen_size"] 覆写为当次尺寸 → 会话中
                  设备分辨率抖动会让整轮交付尺寸等于最后一张（Android/iOS 已修）
                  （**本端不适用**：Windows 本就有同形守卫——仅当
                   len(self.steps) == 0 且 insert_after is None 且 pixmap 非空时才
                   定版 screen_size（annotation_editor.py:1840-1846）；已具备等价
                   保护，仅登记编号）
    DI-21 = B44   每次截图生成唯一名临时文件却不回收 → 临时目录逐张累积泄漏
                  （仅 iOS：其临时名带唯一后缀，已改为下一次截图时回收上一张，
                   keep 集合为 {screenshot_cache, _current_screenshot_filepath}）
                  （**本端不适用**：Windows 截图链路不落中间临时文件（直接抓取
                   屏幕写入目标路径，screenshot_capture.py 无 tmp/tempfile 用法），
                   无泄漏面；Android 用固定临时名逐张覆盖，同样不累积；仅登记编号）
    DI-22 = B49   _build_coords_entry 用 action_data["action"] 直接下标 → 脏数据抛
                  KeyError/TypeError 并中断整轮落盘（仅 Android）
                  （**本端不适用**：Windows _collect_coords_entries 的 action 取自页面
                   下拉框 currentText（必为字符串）且经 action_type_mapping.get 取值，
                   不对磁盘数据做直接下标；仅登记编号以保持三端映射表同步）
    DI-23 = B12   Windows get_data 两处坐标污染：豁免名单缺 answer_terminate（使回答
                  动作交付无意义的 coordinate）+ 裸 except 把解析不了的坐标静默伪造成
                  [0,0]（旧数据经编辑模式载入后坐标被清零交付，不可恢复）
                  （修复：名单补 answer_terminate；改为 except (ValueError, TypeError)
                   且不写 coordinate 键，交由 validate_step_at 的「坐标缺失」拦截）
    DI-24 = B4/B18 + B35   交付的扁平 coords 条目不带 round → 轮内 step 下标每轮都从 0
                  起重编，(step, action) 在多轮间重复，读取只能靠「step 变小则切段」
                  猜测归属；只要有一轮一个坐标步都没有、或多轮 step 同签名，就整段
                  错位把已交付的顶点配到别的轮次上（编辑那一轮时拿到别人的拉框）
                  （修复：写侧只在序列化边界注入 round（iOS 一直是这个口径，本端为
                   基准）；本端正常路径只保留扁平 all_coords_entries，故在唯一的
                   追加点 save_current_round 上轮下标；读侧段数≠轮数时逐段选未占用
                   且轨迹签名匹配的轮次 + 段内逐条目归入，对不上签名的仍并入
                   最后一轮、绝不丢弃）
    DI-25 = B9    Windows 中途关窗绕过必填校验直接产出 gui_N.json，却不删草稿 →
                  同一目录既「已完成」又「可续采」，两个入口互不知晓、后写者覆盖
                  前写者（计划 5.2）
                  （修复：closeEvent 的非编辑分支只 _write_draft_now()，交付件一律
                   由「完成标注」路径产生；口径对齐 iOS/Android）
    DI-26 = B7+B8 Windows 新任务切换的两处现场标志错误（计划 5.3）
                  B7：create_new_task 先 reset_for_new_task（末尾按 DT-3 立即写空
                     草稿）后换 gui_number，于是把空草稿写进刚交付的目录，已完成
                     任务重新出现在续采列表，用户接着采就往已交付目录重写矛盾草稿
                  B8：_final_data_saved 是「上一批数据已落盘」的一次性标志，不随新
                     现场复位 → 新任务中途关窗被 closeEvent 当成已保存而跳过草稿，
                     整轮进度静默丢失
                  （修复：重置期间抑制草稿写入、拿到新编号后再落第一份草稿；
                   reset_for_new_task 首行复位 _final_data_saved）
    DI-27 = B31   落盘失败仍谎报「当前任务已保存到 gui_N/」→ 用户以为已交付，磁盘
                  上其实只有草稿（计划 5.7；iOS/Android 本端修复）
                  （**本端已具备等价保护**：finish_all_annotation 以 save_json_data 的
                   返回值分支，成功才删草稿 + 弹「保存成功」（annotation_editor.py
                   :3377-3390），失败只 QMessageBox.critical("保存 JSON 失败！") 且
                   保留草稿（:3395-3396）；仅登记编号以保持三端映射表同步）
    DI-28 = B45   删步只取消 swipe 测量、不取消 scroll 长滑测量 → _scroll_measuring
                  残留为 True，后续截图被当成测量补充图塞进 _scroll_extra_screenshots
                  而不落进步骤，那些临时 PNG 再无人回收（计划 5.8；仅 iOS 修复）
                  （**本端不适用**：Windows 长滑测量态挂在每一步自己的页面上，
                   is_measuring_scroll / scroll_references 是页内状态，删步即销毁对应
                   页面（_drop_stack_page），态随页消失，无残留面；Android 删步路径
                   已成对调用 _cancel_scroll_measurement（安卓端:2374-2375）；仅登记
                   编号以保持三端映射表同步，不写无法变异的假绿用例）

本文件当前已落地 DI-3 / DI-5 / DI-6 / DI-8 / DI-11 / DI-12 / DI-13 / DI-14 / DI-15 /
DI-23 / DI-24 / DI-25 / DI-26；其余编号随对应阶段修复同批补入（计划 6.2：
每项修复至少一条回归，不允许先修后补测）。DI-4 由既有 DT-6 用例覆盖，DI-10 由
TestDI3 覆盖。

只依赖 conftest 夹具与 helpers。运行（在项目根目录）::

    python -m pytest tests/test_data_integrity_defects.py -q
"""

import os
import json

from PyQt5 import sip
from PyQt5.QtCore import QEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox

import annotation_editor as _ae
import helpers as H
import invariants as I


# ----------------------------------------------------------------------
# 现场准备
# ----------------------------------------------------------------------

def _tmp_leftovers(gui_dir):
    """原子写的临时文件以 .name.tmp 落在 gui_dir 内，成功后必须消失。"""
    return sorted(n for n in os.listdir(gui_dir) if n.endswith(".tmp"))


def _make_dataset(gui_number):
    """单轮 2 步的最终 JSON 与对应 coords 扁平数组。

    Windows 的最终 JSON 不含 rounds 键：每轮拆成相邻两条 messages
    （role=user 携 instruction、role=assistant 携 trajectory）。
    """
    shot1 = f"gui_{gui_number}_0001.png"
    shot2 = f"gui_{gui_number}_0002.png"

    def step(step_no, intent, shot):
        return {
            "step": step_no,
            "intent": intent,
            "CoT": "",
            "observation": {
                "screenshot": shot,
                "active_window": "测试App",
                "ui_tree_segment": "",
            },
            "actions": [{
                "action": "left_click",
                "coordinate": [200 + step_no * 100, 300],
                "element": "按钮",
                "status": "success",
            }],
        }

    data = {
        "platform": "Windows 11",
        "system": "Windows 11",
        "screen_size": [1920, 1080],
        "task_type": "Windows-测试",
        "messages": [
            {"role": "user", "instruction": "第一轮指令"},
            {"role": "assistant", "trajectory": [
                step(0, "第一轮第一次点击", shot1),
                step(1, "第一轮第二次点击", shot2),
            ]},
        ],
    }
    coords = [
        {"step": 0, "action": "left_click",
         "vertices": [100, 200, 300, 400], "center": [200, 300]},
        {"step": 1, "action": "left_click",
         "vertices": [200, 200, 400, 400], "center": [300, 300]},
    ]
    return data, coords


def _prepare_scene(editor, data, coords):
    """把给定的已交付数据集落盘，并把编辑器切到编辑模式。

    经产品入口 load_from_completed_json 建现场（不经 QFileDialog），与
    test_edit_completed 的既有做法一致；原文件用 json.dump 直写，使首字节
    完全可控，便于断言「.bak 等于写回前的原文件」。

    :return: (gui_dir, gui_number, json_path, original_bytes, original_coords_bytes)
    """
    gui_number = editor.gui_number
    gui_dir = os.path.join(editor.data_manager.current_dir, f"gui_{gui_number}")
    os.makedirs(gui_dir, exist_ok=True)

    json_path = os.path.join(gui_dir, f"gui_{gui_number}.json")
    coords_path = os.path.join(gui_dir, f"gui_{gui_number}_coords.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(coords_path, "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)
    with open(json_path, "rb") as f:
        original_bytes = f.read()
    with open(coords_path, "rb") as f:
        original_coords_bytes = f.read()

    ok = editor.load_from_completed_json(data, coords, 0, gui_dir)
    assert ok, "load_from_completed_json 返回 False，编辑现场未建立"
    assert editor._edit_mode, "载入后未进入编辑模式"
    assert editor.rounds, "载入后未解析出任何轮次，用例失去区分力"
    QTest.qWait(50)
    return gui_dir, gui_number, json_path, original_bytes, original_coords_bytes


def _prepare_edit_scene(editor):
    """用默认单轮数据集建编辑现场（DI-12 系列用）。

    :return: (gui_dir, gui_number, json_path, original_bytes)
    """
    data, coords = _make_dataset(editor.gui_number)
    gui_dir, gui_number, json_path, original_bytes, _ = _prepare_scene(
        editor, data, coords
    )
    return gui_dir, gui_number, json_path, original_bytes


# ----------------------------------------------------------------------
# DI-12：最终 JSON 写盘原子化 + 编辑写回留 .bak（计划 1.4）
# ----------------------------------------------------------------------

class TestDI12:
    """写盘必须原子化；编辑写回覆盖已交付 JSON 前先留一份 .bak 兜底。"""

    def test_save_json_failure_keeps_original_intact(self, editor):
        """DI-12：序列化中途失败时原文件必须一字不改，且不残留 .tmp。

        直接 open(path,"w") 会先截断原文件，json.dump 抛异常就留下半截文件。
        tmp + os.replace 的失败语义是「原文件保持不动」。
        """
        gui_dir = H.gui_dir_of(editor)
        gui_number = editor.gui_number
        dm = editor.data_manager

        good = {
            "platform": "Windows 11",
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

    def test_edit_writeback_keeps_bak_of_original(self, editor):
        """DI-12：编辑写回前必须留下原 JSON 的 .bak，写回后不留 .tmp。"""
        gui_dir, gui_number, json_path, original_bytes = _prepare_edit_scene(editor)
        bak_path = f"{json_path}.bak"
        assert not os.path.isfile(bak_path), "准备阶段不该产生 .bak"

        editor.steps[0]["editor"].intent_input.setText("修改后的意图")
        assert editor.save_edited_round(silent=True) is True, "编辑写回失败"
        QTest.qWait(50)

        # 写回确实改动了原文件，否则下面的 .bak 比对会失去区分力
        with open(json_path, "rb") as f:
            assert f.read() != original_bytes, "编辑写回没有改变 JSON 内容"

        assert os.path.isfile(bak_path), "编辑写回未生成 .bak 备份"
        with open(bak_path, "rb") as f:
            assert f.read() == original_bytes, (
                ".bak 内容不等于写回前的原 JSON（备份时机错了）"
            )
        assert not _tmp_leftovers(gui_dir), (
            f"写回残留临时文件：{_tmp_leftovers(gui_dir)}"
        )

    def test_bak_is_overwritten_not_accumulated(self, editor):
        """DI-12：连续写回只保留最新一份 .bak（覆盖式，不累积历史副本）。"""
        gui_dir, gui_number, json_path, original_bytes = _prepare_edit_scene(editor)
        bak_path = f"{json_path}.bak"

        editor.steps[0]["editor"].intent_input.setText("第一次修改")
        assert editor.save_edited_round(silent=True) is True
        with open(json_path, "rb") as f:
            after_first = f.read()
        assert after_first != original_bytes, "第一次写回没有改变 JSON 内容"

        editor.steps[1]["editor"].intent_input.setText("第二次修改")
        assert editor.save_edited_round(silent=True) is True
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
    """编辑写回只动被编辑轮，其余数据一律原样保留。"""

    def test_writeback_keeps_extra_fields_and_orphan_message(self, editor):
        """DI-6：messages 里的额外字段与非配对消息必须原样保留（B40）。"""
        data, coords = _make_dataset(editor.gui_number)
        data["legacy_top_field"] = "顶层附加字段"
        data["messages"][0]["custom_note"] = "用户消息附加字段"
        data["messages"][1]["cot_source"] = "助手消息附加字段"
        # 末尾一条没有配对 assistant 的 user 消息：它不属于任何轮次，
        # 但属于已交付数据，写回不得把它一并删掉
        orphan = {"role": "user", "instruction": "末尾孤立提问"}
        data["messages"].append(orphan)

        scene = _prepare_scene(editor, data, coords)
        gui_dir, gui_number, json_path, _, _ = scene
        assert len(editor.rounds) >= 1, "孤立消息导致轮次解析异常"

        editor.steps[0]["editor"].intent_input.setText("修改后的意图")
        assert editor.save_edited_round(silent=True) is True, "编辑写回失败"
        QTest.qWait(50)

        saved = H.read_final_json(editor)
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

    def test_writeback_rejects_non_alternating_messages(self, editor):
        """DI-6：messages 不满足严格交替时必须拒写，不得退化成全量重建。"""
        data, coords = _make_dataset(editor.gui_number)
        # 开头插入一条 system 消息，使 messages[0] 不再是本轮的 user
        data["messages"].insert(0, {"role": "system", "content": "系统提示"})

        scene = _prepare_scene(editor, data, coords)
        gui_dir, gui_number, json_path, original_bytes, original_coords_bytes = scene
        assert editor.rounds, "插入 system 后轮次解析为空，用例失去区分力"
        bak_path = f"{json_path}.bak"
        assert not os.path.isfile(bak_path)

        editor.steps[0]["editor"].intent_input.setText("不该被写回的意图")
        assert editor.save_edited_round(silent=True) is False, (
            "messages 结构不匹配时竟然写回成功了"
        )
        QTest.qWait(50)

        with open(json_path, "rb") as f:
            assert f.read() == original_bytes, "拒写失败：原 JSON 已被改动"
        coords_path = os.path.join(gui_dir, f"gui_{gui_number}_coords.json")
        with open(coords_path, "rb") as f:
            assert f.read() == original_coords_bytes, "拒写失败：coords 已被改动"
        assert not os.path.isfile(bak_path), "未发生写回却生成了 .bak"
        assert not _tmp_leftovers(gui_dir), (
            f"拒写路径残留临时文件：{_tmp_leftovers(gui_dir)}"
        )

    def test_empty_coords_does_not_overwrite_delivered_file(self, editor):
        """DI-6：本轮导出 0 条坐标时，不得用空数组覆盖已交付 coords（B41）。"""
        scene = _prepare_scene(editor, *_make_dataset(editor.gui_number))
        gui_dir, gui_number, json_path, _, original_coords_bytes = scene
        coords_path = os.path.join(gui_dir, f"gui_{gui_number}_coords.json")

        # Windows 的 _collect_coords_entries 会跳过无拉框的步骤：把全部
        # 步骤的 rect_info 置空，即可复现“本轮导出 0 条坐标”
        assert editor.steps, "编辑现场没有步骤"
        for step in editor.steps:
            step["rect_info"] = None

        assert editor.save_edited_round(silent=True) is True, "编辑写回失败"
        QTest.qWait(50)

        with open(coords_path, "rb") as f:
            after = f.read()
        assert after == original_coords_bytes, (
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
        # 步数必须进摘要：早前 Windows 只截指令，同指令同轮长就彻底撞车
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

        # 早前 Windows 用 try/except 把定位失败静默兜成 round_index = 0，
        # 等于把用户没选的轮次改成第 1 轮再写回已交付数据
        assert resolve_round_index(index_by_item, "不存在的候选项") is None
        assert resolve_round_index(index_by_item, None) is None
        assert resolve_round_index(None, items[0]) is None
        assert resolve_round_index({}, items[0]) is None


# ----------------------------------------------------------------------
# DI-11：answer 落轮后取消新轮，工作区必须回到空白起点（B1）
# ----------------------------------------------------------------------

def _answer_round_then_cancel(editor, dialogs, n_steps=2):
    """走 n_steps 步 → 末步改为「回答用户」落轮 → 续轮对话框点「取消」。

    :return: 已落轮那一轮各步引用的截图名（顺序与步序一致）。

    answer 分支是 save_current_round（同步）+ singleShot(300) start_new_round
    （异步），故 confirm 后必须推进事件循环等定时器回调跑完，直接断言必然过早。
    """
    H.walk_steps(editor, n_steps)
    last_idx = len(editor.steps) - 1
    H.fill_step(editor, last_idx, action_chinese="回答用户", intent="第一轮回答",
                text="第一轮回答")
    shots = [step["screenshot_filename"] for step in editor.steps]

    dialogs.input_ok = False  # 续轮 QInputDialog 走取消分支
    H.confirm(editor)
    QTest.qWait(500)
    # 2.6（B14）后取消分支会清空 task_instruction，后续落轮必须走「弹窗补齐指令」
    # 这条产品控制流，故恢复默认的自动应答（getText 返回 next_instruction）。
    dialogs.input_ok = True
    return shots


class TestDI11:
    """answer 后取消新轮：不能只改状态文案，必须与接受新轮走同一重置入口。"""

    def test_cancel_new_round_clears_stack_and_step_index(self, editor, dialogs):
        """DI-11 回归（B1）：取消新轮后 stack 只剩空白页、步骤索引复位。"""
        _answer_round_then_cancel(editor, dialogs, n_steps=2)

        assert len(editor.rounds) == 1, (
            f"answer 未落轮，用例前提不成立：{len(editor.rounds)}"
        )
        assert editor.steps == [], f"steps 未清空：{len(editor.steps)}"

        # B1 的核心现场：rounds 已消费掉上一轮，但 stack 里上一轮的编辑页没人拆、
        # current_step_index 仍停在上轮末步、侧栏仍是上轮条目 —— 用户看到的界面
        # 还是上一轮的表单与截图，此时继续采集就接在陈旧状态上。
        assert editor.stack_widget.count() == 1, (
            f"取消新轮后 stack 残留上一轮编辑页：count={editor.stack_widget.count()}"
        )
        assert editor.current_step_index == -1, (
            f"取消新轮后 current_step_index 未复位：{editor.current_step_index}"
        )
        assert editor.stack_widget.currentIndex() == 0, (
            "取消新轮后 stack 未切回空白页"
        )
        assert "已取消新任务" in editor.status_label.text(), (
            f"状态提示未回到可继续采集的口径：{editor.status_label.text()!r}"
        )

        I.assert_stack(editor)
        I.assert_all(editor)

    def test_cancel_new_round_keeps_delivered_round_and_draft(self, editor, dialogs):
        """DI-11 边界回归：重置只清界面，已交付轮次与草稿不得被牵连。"""
        shots = _answer_round_then_cancel(editor, dialogs, n_steps=2)

        assert len(editor.rounds) == 1
        trajectory = editor.rounds[0]["trajectory"]
        assert len(trajectory) == 2, f"已交付轮次步数丢失：{len(trajectory)}"
        blob = json.dumps(editor.rounds[0], ensure_ascii=False)
        for name in shots:
            assert name in blob, f"已交付轮次不再引用截图 {name}"

        draft = H.read_draft(editor)
        assert draft is not None, "取消新轮后草稿未落盘（重置入口未写草稿）"
        assert draft.get("current_steps") == [], (
            f"取消新轮后草稿仍留着上一轮的步骤：{draft.get('current_steps')}"
        )
        assert len(draft.get("rounds") or []) == 1, "草稿 rounds 未同步落盘"

        gui_dir = H.gui_dir_of(editor)
        for name in shots:
            assert os.path.isfile(os.path.join(gui_dir, name)), (
                f"重置过程误删了已交付截图：{name}"
            )

    def test_capture_after_cancel_starts_clean_second_round(self, editor, dialogs):
        """DI-11 后果回归：取消新轮后继续采集应成为干净的下一轮，不与旧界面拼接。"""
        shots = _answer_round_then_cancel(editor, dialogs, n_steps=2)
        first_instruction = editor.rounds[0]["instruction"]

        H.walk_steps(editor, 1)
        assert len(editor.steps) == 1, f"新一轮步数异常：{len(editor.steps)}"
        assert editor.stack_widget.count() == 2, (
            f"新一轮 stack 与 steps 不匹配：count={editor.stack_widget.count()}"
        )
        assert editor.current_step_index == 0, (
            f"新一轮起始索引异常：{editor.current_step_index}"
        )
        new_shot = editor.steps[0]["screenshot_filename"]
        assert new_shot not in shots, (
            f"新一轮复用了已交付截图（轮次折叠）：{new_shot}"
        )
        I.assert_stack(editor)
        I.assert_all(editor)

        json_path = H.finish(editor, action="terminate")
        assert json_path, "最终 JSON 产出失败"
        with open(json_path, "r", encoding="utf-8") as f:
            final = json.load(f)
        user_msgs = [m for m in final["messages"] if m.get("role") == "user"]
        assert len(user_msgs) == 2, (
            f"取消新轮后的第二轮未独立落轮：messages 只含 {len(user_msgs)} 轮指令"
        )
        # 2.6（B14）归属断言：取消续轮清空了指令，第二轮是靠「弹窗补齐」拿到的
        # 新指令落轮的，绝不能继续沿用第一条已被上一轮消费掉的指令。
        assert user_msgs[0]["instruction"] == first_instruction
        assert user_msgs[1]["instruction"] == dialogs.next_instruction, (
            f"第二轮指令不是补齐时输入的新指令：{user_msgs[1]['instruction']!r}"
        )
        assert user_msgs[1]["instruction"] != user_msgs[0]["instruction"], (
            "两轮共用同一条指令 —— 第二轮静默挂到了上一条指令上（B14）"
        )


# ----------------------------------------------------------------------
# DI-14：摘掉的步骤页必须真正销毁，不能变游离顶层窗口（B15）
# ----------------------------------------------------------------------

def _drain(ms=120):
    """推进事件循环，并强制清掉 deleteLater 投递的 DeferredDelete。

    只 qWait 不保证 DeferredDelete 被执行（取决于事件循环层级），显式
    sendPostedEvents 才能把“对象到底销毁了没有”变成确定信号。
    """
    QTest.qWait(ms)
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QTest.qWait(20)


def _alive_orphan_step_pages():
    """B15 的用户可见症状面：脱离 stack 却仍活着的游离步骤页。

    removeWidget 只把页从布局里摘出来，setParent(None) 又把它变成不可见的
    游离顶层窗口 —— 对象连同整张标注预览图一直挂在 QApplication 上，
    删步/撤销/换轮做得越多堆得越多。300 步长任务下这是真正的内存吃紧源。
    """
    return [
        w for w in QApplication.topLevelWidgets()
        if isinstance(w, _ae.StepEditorWidget) and not sip.isdeleted(w)
    ]


def _assert_pages_destroyed(victims, scene):
    """断言 victims 里的编辑页 C++ 对象都已销毁，报出仍存活的下标。"""
    alive = [i for i, w in enumerate(victims) if not sip.isdeleted(w)]
    assert not alive, (
        f"{scene}摘掉的步骤页仍存活（下标 {alive}）：只 removeWidget/setParent(None) "
        f"不会销毁对象，页会带着预览图永久泄漏（B15）"
    )


class TestDI14:
    """B15：删步/撤销/重置/换现场时摘掉的编辑页必须 deleteLater 真正释放。"""

    def test_delete_step_destroys_its_stack_page(self, editor):
        """DI-14 回归（B15）：删中间步，被摘掉的那一页必须被销毁。"""
        H.walk_steps(editor, 3)
        orphans_before = len(_alive_orphan_step_pages())
        victim = editor.steps[1]["editor"]

        editor.display_step(1)
        H.delete_current(editor)
        _drain()

        _assert_pages_destroyed([victim], "删步")
        assert len(_alive_orphan_step_pages()) <= orphans_before, (
            "删步后游离顶层步骤页变多：页只被摘下来晾着，没有真正释放"
        )
        I.assert_stack(editor)
        I.assert_all(editor)

    def test_undo_destroys_last_stack_page(self, editor):
        """DI-14 回归（B15）：撤销末步，最后一页必须被销毁。"""
        H.walk_steps(editor, 3)
        orphans_before = len(_alive_orphan_step_pages())
        victim = editor.steps[-1]["editor"]

        editor.display_step(2)
        H.undo(editor)
        _drain()

        _assert_pages_destroyed([victim], "撤销")
        assert len(_alive_orphan_step_pages()) <= orphans_before, (
            "撤销后游离顶层步骤页变多：页只被摘下来晾着，没有真正释放"
        )
        I.assert_stack(editor)
        I.assert_all(editor)

    def test_reset_for_new_task_destroys_all_step_pages(self, editor):
        """DI-14 回归（B15）：重置现场时旧步骤页必须全部销毁。

        这一处原本连 setParent(None) 都没有 —— 页被 removeWidget 摘出布局后
        仍是 QStackedWidget 的子对象，既看不见也永远不会被释放，是四处里最严重的。
        又因为 answer 落轮开新轮也走这里，长任务里每开一轮就泄一轮的页。
        """
        H.walk_steps(editor, 3)
        orphans_before = len(_alive_orphan_step_pages())
        victims = [s["editor"] for s in editor.steps]

        editor.reset_for_new_task()
        _drain()

        _assert_pages_destroyed(victims, "重置新任务")
        assert editor.stack_widget.count() == 1, (
            f"重置后 stack 应只剩第 0 页空提示页：count={editor.stack_widget.count()}"
        )
        assert len(_alive_orphan_step_pages()) <= orphans_before, (
            "重置后游离顶层步骤页变多：页只被摘下来晾着，没有真正释放"
        )

    def test_load_from_draft_destroys_previous_pages(self, editor):
        """DI-14 回归（B15）：恢复草稿前清场，旧步骤页必须全部销毁。"""
        H.walk_steps(editor, 3)
        H.flush_draft(editor)
        draft = H.read_draft(editor)
        assert draft is not None, "草稿未落盘，用例前提不成立"

        # 现场又长了两步：清场时这 5 页都得销毁，而不是只摘下来晾着
        for i in range(3, 5):
            H.append_step(editor)
            H.fill_step(editor, i, coord_text="250,400")
            H.confirm(editor)
        assert len(editor.steps) == 5, f"用例前提不成立：{len(editor.steps)} 步"
        victims = [s["editor"] for s in editor.steps]
        orphans_before = len(_alive_orphan_step_pages())

        H.reload_from_draft(editor, draft)
        _drain()

        _assert_pages_destroyed(victims, "恢复草稿清场")
        assert len(editor.steps) == 3, (
            f"恢复草稿后步数异常：{len(editor.steps)}"
        )
        assert len(_alive_orphan_step_pages()) <= orphans_before, (
            "恢复草稿后游离顶层步骤页变多：清场只摘页不销毁"
        )
        I.assert_stack(editor)

    def test_edit_scene_rebuild_destroys_previous_pages(self, editor):
        """DI-14 回归（B15）：切到编辑已完成任务时，旧步骤页必须全部销毁。

        编辑模式里每选一个轮次就重建一次现场，不销毁则泄漏量随轮数线性上升。
        """
        H.walk_steps(editor, 3)
        victims = [s["editor"] for s in editor.steps]
        orphans_before = len(_alive_orphan_step_pages())

        _prepare_scene(editor, *_make_dataset(editor.gui_number))
        _drain()

        _assert_pages_destroyed(victims, "编辑模式重建现场")
        assert len(_alive_orphan_step_pages()) <= orphans_before, (
            "切编辑模式后游离顶层步骤页变多：旧现场只摘页不销毁"
        )
        I.assert_stack(editor)


# ----------------------------------------------------------------------
# DI-8：answer/terminate 的 300ms 切轮窗口内不得再启动采集（B2）
# ----------------------------------------------------------------------

def _pngs_in(gui_dir):
    """任务目录内的截图清单（排序后便于做「一条都没多」的等值断言）。"""
    return sorted(n for n in os.listdir(gui_dir) if n.endswith(".png"))


def _answer_round_in_window(editor, dialogs, n_steps=2):
    """走 n_steps 步 → 末步改「回答用户」落轮 → 停在 300ms 切轮窗口内。

    :return: 落轮那轮引用的截图名列表（用于断言窗口内没多出孤儿文件）。

    与 DI-11 的 _answer_round_then_cancel 唯一的区别是不等定时器跑完：这里必须
    停在「rounds 已落轮、新轮对话框还没弹」的竞态窗口里，否则门闩已清、用例失效。
    input_ok=False 让切轮走取消分支 —— 窗口内一旦真起了截图，产出的步骤与 PNG
    就绝对没有任何轮次认领，症状无从辩解成「新轮的正常起步」。
    """
    H.walk_steps(editor, n_steps)
    last_idx = len(editor.steps) - 1
    H.fill_step(editor, last_idx, action_chinese="回答用户", intent=None,
                text="第一轮回答")
    shots = [step["screenshot_filename"] for step in editor.steps]

    dialogs.input_ok = False
    H.confirm(editor)          # 内部 qWait(100)，仍在 300ms 窗口内
    QTest.qWait(20)

    assert len(editor.rounds) == 1, (
        f"answer 未落轮，用例前提不成立：rounds={len(editor.rounds)}"
    )
    assert editor.steps == [], f"answer 后 steps 未清空：{len(editor.steps)}"
    assert editor._round_transition_pending is True, (
        "answer 落轮后未升起切轮门闩：300ms 窗口内的采集会落在旧指令的轮次上（B2）"
    )
    return shots


class TestDI8:
    """B2：answer/terminate 落轮后到对话框回调进场之间有 300ms 窗口，
    期间 task_instruction 仍是旧指令、rounds 已消费掉上一轮，采集入口必须早退。"""

    def test_start_capture_inside_round_window_is_refused(self, editor, dialogs):
        """DI-8 回归（B2）：窗口内 start_capture 不得起摄，也不得落孤儿 PNG。"""
        _answer_round_in_window(editor, dialogs)
        gui_dir = H.gui_dir_of(editor)
        before = _pngs_in(gui_dir)

        Fake = H.get_fake_cls(editor)
        Fake.reset_prepare()
        Fake.prepare_single_box(rect=(120, 220, 320, 420), selection_type="click")

        editor.start_capture()

        # start_capture 一旦被放行，_hide_for_capture 会同步把该标志置 True，
        # 所以这是最锐利的即时信号（不依赖任何定时器时序）
        assert editor._capture_in_flight is False, (
            "切轮窗口内 start_capture 被放行：截图会落在旧指令刚交付的轮次上（B2）"
        )
        assert editor.status_label.text() == "轮次切换中，请稍候...", (
            f"窗口内采集未给出等待口径：{editor.status_label.text()!r}"
        )
        assert editor.steps == [], (
            f"切轮窗口内凭空多出了步骤：{len(editor.steps)}"
        )

        QTest.qWait(600)  # 让 300ms 切轮回调与迟到的 350ms 截图遮罩都跑完
        assert _pngs_in(gui_dir) == before, (
            f"切轮窗口内的截图落成了无人引用的孤儿 PNG："
            f"{set(_pngs_in(gui_dir)) - set(before)}（B2）"
        )
        assert editor.steps == [], (
            f"切轮窗口内的截图最终追加成了步骤：{len(editor.steps)}"
        )
        assert len(editor.rounds) == 1, (
            f"切轮窗口内多落了一轮：rounds={len(editor.rounds)}"
        )
        assert editor._round_transition_pending is False, (
            "切轮回调进场后门闩未释放，采集入口被永久堵死"
        )
        I.assert_stack(editor)
        I.assert_all(editor)

    def test_recapture_inside_round_window_is_refused(self, editor, dialogs):
        """DI-8 回归（B2）：第二条采集入口 recapture_current_step 同样要早退。

        无步骤时 recapture 会委派 start_capture，两条入口必须共用同一道门闩，
        只堵一条则 Ctrl+R 仍能在窗口内起摄。
        """
        _answer_round_in_window(editor, dialogs)
        gui_dir = H.gui_dir_of(editor)
        before = _pngs_in(gui_dir)

        Fake = H.get_fake_cls(editor)
        Fake.reset_prepare()
        Fake.prepare_single_box(rect=(140, 240, 340, 440), selection_type="click")

        editor.recapture_current_step()

        assert editor._capture_in_flight is False, (
            "切轮窗口内 recapture_current_step 被放行：重截图入口绕过了门闩（B2）"
        )
        assert editor.status_label.text() == "轮次切换中，请稍候...", (
            f"窗口内重截图未给出等待口径：{editor.status_label.text()!r}"
        )

        QTest.qWait(600)
        assert _pngs_in(gui_dir) == before, (
            "切轮窗口内的重截图覆盖了已交付同名文件或落成孤儿 PNG（B2）"
        )
        assert editor.steps == []

    def test_capture_inside_terminate_window_is_refused(self, editor, dialogs):
        """DI-8 回归（B2）：terminate 分支的 300ms 后置弹窗同样要设门闩。

        这条分支不单独测就会漏：它走 show_new_task_dialog 而不是 start_new_round，
        早期只有 answer 分支设了护栏，terminate 后连按 Ctrl+Q 能再凑一轮。
        """
        H.walk_steps(editor, 2)
        last_idx = len(editor.steps) - 1
        H.fill_step(editor, last_idx, action_chinese="任务完成", intent=None)
        dialogs.question_result = QMessageBox.No  # 不创建新任务

        H.confirm(editor)
        QTest.qWait(20)
        assert editor._round_transition_pending is True, (
            "terminate 落轮后未升起切轮门闩：300ms 窗口内可重复落轮（B2）"
        )

        gui_dir = H.gui_dir_of(editor)
        before = _pngs_in(gui_dir)
        Fake = H.get_fake_cls(editor)
        Fake.reset_prepare()
        Fake.prepare_single_box(rect=(160, 260, 360, 460), selection_type="click")

        editor.start_capture()
        assert editor._capture_in_flight is False, (
            "terminate 后的切轮窗口内 start_capture 被放行（B2）"
        )

        QTest.qWait(600)
        assert _pngs_in(gui_dir) == before, (
            f"terminate 窗口内的截图落成了孤儿 PNG："
            f"{set(_pngs_in(gui_dir)) - set(before)}（B2）"
        )
        assert len(editor.rounds) == 1, (
            f"terminate 窗口内多落了一轮：rounds={len(editor.rounds)}"
        )
        assert editor._round_transition_pending is False

    def test_capture_works_after_round_window(self, editor, dialogs):
        """DI-8 边界回归：门闩只堵 300ms 窗口，不能把后续采集永久卡死。"""
        _answer_round_in_window(editor, dialogs)

        QTest.qWait(400)  # 等切轮回调进场并释放门闩
        assert editor._round_transition_pending is False, (
            "切轮回调结束后门闩未复位，采集入口被永久堵死"
        )

        H.walk_steps(editor, 1)
        assert len(editor.steps) == 1, f"窗口后新采集未落地：{len(editor.steps)}"
        assert len(editor.rounds) == 1, (
            f"正常采集被误判为重复落轮：rounds={len(editor.rounds)}"
        )
        I.assert_stack(editor)
        I.assert_all(editor)


# ----------------------------------------------------------------------
# DI-15：取消新轮后不得沿用旧指令，缺指令轮次必须拒绝落轮（B14）
# ----------------------------------------------------------------------

_FIRST_INSTRUCTION = "测试指令：在测试App中完成一件事"


class TestDI15:
    """续轮取消置空指令 + 落轮前强校验非空 + 缺指令拒绝落轮并保持现场。"""

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
        H.walk_steps(editor, 1)
        shots = [step["screenshot_filename"] for step in editor.steps]
        getText_before = sum(1 for c in dialogs.calls if c[0] == "getText")

        dialogs.input_ok = False  # 「补齐任务指令」弹窗也取消
        json_path = H.finish(editor, action="terminate")

        assert json_path is None, f"缺少任务指令却写出了交付文件（B14）：{json_path}"
        assert len(editor.rounds) == 1, (
            f"空指令轮被静默落入 rounds：rounds={len(editor.rounds)}"
        )
        # 拒绝落轮必须保持现场：若调用方照常清空 steps，指令错乱就升级成整轮丢失
        assert [s["screenshot_filename"] for s in editor.steps] == shots, (
            f"拒绝落轮时 steps 被清空或改写：{len(editor.steps)} 步"
        )
        assert sum(1 for c in dialogs.calls
                   if c[0] == "getText") == getText_before + 1, (
            "落轮被拒前未弹窗要求补齐本轮任务指令（计划 2.6 要求先补再落）"
        )
        assert "缺少任务指令" in editor.status_label.text(), (
            f"拒绝落轮后未给出可操作的状态提示：{editor.status_label.text()!r}"
        )
        gui_dir = H.gui_dir_of(editor)
        for name in shots:
            assert os.path.isfile(os.path.join(gui_dir, name)), (
                f"拒收过程误删了本轮截图：{name}"
            )
        I.assert_stack(editor)
        I.assert_all(editor)

    def test_supplemented_instruction_lands_on_new_round(self, editor, dialogs):
        """DI-15 修复路径：补齐指令后本轮按新指令落轮，两轮指令互不相同。"""
        _answer_round_then_cancel(editor, dialogs, n_steps=2)
        H.walk_steps(editor, 1)

        dialogs.next_instruction = "补齐的第二轮指令"
        json_path = H.finish(editor, action="terminate")
        assert json_path, "补齐任务指令后最终 JSON 未产出"

        assert len(editor.rounds) == 2, f"补齐后第二轮未落轮：{len(editor.rounds)}"
        assert editor.rounds[1]["instruction"] == "补齐的第二轮指令", (
            f"第二轮落到了别的指令上：{editor.rounds[1]['instruction']!r}"
        )
        final = H.read_final_json(editor)
        instructions = [m["instruction"] for m in final["messages"]
                        if m.get("role") == "user"]
        assert instructions == [_FIRST_INSTRUCTION, "补齐的第二轮指令"], (
            f"交付文件里的指令序列错乱：{instructions}"
        )

    def test_close_path_refuses_without_dialog(self, editor, dialogs):
        """DI-15 边界回归：关窗路径无人值守，不弹模态、不落轮、不写交付件。"""
        _answer_round_then_cancel(editor, dialogs, n_steps=2)
        H.walk_steps(editor, 1)
        getText_before = sum(1 for c in dialogs.calls if c[0] == "getText")

        # 5.2（B9）后关窗不再有「应急落轮并写交付件」的路径，唯一入口是 closeEvent
        editor.close()
        QTest.qWait(100)

        assert sum(1 for c in dialogs.calls
                   if c[0] == "getText") == getText_before, (
            "关闭过程中弹出了模态补齐对话框（退出路径可能永久卡住）"
        )
        assert len(editor.rounds) == 1, (
            f"关闭路径用空指令落了轮：rounds={len(editor.rounds)}"
        )
        assert len(editor.steps) == 1, (
            f"关闭路径清掉了尚未落轮的现场：{len(editor.steps)}"
        )
        json_path = os.path.join(H.gui_dir_of(editor),
                                 f"gui_{editor.gui_number}.json")
        assert not os.path.exists(json_path), (
            "缺指令时仍写出了交付文件（会缺最后一轮）"
        )
        # 无人值守路径唯一的产物必须是可续采草稿，否则那一步进度静默丢失
        draft = H.read_draft(editor)
        assert draft is not None, "关窗未落草稿，未落轮的那一步无法续采"
        assert len(draft["current_steps"]) == 1, (
            f"关窗草稿未保留未落轮的步骤：{len(draft['current_steps'])}"
        )


# ----------------------------------------------------------------------
# DI-5：B6 scroll 步顶点必须进 coords（计划 4.1）
# ----------------------------------------------------------------------

class TestDI5:
    """校验层要求 scroll 必须拉框，采集层却把 scroll 排除在 coords 之外。"""

    def test_scroll_vertices_reach_coords(self, editor):
        """用户按要求给 scroll 拉了框，顶点必须如实出现在交付的 coords 里。"""
        idx = H.append_step(editor, rect=(100, 200, 300, 400))
        H.fill_step(editor, idx, action_chinese="滚动", intent="向下滚动列表",
                    coord_text="250,400", pixels="300")
        assert editor.validate_step_at(idx) == [], (
            f"scroll 步校验未通过，用例失去区分力："
            f"{editor.validate_step_at(idx)}"
        )
        H.confirm(editor)
        H.append_step(editor, rect=(600, 100, 200, 200))  # 末步留给收尾
        assert H.finish(editor, action="terminate"), "收尾未产出最终 JSON"

        coords = H.read_final_coords(editor)
        assert isinstance(coords, list) and coords, f"coords 文件为空：{coords!r}"
        scroll_entries = [c for c in coords if c.get("action") == "scroll"]
        assert len(scroll_entries) == 1, (
            f"scroll 步整条被 coords 丢弃（B6）：{coords}"
        )
        assert scroll_entries[0].get("vertices") == [100, 200, 400, 600], (
            f"拉框顶点未如实落盘：{scroll_entries[0]}"
        )
        assert scroll_entries[0].get("center") == [250, 400], (
            f"中心点计算错乱：{scroll_entries[0]}"
        )

    def test_validation_and_collect_share_coord_action_types(self):
        """校验层与 coords 采集层必须共用同一常量（B6 的根因是两处各自列举）。"""
        assert set(_ae.COORD_ACTION_TYPES) == set(I.COORD_ACTION_TYPES), (
            "产品 COORD_ACTION_TYPES 与不变量口径已漂移："
            f"{set(_ae.COORD_ACTION_TYPES) ^ set(I.COORD_ACTION_TYPES)}"
        )


# ----------------------------------------------------------------------
# DI-23：B12 无坐标语义的动作不写坐标 / 解析不了不伪造 [0,0]（计划 4.6）
# ----------------------------------------------------------------------

class TestDI23:
    """answer_terminate 曾被写入 coordinate:[0,0]；畸形坐标曾被静默清零交付。"""

    def test_answer_terminate_delivers_no_coordinate(self, editor):
        """走完整收尾：交付 JSON 里的回答动作不得带无意义坐标。"""
        H.walk_steps(editor, 1)
        H.append_step(editor)  # 末步留给收尾的回答动作
        json_path = H.finish(editor, action="answer",
                             intent="给出答案", text="已完成")
        assert json_path, "收尾未产出最终 JSON"

        final = H.read_final_json(editor)
        actions = [a for m in final["messages"] if m.get("role") == "assistant"
                   for s in m.get("trajectory", []) for a in s.get("actions", [])]
        answers = [a for a in actions if a.get("action") == "answer"]
        assert answers, f"交付数据里没有 answer 动作：{actions}"
        for a in answers:
            assert "coordinate" not in a, (
                f"回答动作被写入无意义坐标（B12）：{a}"
            )

    def test_unparsable_coordinate_is_dropped_not_zeroed(self, editor):
        """旧数据的非数字坐标回填表单后，get_data 不得伪造 [0,0] 交付。"""
        idx = H.append_step(editor, rect=(100, 200, 300, 400))
        ed = editor.steps[idx]["editor"]
        # 接缝：等价于编辑模式从磁盘载入一条 coordinate 为 ["abc","def"] 的历史
        # 步骤（产品载入时就是这么把磁盘值 str() 后填进只读坐标框的）
        ed.step_data = {
            "intent": "旧数据点击",
            "actions": [{"action": "left_click", "coordinate": ["abc", "def"]}],
        }
        ed.load_data()

        action = ed.get_data()["actions"][0]
        assert "coordinate" not in action, (
            f"畸形坐标被静默替换成 [0,0] 写进交付数据（B12）：{action}"
        )
        assert editor.validate_step_at(idx) == ["坐标缺失（请重新拉框）"], (
            f"缺键后校验层未拦截，脏数据仍可交付："
            f"{editor.validate_step_at(idx)}"
        )


# ----------------------------------------------------------------------
# DI-24：交付 coords 必须能判定归属轮次（B4/B18 + B35，计划 4.2/4.3）
# ----------------------------------------------------------------------

class TestDI24:
    """coords 条目不带 round 时，多轮交付的顶点会被静默配到别的轮次上。"""

    def test_delivered_coords_carry_round_index(self, editor):
        """两轮采集收尾：交付 coords 每条都带 round，且能在所属轮的轨迹里对上。"""
        H.walk_rounds(editor, [(2, "第一轮指令", "click"), (2, "第二轮指令", "click")],
                      finish_action=None)
        H.append_step(editor)  # 末步留给收尾动作（finish 会改写最后一个 step）
        assert H.finish(editor, action="terminate"), "收尾未产出最终 JSON"

        final = H.read_final_json(editor)
        traj_by_round = [m["trajectory"] for m in final["messages"]
                         if m.get("role") == "assistant"]
        assert len(traj_by_round) == 2, f"交付数据不是两轮：{len(traj_by_round)}"

        coords = H.read_final_coords(editor)
        assert coords, "交付 coords 为空"
        # 轮内 step 每轮都从 0 起重编：扁平文件里 step 会重复，没 round 就无从判定归属
        assert [e["step"] for e in coords] == [0, 0, 1], (
            f"交付 coords 的 step 序列异常：{coords}"
        )
        rounds_seen = set()
        for entry in coords:
            round_idx = entry.get("round")
            assert isinstance(round_idx, int), (
                f"交付 coords 条目缺 round，无法判定归属轮次（B4/B18）：{entry}"
            )
            trajectory = traj_by_round[round_idx]
            matched = [s for s in trajectory
                       if s.get("step") == entry["step"]
                       and (s.get("actions") or [{}])[0].get("action") == entry["action"]]
            assert matched, (
                f"coords 条目 (round={round_idx}, step={entry['step']}, "
                f"action={entry['action']}) 在该轮轨迹里对不上，归属错乱：{entry}"
            )
            rounds_seen.add(round_idx)
        assert rounds_seen == {0, 1}, f"coords 未覆盖全部坐标轮次：{rounds_seen}"

    def test_legacy_coords_without_round_align_by_trajectory(self, editor):
        """旧格式（无 round）+ 段数≠轮数：逐段选未占用轮次，第 2 轮拿到自己的顶点。

        旧写法逐条目取首个命中的轮次：第 3 条 (step 0, left_click) 又回到第 1 轮，
        于是第 2 轮一条坐标都拿不到——编辑它时拉框全空，用户只能重新拉框并把
        错配顶点写回交付数据。
        """
        gui = editor.gui_number
        gui_dir = os.path.join(editor.data_manager.current_dir, f"gui_{gui}")
        os.makedirs(gui_dir, exist_ok=True)

        def step(step_no, action, shot_no, coordinate=None):
            action_data = {"action": action}
            if coordinate is not None:
                action_data["coordinate"] = coordinate
            return {
                "step": step_no,
                "intent": f"{action} 第{step_no}步",
                "CoT": "",
                "observation": {
                    "screenshot": f"gui_{gui}_000{shot_no}.png",
                    "active_window": "测试App",
                    "ui_tree_segment": "",
                },
                "actions": [action_data],
            }

        data = {
            "platform": "Windows 11",
            "system": "Windows 11",
            "screen_size": [1920, 1080],
            "task_type": "Windows-测试",
            "messages": [
                {"role": "user", "instruction": "第一轮指令"},
                # coordinate 必须等于下面对应 coords 条目的框中心（INV-14），
                # 否则 hydration 会判定 mismatch 而不采信该框，用例失去区分力
                {"role": "assistant", "trajectory": [
                    step(0, "left_click", 1, [200, 300]),
                    step(1, "left_click", 2, [25, 40])]},
                {"role": "user", "instruction": "第二轮指令"},
                {"role": "assistant", "trajectory": [
                    step(0, "left_click", 3, [600, 700])]},
                {"role": "user", "instruction": "第三轮指令"},
                # 末轮只有无坐标语义的回答步 → coords 里根本没有它对应的条目，
                # 于是「段数 2 ≠ 轮数 3」，旧格式下必须走轨迹签名对齐而非位置对应
                {"role": "assistant", "trajectory": [step(0, "answer", 4)]},
            ],
        }
        legacy_coords = [
            {"step": 0, "action": "left_click",
             "vertices": [100, 200, 300, 400], "center": [200, 300]},
            {"step": 1, "action": "left_click",
             "vertices": [10, 20, 40, 60], "center": [25, 40]},
            {"step": 0, "action": "left_click",
             "vertices": [500, 600, 700, 800], "center": [600, 700]},
        ]
        with open(os.path.join(gui_dir, f"gui_{gui}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        with open(os.path.join(gui_dir, f"gui_{gui}_coords.json"), "w", encoding="utf-8") as f:
            json.dump(legacy_coords, f, ensure_ascii=False, indent=2)

        assert editor.load_from_completed_json(data, legacy_coords, 1, gui_dir) is True
        QTest.qWait(50)

        groups = editor._coords_rounds
        assert [len(g) for g in groups] == [2, 1, 0], (
            f"旧格式 coords 归轮错配（B35）：{[len(g) for g in groups]}"
        )
        assert sum(len(g) for g in groups) == len(legacy_coords), "coords 条目被丢弃"
        assert len(editor.steps) == 1
        assert editor.steps[0]["rect_info"] == (500, 600, 200, 200), (
            f"第 2 轮拿到的是别的轮次的拉框（B35）：{editor.steps[0]['rect_info']}"
        )
        assert groups[1][0]["vertices"] == [500, 600, 700, 800], (
            f"第 2 轮的坐标条目不是它自己的顶点（B35）：{groups[1][0]}"
        )


# ----------------------------------------------------------------------
# DI-25：中途关窗只落草稿，绝不产出交付 JSON（B9，计划 5.2）
# ----------------------------------------------------------------------

class TestDI25:
    """5.2（B9）关窗路径的唯一产物是可续采草稿。"""

    def test_close_midway_writes_draft_only(self, editor, dialogs):
        H.walk_steps(editor, 2)
        gui_dir = H.gui_dir_of(editor)
        json_path = os.path.join(gui_dir, f"gui_{editor.gui_number}.json")
        draft_path = os.path.join(gui_dir, f"gui_{editor.gui_number}_draft.json")
        # 防抖定时器可能已经落过一份草稿：先删掉，把观测量隔离成
        # 「关窗这一次到底写了什么」
        if os.path.exists(draft_path):
            os.remove(draft_path)

        editor.close()
        QTest.qWait(100)

        assert not os.path.exists(json_path), (
            "中途关窗绕过必填校验直接产出交付 JSON（B9）：同一目录既「已完成」又可续采"
        )
        assert os.path.isfile(draft_path), "中途关窗未落草稿，本轮进度静默丢失"
        with open(draft_path, "r", encoding="utf-8") as f:
            draft = json.load(f)
        assert len(draft["current_steps"]) == 2, (
            f"关窗草稿未完整保留本轮步骤：{len(draft['current_steps'])} 步"
        )
        assert draft["rounds"] == [], "关窗时把尚未落轮的轨迹写进了草稿 rounds"


# ----------------------------------------------------------------------
# DI-26：新任务切换不得污染已交付目录，也不得继承「已落盘」标志（B7+B8，计划 5.3）
# ----------------------------------------------------------------------

def _deliver_current_task(editor, monkeypatch):
    """走完「任务完成」交付路径，但把「返回主菜单」推成空操作。

    H.finish 会把 question 预置为 No，于是收尾走 _return_to_init_menu()
    → close() + deleteLater()，同一测试里编辑器就被销毁了，无法继续新任务流程。
    """
    monkeypatch.setattr(editor, "_return_to_init_menu", lambda: None)
    assert H.finish(editor, action="terminate"), "用例前提不成立：交付 JSON 未产出"


class TestDI26:
    """B7：旧目录不得被重新标成「可续采」；B8：新现场必须丢掉「已落盘」标志。"""

    def test_new_task_keeps_delivered_dir_draft_free(self, editor, dialogs, monkeypatch):
        _deliver_current_task(editor, monkeypatch)
        old_gui = editor.gui_number
        old_dir = H.gui_dir_of(editor)
        old_json = os.path.join(old_dir, f"gui_{old_gui}.json")
        assert os.path.isfile(old_json), "用例前提不成立：旧任务未交付"

        dialogs.next_instruction = "新任务的第一个指令"
        editor.create_new_task()
        QTest.qWait(100)

        assert editor.gui_number != old_gui, (
            f"新任务未换编号，仍在写已交付目录：{editor.gui_number}"
        )
        assert not os.path.exists(
            os.path.join(old_dir, f"gui_{old_gui}_draft.json")), (
            "新任务重置时把空草稿写进了刚交付的目录（B7）：已完成任务又回到续采列表"
        )
        assert os.path.isfile(old_json), "新任务切换过程改动了已交付的 JSON"

    def test_new_task_resets_final_saved_flag(self, editor, dialogs, monkeypatch):
        _deliver_current_task(editor, monkeypatch)

        dialogs.next_instruction = "新任务的第一个指令"
        editor.create_new_task()
        QTest.qWait(100)

        # _final_data_saved 只对刚交付的那批数据有效，必须随新现场复位
        assert editor._final_data_saved is False, (
            "新现场继承了上一批数据的「已落盘」标志（B8）"
        )
        # 上一批已交付 → 新编号目录尚未创建；走一步让截图把目录建出来再关窗
        H.walk_steps(editor, 1)
        editor.close()
        QTest.qWait(100)

        assert H.read_draft(editor) is not None, (
            "因 _final_data_saved 未复位，closeEvent 跳过了草稿落盘（B8）"
        )


# ----------------------------------------------------------------------
# DI-3：编辑模式放开重截图，但必须原地覆盖同名文件（B30/B11）
#        同一批断言顺带覆盖 DI-10（B50）：按名写盘入口不得越界写盘
# ----------------------------------------------------------------------

def _write_fake_pngs(gui_dir, names):
    """_make_dataset 只落 JSON，截图 PNG 需自己预置可区分的假字节。"""
    payload = {}
    for name in names:
        blob = b"PLACEHOLDER-" + name.encode("utf-8")
        with open(os.path.join(gui_dir, name), "wb") as f:
            f.write(blob)
        payload[name] = blob
    return payload


class TestDI3:
    """需求变更：编辑模式允许重截图，安全网是「原地覆盖 + 不越界写盘」。"""

    def test_edit_mode_recapture_overwrites_same_file(self, editor):
        """DI-3：重截图只覆盖原序号文件，不新增截图、不误改其他步。"""
        gui_dir, gui_number, json_path, _ = _prepare_edit_scene(editor)
        shot1 = f"gui_{gui_number}_0001.png"
        shot2 = f"gui_{gui_number}_0002.png"
        original = _write_fake_pngs(gui_dir, [shot1, shot2])
        names_before = sorted(os.listdir(gui_dir))

        H.recapture(editor, 0)

        assert sorted(os.listdir(gui_dir)) == names_before, (
            "编辑模式重截图新增/删除了文件，未原地覆盖同名文件"
        )
        with open(os.path.join(gui_dir, shot1), "rb") as f:
            shot1_after = f.read()
        assert shot1_after[:4] == b"\x89PNG", (
            f"原截图文件未被新图覆盖，仍是假字节 {shot1_after[:16]!r}"
        )
        with open(os.path.join(gui_dir, shot2), "rb") as f:
            assert f.read() == original[shot2], (
                "重截图第 0 步却改动了第 1 步的截图文件"
            )
        assert editor.steps[0]["screenshot_filename"] == shot1, (
            "重截图后步骤改指别的文件名，交付引用将与磁盘脱节"
        )

        editor.steps[0]["editor"].intent_input.setText("重截图后的意图")
        assert editor.save_edited_round(silent=True) is True, "编辑写回失败"
        QTest.qWait(50)

        saved = H.read_final_json(editor)
        shots = [
            entry["observation"]["screenshot"]
            for message in saved["messages"]
            if message.get("role") == "assistant"
            for entry in message.get("trajectory", [])
        ]
        assert shots == [shot1, shot2], f"交付的截图引用异常：{shots}"
        for name in shots:
            assert os.path.isfile(os.path.join(gui_dir, name)), (
                f"交付引用了磁盘上不存在的截图 {name}"
            )

    def test_recapture_rejects_filename_outside_gui_dir(self, editor, monkeypatch):
        """DI-10（B50）：越界/异编号文件名必须拒写并明确报错，不得静默降级。"""
        gui_dir, gui_number, _json, _ = _prepare_edit_scene(editor)
        shot1 = f"gui_{gui_number}_0001.png"
        original = _write_fake_pngs(gui_dir, [shot1])
        names_before = sorted(os.listdir(gui_dir))
        parent_dir = os.path.dirname(gui_dir)

        # 夹具里的 critical 是 staticmethod 且不记录，这里换成记录器以断言报错
        critical_calls = []
        monkeypatch.setattr(
            _ae.QMessageBox, "critical",
            lambda parent=None, title="", text="", *a, **kw: (
                critical_calls.append((title, text))
            ),
        )

        # 路径穿越：目标名越出 gui_dir
        evil_name = f"evil_{gui_number}.png"
        editor.steps[0]["screenshot_filename"] = os.path.join("..", evil_name)
        H.recapture(editor, 0)

        evil_path = os.path.join(parent_dir, evil_name)
        assert not os.path.exists(evil_path), (
            f"重截图把截图写到了 gui 目录之外：{evil_path}"
        )
        assert sorted(os.listdir(gui_dir)) == names_before, (
            "非法文件名被 basename 归一后写进了 gui 目录"
        )
        assert critical_calls, "保存截图失败必须弹窗报错，否则用户以为已生效"
        with open(os.path.join(gui_dir, shot1), "rb") as f:
            assert f.read() == original[shot1], "非法文件名却改动了原截图"

        # 异编号前缀：会污染别的 gui 编号的截图序列
        critical_calls.clear()
        foreign = "gui_999999_0001.png"
        editor.steps[0]["screenshot_filename"] = foreign
        H.recapture(editor, 0)

        assert critical_calls, "异编号前缀的文件名被接受且未报错"
        assert not os.path.exists(os.path.join(gui_dir, foreign)), (
            "把当前任务的截图写成了别的 gui 编号的文件名"
        )
        assert sorted(os.listdir(gui_dir)) == names_before, (
            f"非法文件名写入后目录内容发生变化：{sorted(os.listdir(gui_dir))}"
        )

