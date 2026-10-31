# DriveDeploy 构建发布与自动更新 Spec

## Why
当前工具只有 Python 源码，分发到各标注人员机器上需要手动配置 Python/PyQt5 环境；版本迭代后也无法保证所有人使用最新版。需要一键打包成单 exe、发布到内网 NAS 共享目录，并在用户每次启动时静默自动更新。

## What Changes
- 新增 `build_release.py`：使用 PyInstaller 将 `main.py` 及其依赖（4 个本地模块 + PyQt5）打包为**单文件、无控制台窗口**的 Windows exe（复用现有 `logo17.ico` 图标）。
- 构建产物自动发布到 UNC 共享目录 `\\NAS-TC\GUI采集300step\工具`，并在该目录生成版本清单 `version.json`。
- 每次成功构建发布后，版本号（语义化 `主.次.补丁`）的补丁位自动 +1 并写回版本源文件。
- 新增 `app_version.py`：版本号与更新地址的唯一来源（初始版本 `1.0.0`）。
- 新增 `updater.py`：exe 启动时读取 NAS 上的 `version.json`，发现新版本则自动下载、通过批处理在进程退出后替换自身并重启；更新过程显示进度，无需用户确认。
- 修改 `main.py`：在 `QApplication` 创建后、主窗口显示前接入更新检查；窗口标题显示当前版本号。
- 容错：NAS 不可达、清单损坏、下载失败、权限不足时静默跳过更新，继续运行当前版本。
- 防护：exe 自身就位于发布共享目录内时不执行自更新（避免替换发布源）；Python 源码开发模式下不执行更新检查。
- 构建脚本支持 `--publish-dir` 参数（默认 `\\NAS-TC\GUI采集300step\工具`），便于在无 NAS 权限时用本地目录验证流程。

## Impact
- Affected specs: 无（新增"构建发布"与"自动更新"能力）
- Affected code:
  - 新增 `build_release.py`、`updater.py`、`app_version.py`
  - 修改 `main.py`（启动流程接入 updater，标题栏版本号）
  - 复用 `logo17.ico`
  - 构建机需安装 `pyinstaller`（脚本检测到缺失时给出安装提示）
- 发布目录结构：
  ```
  \\NAS-TC\GUI采集300step\工具\
      GUI采集标注工具.exe      # 最新版可执行文件
      version.json            # {"version":"1.0.5","exe":"GUI采集标注工具.exe","published_at":"..."}
  ```
- 使用方式：用户首次从 NAS 将 exe 复制到本地任意可写目录运行；之后每次启动自动从 NAS 更新。

## ADDED Requirements

### Requirement: 一键构建发布
系统 SHALL 提供 `build_release.py`，一条命令完成 PyInstaller 单文件打包并将 exe 发布到 `\\NAS-TC\GUI采集300step\工具`。

#### Scenario: 正常构建发布
- **WHEN** 在项目根目录执行 `python build_release.py`
- **THEN** PyInstaller 以 `--onefile --windowed` 方式构建出 `dist\GUI采集标注工具.exe`（图标为 logo17.ico），并复制到发布目录，同时生成包含新版本号和发布时间的 `version.json`

#### Scenario: 缺少 PyInstaller
- **WHEN** 构建机未安装 pyinstaller
- **THEN** 脚本中止并提示 `pip install pyinstaller`，不产生半成品发布物

#### Scenario: 发布目录不可写
- **WHEN** UNC 共享不可达或无写入权限
- **THEN** 脚本报错退出并保留本地 dist 产物，版本号不自增

### Requirement: 发布后自动更新版本号
系统 SHALL 在每次构建发布**成功后**，将版本号补丁位自动加 1 并写回 `app_version.py`，作为下一次构建的版本号。

#### Scenario: 版本自增
- **WHEN** 当前版本为 `1.0.3` 且发布成功
- **THEN** `app_version.py` 中 `__version__` 变为 `1.0.4`，本次发布到 NAS 的 exe 与 `version.json` 中的版本为 `1.0.3`

### Requirement: 启动自动检查并更新
打包后的 exe 每次启动 SHALL 自动检查发布目录上的 `version.json`，发现新版本时自动下载并完成替换重启，全程无需用户确认（仅显示"正在更新"进度提示）。

#### Scenario: 发现新版本
- **WHEN** 本地 exe 版本低于清单版本且 NAS 可访问
- **THEN** 程序显示更新进度，将新 exe 暂存为同目录 `.new.exe`，生成并 detached 启动等待批处理后退出；批处理等待进程结束、用新文件替换原 exe、重新启动新版本程序，并清理临时文件

#### Scenario: 已是最新版本
- **WHEN** 本地版本与清单版本相同或更高
- **THEN** 正常进入主窗口，无任何提示

#### Scenario: 更新环境不可用
- **WHEN** NAS 不可达、version.json 解析失败、下载失败或暂存目录不可写
- **THEN** 静默跳过本次更新，正常启动当前版本

#### Scenario: 从发布共享目录直接运行
- **WHEN** 运行中的 exe 路径位于发布共享目录内
- **THEN** 跳过自更新，直接运行（防止替换发布源）

### Requirement: 版本可见
主窗口标题 SHALL 显示当前版本号，便于确认更新结果。

#### Scenario: 标题显示版本
- **WHEN** 程序启动
- **THEN** 初始化窗口标题形如 `GUI 采集标注工具 v1.0.5 - 任务初始化`
