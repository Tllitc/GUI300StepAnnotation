# Tasks

- [x] Task 1: Windows 端合并策略升级与草稿路径保留
  - [x] SubTask 1.1: 在 [annotation_editor.py](file:///c:/Project/TC/300step采标工具/annotation_editor.py) 中改造 `_merge_step_with_original`：受保护字段（`CoT`、`observation.active_window`、`observation.ui_tree_segment`、动作 `element`/`status`）按"新值非空才覆盖"合并，`observation` 嵌套按字段处理，原步骤缺失键继续保留；终止类动作的 `element=""`、`status="success"` 业务规则保持不变
  - [x] SubTask 1.2: 排查并修复 `confirm_step` 草稿编辑路径（实际函数名为 `save_current_step`，约 2466 行）：对已存在步骤做编辑确认时，以原步骤字典为基底做字段级合并而非整体替换，`save_current_round`/`_write_draft_now` 的实时重建路径同步接入合并
  - [x] SubTask 1.3: 核对 `load_from_draft` → `load_data` 链路：隐藏字段（CoT/active_window）本已回填，`ui_tree_segment` 无 UI 控件，靠合并保留

- [x] Task 2: macOS 端同步 Windows 修复
  - [x] SubTask 2.1: 在 [macos端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/macos端/annotation_editor.py) 对同名函数应用与 Task 1 完全对等的改造（合并函数 2976 行起、save_current_step/save_current_round/_write_draft_now 三处接入）

- [x] Task 3: iOS 端移除硬编码清空并持久化受保护字段
  - [x] SubTask 3.1: 改造 [ios端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/ios端/annotation_editor.py) 的 `save_edited_round`（3064 行）：`new_traj` 中 `CoT`、`active_window`、`ui_tree_segment` 从原步骤/条目可选键读取，不再硬编码 `""`
  - [x] SubTask 3.2: 升级 `_merge_original_missing`（3027 行）为字段级非空覆盖、非原地合并（含嵌套 `observation` 与 actions 下标），保留原步骤未知键
  - [x] SubTask 3.3: 核对 `_serialize_step`（2683 行）与 `_save_current_round_to_list`（3566 行）：序列化本就全键透传无需改；落轮改为 `.get` 透传三字段，无值维持空串默认

- [x] Task 4: 安卓端同步 iOS 修复
  - [x] SubTask 4.1: 改造 [安卓端/annotation_editor.py](file:///c:/Project/TC/300step采标工具/安卓端/annotation_editor.py) 的 `save_edited_round`（3817 行）：`new_traj` 读取原步骤下游字段，移除硬编码空串，并补齐与 iOS 同口径的步序兜底
  - [x] SubTask 4.2: 升级 `_merge_missing_keys`（3621 行）为字段级非空覆盖、非原地合并（旧版就地修改入参）
  - [x] SubTask 4.3: 扩展 `_write_draft_now`（3372 行）与 `load_from_draft`（3433 行）对称持久化四个可选键；`_save_current_round_to_list`（4129 行）同口径透传，无字段时磁盘结构逐字不变

- [x] Task 5: 四端回归测试
  - [x] SubTask 5.1: Windows/macOS：`tests/test_edit_completed.py` 与 `macos端/tests/test_edit_completed.py` 各新增 3 个用例（受保护字段+三层未知键、终止类动作、草稿续采确认），并验证删除修复后用例会失败（非假绿）
  - [x] SubTask 5.2: iOS：`ios端/tests/test_edit_completed.py` 已覆盖已完成编辑保留、合并函数单测、落轮透传，并补齐草稿写盘→`load_draft` 往返与旧格式不变用例
  - [x] SubTask 5.3: 安卓：`安卓端/tests/test_edit_completed.py` 覆盖 `active_window`、`ui_tree_segment`、未知动作字段、草稿往返与旧格式不变
  - [x] SubTask 5.4: 终止类动作专项：四端均已覆盖（Windows 713/816 行、macOS 338 行、iOS 940 行、安卓 994 行），断言 `element == ""`、`status == "success"` 且步骤级受保护字段保留
  - [x] SubTask 5.5: 全量运行四端测试套件：Windows 102 passed、macOS 48 passed、iOS 132 passed、安卓 137 passed，合计 419 通过 / 0 失败，`test_data_integrity_defects.py` 等既有防污染测试无回归

# Task Dependencies
- Task 2 依赖 Task 1（以 Windows 改造为基准对齐）
- Task 4 依赖 Task 3（移动端双端同构，先 iOS 后安卓）
- Task 5 依赖 Task 1–4 完成；其中 SubTask 5.1/5.2/5.3 可在对应端改造完成后并行编写
