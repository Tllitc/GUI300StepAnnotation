# iOS 端截图类按钮与 Windows 端对齐 Spec

## Why
iOS 版 `annotation_editor.py` 目前只有一个「截图 (Ctrl+Q)」入口：当前步已有截图时原地覆盖、没有时追加新步，两种语义混在一个按钮里。Windows 版则拆成「重新截图」（覆盖当前步）与「给下一步截图」（追加新步）两个独立按钮。用户需要按 Windows 端的操作功能与按钮逻辑补齐 iOS 端。

## What Changes
- 工具栏把「截图 (Ctrl+Q)」拆成两个入口并改名：
  - `重新截图`（橙 `#FF9800`）：原地覆盖当前步截图，文件名/序号/步骤下标不变。
  - `给下一步截图 (Ctrl+Q)`（蓝 `#2196F3`）：追加一个新步骤的新截图，不改动当前步截图。
- 保留既有 `在此步后插入截图`（青 `#00897B`），三个采集入口按 Windows 顺序排列：插入截图 → 重新截图 → 在原图上重新拉框 → 给下一步截图。
- 新增 `start_capture()`（给下一步截图）与 `recapture_current_step()`（重新截图）两个入口方法，底层仍复用 `take_screenshot()` / `_do_screenshot()`，默认行为保持不变（既有测试与 scroll extra、插入模式不受影响）。
- `Ctrl+Q` 改绑到「给下一步截图」；`Ctrl+S` 仍为「下一步」（保留 iOS 既有确认流程）。
- 空态提示、初始状态栏文案从「截图(Ctrl+Q)」改为「给下一步截图(Ctrl+Q)」。
- 不对齐的部分（本次明确不改）：「确认」=保存并前进、「撤销」=删除当前步、PageUp/PageDown 快捷键、窗口隐藏/最小化、系统级全局热键。

## Impact
- 影响能力：iOS 端截图采集入口（追加 / 覆盖 / 插入）、快捷键、工具栏布局。
- 影响代码：
  - `ios端/annotation_editor.py`：`init_ui` 工具栏（约 903-979）、`initialize_gui_directory` 附近新增入口方法（约 1297）、`take_screenshot`（1322-1354）、`_do_screenshot`（1356-1518）、`ScreenshotCanvas.paintEvent` 占位文案（246）、状态栏初值（1194）、`keyPressEvent`（3810）。
  - `ios端/tests/`：新增 `test_capture_entries.py`；既有 `test_recapture.py`、`test_insert_capture.py`、`test_data_integrity.py` 等依赖 `take_screenshot()` 默认语义，必须全绿。

## ADDED Requirements

### Requirement: 给下一步截图入口
系统 SHALL 提供独立的「给下一步截图」按钮与 `start_capture()` 方法，语义为追加一个新的待确认步骤截图，绝不覆盖已有步骤的截图文件。

#### Scenario: 已确认步骤上追加下一步
- **WHEN** `current_step < len(steps_data)` 且点击「给下一步截图」
- **THEN** 新截图按 `gui_<编号>_<四位序号>.png` 分配新序号落盘；原步骤的 `screenshot`/`screenshot_filepath` 不变；`steps_data` 长度不变；游标移动到 `len(steps_data)`（新的待确认空位），画布保留新截图，表单/拉框/坐标清空
- **AND** 状态栏提示已为下一步截图，等待标注确认；草稿防抖落盘被触发

#### Scenario: 空列表截取第一张
- **WHEN** `steps_data` 为空且点击「给下一步截图」
- **THEN** 生成第一张截图并停在待确认空位，不报错、不产生额外步骤

#### Scenario: 待确认空位重复点击
- **WHEN** 游标位于未确认空位（`current_step == len(steps_data)`）且已有待确认截图，再次点击「给下一步截图」
- **THEN** 原地覆盖该待确认截图，不新增文件、不产生孤儿截图

#### Scenario: 采集过程中的门闩
- **WHEN** 处于轮次切换窗口、未初始化任务目录、截图进行中、swipe 测量中或 scroll 测量中
- **THEN** 入口直接早退并给出提示，不发起截图、不改变任何步骤数据

