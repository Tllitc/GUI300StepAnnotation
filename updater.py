# -*- coding: utf-8 -*-
"""静默自动更新模块（仅 Windows 打包后生效）。

对外只暴露 ``ensure_latest(app=None)``，由 main.py 在 QApplication 创建后、
主窗口显示前调用。整体流程：

1. 仅在 PyInstaller 等冻结环境（``sys.frozen`` 为真）下执行更新流程；
2. 若当前 exe 直接运行自 NAS 发布共享目录，则跳过（避免替换发布源）；
3. 后台线程读取 ``<PUBLISH_DIR>\\version.json``（4 秒看门狗，UNC 不可达快速失败）；
4. 发现新版本时弹模态“软件更新”进度框，后台线程复制新 exe 到本地临时文件；
5. 生成极简批处理，由其调用 PowerShell 辅助脚本：等当前进程退出 ->
   Move-Item 替换 exe -> 重启新版本 -> 删除 ps1 与批处理自身；
6. 启动无窗口的批处理进程后，当前进程立即退出。

任何失败路径均静默返回，保证用户至少能用旧版本进入主界面。
非 frozen、非 Windows 环境下导入本模块不会报错。
"""

import json
import os
import shutil
import subprocess
import sys

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

    succeeded = pyqtSignal(str, str)  # 远程版本号, 远程 exe 文件名
    failed = pyqtSignal(str)

    def run(self):
        try:
            manifest_path = os.path.join(app_version.PUBLISH_DIR,
                                         app_version.MANIFEST_NAME)
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            remote_version = data["version"]
            # 清单允许通过 exe 字段覆盖默认文件名，缺省时使用内置常量
            remote_exe = data.get("exe") or app_version.EXE_NAME
            self.succeeded.emit(str(remote_version), str(remote_exe))
        except Exception as exc:  # 网络不可达 / JSON 损坏 / KeyError 等
            self.failed.emit(str(exc))


class _DownloadWorker(QThread):
    """在后台线程把新 exe 复制到本地临时文件。"""

    succeeded = pyqtSignal(str)  # 本地临时 exe 路径
    failed = pyqtSignal(str)

    def __init__(self, src_path, dst_path, parent=None):
        super().__init__(parent)
        self._src_path = src_path
        self._dst_path = dst_path

    def run(self):
        try:
            # 临时文件若已存在先删除，避免残留旧包
            if os.path.exists(self._dst_path):
                os.remove(self._dst_path)
            shutil.copy2(self._src_path, self._dst_path)
            # 复制完成后校验文件大小 > 0
            if not os.path.isfile(self._dst_path) or \
                    os.path.getsize(self._dst_path) <= 0:
                raise IOError("下载的更新文件为空")
            self.succeeded.emit(self._dst_path)
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
    # 尾部分隔符保证前缀边界正确，避免 \\nas\share\工具x 误匹配
    return path.startswith(directory + os.sep) or path == directory


