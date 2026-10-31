# 修复断点续采（草稿恢复）失败 Spec

## Why
用户在"开始采标"后的编辑窗口中进行了若干操作（截图、标注、确认步骤），关闭窗口后再次启动工具，点击"继续未完成任务"选择之前的 `gui_xxxxxx` 目录时，系统报错 **"该目录没有可恢复的草稿（draft）或草稿已损坏"**，导致无法断点续采，已采集的数据只能通过重新走完整流程找回。

根因链路有两条：

1. **核心 Bug（closeEvent 无条件删除草稿）**：`AnnotationEditor.closeEvent` 在用户关闭编辑窗口时（无论中途退出还是正常完成），只要 rounds 非空就会调用 `_save_all_rounds_to_file`，而后者保存最终 JSON 成功后**立即删除草稿**。这意味着用户中途关闭窗口（想休息一下稍后继续）与完成任务关闭，草稿都会被清除。关闭后再想"继续未完成任务"，草稿已不存在。
2. **错误信息缺乏诊断能力**：`load_draft_from_dir` 只返回 `None`，`resume_annotation` 无法区分"草稿从未创建"、"草稿已被正常删除（任务已完成）"、"草稿 JSON 已损坏"、"目录中只有截图没有草稿"等不同情况，全部笼统显示为"该目录没有可恢复的草稿（draft）或草稿已损坏"。

## What Changes
- **草稿生命周期与任务完成解耦**：只有 `_finish_task`（用户点击"任务完成"按钮且全量校验通过）才应触发"删除草稿"。`closeEvent` 中途关闭时，应写一次最终的防崩溃草稿，但**不删除草稿**，让下次启动时能继续恢复。
- **草稿恢复的错误信息细分**：`load_draft_from_dir` 改为返回结构化结果（包含错误类型枚举），`resume_annotation` 根据错误类型给用户明确提示。典型场景：任务已正常完成（草稿已删除，目录有最终 JSON）→ 提示"该任务已正常完成，请选择未完成的 gui 目录"。
- **closeEvent 中间状态持久化**：`closeEvent` 在中途关闭时写草稿，但保留草稿文件；`_finish_task` 正常完成时才写最终 JSON + 删除草稿。

## Impact
- Affected specs: 草稿保存/删除生命周期、断点续采入口提示
- Affected code:
  - `annotation_editor.py` — `closeEvent`、`_save_all_rounds_to_file`、`_finish_task` 草稿删除逻辑
  - `data_manager.py` — `load_draft_from_dir` 返回结构化结果
  - `main.py` — `resume_annotation` 根据错误类型给出差异化提示
- 数据文件：不新增、不修改任何现有文件格式

## Requirements

### Requirement: 草稿仅在任务正常完成时删除
系统 SHALL 仅在用户通过"任务完成"按钮触发全量校验通过、成功写出最终 JSON 和 coords JSON 后，才删除对应 `gui_xxxxxx` 目录下的 `*_draft.json`。

#### Scenario: 用户中途关闭编辑窗口
- **WHEN** 用户已采集若干步骤但未点击"任务完成"（可能处于轮次中间或轮次已保存但尚有后续任务），然后关闭编辑窗口
- **THEN** 编辑窗口关闭后，`gui_xxxxxx` 目录中仍然存在有效的 `*_draft.json`，内容包含关闭前的完整工作态（rounds + 当前轮步骤）

#### Scenario: 用户点击"任务完成"正常结束
- **WHEN** 用户点击"任务完成"，全量校验通过，最终 JSON 与 coords JSON 成功落盘
- **THEN** `*_draft.json` 被删除，目录中只保留最终产物（JSON + coords + 截图）

#### Scenario: 校验未通过阻止完成
- **WHEN** 用户点击"任务完成"但存在必填项缺失，校验对话框弹出并跳转补全
- **THEN** 草稿保持不变，不被删除

### Requirement: 断点续采入口提示可诊断
系统 SHALL 在用户选择 gui 目录进行续采时，区分以下场景并给出明确提示：

| 场景 | 判断依据 | 用户提示 |
|------|----------|----------|
| 目录含有效草稿 | `*_draft.json` 存在且 JSON 合法 | （正常恢复，无额外提示） |
| 目录有最终 JSON 但无草稿 | `gui_xxxxxx.json` 存在 且 `*_draft.json` 不存在 | "该任务已正常完成，无需续采" |
| 目录只有截图无草稿也无最终 JSON | 有截图文件 但无 `*_draft.json` 也无 `.json` | "该目录未包含有效的采集数据（无草稿也无最终结果）" |
| 草稿文件存在但 JSON 损坏 | `*_draft.json` 存在 但 `json.load` 失败 | "草稿文件已损坏，无法恢复" |
| 目录中无任何采集数据 | 无截图、无 JSON | "该目录不包含任何采集数据" |

#### Scenario: 续采已完成的任务
- **WHEN** 用户选择一个含有最终 JSON 但无草稿的 gui 目录
- **THEN** 系统提示"该任务已正常完成，无需续采"，不打开编辑器窗口

#### Scenario: 草稿损坏
- **WHEN** 用户选择的 gui 目录中 `*_draft.json` 文件存在但 JSON 解析失败（例如被截断或部分写入）
- **THEN** 系统提示"草稿文件已损坏，无法恢复"，打印解析异常到 console

#### Scenario: 空 gui 目录
- **WHEN** 用户选择的 gui 目录中既无 `*_draft.json` 也无 `gui_xxxxxx.json`
- **THEN** 系统提示"该目录不包含任何采集数据"

## Constraints
- 保持现有草稿文件命名 `gui_xxxxxx_draft.json` 不变
- 保持最终 JSON 与 coords JSON 的格式不变
- `closeEvent` 仍然需要处理窗口关闭时的状态持久化（保存当前轮次到 rounds 等），只是不删除草稿
- iOS 端与 macOS 端的同名文件暂不在本次修复范围内（Android 端优先）
