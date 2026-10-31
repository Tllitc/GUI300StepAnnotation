# 桌面端采集期步骤变更操作的数据一致性测试 Spec

## Why

Windows 桌面端 GUI 长步骤采标工具（入口 `main.py`）在采集过程中支持四类"步骤变更"操作：**撤销**（`undo_last_step`）、**删除当前步骤**（`delete_current_step`）、**在此步骤后插入截图**（`start_insert_capture`）、**重新截图**（`recapture_current_step`）。这些操作会同时改动五条数据线：

1. 内存模型 `self.steps`（`editor` 引用 / `screenshot_filename` / `rect_info` / `selection_type` / 可选 `data` 快照 / 运行时 `confirmed`）
2. `QStackedWidget` 页序（第 0 页为空提示页，第 i+1 页必须是 `steps[i]["editor"]`）
3. 磁盘截图文件及其命名序号（`gui_{gui_number}_{4位}.png`，由目录扫描 max+1 分配）
4. 增量草稿 `*_draft.json`（防抖 1s + 轮次边界立即落盘）
5. 最终产物 `gui_XXXXXX.json` / `gui_XXXXXX_coords.json`（经 `self.rounds` + `self.all_coords_entries` 合并写出）

项目根目录当前**没有任何自动化测试**。上述交叉路径在静态走查中已发现多处可疑点（见"静态走查发现的候选缺陷"），需要一套可离线运行、不依赖真实屏幕截图的自动化测试来系统验证：是否会出现 JSON 错乱、截图与步骤错配、截图命名错乱、JSON 引用截图错乱、命名顺序错乱，以及草稿续采导致的数据错乱；并对确认的缺陷做最小修复。

## What Changes

- 新增 `tests/` 自动化测试集（pytest + `QT_QPA_PLATFORM=offscreen`）：
  - 用桩件替换 `ScreenshotCaptureWindow`（`annotation_editor.py` 中 `from screenshot_capture import ScreenshotCaptureWindow`），不弹真实全屏遮罩、不依赖真实屏幕；
  - 桩件生成**可区分**的 PNG（不同底色 + 文件名文字），使"图↔步骤"映射错乱可被断言；
  - 模态框（`QMessageBox.question/warning/critical`、`QInputDialog.getText`）统一自动应答；
  - 每个测试使用独立 `tmp_path` 作为 `DataManager.base_dir`。
- 围绕**数据一致性不变量**（INV-1 ~ INV-10）对四类变更操作编写场景化断言，并覆盖"变更 → 写草稿 → 关闭 → `load_from_draft` 续采 → 再变更 → 结束"闭环。
- 对测试确认的缺陷做最小化修复（TDD：先写失败测试，再改产品代码），修复不得改变 `gui_XXXXXX.json` / `gui_XXXXXX_coords.json` / `*_draft.json` 的既有字段契约（除补齐本 spec 认定缺失的必需字段）。
- 不做功能增强、不重构无关代码、不新增用户可见功能。

## Impact

- Affected specs:
  - `support-long-trajectory-300plus`（删除/插入/草稿/侧栏/懒加载缩略图能力来源，本 spec 不改其格式契约）
  - `fix-draft-resume`（草稿生命周期与续采语义，本 spec 的续采用例与其相关）
  - `fix-zombie-editor-after-finish`（窗口销毁与"幽灵实例"，本 spec 仅做回归验证）
  - `test-step-mutation-data-integrity`（**iOS 端**同名能力测试，与本 spec 覆盖不同代码目录，互不替代）
- Affected code:
  - `annotation_editor.py` — 撤销/删除/插入/重新截图/草稿/侧栏/页序重排逻辑（主要修复面）
  - `data_manager.py` — 截图命名与覆盖保存（仅在测试确认缺陷时做最小改动）
  - `main.py` — 仅作为入口与续采链路参考，预期不改动
  - `tests/` — **新增**（`conftest.py`、`fakes.py`、`helpers.py`、`invariants.py`、场景测试文件）
- 数据文件：不新增、不修改任何现有样例数据（`test/gui_000001/*` 仅作格式契约参考）。

## 数据一致性不变量（测试断言基线）

四类变更操作执行完成后，以下不变量必须成立：

