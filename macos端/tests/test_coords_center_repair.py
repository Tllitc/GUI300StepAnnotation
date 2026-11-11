# -*- coding: utf-8 -*-
"""coords 中心匹配 / 冒领不复现 回归测试（macOS 端，产品侧）。

对应 2938cd1 的 coords 冒领修复与 INV-14 的判定口径。Windows/根目录版本把纯函数
放在离线脚本 tools/coords_center_repair.py 里、产品侧从该脚本导入；macos端 不落地
该脚本（用户确认：仅用于修复历史问题数据、与产品代码解耦、不参与打包），而是把
同一份纯标准库实现内联进 annotation_editor.py。因此本文件直接测产品模块：

  1) 判定口径纯函数（center_of / coord_pair / is_zero_pair / entry_coordinate_mismatch）
     —— 与写回守卫、测试不变量 INV-14 共用同一份实现，杜绝三处口径漂移；
  2) 冒领不复现：_find_coord_entry 彻底删除位置兜底，step 落空一律 None；
  3) center 恢复匹配：_find_coord_entry_by_center 只在「已验证一致」时认领；
  4) 没有框 ≠ 全屏：_rect_info_from_coord_entry 缺顶点返回空 rect + None，
     不再凭空判成 fullscreen（旧写法会让全屏豁免把「coords 少条目」静默放行）。
"""

import annotation_editor as _ae

COORD_TYPES = _ae.AnnotationEditor


# ---------------------------------------------------------------------------
# 1. 判定口径：center_of 产品取整（x + w//2，奇数宽高向下取整）
# ---------------------------------------------------------------------------
def test_center_of_uses_product_floor_rounding():
    # 65 宽 → 65//2=32；16 高 → 8。中心一律由 vertices 重算
    assert _ae.center_of([0, 0, 65, 16]) == (32, 8)
    assert _ae.center_of([10, 20, 110, 220]) == (60, 120)
    # vertices 缺失 / 过短 → None（无法解析，交给上层报「缺陷」而非静默跳过）
    assert _ae.center_of([1, 2]) is None
    assert _ae.center_of(None) is None


def test_coord_actions_include_scroll_and_type():
    # B6 口径统一：scroll / type 需要拉框，必须落在同一常量里
    for act in ("scroll", "type", "left_click", "left_click_drag"):
        assert act in _ae.COORD_ACTION_TYPES
    assert "wait" not in _ae.COORD_ACTION_TYPES


# ---------------------------------------------------------------------------
# 2. coord_pair / is_zero_pair 容错
# ---------------------------------------------------------------------------
def test_coord_pair_rejects_bool_short_and_nan():
    assert _ae.coord_pair([True, 5]) is None      # bool 是 int 子类，属脏数据
    assert _ae.coord_pair([5]) is None            # 长度不足
    assert _ae.coord_pair("bad") is None          # 非数组
    assert _ae.coord_pair([float("nan"), 5]) is None
    assert _ae.coord_pair((1.0, 2.0)) == (1, 2)   # 归一为 int
    assert _ae.coord_pair([1, 2, 3]) == (1, 2)    # 只取前两轴


def test_is_zero_pair():
    assert _ae.is_zero_pair((0, 0)) is True
    assert _ae.is_zero_pair((0, 1)) is False
    assert _ae.is_zero_pair(None) is False


# ---------------------------------------------------------------------------
# 3. entry_coordinate_mismatch：单框 / drag 双轴 / 无坐标跳过 / 残缺报缺陷
# ---------------------------------------------------------------------------
def test_mismatch_single_box():
    ok = {"action": "left_click", "vertices": [100, 200, 300, 400], "center": [200, 300]}
    # 中心 (200,300) 与 coordinate 一致 → False
    assert _ae.entry_coordinate_mismatch(ok, [200, 300])[0] is False
    # coordinate 偏 300px → True
    assert _ae.entry_coordinate_mismatch(ok, [500, 600])[0] is True


def test_mismatch_drag_dual_axis():
    drag = {"action": "left_click_drag",
            "start_vertices": [10, 20, 40, 60], "start_center": [25, 40],
            "end_vertices": [500, 500, 550, 560], "end_center": [525, 530]}
    start_coordinate = [25, 40]
    # 起点、终点都对齐 → False
    assert _ae.entry_coordinate_mismatch(drag, [525, 530], start_coordinate)[0] is False
    # 终点 coordinate 与 end 中心不符 → True（起点正确不赦免终点）
    assert _ae.entry_coordinate_mismatch(drag, [110, 130], start_coordinate)[0] is True


def test_mismatch_skips_when_no_usable_coordinate():
    entry = {"action": "scroll", "vertices": [120, 308, 184, 323], "center": [152, 315]}
    # 交付侧无可用坐标值 → None（跳过，不算缺陷）
    assert _ae.entry_coordinate_mismatch(entry, None)[0] is None
    assert _ae.entry_coordinate_mismatch(entry, [0, 0])[0] is None
    assert _ae.entry_coordinate_mismatch(entry, "bad")[0] is None
    # 非坐标动作不参与判定
    assert _ae.entry_coordinate_mismatch(
        {"action": "wait", "vertices": [0, 0, 1, 1], "center": [0, 0]}, [999, 999])[0] is None


