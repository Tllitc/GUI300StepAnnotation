#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
截图捕获模块
负责全屏截图和区域选择功能
"""

import sys
from PyQt5.QtWidgets import QApplication, QWidget, QRubberBand
from PyQt5.QtCore import Qt, QRect, pyqtSignal, QSize
from PyQt5.QtGui import QPainter, QPen, QColor, QPixmap, QScreen, QFont


class ScreenshotCaptureWindow(QWidget):
    """截图捕获窗口 - 用于用户拉框或点击选择区域"""
    
    # 信号：当用户完成选择时发出，包含截图和坐标信息
    capture_completed = pyqtSignal(object, object, tuple, str)  # (original_pixmap, marked_pixmap, (x, y, width, height), screenshot_type)
    
    def __init__(self, background_pixmap=None):
        super().__init__()
        
        # 背景图模式：给定截图时不抓屏，直接在该图上重新拉框（None = 原有全屏抓屏行为）
        self.background_pixmap = background_pixmap
        
        # 设置为全屏、无边框、置顶。
        # macOS 上必须使用 Qt.Tool：Qt 会据此创建 QNSPanel（NSPanel 子类），
        # 既能成为 key 窗口接收鼠标/键盘事件，又可附加非激活面板风格位，
        # 避免截图窗口把 Python 工具激活到前台（吞掉首次点击、菜单栏变成工具菜单）。
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setFocusPolicy(Qt.StrongFocus)
        
        # 获取主屏幕
        screen = QApplication.primaryScreen()
        self.screen_geometry = screen.geometry()
        
        # 设置窗口大小为整个屏幕（背景图模式的窗口几何由 _setup_background 接管）
        if self.background_pixmap is None:
            self.setGeometry(self.screen_geometry)
        
        # 截图相关变量
        self.full_pixmap = None
        self.scale_factor = 1.0
        self.rubber_band = QRubberBand(QRubberBand.Rectangle, self)
        self.origin = None
        self.current_rect = None
        
        # 鼠标状态
        self.is_selecting = False
        self.click_only = False  # 是否为纯点击（不拉框）
        
        # 选择状态
        self.has_selection = False  # 是否已完成选择
        self.selection_rect = None  # 保存的选区
        self.selection_type = None  # 保存的选择类型

        # NSWindow 层级是否已提升（防止 showEvent 重复执行）
        self._level_raised = False
        
        # 双框选择支持（用于拖拽动作）
        self.first_rect = None  # 第一个框
        self.second_rect = None  # 第二个框
        self.box_count = 0  # 已选择的框数量
        
        # 设置鼠标指针为十字
        self.setCursor(Qt.CrossCursor)

        # 捕获截图 / 装载背景图
        if self.background_pixmap is not None:
            self._setup_background()
        else:
            self.capture_screen()

    def _setup_background(self):
        """原图重新拉框模式：不抓屏，把背景设为指定截图，窗口尺寸 = 缩放后的显示尺寸"""
        avail = QApplication.primaryScreen().availableGeometry()
        pm = self.background_pixmap
        ratio = min(avail.width() / pm.width(), avail.height() / pm.height(), 1.0)
        disp_w = max(1, int(pm.width() * ratio))
        disp_h = max(1, int(pm.height() * ratio))
        self.full_pixmap = pm.scaled(disp_w, disp_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # 逻辑坐标系与显示图尺寸一致，offset 恒为 0
        self.screen_geometry = QRect(0, 0, self.full_pixmap.width(), self.full_pixmap.height())
        self.setGeometry(
            avail.x() + (avail.width() - self.full_pixmap.width()) // 2,
            avail.y() + (avail.height() - self.full_pixmap.height()) // 2,
            self.full_pixmap.width(), self.full_pixmap.height(),
        )
        # 原图像素 / 显示图逻辑像素 —— 与抓屏模式同口径（乘 sf 得原图像素）
        self.scale_factor = pm.width() / self.full_pixmap.width()
        self.setStyleSheet("background-color: rgba(0, 0, 0, 180);")

    def capture_screen(self):
        """捕获整个屏幕"""
        screen = QApplication.primaryScreen()
        self.full_pixmap = screen.grabWindow(0)
        
        # 计算物理像素与逻辑像素的缩放比例（macOS Retina 屏幕）
        # 截图分辨率（物理像素）与屏幕逻辑分辨率的比值
        self.scale_factor = self.full_pixmap.width() / self.screen_geometry.width() if self.screen_geometry.width() > 0 else 1.0
        
        # 设置背景为半透明遮罩
        self.setStyleSheet("background-color: rgba(0, 0, 0, 100);")
    
    def showEvent(self, event):
        """窗口显示时自动获取键盘焦点"""
        super().showEvent(event)
        self.setFocus()
        self.activateWindow()
        # 提升窗口层级至 macOS 菜单栏之上，使顶部菜单栏区域也可以拉框。
        # 背景图（重新拉框）模式是居中的普通弹窗，无需压过系统菜单栏，跳过提升。
        if self.background_pixmap is None:
            self._raise_window_above_system_ui()

    def _raise_window_above_system_ui(self):
        """将截图面板提升到 macOS 主菜单栏/Dock 之上，并配置为非激活面板。

        - Qt 的 WindowStaysOnTopHint 仅对应 NSFloatingWindowLevel(3)，
          低于 NSMainMenuWindowLevel(24)，顶部菜单栏会截获鼠标事件导致无法拉框，
          因此将 NSWindow level 设为 NSScreenSaverWindowLevel(1000)。
        - 附加 NSNonactivatingPanelMask：面板可成为 key 窗口但不把所属 App
          切到前台——首次点击即可拉框，且系统菜单栏保持为被截图 App。
          （依赖窗口类型为 Qt.Tool → 原生 QNSPanel。）
        - NSPanel 默认在所属 App 停用时隐藏，需关闭 hidesOnDeactivate。
        任何桥接失败都只告警并降级为原有行为，不影响截图流程。
        """
        if sys.platform != 'darwin' or self._level_raised:
            return
        # offscreen 等非 cocoa 平台插件下 winId() 不是 NSView，直接跳过
        if QApplication.platformName() != 'cocoa':
            return
        try:
            import objc
            from AppKit import (
                NSScreenSaverWindowLevel,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorStationary,
                NSWindowCollectionBehaviorFullScreenAuxiliary,
            )
            # 非激活面板风格位（新 SDK 名称与旧名称兼容）
            try:
                from AppKit import NSWindowStyleMaskNonactivatingPanel as _NONACTIVATING
            except ImportError:
                from AppKit import NSNonactivatingPanelMask as _NONACTIVATING

            # PyQt5 中 winId() 返回原生 NSView 指针，经由它取得 NSWindow
            ns_view = objc.objc_object(c_void_p=int(self.winId()))
            ns_window = ns_view.window()
            if ns_window is None:
                return

            # 非激活：成为 key 窗口但不抢占前台 App（不吞首次点击、不切换菜单栏）
            ns_window.setStyleMask_(int(ns_window.styleMask()) | int(_NONACTIVATING))
            # 所属 App 停用时不自动隐藏面板
            ns_window.setHidesOnDeactivate_(False)
            ns_window.setLevel_(NSScreenSaverWindowLevel)
            ns_window.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorStationary
                | NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            # 不激活 App 的前提下置于最前并成为 key 窗口（鼠标/键盘立即可达）
            ns_window.orderFrontRegardless()
            ns_window.makeKeyWindow()
            self._level_raised = True
        except Exception as e:
            print(f"⚠️ 提升截图窗口层级失败，顶部菜单栏区域可能无法拉框: {e}")
        
    def paintEvent(self, event):
        """绘制事件 - 显示截图和选区"""
        painter = QPainter(self)
        
        # 绘制全屏截图
        if self.full_pixmap:
            painter.drawPixmap(0, 0, self.full_pixmap)
        
        # 绘制半透明遮罩（除了选中区域）
        if self.current_rect or self.has_selection:
            # 创建遮罩
            mask = QPixmap(self.full_pixmap.size())
            mask.fill(QColor(0, 0, 0, 100))
            
            # 清除选中区域的遮罩
            painter_mask = QPainter(mask)
            painter_mask.setCompositionMode(QPainter.CompositionMode_Clear)
            
            # 清除第一个框的区域
            if self.first_rect:
                x, y, w, h = self.first_rect
                painter_mask.fillRect(QRect(x, y, w, h), Qt.transparent)
            
            # 清除第二个框的区域
            if self.second_rect:
                x, y, w, h = self.second_rect
                painter_mask.fillRect(QRect(x, y, w, h), Qt.transparent)
            
            # 如果没有双框，使用原有的单框逻辑
            if not self.first_rect and not self.second_rect:
                if self.has_selection and self.selection_rect:
                    x, y, w, h = self.selection_rect
                    painter_mask.fillRect(QRect(x, y, w, h), Qt.transparent)
                elif self.current_rect:
                    painter_mask.fillRect(self.current_rect, Qt.transparent)
            
            painter_mask.end()
            
            painter.drawPixmap(0, 0, mask)
            
            # 绘制选区边框
            pen = QPen(QColor(255, 0, 0), 2)
            painter.setPen(pen)
            
            # 绘制第一个框（已完成的）
            if self.first_rect:
                x, y, w, h = self.first_rect
                painter.drawRect(QRect(x, y, w, h))
            
            # 绘制第二个框（已完成的）
            if self.second_rect:
                x, y, w, h = self.second_rect
                painter.drawRect(QRect(x, y, w, h))
            
            # 绘制当前正在拉的框（橡皮筋）
            if self.current_rect and not self.click_only:
                painter.drawRect(self.current_rect)
            
            # 如果没有双框，使用原有的单框逻辑
            if not self.first_rect and not self.second_rect:
                if self.has_selection and self.selection_rect:
                    x, y, w, h = self.selection_rect
                    painter.drawRect(QRect(x, y, w, h))
                elif self.current_rect and not self.click_only:
                    painter.drawRect(self.current_rect)
        
        # 背景图模式：顶部操作提示
        if self.background_pixmap is not None:
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Helvetica Neue", 11, QFont.Bold))
            painter.drawText(QRect(0, 4, self.width(), 26), Qt.AlignHCenter,
                             "在原图上重新拉框：拖框选区 → Cmd+S 确认 → Esc 取消/清空重画")
        
        super().paintEvent(event)
    
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            self.origin = event.pos()
            self.is_selecting = True
            
            # 判断是点击还是开始拉框
            self.click_only = True
            
            # 初始化橡皮筋
            self.rubber_band.setGeometry(QRect(self.origin, QSize()))
            self.rubber_band.show()
            
    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if self.is_selecting and self.origin:
            current = event.pos()
            
            # 如果移动距离超过阈值，认为是拉框而不是点击
            if abs(current.x() - self.origin.x()) > 5 or abs(current.y() - self.origin.y()) > 5:
                self.click_only = False
            
            if not self.click_only:
                # 更新橡皮筋矩形
                rect = QRect(self.origin, current).normalized()
                self.current_rect = rect
                self.rubber_band.setGeometry(rect)
                self.update()
    
    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.LeftButton and self.is_selecting:
            self.is_selecting = False
            
            if not self.click_only:
                if self.current_rect and self.current_rect.width() > 5 and self.current_rect.height() > 5:
                    self.handle_selection(self.current_rect, "drag")
            
            self.rubber_band.hide()
            self.current_rect = None
            self.update()
    
    def handle_selection(self, rect, selection_type):
        """处理用户选择 - 不关闭窗口，等待 Ctrl+S 确认"""
        # 存储逻辑像素坐标（widget 坐标系），发信号时再转换为物理像素
        x = rect.x()
        y = rect.y()
        width = rect.width()
        height = rect.height()
        
        rect_info = (x, y, width, height)
        
        # 记录第一个框或第二个框
        if self.box_count == 0:
            self.first_rect = rect_info
            self.box_count = 1
            self.has_selection = True
            self.selection_rect = rect_info
            self.selection_type = selection_type
        elif self.box_count == 1:
            self.second_rect = rect_info
            self.box_count = 2
            # 双框模式，更新选择类型为 drag
            self.selection_type = "drag"
        
        # 隐藏橡皮筋
        self.rubber_band.hide()
        self.current_rect = None
        
        # 更新显示（绘制选区标记）
        self.update()
    
    def confirm_selection(self):
        """确认选择并发送信号（坐标以截图物理分辨率为基准）"""
        sf = self.scale_factor
        
        if not self.has_selection or not self.selection_rect:
            if self.background_pixmap is not None:
                # 原图模式：空选区等同于取消，禁止退化成"全屏截图"
                self.capture_completed.emit(None, None, (), "cancelled")
                self.close()
                return
            if self.full_pixmap:
                original_pixmap = QPixmap(self.full_pixmap)
                marked_pixmap = QPixmap(self.full_pixmap)
                self.capture_completed.emit(
                    original_pixmap,
                    marked_pixmap,
                    (),
                    "fullscreen"
                )
            self.close()
            return
        
        if self.box_count == 2 and self.first_rect and self.second_rect:
            # 逻辑坐标（用于在 marked_pixmap 上绘制，因为高 DPI 下 QPainter 使用逻辑坐标）
            l_fr_x, l_fr_y, l_fr_w, l_fr_h = self.first_rect
            l_sr_x, l_sr_y, l_sr_w, l_sr_h = self.second_rect
            
            # 逻辑中心点
            l_first_center_x = l_fr_x + l_fr_w // 2
            l_first_center_y = l_fr_y + l_fr_h // 2
            l_second_center_x = l_sr_x + l_sr_w // 2
            l_second_center_y = l_sr_y + l_sr_h // 2
            
            # 物理像素坐标（用于 signal 发送给坐标输入框）
            physical_first_rect = (
                int(l_fr_x * sf), int(l_fr_y * sf),
                int(l_fr_w * sf), int(l_fr_h * sf)
            )
            physical_second_rect = (
                int(l_sr_x * sf), int(l_sr_y * sf),
                int(l_sr_w * sf), int(l_sr_h * sf)
            )
            
            if self.full_pixmap:
                original_pixmap = QPixmap(self.full_pixmap)
                marked_pixmap = QPixmap(self.full_pixmap)
                
                painter = QPainter(marked_pixmap)
                pen = QPen(QColor(255, 0, 0), 3)
                painter.setPen(pen)
                
                # 在 pixmap 上绘制时使用逻辑坐标（高 DPI 下 QPainter 坐标空间是逻辑像素）
                painter.drawRect(QRect(l_fr_x, l_fr_y, l_fr_w, l_fr_h))
                painter.drawRect(QRect(l_sr_x, l_sr_y, l_sr_w, l_sr_h))
                
                # 绘制箭头连接两个框
                import math
                angle = math.atan2(l_second_center_y - l_first_center_y,
                                   l_second_center_x - l_first_center_x)
                arrow_length = 15
                arrow_angle = math.pi / 6
                
                x1 = l_second_center_x - arrow_length * math.cos(angle - arrow_angle)
                y1 = l_second_center_y - arrow_length * math.sin(angle - arrow_angle)
                x2 = l_second_center_x - arrow_length * math.cos(angle + arrow_angle)
                y2 = l_second_center_y - arrow_length * math.sin(angle + arrow_angle)
                
                painter.drawLine(l_first_center_x, l_first_center_y,
                                 l_second_center_x, l_second_center_y)
                painter.drawLine(l_second_center_x, l_second_center_y, int(x1), int(y1))
                painter.drawLine(l_second_center_x, l_second_center_y, int(x2), int(y2))
                
                painter.end()
                
                dual_rect_info = (physical_first_rect, physical_second_rect)
                self.capture_completed.emit(
                    original_pixmap,
                    marked_pixmap, 
                    dual_rect_info,
                    "drag"
                )
            
            self.close()
        else:
            # 单框模式
            lx, ly, lw, lh = self.selection_rect  # 逻辑坐标
            # 物理像素坐标（用于 signal 发送给坐标输入框）
            physical_rect_info = (
                int(lx * sf), int(ly * sf),
                int(lw * sf), int(lh * sf)
            )
            
            if self.full_pixmap:
                original_pixmap = QPixmap(self.full_pixmap)
                marked_pixmap = QPixmap(self.full_pixmap)
                
                painter = QPainter(marked_pixmap)
                
                if self.selection_type == "click":
                    # 在 pixmap 上绘制时使用逻辑坐标（高 DPI 下 QPainter 坐标空间是逻辑像素）
                    center_x = lx + lw // 2
                    center_y = ly + lh // 2
                    
                    pen = QPen(QColor(255, 0, 0), 3)
                    painter.setPen(pen)
                    
                    cross_size = 20
                    painter.drawLine(center_x - cross_size, center_y, center_x + cross_size, center_y)
                    painter.drawLine(center_x, center_y - cross_size, center_x, center_y + cross_size)
                    
                    painter.setBrush(QColor(255, 0, 0))
                    painter.drawEllipse(center_x - 5, center_y - 5, 10, 10)
                    
                else:
                    pen = QPen(QColor(255, 0, 0), 3)
                    painter.setPen(pen)
                    # 在 pixmap 上绘制时使用逻辑坐标
                    painter.drawRect(QRect(lx, ly, lw, lh))
                
                painter.end()
                
                self.capture_completed.emit(
                    original_pixmap,
                    marked_pixmap, 
                    physical_rect_info,
                    self.selection_type
                )
            
            self.close()
    
    def keyPressEvent(self, event):
        """键盘事件 - ESC 取消/清除，Ctrl+S(Meta+S) 确认"""
        if event.key() == Qt.Key_Escape:
            if self.box_count > 0:
                # 如果有选区，清除所有选区，允许重新选择
                self.has_selection = False
                self.selection_rect = None
                self.selection_type = None
                self.first_rect = None
                self.second_rect = None
                self.box_count = 0
                self.current_rect = None
                self.rubber_band.hide()
                self.update()
            else:
                # 如果没有选区，取消整个截图
                self.capture_completed.emit(None, None, (), "cancelled")
                self.close()
        elif event.key() == Qt.Key_S and (event.modifiers() & Qt.MetaModifier):
            self.confirm_selection()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ScreenshotCaptureWindow()
    window.show()
    sys.exit(app.exec_())
