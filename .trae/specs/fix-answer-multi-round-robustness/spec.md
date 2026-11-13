# answer/answer_terminate 多轮轨迹（含缩略图/预览）健壮性修复 Spec

## Why

四端（Windows / 安卓 / iOS / macOS）的「回答用户（answer）」「回答并结束（answer_terminate）」会把当前轮落入 `rounds` 并开启下一轮，是典型的多轮轮询式问答轨迹入口。审查发现该场景只有 Windows/iOS/Android 的部分分支被加固（B1/B2/B14/B20a/B28/B42），仍存在未覆盖的漏洞：中间轮绕过必填校验、终止类动作允许停在本轮中间步、落轮后取消/续采恢复时旧指令残留、macOS 落轮无防护且编辑已完成任务会触发切轮、macOS coords 丢失轮次归属、交付完成后仍可继续截图污染交付目录。

同时，缩略图/预览链路完全没有按多轮建模：落轮后上一轮的缩略图与大图预览全部从界面消失，采集员无法回看已提交轮次中的框选是否正确；iOS 缩略图缓存只按文件名建键、懒加载队列快照 request 时的 vertices，重拉框/重截图后会复用旧框缩略图；macOS 取消新轮后旧轮画面残留在画布上。这些都会让采集员在多轮任务中误判「框有没有拉对」，或把上一轮的画面当成新一轮。

## What Changes

- **终止类动作必须位于本轮最后一步（四端）**：在 `answer` / `answer_terminate` / `terminate` 确认入口校验当前步之后是否还有步骤；有则弹窗拦截（不得落轮、不得清空 `steps`、不得写交付 JSON）。
- **answer 落轮前全轮必填校验（Windows / macOS）**：与 terminate 分支同口径，用 `validate_step_at` 校验本轮全部步骤，缺项弹 `ValidationFailDialog` 并保持现场（安卓/iOS 已在确认时逐步入表校验，本次不改其校验口径，只补「最后一步」约束）。
- **轮次边界取消后清理旧指令（macOS 主修，Windows/iOS 补续采路径）**：`answer` 落轮后取消新轮、以及「续采恢复后取消下一条指令」时，必须清空 `task_instruction` 并把工作区重置为空白起点；Android 已有 `apply_next_round_instruction`，作为跨端参照口径。
- **macOS 落轮防护与失败传播**：`save_current_round` 增加「本轮缺少指令 → 弹窗补齐，未补齐返回 False」守卫，调用方（answer/terminate 分支、`finish_all_annotation`）必须尊重返回值，禁止写出缺轮或空指令的交付文件。
- **macOS 编辑已完成任务守卫**：`save_current_step` 增加 `_edit_mode` 早退（对齐 Windows），编辑已完成任务时确认 answer/terminate 只落当前步，不追加轮次、不弹新轮对话框。
- **macOS coords 轮次归属**：落轮收集坐标条目时注入 `round` 下标（对齐 Windows B4/B18 与移动端序列化注入），避免多轮同名 `(step, action)` 坐标错配。
- **多轮轨迹回看（四端，缩略图 + 预览）**：新增只读「查看已完成轮次」入口：轮次下拉 + 该轮步骤缩略图列表 + 大图预览（按该轮 coords 条目绘制标注框）；缩略图分批懒加载、独立 LRU 缓存；不读写 `steps`/`rounds`，不触发草稿；无已完成轮次时入口禁用。
- **轮次边界缩略图/预览复位（四端）**：落轮、切轮、取消新轮后清空侧栏缩略图队列与画布/预览，新轮首图出现前不得展示上一轮画面；已落轮的数据仍可通过回看器查看。
- **iOS 缩略图缓存与队列对齐（iOS）**：缓存键由「文件名」改为「文件名 + 框顶点签名」，懒加载批次以加载时刻 `steps_data` 为准（文件名/框已变的陈旧队列项直接丢弃），与 Windows/Android/macOS 口径一致；重拉框/重截图后不再显示旧框缩略图。
- **交付完成后阻断后续采集（四端）**：交付 JSON 成功写出后保持「轮次切换/任务已结束」门闩，截图、确认、重截图、插入、删除等入口一律早退；开启新任务/新轮时复位。`_finish_task` 增加重入保护。
- **测试**：四端各新增 answer 多轮回归用例与回看器用例；更新 Windows/macOS 测试助手，让 answer 步骤带合法 `intent` 以满足新增校验。

## Impact

