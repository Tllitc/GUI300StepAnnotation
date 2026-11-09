# -*- coding: utf-8 -*-
"""INV-14 配套修复脚本 tests/test_coords_center_repair.py。

覆盖 C 节的验收点：dry-run 不动盘、只平移不一致条目且保持宽高、其余条目
逐字节不变、总条数与 round 字段不变、写前留 .bak、幂等、drag 双中心各自
对齐、--verify 退出码、以及「脚本不依赖 PyQt5，可在无 GUI 采集机上独立跑」。
"""

import copy
import hashlib
import json
import os
import subprocess
import sys

import pytest

from tools import coords_center_repair as R

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "tools", "coords_center_repair.py")


# ---------------------------------------------------------------------------
# 夹具：一个含 3 步、其中 2 条 bbox 被污染的交付目录
# ---------------------------------------------------------------------------
GUI_NUMBER = "654321"

# step0：center 与 coordinate 一致（200,300），必须逐字节不动
OK_ENTRY = {"step": 0, "action": "left_click", "round": 0,
            "vertices": [100, 200, 300, 400], "center": [200, 300]}
# step1：scroll，bbox 冒领了别的工作的顶点（尺寸 64×15 沿用，中心须搬到 1533,928）
SCROLL_ENTRY = {"step": 1, "action": "scroll", "round": 0,
                "vertices": [120, 308, 184, 323], "center": [152, 315]}
# step2：drag，起点框正确、终点框被污染（尺寸 50×60 沿用，中心须到 110,130）
DRAG_ENTRY = {"step": 2, "action": "left_click_drag", "round": 0,
              "start_vertices": [10, 20, 40, 60], "start_center": [25, 40],
              "end_vertices": [500, 500, 550, 560], "end_center": [525, 530]}


def _dataset():
    def step(step_no, shot, action):
        return {
            "step": step_no,
            "intent": f"第 {step_no} 步",
            "CoT": "",
            "observation": {"screenshot": shot, "active_window": "测试App",
                            "ui_tree_segment": ""},
            "actions": [action],
        }

    trajectory = [
        step(0, f"gui_{GUI_NUMBER}_0001.png",
             {"action": "left_click", "coordinate": [200, 300], "element": "按钮"}),
        step(1, f"gui_{GUI_NUMBER}_0002.png",
             {"action": "scroll", "coordinate": [1533, 928], "pixels": -3, "element": ""}),
        step(2, f"gui_{GUI_NUMBER}_0003.png",
             {"action": "left_click_drag", "start_coordinate": [25, 40],
              "coordinate": [110, 130], "element": ""}),
    ]
    data = {
        "platform": "Windows 11",
        "messages": [
            {"role": "user", "instruction": "指令一"},
            {"role": "assistant", "trajectory": trajectory},
        ],
    }
    return data, [copy.deepcopy(OK_ENTRY), copy.deepcopy(SCROLL_ENTRY),
                  copy.deepcopy(DRAG_ENTRY)]


@pytest.fixture
def gui_dir(tmp_path):
    """写出一个已污染的交付目录（不落截图，脚本只读 JSON 与 coords）"""
    data, coords = _dataset()
    directory = tmp_path / f"gui_{GUI_NUMBER}"
    directory.mkdir()
    with open(directory / f"gui_{GUI_NUMBER}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(directory / f"gui_{GUI_NUMBER}_coords.json", "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)
    return str(directory)


def _read_coords(directory):
    with open(os.path.join(directory, f"gui_{GUI_NUMBER}_coords.json"),
              "r", encoding="utf-8") as f:
        return json.load(f)


