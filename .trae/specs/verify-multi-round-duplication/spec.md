# 多轮重复采集回归验证 Spec

## Why
老版本产出的 `\\NAS-TC\GUI采集300step\Windows\程婧瑶\gui_000003\gui_000003.json` 出现多轮重复：4 轮 instruction 均为 "111"；每轮截图序号都从 `gui_000003_0001.png` 重新计数，新轮截图覆盖旧轮同名文件；崩溃/异常中止后续采导致同一批步骤被重复写入多个 trajectory（最终 JSON 引用 332 个截图名，磁盘仅 224 个 PNG）。经代码审查，当前版本的生产逻辑已不存在该缺陷，但缺少把该精确场景锁死的跨轮回归断言（现有 INV-8 只校验"轮内"截图唯一）。

## What Changes
- 新增一个复刻 gui_000003 场景的多轮回归测试：连续完成 4 轮采标（含 answer 续轮），断言最终 JSON 中**全部轮次**的截图名全局唯一且序号严格单调递增，磁盘 PNG 数量与 JSON 引用数量一致。
- 增强 `tests/invariants.py` 的 `assert_final_json`：新增跨轮截图名全局唯一断言（轮内唯一保留）。
- 不改动任何生产代码（`main.py` / `annotation_editor.py` / `data_manager.py`）。

## Impact
- Affected specs: 无既有 spec 直接对应（`fix-draft-resume` 为草稿生命周期修复，本 spec 是其结论的回归固化）
- Affected code:
  - `tests/invariants.py`（INV-8 增加跨轮断言）
  - `tests/test_dt_defects.py` 或同目录新增测试文件（新增多轮场景用例）

## 调查结论（当前版本为何不会复现）
1. **截图序号磁盘 max+1 全局递增**：`data_manager.get_next_screenshot_number`（data_manager.py:86-116）扫描 gui 目录已有文件取最大序号 +1；`save_screenshot`（data_manager.py:118-149）每次插入截图都分配新序号，跨轮不重置。`gui_number` 在整个任务生命周期内只分配一次（annotation_editor.py `on_capture_completed`），结构上杜绝跨轮同名覆盖。
2. **草稿时序修复 DT-1/DT-2/DT-3 在位**：`save_current_round` 不再内联写 draft（避免"rounds 已追加、steps 未清空"瞬间产生重复轮）；answer/terminate 分支先 `self.steps = []` 再防抖保存；`reset_for_new_task` 立即用空 current_steps 覆盖草稿。
3. **窗口/保存守卫在位**：`_discard_previous_editor` 销毁旧编辑器防幽灵窗口，`_is_closing` / `_capture_in_flight` / `_final_data_saved` 防重复保存。
4. 现有测试 21 项全部通过；DT-2 已断言 draft 中 rounds 与 current_steps 截图名集合不相交，但最终 JSON 层面尚无跨轮唯一断言。

## ADDED Requirements

### Requirement: 多轮截图全局唯一回归
系统的测试套件 SHALL 包含一个连续多轮采标场景，复刻 gui_000003 的 4 轮结构，并在最终 JSON 产物上保证跨轮不变量。

#### Scenario: 连续 4 轮采标后截图全局唯一且序号单调
- **WHEN** 测试模拟同一 gui 任务连续完成 4 轮（前轮以 answer 续轮，末轮 terminate 正常结束）
- **THEN** 最终 `gui_XXXXXX.json` 的 messages 含 4 个 user/assistant 交替对
- **AND** 所有轮次 trajectory 引用的截图名在全局范围内互不重复
- **AND** 截图序号随采集顺序严格单调递增（不出现每轮回到 0001）
- **AND** gui 目录内磁盘 PNG 文件集合与 JSON 引用集合完全一致（无覆盖、无悬空引用、无孤儿）

#### Scenario: INV-8 跨轮重复检测
- **WHEN** 最终 JSON 中两个不同轮次引用了同一截图名
- **THEN** `assert_final_json` 断言失败并报出重复的截图名与所在轮次

## MODIFIED Requirements

### Requirement: INV-8 最终产物一致
`assert_final_json` 在保留现有轮次 role 交替、step 编号连续、轮内截图唯一、引用文件存在等校验的基础上，SHALL 额外维护一个跨全部轮次的截图名集合；任一截图名在不同轮次重复出现时立即断言失败。
