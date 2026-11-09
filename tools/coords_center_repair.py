#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""coords bbox 中心对齐重建工具（离线维护脚本，非产品运行时代码）。

背景
----
交付数据存在一条构造级不变式：coords 条目的框中心必须等于同一步骤
`actions[0].coordinate`（拖拽为 `start_center == start_coordinate`、
`end_center == coordinate`）。理由是产品侧坐标输入框只读，其值只能由
`_init_editor_from_capture` 从框中心派生，再由 `get_data` 原样写进 JSON。

历史缺陷会打破该不变式：hydration 的「按位置下标回退取条目」让编辑态里
某些步骤冒领了别的步骤的顶点，落盘时污染 bbox 以正确 step 编号写回；
B6（采集层缺 scroll）则先让 coords 少几条，为下标漂移创造条件。
表现为 center 与 coordinate 偏离数百像素，而 INV-8 只查覆盖不查中心，
故这类数据一直假绿通过。

本脚本按 (round, step) 把每条 coords 归属到 trajectory 步骤，对不一致的
条目**保留原宽高、平移 vertices**，使框中心精确等于已交付的 coordinate。

语义提醒：这是**重建**而非还原 —— 原始框尺寸已不可恢复，宽高沿用盘上
原条目，中心对齐已交付 coordinate，产出须人工复核确认后再验收。

用法
----
    python tools/coords_center_repair.py <gui_XXXXXX 目录> [--dry-run|--apply]
                                         [--verify] [--tol 1]

