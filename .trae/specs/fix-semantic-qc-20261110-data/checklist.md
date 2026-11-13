# Checklist

- [x] 修复脚本默认 dry-run 不写盘，只有显式 `--apply` 才修改文件
- [x] 11 个 Windows 任务 JSON 中 15 处反引号全部删除，且每处删除的仅是 `.xlsx/.docx` 后紧邻的那一个反引号字符
- [x] 反引号修复只作用于 `role=user` 的 instruction 字段，intent、CoT、actions 等其他字段未被触碰
- [x] gui_000005 伪步207（跳过 screenshot 步口径）CoT 中"参观苏州博物馆"已改为"参管苏州博物馆"，字段级定位、全文件替换只发生 1 次；伪步189 的 3 处合法"参观"（intent/CoT/text）原样保留
- [x] gui_000005 的 intent 与 action.text 保持"参管"不变，与截图 gui_000005_0209.png 实测输入一致
- [x] 12 个被修改文件在写盘前均已原样备份到 `qctools/backup_semantic_fix_20261112/`，目录结构与源路径对应
- [x] 修复文件与备份的差异比对仅包含目标字符（反引号 / CoT 单个词），无缩进、键顺序、Unicode 转义等附带变化
- [x] 修复后全部 100 个 gui JSON 可被 json.load 正常解析，无解析失败
- [x] 重跑 check_semantic_origin.py 全量质检结果为有问题任务 0，D 反引号 0、C2 0，35_1 批仍为 0
- [x] 未改动任何 PNG 截图及 20261103 批数据
