# -*- coding: utf-8 -*-
"""测试组：start_insert_capture（“在此步骤后插入截图”）。

覆盖正常插入顺序、confirm 侧栏建项（D-2 修复回归）、50ms 回调窗口内切步/
删锚点竞态（D-3 修复回归：失效锚点夹紧到现存末位）、插入后 cache 源与
重新截图（D-4 修复回归：唯一名临时文件，画布不再显示上一张图）、
截图失败复位、scroll/swipe 测量期间插入（swipe 入口拦截，scroll 走
extra 既定路径）、草稿续采再插入等场景。

所有异步点均用 helpers._wait_until 轮询产品状态标记，竞态用 QTimer.singleShot
精确编排，不写死 sleep。

运行（在 ios端 目录）::

    python -m pytest tests/test_insert_capture.py -q
"""

import os
import tempfile

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QImage, QColor, QPixmap
from PyQt5.QtTest import QTest

from annotation_editor import AnnotationEditor
from data_manager import DataManager
from fakes import FakeScreenCapture
from helpers import (
    _wait_until,
    capture,
    draw_rect,
    fill_step,
    confirm,
    walk_steps,
    flush_draft,
    finish_task,
)
from invariants import (
    SCREENSHOT_NAME_RE,
    assert_all,
    assert_disk_consistency,
    assert_sidebar_consistency,
    assert_final_json_consistency,
)


# ----------------------------------------------------------------------
# 本文件专用辅助
# ----------------------------------------------------------------------

def _drive_insert(editor):
    """与 helpers.capture 相同方式驱动一次“插入截图”落盘。

    调用前应已 start_insert_capture()（其内部已 take_screenshot，50ms 回调
    已排队）。等待 _screenshot_in_progress 复位且锚点被消费，再推进一拍
    等回调中的侧栏 rebuild / 草稿事件处理完。
    """
    _wait_until(
        lambda: (not editor._screenshot_in_progress)
        and editor._capture_insert_after is None,
        message="插入截图回调未在超时内完成（in_progress/锚点未复位）",
    )
    QTest.qWait(80)
    assert editor._current_screenshot_filename, "插入截图未成功：没有当前截图文件名"
    return editor._current_screenshot_filename


def _start_insert_and_drive(editor, anchor_index):
    """切到 anchor_index 步后触发 start_insert_capture 并驱动完成。"""
    editor.display_step(anchor_index)
    QTest.qWait(0)
    editor.start_insert_capture()
    # start_insert_capture 内部 take_screenshot 已排队 50ms 回调
    return _drive_insert(editor)


# ----------------------------------------------------------------------
# 5.1 插入后业务顺序
# ----------------------------------------------------------------------

def test_insert_after_first_step_order(editor):
    """在第 1 步后插入：磁盘文件名可有空洞顺序，但 steps_data 业务顺序严格。"""
    walk_steps(editor, 3, action="click")
    initial_names = [s["screenshot"] for s in editor.steps_data]
    assert initial_names == [
        "gui_000001_0001.png",
        "gui_000001_0002.png",
        "gui_000001_0003.png",
    ]

    # 新截图按全局递增序号落盘 -> 0004；文件名顺序与业务顺序允许不一致
    inserted_name = _start_insert_and_drive(editor, anchor_index=0)
    assert inserted_name == "gui_000001_0004.png"

    # 插入后模型立即具备正确业务顺序（锚点步 0001 之后是新图 0004）
    assert [s["screenshot"] for s in editor.steps_data] == [
        "gui_000001_0001.png",
        "gui_000001_0004.png",
        "gui_000001_0002.png",
        "gui_000001_0003.png",
    ]

    # 给新插入步拉框标注并确认
    fill_step(editor, action="click")
    confirm(editor)

    business_names = [s["screenshot"] for s in editor.steps_data]
    assert business_names == [
        "gui_000001_0001.png",
        "gui_000001_0004.png",
        "gui_000001_0002.png",
        "gui_000001_0003.png",
    ]

    # 每张业务图内容必须是其业务位对应的截图（0-based 截图序号 0,3,1,2）
    fake = editor.screen_capture
    expected_shot_index = [0, 3, 1, 2]
    for pos, step in enumerate(editor.steps_data):
        shot_idx = fake.classify(step["screenshot_filepath"])
        assert shot_idx == expected_shot_index[pos], (
            f"业务位置 {pos} 的图 {step['screenshot']} 内容识别为第 "
            f"{shot_idx} 次截图，应为第 {expected_shot_index[pos]} 次"
        )

    # 模型/磁盘/测量态/草稿/侧栏全部一致（D-2 修复后 confirm 不再重复建项）
    assert_all(editor)
    assert len(editor.sidebar.item_widgets) == len(editor.steps_data)


