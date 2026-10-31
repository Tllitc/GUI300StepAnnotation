# -*- coding: utf-8 -*-
"""冒烟测试：不依赖 iPhone 真机走通“截图 -> 标注 -> 确认 -> 多步 -> 结束落盘”
与模态对话框自动应答两条主链路。

运行（在 ios端 目录）::

    python -m pytest tests -q
"""

import os

from helpers import walk_steps, finish_task
from invariants import (
    SCREENSHOT_NAME_RE,
    assert_all,
    assert_disk_consistency,
    assert_final_json_consistency,
    assert_sidebar_consistency,
)


def test_smoke_walk_and_finish(editor, qapp):
    """3 步 click 采集 + terminate 结束：模型/磁盘/侧栏/草稿/最终 JSON 全链路一致。"""
    # ---- 采集 3 步 ----
    walk_steps(editor, 3, action="click")

    assert len(editor.steps_data) == 3
    for step in editor.steps_data:
        assert os.path.isfile(step["screenshot_filepath"])
        assert SCREENSHOT_NAME_RE.match(step["screenshot"])

    # 过程中全套不变量（含草稿落盘校验）
    assert_all(editor)

    # ---- terminate 结束任务（对话框自动答 No：不继续新任务）----
    finish_task(editor, continue_new=False)
    qapp.processEvents()

    gui_dir = editor.gui_dir
    # rounds 已被消费进最终文件，steps_data 被清空
    assert editor._draft_discarded is True

    # 最终产物存在且交叉一致
    assert os.path.isfile(os.path.join(gui_dir, "gui_000001.json"))
    assert os.path.isfile(os.path.join(gui_dir, "gui_000001_coords.json"))
    assert_final_json_consistency(
        gui_dir,
        gui_dir=gui_dir,
        expected_rounds=1,
    )

    # 草稿已删除
    draft_files = [f for f in os.listdir(gui_dir) if f.endswith("_draft.json")]
    assert draft_files == [], f"任务结束后草稿应被删除，仍存在：{draft_files}"

    # 4 张严格命名截图（3 个 click 步 + 1 个 terminate 步），无孤儿
    pngs = {f for f in os.listdir(gui_dir) if SCREENSHOT_NAME_RE.match(f)}
    assert len(pngs) == 4, f"预期 4 张截图，实际 {sorted(pngs)}"


def test_dialog_auto_accept(editor, dialogs):
    """删除步骤弹“确认删除”时由 dialogs fixture 自动答 Yes。"""
    walk_steps(editor, 3, action="click")
    assert len(editor.steps_data) == 3

    removed_name = editor.steps_data[1]["screenshot"]

    # 回到第 2 步并删除（question 自动答 Yes）
    editor.display_step(1)
    n_questions_before = sum(1 for c in dialogs.calls if c[0] == "question")
    editor.delete_current_step()

    question_calls = [c for c in dialogs.calls if c[0] == "question"]
    assert len(question_calls) == n_questions_before + 1, "删除流程未弹确认框"

    assert len(editor.steps_data) == 2, "自动确认后步骤应减 1"
    assert all(s["screenshot"] != removed_name for s in editor.steps_data), (
        "被删步骤的截图引用仍残留在 steps_data"
    )
    assert_sidebar_consistency(editor)

    # 被删截图文件应一并从磁盘移除（剩余步无引用）
    assert not os.path.exists(os.path.join(editor.gui_dir, removed_name)), (
        f"被删步骤截图未从磁盘清理：{removed_name}"
    )
    assert_disk_consistency(editor)
