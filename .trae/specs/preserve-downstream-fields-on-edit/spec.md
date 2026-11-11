# 编辑任务时保留下游字段 Spec

## Why
四端（Windows / macOS / iOS / 安卓）标注工具在"编辑未完成（草稿/续采）任务"和"编辑已完成任务"时，编辑器不采集、不展示的下游字段会被重建的步骤字典覆盖为空。这些字段由下游工具链（或预填数据）生成，包括步骤级的 `CoT`、`observation.active_window`、`observation.ui_tree_segment`，以及动作级的 `element`、`status` 等。现有"仅补缺键"的合并策略无法拦住"键存在但值为空串"的覆盖。

## What Changes
- **Windows / macOS（[annotation_editor.py](file:///c:/Project/TC/300step采标工具/annotation_editor.py)、[macos端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/macos端/annotation_editor.py)）**
  - 已完成任务编辑保存（`_save_edited_trajectory` / `_merge_step_with_original`）：对受保护字段采用"新值非空才覆盖、新值为空则保留原值"的合并，且原步骤中存在、新步骤字典缺失的未知键继续保留。
  - 未完成任务（草稿/续采）编辑确认（`confirm_step` 路径）：步骤级 `CoT`、`active_window`、`ui_tree_segment` 及动作级 `element`、`status` 等受保护字段在编辑器未填写时保留原值，不再被 `get_data()` 产出的空串/空值覆盖。
  - 终止类动作（`terminate` / `answer_terminate`）的既有语义保持不变（`element` 固定为空串、`status` 固定 `success` 是业务规则，不属于缺陷）。
- **iOS / 安卓（[ios端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/ios端/annotation_editor.py)、[安卓端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/安卓端/annotation_editor.py)）**
  - 已完成任务编辑保存（`save_edited_round`）：移除 `new_traj` 中对 `CoT: ""`、`active_window: ""` 的硬编码，改为从原 trajectory 步骤读取原值；合并函数对受保护字段采用非空覆盖语义。
  - 草稿序列化（`_serialize_step` / `_write_draft_now`）与落轮（`_save_current_round_to_list`）：当 `steps_data` 条目携带受保护字段时原样持久化，续采/落轮不丢失（无该字段时维持现状的空串默认值）。
- 四端统一"受保护字段"口径：
  - 步骤级：`CoT`、`observation.active_window`、`observation.ui_tree_segment`
  - 动作级（`actions[0]`）：`element`、`status`（终止类动作的业务规则除外）
- 补充四端回归测试：构造带非空下游字段的草稿与已完成 JSON，执行编辑保存后断言字段不被清空。

## Impact
- Affected specs:
  - `fix-step-edit-data-integrity`（已完成任务编辑的数据完整性，本次在其基础上把"补缺键"升级为"非空覆盖"）
  - `edit-completed-datasets`（已完成任务编辑入口）
  - `test-step-mutation-data-integrity`（防跨样本污染，本次改动不得破坏其隔离保证）
  - `sync-mobile-with-windows-fixes`（移动端与 Windows 修复对齐）
- Affected code:
  - [annotation_editor.py](file:///c:/Project/TC/300step采标工具/annotation_editor.py)：`StepEditorWidget.get_data/load_data`、`AnnotationEditor.confirm_step`、`_save_edited_trajectory`、`_merge_step_with_original`、`load_from_draft`
  - [macos端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/macos端/annotation_editor.py)：同名函数
  - [ios端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/ios端/annotation_editor.py)：`save_edited_round`、`_merge_original_missing`、`_serialize_step`、`_save_current_round_to_list`
  - [安卓端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/安卓端/annotation_editor.py)：`save_edited_round`、`_merge_missing_keys`、`_write_draft_now`、`_save_current_round_to_list`
  - 四端 `tests/` 下的编辑完整性测试

## ADDED Requirements

### Requirement: 编辑已完成任务时保留下游字段
系统在保存对已完成 JSON 的编辑时，SHALL 保留原 trajectory 步骤中由下游生成的 `CoT`、`observation.active_window`、`observation.ui_tree_segment`，以及动作中的 `element`、`status` 字段；编辑器重建产生的空值不得覆盖原值，原步骤中存在的其他未知键也不得丢失。

#### Scenario: Windows/macOS 编辑已完成任务保留下游字段
- **WHEN** 用户打开一个含非空 `CoT`、`active_window`、`ui_tree_segment`、`element` 的已完成 JSON，修改某步动作类型或坐标后保存
- **THEN** 输出 JSON 中未被编辑器显式修改的受保护字段保持原值，未知键保持不变，且被编辑字段（动作类型、坐标、intent 等）为新值

#### Scenario: iOS/安卓编辑已完成任务不再硬编码清空
- **WHEN** 用户在移动端编辑含非空 `CoT`、`active_window` 的已完成轮次并保存
- **THEN** 新 trajectory 对应步骤的 `CoT`、`active_window` 与原值一致，不被硬编码空串覆盖

### Requirement: 编辑未完成任务（草稿/续采）时保留下游字段
系统在草稿恢复后编辑并确认步骤、以及重新序列化草稿时，SHALL 保留步骤已携带的受保护下游字段；编辑器未采集这些字段时不得用空值覆盖。

#### Scenario: 草稿步骤被编辑后下游字段保留
- **WHEN** 一个含非空 `CoT`/`active_window`/`element` 的草稿被恢复，用户编辑该步并点击确认，随后触发草稿写入或落轮
- **THEN** 写回的步骤中受保护字段等于编辑前的值，且动作类型/坐标/参数等被编辑内容为新值

#### Scenario: 无下游字段的新步骤维持默认空值
- **WHEN** 用户新建的步骤本身不含受保护字段
- **THEN** 输出维持现状（`CoT`/`active_window`/`ui_tree_segment` 为空串），不引入额外键

### Requirement: 终止类动作业务规则不受影响
系统 SHALL 保持终止类动作的既有强制语义：`terminate` / `answer_terminate` 的动作 `element` 固定为空串、`status` 固定为 `success`。

#### Scenario: 编辑终止步骤
- **WHEN** 用户编辑一个终止类步骤并保存
- **THEN** 该动作仍满足 `element == ""`、`status == "success"`，但步骤级 `CoT`、`active_window`、`ui_tree_segment` 仍按保留规则处理

## MODIFIED Requirements

### Requirement: 步骤合并策略（由"补缺键"升级为"非空覆盖 + 未知键保留"）
四端保存编辑结果时的合并函数（`_merge_step_with_original` / `_merge_original_missing` / `_merge_missing_keys`）SHALL 遵循：
1. 受保护字段：新字典中值为非空（非 `None`、非空串、空 dict/list 视为空）时用新值，否则保留原值；
2. `observation` 为嵌套对象，按字段级别套用同一规则；
3. 受保护字段之外、原步骤存在而新步骤缺失的键，原样保留；
4. 编辑器实际采集的字段（动作类型、坐标、intent、参数等）始终以新值为准。
