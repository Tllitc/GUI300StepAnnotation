# 采集期步骤变更操作的数据一致性测试 Spec

## Why

iOS 端 GUI 长步骤采标工具在采集过程中支持三类"步骤变更"操作：**撤销**（`undo_last_step`）、**删除当前步骤**（`delete_current_step`）、**在此步骤后插入截图**（`start_insert_capture`），此外还有同步骤**重新截图**。这些操作会同时改动五条数据线：`steps_data` 内存模型、磁盘截图文件与命名序号、侧栏条目（`sidebar.item_widgets`）、草稿 JSON（`*_draft.json`）、最终产物 JSON/coords JSON（经 rounds 落盘）。

静态走查发现这些变更路径与 scroll/swipe 测量状态、草稿实时快照、侧栏全量重建/增量建项之间存在多处交叉，可能引发：JSON 错乱、截图与步骤映射错乱、截图命名错乱、JSON 引用截图错乱、命名顺序错乱，以及其他潜在数据错乱。目前项目没有任何自动化测试，且开发机无 iPhone 真机，需要一套**不依赖真机、可离线运行**的测试来系统验证，并对确认的缺陷进行修复。

## What Changes

- 新增基于 pytest + `QT_QPA_PLATFORM=offscreen` 的无真机自动化测试集：用桩件替换 `AnnotationEditor.screen_capture`，向固定临时路径注入本地生成的 PNG，驱动真实的 `_do_screenshot` → `DataManager.save_screenshot` 全链路；模态对话框（QMessageBox/QInputDialog）用 `QTimer` 自动应答或 monkeypatch 处理。
- 测试围绕**数据一致性不变量**对撤销/删除/插入/重新截图四类操作做场景化断言（见 ADDED Requirements）。
- 对测试确认的缺陷做最小化修复（预期候选见"静态走查发现的候选缺陷"），每个修复必须有对应失败测试先行（TDD），修复不得改变最终产物 `gui_XXXXXX.json` / `gui_XXXXXX_coords.json` 的既有格式契约。
- 不做功能增强、不重构无关代码、不新增任何面向用户的功能。

## Impact

- Affected specs:
  - `support-long-trajectory-300plus`（删除/插入/草稿/侧栏能力由该 spec 引入，本 spec 仅做测试与缺陷修复，不修改其格式契约）
  - `fix-draft-resume`（草稿生命周期，本 spec 的续采测试与其相关但不改变其行为）
- Affected code:
  - `ios端/annotation_editor.py` — 撤销/删除/插入/截图/草稿/侧栏/scroll 测量交叉逻辑（主要修复面）
  - `ios端/data_manager.py` — 截图序号与命名（仅在测试确认缺陷时做最小改动）
  - `ios端/tests/` — **新增**测试目录（conftest、夹具、一致性断言工具、场景测试）
- 数据文件：不新增、不修改任何现有数据文件格式。

## 数据一致性不变量（测试断言基线）

所有变更操作（撤销/删除/插入/重新截图）完成后，以下不变量必须成立：

- **INV-1 模型一致**：`steps_data` 连续无空洞，每步含非空 `screenshot`（文件名）且其值与磁盘文件名相等；步骤顺序即业务顺序。
- **INV-2 文件存在**：`steps_data` 中每个 `screenshot` 文件在 `gui_dir` 下真实存在；草稿/rounds 中引用的文件名同样存在。
- **INV-3 映射唯一**：磁盘文件 → 步骤是单射（一个截图文件最多被一个步骤引用）；不应有步骤引用了"别的步骤"的图。
- **INV-4 无孤儿截图**：gui 目录中 `gui_NNNNNN_*.png` 要么被某步骤引用，要么属于已完成轮次（rounds 引用），要么不存在；变更操作后不得泄漏不可达的截图文件（允许序号空洞，但不允许不可达文件长期残留）。
- **INV-5 命名规范**：文件名严格匹配 `gui_NNNNNN_dddd.png`；新截图序号由目录扫描 max+1 得出；序号允许非连续（删除留空洞），允许与步骤顺序不一致（中间插入取全局最大序号）——这是既有设计，不作为缺陷。
- **INV-6 草稿一致**：草稿落盘（`_write_draft_now`）后，`steps_data` 条数、顺序、截图引用与内存一致；不序列化运行时绝对路径 `screenshot_filepath`；重新载入后文件名→路径能由 `gui_dir` 重建且文件均存在。
- **INV-7 最终产物引用一致**：任务结束写出的 `gui_XXXXXX.json` 中每条 trajectory 的 `observation.screenshot` 与磁盘文件一一对应；`gui_XXXXXX_coords.json` 的条目数、`step`/`round` 与 trajectory 对齐；截图引用无缺失、无张冠李戴。
- **INV-8 UI 与模型一致**：`sidebar.item_widgets` 条数等于 `len(steps_data)`，条目下标与步骤下标一一对应；条目点击信号携带的 index 命中正确的步骤。
- **INV-9 测量状态收敛**：删除/撤销/切轮/确认等操作后，`_scroll_measuring`、`_scroll_preserve_screenshot`、`_capture_insert_after`、`_swipe_measuring`、`_screenshot_in_progress` 等瞬态标记必须复位，`_scroll_extra_screenshots` 清空且对应文件已清理。
- **INV-10 草稿续采一致**：构造"操作序列 → 写草稿 → 关闭 → 重新 load_from_draft"后，上述 INV-1/2/3/6/8 全部成立，可继续删除/插入而不产生错乱。

