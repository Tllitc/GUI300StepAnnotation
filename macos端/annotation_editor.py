#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
标注编辑器模块
负责动作标注的编辑、分页显示、撤销等功能
跨平台支持：Windows / macOS
"""

import sys
import os
import math
import copy
from collections import OrderedDict
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QLineEdit,
                             QComboBox, QTextEdit, QGroupBox, QFormLayout,
                             QStackedWidget, QMessageBox, QScrollArea,
                             QFrame, QSplitter, QTabWidget, QSpinBox,
                             QShortcut, QDialog, QListWidget,
                             QListWidgetItem, QSizePolicy, QSpacerItem)
from PyQt5.QtCore import Qt, QTimer, QSize, pyqtSignal, QRect
from PyQt5.QtGui import (QPixmap, QImage, QFont, QPainter, QPen, QColor,
                         QKeySequence, QFontMetrics)

from screenshot_capture import ScreenshotCaptureWindow
from data_manager import DataManager


class StepEditorWidget(QWidget):
    """单个步骤的编辑界面"""

    # 截图预览区域尺寸变化（分栏拖拽/窗口缩放）后请求按磁盘原图重绘
    preview_resize_requested = pyqtSignal()

    def __init__(self, step_data=None, parent=None):
        super().__init__(parent)
        self.step_data = step_data or {}
        # 滚动测量相关变量
        self.scroll_references = []  # 存储参照物的Y坐标列表
        self.is_measuring_scroll = False  # 是否正在测量滚动
        # 按键组合相关变量
        self.current_keys_input = None  # 当前获得焦点的按键输入框
        # 预览重绘元数据 (filename, rect_info, selection_type)，无截图时为 None
        self.preview_meta = None
        self.init_ui()
        # 安装事件过滤器来监听键盘事件
        self.installEventFilter(self)

    def init_ui(self):
        """初始化界面：左右分栏（左：截图预览；右：动作信息，可滚动）"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.editor_splitter = QSplitter(Qt.Horizontal)

        # ===== 左栏：截图预览区域 =====
        preview_group = QGroupBox("截图预览")
        preview_group.setMinimumWidth(420)
        preview_layout = QVBoxLayout()

        self.screenshot_label = QLabel("暂无截图")
        self.screenshot_label.setAlignment(Qt.AlignCenter)
        self.screenshot_label.setMinimumSize(420, 300)
        self.screenshot_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        # 分栏拖拽时 StepEditorWidget 自身尺寸不变、只有 label 变，直接监听 label resize
        self.screenshot_label.installEventFilter(self)
        preview_layout.addWidget(self.screenshot_label)

        preview_group.setLayout(preview_layout)
        self.editor_splitter.addWidget(preview_group)

        # 动作信息表单
        form_group = QGroupBox("动作信息")
        form_layout = QFormLayout()

        # 步骤编号（只读）
        self.step_number_label = QLabel("")
        form_layout.addRow("步骤:", self.step_number_label)

        # 动作描述
        self.intent_input = QLineEdit()
        self.intent_input.setPlaceholderText("例如：左键单击网易有道翻译")
        form_layout.addRow("动作描述:", self.intent_input)

        # CoT (Chain of Thought) - 隐藏但保留字段
        self.cot_input = QTextEdit()
        self.cot_input.setPlaceholderText("为什么要这么做...")
        self.cot_input.setMaximumHeight(80)
        self.cot_input.hide()  # 隐藏CoT输入框
        cot_label = QLabel("CoT:")
        cot_label.hide()  # 隐藏标签
        form_layout.addRow(cot_label, self.cot_input)

        # 活动窗口 - 隐藏但保留字段
        self.active_window_input = QLineEdit()
        self.active_window_input.setPlaceholderText("例如：网易有道翻译、Desktop")
        self.active_window_input.hide()  # 隐藏活动窗口输入框
        active_window_label = QLabel("活动窗口:")
        active_window_label.hide()  # 隐藏标签
        form_layout.addRow(active_window_label, self.active_window_input)

        # UI 元素名称 - 隐藏但保留字段
        self.element_input = QLineEdit()
        self.element_input.setPlaceholderText("例如：输入框、按钮")
        self.element_input.hide()  # 隐藏UI元素输入框
        element_label = QLabel("UI元素:")
        element_label.hide()  # 隐藏标签
        form_layout.addRow(element_label, self.element_input)

        # 动作类型选择（中文显示，英文存储）
        self.action_type_combo = QComboBox()
        # 定义中英文映射
        self.action_type_mapping = {
            "左键单击": "left_click",
            "双击": "double_click",
            "三击": "triple_click",
            "右键单击": "right_click",
            "中键单击": "middle_click",
            "拖拽": "left_click_drag",
            "鼠标移动": "mouse_move",
            "滚动": "scroll",
            "文本输入": "type",
            "按键组合": "key",
            "等待": "wait",
            "回答用户": "answer",
            "回答并结束": "answer_terminate",
            "任务完成": "terminate",
            "打开app": "open_app",
            "打开网页": "open_url"
        }
        # 添加中文选项
        chinese_types = list(self.action_type_mapping.keys())
        self.action_type_combo.addItems(chinese_types)
        self.action_type_combo.currentTextChanged.connect(self.on_action_type_changed)
        form_layout.addRow("动作类型:", self.action_type_combo)

        # ===== 动态参数行（直接加入主表单，按动作类型显隐） =====
        # 每个动态行保存 (label_widget, field_widget)，field 统一用容器 QWidget 包裹，
        # 以保证整行（含布局内子控件）能一起 hide/show
        self.dynamic_rows = {}

        # 坐标输入（只读）- 支持单坐标和双坐标（拖拽），标签随动作语义切换
        self.coord_x_input = QLineEdit()
        self.coord_x_input.setPlaceholderText("X 坐标")
        self.coord_x_input.setReadOnly(True)  # 设置为只读
        self.coord_y_input = QLineEdit()
        self.coord_y_input.setPlaceholderText("Y 坐标")
        self.coord_y_input.setReadOnly(True)  # 设置为只读
        coord_field = QWidget()
        coord_layout = QHBoxLayout(coord_field)
        coord_layout.setContentsMargins(0, 0, 0, 0)
        coord_layout.addWidget(self.coord_x_input)
        coord_layout.addWidget(self.coord_y_input)
        self.coord_label = QLabel("坐标 [x, y]:")
        form_layout.addRow(self.coord_label, coord_field)
        self.dynamic_rows["coord"] = (self.coord_label, coord_field)

        # 拖拽终点坐标（仅用于 left_click_drag）
        self.end_coord_x_input = QLineEdit()
        self.end_coord_x_input.setPlaceholderText("终点 X 坐标")
        self.end_coord_x_input.setReadOnly(True)
        self.end_coord_y_input = QLineEdit()
        self.end_coord_y_input.setPlaceholderText("终点 Y 坐标")
        self.end_coord_y_input.setReadOnly(True)
        end_coord_field = QWidget()
        end_coord_layout = QHBoxLayout(end_coord_field)
        end_coord_layout.setContentsMargins(0, 0, 0, 0)
        end_coord_layout.addWidget(self.end_coord_x_input)
        end_coord_layout.addWidget(self.end_coord_y_input)
        self.end_coord_label = QLabel("终点坐标 [x, y]:")
        form_layout.addRow(self.end_coord_label, end_coord_field)
        self.dynamic_rows["end_coord"] = (self.end_coord_label, end_coord_field)

        # 文本输入（用于 type/open_app/open_url/answer，标签随动作语义切换）
        # QTextEdit 默认垂直 Expanding，会作为 QFormLayout 中唯一可扩张行吞掉全部
        # 剩余空间，把上方固定行整体推到表单底部；改为固定高度避免沉底
        self.text_input = QTextEdit()
        self.text_input.setFixedHeight(80)
        self.text_input.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.text_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.text_label = QLabel("输入文本:")
        form_layout.addRow(self.text_label, self.text_input)
        self.dynamic_rows["text"] = (self.text_label, self.text_input)

        # 按键输入（用于 keys）- 四个文本框，中间用"+"连接
        self.keys_input_1 = QLineEdit()
        self.keys_input_1.setPlaceholderText("按键1")
        self.keys_input_1.setReadOnly(True)

        self.keys_input_2 = QLineEdit()
        self.keys_input_2.setPlaceholderText("按键2")
        self.keys_input_2.setReadOnly(True)

        self.keys_input_3 = QLineEdit()
        self.keys_input_3.setPlaceholderText("按键3")
        self.keys_input_3.setReadOnly(True)

        self.keys_input_4 = QLineEdit()
        self.keys_input_4.setPlaceholderText("按键4")
        self.keys_input_4.setReadOnly(True)

        # 创建水平布局容器，包含四个文本框和三个"+"符号
        keys_field = QWidget()
        keys_layout = QHBoxLayout(keys_field)
        keys_layout.setContentsMargins(0, 0, 0, 0)
        keys_layout.addWidget(self.keys_input_1)
        keys_layout.addWidget(QLabel("+"))
        keys_layout.addWidget(self.keys_input_2)
        keys_layout.addWidget(QLabel("+"))
        keys_layout.addWidget(self.keys_input_3)
        keys_layout.addWidget(QLabel("+"))
        keys_layout.addWidget(self.keys_input_4)

        self.keys_label = QLabel("按键组合（点输入框后按实际按键）:")
        form_layout.addRow(self.keys_label, keys_field)
        self.dynamic_rows["keys"] = (self.keys_label, keys_field)

        # 为四个按键输入框安装事件过滤器
        self.keys_input_1.installEventFilter(self)
        self.keys_input_2.installEventFilter(self)
        self.keys_input_3.installEventFilter(self)
        self.keys_input_4.installEventFilter(self)

        # 滚动像素（用于 scroll）
        self.pixels_input = QLineEdit()
        self.pixels_input.setPlaceholderText("正值向上，负值向下")
        self.pixels_input.setReadOnly(True)  # 设置为只读，通过按钮自动计算

        # 滚动测量按钮
        self.scroll_measure_btn = QPushButton("开始测量滚动距离")
        self.scroll_measure_btn.clicked.connect(self.start_scroll_measurement)
        self.scroll_measure_btn.setStyleSheet("QPushButton { background-color: #FF9800; color: white; }")

        # 完成测量按钮
        self.scroll_finish_btn = QPushButton("完成测量")
        self.scroll_finish_btn.clicked.connect(self.finish_scroll_measurement)
        self.scroll_finish_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
        self.scroll_finish_btn.hide()  # 初始隐藏

        scroll_field = QWidget()
        scroll_layout = QHBoxLayout(scroll_field)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.addWidget(self.pixels_input)
        scroll_layout.addWidget(self.scroll_measure_btn)
        scroll_layout.addWidget(self.scroll_finish_btn)
        self.scroll_label = QLabel("滚动像素:")
        form_layout.addRow(self.scroll_label, scroll_field)
        self.dynamic_rows["scroll"] = (self.scroll_label, scroll_field)

        # 等待时间（用于 wait）
        self.wait_time_input = QLineEdit()
        self.wait_time_input.setPlaceholderText("单位：秒")
        self.wait_label = QLabel("等待时间（秒）:")
        form_layout.addRow(self.wait_label, self.wait_time_input)
        self.dynamic_rows["wait"] = (self.wait_label, self.wait_time_input)

        # terminate 无参数占位提示（整行占位）
        self.no_param_label = QLabel("该动作无需填写参数")
        self.no_param_label.setStyleSheet("color: #888; font-style: italic;")
        form_layout.addRow(self.no_param_label)
        self.dynamic_rows["no_param"] = (self.no_param_label, None)

        # 终止状态（用于 terminate）- 隐藏但保留字段，不参与动态行显隐
        self.status_combo = QComboBox()
        self.status_combo.addItems(["success", "failure"])
        self.status_combo.hide()  # 隐藏状态选择框
        status_label = QLabel("状态:")
        status_label.hide()  # 隐藏标签
        form_layout.addRow(status_label, self.status_combo)

        # 末尾垂直弹簧：吸收表单多余高度，保证各动作行始终顶对齐
        form_layout.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum,
                                       QSizePolicy.Expanding))

        form_group.setLayout(form_layout)

        # ===== 右栏：动作信息外套滚动区域 =====
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        form_scroll.setMinimumWidth(300)
        form_scroll.setWidget(form_group)
        self.editor_splitter.addWidget(form_scroll)

        # 初始比例约 65:35，可拖拽调整；stretch 保证窗口缩放时同比变化
        self.editor_splitter.setSizes([740, 400])
        self.editor_splitter.setStretchFactor(0, 3)
        self.editor_splitter.setStretchFactor(1, 2)
        layout.addWidget(self.editor_splitter)

        # 预览重绘防抖定时器：分栏拖拽/窗口 resize 停止 250ms 后发信号请求磁盘重建
        self.preview_resize_timer = QTimer(self)
        self.preview_resize_timer.setSingleShot(True)
        self.preview_resize_timer.setInterval(250)
        self.preview_resize_timer.timeout.connect(self.preview_resize_requested.emit)

        # 加载已有数据
        if self.step_data:
            self.load_data()

        # 初始隐藏不相关的参数
        self.on_action_type_changed(self.action_type_combo.currentText())

    def eventFilter(self, obj, event):
        """事件过滤器，用于捕获键盘事件和焦点事件"""
        from PyQt5.QtCore import QEvent

        # 截图预览区尺寸变化（分栏拖拽）：防抖请求按磁盘原图重绘
        if event.type() == QEvent.Resize and obj is self.screenshot_label:
            if self.preview_meta is not None and self.isVisible():
                self.preview_resize_timer.start()

        # 处理焦点进入事件
        if event.type() == QEvent.FocusIn:
            # 如果是按键输入框获得焦点
            if obj in [self.keys_input_1, self.keys_input_2, self.keys_input_3, self.keys_input_4]:
                self.current_keys_input = obj
                return False  # 让焦点事件正常处理

        # 只处理按键按下事件
        if event.type() == QEvent.KeyPress:
            # 如果当前有焦点的按键输入框
            if self.current_keys_input is not None and obj == self.current_keys_input:
                # 获取按下的键（mac 版传入整个 event，用于物理键位与 text() 符号兜底）
                key_name = self.get_key_name(event)

                if key_name:
                    # 将键名填入当前焦点的文本框
                    self.current_keys_input.setText(key_name.lower())
                    # 返回True表示事件已处理，不再传递
                    return True

        # 其他事件交给父类处理
        return super().eventFilter(obj, event)

    def get_key_name(self, event):
        """将 Qt 按键事件转换为键名（macOS 上按物理键位命名，导出 pyautogui 风格全称）"""
        from PyQt5.QtCore import Qt
        key = event.key()

        # macOS 上 Qt 的修饰键逻辑位与物理键位相反：
        # 物理 Command ⌘ 报为 Qt.Control，物理 Control ⌃ 报为 Qt.Meta，物理 Option ⌥ 报为 Qt.Alt
        if sys.platform == 'darwin':
            modifier_map = {
                Qt.Key_Control: "command",   # 物理 Command ⌘
                Qt.Key_Meta: "control",      # 物理 Control ⌃
                Qt.Key_Alt: "option",        # 物理 Option ⌥
                Qt.Key_Shift: "shift",
            }
        else:
            modifier_map = {
                Qt.Key_Meta: "meta",
                Qt.Key_Control: "ctrl",
                Qt.Key_Alt: "alt",
                Qt.Key_Shift: "shift",
            }
        if key in modifier_map:
            return modifier_map[key]

        # 特殊键映射
        key_map = {
            Qt.Key_Enter: "enter",
            Qt.Key_Return: "enter",
            Qt.Key_Tab: "tab",
            Qt.Key_Backspace: "backspace",
            Qt.Key_Delete: "delete",
            Qt.Key_Escape: "escape",
            Qt.Key_Space: "space",
            Qt.Key_Up: "up",
            Qt.Key_Down: "down",
            Qt.Key_Left: "left",
            Qt.Key_Right: "right",
            Qt.Key_Home: "home",
            Qt.Key_End: "end",
            Qt.Key_PageUp: "pageup",
            Qt.Key_PageDown: "pagedown",
            Qt.Key_Insert: "insert",
        }

        if key in key_map:
            return key_map[key]

        # 字母和数字键
        if Qt.Key_A <= key <= Qt.Key_Z:
            return chr(key).lower()
        elif Qt.Key_0 <= key <= Qt.Key_9:
            return chr(key)

        # F1-F12功能键
        if Qt.Key_F1 <= key <= Qt.Key_F12:
            return f"f{key - Qt.Key_F1 + 1}"

        # 其余可打印符号（如 -、=、[、] 等）以 event.text() 兜底
        text = event.text()
        if len(text) == 1 and text.isprintable() and 33 <= ord(text) <= 126:
            return text

        return None

    def start_scroll_measurement(self):
        if self.is_measuring_scroll:
            self.start_reference_capture()
            return

        current_y = None
        try:
            y_text = self.coord_y_input.text().strip()
            if y_text:
                current_y = int(y_text)
        except:
            pass

        if current_y is None:
            QMessageBox.warning(self, "警告", "请先在屏幕上选择一个参照物并拉框！")
            return

        self.scroll_references = [current_y]
        self.is_measuring_scroll = True
        self.scroll_measure_btn.setText("继续测量")
        self.scroll_measure_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; }")
        self.scroll_finish_btn.show()

        QMessageBox.information(self, "滚动测量",
            f"已获取第一个参照物Y坐标: {current_y}\n\n" +
            "请在屏幕上滚动后，选择同一个参照物并拉框，\n" +
            "系统将自动计算滚动像素。\n\n" +
            "您可以多次选择来累积滚动距离。")

        self.start_reference_capture()

    def start_reference_capture(self):
        """启动参照物捕获窗口"""
        # 先将窗口设为完全透明（避免 hide() 动画过程被截图捕捉），再隐藏
        main_window = self.window()
        if main_window:
            main_window.setWindowOpacity(0.0)
            main_window.hide()

        # 延迟确保窗口完全隐藏后再截图
        QTimer.singleShot(350, self.show_reference_capture_window)

    def show_reference_capture_window(self):
        """显示参照物捕获窗口"""
        from screenshot_capture import ScreenshotCaptureWindow
        self.reference_capture_window = ScreenshotCaptureWindow()
        self.reference_capture_window.capture_completed.connect(self.on_reference_captured)
        self.reference_capture_window.show()

    def on_reference_captured(self, original_pixmap, marked_pixmap, rect_info, selection_type):
        """参照物捕获完成回调"""
        # 检查是否被取消
        if selection_type == "cancelled":
            # 用户取消了截图，重新显示主窗口
            main_window = self.window()
            if main_window:
                main_window.setWindowOpacity(1.0)
                main_window.show()
                main_window.activateWindow()
            return

        # 获取参照物的中心Y坐标（兼容单框和双框 rect_info）
        y_center = None
        if isinstance(rect_info, tuple) and len(rect_info) >= 2:
            if isinstance(rect_info[0], tuple):
                # 双框模式 (dual-rect): 取第一个框的中心
                first_rect = rect_info[0]
                y_center = first_rect[1] + first_rect[3] // 2
            else:
                # 单框模式: rect_info = (x, y, w, h)
                y_center = rect_info[1] + rect_info[3] // 2

        if y_center is not None:
            self.scroll_references.append(y_center)

            # 计算滚动距离（至少有两个参照物）
            if len(self.scroll_references) >= 2:
                # 计算相邻参照物之间的高度差并累加
                total_pixels = 0
                for i in range(1, len(self.scroll_references)):
                    # 向上滚动时内容下移，参照物Y坐标增加，所以用后一个减前一个
                    diff = self.scroll_references[i] - self.scroll_references[i-1]
                    total_pixels += diff

                # 更新像素输入框
                self.pixels_input.setText(str(total_pixels))

                # 显示完成测量按钮
                self.scroll_finish_btn.show()

        # 先恢复主窗口（在 ScreenshotCaptureWindow 关闭前），再延迟弹出提示
        main_window = self.window()
        if main_window:
            main_window.setWindowOpacity(1.0)
            main_window.show()
            main_window.activateWindow()

        # 延迟弹出 QMessageBox，确保 ScreenshotCaptureWindow 已完全关闭
        if y_center is not None and len(self.scroll_references) >= 2:
            total_pixels = int(self.pixels_input.text() or "0")
            ref_count = len(self.scroll_references)
            QTimer.singleShot(200, lambda: QMessageBox.information(
                self, "滚动测量",
                f"已选择 {ref_count} 个参照物\n"
                f"当前累计滚动像素: {total_pixels}\n\n"
                "点击'继续测量'按钮可以继续添加参照物，\n"
                "或点击'完成测量'结束测量。"
            ))

    def finish_scroll_measurement(self):
        """完成滚动测量"""
        if len(self.scroll_references) < 2:
            QMessageBox.warning(self, "警告", "至少需要选择两个参照物才能计算滚动距离！")
            return

        # 保存参照物数量用于显示
        ref_count = len(self.scroll_references)

        self.is_measuring_scroll = False
        self.scroll_measure_btn.setText("开始测量滚动距离")
        self.scroll_measure_btn.setStyleSheet("QPushButton { background-color: #FF9800; color: white; }")
        self.scroll_finish_btn.hide()  # 隐藏完成测量按钮

        # 计算最终的滚动像素
        total_pixels = 0
        for i in range(1, len(self.scroll_references)):
            diff = self.scroll_references[i] - self.scroll_references[i-1]
            total_pixels += diff

        self.pixels_input.setText(str(total_pixels))

        # 清空参照物列表，但保留pixels值
        self.scroll_references = []

        QMessageBox.information(self, "测量完成",
            f"滚动测量完成！\n" +
            f"总共选择了 {ref_count} 个参照物\n" +
            f"最终滚动像素: {total_pixels}")

    # 动作类型 → 可见动态行 / 语义标签文案 的显式映射
    ACTION_PARAM_LAYOUT = {
        "left_click":      (["coord"], {"coord": "坐标 [x, y]:"}),
        "double_click":    (["coord"], {"coord": "坐标 [x, y]:"}),
        "triple_click":    (["coord"], {"coord": "坐标 [x, y]:"}),
        "right_click":     (["coord"], {"coord": "坐标 [x, y]:"}),
        "middle_click":    (["coord"], {"coord": "坐标 [x, y]:"}),
        "mouse_move":      (["coord"], {"coord": "坐标 [x, y]:"}),
        "left_click_drag": (["coord", "end_coord"], {"coord": "起点坐标 [x, y]:"}),
        "scroll":          (["coord", "scroll"], {"coord": "坐标 [x, y]:"}),
        "type":            (["text"], {"text": "输入文本:"}),
        "open_app":        (["text"], {"text": "应用名称:"}),
        "open_url":        (["text"], {"text": "网址 URL:"}),
        "answer":          (["text"], {"text": "回答内容:"}),
        "answer_terminate":(["text"], {"text": "回答内容:"}),
        "key":             (["keys"], {}),
        "wait":            (["wait"], {}),
        "terminate":       (["no_param"], {}),
    }

    def _set_row_visible(self, row_key, visible):
        """显示/隐藏一条动态参数行（label + field 整体）"""
        label, field = self.dynamic_rows[row_key]
        label.setVisible(visible)
        if field is not None:
            field.setVisible(visible)

    def on_action_type_changed(self, action_type_chinese):
        """根据动作类型只显示与该动作相关的参数行"""
        # 将中文转换为英文
        action_type = self.action_type_mapping.get(action_type_chinese, action_type_chinese)

        # 先隐藏全部动态参数行
        for row_key in self.dynamic_rows:
            self._set_row_visible(row_key, False)

        # 恢复动态标签默认文案（映射中再按需覆盖）
        self.coord_label.setText("坐标 [x, y]:")
        self.text_label.setText("输入文本:")

        visible_rows, label_texts = self.ACTION_PARAM_LAYOUT.get(
            action_type, (["coord"], {"coord": "坐标 [x, y]:"})
        )
        for row_key in visible_rows:
            self._set_row_visible(row_key, True)
        for row_key, text in label_texts.items():
            label, _ = self.dynamic_rows[row_key]
            label.setText(text)

        # 滚动测量按钮仅 scroll 动作可见；finish 按钮仅测量中且参照物≥2 时可见
        if action_type == "scroll":
            self.scroll_measure_btn.show()
            if self.is_measuring_scroll and len(self.scroll_references) >= 2:
                self.scroll_finish_btn.show()
            else:
                self.scroll_finish_btn.hide()
        else:
            self.scroll_measure_btn.hide()
            self.scroll_finish_btn.hide()

    def set_screenshot(self, pixmap):
        """设置截图预览"""
        if pixmap and not pixmap.isNull():
            # 缩放图片以适应标签
            scaled_pixmap = pixmap.scaled(
                self.screenshot_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.screenshot_label.setPixmap(scaled_pixmap)
        else:
            self.screenshot_label.setText("暂无截图")

    def set_preview_meta(self, filename, rect_info, selection_type):
        """记录当前预览对应的磁盘截图信息，供 resize 后从磁盘重建"""
        self.preview_meta = (filename, rect_info, selection_type)

    def resizeEvent(self, event):
        """分栏/窗口尺寸变化后，防抖请求按磁盘原图重绘预览（仅当前可见页生效）"""
        super().resizeEvent(event)
        if self.preview_meta is not None and self.isVisible():
            self.preview_resize_timer.start()

    def set_step_number(self, number):
        """设置步骤编号"""
        self.step_number_label.setText(str(number))

    def load_data(self):
        """加载已有的步骤数据"""
        if not self.step_data:
            return

        # 加载基本信息
        self.intent_input.setText(self.step_data.get("intent", ""))
        self.cot_input.setPlainText(self.step_data.get("CoT", ""))

        observation = self.step_data.get("observation", {})
        self.active_window_input.setText(observation.get("active_window", ""))

        # 加载动作信息
        actions = self.step_data.get("actions", [])
        if actions:
            action = actions[0]  # 简化处理，假设每个步骤只有一个动作
            action_type = action.get("action", "left_click")

            # 找到对应的中文显示
            index = self.action_type_combo.findText(
                next((k for k, v in self.action_type_mapping.items() if v == action_type), action_type)
            )
            if index >= 0:
                self.action_type_combo.setCurrentIndex(index)

            # 加载参数（起点坐标 start_coordinate / 终点坐标 coordinate）
            if "start_coordinate" in action:
                start = action["start_coordinate"]
                if isinstance(start, list) and len(start) >= 2:
                    self.coord_x_input.setText(str(start[0]))
                    self.coord_y_input.setText(str(start[1]))
                if "coordinate" in action:
                    end = action["coordinate"]
                    if isinstance(end, list) and len(end) >= 2:
                        self.end_coord_x_input.setText(str(end[0]))
                        self.end_coord_y_input.setText(str(end[1]))
            elif "coordinate" in action:
                coord = action["coordinate"]
                if isinstance(coord, list) and len(coord) >= 2:
                    self.coord_x_input.setText(str(coord[0]))
                    self.coord_y_input.setText(str(coord[1]))

            if "text" in action:
                self.text_input.setPlainText(action["text"])

            # 加载按键组合
            if "keys" in action:
                keys = action["keys"]
                if isinstance(keys, list):
                    keys_inputs = [self.keys_input_1, self.keys_input_2, self.keys_input_3, self.keys_input_4]
                    for i, key in enumerate(keys):
                        if i < len(keys_inputs):
                            keys_inputs[i].setText(str(key))

            if "element" in action:
                self.element_input.setText(action["element"])

            # 加载滚动像素
            if "pixels" in action:
                self.pixels_input.setText(str(action["pixels"]))

    def get_data(self):
        """获取当前编辑的数据"""
        # 获取中文显示文本
        action_type_chinese = self.action_type_combo.currentText()
        # 转换为英文字段值
        action_type = self.action_type_mapping.get(action_type_chinese, action_type_chinese)

        # 构建动作对象
        action = {"action": action_type}

        # 添加坐标（open_app、open_url、terminate、answer、wait、key 不需要坐标）
        if action_type not in ["open_app", "open_url", "terminate", "answer", "wait", "key"]:
            try:
                x = int(self.coord_x_input.text()) if self.coord_x_input.text() else 0
                y = int(self.coord_y_input.text()) if self.coord_y_input.text() else 0

                # 拖拽：起点坐标 + 终点坐标
                if action_type == "left_click_drag":
                    end_x = int(self.end_coord_x_input.text()) if self.end_coord_x_input.text() else x
                    end_y = int(self.end_coord_y_input.text()) if self.end_coord_y_input.text() else y
                    action["start_coordinate"] = [x, y]
                    action["coordinate"] = [end_x, end_y]
                else:
                    # 单坐标格式：[x, y]
                    action["coordinate"] = [x, y]
            except:
                if action_type == "left_click_drag":
                    action["start_coordinate"] = [0, 0]
                    action["coordinate"] = [0, 0]
                else:
                    action["coordinate"] = [0, 0]

        # 添加文本
        text = self.text_input.toPlainText().strip()
        if text and action_type in ["type", "answer", "answer_terminate", "open_app", "open_url"]:
            action["text"] = text

        # 添加按键组合（用于 key 动作）
        if action_type == "key":
            keys_list = []
            for keys_input in [self.keys_input_1, self.keys_input_2, self.keys_input_3, self.keys_input_4]:
                key_text = keys_input.text().strip()
                if key_text:
                    keys_list.append(key_text)
            if keys_list:
                action["keys"] = keys_list

        # 添加元素名称（所有动作都包含element字段，即使为空）
        element = self.element_input.text().strip()
        action["element"] = element

        # 特殊处理 wait 动作 - 添加 time 字段
        if action_type == "wait":
            time_text = self.wait_time_input.text().strip()
            if time_text:
                try:
                    action["time"] = float(time_text)
                except ValueError:
                    action["time"] = 0
            else:
                action["time"] = 0

        # 特殊处理 scroll 动作 - 添加 pixels 字段
        if action_type == "scroll":
            pixels_text = self.pixels_input.text().strip()
            if pixels_text:
                try:
                    action["pixels"] = int(pixels_text)
                except ValueError:
                    action["pixels"] = 0
            else:
                action["pixels"] = 0

        if action_type == "answer_terminate":
            action["action"] = "answer"
            action["status"] = "success"

        # 特殊处理 terminate 动作
        if action_type == "terminate":
            action["status"] = "success"  # 默认 success
            # element 保持为空字符串

        # 构建完整步骤数据
        if action_type in ["terminate", "answer_terminate"]:
            # 结束类动作使用固定意图
            data = {
                "intent": "任务已完成" if action_type == "terminate" else self.intent_input.text().strip(),
                "CoT": self.cot_input.toPlainText().strip(),
                "observation": {
                    "screenshot": "",  # 稍后由外部设置
                    "active_window": self.active_window_input.text().strip(),
                    "ui_tree_segment": ""
                },
                "actions": [action]
            }
        else:
            # 其他动作包含 intent 字段
            data = {
                "intent": self.intent_input.text().strip(),
                "CoT": self.cot_input.toPlainText().strip(),
                "observation": {
                    "screenshot": "",  # 稍后由外部设置
                    "active_window": self.active_window_input.text().strip(),
                    "ui_tree_segment": ""
                },
                "actions": [action]
            }

        return data


class StepListItemWidget(QFrame):
    """侧栏中的单个步骤条目：序号 + 磁盘缩略图 + 动作类型 + 完成状态，点击即跳转"""

    clicked = pyqtSignal(int)

    # 缩略图固定等比尺寸（16:9，约 200 宽）
    THUMB_SIZE = QSize(200, 112)

    def __init__(self, step_index, parent=None):
        super().__init__(parent)
        self.step_index = step_index
        self.thumb_loaded = False  # 是否已尝试加载过缩略图（避免重复读盘）
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self._init_ui()
        self.set_current(False)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)

        # 第一行：序号 + 状态
        header_layout = QHBoxLayout()
        self.number_label = QLabel(f"第 {self.step_index + 1} 步")
        font = QFont()
        font.setBold(True)
        self.number_label.setFont(font)
        header_layout.addWidget(self.number_label)
        header_layout.addStretch()
        # 必填项缺失标记（红色 ⚠ 缺项，tooltip 列出具体缺失原因）
        self.missing_label = QLabel("")
        self.missing_label.setStyleSheet("color: #E53935; font-weight: bold;")
        self.missing_label.hide()
        header_layout.addWidget(self.missing_label)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #FF9800;")
        header_layout.addWidget(self.status_label)
        layout.addLayout(header_layout)

        # 缩略图：仅持有小尺寸 QPixmap，绝不持有全屏图
        self.thumb_label = QLabel("缩略图加载中…")
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setFixedSize(self.THUMB_SIZE)
        self.thumb_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ddd;")
        layout.addWidget(self.thumb_label, 0, Qt.AlignHCenter)

        # 动作类型（中文/英文）
        self.action_label = QLabel("动作类型: -")
        self.action_label.setWordWrap(True)
        self.action_label.setStyleSheet("color: #333;")
        layout.addWidget(self.action_label)

    def set_index(self, step_index):
        """撤销/重建后更新条目序号"""
        self.step_index = step_index
        self.number_label.setText(f"第 {step_index + 1} 步")

    def set_current(self, is_current):
        """当前步骤条目高亮"""
        if is_current:
            self.setStyleSheet("StepListItemWidget { background-color: #E3F2FD; "
                               "border: 2px solid #2196F3; border-radius: 4px; }")
        else:
            self.setStyleSheet("StepListItemWidget { background-color: #ffffff; "
                               "border: 1px solid #e0e0e0; border-radius: 4px; }")

    def set_status(self, confirmed):
        """confirmed=True 已完成（绿色）；False 编辑中/未确认（橙色）"""
        if confirmed:
            self.status_label.setText("✓ 已完成")
            self.status_label.setStyleSheet("color: #4CAF50;")
        else:
            self.status_label.setText("● 编辑中")
            self.status_label.setStyleSheet("color: #FF9800;")

    def set_action_text(self, text):
        self.action_label.setText(text)

    def set_missing(self, missing_list):
        """设置必填项缺失标记：missing_list 非空时红色显示“⚠ 缺项”，
        tooltip 逐条列出缺失原因；为空（或 None）时隐藏标记"""
        if missing_list:
            self.missing_label.setText("⚠ 缺项")
            self.missing_label.setToolTip("；".join(missing_list))
            self.missing_label.show()
        else:
            self.missing_label.setText("")
            self.missing_label.hide()
            self.missing_label.setToolTip("")

    def set_thumbnail(self, pixmap):
        """设置小尺寸缩略图"""
        if pixmap is not None and not pixmap.isNull():
            self.thumb_label.setPixmap(pixmap)
        else:
            self.thumb_label.setText("暂无截图")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.step_index)
        super().mousePressEvent(event)


