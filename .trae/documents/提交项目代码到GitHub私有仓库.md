# 将项目代码提交到 GitHub 仓库

## Summary

为 `c:\Project\TC\300step采标工具` 初始化 Git 仓库，添加 `.gitignore` / `requirements.txt` / `README.md`，
在 GitHub 账号 **Tllitc** 下新建**私有**仓库 `GUI300StepAnnotation`，把四端源码 + 单元测试 +
`.trae` 规格文档 + `.vscode` 配置提交并推送到 `main` 分支。

提交范围约 **106 个文件、4.2 MB**（已实测统计），所有构建产物、第三方运行期二进制、样例采标数据、
含私钥的文件一律排除。

## Current State Analysis

- **不是 Git 仓库**：`git status` 返回 `fatal: not a git repository`。无 `.gitignore`、无 `README.md`、无 `requirements.txt`。
- **工作区 717 MB，绝大部分是不可提交的产物**：
  - `安卓端/dist` + `安卓端/build` ≈ 313 MB（单个 exe 73.2 MB）
  - `ios端/dist` + `ios端/build` ≈ 199 MB（单个 exe 46.1 MB）
  - 根 `dist` ≈ 43 MB + 根 `build` ≈ 46 MB
  - `安卓端/scrcpy` ≈ 15 MB、`安卓端/scrcpy_4.0` ≈ 38 MB（adb.exe、SDL3.dll 21.9 MB 等第三方二进制）
  - `ios端/ios.exe` 22.2 MB
  - `test/` 26.1 MB（13 组 `gui_0000NN` 真实 App 截图 + 标注 JSON）
  - `__pycache__/`、`.pytest_cache/`、`.screenshots/`（空）
- **源码为 4 套同源变体**：根目录（Windows）、`安卓端`、`ios端`、`macos端`，各含
  `main.py / annotation_editor.py / data_manager.py / screenshot_capture.py / app_version.py /
  build_release.py / updater.py`（`macos端` 只有前四个 + `main.spec`）以及各自的 `tests/`。
- **第三方依赖极少**（已全量 grep import）：`PyQt5`（全端）、`pynput`（仅 `macos端/main.py:42`）、
  `pytest`（tests）、`pyinstaller`（build_release.py）。其余均为标准库。
- **安全项**：
  - `ios端/selfIdentity.plist`（222 B，二进制 plist）内含 `identifier / privateKey / publicKey`，
    即**私钥**。虽已改为私有仓库，仍强制排除，不纳入版本控制。
  - `app_version.py`（根 / `安卓端` / `ios端` 各 1 处）硬编码内网发布路径
    `\\NAS-TC\GUI采集300step\工具\GUI长步骤采标工具-{Windows,Android,iOS}`。
    用户已选择**改为私有仓库**，因此**代码原样提交，不做脱敏改写**。
- **工具可用性**：
  - `git 2.47.0.windows.2` 可用；`gh` CLI **未安装**。
  - GitHub 连接器（`mcp_plugin_github_github_*`）已认证为 `Tllitc`（id 94032746），
    名下 6 个公开仓库均与本任务无关，需新建。
  - `~/.ssh` 只有 `config` 与 `known_hosts`，**无 SSH 私钥** → 只能走 HTTPS。
  - 系统级 `credential.helper=manager`，`git-credential-manager.exe` 存在；
    Windows 凭据管理器中**无 github.com 凭据** → 首次 `git push` 会触发 GCM 交互式授权。
  - 全局 git 身份是 Gitee noreply：`Tllitc <10135429+tllitc@user.noreply.gitee.com>`。

## Proposed Changes

### 1. 新建 `c:\Project\TC\300step采标工具\.gitignore`

内容（逐条对应上面的排除决策）：

