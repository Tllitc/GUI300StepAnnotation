# 修复 scroll 动作 coords bbox 与 JSON 不一致

## 摘要 / 根因

**根因（已 4/4 实验复现）**：`annotation_editor.py` 的 `_find_coord_entry`（L3003-3013）在按 `entry["step"]` 找不到条目时，**回退取列表第 `fallback_index` 条**。gui_000005 首次交付时工具存在 B6（`_collect_coords_entries` 旧写法不含 `scroll`），coords 少 4 条 scroll 条目；之后以「编辑已完成任务」重开，`load_from_completed_json`（L3080）用位置下标取框，因原列表短 4 条且缺 step 0/9/154，下标漂到 47/83/105/153，使 step 44/79/100/147 **冒领了别的工作的顶点**；而坐标输入框只读、值仍来自 JSON，于是「JSON 正确 / 内存 rect_info 错误」单向分叉，`save_edited_round` L3212 整组替换后把污染 bbox 以正确 step 编号写盘（表现为 4 组重复 bbox）。

**放大因素**：`tests/invariants.py` 的 INV-8 只校验 coords 覆盖与无多余（按 (step, action) 贪婪消费），**从不断言 `center ↔ coordinate` 相等**，故污染数据假绿通过。

**不变式依据**：坐标框是唯一 Primitive，坐标值由框中心派生且输入框只读（L153-158 + `_init_editor_from_capture` L1896-1909 + `get_data` L689-703），故对 `COORD_ACTION_TYPES` 全部单框动作（含 `scroll`）恒有 `center == actions[0].coordinate`；drag 为 `start_center == start_coordinate`、`end_center == coordinate`。允许 1px 取整容差。

## 关键改动

### A. Windows 工具侧（`C:\Project\TC\300step采标工具\annotation_editor.py`）

**A1. 删除位置回退（L3003-3013）**
- `_find_coord_entry(coords, step)`：去掉 `fallback_index` 参数与 L3011-3012 回退；仅当 `isinstance(entry.get("step"), int) and not isinstance(entry.get("step"), bool) and entry["step"] == step` 时返回；未命中返回 `None`。
- 新增 `_find_coord_entry_by_center(coords, action, coordinate, start_coordinate, claimed_ids)`：只在 step 查找落空时调用，在**未被认领**的条目里找 `entry["action"] == action` 且中心点与 JSON 坐标逐轴差 ≤1 的条目（drag 比 `start_center`/`end_center`），命中即返回并登记 `claimed_ids`（用 `id(entry)`）。用途：兼容旧文件 step 编号整体漂移但框本身正确的数据，杜绝「无根据的位置猜测」。
- 调用点 L3080 改为两趟匹配，并把 `claimed_ids` 集合在 `load_from_completed_json` 的循环外初始化。

**A2. 重定义「无框」语义，区分真全屏与框丢失（L2989-3001 + 新方法）**
- `_rect_info_from_coord_entry(entry)`：不再凭空返回 `"fullscreen"`；`entry` 非 dict 或无 vertices → 返回 `(), None`；drag 双框判定（L2994-2997）保持原样。
- 新增 `_step_json_coordinates(step_data)`：从 `step_data["actions"][0]` 取 `coordinate` / `start_coordinate`，缺失或非 list/长度不足 → `None`。
- 新增 `_classify_coord_state(step_data, coord_entry)` → `(rect_info, selection_type, issue)`，`issue ∈ {None, "absent", "mismatch", "no_box"}`：
  1. 动作不在 `COORD_ACTION_TYPES`：`entry is None` → `(), "fullscreen", None`（沿用现状）；否则返回 `_rect_info_from_coord_entry` 结果 + `None`。
  2. `has_coord = coordinate 非 None 且非 (0, 0)`。
  3. `entry is None` 或 `_rect_info_from_coord_entry` 得到空 rect → `has_coord` 时 `(), None, "absent"`；否则 `(), "fullscreen", "no_box"`（真全屏，保留校验豁免）。
  4. 有框但 `has_coord` 且中心与 JSON 坐标差 >1px → **不采信该框**：`(), selection_type_from_entry, "mismatch"`。
  5. 其余 → 正常加载，`issue=None`。
