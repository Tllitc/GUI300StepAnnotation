# 修复安卓/iOS 端长轨迹截图列表刷新卡死 Spec

## Why

安卓端与 iOS 端在单任务达到 100 步以后，每次截图完成或确认进入下一步，左侧步骤截图列表都会触发主线程同步的全量刷新，界面整体卡住直到刷新结束；步数越多卡顿越严重。Windows 端因使用增量刷新不会出现该问题。

根因（与 Windows 端 [annotation_editor.py](../../annotation_editor.py) 的 `refresh_sidebar(fully=False)` 对比）：

- **安卓端**：截图完成回调 `_on_screenshot_finished` 与确认下一步 `confirm_step` 在"追加/覆盖"热路径上无条件调用 `self.sidebar.rebuild_items()`（[安卓端 annotation_editor.py:1794](../../安卓端/annotation_editor.py)、[:2026](../../安卓端/annotation_editor.py)）。`rebuild_items()` 每次销毁全部 N 个 `StepListItemWidget` 并重新 new 出 N 个控件、重排布局。连续采集 N 步的累计开销为 O(N²)，100+ 步后单次重建上百个 widget 即表现为可感知的卡死。此外 `SideBarWidget.refresh_step_item` 每次都执行 `item.thumb_loaded = False` 并重新 `request_thumb`，使单条目刷新也反复进入缩略图加载队列。
- **iOS 端**：确认追加路径已部分增量（`confirm_step` 中 `_create_item` 追加），但 `rebuild_items()` 内对每个条目调用的 `refresh_step_item` 直接执行无缓存的 `self.editor.validate_step_at(index)`，且 `refresh_dashboard()` 又对全部步骤再执行一遍 `validate_step_at`。因此在插入、删除、撤销、轮次切换、断点续采等触发全量重建的路径上，100+ 步时产生大量重复实时校验（重建 O(N) + 看板 O(N) 校验/次），同样造成主线程卡顿。

## What Changes

- **安卓端热路径改为增量刷新**：截图"覆盖当前步"与"确认追加下一步"不再调用 `rebuild_items()`：
  - 覆盖当前步（普通重复截图）：仅刷新当前条目状态并失效/重载该步缩略图与看板；
  - 末尾追加新步：仅 `_create_item` 追加一个新条目 + `refresh_highlight` + `refresh_dashboard`（与 Windows 端一致）。
- **安卓端修正 `refresh_step_item` 的缩略图行为**：单条目刷新不再无条件 `thumb_loaded = False`；仅在截图文件名/vertices 变化（缓存 key 变化）时失效缓存并重载，避免重复入队与读盘。
- **全量重建仅保留给真正的结构性变化**：中间插入、删除、撤销、轮次切换、断点续采等步骤集合或下标整体变化的场景继续使用 `rebuild_items()`（行为不变）。
- **iOS 端消除重建路径的重复校验**：`refresh_step_item` 与 `refresh_dashboard` 的缺项判断统一走缺项缓存（`_missing_cache` / `get_cached_missing`），缓存长度与步数不一致时由既有的 `revalidate_all_missing` 兜底重算一次；单次刷新不再对每一步实时调用 `validate_step_at`。
- 不改变任何数据文件（draft / 最终 JSON / coords）格式，不改变缩略图 LRU 缓存容量与分批懒加载机制。

## Impact

- Affected specs: 长轨迹快速导航（侧栏刷新）、必填项校验（缺项标记/看板计数）
- Affected code:
  - `安卓端/annotation_editor.py`：`SideBarWidget.refresh_step_item`、`AnnotationEditor._on_screenshot_finished`、`confirm_step`
  - `ios端/annotation_editor.py`：`SideBarWidget.refresh_step_item`、`SideBarWidget.refresh_dashboard`（缺项读取改为缓存）

## MODIFIED Requirements

### Requirement: 侧栏刷新与步数解耦（移动端）

系统 SHALL 保证：在不改变步骤集合（仅追加末尾一步或覆盖当前步截图）的常规采集热路径上，侧栏不得销毁/重建已有步骤条目控件，只允许增量创建新增的那一个条目或原地刷新被覆盖的那一个条目，单次操作的 UI 开销与当前总步数无关（O(1)）。步骤集合发生结构性变化（中间插入、删除、撤销导致下标整体平移、轮次切换清空、断点续采恢复）时才允许全量 `rebuild_items()`。

#### Scenario: 安卓端 100+ 步后连续截图不卡顿

- **WHEN** 用户在安卓端已采集 100+ 步后继续对当前步重复截图、并确认进入下一步
- **THEN** 侧栏仅原地刷新当前条目并在末尾增量追加一个条目，界面不出现等待列表重建完成的卡死

#### Scenario: 结构性变化后列表仍正确

- **WHEN** 用户在安卓/iOS 端执行中间插入、删除任意步、撤销或切换轮次、断点续采恢复
- **THEN** 侧栏条目序号、高亮、动作类型、缺项标记、缩略图与步骤数据保持一一对应，无重复条目、无错位

### Requirement: 单条目刷新不重复加载缩略图（安卓端）

系统 SHALL 仅在某步骤的截图文件名或标注 vertices 相对已加载缩略图发生变化时，才失效该条目缩略图并重新进入懒加载队列；动作类型、状态、缺项标记等文本刷新不得把已加载的缩略图标记为未加载。

#### Scenario: 状态刷新不触发缩略图重读

- **WHEN** 仅当前步的动作描述/状态发生变化而截图与 vertices 未变
- **THEN** 该条目缩略图保持原样，不重新读盘、不重新排队加载

### Requirement: 缺项校验结果在刷新路径上有界复用（iOS 端）

系统 SHALL 使侧栏条目与进度看板的缺项判断统一读取缺项缓存；缓存缺失或长度与步数不一致时，由一次全量重算（`revalidate_all_missing`）填充后复用。全量重建侧栏这一单次操作中，对每一步的实时校验不得多于一次，看板不得再对全部步骤重复实时校验。

#### Scenario: iOS 端全量重建在 100+ 步时不卡顿

- **WHEN** 用户在 iOS 端 100+ 步后触发插入/删除/轮次切换/续采导致侧栏全量重建
- **THEN** 缺项标记与看板计数正确显示，且重建过程中不存在随步数平方级增长的重复实时校验