只依赖标准库（不 import PyQt5），可在无 GUI 环境的采集机上运行；
其中的容差常量与比对/平移纯函数同时供产品写回守卫与测试不变量复用，
三条判定路径共用一份口径，杜绝再次漂移。
"""

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass

# 容差：产品侧 center = x + w // 2，奇数宽高会向下取整，故 1px 内视为一致。
# A5 写回守卫、B1/INV-14、本脚本必须共用该常量（改动只在这一处）。
COORD_CENTER_TOL = 1

DRAG_ACTION = "left_click_drag"

# 需要拉框并写入 coords 的动作全集，必须与产品 annotation_editor.COORD_ACTION_TYPES
# 同集。沿用 tests/invariants.py 的镜像常量惯例（脚本侧不得 import PyQt5，
# 无法直接引用产品常量），新增动作时三处一并更新。
COORD_ACTION_TYPES = frozenset({
    "left_click", "double_click", "triple_click", "right_click",
    "middle_click", "mouse_move", DRAG_ACTION, "type", "scroll",
})

GUI_DIR_RE = re.compile(r"^gui_(\d{6})$")


# ---------------------------------------------------------------------------
# 基础解析
# ---------------------------------------------------------------------------
def coord_pair(value):
    """[x, y] → (int, int)；不可解析（缺失/非数组/含非数值）返回 None。"""
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    pair = []
    for item in value[:2]:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        if item != item:  # NaN
            return None
        pair.append(int(item))
    return (pair[0], pair[1])


def is_zero_pair(pair):
    """(0, 0) 在交付数据里等价于「没有可用坐标」，不作为比对基准。"""
    return pair is not None and pair[0] == 0 and pair[1] == 0


def center_of(vertices):
    """vertices [x1, y1, x2, y2] → 产品口径的框中心 (x1 + w//2, y1 + h//2)。

    中心值一律由 vertices 重算而非直接读条目自带的 center —— center 本身
    也可能被污染，vertices 才是拉框现场的真实记录。
    """
    if not isinstance(vertices, (list, tuple)) or len(vertices) < 4:
        return None
    x1, y1, x2, y2 = (int(vertices[0]), int(vertices[1]),
                      int(vertices[2]), int(vertices[3]))
    return (x1 + (x2 - x1) // 2, y1 + (y2 - y1) // 2)


def _as_int(value):
    """严格整数取值：bool 不是步序，浮点 step 视为不可用。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def step_action(actions):
    """trajectory 条目的 actions → (action, coordinate, start_coordinate)。"""
    if not isinstance(actions, list):
        return None, None, None
    for item in actions:
        if not isinstance(item, dict):
            continue
        return item.get("action"), item.get("coordinate"), item.get("start_coordinate")
    return None, None, None


def step_action_info(step_data):
    """trajectory 条目 → (action, coordinate, start_coordinate)；非对象条目返回空。"""
    if not isinstance(step_data, dict):
        return None, None, None
    return step_action(step_data.get("actions"))


# ---------------------------------------------------------------------------
# 判定：center ↔ coordinate 是否一致
# ---------------------------------------------------------------------------
def entry_coordinate_mismatch(entry, coordinate=None, start_coordinate=None,
                              tol=COORD_CENTER_TOL):
    """单条 coords 条目与其所属步骤的坐标值比对。

    :return: (result, detail)
        result=True  不一致（或 center/vertices 不可解析），需要人工处置
        result=False 一致
        result=None  交付侧没有可用坐标值，无从比对（跳过，不算缺陷）
        detail 为可直接展示给人看的差异说明
    """
    if not isinstance(entry, dict):
        return True, "条目不是 JSON 对象"
    action = entry.get("action")
    if action not in COORD_ACTION_TYPES:
        return None, f"动作 {action!r} 无需坐标"

    if action == DRAG_ACTION:
        # (说明, vertices 值, center 值, 该框应对齐的 JSON 坐标)
        axes = (("start_center", entry.get("start_vertices"), start_coordinate,
                 entry.get("start_center")),
                ("end_center", entry.get("end_vertices"), coordinate,
                 entry.get("end_center")))
    else:
        axes = (("center", entry.get("vertices"), coordinate, entry.get("center")),)

    reasons = []
    checked = 0
    for label, vertices_value, coord_value, center_value in axes:
        # 以 vertices 重算为准；vertices 缺失时退回条目自带的 center
        center = center_of(vertices_value) if isinstance(vertices_value, (list, tuple)) \
            else coord_pair(center_value)
        if center is None:
            reasons.append(f"盘上 {label} 无法解析")
            continue
        target = coord_pair(coord_value)
        if target is None or is_zero_pair(target):
            continue
        checked += 1
        dx = abs(center[0] - target[0])
        dy = abs(center[1] - target[1])
        if dx > tol or dy > tol:
            reasons.append(f"盘上 {label}={list(center)} / JSON coordinate={list(target)}"
                           f"（偏差 {dx},{dy}px）")
    if reasons:
        return True, "；".join(reasons)
    if not checked:
        return None, f"{action} 在交付 JSON 中无可用坐标值，跳过比对"
    return False, ""


# ---------------------------------------------------------------------------
# 修复：保宽高平移到 coordinate
# ---------------------------------------------------------------------------
def translate_vertices(vertices, target_center):
    """保持宽高不变，把 vertices 平移到指定中心。

    nx = cx - w//2 使 nx + w//2 == cx 精确成立（与产品 center 计算式同余）。
    """
    x1, y1, x2, y2 = (int(vertices[0]), int(vertices[1]),
                      int(vertices[2]), int(vertices[3]))
    w, h = x2 - x1, y2 - y1
    cx, cy = int(target_center[0]), int(target_center[1])
    nx1, ny1 = cx - w // 2, cy - h // 2
    return [nx1, ny1, nx1 + w, ny1 + h]


def _align_box(new_entry, vertices_key, center_key, coordinate, tol=COORD_CENTER_TOL):
    """把 new_entry 的一个框平移到中心 == coordinate；无需改动时返回 None。"""
    target = coord_pair(coordinate)
    if target is None or is_zero_pair(target):
        return None
    vertices = new_entry.get(vertices_key)
    if not isinstance(vertices, (list, tuple)) or len(vertices) < 4:
        return None
    old_center = center_of(vertices)
    if old_center is None:
        return None
    if abs(old_center[0] - target[0]) <= tol and abs(old_center[1] - target[1]) <= tol:
        return None
    new_vertices = translate_vertices(vertices, target)
    new_entry[vertices_key] = new_vertices
    new_entry[center_key] = list(center_of(new_vertices))
    return f"{center_key}: {list(old_center)} → {list(new_entry[center_key])}（尺寸不变）"


def repair_entry(entry, coordinate=None, start_coordinate=None, tol=COORD_CENTER_TOL):
    """返回 (new_entry, changes)。键序与原条目一致；无需改动时原样返回。"""
    changes = []
    if not isinstance(entry, dict) or entry.get("action") not in COORD_ACTION_TYPES:
        return entry, changes
    new_entry = dict(entry)
    if entry.get("action") == DRAG_ACTION:
        for label, vertices_key, center_key, coord_value in (
                ("起点", "start_vertices", "start_center", start_coordinate),
                ("终点", "end_vertices", "end_center", coordinate)):
            note = _align_box(new_entry, vertices_key, center_key, coord_value, tol)
            if note:
                changes.append(f"{label}{note}")
    else:
        note = _align_box(new_entry, "vertices", "center", coordinate, tol)
        if note:
            changes.append(note)
    return new_entry, changes


# ---------------------------------------------------------------------------
# 交付数据读取与归属
# ---------------------------------------------------------------------------
@dataclass
class Change:
    """一条待修复/已修复的偏差记录。"""
    round: int
    step: int
    action: str
    reason: str
    detail: str


def load_dataset(gui_dir):
    """读取 gui_XXXXXX 目录的最终 JSON 与 coords。

    :return: (gui_number, trajectories, coords, coords_path)
    """
    dir_name = os.path.basename(os.path.normpath(gui_dir or ""))
    match = GUI_DIR_RE.match(dir_name)
    if not match:
        raise ValueError(f"目录名不符合 gui_XXXXXX 形式：{dir_name!r}")
    gui_number = match.group(1)

    json_path = os.path.join(gui_dir, f"gui_{gui_number}.json")
    coords_path = os.path.join(gui_dir, f"gui_{gui_number}_coords.json")
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"最终 JSON 不存在：{json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    trajectories = []
    for message in data.get("messages") or []:
        if isinstance(message, dict) and message.get("role") == "assistant":
            traj = message.get("trajectory")
            trajectories.append(traj if isinstance(traj, list) else [])

    coords = []
    if os.path.isfile(coords_path):
        with open(coords_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            coords = raw
        elif isinstance(raw, dict) and isinstance(raw.get("coords"), list):
            coords = raw["coords"]
        else:
            raise ValueError(f"不支持的坐标文件格式：{coords_path}")
    return gui_number, trajectories, coords, coords_path


def match_entries_to_steps(trajectories, coords):
    """把每条 coords 归属到 (round, step)。

    第一趟按条目自带的 round/step 精确定位（B4 之后的交付件）；第二趟沿用
    INV-8 覆盖层的有序消费口径 —— 只认 (step, action) 同时命中的旧条目
    （B4 之前 Windows coords 不带 round）。仍无法归属的条目一律不改写，
    交由调用方报告：宁可漏修，不可错修。

    :return: (positions, unclaimed) positions 为 {条目下标: (round, step)}
    """
    positions = {}
    used = set()
    for j, entry in enumerate(coords):
        if not isinstance(entry, dict):
            continue
        r = _as_int(entry.get("round"))
        s = _as_int(entry.get("step"))
        if r is None or s is None:
            continue
        if 0 <= r < len(trajectories) and 0 <= s < len(trajectories[r]) and (r, s) not in used:
            positions[j] = (r, s)
            used.add((r, s))

    remaining = [(r, s) for r in range(len(trajectories))
                 for s in range(len(trajectories[r])) if (r, s) not in used]
    unclaimed = []
    for j, entry in enumerate(coords):
        if j in positions:
            continue
        s = _as_int(entry.get("step"))
        action = entry.get("action")
        hit = None
        if s is not None and action:
            for k, (r, cand_s) in enumerate(remaining):
                if cand_s != s:
                    continue
                if step_action_info(trajectories[r][cand_s])[0] == action:
                    hit = k
                    break
        if hit is None:
            unclaimed.append(j)
            continue
        r, cand_s = remaining.pop(hit)
        positions[j] = (r, cand_s)
    return positions, unclaimed


def _describe(coords, j, positions, trajectories):
    """给报告用的「条目在哪、属于哪一步」定位串。"""
    entry = coords[j] if isinstance(coords[j], dict) else {}
    pos = positions.get(j)
    if pos:
        return f"round {pos[0]} step {pos[1]} {entry.get('action')}"
    return f"coords[{j}] round={entry.get('round')!r} step={entry.get('step')!r} {entry.get('action')!r}"


def plan_repair(trajectories, coords, tol=COORD_CENTER_TOL):
    """算出修复方案，不改盘。

    :return: (new_coords, changes, unclaimed)
    """
    positions, unclaimed = match_entries_to_steps(trajectories, coords)
    new_coords = list(coords)
    changes = []
    for j, entry in enumerate(coords):
        pos = positions.get(j)
        if pos is None or not isinstance(entry, dict):
            continue
        r, s = pos
        action, coordinate, start_coordinate = step_action_info(trajectories[r][s])
        mismatched, reason = entry_coordinate_mismatch(
            entry, coordinate, start_coordinate, tol)
        if not mismatched:
            continue
        repaired, ops = repair_entry(entry, coordinate, start_coordinate, tol)
        if not ops:
            # 判定不一致但无法安全平移（如交付侧本就没有该轴坐标）：
            # 保持原条目不动，交给 --verify 继续报红
            continue
        new_coords[j] = repaired
        changes.append(Change(round=r, step=s, action=action or entry.get("action"),
                              reason=reason, detail="；".join(ops)))
    return new_coords, changes, unclaimed


def find_inconsistencies(trajectories, coords, tol=COORD_CENTER_TOL):
    """INV-14 等价断言的数据侧实现：列出所有仍不一致的条目。

    :return: [(定位串, detail), ...]，空列表表示通过
    """
    positions, unclaimed = match_entries_to_steps(trajectories, coords)
    problems = []
    for j, entry in enumerate(coords):
        pos = positions.get(j)
        if pos is None:
            continue
        r, s = pos
        action, coordinate, start_coordinate = step_action_info(trajectories[r][s])
        mismatched, detail = entry_coordinate_mismatch(
            entry, coordinate, start_coordinate, tol)
        if mismatched:
            problems.append((_describe(coords, j, positions, trajectories), detail))
    for j in unclaimed:
        if isinstance(coords[j], dict) and coords[j].get("action") in COORD_ACTION_TYPES:
            problems.append((_describe(coords, j, positions, trajectories),
                             "无法归属到任何步骤（step/action 都对不上），未参与校验"))
    return problems


# ---------------------------------------------------------------------------
# 落盘
# ---------------------------------------------------------------------------
def _atomic_write_json(filepath, payload):
    """与 data_manager._atomic_write_json 同法：tmp + fsync + os.replace。

    直接 open(path, "w") 会在序列化失败时留下半截文件，已交付数据不可恢复。
    """
    directory = os.path.dirname(filepath) or "."
    tmp_path = os.path.join(directory, f".{os.path.basename(filepath)}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, filepath)


def apply_repair(coords_path, new_coords):
    """写前先留 .coords_pre-repair.bak，再原子替换。返回备份路径。"""
    backup = f"{coords_path}.coords_pre-repair.bak"
    if os.path.isfile(coords_path):
        shutil.copy2(coords_path, backup)
    _atomic_write_json(coords_path, new_coords)
    return backup


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _report(changes, unclaimed, applying):
    """打印修复清单；applying 只影响动词，不影响判定口径。"""
    verb = "已平移" if applying else "将平移"
    if not changes:
        print("发现 0 条 center 与 coordinate 不一致的条目，无需修复。")
    for change in changes:
        print(f"- round {change.round} step {change.step} [{change.action}]："
              f"{change.reason} → {verb}：{change.detail}")
    print(f"合计 {len(changes)} 条。")
    if unclaimed:
        print(f"警告：{len(unclaimed)} 条 coords 无法归属到步骤，本脚本不改动它们："
              + ", ".join(f"coords[{j}]" for j in unclaimed))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="coords_center_repair",
        description="按已交付 coordinate 重建 coords bbox 中心（保留宽高）",
    )
    parser.add_argument("gui_dir", help="gui_XXXXXX 任务目录（本地副本或 UNC 路径）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只报告不改盘（默认）")
    mode.add_argument("--apply", action="store_true", help="写回修复结果（自动留 .bak）")
    parser.add_argument("--verify", action="store_true",
                        help="校验 center↔coordinate；仍有不一致则以 1 退出")
    parser.add_argument("--tol", type=int, default=COORD_CENTER_TOL,
                        help=f"中心容差（默认 {COORD_CENTER_TOL}px，取整误差）")
    args = parser.parse_args(argv)

    try:
        gui_number, trajectories, coords, coords_path = load_dataset(args.gui_dir)
    except Exception as e:
        print(f"读取交付数据失败：{e}", file=sys.stderr)
        return 2

    print(f"gui_{gui_number}：{len(trajectories)} 轮 / {len(coords)} 条 coords")

    if args.apply:
        new_coords, changes, unclaimed = plan_repair(trajectories, coords, args.tol)
        _report(changes, unclaimed, applying=True)
        if changes:
            backup = apply_repair(coords_path, new_coords)
            print(f"原 coords 已备份为 {os.path.basename(backup)}")
            print(f"已写回 {coords_path}（语义：中心对齐已交付 coordinate，"
                  f"尺寸沿用原条目宽高，供复核确认）")
        elif not os.path.isfile(coords_path):
            print("coords 文件不存在，未做任何写入。")
        problems = find_inconsistencies(trajectories, new_coords, args.tol)
    else:
        if not args.verify:
            new_coords, changes, unclaimed = plan_repair(trajectories, coords, args.tol)
            _report(changes, unclaimed, applying=False)
            if changes:
                print("（当前为 dry-run，未改动磁盘；确认无误后加 --apply）")
            return 0
        problems = find_inconsistencies(trajectories, coords, args.tol)

    if problems:
        print(f"校验未通过：仍有 {len(problems)} 项 center 与 coordinate 不一致：")
        for where, detail in problems:
            print(f"  - {where}：{detail}")
        return 1
    print("校验通过：全部 coords 条目的框中心与 JSON coordinate 一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
