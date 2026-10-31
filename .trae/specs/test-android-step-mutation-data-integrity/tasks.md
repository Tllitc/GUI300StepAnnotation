# Tasks

- [x] Task 1: 搭建安卓端离线 pytest 测试基础设施（`安卓端/tests/`）
  - [x] SubTask 1.1: 新建 `安卓端/tests/conftest.py`：导入 PyQt5 前设置 `QT_QPA_PLATFORM=offscreen`，提供 session 级 `QApplication`；确认 pytest/PyQt5 可用（缺失则安装）；不修改生产代码
  - [x] SubTask 1.2: 实现 `editor_factory` 夹具：`tmp_path` 下构造 `DataManager(base_dir=tmp_path)` 与 `AnnotationEditor(data_manager=..., app_name=..., task_instruction=..., screen_info={"platform":"Android","system":"","screen_size":[1080,2400]}, app_type=..., serial=None, init_window=None)`，调用 `initialize_task` 建立 gui 目录；夹具负责用例结束时 `close()`/`deleteLater()` 清理
  - [x] SubTask 1.3: 实现桩截图器 `FakeAndroidScreenCapture`：`capture(output_path)` 生成可区分 PNG（不同底色 + 文件名文字，QPixmap 绘制）写至 output_path 并返回 `(True, output_path)`；支持配置"下一次返回 (False, None)"；monkeypatch 替换 editor 的 `screen_capture`
  - [x] SubTask 1.4: 实现异步截图驱动助手：`capture_and_wait(editor)` 触发 `take_screenshot` 后用 `QTest.qWait` 分片推进事件循环，等待 `_screenshot_in_progress` 复位（含 50ms singleShot + 后台线程信号 + 800ms 冷却）；`fill_valid_step(editor, action="click")`（设置 `_current_vertices` + 填坐标必填项使 `_validate_step` 通过）；`confirm_n_steps(editor, n)` 标准走步
  - [x] SubTask 1.5: 实现模态框自动应答夹具：monkeypatch `annotation_editor` 命名空间内 `QMessageBox.question`（删除/撤销/完成确认按用例返回 Yes/No）、`warning/information`（记录并返回）、`QInputDialog.getText`（返回预设指令）；`ValidationFailDialog.exec_` 自动关闭
  - [x] SubTask 1.6: 冒烟测试 `test_smoke.py`：初始化 → 走 3 步 → answer_terminate 结束 → 断言 `gui_000001.json`/`_coords.json`/3 张截图产出且可解析

- [x] Task 2: 实现不变量校验工具（`安卓端/tests/invariants.py`）
  - [x] SubTask 2.1: `assert_model(editor)`：INV-1（steps 连续、screenshot 非空）
  - [x] SubTask 2.2: `assert_files(editor, allow_orphans=False)`：INV-2/3/4/5（引用存在、图步单射、无孤儿——孤儿判定把 `rounds` 引用计入可达集、命名正则）
  - [x] SubTask 2.3: `assert_draft(editor)`：主动 `_write_draft_now()` 后 `json.load` 解析，校验 INV-6（条数/顺序/引用/current_step_index）
  - [x] SubTask 2.4: `assert_sidebar(editor)`：INV-8（条目数==len(steps_data)、无重复文件名、缩略图与步骤文件一致）
  - [x] SubTask 2.5: `assert_transient(editor)`：INV-9（`_screenshot_in_progress`/`_insert_after_index`/`_swipe_measuring`/`_scroll_measuring` 复位）
  - [x] SubTask 2.6: `assert_final_json(gui_dir, gui_number)`：INV-7（trajectory step 连续、screenshot 全存在且按业务顺序、coords 与 trajectory 对齐）
  - [x] SubTask 2.7: `assert_all(editor)` 组合入口 + `assert_resume_consistent(editor)`（INV-10：重建编辑器 load_from_draft 后全套断言）

