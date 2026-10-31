# -*- coding: utf-8 -*-
"""撤销（undo_last_step）测试组。

覆盖：
  4.1 末位已确认步撤销（等同删除）的全套一致性；
  4.2 回到中间步撤销：删除的是“当前步”，后续步前移、引用不串；
  4.3 D-7 修复回归：已截图未确认的新步撤销（静默回收 pending 截图）；
  4.4 空状态撤销（information 提示且无副作用）与选 No 取消（状态完全不变）。

只依赖 conftest 夹具与 helpers/invariants，不修改任何产品代码。
"""

import copy
import os

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QMessageBox

import annotation_editor as _ae
from helpers import capture, fill_step, confirm, walk_steps, flush_draft
from invariants import (
    SCREENSHOT_NAME_RE,
    assert_all,
    assert_disk_consistency,
    assert_sidebar_consistency,
    assert_draft_consistency,
)


# ----------------------------------------------------------------------
# 本文件本地辅助
# ----------------------------------------------------------------------

def _strict_png_names(gui_dir):
    """gui_dir 下当前全部严格命名 PNG（与 invariants 同口径的本地只读快照）。"""
    if not os.path.isdir(gui_dir):
        return set()
    return {f for f in os.listdir(gui_dir) if SCREENSHOT_NAME_RE.match(f)}


def _install_information_spy(monkeypatch):
    """给 QMessageBox.information 装一个记录器。

    conftest 的 DialogController 只记录 question/getText，而空步拦截/无步可删
    走的是 information 分支，测试需要断言它确实弹出过。返回记录列表。
    """
    records = []

    def _spy_information(parent=None, title="", text="", *args, **kwargs):
        records.append((title, text))
        return None

    monkeypatch.setattr(_ae.QMessageBox, "information", _spy_information)
    return records


# ----------------------------------------------------------------------
# 4.1 末位已确认步撤销
# ----------------------------------------------------------------------

def test_undo_last_confirmed_step(editor, dialogs, qapp):
    """walk 4 步后定位到末步再 undo：等同删除末步，全套不变量成立，图步映射不串。"""
    walk_steps(editor, 4, action="click")

    # confirm 后 current_step == len(steps_data)（新步编辑位）；
    # 要撤销“最后一个已确认步”，需先 display_step 回末位。
    editor.display_step(3)
    assert editor.current_step == 3

    before_names = [s["screenshot"] for s in editor.steps_data]
    removed_name = before_names[3]
    removed_path = os.path.join(editor.gui_dir, removed_name)
    assert os.path.isfile(removed_path)

    # 被删图在桩件里对应的截图序号（0-based），删除前用 classify 留证
    shot_idx = editor.screen_capture.classify(removed_path)
    assert shot_idx == 3, f"末步图应反查到第 4 次截图(序号3)，实际 {shot_idx}"

    n_question_before = sum(1 for c in dialogs.calls if c[0] == "question")
    editor.undo_last_step()
    qapp.processEvents()

    # 弹的是“确认撤销”问答且自动答 Yes
    question_calls = [c for c in dialogs.calls if c[0] == "question"]
    assert len(question_calls) == n_question_before + 1
    assert question_calls[-1][1] == "确认撤销"

    # 模型：步数减 1，前 3 步引用原样保留，被删引用消失
    assert len(editor.steps_data) == 3
    assert [s["screenshot"] for s in editor.steps_data] == before_names[:3]
    assert all(s["screenshot"] != removed_name for s in editor.steps_data)

    # 磁盘：被删图已移除，整体无孤儿
    assert not os.path.exists(removed_path), "撤销末步后其截图文件仍残留磁盘"
    assert removed_name not in _strict_png_names(editor.gui_dir)

    # 图步映射：剩余每一步磁盘图仍能按 classify 反查到原截图序号
    for i, step in enumerate(editor.steps_data):
        idx = editor.screen_capture.classify(step["screenshot_filepath"])
        assert idx == i, f"撤销后第 {i} 步图反查截图序号为 {idx}，映射串位"

    # 停位：删的是末位，current_step 回退到新末位 2
    assert editor.current_step == 2

    # 全套一致性：模型/磁盘/侧栏/草稿/测量态
    assert_all(editor)


# ----------------------------------------------------------------------
# 4.2 中间步撤销：删除当前步而非总是末步
# ----------------------------------------------------------------------

