# 修复安卓/iOS 端"缺项、待完善"校验失效 Spec

## Why

安卓端与 iOS 端采标工具的"必填项缺项/待完善"功能系统性失效：数据构建层把用户未填写的输入静默补成合法默认值（`[0,0]`/`0`/`1.0`、`buttons` 恒写），而数据态校验又以"键存在/数值有效"判缺，导致缺项被"洗白"；缓存失效只在步数长度变化时触发，原地编辑、导航离步、重截图覆盖等路径不重算；安卓端整体缺失输入联动；正在采集的未确认新步完全不纳管。最终表现为侧栏"⚠ 缺项"标记不出现/不消失、看板"待完善 N / 缺填项：N"计数错误、结束任务前的全量校验拦截对话框对脏数据放行。

## What Changes

- **数据保真（两端，核心修复）**：`_build_action_data` 对用户缺失/非法的输入字段**整键省略**（不写 `[0,0]`/`0`/`1.0` 默认值）；`buttons` 仅在确有有效选择时写入；不再把解析失败伪装成合法值。**BREAKING**（内部 JSON 形态：缺字段不再出现默认占位值；已确认该键省略对 coords 导出与表单回填安全，下游均以 `"key" in dict`/isinstance 守卫）。
- **统一校验口径（两端）**：以数据态 `validate_step_at` 为唯一缺项判定来源，支持"live 快照"模式（读取当前未保存表单）与"历史数据"模式；历史步判定统一为"键存在 **且** 值为有限数/四点均有限"；补齐 `system_button`、截图缺失、swipe vertices 四点坐标的判定；live 模式校验数值可解析性（拒绝 `abc`/NaN/Inf）。
- **安卓端补输入联动**：新增 300ms 防抖校验 QTimer（对齐 iOS 已有实现），连接全部参数输入控件（意图/文本/时间/坐标/像素/动作下拉/系统按钮下拉）；用户补填后侧栏标记与看板计数实时更新。
- **iOS 端补信号与守卫修复**：防抖信号补连 `button_combo`；修正 `_on_validation_debounced` 中 `current_step < len(steps_data)` 守卫，使未确认的当前编辑步（`current_step == len`）也能被校验并计入看板。
- **缓存失效全覆盖（两端）**：所有"无校验门落表"出口（上一步/下一步/侧栏跳转/草稿定时落表/结束落表/重截图覆盖/删除/插入）保存后必须失效并重算对应下标的缺项缓存，**不再仅以缓存长度与步数相等作为跳过全量重算的条件**；等长原地编辑也要重算当前下标。
- **未确认新步纳管（两端）**：看板"待完善/缺填项"计数与结束前校验必须包含正在采集、尚未点"确认"的当前步（以 live 快照校验）。
- **重截图覆盖（两端）**：覆盖截图后清除与旧图绑定的拉框坐标/vertices，重算缺项、刷新侧栏并排草稿，防止旧坐标残留洗白缺项。
- **截图丢失恢复（iOS）**：草稿/历史步截图文件缺失时，不再把动作字段照常恢复为可编辑态，避免 is_live 失效、编辑静默丢弃。
- **文案与小 bug（两端）**：`answer_terminate` 在结束校验对话框与动作表中显示准确名称（安卓动作表 146 行括注英文误写为 `answer`）；iOS terminate 动作自动填入的"任务完成"意图在切走动作后恢复，不污染他步。
- **导航离步策略（产品口径）**：采用"**允许离开但准确标记，结束时强制拦截**"——上一步/下一步/侧栏跳转遇到缺项不弹框阻止，但缺项必须被保存、标记并计入看板；仅"确认当前步"与"结束任务"两个出口弹框拦截。与现有草稿式工作流一致，不新增阻断式弹窗。
- **测试**：两端 pytest 补充负向用例（wait 缺时间、scroll 缺 pixels、swipe 缺终点/vertices、click 缺坐标、非法数字、未确认新步计数、补填后标记消失、重截图清坐标、system_button、截图丢失）。

## Impact

