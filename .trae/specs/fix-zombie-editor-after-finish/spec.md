# 修复任务结束返回主菜单后幽灵标注窗口（截图卡死/双窗口/数据混乱）Spec

## Why

Windows 端用户在一个任务结束后，于「是否开始一个新的标注任务？」对话框选择 **否**（返回任务初始化菜单），再从主窗口开始下一个任务并按 Ctrl+Q 截图时，会出现三个连锁故障：

1. **截图卡住**：截图遮罩窗口（`ScreenshotCaptureWindow`）无响应或界面冻结。
2. **出现两个标注窗口**：已"关闭"的上一个标注窗口重新出现，与新标注窗口并存。
3. **编辑数据混乱**：截图与步骤被写入错误的 gui 目录 / 旧任务窗口。

根因是**标注窗口（`AnnotationEditor`）生命周期管理缺失**：

- 全局快捷键管理器 `GlobalHotkeyManager.screenshot_triggered` 是一个应用级、常驻的 `pyqtSignal`。`AnnotationEditor.setup_shortcuts()` 在初始化时把该信号连接到自己的 `start_capture`，但**全程从不 `disconnect`**。
- `_return_to_init_menu()` 只调用 `self.close()`；Python 中旧窗口仍被信号连接强引用，Qt 也不会销毁它。于是每完成一个任务返回菜单，就多一个"幽灵" `AnnotationEditor` 实例存活。
- 当用户从主窗口 `start_annotation()` 新建第二个 `AnnotationEditor` 时，Ctrl+Q 的同一个信号**同时分发给所有幽灵窗口和新窗口**：每个实例都执行 `_hide_for_capture()`（把自己隐藏、透明度置 0）并在 350ms 后各自 `new ScreenshotCaptureWindow()`。于是屏幕上同时叠加多个全屏置顶的截图遮罩（键盘焦点被抢占、互相干扰）——即"截图卡住"。
- 幽灵实例的截图回调 `on_capture_completed` 会写自己的截图：若其 `gui_number is None` 则调用 `get_next_gui_number()` 取编号；取消/失败路径以及 `restore_window()` 会把这个本应已销毁的旧窗口 `show()`/`raise_()` 回来——即"两个标注窗口"。
- 多个实例共享各自的 `data_manager`/`gui_number`/`steps`，截图被写进不同 gui 目录、步骤状态互相穿插——即"数据混乱"。

附带问题：

- `closeEvent` 调用 `_save_all_data_before_close()`，而 `finish_all_annotation(close_after_save=False)` 在返回菜单前已经保存并删除草稿；随后 `self.close()` 触发 `closeEvent` 又保存一遍（冗余，且依赖 `self.rounds` 此时是否已被清空，存在重复写文件风险）。
- 防抖定时器 `draft_timer`、校验定时器 `validation_timer` 在窗口关闭时未停止，幽灵实例上仍可能触发 `_write_draft_now()`。

## What Changes

- **窗口退出即解绑快捷键**：`AnnotationEditor` 在真正结束生命周期（返回主菜单 / 关闭窗口）时，断开 `hotkey_listener.screenshot_triggered` 到本实例的连接，并停止 `draft_timer` / `validation_timer`。
- **返回主菜单时彻底销毁旧标注窗口**：`_return_to_init_menu()` 在显示初始化窗口后，对旧标注窗口调用 `deleteLater()`（而非仅 `close()`），确保幽灵实例被回收；主窗口不再长期持有失效引用。
- **主窗口统一管理当前标注窗口引用**：`InitTaskWindow` 在每次打开新编辑器前，确保上一个编辑器（若存在）已断开信号并被销毁；`self.annotation_window` 只指向当前唯一活动实例。
- **防止重入 / 幽灵响应**：`start_capture`（及 `_hide_for_capture`）增加窗口可见性/存活守卫，已关闭或不可见的实例不再响应快捷键、不再创建截图遮罩。
- **避免 closeEvent 重复落盘**：区分"正常完成返回菜单（已保存）"与"中途关闭（需应急保存）"，已由 `finish_all_annotation` 成功保存并删除草稿的返回菜单路径，不再触发 `closeEvent` 的二次保存。

## Impact