- **INV-1 模型一致**：`self.steps` 连续无空洞；每步 `screenshot_filename` 非空且等于磁盘上真实文件名；若该步存在 `data` 快照，则 `data["step"]` 等于其当前下标、`data["observation"]["screenshot"]` 等于 `screenshot_filename`。
- **INV-2 页序一致**：`stack_widget.count() == len(self.steps) + 1`，且对每个 i 有 `stack_widget.widget(i + 1) is self.steps[i]["editor"]`；`0 <= current_step_index < len(steps)`（或为 -1 且 steps 为空）。
- **INV-3 文件存在**：`self.steps`、`self.rounds`、草稿 `current_steps` 中引用的每个截图文件名在 `gui_dir` 下真实存在。
- **INV-4 引用单射**：同一截图文件最多被 `self.steps` 中一个步骤引用；不得出现两个步骤指向同一文件。
- **INV-5 无孤儿**：`gui_dir` 下每个 `gui_{gui_number}_dddd.png` 要么被当前 `self.steps` 引用，要么被 `self.rounds` 中某条 trajectory 引用；删除/撤销后不得残留只属于已删步骤的文件。
- **INV-6 命名规范与覆盖语义**：
  - 文件名严格匹配 `gui_{gui_number}_{4位数字}.png`；
  - 新截图序号由目录扫描 max+1 分配，**允许不连续（删除留空洞）、允许与业务顺序非单调**（中间插入取全局最大序号）——属既有设计，不作为缺陷；
  - **重新截图必须复用原文件名**（序号不变、不产生新文件）。
- **INV-7 草稿一致**：`_write_draft_now()` 后，`draft.current_steps` 的条数、顺序、`screenshot_filename`、`rect_info`、`selection_type` 与内存一致；`draft.rounds`、`draft.coords_entries` 与内存一致；`draft.current_steps[i].data` 的 `observation.screenshot` 与文件名一致；`json.load` 可正常解析（无 tuple 序列化残留）。
- **INV-8 最终产物一致**：
  - `gui_XXXXXX.json` 中每条 assistant `trajectory` 的 `observation.screenshot` 全部存在，且 trajectory 顺序 = 当轮业务顺序，`trajectory[i]["step"] == i`；
  - `gui_XXXXXX_coords.json` 为扁平数组，每条 `step` 落在对应轮次的 trajectory 下标范围内、`action` 与该步 trajectory 的 `action` 语义一致（拖拽条目为 `left_click_drag` 且含 `start_*`/`end_*`）；
  - 注：coords 条目无 `round` 字段、跨轮 `step` 号重复属**既有格式契约**，测试按"每轮独立下标空间"断言，不作为缺陷。
- **INV-9 UI 与模型一致**：`len(sidebar.item_widgets) == len(self.steps)`；`item_widgets[i]` 对应 `steps[i]`；删除/插入/撤销后条目**不重复、不错位**；`已完成/总步数/待完善` 计数与模型一致。
- **INV-10 瞬态状态收敛**：操作结束后 `_capture_in_flight is False`、`_capture_insert_after is None`、`capture_window is None` 或已关闭、主窗口可见且不透明（`windowOpacity() == 1.0`）、`draft_timer` 未悬挂在已销毁对象上。
- **INV-11 续采一致**：构造"操作序列 → 写草稿 → 关闭编辑器 → 新编辑器 `load_from_draft(draft)`"，上述 INV-1/2/3/4/5/6/9 全部成立，且续采后仍能正确删除/插入/撤销/重新截图并结束任务。

## ADDED Requirements

### Requirement: 离线可运行的测试基础设施

系统 SHALL 提供一套不依赖真实屏幕、不依赖人工点击的自动化测试基础设施，可在 Windows 开发机以 `QT_QPA_PLATFORM=offscreen` 运行。

#### Scenario: 桩截图驱动真实链路

- **WHEN** 测试触发截图入口（`start_capture` / `start_insert_capture` / `recapture_current_step`）
- **THEN** 测试通过替换模块级 `ScreenshotCaptureWindow` 注入桩件，桩件在 `capture_completed` 信号中回传可区分的 `QPixmap` 与 `rect_info`/`selection_type`，后续 `DataManager.save_screenshot` / `save_screenshot_overwrite`、建步、页序重排、草稿写盘全部走真实生产代码