- 关键约束：`"absent"`/`"mismatch"` **绝不**写 `selection_type="fullscreen"`，避免 L1504-1505 的豁免把丢框变成静默缺陷。

**A3. hydration 现场登记与可见告警（L3070-3099）**
- `steps.append({...})` 增两键：`"coord_issue": issue`、`"orig_coord_entry": copy.deepcopy(coord_entry) if issue in ("absent", "mismatch") and coord_entry else None`。
- 循环内累加 `self._coord_issues: list[tuple[int, str, str, str]]`（步序、动作中文、issue、`"盘上 center=[..] / JSON coordinate=[..]"` 详情）。
- 循环结束（在 L3101 `display_step` 之前）若 `self._coord_issues` 非空：`QMessageBox.warning` 汇总（标题「coords 与坐标值不一致」，逐条列出，正文说明「这些步骤的框未载入，保存不会改动盘上原条目；如需修复请在原图重新拉框，或运行 `tools/coords_center_repair.py` 做中心对齐重建」），并 `self.status_label.setText(f"检测到 {n} 个步骤的 bbox 与 coordinate 不一致")`。
- `__init__` 中初始化 `self._coord_issues = []`；`_drop_all_step_pages`/`start_new_round` 的重置路径一并清空（与 `_coords_rounds` 同处）。

**A4. 写回保留盘上原条目，杜绝「修复动作本身造成丢框」（`_collect_coords_entries` L2563-2611）**
- 在 L2571-2573 的 `if not rect_info: continue` 之前插入：
  ```
  orig = step.get("orig_coord_entry")
  if not rect_info and isinstance(orig, dict):
      # 编辑态检测到盘上 bbox 与 coordinate 不一致/缺失：不采信也不丢弃，
      # 按当前步序重编号后原样保留，避免「打开看一眼就丢数据」
      entries.append({**copy.deepcopy(orig), "step": i})
      continue
  ```
- 该分支的 action 过滤沿用现有 `coord_action_types` 判定：若用户把动作改成了非坐标类型，则走 L2579-2580 的 `continue`，条目应被丢弃（语义正确）。
- 正常采标路径无 `orig_coord_entry` 键 → 行为完全不变。

**A5. 写回守卫 + 内存赋值下移（`save_edited_round` L3192-3248）**
- 新增 `_audit_coord_consistency(trajectory, entries)` → 不一致项列表。只审计**本轮由内存 rect_info 新生成**的条目（即 `entries` 中 `step` 对应 `trajectory[step]` 的动作 ∈ `COORD_ACTION_TYPES` 且该步在 `_coord_issues` 中不存在），逐条比 `center ↔ coordinate`（drag 加 `start_center ↔ start_coordinate`），容差 1px。
- 重排：L3211-3212 改为先算局部 `new_entries = self._collect_coords_entries()`，**审计通过后**再执行 `self.rounds[round_index]["trajectory"] = trajectory` 与 `self._coords_rounds[round_index] = new_entries`（与 B40 的 messages 校验同样是「先验后改」）。
- 审计失败：`silent=True` → `print(f"编辑写回中止（gui_{self.gui_number}）：{原因}")` 并 `return False`；`silent=False` → `QMessageBox.critical(self, "错误", 原因 + "\n已拒绝写回，磁盘上的原文件未改变！")` 并 `return False`。位置在 L3244 `backup_final_json` 之前（守卫失败连 `.bak` 都不生成，保证目录零变化）。
- 在 L3277 之后（成功写回末尾）若 `self._coord_issues` 非空，追加一次 `print` 提示继承性盘上缺陷未在本次消除。

**A6. 明确不做**
- 不给 `validate_step_at` 增加「bbox 不一致」阻塞规则：重拉框会经 `_init_editor_from_capture` 用新框中心**覆写已交付的 JSON coordinate**，阻塞式引导等于逼采集员改写已验收数据，且会让 300 步任务因个别历史条目整体无法保存。检测与告警由 A3/A5 承担。

