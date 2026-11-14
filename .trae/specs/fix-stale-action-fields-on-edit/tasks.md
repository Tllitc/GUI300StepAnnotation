# Tasks

- [x] Task 1: Windows 端修复合并逻辑并新增回归测试（基准实现）
  - [x] SubTask 1.1: 在 [annotation_editor.py](file:///c:/Project/TC/300step采标工具/annotation_editor.py) 新增类常量 `_ACTION_PARAM_KEYS = {"coordinate", "start_coordinate", "text", "keys", "time", "pixels", "buttons"}`；修改 `_merge_step_with_original`（约 L3741-3746）的 actions[0] 缺失键补齐循环：当 `new_actions[0].get("action") != old_actions[0].get("action")` 时跳过 `_ACTION_PARAM_KEYS` 中的键，其余键照常深拷贝保留；同步更新函数 docstring。受保护字段回退、终止类动作规则、步骤级/observation 级补齐一律不动
  - [x] SubTask 1.2: 在 [tests/test_edit_completed.py](file:///c:/Project/TC/300step采标工具/tests/test_edit_completed.py) 新增回归用例：①合并单测——type→left_click 不带 text、drag→click 不带 start_coordinate、click→wait 不带 coordinate、scroll→click 不带 pixels、key→click 不带 keys；动作变更但未知键 foo 保留、CoT/active_window/ui_tree_segment/element/status 保留规则不变；同动作类型缺失键补齐不变；answer↔answer_terminate（序列化同为 answer）视为同类型。②编辑模式端到端——加载含 type 步骤的已完成 JSON，改 left_click 后确认 + save_edited_round，断言最终 JSON 无 text；silent 写回路径同样干净
  - [x] SubTask 1.3: 先在未修复代码上运行新用例确认失败（非假绿），再应用修复；全量 `pytest tests/`（QT_QPA_PLATFORM=offscreen）通过，既有保留类用例无回归

- [x] Task 2: macOS 端同步 Windows 修复
  - [x] SubTask 2.1: 在 [macos端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/macos端/annotation_editor.py) 对 `_merge_step_with_original`（约 L3851-3856）应用与 Task 1 完全对等的改造（同名常量、同判定条件、同 docstring 更新）
  - [x] SubTask 2.2: 在 [macos端/tests/test_edit_completed.py](file:///c:/Project/TC/300step采标工具/macos端/tests/test_edit_completed.py) 新增与 Task 1 对等的合并单测与端到端用例；验证修复前失败、修复后全量 `pytest macos端/tests/` 通过

- [x] Task 3: iOS 端修复合并逻辑并新增回归测试
  - [x] SubTask 3.1: 在 [ios端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/ios端/annotation_editor.py) 新增 `_ACTION_PARAM_KEYS` 常量；为 `_merge_original_missing`（L3485-3520）增加可选跳过键集参数（默认空，不影响其它调用）：dict 分支补齐缺失键时跳过该键集；actions 列表分支中当新旧元素均为含 "action" 键的 dict 且动作类型不同时，以 `_ACTION_PARAM_KEYS` 作为跳过键集递归合并。受保护键（_PROTECTED_ACTION_KEYS 等）逻辑不动
  - [x] SubTask 3.2: 在 [ios端/tests/test_edit_completed.py](file:///c:/Project/TC/300step采标工具/ios端/tests/test_edit_completed.py) 新增回归用例：合并单测（type→click 无 text、swipe→click 无 start_coordinate、click→wait 无 coordinate、scroll→click 无 pixels、system_button→click 无 buttons；未知键与受保护字段保留；同类型不变）+ save_edited_round 端到端（含 silent 路径）断言最终 JSON 动作干净
  - [x] SubTask 3.3: 验证修复前新用例失败，修复后全量 `pytest ios端/tests/` 通过

- [x] Task 4: 安卓端同步 iOS 修复
  - [x] SubTask 4.1: 在 [安卓端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/安卓端/annotation_editor.py) 对 `_merge_missing_keys`（L3898-3933）应用与 Task 3 完全对等的改造（同名常量、同参数、同动作变更判定）
  - [x] SubTask 4.2: 在 [安卓端/tests/test_edit_completed.py](file:///c:/Project/TC/300step采标工具/安卓端/tests/test_edit_completed.py) 新增与 Task 3 对等用例（另覆盖 key→click 无 keys）；验证修复前失败、修复后全量 `pytest 安卓端/tests/` 通过

- [x] Task 5: 四端全量回归与契约核对
  - [x] SubTask 5.1: 依次全量运行四端测试套件（offscreen），确认全部通过、无 flaky，既有 `test_edit_completed.py` 保留类用例与数据完整性防污染用例无回归
  - [x] SubTask 5.2: 核对最终 JSON/coords 输出契约未变（字段名、_version、round/step 结构、coords 平台格式）；确认「同动作类型编辑」「未暴露字段保留」行为与修复前一致

# Task Dependencies

- Task 2 依赖 Task 1（以 Windows 改造为基准对齐）
- Task 4 依赖 Task 3（移动端双端同构，先 iOS 后安卓）
- Task 1 与 Task 3 互相独立，可并行委派子代理
- Task 5 依赖 Task 1–4 全部完成