#### Scenario: 延迟窗口可被驱动

- **WHEN** 产品代码使用 `QTimer.singleShot(350, ...)` 延迟弹出截图窗口
- **THEN** 测试用 `QTest.qWait(400)` 或等价事件循环推进驱动，不阻塞、不假等待

#### Scenario: 模态框自动应答

- **WHEN** 被测路径弹出 `QMessageBox.question`（删除/撤销确认）、`QInputDialog.getText`（新轮指令）、`QMessageBox.warning/information/critical`
- **THEN** 夹具按用例预设返回 Yes/No 或预设文本，测试无人值守完成

#### Scenario: 隔离存储

- **WHEN** 每个测试运行
- **THEN** `DataManager.current_dir` 与 `base_dir` 指向该用例独立的 `tmp_path`，用例结束自动清理，互不污染

### Requirement: 撤销操作数据一致性

系统 SHALL 保证"撤销"在任意可撤销状态下执行后满足 INV-1 ~ INV-10。

#### Scenario: 撤销末尾已确认步骤

- **WHEN** 已存在 N≥2 步且当前停在最后一步，点击"撤销"并确认
- **THEN** 该步从 `steps` 移除、stack 页同步移除、其截图文件从磁盘删除、剩余步引用与顺序不变、侧栏条目数减少 1 且下标连续、草稿同步更新

#### Scenario: 非末尾位置触发撤销

- **WHEN** 当前停在中间步时调用 `undo_last_step`（如可见性未刷新或程序化调用）
- **THEN** 被删除的步骤与删除后停留位置有确定语义且自洽：不得出现"页面移除的是最后一步、指示器仍指向中间步"的错位，不得留下孤儿截图

#### Scenario: 撤销后重新截图

- **WHEN** 撤销末尾步后再截图追加
- **THEN** 新截图按 max+1 取号（可复用刚释放的序号），只被新步骤引用，历史轮次引用不受影响

#### Scenario: 空步骤撤销与取消撤销

- **WHEN** `steps` 为空时调用撤销，或确认框选"No"
- **THEN** 无任何副作用，`steps`/磁盘/草稿保持不变

### Requirement: 删除当前步骤数据一致性

系统 SHALL 保证 `delete_current_step` 在首步/中间步/末步/唯一一步/删空等边界下满足 INV-1 ~ INV-10。

#### Scenario: 删除中间步

- **WHEN** 存在 5 步，停在第 3 步并确认删除
- **THEN** 第 3 步从模型与 stack 移除、第 4/5 步前移且编辑器显示序号与 `data["step"]` 重编号为 1/2、各步截图引用仍指向各自原文件（不串图）、侧栏全量重建后下标一一对应、草稿同步

#### Scenario: 删除末步与首步

- **WHEN** 删除最后一步 / 删除第 1 步
- **THEN** 删除后停留位置符合实现语义（同位置即原下一步 / 删末步则停前一步），`current_step_index` 合法，stack 页序不变式成立

#### Scenario: 删空全部步骤

- **WHEN** 逐步删除至 `steps` 为空
- **THEN** 回到第 0 页空提示、指示器显示 0/0、删除/插入按钮禁用，**草稿必须同步为"无当前步骤"状态**（不得保留已删步骤导致续采复活）

#### Scenario: 删除后结束任务

- **WHEN** 删除若步后以 terminate 结束任务
- **THEN** 最终 JSON 的 trajectory 按剩余步骤连续编号、截图引用全部存在，coords 条目与 trajectory 下标对齐

### Requirement: 插入截图数据一致性

系统 SHALL 保证 `start_insert_capture` 在插入锚点有效/失效、以及插入后的连锁变更下满足 INV-1 ~ INV-10。

#### Scenario: 中间插入

- **WHEN** 停在第 1 步执行"在此步骤后插入截图"并完成截图
- **THEN** 新步插入到下标 1（业务顺序），新文件名取全局最大序号（文件名序号与业务顺序解耦，属设计允许），stack 页按 `steps` 顺序重排且不变式成立，插入点及之后步骤重编号，侧栏全量重建无重复条目，草稿按业务顺序落盘

#### Scenario: 插入后再次删除/插入