```gitignore
# ---- Python ----
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/

# ---- 测试与缓存产物 ----
.pytest_cache/
.coverage
htmlcov/

# ---- 打包产物（四端各自的 dist/build，可由 build_release.py 重新生成）----
dist/
build/

# ---- 运行期截图工作目录 ----
.screenshots/

# ---- 样例采标数据（真实 App 截图 + 标注 JSON，体积大且属业务数据）----
/test/

# ---- 第三方运行期二进制（需自行下载放置，见 README）----
/安卓端/scrcpy/
/安卓端/scrcpy_4.0/
/ios端/ios.exe

# ---- 本地凭据，绝不入库 ----
/ios端/selfIdentity.plist

# ---- 操作系统 ----
.DS_Store
Thumbs.db
desktop.ini
```

要点：
- `/test/` 必须带前置斜杠并结尾带斜杠，否则会与单元测试目录 `tests/` 混淆（实测 `tests/` 需入库）。
- `dist/`、`build/` 不加前置斜杠，以便同时命中 `安卓端\dist`、`ios端\build` 等嵌套目录。
- **不排除** `.vscode/` 与 `.trae/`（用户明确要求纳入）。

### 2. 新建 `requirements.txt`

```
PyQt5>=5.15
pynput>=1.7
pytest>=7.0
pyinstaller>=5.0
```

只列实际 grep 到的第三方 import；`pynput` 仅 `macos端` 使用，注释说明。

### 3. 新建 `README.md`

中文，控制在 1 屏内，覆盖：
- 工具用途（GUI 长步骤采标，支持 300+ 步骤长轨迹）。
- 目录结构表：根目录=Windows 版、`安卓端`=Android 版（scrcpy/adb 投屏）、`ios端`=iOS 版、`macos端`=macOS 版；
  四端为同源独立分支副本，不共享代码；各端 `tests/` 为 pytest 单元测试。
- 环境准备：`pip install -r requirements.txt`。
- 运行：`python main.py`（在对应端目录下执行）。
- 测试：`python -m pytest tests -q`。
- 打包：`python build_release.py [--set-version X.Y.Z] [--publish-dir DIR]`，
  版本号唯一来源为同目录 `app_version.py` 的 `__version__`，构建成功后补丁位自增。
- **外部依赖提示（必须写）**：仓库不含 `安卓端/scrcpy`、`安卓端/scrcpy_4.0`、`ios端/ios.exe`；
  `安卓端/GUI长步骤采标工具-Android.spec` 的 `datas` 捆绑这两个 scrcpy 目录，
  克隆后需自行放入同名目录，否则安卓端打包失败。
- 发布目录（NAS 共享）由 `app_version.PUBLISH_DIR` 指定，需内网可达。

### 4. 初始化仓库并设置本仓库身份

```powershell
git init -b main
git config --local user.name "Tllitc"
git config --local user.email "94032746+Tllitc@users.noreply.github.com"
git config --local core.quotepath false
```

- 仅 `--local`，**不改动全局 git 配置**。
- GitHub noreply 邮箱由连接器返回的用户 id `94032746` + login `Tllitc` 拼成，提交可关联到 GitHub 账号。
- `core.quotepath false` 让 `git status` 正常显示 `安卓端/`、`ios端/` 等中文路径。

### 5. 用 GitHub 连接器创建私有空仓库

调用 `mcp_plugin_github_github_create_repository`：
- `name`: `GUI300StepAnnotation`
- `private`: `true`
- `autoInit`: **`false`**（关键：必须为空仓库，否则远端 README 会造成首推冲突）
- `description`: `GUI 长步骤采标工具（Windows / Android / iOS / macOS 四端 + pytest 测试）`

### 6. 暂存、提交、推送

```powershell
git add .
git status --short            # 核对：应为 106 个文件，且无 dist/build/test/scrcpy/ios.exe/selfIdentity.plist
git commit -m "Initial commit: GUI长步骤采标工具（Windows/Android/iOS/macOS 四端源码 + 单元测试）"
git remote add origin https://github.com/Tllitc/GUI300StepAnnotation.git
git push -u origin main
```

