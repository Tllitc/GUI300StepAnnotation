# Tasks

- [x] Task 1: 搭建离线 pytest 测试基础设施（`tests/`）
  - [x] SubTask 1.1: 新建 `tests/conftest.py`：在导入 PyQt5 前设置 `QT_QPA_PLATFORM=offscreen`，提供 session 级 `QApplication`；确认 pytest / pytest-qt / PyQt5 可用（缺失则安装到现有环境并在测试文件顶部说明）；不修改生产代码
  - [x] SubTask 1.2: 实现 `editor_factory` 夹具：在 `tmp_path` 下构造 `DataManager(base_dir=tmp_path)` 与 `AnnotationEditor(...)`，并注入 `data_manager`、`app_name`、`task_instruction`、`screen_info`、`app_type`；夹具负责用例结束时的 `cleanup_resources()` / `close()` / `deleteLater()`
  - [x] SubTask 1.3: 实现 `tests/fakes.py::FakeScreenshotCaptureWindow`：行为等价于真实类的信号契约（`capture_completed` 发出 `original_pixmap, marked_pixmap, rect_info, selection_type`），按用例参数生成"可区分 PNG"（不同底色 + 画上文件名文字），支持 `cancelled` 与"保存失败"两种预设；通过 monkeypatch 替换 `annotation_editor` 模块内的 `ScreenshotCaptureWindow`
  - [x] SubTask 1.4: 实现 `tests/helpers.py` 操作助手：`wait_capture(editor)`（`QTest.qWait` 推进 350ms `singleShot` 并等待 `_capture_in_flight` 复位）、`append_step(editor, ...)`（追加截图 + 填必填项）、`insert_step_after(editor, idx, ...)`、`recapture(editor, ...)`、`delete_current(editor)`、`undo(editor)`、`confirm(editor)`、`finish(editor, action="terminate")`，全部经真实生产方法
  - [x] SubTask 1.5: 实现模态框自动应答夹具：`QMessageBox.question` 按用例返回 Yes/No，`QMessageBox.warning/information/critical` 记录并返回、`QInputDialog.getText` 返回预设文本（monkeypatch 到 `annotation_editor` 模块命名空间）
  - [x] SubTask 1.6: 冒烟测试 `tests/test_smoke.py`：创建任务 → 追加 3 步 → terminate 结束 → 断言 `gui_XXXXXX.json`、`gui_XXXXXX_coords.json`、3 张截图均产出且可解析，跑通基础设施

- [x] Task 2: 实现不变量校验工具（`tests/invariants.py`）
  - [x] SubTask 2.1: `assert_model(editor)`：INV-1（steps 连续、文件名非空、`data.step` / `data.observation.screenshot` 一致）
  - [x] SubTask 2.2: `assert_stack(editor)`：INV-2（`count == len+1`、`widget(i+1) is steps[i]["editor"]`、`current_step_index` 合法）
  - [x] SubTask 2.3: `assert_files(editor, allow_orphans=False)`：INV-3/4/5（引用文件存在、steps 内引用单射、无孤儿 PNG，孤儿判定需把 `rounds` 引用计入可达集合）
  - [x] SubTask 2.4: `assert_naming(editor)`：INV-6（文件名正则、重新截图前后文件名集合不变）
  - [x] SubTask 2.5: `assert_draft(editor, draft_path)`：INV-7（主动 `_write_draft_now()` 后 `json.load` 解析、`current_steps` 条数/顺序/引用一致、`rect_info` 已转 list、`rounds`/`coords_entries` 一致）
  - [x] SubTask 2.6: `assert_final_json(gui_dir, gui_number)`：INV-8（trajectory 的 `step` 连续、`screenshot` 存在、coords 每轮 `step` 落在 trajectory 范围内且 `action` 语义一致）
  - [x] SubTask 2.7: `assert_sidebar(editor)`：INV-9（`len(item_widgets) == len(steps)`、无重复文件名条目、计数标签与模型一致）
  - [x] SubTask 2.8: `assert_transient_reset(editor)`：INV-10（`_capture_in_flight is False`、`_capture_insert_after is None`、窗口可见且 `windowOpacity()==1.0`）