- [x] Task 3: 撤销操作测试组（`undo_step`）—— tests/test_undo.py，9 用例，4 passed + 5 xfailed
  - [x] SubTask 3.1: 撤销末尾已确认步（3→2）：文件已删、侧栏 2 条、草稿 2 步（因 DA-2 缓存残留 xfail，待修复转绿）
  - [x] SubTask 3.2: 撤销后立即重新截图（DA-2）：**已复现**——侧栏命中旧缓存显示旧图（xfail 登记）
  - [x] SubTask 3.3: 停在中间步按 Ctrl+Z（DA-3）：**已复现**——固定弹末步，中间步未确认表单编辑静默丢失（xfail 登记）
  - [x] SubTask 3.4: 已截图未确认新步时点撤销（DA-4）：**已验证非缺陷**——两文件同删符合预期，无孤儿/无悬空
  - [x] SubTask 3.5: swipe 测量中撤销（DA-1）：**已验证非缺陷**——undo 经 `_reset_for_next_step`→`_clear_inputs`（L2399-2400）间接复位；已固化回归用例
  - [x] SubTask 3.6: scroll 测量中撤销（DA-1）：**已验证非缺陷**——同上间接复位
  - [x] SubTask 3.7: 逐步撤销至空（DA-5）：**已复现**——空现场 `_write_draft_now` 提前返回且旧草稿不删，`load_from_draft` 复活已删步骤（xfail 登记）
  - [x] SubTask 3.8: 截图在途时点撤销：过期结果按 seq/capture_step 校验丢弃、锁复位无死锁（通过）
  - [x] SubTask 3.9: 撤销后结束任务：最终 JSON/coords 引用连续无缺失（通过）

- [x] Task 4: 删除当前步骤测试组（`delete_current_step`）—— tests/test_delete.py，11 用例，9 passed + 2 xfailed
  - [x] SubTask 4.1: 5 步删第 3 步：后续步前移、各步截图/vertices/action_data 不串（通过）
  - [x] SubTask 4.2: 删除首步/末步/唯一一步：`current_step` 停留位置正确、引用连续（通过）
  - [x] SubTask 4.3: 删空全部步骤：回初始空白态、草稿同步、可重新截图走步（通过）
  - [x] SubTask 4.4: 截图在途（50ms 窗口内）删除中间步（DA-7）：删前序步被正确丢弃；**删当前步已复现**（xfail 登记）
  - [x] SubTask 4.5: ADB 后台线程在途时删除当前步（DA-7）：**已复现**——下标前移同值穿透 L1694 校验，过期截图写入移位步骤（串图）且原步骤文件成孤儿（xfail 登记）
  - [x] SubTask 4.6: 删除 scroll 测量中的步骤（DA-8）：**已验证非缺陷**——测量态复位、随后截图正常
  - [x] SubTask 4.7: 删除 swipe 测量中的步骤（DA-8）：**已验证非缺陷**
  - [x] SubTask 4.8: answer 收尾一轮后删除（DA-6）：**已验证非缺陷**——历史 rounds 引用文件完好（序号扫盘唯一不碰撞）
  - [x] SubTask 4.9: 删除确认框选 No：数据与磁盘原样（通过）
  - [x] SubTask 4.10: 删除后结束任务：最终 JSON/coords 引用连续无缺失（通过）

- [x] Task 5: 在当前步后插入测试组（`start_insert_capture`）—— tests/test_insert.py，11 用例，9 passed + 2 xfailed
  - [x] SubTask 5.1: 第 1 步后插入并确认（3→4）：业务顺序 1-新-2-3，引用各自正确（通过）
  - [x] SubTask 5.2: 插入确认后 `current_step` 跳末尾语义验证：侧栏 4 条目无重复、随后追加不乱序（通过）
  - [x] SubTask 5.3: 插入后删除新步/删除相邻步：模型、磁盘、侧栏、草稿一致（通过）
  - [x] SubTask 5.4: 插入截图在途期间删除锚点步：**已复现**（与 DA-7 同根因）——过期结果按失效下标插入到错误位置（xfail 登记）
  - [x] SubTask 5.5: 插入截图在途期间撤销/导航切换：结果被正确丢弃（通过）；顺带复现 DA-2 缓存残留（xfail 登记，与 3.2 同根因）
  - [x] SubTask 5.6: 桩件返回失败：`_insert_after_index` 复位、锁释放，后续普通截图走追加分支（通过）
  - [x] SubTask 5.7: scroll/swipe 测量中点插入：安全降级，插入分支 `_clear_inputs` 复位测量态，无半插入残留（通过）
  - [x] SubTask 5.8: 插入后草稿落盘 + load_from_draft 续采 + 再次插入/删除（INV-10 通过）

- [x] Task 6: 重新截图测试组（历史步 `take_screenshot` 覆盖）—— tests/test_recapture.py，5 用例，3 passed + 2 xfailed
  - [x] SubTask 6.1: 中间步重新截图：引用指向新文件（同名序号复用、内容已更新）、其余步不变、无孤儿（模型/文件过；侧栏 INV-8 因 DA-2 同源缺陷 xfail）
  - [x] SubTask 6.2: 重新截图后序号复用同名：**已复现**——重截分支（L1764-1772）未失效侧栏 `_thumb_cache`，侧栏显示旧图（画布正常）（xfail 登记，DA-2 扩展面）
  - [x] SubTask 6.3: 截图在途切换步骤（`capture_step != current_step`）：结果丢弃、原步引用不变、锁复位（通过）
  - [x] SubTask 6.4: 桩件失败：旧文件保留、步骤引用不变、锁复位（通过）
  - [x] SubTask 6.5: 重新截图后立即结束任务：最终 JSON 指向新文件且存在（通过）

