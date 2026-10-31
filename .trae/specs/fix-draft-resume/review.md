# Review: 修复断点续采（草稿恢复）失败

## Review History
- **Cycle 1 (2026-10-27)**: 首次独立审查 — Advisor 提出优化建议
- **Cycle 2 (2026-10-27)**: 实现优化 + 最终审查 — ✅ **pass**

## Checkpoints

### Checkpoint 1: closeEvent 不再无条件调用 _save_all_rounds_to_file
- [x] 原来的 `closeEvent` 在 rounds 非空时调用 `_save_all_rounds_to_file()`，该方法会删除草稿。
- [x] 修复后改为调用 `_write_draft_now()`（只写草稿，不写最终 JSON，不删除草稿）。
- [x] 新增 `_task_completed` 标志位（构造函数初始化为 False）。
- [x] closeEvent 中通过 `getattr(self, '_task_completed', False)` 检查，正常完成跳过草稿保存。

### Checkpoint 2: 草稿删除只在正常完成路径触发
- [x] `_save_all_rounds_to_file()` 改为返回 `bool`：`True` 表示最终 JSON 写入成功（草稿已删除），`False` 表示无轮次或写入失败。
- [x] `closeEvent` 不再调用 `_save_all_rounds_to_file()`。
- [x] `_finish_task` 仅在 `_save_all_rounds_to_file()` 返回 `True` 时才设置 `_task_completed = True`。
- [x] 最终 JSON 写入失败时，`_task_completed` 保持 False，草稿文件仍存在，用户可续采。

### Checkpoint 3: load_draft_from_dir 返回结构化结果
- [x] 新增三个类常量：`DRAFT_ERR_NONE = None`、`DRAFT_ERR_NOT_FOUND = "not_found"`、`DRAFT_ERR_CORRUPT = "corrupt"`。
- [x] 方法返回 `(draft_dict, error_type)` 元组，兼容错误分支。
- [x] JSON 解析异常单独捕获并返回 `DRAFT_ERR_CORRUPT`，打印详细错误信息。
- [x] **5 个单元测试全部通过**（Python exit code 0）。

### Checkpoint 4: resume_annotation 差异化提示
- [x] 解析 `(draft, err_type)` 元组。
- [x] 5 种场景差异化提示：
  - 有效草稿 → 正常恢复（无额外提示）
  - 草稿损坏 → "草稿文件已损坏，无法恢复"
  - 有最终 JSON 无草稿 → "该任务已正常完成，无需续采"（information 级别）
  - 有截图无任何 JSON → "该目录未包含有效的采集数据..."
  - 完全空目录 → "该目录不包含任何采集数据"
- [x] 所有分支只读磁盘，不修改任何文件。

### Checkpoint 5: 新增辅助方法
- [x] `is_task_completed(gui_dir_path)`：正则提取 gui 编号，检查 `gui_xxxxxx.json` 存在性。
- [x] `has_screenshots(gui_dir_path)`：glob 检查 `.png` 文件存在性。

### Checkpoint 6: 正常完成后 closeEvent 副作用已修复
- [x] 正常完成后 `self.close()` 触发 `closeEvent`，通过 `_task_completed` 标志跳过草稿保存。
- [x] 用户选择"继续新任务"（reply == Yes）时，标志重置为 False。
- [x] closeEvent 双写注释已添加：`_save_current_round_to_list` 内部调 `_write_draft_now` 后外层再调一次是安全网。

### Checkpoint 7: 向后兼容性
- [x] `load_draft(gui_number)` 旧方法签名和返回值不变（无调用方）。
- [x] `load_draft_from_dir` 返回类型变更，唯一调用方 `main.py:468` 已同步修改。
- [x] 最终 JSON 和 coords JSON 的格式完全不变。
- [x] `find_draft_dirs` 方法不受影响。

### Checkpoint 8: 代码质量验证
- [x] Python 语法检查：3 个文件全部通过（`py_compile`）。
- [x] Dry-run 导入测试：`import data_manager` ✅。
- [x] DRAFT_ERR 常量可访问性验证 ✅。
- [x] 搜索所有调用点：唯一调用方已适配，无遗漏。

### Checkpoint 9: 已知限制（非阻塞）
- 无 Android 设备，未执行实际 GUI 端到端冒烟测试。所有验证基于语法检查、单元测试和代码逻辑审查。
- iOS 和 macOS 端的同名文件可能存在相同的 closeEvent bug，不在本次 Android 端修复范围内。
- `_start_new_task` 不调 `schedule_draft_save()`，新任务首次草稿写入延迟到用户确认步骤时——这是原有设计，非本次修复引入。

## 修复的 Bug 清单
| # | 问题 | 影响 | 修复 |
|---|------|------|------|
| 1 | closeEvent 无条件调 `_save_all_rounds_to_file` → 删草稿 | 用户中途关闭后无法续采 | closeEvent 改为只调 `_write_draft_now` |
| 2 | 错误信息笼统，无法区分场景 | 用户不知道为什么续采失败 | 返回结构化错误类型 + 5 种差异化提示 |
| 3 | 正常完成后 closeEvent 重新创建草稿 | 草稿删除后又被写回来 | `_task_completed` 标志跳过关闭时的草稿保存 |
| 4 | `_task_completed` 无条件设置 | 最终 JSON 写入失败时 closeEvent 仍跳过草稿写入 | `_save_all_rounds_to_file` 返回 bool，仅成功时设标志 |

## Review Result
**pass** — 所有 checkpoint 通过，修复覆盖全部根因，代码质量验证充分。
