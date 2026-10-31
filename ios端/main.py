#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI长步骤采标工具-iOS 入口
用于采集和标注用户在 iOS 平台上的 GUI 操作轨迹
"""

import sys
import os
import re
import json
import subprocess
import threading
import time
from datetime import datetime

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QLineEdit,
                             QComboBox, QGroupBox, QFormLayout, QMessageBox,
                             QFileDialog, QTextEdit)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont

import app_version
import updater
from data_manager import DataManager
from annotation_editor import AnnotationEditor

# 软件分类列表
APP_TYPES = [
    "社交", "电商", "办公", "浏览器/网页", "地图/出行/天气",
    "视频/影音", "系统工具", "文件系统/命令行/终端/任务管理",
    "支付/银行/金融/股票", "教育/学习", "生活服务", "效率工具",
    "开发工具", "知识库/在线文档", "在线会议", "SaaS", "直播平台"
]


def find_ios_exe():
    """查找 ios.exe 路径（支持 PyInstaller 打包）"""
    if getattr(sys, "frozen", False):
        bundle = os.path.join(getattr(sys, "_MEIPASS", ""), "ios.exe")
        if os.path.isfile(bundle):
            return bundle
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ios.exe")
    if os.path.isfile(local):
        return local
    return "ios.exe"


def _get_ios_workdir():
    """获取 ios.exe 所在目录作为工作目录"""
    return os.path.dirname(os.path.abspath(__file__))


def _run_ios_command(ios_exe, args, timeout=30):
    """执行 go-ios 命令，返回解析后的 JSON 或 None"""
    env = os.environ.copy()
    env.setdefault("ENABLE_GO_IOS_AGENT", "user")
    try:
        proc = subprocess.run(
            [ios_exe, "--pretty"] + args,
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=timeout,
            cwd=_get_ios_workdir(),
            env=env,
        )
        output = proc.stdout.strip() or proc.stderr.strip()
        if not output:
            return None
        return json.loads(output)
    except json.JSONDecodeError:
        return None
    except Exception:
        return None


def scan_all_devices(ios_exe):
    """扫描所有已连接的 iOS 设备，返回设备信息列表"""
    data = _run_ios_command(ios_exe, ["list", "--details"])
    if not data:
        return []

    devices = data.get("deviceList", data)
    if isinstance(devices, dict):
        devices = [devices]
    if not isinstance(devices, list):
        return []

    result = []
    seen = set()
    for d in devices:
        if not isinstance(d, dict):
            continue
        udid = d.get("Udid") or d.get("udid") or ""
        if not udid or udid in seen:
            continue
        seen.add(udid)
        name = d.get("ProductName") or d.get("DeviceName") or d.get("deviceName") or "iOS 设备"
        product_type = d.get("ProductType") or d.get("productType") or ""
        product_version = d.get("ProductVersion") or d.get("productVersion") or ""
        result.append({
            "udid": udid,
            "deviceName": name,
            "productType": product_type,
            "productVersion": product_version,
        })
    return result


def check_ios_device(ios_exe):
    """检查是否有 iOS 设备连接，返回 (has_device, first_device_or_empty_dict)"""
    devices = scan_all_devices(ios_exe)
    if devices:
        return True, devices[0]
    return False, {}


def _kill_stale_ios_processes():
    """清理残留的 ios.exe 进程"""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/IM", "ios.exe"],
                capture_output=True, timeout=10,
            )
        else:
            subprocess.run(
                ["pkill", "-f", "ios.*tunnel"],
                capture_output=True, timeout=10,
            )
    except Exception:
        pass


def start_tunnel(ios_exe, udid=None):
    """启动 go-ios userspace tunnel，返回 Popen 进程对象"""
    env = os.environ.copy()
    env.setdefault("ENABLE_GO_IOS_AGENT", "user")

    _kill_stale_ios_processes()
    time.sleep(0.3)

    args = [ios_exe, "tunnel", "start", "--userspace"]
    if udid:
        args += ["--udid", udid]

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace',
        cwd=_get_ios_workdir(),
        env=env,
    )
    print(f"[TUNNEL] 正在启动 userspace tunnel (udid={udid})...")

    def _monitor():
        """后台线程：监控 tunnel 输出，发现 'negotiated' 时标记就绪"""
        try:
            for line in proc.stdout:
                line_stripped = line.rstrip()
                print(f"[TUNNEL] {line_stripped}")
                if "userspace tunnel negotiated" in line_stripped:
                    print("[TUNNEL] tunnel 已就绪")
                    # 继续 drain stdout 保持进程不阻塞
                    for _ in proc.stdout:
                        pass
                    return
        except Exception:
            return

    t = threading.Thread(target=_monitor, daemon=True)
    t.start()
    return proc


def stop_tunnel(proc):
    """停止 tunnel 进程"""
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("[TUNNEL] tunnel 已停止")
    except Exception as e:
        print(f"[TUNNEL] 停止 tunnel 失败: {e}")


class InitTaskWindow(QMainWindow):
    """任务初始化窗口"""

    _tunnel_ready = pyqtSignal()
    _tunnel_failed = pyqtSignal()

    FONT_TITLE = QFont("Microsoft YaHei", 20, QFont.Bold)
    FONT_SUBTITLE = QFont("Microsoft YaHei", 11)
    FONT_GROUP = QFont("Microsoft YaHei", 11, QFont.Bold)
    FONT_LABEL = QFont("Microsoft YaHei", 10)
    FONT_INPUT = QFont("Microsoft YaHei", 10)
    FONT_STATUS = QFont("Microsoft YaHei", 11, QFont.Bold)
    FONT_INFO = QFont("Microsoft YaHei", 10)
    FONT_BTN_NORMAL = QFont("Microsoft YaHei", 10)
    FONT_BTN_START = QFont("Microsoft YaHei", 15, QFont.Bold)

    COLOR_ACCENT = "#4CAF50"
    COLOR_ACCENT_HOVER = "#43A047"
    COLOR_RED = "#E53935"
    COLOR_ORANGE = "#FB8C00"
    COLOR_GREEN = "#43A047"
    COLOR_GRAY = "#757575"
    COLOR_BORDER = "#BDBDBD"
    COLOR_BG_LIGHT = "#FAFAFA"

    BTN_STYLE = (
        "QPushButton {"
        "  padding: 6px 16px;"
        "  background-color: #E0E0E0;"
        "  border: 1px solid #BDBDBD;"
        "  border-radius: 3px;"
        "}"
        "QPushButton:hover {"
        "  background-color: #D0D0D0;"
        "}"
        "QPushButton:pressed {"
        "  background-color: #C0C0C0;"
        "}"
    )

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"GUI长步骤采标工具-iOS v{app_version.__version__} - 任务初始化")
        self.setGeometry(100, 100, 700, 800)
        self.setMinimumSize(620, 700)

        self.data_manager = DataManager()
        self.storage_dir = None
        self.ios_exe = find_ios_exe()
        self.device_info = {}
        self.all_devices = []
        self._tunnel_proc = None
        self._closing = False

        self._tunnel_ready.connect(self._on_tunnel_ready)
        self._tunnel_failed.connect(self._on_tunnel_failed)

        self._base_font = QFont("Microsoft YaHei", 10)
        self.setFont(self._base_font)

        self.init_ui()

        # 延迟检测设备
        QTimer.singleShot(300, self.detect_device)

    def init_ui(self):
        central = QWidget()
        central.setStyleSheet("font-family: 'Microsoft YaHei';")
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        # ---- 标题 ----
        title = QLabel("GUI长步骤采标工具-iOS")
        title.setFont(self.FONT_TITLE)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"color: {self.COLOR_ACCENT}; padding-bottom: 2px;")
        layout.addWidget(title)

        # ---- 设备管理 ----
        device_group = QGroupBox("设备管理")
        device_group.setFont(self.FONT_GROUP)
        device_group.setStyleSheet(self._group_box_style())
        device_layout = QVBoxLayout()
        device_layout.setSpacing(8)

        self.device_status_label = QLabel("检测 iOS 设备...")
        self.device_status_label.setFont(self.FONT_STATUS)
        self.device_status_label.setStyleSheet(
            f"color: {self.COLOR_ORANGE}; padding: 4px 6px;"
            f"background-color: {self.COLOR_BG_LIGHT}; border-radius: 3px;"
        )
        device_layout.addWidget(self.device_status_label)

        # 设备选择下拉 + 扫描按钮
        device_select_layout = QHBoxLayout()
        device_select_layout.setSpacing(8)

        lbl = QLabel("选择设备:")
        lbl.setFont(self.FONT_LABEL)
        device_select_layout.addWidget(lbl)

        self.device_combo = QComboBox()
        self.device_combo.setFont(self.FONT_INPUT)
        self.device_combo.setMinimumWidth(280)
        self.device_combo.setMinimumHeight(28)
        self.device_combo.setToolTip("选择要使用的 iOS 设备")
        self.device_combo.currentIndexChanged.connect(self._on_device_selected)
        device_select_layout.addWidget(self.device_combo, 1)

        self.scan_btn = QPushButton("扫描设备")
        self.scan_btn.setFont(self.FONT_BTN_NORMAL)
        self.scan_btn.setStyleSheet(self.BTN_STYLE)
        self.scan_btn.setMinimumWidth(90)
        self.scan_btn.clicked.connect(self.scan_devices)
        device_select_layout.addWidget(self.scan_btn)

        device_layout.addLayout(device_select_layout)

        device_group.setLayout(device_layout)
        layout.addWidget(device_group)

        # ---- 任务信息 ----
        form_group = QGroupBox("任务信息")
        form_group.setFont(self.FONT_GROUP)
        form_group.setStyleSheet(self._group_box_style())
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        # 存储目录
        storage_layout = QHBoxLayout()
        storage_layout.setSpacing(8)
        self.storage_dir_label = QLabel("未选择")
        self.storage_dir_label.setFont(self.FONT_LABEL)
        self.storage_dir_label.setStyleSheet(f"color: {self.COLOR_GRAY};")
        self.storage_dir_label.setWordWrap(True)
        select_btn = QPushButton("选择存储目录")
        select_btn.setFont(self.FONT_BTN_NORMAL)
        select_btn.setStyleSheet(self.BTN_STYLE)
        select_btn.clicked.connect(self.select_storage_directory)
        storage_layout.addWidget(self.storage_dir_label, 1)
        storage_layout.addWidget(select_btn)

        dir_label = QLabel("存储目录:")
        dir_label.setFont(self.FONT_LABEL)
        form_layout.addRow(dir_label, storage_layout)

        # 软件名称
        self.app_name_input = QLineEdit()
        self.app_name_input.setFont(self.FONT_INPUT)
        self.app_name_input.setMinimumHeight(28)
        self.app_name_input.setPlaceholderText("例如：微信、淘宝、139邮箱")
        name_label = QLabel("软件名称:")
        name_label.setFont(self.FONT_LABEL)
        form_layout.addRow(name_label, self.app_name_input)

        # 软件类型
        self.app_type_combo = QComboBox()
        self.app_type_combo.setFont(self.FONT_INPUT)
        self.app_type_combo.setMinimumHeight(28)
        self.app_type_combo.addItems(APP_TYPES)
        type_label = QLabel("软件类型:")
        type_label.setFont(self.FONT_LABEL)
        form_layout.addRow(type_label, self.app_type_combo)

        form_group.setLayout(form_layout)
        layout.addWidget(form_group)

        # ---- 使用说明 ----
        info = QLabel(
            "使用说明\n"
            "1. 确保 iPhone 通过 USB 连接电脑，点击 [扫描设备]\n"
            "2. 从下拉框选择目标设备\n"
            "3. iOS 17+ 设备开始采标时会自动启动 Tunnel\n"
            "4. 填写任务信息后点击 [开始采标]\n"
            "5. 输入任务指令后开始截图标注\n"
            "6. 快捷键: Ctrl+Q=截图 | Ctrl+S=下一步"
        )
        info.setFont(self.FONT_INFO)
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {self.COLOR_GRAY};"
            f"padding: 10px 12px;"
            f"background-color: {self.COLOR_BG_LIGHT};"
            f"border: 1px solid {self.COLOR_BORDER};"
            f"border-radius: 4px;"
        )
        layout.addWidget(info)

        # ---- 开始采标 ----
        self.start_btn = QPushButton("开始采标")
        self.start_btn.setFont(self.FONT_BTN_START)
        self.start_btn.setMinimumHeight(44)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setStyleSheet(
            "QPushButton {"
            f"  background-color: {self.COLOR_ACCENT};"
            "  color: white;"
            "  padding: 10px;"
            "  border: none;"
            "  border-radius: 4px;"
            "}"
            "QPushButton:hover {"
            f"  background-color: {self.COLOR_ACCENT_HOVER};"
            "}"
            "QPushButton:pressed {"
            "  background-color: #388E3C;"
            "}"
            "QPushButton:disabled {"
            "  background-color: #BDBDBD;"
            "}"
        )
        self.start_btn.clicked.connect(self.start_annotation)
        layout.addWidget(self.start_btn)

        # ---- 继续未完成任务 ----
        self.resume_btn = QPushButton("继续未完成任务")
        self.resume_btn.setFont(self.FONT_BTN_NORMAL)
        self.resume_btn.setMinimumHeight(40)
        self.resume_btn.setCursor(Qt.PointingHandCursor)
        self.resume_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #FB8C00;"
            "  color: white;"
            "  padding: 8px;"
            "  border: none;"
            "  border-radius: 4px;"
            "}"
            "QPushButton:hover {"
            "  background-color: #F57C00;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #EF6C00;"
            "}"
        )
        self.resume_btn.clicked.connect(self.resume_annotation)
        layout.addWidget(self.resume_btn)

        # ---- 编辑已完成任务 ----
        self.edit_btn = QPushButton("编辑已完成任务")
        self.edit_btn.setFont(self.FONT_BTN_NORMAL)
        self.edit_btn.setMinimumHeight(40)
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #00897B;"
            "  color: white;"
            "  padding: 8px;"
            "  border: none;"
            "  border-radius: 4px;"
            "}"
            "QPushButton:hover {"
            "  background-color: #00796B;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #00695C;"
            "}"
        )
        self.edit_btn.clicked.connect(self.edit_completed_annotation)
        layout.addWidget(self.edit_btn)

    def edit_completed_annotation(self):
        """选择已完成的 gui_xxxxxx 数据集，按轮次进入编辑模式"""
        start_dir = self.storage_dir or os.path.expanduser("~")
        gui_dir = QFileDialog.getExistingDirectory(
            self, "选择要编辑的 gui 任务目录", start_dir
        )
        if not gui_dir:
            return

        dir_name = os.path.basename(os.path.normpath(gui_dir))
        match = re.fullmatch(r"gui_(\d{6})", dir_name)
        if not match:
            QMessageBox.warning(self, "警告", "请选择 gui_xxxxxx 形式的任务目录")
            return

        data, error = DataManager.load_json_from_dir(gui_dir)
        if error:
            QMessageBox.warning(self, "警告", error)
            return

        coords, coords_error = DataManager.load_coords_from_dir(gui_dir)
        if coords_error:
            QMessageBox.warning(self, "警告", f"{coords_error}\n将继续编辑，但坐标可能需重新标注")

        # 解析轮次摘要（user instruction + assistant trajectory）
        rounds = []
        pending_instruction = ""
        for message in data.get("messages") or []:
            role = message.get("role")
            if role == "user":
                pending_instruction = message.get("instruction", "")
            elif role == "assistant":
                rounds.append({
                    "instruction": pending_instruction,
                    "trajectory": message.get("trajectory") or [],
                })
                pending_instruction = ""
        if not rounds:
            QMessageBox.warning(self, "警告", "该任务没有可编辑的轮次数据")
            return

        round_index = 0
        if len(rounds) >= 2:
            from PyQt5.QtWidgets import QInputDialog
            items = []
            for i, round_data in enumerate(rounds):
                summary = (round_data["instruction"] or "(无指令)").replace("\n", " ")
                items.append(
                    f"第 {i + 1} 轮：{summary[:60]}（{len(round_data['trajectory'])} 步）"
                )
            choice, ok = QInputDialog.getItem(
                self, "选择要编辑的轮次", "请选择轮次：", items, 0, False
            )
            if not ok:
                return
            round_index = items.index(choice)

        # 设备处理与续采保持一致
        if not self.device_info:
            self.all_devices = scan_all_devices(self.ios_exe)
            if self.all_devices:
                self.device_info = self.all_devices[0]
            else:
                reply = QMessageBox.question(
                    self, "设备未连接",
                    "未检测到 iOS 设备，编辑期间截图功能将不可用。\n\n是否仍要继续？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return

        udid = self.device_info.get("udid") if self.device_info else None
        if udid:
            self._auto_start_tunnel(udid)

        base_dir = os.path.dirname(os.path.normpath(gui_dir))
        dm = DataManager(base_dir=base_dir)

        # 顶层元数据以原 JSON 为准，缺失时回退到设备信息
        if data.get("platform") and data.get("system") and data.get("screen_size"):
            screen_info = {
                "platform": data["platform"],
                "system": data["system"],
                "screen_size": data["screen_size"],
            }
        else:
            screen_info = dm.get_screen_info(udid)

        self.annotation_window = AnnotationEditor(
            data_manager=dm,
            app_name=dir_name,
            task_instruction="",
            screen_info=screen_info,
            app_type="",
            udid=udid,
            close_callback=self.show,
        )
        self.annotation_window.load_from_completed_json(
            data, coords, round_index, gui_dir
        )

        self.annotation_window.show()
        self.hide()

    def _group_box_style(self):
        return (
            "QGroupBox {"
            f"  border: 1px solid {self.COLOR_BORDER};"
            "  border-radius: 4px;"
            "  margin-top: 14px;"
            "  padding: 14px 12px 10px 12px;"
            "}"
            "QGroupBox::title {"
            f"  color: {self.COLOR_ACCENT};"
            "  subcontrol-origin: margin;"
            "  left: 12px;"
            "  padding: 0 6px;"
            "}"
        )

    # ==================== 设备检测 ====================

    def detect_device(self):
        """启动时自动扫描 iOS 设备（静默模式）"""
        self.scan_devices(silent=True)

    def scan_devices(self, silent=False):
        """扫描 iOS 设备"""
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("扫描中...")
        QApplication.processEvents()

        self.all_devices = scan_all_devices(self.ios_exe)

        self.scan_btn.setText("扫描设备")
        self.scan_btn.setEnabled(True)

        # 更新下拉框
        self.device_combo.blockSignals(True)
        self.device_combo.clear()

        if self.all_devices:
            for d in self.all_devices:
                udid = d.get("udid", "未知")
                name = d.get("deviceName") or d.get("name") or "iOS 设备"
                self.device_combo.addItem(f"{name} ({udid})", udid)
            self.device_combo.setCurrentIndex(0)
            self._on_device_selected(0)
        else:
            self.device_combo.addItem("无设备", None)
            self.device_status_label.setText("⚠ 未检测到 iOS 设备，请检查连接")
            self.device_status_label.setStyleSheet(
                f"color: {self.COLOR_RED}; padding: 4px 6px;"
                f"background-color: {self.COLOR_BG_LIGHT}; border-radius: 3px;"
            )

        self.device_combo.blockSignals(False)

        if not silent:
            if self.all_devices:
                QMessageBox.information(self, "扫描完成",
                    f"发现 {len(self.all_devices)} 台 iOS 设备")
            else:
                QMessageBox.warning(self, "扫描完成",
                    "未发现 iOS 设备，请确认：\n"
                    "1. iPhone 已通过 USB 连接电脑\n"
                    "2. 设备已解锁\n"
                    "3. 如首次连接，需先在终端执行: ios pair")

    def _on_device_selected(self, index):
        """用户从下拉框选择了设备"""
        if index < 0 or not self.all_devices:
            self.device_info = {}
            return

        if index >= len(self.all_devices):
            return

        self.device_info = self.all_devices[index]
        udid = self.device_info.get("udid", "未知")
        name = self.device_info.get("deviceName") or self.device_info.get("name") or "iOS 设备"

        self.device_status_label.setText(f"✓ 已选择: {name} ({udid})")
        self.device_status_label.setStyleSheet(
            f"color: {self.COLOR_GREEN}; padding: 4px 6px;"
            f"background-color: {self.COLOR_BG_LIGHT}; border-radius: 3px;"
        )

    # ==================== Tunnel ====================

    def _auto_start_tunnel(self, udid):
        """后台自动启动 Tunnel"""
        self.device_status_label.setText("正在启动 Tunnel...")
        self.device_status_label.setStyleSheet(
            f"color: {self.COLOR_ORANGE}; padding: 4px 6px;"
            f"background-color: {self.COLOR_BG_LIGHT}; border-radius: 3px;"
        )
        self.start_btn.setEnabled(False)
        QApplication.processEvents()

        self._tunnel_proc = start_tunnel(self.ios_exe, udid)

        def _wait_tunnel_ui():
            """后台线程：等待 tunnel 就绪（30 秒超时）"""
            deadline = time.time() + 30
            while time.time() < deadline:
                if self._closing:
                    return
                if self._tunnel_proc is not None and self._tunnel_proc.poll() is not None:
                    # 进程已退出，视为失败
                    self._tunnel_failed.emit()
                    return
                time.sleep(1)
            # 超时则视为就绪（可能已经在后台跑了）
            self._tunnel_ready.emit()

        threading.Thread(target=_wait_tunnel_ui, daemon=True).start()

    def _on_tunnel_ready(self):
        """Tunnel 就绪"""
        self.start_btn.setEnabled(True)
        self.device_status_label.setText("✓ Tunnel 已启动")
        self.device_status_label.setStyleSheet(
            f"color: {self.COLOR_GREEN}; padding: 4px 6px;"
            f"background-color: {self.COLOR_BG_LIGHT}; border-radius: 3px;"
        )

    def _on_tunnel_failed(self):
        """Tunnel 启动失败"""
        self.start_btn.setEnabled(True)
        self.device_status_label.setText("⚠ Tunnel 启动失败")
        self.device_status_label.setStyleSheet(
            f"color: {self.COLOR_RED}; padding: 4px 6px;"
            f"background-color: {self.COLOR_BG_LIGHT}; border-radius: 3px;"
        )

    # ==================== 窗口关闭 ====================

    def closeEvent(self, event):
        self._closing = True
        if self._tunnel_proc is not None:
            stop_tunnel(self._tunnel_proc)
            self._tunnel_proc = None
        event.accept()

    # ==================== 任务方法 ====================

    def select_storage_directory(self):
        directory = QFileDialog.getExistingDirectory(
            self, "选择数据存储目录", os.path.expanduser("~")
        )
        if directory:
            self.storage_dir = directory
            self.storage_dir_label.setText(directory)
            self.storage_dir_label.setStyleSheet("color: black;")

    def start_annotation(self):
        """开始采标"""
        if not self.storage_dir:
            QMessageBox.warning(self, "警告", "请先选择存储目录！")
            return

        app_name = self.app_name_input.text().strip()
        if not app_name:
            QMessageBox.warning(self, "警告", "请输入软件名称！")
            return

        app_type = self.app_type_combo.currentText()

        # 如果还没选设备，再扫一次
        if not self.device_info:
            self.all_devices = scan_all_devices(self.ios_exe)
            if self.all_devices:
                self.device_info = self.all_devices[0]
            else:
                reply = QMessageBox.question(
                    self, "设备未连接",
                    "未检测到 iOS 设备，截图功能将不可用。\n\n是否仍要继续？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return

        udid = self.device_info.get("udid") if self.device_info else None

        # 有设备则自动启动 tunnel
        if udid:
            self._auto_start_tunnel(udid)

        # 初始化数据管理器
        self.data_manager = DataManager(base_dir=self.storage_dir)
        self.data_manager.create_task_directory("iOS", app_type, app_name)

        screen_info = self.data_manager.get_screen_info(udid)

        # 创建标注编辑器
        self.annotation_window = AnnotationEditor(
            data_manager=self.data_manager,
            app_name=app_name,
            task_instruction="",
            screen_info=screen_info,
            app_type=app_type,
            udid=udid,
            close_callback=self.show,
        )

        # 延迟询问任务指令（等 Tunnel 启动一会儿）
        QTimer.singleShot(300, lambda: self.ask_first_instruction(app_name))

        self.annotation_window.show()
        self.hide()

    def ask_first_instruction(self, app_name):
        from PyQt5.QtWidgets import QInputDialog
        new_instruction, ok = QInputDialog.getText(
            self.annotation_window,
            "任务指令",
            f"请输入【{app_name}】的任务指令：",
            QLineEdit.Normal,
            "",
        )
        if ok and new_instruction.strip():
            self.annotation_window.task_instruction = new_instruction.strip()
            self.annotation_window.status_label.setText(
                f"任务初始化中 - 指令: {self.annotation_window.task_instruction}"
            )
            self.annotation_window.initialize_gui_directory()
        else:
            self.annotation_window.close()
            self.show()

    def resume_annotation(self):
        """从已有 gui_xxxxxx 目录的草稿恢复未完成任务"""
        start_dir = self.storage_dir or os.path.expanduser("~")

        gui_dir = QFileDialog.getExistingDirectory(
            self,
            "选择要继续的 gui 任务目录",
            start_dir,
        )
        if not gui_dir:
            return

        dir_name = os.path.basename(os.path.normpath(gui_dir))
        match = re.fullmatch(r"gui_(\d{6})", dir_name)
        if not match:
            QMessageBox.warning(self, "警告", "请选择 gui_xxxxxx 形式的任务目录")
            return

        draft = DataManager.load_draft_from_dir(gui_dir)
        if draft is None:
            QMessageBox.warning(self, "警告",
                "该目录没有可恢复的草稿（draft）或草稿已损坏")
            return

        gui_number = match.group(1)
        base_dir = os.path.dirname(os.path.normpath(gui_dir))

        # 如果还没检测设备，再扫一次
        if not self.device_info:
            self.all_devices = scan_all_devices(self.ios_exe)
            if self.all_devices:
                self.device_info = self.all_devices[0]
            else:
                reply = QMessageBox.question(
                    self, "设备未连接",
                    "未检测到 iOS 设备，续采期间截图功能将不可用。\n\n是否仍要继续？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return

        udid = self.device_info.get("udid") if self.device_info else None

        if udid:
            self._auto_start_tunnel(udid)

        dm = DataManager(base_dir=base_dir)

        app_name = draft.get("app_name") or dir_name
        app_type = draft.get("app_type", "")
        screen_info = draft.get("screen_info")
        if not isinstance(screen_info, dict):
            screen_info = dm.get_screen_info(udid)
        task_instruction = draft.get("task_instruction", "")

        self.annotation_window = AnnotationEditor(
            data_manager=dm,
            app_name=app_name,
            task_instruction=task_instruction,
            screen_info=screen_info,
            app_type=app_type,
            udid=udid,
            close_callback=self.show,
        )
        need_next_instruction = self.annotation_window.load_from_draft(draft)

        self.annotation_window.show()
        self.hide()

        if need_next_instruction:
            QTimer.singleShot(300, self.ask_next_instruction_after_resume)

    def ask_next_instruction_after_resume(self):
        """续采恢复后询问下一条任务指令"""
        from PyQt5.QtWidgets import QInputDialog
        new_instruction, ok = QInputDialog.getText(
            self.annotation_window,
            "任务指令",
            "请输入下一个任务的指令：",
            QLineEdit.Normal,
            "",
        )
        if ok and new_instruction.strip():
            self.annotation_window.task_instruction = new_instruction.strip()
            self.annotation_window.status_label.setText(
                f"新任务开始 - 指令: {self.annotation_window.task_instruction} - 请截图"
            )


def main():
    print("正在启动 GUI长步骤采标工具-iOS...")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 打包后启动时自动检查并应用更新
    try:
        updater.ensure_latest(app)
    except Exception as e:
        print(f"更新检查失败，已忽略: {e}")

    window = InitTaskWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
