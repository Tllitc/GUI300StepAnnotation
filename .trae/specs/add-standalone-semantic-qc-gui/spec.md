# 独立语义质检 GUI（PyQt6）Spec

## Why

B/C/D 语义质检目前只能跑命令行 `python check_semantic_origin.py`，产出 md/json 后人工再翻目录核对，缺少一个能边看统计、边筛选明细、边定位截图/源文件、边导出报告的可视化入口。现有 `qctools/main.py` 是 2204 行的标注编辑器，其内嵌质检服务于「编辑-修复」闭环且明确不提供报告导出；本需求要的是一个**独立、只读、面向质检复核**的 Qt 程序，与标注编辑器互不影响。

## What Changes

- 在 `qctools/` 下**新增独立入口** `qc_gui.py`（PyQt6），不修改 `main.py` / `check_semantic_origin.py` / `check_semantic_v1.py`。
- 直接 import 并复用 `check_semantic_origin`（`find_task_jsons` / `group_key` / `task_label` / `to_pseudo_record` / `write_md`）与 `check_semantic_v1`（`check_record` / `CATS` / `esc`），**不在 GUI 内重写任何 B/C/D 检查规则**，结果与命令行同口径。
- 支持选择一个或多个目录 / `gui_XXXXXX.json` 文件作为输入（与 CLI 多入参一致），在 QThread 后台逐文件质检，实时回传进度，UI 不冻结；单文件异常计入「解析失败」不中断整批。
- 统计区：按分组汇总（任务数 / 有问题任务数 / 各类别条数）+ 各类别总数，口径与 `check_semantic_origin.write_md` 的汇总表一致。
- 明细区：单表格展示 分组 / 任务 / 步号 / 截图文件 / 类别 / 描述 / 附加，支持按类别、分组、关键字筛选与排序。
- 报告导出：在 GUI 内直接导出与命令行一致的 md 报告（复用 `check_semantic_origin.write_md`）与 json 明细。
- 定位能力（只读）：双击/右键明细条目可预览对应截图（截图与 gui json 同目录）、在系统资源管理器中定位源 `gui_XXXXXX.json`。
- 模块缺失降级：检查模块导入失败时给出明确提示、禁用运行入口，窗口仍可打开。
- 全程只读：不修改任何 JSON / 截图，不提供编辑保存。

## Impact

- Affected specs: 无（新独立程序，不改既有能力）。
- Affected code:
  - 新增 `qctools/qc_gui.py`（独立程序主体：窗口、后台 Worker、统计/明细/筛选/导出/定位）。
  - 复用但不修改：`qctools/check_semantic_origin.py`、`qctools/check_semantic_v1.py`。
  - 打包（可选、收尾）：新增独立 `qctools/qc_gui.spec`，`hiddenimports` 含 `check_semantic_v1`、`check_semantic_origin`；不改动现有 `main.spec`。
- 数据安全：质检与定位全程只读；写盘仅发生在用户主动选择的「导出 md/json」路径。
- 非 BREAKING：纯新增文件，不影响现有标注编辑器与命令行脚本。

## ADDED Requirements

### Requirement: 输入选择与同口径检查复用

系统 SHALL 提供独立 PyQt6 窗口，允许用户添加一个或多个目录或 `gui_XXXXXX.json` 文件作为输入；对每个命中的 gui json，系统 SHALL 调用 `check_semantic_origin.to_pseudo_record(data)` 得到 `(rec, shots, extra_tasks)`，对 `rec` 调用 `check_semantic_v1.check_record`，并按 `check_semantic_origin.run` 相同方式对 `extra_tasks` 补充任务文本类检查；不得在 GUI 内重新实现或修改任何 B/C/D 规则。多输入中的重复文件 SHALL 去重（与 CLI 的 `seen` 行为一致）。

#### Scenario: 多目录输入结果与 CLI 一致
- **WHEN** 用户添加若干目录/文件并运行
- **THEN** 每个任务命中的问题类别、步序号、截图名、描述、附加信息与 `python check_semantic_origin.py <相同输入>` 完全一致（分组统计文案不要求逐字相同）

#### Scenario: 重复文件去重
- **WHEN** 同一 gui json 被多个输入路径覆盖
- **THEN** 该文件只质检一次，统计任务数不重复计数

