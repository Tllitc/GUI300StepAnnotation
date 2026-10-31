# Tasks

- [x] Task 1: 搭建无真机 pytest 测试基础设施
  - [x] SubTask 1.1: 新建 `ios端/tests/` 目录与 `conftest.py`：设置 `QT_QPA_PLATFORM=offscreen`，提供 session 级 QApplication；确认环境已安装 pytest/PyQt5（缺失则在 venv 中安装并记录）
  - [x] SubTask 1.2: 实现临时存储夹具：`DataManager` 的 `current_dir` 指向 `tmp_path`；提供创建 `AnnotationEditor`（真实实例，注入 data_manager/screen_info）的工厂夹具
  - [x] SubTask 1.3: 实现桩截图器 `FakeScreenCapture`：记录调用次数；每次 `capture(output_path)` 生成一张可区分的 PNG（如不同底色 + 序号文字，用 QPixmap 绘制保存）写到 output_path 并返回 `(True, output_path)`；支持配置"下一次返回失败"；构造后替换 `editor.screen_capture`
  - [x] SubTask 1.4: 实现编辑器操作助手：`capture_and_wait(editor)`（触发 take_screenshot 后用 `QTest.qWait`/事件处理驱动 50ms QTimer 直至 `_screenshot_in_progress` 复位）、`fill_valid_step(editor, action="click")`（拉框 vertices + 填坐标等必填项使 `_validate_step` 通过）、`confirm_n_steps(editor, n)`（截图→标注→确认的标准走步）
  - [x] SubTask 1.5: 实现模态对话框自动应答夹具：删除/撤销的 QMessageBox.question 自动返回 Yes；QInputDialog.getText 自动返回预设新指令；QMessageBox.warning/information 自动关闭（用 monkeypatch 或 QTimer 预置应答）
  - [x] SubTask 1.6: 冒烟测试：初始化任务 → 走 3 步 → 结束任务，断言产出 JSON/coords/截图，跑通基础设施

- [x] Task 2: 实现数据一致性断言工具（不变量校验器）
  - [x] SubTask 2.1: `assert_model_consistency(editor)`：校验 INV-1/INV-3（steps_data 连续、screenshot 非空、文件→步骤单射）
  - [x] SubTask 2.2: `assert_disk_consistency(editor, allow_orphans=False)`：校验 INV-2/INV-4/INV-5（引用文件存在、无孤儿 png、命名规范）；提供 allow_orphans 选项区分"设计允许的轮次引用"
  - [x] SubTask 2.3: `assert_draft_consistency(editor)`：主动 `_write_draft_now()` 后读取 draft json，校验 INV-6（条数/顺序/引用一致、无 screenshot_filepath、current_step_index 合法）
  - [x] SubTask 2.4: `assert_sidebar_consistency(editor)`：校验 INV-8（`len(item_widgets)==len(steps_data)`、下标一一对应）
  - [x] SubTask 2.5: `assert_final_json_consistency(gui_dir)`：结束任务后校验 INV-7（trajectory.screenshot 全部存在且按业务顺序、coords 条目数/step/round 对齐、引用唯一）
  - [x] SubTask 2.6: `assert_measurement_state_reset(editor)`：校验 INV-9（scroll/swipe/insert/in_progress 标记与 extra 文件已清理）

- [x] Task 3: 删除当前步骤测试组（delete_current_step）
  - [x] SubTask 3.1: 删除中间步（5 步删第 3 步）：模型前移不串图、截图引用各自正确、序号空洞保留 —— INV-1~6
  - [x] SubTask 3.2: 删除首步 / 末步：边界下标、current_step 停留位置、引用连续
  - [x] SubTask 3.3: 删空全部步骤：回初始空白态、可重新截图走步、不残留引用与侧栏条目
  - [x] SubTask 3.4: 删除处于 scroll 测量中的步骤（复现 D-1）：删除前制造 `_scroll_preserve_screenshot=True` + extra 截图；断言删除后状态复位、extra 清理、随后普通截图正确写入当前步
  - [x] SubTask 3.5: 删除处于 swipe 测量中的步骤：测量状态与起点数据复位
  - [x] SubTask 3.6: 删除末尾最大序号步后重新截图：序号复用但引用唯一、无旧引用（覆盖 D-5 删除侧）
  - [x] SubTask 3.7: 删除后草稿落盘 + `load_from_draft` 恢复（INV-10）
  - [x] SubTask 3.8: 删除后结束任务：最终 JSON/coords 引用连续无缺失（INV-7）

- [x] Task 4: 撤销操作测试组（undo_last_step）
  - [x] SubTask 4.1: 撤销末尾已确认步：等同删除的全部一致性断言
  - [x] SubTask 4.2: 回到中间步后撤销：删除的是"当前步"语义验证，后续步正确前移
  - [x] SubTask 4.3: 已截图未确认新步点撤销（复现/定性 D-7）：记录实际行为（拦截或回收）；若产生孤儿截图或状态矛盾，登记为缺陷并给出预期
  - [x] SubTask 4.4: 空步骤撤销：提示且无副作用；取消删除（选 No）后数据原样

