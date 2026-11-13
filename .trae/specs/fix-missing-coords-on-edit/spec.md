# 修复缺失 coords.json 数据集编辑时误报与错乱再生成 Spec

## Why
四端采标工具编辑已完成数据集时，部分数据集不含 coords.json。现有实现把「文件缺失」当作「数据不一致」：打开时逐步弹出「coords 与坐标值不一致」错误告警；保存时又用内存中被编辑轮重建 coords 写盘，生成只含被编辑轮少数条目的部分 coords.json，错乱数据集。用户已拍板写回策略：**数据集没有 coords.json 就不生成 coords.json**——无条件成立，即使用户新拉框（拉框只更新最终 JSON 的 coordinate）。

## What Changes
- 载入（`load_from_completed_json`）：按 `gui_{num}_coords.json` 文件实际存在性判定；缺失为合法态，打开时仅一条信息性提示弹窗，不再注册 absent 问题、不弹逐步告警、不追加状态栏警告；坐标步按最终 JSON 显示 coordinate（无拉框预览），允许重新拉框。
- 保存（`save_edited_round`，含 silent=True 关闭写回）：源数据集缺 coords.json → 无条件跳过 coords 写盘；最终 JSON 照常写（instruction/trajectory 更新、.bak 备份等不变）。
- `_original_coords_exist` 语义由「载入条目非空」改为「coords 文件在盘上存在」（存在但空文件仍算存在，B41 对已有文件行为不变），四端对齐。
- 四端 tests/test_edit_completed.py 各新增缺失 coords 回归用例。
- 不变：含 coords.json 数据集的继承/审计/round 注入/文件格式；正常采集/完成/草稿流程；入口按钮；`data_manager.load_coords_from_dir`（缺失时已返回 ([], None) 不报错）。

## Impact
- Affected specs: edit-completed-datasets（新增缺失 coords 合法分支与写回守卫）、preserve-downstream-fields-on-edit（行为不变，仅回归）
- Affected code:
  - Windows（根目录）：annotation_editor.py — load_from_completed_json（L3471-3630，其中 L3511 语义、L3582-3595 逐步告警、L3616-3619 状态栏）、save_edited_round（L3777-3921，其中 L3886-3901 写盘守卫）
  - macos端：annotation_editor.py — load_from_completed_json（约 L3577-3705）、save_edited_round（约 L3933-3995）
  - ios端：annotation_editor.py — load_from_completed_json（约 L3266-3400）、save_edited_round（L3482 起，写盘 L3661-3676，_build_coords_entry L3842-3871）
  - 安卓端：annotation_editor.py — load_from_completed_json（约 L3930-4070）、save_edited_round（L4090 起，重建 L4170-4216，写盘 L4260-4275）
  - 四端 tests/test_edit_completed.py、tests/helpers.py（按需补充缺失 coords 数据集构造与弹窗断言）

## ADDED Requirements
### Requirement: 缺失 coords.json 为合法数据集态
The system SHALL 将不含 coords.json 的已完成数据集视为合法可编辑：打开时仅显示一条信息性提示弹窗（内容须说明：数据集不含 coords.json，编辑只更新最终 JSON、不会生成 coords.json，拉框仅更新 coordinate），SHALL NOT 注册 absent/mismatch 问题、SHALL NOT 弹逐步告警弹窗、SHALL NOT 追加状态栏警告。

#### Scenario: 打开缺失 coords 的多轮数据集
- **WHEN** 用户打开 gui 目录不含 gui_{num}_coords.json 的多轮已完成数据集
- **THEN** 仅一条信息性提示，无逐步 mismatch 告警；坐标步按最终 JSON 显示 coordinate、无拉框预览，且允许重新拉框

### Requirement: 缺失时无条件不生成 coords.json
The system SHALL 在源数据集缺 coords.json 时，save_edited_round（含 silent=True）无条件跳过 coords 写盘，不得进入「flat_coords 非空即写盘」分支；最终 JSON SHALL 照常写入。

#### Scenario: 仅改文本后保存
- **WHEN** 用户仅修改文本字段并保存
- **THEN** 最终 JSON 更新，gui 目录不生成 coords.json

#### Scenario: 新拉框后保存
- **WHEN** 用户对坐标步新拉框并保存
- **THEN** 最终 JSON 对应步 coordinate 按新框更新，仍不生成 coords.json

#### Scenario: 静默关闭写回
- **WHEN** 关闭编辑窗口触发 silent=True 写回
- **THEN** 最终 JSON 照常写入，不生成 coords.json

## MODIFIED Requirements
### Requirement: _original_coords_exist 判定语义
The system SHALL 以 coords 文件在盘上的实际存在性判定 `_original_coords_exist`，而非载入条目是否非空；存在但内容为空的文件算存在。四端 SHALL 同语义。

#### Scenario: 存在但空的 coords 文件
- **WHEN** 数据集 coords.json 存在但内容为空
- **THEN** 按「存在」处理：不弹缺失提示；写回收集 0 条时告警并跳过写入以保留原文件（B41 不变）

### Requirement: 已完成数据集编辑写回守卫（B41 扩展缺失分支）
The system SHALL 在编辑写回时先按源 coords 文件存在性分支：缺失 → 无条件跳过 coords 写入；存在 → 保持现行为：审计（_audit_coord_consistency）不过拒绝写回、条目按分组下标注入 round、flat_coords 非空写盘、收集 0 条告警跳过（B41）、各端文件格式不变（Windows/macOS 纯数组；iOS 条目带 _version 3.1；安卓 {"version":"3.0","coords":[...]}）。

#### Scenario: 编辑含 coords.json 的数据集
- **WHEN** 用户编辑含 coords.json 的数据集并保存
- **THEN** 继承、审计、round 注入、格式行为与改动前完全一致，既有测试全绿

## REMOVED Requirements
### Requirement: 缺失 coords 触发的逐步 absent 告警
**Reason**: 文件缺失是合法数据集态而非数据缺陷；旧实现缺失时把每个坐标步判为 absent，逐步弹「coords 与坐标值不一致」弹窗并追加状态栏，构成误报。
**Migration**: 以单条信息性提示弹窗替代（见 ADDED）。文件存在但条目缺失场景的 absent/mismatch 判定与告警逻辑保留不变。