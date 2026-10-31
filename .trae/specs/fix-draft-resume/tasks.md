# Tasks

## Task 1: closeEvent 中拆分"保存状态"与"删除草稿"
**Priority**: high
**Status**: completed

### Completion Evidence
- 修改 `closeEvent`：移除了对 `_save_all_rounds_to_file()` 的调用，改为只调用 `_write_draft_now()` 写草稿
- 新增 `_task_completed` 标志位（构造函数初始化为 False）
- `_finish_task` 正常完成后设置 `_task_completed = True`，closeEvent 据此跳过草稿保存
- **额外修复**：`_finish_task` 最后 `self.close()` 会触发 closeEvent，通过标志位避免完成后草稿被重新创建
- **额外加固**：`_save_all_rounds_to_file` 改为返回 True/False，`_finish_task` 仅在最终 JSON 写入成功时才设置 `_task_completed = True`；写入失败时保持草稿不变，用户仍可续采

### Test Requirements

**TR1.1 (rule)**: 中途关闭编辑窗口后草稿保留 — ✅ 逻辑确认正确
- closeEvent 只调用 `_write_draft_now()`，不调 `_save_all_rounds_to_file()`，草稿保留

**TR1.2 (rule)**: 正常完成后草稿被删除 — ✅ 逻辑确认正确
- `_finish_task` 调 `_save_all_rounds_to_file()` 返回 True，草稿删除；closeEvent 因标志位跳过草稿保存

**TR1.3 (rule)**: 校验未通过不删除草稿 — ✅ 逻辑确认正确
- 校验未通过时 return，不触发任何写文件或删草稿的操作

---

## Task 2: load_draft_from_dir 返回结构化结果
**Priority**: high
**Status**: completed

### Completion Evidence
- 在 `DataManager` 类中新增常量：`DRAFT_ERR_NONE = None`、`DRAFT_ERR_NOT_FOUND = "not_found"`、`DRAFT_ERR_CORRUPT = "corrupt"`
- `load_draft_from_dir` 返回 `(draft_dict, error_type)` 元组
- 新增 `is_task_completed(gui_dir_path)` 静态方法
- 新增 `has_screenshots(gui_dir_path)` 静态方法
- **5 个单元测试全部通过**（Python 退出码 0）

### Test Requirements

**TR2.1 (rule)**: 有效草稿返回 (dict, None) — ✅ 单元测试通过
**TR2.2 (rule)**: 无草稿返回 (None, "not_found") — ✅ 单元测试通过
**TR2.3 (rule)**: 损坏草稿返回 (None, "corrupt") — ✅ 单元测试通过

---

## Task 3: resume_annotation 差异化提示
**Priority**: medium
**Status**: completed

### Completion Evidence
- `main.py:resume_annotation` 解析 `(draft, err_type)` 元组
- 5 种场景差异化提示：
  - 有效草稿 → 正常恢复（无额外提示）
  - 草稿损坏 → "草稿文件已损坏，无法恢复"
  - 有最终 JSON 无草稿 → "该任务已正常完成，无需续采"（QMessageBox.information）
  - 有截图无任何 JSON → "该目录未包含有效的采集数据..."
  - 完全空目录 → "该目录不包含任何采集数据"
- 所有分支只读磁盘

### Test Requirements

**TR3.1 (rule)**: 有最终 JSON 无草稿 → 已完成提示 — ✅ 逻辑确认正确
**TR3.2 (rule)**: 草稿损坏 → 损坏提示 — ✅ 逻辑确认正确
**TR3.3 (rule)**: 目录只有截图 → 无数据提示 — ✅ 逻辑确认正确

---

## Task 4: 最终语法检查
**Priority**: medium
**Status**: completed

### Completion Evidence
- `data_manager.py` → `py_compile` 通过 ✅
- `main.py` → `py_compile` 通过 ✅
- `annotation_editor.py` → `py_compile` 通过 ✅
- 搜索所有 `load_draft_from_dir` 调用点，唯一调用方 `main.py:468` 已适配
- 搜索所有 `.load_draft(` 调用点，旧方法无调用方，无副作用

### Test Requirements

**TR4.1 (rubric)**: 断点续采恢复完整性
- **Score**: 2
- **Rationale**: 所有语法检查通过、单元测试通过、代码路径审查确认 closeEvent → _write_draft_now 会正确保存 rounds + 当前轮步骤，恢复逻辑无变化
- **Evidence**: 见 review.md Checkpoint 1-2

**TR4.2 (rubric)**: 提示文案准确性
- **Score**: 2
- **Rationale**: 5 种场景均有明确提示，区分度充足，信息友好
- **Evidence**: 见 review.md Checkpoint 3-5