- [x] Task 5: 在此步骤后插入截图测试组（start_insert_capture）
  - [x] SubTask 5.1: 第 1 步后插入：业务顺序 [0001,0004,0002,0003]，但 JSON/草稿引用严格按业务顺序、图步一一对应（INV-1/2/3/5/6/7）
  - [x] SubTask 5.2: 插入后确认新步：复现 D-2 —— rebuild 后在末步/中间步确认，断言侧栏不出现重复条目、高亮与点击跳转正确
  - [x] SubTask 5.3: 插入后删除新步 / 删除相邻步：模型、文件、侧栏、草稿一致
  - [x] SubTask 5.4: 插入截图 50ms 延迟窗口内切换步骤（复现 D-3）：编排 QTimer 在 `_do_screenshot` 前调用 display_step/go_previous；断言不串步、不覆盖他步表单
  - [x] SubTask 5.5: 插入截图延迟窗口内删除锚点步（复现 D-3）：断言不向失效锚点插入、不产生越界/孤儿
  - [x] SubTask 5.6: 插入时桩件返回失败：`_capture_insert_after`/`_screenshot_in_progress` 复位，后续普通截图走正常追加分支
  - [x] SubTask 5.7: scroll/swipe 测量中点插入：验证边界（拦截或安全降级），不残留半插入状态
  - [x] SubTask 5.8: 验证插入后 screenshot_cache/画布所图源（D-4），后续重新截图不读到被覆盖的固定临时图
  - [x] SubTask 5.9: 插入后草稿落盘 + 续采恢复 + 续采后再次插入/删除（INV-10）

- [x] Task 6: 重新截图与 scroll extra 序号回收测试组
  - [x] SubTask 6.1: 历史步重新截图：文件名/序号不变、内容更新、steps_data/草稿引用不变、缩略图缓存失效后显示新图
  - [x] SubTask 6.2: scroll 测量完成/取消后 extra 截图清理、随后新截图序号回收场景：引用唯一、无误删（覆盖 D-5 extra 侧）
  - [x] SubTask 6.3: 覆盖截图与多步引用关系：确认覆盖不会影响其他步骤（正常流程下文件单射）

- [x] Task 7: 多轮与草稿交叉测试组
  - [x] SubTask 7.1: answer 收尾一轮 → 新一轮删除/插入/撤销：历史 rounds 引用文件不被删（重点复现/排除 D-8），最终合并 JSON 的 round/step 归属正确
  - [x] SubTask 7.2: answer 时新指令对话框取消：状态符合既有语义且数据不损坏
  - [x] SubTask 7.3: 删除/插入/撤销后立即 `_write_draft_now`（不等防抖）：逐条核对 draft 中截图引用与下标（D-6）
  - [x] SubTask 7.4: 高频交替变更序列（删除→插入→截图→导航重复多轮）：过程中与结束后四类数据收敛一致、无异常
  - [x] SubTask 7.5: 续采完整链路：构造"走步+删除+插入+撤销"序列 → 写草稿 → 新建编辑器 `load_from_draft` → 继续变更 → 结束，校验 INV-1~10

- [x] Task 8: 缺陷确认与最小修复（每个缺陷先有失败测试，再改产品代码）
  - [x] SubTask 8.1: 修复 D-1（若复现）：`delete_current_step` 路径补齐 scroll 测量取消与 extra 清理，与 confirm_step/clear_annotations 对齐
  - [x] SubTask 8.2: 修复 D-2（若复现）：confirm_step 的侧栏增量建项改为"不存在才建"或复用统一刷新，杜绝重复 item
  - [x] SubTask 8.3: 修复 D-3（若复现）：为截图延迟窗口增加导航/删除守卫，或在 `_do_screenshot` 执行时重新校验锚点/当前步有效性
  - [x] SubTask 8.4: 修复 D-4（若复现）：插入后 screenshot_cache 指向 gui_dir 内副本而非固定临时文件
  - [x] SubTask 8.5: 处置 D-7（若确认行为缺陷）：未确认新步撤销时正确回收截图或放开删除，消除孤儿/矛盾提示
  - [x] SubTask 8.6: 修复 D-8（若复现）：删图引用检查扩展到 rounds，避免删除历史轮仍引用的文件
  - [x] SubTask 8.7: D-5/D-6 若测试仅证明安全，则在测试中固化为回归用例；若复现真实错乱则最小修复删除/草稿路径

- [x] Task 9: 全量回归与运行说明
  - [x] SubTask 9.1: 全量 `pytest` 通过（offscreen），确认无 flaky（QTimer 相关用例稳定，必要时改用显式事件驱动而非固定 sleep）
  - [x] SubTask 9.2: 核对修复未改变最终 JSON/coords 格式契约（字段名、_version、round/step 结构与既有样例一致）
  - [x] SubTask 9.3: 用一句话在测试 README/模块 docstring 写明离线运行命令（仅测试运行说明，不写其他文档）

# Task Dependencies

- Task 2 依赖 Task 1（断言工具基于夹具）
- Task 3/4/5/6/7 依赖 Task 1、Task 2；五组互相独立，可并行委派子代理
- Task 8 依赖 Task 3~7 的复现结论（按 D-1…D-8 实际是否复现决定修复项）
- Task 9 依赖 Task 8