提交信息按仓库为全新历史，单条初始化提交即可（不拆分，避免无意义历史）。

**推送鉴权处理**（`gh` 不存在、无 SSH key、无已存 GitHub 凭据）：
1. 先按沙箱内直接 `git push` 试一次。
2. GCM 需要写 Windows 凭据管理器并打开浏览器，均在沙箱可写范围之外 —— 一旦卡在鉴权或报
   `could not read Username`/`authentication required`，用
   `dangerouslyDisableSandbox: true` 重试同一条 `git push`，让 GCM 走完交互式授权。
3. 若仍失败，停止并告知用户两种解法（浏览器授权未完成 / 需要 PAT），不要反复重试同一条命令。
4. 最后兜底方案：`mcp_plugin_github_github_push_files`（API 逐文件提交）—— 仅在 git push 彻底不可用时考虑，
   且需排除 4 个 `.ico`/`.icns` 二进制文件（约 2.6 MB base64，连接器不稳）。默认不走这条。

## Assumptions & Decisions

| 项 | 决定 | 依据 |
|---|---|---|
| 仓库可见性 | **私有**，名 `GUI300StepAnnotation`，owner `Tllitc` | 用户在第二轮明确「改为私有仓库」 |
| 内网 NAS 路径 | **原样提交，不改代码** | 已选私有，无需脱敏；不做未被要求的改写 |
| `dist/` `build/` | 排除 | 合计 ≈ 600 MB，单文件最大 73 MB，可由脚本重建 |
| `test/` 样例数据 | 排除 | 用户选择中未勾选；26 MB 真实截图 |
| `scrcpy*` / `ios.exe` | 排除 | 用户未勾选第三方二进制；外部发行物 |
| `.trae/` `.vscode/` | **纳入**（37 + 1 文件） | 用户勾选 |
| `logo17.ico`/`logo11.ico`/`logo15.ico`/`logo.icns` | 纳入 | 打包 `--icon`/`icon=` 必需，合计 ≈ 2.6 MB |
| `selfIdentity.plist` | **强制排除** | 内含 privateKey |
| 单元测试目录 `tests/` | 纳入 | 用户勾选「四端源码 + tests」 |
| 磁盘上的产物文件 | **不删除、不移动** | 任务只要求提交代码，不做清理 |
| 默认分支 | `main` | 与账号下现有仓库一致 |

## Verification

1. `git ls-files | Measure-Object -Line` → 期望 **106**（新增 `.gitignore`/`README.md`/`requirements.txt` 后为 **109**）。
2. `git ls-files | Select-String -Pattern 'dist/|build/|scrcpy|ios\.exe|selfIdentity\.plist|^test/'` → **必须无输出**。
3. `git check-ignore -v "ios端/selfIdentity.plist" "test/gui_000001" "安卓端/dist/GUI长步骤采标工具-Android.exe" "安卓端/scrcpy_4.0/SDL3.dll"` → 四条均命中规则。
4. `git ls-files | Select-String '^tests/|^安卓端/tests/|^ios端/tests/|^.trae/|^\.vscode/'` → 四个目录均有文件（确认未被误排除）。
5. `git log --oneline -1` + `git log -1 --pretty='%an <%ae>'` → 作者为 `Tllitc <94032746+Tllitc@users.noreply.github.com>`。
6. `git remote -v` 与 `git status -sb` → `## main...origin/main` 无落后。
7. 连接器无 `get_repository` 接口，改用：
   `mcp_plugin_github_github_search_repositories`（`query: "user:Tllitc GUI300StepAnnotation"`）
   确认 `private: true`、`default_branch: main`；再用
   `mcp_plugin_github_github_get_file_contents`（`repo: Tllitc/GUI300StepAnnotation`, `path: README.md`）
   确认远端已收到本次提交内容。
8. 本地不受影响：`python -m pytest tests -q`（根目录）仍能通过，证明 `.gitignore` 未删除任何被测试依赖的文件。
