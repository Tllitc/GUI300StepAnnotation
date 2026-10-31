# Tasks

- [x] Task 1: 在 AnnotationEditor 增加统一资源清理方法
  - [x] SubTask 1.1: 新增 `cleanup_resources()`：若 `hotkey_listener` 存在则 `disconnect` 断开 `screenshot_triggered` 到本实例 `start_capture` 的连接（安全处理"未连接"异常），并 `stop()` 停止 `draft_timer`、`validation_timer`
  - [x] SubTask 1.2: 若存在活动的 `self.capture_window` / `reference_capture_window`，在清理时关闭并置空，避免遮罩残留
  - [x] SubTask 1.3: 增加实例存活/活动守卫标志 `self._is_closing`（另含 `_capture_in_flight`、`_final_data_saved`），供截图入口与关闭流程判断

- [x] Task 2: 截图入口增加守卫，阻止幽灵/不可见实例响应
  - [x] SubTask 2.1: 在 `start_capture` / `start_insert_capture` / `recapture_current_step` 及延迟弹窗 `show_capture_window` / `show_recapture_window` 开头判断 `_is_closing` / `_capture_in_flight`，重入或关闭中直接 return；`_hide_for_capture` 置位重入守卫
  - [x] SubTask 2.2: 取消/成功截图回调（`on_capture_completed`、`on_recapture_completed`）开头均复位 `_capture_in_flight`，不影响正常再次截图

- [x] Task 3: 修复返回主菜单的销毁逻辑与重复落盘
  - [x] SubTask 3.1: `_return_to_init_menu` 显示并激活初始化窗口、解除主窗口引用后，调用清理并经 `close()` + `deleteLater()` 销毁旧标注窗口（而非仅 `close()`）
  - [x] SubTask 3.2: 用 `_final_data_saved` 区分"已正常完成保存返回菜单"与"中途关闭"：`finish_all_annotation` 成功落盘并删草稿后置 True，`closeEvent` 据此跳过 `_save_all_data_before_close()`；中途关闭仍走应急保存
  - [x] SubTask 3.3: `closeEvent` 中无条件调用 `cleanup_resources`（幂等），保证任何关闭路径都解绑快捷键、停定时器

- [x] Task 4: 主窗口统一管理唯一活动标注窗口
  - [x] SubTask 4.1: `InitTaskWindow.start_annotation` 与 `resume_annotation` 在创建新 `AnnotationEditor` 前调用 `_discard_previous_editor()`，对残留实例执行 `cleanup_resources()` + `close()` + `deleteLater()` 并置 `None`
  - [x] SubTask 4.2: 新建/续采后 `self.annotation_window` 只指向当前实例；`closeEvent` 与 `_return_to_init_menu` 在销毁时同步清空主窗口引用，无其它强引用残留

- [x] Task 5: 验证与回归
  - [x] SubTask 5.1: 静态检查通过（`python -m py_compile main.py annotation_editor.py hotkey_manager.py data_manager.py` → COMPILE_OK）；离屏生命周期测试通过（两个实例 receivers=2，旧实例清理后 receivers=1 且 emit 只触发新实例，全部清理后为 0，cleanup 幂等）
  - [ ] SubTask 5.2: 手动验证（需用户在 Windows 真机操作）：完成任务选"否"返回菜单→新建任务→Ctrl+Q 仅出现一个截图遮罩、无旧窗口复活
  - [ ] SubTask 5.3: 手动验证（需用户真机操作）：连续完成 2~3 个任务后 Ctrl+Q 仍只有一个遮罩；截图/步骤写入正确的新 gui 目录
  - [ ] SubTask 5.4: 回归验证（需用户真机操作）：任务中途直接关窗仍能应急保存/保留草稿，"继续未完成任务"可恢复

# Task Dependencies
- Task 2 依赖 Task 1（守卫标志/清理方法）
- Task 3 依赖 Task 1
- Task 4 依赖 Task 3（销毁语义确定后再统一管理引用）
- Task 5 依赖 Task 2、Task 3、Task 4