def test_mismatch_broken_box_reports_defect_not_silent_skip():
    # 框本身残缺（无 vertices/center 可解析）→ 报不一致 True，而非静默 None
    assert _ae.entry_coordinate_mismatch({"action": "scroll"}, [10, 10])[0] is True
    # 条目不是 dict → True
    assert _ae.entry_coordinate_mismatch("not-a-dict", [10, 10])[0] is True


# ---------------------------------------------------------------------------
# 4. 冒领不复现：_find_coord_entry 彻底删除位置兜底
# ---------------------------------------------------------------------------
def test_find_coord_entry_exact_step_match_only():
    coords = [
        {"step": 1, "action": "left_click", "vertices": [0, 0, 10, 10]},
        {"step": 2, "action": "scroll", "vertices": [20, 20, 30, 30]},
        {"step": 3, "action": "type", "vertices": [40, 40, 50, 50]},
    ]
    assert COORD_TYPES._find_coord_entry(coords, 2) is coords[1]
    # step 落空：即便列表里还有条目，也绝不按位置回退冒领 —— 返回 None
    assert COORD_TYPES._find_coord_entry(coords, 5) is None
    assert COORD_TYPES._find_coord_entry(coords, 0) is None


def test_find_coord_entry_ignores_bool_dirty_step():
    # step 写成 true/false 属脏数据，即便 == 1 也不参与匹配
    coords = [{"step": True, "action": "left_click", "vertices": [0, 0, 1, 1]}]
    assert COORD_TYPES._find_coord_entry(coords, True) is None
    assert COORD_TYPES._find_coord_entry(coords, 1) is None


def test_find_coord_entry_empty_inputs():
    assert COORD_TYPES._find_coord_entry([], 1) is None
    assert COORD_TYPES._find_coord_entry(None, 1) is None


# ---------------------------------------------------------------------------
# 5. center 恢复匹配：仅在「已验证一致」时认领
# ---------------------------------------------------------------------------
def test_find_by_center_claims_only_verified_entry():
    coords = [
        {"step": 99, "action": "left_click", "vertices": [100, 200, 300, 400],
         "center": [200, 300]},
    ]
    # step 漂移到 99，但框中心与 coordinate 逐轴一致 → 按 center 恢复认领
    claimed = set()
    got = COORD_TYPES._find_coord_entry_by_center(
        coords, "left_click", [200, 300], None, claimed)
    assert got is coords[0]
    assert id(coords[0]) in claimed


def test_find_by_center_refuses_mismatch_and_unusable():
    coords = [
        {"step": 99, "action": "left_click", "vertices": [100, 200, 300, 400],
         "center": [200, 300]},
    ]
    # coordinate 与中心不符（mismatched=True）→ 不认领
    assert COORD_TYPES._find_coord_entry_by_center(
        coords, "left_click", [999, 999], None, set()) is None
    # 交付侧无可用坐标值（mismatched=None）→ 证据不足，不认领
    assert COORD_TYPES._find_coord_entry_by_center(
        coords, "left_click", None, None, set()) is None


def test_find_by_center_action_and_claim_guards():
    coords = [
        {"step": 1, "action": "scroll", "vertices": [100, 200, 300, 400],
         "center": [200, 300]},
    ]
    # action 不同 → 不跨动作认领
    assert COORD_TYPES._find_coord_entry_by_center(
        coords, "left_click", [200, 300], None, set()) is None
    # 非坐标动作查询 → 直接返回 None（guard）
    assert COORD_TYPES._find_coord_entry_by_center(
        coords, "wait", [200, 300], None, set()) is None
    # 已被认领 → 跳过，返回 None
    pre_claimed = {id(coords[0])}
    assert COORD_TYPES._find_coord_entry_by_center(
        coords, "scroll", [200, 300], None, pre_claimed) is None


# ---------------------------------------------------------------------------
# 6. 没有框 ≠ 全屏：_rect_info_from_coord_entry 缺顶点返回空 rect + None
# ---------------------------------------------------------------------------
def test_rect_info_missing_box_is_not_fullscreen():
    # 条目缺顶点：返回空 rect 与 None，交由上层判定是真全屏还是框丢失
    assert COORD_TYPES._rect_info_from_coord_entry({}) == ((), None)
    assert COORD_TYPES._rect_info_from_coord_entry({"action": "left_click"}) == ((), None)
    # 顶点长度不足 4 → 同样视为无框，不凭空判 fullscreen
    assert COORD_TYPES._rect_info_from_coord_entry(
        {"vertices": [1, 2, 3]}) == ((), None)
    # 非 dict → ((), None)
    assert COORD_TYPES._rect_info_from_coord_entry(None) == ((), None)


def test_rect_info_single_and_drag():
    # 单框 → ((x, y, w, h), None)
    assert COORD_TYPES._rect_info_from_coord_entry(
        {"vertices": [100, 200, 300, 400]}) == ((100, 200, 200, 200), None)
    # drag 双框 → ((rect_start, rect_end), "drag")
    drag = {"start_vertices": [10, 20, 40, 60], "end_vertices": [500, 500, 550, 560]}
    assert COORD_TYPES._rect_info_from_coord_entry(drag) == (
        ((10, 20, 30, 40), (500, 500, 50, 60)), "drag")
