# Tasks

- [x] Task 1: 实现「给下一步截图」与「重新截图」两个入口逻辑（`ios端/annotation_editor.py`）
  - [x] SubTask 1.1: 在 `__init__` 增加 `_capture_append_new_step = False` 状态；在 `_do_screenshot` 收尾处与 `_capture_insert_after` 一同复位
  - [x] SubTask 1.2: `take_screenshot` 增加保护：`_capture_append_new_step` 为真时跳过「已有截图则置 `_replacing_screenshot`」的替换判定；其余默认行为（含 `_screenshot_missing` 判据）保持不变
  - [x] SubTask 1.3: 新增 `start_capture()`：门闩（`_round_transition_pending`/`gui_dir`/`_screenshot_in_progress`/`_swipe_measuring`/`_scroll_measuring`）→ 清除插入锚点 `_capture_insert_after` → 若 `current_step < len(steps_data)` 置追加标记 → 调 `take_screenshot()`；未确认空位直接复用 auto 语义（已有待确认图则原地覆盖）
  - [x] SubTask 1.4: 新增 `recapture_current_step()`：同一组门闩（swipe 测量拦截、scroll 测量放行）→ 无可用截图时退化为首次/当前空位截图 → 否则调 `take_screenshot()` 走替换分支
  - [x] SubTask 1.5: `_do_screenshot` 普通追加分支支持「从已落表步追加」：先 `_save_current_to_steps()` 保存旧步现场，再把 `current_step` 移到 `len(steps_data)`，清空表单/坐标/拉框但保留新截图与画布，更新步骤标签、按钮态、侧栏看板与草稿，并给出「已为下一步截图」提示

- [x] Task 2: 工具栏按钮与文案改造（同文件）
  - [x] SubTask 2.1: 移除「截图 (Ctrl+Q)」，新增 `btn_recapture`（`重新截图`，`#FF9800`）与 `btn_capture_next`（`给下一步截图 (Ctrl+Q)`，`#2196F3`）；按 Windows 顺序排列：插入截图 → 重新截图 → 在原图上重新拉框 → 给下一步截图
  - [x] SubTask 2.2: `keyPressEvent` 中 `Ctrl+Q` 改调 `self.start_capture()`，`Ctrl+S`/方向键/`Esc` 保持不变
  - [x] SubTask 2.3: 更新 `ScreenshotCanvas.paintEvent` 占位文案与初始 `status_label` 文案为 `[给下一步截图(Ctrl+Q)]`
  - [x] SubTask 2.4: 检查所有提示语（插入锚点提示、scroll 测量提示等）与新入口口径一致，不残留指向已删除按钮的文案

- [x] Task 3: 新增回归测试 `ios端/tests/test_capture_entries.py`
  - [x] SubTask 3.1: 空列表点「给下一步截图」→ 生成第一张截图，`steps_data` 仍为空，`current_step == 0`
  - [x] SubTask 3.2: 确认首步后点「给下一步截图」→ 新序号文件落盘，首步 `screenshot` 不变，`steps_data` 长度不变，`current_step == len(steps_data)`
  - [x] SubTask 3.3: 回历史步点「给下一步截图」→ 历史步截图不变，游标移到末尾待确认位，磁盘新增一文件且无孤儿
  - [x] SubTask 3.4: 历史步点「重新截图」→ 同名原地覆盖、序号/引用不变、内容更新、坐标与拉框清空、邻步不受影响
  - [x] SubTask 3.5: 未确认空位点「重新截图」「给下一步截图」→ 均原地覆盖待确认文件，不新增文件
  - [x] SubTask 3.6: 无截图时点「重新截图」→ 退化为首次截取，不弹警告
  - [x] SubTask 3.7: swipe 测量中两入口均被拦截；scroll 测量中「重新截图」产出 extra 截图、「给下一步截图」被拦截
  - [x] SubTask 3.8: 快捷键 `Ctrl+Q` 走 `start_capture`、`Ctrl+S` 仍走 `go_next`；断言工具栏存在两个新按钮且不存在通用「截图」按钮

- [x] Task 4: 回归验证：在 `ios端` 目录运行 `python -m pytest tests -q`，全部通过；若既有用例因入口拆分回归，按产品语义修正实现而非改测试预期

- [x] Task 5: 修复编辑已完成任务模式下「给下一步截图」的确认死胡同（`ios端/annotation_editor.py`）
  - [x] SubTask 5.1: `confirm_step` 编辑分支（2451-2477）：当 `current_step == len(steps_data)` 且有待确认截图（`_current_screenshot_filename` 非 None）时，用 `_collect_step_data()` 收集新步并 append 到 `steps_data`，游标留在新步下标，刷新步骤标签/导航按钮/侧栏看板与缺项槽位，提示「已新增第 N 步（编辑模式）」；无截图的越界空位保持早退，不再误报"已更新"
  - [x] SubTask 5.2: 验证 `save_edited_round` 按 `steps_data` 重建 trajectory/coords（约 3530-3614），新增步可完整写回 JSON 与 coords，不被原 trajectory 长度截断；新步无原条目时不做合并（测试断言通过）
- [x] Task 6: 修复编辑模式下插入截图的锚点步落表（同文件）
  - [x] SubTask 6.1: `_do_screenshot` 插入分支（1776-1782）：`_edit_mode` 为真时改调 `_save_current_to_steps_for_edit()`，保住缺图锚点步的文本修改与 `coord_issue/orig_coord_entry` 标记；普通模式行为不变
- [x] Task 7: 补充编辑模式与草稿续采回归测试（`ios端/tests/test_capture_entries_modes.py`，4 用例）
  - [x] SubTask 7.1: 编辑模式：「重新截图」原地覆盖且文本保留、不写草稿；「给下一步截图」→「确认」提交新步 →「保存修改」写回新步（JSON trajectory 与 coords 均含新步、受保护字段不被空值覆盖、无孤儿截图）；插入截图在锚点步缺图时保留文本修改与坐标标记
  - [x] SubTask 7.2: 草稿续采：恢复后「给下一步截图」追加、「重新截图」覆盖，行为与新采标一致
- [x] Task 8: 回归验证：在 `ios端` 目录运行 `python -m pytest tests -q`，157 passed / 0 failed（基线 153 + 新增 4）；新增 4 用例单独复跑亦全绿

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1、Task 2
- Task 4 depends on Task 3
- Task 5、Task 6 相互独立，可并行
- Task 7 depends on Task 5、Task 6
- Task 8 depends on Task 7