### Requirement: 后台线程执行与进度反馈

系统 SHALL 在 QThread 中执行文件发现、读取、`to_pseudo_record` 与 `check_record`，通过信号把「当前文件名 / 已完成数 / 总数」进度与最终结果回传 UI 线程；运行期间禁止重复触发，可取消。任何单文件解析异常 SHALL 被捕获并计入「解析失败」清单，不中断整批。

#### Scenario: 大批量不卡顿
- **WHEN** 输入包含大量任务
- **THEN** 质检过程中窗口可拖动、控件可操作，进度条与计数持续更新，界面不无响应

#### Scenario: 单文件损坏
- **WHEN** 某 gui JSON 无法解析或转换抛异常
- **THEN** 该文件进入解析失败清单并在状态栏/失败区可见，其余任务结果正常产出

### Requirement: 分组与分类统计展示

系统 SHALL 在结果区展示两张统计表：按分组汇总（分组、任务数、有问题任务数、`check_semantic_v1.CATS` 各类别条数）与按类别总数（类别、数量），数据来源与 `check_semantic_origin.write_md` 的汇总口径一致；并展示解析失败数量。

#### Scenario: 统计与明细自洽
- **WHEN** 一次质检完成
- **THEN** 分组表各类别条数之和等于类别总数表对应数量，有问题任务数等于至少含 1 条问题的任务数

### Requirement: 明细筛选与浏览

系统 SHALL 以表格展示全部问题条目，列含 分组、任务、步号、截图文件、类别、描述、附加；提供按类别（多选/下拉，取值来自 `check_semantic_v1.CATS`）、按分组、按关键字（匹配任务/描述/附加/截图名）的组合筛选，并支持列排序；任务级问题（步号为 None）以明确空值文案展示而不是空白。

#### Scenario: 组合筛选
- **WHEN** 用户选定某类别 + 某分组并输入关键字
- **THEN** 表格仅显示同时满足三个条件的条目，底部显示筛选后条数/总条数

#### Scenario: 任务级问题展示
- **WHEN** 条目步号为 None（如反引号/换行）
- **THEN** 步号列显示「任务级」之类占位文案，行仍可正常选中

### Requirement: 报告导出

系统 SHALL 提供「导出 md」与「导出 json」：md 导出 SHALL 复用 `check_semantic_origin.write_md(rows, stats, failed, out, title)` 生成与命令行同结构报告；json 导出 SHALL 写出 `{rows, stats, failed}` 结构（与 CLI `--json` 一致）。导出路径由用户通过系统保存对话框选择；未产生结果时导出按钮禁用。

#### Scenario: 导出 md 与 CLI 同结构
- **WHEN** 用户对当前结果选择导出 md
- **THEN** 生成文件内容与命令行 `--out` 产物结构、类别、条目一致

#### Scenario: 无结果禁用导出
- **WHEN** 尚未运行或结果为空
- **THEN** 导出按钮不可点击

### Requirement: 截图预览与源文件定位（只读）

系统 SHALL 支持对选中明细条目：预览该步截图（截图文件名取自条目的 `shot`，绝对路径为该 gui json 所在目录拼接 `shot`，文件缺失时给出提示而非崩溃）；并通过系统资源管理器定位其源 `gui_XXXXXX.json`（Windows `QDesktopServices` 打开所在目录并选中文件）。系统不提供任何编辑/保存入口。

#### Scenario: 预览截图
- **WHEN** 用户对一条带截图名的条目触发预览
- **THEN** 弹出窗口显示同目录下该截图；截图文件不存在时显示友好提示

#### Scenario: 定位源文件
- **WHEN** 用户触发「在资源管理器中显示」
- **THEN** 打开该 gui json 所在目录并选中该文件

### Requirement: 模块缺失降级

系统 SHALL 在启动时容错导入 `check_semantic_origin` / `check_semantic_v1`；导入失败时窗口仍可打开，但运行/导出入口禁用并展示原因提示，不抛未捕获异常、不崩溃。

#### Scenario: 检查模块不可用
- **WHEN** 两个检查模块因任何原因无法导入
- **THEN** 程序启动不崩溃，界面提示模块缺失，质检相关按钮禁用
