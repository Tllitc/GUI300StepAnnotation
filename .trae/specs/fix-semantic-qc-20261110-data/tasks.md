# Tasks

- [x] Task 1: 编写修复脚本 `qctools/fix_semantic_data_20261110.py`
  - [x] SubTask 1.1: 实现反引号修复——扫描 `role=user` 的 instruction，用正则删除 `(\.(?:xlsx|xls|docx|doc))` 后紧邻的反引号（扩展名大小写不敏感），统计每文件替换处数
  - [x] SubTask 1.2: 实现 gui_000005 的 CoT 字段级定点修复——按 `to_pseudo_record` 同口径（跳过 screenshot 步、跨 assistant 消息连续编号）定位伪步207，校验该步 CoT 串内"参观苏州博物馆"恰 1 次且该步 intent 与 text 均含"参管苏州博物馆"，再以完整 CoT 串做 raw 级 replace(old,new,1)；任一校验不符则中止报错；伪步189 的 3 处合法"参观"不得触碰
  - [x] SubTask 1.3: 实现 dry-run/`--apply` 开关、写盘前按相对路径备份到 `qctools/backup_semantic_fix_20261112/`、精确文本替换（不重新序列化 JSON）、修改清单与处数汇总输出

- [x] Task 2: Dry-run 复核目标清单
  - [x] SubTask 2.1: 不带 `--apply` 跑脚本，确认命中 11 个 Windows 文件共 15 处反引号（gui_000016/000017/000022/000029 各 2 处，其余 7 个文件各 1 处；其中 gui_000023 仅 .xlsx 后 1 处）+ gui_000005 的 1 处 CoT，且无计划外文件被列入、零错误退出

- [x] Task 3: 执行修复并验证数据完整性
  - [x] SubTask 3.1: 带 `--apply` 执行，确认 12 个备份文件已生成且与原文件内容一致（备份发生在写入前）
  - [x] SubTask 3.2: 修复后全部 100 个 JSON 通过 `json.load` 解析；复核 15 处反引号已消失且仅删除了反引号字符（与备份做差异比对，每个文件差异仅限目标字符）
  - [x] SubTask 3.3: 复核 gui_000005 步207 的 intent、action.text 仍为"参管"，CoT 已改为"参管"，其余步骤零改动

- [x] Task 4: 重跑语义质检验证归零
  - [x] SubTask 4.1: 运行 `python qctools/check_semantic_origin.py \\NAS-TC\GUI采集300step\交付数据 --out qctools/语义问题报告_修复后_20261112.md --json qctools/明细_修复后_20261112.json`，确认有问题任务 0、各类计数 0、解析失败 0（备份目录对照实验复现 12 条原始问题，证明工具未失效）

# Task Dependencies

- Task 2 depends on Task 1
- Task 3 depends on Task 2
- Task 4 depends on Task 3