# ----------------------------------------------------------------------
# 5.2 D-2 修复回归：插入回调 rebuild 后 confirm 仅在条目数不足时补建
# ----------------------------------------------------------------------

def test_insert_then_confirm_sidebar_D2(editor):
    """插入成功回调 rebuild 4 项；随后 confirm 新步不再产生重复侧栏项。"""
    walk_steps(editor, 3, action="click")
    _start_insert_and_drive(editor, anchor_index=0)

    # 插入回调 rebuild 后侧栏与模型一致（4 项）
    assert len(editor.sidebar.item_widgets) == 4
    assert [w._index for w in editor.sidebar.item_widgets] == [0, 1, 2, 3]

    fill_step(editor, action="click")
    confirm(editor)

    # D-2 修复回归：条目数与模型一致且各 _index 等于列表位置
    assert len(editor.sidebar.item_widgets) == len(editor.steps_data)
    assert_sidebar_consistency(editor)


# ----------------------------------------------------------------------
# 5.3 插入后删除新步 / 相邻步
# ----------------------------------------------------------------------

def test_insert_then_delete_new_and_adjacent(editor):
    """插入后分别删除新插入步与其相邻步：模型/磁盘/侧栏/草稿全部一致。"""
    walk_steps(editor, 3, action="click")

    # 插入到第 1 步之后：[0001, 0004(NEW), 0002, 0003]
    new_name = _start_insert_and_drive(editor, anchor_index=0)
    assert new_name == "gui_000001_0004.png"
    fill_step(editor, action="click")
    # 删除走 rebuild_items，删除后停留在相邻步 0002（原第 3 步），不 confirm
    assert editor.current_step == 1
    editor.delete_current_step()
    QTest.qWait(80)

    assert [s["screenshot"] for s in editor.steps_data] == [
        "gui_000001_0001.png",
        "gui_000001_0002.png",
        "gui_000001_0003.png",
    ]
    assert not os.path.exists(os.path.join(editor.gui_dir, new_name)), (
        "新插入步截图文件未随删除清理"
    )
    assert_all(editor)

    # 再插入到第 2 步（0002）之后。注意产品命名按磁盘现存最大序号 +1，
    # 上一张 0004 已随删除清盘，序号空洞被复用 -> 新图仍命名 0004：
    # [0001, 0002, 0004(NEW2, 第 5 次截图内容), 0003]
    new2_name = _start_insert_and_drive(editor, anchor_index=1)
    assert new2_name == "gui_000001_0004.png"
    fill_step(editor, action="click")
    assert editor.current_step == 2

    # 删除新步的相邻步：直接导航到前一邻步 0002 删除（后步前移到当前位）
    editor.display_step(1)
    QTest.qWait(0)
    editor.delete_current_step()
    QTest.qWait(80)

    remaining = [s["screenshot"] for s in editor.steps_data]
    assert remaining == [
        "gui_000001_0001.png",
        "gui_000001_0004.png",
        "gui_000001_0003.png",
    ]
    assert not os.path.exists(os.path.join(editor.gui_dir, "gui_000001_0002.png"))
    assert os.path.isfile(os.path.join(editor.gui_dir, new2_name))
    assert_all(editor)


# ----------------------------------------------------------------------
# 5.4 D-3：50ms 回调窗口内切步
# ----------------------------------------------------------------------

