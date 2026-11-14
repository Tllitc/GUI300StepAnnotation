# Checklist

- [x] `qctools/qc_gui.py` 为独立入口，`python qc_gui.py` 可直接启动，且未修改 `main.py` / `check_semantic_origin.py` / `check_semantic_v1.py`
- [x] 检查规则全部经 `to_pseudo_record` + `check_record`（含 extra_tasks 补充检查）复用，GUI 内无任何重写的 B/C/D 规则
- [x] 支持添加多个目录/文件，重复 gui json 只质检一次（与 CLI `seen` 去重一致）
- [x] 质检在 QThread 后台运行，进度条/计数实时更新，窗口运行期可拖动操作、不无响应；可取消、运行中防重入
- [x] 单文件损坏计入解析失败清单且不中断整批，其余任务正常出结果
- [x] 分组汇总表含任务数、有问题任务数及 `CATS` 各类计数；类别总数表与分组表数字自洽（各类之和相等、有问题任务数口径正确）
- [x] 明细表含 分组/任务/步号/截图文件/类别/描述/附加，步号 None 显示「任务级」，支持列排序
- [x] 类别 + 分组 + 关键字组合筛选生效，并显示筛选后/总条数
- [x] 导出 md 复用 `check_semantic_origin.write_md`，与命令行 `--out` 同结构；导出 json 为 `{rows, stats, failed}` 与 CLI `--json` 一致；无结果时导出按钮禁用
- [x] 截图预览按 gui json 同目录拼接 `shot` 加载，缺图有友好提示不崩溃；「在资源管理器中显示」能打开目录并选中源文件
- [x] 程序全程只读，不存在任何修改 JSON/截图或编辑保存的入口
- [x] 检查模块导入失败时窗口仍可打开、运行/导出禁用并提示原因，无未捕获异常
- [x] 同输入下 GUI 结果与 `python check_semantic_origin.py` 的 rows 逐字段（类别/步号/截图/描述/附加）一致
- [x] 新增 `qctools/qc_gui.spec`（hiddenimports 含两检查模块），未改动现有 `main.spec`，打包后可启动