def test_undo_at_middle_step_deletes_current(editor, dialogs, qapp):
    """回到第 2 步（index=1）撤销：删的是当前步，第 3、4 步前移，引用/动作不串。"""
    # 用不同 intent 标记每步，便于验证“后续步数据前移且不串”
    for i in range(4):
        capture(editor)
        fill_step(editor, action="click", intent=f"STEP-{i + 1}")
        confirm(editor)
    assert len(editor.steps_data) == 4

    original = [
        (s["screenshot"], s.get("intent"), copy.deepcopy(s.get("action_data")))
        for s in editor.steps_data
    ]
    middle_name = original[1][0]
    middle_path = os.path.join(editor.gui_dir, middle_name)

    # 回到中间步 index=1 再撤销
    editor.go_previous()  # 4(编辑位) -> 3
    editor.display_step(1)
    assert editor.current_step == 1

    n_question_before = sum(1 for c in dialogs.calls if c[0] == "question")
    editor.undo_last_step()
    qapp.processEvents()
    assert sum(1 for c in dialogs.calls if c[0] == "question") == n_question_before + 1

    # 删除的是中间步：长度 3，保留的是原 0/2/3 步，顺序前移
    assert len(editor.steps_data) == 3
    remaining = [(s["screenshot"], s.get("intent")) for s in editor.steps_data]
    assert remaining == [
        (original[0][0], original[0][1]),
        (original[2][0], original[2][1]),
        (original[3][0], original[3][1]),
    ]

    # 末步没有被误删
    assert editor.steps_data[-1]["screenshot"] == original[3][0]
    assert editor.steps_data[-1].get("intent") == "STEP-4"
    # 中间步截图被清盘，其余图仍在
    assert not os.path.exists(middle_path)
    for s in editor.steps_data:
        assert os.path.isfile(s["screenshot_filepath"])

    # 图步映射随前移正确：位置 i 的图反查应为原截图序号 [0, 2, 3]
    expected_shot_idx = [0, 2, 3]
    for pos, expected in enumerate(expected_shot_idx):
        idx = editor.screen_capture.classify(
            editor.steps_data[pos]["screenshot_filepath"]
        )
        assert idx == expected, (
            f"中间删除后位置 {pos} 图反查截图序号 {idx} != 预期 {expected}（引用串位）"
        )

    # 停位合理：删除 index=1 后停在 index=1（承接前移来的原第 3 步）
    assert editor.current_step == 1
    assert editor.steps_data[1].get("intent") == "STEP-3"

    assert_all(editor)


# ----------------------------------------------------------------------
# 4.3 D-7 修复回归：已截图但未 confirm 的新步撤销
# ----------------------------------------------------------------------

def test_undo_screenshot_not_confirmed_D7(editor, dialogs, monkeypatch, qapp):
    """新步截图已落盘但尚未 confirm（current_step == len(steps_data)）时撤销。

    修复后正确行为：undo 问答 Yes 后静默丢弃未确认截图（不弹 information），
    磁盘当刻无无引用孤儿，current_step 回到最后已确认步并恢复其 UI；
    之后先 go_next 进入新步编辑位即可正常继续走步（序号可能回落复用同一编号，
    但磁盘文件是本次全新截图内容）。
    """
    info_records = _install_information_spy(monkeypatch)

    walk_steps(editor, 2, action="click")
    confirmed_names = [s["screenshot"] for s in editor.steps_data]
    assert editor.current_step == 2 and len(editor.steps_data) == 2

    # 截第 3 张图但不 confirm：图已落盘占序号，steps_data 仍只有 2 步
    orphan_name = capture(editor)
    orphan_path = os.path.join(editor.gui_dir, orphan_name)
    assert os.path.isfile(orphan_path)
    assert editor.current_step == len(editor.steps_data) == 2
    fill_step(editor, action="click")  # 仅填表，仍不 confirm

    n_question_before = sum(1 for c in dialogs.calls if c[0] == "question")
    editor.undo_last_step()
    qapp.processEvents()

    # 撤销问答正常弹过一次并被自动答 Yes；没有任何 information 弹窗
    assert (
        sum(1 for c in dialogs.calls if c[0] == "question") == n_question_before + 1
    )
    info_texts = [text for _t, text in info_records]
    assert not any("没有可删除" in t for t in info_texts), (
        f"未确认新步撤销不应弹‘当前没有可删除的步骤’：{info_texts}"
    )

    # 撤销当刻：pending 截图已回收，磁盘无孤儿；回到最后已确认步（index=1）
    assert not os.path.exists(orphan_path), (
        f"未确认截图撤销后应从磁盘回收：{orphan_name}"
    )
    refs = {s["screenshot"] for s in editor.steps_data}
    assert _strict_png_names(editor.gui_dir) == refs
    assert len(editor.steps_data) == 2
    assert editor.current_step == 1
    assert editor._current_screenshot_filename == confirmed_names[1]
    assert_all(editor)

    # 在最后已确认步上直接截图会原地覆盖该步；要新增步必须先进新步编辑位
    editor.go_next()
    QTest.qWait(0)
    assert editor.current_step == len(editor.steps_data) == 2
    assert editor._current_screenshot_filename is None

    # 新步截图复用刚释放的顶部序号 0003，但磁盘内容是全新截图（第 4 次）
    new_name = capture(editor)
    assert new_name == orphan_name
    new_path = os.path.join(editor.gui_dir, new_name)
    assert os.path.isfile(new_path)
    assert editor.screen_capture.classify(new_path) == 3
    fill_step(editor, action="click")
    confirm(editor)
    qapp.processEvents()
    assert len(editor.steps_data) == 3
    assert editor.steps_data[2]["screenshot"] == new_name
    assert_all(editor)

    # 再走一步，序号继续顺延
    capture(editor)
    fill_step(editor, action="click")
    confirm(editor)
    qapp.processEvents()
    assert len(editor.steps_data) == 4
    assert_all(editor)


