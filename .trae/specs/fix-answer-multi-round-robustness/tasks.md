# Tasks

- [x] Task 1: Windows 端 answer/answer_terminate 多轮修复与回看
  - [x] SubTask 1.1: `save_current_step` 的 answer/answer_terminate/terminate 分支增加「当前步必须是本轮最后一步」拦截（先判定位，再改状态；拦截时回滚 confirmed 并刷新侧栏）
  - [x] SubTask 1.2: answer 分支落轮前按 terminate 同口径用 `validate_step_at` 校验本轮全部步骤，缺项弹 `ValidationFailDialog` 并保持现场
  - [x] SubTask 1.3: 新增 `cancel_next_round_instruction()`：清空 `task_instruction` + `reset_for_new_task` + 状态提示；供续采取消使用
  - [x] SubTask 1.4: `finish_all_annotation` 成功写盘后保持 `_round_transition_pending` 门闩至新任务开始；`reset_for_new_task` 复位该门闩；`start_capture`/`confirm_button_clicked` 等入口在 `_final_data_saved` 时早退
  - [x] SubTask 1.5: `main.py` `ask_next_instruction_after_resume` 取消分支改调 `cancel_next_round_instruction()`
  - [x] SubTask 1.6: 新增只读 `RoundPreviewDialog`（轮次下拉 + 该轮步骤缩略图列表 + 大图预览，复用 `_group_coords_by_round`/`_rect_info_from_coord_entry`/`build_marked_preview`，分批懒加载 + 独立 LRU），工具栏新增「查看已完成轮次」按钮，`refresh_dashboard` 按 `len(rounds)` 启停
  - [x] SubTask 1.7: 调整 `tests/helpers.py`：answer 步骤填合法 `intent`；新增 `tests/test_answer_round_flow.py` 覆盖中间步拦截、中间轮缺项拦截、续采取消清指令、交付后禁止采集、回看器轮次/步骤/预览与只读性

- [x] Task 2: 安卓端 answer/answer_terminate 多轮修复与回看
  - [x] SubTask 2.1: `confirm_step` 在 answer / answer_terminate / terminate 分支增加「当前步之后不得还有步骤」拦截（含 live 空位放行）
  - [x] SubTask 2.2: `_finish_task` 增加 `_task_completed` 重入保护；写盘成功后保持 `_round_transition_pending` 门闩，`_start_new_task`/`_start_new_round`/取消重置路径复位
  - [x] SubTask 2.3: 新增只读 `RoundPreviewDialog`（轮次下拉 + 缩略图列表 + 大图预览，使用 `rounds[r]["coords"]` 的 vertices 画框，分批懒加载 + 独立 LRU），工具栏入口与启停逻辑对齐 Windows
  - [x] SubTask 2.4: 新增 `安卓端/tests/test_answer_round_flow.py`：中间步 answer/terminate 被拦截且数据不变；交付后 `take_screenshot`/`confirm_step` 不产生新步与孤儿截图；回看器轮次/步骤/预览与只读性；正常多轮不受影响

- [x] Task 3: iOS 端 answer/answer_terminate 多轮修复、缩略图对齐与回看
  - [x] SubTask 3.1: `confirm_step` 增加「当前步必须是本轮最后一步」拦截（answer / answer_terminate / terminate）
  - [x] SubTask 3.2: `_finish_task` 增加已完成重入保护；`_save_all_rounds_to_file` 成功后保持门闩；`_start_new_task` 复位 `_final_data_saved` 与门闩
  - [x] SubTask 3.3: `main.py` `ask_next_instruction_after_resume` 取消分支改调编辑器 `_reset_workspace_after_cancel()`（清空旧指令）
  - [x] SubTask 3.4: 侧栏缩略图缓存键改为 `(文件名, 框顶点签名)`；`_load_thumb_batch` 执行时校验队列项与当前 `steps_data` 的文件名/vertices 一致，丢弃陈旧项
  - [x] SubTask 3.5: 新增只读 `RoundPreviewDialog`（轮次下拉 + 缩略图列表 + 大图预览，使用该轮 coords 的 vertices 画框，分批懒加载 + 独立 LRU），工具栏入口与启停逻辑对齐 Windows
  - [x] SubTask 3.6: 新增 `ios端/tests/test_answer_round_flow.py` 覆盖上述流程、回看器与缩略图缓存键/陈旧队列用例

- [x] Task 4: macOS 端 answer/answer_terminate 多轮修复与回看
  - [x] SubTask 4.1: `save_current_step` 增加「最后一步」拦截；answer 分支增加全轮 `validate_step_at` 校验（缺项弹 `ValidationFailDialog` 并保持现场）
  - [x] SubTask 4.2: `save_current_step` 增加 `_edit_mode` 早退（只落当前步并合并受保护字段，返回）
  - [x] SubTask 4.3: `save_current_round(prompt_instruction=True) -> bool` 增加缺指令守卫 + `_prompt_missing_instruction`；answer/terminate 分支、`finish_all_annotation` 尊重返回值（失败中止、不写盘）
  - [x] SubTask 4.4: `start_new_round(from_answer=True)` 取消分支改为清空 `task_instruction` + `reset_for_new_task`；`main.py` 续采取消同口径
  - [x] SubTask 4.5: `save_current_round` 收集 coords 时注入 `round` 下标（`len(rounds)-1`）
  - [x] SubTask 4.6: `finish_all_annotation` 成功写盘后保持门闩；`reset_for_new_task` 复位；采集/确认入口在 `_final_data_saved` 时早退
  - [x] SubTask 4.7: 新增只读 `RoundPreviewDialog`（轮次下拉 + 缩略图列表 + 大图预览，复用 `_group_coords_by_round`/`_rect_info_from_coord_entry`/`build_marked_preview`，分批懒加载 + 独立 LRU），工具栏入口与启停逻辑对齐 Windows
  - [x] SubTask 4.8: 调整 `macos端/tests/helpers.py`（answer 填 intent）；新增 `macos端/tests/test_answer_round_flow.py` 覆盖中间步拦截、全轮校验、取消新轮重置、缺指令拒绝、编辑模式不切轮、coords round、交付后禁止采集、回看器

- [x] Task 5: 四端全量回归与收尾
  - [x] SubTask 5.1: 分别运行 `python -m pytest tests -q`（根目录、安卓端、ios端、macos端），全部通过且既有用例不回归（实测 108 / 144 / 148 / 88）
  - [x] SubTask 5.2: 清理本次调查产生的临时文件，确认未改动无关生产逻辑

# Task Dependencies

- Task 1 / Task 2 / Task 3 / Task 4 相互独立（各改各端文件），可并行
- Task 5 依赖 Task 1~4 全部完成