- Affected specs：`verify-multi-round-duplication`（多轮唯一性回归，规则不变）、`fix-mobile-missing-validation`（校验口径不变，仅扩展 answer 落轮出口）、`edit-completed-datasets`（macOS 编辑模式守卫补齐）、`support-long-trajectory-300plus`（缩略图/预览必须继续分批懒加载，不得一次性读盘）。
- Affected code：
  - `annotation_editor.py`（Windows）：`save_current_step`、`finish_all_annotation`、`reset_for_new_task`、`cancel_next_round_instruction`（新增）、`start_capture`/`confirm_button_clicked` 门闩、新增 `RoundPreviewDialog` 与工具栏入口、`main.py` 续采取消分支。
  - `安卓端/annotation_editor.py`：`confirm_step`（最后一步约束）、`_finish_task`（重入 + 交付后门闩）、`take_screenshot`、新增 `RoundPreviewDialog` 与工具栏入口。
  - `ios端/annotation_editor.py` 与 `ios端/main.py`：`confirm_step`、`_finish_task`、`start_capture`、`_start_new_task`（标志复位）、SideBar 缩略图缓存键与懒加载队列、新增 `RoundPreviewDialog`、续采取消分支。
  - `macos端/annotation_editor.py` 与 `macos端/main.py`：`save_current_step`、`save_current_round`、`_prompt_missing_instruction`（新增）、`start_new_round`、`finish_all_annotation`、`create_new_task`、`reset_for_new_task`、`start_capture`/`confirm_button_clicked` 门闩、新增 `RoundPreviewDialog`、续采取消分支。
  - 四端 `tests/`：新增 `test_answer_round_flow.py`；`tests/helpers.py`（Windows）与 `macos端/tests/helpers.py` 的 answer 填表补 `intent`。

## ADDED Requirements

### Requirement: 终止类动作必须是本轮最后一步

系统 SHALL 在 `answer`、`answer_terminate`、`terminate` 确认时检查当前步在本轮中的位置；当前步之后仍存在步骤时，SHALL 拒绝该次确认并提示先删除/撤销后续步骤，不得落轮、不得清空步骤、不得写出交付 JSON。

#### Scenario: 中间步误选回答用户
- **WHEN** 本轮已有 3 步，用户跳到第 2 步将其动作改为「回答用户」并点击确认
- **THEN** 弹出「终止类动作必须是本轮最后一步」提示
- **AND** `rounds` 长度不变，本轮 3 个步骤完整保留，草稿未被清空

#### Scenario: 中间步误选任务完成
- **WHEN** 本轮已有 3 步，用户在第 2 步选择「任务完成」并确认
- **THEN** 结束被拦截，不写 `gui_XXXXXX.json`，不切轮

#### Scenario: 末步与未确认空位照常放行
- **WHEN** 当前步是本轮最后一步，或当前处于尚未截图的空白待确认位
- **THEN** answer/answer_terminate/terminate 按原流程落轮或结束

### Requirement: answer 落轮前全轮必填校验（Windows / macOS）

Windows 与 macOS 在 `answer` 落轮前 SHALL 以 `validate_step_at` 校验本轮全部步骤（含当前步），存在缺项时 SHALL 弹 `ValidationFailDialog` 并保持数据现场，不得落轮。

#### Scenario: 中间轮缺项被拦截
- **GIVEN** 本轮第 1 步的动作描述被清空，末步为「回答用户」
- **WHEN** 用户确认末步 answer
- **THEN** 弹出缺项清单并定位到第 1 步
- **AND** `rounds` 不增加，`steps` 保持完整；补齐后可正常落轮

### Requirement: 轮次边界取消新轮清空旧指令

在 `answer` 落轮后取消新轮、或在续采恢复（`current_steps` 为空但 `rounds` 非空）时取消下一条指令输入，系统 SHALL 清空 `task_instruction` 并把工作区重置为空白起点，后续采集不得再挂到上一轮已消费的指令上。

#### Scenario: answer 后取消新轮（macOS）
- **WHEN** 用户以 answer 落轮，随后在「新任务指令」对话框点取消
- **THEN** 步骤列表/画布/表单/步骤下标复位，`task_instruction` 为空，侧栏与看板清空
- **AND** 已落轮的 trajectory 与草稿中的 rounds 不被破坏

#### Scenario: 续采恢复后取消下一条指令（Windows / iOS / macOS）
- **GIVEN** 草稿处于「answer 已落轮、等待新指令」状态
- **WHEN** 用户恢复任务并在指令输入框点取消
- **THEN** `task_instruction` 被清空，草稿同样落为空指令
- **AND** 之后采集的新轮必须显式补齐指令才能落轮

### Requirement: macOS 落轮缺指令拒绝

macOS `save_current_round` SHALL 在缺少任务指令时弹窗补齐；用户未补齐时返回 False 且不追加轮次。`save_current_step` 的 answer/terminate 分支与 `finish_all_annotation` SHALL 尊重该返回值：失败时中止落轮/写盘并保持现场。

#### Scenario: 缺指令时不产出空指令轮次
- **WHEN** `task_instruction` 为空且用户在补齐弹窗点取消后触发 answer/结束
- **THEN** `rounds` 不增加，不写交付 JSON，界面提示需要补齐指令

### Requirement: macOS 编辑已完成任务不触发轮次迁移

macOS 在编辑已完成任务模式下确认 answer/answer_terminate/terminate 时 SHALL 只保存当前步数据并合并受保护下游字段，不得调用 `save_current_round`、不得清空步骤、不得弹新轮/新任务对话框。

#### Scenario: 编辑已交付轮次中的 answer 步
- **WHEN** 用户进入某已完成轮次，修改 answer 文本后点击确认
- **THEN** `rounds` 长度不变，页面停留在当前轮，`保存修改` 写回后 messages 不出现重复轮次

