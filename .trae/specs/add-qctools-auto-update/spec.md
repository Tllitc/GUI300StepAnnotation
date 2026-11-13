# qctools 质检工具构建发布与在线更新 Spec

## Why
`qctools/main.py`（GUI 质检标注工具，PyQt6）目前只有源码和一个手工维护的 `main.spec`，缺少与根目录 Windows 版、安卓端、iOS 端一致的一键发布与启动静默自动更新能力。版本迭代后无法保证质检人员运行最新版，需要仿照 `build_release.py` / `updater.py` 机制补齐。

## What Changes
- 新增 `qctools/app_version.py`：qctools 版本号与发布地址的唯一来源（初始版本 `1.0.0`），发布到独立 NAS 子目录，使用独立 exe 名与版本号，与其他产品互不影响。
- 新增 `qctools/build_release.py`：仿照根目录 `build_release.py`，通过现有 `main.spec`（`SPEC_FILE`）调用 PyInstaller 打包，复制 exe 到 NAS 发布目录并写入 `version.json`，成功后版本号补丁位 +1 写回；支持 `--publish-dir` 与 `--set-version` 参数。
- 新增 `qctools/updater.py`：移植根目录 `updater.py` 的静默自更新流程（NAS 清单检查 → 进度框下载 → bat/ps1 进程退出后替换重启），适配 **PyQt6**（枚举写法与信号槽差异）。
- 修改 `qctools/main.py`：在 `QApplication` 创建后、主窗口显示前调用 `updater.ensure_latest(app)`；主窗口标题显示当前版本号。
- 修改 `qctools/main.spec`：补齐 `app_version`、`updater` 两个 hiddenimports，保证单文件打包后更新模块可用。
- 容错与防护与现有产品一致：非 frozen 环境、从发布共享目录直接运行、NAS 不可达、清单损坏、下载失败时均静默跳过，不阻塞旧版本启动。

## Impact
- Affected specs: 无（qctools 新增"构建发布"与"自动更新"能力，复用既有 DriveDeploy 更新模式）
- Affected code:
  - 新增 `qctools/app_version.py`、`qctools/build_release.py`、`qctools/updater.py`
  - 修改 `qctools/main.py`（入口接入更新、标题版本号）
  - 修改 `qctools/main.spec`（hiddenimports）
- 参考实现：根目录 `build_release.py`、`updater.py`、`app_version.py`，以及 `安卓端/`、`ios端/` 的同名三件套
- 关键差异：qctools 使用 **PyQt6**（其余产品为 PyQt5），updater 移植需处理枚举差异（如 `Qt.Key_Escape` → `Qt.Key.Key_Escape`）
- 发布目录结构：
  ```
  \\NAS-TC\GUI采集300step\工具\GUI质检标注工具\
      GUI质检标注工具.exe    # 最新版可执行文件
      version.json          # {"version":"1.0.0","exe":"GUI质检标注工具.exe","published_at":"..."}
  ```

## ADDED Requirements

### Requirement: qctools 版本源文件
系统 SHALL 在 `qctools/app_version.py` 中集中维护 `__version__`、`PUBLISH_DIR`、`EXE_NAME`、`MANIFEST_NAME`、`SPEC_FILE` 常量及 `parse_version` / `is_newer` / `bump_patch` 函数，供构建与更新模块共同导入。

#### Scenario: 独立发布配置
- **WHEN** 查看 `qctools/app_version.py`
- **THEN** `PUBLISH_DIR` 指向 `\\NAS-TC\GUI采集300step\工具\GUI质检标注工具`，`EXE_NAME` 为 `GUI质检标注工具.exe`，`SPEC_FILE` 为 `main.spec`，初始 `__version__` 为 `1.0.0`

### Requirement: 一键构建发布
系统 SHALL 提供 `qctools/build_release.py`，一条命令完成 PyInstaller 打包（按 `main.spec`）并将 exe 发布到 NAS 子目录，同时生成 `version.json`。

#### Scenario: 正常构建发布
- **WHEN** 在 `qctools` 目录执行 `python build_release.py`
- **THEN** 按 `main.spec` 构建出 `dist\GUI质检标注工具.exe`，复制到发布目录并写入含版本号与发布时间的 `version.json`，成功后 `app_version.py` 补丁位 +1

#### Scenario: 缺少 PyInstaller
- **WHEN** 构建机未安装 pyinstaller
- **THEN** 脚本提示 `pip install pyinstaller` 并以非零码退出，不产生半成品发布物、不自增版本号

#### Scenario: 发布失败
- **WHEN** NAS 不可达或无写入权限
- **THEN** 脚本报错退出，保留本地 dist 产物，版本号不自增

#### Scenario: 参数覆盖
- **WHEN** 执行 `python build_release.py --set-version 2.1.0 --publish-dir D:\local_release`
- **THEN** 先将版本写回 `app_version.py`，产物发布到指定本地目录，无需 NAS 权限即可验证流程

### Requirement: 启动自动检查并更新（PyQt6）
打包后的 qctools exe 每次启动 SHALL 自动检查发布目录的 `version.json`，发现新版本时显示模态进度框、后台下载新 exe 到同目录临时文件，并通过 bat + PowerShell 辅助脚本在当前进程退出后替换 exe、重启新版本并清理临时文件；全程无需用户确认。

#### Scenario: 发现新版本
- **WHEN** 本地 exe 版本低于清单版本且 NAS 可访问
- **THEN** 显示"软件更新"进度框，新 exe 暂存为同目录 `.GUI质检标注工具.new.exe`，辅助脚本启动后当前进程退出，替换并重启成功

#### Scenario: 已是最新版本
- **WHEN** 本地版本等于或高于清单版本
- **THEN** 无任何提示，正常进入主窗口

#### Scenario: 更新环境不可用
- **WHEN** 非 frozen 运行、exe 位于发布共享目录内、NAS 不可达、清单解析失败或下载失败
- **THEN** 静默跳过更新，正常启动当前版本

### Requirement: 版本可见
主窗口标题 SHALL 显示当前版本号，便于确认更新结果。

#### Scenario: 标题显示版本
- **WHEN** 程序启动
- **THEN** 主窗口标题形如 `GUI质检标注工具 v1.0.0`

### Requirement: 打包依赖完整
`qctools/main.spec` SHALL 保证 `app_version`、`updater` 及既有语义质检模块在单文件 exe 中可被导入。

#### Scenario: 打包后更新模块可用
- **WHEN** PyInstaller 按 spec 打包完成
- **THEN** exe 运行时 `import app_version` 与 `import updater` 不抛 ImportError，更新检查流程可执行