# ----------------------------------------------------------------------
# 4.4 空状态撤销 + 选 No 取消
# ----------------------------------------------------------------------

def test_undo_empty_state_no_side_effect(editor, dialogs, monkeypatch, qapp):
    """空状态（无 steps_data、无截图）undo：information 提示、无异常、无副作用。"""
    info_records = _install_information_spy(monkeypatch)

    assert editor.steps_data == []
    assert editor._current_screenshot_filename is None
    pngs_before = _strict_png_names(editor.gui_dir)

    n_question_before = sum(1 for c in dialogs.calls if c[0] == "question")
    editor.undo_last_step()  # 不应抛异常
    qapp.processEvents()

    # 空状态直接 information 拦截，没有进入撤销确认问答
    assert len(info_records) >= 1, "空状态撤销未弹出 information 提示"
    assert any("没有可撤销" in text for _t, text in info_records), (
        f"空状态提示文案不符：{info_records}"
    )
    assert sum(1 for c in dialogs.calls if c[0] == "question") == n_question_before

    # 无副作用：模型仍空、磁盘无新增 PNG，且编辑器仍可正常走步
    assert editor.steps_data == []
    assert _strict_png_names(editor.gui_dir) == pngs_before
    walk_steps(editor, 1, action="click")
    assert len(editor.steps_data) == 1
    assert_all(editor)


def test_undo_cancel_with_no_keeps_everything(editor, dialogs, qapp):
    """walk 2 步后回到第 1 步，撤销问答选 No：模型/磁盘/侧栏/草稿与操作前完全一致。"""
    walk_steps(editor, 2, action="click")
    editor.display_step(0)

    # 操作前快照
    steps_snapshot = copy.deepcopy(editor.steps_data)
    current_before = editor.current_step
    pngs_before = _strict_png_names(editor.gui_dir)
    flush_draft(editor)
    draft_files_before = sorted(
        f for f in os.listdir(editor.gui_dir) if f.endswith("_draft.json")
    )

    dialogs.question_result = QMessageBox.No
    n_question_before = sum(1 for c in dialogs.calls if c[0] == "question")
    try:
        editor.undo_last_step()
        qapp.processEvents()
    finally:
        dialogs.question_result = QMessageBox.Yes

    # 弹了撤销问答但被取消
    assert sum(1 for c in dialogs.calls if c[0] == "question") == n_question_before + 1

    # 模型完全不变（深比较，含 action_data/vertices/截图引用）
    assert editor.steps_data == steps_snapshot
    assert len(editor.steps_data) == 2
    assert editor.current_step == current_before == 0

    # 磁盘文件集合不变、引用文件都在
    assert _strict_png_names(editor.gui_dir) == pngs_before
    for s in editor.steps_data:
        assert os.path.isfile(s["screenshot_filepath"])

    # 侧栏/草稿一致
    assert_sidebar_consistency(editor)
    assert_draft_consistency(editor)
    assert (
        sorted(f for f in os.listdir(editor.gui_dir) if f.endswith("_draft.json"))
        == draft_files_before
    )
    assert_disk_consistency(editor)