### B. 测试侧

**B1. `tests/invariants.py` 新增 INV-14（补假绿缺口）**
- 新增 `assert_coords_center_match(coords, trajectories, fullscreen_refs=None)`：按 (round, step) 定位条目（优先 `entry["round"]`，缺 round 时复用 `assert_coords_cover_refs` 的有序消费结果），对 `COORD_ACTION_TYPES` 逐条断言 `center == coordinate`（drag 加 `start_center == start_coordinate`），差 >1px 即 `raise AssertionError`，消息须包含「位置冒领/B6 遗留」提示与 `where`。
- 在 `assert_final_json` L351 之后串入调用（沿用 `_fullscreen`），`coord_refs` 扩展为携带 `actions[0]` 的 coordinate（L333 与 L417 的元组解包同步更新，仅此 2 处调用点）。
- 文件头 INV 清单与 `COORD_ACTION_TYPES` 注释（L25-32）补一行 INV-14 说明。

**B2. `tests/test_edit_completed.py` 新增 4 个回归用例**（复用现有 `_make_dataset` / `_write_dataset` / `_prepare` 与 `helpers.open_edit_mode`、`invariants.assert_edit_writeback_preserved`；坐标输入只读，构造数据时直接写 JSON `actions[0]["coordinate"]`）
1. `test_legacy_coords_missing_scroll_entry_does_not_steal_neighbor_box`：2 步（step0 `left_click`、step1 `scroll`）JSON，coords 仅含 step0 条目（模拟 B6 交付）。断言 `editor.steps[1]["rect_info"] == ()`、`editor.steps[1]["coord_issue"] == "absent"`、`editor.steps[1]["selection_type"] != "fullscreen"`；写回后 step0 条目逐字段不变，且 coords 未出现被冒领的第二组顶点。
2. `test_legacy_entry_step_drift_recovered_by_center`：coords 条目 step 编号漂移（写成 0/1 而轨迹 scroll 在 2），`center` 与 JSON `coordinate` 相同 → 断言按 center 恢复，`rect_info == (120, 308, 64, 15)` 形态正确、`coord_issue is None`。
3. `test_center_mismatch_not_loaded_and_disk_entry_preserved`：条目 step 匹配但 `center` 与 `coordinate` 差 >1px → `rect_info == ()`、`coord_issue == "mismatch"`；显式保存（`helpers.open_edit_mode` + 只改 intent 后 `save_edited_round()`）后该条 coords 与盘上原值逐字段相等（不丢、不新污染），JSON 非编辑轮由 INV-13 保证。
4. `test_writeback_guard_rejects_inconsistent_fresh_box`：`invariant.snapshot_dir` 先拍快照，直接把 `editor.steps[i]["rect_info"]` 改成与坐标输入不一致的值（不更新输入框），`save_edited_round(silent=True)` 返回 `False`，`assert_dir_unchanged` 通过（连 `.bak` 都不生成）。
- 每个用例结尾调 `I.assert_final_json(...)`，确认 INV-14 生效；用例 1/3 传 `fullscreen_refs` 时需覆盖到「absent/mismatch 步」的处理约定（在 docstring 写明该步由 INV-14 跳过、由覆盖层跳过的具体传参）。

**B3. 修复脚本单测 `tests/test_coords_center_repair.py`**
- dry-run 只报告不改盘；仅 `center != coordinate` 的条目被平移，宽高保持；其余条目逐字节不变；总条数与 round 字段不变；写前生成 `.bak`；幂等（第二次运行 0 修改）；drag 双中心各自对齐；`--verify` 在无 GUI 环境下可独立跑（脚本不 import PyQt5）。

### C. 数据侧：`tools/coords_center_repair.py`（新建，含 `tools/__init__.py`）