## ADDED Requirements

### Requirement: 无真机测试基础设施

系统 SHALL 提供一套不依赖 iPhone 真机、不依赖 `ios.exe` 的自动化测试基础设施，可在 Windows 开发机以 `QT_QPA_PLATFORM=offscreen` 离线运行。

#### Scenario: 桩截图驱动真实链路

- **WHEN** 测试调用编辑器的截图入口（`take_screenshot` 并驱动到 `_do_screenshot` 完成，或直接触发延迟回调）
- **THEN** 桩 `screen_capture.capture(output_path)` 把测试生成的 PNG 写入 `output_path` 并返回 `(True, output_path)`，后续保存、命名、建步、草稿全部走真实生产代码路径

#### Scenario: 模态对话框自动应答

- **WHEN** 被测路径弹出 QMessageBox 确认框 / QInputDialog 输入框
- **THEN** 测试夹具以自动应答（删除/撤销选 Yes，新轮指令提供预设文本）或 monkeypatch 方式处理，测试可无人值守完成

#### Scenario: 隔离的临时存储

- **WHEN** 每个测试运行
- **THEN** `DataManager.current_dir` 指向 pytest 临时目录（tmp_path），测试结束自动清理；截图 PNG 由测试动态生成（如带不同底色/编号以便断言图与步骤的映射）

### Requirement: 撤销操作数据一致性

系统 SHALL 保证"撤销"在任何可撤销状态下执行后满足 INV-1～INV-10。

#### Scenario: 撤销末尾已确认步骤

- **WHEN** 已确认 N 步（N≥2），停在第 N 步或回到中间步，点击"撤销"
- **THEN** 该步从 `steps_data` 移除、其截图文件按引用计数删除、后续步前移且引用连续、草稿与侧栏同步正确

#### Scenario: 撤销被删除后序号空洞复用

- **WHEN** 撤销（删除）的是末尾步（占用最大序号）后重新截图
- **THEN** 新图复用刚释放的序号且只被新步引用，旧引用不复存在（验证"序号复用"不会产生引用错乱）

#### Scenario: 对已截图但未确认的新步撤销

- **WHEN** 最后一步已截图落盘但尚未点"确认"（`current_step == len(steps_data)` 或 UI 持有未入表新步），点击"撤销"
- **THEN** 行为有明确结果（拦截提示或正确回收），不得产生孤儿截图、错误覆盖或提示与实际状态矛盾；草稿与续采后状态自洽

### Requirement: 删除当前步骤数据一致性

系统 SHALL 保证删除任意位置步骤后满足 INV-1～INV-10。

#### Scenario: 删除中间步骤

- **WHEN** 已确认 5 步，停在第 3 步执行删除
- **THEN** 第 3 步记录与截图移除，第 4/5 步前移为第 3/4 步且其截图引用、vertices、action_data 保持自身正确（不串图）；序号空洞保留；草稿、侧栏、最终 JSON 引用全部连续

#### Scenario: 删除首步 / 末步 / 删空

- **WHEN** 分别删除第 1 步、最后一步、以及删除到 0 步
- **THEN** 边界正确：删空后回到初始空白态可重新开始；所有瞬态测量标记复位；不出现负下标或残留引用

#### Scenario: 删除处于 scroll/swipe 测量中的步骤

- **WHEN** 当前步正处于 scroll 测量（`_scroll_preserve_screenshot=True`，已产生 extra 截图）或 swipe 测量中时执行删除
- **THEN** 测量状态被取消、extra 截图文件被清理、步骤截图归属正确，删除后再截图不会被错误地当作 extra（重点验证静态走查疑点 D-1）