- [x] Task 7: 草稿/多轮/续采交叉测试组 —— tests/test_draft_rounds.py，6 用例，4 passed + 2 xfailed
  - [x] SubTask 7.1: 删除/插入/撤销后立即 `_write_draft_now()`：draft 与内存逐条一致（通过）
  - [x] SubTask 7.2: answer 收尾一轮 → 新一轮删除/插入/撤销：历史 rounds 引用文件不被删、最终 JSON round/step 归属正确（通过）
  - [x] SubTask 7.3: 轮次边界（`_current_round_saved=True`）时撤销/删除：undo/delete 均无副作用，可达性仅经续采（通过，行为明确）
  - [x] SubTask 7.4: 高频交替变更序列：首轮即确定性复现 DA-2（xfail 登记，待修复转绿）
  - [x] SubTask 7.5: 续采完整链路：走步+删除+插入+撤销 → 写草稿 → load_from_draft → 继续变更 → 结束，INV-1~10 全绿（通过）

- [x] Task 8: 缺陷确认与最小修复（TDD：失败用例已在 Task 3~7 以 xfail(strict) 登记，修复后移除 xfail 转绿）
  - [x] SubTask 8.1: DA-1 **已验证非缺陷**（undo 经 `_clear_inputs` 间接复位测量态），无需修复，回归用例已固化于 test_undo.py
  - [x] SubTask 8.2: 修复 DA-2（已复现，影响面最大）：(a) `undo_step` 删除文件后同步调 `sidebar.remove_thumb_cache_by_filename`；(b) `_on_screenshot_finished` 截图保存成功（重截/覆盖分支 L1764-1773）后按文件名失效侧栏缩略图缓存
  - [x] SubTask 8.3: 处置 DA-3（已复现）：`undo_step` 开头先 `_save_current_to_steps()` 保存当前表单编辑，消除静默丢失；DA-4 已定性符合预期，无需改动
  - [x] SubTask 8.4: 修复 DA-7（已复现，串图根因）：`delete_current_step`/`undo_step` 在 `_screenshot_in_progress` 时拦截并提示"截图进行中"，覆盖 SubTask 4.4b/4.5/5.4 场景；同步更新受影响用例期望（test_delete 4.4a/4.4b/4.5、test_insert 5.4/5.5、test_undo 3.8）
  - [x] SubTask 8.5: DA-6 **已验证非缺陷**（序号扫盘唯一，跨轮不碰撞），无需修复，回归用例已固化于 test_delete.py 4.8
  - [x] SubTask 8.6: 锚点失效问题（SubTask 5.4/5.5）与 DA-7 同根因，由 8.4 拦截方案覆盖
  - [x] SubTask 8.7: 修复 DA-5（已复现）：`_write_draft_now` 在 steps_data 与 rounds 皆空且存在旧草稿时删除草稿文件（`data_manager.delete_draft`），防止续采复活已删步骤
  - [x] SubTask 8.8: 顺手修复测试基础设施缺陷：conftest 的 FakeInputDialog 补 `x()`/`y()` 方法（`_start_new_round` 调用 `dialog.move` 必需），并移除 test_delete.py/test_draft_rounds.py 中的本地二次补丁

- [x] Task 9: 全量回归与收尾
  - [x] SubTask 9.1: 全量 `python -m pytest tests -q`（offscreen）43 passed / 0 xfail，累计 4 次全绿（修复代理 2 次 + 主协调复核 2 次），无 flaky
  - [x] SubTask 9.2: 核对修复未改变最终 JSON/coords 字段契约——修复仅涉 undo/delete 拦截、缩略图缓存失效、空现场删草稿，不触碰 `_save_all_rounds_to_file`/`_save_current_round_to_list` 写盘路径（代码复核确认）
  - [x] SubTask 9.3: 确认未改动桌面端（根 tests/）、`ios端/`、`macos端/` 任何文件（mtime 复核：ios端 改动均早于本任务窗口，属先前 spec；macos端 无改动）

# Task Dependencies

- Task 2 依赖 Task 1
- Task 3/4/5/6/7 依赖 Task 1、Task 2；五组互相独立，可并行委派子代理
- Task 8 依赖 Task 3~7 的复现结论（按 DA-x 实际是否复现决定修复项）
- Task 9 依赖 Task 8