def test_insert_switch_step_within_50ms_D3(editor, qapp):
    """start_insert_capture 后、_do_screenshot 执行前切到别的步骤。

    锚点是 start_insert_capture 时捕获的下标快照，_do_screenshot 不读取
    “当前步”决定插入位置；锚点仍有效时回调以 current_step 为下标保存表单，
    被切到的历史步表单与其落表数据一致，不会被空表单覆盖。
    """
    walk_steps(editor, 3, action="click")
    # 记录各步原始数据，便于事后核对未被覆盖
    before = {i: dict(editor.steps_data[i]) for i in range(3)}

    editor.display_step(0)
    QTest.qWait(0)
    editor.start_insert_capture()
    anchor_at_arm = editor._capture_insert_after
    assert anchor_at_arm == 0

    # 在 50ms 回调之前切到第 3 步（index 2）
    QTimer.singleShot(10, lambda: editor.display_step(2))
    _drive_insert(editor)

    # 回调结束后：新图按锚点快照插到 index 1，而不是被切到的第 3 步之后
    names = [s["screenshot"] for s in editor.steps_data]
    assert names == [
        "gui_000001_0001.png",
        "gui_000001_0004.png",
        "gui_000001_0002.png",
        "gui_000001_0003.png",
    ]

    # 不串步：被切到的第 3 步（业务 index 3）截图与表单未被覆盖
    target_step = editor.steps_data[3]
    assert target_step["screenshot"] == before[2]["screenshot"]
    assert target_step["vertices"] == before[2]["vertices"]
    assert target_step["action_data"] == before[2]["action_data"]

    # 第 2 步（index 2，原本在显示第 1 步时也不在编辑位）同样未受影响
    assert editor.steps_data[2]["screenshot"] == before[1]["screenshot"]

    # 新步没有写入任何旧步位置；无孤儿/无异常/锚点已消费
    assert editor._capture_insert_after is None
    assert not editor._screenshot_in_progress
    assert_all(editor)


# ----------------------------------------------------------------------
# 5.5 D-3：50ms 窗口内删除锚点步
# ----------------------------------------------------------------------

def test_insert_delete_last_anchor_within_50ms_D3(editor, qapp):
    """D-3 场景 A 修复回归：锚点为末步，50ms 窗口内删除该步后让回调执行。

    锚点是 start 时刻的下标快照，删除后锚点失效。修复后回调把插入位置
    夹紧到现存末位（等价 append）：无 IndexError、无磁盘孤儿、current_step
    落在合法区间、草稿与模型严格同长，任何后续保存都不再产生幻影步。
    """
    walk_steps(editor, 4, action="click")
    before = {i: dict(editor.steps_data[i]) for i in range(4)}

    editor.display_step(3)
    QTest.qWait(0)
    editor.start_insert_capture()
    assert editor._capture_insert_after == 3
    QTimer.singleShot(10, lambda: editor.delete_current_step())
    _drive_insert(editor)

    # 修复后行为：
    # 1) 删除末步 -> len=3、current_step 夹紧到 2，UI 恢复为现存末步内容；
    # 2) 回调保存新截图：0004 文件此前随删除清盘，磁盘 max+1 重新发出 0004；
    # 3) anchor=3、len=3 锚点失效，回调跳过 _save_current_to_steps()，
    #    safe_anchor 夹紧为 2，新步 insert(3) 追加到末尾；
    # 4) current_step=3，合法指向新步。
    names = [s["screenshot"] for s in editor.steps_data]
    assert names == [
        "gui_000001_0001.png",
        "gui_000001_0002.png",
        "gui_000001_0003.png",
        "gui_000001_0004.png",
    ]
    assert len(editor.steps_data) == 4
    assert os.path.isfile(os.path.join(editor.gui_dir, "gui_000001_0004.png"))
    # 末位内容是本次新截图（桩第 5 次成功截图，0-based 序号 4）
    assert editor.screen_capture.classify(
        editor.steps_data[3]["screenshot_filepath"]
    ) == 4
    # 前 3 步旧数据未被覆盖
    for i in range(3):
        assert editor.steps_data[i]["screenshot"] == before[i]["screenshot"]
        assert editor.steps_data[i]["vertices"] == before[i]["vertices"]
    assert not editor._screenshot_in_progress
    assert editor._capture_insert_after is None

    # 安全后置条件 1：current_step 落在模型下标区间内（指向末尾新步）
    assert 0 <= editor.current_step < len(editor.steps_data)
    assert editor.current_step == 3

    # 安全后置条件 2：任何 _save_current_to_steps 触发都不再凭空追加幻影步
    editor._save_current_to_steps()
    assert len(editor.steps_data) == 4
    assert editor.current_step == 3

    # 安全后置条件 3：草稿与模型严格同长，全套不变量自洽
    # （assert_all 内部先 _write_draft_now 落盘再校验草稿）
    assert_all(editor)


