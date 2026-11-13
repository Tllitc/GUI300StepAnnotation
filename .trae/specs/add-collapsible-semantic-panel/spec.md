# 语义问题面板折叠功能 Spec

## Why
右侧「语义问题」面板常驻展示筛选项与问题卡片，即使当前任务无问题、或用户专注查看指令与 JSON 时也持续占用垂直空间，压缩 JSON 树的可用高度。需要让它可按需收起。

## What Changes
- 在「语义问题（N）」标题行左侧新增折叠/展开按钮（▾ / ▸），点击切换折叠态；点击标题文字同样可切换。
- 折叠时隐藏类别筛选 chips 行与卡片滚动区，仅保留标题行与问题计数；展开时恢复折叠前高度。
- 折叠态下面板高度锁定为标题行高度，拖拽其上方的纵向分隔条无法把面板拉高；展开后恢复可拖拽。
- 指令区自适应逻辑（`_fit_instruction_pane`）在折叠态不再为语义面板预留固定 40px。
- 折叠状态写入 QSettings（`ui/qc_collapsed`），随窗口状态一起保存并在下次启动恢复。
- 非破坏性：质检数据链路、卡片渲染、类别筛选、双击跳转等既有行为保持不变。

## Impact
- Affected specs: embed-semantic-qc-in-gui（仅影响该面板的布局与交互）
- Affected code: qctools/main.py
  - `_setup_ui` 中语义面板构建（标题行、chips、滚动区、右侧纵向 splitter 装配）
  - `_apply_styles`（新增折叠按钮样式）
  - `_fit_instruction_pane`（三栏高度分配）
  - `_restore_window_state` / `_save_window_state`（折叠状态持久化）

## ADDED Requirements

### Requirement: 面板折叠与展开
系统 SHALL 允许用户通过标题行的切换控件折叠或展开语义问题面板。

#### Scenario: 折叠
- **WHEN** 面板处于展开态，用户点击折叠按钮（▾）或点击标题文字
- **THEN** 类别筛选 chips 行与卡片滚动区隐藏，标题仍显示「语义问题（N）」计数
- **AND** 面板高度收缩为标题行高度，按钮文本变为 ▸，tooltip 变为「展开语义问题」
- **AND** 释放出的垂直空间立即分配给 JSON 树

#### Scenario: 展开
- **WHEN** 面板处于折叠态，用户点击展开按钮（▸）或点击标题文字
- **THEN** chips 行与卡片区恢复显示，面板高度还原为折叠前记录的高度（下限为滚动区最小高度 120px）
- **AND** 按钮文本恢复为 ▾，tooltip 变为「折叠语义问题」

#### Scenario: 折叠态下拖拽分隔条
- **WHEN** 面板折叠且用户拖动其上方的纵向分隔条
- **THEN** 语义面板高度保持为标题行高度，不被拉高；空间在指令区与 JSON 树之间分配

### Requirement: 折叠状态持久化
系统 SHALL 在关闭窗口时保存折叠状态，并在下次启动时恢复。

#### Scenario: 重启后恢复
- **WHEN** 用户折叠面板后关闭应用并重新打开
- **THEN** 面板初始即为折叠态，按钮图标、可见性与 tooltip 与折叠态一致

### Requirement: 折叠态下的高度自适应
系统 SHALL 在折叠态下调整右栏高度分配算法，不再为语义面板预留固定最小高度。

#### Scenario: 窗口缩放
- **WHEN** 面板折叠且窗口尺寸发生变化
- **THEN** 指令区按内容自适应，剩余高度全部分配给 JSON 树，语义面板保持标题行高度

## MODIFIED Requirements

### Requirement: 语义问题明细面板
面板 SHALL 保留原有标题计数、类别筛选 chips（全部/B/C/D）、卡片列表、空态提示与双击跳转行为；标题行新增折叠切换控件并支持折叠态展示。

## REMOVED Requirements
无。