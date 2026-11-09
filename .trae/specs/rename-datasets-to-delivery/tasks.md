# Tasks

- [x] Task 1: 实现核心数据模型与 Excel 解析（`datasubtool/core.py`）
  - [x] SubTask 1.1: 定义 `TaskRow`（excel 行号、日期、平台原始值、平台目录名、采集人员、原文件夹编号、源目录）与 `PlanItem`（新编号、输出目录）数据结构
  - [x] SubTask 1.2: 用 openpyxl 读取第一个工作表，按列名定位 `平台`、`采集人员`、`文件夹编号`；缺列时抛出可读错误
  - [x] SubTask 1.3: 实现平台归一化：与母目录平台目录名精确/大小写不敏感匹配，再按别名表（安卓/Android、ios/IOS→iOS、Mac/macos、windows/Windows）匹配，无法识别时记录错误

- [x] Task 2: 实现转换规划与冲突预检（`datasubtool/core.py`）
  - [x] SubTask 2.1: 按平台分组、组内保持 Excel 行序，为每条分配 `gui_%06d` 新编号（每平台从 1 起）
  - [x] SubTask 2.2: 预检：源目录存在性、Excel 重复源目录、目标 `平台/新编号` 目录是否已存在；汇总错误列表
  - [x] SubTask 2.3: 任一项预检错误时返回失败结果且不产生任何文件写入

- [x] Task 3: 实现数据集复制、文件重命名与 JSON 引用改写（`datasubtool/core.py`）
  - [x] SubTask 3.1: 递归复制源数据集到目标目录，文件名以原编号开头的前缀替换为新编号
  - [x] SubTask 3.2: 对 `.json` 文件按文本方式把 `原编号_`、`原编号.` 形式引用替换为新编号，保持其余内容与排版不变
  - [x] SubTask 3.3: 提供逐数据集进度回调与取消标记；单个数据集失败时记录错误并继续

- [x] Task 4: 实现映射表输出（`datasubtool/core.py`）
  - [x] SubTask 4.1: 在目标目录写出 `数据集映射表_<时间戳>.xlsx`，列：序号、平台、采集人员、原文件夹编号、新编号、源目录、输出目录、状态、备注
  - [x] SubTask 4.2: 支持成功/失败/未处理（取消）三类状态写入

- [x] Task 5: 实现 PyQt5 界面（`datasubtool/app.py`）
  - [x] SubTask 5.1: 三个路径选择控件（默认预填同目录 `长步骤交付.xlsx`）、开始/取消按钮、进度条、日志区
  - [x] SubTask 5.2: 用 `QThread` 执行转换，通过信号回传日志/进度/结束事件，转换中禁用开始按钮并允许取消
  - [x] SubTask 5.3: 参数校验、预检错误与最终结果（成功数/失败数/映射表路径）的界面提示

- [x] Task 6: 编写 pytest 单元测试（`datasubtool/tests/test_core.py`）
  - [x] SubTask 6.1: 用 tmp_path 构造最小数据集（json、coords、两张 png）与临时 Excel，覆盖解析、平台归一化、编号分配
  - [x] SubTask 6.2: 覆盖重复条目、源目录缺失、目标冲突三类中止场景（断言目标目录无新增内容）
  - [x] SubTask 6.3: 覆盖复制重命名、JSON 引用改写、映射表列与状态

- [x] Task 7: 联调验证
  - [x] SubTask 7.1: 运行 `pytest datasubtool/tests` 全部通过
  - [x] SubTask 7.2: 用真实 Excel + NAS 母目录复制 1~2 条数据到临时目标目录，核对文件名、json 引用、映射表，并确认源目录未被修改

- [x] Task 8: 按平台填写起始序号
  - [x] SubTask 8.1: `core.build_plan` 增加 `start_numbers`，按平台起始值编号并校验非法值
  - [x] SubTask 8.2: 新增 `core.detect_platforms` 供界面探测命中平台
  - [x] SubTask 8.3: 界面增加「命中平台起始序号」表格，随 Excel/母目录刷新、保留已填值，并传入工作线程

- [x] Task 9: 数据集文件白名单过滤
  - [x] SubTask 9.1: 新增 `core.is_dataset_file`，仅识别 `<id>.json`、`<id>_<数字>.png`（`_coords.json` 不在白名单）
  - [x] SubTask 9.2: `_convert_item` 只复制白名单文件，日志记录跳过的非数据集文件；无白名单文件时标记失败并清理空目录
  - [x] SubTask 9.3: 更新测试并新增白名单、起始序号、空数据集用例

# Task Dependencies

- Task 2 依赖 Task 1
- Task 3、Task 4 依赖 Task 2
- Task 5 依赖 Task 2、Task 3、Task 4
- Task 6 依赖 Task 1~4
- Task 7 依赖 Task 5、Task 6
- Task 8、Task 9 依赖 Task 1~7（在已完成工具上增量扩展）