#### Scenario: 删除后最终产物引用

- **WHEN** 删除若干中间步后结束任务（terminate/answer_terminate）
- **THEN** 最终 JSON 的 screenshot 引用全部存在且与步骤一一对应，coords 的 step 连续、条目数与 trajectory 相等

### Requirement: 在此步骤后插入截图数据一致性

系统 SHALL 保证插入截图后满足 INV-1～INV-10，并对"命名顺序与步骤顺序分离"有明确验证。

#### Scenario: 中间插入

- **WHEN** 已确认 3 步（序号 0001/0002/0003），在第 1 步后插入截图
- **THEN** 新步成为第 2 步，业务顺序为 [0001, 0004, 0002, 0003]（文件名序号非单调，属设计允许）；但 JSON/草稿中 observation.screenshot 的引用必须严格按业务顺序，图与步一一对应，后续步不被错误前移/覆盖

#### Scenario: 插入后继续确认与再次删除

- **WHEN** 插入后对新步确认、再删除新步或删除相邻步
- **THEN** 侧栏条目数始终等于 `steps_data` 长度，不出现重复条目；高亮、点击跳转命中正确步骤（重点验证静态走查疑点 D-2）

#### Scenario: 插入截图延迟窗口内导航/删除

- **WHEN** `start_insert_capture` 触发截图后的 50ms 延迟窗口（`QTimer.singleShot(50, _do_screenshot)`）内切换步骤或删除锚点步，随后 `_do_screenshot` 执行
- **THEN** 不发生把新图/新数据写到错误步骤、不覆盖他步表单、不产生错锚点插入；要么操作被守卫拦截，要么结果仍满足全部不变量（重点验证静态走查疑点 D-3）

#### Scenario: 插入失败与状态复位

- **WHEN** 插入截图时桩件返回失败，或插入时正处于 scroll/swipe 测量中
- **THEN** `_capture_insert_after` 等标记复位，后续普通截图不会误入插入分支；不残留半插入状态

### Requirement: 重新截图与序号一致性

系统 SHALL 保证同步骤重新截图原地覆盖、不产生序号漂移与引用错乱。

#### Scenario: 重新截图覆盖

- **WHEN** 对历史步骤点重新截图（`_replacing_screenshot`）
- **THEN** 文件名/序号不变、文件内容更新、`steps_data` 与草稿引用不变、侧栏缩略图缓存按文件名失效后显示新图

#### Scenario: 删除/取消测量后的序号回收

- **WHEN** scroll extra 截图（占用过序号）在完成/取消测量后被删除，随后新截图
- **THEN** 序号可能被复用但引用唯一、无文件被错误删除、无步骤引用到已删文件

### Requirement: 草稿与多轮交叉一致性

系统 SHALL 保证删除/插入/撤销与草稿防抖落盘、多轮 answer 切换交叉时数据不错乱。

#### Scenario: 变更后立即落盘并续采

- **WHEN** 删除/插入后立即触发 `_write_draft_now`（不等防抖），随后用 `load_from_draft` 在新编辑器实例恢复
- **THEN** 恢复后的步骤顺序、截图文件名、文件存在性、当前步下标、侧栏条目全部一致，可继续变更操作

#### Scenario: answer 收尾一轮后继续采集再删除

- **WHEN** answer 动作把当前轮写入 rounds 并开启新一轮，在新一轮执行删除/插入/撤销
- **THEN** rounds 中历史轮引用不被破坏，当前轮变更不影响历史截图文件，最终合并 JSON 的 round/step 归属正确

#### Scenario: 高频连续变更

- **WHEN** 在短时间内交替执行 删除→插入→截图→导航 多次（含触发防抖草稿）
- **THEN** 任意时刻内存模型、磁盘文件、草稿、侧栏四者收敛一致，无异常抛出、无 JSON 序列化错误

### Requirement: 确认缺陷最小修复

对经测试复现确认的数据错乱缺陷，SHALL 以最小改动修复，并保持最终产物 JSON/coords 的既有格式与字段契约不变；每个修复必须先有失败的测试用例。

#### Scenario: 修复回归保护

- **WHEN** 某缺陷修复完成
- **THEN** 对应的新增测试由失败转为通过，且既有全部测试通过；不引入对正常采集/续采流程的回归

## 静态走查发现的候选缺陷（测试须重点复现/排除）

