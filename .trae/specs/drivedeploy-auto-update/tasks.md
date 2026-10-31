# Tasks

- [x] Task 1: 创建版本管理模块 `app_version.py`
  - [x] SubTask 1.1: 定义 `__version__ = "1.0.0"` 与发布目录常量 `PUBLISH_DIR = r"\\NAS-TC\GUI采集300step\工具"`、`EXE_NAME = "GUI采集标注工具.exe"`
  - [x] SubTask 1.2: 提供版本比较函数 `is_newer(remote, local)`（按数字元组比较，容错非标准格式）与版本号自增函数 `bump_patch(version)`

- [x] Task 2: 实现构建发布脚本 `build_release.py`
  - [x] SubTask 2.1: 读取 `app_version.__version__`；检测 pyinstaller 是否可用（不可用则提示 `pip install pyinstaller` 并退出）；支持 `--publish-dir` 与 `--set-version` 参数
  - [x] SubTask 2.2: 调用 PyInstaller（`--onefile --noconsole --name GUI采集标注工具 --icon logo17.ico`，`--add-data` 不需要，无外部资源）打包 main.py，确保 4 个本地模块被自动收集（验证 dist exe 能启动）
  - [x] SubTask 2.3: 确保发布目录存在，将 dist 中的 exe 复制为 `<发布目录>\GUI采集标注工具.exe`，并写入 `version.json`（version、exe、published_at）；任一步失败则报错退出且不自增版本号
  - [x] SubTask 2.4: 发布成功后将补丁位 +1 写回 `app_version.py`（仅替换 `__version__` 行），控制台输出现发布版本与下一版本

- [x] Task 3: 实现自动更新模块 `updater.py`
  - [x] SubTask 3.1: `ensure_latest()`：仅在 `getattr(sys, "frozen", False)` 时执行更新流程；若 `sys.executable` 路径位于发布共享目录内则直接跳过
  - [x] SubTask 3.2: 读取 `<发布目录>\version.json`（带短超时，UNC 不可达/解析失败静默返回），比较版本，非新版本直接返回
  - [x] SubTask 3.3: 显示简单 QDialog 进度（"发现新版本 x.y.z，正在更新…"），后台线程将 NAS 上的新 exe 下载到本地同目录 `.<进程名>.new.exe`，完成后关闭对话框
  - [x] SubTask 3.4: 生成同目录临时 `.bat` + PowerShell 辅助脚本：等待原 exe 退出（Wait-Process 超时兜底）→ Move-Item 替换（失败重试）→ Start-Process 重启 → 自删；以 CREATE_NO_WINDOW 启动后退出当前进程（初版 DETACHED_PROCESS + tasklist|find + timeout 方案实测会挂起，已由 Task 6 修复）

- [x] Task 4: 在 `main.py` 接入更新检查与版本显示
  - [x] SubTask 4.1: `QApplication` 创建后、初始化窗口创建前调用 `updater.ensure_latest(app)`（注意它可能终止进程）
  - [x] SubTask 4.2: 初始化窗口标题附加当前版本号（`vX.Y.Z`）

- [x] Task 5: 端到端验证
  - [x] SubTask 5.1: 用 `--publish-dir` 指向本地临时目录执行两次构建：验证 exe 生成、version.json 内容、`app_version.py` 版本自增正确
  - [x] SubTask 5.2: 将首个 exe 复制到另一本地目录运行，再发布一次新版本：验证启动后自动下载替换、脚本重启、新版本生效（修复 Task 6 缺陷后实测通过，约 9 秒完成）
  - [x] SubTask 5.3: 断网/错误发布目录验证静默跳过、程序正常启动（4 个 monkeypatch 容错场景全部 PASS）

- [x] Task 6: 修复批处理在脱离控制台环境下挂起的缺陷（Task 5 实测发现）
  - [x] SubTask 6.1: `updater.py` 的 `_write_launch_and_exit` 启动标志去掉 `DETACHED_PROCESS`，仅保留 `CREATE_NO_WINDOW`
  - [x] SubTask 6.2: 移除会挂起的 `tasklist | find` 管道与 `timeout /t`，改用极简 bat 调用 UTF-8 BOM 的 PowerShell 辅助脚本（Wait-Process 带超时 + Move-Item 重试 + Start-Sleep），真实 E2E 复验通过

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 1
- Task 4 依赖 Task 1、Task 3
- Task 5 依赖 Task 2、Task 3、Task 4
