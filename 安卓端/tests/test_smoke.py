# -*- coding: utf-8 -*-
"""冒烟测试：初始化 → 走 3 步 → answer_terminate 结束 → 产物可解析"""
import glob
import json
import os

from helpers import confirm_n_steps, finish_task, flush_events
from invariants import assert_all, assert_final_json


def test_smoke_three_steps_finish(editor_factory, modal):
    editor = editor_factory()
    assert editor.gui_number == "000001"

    # 前两步普通 click，第三步 answer_terminate 触发 _finish_task（完成框答 No）
    confirm_n_steps(editor, 2)
    assert_all(editor)
    finish_task(editor, modal)
    flush_events(100)

    gui_dir = editor.gui_dir
    data = assert_final_json(gui_dir, "000001")
    traj = data["messages"][1]["trajectory"]
    assert len(traj) == 3
    assert traj[-1]["actions"][0]["action"] == "answer"

    pngs = sorted(glob.glob(os.path.join(gui_dir, "*.png")))
    assert len(pngs) == 3

    for name in ("gui_000001.json", "gui_000001_coords.json"):
        path = os.path.join(gui_dir, name)
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            json.load(f)

    # 最终落盘成功后草稿已删除，任务标记完成
    assert not os.path.exists(os.path.join(gui_dir, "gui_000001_draft.json"))
    assert editor._task_completed is True