| 编号 | 位置 | 假设 | 预期风险 | 测试处置 |
|------|------|------|----------|----------|
| D-1 | [annotation_editor.py#L1681-L1730](file:///c:/Project/TC/300step采标工具/ios端/annotation_editor.py#L1681-L1730) `delete_current_step` | 删除步骤主流程未直接调用 `_cancel_scroll_measurement`（仅删空分支经 `_reset_for_next_step`→`_clear_inputs` 间接取消）；删非空步时若处于 scroll 测量，extra 截图与 `_scroll_preserve_screenshot` 可能残留 | extra 文件泄漏占序号；之后截图被当作 extra 而不更新当前步 → 截图与步骤错乱 | 复现"删除测量中的步骤"；确认后在删除路径补齐 scroll 取消（与 confirm/clear 对齐） |
| D-2 | [annotation_editor.py#L1607-L1616](file:///c:/Project/TC/300step采标工具/ios端/annotation_editor.py#L1607-L1616) `confirm_step` | `sidebar._create_item(new_index-1)` 无条件增量建项；一旦执行过 `rebuild_items()`（插入/删除/续采/切轮均触发），末步 item 已存在，再次确认会重复建项 | `item_widgets` 条数 > `steps_data` 长度，高亮/缺项/点击跳转下标错位，间接诱导误删/误改 | 复现"rebuild 后在末步确认"；改为按是否已存在决定建项或统一刷新 |
| D-3 | [annotation_editor.py#L1120-L1122](file:///c:/Project/TC/300step采标工具/ios端/annotation_editor.py#L1120-L1122)、[#L1159-L1194](file:///c:/Project/TC/300step采标工具/ios端/annotation_editor.py#L1159-L1194) | 截图延迟 50ms 执行；插入模式在回调时才 `_save_current_to_steps()` 并按锚点 insert。窗口内 `_screenshot_in_progress` 不拦截导航/删除 | 切步/删锚点后，当前表单被保存到已变化的 `current_step`，或插入到失效锚点 → 串步/覆盖 | 用 QTimer 事件编排复现；为延迟窗口增加导航/删除守卫或在执行时重新校验锚点 |
| D-4 | [annotation_editor.py#L1187](file:///c:/Project/TC/300step采标工具/ios端/annotation_editor.py#L1187) | 插入分支把 `screenshot_cache` 指向固定名临时文件而非 gui_dir 副本 | 临时文件被下次截图覆盖后，画布/测量可能读到错图 | 断言插入后 screenshot_cache 与画布所图源；必要时指向 gui_dir 文件 |
| D-5 | [data_manager.py#L69-L80](file:///c:/Project/TC/300step采标工具/ios端/data_manager.py#L69-L80) | 序号基于磁盘 max+1，删图/删 extra 后序号回落复用 | 若引用未清理干净，复用序号会"顶替"旧引用造成引用错乱 | 测试验证删除后引用已同步清除、复用安全；若发现引用残留则修复删除路径 |
| D-6 | [annotation_editor.py#L1904-L1919](file:///c:/Project/TC/300step采标工具/ios端/annotation_editor.py#L1904-L1919) | 草稿对 `current_step` 用实时 UI 快照替换、未入表新步再追加；变更后 current_step 与 UI/模型若不同步会写错下标 | 草稿步骤错位，续采后图步错配 | 在删除/插入/撤销后立即写草稿并 reload 断言 |
| D-7 | [annotation_editor.py#L1626-L1640](file:///c:/Project/TC/300step采标工具/ios端/annotation_editor.py#L1626-L1640) | 撤销复用删除；对"已截图未确认新步"可能拦截但图已落盘 | 孤儿截图/提示矛盾（数据未必损坏） | 明确并测试该状态的预期结果，必要时回收截图或放开删除 |
| D-8 | [annotation_editor.py#L1704-L1707](file:///c:/Project/TC/300step采标工具/ios端/annotation_editor.py#L1704-L1707) | 删图引用检查只查 `steps_data`，不查历史 `rounds` | 多轮交叉下理论上可能删掉历史轮仍引用的图（序号单调递增使其概率低） | 用多轮+删除交叉测试排除；若可复现则扩展引用检查到 rounds |

## 非目标（Out of Scope）

- 不测试设备连接、tunnel、`ios.exe` 调用本身（全部 mock）。
- 不验证像素级图像内容正确性，仅验证"文件身份/引用映射"（用可区分的生成图）。
- 不做性能/300 步内存压测（已有 `support-long-trajectory-300plus` 覆盖）。
- 不改动 macOS 端或其他工具目录。