def test_insert_delete_last_anchor_leaves_dangling_state_D3(editor, qapp):
    """D-3 场景 A 修复回归：末锚点在 50ms 窗口内被删，回调安全重定向到末尾。"""
    walk_steps(editor, 3, action="click")
    editor.display_step(2)
    QTest.qWait(0)
    editor.start_insert_capture()
    QTimer.singleShot(10, lambda: editor.delete_current_step())
    _drive_insert(editor)

    # 锚点步已删除：回调把新步追加到现存末位，current_step 落在合法区间
    assert 0 <= editor.current_step < len(editor.steps_data), (
        f"current_step={editor.current_step} 悬空，模型仅 "
        f"{len(editor.steps_data)} 步"
    )
    assert editor.current_step == 2
    # 末锚点 0003 已随删除清盘，磁盘 max 回落到 2，新图序号复用 0003
    # （内容是桩件第 4 次截图，0-based 序号 3）
    assert [s["screenshot"] for s in editor.steps_data] == [
        "gui_000001_0001.png",
        "gui_000001_0002.png",
        "gui_000001_0003.png",
    ]
    assert editor.screen_capture.classify(
        editor.steps_data[2]["screenshot_filepath"]
    ) == 3
    # 再触发任何“保存当前步”都不凭空多出步骤
    n_before = len(editor.steps_data)
    editor._save_current_to_steps()
    assert len(editor.steps_data) == n_before
    # assert_all 内部先落盘草稿再校验（草稿与模型严格同长，无幻影步）
    assert_all(editor)


def test_insert_delete_middle_anchor_within_50ms_D3(editor, qapp):
    """D-3 场景 B 修复回归：锚点为中间步，窗口内删除该步后让回调执行。

    删除 index1 后其后步前移，旧锚点下标 1 仍指向一条现存步（前移到 index1
    的原后步），锚点判定有效，新图插到 index2。模型、磁盘、侧栏、草稿
    全部自洽，无崩溃/无孤儿。
    """
    walk_steps(editor, 4, action="click")

    editor.display_step(1)
    QTest.qWait(0)
    editor.start_insert_capture()
    assert editor._capture_insert_after == 1
    QTimer.singleShot(10, lambda: editor.delete_current_step())
    _drive_insert(editor)

    # walk4：[0001,0002,0003,0004] -> 删 index1(0002)：[0001,0003,0004]
    # 新截图按磁盘 max+1 = 0005 保存；旧锚点 1 有效（指向现前移的 0003），
    # _save_current_to_steps 用 UI（0002 被删后 restore 到 index1 的 0003）
    # 覆盖 index1（内容相同），新步 insert(2)：
    # [0001, 0003, 0005(NEW), 0004]
    names_b = [s["screenshot"] for s in editor.steps_data]
    assert names_b == [
        "gui_000001_0001.png",
        "gui_000001_0003.png",
        "gui_000001_0005.png",
        "gui_000001_0004.png",
    ]
    assert not os.path.exists(os.path.join(editor.gui_dir, "gui_000001_0002.png"))
    # 新步内容是第 5 次截图（0-based 4）
    assert editor.screen_capture.classify(
        editor.steps_data[2]["screenshot_filepath"]
    ) == 4
    # current_step 是回调写入的插入位 2，合法
    assert editor.current_step == 2
    assert_all(editor)


# ----------------------------------------------------------------------
# 5.6 插入截图失败后状态复位，随后普通追加成功
# ----------------------------------------------------------------------

