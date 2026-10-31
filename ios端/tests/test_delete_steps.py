# -*- coding: utf-8 -*-
"""删除当前步骤测试组（3.1 ~ 3.8）。

覆盖：
  - 中间删除后步序前移、图步映射不串（3.1）
  - 首步/末步删除的边界停位（3.2）
  - 全部删空后回到初始态并可重新走步（3.3）
  - scroll 测量态删除（D-1 嫌疑点，3.4）
  - swipe/drag 测量态删除（3.5）
  - 删除最大序号步后重新截图的序号回落复用（D-5 删除侧，3.6）
  - 删除后草稿落盘并在新编辑器实例上断点续采（3.7）
  - 删除若干步后结束任务的最终 JSON/coords 一致性（3.8）

所有用例只驱动真实产品代码，不修改任何产品实现。
"""

import os

from PyQt5.QtTest import QTest

from annotation_editor import AnnotationEditor
from data_manager import DataManager
from fakes import FakeScreenCapture
from helpers import (
    capture,
    draw_rect,
    fill_step,
    confirm,
    walk_steps,
    flush_draft,
    finish_task,
    _wait_until,
)
from invariants import (
    SCREENSHOT_NAME_RE,
    assert_all,
    assert_model_consistency,
    assert_disk_consistency,
    assert_sidebar_consistency,
    assert_final_json_consistency,
)


# ----------------------------------------------------------------------
# 本文件本地助手
# ----------------------------------------------------------------------

def _strict_png_names(gui_dir):
    """gui_dir 下所有匹配严格命名的 PNG。"""
    return {f for f in os.listdir(gui_dir) if SCREENSHOT_NAME_RE.match(f)}


def _shot_number(name):
    """gui_000001_0003.png -> 3。"""
    return int(name[len("gui_000001_"):-len(".png")])


def _start_scroll_measurement_real(editor, rect=(50, 200, 150, 300)):
    """走真实事件路径进入 scroll 测量态。

    前置：当前步已截图（截图成为该步“保留首图”）。
    流程：选 scroll -> 在首图拉参照框 -> 点击“开始测量滚动”。
    """
    fill_step(editor, action="scroll", rect=rect, pixels=0)
    # 真实按钮触发 _start_scroll_measurement（information 已被夹具自动关闭）
    editor.btn_scroll_measure.click()
    QTest.qWait(0)
    assert editor._scroll_measuring is True
    assert editor._scroll_preserve_screenshot is True


def _scroll_extra_capture(editor):
    """scroll 测量态下真实再截一张图（被产品归入 extra，不更新当前步截图）。

    注意产品行为（_do_screenshot 1153-1158）：extra 截图保存为新序号文件并
    append 到 _scroll_extra_screenshots，但**不更新** _current_screenshot_filename，
    因此 capture() 助手返回的仍是“保留首图”旧名，不能用它拼 extra 路径。
    返回 (extra_filename, extra_path)，取 extras 列表最新一项。
    """
    capture(editor)
    assert editor._scroll_extra_screenshots, "scroll 测量中截图未被归入 extra"
    path = editor._scroll_extra_screenshots[-1]
    name = os.path.basename(path)
    assert os.path.isfile(path)
    return name, path


def _start_swipe_measurement_real(editor, rect=(50, 200, 150, 300)):
    """走真实事件路径进入 swipe 测量态（已记录起点）。"""
    fill_step(editor, action="swipe", rect=rect)
    editor.btn_swipe_measure.click()
    QTest.qWait(0)
    assert editor._swipe_measuring is True
    assert editor._swipe_start_vertices


def _new_editor_on_same_dir(dm, qapp):
    """在同一 DataManager（同一临时任务根目录）上构造新的编辑器实例用于续采。"""
    ed = AnnotationEditor(
        data_manager=dm,
        app_name="测试App",
        task_instruction="测试指令",
        screen_info={"screen_size": [390, 844]},
        app_type="iOS",
        udid=None,
        close_callback=None,
    )
    ed.screen_capture = FakeScreenCapture()
    qapp.processEvents()
    return ed


# ----------------------------------------------------------------------
# 3.1 删除中间步：后续步前移，图与步骤不串
# ----------------------------------------------------------------------