- CLI：`python tools/coords_center_repair.py <gui_XXXXXX 目录> [--dry-run|--apply] [--verify] [--tol 1]`；仅依赖 stdlib（`json`/`shutil`/`argparse`/`re`），`from dataclasses import dataclass`。
- 逻辑：读 `gui_XXXXXX.json` 全部 assistant trajectory 与 `gui_XXXXXX_coords.json`；按 (round, step) 归属（优先 `entry["round"]`，无 round 用 `save_edited_round` 同口径的有序消费）；对 `action ∈ COORD_ACTION_TYPES` 且 `center` 与 `coordinate` 差 > tol 的条目，**保留原 w/h 平移 vertices** 使 `x + w//2 == coordinate[0]`、`y + h//2 == coordinate[1]`（drag 分别平移 start/end）；其余条目原样输出（键序保持）。
- 安全：`--apply` 前把原 coords 复制为 `<name>.coords_pre-repair.bak`；用 `tmp + os.replace` 原子写（与 `data_manager.save_coords_json` L438-446 同法）；输出变更清单；`--verify` 复用 INV-14 等价断言，非 0 退出码表示仍有不一致。
- 明确语义：这是**重建**（bbox 尺寸不可恢复），不是还原；脚本 docstring 与输出都需标注「中心对齐已交付 coordinate，尺寸沿用原条目宽高，供复核确认」。

### D. gui_000005 交付数据修复步骤

1. `python tools/coords_center_repair.py "\\NAS-TC\GUI采集300step\Windows\谢子轩\gui_000005" --dry-run` → 应恰好命中 4 条：step 44（center→[1533,928]，尺寸 64×15）、step 79（→[1096,973]，59×16）、step 100（→[1103,823]，71×20）、step 147（→[1510,538]，98×31），round 均为 0。
2. NAS 路径不可写时：先整目录拷到本地工作副本，`--apply` 后 `--verify` 通过再回传；PowerShell 里 UNC 用**单引号 + 单反斜杠**传参（双反斜杠会被 `python -c` 的原始字符串吞掉，此前已踩）。
3. 复核：条目总数仍 152，除上述 4 条外逐字节不变，`gui_000005.json` 不动（`.bak` 的 scroll coordinate 与正式版完全相同，已证 JSON 侧无错）。
4. 与既有规格 `\\NAS-TC\GUI采集300step\Windows\谢子轩\gui_000005\.trae\specs\fix-scroll-bbox-alignment\{spec,tasks,checklist}.md` 对齐后逐条勾选 tasks。

### E. 跨端同步（同一次交付内完成，口径与 A1/A2 一致）

