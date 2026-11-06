#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI长步骤采标工具-Android 入口
用于采集和标注用户在 Android 平台上的 GUI 操作轨迹
"""

import sys
import os
import re
import threading

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QLineEdit,
                             QComboBox, QGroupBox, QFormLayout,
                             QMessageBox, QFileDialog, QInputDialog)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont

import app_version
import updater
from data_manager import DataManager
from annotation_editor import AnnotationEditor
from screenshot_capture import AndroidScreenCapture

# 软件分类列表
APP_TYPES = [
    "社交", "电商", "办公", "浏览器/网页", "地图/出行/天气",
    "视频/影音", "系统工具", "文件系统/命令行/终端/任务管理",
    "支付/银行/金融/股票", "教育/学习", "生活服务", "效率工具",
    "开发工具", "知识库/在线文档", "在线会议", "SaaS", "直播平台"
]


# 1.6（B3）编辑模式选轮次：候选项渲染与下标解析。
# 早前摘要只截指令前若干字，同指令的多轮会渲染出完全相同的字符串，而定位
# 用的是 items.index(item)——永远命中第一个，于是改错轮并把错误内容写回
# 已交付数据，不可恢复。现在：候选项一律带轮次序号与步数保证两两不同；下标
# 直接取自 enumerate 的位置映射，不再做字符串搜索；无法唯一确定时交回 None，
# 由调用方中止，绝不静默退回第 1 轮。
ROUND_SUMMARY_CHARS = 30


def build_round_choices(rounds, summary_chars=ROUND_SUMMARY_CHARS):
    """渲染「选择要编辑的轮次」的候选项。

    :param rounds: 轮次列表，元素为 {"instruction", "trajectory"} 或
        (instruction, trajectory) 二元组
    :return: (items, index_by_item)。items 出现重复时 index_by_item 为 None，
        调用方必须放弃编辑，而不是猜一个轮次。
    """
    items = []
    for i, round_data in enumerate(rounds):
        if isinstance(round_data, dict):
            instruction = round_data.get("instruction") or ""
            trajectory = round_data.get("trajectory") or []
        else:
            instruction, trajectory = round_data
        summary = instruction.strip().replace("\n", " ")
        if not summary:
            summary = "(无指令)"
        if len(summary) > summary_chars:
            summary = summary[:summary_chars] + "..."
        items.append(f"第 {i + 1} 轮（{len(trajectory)} 步）：{summary}")

    if len(set(items)) != len(items):
        return items, None
    return items, {text: i for i, text in enumerate(items)}


def resolve_round_index(index_by_item, selected):
    """把对话框返回的文本换成轮次下标；无法唯一确定时返回 None。"""
    if not index_by_item or selected is None:
        return None
    return index_by_item.get(selected)


class InitTaskWindow(QMainWindow):
    """任务初始化窗口"""

    _device_scan_finished = pyqtSignal(bool, object, object)
    _redetect_finished = pyqtSignal(bool, object, object)

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
        self.setWindowTitle(f"GUI长步骤采标工具-Android - 任务初始化 v{app_version.__version__}")
        self.setGeometry(100, 100, 650, 650)
        self.setMinimumSize(600, 600)

        self.data_manager = DataManager()
        self.storage_dir = None
        self._serial = None
        self._screen_info = {}

        self._base_font = QFont("Microsoft YaHei", 10)
        self.setFont(self._base_font)

        self._scan_silent = False

        self._device_scan_finished.connect(self._on_device_scan_finished)
        self._redetect_finished.connect(self._on_redetect_finished)

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
        title = QLabel("GUI长步骤采标工具-Android")
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

        self.device_status_label = QLabel("检测 Android 设备...")
        self.device_status_label.setFont(self.FONT_STATUS)
        self.device_status_label.setStyleSheet(
            f"color: {self.COLOR_ORANGE}; padding: 4px 6px;"
            f"background-color: {self.COLOR_BG_LIGHT}; border-radius: 3px;"
        )
        device_layout.addWidget(self.device_status_label)

        # 扫描按钮
        self.scan_btn = QPushButton("扫描设备")
        self.scan_btn.setFont(self.FONT_BTN_NORMAL)
        self.scan_btn.setStyleSheet(self.BTN_STYLE)
        self.scan_btn.setMinimumWidth(90)
        self.scan_btn.clicked.connect(self.scan_devices)
        device_layout.addWidget(self.scan_btn)

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
            "1. 确保 Android 手机通过 USB 连接电脑，开启 USB 调试\n"
            "2. 点击 [扫描设备] 确认设备已连接\n"
            "3. 填写任务信息后点击 [开始采标]\n"
            "4. scrcpy 窗口：左键操作手机，右键拖拽拉框标注\n"
            "5. 快捷键: Ctrl+Q = 截图 | Ctrl+S = 确认/下一步 | Ctrl+Z = 撤销上一步"
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

        # ---- 开始按钮 ----
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
            f"  background-color: #388E3C;"
            "}"
            "QPushButton:disabled {"
            "  background-color: #BDBDBD;"
            "}"
        )
        self.start_btn.clicked.connect(self.start_annotation)
        layout.addWidget(self.start_btn)

        # ---- 继续未完成任务（断点续采） ----
        self.resume_btn = QPushButton("继续未完成任务")
        self.resume_btn.setFont(self.FONT_BTN_NORMAL)
        self.resume_btn.setMinimumHeight(36)
        self.resume_btn.setCursor(Qt.PointingHandCursor)
        self.resume_btn.setStyleSheet(
            "QPushButton {"
            "  padding: 8px;"
            "  background-color: #2196F3;"
            "  color: white;"
            "  border: none;"
            "  border-radius: 4px;"
            "}"
            "QPushButton:hover {"
            "  background-color: #1976D2;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #1565C0;"
            "}"
        )
        self.resume_btn.clicked.connect(self.resume_annotation)
        layout.addWidget(self.resume_btn)

        # ---- 编辑已完成任务 ----
        self.edit_completed_btn = QPushButton("编辑已完成任务")
        self.edit_completed_btn.setFont(self.FONT_BTN_NORMAL)
        self.edit_completed_btn.setMinimumHeight(36)
        self.edit_completed_btn.setCursor(Qt.PointingHandCursor)
        self.edit_completed_btn.setStyleSheet(
            "QPushButton {"
            "  padding: 8px;"
            "  background-color: #7E57C2;"
            "  color: white;"
            "  border: none;"
            "  border-radius: 4px;"
            "}"
            "QPushButton:hover {"
            "  background-color: #5E35B1;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #4527A0;"
            "}"
        )
        self.edit_completed_btn.clicked.connect(self.edit_completed_annotation)
        layout.addWidget(self.edit_completed_btn)

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
        """启动时自动检测 Android 设备"""
        self.scan_devices(silent=True)

    def scan_devices(self, silent=False):
        """扫描 ADB 设备（后台线程执行，避免阻塞 UI 主线程）"""
        self._scan_silent = silent
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("扫描中...")
        QApplication.processEvents()

        threading.Thread(target=self._scan_devices_worker, daemon=True).start()

    def _scan_devices_worker(self):
        """后台线程：检测设备并读取设备信息"""
        capture = AndroidScreenCapture()
        has_device, serial = capture.check_device()
        if has_device:
            capture.set_serial(serial)
            screen_info = capture.get_device_info()
        else:
            screen_info = {"platform": "Android", "system": "", "screen_size": [1080, 2400]}
        self._device_scan_finished.emit(has_device, serial, screen_info)

    def _on_device_scan_finished(self, has_device, serial, screen_info):
        """扫描结果回到主线程更新 UI"""
        self.scan_btn.setText("扫描设备")
        self.scan_btn.setEnabled(True)

        if has_device:
            self._serial = serial
            self._screen_info = screen_info
            device_model = screen_info.get("device_model", "")
            platform = screen_info.get("platform", "Android")
            system_ver = screen_info.get("system", "")
            screen_size = screen_info.get("screen_size", [1080, 2400])
            os_label = system_ver or platform
            label = f"✓ 已连接: {device_model} ({os_label}) - 分辨率 {screen_size[0]}x{screen_size[1]}"
            self.device_status_label.setText(label)
            self.device_status_label.setStyleSheet(
                f"color: {self.COLOR_GREEN}; padding: 4px 6px;"
                f"background-color: {self.COLOR_BG_LIGHT}; border-radius: 3px;"
            )
        else:
            self._serial = None
            self._screen_info = {"platform": "Android", "system": "", "screen_size": [1080, 2400]}
            self.device_status_label.setText("⚠ 未检测到 Android 设备，请检查 USB 连接和 USB 调试开关")
            self.device_status_label.setStyleSheet(
                f"color: {self.COLOR_RED}; padding: 4px 6px;"
                f"background-color: {self.COLOR_BG_LIGHT}; border-radius: 3px;"
            )

        if not self._scan_silent:
            if has_device:
                QMessageBox.information(self, "扫描完成", "发现 Android 设备")
            else:
                QMessageBox.warning(self, "扫描完成",
                    "未发现 Android 设备，请确认：\n"
                    "1. 手机已通过 USB 连接电脑\n"
                    "2. 已开启 USB 调试模式\n"
                    "3. 已授权电脑的调试请求")

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

        # 如果还没检测过，再后台检测一次（避免阻塞 UI 主线程）
        if self._serial is None:
            self.start_btn.setEnabled(False)
            self.start_btn.setText("检测设备中...")
            threading.Thread(target=self._redetect_and_continue, daemon=True).start()
            return

        self._begin_annotation(app_name, app_type)

    def _redetect_and_continue(self):
        """后台线程：重新检测设备后继续开始采标流程"""
        capture = AndroidScreenCapture()
        has_device, serial = capture.check_device()
        if has_device:
            capture.set_serial(serial)
            screen_info = capture.get_device_info()
        else:
            screen_info = {"platform": "Android", "system": "", "screen_size": [1080, 2400]}
        self._redetect_finished.emit(has_device, serial, screen_info)

    def _on_redetect_finished(self, has_device, serial, screen_info):
        self.start_btn.setEnabled(True)
        self.start_btn.setText("开始采标")

        if has_device:
            self._serial = serial
            self._screen_info = screen_info
        else:
            reply = QMessageBox.question(
                self, "设备未连接",
                "未检测到 Android 设备。\n\n是否仍要继续？（scrcpy 和截图功能将不可用）",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        self._begin_annotation(self.app_name_input.text().strip(),
                               self.app_type_combo.currentText())

    def _begin_annotation(self, app_name, app_type):
        # 初始化数据管理器
        self.data_manager = DataManager(base_dir=self.storage_dir)
        self.data_manager.create_task_directory("Android", app_type, app_name)

        # 创建标注编辑器（scrcpy 嵌入 + 蒙版拉框 + 动作编辑）
        self.annotation_window = AnnotationEditor(
            data_manager=self.data_manager,
            app_name=app_name,
            task_instruction="",
            screen_info=self._screen_info,
            app_type=app_type,
            serial=self._serial,
            init_window=self
        )

        # 启动 scrcpy
        self.annotation_window.scrcpy_widget.start_scrcpy(self._serial)

        # 询问任务指令
        QTimer.singleShot(500, lambda: self._ask_instruction(app_name))

        self.annotation_window.show()
        self.hide()

    def _ask_instruction(self, app_name):
        dialog = QInputDialog(self.annotation_window)
        dialog.setWindowTitle("任务指令")
        dialog.setLabelText(f"请输入【{app_name}】的任务指令：")
        dialog.setTextEchoMode(QLineEdit.Normal)
        dialog.setTextValue("")
        dialog.move(dialog.x() + 150, dialog.y())
        ok = dialog.exec_()
        new_instruction = dialog.textValue()
        if ok and new_instruction.strip():
            self.annotation_window.task_instruction = new_instruction.strip()
            self.annotation_window.status_label.setText(
                f"任务初始化中 - 指令: {self.annotation_window.task_instruction}"
            )
            self.annotation_window.initialize_task()
        else:
            self.annotation_window.close()
            self.show()

    # ==================== 断点续采 ====================

    def resume_annotation(self):
        """从已有 gui_xxxxxx 目录的草稿恢复未完成任务（断点续采）"""
        if self._serial is None:
            QMessageBox.warning(self, "警告", "请先扫描并连接 Android 设备，再继续未完成任务")
            return

        gui_dir = QFileDialog.getExistingDirectory(
            self,
            "选择要继续的 gui 任务目录",
            self.storage_dir or os.path.expanduser("~")
        )
        if not gui_dir:
            return

        dir_name = os.path.basename(os.path.normpath(gui_dir))
        match = re.fullmatch(r"gui_(\d{6})", dir_name)
        if not match:
            QMessageBox.warning(self, "警告", "请选择 gui_xxxxxx 形式的任务目录")
            return

        # 读取草稿（只读校验，不修改磁盘任何文件）
        draft, err_type = DataManager.load_draft_from_dir(gui_dir)
        if draft is None:
            if err_type == DataManager.DRAFT_ERR_CORRUPT:
                QMessageBox.warning(self, "警告", "草稿文件已损坏，无法恢复")
            elif err_type == DataManager.DRAFT_ERR_NOT_FOUND:
                # 无草稿：进一步区分"已完成任务"、"只有截图"、"完全空目录"
                if DataManager.is_task_completed(gui_dir):
                    QMessageBox.information(self, "提示", "该任务已正常完成，无需续采")
                elif DataManager.has_screenshots(gui_dir):
                    QMessageBox.warning(self, "警告",
                        "该目录未包含有效的采集数据（无草稿也无最终结果），"
                        "可能是中途关闭后草稿被清理")
                else:
                    QMessageBox.warning(self, "警告", "该目录不包含任何采集数据")
            return

        # 数据管理器指向母目录，gui_xxxxxx 文件夹直接位于其下
        base_dir = os.path.dirname(os.path.normpath(gui_dir))
        self.data_manager = DataManager(base_dir=base_dir)
        self.data_manager.create_task_directory("Android")

        app_name = draft.get("app_name") or dir_name
        app_type = draft.get("app_type", "")
        screen_info = draft.get("screen_info")
        if not isinstance(screen_info, dict) or not screen_info:
            screen_info = {"platform": "Android", "system": "", "screen_size": [1080, 2400]}
        task_instruction = draft.get("task_instruction", "")

        # 创建编辑器并从草稿恢复（续采同样要走 scrcpy 嵌入流程）
        self.annotation_window = AnnotationEditor(
            data_manager=self.data_manager,
            app_name=app_name,
            task_instruction=task_instruction,
            screen_info=screen_info,
            app_type=app_type,
            serial=self._serial,
            init_window=self
        )
        need_next_instruction = self.annotation_window.load_from_draft(draft)

        # 启动 scrcpy（与新任务一致）
        self.annotation_window.scrcpy_widget.start_scrcpy(self._serial)
        self.annotation_window.show()

        # 当前轮为空但已有历史轮次（崩溃在轮次切换等待输入时）：追问下一条指令
        if need_next_instruction:
            QTimer.singleShot(300, self.ask_next_instruction_after_resume)

        self.hide()

    def ask_next_instruction_after_resume(self):
        """续采恢复后询问下一条任务指令（取消则停留空白页，不关闭窗口）"""
        new_instruction, ok = QInputDialog.getText(
            self.annotation_window,
            "任务指令",
            "请输入下一个任务的指令：",
            QLineEdit.Normal,
            ""
        )
        # 状态变更全在编辑器侧统一处理（含 B19 的取消分支）
        self.annotation_window.apply_next_round_instruction(new_instruction, ok)

    # ==================== 编辑已完成任务 ====================

    def edit_completed_annotation(self):
        """选择已完成的 gui_xxxxxx 目录，按轮次进入编辑器修改并写回原文件"""
        # 编辑不要求连接设备：无设备时仅截图/实时手机操作不可用
        if self._serial is None:
            QMessageBox.information(
                self, "提示", "未检测到设备，截图功能不可用，可继续编辑已有数据"
            )

        gui_dir = QFileDialog.getExistingDirectory(
            self,
            "选择要编辑的已完成任务目录",
            self.storage_dir or os.path.expanduser("~")
        )
        if not gui_dir:
            return

        dir_name = os.path.basename(os.path.normpath(gui_dir))
        if not re.fullmatch(r"gui_(\d{6})", dir_name):
            QMessageBox.warning(self, "警告", "请选择 gui_xxxxxx 形式的任务目录")
            return

        completed_data, err = DataManager.load_json_from_dir(gui_dir)
        if completed_data is None:
            QMessageBox.warning(self, "警告",
                                err or "该任务尚未完成，请使用『继续未完成任务』")
            return

        coords_entries, coord_err = DataManager.load_coords_from_dir(gui_dir)
        if coord_err:
            print(f"[编辑已完成任务] {coord_err}")

        # 轮次摘要（user instruction + assistant trajectory 步数）
        rounds = []
        pending_instruction = ""
        for msg in completed_data.get("messages") or []:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") == "user":
                pending_instruction = msg.get("instruction", "") or ""
            elif msg.get("role") == "assistant":
                rounds.append((pending_instruction, msg.get("trajectory") or []))
        if not rounds:
            QMessageBox.warning(self, "警告", "该任务没有可编辑的标注轮次")
            return

        round_index = 0
        if len(rounds) > 1:
            items, index_by_item = build_round_choices(rounds)
            item, ok = QInputDialog.getItem(
                self, "选择编辑轮次", "请选择要编辑的轮次：", items, 0, False
            )
            if not ok:
                return
            round_index = resolve_round_index(index_by_item, item)
            if round_index is None:
                QMessageBox.critical(
                    self, "错误",
                    "无法唯一确定所选轮次，已取消编辑（原数据保持不变）"
                )
                return

        # 数据管理器指向母目录，gui_xxxxxx 文件夹直接位于其下
        base_dir = os.path.dirname(os.path.normpath(gui_dir))
        self.data_manager = DataManager(base_dir=base_dir)
        self.data_manager.create_task_directory("Android")

        screen_size = completed_data.get("screen_size")
        if not (isinstance(screen_size, list) and len(screen_size) >= 2):
            screen_size = [1080, 2400]
        screen_info = {
            "platform": completed_data.get("platform", "Android"),
            "system": completed_data.get("system", ""),
            "screen_size": screen_size,
        }

        self.annotation_window = AnnotationEditor(
            data_manager=self.data_manager,
            app_name=dir_name,
            task_instruction="",
            screen_info=screen_info,
            app_type="",
            serial=self._serial,
            init_window=self
        )
        self.annotation_window.load_from_completed_json(
            completed_data, coords_entries, round_index, gui_dir
        )

        if self._serial:
            self.annotation_window.scrcpy_widget.start_scrcpy(self._serial)
        self.annotation_window.show()
        self.hide()


def main():
    print("正在启动 GUI长步骤采标工具-Android...")

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 打包后启动时自动检查并应用更新（可能在此处重启进程）；源码运行或失败时不影响启动
    try:
        updater.ensure_latest(app)
    except Exception as e:
        print(f"[更新检查] 跳过: {e}")

    window = InitTaskWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
