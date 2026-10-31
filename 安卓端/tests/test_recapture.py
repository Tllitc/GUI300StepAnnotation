# -*- coding: utf-8 -*-
"""Task 6 重新截图测试组（SubTask 6.1 ~ 6.5）

覆盖「重新截图」（take_screenshot 对已确认步骤的覆盖路径）：
- 6.1 中间步重新截图：引用指向新图、旧文件删除/同名内容更新、其余步骤不变、无孤儿
- 6.2 序号复用同名场景：steps_data 引用正确、画布与侧栏缩略图显示新图（按字节哈希区分新旧图）
- 6.3 截图在途切换步骤：结果丢弃、原步引用不变、锁复位
- 6.4 桩件 fail_next：重截失败旧文件保留、引用不变、锁复位
- 6.5 重新截图后立即 finish_task：最终 JSON 引用新文件且 assert_final_json 通过

注意：DataManager 先删旧文件再按最小可用序号保存新文件，重截可能复用同一序号
（同名覆盖语义）或更小空洞序号，断言以"引用正确+内容为新图+无孤儿"为准。
"""
import os

from PyQt5.QtGui import QPixmap

from annotation_editor import StepListItemWidget
from helpers import (capture_and_wait, confirm_n_steps, drain_sidebar_thumbs,
                     fill_valid_step, finish_task, flush_events)
from invariants import assert_all, assert_final_json


def _read_bytes(gui_dir, filename):
    with open(os.path.join(gui_dir, filename), "rb") as f:
        return f.read()


def _png_names(gui_dir):
    return sorted(n for n in os.listdir(gui_dir) if n.endswith(".png"))


# ---------- SubTask 6.1：中间步重新截图 ----------

def test_6_1_recapture_middle_step(editor_factory):
    editor = editor_factory()
    confirm_n_steps(editor, 3)
    gui_dir = editor.gui_dir

    old_refs = [s["screenshot"] for s in editor.steps_data]
    old_bytes = {fn: _read_bytes(gui_dir, fn) for fn in old_refs}

    editor.jump_to_step(1)  # 跳到中间步（index 1）
    flush_events()
    assert editor.current_step == 1

    new_fn = capture_and_wait(editor)

    # 该步 screenshot 引用指向新文件
    assert editor.steps_data[1]["screenshot"] == new_fn
    assert editor._current_screenshot_filename == new_fn
    new_bytes = _read_bytes(gui_dir, new_fn)
    assert new_bytes != old_bytes[old_refs[1]], "桩件应产出与旧图不同的新图"
    if new_fn == old_refs[1]:
        # 序号复用同名（删旧后空洞被回填）：断言内容字节已更新为新图
        pass
    else:
        # 新序号：旧文件已删除，新文件存在
        assert not os.path.exists(os.path.join(gui_dir, old_refs[1]))
        assert os.path.isfile(os.path.join(gui_dir, new_fn))

    # 其余 2 步引用与文件内容不变
    for i in (0, 2):
        assert editor.steps_data[i]["screenshot"] == old_refs[i]
        assert _read_bytes(gui_dir, old_refs[i]) == old_bytes[old_refs[i]]

    # 磁盘无孤儿 + 全量不变量（模型/文件/侧栏/草稿/瞬态）
    assert len(_png_names(gui_dir)) == 3
    assert_all(editor)


# ---------- SubTask 6.2：序号复用同名场景（侧栏缩略图/画布新鲜度） ----------

def test_6_2_recapture_same_name_reuse_sidebar_canvas(editor_factory):
    editor = editor_factory()
    confirm_n_steps(editor, 3)
    gui_dir = editor.gui_dir

    editor.jump_to_step(2)  # 对末步重截：删旧图后最小可用序号必然回填同名
    old_fn = editor.steps_data[2]["screenshot"]
    old_bytes = _read_bytes(gui_dir, old_fn)
    drain_sidebar_thumbs(editor)  # 确保旧图缩略图已进入按文件名缓存
    flush_events()

    new_fn = capture_and_wait(editor)
    new_path = os.path.join(gui_dir, new_fn)
    new_bytes = _read_bytes(gui_dir, new_fn)

    # 场景前提：新图复用了与旧图相同的文件名，且字节内容确实已更新
    assert new_fn == old_fn, "末步重截应复用同一序号（同名覆盖语义）"
    assert new_bytes != old_bytes

    # steps_data 引用正确（指向该文件，内容已是新图）
    assert editor.steps_data[2]["screenshot"] == new_fn

    # 画布显示新图（set_screenshot 按路径从磁盘实时加载）
    canvas_pixmap = editor.screenshot_canvas._pixmap
    assert canvas_pixmap is not None and not canvas_pixmap.isNull()
    assert canvas_pixmap.toImage() == QPixmap(new_path).toImage()

    # 侧栏缩略图显示新图（按文件字节内容构建的期望缩略图比对）
    drain_sidebar_thumbs(editor)
    item = editor.sidebar.item_widgets[2]
    assert item.thumb_loaded
    step = editor.steps_data[2]
    expected = editor.build_marked_preview(new_fn, step.get("vertices"),
                                           StepListItemWidget.THUMB_SIZE)
    thumb_pixmap = item.thumb_label.pixmap()
    assert thumb_pixmap is not None and not thumb_pixmap.isNull()
    assert thumb_pixmap.toImage() == expected.toImage(), \
        "侧栏缩略图残留旧图（按文件名缓存未随重新截图失效，DA-2 回归）"