- [x] Task 3: 撤销操作测试组（`undo_last_step`）
  - [x] SubTask 3.1: 撤销末尾已确认步（3 步 → 2 步）：INV-1~10 全绿，文件已删、侧栏 2 条、草稿 2 步
  - [x] SubTask 3.2: 撤销后重新截图：新文件取 max+1、只被新步引用、历史引用不变
  - [x] SubTask 3.3: 当前停在中间步时调用 `undo_last_step`（复现 DT-9）：记录实际行为；若出现"删末步但指示器停在中间步"或 `current_step_index` 越界，断言为缺陷并给出预期（删除当前步或拒绝执行 + 明确提示）
  - [x] SubTask 3.4: 空步骤撤销、确认框选 No：无副作用（`steps`/磁盘/草稿哈希不变）

- [x] Task 4: 删除当前步骤测试组（`delete_current_step`）
  - [x] SubTask 4.1: 5 步删第 3 步：后续步前移、`set_step_number` 与 `data["step"]` 重编号、各步截图引用不串、草稿同步 — INV-1~10
  - [x] SubTask 4.2: 删除首步 / 末步 / 唯一一步：停留位置与 `current_step_index` 正确、stack 不变式成立
  - [x] SubTask 4.3: 逐步删空全部步骤（复现 DT-1）：断言草稿被同步为无当前步骤（`current_steps == []` 或草稿被删除）；随后 `load_from_draft` 不得复活已删步骤
  - [x] SubTask 4.4: 删除后结束任务：最终 JSON trajectory 连续、截图引用全部存在、coords 与 trajectory 对齐
  - [x] SubTask 4.5: 删除确认框选 No：数据与磁盘原样

- [x] Task 5: 插入截图测试组（`start_insert_capture`）
  - [x] SubTask 5.1: 第 1 步后插入（3 步 → 4 步）：业务顺序为 1-新-2-3，新文件名取全局 max+1；stack 页序不变式成立、插入点后重编号、侧栏 4 条无重复 — INV-1~10
  - [x] SubTask 5.2: 插入后删除该新步、以及再插入一步：模型/磁盘/stack/侧栏/草稿持续一致
  - [x] SubTask 5.3: 无步骤或锚点越界时调用插入：不越界、不产生文件、`_capture_insert_after` 复位，随后普通截图走追加
  - [x] SubTask 5.4: 截图保存失败（桩件令 `save_screenshot` 返回 None）：不建步、标志复位、窗口恢复
  - [x] SubTask 5.5: 插入完成后 terminate：最终 JSON 按业务顺序、coords 覆盖插入步（若为坐标类动作）

- [x] Task 6: 重新截图测试组（`recapture_current_step`）
  - [x] SubTask 6.1: 对中间步重新截图：文件名不变、磁盘文件数不变、内容已更新（按像素/哈希区分）、其他步引用不变、草稿引用不变 — INV-1~10
  - [x] SubTask 6.2: 单框 → 双框重新截图（复现 DT-7）：断言 `selection_type` 归一化为 `drag`、编辑器动作自动为 `拖拽`、最终 JSON 的 `action` 与 coords 的 `action` 一致
  - [x] SubTask 6.3: 取消 / 覆盖保存失败：原文件与 `steps` 不变、`_capture_in_flight` 复位
  - [x] SubTask 6.4: 重新截图后立即 terminate：最终 JSON 的 `observation.screenshot` 仍指向原文件名且文件存在