def test_delete_middle_step_shifts_without_image_crosslink(editor):
    """walk 5 步后删除第 3 步（index=2），业务顺序应为原 [0,1,3,4]。"""
    walk_steps(editor, 5, action="click")
    fake = editor.screen_capture

    # 删除前：第 k 步的截图底色序号 == k（每次 walk 恰好一张截图）
    original_names = [s["screenshot"] for s in editor.steps_data]
    for k, step in enumerate(editor.steps_data):
        assert fake.classify(step["screenshot_filepath"]) == k

    removed_name = original_names[2]
    removed_path = editor.steps_data[2]["screenshot_filepath"]

    editor.display_step(2)
    editor.delete_current_step()

    # 模型：剩 4 条
    assert len(editor.steps_data) == 4

    # 业务顺序对应原 [0,1,3,4]：用底色分类验证图步映射未串
    expected_classify = [0, 1, 3, 4]
    for new_idx, original_idx in enumerate(expected_classify):
        step = editor.steps_data[new_idx]
        assert fake.classify(step["screenshot_filepath"]) == original_idx, (
            f"删除后第 {new_idx} 步图步映射错乱："
            f"应对应原第 {original_idx} 步"
        )
        assert step["screenshot"] == original_names[original_idx]

    # 引用文件名集合正确（不含被删名）
    referenced = {s["screenshot"] for s in editor.steps_data}
    assert referenced == {original_names[i] for i in (0, 1, 3, 4)}
    assert removed_name not in referenced

    # 产品设计（delete_current_step 1701-1713）：先从列表移除，
    # 该文件不再被任何剩余步引用时立即 os.remove —— 被删序号文件从磁盘删除。
    assert not os.path.exists(removed_path), (
        f"被删步骤截图应已从磁盘移除：{removed_name}"
    )

    # 序号空洞保留：剩余文件仍是原 0001/0002/0004/0005，不重命名回填 0003
    on_disk = _strict_png_names(editor.gui_dir)
    assert on_disk == referenced
    assert sorted(_shot_number(n) for n in on_disk) == [1, 2, 4, 5]

    # 全套不变量
    assert_all(editor)


# ----------------------------------------------------------------------
# 3.2 删除首步 / 末步的边界停位
# ----------------------------------------------------------------------

def test_delete_first_step_stop_position(editor):
    """删首步：current_step 停在 0，展示的是原第 2 步，边界不越界。"""
    walk_steps(editor, 4, action="click")
    names = [s["screenshot"] for s in editor.steps_data]

    editor.display_step(0)
    editor.delete_current_step()

    assert len(editor.steps_data) == 3
    assert editor.current_step == 0
    # 停位步 UI 展示的是原 index=1 的内容
    assert editor._current_screenshot_filename == names[1]
    assert editor.steps_data[0]["screenshot"] == names[1]
    assert all(s["screenshot"] != names[0] for s in editor.steps_data)
    assert not os.path.exists(os.path.join(editor.gui_dir, names[0]))

    # 上一步按钮在 0 位禁用，不越界
    assert editor.btn_prev.isEnabled() is False
    assert_sidebar_consistency(editor)
    assert_all(editor)


def test_delete_last_step_stop_position(editor):
    """删末步：current_step 回落到新的末位，引用连续、侧栏一致。"""
    walk_steps(editor, 4, action="click")
    names = [s["screenshot"] for s in editor.steps_data]

    editor.display_step(3)
    editor.delete_current_step()

    assert len(editor.steps_data) == 3
    # target = min(3, 2) = 2
    assert editor.current_step == 2
    assert editor.steps_data[2]["screenshot"] == names[2]
    assert editor._current_screenshot_filename == names[2]
    assert all(s["screenshot"] != names[3] for s in editor.steps_data)
    assert not os.path.exists(os.path.join(editor.gui_dir, names[3]))

    # 删除后磁盘引用连续（0001-0003），无孤儿
    assert_disk_consistency(editor)
    assert_sidebar_consistency(editor)

    # 继续向前后应进入“新步”位而不是越界
    editor.go_next()
    QTest.qWait(0)
    # go_next 在末位且无新截图时仅弹警告并停留，不应产生异常/脏数据
    assert 0 <= editor.current_step <= len(editor.steps_data)
    assert len(editor.steps_data) == 3


# ----------------------------------------------------------------------
# 3.3 逐步删空 -> 初始态 -> 重新走步
# ----------------------------------------------------------------------