### Requirement: 重新截图入口
系统 SHALL 提供独立「重新截图」按钮与 `recapture_current_step()` 方法，语义为原地覆盖当前步骤截图。

#### Scenario: 历史步或当前步重新截图
- **WHEN** 当前步已有截图且点击「重新截图」
- **THEN** 复用原文件名原地覆盖（序号不变、不重编号、不新增文件、不改变 `steps_data` 条目引用）；清空旧拉框、X/Y 坐标与画布红框；失效该步缩略图缓存并重建；状态栏提示可重新拉框标注

#### Scenario: 无截图时退化
- **WHEN** 当前没有可用截图（空列表或空白待确认位）且点击「重新截图」
- **THEN** 退化为截取第一张/当前空位截图，不弹错误提示

#### Scenario: 测量态约束
- **WHEN** swipe/拖拽测量进行中点击「重新截图」
- **THEN** 早退并提示先完成或取消测量
- **WHEN** scroll 滚动测量进行中点击「重新截图」
- **THEN** 走既有 extra 截图路径（追加额外截图用于比对参照物），不替换步骤截图、不改变游标

### Requirement: 按钮与快捷键呈现
工具栏 SHALL 只保留三个截图入口（插入 / 重新截图 / 给下一步截图），不再出现通用「截图」按钮。

#### Scenario: 快捷键
- **WHEN** 按下 `Ctrl+Q`
- **THEN** 触发「给下一步截图」（`start_capture`）
- **WHEN** 按下 `Ctrl+S`、`→`、`←`、`Esc`
- **THEN** 行为保持不变（下一步 / 下一步 / 上一步 / 清除标注）

#### Scenario: 新手引导文案
- **WHEN** 画布为空或处于初始状态
- **THEN** 提示文案指向 `[给下一步截图(Ctrl+Q)]`，不再指向「截图」

### Requirement: 编辑已完成任务模式下的采集入口
编辑模式（`_edit_mode=True`）下三个采集入口 SHALL 与新采标模式同样可用，且数据可完整写回：
- 「给下一步截图」产生的待确认新步 SHALL 能被「确认」提交进 `steps_data`（与 Windows 端编辑模式可保存新增步的语义一致），随后「保存修改」将新步完整写回 JSON trajectory 与 coords，不产生孤儿截图。
- 「在此步后插入截图」的锚点步落表 SHALL 走编辑模式落表（`_save_current_to_steps_for_edit`），锚点步截图缺失时文本修改不丢，`coord_issue/orig_coord_entry` 标记保留。
- 「重新截图」原地覆盖当前步截图，intent 等文本修改保留，不写草稿。

#### Scenario: 编辑模式追加新步并写回
- **WHEN** 编辑模式下点击「给下一步截图」，拉框填写后点击「确认」，再点击「保存修改」
- **THEN** 新步进入 `steps_data`，写回后的 JSON trajectory 与 coords 均包含该新步，原步骤受保护字段不被空值覆盖

#### Scenario: 草稿续采模式一致性
- **WHEN** 从草稿恢复任务后使用「给下一步截图」/「重新截图」
- **THEN** 追加/覆盖语义、门闩与草稿落盘行为与新采标模式完全一致

## MODIFIED Requirements

### Requirement: 截图底层入口
`take_screenshot()` / `_do_screenshot()` 的默认行为保持不变：无参调用（既有测试、scroll extra、插入模式）时，若当前步已有截图则原地覆盖，否则追加。新增「强制追加」标记仅供 `start_capture()` 使用，且在追加标记生效时不进入替换分支；所有标记在截图结束（成功或失败）后一律复位。

## REMOVED Requirements

### Requirement: 通用「截图 (Ctrl+Q)」按钮
**Reason**: 覆盖/追加两种语义混在同一按钮，与 Windows 端入口不一致且易误操作。
**Migration**: 需要覆盖当前步用「重新截图」；需要新步骤用「给下一步截图」；需要在中间插步用「在此步后插入截图」。