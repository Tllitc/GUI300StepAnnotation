#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI长步骤采标工具-Android 标注编辑器
嵌入 scrcpy + 透明蒙版拉框 + 截图预览 + 动作参数编辑
"""

import os
import sys
import re
import copy
import subprocess
import ctypes
import tempfile
import threading
from ctypes import wintypes
from datetime import datetime
from collections import OrderedDict

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QComboBox,
                             QLineEdit, QSplitter, QFrame, QMessageBox,
                             QInputDialog, QGroupBox, QFormLayout,
                             QSizePolicy, QShortcut, QScrollArea, QSpinBox,
                             QListWidget, QListWidgetItem, QDialog)
from PyQt5.QtCore import Qt, QTimer, QRect, QPoint, QSize, pyqtSignal
from PyQt5.QtGui import (QPixmap, QImage, QPainter, QPen, QColor, QFont,
                         QKeySequence, QFontMetrics, QIcon)

from screenshot_capture import AndroidScreenCapture
from data_manager import DataManager

# ============================================================
# Win32 API 声明 (for scrcpy embedding)
# ============================================================
user32 = ctypes.windll.user32

FindWindowW = user32.FindWindowW
FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
FindWindowW.restype = wintypes.HWND

EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
EnumWindows.restype = wintypes.BOOL

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
GetWindowThreadProcessId.restype = wintypes.DWORD

SetParent = user32.SetParent
SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
SetParent.restype = wintypes.HWND

SetWindowPos = user32.SetWindowPos
SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, wintypes.UINT]
SetWindowPos.restype = wintypes.BOOL

MoveWindow = user32.MoveWindow
MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int,
                        ctypes.c_int, ctypes.c_int, wintypes.BOOL]
MoveWindow.restype = wintypes.BOOL

GetWindowLongW = user32.GetWindowLongW
GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
GetWindowLongW.restype = ctypes.c_long

SetWindowLongW = user32.SetWindowLongW
SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
SetWindowLongW.restype = ctypes.c_long

SendMessageW = user32.SendMessageW
SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
SendMessageW.restype = wintypes.LPARAM

ScreenToClient = user32.ScreenToClient
ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
ScreenToClient.restype = wintypes.BOOL

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_EX_TOOLWINDOW = 0x80
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
MK_LBUTTON = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
HWND_TOP = 0
HWND_TOPMOST = -1


def make_lparam(x, y):
    return (y << 16) | (x & 0xFFFF)


def find_window_by_pid(pid):
    result = []
    def enum_callback(hwnd, lparam):
        window_pid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if window_pid.value == pid:
            style = GetWindowLongW(hwnd, GWL_STYLE)
            ex_style = GetWindowLongW(hwnd, GWL_EXSTYLE)
            if (style & WS_VISIBLE) and not (ex_style & WS_EX_TOOLWINDOW):
                result.append(hwnd)
                return False
        return True
    EnumWindows(EnumWindowsProc(enum_callback), 0)
    return result[0] if result else None


def get_scrcpy_path():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for d in ['scrcpy_4.0', 'scrcpy']:
        exe = os.path.join(script_dir, d, 'scrcpy.exe')
        if os.path.exists(exe):
            return exe, os.path.join(script_dir, d)
    return None, None


# ============================================================
# 动作定义
# ============================================================
ANDROID_ACTIONS = [
    ("click", "点击 (click)"),
    ("long_press", "长按 (long_press)"),
    ("swipe", "滑动 (swipe)"),
    ("scroll", "滚动 (scroll)"),
    ("drag", "拖拽 (drag)"),
    ("type", "输入文本 (type)"),
    ("key", "组合按键 (key)"),
    ("system_button", "系统按钮 (system_button)"),
    ("answer", "回答问题 (answer)"),
    ("answer_terminate", "回答并结束 (answer_terminate)"),
    ("wait", "等待 (wait)"),
    ("terminate", "任务完成 (terminate)"),
    ("open_app", "打开App (open_app)"),
    ("open_url", "打开网页 (open_url)"),
]

COORD_ACTIONS = {"click", "long_press", "type", "scroll"}
START_END_ACTIONS = {"swipe", "drag"}
TEXT_ACTIONS = {"type", "answer", "answer_terminate", "open_app", "open_url"}
KEY_ACTIONS = {"key"}
TIME_ACTIONS = {"long_press", "wait"}
BUTTON_ACTIONS = {"system_button"}
SYSTEM_BUTTONS = ["Back", "Home", "App_switch", "Power", "Volume_up", "Volume_down", "Volume_mute", "Notifications", "Quick_settings"]


# ============================================================
# coords 条目 ↔ 交付坐标一致性判定（跨端同集口径的本地镜像）
# ============================================================
# 与 Windows 侧 tools/coords_center_repair.py 共用同一容差常量与同一套三态
# 返回语义（True 不一致 / False 一致 / None 无从比对），但**判定基准不同**：
# 本端 _build_coords_entry 把 center 取自 JSON 坐标值、vertices 取自内存拉框，
# 且坐标输入框允许手工改值，故 center 才是「条目归属哪一步」的凭证；Windows 侧
# 坐标输入框只读、center 由框中心派生，才以 vertices 重算为准。
# 本目录是独立分发件（无 tools/ 包），无法 import 上级脚本，只能就地镜像，
# 调整容差或比对规则时两处须一并更新。
COORD_CENTER_TOL = 1


def _finite_int(value):
    """严格取整：排除 bool / NaN / Inf / 非数值；不可用返回 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return int(value)


def coord_pair(value):
    """[x, y] → (int, int)；缺失/非数组/长度不足/含非数值一律 None。"""
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    x = _finite_int(value[0])
    y = _finite_int(value[1])
    if x is None or y is None:
        return None
    return (x, y)


def is_zero_pair(pair):
    """(0, 0) 在交付数据里等价于「没有可用坐标」，不作为比对基准。"""
    return pair is not None and pair[0] == 0 and pair[1] == 0


def entry_coordinate_mismatch(entry, coordinate=None, start_coordinate=None,
                              tol=COORD_CENTER_TOL):
    """单条 coords 条目与其所属步骤的坐标值比对。

    :return: (result, detail)
        result=True  不一致（或 center 不可解析），需要人工处置
        result=False 一致
        result=None  动作无需坐标 / 交付侧没有可用坐标值，无从比对（不算缺陷）
        detail 为可直接展示给人看的差异说明
    """
    if not isinstance(entry, dict):
        return True, "条目不是 JSON 对象"
    action = entry.get("action")
    if action not in COORD_ACTIONS and action not in START_END_ACTIONS:
        return None, f"动作 {action!r} 无需坐标"

    if action in START_END_ACTIONS:
        # swipe/drag：center 对齐 start_coordinate，end_center 对齐 coordinate
        axes = (("center", start_coordinate, entry.get("center")),
                ("end_center", coordinate, entry.get("end_center")))
    else:
        axes = (("center", coordinate, entry.get("center")),)

    reasons = []
    checked = 0
    for label, coord_value, center_value in axes:
        center = coord_pair(center_value)
        if center is None:
            reasons.append(f"盘上 {label} 无法解析")
            continue
        target = coord_pair(coord_value)
        if target is None or is_zero_pair(target):
            continue
        checked += 1
        dx = abs(center[0] - target[0])
        dy = abs(center[1] - target[1])
        if dx > tol or dy > tol:
            reasons.append(f"盘上 {label}={list(center)} / JSON coordinate={list(target)}"
                           f"（偏差 {dx},{dy}px）")
    if reasons:
        return True, "；".join(reasons)
    if not checked:
        return None, f"{action} 在交付 JSON 中无可用坐标值，跳过比对"
    return False, ""