def test_delete_all_steps_to_blank(editor):
    walk_steps(editor, 3, action="click")
    gui_dir = editor.gui_dir

    # 从末位逐步删空（每删一次停位自动回落到新末位）
    editor.display_step(len(editor.steps_data) - 1)
    while editor.steps_data:
        editor.delete_current_step()

    assert editor.steps_data == []
    assert editor.current_step == 0
    assert editor.sidebar.item_widgets == []
    # 回到可重新截图的空白态：当前步无截图引用
    assert editor._current_screenshot_filename is None
    assert editor._current_screenshot_filepath is None
    # 磁盘无残留严格命名 png（无孤儿）
    assert _strict_png_names(gui_dir) == set()

    # 草稿也应为空态（flush 后不残留对已删截图的引用）
    flush_draft(editor)
    draft = DataManager.load_draft_from_dir(gui_dir)
    if draft is not None:
        assert draft.get("steps_data", []) == []

    # 重新 capture + fill + confirm 能正常加步
    name = capture(editor)
    fill_step(editor, action="click")
    confirm(editor)

    assert len(editor.steps_data) == 1
    assert editor.steps_data[0]["screenshot"] == name
    assert_all(editor)


# ----------------------------------------------------------------------
# 3.4 scroll 测量态删除（D-1 修复回归）
# ----------------------------------------------------------------------

def test_delete_during_scroll_measurement_inprogress_D1(editor):
    """D-1 回归：在采（未确认）步 scroll 测量中点删除。

    真实事件路径：截图 -> 选 scroll 拉首框 -> 开始测量 -> 滚动后再截 2 张
    extra -> 删除当前步（此时该步尚未 confirm，不在 steps_data 中）。

    修复后正确行为：delete_current_step 取消测量、回收首图与全部 extra、
    回到初始空白态；随后普通截图不再被归入 extra，可正常重新走步。
    """
    first_name = capture(editor)
    first_path = os.path.join(editor.gui_dir, first_name)
    _start_scroll_measurement_real(editor)
    extra1_name, extra1_path = _scroll_extra_capture(editor)
    draw_rect(editor, 50, 260, 150, 360)  # 测量中拉框只记参照物 Y
    extra2_name, extra2_path = _scroll_extra_capture(editor)
    assert os.path.isfile(extra1_path) and os.path.isfile(extra2_path)
    assert len(editor.steps_data) == 0  # 在采步尚未 confirm

    # 删除“当前步”（未确认编辑位）：不弹确认框，静默丢弃 pending 截图
    editor.delete_current_step()

    # 测量标记全部复位，extra 列表清空
    assert editor._scroll_measuring is False
    assert editor._scroll_preserve_screenshot is False
    assert editor._scroll_extra_screenshots == []
    assert editor._scroll_references == []
    assert editor._scroll_first_coord is None

    # 首图与两张 extra 全部回收（删空后磁盘序号回落到顶部）
    assert not os.path.exists(first_path)
    assert not os.path.exists(extra1_path)
    assert not os.path.exists(extra2_path)
    assert _strict_png_names(editor.gui_dir) == set()

    # 回到初始空白态
    assert editor.steps_data == []
    assert editor.current_step == 0
    assert editor._current_screenshot_filename is None
    assert editor._current_screenshot_filepath is None

    # 随后普通截图不再被误判为 extra：成为全新第 1 步（复用刚释放的 0001）
    new_name = capture(editor)
    assert editor._scroll_extra_screenshots == []
    assert editor._current_screenshot_filename == new_name
    assert new_name == first_name  # 序号回落复用同一编号，但文件是全新内容
    new_path = os.path.join(editor.gui_dir, new_name)
    assert os.path.isfile(new_path)
    assert editor.screen_capture.classify(new_path) == 3  # 第 4 次截图的内容

    fill_step(editor, action="click")
    confirm(editor)
    assert len(editor.steps_data) == 1
    assert editor.steps_data[0]["screenshot"] == new_name
    assert_all(editor)

    # 可继续正常走步（已有 1 步，再走 2 步到绝对 3 步）
    for _ in range(2):
        capture(editor)
        fill_step(editor, action="click")
        confirm(editor)
    assert len(editor.steps_data) == 3
    assert [s["screenshot"] for s in editor.steps_data] == [
        "gui_000001_0001.png",
        "gui_000001_0002.png",
        "gui_000001_0003.png",
    ]
    assert_all(editor)


