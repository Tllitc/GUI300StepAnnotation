#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI长步骤采标工具-macOS
用于采集和标注用户在 macOS 平台上的 GUI 操作轨迹
"""

import sys
import os
import re

# macOS Qt 插件路径设置（必须在导入 PyQt5 之前）
if sys.platform == 'darwin':  # macOS
    try:
        import PyQt5
        qt_plugin_path = os.path.join(os.path.dirname(PyQt5.__file__), 'Qt5', 'plugins')
        os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(qt_plugin_path, 'platforms')
        os.environ['QT_PLUGIN_PATH'] = qt_plugin_path
    except ImportError:
        pass

import json
import platform
import multiprocessing
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QLineEdit, 
                             QComboBox, QTextEdit, QGroupBox, QFormLayout,
                             QStackedWidget, QMessageBox, QFileDialog,
                             QScrollArea, QFrame, QSplitter)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap, QImage, QFont

from screenshot_capture import ScreenshotCaptureWindow
from annotation_editor import AnnotationEditor
from data_manager import DataManager
# from permission_checker import check_and_request_all_permissions


def _hotkey_process_target(queue):
    """在独立子进程中运行 pynput 全局快捷键监听"""
    from pynput import keyboard
    
    def on_screenshot():
        queue.put("screenshot")
    
    def on_save_continue():
        queue.put("save_continue")
    
    try:
        hotkeys = keyboard.GlobalHotKeys({
            '<ctrl>+q': on_screenshot,
            '<ctrl>+s': on_save_continue
        })
        hotkeys.start()
        queue.put(("started", None))
        hotkeys.join()
    except Exception as e:
        queue.put(("error", str(e)))


class GlobalHotkeyListener(QObject):
    """全局快捷键监听器（pynput 运行在独立子进程中，避免崩溃拖垮主进程）"""
    
    screenshot_triggered = pyqtSignal()
    save_continue_triggered = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.process = None
        self.queue = None
        self.timer = None
        self.running = False
        
    def start_listening(self):
        """在独立子进程中启动全局快捷键监听"""
        if self.running:
            return
        
        self.queue = multiprocessing.Queue()
        self.process = multiprocessing.Process(
            target=_hotkey_process_target,
            args=(self.queue,),
            daemon=True
        )
        self.process.start()
        
        self._startup_timeout = QTimer()
        self._startup_timeout.setSingleShot(True)
        self._startup_timeout.timeout.connect(self._on_startup_timeout)
        self._startup_timeout.start(2000)
        
        self.timer = QTimer()
        self.timer.timeout.connect(self._poll_queue)
        self.timer.start(100)
    
    def _on_startup_timeout(self):
        """启动超时检查"""
        if not self.running:
            self.running = True
            print("⚠️ 全局快捷键子进程启动中，请确保应用已获得辅助功能权限")
    
    def _poll_queue(self):
        """定时轮询子进程消息队列"""
        if self.queue is None:
            return
        
        try:
            while not self.queue.empty():
                msg = self.queue.get_nowait()
                if isinstance(msg, tuple):
                    status, detail = msg
                    if status == "started":
                        self.running = True
                        if hasattr(self, '_startup_timeout'):
                            self._startup_timeout.stop()
                        print("✅ 全局快捷键已启用: Control+Q (给下一步截图), Control+S (隐藏窗口)")
                    elif status == "error":
                        print(f"❌ 全局快捷键子进程错误: {detail}")
                        print("⚠️ 请前往 系统设置 > 隐私与安全性 > 辅助功能 中授权终端/Python")
                elif msg == "screenshot":
                    self.screenshot_triggered.emit()
                elif msg == "save_continue":
                    self.save_continue_triggered.emit()
        except Exception:
            pass
        
        if self.process is not None and not self.process.is_alive() and not self.running:
            print("⚠️ 全局快捷键子进程已退出，快捷键功能不可用")
            print("⚠️ 请检查辅助功能权限：系统设置 > 隐私与安全性 > 辅助功能")
            if self.timer:
                self.timer.stop()
    
    def stop_listening(self):
        """停止全局快捷键监听"""
        if self.process and self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=2)
        if self.timer:
            self.timer.stop()
        self.running = False
        print("✅ 全局快捷键已停止")



class InitTaskWindow(QMainWindow):
    """任务初始化窗口"""
    
    def __init__(self, hotkey_listener):
        super().__init__()
        self.setWindowTitle("GUI长步骤采标工具-macOS - 任务初始化")
        self.setGeometry(100, 100, 600, 500)
        
        # 全局快捷键监听器
        self.hotkey_listener = hotkey_listener
        
        # 软件类型列表（按需求文档更新，共17个分类）
        self.app_types = [
            "社交", "电商", "办公",
            "浏览器/网页", "地图/出行/天气",
            "视频/影音", "系统工具",
            "文件系统/命令行/终端/任务管理",
            "支付/银行/金融/股票", "教育/学习",
            "生活服务", "效率工具",
            "开发工具", "知识库/在线文档",
            "在线会议", "SaaS",
            "直播平台"
        ]
        
        # 初始化数据管理器
        self.data_manager = DataManager()
        
        # 存储母目录
        self.storage_dir = None
        
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
        
        # 说明文本
        info_label = QLabel(
            "使用说明：\n"
            "1. 填写任务信息后点击'开始标注'\n"
            "2. 输入第一个任务的指令\n"
            "3. 按 Control+Q 给下一步截图\n"
            "4. 按 Control+S 隐藏窗口\n"
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
                
        # 获取选择的软件类型
        app_type = self.app_type_combo.currentText()
        
        # 创建数据管理器，使用用户选择的存储目录
        self.data_manager = DataManager(base_dir=self.storage_dir)
        
        # 创建任务目录
        success = self.data_manager.create_task_directory("mac", app_type, app_name)
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
            hotkey_listener=self.hotkey_listener,  # 传递全局快捷键监听器
            init_window=self
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

        # 创建编辑器并从草稿恢复
        self.annotation_window = AnnotationEditor(
            data_manager=self.data_manager,
            app_name=app_name,
            task_instruction=task_instruction,
            screen_info=screen_info,
            app_type=app_type,
            hotkey_listener=self.hotkey_listener,  # macOS 全局快捷键监听器
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


def main():
    """主函数"""
    multiprocessing.freeze_support()
    print("正在启动 GUI长步骤采标工具-macOS...")

    # perm_status, perm_tip = check_and_request_all_permissions()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 先初始化全局快捷键监听器对象（不启动，等窗口显示后再启动）
    hotkey_listener = GlobalHotkeyListener()

    # if not perm_status.get('screen_recording') or not perm_status.get('accessibility'):
    #     QMessageBox.warning(
    #         None,
    #         "权限提示",
    #         f"{perm_tip}\n\n缺少必要权限可能影响截图和快捷键功能，但你仍可继续使用。"
    #     )

    print("创建主窗口...")
    window = InitTaskWindow(hotkey_listener)

    # 立即显示窗口，避免 macOS 认为应用无响应（灰色标题栏）
    print("显示窗口...")
    window.show()
    window.raise_()
    window.activateWindow()

    # 强制处理事件队列，让窗口立即渲染，防止灰色标题栏
    app.processEvents()

    # 窗口显示后延迟启动全局快捷键，减少等待时间
    QTimer.singleShot(200, hotkey_listener.start_listening)

    print("程序已启动，窗口应该已显示")
    print("如果窗口未显示，请检查 macOS 权限设置")

    # 运行应用
    exit_code = app.exec_()
    
    # 停止全局快捷键监听
    hotkey_listener.stop_listening()
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
