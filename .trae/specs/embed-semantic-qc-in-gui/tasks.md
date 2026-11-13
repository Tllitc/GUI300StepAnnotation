# Tasks

- [x] Task 1: 模块导入与质检结果数据结构
  - [x] SubTask 1.1: 在 main.py 顶部以容错方式导入 `check_semantic_origin`（间接带出 `check_semantic_v1`），用模块级标志记录导入是否成功，失败不影响启动
  - [x] SubTask 1.2: 定义每个任务的质检结果容器（按 gui json 绝对路径存放：问题条目列表、解析失败标志、类别计数），以及「当前文件夹结果版本号」用于作废过期后台任务

- [x] Task 2: 后台质检线程与触发入口
  - [x] SubTask 2.1: 新增 QThread/Worker，输入文件夹与文件清单，逐文件读取 → `to_pseudo_record` → `check_record`（含 extra_tasks 任务文本检查，口径对齐 `check_semantic_origin.run`），单文件异常捕获为解析失败
  - [x] SubTask 2.2: Worker 通过信号回传进度与完整结果；主线程收到结果后按版本号判断是否过期，过期则丢弃
  - [x] SubTask 2.3: 顶部工具栏新增「语义质检」按钮，连接手动重跑；未加载文件夹或模块缺失时禁用，运行中显示进行中状态并防重入
  - [x] SubTask 2.4: `_load_json_files` 成功后自动触发一次后台质检；重新加载文件夹时作废旧结果

- [x] Task 3: 任务列表内联标记
  - [x] SubTask 3.1: 结果就绪后刷新 `_task_list` 项文本/配色：有问题（前缀+问题数+警示色）、解析失败（独立前缀+警示色）、无问题（默认样式），保留原文件名与任务名信息
  - [x] SubTask 3.2: tooltip 按 `check_semantic_v1.CATS` 全称展示该任务各类别条数；运行中未出结果的任务不显示任何问题标记

- [x] Task 4: 伪步序号 → GUI 页面映射
  - [x] SubTask 4.1: 在 `_build_pages` 完成后，按 `to_pseudo_record` 同规则遍历 messages/trajectory，跳过 screenshot 合成步连续编号，记录伪步号 → `_pages` 索引与截图文件名的映射，挂在当前任务上下文
  - [x] SubTask 4.2: 提供按伪步号取 GUI 页索引的查询方法，映射缺失时返回 None 而不抛异常

- [x] Task 5: 问题明细面板与双击跳转
  - [x] SubTask 5.1: 在右侧栏（JSON 树下的纵向 splitter 中）或任务列表下方新增问题明细控件，列：类别 / 步号 / 截图文件 / 描述 / 附加
  - [x] SubTask 5.2: `_on_task_selected` 中按当前文件路径填充该任务的问题条目；无问题/解析失败/质检进行中分别有空态文案
  - [x] SubTask 5.3: 双击条目：有步号经映射设置 `_current_page_index` 并 `_display_current_page`（必要时先切换任务）；步号 None 仅保证任务已选中；映射缺失给轻量提示

- [x] Task 6: 保存后增量重检
  - [x] SubTask 6.1: `_on_save` 写盘成功后对当前单任务同步/短线程重跑同一检查链路，原子替换该任务结果
  - [x] SubTask 6.2: 刷新该任务的列表标记、tooltip 与明细面板；重检解析失败时标记失败态并提示，其他任务不动

- [x] Task 7: 打包配置与验证
  - [x] SubTask 7.1: 更新 main.spec 的 `hiddenimports` 为 `['check_semantic_v1', 'check_semantic_origin']`
  - [x] SubTask 7.2: 选一个含已知问题的交付文件夹手测：自动质检、手动重跑、列表标记、tooltip、明细、双击跳转（含合成步任务与任务级问题）、保存后标记消失、模块缺失降级（以 offscreen 冒烟测试覆盖全部断言，真实数据待 NAS 文件夹人工抽验）
  - [x] SubTask 7.3: 与命令行 `python check_semantic_origin.py <文件夹>` 对照，核对问题类别/步号/描述口径一致（冒烟测试中逐字段集合比对通过）

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 2
- Task 5 depends on Task 3、Task 4
- Task 4 可与 Task 2、Task 3 并行
- Task 6 depends on Task 2、Task 4
- Task 7 depends on Task 1 ~ Task 6
