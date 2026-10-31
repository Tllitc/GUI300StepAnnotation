# Tasks

- [x] Task 1: 三端 DataManager 增加「按目录读取已完成数据」接口
  - [x] SubTask 1.1: Windows `data_manager.py` 新增 `load_json_from_dir(gui_dir)` 与 `load_coords_from_dir(gui_dir)`，返回 `(data, error)` 风格结果；`load_coords_from_dir` 同时接受数组与 `{"coords":[...]}` 对象
  - [x] SubTask 1.2: `ios端/data_manager.py` 新增同名接口，coords 为数组（条目含 `round`/`_version` 时原样返回）
  - [x] SubTask 1.3: `安卓端/data_manager.py` 新增同名接口，coords 为 `{"version":"3.0","coords":[...]}` 对象
  - [x] SubTask 1.4: 三端接口均校验目录名 `gui_\d{6}`、最终 JSON 存在且可解析，缺失时返回可读错误信息

- [x] Task 2: Windows 编辑器支持编辑已完成任务
  - [x] SubTask 2.1: `annotation_editor.py` 新增编辑模式标志与 `load_from_completed_json(...)`：从最终 JSON 重建 `rounds`（instruction + trajectory）、选中轮的步骤、截图绝对路径、`rect_info`/`selection_type`，并保留顶层 `platform/system/screen_size/task_type`
  - [x] SubTask 2.2: 实现 coords 轮次归属：有 `round` 按轮分组；无 `round` 时按 `step` 回退切分连续段，再按轮次 trajectory 的 `step/action/center` 对齐，未对齐条目保留在最后一轮
  - [x] SubTask 2.3: 编辑模式下「确认」只写回当前步，不触发 answer 轮次切换、terminate 结束与「是否开始新任务」弹窗
  - [x] SubTask 2.4: 工具栏新增「保存修改」按钮：对当前轮全部步骤复用 `validate_step_at` 校验，缺项弹清单阻止保存；通过后仅替换选中轮次并重写最终 JSON + coords（数组格式），然后返回主菜单
  - [x] SubTask 2.5: 按截图文件名关联原步骤，合并原 action/trajectory 中编辑器未暴露的字段（如 `status`、`element`）
  - [x] SubTask 2.6: 编辑模式全程不写 draft（调度与立即写草稿入口直接返回）；`closeEvent` 在编辑模式下自动写回最终数据（不删 draft），写盘失败保持原文件并记录错误

- [x] Task 3: Windows 主菜单新增「编辑已完成任务」入口
  - [x] SubTask 3.1: `main.py` 新增按钮与处理函数：`QFileDialog` 选择目录 → 校验 `gui_XXXXXX` 与最终 JSON → 构造 `AnnotationEditor` 并调用 `load_from_completed_json`
  - [x] SubTask 3.2: 多轮时弹出轮次选择框（轮次号 + 指令摘要），取消回到主菜单；单轮直接进入
  - [x] SubTask 3.3: 目录未完成/格式非法时提示「该任务尚未完成，请使用『继续未完成任务』」/「请选择 gui_xxxxxx 形式的任务目录」并停留在主菜单

- [x] Task 4: iOS 端编辑器与主菜单支持编辑已完成任务
  - [x] SubTask 4.1: `ios端/annotation_editor.py` 新增编辑模式与 `load_from_completed_json`，从 trajectory 重建 `steps_data`（`screenshot/screenshot_filepath/intent/action_data/vertices`）
  - [x] SubTask 4.2: 编辑模式确认只落当前步；新增「保存修改」按 `_validate_all_steps` 校验当前轮，仅替换选中轮后写回 JSON 与 coords（数组，条目保留/补充 `round`），再返回主菜单
  - [x] SubTask 4.3: 编辑模式不写 draft，`closeEvent` 自动写回最终数据
  - [x] SubTask 4.4: `ios端/main.py` 新增「编辑已完成任务」入口（含多轮选择、非法目录提示），保持 `close_callback` 回主菜单

