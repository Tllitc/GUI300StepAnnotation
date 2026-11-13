# Tasks

- [x] Task 1: 新增 `qctools/app_version.py` 版本源文件
  - [x] SubTask 1.1: 仿照 `安卓端/app_version.py` 定义常量：`__version__="1.0.0"`、`PUBLISH_DIR=r"\\NAS-TC\GUI采集300step\工具\GUI质检标注工具"`、`EXE_NAME="GUI质检标注工具.exe"`、`MANIFEST_NAME="version.json"`、`SPEC_FILE="main.spec"`
  - [x] SubTask 1.2: 实现 `parse_version` / `is_newer` / `bump_patch` 三个函数（与根目录逻辑一致）

- [x] Task 2: 新增 `qctools/build_release.py` 一键构建发布脚本
  - [x] SubTask 2.1: 移植根目录 `build_release.py` 全部流程（PyInstaller 检测、版本确定、spec 打包、发布复制、version.json 清单、成功后补丁位 +1）
  - [x] SubTask 2.2: 保留 `--publish-dir`、`--set-version` 参数；因 `SPEC_FILE` 已指定，走 spec 打包分支，删除/保留的命令行分支以根目录实现为准不做多余改动

- [x] Task 3: 新增 `qctools/updater.py` 并适配 PyQt6
  - [x] SubTask 3.1: 移植根目录 `updater.py` 全部类与函数（清单看门狗、下载线程、更新进度框、bat/ps1 生成与启动重启）
  - [x] SubTask 3.2: PyQt6 适配：导入改为 `PyQt6.QtCore/QtWidgets`；枚举改写（`Qt.Key_Escape`→`Qt.Key.Key_Escape`，其余枚举按 PyQt6 规范核对）；确认 pyqtSignal、QThread、QEventLoop、QTimer 行为一致
  - [x] SubTask 3.3: 临时文件名基于 qctools 的 `EXE_NAME` 生成（`.GUI质检标注工具.new.exe`、`.update_GUI质检标注工具.bat/.ps1`），更新提示文案使用 qctools 产品名

- [x] Task 4: 修改 `qctools/main.py` 接入更新与版本展示
  - [x] SubTask 4.1: 顶部新增 `import app_version` 与 `import updater`（更新模块导入失败不得阻断 GUI 启动，可参考语义质检模块的降级风格或直接顶层导入，与根目录 main.py 保持一致）
  - [x] SubTask 4.2: 在 `main()` 中 `QApplication` 创建后、`MainWindow()` 构造前调用 `updater.ensure_latest(app)`
  - [x] SubTask 4.3: 主窗口标题改为包含版本号：`GUI质检标注工具 v{app_version.__version__}`（修改第 988 行 `setWindowTitle`）

- [x] Task 5: 更新 `qctools/main.spec` 的 hiddenimports
  - [x] SubTask 5.1: 在现有 `hiddenimports=['check_semantic_v1', 'check_semantic_origin']` 中追加 `'app_version'`、`'updater'`
  - [x] SubTask 5.2: 确认 spec 中 exe `name='main'` 与 `EXE_NAME` 的衔接——构建脚本依赖产物名为 `GUI质检标注工具.exe`，需将 spec 的 `name` 改为 `GUI质检标注工具`（与 app_version.EXE_NAME 对齐），避免 build_release 找不到产物

- [x] Task 6: 本地验证（不依赖 NAS）
  - [x] SubTask 6.1: 用 `--publish-dir` 指向本地临时目录执行 `python build_release.py --set-version 1.0.1`，确认 exe、version.json 生成且版本号自增为 1.0.2
  - [x] SubTask 6.2: 运行打包出的 exe，确认主窗口标题版本号正确、无更新时正常进入主界面；将发布目录版本改高后再次运行，验证下载-替换-重启链路（可在本地目录模拟）
  - [x] SubTask 6.3: 源码模式直接 `python main.py` 确认更新流程为空操作、GUI 正常启动

# Task Dependencies
- Task 2、Task 3 依赖 Task 1（导入 app_version）
- Task 4 依赖 Task 1、Task 3
- Task 5 依赖 Task 1（exe 名对齐）
- Task 6 依赖 Task 2、Task 4、Task 5
- Task 2 与 Task 3 之间无依赖，可并行
