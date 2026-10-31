# 添加 scrcpy 掉线检测与手动重连 Plan

## Repository Research

### 现状分析

| 组件 | 当前行为 | 问题 |
|------|---------|------|
| `ScrcpyEmbedWidget.start_scrcpy()` | 启动 scrcpy 子进程 + `_embed_timer` 每 500ms 轮询进程状态，成功嵌入后停表 | 启动后完全无监控，掉线后无法感知 |
| `ScrcpyEmbedWidget.closeEvent()` | 关闭窗口时 terminate + kill scrcpy 进程 | 只在关闭时清理，无暴露的"清理+重启"方法 |
| `ScrcpyEmbedWidget.paintEvent()` | placeholder 状态显示 `_status_text`（如启动超时、已退出） | 嵌入成功后 `_show_placeholder=False`，掉线无视觉反馈 |
| `AnnotationEditor._on_scrcpy_error()` | 只更新 status_label 文字 | 启动后不会再触发 |

### 目标

1. **嵌入成功后继续监控进程**：`_embed_timer` 不停，改为"嵌入前尝试嵌入 + 嵌入后监控存活"双模式
2. **暴露 cleanup + restart 方法**：给外部（工具栏按钮）一个安全的重连入口
3. **嵌入成功后 paintEvent 仍能显示状态**：掉线时 overlay 禁用，placeholder 显示"scrcpy 已断开"

### 关键类和方法

| 类/方法 | 位置 | 改动 |
|--------|------|------|
| `ScrcpyEmbedWidget` | annotation_editor.py:165 | 核心改动：持续监控 + 重连方法 + 新信号 |
| `_try_embed()` | line 212 | 扩展：嵌入成功后保留 timer，改为监控进程存活 |
| `start_scrcpy()` | line 186 | 清理逻辑抽成 `_cleanup_process()`，重入时先清理 |
| `closeEvent()` | line 273 | 复用 `_cleanup_process()` |
| `AnnotationEditor.init_ui()` | ~line 1190 | 工具栏添加"重连 scrcpy"按钮 |
| `_on_scrcpy_ready` / `_on_scrcpy_error` | line 1559/1567 | 新增 `_on_scrcpy_disconnected(msg)` 处理掉线 |

## Files and Modules

- `安卓端/annotation_editor.py`: 主要改动

## Implementation Steps

### Step 1: 重构 ScrcpyEmbedWidget 内部方法

#### 1.1 抽取进程清理方法 `_cleanup_process()`
从现有的 `closeEvent` 逻辑抽取：
```python
def _cleanup_process(self):
    """安全终止 scrcpy 子进程，清理 hwnd/timer 引用"""
    if self._embed_timer:
        self._embed_timer.stop()
    if self.scrcpy_process:
        try:
            self.scrcpy_process.terminate()
            self.scrcpy_process.wait(timeout=2)
        except Exception:
            pass
        finally:
            try:
                self.scrcpy_process.kill()
            except Exception:
                pass
    self.scrcpy_process = None
    self.scrcpy_hwnd = None
```

#### 1.2 `start_scrcpy` 重入保护
开头先调 `_cleanup_process()`，防止重启时旧进程残留。

#### 1.3 扩展 `_try_embed` 为双模式
```python
def _try_embed(self):
    if self.scrcpy_process is None:
        return
    ret = self.scrcpy_process.poll()
    if ret is not None:
        # ---- 不管嵌入成功与否，只要进程退出都走这里 ----
        # 区分：已经嵌入过（_embed_attempts 已经过 60 或 self.scrcpy_hwnd 曾赋值）
        self._embed_timer.stop()
        was_embedded = self.scrcpy_hwnd is not None
        self._cleanup_process()
        _, stderr = self.scrcpy_process.communicate()  # 注意 _cleanup_process 已 kill，这里可能读不到
        # 实际上 kill 之后 communicate 已经没用了，改成 kill 前先读
        ...
        if was_embedded:
            self._status_text = "scrcpy 已断开"
            self._show_placeholder = True
            self.update()
            self.scrcpy_error.emit("scrcpy 已断开连接")
        else:
            # 启动阶段退出
            ...
        return
    # ---- 还在运行 ----
    if self.scrcpy_hwnd is None:
        # 嵌入阶段：继续尝试
        self._embed_attempts += 1
        if self._embed_attempts > 60:
            ...  # 超时
        hwnd = find_window_by_pid(...)
        if hwnd: ...  # 嵌入成功
    # 已嵌入：timer 继续跑，下次 poll 检查进程
```

关键点：**嵌入成功后不停 timer**，间隔可以放慢（比如从 500ms 改为 2000ms 省电）。

#### 1.4 新增信号
```python
scrcpy_disconnected = pyqtSignal(str)  # 掉线时发射
scrcpy_embedded  # 已有，启动成功时
scrcpy_error     # 已有，启动失败时
```
把 `_on_scrcpy_error` 的"掉线"情况分流到新信号，避免和启动失败混淆。