def test_delete_during_scroll_measurement_middle(editor):
    """非删空分支：scroll 测量中删除当前步，extra 随 _restore_step_to_ui 清理。"""
    walk_steps(editor, 3, action="click")
    original_names = [s["screenshot"] for s in editor.steps_data]

    # 回到第 2 步（index=1）并在其上真实进入 scroll 测量，产生 1 张 extra
    editor.display_step(1)
    _start_scroll_measurement_real(editor)
    extra_name, extra_path = _scroll_extra_capture(editor)
    assert os.path.isfile(extra_path)

    editor.delete_current_step()

    # 测量复位、extra 清理
    assert editor._scroll_measuring is False
    assert editor._scroll_preserve_screenshot is False
    assert editor._scroll_extra_screenshots == []
    assert not os.path.exists(extra_path), f"scroll extra 泄漏：{extra_name}"

    # 停位 target=min(1,1)=1，展示原第 3 步
    assert len(editor.steps_data) == 2
    assert editor.current_step == 1
    assert editor.steps_data[1]["screenshot"] == original_names[2]
    assert_disk_consistency(editor)
    assert_sidebar_consistency(editor)


# ----------------------------------------------------------------------
# 3.5 swipe/drag 测量态删除（D-1 swipe 同类修复回归）
# ----------------------------------------------------------------------

def test_delete_during_swipe_measurement_inprogress(editor):
    """D-1 swipe 同类回归：在采（未确认）步 swipe 测量中删除。

    修复后正确行为：delete_current_step 取消 swipe 测量、回收 pending 截图、
    回到初始空白态；之后可正常重新走步。
    """
    pending_name = capture(editor)
    pending_path = os.path.join(editor.gui_dir, pending_name)
    _start_swipe_measurement_real(editor)
    assert len(editor.steps_data) == 0  # 在采步尚未 confirm

    editor.delete_current_step()

    # 测量态与起点 vertices 复位
    assert editor._swipe_measuring is False
    assert editor._swipe_start_vertices is None

    # pending 截图回收，回到初始空白态
    assert editor.steps_data == []
    assert editor.current_step == 0
    assert editor._current_screenshot_filename is None
    assert editor._current_screenshot_filepath is None
    assert not os.path.exists(pending_path)
    assert _strict_png_names(editor.gui_dir) == set()
    assert editor.sidebar.item_widgets == []

    # 删空态草稿同 3.3 口径：flush 后不残留对已删截图的引用（草稿可能不保留）
    flush_draft(editor)
    draft = DataManager.load_draft_from_dir(editor.gui_dir)
    if draft is not None:
        assert draft.get("steps_data", []) == []

    # 可继续正常走步
    walk_steps(editor, 2, action="click")
    assert len(editor.steps_data) == 2
    assert_all(editor)


def test_delete_during_swipe_measurement_middle(editor):
    """非删空分支：swipe 测量中删除中间步。"""
    walk_steps(editor, 3, action="click")
    editor.display_step(1)
    _start_swipe_measurement_real(editor)

    editor.delete_current_step()

    assert editor._swipe_measuring is False
    assert editor._swipe_start_vertices is None
    assert len(editor.steps_data) == 2
    assert editor.current_step == 1
    assert_sidebar_consistency(editor)
    assert_disk_consistency(editor)


# ----------------------------------------------------------------------
# 3.6 删除最大序号步后重新截图：序号回落复用（D-5 删除侧）
# ----------------------------------------------------------------------

def test_delete_max_number_then_recapture_reuses_number_D5(editor):
    """删除末尾最大序号步后重新截图，新图序号回落复用但引用唯一、无双份。

    当前实现：截图序号由磁盘 max+1 决定（get_next_screenshot_number），
    删除最大序号 0003 后磁盘 max=2，新截图复用 0003。产品行为安全，
    本用例作为回归固化；若出现旧引用/双份/串图则说明 D-5 复现。
    """
    walk_steps(editor, 3, action="click")
    fake = editor.screen_capture
    names = [s["screenshot"] for s in editor.steps_data]
    assert [_shot_number(n) for n in names] == [1, 2, 3]

    # 删除末步（最大序号 0003）
    editor.display_step(2)
    editor.delete_current_step()
    assert len(editor.steps_data) == 2
    assert not os.path.exists(os.path.join(editor.gui_dir, names[2]))
    assert sorted(_shot_number(n) for n in _strict_png_names(editor.gui_dir)) == [1, 2]

    # 进入下一“新步”编辑位：在末步上走真实 go_next -> confirm_step
    # （D-2 修复后条件建项不再产生侧栏重复条目）
    editor.go_next()
    QTest.qWait(0)
    assert editor.current_step == len(editor.steps_data)
    new_name = capture(editor)

    # 序号回落复用 0003
    assert _shot_number(new_name) == 3, (
        f"删最大序号后新图应回落复用 0003，实际 {new_name}"
    )
    # 磁盘只有一份该文件名（不存在双份/临时残留）
    assert sum(1 for f in _strict_png_names(editor.gui_dir) if f == new_name) == 1
    assert os.path.isfile(os.path.join(editor.gui_dir, new_name))

    # 新图底色是第 4 次截图（classify 序号 3），不是被删的旧第 3 步图
    assert fake.classify(os.path.join(editor.gui_dir, new_name)) == 3

    fill_step(editor, action="click")
    confirm(editor)

    # 引用唯一，无旧引用、无重复
    assert len(editor.steps_data) == 3
    all_names = [s["screenshot"] for s in editor.steps_data]
    assert len(set(all_names)) == 3
    assert all_names[2] == new_name
    assert all_names[:2] == names[:2]
    assert_model_consistency(editor)
    assert_disk_consistency(editor)
    assert_sidebar_consistency(editor)


