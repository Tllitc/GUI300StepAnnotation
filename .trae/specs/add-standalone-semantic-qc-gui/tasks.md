# Tasks

- [x] Task 1: 搭建独立程序骨架与模块容错导入
  - [x] SubTask 1.1: 新增 `qctools/qc_gui.py`，包含 `QApplication` / `QMainWindow` 入口与 `main()`，可独立 `python qc_gui.py` 启动；窗口标题、初始尺寸、基础布局（顶部输入/运行区、中部统计+明细 splitter、底部状态栏）
  - [x] SubTask 1.2: 顶部以容错方式 `import check_semantic_origin` / `check_semantic_v1`，用模块级标志记录可用性；失败时弹窗/标签提示原因并禁用运行与导出，窗口仍可打开

- [x] Task 2: 输入选择与后台质检 Worker
  - [x] SubTask 2.1: 提供「添加目录」「添加文件」「移除/清空输入」控件，维护输入路径列表并展示
  - [x] SubTask 2.2: 新增 `QThread` Worker：用 `check_semantic_origin.find_task_jsons` 收集文件并按 `seen` 去重；逐文件读取 → `to_pseudo_record` → `check_record`，并按 `check_semantic_origin.run` 同方式补 `extra_tasks` 任务文本检查；用 `group_key` / `task_label` 生成 group/task，产出与 CLI 同结构的 rows、stats、failed
  - [x] SubTask 2.3: Worker 通过信号回传进度（当前文件、已完成/总数）与最终结果；支持取消；单文件 try/except 计入 failed 不中断；运行中禁用运行按钮防重入，结束恢复

- [x] Task 3: 统计区
  - [x] SubTask 3.1: 分组汇总表（分组、任务数、有问题任务、`check_semantic_v1.CATS` 各类计数），列标题短名口径对齐 `check_semantic_origin.write_md` 的 short 表
  - [x] SubTask 3.2: 类别总数表（类别、数量）+ 顶部汇总行（分组数/任务总数/有问题任务数/解析失败数）；统计由 rows/stats 派生，保证与明细自洽

- [x] Task 4: 明细区与组合筛选
  - [x] SubTask 4.1: 明细表列：分组、任务、步号、截图文件、类别、描述、附加；步号 None 显示「任务级」；支持点列头排序
  - [x] SubTask 4.2: 筛选控件：类别下拉（取值 `CATS` + 全部）、分组下拉（动态填充 + 全部）、关键字框（匹配任务/描述/附加/截图名）；组合过滤并显示「筛选后/总」条数

- [x] Task 5: 报告导出
  - [x] SubTask 5.1: 「导出 md」用系统保存对话框选路径，调用 `check_semantic_origin.write_md(rows, stats, failed, out, title)`；「导出 json」写 `{rows, stats, failed}`（与 CLI `--json` 同结构）
  - [x] SubTask 5.2: 无结果时两个导出按钮禁用；导出成功/失败在状态栏提示

- [x] Task 6: 截图预览与源文件定位（只读）
  - [x] SubTask 6.1: 明细条目双击或右键菜单「预览截图」：按 gui json 所在目录拼接 `shot` 加载图片，文件缺失给友好提示，不崩溃
  - [x] SubTask 6.2: 右键菜单「在资源管理器中显示」：用 `QDesktopServices`/系统命令打开目录并选中 `gui_XXXXXX.json`；不提供任何编辑/保存入口

- [x] Task 7: 验证与打包配置
  - [x] SubTask 7.1: 用含已知问题的样本文件夹手测/冒烟：选择输入→运行→进度→统计→筛选→导出 md/json→截图预览→资源管理器定位全链路；与 `python check_semantic_origin.py <同输入>` 逐字段比对 rows（类别/步号/截图/描述/附加）一致
  - [x] SubTask 7.2: 验证模块缺失降级（模拟导入失败）窗口不崩溃且入口禁用；验证重复文件去重、单文件损坏不中断
  - [x] SubTask 7.3: 新增独立 `qctools/qc_gui.spec`（hiddenimports 含 `check_semantic_v1`、`check_semantic_origin`），不改动现有 `main.spec`；确认可打包启动

# Task Dependencies
- Task 2 depends on Task 1
- Task 3、Task 4 depend on Task 2
- Task 5 depends on Task 2
- Task 6 depends on Task 4
- Task 7 depends on Task 1 ~ Task 6
