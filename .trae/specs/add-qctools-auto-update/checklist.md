# Checklist

- [x] `qctools/app_version.py` 存在，常量与函数齐全：`__version__="1.0.0"`、`PUBLISH_DIR` 指向 `...\工具\GUI质检标注工具`、`EXE_NAME="GUI质检标注工具.exe"`、`SPEC_FILE="main.spec"`，且 `parse_version/is_newer/bump_patch` 行为与根目录一致
- [x] `qctools/build_release.py` 可独立执行，逻辑与根目录脚本一致：缺 PyInstaller 时提示并退出；按 `main.spec` 打包；发布 exe 与 `version.json`；成功后补丁位 +1，失败时不自增
- [x] `build_release.py --set-version 9.9.9` 能正确校验格式并写回版本号；非法格式报错退出（实测 `bad-version` 被拒、退出码 1、版本文件未被改动）
- [x] `build_release.py --publish-dir <本地目录>` 无需 NAS 权限即可完成完整发布流程（实测发布 1.0.1 到本地临时目录，version.json 正确，版本自增为 1.0.2）
- [x] `qctools/updater.py` 基于 PyQt6 实现，文件内不存在 PyQt5 导入；所有 Qt 枚举使用 PyQt6 限定写法（如 `Qt.Key.Key_Escape`）
- [x] `updater.ensure_latest` 在非 frozen 环境、exe 位于发布目录内、清单读取超时/损坏、下载失败时均静默返回，不抛异常、不阻断启动（20 项离线逻辑检查覆盖）
- [x] 清单版本高于本地版本时，能生成 `.GUI质检标注工具.new.exe` 临时文件及 `.update_*.bat/.ps1` 辅助脚本，脚本内容包含等待旧进程、Move-Item 替换、重启与自清理逻辑（端到端链路实测通过）
- [x] `qctools/main.py` 在 QApplication 创建后、主窗口显示前调用 `updater.ensure_latest(app)`；源码运行时该调用为空操作（源码模式冒烟测试通过）
- [x] 主窗口标题包含版本号，形如 `GUI质检标注工具 v1.0.x`（冻结 exe 实测标题为 `GUI质检标注工具 v1.0.1`）
- [x] `qctools/main.spec` 的 hiddenimports 包含 `app_version`、`updater` 及原有两个语义质检模块；exe `name` 与 `EXE_NAME` 词干一致（`GUI质检标注工具`），build_release 能在 dist 中找到产物（实测产物 58MB 单文件）
- [x] 本地端到端验证通过：构建发布到本地目录 → 运行 exe 标题版本正确 → 抬高清单版本后再次运行可完成下载替换重启 → 临时脚本被清理（9 项链路检查全部 PASS）
- [x] 未改动与本需求无关的既有代码；新增文件均位于 `qctools/` 目录内