# ----------------------------------------------------------------------
# 3.7 删除后草稿 + 新编辑器实例断点续采（INV-10）
# ----------------------------------------------------------------------

def test_delete_then_draft_and_resume(editor, dm, qapp):
    walk_steps(editor, 4, action="click")
    names_before = [s["screenshot"] for s in editor.steps_data]

    # 删除第 2 步（index=1）
    editor.display_step(1)
    editor.delete_current_step()
    expected_names = [names_before[0], names_before[2], names_before[3]]
    assert [s["screenshot"] for s in editor.steps_data] == expected_names
    assert_all(editor)

    # 草稿落盘
    flush_draft(editor)
    gui_dir = editor.gui_dir
    draft = DataManager.load_draft_from_dir(gui_dir)
    assert draft is not None
    assert [s["screenshot"] for s in draft["steps_data"]] == expected_names

    # 在同一任务目录上构造全新编辑器实例并恢复
    ed2 = _new_editor_on_same_dir(dm, qapp)
    try:
        ed2.load_from_draft(draft)

        # 恢复后模型引用一致
        assert [s["screenshot"] for s in ed2.steps_data] == expected_names
        assert len(ed2.steps_data) == 3

        # 运行时绝对路径由 gui_dir + 文件名重建，文件真实存在
        for step in ed2.steps_data:
            assert os.path.isfile(step["screenshot_filepath"])
            assert os.path.basename(step["screenshot_filepath"]) == step["screenshot"]

        # 恢复实例同样满足模型/磁盘/侧栏一致
        assert_model_consistency(ed2)
        assert_disk_consistency(ed2)
        assert_sidebar_consistency(ed2)
    finally:
        ed2.close()
        ed2.deleteLater()
        qapp.processEvents()


# ----------------------------------------------------------------------
# 3.8 删除若干步后结束任务：最终 JSON / coords 一致性
# ----------------------------------------------------------------------

def test_delete_then_finish_final_json(editor, qapp):
    walk_steps(editor, 5, action="click")
    names = [s["screenshot"] for s in editor.steps_data]

    # 删除第 2 步(index=1)与第 4 步(原 index=3，删除前移后 index=2)
    editor.display_step(1)
    editor.delete_current_step()
    editor.display_step(2)  # 原 index=3 在前移后位于 2
    editor.delete_current_step()

    survivors = [names[0], names[2], names[4]]
    assert [s["screenshot"] for s in editor.steps_data] == survivors
    assert_all(editor)

    # 结束任务（finish_task 自行处理 terminate 步截图与确认，答 No 不继续）
    finish_task(editor, continue_new=False)
    qapp.processEvents()

    gui_dir = editor.gui_dir
    data, coords = assert_final_json_consistency(
        gui_dir, gui_dir=gui_dir, expected_rounds=1
    )

    # 当前轮 trajectory：3 个幸存业务步 + 1 个 terminate 步
    traj = data["messages"][1]["trajectory"]
    traj_shots = [e["observation"]["screenshot"] for e in traj]
    assert traj_shots[:3] == survivors
    # 引用截图均存在
    for shot in traj_shots:
        assert os.path.isfile(os.path.join(gui_dir, shot))

    # coords 条数 == trajectory 步数；round/step 对齐
    assert len(coords) == len(traj)
    for i, (coord, entry) in enumerate(zip(coords, traj)):
        assert coord["round"] == 0
        assert coord["step"] == i
        assert coord["action"] == entry["actions"][0]["action"]

    # 磁盘无孤儿：恰好 4 张引用截图（3 幸存 + terminate）
    assert _strict_png_names(gui_dir) == set(traj_shots)