def _digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _run_cli(args):
    """在子进程里跑脚本 —— 顺带证明它不依赖 GUI 环境"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, SCRIPT] + args, cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


# ---------------------------------------------------------------------------
# 1. dry-run 只报告不改盘
# ---------------------------------------------------------------------------
def test_dry_run_does_not_touch_disk(gui_dir, capsys):
    coords_path = os.path.join(gui_dir, f"gui_{GUI_NUMBER}_coords.json")
    before = _digest(coords_path)

    assert R.main([gui_dir, "--dry-run"]) == 0
    out = capsys.readouterr().out

    assert "step 1 [scroll]" in out
    assert "step 2 [left_click_drag]" in out
    assert "step 0" not in out
    assert "合计 2 条。" in out
    assert "未改动磁盘" in out
    assert _digest(coords_path) == before
    assert not os.path.exists(coords_path + ".coords_pre-repair.bak")


# ---------------------------------------------------------------------------
# 2. apply：只动不一致的条目，宽高与 round 保持
# ---------------------------------------------------------------------------
def test_apply_repairs_only_mismatched_entries(gui_dir, capsys):
    original = _read_coords(gui_dir)

    assert R.main([gui_dir, "--apply"]) == 0
    saved = _read_coords(gui_dir)

    # 条数与顺序不变，未被污染的条目逐字段不变
    assert len(saved) == len(original) == 3
    assert saved[0] == original[0]
    # round 字段原样保留（不注入、不删除）
    assert [e["round"] for e in saved] == [0, 0, 0]
    # 键序保持：重建只做值替换，不重排键
    assert list(saved[1].keys()) == list(original[1].keys())
    # 单框：中心精确等于 coordinate，宽高沿用原条目
    assert saved[1]["center"] == [1533, 928]
    assert saved[1]["vertices"] == [1501, 921, 1565, 936]
    w = saved[1]["vertices"][2] - saved[1]["vertices"][0]
    h = saved[1]["vertices"][3] - saved[1]["vertices"][1]
    assert (w, h) == (64, 15)

    # drag：起点框不动，终点框各自对齐
    assert saved[2]["start_vertices"] == original[2]["start_vertices"]
    assert saved[2]["start_center"] == [25, 40]
    assert saved[2]["end_center"] == [110, 130]
    assert saved[2]["end_vertices"] == [85, 100, 135, 160]
    assert (saved[2]["end_vertices"][2] - saved[2]["end_vertices"][0],
            saved[2]["end_vertices"][3] - saved[2]["end_vertices"][1]) == (50, 60)

    # 最终 JSON 一个字都不该动
    with open(os.path.join(gui_dir, f"gui_{GUI_NUMBER}.json"),
              "r", encoding="utf-8") as f:
        assert json.load(f)["messages"][1]["trajectory"][1]["actions"][0]["coordinate"] == [1533, 928]


# ---------------------------------------------------------------------------
# 3. 写前留备份 + 原子写（同目录不留 tmp）
# ---------------------------------------------------------------------------
def test_apply_backs_up_original_coords(gui_dir):
    coords_path = os.path.join(gui_dir, f"gui_{GUI_NUMBER}_coords.json")
    with open(coords_path, "rb") as f:
        original_bytes = f.read()

    assert R.main([gui_dir, "--apply"]) == 0

    backup = coords_path + ".coords_pre-repair.bak"
    assert os.path.isfile(backup)
    with open(backup, "rb") as f:
        assert f.read() == original_bytes
    assert not os.path.exists(os.path.join(gui_dir, f".gui_{GUI_NUMBER}_coords.json.tmp"))


# ---------------------------------------------------------------------------
# 4. 幂等
# ---------------------------------------------------------------------------
def test_repair_is_idempotent(gui_dir, capsys):
    assert R.main([gui_dir, "--apply"]) == 0
    coords_path = os.path.join(gui_dir, f"gui_{GUI_NUMBER}_coords.json")
    after_first = _digest(coords_path)

    capsys.readouterr()
    assert R.main([gui_dir, "--dry-run"]) == 0
    assert "发现 0 条" in capsys.readouterr().out

    assert R.main([gui_dir, "--apply"]) == 0
    assert _digest(coords_path) == after_first


# ---------------------------------------------------------------------------
# 5. --verify 退出码
# ---------------------------------------------------------------------------
def test_verify_reports_exit_code(gui_dir):
    assert R.main([gui_dir, "--verify"]) == 1
    assert R.main([gui_dir, "--apply"]) == 0
    assert R.main([gui_dir, "--verify"]) == 0


def test_verify_runs_without_pyqt5(gui_dir):
    """脚本必须能在没有 Qt 的采集机上独立跑（不 import PyQt5）"""
    code = ("import sys, tools.coords_center_repair as m;"
            "assert not any(n.split('.')[0] == 'PyQt5' for n in sys.modules);"
            "print('NO_QT_OK')")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8")
    assert "NO_QT_OK" in result.stdout, result.stderr

    result = _run_cli([gui_dir, "--verify"])
    assert result.returncode == 1
    assert "center" in result.stdout


# ---------------------------------------------------------------------------
# 6. 归属层：旧 coords 无 round 字段按 (step, action) 有序消费
# ---------------------------------------------------------------------------
def test_legacy_entry_without_round_is_matched(gui_dir):
    data, coords = _dataset()
    for entry in coords:
        entry.pop("round", None)
    # 同一步序在两轮里重复：无 round 时必须靠 action 区分，不能互相顶替
    second_round = copy.deepcopy(data["messages"][1]["trajectory"])
    for step in second_round:
        step["observation"]["screenshot"] = step["observation"]["screenshot"].replace(
            "000", "100")
    data["messages"].append({"role": "user", "instruction": "指令二"})
    data["messages"].append({"role": "assistant", "trajectory": second_round})
    with open(os.path.join(gui_dir, f"gui_{GUI_NUMBER}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(gui_dir, f"gui_{GUI_NUMBER}_coords.json"), "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)

    _number, trajectories, on_disk, _path = R.load_dataset(gui_dir)
    positions, unclaimed = R.match_entries_to_steps(trajectories, on_disk)
    assert unclaimed == []
    assert [positions[j] for j in range(3)] == [(0, 0), (0, 1), (0, 2)]

    assert R.main([gui_dir, "--apply"]) == 0
    saved = _read_coords(gui_dir)
    assert saved[1]["center"] == [1533, 928]
    assert all("round" not in entry for entry in saved)


def test_unclaimable_entry_is_reported_not_repaired(gui_dir):
    """step/action 都对不上任何步骤的条目一律不改写，并让校验报红"""
    coords = _read_coords(gui_dir)
    coords.append({"step": 99, "action": "left_click", "round": 7,
                   "vertices": [1, 2, 3, 4], "center": [2, 3]})
    with open(os.path.join(gui_dir, f"gui_{GUI_NUMBER}_coords.json"), "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)

    _number, trajectories, on_disk, _path = R.load_dataset(gui_dir)
    _new, changes, unclaimed = R.plan_repair(trajectories, on_disk)
    assert len(changes) == 2
    assert unclaimed == [3]
    assert on_disk[3] == _new[3]

    result = _run_cli([gui_dir, "--verify"])
    assert result.returncode == 1
    assert "无法归属" in result.stdout


# ---------------------------------------------------------------------------
# 7. 纯函数判定口径（A5 写回守卫与本脚本共用）
# ---------------------------------------------------------------------------
def test_center_tolerance_and_odd_size():
    # 奇数宽高向下取整：center = x + w//2，1px 内不算偏差
    assert R.center_of([0, 0, 65, 16]) == (32, 8)
    assert R.translate_vertices([0, 0, 65, 16], (100, 200)) == [68, 192, 133, 208]
    assert R.center_of(R.translate_vertices([0, 0, 65, 16], (100, 200))) == (100, 200)
    mismatched, _detail = R.entry_coordinate_mismatch(
        {"action": "left_click", "vertices": [0, 0, 65, 16], "center": [32, 8]},
        [33, 9])
    assert mismatched is False
    mismatched, _detail = R.entry_coordinate_mismatch(
        {"action": "left_click", "vertices": [0, 0, 65, 16], "center": [32, 8]},
        [34, 9])
    assert mismatched is True


def test_unusable_coordinate_is_skipped():
    entry = {"action": "scroll", "vertices": [120, 308, 184, 323], "center": [152, 315]}
    assert R.entry_coordinate_mismatch(entry, None)[0] is None
    assert R.entry_coordinate_mismatch(entry, [0, 0])[0] is None
    assert R.entry_coordinate_mismatch(entry, "bad")[0] is None
    # 非坐标动作不参与判定
    assert R.entry_coordinate_mismatch(
        {"action": "wait", "vertices": [0, 0, 1, 1], "center": [0, 0]}, [999, 999])[0] is None
    # 框本身残缺（无法解析 center）→ 报不一致而非静默跳过
    assert R.entry_coordinate_mismatch({"action": "scroll"}, [10, 10])[0] is True


def test_coord_pair_rejects_bool_and_short_arrays():
    assert R.coord_pair([True, 5]) is None
    assert R.coord_pair([5]) is None
    assert R.coord_pair((1.0, 2.0)) == (1, 2)
    assert R.is_zero_pair((0, 0)) is True
    assert R.is_zero_pair((0, 1)) is False
