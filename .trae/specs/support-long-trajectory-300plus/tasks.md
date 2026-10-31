# Tasks

- [x] Task 1: 截图内存解耦：移除步骤对全屏原图的常驻持有，预览图改为按磁盘文件加载缩放
  - [x] SubTask 1.1: `on_capture_completed` / `on_recapture_completed` 中不再向 step 写入 `original_pixmap`，截图落盘后用文件路径加载带框预览（可临时在内存中生成 marked 预览一次后释放原图）
  - [x] SubTask 1.2: 历史步骤切换/重建时，通过 gui 目录截图文件按预览区尺寸缩放加载图片；确认 300 步场景下内存不随步数增长

- [x] Task 2: 增量自动保存（draft 工作态）
  - [x] SubTask 2.1: 在 `DataManager` 增加 `save_draft(draft, gui_number)` 与 `load_draft(gui_dir)`（读写 `gui_xxxxxx_draft.json`）
  - [x] SubTask 2.2: `AnnotationEditor` 增加约 1 秒防抖的 draft 写出方法，覆盖 rounds、当前轮步骤（含截图文件名、rect_info、selection_type、编辑器动作数据）、coords entries、instruction、screen_info、app_type、更新时间
  - [x] SubTask 2.3: 在确认步骤（防抖）、answer/terminate 轮次切换、关窗保存处触发 draft 写入；最终 JSON 成功写出后删除 draft

- [x] Task 3: 断点续采入口与状态重建
  - [x] SubTask 3.1: `main.py` 初始化窗口增加"继续未完成任务"按钮，弹窗选择 gui 目录并校验 draft
  - [x] SubTask 3.2: `DataManager` 增加按 gui 目录扫描/定位 draft 的能力（修复现有 `load_json_data` 路径拼错、gui 编号目录层级问题）
  - [x] SubTask 3.3: `AnnotationEditor` 增加从 draft 重建 rounds/步骤编辑器/截图预览/coords/gui_number 的加载流程，定位到最后一步，新截图序号正确递增

- [x] Task 4: 步骤导航侧栏与进度看板
  - [x] SubTask 4.1: 主布局改为左右结构（左侧栏 + 右侧编辑区），侧栏为可滚动步骤列表：序号、磁盘缩略图、动作类型、完成状态标记
  - [x] SubTask 4.2: 点击条目跳转对应步骤；增加"跳转到第 N 步"输入框与上一步/下一步键盘快捷键
  - [x] SubTask 4.3: 侧栏顶部进度看板：任务指令、总步数、已完成/未完成、动作类型分布、最近自动保存时间
  - [x] SubTask 4.4: 步骤数据变化后增量刷新受影响条目（缩略图从磁盘缩放加载，避免全屏图常驻）

- [x] Task 5: 中间步骤删除与插入
  - [x] SubTask 5.1: 工具栏增加"删除当前步骤"，删除编辑器页与截图文件，后续步骤 step 连续重编号
  - [x] SubTask 5.2: 工具栏增加"在此步后插入截图"，完成拉框后新步骤插入当前位置之后，原后续步骤顺延（截图文件用新递增序号）
  - [x] SubTask 5.3: 重建 coords entries 的 step 索引，保证最终 coords JSON 与实际步骤对齐

- [x] Task 6: 必填项校验
  - [x] SubTask 6.1: 实现按动作类型的单步校验规则（动作描述 / 坐标 / 按键 / 等待时间 / 文本），返回缺失项描述
  - [x] SubTask 6.2: 侧栏条目与进度看板接入校验结果，实时标记缺失步骤
  - [x] SubTask 6.3: terminate/answer_terminate 结束前执行全量校验，弹出缺失清单并支持点击跳转到目标步骤

- [x] Task 7: 顺手修复与整体验证
  - [x] SubTask 7.1: 修复 `main.py` 中 `create_task_directory("mac", ...)` 平台参数硬编码，按 `sys.platform`/DataManager 系统标识传真实平台
  - [x] SubTask 7.2: 手工冒烟：新建任务 → 采集若干步 → 强杀进程 → 续采恢复一致；中间删除/插入后编号连续；300 步模拟下内存平稳；正常完成后 draft 被清理、最终 JSON/coords 格式不变

# Task Dependencies
- Task 2 依赖 Task 1（draft 数据结构以解耦后的步骤模型为准）
- Task 3 依赖 Task 2（续采读取 draft）
- Task 4 依赖 Task 1（侧栏缩略图按需从磁盘加载）
- Task 5 依赖 Task 4（删除/插入后的定位与列表刷新复用导航侧栏）
- Task 6 依赖 Task 4（缺失标记与缺失清单跳转复用侧栏）
- Task 7 依赖 Task 1–Task 6
- Task 1 与 Task 4 的布局改造可并行起步
