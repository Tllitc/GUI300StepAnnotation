# GUI 内嵌语义质检 Spec

## Why

B/C/D 语义质检目前只能通过命令行 `python check_semantic_origin.py` 运行，产出 md/json 报告后人工再回到 GUI 工具里逐个找任务、找步骤修复，链路割裂。`main.py` 的 GUI 质检工具已具备文件夹加载、任务列表、截图翻页、JSON 编辑保存能力，把语义质检嵌入其工作流后，可在同一界面完成「发现问题 → 定位任务/步骤 → 编辑修复 → 重新质检」闭环。

## What Changes

- 在 `main.py` 中复用 `check_semantic_origin.to_pseudo_record` 与 `check_semantic_v1.check_record`，对当前数据文件夹下的 `gui_XXXXXX.json` 执行与命令行完全同口径的 B/C/D 语义质检（不重复实现检查规则）。
- 顶部工具栏新增「语义质检」按钮：可手动对当前文件夹重跑质检；同时在加载文件夹后自动在后台运行一次。
- 质检在后台线程执行，避免冻结 UI；运行期间按钮显示进行中状态并禁用重复触发。
- 左侧任务列表对有问题的任务做内联标记（文本前缀 + 红色系前景/背景），并在 tooltip 中展示问题类别计数；无问题任务与解析失败任务有可区分状态。
- 新增任务级问题明细面板：选中任务后展示该任务的全部问题条目（类别、步号、截图名、描述、附加信息），双击条目跳转到对应 GUI 页面；任务级问题（步号为 None，如反引号/换行）只定位到任务。
- 建立语义质检「伪步序号」（跳过 `actions[0].action=="screenshot"` 合成步后从 0 连续编号）到 GUI `_pages` 索引的映射，保证跳转落点正确。
- 保存修复后，自动对当前任务增量重检并更新该任务的标记与明细（不重跑整批）。
- 更新 `main.spec` 的 `hiddenimports`，保证 PyInstaller 打包后能导入 `check_semantic_v1` / `check_semantic_origin`；模块导入失败时按钮可用但给出明确提示，不影响原有功能。
- 不在 GUI 内提供 md/json 报告导出（导出仍走命令行脚本）；不新增任何文件输出。

## Impact

- Affected specs: GUI 任务加载与浏览、任务保存、PyInstaller 打包交付。
- Affected code:
  - `qctools/main.py`（主要改动：工具栏、任务列表标记、问题明细面板、后台线程、伪步→GUI 页映射、保存后增量重检、模块导入）。
  - `qctools/main.spec`（`hiddenimports` 增加 `check_semantic_v1`、`check_semantic_origin`）。
  - 复用但不修改：`qctools/check_semantic_origin.py`、`qctools/check_semantic_v1.py`。
- 数据安全：质检全程只读，不修改任何 JSON / 截图；写盘仍只由现有「保存」按钮完成。
- 非 BREAKING：模块缺失或质检异常时，GUI 原有加载/浏览/编辑/保存流程不受影响。

## ADDED Requirements

### Requirement: 文件夹语义质检触发

系统 SHALL 在用户通过「浏览...」成功加载一个数据文件夹后，自动对该文件夹启动一次语义质检；并在顶部工具栏提供「语义质检」按钮，允许用户随时对当前文件夹手动重跑。未加载任何文件夹时按钮禁用。

#### Scenario: 加载后自动质检
- **WHEN** 用户选择文件夹且任务列表加载完成
- **THEN** 后台自动开始语义质检，按钮变为进行中状态，任务列表在结果就绪后被标记，期间用户可正常浏览已加载的任务

#### Scenario: 手动重跑
- **WHEN** 用户点击「语义质检」按钮
- **THEN** 对当前文件夹重新执行全量质检并刷新全部标记与明细；已有旧结果在新结果就绪前继续展示

#### Scenario: 运行中防重入
- **WHEN** 质检正在运行时用户再次点击按钮或重新加载文件夹
- **THEN** 不启动并发的第二个质检任务；新文件夹的加载会让旧任务结果作废，旧任务结束后其结果不写入 UI

### Requirement: 后台线程执行与不冻结 UI

系统 SHALL 在非 UI 线程中执行质检（文件读取、`to_pseudo_record`、`check_record` 均为 CPU/IO 操作），通过 Qt 信号把进度与最终结果回传 UI 线程；任何单个文件解析异常 SHALL 被捕获并计入「解析失败」，不中断整批质检。

#### Scenario: 大文件夹不卡顿
- **WHEN** 文件夹包含大量任务
- **THEN** 质检过程中窗口可拖动、任务可选中、截图可翻页，界面不出现无响应

#### Scenario: 单文件损坏
- **WHEN** 某个 gui JSON 无法解析或 `to_pseudo_record` 抛异常
- **THEN** 该文件计入解析失败清单并在 UI 上有可识别提示，其余任务质检结果正常产出

### Requirement: 与命令行同口径的检查复用

