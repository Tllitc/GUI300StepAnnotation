# datasubtool 起始序号与数据集文件白名单过滤

## Summary

在现有 `datasubtool` 交付整理工具上增加两项能力：

1. **按平台填写起始序号**：界面列出 Excel 中命中的平台，用户可分别填写本次导出的起始序号（默认 1），实现多批次输出编号连续（如 Windows 从 `gui_000006` 开始）。
2. **数据集文件白名单过滤**：复制时只保留真正的数据集文件（`<编号>.json`、`<编号>_coords.json`、`<编号>_<数字>.png`），其余缓存/备份文件（如 `*_draft.json`、`*.json.bak`、`*.json.bak_<时间戳>`）不再复制。

## Current State Analysis

现有实现（当前工作区已通过测试）：

- [core.py](file:///c:/Project/TC/300step采标工具/datasubtool/core.py)
  - `build_plan(rows, source_root, target_root)`（约 L198-263）：按平台 `counters` 从 1 递增分配 `gui_%06d`。
  - `_convert_item(item)`（约 L278-301）：`os.walk` 递归复制，`name.startswith(old_id)` 则替换前缀，**其余文件原样复制**（`note.txt` 这类文件目前也会被复制）。
  - 预留 `available` 平台目录列表的读取在 `build_plan` 内部（L208）。
- [app.py](file:///c:/Project/TC/300step采标工具/datasubtool/app.py)
  - `MainWindow._build_ui`（L131-200）：三行路径选择 + 开始/取消 + 进度条 + 日志区，无编号输入控件。
  - `Worker.run`（L67-117）：自行 `load_excel` → `build_plan` → `convert`，未接收起始序号参数。
  - `_set_running`（L221-225）：运行期禁用开始与浏览按钮。
- [test_core.py](file:///c:/Project/TC/300step采标工具/datasubtool/tests/test_core.py)
  - `test_convert_success`（L203-265）显式断言 `note.txt` 被原样复制，白名单改造后需同步调整。
  - 现有 21 个用例全部通过。

真实数据抽查（8 个数据集）证实：

- 合法文件只有三种命名：`gui_00xxxx.json`、`gui_00xxxx_coords.json`、`gui_00xxxx_0001.png`。
- 需过滤的实例：`gui_000002_draft.json`、`gui_000001.json.bak`、`gui_000003.json.bak_20261028_145211`（后者用 `.bak` 后缀黑名单也会漏掉，因此采用白名单更稳妥），另有隐藏目录 `.screenshots`、`.trae`。

## Proposed Changes

### 1. core.py：白名单与平台起始序号

**a) 新增文件白名单判断**（模块级公开函数，便于单测）：

```python
DATASET_JSON_SUFFIX = "_coords.json"

def is_dataset_file(name: str, folder_id: str) -> bool:
    # 命中：<id>.json / <id>_coords.json / <id>_<数字>.png（扩展名忽略大小写）
```

- 仅接受与当前数据集原编号严格对应的三类文件名，其它一律视为非数据集文件。
- 用 `re.fullmatch(re.escape(folder_id) + r"_\d+\.png", name, re.IGNORECASE)` 等精确匹配，避免 `gui_000002_draft.json`、`gui_000001.json.bak`、`gui_0000011_0001.png` 误入。

**b) `_convert_item` 改为按白名单复制**：

- `os.walk` 时不预先创建目录；仅当遇到白名单文件时创建对应输出子目录并 `copy2`（文件名按原规则替换前缀）。
- 返回跳过的非数据集文件名列表；`convert` 对每个数据集记录一条日志：`[跳过] 平台 原编号 → 新编号：N 个非数据集文件（前若干个文件名…）`。
- 若某数据集没有任何白名单文件被复制，抛 `ConversionError("未找到可复制的数据集文件")`，该条标记失败并清理空目标目录（避免产生空目录被误认为成功）。
- JSON 引用改写仍只针对复制后的 `*.json`，因此 `_draft.json` 与 `.bak*` 天然不会进入改写流程。

**c) `build_plan` 支持每平台起始序号**：

```python
def build_plan(rows, source_root, target_root, start_numbers: Mapping[str, int] | None = None) -> Plan
```

- `counters` 初始化：`start_numbers.get(platform, 1)`，首条编号即该起始值，随后递增；其它校验（源目录存在、重复、目标冲突）逻辑不变。
- 起始序号非法（非整数、<1）时追加错误：`平台「X」起始序号无效：…`，整体预检不通过，不写任何文件。
- 目标编号已存在的冲突判定仍沿用现有逻辑（中止并清单）。

**d) 新增平台探测函数供界面使用**：

```python
def detect_platforms(rows: list[RawRow], source_root: str | Path) -> list[str]
```

- 按 Excel 行序去重返回可识别的平台目录名（复用 `normalize_platform`）；未知平台忽略（预检阶段仍会报错）。