- Affected specs: 步骤缺项校验、侧栏步骤标记、进度看板计数、结束任务校验拦截、草稿自动保存/断点恢复、截图采集与重截图、多轮次切轮。
- Affected code:
  - `安卓端/annotation_editor.py`：`_build_action_data`、`_read_coordinate`/`_parse_number`、`_validate_step`、`validate_step_at`、`_missing_cache` 全部重置点、`go_previous`/`go_next`/`jump_to_step`/`confirm_step`/`_save_current_to_steps`/`_collect_step_data`、截图成功回调（常规覆盖分支）、Sidebar `refresh_step_item`/`refresh_dashboard`、`_finish_task`、动作表文案、新增 validation_timer 与信号接线。
  - `ios端/annotation_editor.py`：`_build_action_data`、`_build_coords_entry`（兼容性确认）、`validate_step_at`、`_step_snapshot`/`_ui_has_value`、`_on_validation_debounced`、`_connect_editor_validation_signals`、`_restore_step_to_ui`（截图丢失分支）、截图覆盖回调、`display_step`/`go_previous`/`go_next`/`jump_to_step`/`delete_current_step`/`_save_current_to_steps`、Sidebar 计数、`_finish_task`、on_action_changed 意图粘连。
  - `安卓端/tests/`、`ios端/tests/`：新增负向测试文件/用例；不得违反 invariants.py 的 INV-1~INV-10（注意 helpers 依赖 system_button 默认有值的既有用例，需按新口径同步夹具）。
  - 数据文件 `gui_XXXXXX.json` / `gui_XXXXXX_coords.json` / `gui_XXXXXX_draft.json`：缺失字段省略；需验证旧草稿（含占位默认值的历史数据）打开后不崩溃——旧数据中的 `[0,0]`/`0`/`1.0` 会被判为"已填合法值"，维持其原有行为（不追溯判缺）。

## ADDED Requirements

### Requirement: 输入防抖实时校验（安卓端）

安卓端 SHALL 在任一步骤参数输入控件（意图、输入文本、时间、坐标 x/y、第二坐标、滑动像素、动作选择、系统按钮选择）值变化后，以约 300ms 防抖重新校验当前步骤，并实时刷新该步骤侧栏缺项标记与看板"待完善"计数。

#### Scenario: 补填后缺项标记实时消失
- **WHEN** 用户在当前步把 wait 动作的时间留空时，侧栏该步显示"⚠ 缺项"且看板待完善计数包含该步
- **AND** 用户在时间框输入合法数字并停留 300ms
- **THEN** 侧栏该步缺项标记消失，看板待完善计数减 1，无需点击"确认"或切换步骤

#### Scenario: 非法数字不判为已填
- **WHEN** 用户在时间/坐标/像素框输入 `abc` 或其它不可解析内容
- **THEN** 该项持续判为缺项并给出原因，防抖校验不抛异常

### Requirement: 未确认当前编辑步纳入缺项统计（两端）

系统 SHALL 对正在采集、尚未点击"确认/下一步确认"的当前步骤（`current_step == len(steps_data)`）以表单实时快照进行缺项校验，其结果计入侧栏/看板与结束前校验。

#### Scenario: 新步未确认即看到缺项
- **WHEN** 用户截图后选择了 wait 动作但尚未填写时间，也未点确认
- **THEN** 看板"待完善/缺填项"计数包含当前编辑步
- **AND** 用户直接点"结束任务"时，该步出现在 ValidationFailDialog 列表中并被拦截

### Requirement: system_button 必填校验（两端）

系统 SHALL 将 system_button 动作的按钮选择纳入缺项判定（live 读控件值、历史步读 `buttons` 有效成员）；iOS 端系统按钮下拉变化 SHALL 接入防抖校验。

#### Scenario: 系统按钮未选择
- **WHEN** 步骤动作为 system_button 且无有效按钮选中
- **THEN** 该步判缺；选中有效按钮后缺项消除

### Requirement: 重截图覆盖清除旧坐标并重算（两端）

对已存在步骤重新截图覆盖时，系统 SHALL 作废与旧截图绑定的拉框坐标/vertices 数据，重算该步缺项、刷新侧栏缩略图与标记，并触发草稿保存。

#### Scenario: 旧坐标不洗白新截图缺项
- **GIVEN** 一个 swipe 步曾在旧图上拉过框
- **WHEN** 用户对该步重新截图覆盖
- **THEN** 旧 vertices/坐标被清除，该步按新截图状态重新判缺，草稿同步写入无旧坐标的数据

## MODIFIED Requirements

### Requirement: 步骤动作数据构建保真

构建步骤 action_data 时，系统 SHALL 仅写入用户实际提供且可解析的字段：坐标类字段解析失败或控件留空时省略该键（不得写 `[0,0]`），滑动终点缺失时省略，scroll pixels 缺失/非法时省略，wait/time 缺失时省略（不得写 `1.0`/默认时长），`buttons` 仅在存在有效选择时写入。answer_terminate 在落盘时仍按既有协议映射为 `answer` 动作名（不变），但其在 UI 与结束校验对话框中的中文名 SHALL 显示为可区分的"回答并结束"。

#### Scenario: 未填时间的 wait 步骤保留缺项
- **WHEN** 用户添加 wait 步骤但不填写时间并离开该步
- **THEN** 落盘 action_data 中不含 time 键
- **AND** 该步在结束任务全量校验中被判缺并拦截，不会以 1.0 秒默认值通过