### Requirement: macOS coords 条目携带轮次

macOS 落轮收集的 coords 条目 SHALL 携带 `round`（从 0 起的轮次下标）；写入 `gui_XXXXXX_coords.json` 时保持该字段，供下游按轮次归属坐标。

#### Scenario: 两轮同签名坐标步
- **WHEN** 第 1、2 轮各有一个 `step=0` 的 click 步并完成交付
- **THEN** coords 文件两条记录分别带 `round: 0`、`round: 1`，不依赖 step 回退猜测

### Requirement: 多轮轨迹回看（缩略图 + 预览，四端）

系统 SHALL 提供只读的「查看已完成轮次」入口，让采集员在 `rounds` 非空时回看每个已提交轮次：
- 轮次选择控件显示全部已完成轮次（含指令摘要，无已完成轮次时入口禁用）；
- 选中轮次后列出该轮全部步骤的缩略图（动作名 + 序号），缩略图按该轮 coords 条目绘制标注框；
- 选中步骤后展示该步大图预览（磁盘原图 + 该轮标注框；条目缺失/截图丢失时降级为原图或明确提示）；
- 回看过程只读：不得修改 `steps`/`rounds`/coords、不得写草稿、不得改变主界面当前步与选中轮次；
- 大量步骤时缩略图分批生成，不阻塞界面，也不得一次性加载全部原图。

#### Scenario: 回看第一轮
- **WHEN** 用户完成第 1 轮（answer 落轮）后点击「查看已完成轮次」
- **THEN** 轮次下拉含第 1 轮，列表条目数等于该轮 trajectory 步数
- **AND** 选中任一步后大图预览显示该步磁盘截图与对应标注框

#### Scenario: 切换到另一轮
- **WHEN** 已有 2 个已完成轮次，用户在下拉中切到第 2 轮
- **THEN** 步骤列表与预览整体切换为第 2 轮数据，不残留第 1 轮条目/画面

#### Scenario: 只读不影响采集
- **WHEN** 用户打开回看器浏览后关闭
- **THEN** 主界面的步骤、轮次、草稿、当前步与打开前完全一致

### Requirement: 轮次边界缩略图与预览复位

落轮、切轮或取消新轮后，系统 SHALL 清空侧栏缩略图队列与显示中的预览画面；新一轮第一张截图产生前不得展示上一轮截图或缩略图。

#### Scenario: answer 落轮后立即取消
- **WHEN** 用户以 answer 落轮后取消新轮
- **THEN** 侧栏无上一轮条目、主预览区回到空白提示，不出现上一轮缩略图

### Requirement: iOS 缩略图缓存与队列对齐

iOS 侧栏缩略图缓存键 SHALL 为「截图文件名 + 框顶点签名」；懒加载批次执行时 SHALL 校验队列项与当前 `steps_data` 的文件名/顶点一致，不一致的陈旧项直接丢弃，不得把旧框缩略图写入缓存。

#### Scenario: 重拉框后缩略图更新
- **WHEN** 某步已在队列中等待生成缩略图，随后用户在原图上重新拉框
- **THEN** 该步最终显示的缩略图使用新框，旧框缩略图不得被缓存复用

### Requirement: 交付完成后阻断后续采集

交付 JSON 成功写出后，系统 SHALL 在进入「是否开始新任务」流程期间保持轮次切换门闩，截图、重截图、插入截图、确认、删除等入口直接早退并提示；仅当确实开启新任务/新轮时复位。`_finish_task` SHALL 幂等（已完成后重复触发不再重复保存）。

#### Scenario: answer_terminate 后误触截图
- **WHEN** 任务已保存并弹出「是否继续新任务」，用户按到截图快捷键
- **THEN** 不产生新截图、不新增步骤、不向已交付目录写入孤儿 PNG

## MODIFIED Requirements

### Requirement: 多轮轮次落盘点

Windows/macOS `save_current_round` 与移动端 `_save_current_round_to_list` 作为本轮唯一落盘点，在新增「最后一步」「全轮校验」「指令守卫」「交付后门闩」约束后，仍 SHALL 保证：已落轮 trajectory/coords 不被后续操作原地改写；落轮后 `steps` 清空且草稿同步为「rounds 非空、current_steps 为空」；交付 JSON 的 messages 始终为 user/assistant 交替且与 rounds 一一对应。

#### Scenario: 正常四轮任务不受影响
- **WHEN** 连续 4 轮采标（前 3 轮以 answer 续轮、末轮 terminate）
- **THEN** messages 为 8 条，各轮 trajectory 完整，截图名跨轮唯一，coords 均带 round

### Requirement: 侧栏缩略图缓存与懒加载

四端侧栏缩略图 SHALL 以「截图文件名 + 框几何」为缓存键并沿用分批懒加载与 LRU 上限；回看器使用独立缓存，不与侧栏缓存互相淘汰。

#### Scenario: 300+ 步多轮任务
- **WHEN** 任务累计 300 步以上且包含多个已完成轮次
- **THEN** 侧栏与回看器都按批生成缩略图，内存中不保留全屏原图，切换轮次不重复读盘已缓存的文件