### 2. app.py：命中平台起始序号输入

**a) 新增「命中平台起始序号」区域**（放在三个路径行之下、按钮行之上）：

- `QGroupBox` 内放 `QTableWidget`：两列「平台」「起始序号」；第二列使用 `QSpinBox`（范围 1–999999，默认 1）作为 cell widget。
- 维护 `self._start_spins: dict[str, QSpinBox]`，重建表格时按平台名保留用户已填值。

**b) 刷新时机**：

- `excel_edit.editingFinished`、`source_edit.editingFinished`，以及三个「浏览…」按钮选择成功后调用 `_refresh_platform_starts()`。
- 刷新逻辑：路径不全或 `core.load_excel`/`core.detect_platforms` 失败 → 清空表格；成功 → 列出命中平台，日志追加「命中平台：Windows、Android…」。
- 刷新为轻量读表（read_only），在 UI 线程执行；失败只提示日志，不弹窗。

**c) Worker 传递起始序号**：

- `Worker.__init__` 增加 `start_numbers: dict[str, int]`，调用 `core.build_plan(rows, source_root, target_root, start_numbers)`。
- `_on_start` 读取 `{平台: spin.value()}` 传入；表格为空时传 `{}`（全部默认 1）。
- `_set_running` 额外禁用 `QTableWidget` 与「刷新」入口，避免运行中修改。

### 3. 测试更新（tests/test_core.py）

- 新增白名单单测：`<id>.json`、`<id>_coords.json`、`<id>_0001.png` 为 True；`<id>_draft.json`、`<id>.json.bak`、`<id>.json.bak_20261028_145211`、`note.txt`、`<id>1_0001.png` 为 False。
- 新增起始序号单测：`start_numbers={"Windows": 5}` 时 Windows 依次 `gui_000005`、`gui_000006`，另一平台仍从 `gui_000001`；`start_numbers={"Windows": 0}` 预检报错且不写目标目录。
- 新增 `detect_platforms` 单测：去重、保持 Excel 行序、跳过无法识别平台。
- 修改 `test_convert_success`：把原来的 `note.txt` 断言改为「`note.txt`、`gui_000003_draft.json`、`gui_000003.json.bak` 均不出现在输出目录」，输出文件清单仅剩白名单文件。
- 新增「全部文件都被过滤」场景：数据集仅含 `_draft.json`/`.bak` 且缺主 JSON 时，该条状态为失败，且不残留空目录。

### 4. spec 文档同步

- [spec.md](file:///c:/Project/TC/300step采标工具/.trae/specs/rename-datasets-to-delivery/spec.md)：新增「按平台起始序号」需求（含默认 1、非法值中止、冲突仍中止）；将「非编号前缀文件按原样复制」改为「仅复制数据集白名单文件，其余跳过并记录日志」。
- [checklist.md](file:///c:/Project/TC/300step采标工具/.trae/specs/rename-datasets-to-delivery/checklist.md)：追加「起始序号按平台生效」与「draft/bak 文件不被复制」两项检查点。
- [tasks.md](file:///c:/Project/TC/300step采标工具/.trae/specs/rename-datasets-to-delivery/tasks.md)：追加本次两条任务的完成记录。

## Assumptions & Decisions

- 白名单规则固定为三种文件名（与当前 NAS 实际数据一致），不做界面可编辑规则；扩展名大小写不敏感，允许子目录内同名规则文件（当前数据无子目录数据集文件）。
- 非数据集文件含隐藏目录（`.screenshots`、`.trae`）内的文件：因不匹配白名单，天然不会被复制，不再单独加黑名单。
- 起始序号按平台单独填写，默认 1，最小 1；只影响本次运行，不写入映射表；映射表列结构保持不变。
- 起始序号导致的编号冲突沿用「预检中止」策略，不自动跳过。
- 不新增依赖，不改动 `datasubtool` 以外的运行时代码。

## Verification

1. `python -m pytest datasubtool/tests -q` 全部通过（含新增用例）。
2. 离屏 GUI 冒烟（`QT_QPA_PLATFORM=offscreen`）：
   - 选择临时 Excel + 母目录后，起始序号表自动列出命中平台，Windows 改为 5；
   - 点击开始后输出为 `目标/Windows/gui_000005`；
   - 构造含 `_draft.json`、`.json.bak` 的数据集，输出目录中不出现这些文件，日志含跳过提示。
3. 真实数据小样本：用 `\\NAS-TC\GUI采集300step\Android\程婧瑶\gui_000001`（含两个 `.bak`）与 `Windows\程婧瑶\gui_000002`（含 `_draft.json`）复制到临时目录，确认输出文件数=白名单文件数、无 draft/bak、JSON 引用一致、源目录未变化，验证后删除临时产物。