# ============================================================
# Scrcpy 嵌入组件
# ============================================================
class ScrcpyEmbedWidget(QWidget):
    scrcpy_embedded = pyqtSignal()
    scrcpy_error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scrcpy_process = None
        self.scrcpy_hwnd = None
        self._embed_timer = None       # 启动期嵌入轮询用
        self._embed_attempts = 0
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setMinimumSize(300, 250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background-color: #1a1a2e;")
        self._status_text = "正在启动 scrcpy..."
        self._show_placeholder = True

    @property
    def hwnd(self):
        return self.scrcpy_hwnd

    def start_scrcpy(self, device_serial=None):
        """启动（或重启）scrcpy 并尝试嵌入窗口。重入时先清理旧进程。"""
        # 重入保护：先 kill 旧进程 + 停旧 timer
        self._cleanup_process()

        scrcpy_exe, scrcpy_dir = get_scrcpy_path()
        if not scrcpy_exe:
            self.scrcpy_error.emit("未找到 scrcpy.exe")
            return False
        self._embed_attempts = 0
        self._show_placeholder = True
        self._status_text = "正在启动 scrcpy..."
        self.update()
        cmd = [scrcpy_exe, '--no-audio', '--stay-awake']
        if device_serial:
            cmd += ['--serial', device_serial]
        try:
            self.scrcpy_process = subprocess.Popen(
                cmd, cwd=scrcpy_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            # 嵌入阶段 timer
            self._embed_timer = QTimer(self)
            self._embed_timer.timeout.connect(self._on_embed_tick)
            self._embed_timer.start(500)
            return True
        except Exception as e:
            self.scrcpy_error.emit(f"启动失败: {e}")
            return False

    def _cleanup_process(self):
        """安全终止 scrcpy 子进程，清理 timer/hwnd/process 引用。
        可在 start_scrcpy 重入时、closeEvent、启动失败处理时调用。"""
        # 先停嵌入轮询 timer
        if self._embed_timer:
            self._embed_timer.stop()
            self._embed_timer = None

        if self.scrcpy_process is not None:
            try:
                # 先尝试 graceful terminate
                self.scrcpy_process.terminate()
                try:
                    self.scrcpy_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.scrcpy_process.kill()
                    try:
                        self.scrcpy_process.wait(timeout=1)
                    except Exception:
                        pass
            except Exception:
                pass

        self.scrcpy_process = None
        self.scrcpy_hwnd = None

    # ---- 嵌入阶段 ----
    def _on_embed_tick(self):
        """嵌入阶段：每 500ms 尝试获取窗口句柄并嵌入。"""
        if self.scrcpy_process is None:
            return
        ret = self.scrcpy_process.poll()
        if ret is not None:
            self._handle_process_exited(ret)
            return
        self._embed_attempts += 1
        if self._embed_attempts > 60:
            # 超时
            self._cleanup_process()
            self._status_text = "启动超时\n请检查 USB 连接和 USB 调试开关"
            self._show_placeholder = True
            self.update()
            self.scrcpy_error.emit("超时: 未找到 scrcpy 窗口")
            return
        hwnd = find_window_by_pid(self.scrcpy_process.pid)
        if hwnd is None:
            return
        # 找到窗口，开始嵌入
        self._embed_timer.stop()
        self._embed_timer = None
        self.scrcpy_hwnd = hwnd
        self._do_embed()
        # 嵌入成功后不再监控进程存活，掉线由用户点击"重连 scrcpy"手动处理
        self._show_placeholder = False
        self._status_text = ""
        self.update()
        self.scrcpy_embedded.emit()

    # ---- 启动期进程退出处理 ----
    def _handle_process_exited(self, exit_code):
        """处理嵌入成功前 scrcpy 进程退出（启动失败）。运行期不监控，故无断线分支。"""
        # 尽量读 stderr（进程已退出，communicate 应立即返回）
        err_msg = ""
        if self.scrcpy_process is not None:
            try:
                _, stderr = self.scrcpy_process.communicate(timeout=1)
                err_msg = stderr.decode('utf-8', errors='replace').strip()
            except Exception:
                pass

        self._cleanup_process()

        self._status_text = f"scrcpy 已退出 (返回码: {exit_code})"
        self._show_placeholder = True
        self.update()
        self.scrcpy_error.emit(f"scrcpy 退出 (码{exit_code}): {err_msg}")

    # ---- 窗口嵌入/调整 ----
    def _do_embed(self):
        qt_hwnd = int(self.winId())
        style = GetWindowLongW(self.scrcpy_hwnd, GWL_STYLE)
        style &= ~(WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        style |= WS_CHILD | WS_VISIBLE
        SetWindowLongW(self.scrcpy_hwnd, GWL_STYLE, style)
        SetParent(self.scrcpy_hwnd, qt_hwnd)
        SetWindowPos(self.scrcpy_hwnd, HWND_TOP, 0, 0, 0, 0,
                     SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW)
        self._resize_scrcpy()

    def _resize_scrcpy(self):
        if self.scrcpy_hwnd and self.width() > 0 and self.height() > 0:
            MoveWindow(self.scrcpy_hwnd, 0, 0, self.width(), self.height(), True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_scrcpy()

    def paintEvent(self, event):
        if self._show_placeholder:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.fillRect(self.rect(), QColor(26, 26, 46))
            painter.setPen(QColor(180, 180, 200))
            font = QFont("Microsoft YaHei", 14)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, self._status_text)

    def closeEvent(self, event):
        self._cleanup_process()
        super().closeEvent(event)

class OverlayWidget(QWidget):
    rect_drawn = pyqtSignal(QRect)
    drawing_cancelled = pyqtSignal()

    DRAWING_PEN_COLOR = QColor(255, 50, 50)
    DRAWING_FILL_COLOR = QColor(255, 50, 50, 30)

    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool |
            Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setMouseTracking(True)

        self._target_widget = parent
        self._scrcpy_hwnd = None
        self._phone_width = None
        self._phone_height = None

        self._drawing = False
        self._start_point = None
        self._end_point = None
        self._final_rect = None
        self._show_final_rect = True
        self._left_btn_down = False
        self._mask_color = QColor(0, 255, 0, 25)

        self._maintain_timer = QTimer(self)
        self._maintain_timer.timeout.connect(self._maintain_styles)
        self._maintain_timer.setInterval(200)

    def set_scrcpy_hwnd(self, hwnd):
        self._scrcpy_hwnd = hwnd

    def set_phone_resolution(self, width, height):
        self._phone_width = width
        self._phone_height = height

    def _sync_geometry(self):
        if not self._target_widget or not self._target_widget.isVisible():
            return
        top_left = self._target_widget.mapToGlobal(QPoint(0, 0))
        widget_w = self._target_widget.width()
        widget_h = self._target_widget.height()
        if widget_w <= 0 or widget_h <= 0:
            return
        if self._phone_width and self._phone_height:
            overlay_w = int(widget_h * self._phone_width / self._phone_height)
            overlay_h = widget_h
            offset_x = (widget_w - overlay_w) // 2
            overlay_x = top_left.x() + offset_x
            overlay_y = top_left.y()
        else:
            overlay_x = top_left.x()
            overlay_y = top_left.y()
            overlay_w = widget_w
            overlay_h = widget_h
        current_geo = self.geometry()
        if current_geo.x() != overlay_x or current_geo.y() != overlay_y or \
           current_geo.width() != overlay_w or current_geo.height() != overlay_h:
            self.setGeometry(overlay_x, overlay_y, overlay_w, overlay_h)

    def _maintain_styles(self):
        self._sync_geometry()
        if not self._drawing:
            SetWindowPos(int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_geometry()
        self._maintain_timer.start()

    def hideEvent(self, event):
        self._maintain_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._maintain_timer.stop()
        super().closeEvent(event)

    def show_overlay(self):
        self._sync_geometry()
        self.show()
        hwnd = int(self.winId())
        SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def _forward_mouse_to_scrcpy(self, msg, local_x, local_y, wParam=0):
        if not self._scrcpy_hwnd:
            return
        pt_screen = self.mapToGlobal(QPoint(local_x, local_y))
        pt = wintypes.POINT(pt_screen.x(), pt_screen.y())
        ScreenToClient(self._scrcpy_hwnd, ctypes.byref(pt))
        SendMessageW(self._scrcpy_hwnd, msg, wParam, make_lparam(pt.x, pt.y))

    def _start_drawing(self, pos):
        if self._drawing:
            return
        self._drawing = True
        self._show_final_rect = False
        self._start_point = pos
        self._end_point = pos
        self.setCursor(Qt.CrossCursor)
        self.grabKeyboard()
        self.update()

    def _exit_drawing(self):
        self._drawing = False
        self.releaseKeyboard()
        self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._start_drawing(event.pos())
            event.accept()
        elif event.button() == Qt.LeftButton:
            self._left_btn_down = True
            self._forward_mouse_to_scrcpy(WM_LBUTTONDOWN, event.pos().x(), event.pos().y(), MK_LBUTTON)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drawing:
            self._end_point = event.pos()
            self.update()
            event.accept()
        elif self._left_btn_down:
            self._forward_mouse_to_scrcpy(WM_MOUSEMOVE, event.pos().x(), event.pos().y(), MK_LBUTTON)
            event.accept()
        else:
            self._forward_mouse_to_scrcpy(WM_MOUSEMOVE, event.pos().x(), event.pos().y(), 0)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton and self._drawing:
            rect = QRect(self._start_point, event.pos()).normalized()
            if rect.width() >= 5 and rect.height() >= 5:
                self._final_rect = rect
                self._show_final_rect = True
                self.rect_drawn.emit(rect)
            else:
                self._final_rect = None
                self._show_final_rect = False
                self.drawing_cancelled.emit()
            self._exit_drawing()
            self.update()
            event.accept()
        elif event.button() == Qt.LeftButton:
            self._left_btn_down = False
            self._forward_mouse_to_scrcpy(WM_LBUTTONUP, event.pos().x(), event.pos().y(), 0)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._drawing:
            self._final_rect = None
            self._show_final_rect = False
            self.drawing_cancelled.emit()
            self._exit_drawing()
            self.update()
            event.accept()
        else:
            super().keyPressEvent(event)

    def set_final_rect(self, rect):
        self._final_rect = rect
        self._show_final_rect = True
        self.update()

    def clear_rect(self):
        self._final_rect = None
        self._show_final_rect = False
        self.update()

    def cycle_mask_color(self):
        if self._mask_color.alpha() > 5:
            self._mask_color = QColor(0, 0, 0, 1)
        else:
            self._mask_color = QColor(0, 255, 0, 25)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self._mask_color)
        if self._drawing and self._start_point:
            rect = QRect(self._start_point, self._end_point).normalized()
            pen = QPen(self.DRAWING_PEN_COLOR, 2, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(self.DRAWING_FILL_COLOR)
            painter.drawRect(rect)
        elif self._show_final_rect and self._final_rect:
            pen = QPen(QColor(0, 200, 100), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QColor(0, 200, 100, 25))
            painter.drawRect(self._final_rect)


# ============================================================
# 截图预览面板 — 显示 ADB 截图 + 标注框
# ============================================================
class ScreenshotCanvas(QFrame):
    """截图显示画布，支持显示图片和标注矩形框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.setMinimumHeight(150)
        self.setStyleSheet("background-color: #e8e8e8;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._pixmap = None
        self._scaled_pixmap = None
        self._offset_x = 0
        self._offset_y = 0
        self._vertices = None  # [left, top, right, bottom] 手机坐标
        # 当前截图的磁盘路径（不长期缓存全屏原图，resize 后按需从磁盘重载）
        self._filepath = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._reload_from_disk)

    def set_screenshot(self, filepath, vertices=None):
        """设置截图和标注框"""
        self._filepath = filepath if (filepath and os.path.exists(filepath)) else None
        if self._filepath:
            self._pixmap = QPixmap(self._filepath)
        else:
            self._pixmap = None
        self._vertices = vertices
        self._scale_pixmap()
        self.update()

    def clear_screenshot(self):
        """清除截图"""
        self._resize_timer.stop()
        self._filepath = None
        self._pixmap = None
        self._scaled_pixmap = None
        self._vertices = None
        self.update()

    def _reload_from_disk(self):
        """resize 防抖触发：从磁盘重新加载原图并按当前尺寸缩放重绘"""
        if not self._filepath or not os.path.exists(self._filepath):
            return
        pixmap = QPixmap(self._filepath)
        if pixmap.isNull():
            return
        self._pixmap = pixmap
        self._scale_pixmap()
        self.update()

    def _scale_pixmap(self):
        if self._pixmap is None or self._pixmap.isNull():
            self._scaled_pixmap = None
            return
        cw = self.width()
        ch = self.height()
        if cw <= 0 or ch <= 0:
            return
        pw = self._pixmap.width()
        ph = self._pixmap.height()
        ratio = min(cw / pw, ch / ph)
        nw = int(pw * ratio)
        nh = int(ph * ratio)
        self._scaled_pixmap = self._pixmap.scaled(nw, nh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._offset_x = (cw - nw) // 2
        self._offset_y = (ch - nh) // 2

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_pixmap()
        self.update()
        # 拖拽分栏时重启防抖定时器，停止 250ms 后从磁盘按新尺寸重建
        if self._filepath:
            self._resize_timer.start(250)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self._scaled_pixmap:
            painter.drawPixmap(self._offset_x, self._offset_y, self._scaled_pixmap)

            # 绘制标注框
            if self._vertices and len(self._vertices) == 4 and self._pixmap:
                scale = self._scaled_pixmap.width() / self._pixmap.width()
                left = int(self._vertices[0] * scale) + self._offset_x
                top = int(self._vertices[1] * scale) + self._offset_y
                right = int(self._vertices[2] * scale) + self._offset_x
                bottom = int(self._vertices[3] * scale) + self._offset_y
                painter.setPen(QPen(QColor(0, 255, 0, 180), 2, Qt.DashLine))
                painter.setBrush(QColor(0, 255, 0, 30))
                painter.drawRect(QRect(left, top, right - left, bottom - top))

                # 绘制中心点
                cx = (left + right) // 2
                cy = (top + bottom) // 2
                painter.setPen(QPen(QColor(255, 0, 0), 3))
                painter.drawLine(cx - 8, cy, cx + 8, cy)
                painter.drawLine(cx, cy - 8, cx, cy + 8)
        else:
            painter.setPen(QColor(150, 150, 150))
            painter.setFont(QFont("Microsoft YaHei", 11))
            painter.drawText(self.rect(), Qt.AlignCenter, '截图预览区 - 按 Ctrl+Q 截图')


# ============================================================
# 「在原图上重新拉框」画布 — 本端 ScreenshotCanvas 纯显示（拉框走 scrcpy 蒙版），
# 编辑已完成任务时需在磁盘截图文件上重画框，故单独实现一套拖框逻辑
# ============================================================
class ReLabelCanvas(QFrame):
    """重新拉框专用画布：背景为指定截图，支持鼠标左键拖拽绘制矩形框

    输出坐标即图片像素 = 手机像素，与 _phone_w/_phone_h 同口径，无需任何换算。
    """

    rect_drawn = pyqtSignal(int, int, int, int)  # left, top, right, bottom（图片/手机像素）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.setMinimumSize(400, 400)
        self.setStyleSheet("background-color: #e0e0e0;")
        self.setMouseTracking(True)

        self._pixmap = None
        self._scaled_pixmap = None
        self._offset_x = 0
        self._offset_y = 0
        self._drawing = False
        self._start_point = None
        self._current_rect = None  # 当前绘制的矩形（画布坐标）
        self._saved_rect = None    # 上一次确认的矩形

        # 尺寸稳定后再缩放，避免拖拽分栏过程中频繁重算
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(250)
        self._resize_timer.timeout.connect(self._on_resize_debounced)

    def set_pixmap(self, pixmap):
        """设置背景截图：同时清空已有的历史框，保证弹窗打开即干净背景"""
        self._pixmap = pixmap
        self._saved_rect = None
        self._current_rect = None
        self._scale_pixmap()
        self.update()

    def clear_rect(self):
        """清除绘制的矩形（Esc/重画前调用）"""
        self._saved_rect = None
        self._current_rect = None
        self.update()

    def _scale_pixmap(self):
        """将 pixmap 缩放以适应画布大小"""
        if self._pixmap is None or self._pixmap.isNull():
            self._scaled_pixmap = None
            return
        cw = self.width()
        ch = self.height()
        pw = self._pixmap.width()
        ph = self._pixmap.height()
        if pw <= 0 or ph <= 0:
            self._scaled_pixmap = None
            return
        ratio = min(cw / pw, ch / ph)
        nw = int(pw * ratio)
        nh = int(ph * ratio)
        self._scaled_pixmap = self._pixmap.scaled(nw, nh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._offset_x = (cw - nw) // 2
        self._offset_y = (ch - nh) // 2

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 250ms 防抖：拖拽分栏/窗口缩放期间不逐帧重缩放
        self._resize_timer.start()

    def _on_resize_debounced(self):
        """尺寸稳定后重新缩放并重绘（弹窗一次性持有原图，不额外读盘）"""
        self._scale_pixmap()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)

        if self._scaled_pixmap:
            painter.drawPixmap(self._offset_x, self._offset_y, self._scaled_pixmap)

            # 绘制已确认的矩形
            if self._saved_rect:
                painter.setPen(QPen(QColor(0, 255, 0, 180), 2, Qt.DashLine))
                painter.setBrush(QColor(0, 255, 0, 30))
                painter.drawRect(self._saved_rect)

            # 绘制拖拽中的矩形
            if self._current_rect:
                painter.setPen(QPen(QColor(255, 0, 0, 200), 2))
                painter.setBrush(QColor(255, 0, 0, 30))
                painter.drawRect(self._current_rect)
        else:
            painter.setPen(QColor(150, 150, 150))
            painter.setFont(QFont("Microsoft YaHei", 11))
            painter.drawText(self.rect(), Qt.AlignCenter, '未找到截图文件')

    def _canvas_to_original(self, canvas_rect):
        """将画布坐标矩形变换回原始图片（= 手机）像素坐标"""
        if self._pixmap is None or self._scaled_pixmap is None:
            return None
        if self._scaled_pixmap.width() <= 0:
            return None
        scale = self._pixmap.width() / self._scaled_pixmap.width()
        left = int((canvas_rect.x() - self._offset_x) * scale)
        top = int((canvas_rect.y() - self._offset_y) * scale)
        right = int((canvas_rect.right() - self._offset_x) * scale)
        bottom = int((canvas_rect.bottom() - self._offset_y) * scale)
        # 限制在图片范围内
        pw = self._pixmap.width()
        ph = self._pixmap.height()
        left = max(0, min(left, pw))
        top = max(0, min(top, ph))
        right = max(0, min(right, pw))
        bottom = max(0, min(bottom, ph))
        return left, top, right, bottom

    def _clamp_to_canvas(self, rect):
        """将矩形限制在图片区域内"""
        if self._scaled_pixmap is None:
            return rect
        x = max(self._offset_x, rect.x())
        y = max(self._offset_y, rect.y())
        r = min(self._offset_x + self._scaled_pixmap.width(), rect.right())
        b = min(self._offset_y + self._scaled_pixmap.height(), rect.bottom())
        return QRect(x, y, r - x, b - y)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._scaled_pixmap:
            self._drawing = True
            self._start_point = event.pos()
            self._current_rect = None

    def mouseMoveEvent(self, event):
        if self._drawing and self._start_point:
            end = event.pos()
            rect = QRect(self._start_point, end).normalized()
            self._current_rect = self._clamp_to_canvas(rect)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drawing:
            self._drawing = False
            if self._current_rect and self._current_rect.width() > 5 and self._current_rect.height() > 5:
                self._saved_rect = self._current_rect
                self._current_rect = None
                # 发送原始坐标
                coords = self._canvas_to_original(self._saved_rect)
                if coords:
                    self.rect_drawn.emit(*coords)
            else:
                self._current_rect = None
            self.update()


# ============================================================
# 「在原图上重新拉框」弹窗：编辑已完成任务时直接在磁盘原截图上重画标注框
# ============================================================
class ReLabelDialog(QDialog):
    """只喂背景图而**绝不 restore 旧框**，因此打开即干净背景，
    落实「直接清空旧框」的交互约定；[取消]/Esc 则原框保持不变。
    """

    rect_confirmed = pyqtSignal(int, int, int, int)  # left, top, right, bottom（手机像素）

    def __init__(self, pixmap, parent=None):
        # 不设 WA_DeleteOnClose：父窗口持有引用，取消/确认路径都能安全访问
        super().__init__(parent)
        self.setWindowTitle("在原图上重新拉框")
        self.setModal(False)
        self.resize(560, 720)
        self._rect = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "拖拽新框替换原标注框；[应用新框] 生效，[取消]/Esc 保留原框。\n"
            "提示：可重复拖框，以最后一次为准。"
        ))
        self.canvas = ReLabelCanvas()
        self.canvas.rect_drawn.connect(self._on_rect)
        layout.addWidget(self.canvas)

        self.hint_label = QLabel("")
        self.hint_label.setStyleSheet("color: #d93025;")
        layout.addWidget(self.hint_label)

        row = QHBoxLayout()
        btn_apply = QPushButton("应用新框")
        btn_apply.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
        btn_apply.clicked.connect(self.apply)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        row.addStretch()
        row.addWidget(btn_apply)
        row.addWidget(btn_cancel)
        layout.addLayout(row)

        # 只喂背景图：set_pixmap 内部已清空 _saved_rect/_current_rect
        self.canvas.set_pixmap(pixmap)

    def _on_rect(self, left, top, right, bottom):
        self._rect = (left, top, right, bottom)
        self.hint_label.setText("")

    def apply(self):
        """无新框时不关闭，等用户拖出一个框；有框则发 rect_confirmed 并 accept"""
        if self._rect is None:
            self.hint_label.setText("请先在原图上拖出一个新框，再点[应用新框]")
            return
        self.rect_confirmed.emit(*self._rect)
        self.accept()


# ============================================================
# 侧栏步骤条目：序号 + 磁盘缩略图 + 动作名 + 缺填标记，点击跳转
# ============================================================
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

        # 第一行：序号 + 缺填标记 + 状态
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
        self.action_label = QLabel("动作: -")
        self.action_label.setWordWrap(True)
        self.action_label.setStyleSheet("color: #333;")
        layout.addWidget(self.action_label)

    def set_index(self, step_index):
        """删除/插入重建后更新条目序号"""
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
        """confirmed=True 已完成（绿色）；False 编辑中（橙色）"""
        if confirmed:
            self.status_label.setText("✓ 已完成")
            self.status_label.setStyleSheet("color: #4CAF50;")
        else:
            self.status_label.setText("● 编辑中")
            self.status_label.setStyleSheet("color: #FF9800;")

    def set_action_text(self, text):
        self.action_label.setText(text)

    def set_missing(self, missing_list):
        """设置必填项缺失标记：missing_list 非空时显示“⚠ 缺项”，
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
    """左侧栏：顶部进度看板 + 可滚动步骤列表（当前轮次）+ 底部跳转区"""

    THUMB_CACHE_LIMIT = 64  # 缩略图 LRU 缓存上限
    THUMB_BATCH_SIZE = 20   # 每批懒加载张数

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor  # 持有 AnnotationEditor 引用以读取步骤数据
        self.item_widgets = []  # StepListItemWidget 列表，与 steps_data 下标一一对应
        # 缩略图 LRU 缓存：key=(截图文件名, vertices 元组) → 小尺寸 QPixmap
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

        task_title = QLabel("当前指令:")
        font = QFont()
        font.setBold(True)
        task_title.setFont(font)
        dashboard_layout.addWidget(task_title)

        self.task_label = QLabel("")
        self.task_label.setWordWrap(False)
        self.task_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dashboard_layout.addWidget(self.task_label)

        self.rounds_label = QLabel("轮次: 1")
        dashboard_layout.addWidget(self.rounds_label)

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
        vertices = step.get("vertices") or []
        try:
            vert_key = tuple(tuple(v) if isinstance(v, (list, tuple)) else v
                             for v in vertices)
        except TypeError:
            vert_key = ()
        return (step.get("screenshot"), vert_key)

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
        """指定步骤的截图/标注发生变化时失效其缓存"""
        if 0 <= index < len(self.editor.steps_data):
            key = self._cache_key(self.editor.steps_data[index])
            self._thumb_cache.pop(key, None)

    def remove_thumb_cache_by_filename(self, filename):
        """删除步骤后清理该截图文件名对应的全部缩略图缓存条目"""
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
        if index < 0 or index >= len(self.editor.steps_data):
            return
        step = self.editor.steps_data[index]
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
        batch = self._thumb_queue[:self.THUMB_BATCH_SIZE]
        self._thumb_queue = self._thumb_queue[self.THUMB_BATCH_SIZE:]
        for index in batch:
            if index < 0 or index >= len(self.item_widgets) \
                    or index >= len(self.editor.steps_data):
                continue
            item = self.item_widgets[index]
            if item.thumb_loaded:
                continue
            step = self.editor.steps_data[index]
            key = self._cache_key(step)
            cached = self._get_cached_thumb(key)
            if cached is None:
                # 从磁盘加载原图、画 vertices 框后缩放到小尺寸，原图随即释放
                cached = self.editor.build_marked_preview(
                    step.get("screenshot"),
                    step.get("vertices"),
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
        """步骤集合变化（确认/删除/插入/重置/恢复）后全量重建条目"""
        # 移除旧条目
        for item in self.item_widgets:
            self.list_layout.removeWidget(item)
            item.setParent(None)
            item.deleteLater()
        self.item_widgets = []
        self._thumb_queue = []
        self._thumb_timer.stop()

        total = len(self.editor.steps_data)
        for i in range(total):
            item = self._create_item(i)
            self.item_widgets.append(item)
            self.refresh_step_item(i)
            self.request_thumb(i)
        self.jump_spin.setMaximum(max(total, 1))
        # 所有缩略图进入懒加载队列（当前步骤插队优先）
        if total:
            self._thumb_queue = list(range(total))
            current = self.editor.current_step
            if 0 <= current < total:
                self._thumb_queue.remove(current)
                self._thumb_queue.insert(0, current)
            self._thumb_timer.start(10)
        # 步骤集合变化的唯一全量点：重建缺项缓存、条目标记与看板
        self.editor.revalidate_all_missing()

    def refresh_step_item(self, index):
        """仅刷新单个条目（序号/状态/动作类型/缺填/高亮），不重建列表"""
        if index < 0 or index >= len(self.item_widgets):
            return
        item = self.item_widgets[index]
        item.set_index(index)

        if index >= len(self.editor.steps_data):
            return
        step = self.editor.steps_data[index]
        # 单表单模型：steps_data 内均为已保存步骤；与表单同下标的为编辑中
        is_current = (index == self.editor.current_step)
        item.set_status(not is_current)
        item.set_current(is_current)

        # 动作类型中文名/英文：从 ANDROID_ACTIONS 反查
        action_en = (step.get("action_data") or {}).get("action", "-")
        action_cn = next((label for value, label in ANDROID_ACTIONS
                          if value == action_en), "")
        item.set_action_text(f"动作: {action_cn}" if action_cn
                             else f"动作: {action_en}")

        # 必填项缺失标记：取缓存（revalidate_all_missing 维护），缓存缺失时实时兜底
        missing = self.editor.get_cached_missing(index)
        if missing is None:
            missing = self.editor.validate_step_at(index)
        item.set_missing(missing)

    def refresh_highlight(self):
        """切换步骤时只更新高亮与状态，避免遍历全部条目"""
        for i, item in enumerate(self.item_widgets):
            is_current = (i == self.editor.current_step)
            item.set_current(is_current)
            item.set_status(not is_current)

    def refresh_dashboard(self):
        """刷新进度看板：指令、轮次、步数统计、动作分布、自动保存状态"""
        # 任务指令超长截断，tooltip 保留全文
        instruction = self.editor.task_instruction or ""
        self.task_label.setToolTip(instruction)
        metrics = QFontMetrics(self.task_label.font())
        elided = metrics.elidedText(instruction, Qt.ElideRight, self.width() - 30)
        self.task_label.setText(elided)

        total = len(self.editor.steps_data)
        current = self.editor.current_step
        # 已保存轮次数 + 当前进行中的一轮
        rounds_count = len(self.editor.rounds) + (0 if self.editor._current_round_saved else 1)
        self.rounds_label.setText(f"轮次: {max(rounds_count, 1)}")
        self.count_label.setText(f"总步数: {total}    当前位置: {min(current + 1, max(total, 1))}")

        # 待完善计数：历史缺项读缓存，未确认新步读 live 槽；刷新本身不触发全量重算
        missing_count = sum(1 for i in range(total)
                            if self.editor.get_cached_missing(i))
        live_missing = self.editor.live_missing_reasons()
        if live_missing:
            missing_count += 1
        self.missing_count_label.setText(f"待完善: {missing_count}")

        # 动作类型分布（直接读 steps_data 快照）
        action_counts = {}
        for step in self.editor.steps_data:
            name = (step.get("action_data") or {}).get("action", "unknown")
            action_counts[name] = action_counts.get(name, 0) + 1
        if action_counts:
            ordered = sorted(action_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            stats_text = "  ".join(f"{name}:{count}" for name, count in ordered)
        else:
            stats_text = "-"
        self.action_stats_label.setText(f"动作分布: {stats_text}")

        self.jump_spin.setMaximum(max(total, 1))

        # 轮次回看入口：仅在存在已落轮时可用（初始化顺序差异用 hasattr 防护）
        if hasattr(self.editor, "view_rounds_btn"):
            self.editor.view_rounds_btn.setEnabled(bool(self.editor.rounds))

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
        if self.editor.steps_data:
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
        current = item if item is not None else self.list_widget.currentItem()
        if current is None:
            return
        self._target_index = int(current.data(Qt.UserRole))
        self.accept()

    def target_index(self):
        """对话框关闭后读取用户请求跳转的下标；未选择跳转返回 None"""
        return self._target_index


# ============================================================
# 已完成轮次只读回看器
# ============================================================
class RoundPreviewDialog(QDialog):
    """只读多轮回看器：按轮次浏览已完成轨迹的截图与拉框标记

    只读约束：不修改 editor.steps_data / editor.rounds / editor.coords_data，
    也不写草稿；缩略图 LRU 为对话框私有，不与侧栏 SideBarWidget._thumb_cache 共享。
    """

    THUMB_SIZE = QSize(160, 90)
    THUMB_BATCH_SIZE = 20
    THUMB_CACHE_LIMIT = 128
    NO_PREVIEW_TEXT = "截图文件缺失或无法加载"

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self._entries = []       # 当前轮条目：[{step, action, filename, vertices}, ...]
        self._thumb_queue = []   # 待生成缩略图的条目下标
        # 独立 LRU：(截图文件名, repr(vertices)) → 小尺寸 QPixmap
        self._thumb_cache = OrderedDict()
        self._current_entry_index = None
        self._placeholder = None

        self.setWindowTitle("已完成轮次回看")
        self.resize(980, 620)
        self._init_ui()
        self._populate_rounds()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("轮次："))
        self.round_combo = QComboBox()
        self.round_combo.setMinimumWidth(420)
        self.round_combo.currentIndexChanged.connect(self._on_round_changed)
        top.addWidget(self.round_combo)
        self.round_count_label = QLabel("")
        top.addWidget(self.round_count_label)
        top.addStretch()
        layout.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)

        self.step_list = QListWidget()
        self.step_list.setViewMode(QListWidget.IconMode)
        self.step_list.setIconSize(self.THUMB_SIZE)
        self.step_list.setGridSize(QSize(170, 130))
        self.step_list.setResizeMode(QListWidget.Adjust)
        self.step_list.setMovement(QListWidget.Static)
        self.step_list.setSpacing(6)
        self.step_list.currentRowChanged.connect(self._on_entry_selected)
        splitter.addWidget(self.step_list)

        self.preview_label = QLabel("")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(360, 240)
        self.preview_label.setStyleSheet("background-color: #1e1e1e; color: #cccccc;")
        splitter.addWidget(self.preview_label)
        splitter.setSizes([340, 620])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self.thumb_timer = QTimer(self)
        self.thumb_timer.setSingleShot(True)
        self.thumb_timer.timeout.connect(self._load_thumb_batch)

    # ---------- 轮次/条目构建（纯读取） ----------

    def _populate_rounds(self):
        rounds = self.editor.rounds or []
        self.round_combo.blockSignals(True)
        for i, round_data in enumerate(rounds):
            instruction = ""
            if isinstance(round_data, dict):
                instruction = (round_data.get("instruction") or "").strip()
            short = instruction[:30] + ("…" if len(instruction) > 30 else "")
            self.round_combo.addItem(f"第 {i + 1} 轮 · {short}")
            self.round_combo.setItemData(i, instruction, Qt.ToolTipRole)
        self.round_combo.blockSignals(False)
        if rounds:
            self.round_combo.setCurrentIndex(0)
            self._on_round_changed(0)

    def _round_coords(self, round_index):
        """该轮 coords 条目：编辑态优先用 _coords_rounds（与 rounds 等长时更准）"""
        rounds = self.editor.rounds
        coords_rounds = getattr(self.editor, "_coords_rounds", None)
        if isinstance(coords_rounds, list) and len(coords_rounds) == len(rounds):
            return coords_rounds[round_index] or []
        round_data = rounds[round_index]
        if isinstance(round_data, dict):
            return round_data.get("coords") or []
        return []

    def _build_entries(self, round_index):
        """把一轮 trajectory 与 coords 按 step 对齐成只读条目列表"""
        coords_by_step = {}
        for entry in self._round_coords(round_index):
            if not isinstance(entry, dict):
                continue
            step = entry.get("step")
            if isinstance(step, int) and not isinstance(step, bool):
                coords_by_step[step] = entry

        round_data = self.editor.rounds[round_index]
        trajectory = round_data.get("trajectory") if isinstance(round_data, dict) else []
        entries = []
        for position, traj in enumerate(trajectory or []):
            if not isinstance(traj, dict):
                continue
            step = traj.get("step")
            if not isinstance(step, int) or isinstance(step, bool):
                step = position
            actions = traj.get("actions") or []
            action_en = ""
            if actions and isinstance(actions[0], dict):
                action_en = actions[0].get("action", "") or ""
            observation = traj.get("observation") or {}
            filename = ""
            if isinstance(observation, dict):
                filename = observation.get("screenshot", "") or ""
            vertices = None
            entry = coords_by_step.get(step)
            if isinstance(entry, dict):
                vertices = AnnotationEditor._valid_vertices(entry.get("vertices"))
            entries.append({"step": step, "action": action_en,
                            "filename": filename, "vertices": vertices})
        return entries

    @staticmethod
    def _action_label(action_en):
        return next((label for value, label in ANDROID_ACTIONS
                     if value == action_en), action_en or "-")

    # ---------- 轮次切换 / 缩略图懒加载 ----------

    def _on_round_changed(self, index):
        if not (0 <= index < len(self.editor.rounds)):
            return
        self.thumb_timer.stop()
        self.step_list.clear()
        self._entries = self._build_entries(index)
        self._current_entry_index = None
        self._thumb_queue = list(range(len(self._entries)))
        self.round_count_label.setText(f"该轮共 {len(self._entries)} 步")
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText("" if self._entries else "该轮没有步骤")
        for i, entry in enumerate(self._entries):
            item = QListWidgetItem(
                f"第 {i + 1} 步 · {self._action_label(entry['action'])}")
            item.setIcon(QIcon(self._placeholder_pixmap()))
            self.step_list.addItem(item)
        if self._entries:
            self.thumb_timer.start(10)

    def _placeholder_pixmap(self):
        """占位图标：缩略图生成前/生成失败时显示"""
        if self._placeholder is None:
            pixmap = QPixmap(self.THUMB_SIZE)
            pixmap.fill(QColor("#2b2b2b"))
            painter = QPainter(pixmap)
            painter.setPen(QColor("#888888"))
            painter.drawText(pixmap.rect(), Qt.AlignCenter, "加载中…")
            painter.end()
            self._placeholder = pixmap
        return self._placeholder

    def _load_thumb_batch(self):
        if not self._thumb_queue:
            return
        batch = self._thumb_queue[:self.THUMB_BATCH_SIZE]
        del self._thumb_queue[:self.THUMB_BATCH_SIZE]
        for entry_index in batch:
            if entry_index >= len(self._entries):
                continue
            item = self.step_list.item(entry_index)
            if item is None:
                continue
            pixmap = self._thumb_of(self._entries[entry_index])
            if pixmap is None:
                item.setToolTip(self.NO_PREVIEW_TEXT)
            else:
                item.setIcon(QIcon(pixmap))
        if self._thumb_queue:
            self.thumb_timer.start(10)
            return
        # 全部缩略图就绪：自动选中第 1 项并刷新大图
        if self.step_list.count():
            self.step_list.setCurrentRow(0)

    def _thumb_of(self, entry):
        key = (entry["filename"], repr(entry["vertices"]))
        cached = self._thumb_cache.get(key)
        if cached is not None:
            self._thumb_cache.move_to_end(key)
            return cached
        pixmap = self.editor.build_marked_preview(
            entry["filename"], entry["vertices"], self.THUMB_SIZE)
        if pixmap is not None:
            self._thumb_cache[key] = pixmap
            while len(self._thumb_cache) > self.THUMB_CACHE_LIMIT:
                self._thumb_cache.popitem(last=False)
        return pixmap

    # ---------- 大图预览 ----------

    def _on_entry_selected(self, row):
        if not (0 <= row < len(self._entries)):
            self._current_entry_index = None
            return
        self._current_entry_index = row
        self._refresh_preview()

    def _refresh_preview(self):
        index = self._current_entry_index
        if index is None or not (0 <= index < len(self._entries)):
            return
        entry = self._entries[index]
        size = self.preview_label.size()
        if size.width() <= 1 or size.height() <= 1:
            size = QSize(600, 400)
        pixmap = self.editor.build_marked_preview(
            entry["filename"], entry["vertices"], size)
        if pixmap is None or pixmap.isNull():
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText(self.NO_PREVIEW_TEXT)
            return
        self.preview_label.setText("")
        self.preview_label.setPixmap(pixmap)

    def resizeEvent(self, event):
        """窗口尺寸变化后按新尺寸重绘当前预览"""
        super().resizeEvent(event)
        if self._current_entry_index is not None:
            QTimer.singleShot(0, self._refresh_preview)


# ============================================================
# 标注编辑器主窗口
# ============================================================
class AnnotationEditor(QMainWindow):
    """GUI长步骤采标工具-Android 标注编辑器主窗口"""

    _screenshot_finished = pyqtSignal(int, int, str, bool, str)

    def __init__(self, data_manager, app_name, task_instruction, screen_info, app_type="", serial=None, init_window=None):
        super().__init__()
        self.data_manager = data_manager
        self.app_name = app_name
        self.task_instruction = task_instruction
        self.screen_info = screen_info
        self.app_type = app_type
        self._serial = serial
        self._init_window = init_window

        # 步骤数据
        self.current_step = 0
        self.steps_data = []
        self.coords_data = []
        self.rounds = []
        self.screenshot_cache = None
        self._current_screenshot_filename = None
        self._current_screenshot_filepath = None
        self.gui_number = None
        self.gui_dir = None

        # 模块
        self.screen_capture = AndroidScreenCapture(serial=serial)

        # UI 状态
        self._action_widgets = {}
        self._current_vertices = None
        self._swipe_measuring = False
        self._swipe_start_vertices = None
        self._scroll_measuring = False
        self._scroll_references = []
        self._scroll_start_vertices = None
        # 连续滚动测量：总累计像素 + 当前参照物的基线Y + 是否在等待设定新参照物
        self._scroll_total = 0
        self._scroll_baseline_y = None
        self._scroll_resetting = False
        self._current_round_saved = False
        self._task_completed = False  # 正常完成后由 _finish_task 置 True，closeEvent 据此跳过草稿保存

        # 编辑已完成任务模式（不写草稿、确认不切轮次、关闭自动写回最终 JSON）
        self._edit_mode = False
        self._completed_json = None      # 加载时的最终 JSON 深拷贝（写回时保留顶层字段）
        self._edit_round_index = 0       # 当前编辑轮次下标
        self._coords_rounds = []         # 按轮次分组的 coords 条目
        self._coord_issues = []          # 编辑态 hydration 检出的 bbox↔坐标不一致清单
        self._original_coords_exist = False  # 加载时磁盘上是否已有 coords 文件
        self._edit_final_saved = False   # 「保存修改」成功或关闭自动写回后置 True

        # 截图防重入标志：确保同一时间只发送一条 adb 截图命令
        self._screenshot_in_progress = False
        # B2 轮次切换门闩：answer 落轮后用 singleShot(300) 延后弹新轮对话框。这 300ms 内
        # 当前轮已写入 rounds 且 task_instruction 还是旧指令，窗口内的截图/确认会直接
        # 改动已落轮那一步的截图与表单（_current_round_saved 只阻止重复 append，不阻止
        # 内容被重画）。置 True 期间所有采集/编辑入口一律早退。
        self._round_transition_pending = False
        self._screenshot_seq = 0  # 截图序号，用于丢弃过期的后台截图结果
        self._screenshot_cooldown_ms = 800  # 截图完成后冷却时间，防止快速双击触发第二次 adb

        # 手机屏幕分辨率
        phone_sz = screen_info.get("screen_size", [1080, 2400])
        self._phone_w = phone_sz[0]
        self._phone_h = phone_sz[1]

        # 「在原图上重新拉框」弹窗引用（仅编辑已完成任务时按需创建）
        self._relabel_dialog = None

        # 长轨迹支持：必填项缺失缓存（步骤下标 -> 中文缺失原因列表）
        self._missing_cache = {}
        # 未确认新步（current_step == len(steps_data)）的实时缺项槽
        self._missing_live = None
        # 中间步插入锚点：None=截图覆盖/追加当前步；整数=在该下标之后插入新步
        self._insert_after_index = None
        # 草稿增量自动保存：约 1000ms 防抖，数据变化点只负责调度
        self.draft_timer = QTimer(self)
        self.draft_timer.setSingleShot(True)
        self.draft_timer.timeout.connect(self._write_draft_now)
        # 必填校验防抖：约 300ms 重启计时，输入停顿后重算当前步缺项
        self.validation_timer = QTimer(self)
        self.validation_timer.setSingleShot(True)
        self.validation_timer.setInterval(300)
        self.validation_timer.timeout.connect(self._on_validation_debounced)

        self.setWindowTitle(f"GUI长步骤采标工具-Android - {app_name}")
        self.setGeometry(50, 30, 1500, 950)
        self.init_ui()
        self._setup_shortcuts()
        self._screenshot_finished.connect(self._on_screenshot_finished)

    def _setup_shortcuts(self):
        """注册快捷键

        注意：不绑定普通单键（如方向键/Escape），避免劫持输入框编辑。
        撤销上一步仅在焦点不在文本输入控件时生效。
        """
        sc_screenshot = QShortcut(QKeySequence("Ctrl+Q"), self)
        sc_screenshot.setContext(Qt.ApplicationShortcut)
        sc_screenshot.setAutoRepeat(False)
        sc_screenshot.activated.connect(self.take_screenshot)

        sc_next = QShortcut(QKeySequence("Ctrl+S"), self)
        sc_next.setContext(Qt.ApplicationShortcut)
        sc_next.activated.connect(self.go_next)

        sc_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        sc_undo.setContext(Qt.WindowShortcut)
        sc_undo.setAutoRepeat(False)
        sc_undo.activated.connect(self._on_undo_shortcut)

    def _is_editing_text(self):
        """判断当前焦点是否在文本输入/下拉控件上"""
        w = QApplication.focusWidget()
        return isinstance(w, (QLineEdit, QComboBox))

    def _on_undo_shortcut(self):
        if self._is_editing_text():
            return
        self.undo_step()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # === 顶部工具栏 ===
        toolbar = QHBoxLayout()

        self.btn_prev = QPushButton("← 上一步")
        self.btn_prev.clicked.connect(self.go_previous)
        toolbar.addWidget(self.btn_prev)

        self.step_label = QLabel("步骤: 0")
        self.step_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self.step_label.setAlignment(Qt.AlignCenter)
        self.step_label.setFixedWidth(120)
        toolbar.addWidget(self.step_label)

        self.btn_next = QPushButton("下一步 →")
        self.btn_next.clicked.connect(self.go_next)
        toolbar.addWidget(self.btn_next)

        toolbar.addSpacing(20)

        self.btn_undo = QPushButton("撤销上一步 (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.undo_step)
        toolbar.addWidget(self.btn_undo)

        self.btn_clear = QPushButton("清除标注")
        self.btn_clear.clicked.connect(self.clear_annotations)
        toolbar.addWidget(self.btn_clear)

        self.btn_mask = QPushButton("显示/隐藏蒙版")
        self.btn_mask.clicked.connect(self._toggle_mask)
        toolbar.addWidget(self.btn_mask)

        # scrcpy 手动重连按钮：任何时候都可点击，点击即重新拉起 scrcpy
        self.btn_reconnect_scrcpy = QPushButton("重连 scrcpy")
        self.btn_reconnect_scrcpy.setStyleSheet(
            "QPushButton { background-color: #FF9800; color: white; padding: 6px 12px; }"
            "QPushButton:hover { background-color: #F57C00; }"
        )
        self.btn_reconnect_scrcpy.clicked.connect(self._reconnect_scrcpy)
        toolbar.addWidget(self.btn_reconnect_scrcpy)

        toolbar.addSpacing(20)

        # 中间步骤编辑：删除当前步（后一步数据回填表单）
        self.btn_delete_step = QPushButton("删除当前步")
        self.btn_delete_step.setStyleSheet(
            "QPushButton { background-color: #E53935; color: white; padding: 6px 12px; }"
            "QPushButton:hover { background-color: #C62828; }"
        )
        self.btn_delete_step.clicked.connect(self.delete_current_step)
        toolbar.addWidget(self.btn_delete_step)

        # 中间步骤编辑：在当前步之后插入新步（复用截图链）
        self.btn_insert_step = QPushButton("在当前步后插入")
        self.btn_insert_step.setStyleSheet(
            "QPushButton { background-color: #FB8C00; color: white; padding: 6px 12px; }"
            "QPushButton:hover { background-color: #EF6C00; }"
        )
        self.btn_insert_step.clicked.connect(self.start_insert_capture)
        toolbar.addWidget(self.btn_insert_step)

        # 编辑已完成任务时可见：不重新截图，直接在磁盘原图上重新拖框
        self.btn_relabel = QPushButton("在原图上重新拉框")
        self.btn_relabel.setStyleSheet(
            "QPushButton { background-color: #9C27B0; color: white; padding: 6px 12px; }"
            "QPushButton:hover { background-color: #7B1FA2; }"
        )
        self.btn_relabel.clicked.connect(self.relabel_current_step)
        self.btn_relabel.hide()
        toolbar.addWidget(self.btn_relabel)

        toolbar.addStretch()

        # 只读回看已完成轮次（无已落轮时禁用，见 SideBarWidget.refresh_dashboard）
        self.view_rounds_btn = QPushButton("查看已完成轮次")
        self.view_rounds_btn.setStyleSheet(
            "QPushButton { background-color: #607D8B; color: white; padding: 6px 12px; }"
            "QPushButton:hover { background-color: #455A64; }"
        )
        self.view_rounds_btn.setEnabled(False)
        self.view_rounds_btn.clicked.connect(self.show_round_preview_dialog)
        toolbar.addWidget(self.view_rounds_btn)

        self.btn_screenshot = QPushButton("截图 (Ctrl+Q)")
        self.btn_screenshot.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1976D2; }"
        )
        self.btn_screenshot.clicked.connect(self.take_screenshot)
        toolbar.addWidget(self.btn_screenshot)

        self.btn_confirm = QPushButton("确认 (Ctrl+S)")
        self.btn_confirm.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #43A047; }"
        )
        self.btn_confirm.clicked.connect(self.go_next)
        toolbar.addWidget(self.btn_confirm)

        # 编辑已完成任务：校验当前轮并写回最终 JSON / coords（默认隐藏）
        self.btn_save_edit = QPushButton("保存修改")
        self.btn_save_edit.setStyleSheet(
            "QPushButton { background-color: #7E57C2; color: white; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #5E35B1; }"
        )
        self.btn_save_edit.clicked.connect(lambda: self.save_edited_round(False))
        self.btn_save_edit.hide()
        toolbar.addWidget(self.btn_save_edit)

        main_layout.addLayout(toolbar)

        # === 主内容区域：外层分栏 [步骤侧栏 | scrcpy/编辑区] ===
        outer_splitter = QSplitter(Qt.Horizontal)

        # ---- 最左侧：步骤导航侧栏 ----
        self.sidebar = SideBarWidget(self)
        self.sidebar.setMinimumWidth(200)
        outer_splitter.addWidget(self.sidebar)

        main_splitter = QSplitter(Qt.Horizontal)

        # ---- 左侧：scrcpy ----
        left_panel = QWidget()
        left_panel.setMinimumWidth(400)

        self.scrcpy_widget = ScrcpyEmbedWidget()
        self.scrcpy_widget.scrcpy_embedded.connect(self._on_scrcpy_ready)
        self.scrcpy_widget.scrcpy_error.connect(self._on_scrcpy_error)

        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.scrcpy_widget)

        # 蒙版层（覆盖在 scrcpy 上方）
        self.overlay = OverlayWidget(self.scrcpy_widget)
        self.overlay.rect_drawn.connect(self._on_overlay_rect_drawn)
        self.overlay.drawing_cancelled.connect(self._on_overlay_cancelled)

        main_splitter.addWidget(left_panel)

        # ---- 右侧：动作信息面板 ----
        right_panel = QWidget()
        right_panel.setMinimumWidth(320)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)

        # 动作组
        action_group = QGroupBox("动作信息")
        action_form = QFormLayout()

        self.intent_input = QLineEdit()
        self.intent_input.setPlaceholderText("描述当前步骤的动作（如：点击搜索按钮）")
        action_form.addRow("动作描述:", self.intent_input)

        self.action_combo = QComboBox()
        for value, label in ANDROID_ACTIONS:
            self.action_combo.addItem(label, value)
        self.action_combo.currentIndexChanged.connect(self.on_action_changed)
        action_form.addRow("动作类型:", self.action_combo)

        # 坐标
        coord_widget = QWidget()
        coord_layout = QHBoxLayout(coord_widget)
        coord_layout.setContentsMargins(0, 0, 0, 0)
        self.coord_x_input = QLineEdit()
        self.coord_x_input.setPlaceholderText("x")
        self.coord_x_input.setFixedWidth(80)
        self.coord_y_input = QLineEdit()
        self.coord_y_input.setPlaceholderText("y")
        self.coord_y_input.setFixedWidth(80)
        self.coord_label = QLabel("坐标 [x, y]:")
        coord_layout.addWidget(self.coord_label)
        coord_layout.addWidget(self.coord_x_input)
        coord_layout.addWidget(self.coord_y_input)
        coord_layout.addStretch()
        self._action_widgets["coordinate"] = coord_widget
        action_form.addRow(coord_widget)

        # 终点坐标 (swipe)
        coord2_widget = QWidget()
        coord2_layout = QHBoxLayout(coord2_widget)
        coord2_layout.setContentsMargins(0, 0, 0, 0)
        self.coord2_x_input = QLineEdit()
        self.coord2_x_input.setPlaceholderText("x2")
        self.coord2_x_input.setFixedWidth(80)
        self.coord2_y_input = QLineEdit()
        self.coord2_y_input.setPlaceholderText("y2")
        self.coord2_y_input.setFixedWidth(80)
        self.coord2_label = QLabel("终点 [x2, y2]:")
        coord2_layout.addWidget(self.coord2_label)
        coord2_layout.addWidget(self.coord2_x_input)
        coord2_layout.addWidget(self.coord2_y_input)
        coord2_layout.addStretch()
        self._action_widgets["coordinate2"] = coord2_widget
        action_form.addRow(coord2_widget)

        # swipe / drag 测量按钮
        swipe_measure_widget = QWidget()
        swipe_measure_layout = QHBoxLayout(swipe_measure_widget)
        swipe_measure_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_swipe_measure = QPushButton("开始测量滑动/拖拽")
        self.btn_swipe_measure.setStyleSheet(
            "QPushButton { background-color: #FF9800; color: white; padding: 4px 12px; }"
        )
        self.btn_swipe_measure.clicked.connect(self._start_swipe_measurement)
        self.btn_swipe_finish = QPushButton("完成测量")
        self.btn_swipe_finish.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; padding: 4px 12px; }"
        )
        self.btn_swipe_finish.clicked.connect(self._finish_swipe_measurement)
        self.btn_swipe_finish.hide()
        swipe_measure_layout.addWidget(self.btn_swipe_measure)
        swipe_measure_layout.addWidget(self.btn_swipe_finish)
        swipe_measure_layout.addStretch()
        self._action_widgets["swipe_measure"] = swipe_measure_widget
        action_form.addRow(swipe_measure_widget)

        # scroll 测量按钮（多次选择参照物滑动后生成像素）
        scroll_measure_widget = QWidget()
        scroll_measure_layout = QHBoxLayout(scroll_measure_widget)
        scroll_measure_layout.setContentsMargins(0, 0, 0, 0)
        self.pixels_input = QLineEdit()
        self.pixels_input.setPlaceholderText("正值=内容下移，负值=上移")
        self.pixels_input.setFixedWidth(120)
        self.pixels_input.setReadOnly(True)
        self.btn_scroll_measure = QPushButton("开始测量滚动")
        self.btn_scroll_measure.setStyleSheet(
            "QPushButton { background-color: #FF9800; color: white; padding: 4px 12px; }"
        )
        self.btn_scroll_measure.clicked.connect(self._start_scroll_measurement)
        self.btn_scroll_finish = QPushButton("完成测量")
        self.btn_scroll_finish.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; padding: 4px 12px; }"
        )
        self.btn_scroll_finish.clicked.connect(self._finish_scroll_measurement)
        self.btn_scroll_finish.hide()
        self.btn_scroll_reset = QPushButton("重设参照物")
        self.btn_scroll_reset.setStyleSheet(
            "QPushButton { background-color: #9E9E9E; color: white; padding: 4px 10px; }"
        )
        self.btn_scroll_reset.clicked.connect(self._on_scroll_reset_reference)
        self.btn_scroll_reset.setToolTip("长列表滚动时，参照物滚出屏幕后换用它为新基线")
        self.btn_scroll_reset.hide()
        scroll_measure_layout.addWidget(QLabel("滚动像素:"))
        scroll_measure_layout.addWidget(self.pixels_input)
        scroll_measure_layout.addWidget(self.btn_scroll_measure)
        scroll_measure_layout.addWidget(self.btn_scroll_finish)
        scroll_measure_layout.addWidget(self.btn_scroll_reset)
        scroll_measure_layout.addStretch()
        self._action_widgets["scroll_measure"] = scroll_measure_widget
        action_form.addRow(scroll_measure_widget)

        # 文本（标签随动作类型语义化变化）
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("输入文本内容")
        self._action_widgets["text"] = self.text_input
        self.text_label = QLabel("文本:")
        action_form.addRow(self.text_label, self.text_input)

        # 组合按键 (key)
        self.keys_input = QLineEdit()
        self.keys_input.setPlaceholderText("逗号分隔，如 ctrl,c")
        self._action_widgets["keys"] = self.keys_input
        self.keys_label = QLabel("组合按键(keys):")
        action_form.addRow(self.keys_label, self.keys_input)

        # 时间
        self.time_input = QLineEdit()
        self.time_input.setPlaceholderText("秒数（如：2.0）")
        self._action_widgets["time"] = self.time_input
        self.time_label = QLabel("时间(秒):")
        action_form.addRow(self.time_label, self.time_input)

        # 系统按钮
        self.button_combo = QComboBox()
        self.button_combo.addItems(SYSTEM_BUTTONS)
        self._action_widgets["button"] = self.button_combo
        action_form.addRow("系统按钮:", self.button_combo)

        # 任务状态（terminate 固定为 success）
        self.status_label = QLabel("success")
        self.status_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
        self._action_widgets["status"] = self.status_label
        action_form.addRow("任务状态:", self.status_label)

        action_group.setLayout(action_form)

        # 右侧参数表单放入滚动区，窄窗口下不挤压截图预览
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        form_scroll.setWidget(action_group)

        # 编辑区分栏：左截图预览（约 65%）| 右参数表单（约 35%）
        editor_splitter = QSplitter(Qt.Horizontal)

        # 左：截图详情 + 截图预览
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        # 截图详情
        detail_group = QGroupBox("截图信息")
        detail_layout = QFormLayout()
        self.screenshot_name_label = QLabel("(暂无)")
        self.screenshot_size_label = QLabel("-")
        detail_layout.addRow("文件名:", self.screenshot_name_label)
        detail_layout.addRow("尺寸:", self.screenshot_size_label)
        detail_group.setLayout(detail_layout)
        preview_layout.addWidget(detail_group)

        # 截图预览面板（resize 后防抖从磁盘按新尺寸重建）
        self.screenshot_canvas = ScreenshotCanvas()
        preview_layout.addWidget(self.screenshot_canvas, 1)

        preview_panel.setMinimumWidth(420)
        form_scroll.setMinimumWidth(300)
        editor_splitter.addWidget(preview_panel)
        editor_splitter.addWidget(form_scroll)
        editor_splitter.setStretchFactor(0, 3)
        editor_splitter.setStretchFactor(1, 2)
        editor_splitter.setSizes([740, 400])
        right_layout.addWidget(editor_splitter, 1)

        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 4)
        main_splitter.setStretchFactor(1, 1)

        outer_splitter.addWidget(main_splitter)
        outer_splitter.setStretchFactor(0, 0)
        outer_splitter.setStretchFactor(1, 1)
        outer_splitter.setSizes([240, 1260])

        main_layout.addWidget(outer_splitter, 1)

        # === 状态栏 ===
        self.status_label = QLabel('就绪 - 请先完成任务初始化和截图')
        self.status_label.setStyleSheet("padding: 5px; background-color: #f0f0f0;")
        main_layout.addWidget(self.status_label)

        self._update_action_fields_visibility()
        self._update_navigation_buttons()
        # 输入变化联动：300ms 防抖重算必填校验 + 1000ms 防抖保存草稿
        self._connect_editor_validation_signals()
        # 侧栏初始构建（此时 steps_data 为空，仅初始化看板与跳转区）
        self.sidebar.rebuild_items()

    def _connect_editor_validation_signals(self):
        """连接各输入控件：变化时重启校验防抖并调度草稿保存"""
        def on_change(*args):
            self.validation_timer.start()
            self.schedule_draft_save()

        self.intent_input.textChanged.connect(on_change)
        self.text_input.textChanged.connect(on_change)
        self.keys_input.textChanged.connect(on_change)
        self.time_input.textChanged.connect(on_change)
        self.coord_x_input.textChanged.connect(on_change)
        self.coord_y_input.textChanged.connect(on_change)
        self.coord2_x_input.textChanged.connect(on_change)
        self.coord2_y_input.textChanged.connect(on_change)
        self.pixels_input.textChanged.connect(on_change)
        self.button_combo.currentIndexChanged.connect(on_change)

    # ========== 动作 UI ==========

    def _update_action_fields_visibility(self):
        action = self._current_action_key()
        for key, widget in self._action_widgets.items():
            visible = False
            if key == "coordinate" and (action in COORD_ACTIONS or action in START_END_ACTIONS):
                visible = True
            elif key == "coordinate2" and action in START_END_ACTIONS:
                visible = True
            elif key == "swipe_measure" and action in START_END_ACTIONS:
                visible = True
            elif key == "scroll_measure" and action == "scroll":
                visible = True
            elif key == "text" and action in TEXT_ACTIONS:
                visible = True
            elif key == "keys" and action in KEY_ACTIONS:
                visible = True
            elif key == "time" and action in TIME_ACTIONS:
                visible = True
            elif key == "button" and action in BUTTON_ACTIONS:
                visible = True
            elif key == "status" and action == "terminate":
                visible = True
            if isinstance(widget, QWidget):
                widget.setVisible(visible)

        # 随动作类型切换语义化中文标签
        if action in START_END_ACTIONS:
            self.coord_label.setText("起点坐标 [x, y]:")
        else:
            self.coord_label.setText("坐标 [x, y]:")
        self.coord2_label.setText("终点坐标 [x, y]:")
        if action == "type":
            self.text_label.setText("输入文本:")
        elif action == "open_app":
            self.text_label.setText("应用名称:")
        elif action == "open_url":
            self.text_label.setText("网址 URL:")
        elif action in ("answer", "answer_terminate"):
            self.text_label.setText("回答内容:")
        else:
            self.text_label.setText("文本:")
        self.keys_label.setText("按键:")
        if action == "long_press":
            self.time_label.setText("长按时间（秒）:")
        elif action == "wait":
            self.time_label.setText("等待时间（秒）:")
        else:
            self.time_label.setText("时间(秒):")

    def _current_action_key(self):
        return self.action_combo.currentData()

    def on_action_changed(self):
        action = self._current_action_key()
        if action == "terminate":
            self.intent_input.setText("任务完成")
            self.intent_input.setReadOnly(True)
        else:
            self.intent_input.setReadOnly(False)
        self._update_action_fields_visibility()
        self.validation_timer.start()
        self.schedule_draft_save()

    # ========== scrcpy 回调 ==========

    def _on_scrcpy_ready(self):
        self.status_label.setText("scrcpy 已连接 - 左键操作手机, 右键拖拽拉框标注")
        self.btn_screenshot.setEnabled(True)
        self.overlay.set_phone_resolution(self._phone_w, self._phone_h)
        if self.scrcpy_widget.hwnd:
            self.overlay.set_scrcpy_hwnd(self.scrcpy_widget.hwnd)
        QTimer.singleShot(200, self.overlay.show_overlay)
        QTimer.singleShot(800, self.overlay.show_overlay)

    def _on_scrcpy_error(self, msg):
        self.status_label.setText(f"scrcpy 错误: {msg} - 可点击[重连 scrcpy]重试")

    def _reconnect_scrcpy(self):
        """用户点击工具栏"重连 scrcpy"按钮：手动重新拉起 scrcpy。

        不监控连接状态，按钮始终可点击；start_scrcpy 内部先 _cleanup_process
        （kill 旧进程）再启动新进程，重复点击安全幂等。
        """
        # 旧 overlay 可能还盖在已失效的窗口上，先隐藏并清空标注
        self.overlay.hide()
        self.overlay.clear_rect()
        self.status_label.setText("正在重新连接 scrcpy...")
        self.scrcpy_widget.start_scrcpy(self._serial)

    # ========== 任务初始化 ==========

    def initialize_task(self):
        self.status_label.setText("正在初始化任务...")
        self.gui_number = self.data_manager.get_next_gui_number()
        self.gui_dir = self.data_manager.create_gui_directory(self.gui_number)
        self.status_label.setText(f"任务已初始化 - 存储目录: gui_{self.gui_number} - 请截取第一张图")

    # ========== 截图 ==========

    def start_insert_capture(self):
        """在当前步之后插入新步：设置插入锚点后复用常规截图链"""
        # B2：门闩必须在设置插入锚点之前早退，否则残留锚点会把下一次普通截图误判为插入
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if self.gui_dir is None:
            QMessageBox.warning(self, "提示", "请先初始化任务（任务初始化后自动创建存储目录）")
            return
        if not self.steps_data:
            QMessageBox.warning(self, "提示", "当前还没有已确认的步骤，无法插入；请先截图确认第一步")
            return
        if not (0 <= self.current_step < len(self.steps_data)):
            QMessageBox.warning(self, "提示", "请先在侧栏选择一个已有步骤，再在其后插入")
            return
        # 记录锚点：截图成功后把新步插到该下标之后
        self._insert_after_index = self.current_step
        self.take_screenshot()

    def take_screenshot(self):
        # B2：切轮窗口内的截图会落在旧 instruction 的轮次上，直接拒绝
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        # 交付后门闩：任务已保存时不得再采集，否则新图会挂进已交付的现场
        if self._task_completed:
            self.status_label.setText("任务已保存，请先选择是否开始新任务")
            return
        if self.gui_dir is None:
            QMessageBox.warning(self, "提示", "请先初始化任务（任务初始化后自动创建存储目录）")
            return
        if self._screenshot_in_progress:
            self.status_label.setText("截图进行中，请等待当前截图完成后重试...")
            return
        self._screenshot_in_progress = True
        self._screenshot_seq += 1
        seq = self._screenshot_seq
        # 快照当前步骤与待替换旧图路径，防止截图期间步骤被导航改变导致误删/误写
        capture_step = self.current_step
        old_path = self._current_screenshot_filepath
        # 插入模式下保留锚点步截图（新图另存为新序号），故旧图路径不参与删除
        if self._insert_after_index is not None:
            old_path = None
        self.status_label.setText("正在从 Android 设备截图...")
        QTimer.singleShot(50, lambda: self._do_screenshot(seq, capture_step, old_path))

    def _do_screenshot(self, seq, capture_step, old_path):
        tmp_path = os.path.join(tempfile.gettempdir(), f"android_capture_tmp_{os.getpid()}.png")
        # 在后台线程执行 ADB 截图，避免阻塞 UI 主线程
        threading.Thread(
            target=self._capture_worker,
            args=(tmp_path, seq, capture_step, old_path),
            daemon=True
        ).start()

    def _capture_worker(self, tmp_path, seq, capture_step, old_path):
        """后台线程：执行 ADB 截图"""
        success, filepath = self.screen_capture.capture(tmp_path)
        self._screenshot_finished.emit(seq, capture_step, old_path or "", success, filepath or "")

    def _on_screenshot_finished(self, seq, capture_step, old_path, success, filepath):
        """截图结果回到主线程处理"""
        if seq != self._screenshot_seq:
            # 已开始新截图，丢弃过期结果
            return
        # 锚点在任何丢弃/失败路径都要复位，避免下一次普通截图被误判为插入
        insert_after = self._insert_after_index
        if capture_step != self.current_step:
            # 截图返回前步骤已被导航切换，丢弃结果并立即释放锁
            self._insert_after_index = None
            self._release_screenshot_lock()
            self.status_label.setText("截图已取消（步骤已切换）")
            return

        if not success or not filepath:
            # 截图失败：保留当前截图与指针，不删除任何文件
            self._insert_after_index = None
            self.status_label.setText("截图失败 - 请检查 ADB 连接")
            QTimer.singleShot(self._screenshot_cooldown_ms, self._release_screenshot_lock)
            return

        # 重复截图替换：原地覆盖旧文件，文件名/序号保持不变。
        # 不再“先删旧图再扫盘抢最小未占用号”——那样一来保存失败时旧图已不可恢复
        # （编辑模式下销毁的是已交付数据），二来目录存在空洞时新图会拿到
        # 与旧图不同的序号，导致步骤截图名漂移。
        # 插入模式下 old_path 已被置空，锚点步截图保留不动、新图另存新序号。
        replace_name = None
        if old_path:
            replace_name = self._current_screenshot_filename or os.path.basename(old_path)

        # 保存截图到 gui 目录（replace_name 为空时才扫盘分配新序号）
        screenshot_filename = self.data_manager.save_screenshot(
            self.gui_number, self.app_name, filepath, filename=replace_name
        )
        if not screenshot_filename:
            # 持久化失败：覆盖模式下旧图仍完好在盘上，保留指针避免它变成孤儿文件；
            # 仅新增模式（确实没有任何文件落地）才清空指针。steps_data 一律不改动
            self._insert_after_index = None
            if not replace_name:
                self._current_screenshot_filename = None
                self._current_screenshot_filepath = None
                self.screenshot_cache = None
            self.status_label.setText("截图保存失败 - 请检查存储目录后重试")
            QTimer.singleShot(self._screenshot_cooldown_ms, self._release_screenshot_lock)
            return

        # 序号复用（重截/撤销后新图取同名文件）时失效侧栏按文件名缓存的旧缩略图
        self.sidebar.remove_thumb_cache_by_filename(screenshot_filename)

        # 覆盖名与旧图名不一致的异常现场（指针错配）：按引用可达集回收旧图，
        # 避免既留孤儿又误删他轮仍在引用的文件
        if old_path and os.path.basename(old_path) != screenshot_filename:
            self._remove_screenshot_if_unreferenced(old_path)

        screenshot_filepath = os.path.join(self.gui_dir, screenshot_filename)
        # 锚点读取后立即复位，后续异常也不会残留插入状态
        self._insert_after_index = None

        if insert_after is not None and 0 <= insert_after < len(self.steps_data):
            # ===== 中间步插入：先把锚点步表单落盘，再在其后插入新步 =====
            # 临时还原锚点步截图指针，确保 _save_current_to_steps 保留锚点截图
            anchor_data = self.steps_data[insert_after]
            self._current_screenshot_filename = anchor_data.get("screenshot")
            self._current_screenshot_filepath = anchor_data.get("screenshot_filepath")
            self.screenshot_cache = anchor_data.get("screenshot_filepath")
            self._save_current_to_steps()

            new_step = {
                "screenshot": screenshot_filename,
                "screenshot_filepath": screenshot_filepath,
                "intent": "",
                "action_data": {"action": "click", "element": ""},
                "vertices": None
            }
            self.steps_data.insert(insert_after + 1, new_step)
            self.current_step = insert_after + 1
            self._missing_cache = {}
            self._missing_live = None
            # 表单切到新插入的空白步，新截图保留在预览区供标注
            self._current_screenshot_filename = screenshot_filename
            self._current_screenshot_filepath = screenshot_filepath
            self.screenshot_cache = screenshot_filepath
            self._current_vertices = None
            self.overlay.clear_rect()
            self._clear_inputs()
            self.status_label.setText(
                f"已在第 {insert_after + 1} 步后插入新步（当前第 {self.current_step + 1} 步）- "
                "请右键拉框标注并填写动作信息"
            )
        else:
            # ===== 常规模式：覆盖/追加当前步 =====
            self.screenshot_cache = filepath
            self._current_screenshot_filename = screenshot_filename
            self._current_screenshot_filepath = screenshot_filepath
            # 重截即作废旧拉框与坐标类测量数据，避免新图沿用旧标注
            self._current_vertices = None
            self.coord_x_input.clear()
            self.coord_y_input.clear()
            self.coord2_x_input.clear()
            self.coord2_y_input.clear()
            self.pixels_input.clear()
            self.overlay.clear_rect()
            self._cancel_swipe_measurement()
            self._cancel_scroll_measurement()
            self._missing_live = None
            if self.current_step < len(self.steps_data):
                # 历史步重截：原地落表（新截图指针进快照，coordinate/pixels 缺键省略，vertices 清空）
                self._save_current_to_steps()
            # current_step == len 的未确认新步只更新三指针，绝不 append
            self.status_label.setText("截图完成 - 请在 scrcpy 窗口右键拉框标注目标区域，然后填写动作信息")

        # 更新截图信息
        pixmap = QPixmap(filepath)
        if not pixmap.isNull():
            # B23：顶层 screen_size 只由「本轮首张追加截图」定版；重截、中间插入、
            # 历史步覆盖都不得覆写，否则会话中一次分辨率抖动会改写整轮交付尺寸。
            # 蒙版坐标映射用的 _phone_w/_phone_h 仍逐张跟随实际截图。
            if not self.steps_data and insert_after is None:
                self.screen_info["screen_size"] = [pixmap.width(), pixmap.height()]
            self._phone_w = pixmap.width()
            self._phone_h = pixmap.height()
            self.overlay.set_phone_resolution(self._phone_w, self._phone_h)
            self.screenshot_name_label.setText(screenshot_filename)
            self.screenshot_size_label.setText(f"{pixmap.width()} x {pixmap.height()}")
            # 显示在截图预览面板中（插入模式下 vertices 已清空）
            self.screenshot_canvas.set_screenshot(screenshot_filepath, self._current_vertices)

        self._update_navigation_buttons()
        self._update_step_label()
        if insert_after is not None and 0 <= insert_after < len(self.steps_data):
            # 中间插入后下标整体变化，必须全量重建
            self.sidebar.rebuild_items()
        else:
            # 常规覆盖：O(1) 增量刷新当前步，避免 100+ 步时全量重建卡死
            index = self.current_step
            if 0 <= index < len(self.sidebar.item_widgets):
                self.sidebar.refresh_step_item(index)
                # 截图已落盘且按文件名失效过缓存，这里重置条目标志后重新请求新缩略图
                self.sidebar.item_widgets[index].thumb_loaded = False
                self.sidebar.request_thumb(index, high_priority=True)
                self.sidebar.refresh_highlight()
                self.sidebar.refresh_dashboard()
        self.schedule_draft_save()
        # 冷却时间结束后才允许下一次截图，防止快速双击
        QTimer.singleShot(self._screenshot_cooldown_ms, self._release_screenshot_lock)

    def _release_screenshot_lock(self):
        """释放截图锁，允许下一次截图"""
        self._screenshot_in_progress = False

    # ========== 蒙版拉框（映射到手机坐标）==========

    def _overlay_to_phone_coords(self, canvas_rect):
        """将蒙版上的画布坐标矩形映射到手机屏幕坐标"""
        if self.overlay.width() <= 0 or self.overlay.height() <= 0:
            return None
        scale_x = self._phone_w / self.overlay.width()
        scale_y = self._phone_h / self.overlay.height()
        left = int(canvas_rect.left() * scale_x)
        top = int(canvas_rect.top() * scale_y)
        right = int(canvas_rect.right() * scale_x)
        bottom = int(canvas_rect.bottom() * scale_y)
        left = max(0, min(left, self._phone_w))
        top = max(0, min(top, self._phone_h))
        right = max(0, min(right, self._phone_w))
        bottom = max(0, min(bottom, self._phone_h))
        return left, top, right, bottom

    def relabel_current_step(self):
        """编辑已完成任务：在当前步磁盘原截图上重新拖框（不重新截图、不覆盖 PNG）"""
        # B2：轮次切换窗口内不得打开弹窗
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        # DI-8/B2：与所有采集入口共用同一门闩，不新增并行标志
        if self._screenshot_in_progress:
            return
        if not self._edit_mode:
            return
        # 本端 screenshot_cache 存的是磁盘文件路径，预览也按该路径从磁盘重载
        filepath = self.screenshot_cache
        if not filepath or not os.path.exists(filepath):
            self.status_label.setText("当前步骤截图文件缺失，请先[截图]")
            return
        pixmap = QPixmap(filepath)
        if pixmap.isNull():
            self.status_label.setText("当前步骤截图文件缺失，请先[截图]")
            return
        # 弹窗拖框走普通动作语义，先取消进行中的测量态，
        # 避免污染 _swipe_start_vertices / _scroll_references
        self._cancel_swipe_measurement()
        self._cancel_scroll_measurement()
        self.btn_swipe_finish.hide()
        self._relabel_dialog = ReLabelDialog(pixmap, self)
        self._relabel_dialog.rect_confirmed.connect(self._on_relabel_rect)
        self._relabel_dialog.show()

    def _on_relabel_rect(self, left, top, right, bottom):
        """重新拉框确认：与 _on_overlay_rect_drawn 普通分支等价 + 落表 + 预览/侧栏刷新"""
        vertices = [left, top, right, bottom]
        if self._valid_vertices(vertices) is None:
            return
        center_x = int((left + right) / 2)
        center_y = int((top + bottom) / 2)
        self._current_vertices = vertices
        self.coord_x_input.setText(str(center_x))
        self.coord_y_input.setText(str(center_y))
        suffix = ""
        if self.coord2_x_input.text():
            suffix = "（滑动/滚动动作仅更新起点，终点保持原值）"
        self.status_label.setText(
            f"已在原图上重新拉框: ({left},{top})-({right},{bottom}) | 中心点: ({center_x},{center_y})"
            f"{suffix} - 请点击[保存修改]写回"
        )
        # 预览画布与蒙版都要跟内存态对齐（与编辑收尾同一出口）
        self._refresh_screenshot_preview()
        self._replay_overlay_rect()
        self._save_current_to_steps_for_edit()
        self.sidebar.rebuild_items()
        self.revalidate_all_missing()
        self._relabel_dialog = None

    def _on_overlay_rect_drawn(self, rect):
        """蒙版右键拉框完成 — 自动填入坐标 + 更新截图预览"""
        coords = self._overlay_to_phone_coords(rect)
        if coords is None:
            return
        left, top, right, bottom = coords
        center_x = int((left + right) / 2)
        center_y = int((top + bottom) / 2)
        vertices = [left, top, right, bottom]

        current_action = self._current_action_key()

        # swipe / drag 测量流程：起点框已记录，此处拉取的是终点框
        if current_action in START_END_ACTIONS and self._swipe_measuring:
            self.coord2_x_input.setText(str(center_x))
            self.coord2_y_input.setText(str(center_y))
            self._current_vertices = self._swipe_start_vertices
            self.btn_swipe_finish.show()
            self.status_label.setText(
                f"终点: ({center_x},{center_y}) - 点击 [完成测量]"
            )
            return

        # scroll 测量流程：测量中时，每次拉框作为新的参照物
        if current_action == "scroll" and self._scroll_measuring:
            if self._scroll_resetting:
                # 换参照物：以本次拉框为新基线，不改动已累计的总像素
                self._scroll_baseline_y = center_y
                self._scroll_resetting = False
                self._scroll_references.append(center_y)
                self.btn_scroll_reset.setText("重设参照物")
                self.status_label.setText(
                    f"已切换到新参照物 (基线Y={center_y})，当前累计滚动像素: {self._scroll_total}"
                    "- 继续滚动后拉框同一参照物累计，或点[完成测量]"
                )
            else:
                self._scroll_total += center_y - self._scroll_baseline_y
                self._scroll_baseline_y = center_y
                self._scroll_references.append(center_y)
                self.btn_scroll_reset.setText("重设参照物")
                self.pixels_input.setText(str(self._scroll_total))
                self.status_label.setText(
                    f"已记录 {len(self._scroll_references)} 个参照物，累计滚动像素: {self._scroll_total}"
                    "（正值=内容下移，负值=内容上移）- 滚动后换参照物请先点[重设参照物]"
                )
            self._current_vertices = self._scroll_start_vertices
            self._refresh_screenshot_preview()
            return

        # 普通动作：填入坐标，更新截图预览
        self._current_vertices = vertices
        self.coord_x_input.setText(str(center_x))
        self.coord_y_input.setText(str(center_y))
        self.status_label.setText(
            f"拉框区域: ({left},{top})-({right},{bottom}) | 中心点: ({center_x},{center_y})"
        )
        # 更新截图预览面板 — 显示截图 + 标注框
        self._refresh_screenshot_preview()

    def _on_overlay_cancelled(self):
        pass

    def _refresh_screenshot_preview(self):
        """刷新截图预览：根据当前截图缓存和 vertices 更新画布"""
        if self.screenshot_cache and os.path.exists(self.screenshot_cache):
            self.screenshot_canvas.set_screenshot(self.screenshot_cache, self._current_vertices)

    def _toggle_mask(self):
        self.overlay.cycle_mask_color()

    # ========== swipe / drag 测量 ==========

    def _start_swipe_measurement(self):
        if not self._current_vertices:
            QMessageBox.warning(self, "提示", "请先在 scrcpy 窗口右键拉框标注起点！")
            return
        self._swipe_measuring = True
        self._swipe_start_vertices = list(self._current_vertices)
        self.btn_swipe_measure.hide()
        self.status_label.setText("起点已记录 - 请在手机上执行滑动/拖拽，再右键拉框标注终点")

    def _finish_swipe_measurement(self):
        if not self._swipe_start_vertices:
            return
        self._swipe_measuring = False
        self._swipe_start_vertices = None
        self.btn_swipe_finish.hide()
        self.btn_swipe_measure.show()
        self.status_label.setText("测量完成 - 起点和终点坐标已填入")

    def _cancel_swipe_measurement(self):
        self._swipe_measuring = False
        self._swipe_start_vertices = None
        self.btn_swipe_measure.show()
        self.btn_swipe_finish.hide()

    # ========== scroll 测量 ==========

    def _start_scroll_measurement(self):
        if self._scroll_measuring:
            return
        if not self._current_vertices:
            QMessageBox.warning(self, "提示", "请先在 scrcpy 窗口右键拉框标注参照物！")
            return
        coord = self._read_coordinate(self.coord_x_input, self.coord_y_input)
        if coord is None:
            QMessageBox.warning(self, "提示", "请先在 scrcpy 窗口右键拉框标注参照物！")
            return
        self._scroll_start_vertices = list(self._current_vertices)
        self._scroll_total = 0
        self._scroll_baseline_y = coord[1]
        self._scroll_resetting = False
        self._scroll_references = [coord[1]]
        self._scroll_measuring = True
        self.pixels_input.setText("0")
        self.btn_scroll_measure.hide()
        self.btn_scroll_finish.show()
        self.btn_scroll_reset.show()
        self.btn_scroll_reset.setText("重设参照物")
        self.status_label.setText(
            "参照物已记录 - 请在手机上滚动后重新拉框同一参照物，"
            "可多次拉框累积距离；滚动后想换参照物请先点[重设参照物]，最后点[完成测量]"
        )

    def _on_scroll_reset_reference(self):
        """换参照物：下一次拉框作为新基线，不改变已累计像素"""
        if not self._scroll_measuring:
            return
        self._scroll_resetting = True
        self.btn_scroll_reset.setText("请拉框新参照物...")
        self.status_label.setText(
            "请在手机上拉框新参照物作为基线（不改变已累计像素），之后继续滚动累计"
        )

    def _finish_scroll_measurement(self):
        total = self._scroll_total
        self._scroll_measuring = False
        self._scroll_references = []
        self._scroll_start_vertices = None
        self._scroll_resetting = False
        self.pixels_input.setText(str(total))
        self.btn_scroll_measure.show()
        self.btn_scroll_finish.hide()
        self.btn_scroll_reset.hide()
        self.status_label.setText(
            f"滚动测量完成，累计滚动像素: {total}（正值=内容下移，负值=内容上移）"
        )

    def _cancel_scroll_measurement(self):
        self._scroll_measuring = False
        self._scroll_references = []
        self._scroll_start_vertices = None
        self._scroll_resetting = False
        self.btn_scroll_measure.show()
        self.btn_scroll_finish.hide()
        self.btn_scroll_reset.hide()

    # ========== 步骤导航 ==========

    def _collect_step_data(self):
        action_data = self._build_action_data()
        return {
            "screenshot": self._current_screenshot_filename or "",
            "screenshot_filepath": self._current_screenshot_filepath or "",
            "intent": self.intent_input.text().strip(),
            "action_data": action_data,
            "vertices": list(self._current_vertices) if self._current_vertices else None
        }

    def _save_current_to_steps(self):
        if self._edit_mode:
            # 编辑模式统一走带截图文件名兜底的落表逻辑
            self._save_current_to_steps_for_edit()
            return
        if self._current_screenshot_filename is None:
            return
        step_data = self._collect_step_data()
        if self.current_step < len(self.steps_data):
            self.steps_data[self.current_step] = step_data
            saved_index = self.current_step
        else:
            self.steps_data.append(step_data)
            saved_index = len(self.steps_data) - 1
        # 落表即失效该下标缓存（等长替换也要重算）
        if 0 <= saved_index < len(self.steps_data):
            self._missing_cache[saved_index] = self.validate_step_at(saved_index)

    def _save_current_to_steps_for_edit(self):
        """编辑模式落表：截图缺失（文件名被清空）时沿用原步的截图文件名"""
        filename = self._current_screenshot_filename
        if not filename and 0 <= self.current_step < len(self.steps_data):
            filename = self.steps_data[self.current_step].get("screenshot", "")
        if not filename:
            return
        step_data = self._collect_step_data()
        step_data["screenshot"] = filename
        step_data["screenshot_filepath"] = (
            os.path.join(self.gui_dir, filename) if self.gui_dir else ""
        )
        # hydration 登记的「框丢失/框与坐标不一致」标记不属 _collect_step_data 的
        # 五个键，不在这里回贴就会被一次普通导航抹掉，写回时的「保留盘上原条目」
        # 分支（见 save_edited_round）随即失效；用户已重新拉到合法框则双双清空。
        prev = (self.steps_data[self.current_step]
                if 0 <= self.current_step < len(self.steps_data) else {})
        if self._valid_vertices(step_data.get("vertices")) is not None:
            step_data["coord_issue"] = None
            step_data["orig_coord_entry"] = None
        else:
            step_data["coord_issue"] = prev.get("coord_issue")
            step_data["orig_coord_entry"] = prev.get("orig_coord_entry")
        if self.current_step < len(self.steps_data):
            self.steps_data[self.current_step] = step_data
            saved_index = self.current_step
        else:
            self.steps_data.append(step_data)
            saved_index = len(self.steps_data) - 1
        if 0 <= saved_index < len(self.steps_data):
            self._missing_cache[saved_index] = self.validate_step_at(saved_index)

    def confirm_step(self):
        # B2：answer 落轮后的 300ms 切轮窗口内不得再确认
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if self._edit_mode:
            # 编辑已完成任务：只把当前表单落回当前步，不切轮次、不结束任务
            self._save_current_to_steps_for_edit()
            if 0 <= self.current_step < len(self.sidebar.item_widgets):
                self.sidebar.refresh_step_item(self.current_step)
                self.sidebar.invalidate_thumb(self.current_step)
                self.sidebar.item_widgets[self.current_step].thumb_loaded = False
                self.sidebar.request_thumb(self.current_step, high_priority=True)
            self.sidebar.refresh_highlight()
            self.revalidate_all_missing()
            self.status_label.setText(f"已更新第 {self.current_step + 1} 步")
            return
        if self._current_screenshot_filename is None:
            QMessageBox.warning(self, "提示", "请先截图！")
            return
        # 终止类动作必须是本轮最后一步：中间步选 answer/answer_terminate/terminate
        # 会把后续步骤遗留在本轮，落轮后它们既没被回答收尾、也不会再被确认，
        # 最终整轮归属与步数都与用户预期不符。current_step == len(steps_data)
        # 的未确认空白位不受影响（不满足 < len - 1）。
        action = self._current_action_key()
        if (action in ("answer", "answer_terminate", "terminate")
                and 0 <= self.current_step < len(self.steps_data) - 1):
            remaining = len(self.steps_data) - 1 - self.current_step
            QMessageBox.warning(
                self, "提示",
                f"终止类动作必须是本轮最后一个步骤，当前第 {self.current_step + 1} 步"
                f"之后还有 {remaining} 个步骤，请先删除或撤销后续步骤"
            )
            return
        if not self._validate_step():
            return
        self._cancel_swipe_measurement()
        self._cancel_scroll_measurement()
        self._save_current_to_steps()

        if action == "answer":
            # 轮次边界：立即写一次草稿，再切下一轮
            if not self._save_current_round_to_list():
                # B14：缺指令且未补齐 → 本轮不落，也不能升门闩弹新轮对话框，
                # 否则 _start_new_round 接受分支会把这条未落轮的 steps_data 直接清空
                return
            self.schedule_draft_save()
            # 升起门闩，300ms 切轮窗口内禁止截图/确认（B2）
            self._round_transition_pending = True
            QTimer.singleShot(300, lambda: self._start_new_round(from_answer=True))
            return

        if action == "answer_terminate":
            self._finish_task()
            return

        if action == "terminate":
            self._finish_task()
            return

        # 2.8（B22）：确认后游标只前进一格，不得越过末尾的待截图空位。
        # 原实现无条件把游标推到 len(steps_data)：回看中间某步改完确认后，用户被
        # 静默传送到末尾，正在核对的表单也被清空，只能重新截图才能续采。
        # 也不采用「原地不动」：go_next 停在最后一步时是委托 confirm_step 来进入
        # 空位的，历史步确认若完全不推进，末步就再也进不了待截图空位。
        saved_index = self.current_step
        total = len(self.steps_data)
        if saved_index + 1 < total:
            # 编辑历史步后确认：前进一格到下一已有步，现场完整回填、不清表单
            self.current_step = saved_index + 1
            self._load_step_to_form(self.current_step)
            if 0 <= saved_index < len(self.sidebar.item_widgets):
                # 被改的那一步条目按最新 vertices/动作重画缩略图与文本
                self.sidebar.refresh_step_item(saved_index)
                self.sidebar.invalidate_thumb(saved_index)
                self.sidebar.item_widgets[saved_index].thumb_loaded = False
                self.sidebar.request_thumb(saved_index, high_priority=True)
            self.sidebar.refresh_highlight()
            self._on_validation_debounced()
            self.schedule_draft_save()
            self.status_label.setText(
                f"已更新第 {saved_index + 1} 步，步骤 {self.current_step} - 可继续编辑"
            )
            return

        # 追加新步/确认末步：进入末尾待截图空位，侧栏增量追加一个条目 + 草稿调度
        self.current_step = total
        self._reset_for_next_step()
        target = len(self.sidebar.item_widgets)
        if target < len(self.steps_data):
            # 新确认的一步：追加一个条目（新 item 懒加载其缩略图）
            item = self.sidebar._create_item(target)
            self.sidebar.item_widgets.append(item)
            self.sidebar.refresh_step_item(target)
            self.sidebar.request_thumb(target, high_priority=True)
        elif 0 <= saved_index < len(self.sidebar.item_widgets):
            # 条目数已齐（插入分支已 rebuild_items）：按最新 vertices 重画该步缩略图
            self.sidebar.refresh_step_item(saved_index)
            self.sidebar.invalidate_thumb(saved_index)
            self.sidebar.item_widgets[saved_index].thumb_loaded = False
            self.sidebar.request_thumb(saved_index, high_priority=True)
        self.sidebar.refresh_highlight()
        self.revalidate_all_missing()
        self.schedule_draft_save()
        self.status_label.setText(f"步骤 {self.current_step} - 请截图并标注")

    def _load_step_to_form(self, index):
        """把 steps_data[index] 的纯数据回填到唯一表单与预览（回看历史步统一入口）

        预览图只保留磁盘路径，由 ScreenshotCanvas 从磁盘按需重载，不常驻全屏 QPixmap。
        """
        if not (0 <= index < len(self.steps_data)):
            return
        step_data = self.steps_data[index]

        # 恢复动作面板
        self.intent_input.setText(step_data.get("intent", ""))
        self._restore_action_ui(step_data.get("action_data", {}))
        vertices = step_data.get("vertices")
        self._current_vertices = list(vertices) if vertices else None

        # 截图三指针只保留磁盘引用
        screenshot_filepath = step_data.get("screenshot_filepath") or ""
        if not screenshot_filepath:
            filename = step_data.get("screenshot") or ""
            if filename and self.gui_dir:
                screenshot_filepath = os.path.join(self.gui_dir, filename)
        self.screenshot_cache = screenshot_filepath
        self._current_screenshot_filename = step_data.get("screenshot", "")
        self._current_screenshot_filepath = screenshot_filepath
        self.screenshot_name_label.setText(self._current_screenshot_filename or "(无)")

        # 恢复蒙版拉框与截图预览（画布按磁盘路径重载）
        # vertices 是手机物理像素，需逆映射为蒙版本地坐标后再显示历史拉框
        overlay_rect = self._phone_vertices_to_overlay_rect(self._current_vertices)
        if overlay_rect is not None:
            self.overlay.set_final_rect(overlay_rect)
        else:
            self.overlay.clear_rect()
        self._refresh_screenshot_preview()

        self._update_navigation_buttons()
        self._update_step_label()

    def go_previous(self):
        if self.current_step <= 0:
            return
        self._save_current_to_steps()
        self.current_step -= 1
        self._load_step_to_form(self.current_step)
        # 侧栏高亮移动、当前步缩略图优先、缺项标记与看板计数刷新
        self.sidebar.refresh_highlight()
        self.sidebar.ensure_current_thumb(self.current_step)
        self._on_validation_debounced()
        self.status_label.setText(f"步骤 {self.current_step} - 可继续编辑")

    def go_next(self):
        if self._current_screenshot_filename is None:
            QMessageBox.warning(self, "提示", "请先截图再进行下一步操作！")
            return
        self._save_current_to_steps()
        if self.current_step + 1 < len(self.steps_data):
            self.current_step += 1
            self._load_step_to_form(self.current_step)
            self.sidebar.refresh_highlight()
            self.sidebar.ensure_current_thumb(self.current_step)
            self._on_validation_debounced()
            self.status_label.setText(f"步骤 {self.current_step} - 可继续编辑")
        else:
            self.confirm_step()

    def jump_to_step(self, index):
        """侧栏条目点击/跳转按钮入口：保存当前表单后跳到指定历史步"""
        if not (0 <= index < len(self.steps_data)):
            return
        self._save_current_to_steps()
        self._cancel_swipe_measurement()
        self._cancel_scroll_measurement()
        self.current_step = index
        self._load_step_to_form(index)
        self.sidebar.refresh_highlight()
        self.sidebar.ensure_current_thumb(index)
        self._on_validation_debounced()
        self.status_label.setText(f"步骤 {index} - 可继续编辑")

    def _reachable_screenshot_names(self, ignore_current=False):
        """收集仍被引用的截图文件名可达集（B16/B17 修复）

        可达集 = 当前 steps_data ∪ 已落轮 rounds 的 trajectory ∪ 当前在编截图。
        只查 steps_data 会误删已落轮仍在引用的 PNG；而编辑模式下
        steps_data 只含被编辑的那一轮、rounds 含全部轮，其中被编辑轮在
        rounds 内是加载时的陈旧副本，必须以 steps_data 为准，
        否则删步永远回收不掉截图（变孤儿文件）。

        :param ignore_current: 忽略「当前在编位置」的引用，即 steps_data
            [current_step] 与 _current_screenshot_filename。删除/撤销时这条
            记录即将消失，不忽略就会「自己引用自己」，文件永远回收不掉。
            该开关**只作用于当前在编位置**：rounds 中已落轮的引用一律完整
            计入。曾按文件名排除（exclude_names），会把 rounds 里的同名引用
            一并抹掉，等于废掉 B16/B17 的修复——已交付数据不得据以删盘。
        """
        names = set()
        for i, step in enumerate(self.steps_data):
            if ignore_current and i == self.current_step:
                continue
            fn = step.get("screenshot")
            if fn:
                names.add(fn)
        edited = self._edit_round_index if self._edit_mode else None
        for i, round_data in enumerate(self.rounds or []):
            if i == edited or not isinstance(round_data, dict):
                continue
            for traj in round_data.get("trajectory") or []:
                if not isinstance(traj, dict):
                    continue
                obs = traj.get("observation") or {}
                fn = obs.get("screenshot") if isinstance(obs, dict) else None
                if fn:
                    names.add(fn)
        cur = self._current_screenshot_filename
        if cur and not ignore_current:
            names.add(cur)
        return names

    def _remove_screenshot_if_unreferenced(self, path, filename=None,
                                           ignore_current=False):
        """按引用可达集回收截图文件：仅当没有任何步骤/已落轮仍引用时才删盘。

        :param ignore_current: 见 _reachable_screenshot_names；删当前步/撤销时传 True
        """
        if not path or not os.path.isfile(path):
            return False
        name = filename or os.path.basename(path)
        if name in self._reachable_screenshot_names(ignore_current=ignore_current):
            return False
        try:
            os.remove(path)
            return True
        except OSError as e:
            print(f"[截图] 删除文件失败: {e}")
            return False

    def delete_current_step(self):
        """删除当前步骤：二次确认后移除数据与磁盘截图，后一步数据回填表单"""
        # B2：切轮窗口内不得删改已落轮的数据
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        index = self.current_step
        if not (0 <= index < len(self.steps_data)):
            QMessageBox.information(self, "提示", "当前没有可删除的步骤")
            return
        if self._screenshot_in_progress:
            self.status_label.setText("截图进行中，请等待当前截图完成后再操作")
            return

        reply = QMessageBox.question(
            self,
            "删除当前步骤",
            f"确定删除第 {index + 1} 步？该步截图文件将一并删除，后续步骤自动前移",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._cancel_swipe_measurement()
        self._cancel_scroll_measurement()
        removed = self.steps_data[index]
        removed_filename = removed.get("screenshot", "")
        removed_path = removed.get("screenshot_filepath") or (
            os.path.join(self.gui_dir, removed_filename) if self.gui_dir else "")

        # B16/B17 修复：删盘判定须在移除步骤之前做。此刻 current_step==index
        # 精确指向被删步，ignore_current 按位置忽略它自己；若先 pop 再判定，
        # index 会落到「原下一步」，位置忽略将误把幸存步排除出可达集。
        # 只比对 steps_data 会误删其他轮仍引用的已交付 PNG，故可达集含 rounds。
        self._remove_screenshot_if_unreferenced(
            removed_path, removed_filename, ignore_current=True
        )
        del self.steps_data[index]

        # 清理侧栏中被删文件名的缩略图缓存条目
        self.sidebar.remove_thumb_cache_by_filename(removed_filename)

        # 删除后定位：同位置（即原下一步）回填表单；删的是末尾步则定位前一步；删空回初始态
        total = len(self.steps_data)
        if total == 0:
            self.current_step = 0
            self._missing_cache = {}
            self._reset_for_next_step()
            self.sidebar.rebuild_items()
            self.status_label.setText("已删除全部步骤，请重新截图开始")
        else:
            self.current_step = min(index, total - 1)
            self._missing_cache = {}
            self._load_step_to_form(self.current_step)
            self.sidebar.rebuild_items()
            self.status_label.setText(
                f"已删除第 {index + 1} 步，当前第 {self.current_step + 1} 步（共 {total} 步）"
            )
        self.schedule_draft_save()

    def _reset_for_next_step(self):
        self._screenshot_in_progress = False
        self.overlay.clear_rect()
        self.screenshot_cache = None
        self._current_screenshot_filename = None
        self._current_screenshot_filepath = None
        self._current_vertices = None
        self.screenshot_canvas.clear_screenshot()
        self._clear_inputs()
        self._update_navigation_buttons()
        self._update_step_label()

    def undo_step(self):
        """撤销上一步：移除最后一步，并回到该步骤位置重新截图标注"""
        # B2：切轮窗口内不得删改已落轮的数据
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if not self.steps_data:
            self.status_label.setText("没有可撤销的步骤")
            return
        if self._screenshot_in_progress:
            self.status_label.setText("截图进行中，请等待当前截图完成后再操作")
            return
        # 撤销前先落盘当前表单编辑，避免回看历史步时的未确认修改被静默丢弃
        # （当前步是未确认新步时不保存，保持撤销弹末步语义）
        if self.current_step < len(self.steps_data):
            self._save_current_to_steps()
        # 移除最后一步
        removed = self.steps_data.pop()
        # 回到被移除步骤的位置（此时为待编辑的空步骤）
        self.current_step = len(self.steps_data)
        self._missing_cache = {}

        # 收集待回收的候选文件，按引用可达集判定（B16/B17）：
        # 只比对保留下来的 steps_data 会误删已落轮仍在引用的已交付 PNG。
        # removed 已弹出列表，current 是待重截的在编位，两者均按位置忽略
        removed_path = removed.get("screenshot_filepath", "")
        current_path = self._current_screenshot_filepath or ""
        candidates = [p for p in {removed_path, current_path} if p]
        reachable = self._reachable_screenshot_names(ignore_current=True)
        for path in candidates:
            if os.path.basename(path) in reachable:
                continue
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError as e:
                    print(f"[撤销] 删除截图失败: {e}")

        # 清理侧栏中被撤销步骤与当前未保存截图的缩略图缓存（对照 delete_current_step）
        self.sidebar.remove_thumb_cache_by_filename(removed.get("screenshot"))
        self.sidebar.remove_thumb_cache_by_filename(self._current_screenshot_filename)

        self._reset_for_next_step()
        # 侧栏重建 + 草稿调度（撤销同样属于轨迹变化）
        self.sidebar.rebuild_items()
        self.schedule_draft_save()
        if self.steps_data:
            self.status_label.setText(f"已撤销，当前步骤 {self.current_step} - 请重新截图标注")
        else:
            self.status_label.setText("已撤销全部步骤，请重新开始")

    def clear_annotations(self):
        self.overlay.clear_rect()
        self._current_vertices = None
        self.coord_x_input.clear()
        self.coord_y_input.clear()
        self.coord2_x_input.clear()
        self.coord2_y_input.clear()
        self.text_input.clear()
        self.keys_input.clear()
        self.time_input.clear()
        self.intent_input.clear()
        self.pixels_input.clear()
        self.action_combo.setCurrentIndex(0)
        self.screenshot_canvas.clear_screenshot()
        self._cancel_swipe_measurement()
        self._cancel_scroll_measurement()
        self.status_label.setText("标注已清除")

    # ========== 内部方法 ==========

    def _validate_step(self):
        """确认前表单态校验：与看板/结束前统一走 validate_step_at 的 live 源，只弹首个原因"""
        reasons = self.validate_step_at(self.current_step)
        if reasons:
            QMessageBox.warning(self, "提示", reasons[0])
            return False
        return True

    @staticmethod
    def _parse_number(text):
        """解析数值字符串，非法输入（空、NaN、Inf）返回 None"""
        s = text.strip() if text else ""
        if not s:
            return None
        try:
            v = float(s)
        except (ValueError, OverflowError):
            return None
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return v

    def _read_coordinate(self, x_input, y_input):
        x = self._parse_number(x_input.text())
        y = self._parse_number(y_input.text())
        if x is None or y is None:
            return None
        return [int(x), int(y)]

    def _build_action_data(self):
        action = self._current_action_key()
        serialized_action = "answer" if action == "answer_terminate" else action
        data = {"action": serialized_action, "element": ""}
        if action in COORD_ACTIONS:
            coord = self._read_coordinate(self.coord_x_input, self.coord_y_input)
            if coord is not None:
                data["coordinate"] = coord
        if action == "scroll":
            pv = self._parse_number(self.pixels_input.text())
            if pv is not None:
                data["pixels"] = int(pv)
        if action in START_END_ACTIONS:
            start = self._read_coordinate(self.coord_x_input, self.coord_y_input)
            if start is not None:
                data["start_coordinate"] = start
            end = self._read_coordinate(self.coord2_x_input, self.coord2_y_input)
            if end is not None:
                data["coordinate"] = end
        if action in TEXT_ACTIONS:
            data["text"] = self.text_input.text().strip()
        if action in KEY_ACTIONS:
            data["keys"] = [k.strip() for k in self.keys_input.text().split(',') if k.strip()]
        if action in TIME_ACTIONS:
            tv = self._parse_number(self.time_input.text())
            if tv is not None:
                data["time"] = tv
        if action in BUTTON_ACTIONS:
            button = self.button_combo.currentText()
            if button in SYSTEM_BUTTONS:
                data["buttons"] = [button]
                data["element"] = f"系统按钮{button}"
        if action in ("terminate", "answer_terminate"):
            data["status"] = "success"
        return data

    def _restore_action_ui(self, action_data):
        action = action_data.get("action", "click")
        idx = self.action_combo.findData(action)
        if idx >= 0:
            self.action_combo.setCurrentIndex(idx)

        # 坐标类字段缺键/畸形时清空对应输入框，避免残留上一步的值
        start_pair = self._valid_coord_pair(action_data.get("start_coordinate"))
        end_pair = self._valid_coord_pair(action_data.get("coordinate"))
        if "start_coordinate" in action_data:
            if start_pair is not None:
                self.coord_x_input.setText(str(start_pair[0]))
                self.coord_y_input.setText(str(start_pair[1]))
            else:
                self.coord_x_input.clear()
                self.coord_y_input.clear()
            if end_pair is not None:
                self.coord2_x_input.setText(str(end_pair[0]))
                self.coord2_y_input.setText(str(end_pair[1]))
            else:
                self.coord2_x_input.clear()
                self.coord2_y_input.clear()
        else:
            if end_pair is not None:
                self.coord_x_input.setText(str(end_pair[0]))
                self.coord_y_input.setText(str(end_pair[1]))
            else:
                self.coord_x_input.clear()
                self.coord_y_input.clear()
            self.coord2_x_input.clear()
            self.coord2_y_input.clear()

        self.text_input.setText(action_data.get("text", "") if isinstance(action_data.get("text", ""), str) else "")
        keys = action_data.get("keys", [])
        self.keys_input.setText(",".join(str(k) for k in keys) if isinstance(keys, list) else "")
        time_val = action_data.get("time")
        self.time_input.setText(str(time_val) if self._is_valid_number(time_val) else "")
        pixels = action_data.get("pixels")
        self.pixels_input.setText(str(pixels) if self._is_valid_number(pixels) else "")
        buttons = action_data.get("buttons", [])
        if isinstance(buttons, list) and buttons:
            bidx = self.button_combo.findText(str(buttons[0]))
            if bidx >= 0:
                self.button_combo.setCurrentIndex(bidx)

    def _build_coords_entry(self, action_data, vertices=None):
        # B49：action_data 可能来自磁盘上的历史 JSON / 草稿，缺 action 键或整体
        # 为 None 都现实存在。旧写法用 action_data["action"] 直接下标，一旦命中
        # 就抛 KeyError/TypeError，而本函数处在整轮落盘（_save_current_round_to_list
        # / save_edited_round）的循环里，异常会中断整轮写回——一步脏数据毁掉一整轮。
        # iOS 端同功能一直用 .get("action", "")，本端对齐该安全写法。
        if not isinstance(action_data, dict):
            action_data = {}
        entry = {"step": self.current_step, "action": action_data.get("action", "")}
        valid_vertices = self._valid_vertices(vertices)
        start = self._valid_coord_pair(action_data.get("start_coordinate"))
        if start is not None:
            sx, sy = start
            if valid_vertices is not None:
                entry["vertices"] = list(valid_vertices)
            else:
                entry["vertices"] = [sx, sy, sx, sy]
            entry["center"] = [sx, sy]
            end = self._valid_coord_pair(action_data.get("coordinate"))
            if end is not None:
                entry["end_center"] = [end[0], end[1]]
            else:
                entry["end_center"] = [sx, sy]
        else:
            coord = self._valid_coord_pair(action_data.get("coordinate"))
            if coord is not None:
                x, y = coord
                if valid_vertices is not None:
                    entry["vertices"] = list(valid_vertices)
                else:
                    entry["vertices"] = [x, y, x, y]
                entry["center"] = [x, y]
        return entry

    def _clear_inputs(self):
        self.intent_input.clear()
        self.coord_x_input.clear()
        self.coord_y_input.clear()
        self.coord2_x_input.clear()
        self.coord2_y_input.clear()
        self.text_input.clear()
        self.keys_input.clear()
        self.time_input.clear()
        self.pixels_input.clear()
        self.action_combo.setCurrentIndex(0)
        self._current_vertices = None
        self._cancel_swipe_measurement()
        self._cancel_scroll_measurement()
        self.screenshot_name_label.setText("(暂无)")
        self.screenshot_size_label.setText("-")

    def _update_step_label(self):
        self.step_label.setText(f"步骤: {self.current_step}")

    def _update_navigation_buttons(self):
        self.btn_prev.setEnabled(self.current_step > 0)

    # ========== 长轨迹：缺填校验 / 缩略图 / 草稿 / 断点恢复 ==========

    def _phone_vertices_to_overlay_rect(self, vertices):
        """手机物理像素 vertices [left, top, right, bottom] 逆映射为蒙版本地坐标 QRect

        回看历史步时恢复蒙版拉框显示；无有效框或蒙版尚未布局时返回 None。
        """
        if not vertices or len(vertices) != 4:
            return None
        if (self.overlay.width() <= 0 or self.overlay.height() <= 0
                or self._phone_w <= 0 or self._phone_h <= 0):
            return None
        scale_x = self.overlay.width() / self._phone_w
        scale_y = self.overlay.height() / self._phone_h
        left = int(vertices[0] * scale_x)
        top = int(vertices[1] * scale_y)
        right = int(vertices[2] * scale_x)
        bottom = int(vertices[3] * scale_y)
        return QRect(left, top, max(right - left, 1), max(bottom - top, 1))

    def _replay_overlay_rect(self):
        """窗口 show 后按当前步 vertices 重放一次蒙版历史拉框（补救布局前 width=0）"""
        overlay_rect = self._phone_vertices_to_overlay_rect(self._current_vertices)
        if overlay_rect is not None:
            self.overlay.set_final_rect(overlay_rect)
        else:
            self.overlay.clear_rect()

    @staticmethod
    def _is_valid_number(value):
        """JSON 反序列化后的数值是否为有效数字（排除布尔/NaN/Inf）"""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return value == value and value not in (float("inf"), float("-inf"))

    @classmethod
    def _valid_coord_pair(cls, value):
        """合法坐标点：list/tuple 至少两个有限数；合法则返回 [x, y]，否则 None"""
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            if cls._is_valid_number(value[0]) and cls._is_valid_number(value[1]):
                return [value[0], value[1]]
        return None

    @classmethod
    def _valid_vertices(cls, value):
        """合法拉框：扁平 4 个有限数；兼容 iOS 风格 [[x,y]×4] 嵌套四点"""
        if isinstance(value, (list, tuple)) and len(value) == 4:
            if all(cls._is_valid_number(v) for v in value):
                return list(value)
            if all(isinstance(v, (list, tuple)) and len(v) >= 2
                   and cls._is_valid_number(v[0]) and cls._is_valid_number(v[1])
                   for v in value):
                return [value[0][0], value[0][1], value[2][0], value[2][1]]
        return None

    @staticmethod
    def _find_coord_entry(coords, step):
        """在该轮 coords 中按 step 精确查找条目；未命中返回 None

        旧写法先用 dict 建索引（同 step 后者覆盖前者），再在落空时回退取
        round_coords[i]。位置相同不代表内容相关——旧交付件 coords 少几条时
        下标整体漂移，编辑态由此冒领别的工作的顶点，写回时把污染 bbox 以
        正确 step 编号落盘。位置猜测不可挽救，彻底删除，改由
        _find_coord_entry_by_center 做有根据的恢复。
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

        兼容「step 编号整体漂移但条目本身正确」的旧数据：在尚未被其它步骤
        认领的条目里找 action 相同、且 center 与 JSON 坐标逐轴差 ≤
        COORD_CENTER_TOL 的那一条。命中的是对真实内容的验证，不是对列表位置的猜测。
        """
        if not coords:
            return None
        if action not in COORD_ACTIONS and action not in START_END_ACTIONS:
            return None
        for entry in coords:
            if not isinstance(entry, dict) or id(entry) in claimed_ids:
                continue
            if entry.get("action") != action:
                continue
            mismatched, _detail = entry_coordinate_mismatch(
                entry, coordinate, start_coordinate, COORD_CENTER_TOL)
            # 只有「已验证一致」才认领；None（无可用坐标值）不足以证明归属
            if mismatched is False:
                claimed_ids.add(id(entry))
                return entry
        return None

    @classmethod
    def _classify_coord_state(cls, action_data, coord_entry):
        """coords 条目 + JSON 坐标 → (vertices, coord_issue)

        coord_issue ∈ {None, "absent", "mismatch", "no_box"}：
          absent   交付 JSON 里该步有坐标值，coords 却没有可信的框 → 框丢失
          mismatch 有条目但 center 与坐标值对不上（位置冒领的典型现场）→ 不采信
          no_box   既没有框也没有坐标值 → 本就无框可还原
        "absent"/"mismatch" 一律返回 vertices=None：宁可不显示框，也不让错误
        bbox 在下次写回时以正确 step 编号落进已交付数据。
        """
        data = action_data if isinstance(action_data, dict) else {}
        action = data.get("action")
        coordinate = coord_pair(data.get("coordinate"))
        start_coordinate = coord_pair(data.get("start_coordinate"))
        raw_vertices = coord_entry.get("vertices") if isinstance(coord_entry, dict) else None
        vertices = cls._valid_vertices(raw_vertices)

        if action not in COORD_ACTIONS and action not in START_END_ACTIONS:
            # 非坐标类动作：维持现状（有条目就带上，没有就 None）
            return vertices, None

        has_coord = (coordinate is not None and not is_zero_pair(coordinate)) \
            or (start_coordinate is not None and not is_zero_pair(start_coordinate))
        if vertices is None:
            return None, ("absent" if has_coord else "no_box")
        if has_coord:
            mismatched, _detail = entry_coordinate_mismatch(
                coord_entry, coordinate, start_coordinate, COORD_CENTER_TOL)
            if mismatched:
                return None, "mismatch"
        return vertices, None

    @classmethod
    def _coord_issue_detail(cls, action_data, coord_entry):
        """给汇总告警用的一行差异说明（盘上值 vs JSON 值，给人直接看的格式）"""
        data = action_data if isinstance(action_data, dict) else {}
        coordinate = coord_pair(data.get("coordinate"))
        start_coordinate = coord_pair(data.get("start_coordinate"))
        json_part = (f"JSON coordinate={list(coordinate)}" if coordinate
                     else "JSON 无坐标值")
        if not isinstance(coord_entry, dict):
            return f"coords 无对应条目 / {json_part}"
        mismatched, detail = entry_coordinate_mismatch(
            coord_entry, coordinate, start_coordinate, COORD_CENTER_TOL)
        if mismatched:
            return detail
        return f"coords 条目没有可用的框顶点 / {json_part}"

    def _step_snapshot(self, index):
        """某下标的校验快照：当前编辑步取表单实时值，其余取已落表数据；越界 None"""
        if index == self.current_step and self._current_screenshot_filename:
            return self._collect_step_data()
        if 0 <= index < len(self.steps_data):
            return self.steps_data[index]
        return None

    def validate_step_at(self, index):
        """双源必填校验，返回中文缺失原因列表（空列表表示通过），任何畸形数据都不抛异常。

        live 源（index==current_step 且已截图）：从当前表单实时解析，空串/abc/NaN/Inf
        经 _build_action_data 缺键省略后判缺；历史源只读已落表数据，显式 0/[0,0]/1.0
        均为合法用户数据。下标越界返回空列表。
        """
        is_live = index == self.current_step and bool(self._current_screenshot_filename)
        step = self._step_snapshot(index)
        if not step:
            return []
        reasons = []

        filename = step.get("screenshot")
        if not isinstance(filename, str) or not filename:
            reasons.append("缺少截图")
        else:
            # 磁盘存在性对 live 步同样校验（B24）：草稿恢复回来的当前步、以及
            # 结束前刚 append 的当前步，其截图引用来自磁盘而非本次实时拍摄；
            # 实时截图一律先落盘成功再置三指针，故正常采集中不会误判
            filepath = step.get("screenshot_filepath") or ""
            if not filepath and self.gui_dir:
                filepath = os.path.join(self.gui_dir, filename)
            if filepath and not os.path.isfile(filepath):
                reasons.append("截图文件缺失，请重新截图")

        data = step.get("action_data") or {}
        action = data.get("action", "click")
        vertices = self._current_vertices if is_live else step.get("vertices")

        if action in COORD_ACTIONS or action in START_END_ACTIONS:
            if self._valid_vertices(vertices) is None:
                # hydration 已判定该步「盘上框丢失/框与坐标值不一致」时不阻塞：
                # 强迫重拉框会连带改写已交付的 coordinate（与 Windows A6 同一
                # 取舍）；该步的盘上条目由 save_edited_round 原样保留。
                # is_live 时 _step_snapshot 只回五个键，必须回查 steps_data
                stored = (self.steps_data[index]
                          if 0 <= index < len(self.steps_data) else {})
                inherited = (isinstance(stored, dict)
                             and stored.get("coord_issue") in ("absent", "mismatch"))
                if not inherited:
                    reasons.append("缺少拉框区域（请在 scrcpy 窗口右键拉框标注目标区域）")
            if action in START_END_ACTIONS:
                if self._valid_coord_pair(data.get("start_coordinate")) is None:
                    reasons.append("缺少起点坐标（请在 scrcpy 窗口右键拉框标注目标区域）")
                if self._valid_coord_pair(data.get("coordinate")) is None:
                    reasons.append("缺少终点坐标")
            else:
                if self._valid_coord_pair(data.get("coordinate")) is None:
                    reasons.append("缺少坐标（请在 scrcpy 窗口右键拉框标注目标区域）")
        if action == "scroll":
            # 0/负值是合法测量结果；规格要求有限整数（排除 bool），
            # 手改历史 JSON 中的 1.5/True 等一律判缺；live 源恒由 int 落表
            pixels = data.get("pixels")
            if not (isinstance(pixels, int) and not isinstance(pixels, bool)):
                reasons.append("缺少滚动像素（请完成滚动测量）")
        if action in TEXT_ACTIONS:
            text = data.get("text", "")
            text = text.strip() if isinstance(text, str) else ""
            if not text:
                if action == "type":
                    reasons.append("缺少输入文本")
                elif action == "open_app":
                    reasons.append("缺少应用名称")
                elif action == "open_url":
                    reasons.append("缺少网址 URL")
                else:
                    reasons.append("缺少回答内容")
        if action in KEY_ACTIONS:
            keys = data.get("keys")
            if (not isinstance(keys, list) or not keys
                    or not all(isinstance(k, str) and k.strip() for k in keys)):
                reasons.append("缺少按键")
        if action in TIME_ACTIONS:
            if not self._is_valid_number(data.get("time")):
                if action == "long_press":
                    reasons.append("缺少长按时间")
                else:
                    reasons.append("缺少等待时间")
        if action in BUTTON_ACTIONS:
            buttons = data.get("buttons")
            if not (isinstance(buttons, list) and buttons
                    and str(buttons[0]) in SYSTEM_BUTTONS):
                reasons.append("缺少系统按钮选择")
        return reasons

    def get_cached_missing(self, index):
        """读取缺填缓存；该下标尚未缓存返回 None（区别于空列表“无缺失”）"""
        return self._missing_cache.get(index)

    def revalidate_all_missing(self):
        """重建缺填缓存（含未确认新步 live 槽复位）并刷新侧栏缺填标记与看板计数"""
        self._missing_cache = {
            i: self.validate_step_at(i) for i in range(len(self.steps_data))
        }
        self._missing_live = None
        for i, item in enumerate(self.sidebar.item_widgets):
            item.set_missing(self._missing_cache.get(i) or [])
        self.sidebar.refresh_dashboard()

    def live_missing_reasons(self):
        """未确认新步（current_step == len 且已截图）的实时缺项；无该槽返回 None。

        惰性计算一次并缓存，避免看板频繁刷新时反复实时校验。
        """
        if not (self.current_step == len(self.steps_data)
                and self._current_screenshot_filename):
            self._missing_live = None
            return None
        if self._missing_live is None:
            self._missing_live = self.validate_step_at(self.current_step)
        return self._missing_live

    def _on_validation_debounced(self):
        """输入防抖后重算当前步缺项；缓存下标集合与 0..total-1 漂移时退化为全量"""
        total = len(self.steps_data)
        if set(self._missing_cache.keys()) != set(range(total)):
            self.revalidate_all_missing()
            return
        self._missing_live = None
        current = self.current_step
        if 0 <= current < total:
            reasons = self.validate_step_at(current)
            self._missing_cache[current] = reasons
            if current < len(self.sidebar.item_widgets):
                self.sidebar.item_widgets[current].set_missing(reasons)
            self.sidebar.refresh_dashboard()
            self.sidebar.ensure_current_thumb(current)
        else:
            # 未确认新步无侧栏条目，缺项只并入看板计数
            self.sidebar.refresh_dashboard()

    def build_marked_preview(self, filename, vertices, target_size):
        """从磁盘加载截图，按手机物理像素绘制 vertices 绿框红十字，再缩放到 target_size

        供侧栏缩略图懒加载调用；原图仅短暂驻留，返回的是小尺寸 QPixmap。
        """
        if not filename or self.gui_number is None:
            return None
        pixmap = self.data_manager.load_screenshot(self.gui_number, filename)
        if pixmap is None or pixmap.isNull():
            return None
        if not (isinstance(target_size, QSize) and target_size.isValid()
                and target_size.width() > 0 and target_size.height() > 0):
            target_size = QSize(200, 112)

        marked = QPixmap(pixmap)
        if vertices and len(vertices) == 4:
            painter = QPainter(marked)
            painter.setRenderHint(QPainter.Antialiasing)
            left, top, right, bottom = (int(v) for v in vertices)
            painter.setPen(QPen(QColor(0, 255, 0, 200), 6, Qt.DashLine))
            painter.setBrush(QColor(0, 255, 0, 30))
            painter.drawRect(QRect(left, top, right - left, bottom - top))
            cx, cy = (left + right) // 2, (top + bottom) // 2
            painter.setPen(QPen(QColor(255, 0, 0), 10))
            painter.drawLine(cx - 30, cy, cx + 30, cy)
            painter.drawLine(cx, cy - 30, cx, cy + 30)
            painter.end()
        return marked.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def schedule_draft_save(self):
        """数据变化点统一入口：看板提示“保存中”，约 1000ms 防抖后写草稿"""
        if self._edit_mode:
            # 编辑已完成任务不产生草稿，避免重新出现在「继续未完成任务」
            return
        if self.gui_number is None:
            return
        self.sidebar.set_draft_saving()
        self.draft_timer.stop()
        self.draft_timer.start(1000)

    def _write_draft_now(self):
        """立即序列化当前编辑现场到 gui_编号_draft.json

        steps_data 只落可序列化字段（截图文件名/intent/action_data/vertices），
        绝不含 QPixmap/QWidget/screenshot_filepath 等运行态对象。
        """
        self.draft_timer.stop()
        if self._edit_mode:
            # 编辑已完成任务：不写草稿（关闭时由 save_edited_round 写回最终 JSON）
            return
        if self.gui_number is None:
            return
        # 先把当前表单同步进 steps_data，避免草稿落后于编辑现场
        self._save_current_to_steps()
        if not self.steps_data and not self.rounds:
            # 空现场（如撤销/删除清空全部步骤）：删除残留草稿，防止续采复活已删步骤
            self.data_manager.delete_draft(self.gui_number)
            return

        # 2.1（B20a）恒用当前编辑现场写草稿。早前在轮次边界从 rounds[-1] 反推
        # steps_for_draft，草稿于是带上已落轮的全部步骤；续采 load_from_draft 见
        # steps_data 非空就判定“当前轮未结束”，既不追问新指令，又把旧轮步骤接在
        # 新步前面，再落轮就成了 rounds = [R1(旧步), R2(旧步 + 新步)]。
        # 落轮后 steps_data 已由 _save_current_round_to_list 清空，无需重建。
        steps_for_draft = self.steps_data
        serial_steps = []
        for step in steps_for_draft:
            serial_entry = {
                "screenshot": step.get("screenshot", ""),
                "intent": step.get("intent", ""),
                "action_data": copy.deepcopy(step.get("action_data") or {}),
                "vertices": copy.deepcopy(step.get("vertices")),
            }
            # 下游字段（CoT/active_window/ui_tree_segment）为可选透传：
            # 有条目才写，无则不引入新键；与 load_from_draft 的恢复对称
            if step.get("CoT"):
                serial_entry["CoT"] = copy.deepcopy(step.get("CoT"))
            if step.get("active_window"):
                serial_entry["active_window"] = copy.deepcopy(step.get("active_window"))
            if step.get("ui_tree_segment"):
                serial_entry["ui_tree_segment"] = copy.deepcopy(
                    step.get("ui_tree_segment"))
            if isinstance(step.get("observation"), dict):
                serial_entry["observation"] = copy.deepcopy(step.get("observation"))
            serial_steps.append(serial_entry)

        draft = {
            "gui_number": self.gui_number,
            "app_name": self.app_name,
            "task_instruction": self.task_instruction,
            "screen_info": copy.deepcopy(self.screen_info) if self.screen_info else {},
            "app_type": self.app_type,
            "rounds": copy.deepcopy(self.rounds),
            "steps_data": serial_steps,
            "current_step_index": self.current_step,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        saved_path = self.data_manager.save_draft(draft, self.gui_number)
        if saved_path:
            self.sidebar.set_draft_saved()

    def load_from_draft(self, draft):
        """从草稿恢复编辑现场（断点续采）

        :return: True 表示当前轮无步骤但已有历史轮次，需要上层追问下一条指令
        """
        if not draft:
            return False

        self.gui_number = str(draft.get("gui_number") or "").zfill(6)
        self.gui_dir = os.path.join(self.data_manager.current_dir, f"gui_{self.gui_number}")
        self.app_name = draft.get("app_name", self.app_name) or self.app_name
        self.task_instruction = draft.get("task_instruction", "") or ""
        screen_info = draft.get("screen_info")
        if isinstance(screen_info, dict) and screen_info:
            self.screen_info = screen_info
        self.app_type = draft.get("app_type", self.app_type) or self.app_type
        self.rounds = copy.deepcopy(draft.get("rounds") or [])
        self.coords_data = []

        # 恢复当前轮步骤，截图只保留磁盘文件名并现场重拼绝对路径
        restored_steps = []
        for step in draft.get("steps_data") or []:
            filename = step.get("screenshot", "") or ""
            filepath = os.path.join(self.gui_dir, filename) if filename else ""
            restored = {
                "screenshot": filename,
                "screenshot_filepath": filepath,
                "intent": step.get("intent", ""),
                "action_data": copy.deepcopy(step.get("action_data") or {}),
                "vertices": copy.deepcopy(step.get("vertices")),
            }
            # 对称恢复草稿透传的下游可选字段；缺键不补，保持原有四键结构
            if step.get("CoT"):
                restored["CoT"] = copy.deepcopy(step.get("CoT"))
            if step.get("active_window"):
                restored["active_window"] = copy.deepcopy(step.get("active_window"))
            if step.get("ui_tree_segment"):
                restored["ui_tree_segment"] = copy.deepcopy(
                    step.get("ui_tree_segment"))
            if isinstance(step.get("observation"), dict):
                restored["observation"] = copy.deepcopy(step.get("observation"))
            restored_steps.append(restored)
        self.steps_data = restored_steps

        # 恢复手机分辨率（蒙版坐标映射依赖）
        phone_sz = self.screen_info.get("screen_size", [1080, 2400])
        self._phone_w = phone_sz[0]
        self._phone_h = phone_sz[1]

        # 当前步下标裁剪到合法范围
        try:
            idx = int(draft.get("current_step_index", 0) or 0)
        except (TypeError, ValueError):
            idx = 0
        self.current_step = max(0, min(idx, len(self.steps_data) - 1)) if self.steps_data else 0

        self._missing_cache = {}
        self._insert_after_index = None
        if self.steps_data:
            # 当前轮有未结束步骤：回到当时编辑的步骤
            self._current_round_saved = False
            self._load_step_to_form(self.current_step)
            # 此时窗口尚未 show，蒙版宽高可能为 0，历史拉框画不上；
            # 事件循环空转一轮等布局完成后按当前 vertices 再重放一次
            QTimer.singleShot(0, self._replay_overlay_rect)
        else:
            # 当前轮为空：有历史轮次时保持“轮次已保存”语义，等待新指令
            self._current_round_saved = bool(self.rounds)
            self._reset_for_next_step()

        self.sidebar.rebuild_items()
        self.setWindowTitle(f"GUI长步骤采标工具-Android - {self.app_name}")
        self.schedule_draft_save()
        # steps_data 为空且 rounds 非空：上层需追问下一条任务指令
        return (not self.steps_data) and bool(self.rounds)

    # ========== 编辑已完成任务 ==========

    @staticmethod
    def _assign_coords_to_rounds(coords_entries, rounds):
        """把扁平 coords 条目归属到各轮次

        优先按条目 round 字段分组（只要有任何条目带可用 round）；否则按 step 回退切连续段，
        组数不匹配时逐段对齐 (step, action) 到未占用的轮次，无法对齐的并入最后一轮，绝不丢弃。
        """
        if not rounds:
            return []
        entries = [e for e in (coords_entries or []) if isinstance(e, dict)]
        if not entries:
            return [[] for _ in rounds]

        def usable_round(e):
            r = e.get("round")
            return isinstance(r, int) and not isinstance(r, bool)

        # 4.3（B35）对齐 iOS _group_coords_into_rounds：只要有条目带可用 round 就按
        # round 逐条目归组，缺失/越界的并入最后一轮。旧写法要求全部条目都可用，于是
        # 一份文件里混进一条无 round 的历史条目就整体退化回不可靠的 step 切段。
        if any(usable_round(e) for e in entries):
            groups = [[] for _ in rounds]
            for e in entries:
                r = e.get("round") if usable_round(e) else None
                groups[r if r is not None and 0 <= r < len(rounds) else -1].append(e)
            return groups

        # 无 round：按 step 回退切分连续段（step 变小即视为下一轮）
        groups = [[]]
        prev_step = None
        for e in entries:
            step = e.get("step")
            valid_step = isinstance(step, int) and not isinstance(step, bool)
            if valid_step and prev_step is not None and step < prev_step:
                groups.append([])
            groups[-1].append(e)
            prev_step = step if valid_step else None
        if len(groups) == len(rounds):
            return groups

        # 组数不匹配：逐段找一个「尚未被占用」且轨迹签名匹配的轮次，段内逐条目归入
        # （4.3/B35 对齐 iOS 的 used 集合）。旧写法把 (step, action) 用 setdefault
        # 映射到首个命中的轮次，于是多段的同签名条目全挤进第一轮、其余轮次一条坐标
        # 都拿不到——已交付顶点被静默错配；段内对不上签名的条目仍并入最后一轮，绝不丢弃。
        def entry_matches_round(entry, round_data):
            step = entry.get("step")
            action = entry.get("action")
            for t in round_data.get("trajectory") or []:
                if not isinstance(t, dict) or t.get("step") != step:
                    continue
                actions = t.get("actions") or []
                traj_action = (actions[0].get("action")
                               if actions and isinstance(actions[0], dict) else None)
                if action is None or traj_action == action:
                    return True
            return False

        matched = [[] for _ in rounds]
        used = set()
        for segment in groups:
            target = None
            for e in segment:
                for r, rd in enumerate(rounds):
                    if r in used:
                        continue
                    if entry_matches_round(e, rd):
                        target = r
                        break
                if target is not None:
                    break
            if target is None:
                # 整段都对不上任何未占用的轮次：并入最后一轮且不占用该轮
                matched[-1].extend(segment)
                continue
            for e in segment:
                if entry_matches_round(e, rounds[target]):
                    matched[target].append(e)
                else:
                    # 签名对不上选定的轮次：仍并入最后一轮，绝不丢弃
                    matched[-1].append(e)
            used.add(target)
        return matched

    # 受保护字段：新值为空（None/空串/空 dict/空 list）时保留旧值，
    # 避免编辑保存把下游已填好的 CoT / active_window / ui_tree_segment /
    # element / status 用空串覆盖
    _PROTECTED_STEP_KEYS = ("CoT",)
    _PROTECTED_OBSERVATION_KEYS = ("active_window", "ui_tree_segment")
    _PROTECTED_ACTION_KEYS = ("element", "status")

    @staticmethod
    def _is_empty_protected_value(value):
        """受保护字段的空值定义：None、空串、空 dict、空 list。"""
        if value is None or value == "":
            return True
        if isinstance(value, (dict, list)) and len(value) == 0:
            return True
        return False

    @classmethod
    def _merge_protected_field(cls, merged, key, old_value, protected_keys):
        """受保护字段：新值非空才覆盖，空值保留原值。"""
        if key not in protected_keys:
            return False
        if key in merged and not cls._is_empty_protected_value(merged[key]):
            return True
        merged[key] = copy.deepcopy(old_value)
        return True

    @classmethod
    def _merge_missing_keys(cls, new, old, protected_keys=()):
        """字段级递归合并，返回新对象，不就地修改入参。

        - 受保护字段（protected_keys）：新值非空才覆盖，空值保留旧值；
        - 其余键：新结构缺失则深拷贝旧值；新旧同为 dict/list 时递归合并；
        - 其余情况以新值为准。
        """
        if isinstance(new, dict) and isinstance(old, dict):
            merged = copy.deepcopy(new)
            for k, v in old.items():
                if k not in merged:
                    merged[k] = copy.deepcopy(v)
                    continue
                if cls._merge_protected_field(merged, k, v, protected_keys):
                    continue
                if isinstance(merged[k], dict) and isinstance(v, dict):
                    child_protected = ()
                    if k == "observation":
                        child_protected = cls._PROTECTED_OBSERVATION_KEYS
                    merged[k] = cls._merge_missing_keys(
                        merged[k], v, child_protected)
                elif isinstance(merged[k], list) and isinstance(v, list):
                    merged[k] = cls._merge_missing_keys(merged[k], v)
            return merged
        if isinstance(new, list) and isinstance(old, list):
            # actions 等列表按元素位置递归合并，保留元素内编辑器未管理的键
            merged = [copy.deepcopy(item) for item in new]
            for i, old_item in enumerate(old):
                if i < len(merged):
                    # trajectory 的 list 只有 actions：动作元素按动作受保护键合并
                    merged[i] = cls._merge_missing_keys(
                        merged[i], old_item, cls._PROTECTED_ACTION_KEYS)
                else:
                    merged.append(copy.deepcopy(old_item))
            return merged
        return copy.deepcopy(new)

    def load_from_completed_json(self, completed_data, coords_entries, round_index, gui_dir):
        """从已完成任务的最终 JSON + coords 重建编辑现场（编辑模式）

        :param completed_data: gui_xxxxxx.json 内容
        :param coords_entries: 扁平 coords 条目列表
        :param round_index: 要编辑的轮次下标（从 0 开始）
        :param gui_dir: gui_xxxxxx 目录完整路径
        """
        data = completed_data if isinstance(completed_data, dict) else {}
        self._completed_json = copy.deepcopy(data)

        gui_dir = os.path.normpath(gui_dir)
        dir_name = os.path.basename(gui_dir)
        match = re.fullmatch(r"gui_(\d{6})", dir_name)
        self.gui_number = match.group(1) if match else (self.gui_number or dir_name)
        self.gui_dir = gui_dir

        # messages → rounds（user 记录待用指令，assistant 生成一轮）
        rounds = []
        pending_instruction = ""
        for msg in data.get("messages") or []:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") == "user":
                pending_instruction = msg.get("instruction", "") or ""
            elif msg.get("role") == "assistant":
                rounds.append({
                    "instruction": pending_instruction,
                    "trajectory": copy.deepcopy(msg.get("trajectory") or []),
                    "coords": [],
                })
        self.rounds = rounds
        self.coords_data = []

        self._coords_rounds = self._assign_coords_to_rounds(coords_entries, rounds)
        for i, rd in enumerate(rounds):
            if i < len(self._coords_rounds):
                rd["coords"] = copy.deepcopy(self._coords_rounds[i])

        coords_path = os.path.join(gui_dir, f"gui_{self.gui_number}_coords.json")
        self._original_coords_exist = os.path.isfile(coords_path)

        if rounds:
            idx = max(0, min(int(round_index), len(rounds) - 1))
        else:
            idx = 0
        self._edit_round_index = idx
        selected = rounds[idx] if rounds else {"instruction": "", "trajectory": [], "coords": []}
        self.task_instruction = selected.get("instruction", "") or ""

        # 选中轮 trajectory → steps_data（step 顺序与 JSON 一致）
        round_coords = self._coords_rounds[idx] if idx < len(self._coords_rounds) else []
        steps_data = []
        missing_files = []
        coord_issues = []
        claimed_ids = set()      # 已被某一步认领的条目，防止按 center 恢复时重复占用
        for i, t in enumerate(selected.get("trajectory") or []):
            if not isinstance(t, dict):
                continue
            obs = t.get("observation") or {}
            filename = obs.get("screenshot", "") if isinstance(obs, dict) else ""
            # 截图文件在 gui_dir 下不存在时收集清单，加载后统一提示（不阻断编辑）
            if filename and not os.path.isfile(os.path.join(gui_dir, filename)):
                missing_files.append(f"步骤 {i}: {filename}")
            actions = t.get("actions") or []
            action_data = copy.deepcopy(actions[0]) if actions and isinstance(actions[0], dict) else {}
            # 两趟匹配：先按 step 精确查，落空再按 center 在未认领条目里恢复。
            # 不再有「按下标回退取第 i 条」——位置冒领会污染已交付 bbox。
            coord_entry = self._find_coord_entry(round_coords, t.get("step"))
            if coord_entry is not None:
                claimed_ids.add(id(coord_entry))
            else:
                coord_entry = self._find_coord_entry_by_center(
                    round_coords, action_data.get("action"),
                    coord_pair(action_data.get("coordinate")),
                    coord_pair(action_data.get("start_coordinate")),
                    claimed_ids)
            vertices, coord_issue = self._classify_coord_state(action_data, coord_entry)
            if coord_issue in ("absent", "mismatch"):
                action_en = action_data.get("action", "-")
                action_cn = next((label for value, label in ANDROID_ACTIONS
                                  if value == action_en), action_en)
                coord_issues.append((
                    i, action_cn, coord_issue,
                    self._coord_issue_detail(action_data, coord_entry)))
            steps_data.append({
                "screenshot": filename,
                "screenshot_filepath": os.path.join(gui_dir, filename) if filename else "",
                "intent": t.get("intent", ""),
                "action_data": action_data,
                "vertices": vertices,
                # 盘上 bbox 缺失/与已交付坐标不一致时保留原条目快照，供写回时
                # 原样继承（见 save_edited_round），绝不让「打开看一眼」丢数据
                "coord_issue": coord_issue,
                "orig_coord_entry": (
                    copy.deepcopy(coord_entry)
                    if coord_issue in ("absent", "mismatch")
                    and isinstance(coord_entry, dict) else None),
            })
        self.steps_data = steps_data
        self._coord_issues = coord_issues

        # 恢复手机分辨率（蒙版坐标映射依赖）
        phone_sz = self.screen_info.get("screen_size", [1080, 2400]) if isinstance(self.screen_info, dict) else [1080, 2400]
        self._phone_w = phone_sz[0]
        self._phone_h = phone_sz[1]

        # 编辑模式标志：不写草稿、确认不切轮次、关闭自动写回
        self._edit_mode = True
        self._task_completed = False
        self._current_round_saved = True   # 避免旧逻辑误判为"未保存轮次"
        self.current_step = 0
        self._missing_cache = {}
        self._missing_live = None
        self._insert_after_index = None
        self._screenshot_in_progress = False

        if self.steps_data:
            self._load_step_to_form(0)
            QTimer.singleShot(0, self._replay_overlay_rect)
        else:
            self._reset_for_next_step()

        self.sidebar.rebuild_items()
        self.btn_save_edit.show()
        self.btn_relabel.show()
        self.setWindowTitle(f"GUI长步骤采标工具-Android - {self.app_name}（编辑已完成任务）")
        # 先于任何常规提示告警：不一致必须先被看见，否则采集员会以为框没拉到
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
                  "如需修复请在原图重新拉框。"
            )

        edit_status = (
            f"编辑已完成任务 gui_{self.gui_number} · 第 {idx + 1} 轮 - 修改后请点击[保存修改]"
        )
        if self._coord_issues:
            # 保留常规状态串，只追加告警：直接覆盖会让其他依赖该文本的
            # 现场提示（和后续测试）被顶掉
            edit_status += f" · ⚠ 检测到 {len(self._coord_issues)} 个步骤的 bbox 与 coordinate 不一致"
        self.status_label.setText(edit_status)

        if missing_files:
            QMessageBox.warning(
                self,
                "截图文件缺失",
                "以下步骤的截图文件在磁盘上不存在，预览将无法显示：\n\n"
                + "\n".join(missing_files),
            )

    def save_edited_round(self, silent=False):
        """把当前轮修改写回最终 JSON 与 coords JSON（仅替换被编辑轮次）

        :param silent: True 为关闭窗口时自动写回（跳过校验、不弹窗）
        :return: True 表示最终 JSON 写入成功
        """
        self._save_current_to_steps_for_edit()

        if not silent:
            missing_entries = []
            for i, step in enumerate(self.steps_data):
                reasons = self.validate_step_at(i)
                if reasons:
                    action_en = (step.get("action_data") or {}).get("action", "-")
                    action_cn = next((label for value, label in ANDROID_ACTIONS
                                      if value == action_en), action_en)
                    missing_entries.append((i, action_cn, reasons))
            if missing_entries:
                dialog = ValidationFailDialog(missing_entries, self)
                dialog.exec_()
                target = dialog.target_index()
                if target is not None:
                    self.jump_to_step(target)
                return False

        r = self._edit_round_index
        if not (0 <= r < len(self.rounds)):
            print(f"[编辑保存] 轮次下标非法: {r}")
            return False
        if not self.gui_number:
            print("[编辑保存] 缺少 gui 编号")
            return False

        # ---- 重建当前轮 trajectory（按截图文件名合并原步未暴露字段）----
        original_traj = self.rounds[r].get("trajectory") or []
        origin_by_shot = {}
        for t in original_traj:
            if not isinstance(t, dict):
                continue
            fn = (t.get("observation") or {}).get("screenshot")
            if fn and fn not in origin_by_shot:
                origin_by_shot[fn] = t

        new_trajectory = []
        for i, step in enumerate(self.steps_data):
            filename = step.get("screenshot", "") or ""
            # steps_data 条目自身可能透传了下游字段（草稿续采场景）
            step_obs = step.get("observation")
            if isinstance(step_obs, dict):
                active_window = step_obs.get("active_window", "")
                ui_tree_segment = step_obs.get("ui_tree_segment", "")
            else:
                active_window = step.get("active_window", "")
                ui_tree_segment = step.get("ui_tree_segment", "")
            t_step = {
                "step": i,
                "intent": step.get("intent", ""),
                "CoT": step.get("CoT", ""),
                "observation": {
                    "screenshot": filename,
                    "active_window": active_window,
                    "ui_tree_segment": ui_tree_segment,
                },
                "actions": [copy.deepcopy(step.get("action_data") or {})],
            }
            origin = origin_by_shot.get(filename)
            # 文件名匹配不到时按步序兜底（与 iOS 同口径），保证无同名截图
            # 或重命名场景下原步骤的下游字段仍可参与保留合并
            if not isinstance(origin, dict) and i < len(original_traj) \
                    and isinstance(original_traj[i], dict):
                origin = original_traj[i]
            if isinstance(origin, dict):
                # 字段级合并（返回新对象）：CoT / active_window /
                # ui_tree_segment / element / status 新值为空时保留原值。
                # 终止类动作（terminate/answer）的 element=""、status="success"
                # 由 _build_action_data 在重建动作时强制给出，非空新值自然胜出，
                # 无需后置覆盖，避免给历史交付件中本无 status 键的条目凭空加键。
                t_step = self._merge_missing_keys(
                    t_step, origin, self._PROTECTED_STEP_KEYS)
            new_trajectory.append(t_step)

        # ---- 重建当前轮 coords（内部条目不加 round，round 只在写盘副本上注入）----
        editor_coord_keys = {"step", "action", "vertices", "center",
                             "start_vertices", "start_center", "end_vertices", "end_center"}
        original_coords = self.rounds[r].get("coords") or []
        origin_coords_by_step = {}
        for c in original_coords:
            if isinstance(c, dict):
                try:
                    origin_coords_by_step[c.get("step")] = c
                except TypeError:
                    continue

        new_coords = []
        for i, step in enumerate(self.steps_data):
            action_data = step.get("action_data") or {}
            action = action_data.get("action")
            needs_box = action in COORD_ACTIONS or action in START_END_ACTIONS
            orig = step.get("orig_coord_entry")
            if (needs_box and self._valid_vertices(step.get("vertices")) is None
                    and isinstance(orig, dict)):
                # hydration 已判定该步「盘上框丢失/框与坐标值不一致」：既不给
                # _build_coords_entry 伪造 1×1 退化框，也不因“没框”丢条目，而是按
                # 当前步序重编号后原样保留盘上顶点（与 Windows A4 同口径），
                # 保证「打开看一眼就保存」不会改变已交付的 bbox
                kept = copy.deepcopy(orig)
                kept["step"] = i
                new_coords.append(kept)
                continue
            entry = self._build_coords_entry(action_data, step.get("vertices"))
            entry["step"] = i
            if "center" not in entry:
                v = self._valid_vertices(step.get("vertices"))
                if v is not None:
                    entry["center"] = [int((v[0] + v[2]) / 2), int((v[1] + v[3]) / 2)]
            origin = origin_coords_by_step.get(i)
            if origin is None and i < len(original_coords) and isinstance(original_coords[i], dict):
                origin = original_coords[i]
            if isinstance(origin, dict):
                for k, v in origin.items():
                    if k not in entry and k not in editor_coord_keys:
                        entry[k] = copy.deepcopy(v)
            new_coords.append(entry)

        self.rounds[r]["trajectory"] = new_trajectory
        self.rounds[r]["coords"] = new_coords
        if r < len(self._coords_rounds):
            self._coords_rounds[r] = copy.deepcopy(new_coords)

        # 1.5（B40）原地只改被编辑轮对应的两条消息，其余消息对象一律不动。
        # 早前先 deepcopy 再按 self.rounds 全量重建，会把原 JSON 里非
        # user/assistant 的消息、每轮消息自带的其他字段、末尾孤立 user 消息
        # 整条丢掉——已交付数据不可恢复。结构不满足「严格交替」时
        # 拒绝写回，绝不退化成全量重建。
        data = copy.deepcopy(self._completed_json) if isinstance(self._completed_json, dict) else {}
        messages = data.get("messages")
        anchor = 2 * r + 1
        if (not isinstance(messages, list) or len(messages) <= anchor
                or not isinstance(messages[2 * r], dict)
                or not isinstance(messages[anchor], dict)
                or messages[2 * r].get("role") != "user"
                or messages[anchor].get("role") != "assistant"):
            reason = (
                f"最终 JSON 的 messages 结构与轮次不匹配：第 {r + 1} 轮需要 "
                f"messages[{2 * r}]=user / messages[{anchor}]=assistant"
            )
            if silent:
                print(f"[关闭] 编辑写回中止: gui_{self.gui_number}/ {reason}")
            else:
                QMessageBox.critical(
                    self, "保存失败", reason + "\n已拒绝写回，原数据保持不变"
                )
            return False

        edited_round = self.rounds[r]
        messages[2 * r]["instruction"] = edited_round.get("instruction", "")
        messages[anchor]["trajectory"] = edited_round.get("trajectory") or []
        data["messages"] = messages

        # 1.4 安全网：编辑写回会整份替换已交付 JSON，先把原文件留一份 .bak（覆盖式）。
        # 仅在原文件存在时生成；备份失败不阻断保存。
        self.data_manager.backup_final_json(self.gui_number)

        json_path = self.data_manager.save_json_data(data, self.gui_number)
        if not json_path:
            if silent:
                print(f"[关闭] 编辑保存失败: gui_{self.gui_number}/ 最终 JSON 写入失败")
            else:
                QMessageBox.critical(self, "保存失败", "最终 JSON 写入失败，原数据保持不变")
            return False

        all_coords = []
        for round_index, rd in enumerate(self.rounds):
            # 4.2（B4/B18）与 _save_all_rounds_to_file 同口径：写盘副本注入 round
            for coord in rd.get("coords") or []:
                if isinstance(coord, dict):
                    coord = {**coord, "round": round_index}
                all_coords.append(coord)
        # 1.5（B41）coords 只在真的收集到条目时才写盘。旧条件带了
        # or self._original_coords_exist，会在「本轮导出 0 条坐标」时用空数组
        # 覆盖已交付的坐标文件；现在改为告警并跳过写入，保留原文件。
        if all_coords:
            self.data_manager.save_coords_json(all_coords, self.gui_number)
        elif self._original_coords_exist:
            print(
                f"警告：编辑写回收集到 0 条坐标，已跳过 coords 写入以保留原文件"
                f"（gui_{self.gui_number}）"
            )

        self._edit_final_saved = True
        if self._coord_issues:
            # 继承性盘上缺陷本次未消除：写回成功不等于数据已干净，提醒显式处置
            print(
                f"提示：gui_{self.gui_number} 仍有 {len(self._coord_issues)} 个步骤的盘上 bbox 与 "
                f"coordinate 不一致（本次原样保留、未改动这些条目）；"
                f"如需修复请在原图重新拉框。"
            )
        self.draft_timer.stop()
        self.status_label.setText(f"第 {r + 1} 轮修改已保存到 gui_{self.gui_number}/")

        if silent:
            print(f"[关闭] 编辑保存成功: gui_{self.gui_number}/")
            return True

        QMessageBox.information(
            self, "保存成功",
            f"第 {r + 1} 轮修改已保存到 gui_{self.gui_number}/"
        )
        if self._init_window:
            self._init_window.show()
        self.close()
        return True

    def refresh_sidebar(self, fully=False):
        """供外部在程序改动数据后刷新侧栏：fully=True 全量重建，否则只刷新看板"""
        if fully:
            self.sidebar.rebuild_items()
        else:
            self.sidebar.refresh_dashboard()

    # ========== 任务完成 / 轮次管理 ==========

    def show_round_preview_dialog(self):
        """打开只读多轮回看器；暂无已完成轮次时直接返回"""
        if not self.rounds:
            return
        RoundPreviewDialog(self).exec_()

    def _finish_task(self):
        # 重入保护：已交付后再次触发（重复确认/按钮连点）不得重复落轮与重复写盘
        if self._task_completed:
            return
        # 先把当前表单同步进 steps_data，再对全部步骤做必填校验
        self._save_current_to_steps()
        missing_entries = []
        for i, step in enumerate(self.steps_data):
            reasons = self.validate_step_at(i)
            if reasons:
                action_en = (step.get("action_data") or {}).get("action", "-")
                if (action_en == "answer" and i == self.current_step
                        and self._current_action_key() == "answer_terminate"):
                    action_cn = "回答并结束"
                else:
                    action_cn = next((label for value, label in ANDROID_ACTIONS
                                      if value == action_en), action_en)
                missing_entries.append((i, action_cn, reasons))
        if missing_entries:
            # DI-18：上面的 _save_current_to_steps 可能刚 append 出新步，而拒收分支
            # 不重建侧栏 → 条目数落后于 steps_data、缺填标记停在旧步骤集合上。
            # 弹清单前先全量重建（内部会重算缺项缓存与条目标记），保证界面与模型一致
            self.sidebar.rebuild_items()
            # 校验未通过：清单对话框支持跳转到缺填步骤，阻止结束
            dialog = ValidationFailDialog(missing_entries, self)
            dialog.exec_()
            target = dialog.target_index()
            if target is not None:
                self.jump_to_step(target)
            return

        if not self._save_current_round_to_list():
            # B14：缺指令被拒绝落轮 → 中止收尾，不写出缺最后一轮的交付文件，
            # 也不把未完成的 steps_data 清掉
            QMessageBox.warning(
                self, "缺少任务指令",
                "当前轮次还没有任务指令，已中止保存以免轨迹挂到错误指令上。\n"
                "请重新确认本步并输入本轮指令后再完成标注。"
            )
            return
        save_ok = self._save_all_rounds_to_file()

        # 标记：正常完成且写入成功后，closeEvent 跳过草稿保存（草稿已删除）
        # 如果最终 JSON 写入失败，_task_completed 保持 False，closeEvent 会保留草稿
        self._task_completed = save_ok
        if save_ok:
            # 交付门闩保持到新任务开始：交付后现场仍是旧轮数据，任何采集/确认
            # 入口都必须早退，直到用户明确选择「继续新任务」或关闭窗口
            self._round_transition_pending = True

        if not save_ok:
            # 5.7（B31）落盘失败绝不能接着弹"当前任务已保存到 gui_N/"：用户会据此
            # 认为数据已交付，而磁盘上只有草稿。失败即中止并明确报错。
            QMessageBox.critical(
                self, "保存失败",
                f"本轮数据未能写入 gui_{self.gui_number}/，草稿已保留，"
                "请重新打开工具续采后再完成一次。"
            )
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("任务完成")
        msg_box.setText(f"当前任务已保存到 gui_{self.gui_number}/\n\n是否继续新任务？")
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.move(50, 50)
        reply = msg_box.exec_()
        if reply == QMessageBox.Yes:
            # 继续新任务：重置完成标记与交付门闩，新任务需要正常采集与写草稿
            self._task_completed = False
            self._round_transition_pending = False
            self._start_new_task()
        else:
            self.status_label.setText(f"任务完成 - 数据已保存到 gui_{self.gui_number}/")
            if self._init_window:
                self._init_window.show()
            self.close()

    def _prompt_missing_instruction(self):
        """本轮缺少任务指令时弹窗补齐；返回 False 表示用户仍未给出指令。

        B14：取消新轮后 task_instruction 被置空（见 _reset_workspace_after_cancel）。
        放任空指令落轮的话，新一轮轨迹会静默挂到上一轮的旧指令上，事后无从
        分辨哪段轨迹属于哪条指令，因此落轮前必须显式补齐，补齐失败由调用方拒绝落轮。
        """
        dialog = QInputDialog(self)
        dialog.setWindowTitle("任务指令")
        dialog.setLabelText(f"【{self.app_name}】当前轮次缺少任务指令，请输入本轮对应的指令：")
        dialog.setTextEchoMode(QLineEdit.Normal)
        dialog.setTextValue("")
        dialog.move(dialog.x() + 150, dialog.y())
        ok = dialog.exec_()
        new_instruction = dialog.textValue()
        if ok and new_instruction.strip():
            self.task_instruction = new_instruction.strip()
            return True
        self.status_label.setText("缺少任务指令 - 本轮未落轮，请补齐指令后重新确认")
        return False

    def _save_current_round_to_list(self, prompt_instruction=True):
        """把当前轮次落入 rounds 列表并消费掉本轮数据。

        :param prompt_instruction: 指令缺失时是否弹窗补齐；closeEvent 等无人值守路径
            传 False 只做静默拒绝，不在退出过程中弹模态框
        :return: True 表示已落轮或本轮无需落轮；False 表示因缺少任务指令被拒绝落轮，
            调用方必须保持 steps_data 原样并中止后续的切轮/写盘动作
        """
        if not self.steps_data or self._current_round_saved:
            return True  # 无步骤或已落轮，不构成拒绝
        if not (self.task_instruction or "").strip():
            if not prompt_instruction or not self._prompt_missing_instruction():
                return False
        trajectory = []
        all_coords = []
        # 2.7（B42）落轮必须存 action 的深拷贝：早前直接把 steps_data 里的活对象塞进
        # rounds，于是 rounds 与本轮数据共享同一个 dict，任何对步骤 action 的原地改写
        # （含嵌套的 coordinate 列表）都会回写到已落轮、甚至已交付的轮次上。
        # coords 侧无需再包一层：_build_coords_entry 内对 vertices 已做 list() 复制，
        # 且只读 action_data，不写回。
        for i, step_data in enumerate(self.steps_data):
            # 下游字段（CoT/active_window/ui_tree_segment）可能由草稿透传，
            # 有值则保留，无值维持空串，不再无条件硬编码覆盖
            step_obs = step_data.get("observation")
            if isinstance(step_obs, dict):
                active_window = step_obs.get("active_window", "")
                ui_tree_segment = step_obs.get("ui_tree_segment", "")
            else:
                active_window = step_data.get("active_window", "")
                ui_tree_segment = step_data.get("ui_tree_segment", "")
            trajectory.append({
                "step": i,
                "intent": step_data["intent"],
                "CoT": step_data.get("CoT", ""),
                "observation": {
                    "screenshot": step_data["screenshot"],
                    "active_window": active_window,
                    "ui_tree_segment": ui_tree_segment
                },
                "actions": [copy.deepcopy(step_data["action_data"])]
            })
            coords_entry = self._build_coords_entry(step_data["action_data"], step_data.get("vertices"))
            coords_entry["step"] = i
            all_coords.append(coords_entry)
        self.rounds.append({
            "instruction": self.task_instruction,
            "trajectory": trajectory,
            "coords": all_coords
        })
        self._current_round_saved = True
        # 2.1（B20a）落轮后必须消费掉当前轮，口径对齐 iOS _save_current_round_to_list。
        # 早前只置 _current_round_saved 不清 steps_data，叠加 _write_draft_now 从
        # rounds[-1] 重建草稿，于是续采时旧轮步骤被当成“未结束步骤”复活，
        # 再落轮就变成 rounds = [R1(旧步), R2(旧步 + 新步)]：旧轮重复、跨轮截图
        # 重复引用、R2 还沿用 R1 的 instruction，已交付数据被静默污染。
        self.steps_data = []
        self.coords_data = []
        self.current_step = 0
        self._missing_cache = {}
        self._insert_after_index = None
        self._reset_for_next_step()
        self.sidebar.rebuild_items()
        # 轮次边界立即把 rounds 变化落到草稿（不等防抖），断点续采不丢已确认轮次
        self._write_draft_now()
        return True

    def _save_all_rounds_to_file(self):
        """将全部轮次写入最终 JSON 和 coords JSON，并删除草稿。

        :return: True 表示最终 JSON 写入成功（草稿已删除）；False 表示无轮次或写入失败
        """
        if not self.rounds:
            return False
        json_data = self.data_manager.create_initial_json_structure(
            self.rounds[0].get("instruction", ""), self.screen_info, self.app_type
        )
        json_data["messages"] = []
        all_coords = []
        for round_index, round_data in enumerate(self.rounds):
            json_data["messages"].append({
                "role": "user",
                "instruction": round_data["instruction"]
            })
            json_data["messages"].append({
                "role": "assistant",
                "trajectory": round_data["trajectory"]
            })
            # 4.2（B4/B18）序列化边界注入 round（对齐 iOS _save_all_rounds_to_file）：
            # 轮内 step 下标每轮都从 0 起重编，扁平 coords 文件里 (step, action) 无法
            # 唯一归属；早前不写 round 时读取只能靠「step 变小则切段」，只要有一轮一个
            # 坐标步都没有就整段错位，把顶点配到别的轮次上。只加在写盘副本上，
            # rounds[r]["coords"] 保持原样，避免轮次变动后留下陈旧的 round 值。
            for coord in round_data.get("coords") or []:
                if isinstance(coord, dict):
                    coord = {**coord, "round": round_index}
                all_coords.append(coord)
        json_path = self.data_manager.save_json_data(json_data, self.gui_number)
        if all_coords:
            self.data_manager.save_coords_json(all_coords, self.gui_number)
        # 最终数据成功落盘后删除草稿，避免“已完成任务”反复出现在续采入口
        if json_path:
            self.draft_timer.stop()
            self.data_manager.delete_draft(self.gui_number)
            self.status_label.setText(f"所有轮次已保存到 gui_{self.gui_number}/")
            return True
        self.status_label.setText(f"所有轮次已保存到 gui_{self.gui_number}/（JSON 写入失败）")
        return False

    def _reset_workspace_after_cancel(self):
        """已落轮后用户放弃开启新轮：把工作区清成空白起点。

        关键在复位 _current_round_saved：该标志为 True 时
        _save_current_round_to_list 直接早退，用户接着采集的整轮会被静默丢弃。
        当前轮已入 rounds，故步骤/坐标/缺填缓存/插入锚点一并清空。
        """
        self._current_round_saved = False
        self.current_step = 0
        # B14：上一轮已随 answer 落轮并被消费，取消新轮后不得继续持有旧指令，
        # 否则用户接着采集的整轮会被静默挂到上一条指令上（落轮前的强校验是第二层
        # 安全网，两者缺一都会重现指令错乱）。
        self.task_instruction = ""
        self.steps_data = []
        self.coords_data = []
        self._missing_cache = {}
        self._insert_after_index = None
        self._reset_for_next_step()
        self.sidebar.rebuild_items()
        self.schedule_draft_save()
        self.status_label.setText("已取消新任务 - 可继续截图标注")

    def apply_next_round_instruction(self, text, ok):
        """轮次边界追问下一条指令的落地入口（新轮与断点续采共用）。

        取消分支不能只当“什么都没发生”：此时 _current_round_saved 仍为 True，
        而 _save_current_round_to_list 靠该标志早退，用户接着采集的整轮会被
        静默丢弃（B19）。

        :return: True 已开启新轮；False 取消，工作区已回到空白可采集状态
        """
        instruction = (text or "").strip()
        if ok and instruction:
            self.task_instruction = instruction
            self._current_round_saved = False
            self.status_label.setText(f"新任务开始 - 指令: {self.task_instruction} - 请截图")
            return True
        self._reset_workspace_after_cancel()
        return False

    def _start_new_round(self, from_answer=False):
        # 门闩回调已进场，切轮窗口结束，恢复采集/编辑入口（B2）
        self._round_transition_pending = False
        dialog = QInputDialog(self)
        dialog.setWindowTitle("新任务指令")
        dialog.setLabelText(f"请输入【{self.app_name}】的新任务指令：")
        dialog.setTextEchoMode(QLineEdit.Normal)
        dialog.setTextValue("")
        dialog.move(dialog.x() + 150, dialog.y())
        ok = dialog.exec_()
        new_instruction = dialog.textValue()
        if ok and new_instruction.strip():
            self.task_instruction = new_instruction.strip()
            self.current_step = 0
            self.steps_data = []
            self.coords_data = []
            self.screenshot_cache = None
            self._current_screenshot_filename = None
            self._current_screenshot_filepath = None
            self._current_round_saved = False
            self._cancel_swipe_measurement()
            self._cancel_scroll_measurement()
            self._screenshot_in_progress = False
            self.overlay.clear_rect()
            self.screenshot_canvas.clear_screenshot()
            self._clear_inputs()
            self._update_navigation_buttons()
            self._update_step_label()
            # 新一轮：缺填缓存失效、侧栏清空重建、立即调度草稿
            self._missing_cache = {}
            self.sidebar.rebuild_items()
            self.schedule_draft_save()
            self.status_label.setText(f"新任务开始 - 指令: {self.task_instruction} - 请截图")
        else:
            if from_answer:
                # 取消新任务：当前轮次已保存到 rounds；重置工作区，
                # 避免 _current_round_saved 仍为 True 导致后续步骤被静默丢弃
                self._reset_workspace_after_cancel()
            else:
                self.close()

    def _start_new_task(self):
        dialog = QInputDialog(self)
        dialog.setWindowTitle("新任务指令")
        dialog.setLabelText(f"请输入【{self.app_name}】的新任务指令：")
        dialog.setTextEchoMode(QLineEdit.Normal)
        dialog.setTextValue("")
        dialog.move(dialog.x() + 150, dialog.y())
        ok = dialog.exec_()
        new_instruction = dialog.textValue()
        if ok and new_instruction.strip():
            self.task_instruction = new_instruction.strip()
            # 新任务起点：清除完成标记与交付门闩（任何入口进入新任务都不得残留）
            self._task_completed = False
            self._round_transition_pending = False
            self.current_step = 0
            self.steps_data = []
            self.coords_data = []
            self.rounds = []
            self.screenshot_cache = None
            self._current_screenshot_filename = None
            self._current_screenshot_filepath = None
            self._current_round_saved = False
            self._screenshot_in_progress = False
            self.overlay.clear_rect()
            self.screenshot_canvas.clear_screenshot()
            self._clear_inputs()
            self._update_navigation_buttons()
            self._update_step_label()
            self.gui_number = self.data_manager.get_next_gui_number()
            self.gui_dir = self.data_manager.create_gui_directory(self.gui_number)
            # 新任务：缺填缓存失效、侧栏清空重建（新 gui 编号暂不写空草稿）
            self._missing_cache = {}
            self.sidebar.rebuild_items()
            self.status_label.setText(f"新任务已开始 - 指令: {self.task_instruction} - 请截图")
            self.btn_screenshot.setEnabled(True)
            self.btn_next.setEnabled(True)

    def closeEvent(self, event):
        # 弹窗残留会遮挡编辑态的自动写回，先关掉再走后续分支
        if getattr(self, "_relabel_dialog", None) is not None:
            try:
                self._relabel_dialog.close()
            except RuntimeError:
                pass
            self._relabel_dialog = None
        # 编辑已完成任务：关闭时自动写回最终 JSON，全程不碰草稿
        if self._edit_mode:
            if not self._edit_final_saved:
                try:
                    self.save_edited_round(silent=True)
                except Exception as e:
                    print(f"[关闭] 编辑保存异常: {e}")
            # 进入编辑时主窗口已被隐藏，关闭编辑器后必须恢复，否则应用没有任何可见窗口
            if self._init_window is not None:
                self._init_window.show()
                self._init_window.raise_()
                self._init_window.activateWindow()
            self.overlay.close()
            self.scrcpy_widget.close()
            super().closeEvent(event)
            return
        # 关闭前保存数据
        # 注意：中途关闭只写草稿，不写最终 JSON，不删除草稿
        # 最终 JSON 写入 + 草稿删除 仅在 _finish_task（任务完成按钮）中触发
        try:
            # 正常完成后的关闭：跳过草稿保存（草稿已删除，最终 JSON 已写入）
            if getattr(self, '_task_completed', False):
                print(f"[关闭] 任务已正常完成，跳过草稿保存")
            else:
                self._save_current_to_steps()
                # 注：_save_current_round_to_list 内部已调 _write_draft_now，但 closeEvent 外层再调一次
                # 是安全网——覆盖 steps_data 已空但 rounds 非空的边界态（轮次刚保存、current_step 已重置为 0）
                if self.steps_data and not self._current_round_saved:
                    # 关闭路径不弹模态框：缺指令就静默拒绝落轮，steps_data 保留、
                    # 随后仍会写草稿，下次续采时数据不丢（B14）
                    self._save_current_round_to_list(prompt_instruction=False)
                if self.gui_number:
                    # 关闭时写一次最终草稿，确保下次启动可续采
                    self._write_draft_now()
                    print(f"[关闭] 草稿已保存到 gui_{self.gui_number}/")
        except Exception as e:
            print(f"[关闭] 保存数据异常: {e}")
        self.overlay.close()
        self.scrcpy_widget.close()
        super().closeEvent(event)