- [x] Task 5: Android 端编辑器与主菜单支持编辑已完成任务
  - [x] SubTask 5.1: `安卓端/annotation_editor.py` 新增编辑模式与 `load_from_completed_json`，重建 `steps_data` 并恢复 `vertices`
  - [x] SubTask 5.2: 编辑模式 `confirm_step` 不触发 `_finish_task`/新轮次；新增「保存修改」校验当前轮后仅替换选中轮，写回 JSON 与 `{"version":"3.0","coords":[...]}`，再返回主菜单
  - [x] SubTask 5.3: 编辑模式不写 draft，`_task_completed` 逻辑不干扰关闭写回；`closeEvent` 自动写回
  - [x] SubTask 5.4: `安卓端/main.py` 新增「编辑已完成任务」入口（允许未连接设备时进入编辑，多轮选择，非法目录提示）

- [x] Task 6: 新增 Windows 编辑模式回归测试
  - [x] SubTask 6.1: 用 `tests/helpers.py` 生成单轮/多轮已完成数据集，验证加载后步骤数、截图引用、`rect_info` 与 JSON 一致
  - [x] SubTask 6.2: 验证编辑第 r 轮后保存：仅该轮 trajectory 变化，其它轮与顶层字段不变
  - [x] SubTask 6.3: 验证编辑模式不生成 draft、关闭窗口自动写回、缺项校验阻止保存
  - [x] SubTask 6.4: 覆盖旧 coords（无 `round`）的多轮切分与未对齐条目保留

- [x] Task 7: 新增 iOS/Android 编辑模式回归测试
  - [x] SubTask 7.1: iOS：加载重建 `vertices`、保存后 coords 仍为数组且条目带 `round`、仅替换选中轮
  - [x] SubTask 7.2: Android：加载重建、保存后 coords 仍为 `{"version":"3.0","coords":[...]}` 对象、仅替换选中轮
  - [x] SubTask 7.3: 两端验证编辑模式不写 draft、关闭窗口自动写回

- [x] Task 8: 运行三套测试并修复回归
  - [x] SubTask 8.1: `QT_QPA_PLATFORM=offscreen python -m pytest tests -q`（根目录）
  - [x] SubTask 8.2: 同上运行 `ios端/tests`
  - [x] SubTask 8.3: 同上运行 `安卓端/tests`

- [x] Task 9: 修复「编辑模式下关闭编辑窗口后主窗口仍隐藏」的问题
  - [x] SubTask 9.1: Windows `annotation_editor.py` `closeEvent` 编辑模式分支：写回后若存在 `init_window`，调用 `show()/raise_()/activateWindow()` 恢复主窗口（不得在 `closeEvent` 内递归调用 `self.close()`）
  - [x] SubTask 9.2: 安卓端 `annotation_editor.py` `closeEvent` 编辑模式分支：写回后若存在 `_init_window`，恢复其显示
  - [x] SubTask 9.3: 复跑根目录与安卓端 pytest，确认无回归

- [x] Task 10: 补齐 iOS/Android 加载已完成数据时的「截图文件缺失」警告
  - [x] SubTask 10.1: `ios端/annotation_editor.py` `load_from_completed_json` 加载选中轮步骤时检查 `gui_dir/截图文件名` 是否存在，收集缺失清单后用 `QMessageBox.warning` 提示（允许继续编辑）
  - [x] SubTask 10.2: `安卓端/annotation_editor.py` `load_from_completed_json` 同上（窗口显示前提示）
  - [x] SubTask 10.3: 复跑 iOS 与安卓端 pytest，确认无回归

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 2
- Task 4 依赖 Task 1
- Task 5 依赖 Task 1
- Task 6 依赖 Task 2、Task 3
- Task 7 依赖 Task 4、Task 5
- Task 8 依赖 Task 6、Task 7
- Task 9 依赖 Task 2、Task 5
- Task 10 依赖 Task 4、Task 5
- Task 4 与 Task 5 可并行；Task 6 与 Task 7 可并行
