# Checklist

- [x] 安卓端 `_on_screenshot_finished` 普通覆盖分支不再调用 `rebuild_items()`，仅原地刷新当前条目（含缩略图失效重载）与看板
- [x] 安卓端 `confirm_step` 末尾追加路径改为增量 `_create_item`，不再全量重建
- [x] 安卓端中间插入/删除/撤销/轮次切换/续采路径仍调用 `rebuild_items()`，条目序号与下标一一对应
- [x] 安卓端 `refresh_step_item` 不再无条件重置 `thumb_loaded`，截图/vertices 未变时缩略图不重新读盘或排队
- [x] 安卓端截图覆盖当前步后，该条目缩略图显示的是新截图（旧文件名缓存被失效）
- [x] iOS 端 `refresh_step_item` 的缺项判断读缓存，不再每步直接调用 `validate_step_at`
- [x] iOS 端 `refresh_dashboard` 不再对全部步骤循环调用 `validate_step_at`，待完善计数与动作分布与改动前一致
- [x] iOS 端缓存失效点（确认/删除/插入/输入防抖/轮次切换）后缺项标记和看板计数正确
- [x] 安卓端 100+ 步后连续截图与确认进入下一步不再出现等待列表刷新的卡死（热路径为 O(1) 增量）
- [x] iOS 端 100+ 步后触发全量重建（插入/删除/切轮/续采）无平方级重复校验导致的卡顿
- [x] `安卓端/tests` pytest 全部通过
- [x] `ios端/tests` pytest 全部通过
- [x] 未改动 draft / 最终 JSON / coords 数据格式
