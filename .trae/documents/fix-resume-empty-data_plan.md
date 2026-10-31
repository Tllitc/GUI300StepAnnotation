# 续采后没有数据修复 Plan

## Repository Research

### 问题复现链路

以 `test/gui_000005/gui_000005_draft.json` 为例，草稿结构：
```json
"rounds": [ { "trajectory": [3 个完整步骤] } ],
"steps_data": [],
"current_step_index": 0
```

用户操作路径：
1. 正常采集 3 步 → 点击 answer（确认当前轮次完成 + 切下一轮）
2. `_save_current_round_to_list()` 把 `steps_data` 打包进 `rounds[-1]`，设 `_current_round_saved = True`
3. `_write_draft_now()` 写入草稿时：
   ```python
   steps_for_draft = [] if self._current_round_saved else self.steps_data
   ```
   因为 `_current_round_saved = True`，所以写出来的 `steps_data = []`
4. 用户关闭窗口 → closeEvent 再次调 `_write_draft_now`，结果一样

恢复路径（`load_from_draft`）：
1. `self.rounds` = [第一轮完整 trajectory] ✅ 有数据
2. `self.steps_data` = []（从草稿恢复）
3. `self._current_round_saved = True`（else 分支设）
4. `_reset_for_next_step()` → 清空预览区、表单等
5. `sidebar.rebuild_items()` → 用 `editor.steps_data` 渲染 → **空侧栏！用户看不到任何历史步骤**

### 核心矛盾

`SideBarWidget.rebuild_items()` 只渲染 `editor.steps_data`，不读 `rounds`。而轮次边界态下草稿里 `steps_data` 是空的，导致用户恢复后看到空白。

### 关键代码

| 文件 | 行号 | 作用 |
|------|------|------|
| `annotation_editor.py` | 2505 | `steps_for_draft = [] if self._current_round_saved else self.steps_data` — 问题源 |
| `annotation_editor.py` | 2546-2561 | 草稿恢复 steps_data |
| `annotation_editor.py` | 2577-2587 | 空 steps_data 走 else 分支 |
| `annotation_editor.py` | 918-923 | sidebar.rebuild_items 用 steps_data 渲染 |

## Files and Modules

- `安卓端/annotation_editor.py`: 修改 `_write_draft_now()` 和 `load_from_draft()`

## Implementation Steps

### Step 1: 修改 `_write_draft_now` — 轮次边界态时从 rounds[-1] 重建 steps_for_draft

当 `_current_round_saved = True` 但 `rounds` 非空时，把 `rounds[-1].trajectory` 和 `rounds[-1].coords` 合并重建为可序列化的 steps_data：

```python
# 轮次边界态：从 rounds[-1] 重建 steps_for_draft，确保恢复后用户能在侧栏看到
# 最后一轮的完整步骤（rounds 仍保持完整多轮次结构）
if self._current_round_saved and self.rounds:
    last_round = self.rounds[-1]
    round_trajectory = last_round.get("trajectory") or []
    round_coords = last_round.get("coords") or []
    # coords 按 step 下标建索引
    coords_by_step = {c.get("step"): c for c in round_coords if isinstance(c, dict)}
    steps_for_draft = []
    for t_step in round_trajectory:
        obs = t_step.get("observation") or {}
        actions = t_step.get("actions") or []
        action_data = actions[0] if actions else {}
        coord_entry = coords_by_step.get(t_step.get("step"), {})
        steps_for_draft.append({
            "screenshot": obs.get("screenshot", ""),
            "intent": t_step.get("intent", ""),
            "action_data": copy.deepcopy(action_data),
            "vertices": copy.deepcopy(coord_entry.get("vertices")),
        })
else:
    steps_for_draft = self.steps_data
```

这样草稿里的 `steps_data` 始终代表"最后一轮的完整步骤"，而 `rounds` 仍保持多轮次结构。

### Step 2: 更新草稿恢复的 current_step_index 逻辑（适配新 steps_data 来源）

恢复逻辑 `load_from_draft` 中 `current_step_index = 0` 在空 steps_data 场景下是合理的（回到第一步）。新逻辑下 steps_data 会有内容（从 rounds[-1] 重建），恢复到正确步骤就行，不需要改动。

### Step 3: 验证

1. Python 语法检查
2. 用现有草稿文件 `gui_000005_draft.json` 做 dry-run：模拟 `_write_draft_now` 新逻辑 + `load_from_draft`，确认恢复后 steps_data 有 3 步

## Dependencies and Considerations

- 旧草稿兼容性：已有的旧草稿（`steps_data = []` 但 rounds 有数据）在用户升级后会被正常恢复，但侧栏仍空——**这是一次性问题**，用户重新开一次工具，后续的草稿就会用新格式写入。
- rounds 多轮次结构不变，`_save_current_round_to_list` 和 `_save_all_rounds_to_file` 不受影响。
- `rounds[-1].trajectory` 里的 action_data 格式和 `steps_data[i].action_data` 一致（都是 `{"action": "click", ...}`），可以直接复用。
- vertices 需要从 coords 数组按 step 下标匹配，不能直接从 trajectory 里取（trajectory 里没有 vertices，只有 coords 里有）。

## Validation

1. `py_compile` 语法检查通过
2. 模拟测试：用现有 `gui_000005_draft.json` 里的 rounds 数据，走 Step 1 新逻辑，确认能重建出 3 个 step
3. 人工审查：对比草稿 round.trajectory 与重建出的 steps_data 字段完全对齐

## Risks

- **rounds[-1] 的 coords/trajectory 长度不一致**：用 `min(len(trajectory), len(coords))` 或直接按 trajectory 遍历、找不到 coords 时 vertices 为 None（安全降级）
- **旧草稿恢复后仍空**：这是预期内的一次性问题，可在 `load_from_draft` 中增加降级逻辑——如果 steps_data 空但 rounds 非空，动态从 rounds[-1] 重建（双保险）
