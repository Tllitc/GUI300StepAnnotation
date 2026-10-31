# Tasks

- [x] Task 1: 安卓端截图/确认热路径改为增量刷新
  - [x] SubTask 1.1: 修改 `_on_screenshot_finished`：普通"覆盖当前步"分支不调用 `rebuild_items()`，改为失效当前步缩略图缓存（`invalidate_thumb`/`remove_thumb_cache_by_filename`）+ `refresh_step_item(current_step)` + 高优先级 `request_thumb(current_step)` + `refresh_highlight` + `refresh_dashboard`
  - [x] SubTask 1.2: 修改 `_on_screenshot_finished`：中间插入分支保留全量重建（下标整体变化），或改用插入单条目并对其后条目 `set_index` 重编号（优先保留全量重建以降低风险）
  - [x] SubTask 1.3: 修改 `confirm_step`：末尾追加新步时不调用 `rebuild_items()`，改为 `_create_item(new_index)` 追加（条目数不足时）+ `refresh_highlight` + `refresh_dashboard`，参照 Windows 端 `refresh_sidebar(fully=False)`
  - [x] SubTask 1.4: 删除、撤销、轮次切换（`_start_new_round`/`_start_new_task`）、`load_from_draft` 等结构性变化路径保留 `rebuild_items()` 不变

- [x] Task 2: 安卓端修正 refresh_step_item 的缩略图重复加载
  - [x] SubTask 2.1: 移除 `SideBarWidget.refresh_step_item` 末尾无条件的 `item.thumb_loaded = False` 与 `request_thumb`
  - [x] SubTask 2.2: 需要刷新缩略图的调用方（截图覆盖/vertices 变化）显式走 `invalidate_thumb(index)` + `request_thumb(index, high_priority=...)`；确认其余调用点（rebuild、状态变化）行为正确
  - [x] SubTask 2.3: 检查 `_create_item`/`rebuild_items` 后新条目仍能正常懒加载缩略图

- [x] Task 3: iOS 端消除全量重建路径的重复实时校验
  - [x] SubTask 3.1: 修改 `SideBarWidget.refresh_step_item`：缺项判断改为读取 `_missing_cache`（新增/复用一个 `get_cached_missing(index)` 访问器），仅当缓存长度与步数不一致时触发一次 `revalidate_all_missing()`，不再对每步直接调用 `validate_step_at`
  - [x] SubTask 3.2: 修改 `SideBarWidget.refresh_dashboard`：待完善计数与动作分布改读 `_missing_cache` 快照，删除其内部对全部步骤循环调用 `validate_step_at` 的逻辑；缓存失效时同样由 `revalidate_all_missing` 兜底
  - [x] SubTask 3.3: 确认数据变化点（确认、删除、插入、输入防抖 `_on_validation_debounced`、轮次切换重置 `_missing_cache=[]`）后缓存会被正确重算，缺项标记与看板计数与现状一致

- [x] Task 4: 回归验证
  - [x] SubTask 4.1: 运行安卓端 `安卓端/tests` 既有 pytest 全部通过
  - [x] SubTask 4.2: 运行 iOS 端 `ios端/tests` 既有 pytest 全部通过
  - [x] SubTask 4.3: 静态走查：安卓端常规截图覆盖、末尾追加确认、中间插入、删除、撤销、续采六条路径的侧栏条目数/序号/高亮/缩略图正确性；iOS 端相同路径缺项标记与看板计数正确性

# Task Dependencies

- Task 2 可与 Task 1 同文件改动，建议在 Task 1 之后顺序进行以避免冲突
- Task 3 独立于 Task 1/2，可并行
- Task 4 依赖 Task 1、2、3 全部完成
