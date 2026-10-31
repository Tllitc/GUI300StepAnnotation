# 安卓端步骤变更操作数据完整性测试 Spec

## Why

安卓端采标工具（`安卓端/main.py` + `annotation_editor.py`）的「撤销上一步」「删除当前步骤」「在当前步后插入」「重新截图」四类操作直接改写步骤模型、截图文件与草稿，且安卓端与桌面端/iOS 端实现差异显著：ADB 后台线程异步截图（50ms 延迟 + seq 校验）、截图序号采用「最小可用序号」复用空洞、`undo_step` 固定弹末步。桌面端/iOS 端已完成的同类测试不能覆盖这些差异路径，需要对安卓端单独做离线自动化测试，验证 JSON 错乱、截图错乱、命名错乱、引用错乱等数据完整性问题，并顺带排查潜在缺陷。

## What Changes

- 新增 `安卓端/tests/` 离线 pytest 测试套件（`QT_QPA_PLATFORM=offscreen`，无需真机/ADB），覆盖撤销/删除/插入/重新截图及草稿、多轮、续采交叉场景
- 新增不变量校验工具，对每个变更场景断言：模型、磁盘文件、草稿、侧栏、最终 JSON/coords 五者一致
- 对测试中复现的缺陷做**最小化修复**（TDD：先有失败用例再改产品代码）
- 不改动最终产物 `gui_XXXXXX.json` / `gui_XXXXXX_coords.json` 的字段契约

## Impact

- Affected code（被测对象）：
  - `安卓端/annotation_editor.py` — `undo_step`（L2174，弹末步语义，**未取消 scroll/swipe 测量态**）、`delete_current_step`（L2108，引用检查仅覆盖 steps_data 未覆盖 rounds）、`start_insert_capture`/`_on_screenshot_finished`（L1639/L1687，锚点 `_insert_after_index` + seq 校验）、`take_screenshot`/`_do_screenshot`（L1654/L1673，50ms singleShot + ADB 后台线程，800ms 冷却锁）、`_write_draft_now`/`load_from_draft`（L2548/L2607）、`_save_current_round_to_list`（L2724）
  - `安卓端/data_manager.py` — `get_next_screenshot_number`（L61，**最小可用序号**复用空洞）、`save_screenshot`
- Affected specs：无（新增独立测试能力，与 `test-step-mutation-data-integrity`（iOS）、`test-desktop-step-mutation-data-integrity`（桌面）并列）

## 一致性不变量（测试断言依据）

- INV-1 模型连续：`steps_data` 下标连续、每步 `screenshot` 非空（已确认步）
- INV-2 引用存在：所有 `steps_data`/`rounds` 引用的截图文件在磁盘存在
- INV-3 图步单射：同一轮内一个截图文件仅被一个步骤引用
- INV-4 无孤儿：gui 目录内 png 均被 steps_data 或 rounds 引用（轮次引用计入可达集）
- INV-5 命名规范：文件名匹配 `gui_XXXXXX_NNNN.png`；安卓端允许序号空洞复用（设计允许，业务顺序与文件名顺序可解耦），但同一时刻引用必须唯一正确
- INV-6 草稿一致：`_write_draft_now()` 后 draft 的条数/顺序/截图引用与内存一致、`current_step_index` 合法、无可序列化违禁字段（无 screenshot_filepath 绝对路径泄漏为不可用状态的字段不强制，以产品当前契约为准）
- INV-7 最终 JSON：结束后 trajectory 的 step 连续、screenshot 全部存在且按业务顺序、coords 与 trajectory 对齐
- INV-8 侧栏一致：`rebuild_items` 后条目数 == `len(steps_data)`、无重复文件名条目、缩略图不错位
- INV-9 瞬态复位：`_screenshot_in_progress is False`、`_insert_after_index is None`、`_swipe_measuring/_scroll_measuring` 为 False、无残留冷却锁死
- INV-10 续采一致：`load_from_draft` 恢复后 INV-1~9 继续成立，可继续变更并正常结束

## ADDED Requirements

### Requirement: 离线测试基础设施

The system SHALL 提供 `安卓端/tests/` pytest 套件，在无 Android 真机、无 ADB 的环境以 `QT_QPA_PLATFORM=offscreen` 离线运行；以桩 `AndroidScreenCapture.capture` 生成可区分 PNG（不同底色+序号文字）并真实经过 `_do_screenshot` → 后台线程 → `_screenshot_finished` → `_on_screenshot_finished` → `DataManager.save_screenshot` 全链路；用真实事件循环驱动 50ms singleShot 与 800ms 冷却（非 sleep 假等待）；删除/撤销确认框、任务完成框、新轮指令框全部自动应答。

#### Scenario: 冒烟
- **WHEN** 初始化任务 → 走 3 步 → answer_terminate 结束
- **THEN** 产出 `gui_000001.json`、`_coords.json` 与 3 张截图且均可解析

### Requirement: 撤销操作（undo_step）一致性

