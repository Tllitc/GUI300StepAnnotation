# Tasks

- [x] Task 1: 增强 INV-8 跨轮截图唯一性断言
  - [x] SubTask 1.1: 在 `tests/invariants.py` 的 `assert_final_json` 中新增跨轮全局截图名集合（与现有每轮 `seen_shots` 并列），跨轮重复时断言失败并报出截图名与两个轮次号
  - [x] SubTask 1.2: 保持现有轮内断言与其余校验行为不变，确认既有 21 个测试不回归

- [x] Task 2: 新增 4 轮采标复刻回归测试
  - [x] SubTask 2.1: 在 `tests/` 下（优先复用 `test_dt_defects.py` 既有 helper/夹具，必要时新建测试文件）编写连续 4 轮用例：前 3 轮以 answer 结束续轮，第 4 轮 terminate 正常结束；各轮步数不同（如 2/3/2/1）
  - [x] SubTask 2.2: 断言最终 messages 为 8 条、role 交替、4 个 trajectory 长度正确
  - [x] SubTask 2.3: 断言全部轮次截图名全局唯一、序号严格单调递增（首轮从 0001 起，之后跨轮接续不重置）
  - [x] SubTask 2.4: 断言 gui 目录磁盘 PNG 集合与 JSON 引用集合完全一致（数量相等、无悬空引用、无孤儿文件），并调用增强后的 `assert_final_json`

- [x] Task 3: 全量测试与收尾
  - [x] SubTask 3.1: 运行 `python -m pytest tests/ -q`，确认全部通过（原 21 项 + 新增用例）
  - [x] SubTask 3.2: 删除本次调查产生的临时文件：`_inspect_gui_000003.json`、`_inspect_gui_000003_coords.json`、`_analyze_rounds.py`

# Task Dependencies
- Task 2 依赖 Task 1（用例复用增强后的 INV-8 断言）
- Task 3 依赖 Task 1、Task 2
