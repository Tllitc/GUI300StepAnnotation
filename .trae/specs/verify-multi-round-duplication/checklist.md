# Checklist

- [x] `tests/invariants.py` 的 `assert_final_json` 含跨轮全局截图名集合，跨轮重复时断言失败并指明截图名与轮次
- [x] 轮内截图唯一、role 交替、step 连续、引用文件存在等既有校验保持不变
- [x] 新增 4 轮（3 次 answer 续轮 + 末轮 terminate）回归用例存在并可运行
- [x] 用例断言最终 messages 为 8 条且 4 个 trajectory 长度与采集步数一致
- [x] 用例断言全部截图名跨轮全局唯一、序号跨轮严格单调递增不重置
- [x] 用例断言磁盘 PNG 集合与 JSON 引用集合完全一致（数量相等、无悬空、无孤儿）
- [x] `python -m pytest tests/ -q` 全部通过（原 21 项不回归，新增用例通过）—— 实测 22 passed
- [x] 未改动任何生产代码（main.py / annotation_editor.py / data_manager.py）—— 文件修改时间均早于实施时间
- [x] 临时调查文件 `_inspect_gui_000003.json`、`_inspect_gui_000003_coords.json`、`_analyze_rounds.py` 已删除