def test_insert_capture_failure_resets_state(editor):
    """插入截图失败：锚点/进行中标记复位；随后可正常走普通追加分支。"""
    walk_steps(editor, 3, action="click")

    editor.display_step(1)
    QTest.qWait(0)
    calls_before = editor.screen_capture.call_count

    editor.screen_capture.fail_next = True
    editor.start_insert_capture()
    _wait_until(lambda: not editor._screenshot_in_progress, message="失败回调未完成")
    QTest.qWait(80)

    # 失败后所有临时状态复位
    assert editor._capture_insert_after is None
    assert not editor._screenshot_in_progress
    assert not editor._replacing_screenshot
    # 失败不产生截图调用计数、不新增文件
    assert editor.screen_capture.call_count == calls_before
    on_disk = {f for f in os.listdir(editor.gui_dir) if SCREENSHOT_NAME_RE.match(f)}
    assert on_disk == {f"gui_000001_{i:04d}.png" for i in range(1, 4)}
    # 失败插入未改动模型
    assert [s["screenshot"] for s in editor.steps_data] == [
        f"gui_000001_{i:04d}.png" for i in range(1, 4)
    ]

    # 失败后界面仍停在锚点步（其图仍被引用）；切回末步再用“下一步”走真实
    # confirm_step 创建空步（不直接手改 current_step），随后普通追加截图成功。
    editor.display_step(2)
    QTest.qWait(0)
    # go_next 在末步且已截图时内部走 confirm_step 创建空步
    editor.go_next()
    QTest.qWait(80)
    assert editor._current_screenshot_filename is None
    assert editor.current_step == 3

    shot = capture(editor)
    assert shot == "gui_000001_0004.png"
    # 普通追加分支：不是原地覆盖任何旧文件
    assert editor._replacing_screenshot is False
    fill_step(editor, action="click")
    confirm(editor)
    assert [s["screenshot"] for s in editor.steps_data] == [
        f"gui_000001_{i:04d}.png" for i in range(1, 5)
    ]
    assert_all(editor)


# ----------------------------------------------------------------------
# 5.7 scroll/swipe 测量期间触发插入
# ----------------------------------------------------------------------

def test_insert_during_scroll_measurement(editor):
    """scroll 测量中 start_insert_capture：产品不拦截，但回调分支优先级
    _scroll_preserve_screenshot > _capture_insert_after，新图作为测量 extra
    保存，插入锚点被静默消费（未插入任何步骤）；取消测量后状态自洽、无孤儿。

    编排：先确出 1 个历史步（start_insert_capture 守卫要求锚点是已落表步），
    再回看该步恢复 cache/参照物，进入 scroll 测量后触发插入。
    """
    walk_steps(editor, 1, action="click")
    assert [s["screenshot"] for s in editor.steps_data] == ["gui_000001_0001.png"]

    # 回看历史步：恢复截图 cache 与起点框/坐标，满足进入 scroll 测量的前置条件
    editor.display_step(0)
    QTest.qWait(0)
    assert editor.screenshot_cache is not None
    # 历史步是 click，这里在其图上拉一个 scroll 参照物框并进入测量
    fill_step(editor, action="scroll", rect=(50, 200, 150, 300))
    editor._start_scroll_measurement()
    QTest.qWait(0)
    assert editor._scroll_measuring is True
    assert editor._scroll_preserve_screenshot is True

    # 锚点合法（index0 已落表），触发插入
    editor.start_insert_capture()
    assert editor._capture_insert_after == 0  # 已挂锚点
    _wait_until(lambda: not editor._screenshot_in_progress, message="scroll 期截图未完成")
    QTest.qWait(80)

    # 实测行为：scroll_preserve 分支优先，新图（0002）进 extra 列表；
    # 插入锚点在 _do_screenshot 末尾被清掉，但没有任何步骤被插入
    assert editor._capture_insert_after is None
    assert [s["screenshot"] for s in editor.steps_data] == ["gui_000001_0001.png"]
    assert editor._scroll_measuring is True  # 测量流程未被插入打断
    extra = list(editor._scroll_extra_screenshots)
    assert len(extra) == 1
    assert os.path.isfile(extra[0])
    assert os.path.basename(extra[0]) == "gui_000001_0002.png"
    # 步骤首图仍为 0001，未被测量 extra 顶替
    assert editor._current_screenshot_filename == "gui_000001_0001.png"

    # 取消测量：extra 被清理，画布回到首图，所有临时状态复位，无孤儿
    editor._cancel_scroll_measurement()
    QTest.qWait(80)
    assert not os.path.exists(extra[0]), "scroll extra 截图取消测量后未清理"
    assert not editor._scroll_measuring
    assert not editor._scroll_preserve_screenshot
    assert editor._capture_insert_after is None
    assert not editor._screenshot_in_progress
    assert_disk_consistency(editor)  # 0002 已删，磁盘仅余被引用的 0001，无孤儿

    # 把该步以合法 scroll 像素正常确认（修复5 不拦截 scroll 期间插入；
    # D-2 修复后历史步 confirm 也不再重复建项，全套不变量自洽）
    fill_step(editor, action="scroll", rect=(50, 200, 150, 300), pixels=300)
    confirm(editor)
    assert [s["screenshot"] for s in editor.steps_data] == ["gui_000001_0001.png"]
    assert_all(editor)