The system SHALL 验证撤销后模型/磁盘/草稿/侧栏/最终产物五者一致，并对以下代码走查疑点给出确定结论（复现则修复，证明安全则固化回归用例）：

- DA-1：`undo_step` **未调用** `_cancel_swipe_measurement/_cancel_scroll_measurement`（对照 delete L2124-2125、confirm L1999-2000 均有）——测量中撤销后测量态残留，下次拉框误入测量分支
- DA-2：`undo_step` 删除被撤销步骤文件但**未清理侧栏缩略图缓存**，且序号复用使新截图取同名文件——侧栏/预览显示旧图
- DA-3：`undo_step` 固定弹**末步**而非当前步；用户停在中间步按 Ctrl+Z 时删末步且未确认表单编辑静默丢失（`_save_current_to_steps` 未被调用）
- DA-4：已截图未确认新步（`current_step == len`）时点撤销：末步与当前未保存新图**两个文件同时被删**（L2192-2204），需定性行为是否符合预期
- DA-5：撤销把步骤删空后草稿同步正确，续采不复活已删步骤

#### Scenario: 测量中撤销（DA-1）
- **WHEN** 某步处于 swipe/scroll 测量态时触发 `undo_step`
- **THEN** 测量标志复位、无残留起点数据，后续普通拉框走正常分支

#### Scenario: 撤销后重截同名复用（DA-2）
- **WHEN** 撤销末步（文件 N）后立即重新截图，新文件复用序号 N
- **THEN** 侧栏缩略图与画布显示新图而非缓存旧图，steps_data 引用正确

### Requirement: 删除当前步骤（delete_current_step）一致性

The system SHALL 验证删除中间步/首步/末步/删空后五者一致，并确认：

- DA-6：删除时引用检查仅扫描 `steps_data`（L2130），未覆盖 `rounds`——历史轮仍引用的同名文件是否可能被误删（正常流程文件名唯一，需构造交叉场景验证）
- DA-7：**截图在途**（50ms 窗口或 ADB 后台线程期间）删除中间步——删除后 `current_step` 前移与 `capture_step` 同值时（L1694 校验通过），过期截图写入错位步骤、原步骤文件成孤儿
- DA-8：删除处于 scroll/swipe 测量中的步骤后状态复位、随后截图正常

#### Scenario: 在途截图+删除中间步（DA-7）
- **WHEN** 对第 k 步发起截图后在结果返回前删除第 k 步（或其前序步使下标前移）
- **THEN** 过期结果被丢弃且不写入任何步骤，或不产生串图/孤儿

### Requirement: 在当前步后插入（start_insert_capture）一致性

The system SHALL 验证插入后业务顺序正确、JSON/草稿引用严格按业务顺序、图步一一对应，并确认：

- 插入锚点在截图在途期间被删除/撤销/导航切换后的处理（L1694 仅校验 `capture_step` 是否等于当前下标，锚点步内容是否已被删除不在校验范围）
- 插入确认后 `confirm_step` 把 `current_step` 置为 `len(steps_data)`（L2020）跳到末尾的语义与侧栏表现
- 插入失败（桩件返回失败）后 `_insert_after_index` 复位，后续普通截图不误入插入分支

#### Scenario: 中间插入
- **WHEN** 3 步任务在第 1 步后插入并确认新步
- **THEN** 业务顺序为 1-新-2-3，各步截图引用各自正确，INV-1~10 全绿

### Requirement: 重新截图一致性

The system SHALL 验证对历史步重新截图（take_screenshot 覆盖路径）后：旧文件在**新图保存成功后**才删除、步骤引用更新、磁盘无孤儿、其他步骤不受影响；并确认旧文件删除失败（占用）时不产生双引用。

#### Scenario: 中间步重新截图
- **WHEN** 对已确认的中间步再次截图
- **THEN** 该步引用指向新文件、旧文件已删、其余步骤引用与文件不变

### Requirement: 草稿/多轮/续采交叉一致性

The system SHALL 验证删除/插入/撤销后立即写草稿、answer 收尾一轮后在新轮变更、续采恢复后继续变更等交叉场景下 INV-1~10 成立；高频交替变更序列（删除→插入→截图→导航循环）过程与结束后五者收敛一致。

#### Scenario: 续采全链路
- **WHEN** 构造"走步+删除+插入+撤销"序列 → 写草稿 → 新编辑器 `load_from_draft` → 继续变更 → 结束
- **THEN** INV-1~10 全绿，最终 JSON/coords 引用连续无缺失

### Requirement: 缺陷最小修复

The system SHALL 对每个复现的缺陷先做失败测试再做最小化修复，不引入与数据一致性无关的重构；修复不改变 `gui_XXXXXX.json`/`gui_XXXXXX_coords.json` 字段契约（字段名、round/step 结构与既有样例一致）。

#### Scenario: TDD 闭环
- **WHEN** 任一 DA-x 疑点复现为真实缺陷
- **THEN** 存在对应用例在修复前失败、修复后通过

## MODIFIED Requirements

无（纯新增测试能力与缺陷修复，不修改既有功能需求）。

## REMOVED Requirements

无。