class SideBarWidget(QWidget):
    """左侧栏：顶部进度看板 + 可滚动步骤列表 + 底部跳转区"""

    THUMB_CACHE_LIMIT = 64  # 缩略图 LRU 缓存上限

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor  # 持有 AnnotationEditor 引用以读取步骤数据
        self.item_widgets = []  # StepListItemWidget 列表，与步骤下标一一对应
        # 缩略图 LRU 缓存：key=(filename, rect_info, selection_type) → 小尺寸 QPixmap
        self._thumb_cache = OrderedDict()
        # 懒加载队列：等待加载缩略图的步骤下标
        self._thumb_queue = []
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._load_thumb_batch)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # ===== 进度看板 =====
        dashboard_group = QGroupBox("进度看板")
        dashboard_layout = QVBoxLayout()
        dashboard_layout.setSpacing(4)

        task_title = QLabel("任务指令:")
        font = QFont()
        font.setBold(True)
        task_title.setFont(font)
        dashboard_layout.addWidget(task_title)

        self.task_label = QLabel("")
        self.task_label.setWordWrap(False)
        self.task_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dashboard_layout.addWidget(self.task_label)

        self.count_label = QLabel("总步数: 0")
        dashboard_layout.addWidget(self.count_label)

        # 必填项待完善计数（有缺失项的步骤数）
        self.missing_count_label = QLabel("待完善: 0")
        self.missing_count_label.setStyleSheet("color: #E53935; font-weight: bold;")
        dashboard_layout.addWidget(self.missing_count_label)

        self.action_stats_label = QLabel("动作分布: -")
        self.action_stats_label.setWordWrap(True)
        dashboard_layout.addWidget(self.action_stats_label)

        self.draft_time_label = QLabel("自动保存: -")
        dashboard_layout.addWidget(self.draft_time_label)

        dashboard_group.setLayout(dashboard_layout)
        layout.addWidget(dashboard_group)

        # ===== 可滚动步骤列表 =====
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(2, 2, 2, 2)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch()
        self.scroll_area.setWidget(self.list_container)
        layout.addWidget(self.scroll_area, 1)

        # ===== 跳转到第 N 步 =====
        jump_group = QGroupBox("步骤跳转")
        jump_layout = QHBoxLayout()
        jump_layout.addWidget(QLabel("第"))
        self.jump_spin = QSpinBox()
        self.jump_spin.setMinimum(1)
        self.jump_spin.setMaximum(1)
        jump_layout.addWidget(self.jump_spin)
        jump_layout.addWidget(QLabel("步"))
        self.jump_btn = QPushButton("跳转")
        self.jump_btn.clicked.connect(self._on_jump_clicked)
        jump_layout.addWidget(self.jump_btn)
        jump_group.setLayout(jump_layout)
        layout.addWidget(jump_group)

    # ---------- 缩略图 LRU 缓存 ----------

    def _cache_key(self, step):
        return (step.get("screenshot_filename"),
                step.get("rect_info"),
                step.get("selection_type"))

    def _get_cached_thumb(self, key):
        """命中时移动到 LRU 末尾并返回缩略图"""
        if key in self._thumb_cache:
            self._thumb_cache.move_to_end(key)
            return self._thumb_cache[key]
        return None

    def _put_cached_thumb(self, key, pixmap):
        self._thumb_cache[key] = pixmap
        self._thumb_cache.move_to_end(key)
        while len(self._thumb_cache) > self.THUMB_CACHE_LIMIT:
            self._thumb_cache.popitem(last=False)  # 淘汰最久未使用

    def invalidate_thumb(self, index):
        """指定步骤的截图发生变化（重新截图）时失效其缓存"""
        if 0 <= index < len(self.editor.steps):
            key = self._cache_key(self.editor.steps[index])
            self._thumb_cache.pop(key, None)

    def remove_thumb_cache_by_filename(self, filename):
        """删除步骤后清理该截图文件名对应的全部缩略图缓存条目（key 含文件名）"""
        if not filename:
            return
        stale_keys = [key for key in self._thumb_cache if key and key[0] == filename]
        for key in stale_keys:
            self._thumb_cache.pop(key, None)

    def request_thumb(self, index, high_priority=False):
        """请求加载某步骤缩略图：命中立即设置，否则进入懒加载队列分批读盘"""
        if index < 0 or index >= len(self.item_widgets):
            return
        item = self.item_widgets[index]
        if item.thumb_loaded:
            return
        if index < 0 or index >= len(self.editor.steps):
            return
        step = self.editor.steps[index]
        key = self._cache_key(step)
        cached = self._get_cached_thumb(key)
        if cached is not None:
            item.set_thumbnail(cached)
            item.thumb_loaded = True
            return
        if index not in self._thumb_queue:
            if high_priority:
                self._thumb_queue.insert(0, index)
            else:
                self._thumb_queue.append(index)
        self._thumb_timer.start(10)

    def _load_thumb_batch(self):
        """事件循环空闲时每批加载 20 张缩略图，300 步场景下不一次性读盘"""
        if not self._thumb_queue:
            return
        batch = self._thumb_queue[:20]
        self._thumb_queue = self._thumb_queue[20:]
        for index in batch:
            if index < 0 or index >= len(self.item_widgets) \
                    or index >= len(self.editor.steps):
                continue
            item = self.item_widgets[index]
            if item.thumb_loaded:
                continue
            step = self.editor.steps[index]
            key = self._cache_key(step)
            cached = self._get_cached_thumb(key)
            if cached is None:
                # 从磁盘加载原图、画框后缩放到小尺寸，原图随即释放
                cached = self.editor.build_marked_preview(
                    step.get("screenshot_filename"),
                    step.get("rect_info"),
                    step.get("selection_type"),
                    StepListItemWidget.THUMB_SIZE
                )
                if cached is not None:
                    self._put_cached_thumb(key, cached)
            item.set_thumbnail(cached)
            item.thumb_loaded = True
        if self._thumb_queue:
            self._thumb_timer.start(10)

    def ensure_current_thumb(self, index):
        """当前步骤缩略图优先加载"""
        if 0 <= index < len(self.item_widgets):
            self.request_thumb(index, high_priority=True)

    # ---------- 条目构建 / 刷新 ----------

    def _create_item(self, index):
        item = StepListItemWidget(index)
        item.clicked.connect(self.editor.jump_to_step)
        self.list_layout.insertWidget(index, item)
        return item

    def rebuild_items(self):
        """步骤集合变化（新增/撤销/重置/恢复）后全量重建条目"""
        # 移除旧条目
        for item in self.item_widgets:
            self.list_layout.removeWidget(item)
            item.setParent(None)
            item.deleteLater()
        self.item_widgets = []
        self._thumb_queue = []
        self._thumb_timer.stop()

        total = len(self.editor.steps)
        for i in range(total):
            item = self._create_item(i)
            self.item_widgets.append(item)
            self.refresh_step_item(i)
        self.jump_spin.setMaximum(max(total, 1))
        # 所有缩略图进入懒加载队列（当前步骤插队优先）
        if total:
            self._thumb_queue = list(range(total))
            current = self.editor.current_step_index
            if 0 <= current < total:
                self._thumb_queue.remove(current)
                self._thumb_queue.insert(0, current)
            self._thumb_timer.start(10)
        self.refresh_dashboard()

    def refresh_step_item(self, index):
        """仅刷新单个条目（序号/状态/动作类型/高亮），不重建列表"""
        if index < 0 or index >= len(self.item_widgets):
            return
        item = self.item_widgets[index]
        item.set_index(index)

        # 已点过确认（confirmed 运行时标志，兼容仅有 data 快照的情况）算已完成
        step = self.editor.steps[index]
        confirmed = step.get("confirmed", "data" in step)
        item.set_status(confirmed)
        item.set_current(index == self.editor.current_step_index)

        # 动作类型中文名/英文：优先读已保存快照，当前步实时 get_data
        action_en = "-"
        data = step.get("data")
        if data is None and index == self.editor.current_step_index:
            try:
                data = step["editor"].get_data()
            except Exception:
                data = None
        if data:
            actions = data.get("actions", [])
            if actions:
                action_en = actions[0].get("action", "-")
        mapping = step["editor"].action_type_mapping
        action_cn = next((k for k, v in mapping.items() if v == action_en), "")
        item.set_action_text(f"动作: {action_cn} ({action_en})" if action_cn
                             else f"动作: {action_en}")

        # 必填项缺失标记：取缓存（revalidate_all/revalidate_current 维护），
        # 缓存缺失时实时校验一次兜底
        missing = self.editor.get_cached_missing(index)
        if missing is None:
            missing = self.editor.validate_step_at(index)
        item.set_missing(missing)

    def refresh_highlight(self):
        """切换步骤时只更新高亮，避免遍历全部条目"""
        for i, item in enumerate(self.item_widgets):
            item.set_current(i == self.editor.current_step_index)

    def refresh_dashboard(self):
        """刷新进度看板：指令、步数统计、动作分布、自动保存时间"""
        # 任务指令超长截断，tooltip 保留全文
        instruction = self.editor.task_instruction or ""
        self.task_label.setToolTip(instruction)
        metrics = QFontMetrics(self.task_label.font())
        elided = metrics.elidedText(instruction, Qt.ElideRight, self.width() - 30)
        self.task_label.setText(elided)

        total = len(self.editor.steps)
        finished = sum(1 for s in self.editor.steps
                       if s.get("confirmed", "data" in s))
        unfinished = total - finished
        self.count_label.setText(f"总步数: {total}    已完成: {finished}    未完成: {unfinished}")

        # 待完善计数：以缓存为主，缓存长度与步数不一致时触发一次全量重算
        if len(self.editor._missing_cache) != total:
            self.editor.revalidate_all_missing()
        missing_count = sum(1 for i in range(total)
                            if self.editor.get_cached_missing(i))
        self.missing_count_label.setText(f"待完善: {missing_count}")

        # 动作类型分布（已保存步骤读快照，未保存步骤实时取编辑器数据）
        action_counts = {}
        for i, step in enumerate(self.editor.steps):
            data = step.get("data")
            if data is None:
                try:
                    data = step["editor"].get_data()
                except Exception:
                    data = None
            if data:
                for action in data.get("actions", []):
                    name = action.get("action", "unknown")
                    action_counts[name] = action_counts.get(name, 0) + 1
        if action_counts:
            ordered = sorted(action_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            stats_text = "  ".join(f"{name}:{count}" for name, count in ordered)
        else:
            stats_text = "-"
        self.action_stats_label.setText(f"动作分布: {stats_text}")

        self.jump_spin.setMaximum(max(total, 1))

    def set_draft_saving(self):
        self.draft_time_label.setText("自动保存: 保存中…")

    def set_draft_saved(self):
        self.draft_time_label.setText("自动保存: 已保存 " + datetime.now().strftime("%H:%M:%S"))

    def resizeEvent(self, event):
        """侧栏宽度变化时重新截断任务指令"""
        super().resizeEvent(event)
        instruction = self.editor.task_instruction or ""
        metrics = QFontMetrics(self.task_label.font())
        self.task_label.setText(
            metrics.elidedText(instruction, Qt.ElideRight, self.width() - 30)
        )

    def _on_jump_clicked(self):
        if self.editor.steps:
            self.editor.jump_to_step(self.jump_spin.value() - 1)


class ValidationFailDialog(QDialog):
    """结束前全量校验未通过对话框：缺失清单 + 跳转到对应步骤"""

    def __init__(self, missing_entries, parent=None):
        """
        :param missing_entries: [(index, 动作中文名, [缺失原因...]), ...]
        """
        super().__init__(parent)
        self.setWindowTitle("校验未通过")
        self.setMinimumWidth(520)
        self._target_index = None

        layout = QVBoxLayout(self)

        tip = QLabel("以下步骤存在必填项缺失，请补全后再结束任务：")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self.list_widget = QListWidget()
        for index, action_cn, reasons in missing_entries:
            item = QListWidgetItem(
                f"第 {index + 1} 步（{action_cn}）：{'；'.join(reasons)}"
            )
            item.setData(Qt.UserRole, index)
            self.list_widget.addItem(item)
        self.list_widget.itemDoubleClicked.connect(self._on_jump_selected)
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        self.jump_btn = QPushButton("跳转到该步")
        self.jump_btn.clicked.connect(self._on_jump_selected)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(self.jump_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _on_jump_selected(self, item=None):
        """点击“跳转到该步”或双击列表行：记录目标下标并关闭对话框"""
        current = item or self.list_widget.currentItem()
        if current is None:
            return
        self._target_index = int(current.data(Qt.UserRole))
        self.accept()

    def target_index(self):
        """对话框关闭后读取用户请求跳转的下标；未选择跳转返回 None"""
        return self._target_index


class AnnotationEditor(QMainWindow):
    """标注编辑器主窗口"""

    def __init__(self, data_manager, app_name, task_instruction, screen_info, app_type="", hotkey_listener=None, init_window=None):
        super().__init__()
        self.setWindowTitle(f"GUI长步骤采标工具-macOS - {app_name}")
        self.setGeometry(100, 100, 1400, 900)

        self.data_manager = data_manager
        self.app_name = app_name
        self.app_type = app_type  # 保存应用类型
        self.task_instruction = task_instruction
        self.screen_info = screen_info
        self.init_window = init_window  # 任务初始化窗口引用，用于返回菜单

        # 全局快捷键监听器
        self.hotkey_listener = hotkey_listener

        # 数据状态
        self.gui_number = None  # 整个任务共用一个 gui_number
        self.steps = []  # 步骤列表
        self.current_step_index = -1
        # 截图模式标志：None=给下一步追加截图；整数=在该下标步骤之后插入一步
        self._capture_insert_after = None

        # draft 增量自动保存（防抖定时器）
        self.draft_timer = QTimer(self)
        self.draft_timer.setSingleShot(True)
        self.draft_timer.setInterval(1000)
        self.draft_timer.timeout.connect(self._write_draft_now)

        # 必填项校验：各步骤缺失项描述缓存（list，与 steps 下标一一对应；元素为 list[str]）
        self._missing_cache = []
        # 输入中只校验当前步的防抖定时器（300ms），避免 300 步下每键全量校验
        self.validation_timer = QTimer(self)
        self.validation_timer.setSingleShot(True)
        self.validation_timer.setInterval(300)
        self.validation_timer.timeout.connect(self._on_validation_debounced)

        self.init_ui()

    def init_ui(self):
        """初始化界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(2, 2, 2, 2)

        # 设置窗口快捷键
        self.setup_shortcuts()

        # 左右分栏：左侧步骤导航侧栏（可拖拽调宽），右侧原有编辑区
        self.splitter = QSplitter(Qt.Horizontal)

        # 左侧栏（进度看板 + 步骤列表 + 跳转）
        self.sidebar = SideBarWidget(self)
        self.sidebar.setMinimumWidth(200)
        self.splitter.addWidget(self.sidebar)

        # 右侧容器：工具栏 + 分隔线 + stack + 状态栏（维持原有布局）
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(2, 2, 2, 2)
        self.splitter.addWidget(right_widget)

        # 初始左栏约 260px，其余给编辑区
        self.splitter.setSizes([260, 1120])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        main_layout.addWidget(self.splitter)

        # 顶部工具栏
        toolbar = QHBoxLayout()

        # 步骤导航
        prev_btn = QPushButton("← 上一步")
        prev_btn.clicked.connect(self.previous_step)
        toolbar.addWidget(prev_btn)

        self.step_indicator = QLabel("步骤: 0 / 0")
        self.step_indicator.setFont(QFont("Arial", 12))
        toolbar.addWidget(self.step_indicator)

        next_btn = QPushButton("下一步 →")
        next_btn.clicked.connect(self.next_step)
        toolbar.addWidget(next_btn)

        toolbar.addStretch()

        # 操作按钮
        self.undo_btn = QPushButton("撤销上一步")
        self.undo_btn.clicked.connect(self.undo_last_step)
        self.undo_btn.hide()  # 初始时隐藏，因为没有步骤
        toolbar.addWidget(self.undo_btn)

        # 删除当前步骤（无步骤时禁用）
        self.delete_step_btn = QPushButton("删除当前步骤")
        self.delete_step_btn.setStyleSheet("QPushButton { background-color: #E53935; color: white; }")
        self.delete_step_btn.clicked.connect(self.delete_current_step)
        self.delete_step_btn.setEnabled(False)
        toolbar.addWidget(self.delete_step_btn)

        # 在当前步之后插入一步截图（无步骤时禁用）
        self.insert_step_btn = QPushButton("在此步后插入截图")
        self.insert_step_btn.setStyleSheet("QPushButton { background-color: #00897B; color: white; }")
        self.insert_step_btn.clicked.connect(self.start_insert_capture)
        self.insert_step_btn.setEnabled(False)
        toolbar.addWidget(self.insert_step_btn)

        recapture_btn = QPushButton("重新截图")
        recapture_btn.setStyleSheet("QPushButton { background-color: #FF9800; color: white; }")
        recapture_btn.clicked.connect(self.recapture_current_step)
        toolbar.addWidget(recapture_btn)

        # macOS 版全局热键由 pynput 子进程监听物理 Control+Q（见 main.py）
        screenshot_hk = "Control"
        capture_btn = QPushButton(f"给下一步截图 ({screenshot_hk}+Q)")
        capture_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; }")
        capture_btn.clicked.connect(self.start_capture)
        toolbar.addWidget(capture_btn)

        save_btn = QPushButton("确认")
        save_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
        save_btn.clicked.connect(self.confirm_button_clicked)
        toolbar.addWidget(save_btn)

        right_layout.addLayout(toolbar)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        right_layout.addWidget(line)

        # 步骤编辑区域（使用 StackWidget 实现分页）
        self.stack_widget = QStackedWidget()
        right_layout.addWidget(self.stack_widget)

        # 初始提示
        empty_widget = QWidget()
        empty_layout = QVBoxLayout(empty_widget)
        empty_label = QLabel("点击'给下一步截图'开始标注第一个步骤")
        empty_label.setAlignment(Qt.AlignCenter)
        empty_label.setStyleSheet("color: gray; font-size: 16px;")
        empty_layout.addWidget(empty_label)
        self.stack_widget.addWidget(empty_widget)

        # 底部状态栏
        status_bar = QHBoxLayout()
        self.status_label = QLabel(f"就绪 - 按 {screenshot_hk}+Q 给下一步截图")
        status_bar.addWidget(self.status_label)
        right_layout.addLayout(status_bar)

        # 侧栏导航快捷键：PageUp/PageDown 上一步/下一步（不与全局 Control+Q 及输入框常用键冲突）
        self.prev_shortcut = QShortcut(QKeySequence(Qt.Key_PageUp), self)
        self.prev_shortcut.setContext(Qt.WindowShortcut)
        self.prev_shortcut.activated.connect(self.previous_step)
        self.next_shortcut = QShortcut(QKeySequence(Qt.Key_PageDown), self)
        self.next_shortcut.setContext(Qt.WindowShortcut)
        self.next_shortcut.activated.connect(self.next_step)

        # 多轮任务支持
        self.rounds = []  # 存储所有轮次的数据
        self.current_round_index = 0  # 当前轮次索引

        # 拉框坐标收集（保存到独立的 _coords.json 文件）
        self.all_coords_entries = []

        # 初始渲染看板（任务指令、零步统计）
        self.sidebar.refresh_dashboard()

    # ---------- 必填项校验（Task 6） ----------

    def validate_step_at(self, index):
        """按动作类型校验指定步骤，返回中文缺失项描述列表（空列表表示通过）。
        只读编辑器控件，不修改任何数据；全屏截图（selection_type == "fullscreen"）
        豁免坐标要求。"""
        if not (0 <= index < len(self.steps)):
            return []
        step = self.steps[index]
        editor = step["editor"]
        action_type = editor.action_type_mapping.get(
            editor.action_type_combo.currentText(),
            editor.action_type_combo.currentText()
        )
        missing = []

        # 1. 除 terminate 外，动作描述必填（answer_terminate 按 answer 口径同样要求）
        if action_type != "terminate":
            if not editor.intent_input.text().strip():
                missing.append("动作描述不能为空")

        # 2. 坐标类动作（全屏截图豁免）
        coord_actions = ("left_click", "double_click", "triple_click",
                         "right_click", "middle_click", "mouse_move",
                         "left_click_drag", "type", "scroll")
        fullscreen = step.get("selection_type") == "fullscreen"
        if action_type in coord_actions and not fullscreen:

            def _is_zero(line_edit):
                # 与 get_data 的 (0,0) 兜底口径对齐：空、非数字或 0 均视为缺失
                text = line_edit.text().strip()
                if not text:
                    return True
                try:
                    return int(float(text)) == 0
                except ValueError:
                    return True

            start_missing = _is_zero(editor.coord_x_input) or _is_zero(editor.coord_y_input)
            if action_type == "left_click_drag":
                # 起点缺失则整框需要重拉；终点 0,0 且起点非 0,0 视为终点缺失
                if start_missing:
                    missing.append("坐标缺失（请重新拉框）")
                elif _is_zero(editor.end_coord_x_input) or _is_zero(editor.end_coord_y_input):
                    missing.append("拖拽终点坐标缺失")
            elif start_missing:
                missing.append("坐标缺失（请重新拉框）")

        # 3. key：四个按键输入框至少一个非空
        if action_type == "key":
            if not any(getattr(editor, f"keys_input_{n}").text().strip()
                       for n in range(1, 5)):
                missing.append("按键不能为空")

        # 4. wait：等待时间必须为可解析数字且 > 0
        if action_type == "wait":
            time_text = editor.wait_time_input.text().strip()
            try:
                wait_value = float(time_text) if time_text else 0
            except ValueError:
                wait_value = 0
            if wait_value <= 0:
                missing.append("等待时间必须大于 0")

        # 5. 文本类动作
        if action_type in ("type", "open_app", "open_url", "answer", "answer_terminate"):
            if not editor.text_input.toPlainText().strip():
                text_messages = {
                    "type": "输入文本不能为空",
                    "open_app": "应用名不能为空",
                    "open_url": "URL 不能为空",
                    "answer": "回答内容不能为空",
                    "answer_terminate": "回答内容不能为空",
                }
                missing.append(text_messages[action_type])

        # 6. terminate：无额外必填
        return missing

    def get_cached_missing(self, index):
        """读取某步缺失项缓存；下标越界/缓存未建立时返回 None"""
        if 0 <= index < len(self._missing_cache):
            return self._missing_cache[index]
        return None

    def revalidate_all_missing(self):
        """全量重算所有步骤的缺失状态（仅结构性变化时调用，300 步只读取少量控件）"""
        self._missing_cache = [self.validate_step_at(i) for i in range(len(self.steps))]
        for i, item in enumerate(self.sidebar.item_widgets):
            item.set_missing(self._missing_cache[i] if i < len(self._missing_cache) else [])
        self.sidebar.refresh_dashboard()

    def revalidate_current_missing(self):
        """只重算当前编辑步的缺失标记并更新看板计数（输入防抖路径）"""
        index = self.current_step_index
        if not (0 <= index < len(self.steps)):
            return
        # 缓存长度漂移（极端时序）时退化为全量重算
        if len(self._missing_cache) != len(self.steps):
            self.revalidate_all_missing()
            return
        missing = self.validate_step_at(index)
        self._missing_cache[index] = missing
        if index < len(self.sidebar.item_widgets):
            self.sidebar.item_widgets[index].set_missing(missing)
        total = len(self.steps)
        missing_count = sum(1 for i in range(total) if self.get_cached_missing(i))
        self.sidebar.missing_count_label.setText(f"待完善: {missing_count}")

    def _schedule_current_validation(self, *args):
        """控件内容变化信号的统一槽：重启 300ms 防抖，只校验当前步"""
        self.validation_timer.start()

    def _on_validation_debounced(self):
        self.revalidate_current_missing()

    def _connect_editor_validation_signals(self, editor):
        """为一个步骤编辑器连接必填项实时校验信号（textChanged/文本类）"""
        editor.intent_input.textChanged.connect(self._schedule_current_validation)
        editor.text_input.textChanged.connect(self._schedule_current_validation)
        editor.wait_time_input.textChanged.connect(self._schedule_current_validation)
        editor.action_type_combo.currentTextChanged.connect(self._schedule_current_validation)
        editor.coord_x_input.textChanged.connect(self._schedule_current_validation)
        editor.coord_y_input.textChanged.connect(self._schedule_current_validation)
        editor.end_coord_x_input.textChanged.connect(self._schedule_current_validation)
        editor.end_coord_y_input.textChanged.connect(self._schedule_current_validation)
        for n in range(1, 5):
            getattr(editor, f"keys_input_{n}").textChanged.connect(
                self._schedule_current_validation)

    def _action_cn_name(self, index):
        """取某步动作类型中文名（校验清单展示用）"""
        if not (0 <= index < len(self.steps)):
            return ""
        editor = self.steps[index]["editor"]
        current = editor.action_type_combo.currentText()
        # 若当前文本恰好是英文（兼容异常数据），反查中文
        if current in editor.action_type_mapping.values():
            current = next((k for k, v in editor.action_type_mapping.items()
                            if v == current), current)
        return current

    def _show_validation_fail_dialog(self, missing_entries):
        """弹出结束前校验未通过清单；用户选择跳转时 display_step 到对应步骤"""
        dialog = ValidationFailDialog(missing_entries, self)
        dialog.exec_()
        target = dialog.target_index()
        if target is not None and 0 <= target < len(self.steps):
            self.display_step(target)

    def setup_shortcuts(self):
        """连接全局快捷键监听器的信号"""
        if self.hotkey_listener:
            # 连接全局快捷键信号
            self.hotkey_listener.screenshot_triggered.connect(self.start_capture)
            print("✅ 全局快捷键已连接到标注编辑器")
        else:
            print("⚠️ 未设置全局快捷键监听器")

    def recapture_current_step(self):
        """重新截取当前步骤的截图，如果没有步骤则开始第一个截图"""
        if self.current_step_index < 0 or self.current_step_index >= len(self.steps):
            # 没有步骤时，开始第一个截图
            self.start_capture()
            return

        # 先将窗口设为完全透明（避免 hide() 动画过程被截图捕捉），再隐藏
        self.setWindowOpacity(0.0)
        self.hide()

        # 延迟确保窗口完全隐藏后再截图
        QTimer.singleShot(350, self.show_recapture_window)

    def show_recapture_window(self):
        """显示重新截图窗口"""
        self.capture_window = ScreenshotCaptureWindow()
        self.capture_window.capture_completed.connect(self.on_recapture_completed)
        self.capture_window.show()

    def on_recapture_completed(self, original_pixmap, marked_pixmap, rect_info, selection_type):
        """重新截图完成回调"""
        # 检查是否被取消
        if selection_type == "cancelled":
            # 用户取消了截图，重新显示主窗口
            self.restore_window()
            self.status_label.setText("重新截图已取消")
            return

        # 获取当前步骤
        current_step = self.steps[self.current_step_index]

        # 覆盖保存到原有的截图文件（复用原序号，不新增文件）
        filename = current_step["screenshot_filename"]
        filepath = self.data_manager.save_screenshot_overwrite(
            original_pixmap, self.gui_number, filename, format="PNG"
        )

        if filepath:
            current_step["rect_info"] = rect_info
            current_step["selection_type"] = selection_type
            # 不再保存全屏 QPixmap 引用；预览用完即用即释放，历史预览从磁盘重建

            editor = current_step["editor"]
            editor.set_screenshot(marked_pixmap)
            editor.set_preview_meta(filename, rect_info, selection_type)

            # 判断是否为双框模式（拖拽动作）
            if selection_type == "fullscreen":
                pass
            elif isinstance(rect_info, tuple) and len(rect_info) == 2 and isinstance(rect_info[0], tuple):
                # 双框模式 - 拖拽动作
                first_rect = rect_info[0]
                second_rect = rect_info[1]

                # 计算两个框的中心点
                start_x = first_rect[0] + first_rect[2] // 2
                start_y = first_rect[1] + first_rect[3] // 2
                end_x = second_rect[0] + second_rect[2] // 2
                end_y = second_rect[1] + second_rect[3] // 2

                # 设置起点坐标
                editor.coord_x_input.setText(str(start_x))
                editor.coord_y_input.setText(str(start_y))

                # 设置终点坐标
                editor.end_coord_x_input.setText(str(end_x))
                editor.end_coord_y_input.setText(str(end_y))

                # 自动选择"拖拽"动作
                drag_index = editor.action_type_combo.findText("拖拽")
                if drag_index >= 0:
                    editor.action_type_combo.setCurrentIndex(drag_index)
            elif len(rect_info) == 4:
                # 单框模式 - 原有逻辑
                center_x = rect_info[0] + rect_info[2] // 2
                center_y = rect_info[1] + rect_info[3] // 2
                editor.coord_x_input.setText(str(center_x))
                editor.coord_y_input.setText(str(center_y))

            # 显示主窗口
            self.restore_window()

            self.status_label.setText(f"已重新捕获截图 {filename}")
            # 更新撤销按钮可见性
            self.update_undo_button_visibility()
            # 截图已覆盖：失效该步骤缩略图缓存并重载条目（动作类型可能随拖拽框变化）
            self.sidebar.invalidate_thumb(self.current_step_index)
            item = self.sidebar.item_widgets[self.current_step_index] \
                if self.current_step_index < len(self.sidebar.item_widgets) else None
            if item is not None:
                item.thumb_loaded = False
                self.sidebar.request_thumb(self.current_step_index, high_priority=True)
                self.refresh_step_item(self.current_step_index)
            self.schedule_draft_save()
        else:
            QMessageBox.critical(self, "错误", "保存截图失败！")
            self.restore_window()

    def start_capture(self):
        """开始截图捕获（追加模式：新步骤加到末尾）"""
        self._capture_insert_after = None
        self._hide_for_capture()

    def start_insert_capture(self):
        """在当前步骤之后插入一步截图（插入模式）"""
        if not (0 <= self.current_step_index < len(self.steps)):
            return
        # 记录插入锚点：新步将插入到该下标 +1 位置
        self._capture_insert_after = self.current_step_index
        self._hide_for_capture()

    def _hide_for_capture(self):
        """截图前隐藏主窗口（追加/插入两路径共用）"""
        # 先将窗口设为完全透明（避免 hide() 动画过程被截图捕捉），再隐藏
        self.setWindowOpacity(0.0)
        self.hide()

        # 延迟确保窗口完全隐藏后再截图
        QTimer.singleShot(350, self.show_capture_window)

    def show_capture_window(self):
        """显示截图窗口"""
        self.capture_window = ScreenshotCaptureWindow()
        self.capture_window.capture_completed.connect(self.on_capture_completed)
        self.capture_window.show()

    def _init_editor_from_capture(self, editor, marked_pixmap, rect_info, selection_type):
        """新截图落到一个全新编辑器上的公共初始化：预览图 + 坐标填充 + 拖拽自动选动作
        （追加/插入两条路径共用，避免逻辑复制漂移）
        :return: 归一化后的 selection_type（双框拖拽归并为 "drag"）
        """
        # 预览图使用带标记的截图
        editor.set_screenshot(marked_pixmap)

        # 判断是否为双框模式（拖拽动作）
        if selection_type == "fullscreen":
            pass
        elif isinstance(rect_info, tuple) and len(rect_info) == 2 and isinstance(rect_info[0], tuple):
            # 双框模式 - 拖拽动作
            first_rect = rect_info[0]
            second_rect = rect_info[1]

            # 计算两个框的中心点
            start_x = first_rect[0] + first_rect[2] // 2
            start_y = first_rect[1] + first_rect[3] // 2
            end_x = second_rect[0] + second_rect[2] // 2
            end_y = second_rect[1] + second_rect[3] // 2

            # 设置起点坐标
            editor.coord_x_input.setText(str(start_x))
            editor.coord_y_input.setText(str(start_y))

            # 设置终点坐标
            editor.end_coord_x_input.setText(str(end_x))
            editor.end_coord_y_input.setText(str(end_y))

            # 自动选择"拖拽"动作
            drag_index = editor.action_type_combo.findText("拖拽")
            if drag_index >= 0:
                editor.action_type_combo.setCurrentIndex(drag_index)

            selection_type = "drag"  # 确保选择类型为 drag
        elif len(rect_info) == 4:
            # 单框模式 - 原有逻辑
            center_x = rect_info[0] + rect_info[2] // 2
            center_y = rect_info[1] + rect_info[3] // 2
            editor.coord_x_input.setText(str(center_x))
            editor.coord_y_input.setText(str(center_y))

        return selection_type

    def on_capture_completed(self, original_pixmap, marked_pixmap, rect_info, selection_type):
        """截图完成回调（根据 self._capture_insert_after 区分追加 / 插入）"""
        # 取出插入锚点（无论取消与否都要复位模式标志）
        insert_after = self._capture_insert_after

        # 检查是否被取消
        if selection_type == "cancelled":
            self._capture_insert_after = None  # 取消时复位插入模式
            self.restore_window()
            self.status_label.setText("截图已取消")
            return

        # 保存截图（整个任务共用一个 gui_number）
        if self.gui_number is None:
            self.gui_number = self.data_manager.get_next_gui_number()

        # 首次截图（且为追加模式）时，以截图物理分辨率为准更新 screen_size
        if len(self.steps) == 0 and insert_after is None \
                and original_pixmap and not original_pixmap.isNull():
            self.screen_info["screen_size"] = [
                original_pixmap.width(),
                original_pixmap.height()
            ]

        # 保存原始截图文件（不带标记），文件名按 gui_编号_序号.png 递增；
        # 插入同样走 save_screenshot 分配全新序号（磁盘 max+1），旧文件不重命名（允许序号空洞）
        filepath = self.data_manager.save_screenshot(
            original_pixmap,
            self.gui_number,
            format="PNG"
        )

        if filepath:
            filename = os.path.basename(filepath)

            # 创建新的步骤编辑器并完成坐标/动作初始化（追加、插入共用）
            step_editor = StepEditorWidget()
            # 必填项实时校验信号（输入防抖，只重算当前步）
            self._connect_editor_validation_signals(step_editor)
            # 分栏/窗口 resize 后按磁盘原图防抖重绘预览
            step_editor.preview_resize_requested.connect(
                lambda ed=step_editor: self._on_editor_preview_resize(ed)
            )
            selection_type = self._init_editor_from_capture(
                step_editor, marked_pixmap, rect_info, selection_type
            )
            step_editor.set_preview_meta(filename, rect_info, selection_type)

            # 新步骤项（不保存全屏 QPixmap 引用，避免随步数线性增长内存）
            # confirmed 为运行时状态标志（不写入 draft/JSON）：False=编辑中，True=已确认
            new_step = {
                "editor": step_editor,
                "screenshot_filename": filename,
                "rect_info": rect_info,
                "selection_type": selection_type,
                "confirmed": False
            }

            # 插入模式锚点失效（无步骤）时兜底按追加处理
            is_insert = insert_after is not None and 0 <= insert_after < len(self.steps)
            if is_insert:
                insert_index = insert_after + 1
                self.steps.insert(insert_index, new_step)
                # addWidget 先挂到末尾，再按 steps 顺序重排 insert_index 起的页序
                self.stack_widget.addWidget(step_editor)
                self._rebuild_stack_page_order(insert_index)
                # 插入位置及之后的步骤全部重新编号（编辑器编号 + data 快照 step 字段）
                self._renumber_steps_from(insert_index)
                new_current = insert_index
            else:
                # 追加到末尾
                self.steps.append(new_step)
                self.stack_widget.addWidget(step_editor)
                new_current = len(self.steps) - 1
                step_editor.set_step_number(new_current)

            # 复位插入模式标志
            self._capture_insert_after = None

            # 切到新步（统一出口：页序不变式保证 stack 页 index == step_index+1）
            self.display_step(new_current)

            # 下标整体变化（插入）或末尾追加：统一全量重建侧栏，保证条目/缩略图下标一致
            self.refresh_sidebar(fully=is_insert)

            # 显示主窗口
            self.restore_window()

            if is_insert:
                self.status_label.setText(
                    f"已在第 {insert_after + 1} 步后插入截图 {filename}，请填写动作信息")
            else:
                self.status_label.setText(f"已捕获截图 {filename}，请填写动作信息")
            self.schedule_draft_save()
        else:
            self._capture_insert_after = None
            QMessageBox.critical(self, "错误", "保存截图失败！")
            self.restore_window()

    def get_current_step_number(self):
        """获取当前步骤编号（当前步下标；中间插入步后不再等于末尾下标）"""
        return self.current_step_index

    def _rebuild_stack_page_order(self, start_index):
        """按 self.steps 顺序重排 stack 中从 start_index 起的编辑器页

        QStackedWidget 不支持在中间插页/改页序。做法：把起始位置（含）之后的
        编辑器页全部 removeWidget（不销毁，widget 仍由 self.steps 持有），
        再按 self.steps 的新顺序依次 addWidget 重新接管父对象。
        第 0 页空提示页始终不动。
        不变式：stack.count() == len(steps)+1，且 widget(i+1) is steps[i]["editor"]
        """
        # 收集需要重排的编辑器（起始下标之后的全部步骤页）
        tail_editors = [step["editor"] for step in self.steps[start_index:]]
        # 先摘除：从后往前 removeWidget，避免索引漂移；removeWidget 不销毁对象
        for editor in reversed(tail_editors):
            self.stack_widget.removeWidget(editor)
        # 再按目标顺序挂回末尾（前面的页未动，挂回后顺序恰好与 steps 对齐）
        for editor in tail_editors:
            self.stack_widget.addWidget(editor)
        self._check_stack_invariant()

    def _check_stack_invariant(self):
        """校验 stack 页序不变式（异常只打印，不打断用户操作）"""
        try:
            assert self.stack_widget.count() == len(self.steps) + 1, \
                f"stack 页数 {self.stack_widget.count()} != 步数+1 {len(self.steps) + 1}"
            for i, step in enumerate(self.steps):
                assert self.stack_widget.widget(i + 1) is step["editor"], \
                    f"第 {i} 步对应的 stack 页不是其编辑器（页下标 {i + 1}）"
        except AssertionError as e:
            print(f"stack 页序不变式校验失败: {e}")

    def _renumber_steps_from(self, start_index):
        """从 start_index 起按新下标连续重编号：编辑器显示编号 + 已有 data 快照的 step 字段

        注意：data 快照中 observation.screenshot 文件名保持各自文件名不变
        （文件不重命名，允许磁盘序号出现空洞）。
        """
        for i in range(max(0, start_index), len(self.steps)):
            step = self.steps[i]
            step["editor"].set_step_number(i)
            data = step.get("data")
            if isinstance(data, dict):
                data["step"] = i

    def _delete_screenshot_file(self, filename):
        """删除指定步骤的磁盘截图文件，失败仅打印不阻断主流程"""
        try:
            if self.gui_number is None:
                return
            gui_dir = os.path.join(self.data_manager.current_dir, f"gui_{self.gui_number}")
            filepath = os.path.join(gui_dir, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            print(f"删除截图失败: {e}")

    def delete_current_step(self):
        """删除当前步骤：二次确认后删除步骤/页面/磁盘截图，后续步骤自动前移重编号"""
        index = self.current_step_index
        if not (0 <= index < len(self.steps)):
            # 无步骤（含 answer/terminate 后 steps 已清空）直接保护返回
            return

        reply = QMessageBox.question(
            self,
            "删除当前步骤",
            f"确定删除第 {index + 1} 步？该步截图文件将一并删除，后续步骤自动前移",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        removed = self.steps.pop(index)
        removed_filename = removed.get("screenshot_filename", "")

        # 删除 stack 对应页并释放（setParent(None) 解除父子关系）
        page = self.stack_widget.widget(index + 1)  # +1 因为第 0 页是空提示页
        if page is not None:
            self.stack_widget.removeWidget(page)
            page.setParent(None)

        # 删除磁盘截图文件（失败仅打印不阻断）
        self._delete_screenshot_file(removed_filename)
        # 清理侧栏中被删文件名的缩略图缓存条目
        self.sidebar.remove_thumb_cache_by_filename(removed_filename)

        # 删除位置及之后的步骤整体前移，重新连续编号
        self._renumber_steps_from(index)
        self._check_stack_invariant()

        # 删除后定位：同位置（即原下一步）；删的是最后一步则定位前一步；删空回第 0 页
        total = len(self.steps)
        if total == 0:
            self.current_step_index = -1
            self.stack_widget.setCurrentIndex(0)
            self.update_step_indicator()
            self.sidebar.refresh_dashboard()
        else:
            target = index if index < total else total - 1
            self.display_step(target)

        # 下标整体变化，侧栏全量重建
        self.refresh_sidebar(fully=True)

        self.status_label.setText(f"已删除第 {index + 1} 步")
        self.schedule_draft_save()

    def update_undo_button_visibility(self):
        """根据当前步骤位置更新撤销按钮的可见性"""
        # 只有当当前步骤是最后一步时才显示撤销按钮
        if len(self.steps) > 0 and self.current_step_index == len(self.steps) - 1:
            self.undo_btn.show()
        else:
            self.undo_btn.hide()

    def update_step_indicator(self):
        """更新步骤指示器"""
        total = len(self.steps)
        current = self.current_step_index + 1 if self.current_step_index >= 0 else 0
        self.step_indicator.setText(f"步骤: {current} / {total}")
        # 同时更新撤销按钮的可见性
        self.update_undo_button_visibility()
        # 删除/插入按钮仅在存在步骤时可用（answer/terminate 后 steps 已清空时自动禁用）
        has_steps = total > 0
        self.delete_step_btn.setEnabled(has_steps)
        self.insert_step_btn.setEnabled(has_steps)

    def build_marked_preview(self, filename, rect_info, selection_type, target_size):
        """从磁盘加载原图，按物理像素坐标重绘红框标记，再缩放到 target_size
        :return: 缩放后的 QPixmap；加载失败返回 None
        """
        if self.gui_number is None:
            return None

        pixmap = self.data_manager.load_screenshot(self.gui_number, filename)
        if pixmap is None or pixmap.isNull():
            return None

        # rect_info 与磁盘 PNG 同为物理像素坐标，直接在原始尺寸 pixmap 上绘制
        # 按 rect_info 结构判定：嵌套二元组=双框拖拽；四元组=单框；()/fullscreen=不画
        is_dual = (isinstance(rect_info, (tuple, list)) and len(rect_info) == 2
                   and isinstance(rect_info[0], (tuple, list)))
        is_single = isinstance(rect_info, (tuple, list)) and len(rect_info) == 4
        if is_dual or is_single:
            painter = QPainter(pixmap)
            pen = QPen(QColor(255, 0, 0), 3)
            painter.setPen(pen)

            if is_dual:
                first_rect, second_rect = rect_info
                fx, fy, fw, fh = first_rect
                sx, sy, sw, sh = second_rect
                painter.drawRect(QRect(fx, fy, fw, fh))
                painter.drawRect(QRect(sx, sy, sw, sh))

                # 双框之间画带箭头的连线（复刻 screenshot_capture.confirm_selection）
                first_cx, first_cy = fx + fw // 2, fy + fh // 2
                second_cx, second_cy = sx + sw // 2, sy + sh // 2
                angle = math.atan2(second_cy - first_cy, second_cx - first_cx)
                arrow_length = 15
                arrow_angle = math.pi / 6
                x1 = second_cx - arrow_length * math.cos(angle - arrow_angle)
                y1 = second_cy - arrow_length * math.sin(angle - arrow_angle)
                x2 = second_cx - arrow_length * math.cos(angle + arrow_angle)
                y2 = second_cy - arrow_length * math.sin(angle + arrow_angle)
                painter.drawLine(first_cx, first_cy, second_cx, second_cy)
                painter.drawLine(second_cx, second_cy, int(x1), int(y1))
                painter.drawLine(second_cx, second_cy, int(x2), int(y2))
            else:
                x, y, w, h = rect_info
                painter.drawRect(QRect(x, y, w, h))

            painter.end()

        # 目标尺寸异常时兜底，避免预览模糊或缩成一点
        if target_size is None or target_size.width() < 2 or target_size.height() < 2:
            target_size = QSize(400, 300)

        return pixmap.scaled(
            target_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

    def _refresh_step_preview(self, index):
        """用磁盘文件刷新指定步骤的预览图（不缓存全屏图）"""
        if index < 0 or index >= len(self.steps):
            return
        step = self.steps[index]
        editor = step["editor"]
        label_size = editor.screenshot_label.size()
        if label_size.width() < 2 or label_size.height() < 2:
            label_size = QSize(400, 300)
        preview = self.build_marked_preview(
            step.get("screenshot_filename"),
            step.get("rect_info"),
            step.get("selection_type"),
            label_size
        )
        if preview is not None:
            editor.screenshot_label.setPixmap(preview)
            editor.set_preview_meta(
                step.get("screenshot_filename"),
                step.get("rect_info"),
                step.get("selection_type")
            )

    def _on_editor_preview_resize(self, editor):
        """编辑器预览区 resize 防抖后的重建槽：仅处理当前可见页，从磁盘原图重绘"""
        if not self.steps:
            return
        current_editor = self.steps[self.current_step_index]["editor"] \
            if 0 <= self.current_step_index < len(self.steps) else None
        if editor is not current_editor or not editor.isVisible():
            return
        filename, rect_info, selection_type = editor.preview_meta
        label_size = editor.screenshot_label.size()
        if label_size.width() < 2 or label_size.height() < 2:
            label_size = QSize(400, 300)
        preview = self.build_marked_preview(filename, rect_info, selection_type, label_size)
        if preview is not None:
            editor.screenshot_label.setPixmap(preview)

    def display_step(self, index):
        """切换步骤页的统一出口：切页后从磁盘刷新该步预览"""
        if index < 0 or index >= len(self.steps):
            return
        self.current_step_index = index
        self.stack_widget.setCurrentIndex(index + 1)  # +1 因为第 0 页是空提示页
        self.update_step_indicator()
        # 侧栏：高亮随切换移动（纯展示态，与 prev/next 一样不自动保存编辑器数据）
        self.sidebar.refresh_highlight()
        self.sidebar.refresh_dashboard()
        self.sidebar.ensure_current_thumb(index)
        # 延迟到页面真正显示后再缩放，此时 label 尺寸才准确
        QTimer.singleShot(0, lambda idx=index: self._refresh_step_preview(idx))

    def previous_step(self):
        """上一步"""
        if self.current_step_index > 0:
            self.display_step(self.current_step_index - 1)

    def next_step(self):
        """下一步"""
        if self.current_step_index < len(self.steps) - 1:
            self.display_step(self.current_step_index + 1)

    def jump_to_step(self, index):
        """侧栏条目点击/跳转按钮入口：仅做展示态切换（语义与 prev/next 一致）"""
        if 0 <= index < len(self.steps):
            self.display_step(index)

    def refresh_sidebar(self, fully=False):
        """刷新侧栏：fully=True 全量重建条目（步骤集合增删/恢复时）；
        fully=False 只刷新计数、动作分布与当前步状态（新增一步后）"""
        if fully:
            self.sidebar.rebuild_items()
        else:
            # 常规新增：增量追加一个条目，避免重建整个列表
            target = len(self.sidebar.item_widgets)
            if target < len(self.steps):
                item = self.sidebar._create_item(target)
                self.sidebar.item_widgets.append(item)
                self.sidebar.refresh_step_item(target)
                self.sidebar.request_thumb(target, high_priority=True)
            self.sidebar.refresh_highlight()
            self.sidebar.refresh_dashboard()

    def refresh_step_item(self, index):
        """刷新单个侧栏条目（重新截图/状态变化后调用）"""
        self.sidebar.refresh_step_item(index)

    def refresh_dashboard(self):
        """刷新进度看板计数"""
        self.sidebar.refresh_dashboard()

    def undo_last_step(self):
        """撤销上一步"""
        if len(self.steps) > 0:
            reply = QMessageBox.question(
                self,
                "确认撤销",
                "确定要撤销最后一步吗？",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                # 移除最后一个步骤
                removed = self.steps.pop()

                # 从 stack widget 移除（撤销的永远是最后一页，setParent(None) 释放）
                widget = self.stack_widget.widget(self.stack_widget.count() - 1)
                self.stack_widget.removeWidget(widget)
                widget.setParent(None)

                # 删除截图文件（失败仅打印不阻断），并清理其缩略图缓存
                removed_filename = removed.get("screenshot_filename", "")
                self._delete_screenshot_file(removed_filename)
                self.sidebar.remove_thumb_cache_by_filename(removed_filename)

                # 调整当前索引
                if self.current_step_index >= len(self.steps):
                    self.current_step_index = len(self.steps) - 1

                if self.current_step_index >= 0:
                    self.display_step(self.current_step_index)
                else:
                    self.stack_widget.setCurrentIndex(0)
                    self.update_step_indicator()

                # 撤销后所有条目序号前移，全量重建侧栏
                self.refresh_sidebar(fully=True)

                self.status_label.setText("已撤销上一步")
                self.schedule_draft_save()

    def hide_window(self):
        """隐藏窗口"""
        self.showMinimized()

    def confirm_button_clicked(self):
        if self.current_step_index >= 0 and self.current_step_index < len(self.steps):
            editor = self.steps[self.current_step_index]["editor"]
            action_type_chinese = editor.action_type_combo.currentText()
            action_type = editor.action_type_mapping.get(action_type_chinese, action_type_chinese)
            if action_type in ("terminate", "answer", "answer_terminate"):
                self.save_current_step()
                return
        # 普通确认：当前步骤标记为已确认并更新侧栏状态/计数
        if 0 <= self.current_step_index < len(self.steps):
            self.steps[self.current_step_index]["confirmed"] = True
            self.refresh_step_item(self.current_step_index)
            self.refresh_dashboard()
        # 用户可能填了描述但未触发保存分支，隐藏窗口前先排一次 draft
        self.schedule_draft_save()
        self.hide_window()

    def restore_window(self):
        """恢复窗口显示（处理最小化状态）"""
        self.setWindowOpacity(1.0)
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def save_current_step(self):
        """保存当前步骤"""
        if self.current_step_index < 0 or self.current_step_index >= len(self.steps):
            QMessageBox.warning(self, "警告", "没有可保存的步骤！")
            return

        # 获取当前编辑器
        current_step = self.steps[self.current_step_index]
        editor = current_step["editor"]

        # 获取编辑数据
        step_data = editor.get_data()

        # 设置步骤编号（放在首部）
        step_num = self.get_current_step_number()
        step_data_with_step = {"step": step_num}
        step_data_with_step.update(step_data)
        step_data = step_data_with_step

        # 设置截图文件名
        step_data["observation"]["screenshot"] = current_step["screenshot_filename"]

        # 当前步骤确认落快照，运行时标志置为已确认（answer/terminate 分支随后会清空 steps）
        previous_confirmed = current_step.get("confirmed", False)
        current_step["confirmed"] = True

        # 检查是否为 answer / answer_terminate 动作
        actions = step_data.get("actions", [])
        selected_action_type = editor.action_type_mapping.get(
            editor.action_type_combo.currentText(), editor.action_type_combo.currentText()
        )
        if selected_action_type == "answer":
            # answer 动作：保存后直接开始新一轮任务
            current_step["data"] = step_data
            self.status_label.setText(f"步骤 {step_num} 已保存（回答用户）")

            # 保存当前轮次并直接开始新任务
            self.save_current_round()
            # 清空步骤列表，避免后续重复保存
            self.steps = []
            QTimer.singleShot(300, lambda: self.start_new_round(from_answer=True))
        elif selected_action_type in ("terminate", "answer_terminate"):
            # 结束前全量必填项校验（含当前步）：存在缺失则弹窗并阻止结束，
            # 不执行 save_current_round / 轮次切换，数据状态保持原样
            missing_entries = []
            for i in range(len(self.steps)):
                reasons = self.validate_step_at(i)
                if reasons:
                    missing_entries.append((i, self._action_cn_name(i), reasons))
            if missing_entries:
                # 校验未通过：回滚本分支前置的 confirmed 置位，保持状态真实
                current_step["confirmed"] = previous_confirmed
                self.revalidate_all_missing()
                self.refresh_step_item(self.current_step_index)
                self.refresh_dashboard()
                self._show_validation_fail_dialog(missing_entries)
                return
            # 任务完成或回答并结束动作：先保存当前轮次，最后弹窗
            current_step["data"] = step_data
            finish_label = "回答并结束" if selected_action_type == "answer_terminate" else "任务完成"
            self.status_label.setText(f"步骤 {step_num} 已保存（{finish_label}）")

            # 立即保存当前轮次到 rounds 列表，防止弹窗前窗口关闭导致数据丢失
            self.save_current_round()
            # 清空步骤列表，避免 finish_all_annotation 重复保存
            self.steps = []

            # 显示后续对话框
            QTimer.singleShot(300, self.show_new_task_dialog)
        else:
            # 普通步骤
            current_step["data"] = step_data
            self.status_label.setText(f"步骤 {step_num} 已保存")

        # 更新指示器与侧栏（answer/terminate 分支已清空 steps，仅刷看板即可）
        self.update_step_indicator()
        if 0 <= self.current_step_index < len(self.steps):
            self.refresh_step_item(self.current_step_index)
        self.refresh_dashboard()
        # 三个分支统一触发防抖 draft 写出
        self.schedule_draft_save()

    def show_terminate_dialog(self):
        """显示任务完成对话框"""
        # 确保主窗口在前台
        self.restore_window()

        reply = QMessageBox.question(
            self,
            "任务完成",
            "当前任务已完成。\n\n是否继续当前任务？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # 保存当前轮次并开始新任务（同一 gui 文件夹）
            self.save_current_round()
            self.start_new_round()
        else:
            # 询问是否创建新的标注任务
            self.show_new_task_dialog()

    def save_current_round(self):
        """保存当前轮次的数据到 rounds 列表"""
        # 说明（删除/插入对齐）：本方法是轮次结束时唯一的落盘点，trajectory 与 coords
        # entries 都在此刻按当时 self.steps 的 enumerate 下标 i 现场重建。轮次中途的
        # 删除/插入只会改变 self.steps 顺序，任何 data 快照里旧的 "step" 不被读取
        # （有快照的分支直接沿用快照对象，其 step 已在删除/插入时同步重编号），
        # 因此最终写出的 step 一定与重排后的新下标一致；all_coords_entries 也没有
        # 轮次中途缓存路径（全项目仅本方法 append）。
        # 收集所有步骤数据
        trajectory = []
        for i, step in enumerate(self.steps):
            if "data" in step:
                trajectory.append(step["data"])
            else:
                # 如果步骤还没有保存，尝试从编辑器获取数据
                editor = step["editor"]
                step_data = editor.get_data()
                step_data["observation"]["screenshot"] = step["screenshot_filename"]
                # 将 step 字段放到首部
                step_data_with_step = {"step": i}
                step_data_with_step.update(step_data)
                step_data = step_data_with_step
                trajectory.append(step_data)

        # 添加到轮次列表（只保存 instruction 和 trajectory）
        self.rounds.append({
            "instruction": self.task_instruction,
            "trajectory": trajectory
        })

        # 提取需要坐标的步骤，收集其拉框顶点和中心点坐标
        coord_action_types = {"left_click", "double_click", "triple_click",
                              "right_click", "middle_click", "mouse_move",
                              "left_click_drag", "type"}

        for i, step in enumerate(self.steps):
            rect_info = step.get("rect_info")
            if not rect_info:
                continue

            editor = step["editor"]
            action_type_chinese = editor.action_type_combo.currentText()
            action_type = editor.action_type_mapping.get(action_type_chinese, action_type_chinese)

            if action_type not in coord_action_types:
                continue

            try:
                if action_type == "left_click_drag":
                    # 拖拽动作有两个框
                    if isinstance(rect_info, tuple) and len(rect_info) == 2 and isinstance(rect_info[0], tuple):
                        first_rect, second_rect = rect_info
                        x1, y1, w1, h1 = first_rect
                        x2, y2, w2, h2 = second_rect

                        entry = {
                            "step": i,
                            "action": action_type,
                            "start_vertices": [x1, y1, x1 + w1, y1 + h1],
                            "start_center": [x1 + w1 // 2, y1 + h1 // 2],
                            "end_vertices": [x2, y2, x2 + w2, y2 + h2],
                            "end_center": [x2 + w2 // 2, y2 + h2 // 2]
                        }
                        self.all_coords_entries.append(entry)
                else:
                    # 单框动作
                    if isinstance(rect_info, tuple) and len(rect_info) == 4:
                        x, y, w, h = rect_info
                        entry = {
                            "step": i,
                            "action": action_type,
                            "vertices": [x, y, x + w, y + h],
                            "center": [x + w // 2, y + h // 2]
                        }
                        self.all_coords_entries.append(entry)
            except Exception as e:
                print(f"提取步骤 {i} 的坐标信息时出错: {e}")

        # 轮次边界立即落盘，不靠防抖
        self._write_draft_now()

    def schedule_draft_save(self):
        """重启防抖定时器，1s 内无新变化后写 draft"""
        self.sidebar.set_draft_saving()
        self.draft_timer.stop()
        self.draft_timer.start()

    def _write_draft_now(self):
        """构造 draft 并写盘（失败仅打印日志，不打断主流程）"""
        if self.gui_number is None:
            return
        if not self.steps and not self.rounds:
            return

        def to_list(value):
            # tuple 递归转 list，兼容 () 与嵌套双框结构
            if isinstance(value, tuple):
                return [to_list(v) for v in value]
            if isinstance(value, list):
                return [to_list(v) for v in value]
            return value

        current_steps = []
        for step in self.steps:
            if "data" in step:
                step_data = step["data"]
            else:
                step_data = step["editor"].get_data()
                step_data["observation"]["screenshot"] = step["screenshot_filename"]
            current_steps.append({
                "screenshot_filename": step["screenshot_filename"],
                "rect_info": to_list(step.get("rect_info")),
                "selection_type": step.get("selection_type"),
                "data": step_data
            })

        draft = {
            "gui_number": self.gui_number,
            "app_name": self.app_name,
            "task_instruction": self.task_instruction,
            "screen_info": self.screen_info,
            "app_type": self.app_type,
            "rounds": self.rounds,
            "current_steps": current_steps,
            "coords_entries": self.all_coords_entries,
            "updated_at": datetime.now().isoformat(timespec="seconds")
        }

        saved_path = self.data_manager.save_draft(draft, self.gui_number)
        # draft 写盘成功后更新看板最近自动保存时间
        if saved_path:
            self.sidebar.set_draft_saved()

    @staticmethod
    def _to_tuple(value):
        """draft 中的 list 递归转回 tuple（[]→()，嵌套 list→tuple of tuples）"""
        if isinstance(value, (list, tuple)):
            return tuple(AnnotationEditor._to_tuple(v) for v in value)
        return value

    def load_from_draft(self, draft):
        """从草稿恢复任务状态（在 show 之前调用，不触发保存/重置）
        :return: True 表示需要由调用方询问下一条指令（current_steps 为空但 rounds 非空）；False 否则
        """
        gui_number = draft.get("gui_number")
        if not gui_number:
            QMessageBox.warning(self, "恢复失败", "草稿中缺少 gui_number，无法恢复！")
            return False

        # 恢复基础状态（深拷贝避免后续编辑污染 draft）
        self.gui_number = str(gui_number)
        if draft.get("task_instruction"):
            self.task_instruction = draft.get("task_instruction", "")
        if draft.get("screen_info"):
            self.screen_info = copy.deepcopy(draft["screen_info"])
        if draft.get("app_type"):
            self.app_type = draft["app_type"]
        if draft.get("app_name"):
            self.app_name = draft["app_name"]
            self.setWindowTitle(f"GUI长步骤采标工具-macOS - {self.app_name}")
        self.rounds = copy.deepcopy(draft.get("rounds", []))
        self.all_coords_entries = copy.deepcopy(draft.get("coords_entries", []))

        current_steps = draft.get("current_steps", [])

        # 清空 stack 中除第 0 页空提示外的页面
        while self.stack_widget.count() > 1:
            widget = self.stack_widget.widget(1)
            self.stack_widget.removeWidget(widget)
            widget.setParent(None)
        self.steps = []

        # 截图缺失检查（不中断恢复）
        gui_dir = os.path.join(self.data_manager.current_dir, f"gui_{self.gui_number}")
        missing_files = []

        for i, entry in enumerate(current_steps):
            filename = entry.get("screenshot_filename", "")
            if filename and not os.path.exists(os.path.join(gui_dir, filename)):
                missing_files.append(f"步骤 {i}: {filename}")

            rect_info = self._to_tuple(entry.get("rect_info", ()))

            step_data = copy.deepcopy(entry.get("data"))
            step_editor = StepEditorWidget(step_data=step_data)
            # 必填项实时校验信号（恢复出的编辑器同样参与缺失标记）
            self._connect_editor_validation_signals(step_editor)
            # 分栏/窗口 resize 后按磁盘原图防抖重绘预览
            step_editor.preview_resize_requested.connect(
                lambda ed=step_editor: self._on_editor_preview_resize(ed)
            )

            # data 中 observation.screenshot 为空时补上文件名
            if step_data is not None:
                observation = step_data.setdefault("observation", {})
                if not observation.get("screenshot"):
                    observation["screenshot"] = filename

            self.steps.append({
                "editor": step_editor,
                "screenshot_filename": filename,
                "rect_info": rect_info,
                "selection_type": entry.get("selection_type"),
                "data": step_data,
                # 恢复的步骤均为已确认落过 draft 的，最后一步恢复后可继续编辑，统一先标已确认
                "confirmed": True
            })
            self.stack_widget.addWidget(step_editor)
            step_editor.set_step_number(i)

        if self.steps:
            last_index = len(self.steps) - 1
            self.current_step_index = last_index
            self.update_step_indicator()
            self.display_step(last_index)
        else:
            self.current_step_index = -1
            self.stack_widget.setCurrentIndex(0)
            self.update_step_indicator()

        if missing_files:
            QMessageBox.warning(
                self,
                "截图文件缺失",
                "以下步骤的截图文件在磁盘上不存在，预览将无法显示：\n\n" + "\n".join(missing_files)
            )

        # 恢复后侧栏全量重建（display_step 内的增量刷新在此之前执行，此处以全量结果为准）
        self.refresh_sidebar(fully=True)

        self.status_label.setText(f"已从草稿恢复任务（gui_{self.gui_number}）")
        # 恢复完成后排一次 draft 保存（无害）
        self.schedule_draft_save()

        # current_steps 为空但 rounds 非空：崩溃在 answer 后轮次重置、等待输入新指令时
        return not self.steps and bool(self.rounds)

    def show_new_task_dialog(self):
        """显示是否创建新任务的对话框"""
        # 确保主窗口在前台
        self.restore_window()

        reply = QMessageBox.question(
            self,
            "创建新任务",
            "是否开始一个新的标注任务？\n\n是：创建新任务（gui_000002...）\n否：返回任务初始化菜单",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # 先保存当前任务的所有轮次
            self.finish_all_annotation()
            # 然后创建新任务
            self.create_new_task()
        else:
            # 保存当前任务并返回初始化菜单
            self.finish_all_annotation(close_after_save=False)

    def create_new_task(self):
        """创建新的标注任务（新的 gui 编号）"""
        from PyQt5.QtWidgets import QInputDialog

        # 确保主窗口在前台
        self.restore_window()

        new_instruction, ok = QInputDialog.getText(
            self,
            "新任务指令",
            "请输入新任务的第一个指令：",
            QLineEdit.Normal,
            ""
        )

        if ok and new_instruction.strip():
            # 清空所有轮次数据
            self.rounds = []

            # 清空坐标收集数据
            self.all_coords_entries = []

            # 更新任务指令
            self.task_instruction = new_instruction.strip()

            # 重置状态并获取新的 gui_number
            self.reset_for_new_task()
            self.gui_number = self.data_manager.get_next_gui_number()

            self.status_label.setText(f"新任务开始 - 指令: {self.task_instruction}")
        else:
            # 用户取消了，关闭窗口
            self.close()

    def start_new_round(self, from_answer=False):
        """开始新一轮任务（同一 gui 文件夹内）
        :param from_answer: 是否从 answer 动作触发，如果是则取消时不保存退出
        """
        # 弹出对话框让用户输入新的 instruction
        from PyQt5.QtWidgets import QInputDialog

        # 确保主窗口在前台
        self.restore_window()

        new_instruction, ok = QInputDialog.getText(
            self,
            "新任务指令",
            "请输入下一个任务的指令：",
            QLineEdit.Normal,
            ""
        )

        if ok and new_instruction.strip():
            # 更新任务指令
            self.task_instruction = new_instruction.strip()

            # 重置状态（但保持 gui_number 不变，共用同一个文件夹）
            self.reset_for_new_task()

            self.status_label.setText(f"新任务开始 - 指令: {self.task_instruction}")
        else:
            # 用户取消了
            if from_answer:
                # 如果是从 answer 动作触发，只关闭弹窗，不保存退出
                self.status_label.setText("已取消新任务")
            else:
                # 否则完成所有标注
                self.finish_all_annotation()

    def finish_all_annotation(self, close_after_save=True):
        """完成所有轮次的标注并保存
        :param close_after_save: 保存后是否关闭窗口。False 时返回初始化菜单
        """
        # 先保存当前轮次（如果有的话）
        if len(self.steps) > 0:
            self.save_current_round()

        # 保存所有轮次的数据
        if len(self.rounds) == 0:
            QMessageBox.warning(self, "警告", "没有可保存的数据！")
            return

        # 构建完整的 JSON 结构（包含平台信息）
        merged_data = self.data_manager.create_initial_json_structure(
            self.rounds[0].get("instruction", ""),  # 使用第一个指令作为示例
            self.screen_info,
            self.app_type  # 传入应用类型
        )

        # 清空默认的 messages，重新构建
        merged_data["messages"] = []

        # 合并所有轮次到一个 messages 数组
        for round_data in self.rounds:
            # 添加 user 消息（instruction）
            merged_data["messages"].append({
                "role": "user",
                "instruction": round_data["instruction"]
            })

            # 添加 assistant 消息（trajectory）
            merged_data["messages"].append({
                "role": "assistant",
                "trajectory": round_data["trajectory"]
            })

        # 保存合并后的 JSON 文件
        filepath = self.data_manager.save_json_data(merged_data, self.gui_number)

        # 保存拉框坐标到独立 JSON 文件
        coords_filepath = None
        if self.all_coords_entries:
            try:
                coords_filepath = self.data_manager.save_coords_json(
                    self.all_coords_entries, self.gui_number
                )
            except Exception as e:
                print(f"保存坐标 JSON 文件时出错: {e}")

        if filepath:
            # 最终数据已成功落盘，删除增量草稿（关窗应急保存路径不删，保留崩溃恢复能力）
            self.data_manager.delete_draft(self.gui_number)

            msg = f"所有轮次数据已保存到:\n{filepath}"
            if coords_filepath:
                msg += f"\n拉框坐标已保存到:\n{coords_filepath}"
            QMessageBox.information(
                self,
                "保存成功",
                msg
            )
            if close_after_save:
                self.close()
            else:
                self._return_to_init_menu()
        else:
            QMessageBox.critical(self, "错误", "保存 JSON 失败！")

    def finish_annotation(self):
        """完成标注并保存（已废弃，由 show_terminate_dialog 替代）"""
        pass

    def reset_for_new_task(self):
        """重置状态以开始新任务（保持 gui_number 不变）"""
        self.steps = []
        self.current_step_index = -1
        # 注意：不重置 gui_number，整个任务共用同一个文件夹

        # 清空 stack widget（保留空页面）
        while self.stack_widget.count() > 1:
            widget = self.stack_widget.widget(1)
            self.stack_widget.removeWidget(widget)

        self.stack_widget.setCurrentIndex(0)
        self.update_step_indicator()
        # 新轮次/新任务：清空侧栏步骤列表与看板（任务指令可能已更新）
        self.refresh_sidebar(fully=True)
        # 隐藏撤销按钮
        self.undo_btn.hide()
        self.status_label.setText("就绪 - 按 Control+Q 给下一步截图")

    def closeEvent(self, event):
        """窗口关闭事件 — 确保未保存的数据在关闭前写入 JSON"""
        # 如果有未保存的步骤数据，先保存当前轮次再整体写入 JSON
        if len(self.steps) > 0 or len(self.rounds) > 0:
            try:
                self._save_all_data_before_close()
            except Exception as e:
                print(f"关闭前保存数据失败: {e}")

        event.accept()

    def _save_all_data_before_close(self):
        """关闭窗口前保存所有数据到 JSON 文件（内部方法，不弹窗）"""
        # 先保存当前轮次（如果有未落盘的步骤）
        if len(self.steps) > 0:
            self.save_current_round()

        if len(self.rounds) == 0:
            return

        # 构建完整的 JSON 结构
        merged_data = self.data_manager.create_initial_json_structure(
            self.rounds[0].get("instruction", ""),
            self.screen_info,
            self.app_type
        )

        merged_data["messages"] = []
        for round_data in self.rounds:
            merged_data["messages"].append({
                "role": "user",
                "instruction": round_data["instruction"]
            })
            merged_data["messages"].append({
                "role": "assistant",
                "trajectory": round_data["trajectory"]
            })

        # 保存 JSON（失败时只打印日志，不阻塞关闭）
        filepath = self.data_manager.save_json_data(merged_data, self.gui_number)
        if filepath:
            print(f"窗口关闭前已保存数据到: {filepath}")
        else:
            print("窗口关闭前保存 JSON 失败")

        # 保存拉框坐标
        if self.all_coords_entries:
            try:
                self.data_manager.save_coords_json(self.all_coords_entries, self.gui_number)
            except Exception as e:
                print(f"关闭前保存坐标 JSON 失败: {e}")

    def _return_to_init_menu(self):
        """返回任务初始化菜单"""
        if self.init_window:
            self.init_window.show()
            self.init_window.raise_()
            self.init_window.activateWindow()
        self.close()