def test_insert_during_swipe_measurement(editor):
    """swipe 测量中 start_insert_capture：入口直接 warning 拦截并 return。

    swipe/drag 是“起点框 -> 终点框”的两阶段流程，插入截图会破坏当前步
    测量上下文并产生孤儿截图。修复后 start_insert_capture 在 _swipe_measuring
    时不挂锚点、不触发 take_screenshot，测量态与模型都保持原样。
    （对照：scroll 测量期间的插入走 extra 既定路径，不在此拦截。）
    """
    walk_steps(editor, 1, action="click")
    editor.display_step(0)
    QTest.qWait(0)

    # 在历史步图上拉 swipe 起点框并进入测量（不 confirm，保持测量态）
    draw_rect(editor, 50, 200, 150, 300)
    editor.coord2_x_input.setText("250")
    editor.coord2_y_input.setText("550")
    editor._start_swipe_measurement()
    QTest.qWait(0)
    assert editor._swipe_measuring is True
    assert editor._swipe_start_vertices == [50, 200, 150, 300]

    calls_before = editor.screen_capture.call_count
    # 测量期间触发插入：入口拦截，不挂锚点、不发起截图
    editor.start_insert_capture()
    assert editor._capture_insert_after is None
    assert not editor._screenshot_in_progress
    assert editor.screen_capture.call_count == calls_before
    # 再推进一拍，确认没有任何延迟截图回调产生文件/副作用
    QTest.qWait(80)
    assert editor.screen_capture.call_count == calls_before
    assert editor._current_screenshot_filename == "gui_000001_0001.png"

    # swipe 测量态原样保留，未被插入流程污染或打断
    assert editor._swipe_measuring is True
    assert editor._swipe_start_vertices == [50, 200, 150, 300]
    # 模型仍是原 1 步，磁盘无新增截图
    assert [s["screenshot"] for s in editor.steps_data] == ["gui_000001_0001.png"]
    on_disk = {f for f in os.listdir(editor.gui_dir) if SCREENSHOT_NAME_RE.match(f)}
    assert on_disk == {"gui_000001_0001.png"}

    # 取消测量后把该步正常确认，编辑器回到合法稳定态
    editor._cancel_swipe_measurement()
    QTest.qWait(0)
    assert not editor._swipe_measuring
    assert editor._swipe_start_vertices is None
    fill_step(editor, action="click")
    confirm(editor)
    assert_all(editor)


# ----------------------------------------------------------------------
# 5.8 D-4：插入后 cache 源 / 重新截图
# ----------------------------------------------------------------------

def _image_rgb(path):
    """读图片左上角像素底色（直接走 QImage，不经 QPixmap 路径缓存）。"""
    return QColor(QImage(path).pixel(4, 4)).getRgb()[:3]


