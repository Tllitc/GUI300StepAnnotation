# 20261110 批语义质检问题数据修复 Spec

## Why

`check_semantic_origin.py` 对 NAS 交付数据（100 条任务）的语义质检发现 12 条任务有问题，根因已定位且经数据/截图核实：

1. **11 条 Windows 任务的用户指令含 15 处模板残留反引号**（D 任务文本含多余反引号）：全部出现在 `20261110_GUI_Agent_交付数据_65_1` 批，且无一例外紧跟在保存文件名 `.xlsx`/`.docx` 之后（如 `...比价表.xlsx`；...`），属上游指令生成模板的 Markdown 反引号残留。
2. **1 处 CoT 与实际输入不一致**（C2）：`macos/gui_000005` 步207（截图 `gui_000005_0209.png`）微信输入框实际文字为"参**管**苏州博物馆"，与 intent、action.text 一致；仅 CoT【下步思考】误写为"参**观**苏州博物馆"，属 CoT 标注自行纠错导致的不一致。

这些是交付数据本身的脏数据，质检工具判定无误，需直接修复原始 JSON。

## What Changes

- 修复 11 个 Windows 任务 JSON（`20261110_GUI_Agent_交付数据_65_1/Windows/` 下 gui_000015、000016、000017、000018、000019、000021、000022、000023、000025、000029、000038）中 `messages[].role=user` 的 `instruction` 字段：删除文件名扩展名 `.xlsx`/`.docx`（兼容 `.xls`/`.doc`）后紧邻的孤立反引号，共 15 处。
- 修复 `20261110_GUI_Agent_交付数据_65_1/macos/gui_000005/gui_000005.json` 伪步207（跳过 screenshot 合成步后的编号，对应截图 0209）的 `CoT` 字段：字段级定位后将其中"参观苏州博物馆"改为"参管苏州博物馆"（全文件仅此 1 处替换，与截图实测输入对齐；伪步189 的 3 处合法"参观"不动）。
- 修复前对全部 12 个被改文件做原样备份（保留相对目录结构，集中存放于 `qctools/backup_semantic_fix_20261112/`）。
- 修复后重跑 `check_semantic_origin.py` 全量质检验证。
- 修复逻辑沉淀为可复用脚本 `qctools/fix_semantic_data_20261110.py`（默认 dry-run，显式 `--apply` 才写盘）。

## Impact

- 受影响数据：仅 `\\NAS-TC\GUI采集300step\交付数据\20261110_GUI_Agent_交付数据_65_1` 下 12 个 `gui_XXXXXX.json`（11 Windows + 1 macOS）。
- 不改动：任何截图 PNG、action 动作数据、intent 文本（gui_000005 的 intent 与 text 保持"参管"不动）、`20261103_..._35_1` 批、多轮追问指令（经扫描确认无反引号）。
- 修复采用精确文本替换、不重新序列化整个 JSON，避免缩进、键顺序、Unicode 转义形式发生意外变化。
- 受影响质检能力：B/C/D 语义质检（修复后 D 反引号与 C2 两类计数应归零）。

## ADDED Requirements

### Requirement: 反引号脏数据修复

系统 SHALL 提供修复脚本，对指定交付目录下的 `gui_XXXXXX.json`，仅在 `role=user` 的 `instruction` 文本中删除紧跟文件扩展名（`.xlsx/.xls/.docx/.doc`，大小写不敏感）之后的反引号字符，其余内容逐字保留。

#### Scenario: 文件名后残留反引号
- **WHEN** instruction 中出现 `保存为比价表.xlsx`；最后...`
- **THEN** 修复后变为 `保存为比价表.xlsx；最后...`，反引号被删除且其他字符不变

#### Scenario: 无反引号文件
- **WHEN** JSON 的 instruction 不含目标模式
- **THEN** 文件内容保持字节级不变，不产生写入

#### Scenario: Dry-run 默认安全
- **WHEN** 不带 `--apply` 运行脚本
- **THEN** 只报告拟修改的文件与替换处数，不写任何文件

### Requirement: CoT 与实际输入对齐修复

系统 SHALL 按与 `check_semantic_origin.to_pseudo_record` 相同的口径（跳过 `actions[0].action=="screenshot"` 的合成截图步，跨全部 assistant 消息从 0 连续编号）定位 gui_000005.json 的伪步207，取其完整 `CoT` 字段字符串做字段级精确替换：仅当该 CoT 字符串中"参观苏州博物馆"恰好出现 1 次、且该步 intent 与 action.text 均含"参管苏州博物馆"（证实真值为"参管"）时，才将该 CoT 串中的"参观"改为"参管"，并用完整 CoT 串在 raw 中 `replace(old, new, 1)`（完整串在 raw 中唯一）。校验不通过则中止该文件并报错，不做任何写入。

约束：raw 中"参观苏州博物馆"实际出现 4 次，其中伪步189 的 intent/CoT/text 共 3 处是合法的"参观"任务输入，SHALL NOT 被改动；仅伪步207 CoT 中的 1 处被替换，全文件替换总次数为 1。

#### Scenario: CoT 错字修正
- **WHEN** 执行修复
- **THEN** 伪步207 CoT 中该片段变为"参管苏州博物馆"，该步 intent、action.text 保持"参管"不变，伪步189 及其他所有步骤内容字节级不变

#### Scenario: 修复幂等（已修复数据重跑）
- **WHEN** 伪步207 CoT 中已无"参观苏州博物馆"（计数 0）且已含"参管苏州博物馆"
- **THEN** 视为已修复、安静跳过（不报错、不写入、cot 不计替换）；仅当计数既非 0 也非 1，或计数为 1 但 intent/text 真值前提不成立时，才中止报错

### Requirement: 修复前备份与修复后验证

系统 SHALL 在首次写盘前把每个待修改文件按原始相对路径备份到 `qctools/backup_semantic_fix_20261112/`；修复完成后重跑语义质检，100 条任务问题数为 0，且全部 JSON 可被 `json.load` 正常解析。

#### Scenario: 质检归零
- **WHEN** 修复后运行 `python qctools/check_semantic_origin.py \\NAS-TC\GUI采集300step\交付数据`
- **THEN** 输出"有问题任务 0"，D 反引号与 C2 计数均为 0，解析失败 0
