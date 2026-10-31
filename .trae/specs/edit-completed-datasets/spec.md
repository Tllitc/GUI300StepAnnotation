# 已完成任务再编辑（三端） Spec

## Why

Windows、iOS、Android 三端采标工具在用户点击「任务完成」后，会把全部轮次写入 `gui_XXXXXX.json` / coords JSON 并删除 `*_draft.json`。主菜单只有「继续未完成任务」（依赖 draft），因此已完成的任务无法再从工具内打开修改；标注人员发现已提交数据中的意图、动作参数或遗漏步骤有误时，只能整段重采。

需要提供一个入口：**任务完成后仍可选择某个已完成的 `gui_XXXXXX` 数据集，按轮次进入编辑器修改并写回原文件**，且不影响同一数据集中的其它轮次、截图引用与坐标数据。

## What Changes

- 三端主菜单新增「编辑已完成任务」按钮：选择 `gui_XXXXXX` 目录 → 校验存在最终 JSON → 多轮时选择要编辑的轮次 → 打开编辑器。
- 三端 `AnnotationEditor` 新增 `load_from_completed_json(...)`：从最终 JSON 与 coords JSON 重建 `rounds`、当前编辑轮的步骤、截图路径、拉框坐标（`rect_info` / `vertices`）与动作表单，进入**编辑模式**。
- 编辑模式下工具栏新增「保存修改」按钮；「确认」只把当前步数据写回内存，不触发 answer 轮次切换、terminate 结束或"是否开始新任务"弹窗（避免编辑中间轮次时误切轮次）。
- 「保存修改」先对当前轮全部步骤做必填校验，通过后仅替换选中轮次的数据，其余轮次原样保留，重写最终 JSON 与 coords JSON，然后返回主菜单。
- 编辑模式不产生 draft；直接关闭编辑窗口时自动把修改写回最终 JSON（不弹保存确认），保证已完成任务不会重新出现在「继续未完成任务」列表中。
- 三端 `DataManager` 增加按目录读取最终 JSON / coords 的静态接口，兼容 coords 为 JSON 数组（Windows/iOS）或 `{"version","coords":[...]}` 对象（Android），并兼容旧文件中缺少轮次标记的情况。
- 输出契约不变：最终 JSON 的 `platform/system/screen_size/task_type/messages` 字段结构、coords 的平台格式保持原样；本轮未被编辑器暴露的未知字段（如 `status`、`element`、trajectory 其它键）在编辑后保留。

## Impact

- Affected specs: `support-long-trajectory-300plus`（rounds/steps/coords 数据模型）、`fix-draft-resume`（草稿生命周期，本变更在编辑模式下明确不写草稿）
- Affected code:
  - `main.py`、`annotation_editor.py`、`data_manager.py`（Windows 根目录）
  - `ios端/main.py`、`ios端/annotation_editor.py`、`ios端/data_manager.py`
  - `安卓端/main.py`、`安卓端/annotation_editor.py`、`安卓端/data_manager.py`
  - `tests/`、`ios端/tests/`、`安卓端/tests/`（新增回归测试）

## ADDED Requirements

### Requirement: 主菜单编辑入口
三端任务初始化窗口 SHALL 提供「编辑已完成任务」入口，允许用户选择已完成的 `gui_XXXXXX` 目录进入编辑模式。

#### Scenario: 选择已完成任务目录
- **WHEN** 用户在初始化窗口点击「编辑已完成任务」并选择一个包含 `gui_XXXXXX.json` 的目录
- **THEN** 工具创建对应 `AnnotationEditor`，加载该数据集的全部轮次并打开第 1 个可编辑轮次，窗口标题/状态栏明确显示「编辑已完成任务」

#### Scenario: 目录未完成或格式非法
- **WHEN** 用户选择的目录不存在最终 JSON，或目录名不是 `gui_XXXXXX`
- **THEN** 工具不打开编辑器，并提示"该任务尚未完成，请使用『继续未完成任务』"或"请选择 gui_xxxxxx 形式的任务目录"

#### Scenario: 多轮任务选择轮次
- **WHEN** 已完成 JSON 中存在多个 assistant 轮次
- **THEN** 工具弹出轮次选择框（轮次号 + 指令摘要）；用户取消则回到初始化窗口；只有一轮时自动进入该轮

### Requirement: 从已完成 JSON 重建编辑现场
编辑器 SHALL 能从最终 JSON + coords JSON 无损重建可编辑步骤。

#### Scenario: 单轮/多轮加载
- **WHEN** 选中第 r 轮（r 从 0 开始）
- **THEN** `rounds` 保存全部轮次的 instruction 与 trajectory；当前编辑步骤来自第 r 轮 trajectory，步骤顺序、`step` 字段、截图文件名与 JSON 一致

