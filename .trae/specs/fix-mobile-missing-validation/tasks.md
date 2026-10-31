# Tasks

> 端内任务按顺序执行；标注【可并行】的任务块两端之间无依赖，可派两个子代理并行。所有改动仅限各自端目录，不得改动另一端文件。实现完成后逐项勾选本文件。

- [x] Task 1:【安卓】动作数据构建保真：修改 `安卓端/annotation_editor.py` 的 `_build_action_data`、`_read_coordinate`、`_parse_number`
  - [x] 1.1 坐标解析失败/留空时返回"缺失"信号（如 None），builder 对 coordinate/start_coordinate/end_coordinate 整键省略，不写 `[0,0]`
  - [x] 1.2 scroll pixels 缺失/非法时省略 pixels 键，不写 0；time 动作缺失/非法时省略 time 键，不写 1.0
  - [x] 1.3 buttons 仅在选中有效系统按钮时写入；answer_terminate→"answer" 的既有映射保持不变
  - [x] 1.4 核查 `_build_coords_entry`（安卓侧 coords 导出）与 `_restore_step_to_ui`/历史回填对缺键的守卫，缺键时不抛异常、不产生该坐标条目

- [x] Task 2:【安卓】统一并强化缺项校验：改造 `validate_step_at` 与 `_validate_step`
  - [x] 2.1 `validate_step_at(index)` 支持 live 快照（index==current_step 且当前为编辑态时读 UI 实时值）与历史数据两种来源；复用 `_is_valid_number`/`_coord_invalid`
  - [x] 2.2 补齐判定：COORD_ACTIONS 坐标有限可解析；START_END_ACTIONS(swipe/drag) 起终点 + vertices 四点均有限数；scroll pixels 有限整数；TEXT_ACTIONS 非空；TIME_ACTIONS 有限时间；BUTTON_ACTIONS(system_button) 有效选择；截图关联存在
  - [x] 2.3 `_validate_step`（确认拦截）改为复用/对齐 `validate_step_at` live 结果，消除两口径分歧
  - [x] 2.4 非法输入（`abc`/NaN/Inf/空串）判缺且不抛异常

- [x] Task 3:【安卓】防抖输入联动与缓存失效
  - [x] 3.1 新增 300ms QTimer（对齐 iOS validation_timer 模式），连接意图、文本、时间、坐标 x/y、第二坐标、pixels、action_combo、button_combo 的变化信号
  - [x] 3.2 防抖回调：重算当前步（含 current_step==len 的未确认新步）缺项缓存、刷新侧栏条目与看板计数、刷新缩略图红框；缓存漂移时退化为全量重算
  - [x] 3.3 `go_previous`/`go_next`/`jump_to_step`/`_save_current_to_steps`/草稿定时保存落表后失效并重算被保存下标缓存（等长也重算）；修复 jump 目标==当前步静默无反馈（至少重算/刷新）
  - [x] 3.4 截图"常规覆盖"分支：清除旧坐标/vertices、重算该步、刷新侧栏并排草稿
  - [x] 3.5 看板"待完善"计数纳入未确认当前编辑步；移除/放宽 `refresh_dashboard` 中"缓存长度==总步数即不重算"的唯一闸门
  - [x] 3.6 排查 `_missing_cache` 全部重置点（重置/重开/切轮/删除/插入/结束等），保证长度与下标位移后全量重算

- [x] Task 4:【安卓】文案与结束校验
  - [x] 4.1 动作表 146 行 answer_terminate 括注英文修正（label 与动作名一致）
  - [x] 4.2 `_finish_task` 先保存当前步再对全部步（含未确认步）统一校验，ValidationFailDialog 中 answer_terminate 显示"回答并结束"等可区分名称
  - [x] 4.3 手工/脚本验证：wait 缺时间、click 缺坐标、scroll 缺像素、swipe 缺终点、system_button 缺选择五类脏数据均被结束拦截，且最终 JSON 不含伪造默认值

- [x] Task 5:【安卓】负向 pytest 用例：在 `安卓端/tests/` 新增用例（沿用既有 conftest/fakes/helpers）
  - [x] 5.1 wait/time 缺时间、scroll 缺 pixels、swipe/drag 缺终点或 vertices 含非有限数、click 缺坐标、system_button 缺选择 → 判缺且 JSON 无默认占位键
  - [x] 5.2 非法数字字符串判缺；补填后防抖重算使标记消失、计数递减
  - [x] 5.3 导航离步（上一步/下一步/跳转）后标记准确；删除/插入后下标不错位
  - [x] 5.4 未确认新步计入看板并被结束拦截；重截图覆盖清除旧坐标；旧草稿（含 1.0/[0,0]）可正常打开
  - [x] 5.5 全量既有测试 + INV 不变量通过（注意同步依赖 system_button 默认值的夹具）

