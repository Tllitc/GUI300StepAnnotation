# GUI 长步骤采标工具

面向 GUI 自动化数据采集的桌面标注工具，支持 300+ 步骤的长轨迹采标：区域截图、步骤标注编辑、
草稿续采、多轮（round）管理与校验，并可一键打包发布、在线静默升级。

## 目录结构

仓库内含四端**同源但各自独立**的副本，互不共享代码，修复需分别同步：

| 目录 | 目标平台 | 说明 |
| --- | --- | --- |
| `.`（根目录） | Windows | 主版本，含全局热键 `hotkey_manager.py` 与在线升级 `updater.py` |
| `安卓端/` | Android | 通过 scrcpy / adb 投屏采集手机画面 |
| `ios端/` | iOS | 通过 `ios.exe` 采集投屏画面 |
| `macos端/` | macOS | 使用 `pynput` 监听全局快捷键 |

各端主要文件：`main.py`（入口）、`annotation_editor.py`（标注编辑页）、`data_manager.py`（采标数据读写）、
`screenshot_capture.py`（截图）、`app_version.py`（版本号与发布配置）、`build_release.py`（一键打包发布）、
`*.spec`（PyInstaller 打包配置）；`tests/` 为该端的 pytest 单元测试。

## 环境准备

```bash
pip install -r requirements.txt
```

## 运行与测试

```bash
python main.py                    # 在对应端目录下执行，例如 安卓端/main.py
python -m pytest tests -q        # 运行该端单元测试（macOS 端暂无独立 tests）
```

## 打包发布

```bash
python build_release.py                          # 按当前版本号打包并发布到 app_version.PUBLISH_DIR
python build_release.py --set-version 1.2.0      # 手动指定本次发布版本（X.Y.Z）
python build_release.py --publish-dir D:\out     # 覆盖发布目录
```

版本号唯一来源为同目录 `app_version.py` 的 `__version__`；发布成功后补丁位自动 +1。
发布目录默认是 NAS 共享路径，需内网可达。

## 外部依赖说明

出于体积与许可考虑，仓库**不包含**以下运行期资源，需自行下载后放到对应位置，否则该端打包会失败：

- `安卓端/scrcpy/`、`安卓端/scrcpy_4.0/` —— `GUI长步骤采标工具-Android.spec` 的 `datas` 会捆绑这两个目录
- `ios端/ios.exe` —— `GUI长步骤采标工具-iOS.spec` 打包时引用

同时，`dist/`、`build/`、`test/`（样例采标数据）等产物与业务数据均已由 `.gitignore` 排除。
