# Checklist

- [x] `app_version.py` 存在，包含 `__version__`（初始 1.0.0）、发布目录常量与版本比较/自增函数
- [x] 执行 `python build_release.py` 可成功生成单文件、无控制台、带 logo17.ico 图标的 `dist\GUI采集标注工具.exe`
- [x] 未安装 pyinstaller 时脚本给出明确安装提示并退出，不产生不完整发布物
- [x] 构建发布后发布目录中存在 exe 与合法的 `version.json`（含 version、exe、published_at）
- [x] 每次成功发布后 `app_version.py` 的补丁位自动 +1；发布失败时版本号不变
- [x] `--publish-dir` 参数可将发布目标切换为本地目录
- [x] exe 启动时自动检查 NAS 版本；有新版本时显示更新进度、自动下载、替换、重启为新版本
- [x] 更新通过退出后的等待批处理完成（进程运行中无法直接覆盖 exe 的问题已解决），临时 .new.exe/.bat 被清理
- [x] 已是最新版本时无任何提示，直接进入主窗口
- [x] NAS 不可达、version.json 损坏、下载失败等异常均静默跳过，程序正常启动
- [x] 从发布共享目录直接运行 exe 时不执行自更新；Python 源码运行时不执行更新检查
- [x] 主窗口标题包含当前版本号，如 `GUI 采集标注工具 v1.0.5 - 任务初始化`
