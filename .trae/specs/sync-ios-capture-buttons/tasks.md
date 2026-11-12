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

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1、Task 2
- Task 4 depends on Task 3