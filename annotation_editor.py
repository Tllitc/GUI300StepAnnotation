#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
标注编辑器模块
负责动作标注的编辑、分页显示、撤销等功能
跨平台支持：Windows / macOS
"""

import sys
import os
import re
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
# center ↔ coordinate 的判定口径与离线修复脚本、测试不变量 INV-14 共用同一份
# 实现（tools/coords_center_repair.py 只依赖标准库，可安全 import），
# 避免三处各写一遍比较逻辑后再次漂移
from tools.coords_center_repair import (COORD_CENTER_TOL, coord_pair,
                                        entry_coordinate_mismatch)

# 需要拉框坐标的动作全集。校验层（validate_step_at：要求用户必须标注）与
# coords 采集层（_collect_coords_entries：决定哪些标注顶点写进 coords 文件）
# 共用同一常量，杜绝两处口径漂移（B6：scroll 被校验层要求拉框却不被采集层
# 收集，用户按要求标的顶点在交付数据中静默丢失）
COORD_ACTION_TYPES = {"left_click", "double_click", "triple_click",
                      "right_click", "middle_click", "mouse_move",
                      "left_click_drag", "type", "scroll"}


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
                # 获取按下的键
                key = event.key()
                key_name = self.get_key_name(key)

                if key_name:
                    # 将键名填入当前焦点的文本框
                    self.current_keys_input.setText(key_name.lower())
                    # 返回True表示事件已处理，不再传递
                    return True

        # 其他事件交给父类处理
        return super().eventFilter(obj, event)

    def get_key_name(self, key):
        """将Qt键码转换为键名"""
        from PyQt5.QtCore import Qt

        # 特殊键映射
        key_map = {
            Qt.Key_Meta: "win",
            Qt.Key_Control: "ctrl",
            Qt.Key_Alt: "alt",
            Qt.Key_Shift: "shift",
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

        # 添加坐标（无坐标语义的动作不写 coordinate 键；B12：豁免名单曾缺
        # answer_terminate，使该动作交付数据里多出无意义的 coordinate:[0,0]）
        if action_type not in ["open_app", "open_url", "terminate",
                               "answer", "answer_terminate", "wait", "key"]:
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
            except (ValueError, TypeError) as e:
                # B12：坐标文本无法解析时不再伪造 [0,0] 写进交付数据，改为缺键，
                # 由 validate_step_at 的「坐标缺失」拦截，同时留下诊断痕迹
                print(f"步骤坐标解析失败（动作 {action_type}）：{e}")

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
        self.setWindowTitle(f"GUI长步骤采标工具-Windows - {app_name}")
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

        # 生命周期标志：窗口正在关闭/已清理时为 True，截图入口据此拒绝响应，
        # 避免“已返回主菜单的旧窗口”仍响应全局快捷键而成为幽灵窗口
        self._is_closing = False
        # 防止截图流程重入：隐藏窗口到截图遮罩弹出期间忽略重复的 Ctrl+Q
        self._capture_in_flight = False
        # 原图重新拉框弹窗与其目标步骤下标（编辑已完成任务时使用）
        self.relabel_window = None
        self._relabel_step_index = None
        # B2 轮次切换门闩：answer/terminate 落轮后用 singleShot(300) 延后弹新轮对话框。
        # 这 300ms 内 self.steps 已被清空而 self.task_instruction 还是旧指令，此时若响应
        # 截图/确认（含全局快捷键 Ctrl+Q），会用同一条指令再凑出一轮并 append 进 rounds，
        # 产出两条 instruction 完全相同的重复轮次。置 True 期间所有采集/编辑入口一律早退。
        self._round_transition_pending = False
        # DT-8 相关：stack 页序不变式曾被打穿时置 True，供 undo/delete 等危险操作拦截
        self._stack_invariant_broken = False
        # 最终数据已成功落盘标志：finish_all_annotation 成功后置 True，
        # 使随后的 closeEvent 不再对同一批数据二次保存
        self._final_data_saved = False
        # 5.3（B7）临时抑制草稿落盘：创建新任务时 gui_number 尚未换新，
        # 此间任何草稿写入都会落到上一个已交付任务的目录里
        self._suppress_draft_write = False

        # 「已完成任务再编辑」模式状态
        self._edit_mode = False
        self._completed_json = None    # 原始最终 JSON 深拷贝，保存时以其为基底重建
        self._edit_round_index = 0     # 正在编辑的轮次下标
        self._coords_rounds = []       # 每轮一份 coords 列表（与 self.rounds 等长）
        self._original_coords_exist = False
        # 编辑态 hydration 检出的「盘上 bbox 与 coordinate 不一致」清单，
        # 元素为 (步序, 动作中文名, issue, 差异说明)；issue ∈ absent/mismatch/no_box
        self._coord_issues = []

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

        # 编辑已完成任务时可见：不重新截图，直接在磁盘原图上重新拖框
        self.relabel_btn = QPushButton("在原图上重新拉框")
        self.relabel_btn.setStyleSheet("QPushButton { background-color: #9C27B0; color: white; }")
        self.relabel_btn.clicked.connect(self.relabel_current_step)
        self.relabel_btn.hide()
        toolbar.addWidget(self.relabel_btn)

        # 根据平台显示对应快捷键
        if sys.platform == 'darwin':
            screenshot_hk = "Cmd"
            save_hk = "Cmd"
        else:
            screenshot_hk = "Ctrl"
            save_hk = "Ctrl"
        capture_btn = QPushButton(f"给下一步截图 ({screenshot_hk}+Q)")
        capture_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; }")
        capture_btn.clicked.connect(self.start_capture)
        toolbar.addWidget(capture_btn)

        save_btn = QPushButton("确认")
        save_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
        save_btn.clicked.connect(self.confirm_button_clicked)
        toolbar.addWidget(save_btn)

        # 编辑已完成任务时可见：校验当前轮并写回最终 JSON / coords
        self.save_edit_btn = QPushButton("保存修改")
        self.save_edit_btn.setStyleSheet("QPushButton { background-color: #3F51B5; color: white; }")
        self.save_edit_btn.clicked.connect(lambda: self.save_edited_round(False))
        self.save_edit_btn.hide()
        toolbar.addWidget(self.save_edit_btn)

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

        # 侧栏导航快捷键：PageUp/PageDown 上一步/下一步（不与全局 Ctrl+Q 及输入框常用键冲突）
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

        # 2. 坐标类动作（全屏截图豁免）：与 coords 采集层取同一常量（B6）
        coord_actions = COORD_ACTION_TYPES
        fullscreen = step.get("selection_type") == "fullscreen"
        if action_type in coord_actions and not fullscreen:

            def _is_zero(line_edit):
                # 空、非数字或 0 均视为缺失（与 get_data 保持一致：B12 后坐标解析
                # 不了就不写 coordinate 键，不再伪造 [0,0] 蒙混过关）
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

    def cleanup_resources(self):
        """窗口结束生命周期时的统一资源清理（幂等，可重复调用）。

        - 断开本实例与全局快捷键信号的连接，确保不再响应 Ctrl+Q；
        - 停止 draft / 校验防抖定时器，避免幽灵实例上的延迟回调；
        - 关闭可能残留的截图遮罩窗口。
        """
        if self._is_closing:
            return
        self._is_closing = True

        if self.hotkey_listener is not None:
            try:
                self.hotkey_listener.screenshot_triggered.disconnect(self.start_capture)
            except (TypeError, RuntimeError):
                # 信号未连接或底层对象已销毁时忽略
                pass

        try:
            self.draft_timer.stop()
            self.validation_timer.stop()
        except (AttributeError, RuntimeError):
            pass

        for attr in ("capture_window", "reference_capture_window", "relabel_window"):
            win = getattr(self, attr, None)
            if win is not None:
                try:
                    win.close()
                except RuntimeError:
                    pass
                setattr(self, attr, None)

    def recapture_current_step(self):
        """重新截取当前步骤的截图，如果没有步骤则开始第一个截图"""
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if self._is_closing or self._capture_in_flight:
            return
        if self.current_step_index < 0 or self.current_step_index >= len(self.steps):
            # 没有步骤时，开始第一个截图
            self.start_capture()
            return

        # 标记截图流程进行中，防止重入
        self._capture_in_flight = True
        # 先将窗口设为完全透明（避免 hide() 动画过程被截图捕捉），再隐藏
        self.setWindowOpacity(0.0)
        self.hide()

        # 延迟确保窗口完全隐藏后再截图
        QTimer.singleShot(350, self.show_recapture_window)

    def show_recapture_window(self):
        """显示重新截图窗口"""
        if self._is_closing:
            self._capture_in_flight = False
            return
        self.capture_window = ScreenshotCaptureWindow()
        self.capture_window.capture_completed.connect(self.on_recapture_completed)
        self.capture_window.show()

    def relabel_current_step(self):
        """编辑已完成任务：在该步磁盘原截图上重新拖框（不重新截图、不覆盖 PNG）"""
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if self._is_closing or self._capture_in_flight:
            return
        if not self._edit_mode:
            return
        if not (0 <= self.current_step_index < len(self.steps)):
            self.status_label.setText("没有可重新拉框的步骤")
            return
        filename = self.steps[self.current_step_index]["screenshot_filename"]
        if not filename:
            self.status_label.setText("该步骤没有截图文件，请使用[重新截图]")
            return
        background = self.data_manager.load_screenshot(self.gui_number, filename)
        if background is None or background.isNull():
            self.status_label.setText(f"截图文件缺失（{filename}），请使用[重新截图]")
            return
        # 与所有采集入口共用同一门闩（不新增并行标志）
        self._capture_in_flight = True
        self._relabel_step_index = self.current_step_index
        self.relabel_window = ScreenshotCaptureWindow(background_pixmap=background)
        self.relabel_window.capture_completed.connect(self.on_relabel_completed)
        self.relabel_window.show()

    def on_relabel_completed(self, original_pixmap, marked_pixmap, rect_info, selection_type):
        """原图重新拉框完成回调：只改内存中的标注与坐标，不写任何图片文件"""
        # 第一行无条件复位门闩，任何路径都不泄漏
        self._capture_in_flight = False
        if self._is_closing:
            return
        index = self._relabel_step_index
        self._relabel_step_index = None
        self.relabel_window = None  # closeEvent 仍会兜底清理同名属性
        if selection_type == "cancelled" or not rect_info:
            self.status_label.setText("重新拉框已取消，标注框保持不变")
            return
        if not (0 <= index < len(self.steps)):
            return
        if index != self.current_step_index:
            # 弹窗期间不预期切步，仍防御式对齐
            self.display_step(index)
        current_step = self.steps[index]
        editor = current_step["editor"]
        filename = current_step["screenshot_filename"]
        # 复用与重新截图同一口径的初始化（双框自动切「拖拽」并归一化 selection_type）
        normalized_type = self._init_editor_from_capture(
            editor, marked_pixmap, rect_info, selection_type
        )
        current_step["rect_info"] = rect_info
        current_step["selection_type"] = normalized_type
        editor.set_preview_meta(filename, rect_info, normalized_type)
        # 让写回走实时 editor.get_data() 而不是旧快照
        current_step.pop("data", None)
        # marked_pixmap 是缩放显示图，改从磁盘原图重绘，避免预览停留在低分辨率
        self._on_editor_preview_resize(editor)
        self.update_undo_button_visibility()
        # 框已变化：失效该步缩略图缓存并重载条目（动作类型可能随拖拽框变化）
        self.sidebar.invalidate_thumb(index)
        item = self.sidebar.item_widgets[index] \
            if index < len(self.sidebar.item_widgets) else None
        if item is not None:
            item.thumb_loaded = False
            self.sidebar.request_thumb(index, high_priority=True)
            self.refresh_step_item(index)
        self.status_label.setText(f"已在原图上重新拉框 {filename}（请点击[保存修改]写回）")

    def on_recapture_completed(self, original_pixmap, marked_pixmap, rect_info, selection_type):
        """重新截图完成回调"""
        # 截图遮罩已关闭，解除重入守卫
        self._capture_in_flight = False
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
            # DT-7 修复：复用 _init_editor_from_capture 完成预览/坐标/双框归一化，
            # 保证与新建步骤的口径一致（双框统一为 selection_type="drag"、自动选"拖拽"动作）
            editor = current_step["editor"]
            normalized_type = self._init_editor_from_capture(
                editor, marked_pixmap, rect_info, selection_type
            )
            current_step["rect_info"] = rect_info
            current_step["selection_type"] = normalized_type
            editor.set_preview_meta(filename, rect_info, normalized_type)
            # 让下次 _write_draft_now 走实时 editor.get_data() 而不是旧快照
            current_step.pop("data", None)

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
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if self._is_closing or self._capture_in_flight:
            return
        self._capture_insert_after = None
        self._hide_for_capture()

    def start_insert_capture(self):
        """在当前步骤之后插入一步截图（插入模式）"""
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if self._is_closing or self._capture_in_flight:
            return
        if not (0 <= self.current_step_index < len(self.steps)):
            return
        # 记录插入锚点：新步将插入到该下标 +1 位置
        self._capture_insert_after = self.current_step_index
        self._hide_for_capture()

    def _hide_for_capture(self):
        """截图前隐藏主窗口（追加/插入两路径共用）"""
        # 标记截图流程进行中，防止隐藏到遮罩弹出期间重复响应 Ctrl+Q
        self._capture_in_flight = True
        # 先将窗口设为完全透明（避免 hide() 动画过程被截图捕捉），再隐藏
        self.setWindowOpacity(0.0)
        self.hide()

        # 延迟确保窗口完全隐藏后再截图
        QTimer.singleShot(350, self.show_capture_window)

    def show_capture_window(self):
        """显示截图窗口"""
        if self._is_closing:
            self._capture_in_flight = False
            return
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
        # 截图遮罩已关闭，解除重入守卫（取消/成功两条路径都会走到这里）
        self._capture_in_flight = False
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
        """校验 stack 页序不变式

        DT-8 修复：异常时除打印外，同时置 self._stack_invariant_broken=True，
        使 undo/delete 等危险操作可以先做前置拦截，防止"stack 页序已乱还 widget(count-1)"
        删错编辑器/删错文件的连锁破坏。
        """
        try:
            assert self.stack_widget.count() == len(self.steps) + 1, \
                f"stack 页数 {self.stack_widget.count()} != 步数+1 {len(self.steps) + 1}"
            for i, step in enumerate(self.steps):
                assert self.stack_widget.widget(i + 1) is step["editor"], \
                    f"第 {i} 步对应的 stack 页不是其编辑器（页下标 {i + 1}）"
            # 全部通过：复位标志
            self._stack_invariant_broken = False
        except AssertionError as e:
            self._stack_invariant_broken = True
            print(f"[INV] stack 页序不变式校验失败: {e}（已置 _stack_invariant_broken=True）")

    def _drop_stack_page(self, index):
        """摘除并真正销毁 stack 第 index 页（B15：removeWidget 只脱离布局，不销毁对象）

        removeWidget 之后 widget 仍是 QStackedWidget 的子对象；再 setParent(None) 会让它
        变成不可见的游离顶层窗口 —— 对象连同其中的截图 pixmap 一直留在内存里，
        删步/撤销/重置做得越多泄漏越严重。步骤页已从 self.steps 弹出（不再有任何引用）时，
        必须 deleteLater 把它交给事件循环销毁。

        注意：_rebuild_stack_page_order 的摘页属于"摘后立刻按新序挂回"，widget 仍由
        self.steps 持有，绝不能走这里。
        """
        widget = self.stack_widget.widget(index)
        if widget is None:
            return
        self.stack_widget.removeWidget(widget)
        widget.setParent(None)
        widget.deleteLater()

    def _drop_all_step_pages(self):
        """销毁除第 0 页空提示页以外的全部步骤页（整体清空现场时用）

        现场整体重建时，上一现场检出的 coords 不一致清单也随之失效：不跟着清空
        的话，草稿恢复/切轮后残留的旧记录会被 A5 写回守卫当作「本轮未触碰的
        继承性缺陷」而放过，审计范围出现空洞。
        """
        self._coord_issues = []
        while self.stack_widget.count() > 1:
            self._drop_stack_page(1)

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
        """删除指定步骤的磁盘截图文件，失败仅打印不阻断主流程。

        DT-6 修复：删除前先检查 filename 是否仍被 self.rounds 中某条 trajectory
        引用（轮次已结束、trajectory 已落 rounds 时不能删，否则历史轮次引用失效）。
        """
        try:
            if self.gui_number is None:
                return
            # DT-6: 跳过被 rounds 引用的文件
            for round_data in self.rounds:
                for traj in round_data.get("trajectory", []):
                    obs = traj.get("observation") or {}
                    if obs.get("screenshot") == filename:
                        print(f"_delete_screenshot_file: {filename!r} 仍被历史轮次引用，跳过删除")
                        return
            gui_dir = os.path.join(self.data_manager.current_dir, f"gui_{self.gui_number}")
            filepath = os.path.join(gui_dir, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            print(f"删除截图失败: {e}")

    def delete_current_step(self):
        """删除当前步骤：二次确认后删除步骤/页面/磁盘截图，后续步骤自动前移重编号"""
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
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

        # 删除 stack 对应页并真正销毁（+1 因为第 0 页是空提示页）
        self._drop_stack_page(index + 1)

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
        """撤销上一步

        DT-9 修复：只有当当前步就是最后一步时才允许撤销（与按钮可见性约束一致）。
        非末步被触发时（可见性被破坏）弹出提示并拒绝执行，避免出现
        "steps.pop() 删末尾步但 current_step_index 仍指向中间步" 的模型错位。
        同时 DT-8 修复：stack 不变式已破时也拒绝操作，防止删错编辑器。
        """
        # B2：切轮窗口内不得删改本轮已落轮的数据
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if len(self.steps) == 0:
            return
        # DT-9: 非末步拦截
        if self.current_step_index != len(self.steps) - 1:
            QMessageBox.warning(
                self, "撤销提示",
                f"当前停在第 {self.current_step_index + 1} 步，只能撤销最后一步（第 {len(self.steps)} 步）。\n"
                f"请先跳到最后一步再撤销。"
            )
            return
        # DT-8: stack 不变式已破，拒绝危险操作
        if getattr(self, "_stack_invariant_broken", False):
            QMessageBox.warning(
                self, "数据异常",
                "内部页序状态不一致，已自动拦截撤销操作以避免数据破坏。"
            )
            return

        reply = QMessageBox.question(
            self,
            "确认撤销",
            f"确定要撤销最后一步（第 {len(self.steps)} 步）吗？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # 移除最后一个步骤
            removed = self.steps.pop()

            # 从 stack widget 移除并销毁（撤销的永远是最后一页）
            self._drop_stack_page(self.stack_widget.count() - 1)

            # 删除截图文件（失败仅打印不阻断），并清理其缩略图缓存
            removed_filename = removed.get("screenshot_filename", "")
            self._delete_screenshot_file(removed_filename)
            self.sidebar.remove_thumb_cache_by_filename(removed_filename)

            # 调整当前索引：本来就是末步，撤销后就是新的末步或 -1
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
        # B2：切轮窗口内的确认会被旧指令再次落轮，直接拒绝
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
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
        # B2：answer/terminate 落轮后的 300ms 切轮窗口内拒绝再次落轮
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if self.current_step_index < 0 or self.current_step_index >= len(self.steps):
            QMessageBox.warning(self, "警告", "没有可保存的步骤！")
            return

        # 获取当前编辑器
        current_step = self.steps[self.current_step_index]
        editor = current_step["editor"]

        # 编辑已完成任务：确认只落当前步数据，不触发 answer/terminate 的轮次迁移
        if self._edit_mode:
            step_data = editor.get_data()
            step_num = self.get_current_step_number()
            step_data_with_step = {"step": step_num}
            step_data_with_step.update(step_data)
            step_data = step_data_with_step
            step_data["observation"]["screenshot"] = current_step["screenshot_filename"]
            # 与原 data 合并：受保护下游字段（CoT/observation.ui_tree_segment 等）为空值
            # 时保留原值，避免编辑器重建字典把下游字段清空；新增步骤无原 data 时直接写入
            original_data = current_step.get("data")
            if isinstance(original_data, dict):
                step_data = self._merge_step_with_original(step_data, original_data)
            current_step["data"] = step_data
            current_step["confirmed"] = True
            self.status_label.setText(f"步骤 {step_num} 已保存（编辑模式）")
            self.update_step_indicator()
            self.refresh_step_item(self.current_step_index)
            self.refresh_dashboard()
            return

        # 获取编辑数据
        step_data = editor.get_data()

        # 设置步骤编号（放在首部）
        step_num = self.get_current_step_number()
        step_data_with_step = {"step": step_num}
        step_data_with_step.update(step_data)
        step_data = step_data_with_step

        # 设置截图文件名
        step_data["observation"]["screenshot"] = current_step["screenshot_filename"]

        # 编辑已存在步骤（草稿/续采）：与原快照合并，受保护下游字段空值保留原值；
        # 新增步骤无原 data，直接写入
        original_data = current_step.get("data")
        if isinstance(original_data, dict):
            step_data = self._merge_step_with_original(step_data, original_data)

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
            if not self.save_current_round():
                # B14：本轮缺少任务指令且用户未补齐 → 拒绝落轮。此时绝不能清空
                # steps，否则整轮轨迹会静默消失（比指令错乱更严重）
                return
            # 清空步骤列表，避免后续重复保存
            self.steps = []
            # 升起门闩，300ms 切轮窗口内禁止采集/编辑（B2）
            self._round_transition_pending = True
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
            if not self.save_current_round():
                # B14：同上，缺指令被拒绝落轮时保持 steps 原样，等用户补齐指令
                return
            # 清空步骤列表，避免 finish_all_annotation 重复保存
            self.steps = []

            # 升起门闩：这条分支同样延后 300ms 弹后续对话框，窗口内被再次确认/截图
            # 会用同一条旧指令再落一轮，并让 show_new_task_dialog 弹出两次（B2）
            self._round_transition_pending = True
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
            if not self.save_current_round():
                return  # B14：缺指令且未补齐，不落轮也不切轮，保持现场
            self.start_new_round()
        else:
            # 询问是否创建新的标注任务
            self.show_new_task_dialog()

    def _collect_coords_entries(self):
        """按当前 self.steps 现场重建本轮 coords 条目列表（step 为轮内 0 起连续下标）"""
        entries = []
        # B6：改用 COORD_ACTION_TYPES。旧写法缺 scroll，导致校验层要求拉框的
        # scroll 步顶点在落盘时被丢弃
        coord_action_types = COORD_ACTION_TYPES

        for i, step in enumerate(self.steps):
            rect_info = step.get("rect_info")
            # 编辑态 hydration 判定盘上 bbox 与 coordinate 不一致/缺失（absent/mismatch）：
            # 既不采信也不丢弃，按当前步序重编号后原样保留，避免「打开看一眼就丢数据」。
            # 动作已被改成非坐标类型时不走此分支，条目应被丢弃（语义正确）
            orig = step.get("orig_coord_entry")
            if not rect_info and isinstance(orig, dict):
                editor = step["editor"]
                orig_action = editor.action_type_mapping.get(
                    editor.action_type_combo.currentText(),
                    editor.action_type_combo.currentText())
                if orig_action in coord_action_types:
                    entries.append({**copy.deepcopy(orig), "step": i})
                continue
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

                        entries.append({
                            "step": i,
                            "action": action_type,
                            "start_vertices": [x1, y1, x1 + w1, y1 + h1],
                            "start_center": [x1 + w1 // 2, y1 + h1 // 2],
                            "end_vertices": [x2, y2, x2 + w2, y2 + h2],
                            "end_center": [x2 + w2 // 2, y2 + h2 // 2]
                        })
                else:
                    # 单框动作
                    if isinstance(rect_info, tuple) and len(rect_info) == 4:
                        x, y, w, h = rect_info
                        entries.append({
                            "step": i,
                            "action": action_type,
                            "vertices": [x, y, x + w, y + h],
                            "center": [x + w // 2, y + h // 2]
                        })
            except Exception as e:
                print(f"提取步骤 {i} 的坐标信息时出错: {e}")

        return entries

    def _prompt_missing_instruction(self):
        """本轮缺少任务指令时弹窗补齐；返回 False 表示用户仍未给出指令。

        B14：取消新轮后 task_instruction 被置空（见 start_new_round 取消分支）。
        放任空指令落轮的话，新一轮轨迹会静默挂到上一轮的旧指令上，事后无从
        分辨哪段轨迹属于哪条指令，因此落轮前必须显式补齐，补齐失败由调用方拒绝落轮。
        """
        from PyQt5.QtWidgets import QInputDialog

        self.restore_window()
        new_instruction, ok = QInputDialog.getText(
            self,
            "任务指令",
            "当前轮次缺少任务指令，请输入本轮对应的指令：",
            QLineEdit.Normal,
            ""
        )
        if ok and new_instruction.strip():
            self.task_instruction = new_instruction.strip()
            return True
        self.status_label.setText("缺少任务指令 - 本轮未落轮，请补齐指令后重新确认")
        return False

    def save_current_round(self, prompt_instruction=True):
        """保存当前轮次的数据到 rounds 列表
        :param prompt_instruction: 指令缺失时是否弹窗补齐；关闭等无人值守路径传 False，
            只做静默拒绝，不在退出过程中弹模态框
        :return: True 表示本轮已落入 rounds；False 表示因缺少任务指令被拒绝落轮，
            调用方必须保持 steps 原样并中止后续的清空/切轮动作
        """
        if not (self.task_instruction or "").strip():
            if not prompt_instruction or not self._prompt_missing_instruction():
                return False
        # 说明（删除/插入对齐）：本方法是轮次结束时唯一的落盘点，trajectory 与 coords
        # entries 都在此刻按当时 self.steps 的 enumerate 下标 i 现场重建。轮次中途的
        # 删除/插入只会改变 self.steps 顺序，任何 data 快照里旧的 "step" 不被读取
        # （有快照的分支直接沿用快照对象，其 step 已在删除/插入时同步重编号），
        # 因此最终写出的 step 一定与重排后的新下标一致；all_coords_entries 也没有
        # 轮次中途缓存路径（全项目仅本方法 append）。
        # 收集所有步骤数据
        trajectory = []
        for i, step in enumerate(self.steps):
            # DT-4 修复：一律取实时 editor.get_data() 作为本轮轨迹，不优先用陈旧的
            # step["data"] 快照（续采后用户编辑但未重新 confirm/save 时，旧快照会
            # 被沿用导致最终 JSON 静默丢数据）。step 字段统一在本次重建时补齐。
            editor = step["editor"]
            step_data = copy.deepcopy(editor.get_data())
            step_data.setdefault("observation", {})["screenshot"] = step["screenshot_filename"]
            # 与旧 data 快照合并：编辑器重建字典时空值的受保护下游字段
            # （CoT/observation.ui_tree_segment/active_window、动作 element/status）
            # 保留快照原值；新增步骤无快照则跳过
            original_data = step.get("data")
            if isinstance(original_data, dict):
                step_data = self._merge_step_with_original(step_data, original_data)
                step_data.setdefault("observation", {})["screenshot"] = step["screenshot_filename"]
            # step 字段放在首部，值为当前 enumerate 下标
            existing_step = step_data.pop("step", None)
            if existing_step != i:
                step_data = {"step": i, **step_data}
            else:
                step_data["step"] = i
            trajectory.append(step_data)

        # 添加到轮次列表（只保存 instruction 和 trajectory）
        self.rounds.append({
            "instruction": self.task_instruction,
            "trajectory": trajectory
        })

        # 提取需要坐标的步骤，收集其拉框顶点和中心点坐标
        # 4.2（B4/B18）落轮时给每个 coords 条目注入 round：轮内 step 下标每轮都从 0
        # 起重编，扁平坐标文件里 (step, action) 无法唯一归属。早前不写 round，读取
        # 只能靠「step 变小则切段」猜测，只要有一轮一个坐标步都没有、或两轮 step
        # 同签名，就整段错位把顶点配到别的轮次上。iOS 在序列化边界注入；本端正常
        # 路径只保留扁平 all_coords_entries（rounds 内不存坐标分组），故在唯一的
        # 追加点上当前轮下标，口径等价。条目由 _collect_coords_entries 现场新建，
        # 就地加键不会别名到步骤数据。
        round_index = len(self.rounds) - 1
        for coords_entry in self._collect_coords_entries():
            coords_entry["round"] = round_index
            self.all_coords_entries.append(coords_entry)

        # DT-2 修复：不再在 save_current_round 内部立即 _write_draft_now()。
        # 调用方（save_current_step / finish_all_annotation / closeEvent）会在 steps 状态就绪后
        # 通过 schedule_draft_save 或 delete_draft 处理。这样避免了"rounds 已追加、steps 还没清"
        # 的瞬间 draft 同时包含本轮轨迹和 current_steps，防止崩溃恢复后同一轮被重复写入最终 JSON。
        return True

    def schedule_draft_save(self):
        """重启防抖定时器，1s 内无新变化后写 draft"""
        # 编辑已完成任务时绝不生成 draft，避免已保存任务出现在「继续未完成任务」
        if self._edit_mode:
            return
        self.sidebar.set_draft_saving()
        self.draft_timer.stop()
        self.draft_timer.start()

    def _write_draft_now(self):
        """构造 draft 并写盘（失败仅打印日志，不打断主流程）"""
        # 编辑已完成任务模式下不写草稿（关窗写回最终 JSON 由 closeEvent 处理）
        if self._edit_mode:
            return
        if self._suppress_draft_write:
            # 5.3（B7）新任务切换窗口：旧 gui_number 已交付，不得再往它的目录写草稿
            return
        if self.gui_number is None:
            return
        # DT-1 修复：即使 steps 和 rounds 皆空，只要 gui_number 还在（即用户已有任务），
        # 也必须落一份空状态 draft 覆盖磁盘上可能残留的旧草稿，
        # 防止续采时已删步骤"复活"。只有在 gui_number 也不存在（完全没有任务）时才跳过。

        def to_list(value):
            # tuple 递归转 list，兼容 () 与嵌套双框结构
            if isinstance(value, tuple):
                return [to_list(v) for v in value]
            if isinstance(value, list):
                return [to_list(v) for v in value]
            return value

        current_steps = []
        # DT-4/DT-5 修复：一律取实时 editor.get_data() 作为 data 快照，不优先使用
        # 步骤里可能陈旧的 step["data"]（续采后用户编辑但未重新确认时，旧快照会
        # 被沿用导致草稿/最终 JSON 静默丢数据）。同时补齐 step 字段。
        for i, step in enumerate(self.steps):
            try:
                step_data = copy.deepcopy(step["editor"].get_data())
            except Exception:
                step_data = copy.deepcopy(step.get("data") or {})
            step_data.setdefault("observation", {})["screenshot"] = step["screenshot_filename"]
            # 与旧 data 快照合并：编辑器重建字典时空值的受保护下游字段保留快照原值
            original_data = step.get("data")
            if isinstance(original_data, dict):
                step_data = self._merge_step_with_original(step_data, original_data)
                step_data.setdefault("observation", {})["screenshot"] = step["screenshot_filename"]
            # 补齐 step 字段（放在首部）
            if step_data.get("step") != i:
                step_data = {"step": i, **{k: v for k, v in step_data.items() if k != "step"}}
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
            self.setWindowTitle(f"GUI长步骤采标工具-Windows - {self.app_name}")
        self.rounds = copy.deepcopy(draft.get("rounds", []))
        self.all_coords_entries = copy.deepcopy(draft.get("coords_entries", []))

        current_steps = draft.get("current_steps", [])

        # 清空 stack 中除第 0 页空提示外的页面（并销毁，避免游离顶层窗口堆积）
        self._drop_all_step_pages()
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

    # ---------- 已完成任务再编辑 ----------

    @staticmethod
    def _entry_round_index(entry):
        """读取 coords 条目的 round 字段；不可用时返回 None"""
        if not isinstance(entry, dict):
            return None
        value = entry.get("round")
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None

    @staticmethod
    def _trajectory_matches(trajectory, step, action):
        """判断某轮 trajectory 中是否存在 (step, action) 对应的步骤"""
        for item in trajectory or []:
            if not isinstance(item, dict) or item.get("step") != step:
                continue
            actions = item.get("actions") or []
            if action is None:
                return True
            if actions and isinstance(actions[0], dict) and actions[0].get("action") == action:
                return True
        return False

    def _append_coord_by_alignment(self, entry, rounds, groups):
        """按 trajectory 的 (step, action) 将条目对齐到某轮；无法对齐则追加到最后一轮"""
        step = entry.get("step") if isinstance(entry, dict) else None
        action = entry.get("action") if isinstance(entry, dict) else None
        for idx, round_data in enumerate(rounds):
            if self._trajectory_matches(round_data.get("trajectory"), step, action):
                groups[idx].append(entry)
                return
        groups[-1].append(entry)

    def _group_coords_by_round(self, rounds, coords_entries):
        """把扁平 coords 条目按轮次分组（长度 = len(rounds)，绝不丢弃条目）

        优先使用条目的 round 字段；旧文件无 round 时按 step 回退切分连续段，
        段数与轮次不一致时按各轮 trajectory 的 (step, action) 对齐。
        """
        n = len(rounds)
        if n == 0:
            return []
        groups = [[] for _ in range(n)]
        entries = list(coords_entries or [])
        if not entries:
            return groups

        if any(self._entry_round_index(e) is not None for e in entries):
            for entry in entries:
                round_idx = self._entry_round_index(entry)
                if round_idx is None:
                    self._append_coord_by_alignment(entry, rounds, groups)
                elif 0 <= round_idx < n:
                    groups[round_idx].append(entry)
                else:
                    # round 越界：追加到最后一轮，绝不丢弃
                    groups[-1].append(entry)
            return groups

        # 无 round 字段：step 回退即视为下一轮，切分连续段
        segments = []
        current = []
        prev_step = None
        for entry in entries:
            step = entry.get("step") if isinstance(entry, dict) else None
            step_ok = isinstance(step, int) and not isinstance(step, bool)
            if current and step_ok and isinstance(prev_step, int) and step < prev_step:
                segments.append(current)
                current = []
            current.append(entry)
            if step_ok:
                prev_step = step
        if current:
            segments.append(current)

        if len(segments) == n:
            return segments

        # 4.3（B35）段数与轮次不一致：逐段找一个「尚未被占用」且轨迹签名匹配的轮次，
        # 段内逐条目归入（对齐 iOS _group_coords_into_rounds 的 used 集合）。旧写法逐条目
        # 取首个命中的轮次，多段同签名时全挤进第一轮、其余轮次一条坐标都拿不到——已交付
        # 顶点被静默错配；对不上签名的条目仍并入最后一轮，绝不丢弃。
        used = set()
        for segment in segments:
            target = None
            for entry in segment:
                step = entry.get("step") if isinstance(entry, dict) else None
                action = entry.get("action") if isinstance(entry, dict) else None
                for idx, round_data in enumerate(rounds):
                    if idx in used:
                        continue
                    if self._trajectory_matches(round_data.get("trajectory"), step, action):
                        target = idx
                        break
                if target is not None:
                    break
            if target is None:
                # 整段都对不上任何未占用的轮次：并入最后一轮且不占用该轮
                groups[-1].extend(segment)
                continue
            for entry in segment:
                step = entry.get("step") if isinstance(entry, dict) else None
                action = entry.get("action") if isinstance(entry, dict) else None
                if self._trajectory_matches(rounds[target].get("trajectory"), step, action):
                    groups[target].append(entry)
                else:
                    # 签名对不上选定的轮次：仍并入最后一轮，绝不丢弃
                    groups[-1].append(entry)
            used.add(target)
        return groups

    @staticmethod
    def _vertices_to_rect(vertices):
        """coords 的 [x1, y1, x2, y2] → 编辑器 rect_info 的 (x, y, w, h)"""
        x1, y1, x2, y2 = vertices[:4]
        return int(x1), int(y1), int(x2) - int(x1), int(y2) - int(y1)

    @classmethod
    def _rect_info_from_coord_entry(cls, entry):
        """coords 条目 → (rect_info, selection_type)

        「没有框」和「全屏截图」是两回事：条目缺失或没有顶点时返回空 rect 与
        None，由 _classify_coord_state 结合 JSON 坐标值判定究竟是真全屏还是框
        丢失。旧写法在这里凭空返回 "fullscreen"，会让 validate_step_at 的全屏
        豁免把「coords 少条目」变成静默通过校验的缺陷——正是本次要修的失败模式。
        """
        if not isinstance(entry, dict):
            return (), None
        start = entry.get("start_vertices")
        end = entry.get("end_vertices")
        if start and end and len(start) >= 4 and len(end) >= 4:
            return (cls._vertices_to_rect(start), cls._vertices_to_rect(end)), "drag"
        vertices = entry.get("vertices")
        if vertices and len(vertices) >= 4:
            return cls._vertices_to_rect(vertices), None
        return (), None

    @staticmethod
    def _find_coord_entry(coords, step):
        """在该轮 coords 中按 step 精确查找条目；未命中返回 None

        曾有 fallback_index 参数：按 step 落空时回退取列表第 i 条。位置相同不代表
        内容相关——旧交付件（B6 采集层缺 scroll，coords 少几条）会让下标整体漂移，
        编辑态由此冒领别的步骤的顶点，写回时污染 bbox 以正确 step 编号落盘。
        位置猜测不可挽救，彻底删除。
        """
        if not coords:
            return None
        for entry in coords:
            if not isinstance(entry, dict):
                continue
            step_value = entry.get("step")
            # bool 是 int 子类，step 写成 true/false 属于脏数据，不参与匹配
            if isinstance(step_value, int) and not isinstance(step_value, bool) \
                    and step_value == step:
                return entry
        return None

    @classmethod
    def _find_coord_entry_by_center(cls, coords, action, coordinate,
                                    start_coordinate, claimed_ids):
        """按 center 恢复匹配：仅在 _find_coord_entry 落空后调用

        兼容「step 编号整体漂移但框本身正确」的旧数据：在尚未被其它步骤认领的
        条目里找 action 相同、且框中心与 JSON coordinate 逐轴差 ≤ COORD_CENTER_TOL
        的那一条。命中的是对真实内容的验证，不是对列表位置的猜测。
        """
        if not coords or action not in COORD_ACTION_TYPES:
            return None
        for entry in coords:
            if not isinstance(entry, dict) or id(entry) in claimed_ids:
                continue
            if entry.get("action") != action:
                continue
            mismatched, _detail = entry_coordinate_mismatch(
                entry, coordinate, start_coordinate, COORD_CENTER_TOL)
            # 只有「已验证一致」才认领；None（交付侧无可用坐标值）不足以证明归属
            if mismatched is False:
                claimed_ids.add(id(entry))
                return entry
        return None

    @staticmethod
    def _step_json_coordinates(step_data):
        """trajectory 条目 → (action, coordinate, start_coordinate)

        coordinate 统一由 coord_pair 归一为 (int, int) 或 None：缺失、非数组、
        长度不足、含非数值均返回 None，避免各处再各自手写容错分支。
        """
        actions = (step_data or {}).get("actions")
        if not isinstance(actions, list):
            return None, None, None
        for item in actions:
            if not isinstance(item, dict):
                continue
            return (item.get("action"),
                    coord_pair(item.get("coordinate")),
                    coord_pair(item.get("start_coordinate")))
        return None, None, None

    @classmethod
    def _classify_coord_state(cls, step_data, coord_entry):
        """coords 条目 + JSON 坐标 → (rect_info, selection_type, coord_issue)

        coord_issue ∈ {None, "absent", "mismatch", "no_box"}：
          absent   交付 JSON 里该步有坐标值，coords 却没有可信的框 → 框丢失
          mismatch 有条目但框中心与坐标值对不上（位置冒领的典型现场）→ 不采信
          no_box   既没有框也没有坐标值 → 真全屏，沿用既有校验豁免
        "absent"/"mismatch" 绝不返回 selection_type="fullscreen"，否则
        validate_step_at 的坐标豁免会让「丢框」静默通过校验。
        """
        action, coordinate, start_coordinate = cls._step_json_coordinates(step_data)
        rect_info, selection_type = cls._rect_info_from_coord_entry(coord_entry)

        if action not in COORD_ACTION_TYPES:
            # 非坐标类动作：有条目就按条目还原，没条目维持「全屏」现状
            if coord_entry is None:
                return (), "fullscreen", None
            return rect_info, selection_type, None

        has_coord = coordinate is not None and coordinate != (0, 0)
        if not rect_info:
            if has_coord:
                return (), None, "absent"
            return (), "fullscreen", "no_box"

        if has_coord:
            mismatched, _detail = entry_coordinate_mismatch(
                coord_entry, coordinate, start_coordinate, COORD_CENTER_TOL)
            if mismatched:
                # 框中心与已交付坐标对不上：宁可不显示框，也不让错误 bbox 在
                # 下次写回时以正确 step 编号落进已交付数据
                return (), selection_type, "mismatch"
        return rect_info, selection_type, None

    @classmethod
    def _coord_issue_detail(cls, step_data, coord_entry):
        """给汇总告警用的一行差异说明（盘上值 vs JSON 值，给人直接看的格式）"""
        _action, coordinate, _start_coordinate = cls._step_json_coordinates(step_data)
        json_part = (f"JSON coordinate={list(coordinate)}" if coordinate
                     else "JSON 无坐标值")
        if coord_entry is None:
            return f"coords 无对应条目 / {json_part}"
        mismatched, detail = entry_coordinate_mismatch(
            coord_entry, coordinate, _start_coordinate, COORD_CENTER_TOL)
        if mismatched:
            return detail
        return f"coords 条目没有可用的框顶点 / {json_part}"

    def load_from_completed_json(self, completed_data, coords_entries, round_index, gui_dir):
        """从已完成任务的最终 JSON + coords 重建编辑现场（在 show 之前调用）

        :param completed_data: 最终 gui_XXXXXX.json 解析后的字典
        :param coords_entries: coords JSON 的扁平条目列表（可为空）
        :param round_index: 要编辑的轮次下标（0 起）
        :param gui_dir: 该任务目录完整路径（截图存在性检查用）
        :return: True 表示载入成功
        """
        dir_name = os.path.basename(os.path.normpath(gui_dir or ""))
        match = re.fullmatch(r"gui_(\d{6})", dir_name)
        if match:
            self.gui_number = match.group(1)

        # 按 user/assistant 配对重建全部轮次
        rounds = []
        pending_instruction = ""
        for message in (completed_data or {}).get("messages", []) or []:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role == "user":
                pending_instruction = message.get("instruction", "") or ""
            elif role == "assistant":
                rounds.append({
                    "instruction": pending_instruction,
                    "trajectory": copy.deepcopy(message.get("trajectory", []) or []),
                })
                pending_instruction = ""

        if not rounds:
            QMessageBox.warning(self, "编辑失败", "该任务没有任何可编辑轮次")
            return False

        self.rounds = rounds
        if not (0 <= round_index < len(self.rounds)):
            round_index = 0
        self._edit_round_index = round_index
        self.current_round_index = round_index
        self._completed_json = copy.deepcopy(completed_data)
        self._original_coords_exist = bool(coords_entries)
        self._coords_rounds = self._group_coords_by_round(self.rounds, coords_entries or [])
        self._edit_mode = True
        self._final_data_saved = False
        self.task_instruction = self.rounds[round_index].get("instruction", "")

        # 清空 stack 并重建当前轮的步骤（旧页一并销毁）
        self._drop_all_step_pages()
        self.steps = []
        self.current_step_index = -1

        current_trajectory = self.rounds[round_index].get("trajectory", [])
        current_coords = self._coords_rounds[round_index]
        missing_files = []
        # 已被某个步骤认领的 coords 条目（用对象 id：条目内容可能重复，位置不能代表身份）
        claimed_ids = set()
        # hydration 现场逐条登记的不一致清单（循环前重置，覆盖 _drop_all_step_pages 的清空）
        self._coord_issues = []

        for i, t_entry in enumerate(current_trajectory):
            step_data = copy.deepcopy(t_entry) if isinstance(t_entry, dict) else {}
            step_data.setdefault("step", i)
            observation = step_data.setdefault("observation", {})
            filename = observation.get("screenshot", "") or ""
            observation["screenshot"] = filename

            if filename and not os.path.exists(os.path.join(gui_dir, filename)):
                missing_files.append(f"步骤 {i}: {filename}")

            step_editor = StepEditorWidget(step_data=step_data)
            # 必填项实时校验 + 分栏 resize 后按磁盘原图重绘预览
            self._connect_editor_validation_signals(step_editor)
            step_editor.preview_resize_requested.connect(
                lambda ed=step_editor: self._on_editor_preview_resize(ed)
            )
            step_editor.set_step_number(i)

            # 两趟匹配：先按 step 精确定位，落空才按 center 恢复（不再有位置回退）
            step_action, coordinate, start_coordinate = self._step_json_coordinates(step_data)
            coord_entry = self._find_coord_entry(current_coords, step_data.get("step"))
            if coord_entry is not None:
                claimed_ids.add(id(coord_entry))
            else:
                coord_entry = self._find_coord_entry_by_center(
                    current_coords, step_action, coordinate, start_coordinate, claimed_ids)
            rect_info, selection_type, coord_issue = self._classify_coord_state(
                step_data, coord_entry)
            if coord_issue in ("absent", "mismatch"):
                action_cn = next((cn for cn, en in step_editor.action_type_mapping.items()
                                  if en == step_action), step_action or "")
                self._coord_issues.append((
                    i, action_cn, coord_issue,
                    self._coord_issue_detail(step_data, coord_entry)))

            self.steps.append({
                "editor": step_editor,
                "screenshot_filename": filename,
                "rect_info": rect_info,
                "selection_type": selection_type,
                "data": step_data,
                "confirmed": True,
                # 盘上 bbox 与 coordinate 不一致时保留原条目快照，供写回时
                # 原样继承（见 _collect_coords_entries），绝不让「打开看一眼」丢数据
                "coord_issue": coord_issue,
                "orig_coord_entry": (
                    copy.deepcopy(coord_entry)
                    if coord_issue in ("absent", "mismatch") and coord_entry else None),
            })
            self.stack_widget.addWidget(step_editor)

        # 先于 display_step 告警：不一致必须先被看见，否则采集员会以为框没拉到
        if self._coord_issues:
            lines = []
            for step_index, action_cn, issue_kind, detail in self._coord_issues:
                kind_cn = "框丢失" if issue_kind == "absent" else "框与坐标值不一致"
                lines.append(f"步骤 {step_index}（{action_cn}）· {kind_cn}：{detail}")
            QMessageBox.warning(
                self,
                "coords 与坐标值不一致",
                "检测到以下步骤的 bbox 与已交付坐标值对不上：\n\n"
                + "\n".join(lines)
                + "\n\n这些步骤的框未载入，保存不会改动盘上原条目；"
                  "如需修复请在原图重新拉框，"
                  "或运行 tools/coords_center_repair.py 做中心对齐重建。"
            )

        if self.steps:
            self.display_step(0)
        else:
            self.stack_widget.setCurrentIndex(0)
            self.update_step_indicator()

        if missing_files:
            QMessageBox.warning(
                self,
                "截图文件缺失",
                "以下步骤的截图文件在磁盘上不存在，预览将无法显示：\n\n" + "\n".join(missing_files)
            )

        base_title = self.windowTitle()
        if " - 编辑已完成任务" not in base_title:
            self.setWindowTitle(base_title + " - 编辑已完成任务")
        edit_status = (
            f"编辑已完成任务 gui_{self.gui_number} · 第 {round_index + 1} 轮"
        )
        if self._coord_issues:
            # 保留常规状态串，只追加告警：直接覆盖会让其他依赖该文本的
            # 现场提示（和后续测试）被顶掉
            edit_status += f" · ⚠ 检测到 {len(self._coord_issues)} 个步骤的 bbox 与 coordinate 不一致"
        self.status_label.setText(edit_status)
        self.save_edit_btn.show()
        # 编辑已完成任务：允许在磁盘原图上重新拉框
        self.relabel_btn.show()

        self.revalidate_all_missing()
        self.refresh_sidebar(fully=True)
        self.update_step_indicator()
        self.sidebar.refresh_dashboard()
        # 编辑模式不排 draft 保存
        return True

    @staticmethod
    def _find_original_step(trajectory, filename):
        """按截图文件名在原 trajectory 中找到被编辑的步骤"""
        if not filename:
            return None
        for item in trajectory or []:
            if not isinstance(item, dict):
                continue
            observation = item.get("observation")
            if isinstance(observation, dict) and observation.get("screenshot") == filename:
                return item
        return None

    # 编辑器不采集、重建步骤字典时可能被写成空值的下游字段：
    # 步骤级 CoT；observation 内嵌 active_window / ui_tree_segment；
    # 动作级 element / status（终止类动作的这两个字段走业务规则，不参与保留合并）
    _PROTECTED_STEP_FIELDS = ("CoT",)
    _PROTECTED_OBSERVATION_FIELDS = ("active_window", "ui_tree_segment")
    _PROTECTED_ACTION_FIELDS = ("element", "status")
    _TERMINAL_ACTIONS = ("terminate", "answer", "answer_terminate")

    @staticmethod
    def _is_empty_protected_value(value):
        """受保护字段的空值判定：None、空字符串、空 dict、空 list 视为空"""
        if value is None:
            return True
        if isinstance(value, str) and value == "":
            return True
        if isinstance(value, (dict, list)) and len(value) == 0:
            return True
        return False

    def _merge_step_with_original(self, new_step, original_step):
        """合并重建步骤与原步骤：受保护下游字段空值不覆盖原值，其余新值优先。

        - 受保护字段（CoT / observation.active_window / observation.ui_tree_segment /
          非终止动作的 element、status）：new 非空用 new，new 为空且 original 有该键
          时保留 original 值；original 没有该键则保留 new 的空值，不引入新键。
        - 终止类动作（terminate / answer / answer_terminate）保持业务规则：
          element 恒为 ""、status 恒为 "success"，不做保留合并。
        - 其余键：new 有的以 new 为准；original 有而 new 缺失的键深拷贝保留。
        返回新 dict，不原地修改入参。
        """
        if not isinstance(original_step, dict):
            return copy.deepcopy(new_step)
        if not isinstance(new_step, dict):
            return copy.deepcopy(original_step)

        merged = copy.deepcopy(new_step)

        # 受保护步骤级字段：空值回退为原值（仅当原步骤存在该键）
        for field in self._PROTECTED_STEP_FIELDS:
            if field in merged and self._is_empty_protected_value(merged[field]) \
                    and field in original_step:
                merged[field] = copy.deepcopy(original_step[field])

        # observation 按字段级合并：screenshot 等非保护字段一律以 new 为准
        new_observation = merged.get("observation")
        old_observation = original_step.get("observation")
        if isinstance(new_observation, dict) and isinstance(old_observation, dict):
            for field in self._PROTECTED_OBSERVATION_FIELDS:
                if field in new_observation \
                        and self._is_empty_protected_value(new_observation[field]) \
                        and field in old_observation:
                    new_observation[field] = copy.deepcopy(old_observation[field])

        # 动作级合并：只处理 actions[0]，终止类动作不保留 element/status
        new_actions = merged.get("actions")
        old_actions = original_step.get("actions")
        if isinstance(new_actions, list) and isinstance(old_actions, list) \
                and new_actions and isinstance(new_actions[0], dict) \
                and len(old_actions) > 0 and isinstance(old_actions[0], dict):
            new_action = new_actions[0]
            old_action = old_actions[0]
            is_terminal = new_action.get("action") in self._TERMINAL_ACTIONS
            if is_terminal:
                new_action["element"] = ""
                new_action["status"] = "success"
            else:
                for field in self._PROTECTED_ACTION_FIELDS:
                    if field in new_action \
                            and self._is_empty_protected_value(new_action[field]) \
                            and field in old_action:
                        new_action[field] = copy.deepcopy(old_action[field])

        # 其余所有键：original 有而 new 缺失的，原样深拷贝保留（含未知键）
        for key, old_value in original_step.items():
            if key not in merged:
                merged[key] = copy.deepcopy(old_value)
        # observation / actions 内部的未知键同样补齐
        if isinstance(new_observation, dict) and isinstance(old_observation, dict):
            for key, old_value in old_observation.items():
                if key not in new_observation:
                    new_observation[key] = copy.deepcopy(old_value)
        if isinstance(new_actions, list) and isinstance(old_actions, list) \
                and new_actions and isinstance(new_actions[0], dict) \
                and len(old_actions) > 0 and isinstance(old_actions[0], dict):
            for key, old_value in old_actions[0].items():
                if key not in new_actions[0]:
                    new_actions[0][key] = copy.deepcopy(old_value)

        return merged

    def _audit_coord_consistency(self, trajectory, entries):
        """写回前审计：本轮由内存 rect_info 新生成的条目必须 center ↔ coordinate 一致

        只审计「本轮新写的」条目。编辑态从盘上原样继承的条目（hydration 已标为
        absent/mismatch，见 _collect_coords_entries 的 orig_coord_entry 分支）不在
        范围——那是本次编辑没有触碰的历史缺陷，工具既不伪造也不丢弃。
        判定条件直接取自当前 steps 现场而不靠 hydration 记录的步序，因此中途
        删步导致的下标漂移不会让审计漏掉真正被重写的条目。
        :return: 不一致项描述列表（空表示通过）
        """
        inherited_steps = set()
        for index, step in enumerate(self.steps):
            if not step.get("rect_info") and isinstance(step.get("orig_coord_entry"), dict):
                inherited_steps.add(index)

        problems = []
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            action = entry.get("action")
            if action not in COORD_ACTION_TYPES:
                continue
            step_index = entry.get("step")
            if isinstance(step_index, bool) or not isinstance(step_index, int):
                continue
            if step_index in inherited_steps:
                continue
            if not (0 <= step_index < len(trajectory)):
                problems.append(f"步骤 {step_index} [{action}]：coords 条目找不到对应的轨迹步骤")
                continue
            json_action, coordinate, start_coordinate = self._step_json_coordinates(
                trajectory[step_index])
            if json_action != action:
                problems.append(
                    f"步骤 {step_index}：coords 动作 {action} 与 JSON 动作 {json_action} 不一致")
                continue
            mismatched, detail = entry_coordinate_mismatch(
                entry, coordinate, start_coordinate, COORD_CENTER_TOL)
            if mismatched:
                problems.append(f"步骤 {step_index} [{action}]：{detail}")
        return problems

    def save_edited_round(self, silent=False):
        """校验并仅写回正在编辑的轮次（其余轮次与顶层字段原样保留）

        :param silent: True 时不弹窗（用于关闭窗口前自动写回）
        :return: True 表示最终 JSON 写入成功
        """
        if self._edit_mode is False or not self._completed_json:
            return False
        round_index = self._edit_round_index
        if not (0 <= round_index < len(self.rounds)):
            return False

        # 与「任务完成」一致的必填校验（silent 关闭写回时跳过）
        if not silent:
            missing_entries = []
            for i in range(len(self.steps)):
                reasons = self.validate_step_at(i)
                if reasons:
                    missing_entries.append((i, self._action_cn_name(i), reasons))
            if missing_entries:
                self.revalidate_all_missing()
                self._show_validation_fail_dialog(missing_entries)
                return False

        # 本轮原始 trajectory（按截图文件名匹配，合并未暴露字段用）
        original_trajectory = copy.deepcopy(self.rounds[round_index].get("trajectory", []))

        trajectory = []
        for i, step in enumerate(self.steps):
            editor = step["editor"]
            step_data = copy.deepcopy(editor.get_data())
            step_data.setdefault("observation", {})["screenshot"] = step["screenshot_filename"]
            existing_step = step_data.pop("step", None)
            if existing_step != i:
                step_data = {"step": i, **step_data}
            else:
                step_data["step"] = i

            original_step = self._find_original_step(
                original_trajectory, step["screenshot_filename"]
            )
            trajectory.append(self._merge_step_with_original(step_data, original_step))

        # 先验后改：审计不过就既不碰内存也不碰磁盘（与 B40 的 messages 校验同口径）。
        # 旧写法先赋值 self.rounds / self._coords_rounds 再校验，一旦中途中止，
        # 内存里已留下污染 bbox 且以正确 step 编号等着下一轮写回。
        new_entries = self._collect_coords_entries()
        audit_problems = self._audit_coord_consistency(trajectory, new_entries)
        if audit_problems:
            reason = ("coords 与坐标值不一致：\n"
                      + "\n".join(f"  - {problem}" for problem in audit_problems))
            if silent:
                print(f"编辑写回中止（gui_{self.gui_number}）：{reason}")
            else:
                QMessageBox.critical(
                    self, "错误", reason + "\n已拒绝写回，磁盘上的原文件未改变！"
                )
            return False

        self.rounds[round_index]["trajectory"] = trajectory
        self._coords_rounds[round_index] = new_entries

        # 1.5（B40）原地只改被编辑轮对应的两条消息，其余消息对象一律不动。
        # 早前先 deepcopy 再按 self.rounds 全量重建，会把原 JSON 里非
        # user/assistant 的消息、每轮消息自带的其他字段、末尾孤立 user 消息
        # 整条丢掉——已交付数据不可恢复。结构不满足「严格交替」时
        # 拒绝写回，绝不退化成全量重建。
        data = copy.deepcopy(self._completed_json)
        messages = data.get("messages")
        anchor = 2 * round_index + 1
        if (not isinstance(messages, list) or len(messages) <= anchor
                or not isinstance(messages[2 * round_index], dict)
                or not isinstance(messages[anchor], dict)
                or messages[2 * round_index].get("role") != "user"
                or messages[anchor].get("role") != "assistant"):
            reason = (
                f"最终 JSON 的 messages 结构与轮次不匹配：第 {round_index + 1} 轮需要 "
                f"messages[{2 * round_index}]=user / messages[{anchor}]=assistant"
            )
            if silent:
                print(f"编辑模式写回中止（gui_{self.gui_number}）：{reason}")
            else:
                QMessageBox.critical(
                    self, "错误", reason + "\n已拒绝写回，磁盘上的原文件未改变！"
                )
            return False

        edited_round = self.rounds[round_index]
        messages[2 * round_index]["instruction"] = edited_round.get("instruction", "")
        messages[anchor]["trajectory"] = edited_round.get("trajectory") or []
        data["messages"] = messages

        # 1.4 安全网：编辑写回会整份替换已交付 JSON，先把原文件留一份 .bak（覆盖式）。
        # 仅在原文件存在时生成；备份失败不阻断保存。
        self.data_manager.backup_final_json(self.gui_number)

        filepath = self.data_manager.save_json_data(data, self.gui_number)
        if not filepath:
            if silent:
                print(f"编辑模式关闭前保存修改失败（gui_{self.gui_number}）")
            else:
                QMessageBox.critical(self, "错误", "保存修改失败，磁盘上的原文件未改变！")
            return False

        # 1.5（B41）coords 只在真的收集到条目时才写盘。旧条件带了
        # or self._original_coords_exist，会在「本轮导出 0 条坐标」时用空数组
        # 覆盖已交付的坐标文件；现在改为告警并跳过写入，保留原文件。
        # 4.2（B4/B18）按分组下标注入 round，与落轮路径同口径；用浅拷贝写出，
        # 避免就地修改 _coords_rounds 里来自磁盘的历史条目对象。
        flat_coords = []
        for group_index, group in enumerate(self._coords_rounds):
            for entry in group:
                if isinstance(entry, dict):
                    entry = {**entry, "round": group_index}
                flat_coords.append(entry)
        if flat_coords:
            try:
                self.data_manager.save_coords_json(flat_coords, self.gui_number)
            except Exception as e:
                print(f"保存修改时写出坐标失败: {e}")
        elif self._original_coords_exist:
            print(
                f"警告：编辑写回收集到 0 条坐标，已跳过 coords 写入以保留原文件"
                f"（gui_{self.gui_number}）"
            )
        self.all_coords_entries = flat_coords
        if self._coord_issues:
            # 继承性盘上缺陷本次未消除：写回成功不等于数据已干净，提醒显式处置
            print(
                f"提示：gui_{self.gui_number} 仍有 {len(self._coord_issues)} 个步骤的盘上 bbox 与 "
                f"coordinate 不一致（本次原样保留、未改动这些条目）；如需修复请重新拉框，"
                f"或运行 tools/coords_center_repair.py 做中心对齐重建。"
            )
        self._final_data_saved = True

        if silent:
            print(f"编辑模式关闭前已保存修改到: {filepath}")
            return True

        QMessageBox.information(
            self, "保存成功",
            f"已完成任务 gui_{self.gui_number} 第 {round_index + 1} 轮的修改已保存到：\n{filepath}"
        )
        self._return_to_init_menu()
        return True

    def show_new_task_dialog(self):
        """显示是否创建新任务的对话框"""
        # 门闩回调已进场，切轮窗口结束，恢复采集/编辑入口（B2）
        self._round_transition_pending = False
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

            # 5.3（B7）顺序必须是“先换编号、后重置”：reset_for_new_task 末尾按 DT-3
            # 立即写一份空草稿，而此刻 gui_number 仍指向刚交付完成的旧目录，等于把
            # gui_N 重新标成「未完成任务」——它会再次出现在续采列表里，用户接着采就
            # 会往已交付目录里重写一份互相矛盾的草稿。重置期间抑制草稿写入，拿到新
            # 编号后由采集流程自己落第一份草稿。
            self._suppress_draft_write = True
            try:
                self.reset_for_new_task()
            finally:
                self._suppress_draft_write = False
            self.gui_number = self.data_manager.get_next_gui_number()

            self.status_label.setText(f"新任务开始 - 指令: {self.task_instruction}")
        else:
            # 用户取消了，关闭窗口
            self.close()

    def start_new_round(self, from_answer=False):
        """开始新一轮任务（同一 gui 文件夹内）
        :param from_answer: 是否从 answer 动作触发，如果是则取消时不保存退出
        """
        # 门闩回调已进场，切轮窗口结束，恢复采集/编辑入口（B2）
        self._round_transition_pending = False

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
                # 2.3（B1）answer 分支已把当前轮落入 rounds 并清空 steps，但 stack 里
                # 上一轮的编辑页、current_step_index、侧栏条目都还在原地：用户看到的
                # 仍是上一轮的表单与截图残留，此时继续采集就接在陈旧界面上。
                # 取消新轮必须与接受新轮走同一个重置入口，回到只剩空白页的起点。
                # B14：重置前先清空 task_instruction —— 上一轮已随 answer 落轮并被
                # 消费，继续留着旧指令，用户接着采集的整轮就会被挂到上一条指令上。
                self.task_instruction = ""
                self.reset_for_new_task()
                self.status_label.setText("已取消新任务 - 可继续截图标注")
            else:
                # 否则完成所有标注
                self.finish_all_annotation()

    def finish_all_annotation(self, close_after_save=True):
        """完成所有轮次的标注并保存
        :param close_after_save: 保存后是否关闭窗口。False 时返回初始化菜单
        """
        # 先保存当前轮次（如果有的话）
        if len(self.steps) > 0:
            # B14：缺指令被拒绝落轮时中止收尾，不写出缺最后一轮的交付文件
            if not self.save_current_round():
                QMessageBox.warning(
                    self, "缺少任务指令",
                    "当前轮次还没有任务指令，已中止保存以免轨迹挂到错误指令上。\n"
                    "请重新确认本步并输入本轮指令后再完成标注。"
                )
                return

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
            # 最终数据已成功落盘，删除增量草稿：交付件是此目录的唯一真相，
            # 留着草稿会让同一目录既「已完成」又「可续采」（B9 口径）
            self.data_manager.delete_draft(self.gui_number)
            # 标记已最终保存，随后的 closeEvent 不再对同一批数据二次落盘
            self._final_data_saved = True

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
        # 5.3（B8）进入新的工作现场就清掉「已落盘」标志：该标志只对刚完成交付的
        # 那批数据有效。不重置时，新任务中途关窗会被 closeEvent 当成“已保存”而
        # 跳过草稿落盘，整轮进度静默丢失。
        self._final_data_saved = False
        self.steps = []
        self.current_step_index = -1
        # 注意：不重置 gui_number，整个任务共用同一个文件夹

        # 清空 stack widget（保留空页面；旧步骤页销毁掉）
        self._drop_all_step_pages()

        self.stack_widget.setCurrentIndex(0)
        self.update_step_indicator()
        # 新轮次/新任务：清空侧栏步骤列表与看板（任务指令可能已更新）
        self.refresh_sidebar(fully=True)
        # 隐藏撤销按钮
        self.undo_btn.hide()
        hk2 = "Cmd" if sys.platform == 'darwin' else "Alt"
        self.status_label.setText(f"就绪 - 按 {hk2}+Q 给下一步截图")
        # DT-3 修复：轮次重置后立即写一份空 current_steps 的草稿覆盖磁盘上
        # 可能残留的上一轮步骤，避免崩溃续采时与 rounds 已追加的本轮轨迹重复。
        self._write_draft_now()

    def closeEvent(self, event):
        """窗口关闭事件 — 把未交付的进度落进草稿，并释放快捷键/定时器"""
        # 任何关闭路径都先解绑全局快捷键并停掉定时器，避免旧窗口残留为幽灵实例
        self.cleanup_resources()

        # 让主窗口不再持有正在销毁的本实例引用
        init_win = self.init_window
        if init_win is not None \
                and getattr(init_win, "annotation_window", None) is self:
            init_win.annotation_window = None

        # 已通过“任务完成”正常落盘的不再重复处理；中途关闭只保留可续采的草稿
        if self._edit_mode:
            # 编辑已完成任务：关闭前把当前轮写回最终 JSON，绝不写/删草稿
            if not self._final_data_saved:
                try:
                    self.save_edited_round(silent=True)
                except Exception as e:
                    print(f"编辑模式关闭前保存修改失败: {e}")
            # 进入编辑时主窗口已被隐藏，关闭编辑器后必须恢复，否则应用没有任何可见窗口
            # 注意：此处不能调用 self.close() 或 _return_to_init_menu()，否则会递归销毁自身
            init_win = self.init_window
            if init_win is not None:
                init_win.show()
                init_win.raise_()
                init_win.activateWindow()
        elif not self._final_data_saved:
            # 5.2（B9）中途关窗只落增量草稿，不写交付 JSON：旧实现在这里绕过必填
            # 校验直接产出 gui_N.json，却不删草稿，于是同一个目录既「已完成」又
            # 「可续采」，两个入口互不知晓、后写者覆盖前写者。口径对齐 iOS/Android：
            # 交付只由「完成标注」路径产生，关窗进度靠草稿恢复。
            try:
                self._write_draft_now()
            except Exception as e:
                print(f"关闭前写草稿失败: {e}")

        event.accept()

    def _return_to_init_menu(self):
        """返回任务初始化菜单"""
        if self.init_window:
            self.init_window.show()
            self.init_window.raise_()
            self.init_window.activateWindow()
            # 解绑快捷键/定时器并销毁本窗口，避免旧实例残留为幽灵窗口；
            # 让主窗口不再持有本实例引用
            if getattr(self.init_window, "annotation_window", None) is self:
                self.init_window.annotation_window = None
        self.close()
        self.deleteLater()
