# 修复编辑模式下修改动作后遗留旧动作字段（四端） Spec

## Why

四端工具在「编辑已完成任务」等编辑路径中，确认/保存步骤时会把编辑器重建的步骤与原步骤做字段级合并（`preserve-downstream-fields-on-edit` 引入），以保留 CoT、active_window、ui_tree_segment、element/status 及未知下游字段。但合并逻辑对 actions 内部「旧动作有、新动作缺失」的键**无条件深拷贝补齐**。当用户修改某 step 的动作类型后（如 type→left_click），`get_data` / `_build_action_data` 已按新动作正确省略无关参数，合并却把旧动作的参数键（text / keys / time / pixels / coordinate / start_coordinate / buttons）连同旧值复活进交付 JSON，形成「新动作 + 旧动作参数」的脏数据。

## What Changes

- 四端合并函数在**新旧动作类型不同**时，跳过对「已知动作参数键」的缺失补齐；动作类型相同时行为完全不变。
  - Windows [annotation_editor.py](file:///c:/Project/TC/300step采标工具/annotation_editor.py) `_merge_step_with_original`（约 L3741-3746 的 actions[0] 补齐循环）。
  - macOS [macos端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/macos端/annotation_editor.py) 同名函数（约 L3851-3856）。
  - iOS [ios端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/ios端/annotation_editor.py) `_merge_original_missing`（L3485-3520，递归合并的 actions 列表分支注入跳过键集）。
  - Android [安卓端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/安卓端/annotation_editor.py) `_merge_missing_keys`（L3898-3933，同 iOS 方案）。
- 四端统一新增常量 `_ACTION_PARAM_KEYS = {"coordinate", "start_coordinate", "text", "keys", "time", "pixels", "buttons"}`（各端序列化 schema 的并集；跳过某端本就不产生的键无副作用）。
- 动作类型比较使用字典中已序列化的 `action` 值（`answer_terminate` 已序列化为 `answer`，故 answer↔answer_terminate 视为同类型，二者共享 text 参数，行为正确）。
- 保持不变：受保护字段空值回退规则（CoT / observation.active_window / observation.ui_tree_segment / 非终止动作 element、status）、终止类动作 element=""、status="success" 业务规则、步骤级与 observation 级未知键保留、**动作内真正未知键（下游/自定义字段）在动作变更后仍保留**。
- 修复合并函数本身即覆盖全部调用点：Windows/macOS 的 `save_current_step`（编辑模式分支与草稿编辑分支）、`save_current_round`、`_write_draft_now`、`save_edited_round`；iOS/Android 的 `save_edited_round`。
- 四端 `tests/test_edit_completed.py` 新增回归测试（合并函数单测 + 编辑模式端到端），并验证修复前用例会失败（非假绿）。

## Impact

- Affected specs: `preserve-downstream-fields-on-edit`（收窄「未知动作字段保留」边界：已知动作参数键不再跨动作类型保留）、`edit-completed-datasets`（编辑写回数据正确性）
- Affected code:
  - `annotation_editor.py`、`macos端/annotation_editor.py`、`ios端/annotation_editor.py`、`安卓端/annotation_editor.py`
  - `tests/test_edit_completed.py`、`macos端/tests/test_edit_completed.py`、`ios端/tests/test_edit_completed.py`、`安卓端/tests/test_edit_completed.py`

## ADDED Requirements

### Requirement: 动作变更后动作参数干净
合并重建步骤与原步骤时，若新旧动作类型不同，系统 SHALL NOT 把旧动作的已知参数键（`_ACTION_PARAM_KEYS`）补齐进新动作；新动作只包含编辑器按当前动作类型序列化的键、受保护字段与真正未知的下游键。

#### Scenario: 文本类动作改为点击
- **WHEN** 原步骤动作为 type（含 text="你好"），编辑模式下改为 left_click 并确认/保存
- **THEN** 交付 JSON 该步 actions[0] 不含 text 键，coordinate 为新表单值

#### Scenario: 拖拽改为单击
- **WHEN** 原步骤为 left_click_drag（含 start_coordinate），改为 left_click 并保存
- **THEN** actions[0] 不含 start_coordinate，仅含新 coordinate

#### Scenario: 坐标动作改为无坐标动作
- **WHEN** 原步骤为 left_click（含 coordinate），改为 wait / answer / terminate / open_app 等无坐标语义动作并保存
- **THEN** actions[0] 不含 coordinate；wait 含新 time，terminate/answer 保持 element=""、status="success"

#### Scenario: 专项参数键清除
- **WHEN** scroll→left_click（pixels）、key→left_click（keys，Windows/Android）、system_button→click（buttons，iOS/Android）
- **THEN** 对应旧参数键不出现在新动作中

#### Scenario: 未知下游键仍保留
- **WHEN** 原动作含编辑器未管理的自定义键（如 foo="bar"），动作类型变更后保存
- **THEN** foo 键及其值仍被保留（不破坏下游字段保留契约）

#### Scenario: 受保护字段与步骤级字段不受影响
- **WHEN** 动作类型变更且新值为空
- **THEN** CoT、observation.active_window、observation.ui_tree_segment、非终止动作 element/status 仍按既有「空值回退原值」规则保留；步骤级/observation 级未知键保留不变

### Requirement: 全写回路径一致
修复 SHALL 对所有经过合并函数的写回路径生效，且同动作类型编辑行为不变。

#### Scenario: 编辑模式确认后再保存
- **WHEN** 编辑模式下修改动作 → 点「确认」→ 点「保存修改」（或直接关闭窗口触发 silent 写回）
- **THEN** 最终 JSON 中该步动作干净，无旧动作参数键；coords 条目与动作类型一致（非坐标动作无该步条目）

#### Scenario: 草稿/续采编辑路径（Windows/macOS）
- **WHEN** 采标过程中回到已确认步骤修改动作类型并重新确认
- **THEN** 快照、草稿与落轮数据同样不携带旧动作参数键

#### Scenario: 同动作类型编辑不回归
- **WHEN** 动作类型不变，仅修改 intent/text/坐标等
- **THEN** 合并行为与修复前完全一致（缺失键补齐、受保护字段回退均不变），既有保留类测试全部通过

## MODIFIED Requirements

### Requirement: 未暴露字段保留（源自 edit-completed-datasets / preserve-downstream-fields-on-edit）
编辑保存时，原步骤中编辑器未管理的字段 SHALL 继续保留：步骤级未知键、observation 未知键、受保护下游字段（CoT/active_window/ui_tree_segment/element/status）按既有规则合并；动作内**真正未知**的键在动作变更前后均保留。唯一收窄：当新旧动作类型不同时，旧动作的已知参数键（coordinate/start_coordinate/text/keys/time/pixels/buttons）不再补齐进新动作。

#### Scenario: 只改 intent 不动动作
- **WHEN** 用户仅修改某步 intent，动作类型不变
- **THEN** 原动作全部字段（含编辑器未管理键）逐字保留，与修复前一致

## REMOVED Requirements

无。