- **WHEN** 插入后删除新步，或在新步后再次插入
- **THEN** 模型、磁盘、stack、侧栏、草稿持续一致，`data` 快照 `step` 字段与 `screenshot` 字段均正确

#### Scenario: 插入锚点失效

- **WHEN** `current_step_index` 越界（无步骤）或延迟窗口内步骤被删空时执行插入
- **THEN** 不产生越界插入、不产生孤儿截图，`_capture_insert_after` 必须复位，后续普通截图走追加分支

#### Scenario: 插入截图失败

- **WHEN** `save_screenshot` 返回 `None`（磁盘异常）
- **THEN** 不建步、不改变 `steps`、`_capture_insert_after` 复位、主窗口恢复可见，后续截图仍可正常追加

### Requirement: 重新截图数据一致性

系统 SHALL 保证 `recapture_current_step` 覆盖原文件且不破坏引用关系。

#### Scenario: 历史步重新截图

- **WHEN** 对第 2 步重新截图并确认
- **THEN** 沿用原文件名（序号不变、文件数不变）、磁盘内容更新、`steps[1]["rect_info"]` 与 `selection_type` 更新、其他步骤引用不受影响、缩略图缓存失效并重载、草稿引用不变

#### Scenario: 重新截图改变框选形态

- **WHEN** 原为单框（单击）重新截图为双框（拖拽），或反之
- **THEN** `selection_type` 归一化口径与新建步骤路径一致（双框 → `drag`），编辑器动作类型 / 坐标输入与最终 JSON 的 `action`、coords 的 `action` 三者语义一致

#### Scenario: 重新截图取消或失败

- **WHEN** 用户在遮罩中取消，或 `save_screenshot_overwrite` 返回 `None`
- **THEN** `_capture_in_flight` 复位、主窗口恢复、原文件与 `steps` 数据保持不变

### Requirement: 草稿与多轮交叉一致性

系统 SHALL 保证草稿写入、轮次切换与续采不会产生重复轮次、幽灵步骤或引用错乱。

#### Scenario: 单步删除后的草稿内容

- **WHEN** 任意变更操作后触发 `_write_draft_now()`（防抖或显式）
- **THEN** `current_steps` 与内存逐项一致；`rounds`/`coords_entries` 未被重复追加；`json` 文件可解析

#### Scenario: 轮次结束时的草稿窗口

- **WHEN** answer / terminate 分支 `save_current_round()` 之后、`steps` 清空之前程序异常退出
- **THEN** 续采得到的状态必须是"可继续且不重复"的：同一轮数据不得同时以 `rounds` 与 `current_steps` 身份被二次写入最终 JSON

#### Scenario: 续采后继续编辑

- **WHEN** 从草稿恢复后修改某步的动作类型/文本/坐标，再写草稿并结束任务
- **THEN** 修改必须进入草稿与最终 JSON（不得被恢复时的旧 `data` 快照覆盖），且 JSON 的 `action` 与 coords 的 `action` 一致

#### Scenario: 续采后继续变更

- **WHEN** 续采后执行删除/插入/撤销/重新截图
- **THEN** INV-1 ~ INV-10 全部成立，且最终产物引用完整

## 静态走查发现的候选缺陷（需测试确认后修复）

> 行号基于当前 `annotation_editor.py` / `data_manager.py`；测试必须先复现（红灯）再修复。

