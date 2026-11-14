# Checklist

- [x] Windows：动作类型变更后，`_merge_step_with_original` 不再把旧动作已知参数键（coordinate/start_coordinate/text/keys/time/pixels/buttons）补齐进新动作
- [x] macOS：同名函数完成与 Windows 完全对等的修复
- [x] iOS：`_merge_original_missing` 在动作类型变更时跳过已知参数键补齐（含 buttons），其它递归合并行为不变
- [x] Android：`_merge_missing_keys` 完成与 iOS 完全对等的修复（含 keys/buttons）
- [x] 动作变更后，动作内真正未知键（下游/自定义字段）仍保留；步骤级/observation 级未知键与受保护字段（CoT/active_window/ui_tree_segment/element/status）保留规则不变
- [x] 终止类动作 element=""、status="success" 业务规则不变；answer 与 answer_terminate（序列化同为 answer）视为同类型
- [x] 同动作类型编辑的合并行为与修复前完全一致（既有保留类测试全部通过）
- [x] 编辑模式「确认→保存修改」、直接关闭 silent 写回、Windows/macOS 草稿编辑路径产出的动作均无旧动作参数残留；coords 条目与动作类型一致
- [x] 四端各新增回归测试（合并单测 + 端到端），且验证过修复前用例失败（非假绿）
- [x] 四端全量测试套件通过（Windows/macOS/iOS/Android，offscreen），无回归
- [x] 最终 JSON/coords 格式契约未变（字段名、_version、round/step 结构、平台 coords 格式）