# Checklist

## 基础设施
- [x] 测试可在 Windows 开发机以 `QT_QPA_PLATFORM=offscreen` 离线运行，`python -m pytest tests -q` 全部通过
- [x] 桩 `ScreenshotCaptureWindow` 回传可区分 PNG（不同底色/编号），后续保存、命名、建步、页序重排、草稿写盘均走真实生产代码
- [x] 350ms `singleShot` 延迟窗口被真实事件循环驱动（`QTest.qWait`），非 sleep 假等待
- [x] 删除/撤销确认框、新轮指令输入框、告警/信息框全部自动应答，测试无人值守
- [x] 每个用例使用独立 `tmp_path`，互不污染，且用例结束正确释放编辑器（无残留窗口/定时器）

## 通用一致性
- [x] 每个变更场景结束后均执行 INV-1/2/3/4/5/9/10 断言
- [x] 每个变更场景后均校验草稿一致（INV-7），且 `load_from_draft` 后一致性保持（INV-11）
- [x] 结束任务的场景均校验最终 JSON 与 coords（INV-8）
- [x] 孤儿判定把 `rounds` 中的引用计入可达集合，未把合法历史图片误判为孤儿

## 撤销
- [x] 撤销末尾已确认步：模型/磁盘/stack/侧栏/草稿全部同步，无非末步语义歧义
- [x] 撤销后重新截图：序号按 max+1 分配且引用唯一，历史引用不受影响
- [x] 非末步触发撤销（DT-9）有确定结论：已复现并修复，或被测试证明不可达并记录原因
- [x] 空步骤撤销与确认选"No"：无副作用（数据与磁盘哈希不变）

## 删除当前步骤
- [x] 删除中间步后：后续步前移，`set_step_number`、`data["step"]`、`observation.screenshot` 与截图引用一致，无串图
- [x] 删除首步/末步/唯一一步：`current_step_index` 合法、stack 页序不变式成立
- [x] 删空全部步骤后草稿被同步（DT-1 已复现并修复，或被证明不影响续采）
- [x] 删除后结束任务：最终 trajectory 连续、截图全部存在、coords 与 trajectory 对齐

## 插入截图
- [x] 中间插入后业务顺序正确、文件名序号与业务顺序解耦属设计允许（NO-3），但 JSON/草稿引用严格按业务顺序
- [x] 插入后 stack 页序不变式成立，侧栏无重复条目（NO-1 已回归验证）
- [x] 插入失败/锚点失效：不建步、不产生文件、`_capture_insert_after` 复位、窗口恢复
- [x] 插入后删除/再次插入：模型、磁盘、侧栏、草稿持续一致

## 重新截图
- [x] 重新截图复用原文件名，磁盘文件数不变，内容已更新，其他步引用不变
- [x] 单框↔双框重新截图后 `selection_type` 归一化口径与新建路径一致（DT-7 已复现并修复，或证明不影响产物）
- [x] 重新截图后的最终 JSON `action` 与 coords `action` 语义一致
- [x] 取消/覆盖失败：原文件与 `steps` 不变、`_capture_in_flight` 复位

## 草稿 / 多轮 / 续采
- [x] 草稿写入后 `json.load` 可解析，`current_steps` 与内存逐项一致，`rect_info` 已序列化为 list
- [x] 轮次边界不产生"rounds 与 current_steps 同轮重复"（DT-2 有结论，`tasks.md` 已注明）
- [x] `reset_for_new_task` 后草稿不残留上一轮 `current_steps`（DT-3 有结论）
- [x] 续采后编辑能进入草稿与最终 JSON（DT-4 已复现并修复，或被证明由其他路径兜底）
- [x] 续采后最终 trajectory 每条含 `step` 字段且等于下标（DT-5 有结论）
- [x] 续采后继续删除/插入/撤销/重截并结束：INV-1~11 全绿

## 修复与回归
- [x] 每项产品代码修复都有对应的失败用例先行（TDD），且用例在修复后转绿
- [x] DT-6（删除被 rounds 引用的截图）有结论，未误删历史轮图片
- [x] DT-8（页序不变式静默失败）有结论：失败时不再静默导致删错页
- [x] `macos端/`、`ios端/`、`安卓端/` 未被修改；样例数据 `test/gui_000001/*` 未被修改
- [x] 最终产物字段契约未被破坏（除补齐 `step` 字段），`gui_XXXXXX.json` / `gui_XXXXXX_coords.json` 结构与本项说明一致