def test_insert_persistence_safe_D4(editor):
    """D-4 修复回归：每次截图使用唯一名临时文件，steps_data、gui_dir 副本、
    原地重新截图覆盖、邻步、切步回看全部内容正确、不串图。

    产品把截图写入临时文件 ios_capture_tmp_{pid}_{monotonic_ns}.png（修复前
    为固定名 ios_capture_tmp_{pid}.png，会被 QPixmap 按路径缓存导致串图），
    再 copy 一份到 gui_dir（覆盖走“临时文件 + os.replace”）。本用例核验：
    gui_dir 副本即本次截图内容；两次截图临时路径互不相同；重新截图原地覆盖
    后文件内容更新、序号不变；相邻步仍是各自原始截图；切步回看从 gui_dir
    按文件名重载，内容正确。
    """
    walk_steps(editor, 2, action="click")
    # 记录普通截图阶段最后一次临时路径，与插入截图的临时路径比较
    tmp_before_insert = editor._last_capture_tmp_path
    inserted_name = _start_insert_and_drive(editor, anchor_index=0)
    gui_dir = editor.gui_dir
    gui_copy = os.path.join(gui_dir, inserted_name)

    # gui_dir 副本存在，内容就是该次截图（按底色识别为第 3 次截图，0-based 2）
    assert os.path.isfile(gui_copy)
    fake = editor.screen_capture
    assert fake.classify(gui_copy) == 2

    # D-4 修复回归：本次插入截图的临时路径与上一次截图不同（唯一名）
    tmp_at_insert = editor._last_capture_tmp_path
    assert tmp_at_insert and os.path.basename(tmp_at_insert).startswith(
        "ios_capture_tmp_"
    )
    assert tmp_at_insert != tmp_before_insert

    # 模型引用严格命名且指向 gui_dir
    new_step = editor.steps_data[1]
    assert SCREENSHOT_NAME_RE.match(new_step["screenshot"])
    assert os.path.normcase(os.path.dirname(new_step["screenshot_filepath"])) == \
        os.path.normcase(gui_dir)

    # screenshot_cache 指向本次唯一名临时文件，临时目录正确
    assert editor.screenshot_cache is not None
    tmp_dir = os.path.dirname(editor.screenshot_cache)
    assert os.path.basename(editor.screenshot_cache).startswith("ios_capture_tmp_")
    assert os.path.normcase(tmp_dir) == os.path.normcase(tempfile.gettempdir())
    # 临时文件当前内容也是本次截图（与 gui_dir 副本同内容）
    assert _image_rgb(editor.screenshot_cache) == fake.colors[2]

    # 关键验证：对新插入步“重新截图”走真实 take_screenshot 的原地覆盖分支
    # （_current_screenshot_filepath 已指向 gui_dir 副本，_replacing_screenshot），
    # 读源是新的唯一名临时文件但目标文件名/序号不变，覆盖后 gui_dir 文件内容
    # 更新、其它步不串图。
    assert editor._current_screenshot_filepath == gui_copy
    editor.take_screenshot()
    _wait_until(lambda: not editor._screenshot_in_progress, message="重新截图未完成")
    QTest.qWait(80)
    # 重新截图又是一个新的唯一名临时路径
    tmp_after_recapture = editor._last_capture_tmp_path
    assert tmp_after_recapture not in (tmp_before_insert, tmp_at_insert)
    assert editor._current_screenshot_filename == inserted_name  # 序号不变
    # gui_dir 副本内容已更新为第 4 次截图（0-based 3）
    assert fake.classify(gui_copy) == 3
    # 相邻旧步仍是各自原始截图，未被共享临时图污染
    assert fake.classify(editor.steps_data[0]["screenshot_filepath"]) == 0
    assert fake.classify(editor.steps_data[2]["screenshot_filepath"]) == 1

    # 切步回看再切回：从 gui_dir 按文件名重载，显示的仍是覆盖后的新内容
    editor.display_step(0)
    QTest.qWait(0)
    editor.display_step(1)
    QTest.qWait(0)
    assert editor._current_screenshot_filename == inserted_name
    assert fake.classify(editor._current_screenshot_filepath) == 3

    # 完整落表确认后模型/磁盘/侧栏/草稿全套一致
    fill_step(editor, action="click")
    confirm(editor)
    assert_all(editor)


def test_insert_canvas_shows_previous_image_D4(editor):
    """D-4 修复回归：插入截图成功后，画布立即显示本次新截图而非上一张。

    修复前每次截图写入固定路径 ios_capture_tmp_{pid}.png，Windows/Qt 按路径
    缓存 pixmap，连续截图时画布拿到陈旧图像。修复后临时文件名含单调时钟纳秒，
    每次唯一，QPixmap 不再命中旧缓存；gui_dir 副本与画布内容一致。
    """
    walk_steps(editor, 2, action="click")
    # 保留“把上一张临时路径加载进 QPixmap 缓存”的预热动作，模拟连续采标会话；
    # 唯一名下这不会污染下一次截图。confirm 后 _reset_for_next_step 会清空
    # screenshot_cache，但 _last_capture_tmp_path 仍保留最后一次临时路径。
    tmp_path = editor._last_capture_tmp_path
    assert tmp_path and os.path.basename(tmp_path).startswith("ios_capture_tmp_")
    assert os.path.isfile(tmp_path)
    QPixmap(tmp_path)
    tmp_before = editor._last_capture_tmp_path
    inserted_name = _start_insert_and_drive(editor, anchor_index=0)
    gui_copy = os.path.join(editor.gui_dir, inserted_name)
    fake = editor.screen_capture

    # 前提：磁盘 gui_dir 副本是本次截图（colors[2]）
    assert _image_rgb(gui_copy) == fake.colors[2]
    # 唯一名临时路径，未与上一张共用
    assert editor._last_capture_tmp_path != tmp_before

    canvas_pm = editor.canvas.pixmap
    assert canvas_pm is not None and not canvas_pm.isNull()
    canvas_rgb = QColor(canvas_pm.toImage().pixel(4, 4)).getRgb()[:3]
    # 回归断言：插入成功后画布显示的就是本次新截图，而非锚点步上一张图
    assert canvas_rgb == fake.colors[2], (
        f"插入后画布底色 {canvas_rgb} 是上一张截图，本次截图底色应为 "
        f"{fake.colors[2]}"
    )


