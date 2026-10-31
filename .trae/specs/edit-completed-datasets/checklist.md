# Checklist

## 入口与加载

- [x] 三端主菜单均出现「编辑已完成任务」入口，可选择 `gui_XXXXXX` 目录
- [x] 选择不含最终 JSON 的目录时提示「该任务尚未完成，请使用『继续未完成任务』」，不打开编辑器
- [x] 选择非 `gui_XXXXXX` 目录时提示目录格式错误，不打开编辑器
- [x] 已完成 JSON 含多个 assistant 轮次时弹出轮次选择框（轮次号 + 指令摘要）；取消回到主菜单；单轮自动进入
- [x] 进入编辑后窗口标题/状态栏明确标识「编辑已完成任务」

## 重建编辑现场

- [x] 选中第 r 轮后，步骤顺序、`step` 字段、截图文件名与 JSON 完全一致
- [x] 编辑器按 `gui_dir/文件名` 恢复截图预览；截图缺失时给警告但仍可编辑（三端均已实现）
- [x] Windows 按 coords 条目恢复 `rect_info`（单框/拖拽双框），iOS/Android 恢复 `vertices`
- [x] coords 条目含 `round` 时按 `round` 分组；旧文件无 `round` 时按 `step` 回退切分连续段并对齐轮次轨迹，未对齐条目保留在最后一轮且无丢失
- [x] 加载后顶层 `platform/system/screen_size/task_type` 与原 JSON 一致

## 编辑模式交互

- [x] 编辑模式下点击「确认」，即使动作是 answer / answer_terminate / terminate，也只落当前步，不切轮次、不结束任务、不弹「是否开始新任务」
- [x] 编辑模式存在「保存修改」按钮
- [x] 「保存修改」对当前轮全部步骤做必填校验；缺项时弹出清单并阻止保存
- [x] 校验通过后写回最终 JSON 与 coords，提示成功并返回初始化窗口
- [x] 编辑模式下删除/插入/重新截图只影响当前轮，其它轮 trajectory 与 coords 不变

## 写回一致性

- [x] 保存后最终 JSON 的 `messages` 顺序不变，仅第 r 轮 instruction/trajectory 更新，其它轮逐字段保持原值
- [x] 保存后 `step` 仍从 0 连续递增，截图全局唯一性约束仍成立
- [x] 仅修改 intent/text 时，原 action 的 `status`、`element` 等未暴露字段与 observation/trajectory 其它键被保留
- [x] Windows/iOS coords 写数组；Android 写 `{"version":"3.0","coords":[...]}`；iOS 条目保留 `round` 标记
- [x] 编辑后步骤的 `step/action/vertices/center`（拖拽含 start/end 四组字段）与拉框一致；未编辑轮坐标数值不变
- [x] 最终 JSON 写入失败时编辑器保持打开并提示失败，原文件不被破坏

## 草稿隔离与关闭

- [x] 编辑模式下的自动保存调度与立即写草稿入口均不生成 `*_draft.json`
- [x] 编辑模式直接关闭窗口时，先把当前轮修改写回最终 JSON 与 coords，再关闭；不生成 draft
- [x] 编辑模式直接关闭窗口后主窗口恢复显示（Windows/Android 已修复，iOS 由 `_close_callback` 恢复）
- [x] 关闭写回失败时保留原文件并记录错误

## 测试

- [x] Windows 编辑模式回归测试覆盖单轮/多轮加载、仅替换选中轮、关闭自动写回、缺项阻止保存、旧 coords 切分
- [x] 根目录 `QT_QPA_PLATFORM=offscreen python -m pytest tests -q` 通过（29 passed）
- [x] iOS `ios端/tests` pytest 通过（68 passed）
- [x] Android `安卓端/tests` pytest 通过（64 passed）
