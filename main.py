#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI长步骤采标工具-Windows
用于采集和标注用户在桌面平台上的 GUI 操作轨迹
支持 Windows / macOS / Linux
"""

import sys
import os
import re

# Qt 插件路径设置（必须在导入 PyQt5 之前，跨平台）
try:
    import PyQt5
    qt_plugin_path = os.path.join(os.path.dirname(PyQt5.__file__), 'Qt5', 'plugins')
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(qt_plugin_path, 'platforms')
    os.environ['QT_PLUGIN_PATH'] = qt_plugin_path
except ImportError:
    pass

import json
import platform
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QLineEdit,
                             QComboBox, QTextEdit, QGroupBox, QFormLayout,
                             QStackedWidget, QMessageBox, QFileDialog,
                             QScrollArea, QFrame, QSplitter)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap, QImage, QFont

from screenshot_capture import ScreenshotCaptureWindow
from annotation_editor import AnnotationEditor
from data_manager import DataManager
from hotkey_manager import GlobalHotkeyManager
import app_version
import updater


class InitTaskWindow(QMainWindow):
    """任务初始化窗口"""

    def __init__(self, hotkey_manager):
        super().__init__()
        self.setWindowTitle(f"GUI长步骤采标工具-Windows v{app_version.__version__} - 任务初始化")
        self.setGeometry(100, 100, 600, 500)

        # 全局快捷键管理器
        self.hotkey_manager = hotkey_manager

        # 软件类型列表（平台前缀表示该类 app 只需在对应平台上标注）
        self.app_types = [
            "社交", "电商", "办公", "浏览器/网页", "地图/出行/天气",
            "视频/影音", "系统工具", "文件系统/命令行/终端/任务管理",
            "支付/银行/金融/股票", "教育/学习", "生活服务", "效率工具",
            "开发工具", "知识库/在线文档", "在线会议", "SaaS", "直播平台"
        ]

        # 初始化数据管理器
        self.data_manager = DataManager()

        # 存储母目录
        self.storage_dir = None

        # 当前唯一活动的标注窗口引用（返回菜单/关闭时会被置空）
        self.annotation_window = None

        self.init_ui()

    def init_ui(self):
        """初始化界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # 标题
        title_label = QLabel("新建标注任务")
        title_label.setFont(QFont("Arial", 18, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # 表单区域
        form_group = QGroupBox("任务信息")
        form_layout = QFormLayout()

        # 存储母目录选择
        storage_layout = QHBoxLayout()
        self.storage_dir_label = QLabel("未选择")
        self.storage_dir_label.setStyleSheet("color: gray;")
        select_storage_btn = QPushButton("选择存储目录")
        select_storage_btn.clicked.connect(self.select_storage_directory)
        storage_layout.addWidget(QLabel("存储目录:"))
        storage_layout.addWidget(self.storage_dir_label)
        storage_layout.addWidget(select_storage_btn)
        form_layout.addRow(storage_layout)

        # 具体软件名称
        self.app_name_input = QLineEdit()
        self.app_name_input.setPlaceholderText("例如:网易有道翻译、微信、淘宝等")
        form_layout.addRow("软件名称:", self.app_name_input)

        # 软件类型选择
        self.app_type_combo = QComboBox()
        self.app_type_combo.addItems(self.app_types)
        form_layout.addRow("软件类型:", self.app_type_combo)

        form_group.setLayout(form_layout)
        layout.addWidget(form_group)

        # 根据平台显示对应的快捷键说明
        if sys.platform == 'darwin':
            hotkey_name = "Cmd"
            screenshot_hk = "Cmd"
        else:
            hotkey_name = "Ctrl"
            screenshot_hk = "Alt"

        # 说明文本
        info_label = QLabel(
            "使用说明：\n"
            "1. 填写任务信息后点击'开始标注'\n"
            "2. 输入第一个任务的指令\n"
            f"3. 按 {screenshot_hk}+Q 给下一步截图\n"
            f"4. 截图选框后按 {hotkey_name}+S 确认选择（ESC 清除/取消）\n"
            "5. 如果当前步骤没有截图，不允许进入下一步\n"
            "6. 选择'任务完成'动作结束当前任务，可选择继续新任务"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: gray; padding: 10px;")
        layout.addWidget(info_label)

        # 按钮
        btn_layout = QHBoxLayout()
        start_btn = QPushButton("开始标注")
        start_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 10px; font-size: 14px; }")
        start_btn.clicked.connect(self.start_annotation)
        btn_layout.addWidget(start_btn)

        # 断点续采：从已有 gui_xxxxxx 目录的 draft 恢复
        resume_btn = QPushButton("继续未完成任务")
        resume_btn.setStyleSheet("QPushButton { background-color: #FF9800; color: white; padding: 10px; font-size: 14px; }")
        resume_btn.clicked.connect(self.resume_annotation)
        btn_layout.addWidget(resume_btn)

        # 已完成任务再编辑：选择 gui_xxxxxx 目录，按轮次打开编辑器修改并写回
        edit_btn = QPushButton("编辑已完成任务")
        edit_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; padding: 10px; font-size: 14px; }")
        edit_btn.clicked.connect(self.edit_completed_annotation)
        btn_layout.addWidget(edit_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

    def select_storage_directory(self):
        """选择存储母目录"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择数据存储母目录",
            os.path.expanduser("~")  # 默认用户主目录
        )
        if directory:
            self.storage_dir = directory
            self.storage_dir_label.setText(directory)
            self.storage_dir_label.setStyleSheet("color: black;")

    def _discard_previous_editor(self):
        """打开新编辑器前，确保上一个标注窗口已解绑快捷键并被销毁。"""
        prev = self.annotation_window
        if prev is None:
            return
        try:
            # cleanup_resources 幂等：即便窗口已在关闭流程中也安全
            prev.cleanup_resources()
            prev.close()
            prev.deleteLater()
        except RuntimeError:
            # 底层 C++ 对象可能已被销毁
            pass
        self.annotation_window = None

    def start_annotation(self):
        """开始标注流程"""
        # 检查是否选择了存储目录
        if not self.storage_dir:
            QMessageBox.warning(self, "警告", "请先选择存储母目录！")
            return

        app_name = self.app_name_input.text().strip()
        if not app_name:
            QMessageBox.warning(self, "警告", "请输入软件名称!")
            return

        # 清理可能残留的上一个标注窗口，避免幽灵窗口同时响应快捷键
        self._discard_previous_editor()

        # 获取选择的软件类型
        app_type = self.app_type_combo.currentText()

        # 创建数据管理器，使用用户选择的存储目录
        self.data_manager = DataManager(base_dir=self.storage_dir)

        # 创建任务目录（按真实系统传平台参数，不再硬编码 mac）
        platform_name = {"darwin": "mac", "win32": "windows"}.get(sys.platform, "linux")
        success = self.data_manager.create_task_directory(platform_name, app_type, app_name)
        if not success:
            QMessageBox.critical(self, "错误", "创建任务目录失败!")
            return

        # 获取屏幕信息
        screen_info = self.data_manager.get_screen_info()

        # 启动标注编辑器（不传入初始 instruction）
        self.annotation_window = AnnotationEditor(
            data_manager=self.data_manager,
            app_name=app_name,
            task_instruction="",  # 初始为空，稍后询问
            screen_info=screen_info,
            app_type=app_type,  # 传入应用类型
            hotkey_listener=self.hotkey_manager,  # 传递全局快捷键管理器
            init_window=self  # 传递初始化窗口引用，用于返回菜单
        )
        self.annotation_window.show()

        # 延迟后询问第一个任务的 instruction
        from PyQt5.QtWidgets import QInputDialog
        QTimer.singleShot(300, lambda: self.ask_first_instruction(app_name))

        # 隐藏初始化窗口
        self.hide()

    def ask_first_instruction(self, app_name):
        """询问第一个任务的指令"""
        from PyQt5.QtWidgets import QInputDialog

        new_instruction, ok = QInputDialog.getText(
            self.annotation_window,
            "任务指令",
            f"请输入【{app_name}】的第一个任务指令：",
            QLineEdit.Normal,
            ""
        )

        if ok and new_instruction.strip():
            # 设置任务指令
            self.annotation_window.task_instruction = new_instruction.strip()
            self.annotation_window.status_label.setText(f"任务开始 - 指令: {self.annotation_window.task_instruction}")
        else:
            # 用户取消了，关闭窗口
            self.annotation_window.close()

    def resume_annotation(self):
        """从已有 gui_xxxxxx 目录的草稿恢复未完成任务（断点续采）"""
        # 让用户选择要继续的 gui 任务目录
        gui_dir = QFileDialog.getExistingDirectory(
            self,
            "选择要继续的 gui 任务目录",
            os.path.expanduser("~")
        )
        if not gui_dir:
            return

        dir_name = os.path.basename(os.path.normpath(gui_dir))
        match = re.fullmatch(r"gui_(\d{6})", dir_name)
        if not match:
            QMessageBox.warning(self, "警告", "请选择 gui_xxxxxx 形式的任务目录")
            return

        # 读取草稿（只读校验，不修改磁盘任何文件）
        draft = DataManager.load_draft_from_dir(gui_dir)
        if draft is None:
            QMessageBox.warning(self, "警告", "该目录没有可恢复的草稿（draft）或草稿已损坏")
            return

        gui_number = match.group(1)
        base_dir = os.path.dirname(os.path.normpath(gui_dir))

        # 数据管理器指向母目录，gui_xxxxxx 文件夹直接位于其下
        self.data_manager = DataManager(base_dir=base_dir)

        app_name = draft.get("app_name") or dir_name
        app_type = draft.get("app_type", "")
        screen_info = draft.get("screen_info")
        if not screen_info:
            screen_info = self.data_manager.get_screen_info()
        task_instruction = draft.get("task_instruction", "")

        # 清理可能残留的上一个标注窗口，避免幽灵窗口同时响应快捷键
        self._discard_previous_editor()

        # 创建编辑器并从草稿恢复
        self.annotation_window = AnnotationEditor(
            data_manager=self.data_manager,
            app_name=app_name,
            task_instruction=task_instruction,
            screen_info=screen_info,
            app_type=app_type,
            hotkey_listener=self.hotkey_manager,
            init_window=self
        )
        need_next_instruction = self.annotation_window.load_from_draft(draft)
        self.annotation_window.show()

        # current_steps 为空（崩溃在轮次切换等待输入时）：询问下一条指令
        if need_next_instruction:
            QTimer.singleShot(300, self.ask_next_instruction_after_resume)

        # 隐藏初始化窗口
        self.hide()

    def ask_next_instruction_after_resume(self):
        """续采恢复后询问下一条任务指令（取消则停留空白页，不关闭窗口）"""
        from PyQt5.QtWidgets import QInputDialog

        new_instruction, ok = QInputDialog.getText(
            self.annotation_window,
            "任务指令",
            "请输入下一个任务的指令：",
            QLineEdit.Normal,
            ""
        )

        if ok and new_instruction.strip():
            self.annotation_window.task_instruction = new_instruction.strip()
            self.annotation_window.status_label.setText(
                f"新任务开始 - 指令: {self.annotation_window.task_instruction}")

    def edit_completed_annotation(self):
        """编辑已完成任务：选择 gui_xxxxxx 目录 → 选轮次 → 打开编辑器编辑并写回原文件"""
        gui_dir = QFileDialog.getExistingDirectory(
            self,
            "选择要编辑的已完成任务目录",
            self.storage_dir or os.path.expanduser("~")
        )
        if not gui_dir:
            return

        dir_name = os.path.basename(os.path.normpath(gui_dir))
        match = re.fullmatch(r"gui_(\d{6})", dir_name)
        if not match:
            QMessageBox.warning(self, "警告", "请选择 gui_xxxxxx 形式的任务目录")
            return

        # 读取最终 JSON（目录未完成时会返回明确提示）；不修改磁盘任何文件
        data, error = DataManager.load_json_from_dir(gui_dir)
        if error:
            QMessageBox.warning(self, "警告", error)
            return

        coords_entries, coords_error = DataManager.load_coords_from_dir(gui_dir)
        if coords_error:
            QMessageBox.warning(self, "警告", coords_error)
            coords_entries = []

        # 解析轮次（user/assistant 配对）
        rounds = []
        pending_instruction = ""
        for message in data.get("messages", []) or []:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role == "user":
                pending_instruction = message.get("instruction", "") or ""
            elif role == "assistant":
                rounds.append({
                    "instruction": pending_instruction,
                    "trajectory": message.get("trajectory", []) or []
                })
                pending_instruction = ""
        if not rounds:
            QMessageBox.warning(self, "警告", "该任务没有任何可编辑轮次")
            return

        round_index = 0
        if len(rounds) >= 2:
            from PyQt5.QtWidgets import QInputDialog
            items = []
            for i, round_data in enumerate(rounds):
                summary = (round_data.get("instruction") or "").strip().replace("\n", " ")[:30]
                items.append(f"第 {i + 1} 轮：{summary}")
            selected, ok = QInputDialog.getItem(
                self, "选择轮次", "请选择要编辑的轮次：", items, 0, False
            )
            if not ok or not selected:
                return
            try:
                round_index = items.index(selected)
            except ValueError:
                round_index = 0

        base_dir = os.path.dirname(os.path.normpath(gui_dir))
        self.data_manager = DataManager(base_dir=base_dir)

        # 最终 JSON 中没有 app_name，使用目录名；app_type 仅用于新建任务，编辑时留空
        app_name = dir_name
        app_type = ""
        screen_info = {
            "platform": data.get("platform") or "",
            "system": data.get("system") or "",
            "screen_size": data.get("screen_size") or [1920, 1080]
        }
        if not screen_info["platform"] or not screen_info["system"]:
            fallback = self.data_manager.get_screen_info()
            screen_info["platform"] = screen_info["platform"] or fallback.get("platform", "")
            screen_info["system"] = screen_info["system"] or fallback.get("system", "")

        # 清理可能残留的上一个标注窗口，避免幽灵窗口同时响应快捷键
        self._discard_previous_editor()

        self.annotation_window = AnnotationEditor(
            data_manager=self.data_manager,
            app_name=app_name,
            task_instruction="",
            screen_info=screen_info,
            app_type=app_type,
            hotkey_listener=self.hotkey_manager,
            init_window=self
        )
        self.annotation_window.load_from_completed_json(
            data, coords_entries, round_index, gui_dir
        )
        self.annotation_window.show()

        # 隐藏初始化窗口
        self.hide()


def main():
    """主函数"""
    print("正在启动 GUI长步骤采标工具-Windows...")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 打包后启动时自动检查并应用更新（可能在此处重启进程）；源码运行时为空操作
    updater.ensure_latest(app)

    # 创建全局快捷键管理器
    hotkey_manager = GlobalHotkeyManager()

    print("创建主窗口...")
    window = InitTaskWindow(hotkey_manager)

    # 显示窗口，使用 processEvents 确保窗口立即渲染
    print("显示窗口...")
    window.show()
    window.raise_()
    window.activateWindow()

    # 强制处理事件队列，让窗口立即渲染
    app.processEvents()

    # 窗口显示后注册全局快捷键
    hotkey_manager.register_all()

    print("程序已启动，窗口应该已显示")

    # 运行应用
    exit_code = app.exec_()

    # 退出前注销全局快捷键
    hotkey_manager.unregister_all()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