- [x] Task 6:【iOS】动作数据构建保真：修改 `ios端/annotation_editor.py` 的 `_build_action_data`，并确认 `_build_coords_entry` 兼容
  - [x] 6.1 坐标缺失/非法省略 coordinate（不补 0）；swipe/drag 终点缺失省略 end_coordinate/相关键，不补 `[0,0]`
  - [x] 6.2 time 缺失/非法省略 time（不补 1.0）；pixels 缺失/非法省略（不补 0）；buttons 仅有效选择时写入
  - [x] 6.3 answer_terminate→"answer" 映射保持；`_build_coords_entry` 对缺键安全跳过（其以 `"key" in dict` 守卫，验证 start_coordinate 缺键时不走到解包）

- [x] Task 7:【iOS】统一并强化缺项校验：改造 `validate_step_at`、`_step_snapshot`、`_ui_has_value`
  - [x] 7.1 live 判定从"文本非空"升级为"可解析且有限"：移植安卓 `_is_valid_number`/`_coord_invalid` 等价逻辑（复用本端 `_parse_int/_parse_float`，拒绝 NaN/Inf/`abc`）
  - [x] 7.2 swipe：vertices 必须四点且每点坐标均为有限数，起终点可解析（不再只判 len==4 / list 长度）；scroll pixels 有限整数；time 有限；text 非空
  - [x] 7.3 system_button 增加 live 分支（读 button_combo），删除/修正 1942-1946 恒写 buttons 造成的死代码判定
  - [x] 7.4 截图关联缺失判缺；确认 `_validate`/确认拦截与结束拦截共用同一判定结论

- [x] Task 8:【iOS】防抖信号、守卫与缓存失效
  - [x] 8.1 `_connect_editor_validation_signals` 补连 button_combo
  - [x] 8.2 修正 `_on_validation_debounced` 的 `current_step < len(steps_data)` 守卫，使未确认新步（==len）也执行 live 校验并刷新看板
  - [x] 8.3 `display_step`/`go_previous`/`go_next`/`jump_to_step`/`_save_current_to_steps`/`delete_current_step`/`_finish_task` 落表后失效重算对应下标（等长也重算）；删除 pending 新步后强制重算
  - [x] 8.4 截图覆盖分支（1231-1237）：清除旧 vertices/坐标、重算缺项、刷新侧栏、schedule_draft_save
  - [x] 8.5 看板"缺填项"计数纳入未确认当前编辑步；`_refresh_item` 长度相等不再跳过重算

- [x] Task 9:【iOS】截图丢失、意图粘连与文案
  - [x] 9.1 `_restore_step_to_ui` 截图加载失败时进入截图缺失态（判缺、提示重截图），动作字段编辑不被静默丢弃、不误入 live 落表
  - [x] 9.2 on_action_changed：terminate 自动填入的"任务完成"意图在切离 terminate 时恢复/清空，不污染他步；结束校验对话框 answer_terminate 显示名可区分
  - [x] 9.3 answer 确认后 300ms singleShot 切轮窗口期校验状态一致（切轮前缺项结论不丢失/不串步）

- [x] Task 10:【iOS】负向 pytest 用例：在 `ios端/tests/` 新增用例
  - [x] 10.1 wait/long_press 缺时间、scroll 缺 pixels、swipe 缺终点/vertices 非有限数、click 缺坐标、system_button 缺选择 → 判缺且无伪造默认键
  - [x] 10.2 live 输入 `abc`/NaN/Inf 判缺；补填后防抖更新；未确认新步计入计数并被结束拦截
  - [x] 10.3 重截图覆盖清旧坐标并排草稿；截图文件丢失恢复为缺项态；terminate 意图不污染他步
  - [x] 10.4 旧草稿（含默认值）可打开；全量既有测试 + INV-1~10 不变量通过（同步 helpers 中 system_button 默认值相关夹具）

# Task Dependencies

- Task 2 依赖 Task 1；Task 3 依赖 Task 2；Task 4/5 依赖 Task 3（安卓端内串行）。
- Task 7 依赖 Task 6；Task 8 依赖 Task 7；Task 9/10 依赖 Task 8（iOS 端内串行）。
- 安卓链（Task 1→5）与 iOS 链（Task 6→10）【可并行】，派两个子代理同时实施。
- 最终跨端回归（两侧 pytest 全绿 + 手工结束拦截抽验）在两条链均完成后统一进行。
