# Tasks

- [x] Task 1: 标题行折叠控件
  - [x] SubTask 1.1: 将语义面板标题行封装为独立 header 控件（便于计算标题行高度），左侧新增 QToolButton 折叠按钮（flat、固定尺寸、初始 ▾），保留「语义问题（N）」计数与右侧「双击卡片跳转」提示
  - [x] SubTask 1.2: `_apply_styles` 增加折叠按钮样式（透明背景、hover 高亮、字号与对齐与标题协调）
  - [x] SubTask 1.3: 按钮点击与标题文字点击均连接到 `_toggle_qc_panel`

- [x] Task 2: 折叠/展开逻辑与分栏适配
  - [x] SubTask 2.1: 新增 `_qc_collapsed`、`_qc_last_height` 状态；`_toggle_qc_panel` 切换 chips 行与卡片滚动区可见性、按钮文本/tooltip、右侧提示可见性
  - [x] SubTask 2.2: 折叠时记录当前面板高度、将面板最大高度限制为标题行高度并设置分栏高度；展开时清除最大高度限制并恢复记录高度（≥120px）
  - [x] SubTask 2.3: `_fit_instruction_pane` 三栏分支按折叠态取语义面板高度（折叠=标题行高度，展开=原逻辑）

- [x] Task 3: 折叠状态持久化
  - [x] SubTask 3.1: `_restore_window_state` 读取 `ui/qc_collapsed`，在分栏状态恢复后应用折叠态（仅切换可见性与高度限制，不覆盖已恢复的尺寸）
  - [x] SubTask 3.2: `_save_window_state` 写入 `ui/qc_collapsed`

- [x] Task 4: 验证
  - [x] SubTask 4.1: offscreen 冒烟验证：默认展开；折叠后 chips 与滚动区隐藏、按钮为 ▸；展开后恢复可见且高度还原
  - [x] SubTask 4.2: 验证折叠态下窗口缩放后语义面板高度等于标题行高度，JSON 树获得剩余空间
  - [x] SubTask 4.3: 验证折叠状态保存后可被设置项读回，且手动启动应用时暗色样式、筛选与双击跳转无回归

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 2
- Task 4 depends on Task 1 ~ Task 3