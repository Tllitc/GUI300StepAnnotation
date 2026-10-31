# 重写 scrcpy 重连逻辑：按钮常亮 + 移除连接状态监控

## Summary（摘要）

当前 [annotation_editor.py](file:///c:/Project/TC/300step采标工具/安卓端/annotation_editor.py) 中 scrcpy 有两个运行阶段：嵌入阶段（`_embed_timer` 500ms 轮询窗口句柄）和监控阶段（`_monitor_timer` 2000ms 轮询进程存活）。「重连 scrcpy」按钮初始为禁用（灰色），只有监控 timer 检测到进程退出、发出 `scrcpy_disconnected` 信号后才会被启用。

用户需求：
1. **按钮始终可点击**（不要灰色禁用态）。
2. **不需要监控 scrcpy 连接状态**（移除运行期存活轮询与断开信号）。
3. 用户在需要时**手动点击按钮重新连接**即可。

改动仅涉及 `安卓端/annotation_editor.py` 一个文件，删除监控机制、保留启动期嵌入轮询（用于首次启动/重连时把 scrcpy 窗口嵌入进来）。

## Current State Analysis（现状分析）

- `ScrcpyEmbedWidget`（[L165-362](file:///c:/Project/TC/300step采标工具/安卓端/annotation_editor.py#L165-L362)）
  - 三个信号：`scrcpy_embedded`、`scrcpy_error`、`scrcpy_disconnected`（L166-168）。
  - `_MODE_EMBEDDING` / `_MODE_MONITORING` 两态（L171-172、L181）。
  - `start_scrcpy()`（L193-223）：先 `_cleanup_process()` 再 Popen 启动，开启 500ms 嵌入 timer。
  - `_on_embed_tick()`（L256-290）：找到窗口→嵌入→切到 monitoring 态→**启动 2000ms 监控 timer**（L288-290）。
  - `_on_monitor_tick()`（L293-299）：每 2s `poll()`，退出则调 `_handle_process_exited`。
  - `_handle_process_exited()`（L302-328）：按 `_mode` 区分「启动失败（emit error）」与「运行中断线（emit disconnected）」。
- `AnnotationEditor`
  - 按钮创建即 `setEnabled(False)`（[L1294-1302](file:///c:/Project/TC/300step采标工具/安卓端/annotation_editor.py#L1294-L1302)），含 `:disabled` 灰色样式。
  - 信号连接 L1359-1361。
  - `_on_scrcpy_ready`（L1644-1653）：再次禁用按钮（L1647）。
  - `_on_scrcpy_disconnected`（L1658-1664）：启用按钮、隐藏并清空 overlay。
  - `_reconnect_scrcpy`（L1666-1672）：禁用按钮→调 `start_scrcpy`。
- `main.py` 只通过 `scrcpy_widget.start_scrcpy(serial)` 启动（L418、L509），不引用任何断开信号，无需改动。

## Proposed Changes（具体改动）

文件：`c:\Project\TC\300step采标工具\安卓端\annotation_editor.py`

### 1. `ScrcpyEmbedWidget` 移除监控阶段

- **删除信号** `scrcpy_disconnected`（L168）。
- **删除状态常量与字段**：`_MODE_EMBEDDING`/`_MODE_MONITORING`（L170-172）、`__init__` 中的 `self._monitor_timer`（L179）、`self._mode`（L181）。
- `start_scrcpy()`（L193-223）：删除 `self._mode = self._MODE_EMBEDDING`（L203）。其余逻辑（清理旧进程、Popen、开嵌入 timer）不变。
- `_cleanup_process()`（L225-253）：删除停止 `_monitor_timer` 的 4 行（L232-234）和末尾 `self._mode = self._MODE_EMBEDDING`（L253）。
- `_on_embed_tick()`（L256-290）：
  - 进程在嵌入成功前退出仍调 `_handle_process_exited(ret)`（保留，作为启动失败反馈）。
  - 嵌入成功后：删除 `self._mode = self._MODE_MONITORING`（L282）与创建/启动 `_monitor_timer` 的 3 行（L287-290）。保留隐藏 placeholder、`update()`、`emit scrcpy_embedded`。
- **删除方法** `_on_monitor_tick()`（L293-299）。
- 简化 `_handle_process_exited()`（L302-328）：去掉 `was_embedded` 分支与 disconnected 发射，仅保留「启动阶段退出」逻辑——读取 stderr、`_cleanup_process()`、设置占位文字（沿用现有 `scrcpy 已退出 (返回码...)` 文案）、`emit scrcpy_error(...)`。方法可保留原名（仅被嵌入 tick 调用）。
- `closeEvent` 不变（仍调 `_cleanup_process`）。

### 2. `AnnotationEditor` 按钮常亮 + 手动重连

- 按钮（L1293-1302）：
  - 删除 `self.btn_reconnect_scrcpy.setEnabled(False)`（L1295），按钮创建即为可用态。
  - 样式表中删除 `:disabled { ... }` 那条规则（L1299），保留橙色正常/hover 样式。
  - 注释改为「手动重连：任何时候点击都重新拉起 scrcpy」。
- 删除信号连接 `self.scrcpy_widget.scrcpy_disconnected.connect(...)`（L1361）。
- `_on_scrcpy_ready()`（L1644-1653）：删除 `self.btn_reconnect_scrcpy.setEnabled(False)`（L1647），其余（状态栏、overlay 分辨率/hwnd/显示）不变。
- **删除方法** `_on_scrcpy_disconnected()`（L1658-1664）。
- 重写 `_reconnect_scrcpy()`（L1666-1672）：
  - 不再禁用按钮（保持常亮）。
  - 先隐藏并清空蒙版：`self.overlay.hide()` + `self.overlay.clear_rect()`（承接原断开回调里对失效 overlay 的处理，避免旧框残留在新窗口上）。
  - 状态栏设置「正在重新连接 scrcpy...」。
  - 调用 `self.scrcpy_widget.start_scrcpy(self._serial)`（内部已 `_cleanup_process` 先 kill 旧进程，重复点击安全、幂等）。
- `_on_scrcpy_error()`（L1655-1656）保持不变：仅更新状态栏提示，按钮依旧可点击，便于用户重试。

### 3. 不改动项

- `screenshot_capture.py`、`main.py`、`data_manager.py` 均不改动。
- 首次启动流程（main.py L418/L509）不变：仍由嵌入轮询在窗口出现时自动嵌入。
- 嵌入超时逻辑（60 次 ×500ms = 30s，L265-272）保留。

## Assumptions & Decisions（假设与决策）

- **保留启动期轮询**：嵌入窗口必须靠 500ms 轮询发现 scrcpy 窗口句柄，这是功能必需，不属于「连接状态监控」，故保留；只删除嵌入成功后的 2s 存活监控。
- **运行中 scrcpy 死亡后不再自动提示**：画面会停留在最后状态，用户自行判断后点按钮重连——这正是用户要求。占位文字「scrcpy 已断开…请点击重连」仅在启动失败路径由 error 文案覆盖，不再有专门的 disconnected 文案。
- **不新增重入锁/标志位**：`start_scrcpy` 自带 `_cleanup_process`，连续点击只会反复 kill+重启，无副作用，维持最小改动。
- 行为对齐用户原话，不做额外健壮性增强。

## Verification（验证步骤）

1. 语法检查：`python -m py_compile annotation_editor.py`（在 `安卓端` 目录）。
2. 连接 Android 设备正常启动新任务：scrcpy 窗口正常嵌入；「重连 scrcpy」按钮全程为橙色可点击（非灰色）。
3. 采集过程中直接拔掉 USB（或在手机上关闭 scrcpy 窗口）：应用不报错、不弹断开提示；重新插上后点击「重连 scrcpy」，scrcpy 窗口被重新拉起并嵌入，左键操作与右键拉框恢复正常。
4. 正常连接状态下直接点击「重连 scrcpy」：旧进程被清理、新窗口重新嵌入，蒙版旧拉框被清空。
5. 断开 USB 时点击「重连 scrcpy」：状态栏出现 scrcpy 退出/超时错误提示，按钮仍可继续点击；恢复设备后再次点击可成功。
6. 断点续采入口（main.py resume）启动后行为同 2。
