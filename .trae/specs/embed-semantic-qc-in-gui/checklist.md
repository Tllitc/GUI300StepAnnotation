# Checklist

- [x] main.py 容错导入 check_semantic_origin/check_semantic_v1，模块缺失时启动不崩溃、原有功能可用（冒烟测试模拟 ImportError 验证通过）
- [x] 顶部存在「语义质检」按钮，未加载文件夹或模块缺失时禁用，运行中防重入且有进行中状态（`_update_qc_button_state`，运行中显示「质检中…」）
- [x] 加载文件夹后自动触发一次后台质检；重新加载文件夹后旧结果不会写入 UI（版本号校验，冒烟测试覆盖过期丢弃逻辑）
- [x] 质检运行期间界面可拖动、可切换任务、可翻页，无无响应（QThread 后台执行 + 信号回传）
- [x] 单个 gui JSON 解析/转换异常被计入解析失败，不中断整批（worker 逐文件 try/except，冒烟测试损坏文件验证通过）
- [x] GUI 检查直接复用 to_pseudo_record + check_record（含 extra_tasks 任务文本检查），未在 GUI 内重写 B/C/D 规则（`check_semantic_one_file`）
- [x] 同一文件夹 GUI 结果与命令行 check_semantic_origin.py 的类别、步号、描述口径一致（冒烟测试 (cat,step,desc,extra,shot) 五元组集合逐字段相等）
- [x] 任务列表正确区分有问题 / 无问题 / 解析失败三种状态，有问题项显示问题数与警示配色（`●N` 红色 / `⚠` 橙色 / 默认）
- [x] tooltip 使用 CATS 全称展示各类别条数；质检未完成的任务不显示「无问题」（结果字典无 key 时保持原样）
- [x] 伪步→GUI 页映射跳过 screenshot 合成步、从 0 连续编号，跳转后截图文件名与结果 shots[N] 一致（冒烟测试断言 {0:'step_1.png',1:'step_2.png'}）
- [x] 双击带步号问题可跳到对应页面；步号为 None 的任务级问题只切换任务不翻页；映射缺失有提示且不崩溃（statusBar 轻量提示）
- [x] 选中任务时明细面板展示该任务全部问题（类别/步号/截图/描述/附加），并具备空态文案（未选择/进行中/解析失败/未发现问题四种）
- [x] 保存修复后仅重检当前任务：问题归零时标记与明细清空，其他任务标记不变；重检失败有失败态提示（冒烟测试修复反引号+C1 后归零验证通过）
- [x] 质检全过程只读，不产生任何新文件、不修改 JSON 与截图（写盘仅由保存按钮触发；代码检索确认无 md/json 导出）
- [x] main.spec 的 hiddenimports 包含 check_semantic_v1 与 check_semantic_origin
- [x] 不包含 md/json 报告导出入口（导出仍走命令行）
