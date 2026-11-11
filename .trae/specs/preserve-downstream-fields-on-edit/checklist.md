# Checklist

## Windows / macOS
- [x] 编辑已完成 JSON 并保存后，原步骤非空 `CoT` 保持原值不被清空
- [x] 编辑已完成 JSON 并保存后，`observation.active_window`、`observation.ui_tree_segment` 保持原值
- [x] 动作中的 `element`、`status` 在未被编辑器显式修改时保持原值
- [x] 原步骤存在而新步骤字典缺失的未知键在保存后仍然存在且值不变
- [x] 草稿恢复后编辑某步并确认，触发草稿写入/落轮，受保护字段不被 `get_data()` 空串覆盖
- [x] 编辑器实际采集的字段（动作类型、坐标、intent、action 参数）保存后为新值
- [x] 终止类动作编辑后仍满足 `element == ""`、`status == "success"`
- [x] Windows 与 macOS 同名函数行为一致

## iOS / 安卓
- [x] `save_edited_round` 产出的新 trajectory 中 `CoT`、`active_window` 等于原步骤值，不再出现硬编码空串覆盖
- [x] `ui_tree_segment` 在原步骤非空时保留原值
- [x] 合并函数对嵌套 `observation` 按字段级"非空覆盖"处理，原步骤未知键保留
- [x] 草稿序列化（`_serialize_step` / `_write_draft_now`）不丢失条目携带的受保护字段；无字段时仍输出空串默认值
- [x] 落轮（`_save_current_round_to_list`）保留受保护字段
- [x] 新建步骤（本身无下游字段）输出结构与现状一致，不引入额外键
- [x] iOS 与安卓双端行为一致

## 回归验证
- [x] 四端 `tests/` 新增/扩展用例全部通过：已完成任务编辑、草稿续采编辑两个场景均覆盖非空下游字段保留
- [x] 安卓端既有 `test_edit_completed.py`（含 CoT 保留断言）仍通过（18 passed）
- [x] Windows 端 `test_data_integrity_defects.py`、`test_step_mutation_safety.py` 等防污染测试无回归（全量 102 passed）
- [x] 四端全量测试套件通过，无新增失败：Windows 102 / macOS 48 / iOS 132 / 安卓 137，合计 419 passed