#### Scenario: 未拉框的 click 步骤
- **WHEN** 用户选择 click 但未在截图上拉框/填坐标
- **THEN** action_data 中不含 coordinate 键，该步判缺；coords JSON 导出不包含该坐标条目且不报错

#### Scenario: 旧版草稿兼容
- **GIVEN** 一份历史草稿/JSON，其 wait 步骤含 `"time": 1.0`、click 含 `"coordinate": [0,0]`
- **WHEN** 在新版工具中打开
- **THEN** 正常加载不崩溃，这些字段按"已提供的值"参与校验（不因本次修复追溯判缺）

### Requirement: 统一的缺项校验判定

系统 SHALL 以单一 `validate_step_at(index)` 作为侧栏标记、看板计数、确认拦截、结束拦截的共同判定来源，支持 live（当前表单快照）与历史（steps_data 数据）两种来源，并对两端动作集合给出一致判定：坐标动作（click/long_press/type；iOS 另含 scroll 相关坐标）需有可解析有限坐标；swipe/drag（安卓 START_END_ACTIONS）需有起点、终点且 vertices 四点均为有限数；scroll 需有 pixels 有限整数（及平台要求的坐标）；文本动作需非空文本；time 动作需有可解析有限时间；system_button 需有有效按钮；每步需关联有效截图（live 允许当前截图状态）。表单态 `_validate_step`（安卓）SHALL 复用或对齐该判定，消除"确认被拦、导航离开后结束却放行"的口径分歧。

#### Scenario: 同一表单两种出口结论一致
- **WHEN** 一个缺时间的 wait 步在表单上点击"确认"会被拦截
- **THEN** 该步通过任意导航离开后再点"结束任务"，同样出现在拦截列表中

#### Scenario: swipe vertices 非法
- **WHEN** 历史 swipe 步 vertices 元素个数为 4 但含非有限数（NaN/字符串/None）
- **THEN** 该步判缺，不再仅以 `len(vertices) == 4` 判定通过

### Requirement: 缺项缓存失效覆盖所有数据变更路径

每次步骤数据被写入/覆盖/删除/插入/重截图后，系统 SHALL 失效并重算受影响下标（及下标位移后的全部步骤）的缺项缓存；缓存长度与步数相等不得作为跳过重算的理由。看板计数 SHALL 等于"历史各步缓存缺项数 + 当前未确认编辑步 live 缺项（有实际输入时）"。

#### Scenario: 导航离步后标记准确
- **GIVEN** 当前步缺时间，用户未补填
- **WHEN** 用户点击"上一步"或侧栏跳转至其它步再返回
- **THEN** 该步侧栏显示"⚠ 缺项"，看板计数包含它；补填并再次离开后标记与计数立即更新

#### Scenario: 删除与插入后下标不错位
- **WHEN** 用户删除中间步或在中间插入截图步
- **THEN** 其后所有步骤的缺项标记按新下标重新计算，不错位、不残留他步原因

### Requirement: 结束任务强制全量校验（两端）

点击"结束任务"时，系统 SHALL 先保存当前编辑步，再对全部步骤（含未确认当前步）执行统一缺项校验；存在缺项时弹出 ValidationFailDialog 列出步骤号、动作、缺项原因，并可跳转到目标步骤；无缺项时方可完成并写出最终数据。

#### Scenario: 脏数据不得落最终 JSON
- **WHEN** 任意步骤存在缺坐标/缺时间/缺像素/缺终点/缺按钮/缺截图
- **THEN** 结束被拦截，最终 `gui_XXXXXX.json` 不写出为完成态，用户补齐并复验通过后才能结束

### Requirement: iOS 截图丢失恢复安全

历史步/草稿步骤关联的截图文件无法加载时，系统 SHALL 明确进入"截图缺失"状态（该步判缺并提示重新截图），不得在无截图情况下照常恢复动作字段进入可编辑的 live 态。

#### Scenario: 截图文件被删
- **GIVEN** 草稿中某步截图文件已不存在
- **WHEN** 用户恢复草稿并跳到该步
- **THEN** 该步标记截图缺项，提示重截图，对该步动作字段的编辑不会被静默丢弃

## REMOVED Requirements

### Requirement: 缺失输入静默补默认值

**Reason**: `_build_action_data` 对未填坐标写 `[0,0]`、未填 pixels 写 `0`、未填时间写 `1.0`、buttons 恒写，使数据态校验永远无法识别缺项，是本功能失效的根因。
**Migration**: 改为整键省略；coords 导出与 UI 回填已有 `"key" in dict`/isinstance 守卫适配；旧文件中的显式默认值视为用户数据，不追溯。