# ---------- SubTask 6.3：截图在途切换步骤，结果被丢弃 ----------

def test_6_3_in_flight_screenshot_discarded_on_step_switch(editor_factory):
    editor = editor_factory()
    confirm_n_steps(editor, 2)
    gui_dir = editor.gui_dir
    old_refs = [s["screenshot"] for s in editor.steps_data]

    # 当前位于新步（current_step == len == 2），发起截图后立即切走
    assert editor.current_step == 2
    editor.take_screenshot()
    assert editor._screenshot_in_progress is True
    editor.go_previous()  # capture_step=2，切换后 current_step=1
    assert editor.current_step == 1
    flush_events(300)  # 推进 50ms singleShot + 后台线程 + 信号回收

    # 结果被丢弃：状态栏提示取消、锁立即复位、未新增步骤/文件
    assert "截图已取消" in editor.status_label.text()
    assert editor._screenshot_in_progress is False
    assert len(editor.steps_data) == 2
    for i, fn in enumerate(old_refs):
        assert editor.steps_data[i]["screenshot"] == fn
    assert _png_names(gui_dir) == sorted(old_refs)

    assert_all(editor)


# ---------- SubTask 6.4：桩件 fail_next，重截失败 ----------

def test_6_4_recapture_failure_preserves_old(editor_factory):
    editor = editor_factory()
    confirm_n_steps(editor, 2)
    gui_dir = editor.gui_dir

    editor.jump_to_step(0)  # 对第 1 步重截
    old_fn = editor.steps_data[0]["screenshot"]
    old_bytes = _read_bytes(gui_dir, old_fn)

    editor.screen_capture.fail_next()
    returned_fn = capture_and_wait(editor)

    # 失败路径：状态提示、步骤引用不变、旧文件保留且内容不变、锁复位
    assert "截图失败" in editor.status_label.text()
    assert editor._screenshot_in_progress is False
    assert returned_fn == old_fn
    assert editor._current_screenshot_filename == old_fn
    assert len(editor.steps_data) == 2
    assert editor.steps_data[0]["screenshot"] == old_fn
    assert _read_bytes(gui_dir, old_fn) == old_bytes
    assert len(_png_names(gui_dir)) == 2

    assert_all(editor)


# ---------- SubTask 6.5：重新截图后立即 finish_task ----------

def test_6_5_recapture_then_finish(editor_factory, modal):
    editor = editor_factory()
    confirm_n_steps(editor, 2)
    gui_dir = editor.gui_dir

    editor.jump_to_step(1)  # 重截末步
    old_fn = editor.steps_data[1]["screenshot"]
    new_fn = capture_and_wait(editor)
    new_bytes = _read_bytes(gui_dir, new_fn)
    assert new_bytes != _read_bytes(gui_dir, editor.steps_data[0]["screenshot"])
    if new_fn != old_fn:
        assert not os.path.exists(os.path.join(gui_dir, old_fn))

    # 重新确认该步回到末尾，随后立即结束任务
    fill_valid_step(editor)
    editor.confirm_step()
    flush_events(50)
    assert editor.current_step == len(editor.steps_data)
    finish_task(editor, modal)
    flush_events(100)

    # 最终 JSON 中被重截步的 observation.screenshot 指向新文件且文件存在
    data = assert_final_json(gui_dir, editor.gui_number)
    traj = data["messages"][1]["trajectory"]
    assert len(traj) == 3
    fn = traj[1]["observation"]["screenshot"]
    assert fn == new_fn
    assert os.path.isfile(os.path.join(gui_dir, fn))
    assert _read_bytes(gui_dir, fn) == new_bytes