def _read_manifest_with_timeout():
    """同步读取远程清单（阻塞调用线程），返回 (version, exe) 或 None。

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
    worker.succeeded.connect(lambda version, exe: finish((version, exe)))
    worker.failed.connect(lambda _msg: finish(None))

    QTimer.singleShot(MANIFEST_TIMEOUT_MS, lambda: finish(None))
    worker.start()
    loop.exec_()
    return result["data"]


def _download_with_dialog(version, src_path, dst_path, parent):
    """显示更新进度框并在后台下载，成功返回 True，失败返回 False。"""
    dialog = _UpdateDialog(version, parent)
    outcome = {"ok": False}

    worker = _track(_DownloadWorker(src_path, dst_path))

    def on_succeeded(_path):
        outcome["ok"] = True
        dialog.allow_close()

    def on_failed(_msg):
        dialog.allow_close()

    worker.succeeded.connect(on_succeeded)
    worker.failed.connect(on_failed)

    worker.start()
    dialog.exec_()  # 模态等待下载结束（允许关闭即代表结束）
    return outcome["ok"]


def _helper_script_paths(target_exe):
    """返回 (批处理路径, PowerShell 辅助脚本路径)。

    两个临时脚本均放在目标 exe 同目录，命名风格保持一致。
    """
    target_dir = os.path.dirname(target_exe)
    stem = os.path.splitext(app_version.EXE_NAME)[0]
    bat_path = os.path.join(target_dir, ".update_" + stem + ".bat")
    ps1_path = os.path.join(target_dir, ".update_" + stem + ".ps1")
    return bat_path, ps1_path


def _build_powershell_script(pid, new_exe, target_exe):
    """生成等待/替换/重启用的 PowerShell 辅助脚本内容（纯函数，便于测试）。

    - 参数传入旧进程 PID 与新旧 exe 路径，路径以单引号字面量使用；
    - Wait-Process 等待旧进程退出（最多 60 秒，超时也继续）；
    - Move-Item 替换失败最多重试 10 轮；
    - 替换成功后重启新版本，最后清理残留 new exe 与脚本自身。
    """
    # 注意：$Pid 是 PowerShell 只读自动变量，不能直接作为参数名，
    # 这里用 Alias('Pid') 让命令行仍可通过 -Pid 绑定。
    return (
        "param(\r\n"
        "    [Parameter(Mandatory=$true)] [Alias('Pid')] [int]$OldPid,\r\n"
        "    [Parameter(Mandatory=$true)] [string]$NewExe,\r\n"
        "    [Parameter(Mandatory=$true)] [string]$TargetExe\r\n"
        ")\r\n"
        "$ErrorActionPreference = 'Continue'\r\n"
        "try {\r\n"
        "    Wait-Process -Id $OldPid -Timeout 60 -ErrorAction Stop\r\n"
        "} catch {\r\n"
        "    # 等待超时或进程已不存在，均继续尝试替换\r\n"
        "}\r\n"
        "Start-Sleep -Milliseconds 500\r\n"
        "$moved = $false\r\n"
        "for ($i = 0; $i -lt 10; $i++) {\r\n"
        "    try {\r\n"
        "        Move-Item -LiteralPath $NewExe -Destination $TargetExe "
        "-Force -ErrorAction Stop\r\n"
        "        $moved = $true\r\n"
        "        break\r\n"
        "    } catch {\r\n"
        "        Start-Sleep -Seconds 1\r\n"
        "    }\r\n"
        "}\r\n"
        "if ($moved) {\r\n"
        "    Start-Process -FilePath $TargetExe -WorkingDirectory "
        "(Split-Path -Parent $TargetExe)\r\n"
        "}\r\n"
        "if (Test-Path -LiteralPath $NewExe) {\r\n"
        "    Remove-Item -LiteralPath $NewExe -Force -ErrorAction SilentlyContinue\r\n"
        "}\r\n"
        "Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force "
        "-ErrorAction SilentlyContinue\r\n"
    )


def _build_batch_script(pid, new_exe, target_exe, ps1_path):
    """生成极简更新批处理内容（纯函数，便于测试）。

    批处理本身不做循环/管道/等待，仅调用 PowerShell 辅助脚本，
    避免在无控制台环境下 find 管道与 timeout 命令挂起。
    """
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "powershell -NoProfile -ExecutionPolicy Bypass -File \"{ps1}\" "
        "-Pid {pid} -NewExe \"{new}\" -TargetExe \"{target}\"\r\n"
        "del /f /q \"{ps1}\" 2>nul\r\n"
        "(goto) 2>nul & del \"%~f0\"\r\n"
    ).format(ps1=ps1_path, pid=pid, new=new_exe, target=target_exe)


def _write_launch_and_exit(new_exe, target_exe, app):
    """写批处理与 PowerShell 辅助脚本、无窗口启动，然后终止当前进程。

    本函数正常情况下不会返回（进程退出）；任何失败则抛异常由上层静默处理。
    """
    bat_path, ps1_path = _helper_script_paths(target_exe)
    pid = os.getpid()

    # ps1 含中文路径，必须 UTF-8 with BOM，PowerShell 5.1 才能正确识别
    with open(ps1_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(_build_powershell_script(pid, new_exe, target_exe))
    # bat 内容基本为 ASCII，路径在引号内交给 powershell -File 解析
    with open(bat_path, "w", encoding="utf-8", newline="") as f:
        f.write(_build_batch_script(pid, new_exe, target_exe, ps1_path))

    # 仅 CREATE_NO_WINDOW：叠加 DETACHED_PROCESS 会使管道/控制台命令挂起
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=creationflags,
        close_fds=True,
    )

    # 双保险退出：先优雅退出 Qt 事件循环，再立即结束进程，
    # 确保 PowerShell 的 Wait-Process 能尽快观察到进程已退出
    if app is not None:
        app.quit()
    else:
        QApplication.quit()
    os._exit(0)


def ensure_latest(app=None):
    """启动时检查并静默应用内网 NAS 更新；可能终止当前进程（更新重启）。

    源码运行（非 frozen）、直接从发布共享目录运行、检查超时/失败、
    无新版本、下载失败等情况下均直接返回，不影响旧版本启动。
    """
    try:
        # 1. 仅打包后的 exe 执行更新流程
        if not getattr(sys, "frozen", False):
            return

        # 2. 从 NAS 发布目录直接运行时跳过，避免替换发布源
        current_exe = os.path.normcase(os.path.abspath(sys.executable))
        if _is_in_directory(current_exe, app_version.PUBLISH_DIR):
            return

        # 3. 读取清单并比较版本（4 秒看门狗，失败静默）
        manifest = _read_manifest_with_timeout()
        if manifest is None:
            return
        remote_version, remote_exe = manifest
        if not app_version.is_newer(remote_version, app_version.__version__):
            return

        target_exe = current_exe
        target_dir = os.path.dirname(target_exe)
        src_path = os.path.join(app_version.PUBLISH_DIR, remote_exe)
        # 临时文件名以句点开头，放在当前 exe 同目录，如 .GUI长步骤采标工具-Windows.new.exe
        exe_stem = os.path.splitext(app_version.EXE_NAME)[0]
        new_exe = os.path.join(target_dir, "." + exe_stem + ".new.exe")

        parent = app.activeWindow() if app is not None else QApplication.activeWindow()

        # 4-5. 显示进度框并后台下载，失败则静默返回继续运行旧版本
        if not _download_with_dialog(remote_version, src_path, new_exe, parent):
            return

        # 6. 生成批处理并重启（正常不返回）
        _write_launch_and_exit(new_exe, target_exe, app)
    except Exception as exc:  # 最终兜底：任何意外都不阻塞程序启动
        print("[updater] 自动更新检查失败: {}".format(exc))
