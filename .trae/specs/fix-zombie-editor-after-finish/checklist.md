# Checklist

- [x] AnnotationEditor 提供统一清理方法 `cleanup_resources()`，能断开 `screenshot_triggered` 到本实例的连接且对"未连接"情况不报错（捕获 TypeError/RuntimeError，幂等）
- [x] 返回主菜单（`_return_to_init_menu`）后旧标注窗口经 `close()` + `deleteLater()` 销毁，而非仅隐藏/关闭残留
- [x] 任何关闭路径（`closeEvent`，含返回菜单与直接关窗）都会断开快捷键连接并停止 `draft_timer`、`validation_timer`
- [x] `start_capture` / `start_insert_capture` / `recapture_current_step` 及延迟弹窗对正在关闭或重入中的实例有守卫，幽灵实例不会创建截图遮罩
- [x] 完成任务选"否"返回菜单后再新建任务，按 Ctrl+Q 只有当前实例响应（离屏信号测试：旧实例 cleanup 后 receivers 2→1，emit 仅触发新实例）→ 屏幕上只出现一个截图遮罩
- [x] 已清理的旧实例 `_is_closing=True` 后 `start_capture`/`show_capture_window` 直接 return，旧标注窗口不会重新 show（无两个标注窗口）
- [x] 每次返回菜单/新建前都 disconnect 旧实例，连续多个任务无累积接收者（离屏测试 receivers 随 cleanup 单调下降至 0，cleanup 幂等）
- [x] 新任务的截图与步骤由当前 `AnnotationEditor` 持有的 `data_manager` / `gui_number` 写入；幽灵实例不再响应快捷键，不会触发 `get_next_gui_number()` 串写旧/新 gui 目录
- [x] 已通过 `finish_all_annotation` 保存并删草稿的返回菜单流程，`_final_data_saved=True`，`closeEvent` 不二次写同一 gui 目录的 JSON/coords
- [x] 任务中途直接关闭窗口（`_final_data_saved=False` 且有 steps/rounds）仍调用 `_save_all_data_before_close()` 应急保存；草稿不删除，"继续未完成任务"恢复入口 `resume_annotation` 保持不变
- [x] InitTaskWindow 在新建/续采前经 `_discard_previous_editor()` 清理上一编辑器引用，`annotation_window` 始终唯一指向当前实例
- [x] 修改后的 main.py / annotation_editor.py 通过 `python -m py_compile`，无语法错误（COMPILE_OK）
- [x] 最终 JSON / coords / draft / 截图文件的命名与格式保持不变（未改动 data_manager.py、screenshot_capture.py、hotkey_manager.py 的任何落盘/命名逻辑）

> 备注：以上项由代码审查、`py_compile` 与离屏（offscreen）信号生命周期测试自动验证。tasks.md 中 SubTask 5.2 / 5.3 / 5.4 为真机 GUI 操作场景（单遮罩肉眼确认、连续多任务、中途关窗续采），自动化环境无法操作桌面，请在 Windows 真机按这三条场景各实测一遍确认。