系统 SHALL 直接调用 `check_semantic_origin.to_pseudo_record(data)` 得到 `(rec, shots, extra_tasks)`，对 `rec` 调用 `check_semantic_v1.check_record`，并对 `extra_tasks`（多轮追问指令）按 `check_semantic_origin.run` 相同方式补充任务文本类检查；不得在 GUI 内重新实现或修改任何 B/C/D 规则。

#### Scenario: 结果一致
- **WHEN** 对同一文件夹分别运行 GUI 质检与 `python check_semantic_origin.py <文件夹>`
- **THEN** 每个任务命中的问题类别、步序号、描述、附加信息与命令行结果一致（不要求分组统计文案逐字相同）

### Requirement: 任务列表内联标记

系统 SHALL 在左侧任务列表中区分三种任务状态：有问题、无问题、解析失败。有问题任务在显示文本前增加醒目前缀（如 `● N 问题`）并使用红色系样式；解析失败任务使用独立前缀与警示色；无问题任务保持默认样式或加中性标记。鼠标悬停 tooltip SHALL 展示该任务各问题类别（使用 `check_semantic_v1.CATS` 全称）及其条数。

#### Scenario: 有问题任务
- **WHEN** 某任务质检返回至少 1 条问题
- **THEN** 列表项显示问题总数前缀与警示配色，tooltip 分类列出计数

#### Scenario: 无问题任务
- **WHEN** 某任务质检返回 0 条问题且解析成功
- **THEN** 列表项不使用警示配色

#### Scenario: 质检尚未完成
- **WHEN** 后台质检仍在运行
- **THEN** 未出结果的任务不显示任何问题标记，不得显示为「无问题」

### Requirement: 任务问题明细与跳转

系统 SHALL 在选中某任务时，于常驻可见的问题明细区域（可放置在右侧栏 JSON 树下方或任务列表下方）以表格/列表展示该任务全部问题条目：类别、步序号、截图文件名、描述、附加信息。双击某条目时：
- 步序号不为 None：切换到该任务并翻到问题对应的 GUI 页面；
- 步序号为 None（任务级问题）：仅确保切换到该任务。

#### Scenario: 跳转到问题步
- **WHEN** 用户双击一条带步号的问题
- **THEN** 中间截图区显示该伪步对应的页面，页码与截图文件名和问题条目一致

#### Scenario: 任务级问题
- **WHEN** 用户双击「D 任务文本含多余反引号」等步号为 None 的条目
- **THEN** 切换到对应任务，不进行翻页、不报错

### Requirement: 伪步序号到 GUI 页面的映射

系统 SHALL 按与 `to_pseudo_record` 相同的规则遍历当前任务 `messages` 中全部 assistant 消息的 `trajectory`：跳过 `actions[0].action == "screenshot"` 的合成步，其余步按出现顺序从 0 连续编号得到伪步序号；同时记录每个非合成步对应的 GUI `_pages` 索引（`_pages` 含 1 个 `top_level` 页、若干 `message` 页与全部 `trajectory_step` 页，含合成步）。映射 SHALL 在任务加载、`_build_pages` 完成后构建，质检结果与映射使用同一套伪步编号。

#### Scenario: 含合成截图步的任务
- **WHEN** 任务轨迹中夹杂 screenshot 合成步
- **THEN** 伪步 N 跳转后的页面截图文件名等于质检结果 `shots[N]`

#### Scenario: 映射缺失的防御
- **WHEN** 某伪步在映射表中找不到对应 GUI 页（数据异常）
- **THEN** 跳转被忽略并给出轻量提示，不抛异常、不崩溃

### Requirement: 保存后增量重检

系统 SHALL 在用户通过「保存」成功写盘后，仅对当前这一个任务重新执行语义质检，并用新结果原子替换该任务的旧问题数据、刷新列表标记与明细面板；不重新扫描整个文件夹。

#### Scenario: 修复后标记消失
- **WHEN** 用户修复某任务的问题并保存，且重检返回 0 条
- **THEN** 该任务列表项的问题标记移除，明细面板清空，其他任务标记不变

#### Scenario: 重检失败
- **WHEN** 保存后重检过程中该文件解析失败
- **THEN** 该任务标记为解析失败并提示，其他任务不受影响

### Requirement: 打包与模块缺失降级

系统 SHALL 更新 `main.spec`，在 `hiddenimports` 中加入 `check_semantic_v1` 与 `check_semantic_origin`（两者与 main.py 同目录）；运行时导入 SHALL 做容错：导入失败时「语义质检」按钮置为禁用或点击后弹出说明对话框，GUI 其余功能（加载、浏览、翻页、编辑、保存）保持可用。

#### Scenario: 打包环境可运行
- **WHEN** 用更新后的 main.spec 打包并在无 Python 环境的机器运行
- **THEN** 语义质检功能可正常执行，无 `ModuleNotFoundError`

#### Scenario: 模块缺失
- **WHEN** 两个检查模块因任何原因无法导入
- **THEN** 启动不崩溃，按钮不可用并提示原因，原有功能完整可用