# ----------------------------------------------------------------------
# 5.9 草稿续采后再次插入 / 删除 / 结束
# ----------------------------------------------------------------------

def test_insert_draft_resume_and_reinsert(editor, qapp, dm):
    """插入序列 -> flush_draft -> 新编辑器 load_from_draft -> 再插入/删除
    -> 全套不变量；最后 finish 验最终 JSON（INV-9/10）。"""
    walk_steps(editor, 3, action="click")
    _start_insert_and_drive(editor, anchor_index=0)  # [0001,0004,0002,0003]
    fill_step(editor, action="click")
    # 不 confirm 新步；_write_draft_now 会把当前 live 步序列化进草稿
    flush_draft(editor)
    gui_dir = editor.gui_dir
    draft = DataManager.load_draft_from_dir(gui_dir)
    assert draft is not None
    assert [s["screenshot"] for s in draft["steps_data"]] == [
        "gui_000001_0001.png",
        "gui_000001_0004.png",
        "gui_000001_0002.png",
        "gui_000001_0003.png",
    ]

    # 新编辑器（同 DataManager 基目录）从草稿续采，不新建 gui 目录
    ed2 = AnnotationEditor(
        data_manager=dm,
        app_name=editor.app_name,
        task_instruction=editor.task_instruction,
        screen_info=dict(editor.screen_info) if isinstance(editor.screen_info, dict) else {},
        app_type=editor.app_type,
        udid=None,
        close_callback=None,
    )
    try:
        ed2.screen_capture = FakeScreenCapture()
        ed2._test_dialogs = editor._test_dialogs
        resumed = ed2.load_from_draft(draft)
        qapp.processEvents()
        assert resumed is False
        assert ed2.gui_dir == gui_dir
        assert [s["screenshot"] for s in ed2.steps_data] == [
            "gui_000001_0001.png",
            "gui_000001_0004.png",
            "gui_000001_0002.png",
            "gui_000001_0003.png",
        ]
        assert_sidebar_consistency(ed2)

        # 续采后再插入到第 2 步之后（新桩 call_count 从 0 计，文件名仍按磁盘
        # 全局递增 -> 0005），随后删除该新步（删除走 rebuild_items）
        new_name = _start_insert_and_drive(ed2, anchor_index=1)
        assert new_name == "gui_000001_0005.png"
        assert [s["screenshot"] for s in ed2.steps_data] == [
            "gui_000001_0001.png",
            "gui_000001_0004.png",
            "gui_000001_0005.png",
            "gui_000001_0002.png",
            "gui_000001_0003.png",
        ]
        fill_step(ed2, action="click")
        assert ed2.current_step == 2
        ed2.delete_current_step()
        QTest.qWait(80)
        assert [s["screenshot"] for s in ed2.steps_data] == [
            "gui_000001_0001.png",
            "gui_000001_0004.png",
            "gui_000001_0002.png",
            "gui_000001_0003.png",
        ]
        assert_all(ed2)

        # 结束任务：终止类动作必须是本轮最后一步，先切到末步（0003），
        # 再走真实 _finish_task（结束前全量校验）；问答临时置 No -> 落盘后
        # close，不开始新任务。
        ed2.display_step(3)
        finish_task(ed2, continue_new=False)

        assert ed2._draft_discarded is True
        assert_final_json_consistency(
            ed2,
            gui_dir=gui_dir,
            expected_rounds=1,
        )
        # terminate 复用当前步截图，不新增 PNG：磁盘严格命名 PNG 共 4 张，无孤儿
        pngs = {f for f in os.listdir(gui_dir) if SCREENSHOT_NAME_RE.match(f)}
        assert pngs == {f"gui_000001_{i:04d}.png" for i in (1, 2, 3, 4)}
        draft_files = [f for f in os.listdir(gui_dir) if f.endswith("_draft.json")]
        assert draft_files == []
    finally:
        ed2.close()
        ed2.deleteLater()
        qapp.processEvents()