- `安卓端\annotation_editor.py` L3453-3457：删除 `if coord_entry is None and i < len(round_coords): fallback = round_coords[i]` 的位置回退；补 center 恢复与「坐标缺失/不一致」标记，与该端 hydration 的 `steps_data` 结构对齐。
- `ios端\annotation_editor.py` L2702-2719：同上；iOS 端已有 `_group_coords_into_rounds`，只改条目查找层。
- `macos端`：grep 无 `load_from_completed_json` / 位置回退（编辑态 hydration 不存在）→ 不改。
- 两端各自 `tests/` 补一条与 B2-用例1 等价的回归（安卓 `安卓端\tests\`、iOS `ios端\tests\`），断言其自身 invariants 组合入口。

## 依赖关系

- A1 → A3（hydration 需先有 A1/A2 的新签名与分类结果）。
- A3 → A4（`orig_coord_entry` 键由 A3 写入，A4 才读得到）；A4 → A5（审计必须能识别 A4 保留下来的继承性条目并豁免）。
- B1 可与 A 并行编写，但 B2 的用例 1/2/3 依赖 A1-A4 完成，B2-用例 4 依赖 A5。
- C 独立于 A/B，可先落地以尽早修复交付数据；D 依赖 C。
- E 依赖 A1/A2 的最终判定口径定稿（避免两端漂移）。
- 建议提交切分：① A1-A5 + B1 + B2（Windows 根治）；② C + B3 + D（数据修复）；③ E（跨端一致）。

## 验证

```powershell
# Windows 端全量（必须先设 offscreen）
$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests -q
# 定向回归
python -m pytest tests/test_edit_completed.py tests/test_coords_center_repair.py tests/test_relabel_on_screenshot.py -q
# 正常采标路径未被 A4 影响的证据
python -m pytest tests/test_smoke.py tests/test_data_integrity_defects.py tests/test_dt_defects.py -q
# 修复脚本
python tools/coords_center_repair.py "<gui_000005 目录>" --dry-run
python tools/coords_center_repair.py "<gui_000005 目录>" --apply --verify
```
通过标准：全部 pytest 绿；用例 1/3/4 的断言逐条成立；gui_000005 `--verify` 退出码 0；手工用修复后工具打开 gui_000005 编辑态 → 4 个不一致步给出告警、其余 148 条 round-trip 后逐字节不变。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 去掉位置回退后，旧 coords 若 `step` 字段整体不可靠 → 编辑态大量步看不到框 | A1 的 center 精确匹配兜底（同 action + 差 ≤1px 才可认领）；A3 汇总告警明示；不改盘上任何数据；改动集中在 3 个函数，可单点回退 |
| A4 保留继承性缺陷条目 → 盘上不一致仍存在 | 有意取舍：工具不伪造框也不丢数据；由 C/D 或重新拉框显式解决；A5 末尾 print + B1/INV-14 保证任何新增污染都会红 |
| A5 重排 L3211-3212 影响 B40/B41 既有用例 | 先单跑 `tests/test_edit_completed.py` 全绿，再扩展新用例；B2-用例 4 用 INV-12 目录快照证明「零副作用中止」 |
| 1px 容差判定误报（奇数宽高取整） | 统一用 `abs(dx) <= 1 and abs(dy) <= 1`；A5 与 B1、C 共用同一容差常量与同一比较函数（`tools/coords_center_repair.py` 提供纯函数供产品侧 import） |
| 重拉框会改写已交付 coordinate | A6 明确不做阻塞校验；数据修复走 C 的中心对齐重建，保持 coordinate 不动 |
| NAS 目录权限/网络失败 | 本地工作副本修复 + `--verify` 后回传；脚本内建 `.bak` 与原子写 |
| 跨端不同步导致安卓/iOS 交付继续冒领 | E 与 ① 同一批交付，各端自带回归用例 |
| 新工具脚本被 PyInstaller 打包 | spec 的 `datas/hiddenimports/pathex` 均为空列表且显式列源码，`tools/` 不参与打包；无 pytest 配置文件，`pytest tests` 调用方式不变 |

## 已否决的方案

1. **只改数据不改代码**：gui_000005 修好，下个含 scroll 的任务重开编辑照样污染，不可接受。
2. **在工具内由 JSON coordinate 自动生成 bbox**：把「重建」混入采集产品，采集员无法察觉框尺寸是伪造的，语义失真；同样的平移逻辑放到离线脚本（C）并显式标注为重建，边界清晰。
3. **把缺条目的步骤标记为 `selection_type="fullscreen"`**（即保留 `_rect_info_from_coord_entry` 现状）：会命中 `validate_step_at` L1504-1505 的坐标豁免，让「框丢失」彻底静默通过校验——正是本次要修的失败模式的镜像。
4. **只给位置回退加边界保护 / 只在 A2 处修 `_rect_info_from_coord_entry`**：无法区分「合法的第 k 框」与「冒领的第 k 框」，根因仍在。
5. **在 `validate_step_at` 增加阻塞规则强制重拉框**：见 A6，会逼采集员改写已交付 coordinate 并大面积阻塞历史任务编辑。
6. **在 `_group_coords_by_round` 层修复**：gui_000005 的 round 字段与分组本身正确（152 条全在 round 0），错在条目查找层，分组层无可修。
7. **把 JSON 与 coords 改为同一事务提交**：`data_manager` 已是 `tmp + os.replace` 原子写，跨文件事务不解决「内存 rect_info 已被错框污染」的上游问题，且改动面显著变大。
8. **修 `_init_editor_from_capture` 在 hydration 时也同步坐标输入框**：会把错误 bbox 写进 JSON coordinate，把「coords 错」升级为「两份交付物都错」，方向相反。
