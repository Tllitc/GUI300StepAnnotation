# Tasks
- [x] Task 1: Windows 端参考实现与测试（根目录 annotation_editor.py、tests/）
  - [x] 1.1 载入：按 gui_{num}_coords.json 实际存在性判定；_original_coords_exist=文件存在；缺失分支仅一条信息性提示弹窗，不注册 absent 问题、不弹逐步告警、不追加状态栏；rect_info=None、coordinate 按 JSON 显示、允许重新拉框
  - [x] 1.2 保存（含 silent=True）：缺失 → 无条件跳过 coords 写盘；存在 → B41/审计/round 注入/格式不变；最终 JSON 写路径不变
  - [x] 1.3 tests/test_edit_completed.py 新增用例：缺失打开无告警 / 仅改文本保存不生成 coords / 拉框保存 coordinate 更新且不生成 coords / silent 关闭同 / 空文件按存在处理
  - [x] 1.4 根目录运行 `python -m pytest tests -q` 全绿（113 passed，主会话复核）
- [x] Task 2: macos 端对齐实现与测试（macos端/）
  - [x] 2.1 载入判定与提示对齐 1.1（本端 entry_coordinate_mismatch 判定逻辑不改）
  - [x] 2.2 保存守卫对齐 1.2（纯数组格式不变）
  - [x] 2.3 macos端/tests/test_edit_completed.py 新增与 1.3 同五组用例；macos端 运行 `python -m pytest tests -q` 全绿（93 passed，主会话复核）
- [x] Task 3: ios 端对齐实现与测试（ios端/）
  - [x] 3.1 载入判定与提示对齐 1.1
  - [x] 3.2 保存守卫对齐 1.2：缺失时不得走 _build_coords_entry 的 JSON coordinate 兜底退化框 [x,y,x,y] 写盘分支
  - [x] 3.3 ios端/tests/test_edit_completed.py 新增与 1.3 同五组用例；ios端 运行 `python -m pytest tests -q` 全绿（153 passed，主会话复核；含 _edit_mode 门控的校验豁免补充）
- [x] Task 4: 安卓端对齐实现与测试（安卓端/）
  - [x] 4.1 载入判定与提示对齐 1.1
  - [x] 4.2 保存守卫对齐 1.2：缺失时不得走 original_coords[i] 下标回退写盘分支
  - [x] 4.3 安卓端/tests/test_edit_completed.py 新增与 1.3 同五组用例；安卓端 运行 `python -m pytest tests -q` 全绿（149 passed，主会话复核 680.64s；含 _edit_mode 门控的校验豁免补充）
- [x] Task 5: 四端全量回归与 checklist 验收
  - [x] 5.1 四端各自运行全量测试，全绿（Windows 113 / macos 93 / ios 153 / 安卓 149，均主会话复核）
  - [x] 5.2 逐项核对 checklist.md 并勾选：含 coords 数据集行为不变、正常采集/完成/草稿流程与入口按钮不变（既有用例零改动全绿；豁免仅编辑态生效；main.py/入口按钮未改）

# Task Dependencies
- Task 2 / Task 3 / Task 4 依赖 Task 1（以 Windows 为参考实现），三者相互独立可并行
- Task 5 依赖 Task 2 / Task 3 / Task 4