#### 1.5 paintEvent 在嵌入成功后仍能显示状态
现在 paintEvent 只在 `_show_placeholder=True` 时才显示。嵌入成功后 `_show_placeholder=False`。需要改成：
- 掉线时设 `_show_placeholder=True` + 更新 `_status_text`
- 这样 paintEvent 自动显示"scrcpy 已断开"

### Step 2: AnnotationEditor 添加重连按钮和处理

#### 2.1 init_ui 工具栏添加按钮
在 `toolbar.addStretch()` 之前（或者和蒙版按钮放一起）：
```python
self.btn_reconnect_scrcpy = QPushButton("重连 scrcpy")
self.btn_reconnect_scrcpy.setEnabled(False)  # 初始禁用，掉线后启用
self.btn_reconnect_scrcpy.setStyleSheet(
    "QPushButton { background-color: #FF9800; color: white; padding: 6px 12px; }"
    "QPushButton:hover { background-color: #F57C00; }"
    "QPushButton:disabled { background-color: #BDBDBD; color: white; }"
)
self.btn_reconnect_scrcpy.clicked.connect(self._reconnect_scrcpy)
toolbar.addWidget(self.btn_reconnect_scrcpy)
```

#### 2.2 连接掉线信号 + 实现处理方法
```python
self.scrcpy_widget.scrcpy_disconnected.connect(self._on_scrcpy_disconnected)
self.scrcpy_widget.scrcpy_embedded.connect(self._on_scrcpy_ready)  # 已有
```

```python
def _on_scrcpy_disconnected(self, msg):
    self.status_label.setText(f"scrcpy 已断开: {msg} - 可点击[重连 scrcpy]")
    self.btn_reconnect_scrcpy.setEnabled(True)
    self.overlay.clear_rect()
    self.overlay.hide()
    # 截图按钮禁用（scrcpy 断了 ADB 可能还在，但提示用户）
    self.btn_screenshot.setEnabled(False)

def _on_scrcpy_ready(self):
    # 已有逻辑 + 新增：重连成功后恢复按钮状态
    self.btn_reconnect_scrcpy.setEnabled(False)
    self.btn_screenshot.setEnabled(True)
    ...  # 原有 overlay 恢复逻辑
```

#### 2.3 重连实现
```python
def _reconnect_scrcpy(self):
    if not self._serial:
        QMessageBox.warning(self, "提示", "设备未连接，无法重连")
        return
    self.status_label.setText("正在重新连接 scrcpy...")
    self.btn_reconnect_scrcpy.setEnabled(False)
    self.scrcpy_widget.start_scrcpy(self._serial)
```

#### 2.4 closeEvent 清理
复用 `ScrcpyEmbedWidget._cleanup_process()`（现在在 ScrcpyEmbedWidget.closeEvent 里也复用这个方法，两边一致）。

### Step 3: 验证
1. 语法检查
2. 手动验证流程（有设备时）：启动 → 拔 USB → 状态变化 + 按钮启用 → 插回 USB → 点重连 → 恢复
3. 无设备时至少跑 dry-run import + 逻辑审查

## Dependencies and Considerations

- **poll() 间隔**：嵌入成功后 2000ms 足够，掉线有几秒感知延迟但可接受。启动阶段 500ms 保持。
- **进程清理顺序**：terminate → wait → kill，先 gracefully 再强杀，防止僵尸进程。
- **ADB vs scrcpy 生命周期**：scrcpy 掉线不代表 ADB 断了。但 `_on_scrcpy_disconnected` 暂时禁用截图按钮是保守策略（用户可以重连后恢复）。也可以选择不禁用，让 ADB 截图照常工作——按用户体验决定。
- **窗口句柄失效**：旧 scrcpy 被强杀后 hwnd 已无效，新 scrcpy 有新 pid 和 hwnd，`_do_embed` 会重新设 parent，没问题。
- **_status_text 状态文案**：
  - 启动中："正在启动 scrcpy..."
  - 启动超时："启动超时\n请检查 USB 连接和 USB 调试开关"
  - 启动失败（进程秒退）："scrcpy 已退出 (返回码: N)"
  - **新增** 嵌入后掉线："scrcpy 已断开连接"

## Validation
1. `py_compile` annotation_editor.py
2. 代码路径审查：启动→嵌入→运行→掉线→重连→成功

## Risks
- **连续快速重连导致僵尸进程**：`_cleanup_process()` 必须先 kill 旧进程再 start，已在 start_scrcpy 开头调用
- **重连后 overlay 覆盖层未正确重设**：`_on_scrcpy_ready` 已有 overlay.set_scrcpy_hwnd + show_overlay 逻辑，重连会再次触发
- **_embed_timer 双职责**：需要用状态标记区分"嵌入阶段"和"监控阶段"，不能混淆