- [x] Task 7: 草稿与多轮交叉测试组
  - [x] SubTask 7.1: 变更后显式 `_write_draft_now()`：逐条核对 `current_steps` 与内存一致、文件可解析（INV-7）
  - [x] SubTask 7.2: 续采后编辑再落盘（复现 DT-4）：模拟 `load_from_draft` 后修改动作类型/文本/坐标 → `_write_draft_now` → 结束任务，断言修改进入草稿与最终 JSON；当前若被旧快照覆盖则判缺陷
  - [x] SubTask 7.3: 续采后快照字段完整性（复现 DT-5）：构造"追加步 → 写草稿 → 续采 → terminate"，断言最终 trajectory 每条都有 `step` 字段且等于下标
  - [x] SubTask 7.4: answer 收尾一轮后的草稿窗口（复现 DT-2）：在 `save_current_round()` 后、`steps` 清空前抓取草稿，断言 `rounds` 与 `current_steps` 不构成"同一轮重复"；若重复，`load_from_draft` + `finish_all_annotation` 后 rounds 不得翻倍
  - [x] SubTask 7.5: `reset_for_new_task` 后草稿状态（复现 DT-3）：断言草稿不残留上一轮 `current_steps`，或续采不会重复写轮
  - [x] SubTask 7.6: 续采后删除/插入/撤销/重截全链路：INV-1~11 全绿（含最终产物）

- [x] Task 8: 缺陷确认与最小修复（TDD：每个缺陷先有失败用例）
  - [x] SubTask 8.1: DT-1——`_write_draft_now` 在 `gui_number` 非空且用户已有任务时，即使 `steps`/`rounds` 皆空也应落一份"空状态"草稿（或删除草稿），保证续采不复活已删步骤
  - [x] SubTask 8.2: DT-2/DT-3——轮次边界先清空 `steps` 再落草稿，或草稿写入时排除与 `rounds` 重复的本轮 `current_steps`；`reset_for_new_task` 后调度一次草稿落盘
  - [x] SubTask 8.3: DT-4/DT-5——普通步骤确认（或 `_write_draft_now`/`save_current_round` 取数路径）统一以编辑器实时数据为准刷新 `data` 快照，并补齐 `step` 字段
  - [x] SubTask 8.4: DT-6——删除截图文件前检查 `self.rounds` 中是否仍被引用，被引用则跳过删除并打印提示
  - [x] SubTask 8.5: DT-7——`on_recapture_completed` 与 `_init_editor_from_capture` 共用归一化逻辑（双框 → `drag`），并在重新截图后同步刷新 `step["data"]`
  - [x] SubTask 8.6: DT-8——`_check_stack_invariant` 失败时除打印外，标记进入"数据异常"保护态（至少阻止无把握的 `widget(count-1)` 删除路径），不改变正常运行行为
  - [x] SubTask 8.7: DT-9——`undo_last_step` 改为删除"当前步"语义（或非末步时拦截并提示），并同步 `_missing_cache`/页码定位；与按钮可见性约束保持一致
  - [x] SubTask 8.8: 若某项经测试确认不可复现（或属 NO-1~NO-6 允许行为），在 `tasks.md` 对应子项注明"已验证非缺陷"并保留回归用例

- [x] Task 9: 回归与收尾
  - [x] SubTask 9.1: 全量运行 `python -m pytest tests -q`（`QT_QPA_PLATFORM=offscreen`）全绿，输出结果记录在最终回复中
  - [x] SubTask 9.2: 确认未改动 `macos端/`、`ios端/`、`安卓端/` 任何文件，未修改样例数据 `test/gui_000001/*`
  - [x] SubTask 9.3: 确认最终产物字段契约未被破坏（除补齐 `step` 字段这一项），并在 checklist 中标注

# Task Dependencies

- Task 2 依赖 Task 1
- Task 3 ~ Task 7 依赖 Task 2（可并行）
- Task 8 依赖对应测试组已复现（Task 3~7 中标注"复现 DT-x"的子项）
- Task 9 依赖 Task 8