| 编号 | 位置 | 现象 | 影响 |
| --- | --- | --- | --- |
| DT-1 | `_write_draft_now` L2461-L2462 | `steps` 与 `rounds` 同时为空时直接 return，不覆盖草稿 | 删空全部步骤后旧草稿仍含已删步骤（其截图已删），续采后已删步骤"复活"且预览缺图 |
| DT-2 | `save_current_round` L2449 与 `save_current_step` L2305-L2307 / L2331-L2333 | `_write_draft_now()` 在 `steps` 尚未清空时执行，草稿同时写入 `rounds`（本轮）与 `current_steps`（本轮） | 该窗口内崩溃/强杀，续采后同一轮被 `save_current_round` 再存一次 → 轮次与 coords 重复 |
| DT-3 | `reset_for_new_task` L2772-L2790 | 清空 `steps` 后不调度草稿写盘 | 开启新轮次后、下一次截图前崩溃，续采仍显示上一轮步骤 + rounds 中已有该轮 → 与 DT-2 同源重复 |
| DT-4 | `_write_draft_now` L2474-L2475 / `save_current_round` L2381-L2382 / `confirm_button_clicked` L2252-L2258 | 续采步骤带 `data` 快照，写盘优先读快照；普通确认只置 `confirmed`，不刷新快照 | 续采后对步骤的编辑不进入草稿与最终 JSON（静默丢数据） |
| DT-5 | `save_current_step` L2250 唯一调用点 + L2337-L2340 不可达分支 | 普通步骤永不写入 `data`，草稿 `current_steps[].data` 缺 `step` 字段；续采后沿用该快照 | 最终 `trajectory` 条目缺 `step` 字段，与"step 放在首部"的既有格式不一致 |
| DT-6 | `_delete_screenshot_file` L1968-L1978 | 删除前不检查该文件是否已被 `self.rounds` 引用 | 在 DT-2/DT-3 造成的"rounds 与本轮 steps 共存"状态下删步，会删掉已入 rounds 的图片 → 历史轮引用失效 |
| DT-7 | `on_recapture_completed` L1679-L1684 vs `_init_editor_from_capture` L1810 | 重新截图未把双框归一化为 `selection_type="drag"`，也不更新 `step["data"]` | `rect_info`/`selection_type` 口径与新建路径不一致；若动作类型随框选变化，JSON trajectory 与 coords 的 `action` 相互矛盾 |
| DT-8 | `_check_stack_invariant` L1944-L1953 | 不变式校验失败仅 `print`，不抛错、不告警 | 页序一旦错乱将静默传播，后续 `widget(count-1)`（撤销 L2215）取到错误页 → 删错编辑器/删错文件 |
| DT-9 | `undo_last_step` L2212-L2215 | 无条件 `steps.pop()` + 移除最后一页，仅靠按钮可见性约束"当前步即末步" | 在非末步被触发时删除末尾步而保留当前步，`current_step_index` 与模型/页面错位；且不更新 `_missing_cache` 对应关系 |

### 已排除 / 非缺陷项（测试中作为"允许行为"断言）

- **NO-1**：`refresh_sidebar(fully=False)` 增量建项不会重复——`SideBarWidget._create_item`（L1063-L1067）只 `insertWidget` 不自 `append`，`item_widgets.append` 仅在调用方执行一次。
- **NO-2**：删除/插入后 `_missing_cache` 长度变化，`refresh_dashboard`（L1153-L1158）会触发 `revalidate_all_missing` 重算，最终标记正确（`rebuild_items` 过程中存在瞬时错标，不作为缺陷）。
- **NO-3**：截图文件名序号非单调、允许空洞（中间插入取 max+1），属既有设计（`data_manager.get_next_screenshot_number` L86-L116）。
- **NO-4**：`gui_XXXXXX_coords.json` 无 `round` 字段、跨轮 `step` 号重复，属既有格式契约（样例 `test/gui_000001/gui_000001_coords.json`）。
- **NO-5**：`show_terminate_dialog`（L2350）与 `start_new_round(from_answer=False)`（L2695 分支）当前**无调用点**（死代码）；测试仅记录其存在，不为其编写修复，但需防止后续接线时引入重复轮次。
- **NO-6**：`create_task_directory`（`data_manager.py` L33-L47）不预建 `gui_XXXXXX` 目录，不存在"空目录占用编号"问题。

## Out of Scope

- `macos端/`、`ios端/`、`安卓端/` 目录下的任何代码与测试（iOS 端已有独立 spec `test-step-mutation-data-integrity`）。
- `screenshot_capture.py` 内部遮罩绘制与框选交互逻辑（本 spec 用桩件替代）。
- 新增用户可见功能、UI 布局调整、性能优化、日志体系改造。
- 改变 `gui_XXXXXX.json` / `gui_XXXXXX_coords.json` / `*_draft.json` 的既有字段契约（仅在缺陷修复必须时补齐字段，且需在 checklist 中说明）。
- 真实多显示器 / 高 DPI 缩放 / 真实全局快捷键（`Alt+Q`）的人工交互验证。