- Affected specs: 标注窗口生命周期管理、全局快捷键分发、任务结束→返回菜单→新建任务流程、草稿/最终数据落盘时机
- Affected code:
  - `annotation_editor.py` — `setup_shortcuts`、`_return_to_init_menu`、`closeEvent`、`start_capture`/`_hide_for_capture`、新增资源清理逻辑（断开信号、停定时器、销毁截图窗口）
  - `main.py` — `InitTaskWindow.start_annotation` / `resume_annotation` 打开新编辑器前清理上一实例；维护唯一 `annotation_window` 引用
  - `hotkey_manager.py` — 仅在需要时核对信号连接方式（预期不改其 API）
- 数据文件：不新增、不修改任何现有文件格式（JSON / coords / draft / 截图命名均不变）
- 范围：仅 Windows 端根目录代码（`main.py`、`annotation_editor.py`、`hotkey_manager.py`）；iOS / macOS / 安卓端同名文件不在本次范围内

## ADDED Requirements

### Requirement: 标注窗口退出时释放全局快捷键与定时器

系统 SHALL 在 `AnnotationEditor` 结束生命周期时，断开本实例与 `GlobalHotkeyManager.screenshot_triggered` 的所有信号连接，并停止 `draft_timer` 与 `validation_timer`，使其不再响应任何全局快捷键、不再触发任何延迟回调。

#### Scenario: 任务结束选择"否"返回主菜单
- **WHEN** 用户在"是否开始一个新的标注任务？"对话框选择"否"，系统保存最终数据并返回任务初始化菜单
- **THEN** 旧标注窗口被销毁（`deleteLater`），它不再连接 `screenshot_triggered`，其 `draft_timer`/`validation_timer` 已停止

#### Scenario: 用户直接关闭标注窗口
- **WHEN** 用户通过窗口关闭按钮关闭标注窗口
- **THEN** 该窗口同样断开全局快捷键连接并停止定时器，不会在后续 Ctrl+Q 时被唤醒或创建截图窗口

### Requirement: 任意时刻只有一个活动标注窗口响应截图快捷键

系统 SHALL 保证全局截图快捷键 Ctrl+Q 在任一时刻只被当前唯一活动的 `AnnotationEditor` 实例接收处理；已关闭、已隐藏待销毁或不可见的实例 SHALL NOT 创建 `ScreenshotCaptureWindow`。

#### Scenario: 返回菜单后开始第二个任务并截图
- **WHEN** 用户完成任务 1 返回菜单，开始任务 2，按 Ctrl+Q
- **THEN** 屏幕上只出现一个截图遮罩窗口，且属于任务 2 的标注窗口；任务 1 的旧窗口不出现、不创建遮罩、不写任何文件

#### Scenario: 连续完成多个任务
- **WHEN** 用户反复"完成任务→返回菜单→新建任务"多次
- **THEN** 每按一次 Ctrl+Q 始终只弹出一个截图遮罩，不存在累积的幽灵窗口

### Requirement: 新建/续采前清理上一标注窗口

系统 SHALL 在 `InitTaskWindow` 打开新的 `AnnotationEditor`（新建或断点续采）前，确保上一个标注窗口引用（如存在）已断开快捷键并被销毁，且 `InitTaskWindow.annotation_window` 始终只指向当前活动实例。

#### Scenario: 从主菜单连续新建任务
- **WHEN** 用户返回主菜单后再次点击"开始标注"
- **THEN** 不存在上一个编辑器实例残留；新编辑器是唯一持有 `screenshot_triggered` 连接的实例

### Requirement: 返回主菜单路径不重复落盘

系统 SHALL 在已通过 `finish_all_annotation` 成功写出最终 JSON（并删除草稿）的返回菜单流程中，避免 `closeEvent` 对同一批数据二次保存。

#### Scenario: 正常完成后返回菜单
- **WHEN** 最终 JSON 已成功保存、草稿已删除，随后标注窗口关闭返回菜单
- **THEN** 不再触发一次针对同一 `gui_number` 的最终 JSON/coords 写入，目录内容与正常完成时一致

#### Scenario: 中途异常关闭
- **WHEN** 用户在任务未正常完成时直接关闭窗口
- **THEN** 仍按既有应急逻辑保存数据/草稿（保留断点续采能力），不被本次修改破坏

## Constraints

- 不改变最终 JSON、coords JSON、draft JSON、截图文件的命名与格式
- 不修改全局快捷键的注册/注销时机（`register_all`/`unregister_all` 仍在应用启动/退出时进行）
- iOS、macOS、安卓端代码不在本次修改范围
