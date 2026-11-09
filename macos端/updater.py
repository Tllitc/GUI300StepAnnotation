# -*- coding: utf-8 -*-
"""静默自动更新模块（仅 macOS 打包后生效）。

对外只暴露 ``ensure_latest(app=None)``，由 main.py 在 QApplication 创建后、
主窗口显示前调用。整体流程：

1. 仅在 PyInstaller 等冻结环境（``sys.frozen`` 为真）下执行更新流程；
2. 从 ``sys.executable`` 上溯 3 级定位当前 ``.app`` bundle；若该 bundle 直接
   运行自 NAS 发布共享目录，则跳过（避免替换发布源）；
3. 后台线程读取 ``<PUBLISH_DIR>/version.json``（4 秒看门狗，挂载点不可达快速失败）；
4. 发现新版本时弹模态“软件更新”进度框，后台线程用 ``ditto`` 把发布目录的
   ``.app`` bundle 保真复制到本地临时目录（不再解压 zip）；
5. 生成极简 bash 脚本：等当前进程退出 -> ``rm -rf`` 旧 bundle ->
   ``ditto`` 复制新 bundle 到位 -> ``open`` 重启新版本 -> 清理临时目录与脚本自身；
6. 以脱离会话（``start_new_session``）的方式启动脚本后，当前进程立即退出。

任何失败路径均静默返回，保证用户至少能用旧版本进入主界面。
非 frozen、非 macOS 环境下导入本模块不会报错。

注意：Gatekeeper 可能拦截未签名/未公证的 .app 替换，发布前建议对 bundle
签名并公证，或在部署文档中注明首次运行需“仍要打开”。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

from PyQt5.QtCore import Qt, QEventLoop, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QDialog, QLabel, QProgressBar,
                             QVBoxLayout)

import app_version

# 读取远程清单的看门狗超时时间（毫秒）
MANIFEST_TIMEOUT_MS = 4000

# 保存在途工作线程引用，防止线程对象被 Python 回收后出现崩溃
_alive_threads = set()


def _track(thread):
    """登记工作线程，线程结束后自动解除引用。"""
    _alive_threads.add(thread)
    thread.finished.connect(lambda: _alive_threads.discard(thread))
    return thread


class _ManifestWorker(QThread):
    """在后台线程读取并解析发布目录中的 version.json。"""

    succeeded = pyqtSignal(str, str)  # 远程版本号, 远程 zip 文件名
    failed = pyqtSignal(str)

    def run(self):
        try:
            manifest_path = os.path.join(app_version.PUBLISH_DIR,
                                         app_version.MANIFEST_NAME)
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            remote_version = data["version"]
            # 清单允许通过 app 字段覆盖默认文件名，缺省时使用内置 .app 常量
            remote_app = data.get("app") or app_version.APP_NAME
            self.succeeded.emit(str(remote_version), str(remote_app))
        except Exception as exc:  # 挂载点不可达 / JSON 损坏 / KeyError 等
            self.failed.emit(str(exc))


class _DownloadWorker(QThread):
    """在后台线程把发布目录的 .app bundle 保真复制到本地临时目录。"""

    succeeded = pyqtSignal(str)  # 复制出的新 .app 绝对路径
    failed = pyqtSignal(str)

    def __init__(self, src_app, work_dir, app_name, parent=None):
        super().__init__(parent)
        self._src_app = src_app
        self._work_dir = work_dir
        self._app_name = app_name

    def run(self):
        try:
            # NAS 可能只读且较慢，用 ditto 把 .app bundle 保真复制到本地临时目录
            # （保留符号链接/可执行权限/扩展属性，避免 zipfile 解压损坏 bundle）
            dest_app = os.path.join(self._work_dir, self._app_name)
            if os.path.exists(dest_app):
                shutil.rmtree(dest_app)
            ditto = shutil.which("ditto")
            if ditto:
                subprocess.run([ditto, self._src_app, dest_app], check=True)
            else:
                shutil.copytree(self._src_app, dest_app, symlinks=True)
            # 校验 bundle 结构：Contents/MacOS 下存在带可执行位的启动器
            if not os.path.isdir(dest_app):
                raise IOError("更新包中未找到 {}".format(self._app_name))
            macos_dir = os.path.join(dest_app, "Contents", "MacOS")
            if not os.path.isdir(macos_dir) or not os.listdir(macos_dir):
                raise IOError("更新包 .app 缺少 Contents/MacOS 可执行文件")
            exe_name = (self._app_name[:-4]
                        if self._app_name.endswith(".app") else self._app_name)
            exe_path = os.path.join(macos_dir, exe_name)
            if not os.path.isfile(exe_path):
                raise IOError("更新包 .app 缺少可执行文件 {}".format(exe_name))
            if not os.access(exe_path, os.X_OK):
                raise IOError("更新包 .app 可执行文件缺少执行权限")
            self.succeeded.emit(dest_app)
        except Exception as exc:
            self.failed.emit(str(exc))


class _UpdateDialog(QDialog):
    """无确认按钮的模态更新进度框（不确定进度条）。"""

    def __init__(self, version, parent=None):
        super().__init__(parent)
        self.setWindowTitle("软件更新")
        self.setModal(True)
        # 不允许通过 Esc / 外部关闭跳过更新流程
        self._closable = False

        layout = QVBoxLayout(self)
        tip = QLabel("发现新版本 {}，正在自动更新…".format(version), self)
        layout.addWidget(tip)
        progress = QProgressBar(self)
        progress.setRange(0, 0)  # 不确定进度（忙碌态）
        layout.addWidget(progress)
        self.resize(320, 120)

    def allow_close(self):
        """下载结束后才允许真正关闭对话框。"""
        self._closable = True
        self.accept()

    def keyPressEvent(self, event):
        # 屏蔽 Esc
        if event.key() == Qt.Key_Escape:
            event.ignore()
        else:
            super().keyPressEvent(event)

    def reject(self):
        if self._closable:
            super().reject()

    def closeEvent(self, event):
        if self._closable:
            event.accept()
        else:
            event.ignore()


def _is_in_directory(path, directory):
    """判断 path 是否位于 directory 之内（两者均先 normcase/abspath）。"""
    path = os.path.normcase(os.path.abspath(path))
    directory = os.path.normcase(os.path.abspath(directory))
    # 尾部分隔符保证前缀边界正确，避免 /Volumes/x/工具y 误匹配 /Volumes/x/工具
    return path.startswith(directory + os.sep) or path == directory


def _current_bundle_root():
    """从 sys.executable 上溯定位当前 .app bundle 根目录。

    冻结环境下 sys.executable 形如 ``.../<APP>.app/Contents/MacOS/<exe>``，
    上溯 3 级 ``os.path.dirname`` 得到 ``.../<APP>.app``。
    非 bundle 布局（如源码运行）时返回值不会以 ``.app`` 结尾，由调用方判定。
    """
    exe = os.path.abspath(sys.executable)
    # .../<APP>.app/Contents/MacOS/<exe> -> .../<APP>.app
    return os.path.dirname(os.path.dirname(os.path.dirname(exe)))


def _read_manifest_with_timeout():
    """同步读取远程清单（阻塞调用线程），返回 (version, zip_name) 或 None。

    使用 QThread 执行读取、QTimer.singleShot 做 4 秒看门狗；
    通过局部 QEventLoop 等待，超时或异常一律返回 None。
    超时后即便工作线程晚些返回，done 标志也会丢弃其结果。
    """
    loop = QEventLoop()
    result = {"done": False, "data": None}

    def finish(data):
        # 只接受第一次结果；超时后 late signal 不再产生任何动作
        if result["done"]:
            return
        result["done"] = True
        result["data"] = data
        loop.quit()

    worker = _track(_ManifestWorker())
    worker.succeeded.connect(lambda version, zip_name: finish((version, zip_name)))
    worker.failed.connect(lambda _msg: finish(None))

    QTimer.singleShot(MANIFEST_TIMEOUT_MS, lambda: finish(None))
    worker.start()
    loop.exec_()
    return result["data"]


def _download_with_dialog(version, src_app, work_dir, app_name, parent):
    """显示更新进度框并在后台复制 .app，成功返回新 .app 路径，失败返回 None。"""
    dialog = _UpdateDialog(version, parent)
    outcome = {"app": None}

    worker = _track(_DownloadWorker(src_app, work_dir, app_name))

    def on_succeeded(new_app):
        outcome["app"] = new_app
        dialog.allow_close()

    def on_failed(_msg):
        dialog.allow_close()

    worker.succeeded.connect(on_succeeded)
    worker.failed.connect(on_failed)

    worker.start()
    dialog.exec_()  # 模态等待下载结束（允许关闭即代表结束）
    return outcome["app"]


def _build_shell_script(pid, new_app, target_app):
    """生成等待/替换/重启用的 bash 脚本内容（纯函数，便于测试）。

    - 参数传入旧进程 PID 与新旧 .app 路径，路径以双引号字面量使用；
    - ``while kill -0 <pid>`` 轮询等待旧进程退出（最多约 60 秒，超时也继续）；
    - ``rm -rf`` 删除旧 bundle，``ditto`` 复制新 bundle（保留权限/扩展属性），
      替换失败最多重试 10 轮；
    - 替换成功后 ``open`` 重启新版本；
    - 最后 ``rm -rf`` 临时工作目录（其中同时含新 bundle 源与本脚本自身）。
    """
    work_dir = os.path.dirname(new_app)
    return (
        "#!/bin/bash\n"
        'PID="{pid}"\n'
        'NEW_APP="{new_app}"\n'
        'TARGET_APP="{target_app}"\n'
        'WORK_DIR="{work_dir}"\n'
        "i=0\n"
        'while kill -0 "$PID" 2>/dev/null; do\n'
        "    sleep 0.3\n"
        "    i=$((i+1))\n"
        '    if [ "$i" -ge 200 ]; then\n'
        "        break\n"
        "    fi\n"
        "done\n"
        "sleep 0.5\n"
        "ok=0\n"
        "for n in 1 2 3 4 5 6 7 8 9 10; do\n"
        '    rm -rf "$TARGET_APP" 2>/dev/null\n'
        '    if ditto "$NEW_APP" "$TARGET_APP" 2>/dev/null; then\n'
        "        ok=1\n"
        "        break\n"
        "    fi\n"
        "    sleep 1\n"
        "done\n"
        'if [ "$ok" = "1" ]; then\n'
        '    xattr -dr com.apple.quarantine "$TARGET_APP" 2>/dev/null\n'
        '    open -n "$TARGET_APP"\n'
        "fi\n"
        # 清理临时目录（含新 bundle 源与脚本自身）；作为最后一行执行
        'rm -rf "$WORK_DIR" 2>/dev/null\n'
    ).format(pid=pid, new_app=new_app, target_app=target_app, work_dir=work_dir)


def _write_launch_and_exit(new_app, target_app, app):
    """写 bash 更新脚本、脱离会话启动，然后终止当前进程。

    脚本与解出的新 bundle 同处临时工作目录，脚本末行 ``rm -rf`` 该目录时
    会连同自身一并清理。本函数正常情况下不会返回（进程退出）；
    任何失败则抛异常由上层静默处理。
    """
    work_dir = os.path.dirname(new_app)
    script_path = os.path.join(work_dir, ".update_macos.sh")
    pid = os.getpid()

    with open(script_path, "w", encoding="utf-8") as f:
        f.write(_build_shell_script(pid, new_app, target_app))
    os.chmod(script_path, 0o755)

    # start_new_session 让脚本脱离当前进程的会话/进程组，父进程退出后仍继续运行；
    # close_fds 避免继承 Qt/文件描述符导致占用
    subprocess.Popen(
        ["/bin/bash", script_path],
        start_new_session=True,
        close_fds=True,
    )

    # 双保险退出：先优雅退出 Qt 事件循环，再立即结束进程，
    # 确保脚本的 kill -0 轮询能尽快观察到旧进程已退出
    if app is not None:
        app.quit()
    else:
        QApplication.quit()
    os._exit(0)


def ensure_latest(app=None):
    """启动时检查并静默应用内网 NAS 更新；可能终止当前进程（更新重启）。

    源码运行（非 frozen）、非 .app bundle 布局、直接从发布共享目录运行、
    检查超时/失败、无新版本、下载失败等情况下均直接返回，不影响旧版本启动。
    """
    work_dir = None
    try:
        # 1. 仅打包后的 .app 执行更新流程
        if not getattr(sys, "frozen", False):
            return

        # 2. 定位当前 bundle；布局异常或从 NAS 发布目录直接运行时跳过
        target_app = _current_bundle_root()
        if not target_app.endswith(".app"):
            return
        if _is_in_directory(target_app, app_version.PUBLISH_DIR):
            return

        # 3. 读取清单并比较版本（4 秒看门狗，失败静默）
        manifest = _read_manifest_with_timeout()
        if manifest is None:
            return
        remote_version, remote_app = manifest
        if not app_version.is_newer(remote_version, app_version.__version__):
            return

        # 4. 准备临时工作目录，后台用 ditto 保真复制发布目录的新 .app
        src_app = os.path.join(app_version.PUBLISH_DIR, remote_app)
        work_dir = tempfile.mkdtemp(prefix="gui_update_")

        parent = app.activeWindow() if app is not None else QApplication.activeWindow()

        new_app = _download_with_dialog(remote_version, src_app, work_dir,
                                        app_version.APP_NAME, parent)
        if not new_app:
            # 下载/解压失败：清理临时目录后静默继续运行旧版本
            shutil.rmtree(work_dir, ignore_errors=True)
            return

        # 5. 生成 bash 脚本并重启（正常不返回）
        _write_launch_and_exit(new_app, target_app, app)
    except Exception as exc:  # 最终兜底：任何意外都不阻塞程序启动
        if work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
        print("[updater] 自动更新检查失败: {}".format(exc))