#### Scenario: 截图与坐标恢复
- **WHEN** 某步在 trajectory 中引用 `gui_XXXXXX_YYYY.png`
- **THEN** 编辑器按 `gui_dir/文件名` 恢复截图预览；若该步在 coords 中有条目，则恢复其拉框区域（Windows 为 `rect_info`，iOS/Android 为 `vertices`）；截图文件缺失时给出警告但允许继续编辑

#### Scenario: coords 轮次归属
- **WHEN** coords 条目含 `round` 字段（iOS 新格式）
- **THEN** 按 `round` 分组归属到对应轮次
- **WHEN** 旧文件缺少 `round` 字段
- **THEN** 按条目顺序与 `step` 递增关系切分为连续段（`step` 回退即视为下一轮），再按轮次轨迹的 `step/action/center` 匹配对齐；无法对齐的条目保留在最后一轮，绝不丢弃

#### Scenario: 元数据保留
- **WHEN** 加载已完成 JSON
- **THEN** `platform/system/screen_size/task_type` 等顶层字段以原 JSON 为准，编辑保存时原样写回，不因重新构造结构而丢失

### Requirement: 编辑模式交互
编辑模式下已有步骤编辑能力 SHALL 继续可用，但 SHALL NOT 触发采标流程的轮次迁移。

#### Scenario: 确认步骤
- **WHEN** 编辑模式下用户点击「确认」
- **THEN** 只把当前表单数据落回当前步骤（即使动作类型是 answer / answer_terminate / terminate），不切换轮次、不结束任务、不弹"是否开始新任务"

#### Scenario: 保存修改
- **WHEN** 用户点击「保存修改」
- **THEN** 对当前轮全部步骤执行与任务完成一致的必填校验；有缺项时弹出缺项清单并阻止保存；校验通过后写回最终 JSON 与 coords JSON，提示保存成功并返回初始化窗口

#### Scenario: 结构操作
- **WHEN** 编辑模式下用户删除/插入/重新截图
- **THEN** 只影响当前编辑轮次的步骤、截图文件与坐标，其它轮次的 trajectory 与 coords 不变

#### Scenario: 关闭窗口
- **WHEN** 用户在编辑模式下直接关闭窗口（含 `Esc`/标题栏关闭）
- **THEN** 工具先把当前轮的修改写回最终 JSON 与 coords JSON，再关闭窗口；不生成 draft；写盘失败时保留原文件并输出错误日志

### Requirement: 写回一致性
编辑保存 SHALL 只替换被编辑轮次，保持整个数据集其余内容与平台输出格式不变。

#### Scenario: 只替换选中轮次
- **WHEN** 用户编辑第 r 轮后保存
- **THEN** 最终 JSON 的 `messages` 顺序不变，第 r 轮的 instruction/trajectory 被更新，其它轮次逐字段保持原值；截图全局唯一性、`step` 从 0 连续递增的既有约束仍然成立

#### Scenario: 未暴露字段保留
- **WHEN** 用户在编辑器中只修改某步的 intent/text
- **THEN** 该步原 action 对象中编辑器未管理的字段（如 `status`、`element`、平台特有键）及 trajectory/observation 的其它键被保留；若截图文件名仍匹配原步骤，按文件名关联原步骤并合并缺失字段

#### Scenario: coords 输出格式
- **WHEN** 保存编辑结果
- **THEN** Windows/iOS 写数组格式、Android 写 `{"version":"3.0","coords":[...]}`；iOS 保持为每个条目附加 `round`；步骤的 `step/action/vertices/center`（拖拽含 `start_vertices/start_center/end_vertices/end_center`）与编辑后拉框一致，未被编辑轮次的坐标条目数值不变

#### Scenario: 保存失败
- **WHEN** 最终 JSON 写入返回失败
- **THEN** 编辑器保持打开并提示失败，不删除任何已完成数据

### Requirement: 已完成任务与草稿隔离
编辑模式 SHALL NOT 生成 `*_draft.json`，避免已完成的 `gui_XXXXXX` 出现在「继续未完成任务」入口。

#### Scenario: 编辑期间与关闭
- **WHEN** 编辑模式下的任意数据变更触发自动保存调度
- **THEN** 调度与立即写草稿入口均直接返回；关闭窗口也不写草稿

## MODIFIED Requirements

### Requirement: 任务完成流程
编辑已完成任务时的结束动作改为「保存修改」，不再询问"是否开始一个新的标注任务"。

- 原行为：terminate/answer_terminate 确认后保存并询问是否新建任务。
- 新行为：编辑模式下确认任意动作只落当前步；仅「保存修改」触发校验、写回与返回主菜单。

## REMOVED Requirements

无。
