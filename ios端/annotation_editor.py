#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iOS 标注编辑器
截图展示、拉框标注采标区域、动作参数编辑
"""

import math
import os
import re
import copy
import time
from collections import OrderedDict
from datetime import datetime

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QComboBox, QLineEdit,
                             QScrollArea, QSplitter, QFrame, QMessageBox,
                             QInputDialog, QGroupBox, QFormLayout, QTextEdit,
                             QDialog, QListWidget, QListWidgetItem, QSpinBox,
                             QListView)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRect, QSize
from PyQt5.QtGui import (QPixmap, QImage, QPainter, QPen, QColor, QFont,
                         QFontMetrics, QIcon)
from screenshot_capture import IOSScreenCapture
from data_manager import DataManager


# iOS 动作类型定义
IOS_ACTIONS = [
    ("click", "点击 (click)"),
    ("long_press", "长按 (long_press)"),
    ("swipe", "滑动 (swipe)"),
    ("drag", "拖拽 (drag)"),
    ("scroll", "滚动 (scroll)"),
    ("type", "输入文本 (type)"),
    ("system_button", "系统按钮 (system_button)"),
    ("answer", "回答问题 (answer)"),
    ("answer_terminate", "回答问题并结束 (answer+terminate)"),
    ("wait", "等待 (wait)"),
    ("open_app", "打开App (open_app)"),
    ("open_url", "打开链接 (open_url)"),
    ("terminate", "任务完成 (terminate)"),
]

# 需要坐标参数的动作
COORD_ACTIONS = {"click", "long_press", "swipe", "drag", "scroll", "type"}
# 需要终点坐标的动作（swipe 与 drag 共用滑动测量流程）
SWIPE_ACTIONS = {"swipe", "drag"}
# 需要滚动测量的动作
SCROLL_ACTIONS = {"scroll"}
# 需要文本参数的动作
TEXT_ACTIONS = {"type", "answer", "answer_terminate", "open_app", "open_url"}
# 需要时间参数的动作
TIME_ACTIONS = {"long_press", "wait"}
# 需要按钮参数的动作
BUTTON_ACTIONS = {"system_button"}
SYSTEM_BUTTONS = [
    "Back", "Home", "App_switch", "Power",
    "Volume_up", "Volume_down", "Volume_mute",
    "Notifications", "Quick_settings"
]


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
    if not math.isfinite(value):
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
    if action not in COORD_ACTIONS:
        return None, f"动作 {action!r} 无需坐标"

    if action in SWIPE_ACTIONS:
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


class ScreenshotCanvas(QFrame):
    """截图显示区域，支持鼠标拖拽绘制矩形框"""

    rect_drawn = pyqtSignal(int, int, int, int)  # left, top, right, bottom

    def __init__(self):
        super().__init__()
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.setMinimumSize(400, 400)
        self.setStyleSheet("background-color: #e0e0e0;")
        self.setMouseTracking(True)

        self.pixmap = None
        self.scaled_pixmap = None
        self._drawing = False
        self._start_point = None
        self._current_rect = None  # 当前绘制的矩形（画布坐标）
        self._saved_rect = None    # 上一次确认的矩形

        # 窗口尺寸变化时延迟缩放，避免拖拽分栏过程中频繁重绘
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(250)
        self._resize_timer.timeout.connect(self._on_resize_debounced)

    def set_pixmap(self, pixmap):
        """设置截图图片"""
        self.pixmap = pixmap
        self._saved_rect = None
        self._current_rect = None
        self._scale_pixmap()
        self.update()

    def restore_vertices(self, vertices):
        """根据原始坐标顶点恢复绿色矩形框（用于步骤切换时恢复标注框）"""
        if self.pixmap is None or self.scaled_pixmap is None:
            return
        if not vertices or len(vertices) != 4:
            return
        # 将原始坐标变换回画布坐标
        scale = self.scaled_pixmap.width() / self.pixmap.width()
        left = int(vertices[0] * scale) + self._offset_x
        top = int(vertices[1] * scale) + self._offset_y
        right = int(vertices[2] * scale) + self._offset_x
        bottom = int(vertices[3] * scale) + self._offset_y
        self._saved_rect = QRect(left, top, right - left, bottom - top)
        self.update()

    def _scale_pixmap(self):
        """将 pixmap 缩放以适应画布大小"""
        if self.pixmap is None:
            self.scaled_pixmap = None
            return
        cw = self.width()
        ch = self.height()
        pw = self.pixmap.width()
        ph = self.pixmap.height()
        if pw <= 0 or ph <= 0:
            self.scaled_pixmap = None
            return
        ratio = min(cw / pw, ch / ph)
        nw = int(pw * ratio)
        nh = int(ph * ratio)
        self.scaled_pixmap = self.pixmap.scaled(nw, nh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._offset_x = (cw - nw) // 2
        self._offset_y = (ch - nh) // 2

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 250ms 防抖：拖拽分栏/窗口缩放期间不逐帧重缩放
        self._resize_timer.start()

    def _on_resize_debounced(self):
        """尺寸稳定后重新缩放并重绘（仍使用当前步持有的原图，不产生额外磁盘 IO）"""
        self._scale_pixmap()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)

        if self.scaled_pixmap:
            painter.drawPixmap(self._offset_x, self._offset_y, self.scaled_pixmap)

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

        if self.pixmap is None:
            painter.setPen(QColor(120, 120, 120))
            painter.setFont(QFont("Microsoft YaHei", 14))
            painter.drawText(self.rect(), Qt.AlignCenter, '点击 [给下一步截图(Ctrl+Q)] 按钮获取iPhone截图')

    def _canvas_to_original(self, canvas_rect):
        """将画布坐标矩形变换回原始图片坐标"""
        if self.pixmap is None or self.scaled_pixmap is None:
            return None
        scale = self.pixmap.width() / self.scaled_pixmap.width()
        left = int((canvas_rect.x() - self._offset_x) * scale)
        top = int((canvas_rect.y() - self._offset_y) * scale)
        right = int((canvas_rect.right() - self._offset_x) * scale)
        bottom = int((canvas_rect.bottom() - self._offset_y) * scale)
        # 限制在图片范围内
        pw = self.pixmap.width()
        ph = self.pixmap.height()
        left = max(0, min(left, pw))
        top = max(0, min(top, ph))
        right = max(0, min(right, pw))
        bottom = max(0, min(bottom, ph))
        return left, top, right, bottom

    def _clamp_to_canvas(self, rect):
        """将矩形限制在图片区域内"""
        if self.scaled_pixmap is None:
            return rect
        x = max(self._offset_x, rect.x())
        y = max(self._offset_y, rect.y())
        r = min(self._offset_x + self.scaled_pixmap.width(), rect.right())
        b = min(self._offset_y + self.scaled_pixmap.height(), rect.bottom())
        return QRect(x, y, r - x, b - y)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.scaled_pixmap:
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

    def clear_rect(self):
        """清除绘制的矩形"""
        self._saved_rect = None
        self._current_rect = None
        self.update()


class ReLabelDialog(QDialog):
    """「在原图上重新拉框」弹窗：编辑已完成任务时直接在磁盘原截图上重画标注框。

    复用 ScreenshotCanvas 的拖框 / 原图像素反算能力；只调用 set_pixmap 而**绝不调用**
    restore_vertices，因此打开即干净背景（不叠加旧框），落实「直接清空旧框」的交互约定。
    """

    rect_confirmed = pyqtSignal(int, int, int, int)  # left, top, right, bottom（原图像素）

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
        self.canvas = ScreenshotCanvas()
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

        # 只喂背景图：ScreenshotCanvas.set_pixmap 内部已清空 _saved_rect/_current_rect
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


def action_cn_name(action_en):
    """根据动作英文 key 反查中文名"""
    for value, label in IOS_ACTIONS:
        if value == action_en:
            return label
    return action_en or "未知动作"


class StepListItemWidget(QFrame):
    """侧栏中的单个步骤条目：序号、动作名、缺项提示、缩略图"""

    clicked = pyqtSignal(int)
    THUMB_SIZE = QSize(200, 112)

    def __init__(self, index, parent=None):
        super().__init__(parent)
        self._index = index
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("stepListItem")
        self.setStyleSheet(
            "#stepListItem { border: 1px solid #cfd8dc; border-radius: 6px; background: white; }"
        )
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        self.number_label = QLabel()
        self.number_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: #2e7d32; font-size: 12px;")
        top_row.addWidget(self.number_label)
        top_row.addStretch()
        top_row.addWidget(self.status_label)
        layout.addLayout(top_row)

        self.thumb_label = QLabel("暂无截图")
        self.thumb_label.setFixedSize(202, 114)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("background-color: #eceff1; color: #78909c;")
        layout.addWidget(self.thumb_label)

        self.action_label = QLabel()
        self.action_label.setWordWrap(True)
        self.action_label.setStyleSheet("font-size: 12px; color: #37474f;")
        layout.addWidget(self.action_label)

        self.missing_label = QLabel()
        self.missing_label.setWordWrap(True)
        self.missing_label.setStyleSheet("color: #c62828; font-size: 12px;")
        self.missing_label.hide()
        layout.addWidget(self.missing_label)

        self.set_index(index)

    def set_index(self, index):
        self._index = index
        self.number_label.setText(f"第 {index + 1} 步")

    def set_current(self, is_current):
        """当前正在编辑的步骤用蓝色粗边框高亮"""
        if is_current:
            self.setStyleSheet(
                "#stepListItem { border: 2px solid #1e88e5; border-radius: 6px; background: #e3f2fd; }"
            )
            self.status_label.setText("● 编辑中")
            self.status_label.setStyleSheet("color: #1565c0; font-size: 12px;")
        else:
            self.setStyleSheet(
                "#stepListItem { border: 1px solid #cfd8dc; border-radius: 6px; background: white; }"
            )
            self.status_label.setText("✓ 已完成")
            self.status_label.setStyleSheet("color: #2e7d32; font-size: 12px;")

    def set_action_text(self, text):
        self.action_label.setText(text)

    def set_missing(self, reasons):
        """reasons 为缺失原因列表；为空表示无缺项"""
        if reasons:
            self.missing_label.setText("⚠ " + "；".join(reasons))
            self.missing_label.setToolTip("；".join(reasons))
            self.missing_label.show()
        else:
            self.missing_label.hide()
            self.missing_label.setToolTip("")

    def set_thumbnail(self, pixmap):
        if pixmap is not None and not pixmap.isNull():
            self.thumb_label.setPixmap(pixmap)
            self.thumb_label.setText("")
        else:
            self.thumb_label.clear()
            self.thumb_label.setText("暂无截图")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._index)
        super().mousePressEvent(event)


class SideBarWidget(QWidget):
    """步骤导航侧栏：进度看板 + 当前轮次步骤缩略图列表（LRU 缓存 + 分批懒加载）"""

    THUMB_CACHE_LIMIT = 64   # 缩略图 LRU 缓存上限
    THUMB_BATCH = 20         # 每批懒加载张数

    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.item_widgets = []
        self._thumb_cache = OrderedDict()   # key: (截图文件名, 顶点签名) -> QPixmap
        self._thumb_queue = []              # 待加载 (index, filename, vertices_sig)
        self._thumb_queued = set()          # 去重：已在队列中的 index

        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._load_thumb_batch)

        self.setMinimumWidth(220)
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        title = QLabel("步骤导航")
        title.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        root.addWidget(title)

        # === 进度看板 ===
        self.task_label = QLabel("当前指令：-")
        self.task_label.setWordWrap(True)
        self.task_label.setStyleSheet("color: #263238; font-size: 12px;")
        root.addWidget(self.task_label)

        self.round_label = QLabel("已完成轮次：0")
        self.round_label.setStyleSheet("color: #546e7a; font-size: 12px;")
        root.addWidget(self.round_label)

        self.count_label = QLabel("当前轮步数：0")
        self.count_label.setStyleSheet("color: #546e7a; font-size: 12px;")
        root.addWidget(self.count_label)

        self.missing_count_label = QLabel("缺填项：0")
        self.missing_count_label.setStyleSheet("color: #c62828; font-size: 12px;")
        root.addWidget(self.missing_count_label)

        self.action_stats_label = QLabel("")
        self.action_stats_label.setWordWrap(True)
        self.action_stats_label.setStyleSheet("color: #546e7a; font-size: 12px;")
        root.addWidget(self.action_stats_label)

        self.draft_time_label = QLabel("草稿：-")
        self.draft_time_label.setStyleSheet("color: #8d6e63; font-size: 12px;")
        root.addWidget(self.draft_time_label)

        # === 步骤列表（滚动） ===
        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(2, 2, 2, 2)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch()
        self.list_scroll.setWidget(self.list_container)
        root.addWidget(self.list_scroll, 1)

        # === 底部跳转 ===
        jump_row = QHBoxLayout()
        self.jump_spin = QSpinBox()
        self.jump_spin.setMinimum(1)
        self.jump_spin.setMaximum(1)
        self.jump_spin.setPrefix("第 ")
        self.jump_spin.setSuffix(" 步")
        self.jump_btn = QPushButton("跳转")
        self.jump_btn.clicked.connect(self._on_jump_clicked)
        jump_row.addWidget(self.jump_spin)
        jump_row.addWidget(self.jump_btn)
        root.addLayout(jump_row)

    # ---------- 缩略图 LRU 缓存 ----------

    @staticmethod
    def _vertices_signature(vertices):
        """把 vertices 归一化为可哈希 tuple（区分 None / list / tuple / 嵌套）。

        缓存键必须同时带文件名与顶点签名：截图文件名可被「重新拉框」复用而
        框内容已变，只按文件名命中会把旧框缩略图贴到新框步骤上。
        """
        if vertices is None:
            return None
        if isinstance(vertices, (list, tuple)):
            return tuple(SideBarWidget._vertices_signature(v) for v in vertices)
        try:
            hash(vertices)
        except TypeError:
            return repr(vertices)
        return vertices

    def _thumb_key(self, filename, vertices=None):
        """缩略图缓存键：(文件名, 顶点签名)"""
        return (filename, self._vertices_signature(vertices))

    def _get_cached_thumb(self, key):
        if key in self._thumb_cache:
            self._thumb_cache.move_to_end(key)
            return self._thumb_cache[key]
        return None

    def _put_cached_thumb(self, key, pixmap):
        filename = key[0] if isinstance(key, tuple) and key else None
        if not filename:
            return
        # 同一文件只保留最新签名的缩略图：旧签名键永久不可达，留着只会
        # 让缓存无限膨胀，也会让「旧键是否命中」这类断言失去意义
        for stale_key in [k for k in self._thumb_cache
                          if isinstance(k, tuple) and k[0] == filename
                          and k != key]:
            self._thumb_cache.pop(stale_key, None)
        self._thumb_cache[key] = pixmap
        self._thumb_cache.move_to_end(key)
        while len(self._thumb_cache) > self.THUMB_CACHE_LIMIT:
            self._thumb_cache.popitem(last=False)

    def remove_thumb_cache_by_filename(self, filename):
        """文件被删除或覆盖后移除该文件的全部缓存（含不同顶点签名）"""
        for key in [k for k in self._thumb_cache
                    if isinstance(k, tuple) and k[0] == filename]:
            self._thumb_cache.pop(key, None)

    def invalidate_thumb(self, index):
        """强制某步骤缩略图下次重新加载（按当前文件名+顶点签名精确失效）"""
        if 0 <= index < len(self.editor.steps_data):
            step = self.editor.steps_data[index]
            key = self._thumb_key(step.get("screenshot", ""), step.get("vertices"))
            self._thumb_cache.pop(key, None)

    def request_thumb(self, index, high_priority=False):
        """请求加载某步骤缩略图（懒加载、去重、可插队）

        high_priority 刷新会丢弃该下标此前排队的旧签名项，保证重拉框后的
        新结果不会被仍在队列里的旧项覆盖。
        """
        if not (0 <= index < len(self.editor.steps_data)):
            return
        step = self.editor.steps_data[index]
        filename = step.get("screenshot", "")
        if not filename:
            return
        vertices_sig = self._vertices_signature(step.get("vertices"))
        if index in self._thumb_queued:
            if not high_priority:
                return
            self._thumb_queue = [e for e in self._thumb_queue if e[0] != index]
            self._thumb_queued.discard(index)
        entry = (index, filename, vertices_sig)
        self._thumb_queued.add(index)
        if high_priority:
            self._thumb_queue.insert(0, entry)
        else:
            self._thumb_queue.append(entry)
        self._thumb_timer.start(10)

    def _load_thumb_batch(self):
        """每批加载 THUMB_BATCH 张缩略图，剩余的排队继续加载"""
        if self.editor.gui_number is None:
            self._thumb_queue.clear()
            self._thumb_queued.clear()
            return

        batch = self._thumb_queue[:self.THUMB_BATCH]
        self._thumb_queue = self._thumb_queue[self.THUMB_BATCH:]

        for index, filename, vertices_sig in batch:
            self._thumb_queued.discard(index)
            if not (0 <= index < len(self.editor.steps_data)):
                continue
            # 以执行时刻的模型为准：重拉框/重截图后，队列里的旧文件名或旧
            # 顶点签名均已过期，直接丢弃，绝不写入缓存或贴到条目上
            step = self.editor.steps_data[index]
            if step.get("screenshot", "") != filename:
                continue
            if self._vertices_signature(step.get("vertices")) != vertices_sig:
                continue
            if not (0 <= index < len(self.item_widgets)):
                continue
            key = (filename, vertices_sig)
            pixmap = self._get_cached_thumb(key)
            if pixmap is None:
                pixmap = self.editor.build_marked_preview(
                    filename, step.get("vertices"), StepListItemWidget.THUMB_SIZE
                )
                if pixmap is not None:
                    self._put_cached_thumb(key, pixmap)
            if 0 <= index < len(self.item_widgets):
                self.item_widgets[index].set_thumbnail(pixmap)

        if self._thumb_queue:
            self._thumb_timer.start(10)

    def ensure_current_thumb(self):
        """保证当前编辑步缩略图最新（坐标变化/切步时高优先级刷新）"""
        index = self.editor.current_step
        if 0 <= index < len(self.editor.steps_data):
            self.invalidate_thumb(index)
            self.request_thumb(index, high_priority=True)

    # ---------- 条目构建与刷新 ----------

    def _create_item(self, index):
        item = StepListItemWidget(index)
        item.clicked.connect(self.editor.jump_to_step)
        # 插到末尾 stretch 之前
        self.list_layout.insertWidget(self.list_layout.count() - 1, item)
        self.item_widgets.append(item)
        self.refresh_step_item(index)
        self.request_thumb(index)

    def rebuild_items(self):
        """全量重建步骤条目（切轮次/删除/插入/续采后调用）"""
        for item in self.item_widgets:
            self.list_layout.removeWidget(item)
            item.deleteLater()
        self.item_widgets = []
        self._thumb_queue.clear()
        self._thumb_queued.clear()

        for index in range(len(self.editor.steps_data)):
            item = StepListItemWidget(index)
            item.clicked.connect(self.editor.jump_to_step)
            self.list_layout.insertWidget(self.list_layout.count() - 1, item)
            self.item_widgets.append(item)
            self.refresh_step_item(index)

        # 当前步插队优先加载，其余懒加载
        self.refresh_highlight()
        self.refresh_dashboard()
        for index in range(len(self.editor.steps_data)):
            if index != self.editor.current_step:
                self.request_thumb(index)
        self.ensure_current_thumb()

    def refresh_step_item(self, index):
        """刷新单个条目的动作名/缺项/状态"""
        if not (0 <= index < len(self.item_widgets)):
            return
        if not (0 <= index < len(self.editor.steps_data)):
            return
        item = self.item_widgets[index]
        step = self.editor.steps_data[index]
        action_data = step.get("action_data") or {}
        action_en = action_data.get("action", "")
        intent = step.get("intent", "")
        item.set_action_text(
            f"{action_cn_name(action_en)}" + (f"\n{intent}" if intent else "")
        )
        item.set_current(index == self.editor.current_step)
        # 读缺项缓存快照，避免全量重建时 N 个条目各做一次实时校验
        if len(self.editor._missing_cache) != len(self.editor.steps_data):
            self.editor.revalidate_all_missing()
        reasons = self.editor.get_cached_missing(index)
        item.set_missing(reasons or [])

    def refresh_highlight(self):
        """刷新当前编辑步高亮"""
        for i, item in enumerate(self.item_widgets):
            item.set_current(i == self.editor.current_step)

    def refresh_dashboard(self):
        """刷新进度看板（指令、轮次、步数、缺项、动作分布）"""
        instruction = self.editor.task_instruction or "-"
        fm = QFontMetrics(self.task_label.font())
        self.task_label.setText("当前指令：" + fm.elidedText(
            instruction, Qt.ElideRight, max(120, self.width() - 40)
        ))
        self.task_label.setToolTip(instruction)

        self.round_label.setText(f"已完成轮次：{len(self.editor.rounds)}")
        total = len(self.editor.steps_data)
        self.count_label.setText(f"当前轮步数：{total}")

        # 待完善数直接读缺项缓存快照（缓存漂移时兜底全量重算一次），
        # 动作分布只遍历纯数据字段；不再对每步做实时校验
        if len(self.editor._missing_cache) != len(self.editor.steps_data):
            self.editor.revalidate_all_missing()
        missing_total = sum(1 for r in self.editor._missing_cache if r)
        # 未确认新步（无侧栏条目）的实时缺项惰性算一次并入计数
        live_reasons = self.editor.live_missing_reasons()
        if live_reasons:
            missing_total += 1
        stats = {}
        for step in self.editor.steps_data:
            action_en = (step.get("action_data") or {}).get("action", "")
            stats[action_en] = stats.get(action_en, 0) + 1
        self.missing_count_label.setText(f"缺填项：{missing_total}")

        if stats:
            stats_text = "，".join(
                f"{action_cn_name(a).split(' ')[0]}×{n}" for a, n in stats.items()
            )
            self.action_stats_label.setText(stats_text)
        else:
            self.action_stats_label.setText("")

        self.jump_spin.setMaximum(max(1, total))

        # 无已完成轮次时禁用回看入口（防止打开空对话框）
        if hasattr(self.editor, "view_rounds_btn"):
            self.editor.view_rounds_btn.setEnabled(bool(self.editor.rounds))

    def set_draft_saving(self):
        self.draft_time_label.setText("草稿：保存中…")

    def set_draft_saved(self, time_text=None):
        if time_text is None:
            time_text = datetime.now().strftime("%H:%M:%S")
        self.draft_time_label.setText(f"草稿：已保存 {time_text}")

    def _on_jump_clicked(self):
        self.editor.jump_to_step(self.jump_spin.value() - 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 宽度变化时重新截断当前指令
        self.refresh_dashboard()


class ValidationFailDialog(QDialog):
    """结束任务前的全量必填校验失败对话框，可双击跳转到对应步骤"""

    def __init__(self, missing_list, parent=None):
        # missing_list: [(index, 动作中文名, [原因...]), ...]
        super().__init__(parent)
        self.setWindowTitle("必填项校验未通过")
        self.setMinimumWidth(560)
        self._target_index = None

        layout = QVBoxLayout(self)
        tip = QLabel(f"共有 {len(missing_list)} 个步骤存在缺填项，请补全后再结束任务：")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #c62828; padding: 4px;")
        layout.addWidget(tip)

        self.list_widget = QListWidget()
        for index, action_label, reasons in missing_list:
            item = QListWidgetItem(
                f"第 {index + 1} 步（{action_label}）：{'；'.join(reasons)}"
            )
            item.setData(Qt.UserRole, index)
            self.list_widget.addItem(item)
        self.list_widget.itemDoubleClicked.connect(self._on_jump_selected)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.jump_btn = QPushButton("跳转到该步")
        self.jump_btn.clicked.connect(self._on_jump_selected)
        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.jump_btn)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

    def _on_jump_selected(self, item=None):
        current = self.list_widget.currentItem()
        target_item = item or current
        if target_item is not None:
            self._target_index = target_item.data(Qt.UserRole)
            self.accept()

    def target_index(self):
        return self._target_index


class RoundPreviewDialog(QDialog):
    """已完成轮次的只读回看器（不修改编辑器数据、不写草稿）"""

    THUMB_SIZE = QSize(160, 90)
    THUMB_BATCH = 20
    CACHE_LIMIT = 128

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self._rounds = editor.rounds if isinstance(editor.rounds, list) else []
        self._items_meta = []       # [(filename, vertices)]，与列表行一一对应
        self._pending = []          # 待生成缩略图的 (item, filename, vertices)
        self._cache = OrderedDict()  # 独立 LRU：key=(filename, repr(vertices))

        self.setWindowTitle("已完成轮次回看")
        self.resize(980, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ---- 顶部：轮次选择 ----
        top = QHBoxLayout()
        top.addWidget(QLabel("轮次："))
        self.round_combo = QComboBox()
        self.round_combo.setMinimumWidth(420)
        for i, round_data in enumerate(self._rounds):
            instruction = str(round_data.get("instruction", "") or "")
            one_line = " ".join(instruction.split())
            short = one_line[:30] + ("…" if len(one_line) > 30 else "")
            self.round_combo.addItem(f"第 {i + 1} 轮 · {short or '（无指令）'}")
            self.round_combo.setItemData(
                i, f"第 {i + 1} 轮\n{instruction}", Qt.ToolTipRole
            )
        top.addWidget(self.round_combo, 1)
        self.step_count_label = QLabel("共 0 步")
        self.step_count_label.setStyleSheet("color: #546e7a;")
        top.addWidget(self.step_count_label)
        root.addLayout(top)

        # ---- 中部：缩略图列表 + 大图预览 ----
        body = QSplitter(Qt.Horizontal)

        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListView.IconMode)
        self.list_widget.setIconSize(self.THUMB_SIZE)
        self.list_widget.setGridSize(QSize(170, 130))
        self.list_widget.setResizeMode(QListView.Adjust)
        self.list_widget.setMovement(QListView.Static)
        self.list_widget.setSpacing(4)
        self.list_widget.setWordWrap(True)
        self.list_widget.currentRowChanged.connect(self._on_current_row_changed)
        body.addWidget(self.list_widget)

        self.preview_label = QLabel("请选择左侧步骤查看大图")
        self.preview_label.setMinimumSize(480, 300)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(
            "background-color: #263238; color: #cfd8dc; font-size: 14px;"
        )
        body.addWidget(self.preview_label)

        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([340, 640])
        root.addWidget(body, 1)

        # 缩略图分批生成定时器（10ms/批）
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(10)
        self._thumb_timer.timeout.connect(self._load_thumb_batch)

        self.round_combo.currentIndexChanged.connect(self._load_round)
        if self._rounds:
            self._load_round(0)

    # ---------- 数据读取（只读） ----------

    def _round_coords(self, round_index):
        """取某轮的 coords：优先 _coords_rounds，缺失时回退 rounds[i]['coords']"""
        coords_rounds = getattr(self.editor, "_coords_rounds", None) or []
        if len(coords_rounds) == len(self._rounds):
            coords = coords_rounds[round_index]
        else:
            coords = (self._rounds[round_index] or {}).get("coords") or []
        return coords if isinstance(coords, list) else []

    def _round_vertices(self, round_index, step):
        """按 step 从该轮 coords 中取合法 vertices；没有则返回 None（不画框）"""
        entry = AnnotationEditor._find_coord_entry(
            self._round_coords(round_index), step
        )
        if not isinstance(entry, dict):
            return None
        return AnnotationEditor._valid_vertices(entry.get("vertices"))

    @staticmethod
    def _trajectory_action_name(traj):
        actions = (traj or {}).get("actions") or []
        if isinstance(actions, list) and actions:
            action = (actions[0] or {}).get("action", "")
            if action:
                return action_cn_name(action)
        return "未知动作"

    # ---------- 轮次切换与列表构建 ----------

    def _load_round(self, round_index):
        if not (0 <= round_index < len(self._rounds)):
            return
        self._thumb_timer.stop()
        self._pending = []
        self._items_meta = []
        self.list_widget.clear()

        trajectory = (self._rounds[round_index] or {}).get("trajectory") or []
        if not isinstance(trajectory, list):
            trajectory = []
        self.step_count_label.setText(f"共 {len(trajectory)} 步")

        placeholder = QPixmap(self.THUMB_SIZE)
        placeholder.fill(QColor("#37474f"))

        for i, traj in enumerate(trajectory):
            traj = traj if isinstance(traj, dict) else {}
            step = traj.get("step", i)
            filename = (traj.get("observation") or {}).get("screenshot", "")
            vertices = self._round_vertices(round_index, step)
            action_text = self._trajectory_action_name(traj)
            item = QListWidgetItem(
                QIcon(placeholder), f"第 {int(step) + 1} 步 · {action_text}"
            )
            item.setToolTip(f"第 {int(step) + 1} 步 · {action_text}\n{filename}")
            self.list_widget.addItem(item)
            self._items_meta.append((filename, vertices))
            self._pending.append((item, filename, vertices))

        if self._pending:
            self._thumb_timer.start(10)

    def _load_thumb_batch(self):
        """每批生成 THUMB_BATCH 张缩略图，全部完成后自动选中第 1 项"""
        batch = self._pending[:self.THUMB_BATCH]
        self._pending = self._pending[self.THUMB_BATCH:]
        for item, filename, vertices in batch:
            pixmap = self._thumb_pixmap(filename, vertices)
            if pixmap is not None and not pixmap.isNull():
                item.setIcon(QIcon(pixmap))
        if self._pending:
            self._thumb_timer.start(10)
        else:
            # 全部生成完毕再自动选中，避免大图反复重绘
            if self.list_widget.count() > 0 and self.list_widget.currentRow() != 0:
                self.list_widget.setCurrentRow(0)
            elif self.list_widget.count() > 0:
                self._refresh_preview()

    # ---------- 独立缩略图 LRU（不触碰 SideBarWidget 缓存） ----------

    def _cache_key(self, filename, vertices):
        return (filename, repr(vertices))

    def _thumb_pixmap(self, filename, vertices):
        if not filename:
            return None
        key = self._cache_key(filename, vertices)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        pixmap = self.editor.build_marked_preview(
            filename, vertices, self.THUMB_SIZE
        )
        if pixmap is not None and not pixmap.isNull():
            self._cache[key] = pixmap
            self._cache.move_to_end(key)
            while len(self._cache) > self.CACHE_LIMIT:
                self._cache.popitem(last=False)
        return pixmap

    # ---------- 大图预览 ----------

    def _on_current_row_changed(self, row):
        self._refresh_preview()

    def _refresh_preview(self):
        if not hasattr(self, "preview_label"):
            return
        row = self.list_widget.currentRow()
        if not (0 <= row < len(self._items_meta)):
            self.preview_label.clear()
            self.preview_label.setText("请选择左侧步骤查看大图")
            return
        filename, vertices = self._items_meta[row]
        size = self.preview_label.size()
        target = QSize(max(480, size.width()), max(300, size.height()))
        pixmap = self.editor.build_marked_preview(filename, vertices, target)
        if pixmap is None or pixmap.isNull():
            self.preview_label.clear()
            self.preview_label.setText("截图文件缺失或无法加载")
        else:
            self.preview_label.setPixmap(pixmap)
            self.preview_label.setText("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_preview()


class AnnotationEditor(QMainWindow):
    """GUI长步骤采标工具-iOS 标注编辑器主窗口"""

    def __init__(self, data_manager, app_name, task_instruction, screen_info, app_type="", udid=None, close_callback=None):
        super().__init__()
        self.data_manager = data_manager
        self.app_name = app_name
        self.task_instruction = task_instruction
        self.screen_info = screen_info
        self.app_type = app_type
        self.udid = udid
        self._close_callback = close_callback

        # 步骤数据
        self.current_step = 0
        self.steps_data = []       # 每个步骤的截图文件名、文件路径和动作数据
        self.coords_data = []      # 坐标数据列表
        self.rounds = []           # 多轮任务数据（参考 macOS rounds），每轮 {instruction, trajectory}
        self.screenshot_cache = None  # 当前截图的数据（临时文件路径）
        self._current_screenshot_filename = None  # 当前截图在 gui 目录下的文件名
        self._current_screenshot_filepath = None  # 当前截图在 gui 目录下的完整路径
        self.gui_number = None
        self.gui_dir = None

        # 模块
        self.screen_capture = IOSScreenCapture(udid=udid)

        # UI 状态
        self._action_widgets = {}
        self._updating_action_ui = False
        self._current_vertices = None

        # swipe/drag 测量状态：先拉起点框，再点测量，最后拉终点框
        self._swipe_measuring = False  # 是否正在测量滑动/拖拽
        self._swipe_start_vertices = None  # 滑动/拖拽起点顶点数据

        # scroll 测量状态：多次选择参照物，累积计算滚动像素
        self._scroll_measuring = False  # 是否正在测量滚动
        self._scroll_references = []  # 存储参照物的 Y 坐标列表
        self._scroll_preserve_screenshot = False  # scroll 测量期间保留第一张截图
        self._scroll_extra_screenshots = []  # scroll 测量期间产生的额外截图路径
        self._scroll_first_coord = None  # 保存第一个拉框的坐标

        # 重新截图标记
        self._replacing_screenshot = False

        # “在当前步之后插入”截图锚点（None 表示普通追加；整数表示锚点步下标）
        self._capture_insert_after = None

        # 「给下一步截图」：从已落表步骤追加新步骤空位（True 时跳过原地覆盖判定）
        self._capture_append_new_step = False

        # 截图进行中标记（防止重复触发）
        self._screenshot_in_progress = False

        # B2 轮次切换门闩：answer 落轮后用 singleShot(300) 延后弹新轮对话框。这 300ms 内
        # steps_data 仍然完整、task_instruction 还是旧指令，再确认一次 answer 就会用同一
        # 条指令往 rounds 重复 append 一轮。置 True 期间所有采集/编辑入口一律早退。
        self._round_transition_pending = False

        # 当前步截图文件在磁盘上丢失（历史步恢复加载失败）：判缺、提示重截图
        self._screenshot_missing = False

        # 「在原图上重新拉框」弹窗引用（编辑已完成任务专用，普通采标不创建）
        self._relabel_dialog = None

        # 切到 terminate 前的 intent 备份：切走 terminate 时还原，避免污染其它步
        self._terminate_intent_saved = False
        self._pre_terminate_intent = ""

        # 最近一次截图的临时文件完整路径（只读调试属性：每次截图唯一名，
        # 避免多编辑器/连续截图共用固定临时路径导致 QPixmap 缓存串图）
        self._last_capture_tmp_path = None

        # 草稿自动保存：输入变化后 1000ms 防抖落盘
        self.draft_timer = QTimer(self)
        self.draft_timer.setSingleShot(True)
        self.draft_timer.setInterval(1000)
        self.draft_timer.timeout.connect(self._write_draft_now)
        # 任务数据已正式落盘后置 True，阻止关闭窗口时重新生成草稿
        self._draft_discarded = False

        # 编辑已完成任务模式（不写草稿，确认不切轮，保存修改才写回）
        self._edit_mode = False
        self._completed_json = None  # 从已完成 JSON 读入的原始结构（保留顶层字段）
        self._edit_round_index = 0
        self._coords_rounds = []     # 与 rounds 等长的坐标分组
        self._original_coords_exist = False
        # hydration 检测出的「盘上 bbox 与 coordinate 不一致」清单：
        # (步序, 动作中文名, issue, 差异详情)，编辑期间只读，不参与写回判定
        self._coord_issues = []
        self._final_data_saved = False

        # 必填校验结果缓存（按步骤下标），输入变化后 300ms 防抖重算
        self._missing_cache = []
        # 未确认新步（current_step == len）的实时缺项槽位；None 表示待重算/无该槽
        self._missing_live = None
        self.validation_timer = QTimer(self)
        self.validation_timer.setSingleShot(True)
        self.validation_timer.setInterval(300)
        self.validation_timer.timeout.connect(self._on_validation_debounced)

        self.setWindowTitle(f"GUI长步骤采标工具-iOS - {app_name}")
        self.setGeometry(100, 50, 1400, 900)
        self.init_ui()

        # 键盘事件
        self.setFocusPolicy(Qt.StrongFocus)

    def init_ui(self):
        """初始化界面"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # === 顶部工具栏 ===
        toolbar = QHBoxLayout()

        self.btn_prev = QPushButton("← 上一步")
        self.btn_prev.clicked.connect(self.go_previous)
        toolbar.addWidget(self.btn_prev)

        self.btn_undo = QPushButton("撤销")
        self.btn_undo.clicked.connect(self.undo_last_step)
        toolbar.addWidget(self.btn_undo)

        self.step_label = QLabel("步骤: 0")
        self.step_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self.step_label.setAlignment(Qt.AlignCenter)
        self.step_label.setFixedWidth(120)
        toolbar.addWidget(self.step_label)

        self.btn_next = QPushButton("下一步 →")
        self.btn_next.clicked.connect(self.go_next)
        toolbar.addWidget(self.btn_next)

        toolbar.addSpacing(20)

        self.btn_clear = QPushButton("清除标注")
        self.btn_clear.clicked.connect(self.clear_annotations)
        toolbar.addWidget(self.btn_clear)

        # 删除当前步骤（中间步骤可删，后续步骤下标前移）
        self.btn_delete = QPushButton("删除当前步骤")
        self.btn_delete.setStyleSheet(
            "QPushButton { background-color: #E53935; color: white; padding: 6px 12px; font-weight: bold; }"
        )
        self.btn_delete.clicked.connect(self.delete_current_step)
        toolbar.addWidget(self.btn_delete)

        # 在当前步之后插入一个新截图步骤
        self.btn_insert = QPushButton("在此步后插入截图")
        self.btn_insert.setStyleSheet(
            "QPushButton { background-color: #00897B; color: white; padding: 6px 12px; font-weight: bold; }"
        )
        self.btn_insert.clicked.connect(self.start_insert_capture)
        toolbar.addWidget(self.btn_insert)

        # 原地覆盖当前步截图（不新增步骤，序号不变）
        self.btn_recapture = QPushButton("重新截图")
        self.btn_recapture.setStyleSheet(
            "QPushButton { background-color: #FF9800; color: white; padding: 6px 12px; font-weight: bold; }"
        )
        self.btn_recapture.clicked.connect(self.recapture_current_step)
        toolbar.addWidget(self.btn_recapture)

        # 编辑已完成任务时可见：不重新截图，直接在磁盘原图上重新拖框
        self.btn_relabel = QPushButton("在原图上重新拉框")
        self.btn_relabel.setStyleSheet(
            "QPushButton { background-color: #9C27B0; color: white; padding: 6px 12px; font-weight: bold; }"
        )
        self.btn_relabel.clicked.connect(self.relabel_current_step)
        self.btn_relabel.hide()
        toolbar.addWidget(self.btn_relabel)

        self.btn_capture_next = QPushButton("给下一步截图 (Ctrl+Q)")
        self.btn_capture_next.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; padding: 6px 16px; font-weight: bold; }"
        )
        self.btn_capture_next.clicked.connect(self.start_capture)
        toolbar.addWidget(self.btn_capture_next)

        self.btn_confirm = QPushButton("确认 (Ctrl+S)")
        self.btn_confirm.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; padding: 6px 16px; font-weight: bold; }"
        )
        self.btn_confirm.clicked.connect(self.go_next)
        toolbar.addWidget(self.btn_confirm)

        # 编辑已完成任务时的唯一写回入口（普通采标模式下隐藏）
        self.btn_save_edit = QPushButton("保存修改")
        self.btn_save_edit.setStyleSheet(
            "QPushButton { background-color: #8E24AA; color: white; padding: 6px 16px; font-weight: bold; }"
        )
        self.btn_save_edit.clicked.connect(lambda: self.save_edited_round(False))
        self.btn_save_edit.hide()
        toolbar.addWidget(self.btn_save_edit)

        # 只读回看已完成轮次（不修改任何数据；无已落轮时禁用）
        self.view_rounds_btn = QPushButton("查看已完成轮次")
        self.view_rounds_btn.setEnabled(False)
        self.view_rounds_btn.clicked.connect(self.show_round_preview_dialog)
        toolbar.addWidget(self.view_rounds_btn)

        toolbar.addStretch()
        main_layout.addLayout(toolbar)

        # === 外层分栏：左侧步骤导航侧栏 + 右侧编辑区 ===
        outer_splitter = QSplitter(Qt.Horizontal)

        # 左侧：步骤导航侧栏
        self.sidebar = SideBarWidget(self)
        outer_splitter.addWidget(self.sidebar)

        # === 内层分栏：左截图预览 + 右参数表单 ===
        inner_splitter = QSplitter(Qt.Horizontal)

        # 截图预览
        self.canvas = ScreenshotCanvas()
        self.canvas.rect_drawn.connect(self.on_rect_drawn)
        inner_splitter.addWidget(self.canvas)

        # 右侧：动作信息面板（放入滚动区域，参数较多时可滚动）
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)

        # 动作组
        action_group = QGroupBox("动作信息")
        action_form = QFormLayout()

        # 动作描述
        self.intent_input = QLineEdit()
        self.intent_input.setPlaceholderText("描述当前步骤的动作（如：点击搜索按钮）")
        action_form.addRow("动作描述:", self.intent_input)

        # 动作类型
        self.action_combo = QComboBox()
        for value, label in IOS_ACTIONS:
            self.action_combo.addItem(label, value)
        self.action_combo.currentIndexChanged.connect(self.on_action_changed)
        action_form.addRow("动作类型:", self.action_combo)

        # 坐标 X, Y（click/long_press/type/scroll；swipe/drag 时语义为起点坐标）
        coord_widget = QWidget()
        coord_layout = QHBoxLayout(coord_widget)
        coord_layout.setContentsMargins(0, 0, 0, 0)
        self.coord_label = QLabel("坐标 [x, y]:")
        self.coord_label.setFixedWidth(110)
        self.coord_x_input = QLineEdit()
        self.coord_x_input.setPlaceholderText("x")
        self.coord_x_input.setFixedWidth(80)
        self.coord_y_input = QLineEdit()
        self.coord_y_input.setPlaceholderText("y")
        self.coord_y_input.setFixedWidth(80)
        coord_layout.addWidget(self.coord_label)
        coord_layout.addWidget(self.coord_x_input)
        coord_layout.addWidget(self.coord_y_input)
        coord_layout.addStretch()
        self._action_widgets["coordinate"] = coord_widget
        action_form.addRow(coord_widget)

        # 终点坐标 X2, Y2 (swipe/drag)
        coord2_widget = QWidget()
        coord2_layout = QHBoxLayout(coord2_widget)
        coord2_layout.setContentsMargins(0, 0, 0, 0)
        self.coord2_label = QLabel("终点坐标 [x2, y2]:")
        self.coord2_label.setFixedWidth(110)
        self.coord2_x_input = QLineEdit()
        self.coord2_x_input.setPlaceholderText("x2")
        self.coord2_x_input.setFixedWidth(80)
        self.coord2_y_input = QLineEdit()
        self.coord2_y_input.setPlaceholderText("y2")
        self.coord2_y_input.setFixedWidth(80)
        coord2_layout.addWidget(self.coord2_label)
        coord2_layout.addWidget(self.coord2_x_input)
        coord2_layout.addWidget(self.coord2_y_input)
        coord2_layout.addStretch()
        self._action_widgets["coordinate2"] = coord2_widget
        action_form.addRow(coord2_widget)

        # swipe/drag 测量按钮组：先拉起点框，再点测量，最后拉终点框
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

        # 滚动像素输入 (scroll)
        scroll_pixel_widget = QWidget()
        scroll_pixel_layout = QHBoxLayout(scroll_pixel_widget)
        scroll_pixel_layout.setContentsMargins(0, 0, 0, 0)
        self.pixels_label = QLabel("滚动像素:")
        self.pixels_label.setFixedWidth(110)
        self.pixels_input = QLineEdit()
        self.pixels_input.setPlaceholderText("内容向下为正，内容向上为负")
        self.pixels_input.setReadOnly(True)
        scroll_pixel_layout.addWidget(self.pixels_label)
        scroll_pixel_layout.addWidget(self.pixels_input)
        scroll_pixel_layout.addStretch()
        self._action_widgets["scroll_pixel"] = scroll_pixel_widget
        action_form.addRow(scroll_pixel_widget)

        # scroll 测量按钮组：多次选择参照物，累积计算滚动像素
        scroll_measure_widget = QWidget()
        scroll_measure_layout = QHBoxLayout(scroll_measure_widget)
        scroll_measure_layout.setContentsMargins(0, 0, 0, 0)
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
        scroll_measure_layout.addWidget(self.btn_scroll_measure)
        scroll_measure_layout.addWidget(self.btn_scroll_finish)
        scroll_measure_layout.addStretch()
        self._action_widgets["scroll_measure"] = scroll_measure_widget
        action_form.addRow(scroll_measure_widget)

        # 文本输入（type/answer/open_app/open_url 共用，标签随动作切换）
        text_widget = QWidget()
        text_layout = QHBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        self.text_label = QLabel("输入文本:")
        self.text_label.setFixedWidth(110)
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("输入文本内容")
        text_layout.addWidget(self.text_label)
        text_layout.addWidget(self.text_input)
        self._action_widgets["text"] = text_widget
        action_form.addRow(text_widget)

        # 等待时间 (long_press/wait)
        time_widget = QWidget()
        time_layout = QHBoxLayout(time_widget)
        time_layout.setContentsMargins(0, 0, 0, 0)
        self.time_label = QLabel("等待时间（秒）:")
        self.time_label.setFixedWidth(110)
        self.time_input = QLineEdit()
        self.time_input.setPlaceholderText("秒数（如：2.0）")
        time_layout.addWidget(self.time_label)
        time_layout.addWidget(self.time_input)
        self._action_widgets["time"] = time_widget
        action_form.addRow(time_widget)

        # 系统按钮 (system_button)
        button_widget = QWidget()
        button_layout = QHBoxLayout(button_widget)
        button_layout.setContentsMargins(0, 0, 0, 0)
        self.button_label = QLabel("系统按钮:")
        self.button_label.setFixedWidth(110)
        self.button_combo = QComboBox()
        self.button_combo.addItems(SYSTEM_BUTTONS)
        button_layout.addWidget(self.button_label)
        button_layout.addWidget(self.button_combo)
        button_layout.addStretch()
        self._action_widgets["button"] = button_widget
        action_form.addRow(button_widget)

        # 无参数动作（terminate）占位提示
        self.no_param_label = QLabel("该动作无需填写参数，确认后即可结束任务。")
        self.no_param_label.setWordWrap(True)
        self.no_param_label.setStyleSheet("color: #757575; padding: 4px;")
        self._action_widgets["no_param"] = self.no_param_label
        action_form.addRow(self.no_param_label)

        action_group.setLayout(action_form)
        right_layout.addWidget(action_group)

        # 截图详情
        detail_group = QGroupBox("截图信息")
        detail_layout = QFormLayout()
        self.screenshot_name_label = QLabel("(暂无)")
        self.screenshot_size_label = QLabel("-")
        detail_layout.addRow("文件名:", self.screenshot_name_label)
        detail_layout.addRow("尺寸:", self.screenshot_size_label)
        detail_group.setLayout(detail_layout)
        right_layout.addWidget(detail_group)

        right_layout.addStretch()

        # 右参数面板放入滚动区域
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setWidget(right_panel)
        inner_splitter.addWidget(right_scroll)

        # 截图约 65%、表单约 35%
        inner_splitter.setStretchFactor(0, 3)
        inner_splitter.setStretchFactor(1, 2)
        inner_splitter.setSizes([740, 400])

        outer_splitter.addWidget(inner_splitter)
        outer_splitter.setStretchFactor(0, 0)
        outer_splitter.setStretchFactor(1, 1)
        outer_splitter.setSizes([240, 1160])

        main_layout.addWidget(outer_splitter, 1)

        # === 状态栏 ===
        self.status_label = QLabel('就绪 - 请点击 [给下一步截图(Ctrl+Q)] 按钮开始')
        self.status_label.setStyleSheet("padding: 5px; background-color: #f0f0f0;")
        main_layout.addWidget(self.status_label)

        # 输入变化联动：300ms 防抖重算必填校验 + 1000ms 防抖保存草稿
        self._connect_editor_validation_signals()

        # 初始更新 UI
        self._update_action_fields_visibility()
        self._update_navigation_buttons()
        self.sidebar.rebuild_items()

    def _connect_editor_validation_signals(self):
        """连接各输入控件：变化时触发校验防抖与草稿防抖"""
        def on_change(*args):
            self.validation_timer.start()
            self.schedule_draft_save()

        self.intent_input.textChanged.connect(on_change)
        self.text_input.textChanged.connect(on_change)
        self.time_input.textChanged.connect(on_change)
        self.coord_x_input.textChanged.connect(on_change)
        self.coord_y_input.textChanged.connect(on_change)
        self.coord2_x_input.textChanged.connect(on_change)
        self.coord2_y_input.textChanged.connect(on_change)
        self.pixels_input.textChanged.connect(on_change)
        self.button_combo.currentIndexChanged.connect(on_change)
        self.action_combo.currentIndexChanged.connect(on_change)

    # ========== 动作 UI 逻辑 ==========

    def _update_action_fields_visibility(self):
        """根据当前动作类型显示/隐藏参数行，并切换语义化中文标签"""
        action = self._current_action_key()

        visibility = {
            "coordinate": action in COORD_ACTIONS,
            "coordinate2": action in SWIPE_ACTIONS,
            "swipe_measure": action in SWIPE_ACTIONS,
            "scroll_pixel": action in SCROLL_ACTIONS,
            "scroll_measure": action in SCROLL_ACTIONS,
            "text": action in TEXT_ACTIONS,
            "time": action in TIME_ACTIONS,
            "button": action in BUTTON_ACTIONS,
            "no_param": action == "terminate",
        }
        for key, widget in self._action_widgets.items():
            if isinstance(widget, QWidget):
                widget.setVisible(visibility.get(key, False))

        # 语义化标签：坐标行在滑动/拖拽时表示起点
        if action in SWIPE_ACTIONS:
            self.coord_label.setText("起点坐标 [x, y]:")
        else:
            self.coord_label.setText("坐标 [x, y]:")

        # 文本行标签随动作切换
        text_labels = {
            "type": "输入文本:",
            "answer": "回答内容:",
            "answer_terminate": "回答内容:",
            "open_app": "应用名称:",
            "open_url": "网址 URL:",
        }
        if action in text_labels:
            self.text_label.setText(text_labels[action])

        # 时间行标签
        if action == "long_press":
            self.time_label.setText("长按时长（秒）:")
        else:
            self.time_label.setText("等待时间（秒）:")

    def _current_action_key(self):
        """获取当前选中的动作类型 key"""
        return self.action_combo.currentData()

    def on_action_changed(self):
        """动作类型切换"""
        action = self._current_action_key()
        if action == "terminate":
            if not self._terminate_intent_saved:
                self._terminate_intent_saved = True
                self._pre_terminate_intent = self.intent_input.text()
            self.intent_input.setText("任务完成")
        elif self._terminate_intent_saved:
            # 切离 terminate：还原进入前的 intent（可能本就是空串）
            self._terminate_intent_saved = False
            self.intent_input.setText(self._pre_terminate_intent)
            self._pre_terminate_intent = ""
        self._update_action_fields_visibility()
        self.validation_timer.start()

    # ========== 截图逻辑 ==========

    def initialize_gui_directory(self):
        """初始化任务目录（取消录屏后仅创建 gui 目录）"""
        self.gui_number = self.data_manager.get_next_gui_number()
        self.gui_dir = self.data_manager.create_gui_directory(self.gui_number)
        self.status_label.setText(
            f"任务目录已创建 - gui_{self.gui_number} - 请截取第一张图"
        )

    def start_insert_capture(self):
        """工具栏入口：在当前步之后插入一个新截图步骤"""
        # B2：门闩必须在设置插入锚点之前早退，否则残留锚点会把下一次普通截图误判为插入
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if self.gui_dir is None:
            QMessageBox.warning(self, "提示", "请先初始化任务目录")
            return
        if not (0 <= self.current_step < len(self.steps_data)):
            QMessageBox.warning(self, "提示", "请先确认当前步骤后再插入")
            return
        # swipe/drag 测量是“起点框 -> 终点框”的两阶段流程，插入截图会破坏
        # 当前步测量上下文并产生孤儿截图，入口直接拦截（scroll 测量期间的
        # 插入走 extra 截图既定路径，不在此拦截）
        if self._swipe_measuring:
            QMessageBox.warning(self, "提示", "滑动/拖拽测量进行中，请先完成或取消测量后再插入")
            return
        # 锚点 = 当前步骤下标；截图成功后插入到锚点之后
        self._capture_insert_after = self.current_step
        self.status_label.setText(
            f"准备在第 {self.current_step + 1} 步之后插入 - 正在从 iPhone 截图..."
        )
        self.take_screenshot()

    def start_capture(self):
        """给下一步截图：追加一个新步骤的截图（绝不覆盖当前步截图）"""
        if self._final_data_saved and not self._edit_mode:
            self.status_label.setText("任务已保存，请先选择是否开始新任务")
            return
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if self._screenshot_in_progress:
            return  # 上一次截图尚未完成，忽略重复触发
        if self.gui_dir is None:
            QMessageBox.warning(self, "提示", "请先初始化任务目录")
            return
        # swipe/drag 测量是「起点框 -> 终点框」两阶段流程，此时追加新步会
        # 破坏当前测量上下文并产生孤儿截图，入口直接拦截
        if self._swipe_measuring:
            QMessageBox.warning(self, "提示", "滑动/拖拽测量进行中，请先完成或取消测量后再截图")
            return
        if self._scroll_measuring:
            QMessageBox.warning(
                self, "提示",
                "滚动测量进行中，请使用[重新截图]获取参照物截图，或先完成测量",
            )
            return
        # 防御性清除残留：追加模式不得叠加插入锚点或原地覆盖标记
        self._capture_insert_after = None
        self._replacing_screenshot = False
        if self.current_step < len(self.steps_data):
            # 当前停在已落表步骤：新截图将成为下一个步骤
            self._capture_append_new_step = True
            self.status_label.setText("正在为下一步从 iPhone 截图...")
        else:
            # 已处于待确认空位，它本身就是「下一步」：走默认语义，
            # 已有待确认图则原地覆盖，避免产生无主的孤儿文件
            self.status_label.setText("正在从 iPhone 截图...")
        self.take_screenshot()

    def recapture_current_step(self):
        """重新截图：原地覆盖当前步骤的截图（无可用截图时退化为首次截图）"""
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if self._screenshot_in_progress:
            return  # 上一次截图尚未完成，忽略重复触发
        if self.gui_dir is None:
            QMessageBox.warning(self, "提示", "请先初始化任务目录")
            return
        if self._swipe_measuring:
            QMessageBox.warning(
                self, "提示", "滑动/拖拽测量进行中，请先完成或取消测量后再重新截图"
            )
            return
        # 重新截图语义固定为原地覆盖，不得走插入/追加
        self._capture_insert_after = None
        self._capture_append_new_step = False
        self._replacing_screenshot = False

        has_capture = bool(self._current_screenshot_filename) or (
            self._screenshot_missing
            and 0 <= self.current_step < len(self.steps_data)
            and self.steps_data[self.current_step].get("screenshot")
        )
        if not has_capture:
            # 空位/首次截图：交给默认语义决定追加还是覆盖
            self.status_label.setText("正在从 iPhone 截图...")
            self.take_screenshot()
            return
        # scroll 测量期间不拦截：必须继续走 extra 截图路径
        # （由 _scroll_preserve_screenshot 分支处理，避免覆盖步骤截图）
        self.status_label.setText("正在重新截取当前步骤截图...")
        self.take_screenshot()

    def take_screenshot(self):
        """截取 iOS 屏幕（如同一步骤已有截图则替换）"""
        if self._final_data_saved and not self._edit_mode:
            self.status_label.setText("任务已保存，请先选择是否开始新任务")
            return
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if self._screenshot_in_progress:
            return  # 上一次截图尚未完成，忽略重复触发

        if self.gui_dir is None:
            QMessageBox.warning(self, "提示", "请先初始化任务目录")
            return

        # 插入模式：即将生成新序号文件，不能覆盖锚点步截图
        if self._capture_insert_after is not None:
            pass
        # 给下一步截图：强制走追加分支，不能把当前步判定为「原地覆盖」
        elif self._capture_append_new_step:
            pass
        # scroll 测量期间不删除旧截图，保留第一张作为步骤截图
        elif not self._scroll_preserve_screenshot:
            # 如果当前步骤已有截图，仅标记为替换；真正的删除推迟到新截图成功后，
            # 避免“先删后截”导致截图失败时旧图丢失（见 _do_screenshot）
            if self._current_screenshot_filepath:
                self._replacing_screenshot = True
            # 截图缺失态：文件名已置 None，但 steps_data 里仍保留旧名，
            # 必须按原地替换处理，否则会误入普通追加分支抬高步骤序号
            elif (
                self._screenshot_missing
                and 0 <= self.current_step < len(self.steps_data)
                and self.steps_data[self.current_step].get("screenshot")
            ):
                self._replacing_screenshot = True

        self._screenshot_in_progress = True
        self.status_label.setText("正在从 iPhone 截图...")
        QTimer.singleShot(50, self._do_screenshot)

    def _do_screenshot(self):
        """执行截图操作，截图后立即保存到 gui 目录"""
        import tempfile
        # 固定临时文件名会被 QPixmap 按路径缓存：多个编辑器实例或连续截图
        # 共用同一路径时画布会显示上一张旧图。用 pid + 单调时钟纳秒保证唯一。
        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"ios_capture_tmp_{os.getpid()}_{time.monotonic_ns()}.png",
        )
        # B44：唯一名临时文件在下一次截图后即失去所有引用，记下上一张以便回收
        prev_tmp_path = self._last_capture_tmp_path
        self._last_capture_tmp_path = tmp_path

        success, filepath = self.screen_capture.capture(tmp_path)
        if success and filepath:
            self.screenshot_cache = filepath
            # 显示截图
            pixmap = QPixmap(filepath)
            if not pixmap.isNull():
                self.canvas.set_pixmap(pixmap)
                # 更新截图信息
                self.screenshot_name_label.setText(os.path.basename(filepath))
                self.screenshot_size_label.setText(f"{pixmap.width()} x {pixmap.height()}")
                # B23：顶层 screen_size 只由「本轮首张追加截图」定版；重截、中间插入、
                # 历史步覆盖都不得覆写，否则会话中一次分辨率抖动会改写整轮交付尺寸
                if (not self.steps_data and self._capture_insert_after is None
                        and isinstance(self.screen_info, dict)):
                    self.screen_info["screen_size"] = [pixmap.width(), pixmap.height()]
                # 立即保存截图到 gui 目录（参考 macOS 版做法）
                if self._replacing_screenshot:
                    # 同步骤重新截图：原地覆盖原文件，序号保持不变。
                    # 截图缺失态下当前文件名为 None，回退取 steps_data 历史名
                    replace_name = self._current_screenshot_filename
                    if (
                        not replace_name
                        and 0 <= self.current_step < len(self.steps_data)
                    ):
                        replace_name = self.steps_data[self.current_step].get("screenshot")
                    screenshot_filename = self.data_manager.save_screenshot(
                        self.gui_number, filepath,
                        filename=replace_name,
                    )
                else:
                    screenshot_filename = self.data_manager.save_screenshot(
                        self.gui_number, filepath
                    )
                if screenshot_filename:
                    if self._scroll_preserve_screenshot:
                        # scroll 测量期间：截图保存到 gui 目录用于显示，但不更新步骤截图
                        extra_path = os.path.join(self.gui_dir, screenshot_filename)
                        self._scroll_extra_screenshots.append(extra_path)
                        self.status_label.setText("截图完成 - 请在图片上选择同一个参照物拉框")
                    elif self._capture_insert_after is not None:
                        # 插入模式：先把锚点步当前表单内容落表，再把新截图插到锚点之后
                        anchor = self._capture_insert_after
                        self._capture_insert_after = None
                        # 50ms 异步窗口内锚点步可能已被删除：夹紧到现存末位
                        # （空表时为 -1，新步插到 0），避免 insert_index 越界
                        # 与 current_step 悬空导致幻影追加
                        anchor_valid = 0 <= anchor < len(self.steps_data)
                        if anchor_valid:
                            self._save_current_to_steps()
                        safe_anchor = (
                            anchor
                            if 0 <= anchor < len(self.steps_data)
                            else len(self.steps_data) - 1
                        )
                        new_filepath = os.path.join(self.gui_dir, screenshot_filename)
                        new_step = {
                            "screenshot": screenshot_filename,
                            "screenshot_filepath": new_filepath,
                            "intent": "",
                            "action_data": {"action": "click", "element": ""},
                            "vertices": None,
                        }
                        insert_index = safe_anchor + 1
                        self.steps_data.insert(insert_index, new_step)
                        self.current_step = insert_index
                        # 新步只清表单/坐标，保留刚截到的画布内容
                        self.coord_x_input.clear()
                        self.coord_y_input.clear()
                        self.coord2_x_input.clear()
                        self.coord2_y_input.clear()
                        self.text_input.clear()
                        self.time_input.clear()
                        self.pixels_input.clear()
                        self._current_vertices = None
                        self._current_screenshot_filename = screenshot_filename
                        self._current_screenshot_filepath = new_filepath
                        self._screenshot_missing = False
                        self.screenshot_cache = filepath
                        self._update_step_label()
                        self._update_navigation_buttons()
                        self.sidebar.rebuild_items()
                        self.schedule_draft_save()
                        if anchor_valid:
                            self.status_label.setText(
                                f"已在第 {anchor + 1} 步后插入 - 请拉框标注并填写动作信息后确认"
                            )
                        else:
                            self.status_label.setText(
                                "锚点步骤已删除，截图已插入到末尾 - 请拉框标注并填写动作信息后确认"
                            )
                    elif self._replacing_screenshot:
                        # 旧文件已被原地覆盖，文件名/路径与 steps_data 引用均不变。
                        # 截图缺失态恢复时文件名回退取了 steps_data 历史名，这里
                        # 显式回写当前状态；旧拉框/坐标已不匹配新图，全部清掉
                        self.sidebar.remove_thumb_cache_by_filename(
                            screenshot_filename
                        )
                        self._current_screenshot_filename = screenshot_filename
                        self._current_screenshot_filepath = os.path.join(
                            self.gui_dir, screenshot_filename
                        )
                        self._screenshot_missing = False
                        self.coord_x_input.clear()
                        self.coord_y_input.clear()
                        self.coord2_x_input.clear()
                        self.coord2_y_input.clear()
                        self._current_vertices = None
                        self.canvas.clear_rect()
                        self._missing_live = None
                        self.validation_timer.stop()
                        if 0 <= self.current_step < len(self.steps_data):
                            # 已落表步：重算该下标并刷新侧栏标记/缩略图
                            self._invalidate_missing_slot(self.current_step)
                        else:
                            # 未确认新步的重截：刷新看板计数
                            self._refresh_live_slot()
                        self.sidebar.ensure_current_thumb()
                        self.schedule_draft_save()
                        self.status_label.setText("截图完成 - 请在图片上拉框标注目标区域，然后填写动作信息")
                    else:
                        # 从已落表步骤追加新步：当前游标还在旧步，必须先把旧步
                        # 现场落表（此时 _current_screenshot_filename 仍指向旧步
                        # 截图），再切换截图状态，否则旧步编辑内容丢失
                        appended_from_step = (
                            self._capture_append_new_step
                            and self.current_step < len(self.steps_data)
                        )
                        if appended_from_step:
                            # 编辑已完成任务时截图可能缺失，走编辑模式落表才能保住文本修改
                            if self._edit_mode:
                                self._save_current_to_steps_for_edit()
                            else:
                                self._save_current_to_steps()
                        self._current_screenshot_filename = screenshot_filename
                        self._current_screenshot_filepath = os.path.join(
                            self.gui_dir, screenshot_filename
                        )
                        self._screenshot_missing = False
                        if appended_from_step:
                            # 游标移到待确认空位，清表单/标注但保留刚截到的
                            # 画布内容与 _current_screenshot_* 引用
                            self.current_step = len(self.steps_data)
                            self._clear_inputs()
                            self.canvas.clear_rect()
                            self._update_step_label()
                            self._update_navigation_buttons()
                            self.sidebar.refresh_dashboard()
                            self.sidebar.refresh_highlight()
                            self.schedule_draft_save()
                            self.status_label.setText(
                                "已为下一步截图 - 请拉框标注并填写动作信息后确认"
                            )
                        elif self._capture_append_new_step:
                            # 已在待确认空位：沿用默认更新，只补草稿与提示
                            self.schedule_draft_save()
                            self.status_label.setText(
                                "已为下一步截图 - 请拉框标注并填写动作信息后确认"
                            )
                        else:
                            self.status_label.setText("截图完成 - 请在图片上拉框标注目标区域，然后填写动作信息")
                else:
                    # 保存被拒（非法文件名）或写盘失败：原地覆盖模式下旧图未被破坏，
                    # 不能静默无反应，否则用户以为重截已生效
                    self.status_label.setText("截图保存失败 - 请检查存储目录后重试")
            else:
                self.status_label.setText("截图加载失败")
        else:
            self.status_label.setText("截图失败 - 请检查 iPhone 连接（ios list 验证）")

        # B44 回归：回收上一张截图遗留的临时文件，避免长会话在临时目录逐张净增。
        # 本次截图的临时路径仍被 screenshot_cache 引用（swipe/scroll 测量依赖），
        # 保留不动；截图失败时缓存未推进，旧临时文件同样不删。
        keep_paths = {self.screenshot_cache, self._current_screenshot_filepath}
        if prev_tmp_path and prev_tmp_path not in keep_paths:
            try:
                if os.path.isfile(prev_tmp_path):
                    os.remove(prev_tmp_path)
            except OSError:
                pass

        # 无论成功与否都复位标记，避免失败后状态残留影响后续步骤
        self._replacing_screenshot = False
        self._capture_insert_after = None
        self._capture_append_new_step = False
        self._screenshot_in_progress = False

    def _delete_old_screenshot(self):
        """删除当前步骤的旧截图文件（如果未被其他步骤引用）"""
        self._delete_file_if_unreferenced(
            self._current_screenshot_filepath, ignore_current=True
        )

    def _reachable_screenshot_names(self, ignore_current=False):
        """收集仍被引用的截图文件名可达集（B16/B17 修复）

        可达集 = 当前 steps_data ∪ 已落轮 rounds 的 trajectory ∪ 当前在编截图。
        只查 steps_data 会误删已落轮仍在引用的 PNG；而编辑模式下
        steps_data 只含被编辑的那一轮、rounds 含全部轮，其中被编辑轮在
        rounds 内是加载时的陈旧副本，必须以 steps_data 为准，
        否则删步永远回收不掉截图（变孤儿文件）。

        :param ignore_current: 忽略「当前在编位置」的引用，即 steps_data
            [current_step] 与 _current_screenshot_filename。删除/撤销当前步时
            这条记录即将消失，不忽略就会「自己引用自己」，文件永远回收不掉。
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

    def _delete_file_if_unreferenced(self, path, ignore_current=False):
        """删除指定截图文件（仅当其未被任何步骤/已落轮引用时）

        :param ignore_current: 见 _reachable_screenshot_names；删当前步/撤销时传 True
        """
        if not path or not os.path.isfile(path):
            return

        # B16/B17 修复：可达集含 rounds 各轮 trajectory。原实现只遍历
        # steps_data（编辑模式下只含被编辑的那一轮），会删掉
        # 已落轮仍在引用的已交付 PNG，且无备份、不可恢复。
        name = os.path.basename(path)
        if name in self._reachable_screenshot_names(ignore_current=ignore_current):
            return

        try:
            os.remove(path)
        except Exception as e:
            print(f"删除旧截图失败: {e}")

    # ========== swipe 测量流程（参考 macOS scroll 测量）==========

    def _start_swipe_measurement(self):
        """开始测量滑动/拖拽：记录起点框，提示拉终点框"""
        if self.screenshot_cache is None:
            QMessageBox.warning(self, "提示", "请先截图！")
            return

        current_vertices = getattr(self, '_current_vertices', None)
        if not current_vertices:
            QMessageBox.warning(self, "提示", "请先在截图上拉框标注滑动/拖拽起点！")
            return

        self._swipe_measuring = True
        self._swipe_start_vertices = list(current_vertices)
        self.btn_swipe_measure.hide()
        self.status_label.setText(
            f"起点已记录 ({self.coord_x_input.text()},{self.coord_y_input.text()}) - 请直接拉第二个框标记终点"
        )

    def _finish_swipe_measurement(self):
        """完成滑动/拖拽测量"""
        if not self._swipe_start_vertices:
            return
        self._swipe_measuring = False
        self._swipe_start_vertices = None
        self.btn_swipe_finish.hide()
        self.btn_swipe_measure.show()
        self.status_label.setText("测量完成 - 起点和终点坐标已填入")

    def _cancel_swipe_measurement(self):
        """取消滑动/拖拽测量状态"""
        self._swipe_measuring = False
        self._swipe_start_vertices = None
        self.btn_swipe_measure.show()
        self.btn_swipe_finish.hide()

    # ========== scroll 测量流程（多次选择参照物，累积计算滚动像素）==========

    def _start_scroll_measurement(self):
        """开始测量滚动：记录第一个参照物的 Y 坐标"""
        if self.screenshot_cache is None:
            QMessageBox.warning(self, "提示", "请先截图！")
            return

        current_y = None
        try:
            y_text = self.coord_y_input.text().strip()
            if y_text:
                current_y = int(y_text)
        except (ValueError, TypeError):
            pass

        if current_y is None:
            QMessageBox.warning(self, "提示", "请先在截图上拉框标注一个参照物！")
            return

        # 保存第一个拉框的完整坐标
        current_x = None
        try:
            x_text = self.coord_x_input.text().strip()
            if x_text:
                current_x = int(x_text)
        except (ValueError, TypeError):
            pass
        
        self._scroll_first_coord = [current_x or 0, current_y]
        self._scroll_references = [current_y]
        self._scroll_measuring = True
        self._scroll_preserve_screenshot = True  # 保留第一张截图作为步骤截图
        self.btn_scroll_measure.hide()
        self.btn_scroll_finish.show()

        QMessageBox.information(self, "滚动测量",
            f"已获取第一个参照物 Y 坐标: {current_y}\n\n"
            "请在设备上滚动后，重新截图并选择同一个参照物拉框，\n"
            "系统将自动计算滚动像素。\n\n"
            "您可以多次选择来累积滚动距离，完成后点击 [完成测量]。")

    def _continue_scroll_measurement(self):
        """继续测量滚动：记录下一个参照物的 Y 坐标并计算累积像素"""
        current_y = None
        try:
            y_text = self.coord_y_input.text().strip()
            if y_text:
                current_y = int(y_text)
        except (ValueError, TypeError):
            pass

        if current_y is None:
            QMessageBox.warning(self, "提示", "请先在截图上拉框标注同一个参照物！")
            return

        self._scroll_references.append(current_y)

        # 计算累积滚动像素
        total_pixels = self._calculate_scroll_pixels()
        self.pixels_input.setText(str(total_pixels))

        self.btn_scroll_finish.show()

        QMessageBox.information(self, "滚动测量",
            f"已选择 {len(self._scroll_references)} 个参照物\n"
            f"当前累计滚动像素: {total_pixels}\n\n"
            "点击'继续测量'按钮可以继续添加参照物，\n"
            "或点击'完成测量'结束测量。")

    def _calculate_scroll_pixels(self):
        """根据参照物 Y 坐标列表计算累积滚动像素"""
        total_pixels = 0
        for i in range(1, len(self._scroll_references)):
            # 内容向上移动时参照物 Y 减小，故后一个减前一个得到负值
            diff = self._scroll_references[i] - self._scroll_references[i - 1]
            total_pixels += diff
        return total_pixels

    def _finish_scroll_measurement(self):
        """完成滚动测量"""
        if len(self._scroll_references) < 2:
            QMessageBox.warning(self, "提示", "至少需要选择两个参照物才能计算滚动距离！")
            return

        # 计算最终的滚动像素
        total_pixels = self._calculate_scroll_pixels()
        self.pixels_input.setText(str(total_pixels))

        # 恢复画布显示第一张截图（步骤截图）
        if self._current_screenshot_filepath and os.path.isfile(self._current_screenshot_filepath):
            pixmap = QPixmap(self._current_screenshot_filepath)
            if not pixmap.isNull():
                self.canvas.set_pixmap(pixmap)
                self.screenshot_cache = self._current_screenshot_filepath
                self.screenshot_name_label.setText(self._current_screenshot_filename)
                self.screenshot_size_label.setText(f"{pixmap.width()} x {pixmap.height()}")

        # 清理 scroll 测量期间产生的额外截图文件
        for extra_path in self._scroll_extra_screenshots:
            if extra_path and os.path.isfile(extra_path):
                try:
                    os.remove(extra_path)
                except Exception as e:
                    print(f"删除额外截图失败: {e}")

        self._scroll_measuring = False
        self._scroll_references = []
        self._scroll_preserve_screenshot = False
        self._scroll_extra_screenshots = []
        self._scroll_first_coord = None  # 清理第一个拉框的坐标
        self.btn_scroll_measure.show()
        self.btn_scroll_finish.hide()
        self.status_label.setText(f"滚动测量完成 - 滚动像素: {total_pixels}")

    def _cancel_scroll_measurement(self):
        """取消滚动测量状态，恢复画布显示第一张截图并清理多余文件"""
        # 清理 scroll 测量期间产生的额外截图文件
        for extra_path in self._scroll_extra_screenshots:
            if extra_path and os.path.isfile(extra_path):
                try:
                    os.remove(extra_path)
                except Exception as e:
                    print(f"删除额外截图失败: {e}")
        self._scroll_extra_screenshots = []

        # 恢复画布显示第一张截图
        if self._current_screenshot_filepath and os.path.isfile(self._current_screenshot_filepath):
            pixmap = QPixmap(self._current_screenshot_filepath)
            if not pixmap.isNull():
                self.canvas.set_pixmap(pixmap)
                self.screenshot_cache = self._current_screenshot_filepath
                self.screenshot_name_label.setText(self._current_screenshot_filename)
                self.screenshot_size_label.setText(f"{pixmap.width()} x {pixmap.height()}")

        self._scroll_measuring = False
        self._scroll_references = []
        self._scroll_preserve_screenshot = False
        self._scroll_first_coord = None  # 清理第一个拉框的坐标
        self.pixels_input.clear()
        self.btn_scroll_measure.show()
        self.btn_scroll_finish.hide()

    # ========== 在原图上重新拉框（编辑已完成任务） ==========

    def relabel_current_step(self):
        """编辑已完成任务：在当前步磁盘原截图上重新拖框（不重新截图、不覆盖 PNG）"""
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if self._screenshot_in_progress:
            return
        if not self._edit_mode:
            return
        if self._screenshot_missing:
            self.status_label.setText("当前步骤截图缺失，请先[重新截图]")
            return
        filename = self._current_screenshot_filename
        pixmap = None
        if filename and self.gui_number is not None:
            pixmap = self.data_manager.load_screenshot(self.gui_number, filename)
        if pixmap is None:
            # 与 _restore_step_to_ui 同口径的磁盘回退（按完整路径直读）
            filepath = self.screenshot_cache
            if filepath and os.path.exists(filepath):
                candidate = QPixmap(filepath)
                pixmap = None if candidate.isNull() else candidate
        if pixmap is None:
            self.status_label.setText("截图文件缺失，请使用[重新截图]")
            return
        # 弹窗拖框走普通动作语义，先取消进行中的测量态，
        # 避免拖出的框被当成滑动终点/滚动参照物，也避免清理额外截图时误删文件
        self._cancel_swipe_measurement()
        self._cancel_scroll_measurement()
        # 取消测量会用 set_pixmap 重设主画布（附带清空已绘框），补回当前框，
        # 保证取消弹窗时旧标注框的显示也原样保留
        if self._valid_vertices(self._current_vertices) is not None:
            self.canvas.restore_vertices(self._current_vertices)
        self._relabel_dialog = ReLabelDialog(pixmap, self)
        self._relabel_dialog.rect_confirmed.connect(self._on_relabel_rect)
        self._relabel_dialog.show()

    def _on_relabel_rect(self, left, top, right, bottom):
        """重新拉框确认：与 on_rect_drawn 普通分支等价 + 落表 + 主画布重绘"""
        if not (0 <= self.current_step < len(self.steps_data)):
            return
        vertices = [left, top, right, bottom]
        if self._valid_vertices(vertices) is None:
            return
        center_x = (left + right) // 2
        center_y = (top + bottom) // 2
        self._current_vertices = vertices
        self.coord_x_input.setText(str(center_x))
        self.coord_y_input.setText(str(center_y))
        # 主预览画布立即显示新框（弹窗内已清空旧框，回到主界面也应一致）
        self.canvas.restore_vertices(vertices)
        suffix = ""
        if self._swipe_start_vertices is not None or self.coord2_x_input.text():
            suffix = "（滑动/滚动动作仅更新起点，终点保持原值）"
        self.status_label.setText(
            f"已在原图上重新拉框: ({left},{top})-({right},{bottom})"
            f" | 中心点: ({center_x},{center_y}){suffix} - 请点击[保存修改]写回"
        )
        # 只改内存：落 steps_data（内部已失效缺项缓存）+ 重建侧栏，必须再点
        # [保存修改] 才会写 JSON/coords，全程不碰任何图片文件
        self._save_current_to_steps_for_edit()
        self.sidebar.rebuild_items()
        self._relabel_dialog = None

    # ========== 拉框标注 ==========

    def on_rect_drawn(self, left, top, right, bottom):
        """用户在截图上绘制矩形框后回调"""
        center_x = int((left + right) / 2)
        center_y = int((top + bottom) / 2)
        vertices = [left, top, right, bottom]

        current_action = self._current_action_key()

        # swipe/drag 测量流程：起点框已在“开始测量”时记录，这里记录终点框
        if current_action in SWIPE_ACTIONS and self._swipe_measuring:
            if not self._swipe_start_vertices:
                # 兜底：尚未记录起点时，先把当前框当作起点
                self._swipe_start_vertices = vertices
                self.coord_x_input.setText(str(center_x))
                self.coord_y_input.setText(str(center_y))
                self._current_vertices = vertices
                self.status_label.setText(
                    f"起点: ({center_x},{center_y}) - 请再拉第二个框标记终点"
                )
            else:
                # 记录终点
                self.coord2_x_input.setText(str(center_x))
                self.coord2_y_input.setText(str(center_y))
                self._current_vertices = self._swipe_start_vertices  # 保持起点顶点
                self.btn_swipe_finish.show()
                self.status_label.setText(
                    f"终点: ({center_x},{center_y}) - 起点: ({self.coord_x_input.text()},{self.coord_y_input.text()}) - 点击 [完成测量]"
                )
            return

        # scroll 测量流程：拉框后自动记录参照物 Y 坐标
        if current_action in SCROLL_ACTIONS and self._scroll_measuring:
            # 不更新坐标输入框，保持第一个拉框的坐标
            # self._current_vertices = vertices  # 不更新顶点
            # self.coord_x_input.setText(str(center_x))  # 不更新x坐标
            # self.coord_y_input.setText(str(center_y))  # 不更新y坐标
            # 自动记录参照物（只记录Y坐标用于计算滚动像素）
            self._scroll_references.append(center_y)
            total_pixels = self._calculate_scroll_pixels()
            self.pixels_input.setText(str(total_pixels))
            ref_count = len(self._scroll_references)
            self.status_label.setText(
                f"参照物 #{ref_count}: ({center_x},{center_y}) | 累计滚动像素: {total_pixels} - 请滚动后截图继续选择，或点击 [完成测量]"
            )
            return

        # 普通动作：填入坐标
        self._current_vertices = vertices
        self.coord_x_input.setText(str(center_x))
        self.coord_y_input.setText(str(center_y))
        self.status_label.setText(f"拉框区域: ({left},{top})-({right},{bottom}) | 中心点: ({center_x},{center_y})")

    # ========== 步骤导航 ==========

    def _collect_step_data(self):
        """从当前界面收集步骤数据（不保存到列表）"""
        action_data = self._build_action_data()
        return {
            "screenshot": self._current_screenshot_filename or "",
            "screenshot_filepath": self._current_screenshot_filepath or "",
            "intent": self.intent_input.text().strip(),
            "action_data": action_data,
            "vertices": list(self._current_vertices) if self._current_vertices else None
        }

    def _invalidate_missing_slot(self, index=None):
        """落表/切步后失效重算某个已落表下标（等长也重算）；
        缓存长度漂移时退化为全量；同时清空未确认新步实时槽。"""
        self._missing_live = None
        if len(self._missing_cache) != len(self.steps_data):
            self.revalidate_all_missing()
            return
        if index is None or not (0 <= index < len(self.steps_data)):
            return
        reasons = self.validate_step_at(index)
        self._missing_cache[index] = reasons
        if index < len(self.sidebar.item_widgets):
            self.sidebar.item_widgets[index].set_missing(reasons)
        self.sidebar.refresh_dashboard()

    def _save_current_to_steps(self):
        """将当前界面数据保存到 steps_data 中对应位置"""
        if self._current_screenshot_filename is None:
            return  # 没有截图，不保存
        step_data = self._collect_step_data()
        if self.current_step < len(self.steps_data):
            # 更新已有步骤（覆盖编辑后的数据）
            self.steps_data[self.current_step] = step_data
        else:
            # 新增步骤
            self.steps_data.append(step_data)
        # 落表即终态：同步该步缺项缓存（等长 update 与 append 漂移都重算），
        # 避免 300ms 防抖窗口内立即确认/跳转/撤销/完成任务时读到陈旧结果
        self._invalidate_missing_slot(self.current_step)

    def _save_current_to_steps_for_edit(self):
        """编辑模式落表：截图文件缺失时保留原文件名，仍收集 intent/动作/顶点。

        _collect_step_data 在 _current_screenshot_filename 为 None 时会给出空
        screenshot，导致缺图步骤的文本修改无法保存；这里用原步文件名覆盖。
        """
        if not (0 <= self.current_step < len(self.steps_data)):
            return
        step_data = self._collect_step_data()
        if self._current_screenshot_filename is None:
            old = self.steps_data[self.current_step]
            filename = old.get("screenshot", "")
            step_data["screenshot"] = filename
            step_data["screenshot_filepath"] = (
                os.path.join(self.gui_dir, filename)
                if filename and self.gui_dir else ""
            )
        # hydration 登记的「框丢失/框与坐标不一致」标记不属 _collect_step_data 的
        # 五个键，不在这里回贴就会被一次普通导航抹掉，写回时的「保留盘上原条目」
        # 分支（见 save_edited_round）随即失效；用户已重新拉到合法框则双双清空。
        prev = self.steps_data[self.current_step]
        if self._valid_vertices(step_data.get("vertices")) is not None:
            step_data["coord_issue"] = None
            step_data["orig_coord_entry"] = None
        else:
            step_data["coord_issue"] = prev.get("coord_issue")
            step_data["orig_coord_entry"] = prev.get("orig_coord_entry")
        self.steps_data[self.current_step] = step_data
        self._invalidate_missing_slot(self.current_step)

    def _restore_step_to_ui(self, step_data):
        """将步骤数据恢复到界面"""
        self._clear_inputs()

        # 恢复截图显示：内存解耦后统一从磁盘按文件名重新加载
        filename = step_data.get("screenshot", "")
        filepath = step_data.get("screenshot_filepath", "")
        if not filepath and filename and self.gui_dir:
            filepath = os.path.join(self.gui_dir, filename)
        pixmap = None
        if filename and self.gui_number is not None:
            pixmap = self.data_manager.load_screenshot(self.gui_number, filename)
        if pixmap is None and filepath and os.path.exists(filepath):
            pixmap = QPixmap(filepath)
            if pixmap.isNull():
                pixmap = None
        self._screenshot_missing = False
        if pixmap is not None:
            self.canvas.set_pixmap(pixmap)
            self.screenshot_cache = filepath
            self._current_screenshot_filename = filename
            self._current_screenshot_filepath = filepath
            self.screenshot_name_label.setText(filename)
            self.screenshot_size_label.setText(f"{pixmap.width()} x {pixmap.height()}")
            # 恢复绿色标注框
            vertices = step_data.get("vertices")
            if self._valid_vertices(vertices) is not None:
                self.canvas.restore_vertices(vertices)
        else:
            # 截图文件丢失：进入明确的“截图缺失”态。filename 置 None 以阻止
            # _save_current_to_steps 误落表覆盖历史数据；编辑内容仍照常恢复
            self.canvas.clear_rect()
            self.canvas.set_pixmap(None)
            self.screenshot_cache = None
            self._current_screenshot_filename = None
            self._current_screenshot_filepath = None
            if filename:
                self._screenshot_missing = True
                self.screenshot_name_label.setText(f"{filename}（截图文件缺失，请重新截图）")
                self.screenshot_size_label.setText("截图缺失")
                self.status_label.setText("截图文件缺失，请重新截图后再确认")

        # 恢复动作字段
        self.intent_input.setText(step_data.get("intent", ""))
        action_data = step_data.get("action_data", {})
        action = action_data.get("action", "click")
        idx = self.action_combo.findData(action)
        if idx >= 0:
            self.action_combo.setCurrentIndex(idx)

        if action in SWIPE_ACTIONS:
            start_coord = self._valid_coord_pair(action_data.get("start_coordinate"))
            if start_coord is not None:
                self.coord_x_input.setText(str(start_coord[0]))
                self.coord_y_input.setText(str(start_coord[1]))

            end_coord = self._valid_coord_pair(action_data.get("coordinate"))
            if end_coord is not None:
                self.coord2_x_input.setText(str(end_coord[0]))
                self.coord2_y_input.setText(str(end_coord[1]))
        else:
            coord = self._valid_coord_pair(action_data.get("coordinate"))
            if coord is not None:
                self.coord_x_input.setText(str(coord[0]))
                self.coord_y_input.setText(str(coord[1]))

        text_val = action_data.get("text")
        if isinstance(text_val, str):
            self.text_input.setText(text_val)
        time_val = action_data.get("time")
        if self._is_valid_number(time_val):
            self.time_input.setText(str(time_val))

        # 恢复滚动像素（0 为合法测量结果，仍如实回填）
        pixels_val = action_data.get("pixels")
        if self._is_valid_number(pixels_val):
            self.pixels_input.setText(str(pixels_val))

        buttons = action_data.get("buttons", [])
        if isinstance(buttons, (list, tuple)) and buttons:
            bidx = self.button_combo.findText(str(buttons[0]))
            if bidx >= 0:
                self.button_combo.setCurrentIndex(bidx)

        self._current_vertices = self._valid_vertices(step_data.get("vertices"))

    def confirm_step(self):
        """确认当前步骤，保存并进入下一步（创建新步骤）"""
        # B2：切轮窗口内的再次确认会用旧指令重复落轮（_save_current_round_to_list
        # 只要 steps_data 非空就 append），直接拒绝
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if self._edit_mode:
            # 编辑已完成任务：只落当前步，不切轮、不结束任务、不询问新任务
            self._save_current_to_steps_for_edit()
            self._cancel_swipe_measurement()
            self._cancel_scroll_measurement()
            self.sidebar.rebuild_items()
            self.status_label.setText(f"已更新第 {self.current_step + 1} 步")
            return

        if self._current_screenshot_filename is None:
            if self._screenshot_missing:
                QMessageBox.warning(self, "提示", "截图文件缺失，请重新截图！")
            else:
                QMessageBox.warning(self, "提示", "请先截图！")
            return

        # 终止类动作必须是本轮最后一个步骤：answer/answer_terminate/terminate
        # 会立即落轮或收尾，若后面还留着已落表步骤，这些步骤既不会被本次确认
        # 提交，也不会进入下一轮，会在切轮/清空时静默丢失。
        # current_step == len(steps_data) 的待确认空位不属于“后面还有步骤”，放行。
        current_action = self._current_action_key()
        if (
            current_action in ("answer", "answer_terminate", "terminate")
            and 0 <= self.current_step < len(self.steps_data) - 1
        ):
            remaining = len(self.steps_data) - 1 - self.current_step
            QMessageBox.warning(
                self, "提示",
                f"「{action_cn_name(current_action)}」必须是本轮最后一个步骤。\n"
                f"当前第 {self.current_step + 1} 步之后还有 {remaining} 个步骤，"
                "请先删除或撤销这些步骤后再确认。"
            )
            return

        if not self._validate_step():
            return

        # 先保存当前步骤（_cancel_scroll_measurement 会清空 pixels_input，
        # 若先清理再保存会导致滚动像素丢失为 0）
        self._save_current_to_steps()

        # 取消 swipe/scroll 测量状态
        self._cancel_swipe_measurement()
        self._cancel_scroll_measurement()

        # answer 动作：保存当前轮次到 rounds 列表，然后开始新轮次（不结束任务）
        if current_action == "answer":
            # 300ms singleShot 切轮窗口内立即同步落表/重算并停掉防抖，
            # 防止窗口内串步或缺项结论丢失
            self.validation_timer.stop()
            self._missing_live = None
            if not self._save_current_round_to_list():
                # B14：缺指令且未补齐 → 本轮不落，也不能升门闩弹新轮对话框，
                # 否则 _start_new_round 会把这条未落轮的 steps_data 直接清空
                return
            # 升起门闩，300ms 切轮窗口内禁止截图/确认（B2）
            self._round_transition_pending = True
            QTimer.singleShot(300, lambda: self._start_new_round(from_answer=True))
            return

        # answer+terminate 动作：填写回答文本后结束任务（action 字段仍记录为 answer）
        if current_action == "answer_terminate":
            self._finish_task()
            return

        # terminate 动作：任务完成
        if current_action == "terminate":
            self._finish_task()
            return

        # 2.8（B22）：确认后游标只前进一格，不得越过末尾的待截图空位（Android 同批移植）。
        # 原实现无条件把游标推到 len(steps_data)：回看中间某步改完确认后，用户被
        # 静默传送到末尾，正在核对的表单也被清空，只能重新截图才能续采。
        saved_index = self.current_step
        total = len(self.steps_data)
        if saved_index + 1 < total:
            # 编辑历史步后确认：前进一格到下一已有步，现场完整回填、不清表单
            self.current_step = saved_index + 1
            self._restore_step_to_ui(self.steps_data[self.current_step])
            self._update_step_label()
            self._update_navigation_buttons()
            self.sidebar.refresh_step_item(saved_index)
            self.sidebar.invalidate_thumb(saved_index)
            self.sidebar.request_thumb(saved_index, high_priority=True)
            self.sidebar.refresh_highlight()
            self.sidebar.ensure_current_thumb()
            self._invalidate_missing_slot(self.current_step)
            self.schedule_draft_save()
            self.status_label.setText(
                f"已更新第 {saved_index + 1} 步，步骤 {self.current_step} - 可继续编辑"
            )
            return

        # 追加新步/确认末步：创建末尾待截图空位（原行为）
        new_index = total
        self.current_step = new_index
        self._reset_for_next_step()
        # 300+ 步场景下增量追加条目，避免全量重建（首次确认时列表为空也必须创建）。
        # 插入分支已 rebuild_items，历史步再确认时条目数已齐，重复 _create_item
        # 会多出一个重复侧栏条目，故仅在条目数不足时补建
        if len(self.sidebar.item_widgets) < new_index:
            self.sidebar._create_item(new_index - 1)
        self.sidebar.refresh_highlight()
        self.sidebar.refresh_dashboard()
        self.schedule_draft_save()
        self.status_label.setText(f"步骤 {self.current_step} - 请截图并标注")

    def go_previous(self):
        """回到上一步，自动保存当前步骤并恢复上一步数据"""
        if self.current_step <= 0:
            return
        if self._edit_mode:
            self._save_current_to_steps_for_edit()
        else:
            self._save_current_to_steps()
        self.display_step(self.current_step - 1)
        self.status_label.setText(f"步骤 {self.current_step} - 可继续编辑")

    def undo_last_step(self):
        """撤销上一步：删除当前步骤数据并回到上一步（复用删除流程）"""
        # B2：切轮窗口内不得删改已落轮的数据
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        if not self.steps_data:
            QMessageBox.information(self, "提示", "没有可撤销的步骤")
            return

        reply = QMessageBox.question(
            self, "确认撤销",
            "确定要撤销当前步骤吗？\n这将删除当前步骤的数据。",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.delete_current_step(confirm_dialog=False)

    def go_next(self):
        """进入下一步"""
        # 验证：未截图时禁止进入下一步（编辑模式允许截图缺失继续编辑）
        if self._current_screenshot_filename is None and not self._edit_mode:
            QMessageBox.warning(self, "提示", "请先截图再进行下一步操作！")
            return

        # 自动保存当前步骤编辑内容
        if self._edit_mode:
            self._save_current_to_steps_for_edit()
        else:
            self._save_current_to_steps()

        if self.current_step + 1 < len(self.steps_data):
            # 前方已有步骤，直接导航过去
            self.display_step(self.current_step + 1)
            self.status_label.setText(f"步骤 {self.current_step} - 可继续编辑")
        else:
            # 在最后一步，需要创建新步骤（编辑模式下被 confirm_step 拦截）
            self.confirm_step()

    # ========== 步骤导航（侧栏/上一步/下一步统一出口）==========

    def display_step(self, index):
        """保存当前 UI 编辑并切换到指定步骤（侧栏点击/上下步跳转统一走这里）"""
        if not (0 <= index < len(self.steps_data)):
            return
        if self._edit_mode:
            self._save_current_to_steps_for_edit()
        else:
            self._save_current_to_steps()
        self.current_step = index
        self._restore_step_to_ui(self.steps_data[index])
        self._update_step_label()
        self._update_navigation_buttons()
        # 切步后重算目标下标（恢复的 UI 为 live 口径）并刷新看板/缩略图
        self._invalidate_missing_slot(index)
        self.sidebar.refresh_highlight()
        self.sidebar.ensure_current_thumb()

    def jump_to_step(self, index):
        """侧栏条目/跳转按钮入口"""
        if 0 <= index < len(self.steps_data):
            self.display_step(index)
            self.status_label.setText(f"步骤 {index} - 可继续编辑")

    def delete_current_step(self, confirm_dialog=True):
        """删除当前步骤：删 steps_data 记录与截图文件，后一步回填表单"""
        if self._round_transition_pending:
            self.status_label.setText("轮次切换中，请稍候...")
            return
        index = self.current_step
        if not (0 <= index < len(self.steps_data)):
            # current_step == len(steps_data) 且已截图：在采未确认的新步。
            # 撤销/删除该编辑位时丢弃 pending 截图并回到最后已确认步，
            # 不弹确认框/提示框，也不调用 _save_current_to_steps（防止幻影追加）
            pending_filename = self._current_screenshot_filename
            if not pending_filename:
                QMessageBox.information(self, "提示", "当前没有可删除的步骤")
                return
            pending_path = self._current_screenshot_filepath or ""

            # 1. 先取消 swipe/scroll 测量（scroll 会顺带清理 extra 截图并恢复首图）
            self._cancel_swipe_measurement()
            self._cancel_scroll_measurement()

            # 2. 失效缩略图缓存，并按引用可达集回收 pending 截图文件（B16/B17）
            #    pending 就是 _current_screenshot_filename，须按位置忽略它自己
            self.sidebar.remove_thumb_cache_by_filename(pending_filename)
            self._delete_file_if_unreferenced(pending_path, ignore_current=True)

            # 3. 回到最后已确认步（直接恢复 UI，不落表、不导航）；删空则回初始态
            if self.steps_data:
                target = len(self.steps_data) - 1
                self.current_step = target
                self._restore_step_to_ui(self.steps_data[target])
            else:
                self.current_step = 0
                self._reset_for_next_step()

            self._update_step_label()
            self._update_navigation_buttons()
            # pending 删除后步数不变（漂移兜底不触发），强制全量重算并清 live 槽
            self.revalidate_all_missing()
            self.sidebar.rebuild_items()
            self.schedule_draft_save()
            self.status_label.setText(
                f"已丢弃未确认截图 - 当前步骤: {self.current_step}"
            )
            return

        if confirm_dialog:
            reply = QMessageBox.question(
                self, "确认删除",
                f"确定删除第 {index + 1} 步吗？\n后续步骤会自动前移，截图序号保留空洞。",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        step = self.steps_data[index]
        path = step.get("screenshot_filepath") or ""
        filename = step.get("screenshot") or ""

        # B16/B17 修复：删盘判定须在移除步骤之前做。此刻 current_step==index
        # 精确指向被删步，ignore_current 按位置忽略它自己；若先 del 再判定，
        # index 会落到「原下一步」，位置忽略将误把幸存步排除出可达集。
        # 只比对 steps_data 会误删已落轮 rounds 仍在引用的已交付 PNG，故可达集
        # 含 rounds 各轮 trajectory；_current_screenshot_filename 此刻亦仍指向被删步。
        self._delete_file_if_unreferenced(path, ignore_current=True)
        del self.steps_data[index]
        self.sidebar.remove_thumb_cache_by_filename(filename)

        # 定位到删除后应停留的步骤
        if self.steps_data:
            target = min(index, len(self.steps_data) - 1)
            self.current_step = target
            self._restore_step_to_ui(self.steps_data[target])
        else:
            # 删空：回到初始空白态
            self.current_step = 0
            self._reset_for_next_step()

        self._cancel_swipe_measurement()
        # 5.8（B45）防御式成对取消：删步后无论走哪条分支都必须退出 scroll 长滑
        # 测量态。注：本端两条分支都会先调 _clear_inputs()（_restore_step_to_ui:1728 /
        # _reset_for_next_step:2845），而 _clear_inputs 已自带 swipe+scroll 取消，
        # 故此行在 iOS 上不可单独观测（写变异用例会是假绿）；保留它是为了
        # 与 Android/Windows 同名分支保持口径一致，并防止日后有人拆掉 _clear_inputs。
        self._cancel_scroll_measurement()
        self._update_step_label()
        self._update_navigation_buttons()
        self.sidebar.rebuild_items()
        self.schedule_draft_save()
        self.status_label.setText(f"已删除第 {index + 1} 步 - 当前步骤: {self.current_step}")

    def build_marked_preview(self, filename, vertices, target_size):
        """从磁盘加载截图并绘制红框标注，缩放到缩略图尺寸（不缓存全屏原图）"""
        if self.gui_number is None or not filename:
            return None
        pixmap = self.data_manager.load_screenshot(self.gui_number, filename)
        if pixmap is None or pixmap.isNull():
            return None
        try:
            marked = QPixmap(pixmap)
            painter = QPainter(marked)
            painter.setPen(QPen(QColor(229, 57, 53), 4))
            painter.setBrush(QColor(229, 57, 53, 30))
            if vertices and len(vertices) == 4:
                left, top, right, bottom = vertices
                painter.drawRect(QRect(left, top, right - left, bottom - top))
            painter.end()

            if not isinstance(target_size, QSize) or target_size.width() <= 0:
                target_size = QSize(200, 112)
            return marked.scaled(
                target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        except Exception as e:
            print(f"构建缩略图失败: {e}")
            return pixmap.scaled(
                target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )

    def show_round_preview_dialog(self):
        """工具栏入口：只读回看已完成轮次"""
        if not self.rounds:
            return
        RoundPreviewDialog(self).exec_()

    # ========== 必填校验（支持任意下标，供侧栏缺项标记与结束前全量校验）==========

    @classmethod
    def _find_coord_entry(cls, coords, step):
        """在该轮 coords 中按 step 精确查找条目；未命中返回 None

        旧写法在按 step 落空时回退取 round_coords[i]。位置相同不代表内容
        相关——旧交付件 coords 少几条时下标整体漂移，编辑态由此冒领
        别的工作的顶点，写回时把污染 bbox 以正确 step 编号落盘。位置猜测
        不可挽救，彻底删除，改由 _find_coord_entry_by_center 做有根据的恢复。
        step 取值沿用本端 _coord_step_of 的归一化口径（接受整浮点/数字串，
        排除 bool）；无法确定步序时不做任何认领。
        """
        if step is None or not coords:
            return None
        for entry in coords:
            if not isinstance(entry, dict):
                continue
            if cls._coord_step_of(entry) == step:
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
        if action not in COORD_ACTIONS:
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
        raw_vertices = (coord_entry.get("vertices")
                        if isinstance(coord_entry, dict) else None)
        vertices = cls._valid_vertices(raw_vertices)

        if action not in COORD_ACTIONS:
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
        """获取某步骤的校验快照：当前编辑步且尚未落表时实时收集 UI 数据"""
        if index == self.current_step and self._current_screenshot_filename:
            return self._collect_step_data()
        if 0 <= index < len(self.steps_data):
            return self.steps_data[index]
        return None

    def validate_step_at(self, index):
        """校验任意下标步骤，返回缺失原因中文列表（空列表表示通过）。
        live 步（当前正在编辑且截图有效）从 UI 实时解析，拒绝 NaN/Inf/abc/空串；
        历史步读取已落表数据，显式存在的 0/[0,0]/1.0 等视为用户数据。
        """
        is_live = (
            index == self.current_step
            and bool(self._current_screenshot_filename)
            and not self._screenshot_missing
        )
        step = self._step_snapshot(index)
        reasons = []
        if not step:
            return ["步骤数据缺失"]

        filename = step.get("screenshot")
        if not filename:
            if index == self.current_step and self._screenshot_missing:
                reasons.append("截图文件缺失，请重新截图")
            else:
                reasons.append("缺少截图")
        elif not is_live:
            # 历史步（含结束前全量扫描）：文件被删/移走也要判缺
            filepath = step.get("screenshot_filepath") or ""
            if not filepath and self.gui_dir:
                filepath = os.path.join(self.gui_dir, filename)
            if filepath and not os.path.isfile(filepath):
                reasons.append("截图文件缺失，请重新截图")

        action_data = step.get("action_data") or {}
        action = action_data.get("action", "")
        vertices = step.get("vertices")
        live_vertices = self._valid_vertices(
            self._current_vertices if is_live else vertices
        )
        # hydration 已判定该步「盘上框丢失/框与坐标值不一致」时不阻塞重拉框：
        # 强迫重拉会连带改写已交付的 coordinate（与 Windows A6 同一取舍）；
        # 该步的盘上条目由 save_edited_round 原样保留。is_live 时
        # _step_snapshot 只回五个键，必须回查 steps_data 才拿得到标记。
        stored = (self.steps_data[index]
                  if 0 <= index < len(self.steps_data) else {})
        inherited_box_lost = (isinstance(stored, dict)
                              and stored.get("coord_issue") in ("absent", "mismatch"))

        # 坐标动作：需要 coordinate（scroll 同样要求先在首图拉框）
        if action in COORD_ACTIONS:
            if action in SWIPE_ACTIONS:
                if is_live:
                    sx = self._parse_int(self.coord_x_input.text().strip())
                    sy = self._parse_int(self.coord_y_input.text().strip())
                    ex = self._parse_int(self.coord2_x_input.text().strip())
                    ey = self._parse_int(self.coord2_y_input.text().strip())
                    has_start = self._is_valid_number(sx) and self._is_valid_number(sy)
                    has_end = self._is_valid_number(ex) and self._is_valid_number(ey)
                else:
                    has_start = self._valid_coord_pair(action_data.get("start_coordinate")) is not None
                    has_end = self._valid_coord_pair(action_data.get("coordinate")) is not None
                if live_vertices is None and not inherited_box_lost:
                    reasons.append("缺少起点拉框")
                if not has_start:
                    reasons.append("缺少起点坐标")
                if not has_end:
                    reasons.append("缺少终点坐标")
            else:
                if is_live:
                    x = self._parse_int(self.coord_x_input.text().strip())
                    y = self._parse_int(self.coord_y_input.text().strip())
                    has_coord = self._is_valid_number(x) and self._is_valid_number(y)
                else:
                    has_coord = self._valid_coord_pair(action_data.get("coordinate")) is not None
                if live_vertices is None and not inherited_box_lost:
                    reasons.append("缺少拉框区域")
                if not has_coord:
                    reasons.append("缺少坐标")

        if action in SCROLL_ACTIONS:
            if is_live:
                pixels = self._parse_int(self.pixels_input.text().strip())
                has_pixels = self._is_valid_number(pixels)
            else:
                # 0 是合法测量结果；键存在且为有限数即视为已测量
                has_pixels = self._is_valid_number(action_data.get("pixels"))
            if not has_pixels:
                reasons.append("缺少滚动像素")

        if action in TEXT_ACTIONS:
            if is_live:
                text = self.text_input.text().strip()
            else:
                text = action_data.get("text")
                text = text.strip() if isinstance(text, str) else ""
            if not text:
                label_map = {
                    "type": "缺少输入文本",
                    "answer": "缺少回答内容",
                    "answer_terminate": "缺少回答内容",
                    "open_app": "缺少应用名称",
                    "open_url": "缺少网址 URL",
                }
                reasons.append(label_map.get(action, "缺少文本"))

        if action in TIME_ACTIONS:
            if is_live:
                has_time = self._parse_float(self.time_input.text().strip()) is not None
            else:
                has_time = self._is_valid_number(action_data.get("time"))
            if not has_time:
                reasons.append("缺少等待时间")

        if action in BUTTON_ACTIONS:
            if is_live:
                has_button = self.button_combo.currentText().strip() in SYSTEM_BUTTONS
            else:
                buttons = action_data.get("buttons")
                has_button = (
                    isinstance(buttons, (list, tuple))
                    and len(buttons) > 0
                    and str(buttons[0]) in SYSTEM_BUTTONS
                )
            if not has_button:
                reasons.append("缺少系统按钮选择")

        return reasons

    def get_cached_missing(self, index):
        """读取某步缺失项缓存；下标越界/缓存未建立时返回 None（区别于空列表“无缺失”）"""
        if 0 <= index < len(self._missing_cache):
            return self._missing_cache[index]
        return None

    def revalidate_all_missing(self):
        """全量重算缺项并刷新侧栏标记与看板"""
        self._missing_cache = [
            self.validate_step_at(i) for i in range(len(self.steps_data))
        ]
        self._missing_live = None
        for i, item in enumerate(self.sidebar.item_widgets):
            if i < len(self._missing_cache):
                item.set_missing(self._missing_cache[i])
        self.sidebar.refresh_dashboard()

    def live_missing_reasons(self):
        """未确认新步（current_step == len 且已截图）的实时缺项；无该槽返回 None。
        惰性计算一次并缓存，避免 resize/看板频繁刷新时反复实时校验。"""
        if not (
            self.current_step == len(self.steps_data)
            and self._current_screenshot_filename
        ):
            self._missing_live = None
            return None
        if self._missing_live is None:
            self._missing_live = self.validate_step_at(self.current_step)
        return self._missing_live

    def _on_validation_debounced(self):
        """输入防抖后：重算当前步缺项（缓存漂移则退化为全量）。
        current_step == len 的未确认新步同样实时校验并计入看板。"""
        if len(self._missing_cache) != len(self.steps_data):
            self.revalidate_all_missing()
            self._refresh_live_slot()
            return
        self._missing_live = None
        if 0 <= self.current_step < len(self.steps_data):
            reasons = self.validate_step_at(self.current_step)
            self._missing_cache[self.current_step] = reasons
            if self.current_step < len(self.sidebar.item_widgets):
                self.sidebar.item_widgets[self.current_step].set_missing(reasons)
            self.sidebar.refresh_dashboard()
            # 坐标变化时刷新当前步缩略图红框
            self.sidebar.ensure_current_thumb()
        else:
            # 未确认新步：不建侧栏条目（INV-8 item_widgets 严格等长），
            # 只把缺项并入看板计数
            self._refresh_live_slot()

    def _refresh_live_slot(self):
        """重算并展示未确认新步缺项槽（看板计数）"""
        self._missing_live = None
        self.live_missing_reasons()
        self.sidebar.refresh_dashboard()

    def _show_validation_fail_dialog(self, missing_list):
        """弹出缺项对话框并按用户选择跳转"""
        dialog = ValidationFailDialog(missing_list, self)
        if dialog.exec_() == QDialog.Accepted and dialog.target_index() is not None:
            self.jump_to_step(dialog.target_index())

    # ========== 草稿自动保存 / 断点续采 ==========

    def schedule_draft_save(self):
        """防抖触发草稿落盘（确认步/删除/插入/新指令等变化点调用）"""
        if self._edit_mode:
            return  # 编辑已完成任务不产生 draft
        if self.gui_number is None or self._draft_discarded:
            return
        self.sidebar.set_draft_saving()
        self.draft_timer.start()

    def _write_draft_now(self):
        """立即把当前进度写入 gui_XXXXXX_draft.json（steps_data 只保留可序列化字段）"""
        if self._edit_mode:
            return  # 编辑已完成任务不产生 draft
        if self.gui_number is None or self._draft_discarded:
            return

        # 已落表步骤序列化；当前正在编辑的步用实时 UI 数据，保证草稿不滞后
        serializable_steps = []
        for i in range(len(self.steps_data)):
            if i == self.current_step and self._current_screenshot_filename:
                step = self._collect_step_data()
            else:
                step = self.steps_data[i]
            serializable_steps.append(self._serialize_step(step))
        # 仅当当前步是尚未落表的新步时才追加，避免编辑/回看已存在步时草稿重复
        if self._current_screenshot_filename and self.current_step >= len(self.steps_data):
            serializable_steps.append(self._serialize_step(self._collect_step_data()))

        if not serializable_steps and not self.rounds:
            # 5.1（B37）空现场（撤销/删除清空全部步骤）必须删掉磁盘上的残留草稿，
            # 只 return 会让已删步骤在下次续采 load_from_draft 时整批复活。
            # 口径对齐 Android _write_draft_now 的同名分支。
            self.data_manager.delete_draft(self.gui_number)
            self.sidebar.set_draft_saved()
            return

        draft = {
            "gui_number": self.gui_number,
            "app_name": self.app_name,
            "task_instruction": self.task_instruction,
            "screen_info": self.screen_info,
            "app_type": self.app_type,
            "rounds": self.rounds,
            "steps_data": serializable_steps,
            "current_step_index": self.current_step,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        saved_path = self.data_manager.save_draft(draft, self.gui_number)
        if saved_path:
            self.sidebar.set_draft_saved()

    @staticmethod
    def _serialize_step(step):
        """steps_data 序列化：剔除运行时绝对路径，只保留磁盘文件名等可 JSON 化字段"""
        result = {}
        for key, value in step.items():
            if key == "screenshot_filepath":
                continue  # 不持久化绝对路径，载入时由 gui_dir + 文件名重建
            try:
                import json as _json
                _json.dumps(value, ensure_ascii=False)
                result[key] = copy.deepcopy(value)
            except (TypeError, ValueError):
                result[key] = None
        return result

    def load_from_draft(self, draft):
        """从草稿恢复编辑器状态；不新建任何 gui 目录。
        返回 True 表示当前轮步骤为空但已有历史轮次，需要向用户追问下一条指令。
        """
        if not draft:
            return False

        self.gui_number = str(draft.get("gui_number", "")).zfill(6)
        self.gui_dir = os.path.join(self.data_manager.current_dir, f"gui_{self.gui_number}")
        self._draft_discarded = False
        self.app_name = draft.get("app_name", self.app_name)
        self.task_instruction = draft.get("task_instruction", "")
        if isinstance(draft.get("screen_info"), dict):
            self.screen_info = draft["screen_info"]
        self.app_type = draft.get("app_type", self.app_type)
        self.rounds = copy.deepcopy(draft.get("rounds", []))

        self.steps_data = []
        for raw in draft.get("steps_data", []):
            step = copy.deepcopy(raw)
            filename = step.get("screenshot", "")
            step["screenshot_filepath"] = (
                os.path.join(self.gui_dir, filename) if filename else ""
            )
            if filename and not os.path.isfile(step["screenshot_filepath"]):
                print(f"草稿截图文件缺失: {filename}")
            self.steps_data.append(step)

        total = len(self.steps_data)
        self.current_step = max(0, min(int(draft.get("current_step_index", 0)), max(total - 1, 0)))

        self.setWindowTitle(f"GUI长步骤采标工具-iOS - {self.app_name}（续采）")

        if self.steps_data:
            self._restore_step_to_ui(self.steps_data[self.current_step])
        else:
            self._reset_for_next_step()

        self._update_step_label()
        self._update_navigation_buttons()
        # 草稿整体替换了 steps_data，旧缓存可能等长但内容陈旧，重置后由
        # rebuild_items 在长度不符时兜底全量重算
        self._missing_cache = []
        self._missing_live = None
        self.validation_timer.stop()
        self.sidebar.rebuild_items()
        self.schedule_draft_save()

        # 步骤为空但 rounds 非空：上一轮已收尾，等待下一条指令
        return (not self.steps_data) and bool(self.rounds)

    # ========== 已完成任务再编辑 ==========

    @staticmethod
    def _coord_round_of(entry):
        """从 coords 条目读取可用整数 round；无/非法返回 None"""
        value = entry.get("round")
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
        return None

    @staticmethod
    def _coord_step_of(entry):
        """从 coords/trajectory 条目读取可用整数 step；无/非法返回 None"""
        value = entry.get("step")
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
        return None

    def _coord_matches_round(self, entry, round_data):
        """按 (step, action) 判断 coords 条目是否属于某轮轨迹"""
        step = self._coord_step_of(entry)
        if step is None:
            return False
        action = entry.get("action")
        for traj in round_data.get("trajectory") or []:
            if self._coord_step_of(traj) != step:
                continue
            actions = traj.get("actions") or []
            traj_action = actions[0].get("action") if actions else None
            if action is None or traj_action == action:
                return True
        return False

    def _group_coords_into_rounds(self, coords_entries, rounds):
        """把 coords 条目归属到各轮次，返回与 rounds 等长的分组列表。

        新格式按 round 分组；旧格式按 step 回退切分连续段，段数不匹配时
        再按 (step, action) 对齐，无法对齐的条目并入最后一轮，绝不丢弃。
        """
        count = len(rounds)
        groups = [[] for _ in range(count)]
        entries = [e for e in (coords_entries or []) if isinstance(e, dict)]
        if count == 0 or not entries:
            return groups

        has_round = any(self._coord_round_of(e) is not None for e in entries)
        if has_round:
            for entry in entries:
                idx = self._coord_round_of(entry)
                if idx is None or not (0 <= idx < count):
                    groups[-1].append(entry)
                else:
                    groups[idx].append(entry)
            return groups

        # 旧格式：step 回退即视为下一轮
        segments = [[]]
        prev_step = None
        for entry in entries:
            step = self._coord_step_of(entry)
            if step is not None and prev_step is not None and step < prev_step:
                segments.append([])
            segments[-1].append(entry)
            if step is not None:
                prev_step = step

        if len(segments) == count:
            return segments

        used = set()
        last = count - 1
        for segment in segments:
            target = None
            for entry in segment:
                for r in range(count):
                    if r in used:
                        continue
                    if self._coord_matches_round(entry, rounds[r]):
                        target = r
                        break
                if target is not None:
                    break
            if target is None:
                target = last
            groups[target].extend(segment)
            used.add(target)
        return groups

    def load_from_completed_json(self, completed_data, coords_entries, round_index, gui_dir):
        """从已完成 JSON + coords 重建编辑现场（进入编辑模式，不写草稿）。"""
        dir_name = os.path.basename(os.path.normpath(gui_dir))
        match = re.fullmatch(r"gui_(\d{6})", dir_name)
        self.gui_number = match.group(1) if match else ""
        self.gui_dir = gui_dir
        self._completed_json = copy.deepcopy(completed_data or {})

        # messages 交替解析为 rounds（user 提供 instruction，assistant 提供 trajectory）
        self.rounds = []
        pending_instruction = ""
        for message in self._completed_json.get("messages") or []:
            role = message.get("role")
            if role == "user":
                pending_instruction = message.get("instruction", "")
            elif role == "assistant":
                trajectory = copy.deepcopy(message.get("trajectory") or [])
                self.rounds.append({
                    "instruction": pending_instruction,
                    "trajectory": trajectory,
                    "coords": [],
                })
                pending_instruction = ""

        round_index = int(round_index or 0)
        if self.rounds:
            round_index = max(0, min(round_index, len(self.rounds) - 1))
        else:
            round_index = 0
        self._edit_round_index = round_index

        self._coords_rounds = self._group_coords_into_rounds(
            coords_entries, self.rounds
        )
        for idx, round_data in enumerate(self.rounds):
            round_data["coords"] = copy.deepcopy(self._coords_rounds[idx])

        coords_path = os.path.join(
            gui_dir, f"gui_{self.gui_number}_coords.json"
        )
        self._original_coords_exist = os.path.isfile(coords_path)

        # 用选中轮 trajectory 重建 steps_data
        self.steps_data = []
        missing_files = []
        coord_issues = []
        claimed_ids = set()   # 已被某一步认领的条目，防止按 center 恢复时重复占用
        if self.rounds:
            round_data = self.rounds[round_index]
            round_coords = self._coords_rounds[round_index]
            for i, traj in enumerate(round_data.get("trajectory") or []):
                observation = traj.get("observation") or {}
                filename = observation.get("screenshot", "")
                # 截图文件在 gui_dir 下不存在时收集清单，加载后统一提示（不阻断编辑）
                if filename and not os.path.isfile(os.path.join(gui_dir, filename)):
                    missing_files.append(f"步骤 {i}: {filename}")
                actions = traj.get("actions") or []
                action_data = copy.deepcopy(actions[0] if actions else {})
                # 两趟匹配：先按 step 精确查，落空再按 center 在未认领条目里恢复。
                # 不再有「按下标回退取第 i 条」——位置冒领会污染已交付 bbox。
                coord_entry = self._find_coord_entry(
                    round_coords, self._coord_step_of(traj))
                if coord_entry is not None:
                    claimed_ids.add(id(coord_entry))
                else:
                    coord_entry = self._find_coord_entry_by_center(
                        round_coords, action_data.get("action"),
                        coord_pair(action_data.get("coordinate")),
                        coord_pair(action_data.get("start_coordinate")),
                        claimed_ids)
                vertices, coord_issue = self._classify_coord_state(
                    action_data, coord_entry)
                if coord_issue in ("absent", "mismatch"):
                    coord_issues.append((
                        i, action_cn_name(action_data.get("action")), coord_issue,
                        self._coord_issue_detail(action_data, coord_entry)))
                self.steps_data.append({
                    "screenshot": filename,
                    "screenshot_filepath": (
                        os.path.join(gui_dir, filename) if filename else ""
                    ),
                    "intent": traj.get("intent", ""),
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
        self._coord_issues = coord_issues

        self._edit_mode = True
        self._draft_discarded = True
        self.task_instruction = (
            self.rounds[round_index]["instruction"] if self.rounds else ""
        )
        self.current_step = 0

        if self.steps_data:
            self._restore_step_to_ui(self.steps_data[0])
        else:
            self._reset_for_next_step()

        self._update_step_label()
        self._update_navigation_buttons()
        self._missing_cache = []
        self._missing_live = None
        self.validation_timer.stop()
        self.sidebar.rebuild_items()

        if hasattr(self, "btn_save_edit"):
            self.btn_save_edit.show()
        self.btn_relabel.show()

        self.setWindowTitle(
            f"GUI长步骤采标工具-iOS - {self.app_name}（编辑已完成任务）"
        )
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
        edit_status = f"编辑已完成任务 gui_{self.gui_number} · 第 {round_index + 1} 轮"
        if self._coord_issues:
            # 保留常规状态串，只追加告警：直接覆盖会让其他依赖该文本的
            # 现场提示（和后续测试）被顶掉
            edit_status += (
                f" · ⚠ 检测到 {len(self._coord_issues)} 个步骤的 "
                f"bbox 与 coordinate 不一致"
            )
        self.status_label.setText(edit_status)

        if missing_files:
            QMessageBox.warning(
                self,
                "截图文件缺失",
                "以下步骤的截图文件在磁盘上不存在，预览将无法显示：\n\n"
                + "\n".join(missing_files),
            )

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
    def _merge_original_missing(cls, new_value, old_value, protected_keys=()):
        """字段级递归合并（返回新对象，不原地修改入参）。

        - 受保护字段（protected_keys）：新值非空才覆盖，空值保留旧值；
        - 其余键：新结构缺失则深拷贝旧值；新旧同为 dict/list 时递归合并；
        - 其余情况以新值为准。
        """
        if isinstance(new_value, dict) and isinstance(old_value, dict):
            merged = copy.deepcopy(new_value)
            for key, value in old_value.items():
                if key not in merged:
                    merged[key] = copy.deepcopy(value)
                    continue
                if cls._merge_protected_field(merged, key, value, protected_keys):
                    continue
                if isinstance(merged[key], dict) and isinstance(value, dict):
                    child_protected = ()
                    if key == "observation":
                        child_protected = cls._PROTECTED_OBSERVATION_KEYS
                    merged[key] = cls._merge_original_missing(
                        merged[key], value, child_protected)
                elif isinstance(merged[key], list) and isinstance(value, list):
                    merged[key] = cls._merge_original_missing(merged[key], value)
            return merged
        if isinstance(new_value, list) and isinstance(old_value, list):
            # actions 等列表按元素位置递归合并，保留元素内编辑器未管理的键
            merged = [copy.deepcopy(item) for item in new_value]
            for i, old_item in enumerate(old_value):
                if i < len(merged):
                    # trajectory 的 list 只有 actions：动作元素按动作受保护键合并
                    merged[i] = cls._merge_original_missing(
                        merged[i], old_item, cls._PROTECTED_ACTION_KEYS)
                else:
                    merged.append(copy.deepcopy(old_item))
            return merged
        return copy.deepcopy(new_value)

    def save_edited_round(self, silent=False):
        """保存当前编辑轮次并写回最终 JSON / coords JSON。

        silent=True 用于直接关闭窗口：跳过必填校验，失败只打印日志。
        返回是否成功写盘。
        """
        if not self._edit_mode or not self.rounds:
            return False

        self._save_current_to_steps_for_edit()
        round_index = self._edit_round_index
        round_data = self.rounds[round_index]
        original_trajectory = round_data.get("trajectory") or []
        original_coords = (
            self._coords_rounds[round_index]
            if round_index < len(self._coords_rounds)
            else round_data.get("coords") or []
        )

        if not silent:
            missing_list = []
            for i, step in enumerate(self.steps_data):
                reasons = self.validate_step_at(i)
                if reasons:
                    action_data = step.get("action_data") or {}
                    missing_list.append(
                        (i, action_cn_name(action_data.get("action", "")), reasons)
                    )
            if missing_list:
                self._show_validation_fail_dialog(missing_list)
                return False

        # 重建该轮 trajectory：按截图文件名关联原步骤，补齐未知字段
        trajectory = []
        for i, step in enumerate(self.steps_data):
            action_data = copy.deepcopy(step.get("action_data") or {})
            filename = step.get("screenshot", "")
            # steps_data 条目自身可能透传了下游字段（草稿续采场景）
            step_obs = step.get("observation")
            if isinstance(step_obs, dict):
                active_window = step_obs.get("active_window", "")
                ui_tree_segment = step_obs.get("ui_tree_segment", "")
            else:
                active_window = step.get("active_window", "")
                ui_tree_segment = step.get("ui_tree_segment", "")
            new_traj = {
                "step": i,
                "intent": step.get("intent", ""),
                "CoT": step.get("CoT", ""),
                "observation": {
                    "screenshot": filename,
                    "active_window": active_window,
                    "ui_tree_segment": ui_tree_segment,
                },
                "actions": [action_data],
            }
            original = None
            if filename:
                for traj in original_trajectory:
                    if (traj.get("observation") or {}).get("screenshot") == filename:
                        original = traj
                        break
            if original is None and i < len(original_trajectory):
                original = original_trajectory[i]
            if original is not None:
                # 字段级合并：CoT / active_window / ui_tree_segment / element /
                # status 新值为空时保留原已交付值，不被空串覆盖。
                # 终止类动作（terminate/answer）的 element=""、status="success"
                # 由 _build_action_data 在重建动作时强制给出，非空新值自然胜出，
                # 无需后置覆盖，避免给历史交付件中本无 status 键的条目凭空加键。
                new_traj = self._merge_original_missing(
                    new_traj, original, self._PROTECTED_STEP_KEYS)
            new_traj["step"] = i
            trajectory.append(new_traj)

        # 重建该轮 coords：编辑器管理的键以当前步为准，其它键按 step 合并保留
        managed_keys = {
            "step", "action", "vertices", "center",
            "start_vertices", "start_center", "end_vertices", "end_center",
        }
        coords = []
        for i, step in enumerate(self.steps_data):
            action_data = step.get("action_data") or {}
            action = action_data.get("action", "")
            orig = step.get("orig_coord_entry")
            if (action in COORD_ACTIONS
                    and self._valid_vertices(step.get("vertices")) is None
                    and isinstance(orig, dict)):
                # hydration 已判定该步「盘上框丢失/框与坐标值不一致」：既不伪造退化
                # 点框，也不因“没框”丢条目，而是按当前步序重编号后原样保留盘上顶点
                # （与 Windows A4 同口径），保证「打开看一眼就保存」不改变已交付 bbox
                kept = copy.deepcopy(orig)
                kept["step"] = i
                coords.append(kept)
                continue
            entry = {"step": i, "action": action}
            vertices = self._valid_vertices(step.get("vertices"))
            start = self._valid_coord_pair(action_data.get("start_coordinate"))
            coord = self._valid_coord_pair(action_data.get("coordinate"))
            if start is not None:
                if vertices is not None:
                    entry["vertices"] = list(vertices)
                    entry["center"] = [
                        int((vertices[0] + vertices[2]) / 2),
                        int((vertices[1] + vertices[3]) / 2),
                    ]
                else:
                    entry["center"] = list(start)
                if coord is not None:
                    entry["end_center"] = list(coord)
            elif vertices is not None:
                entry["vertices"] = list(vertices)
                entry["center"] = [
                    int((vertices[0] + vertices[2]) / 2),
                    int((vertices[1] + vertices[3]) / 2),
                ]
            elif coord is not None:
                entry["center"] = list(coord)

            original_entry = None
            for c in original_coords:
                if self._coord_step_of(c) == i:
                    original_entry = c
                    break
            if original_entry is not None:
                for key, value in original_entry.items():
                    if key not in managed_keys and key not in entry:
                        entry[key] = copy.deepcopy(value)
            coords.append(entry)

        round_data["trajectory"] = trajectory
        round_data["coords"] = copy.deepcopy(coords)
        if round_index < len(self._coords_rounds):
            self._coords_rounds[round_index] = copy.deepcopy(coords)

        # 1.5（B40）原地只改被编辑轮对应的两条消息，其余消息对象一律不动。
        # 早前先 deepcopy 再按 self.rounds 全量重建，会把原 JSON 里非
        # user/assistant 的消息、每轮消息自带的其他字段、末尾孤立 user 消息
        # 整条丢掉——已交付数据不可恢复。结构不满足「严格交替」时
        # 拒绝写回，绝不退化成全量重建。
        data = copy.deepcopy(self._completed_json or {})
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
                print(f"编辑保存中止（gui_{self.gui_number}）：{reason}")
            else:
                QMessageBox.critical(
                    self, "保存失败", reason + "\n已拒绝写回，原文件保持不变"
                )
            return False

        edited_round = self.rounds[round_index]
        messages[2 * round_index]["instruction"] = edited_round.get("instruction", "")
        messages[anchor]["trajectory"] = edited_round.get("trajectory") or []
        data["messages"] = messages

        # 1.4 安全网：编辑写回会整份替换已交付 JSON，先把原文件留一份 .bak（覆盖式）。
        # 仅在原文件存在时生成；备份失败不阻断保存。
        self.data_manager.backup_final_json(self.gui_number)

        saved_path = self.data_manager.save_json_data(data, self.gui_number)
        if not saved_path:
            if silent:
                print(f"编辑保存失败：无法写入 gui_{self.gui_number}.json")
            else:
                QMessageBox.critical(
                    self, "保存失败", "写入任务 JSON 失败，原文件保持不变"
                )
            return False

        all_coords = []
        for r_idx, round_item in enumerate(self.rounds):
            for coord in round_item.get("coords") or []:
                item = copy.deepcopy(coord)
                item["round"] = r_idx
                all_coords.append(item)
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

        self._draft_discarded = True
        self.draft_timer.stop()
        self._final_data_saved = True
        self.status_label.setText(
            f"已保存编辑 gui_{self.gui_number} · 第 {round_index + 1} 轮"
        )
        if self._coord_issues:
            # 继承性盘上缺陷本次未消除：写回成功不等于数据已干净，提醒显式处置
            print(
                f"提示：gui_{self.gui_number} 仍有 {len(self._coord_issues)} 个步骤的盘上 bbox 与 "
                f"coordinate 不一致（本次原样保留、未改动这些条目）；"
                f"如需修复请在原图重新拉框。"
            )

        if silent:
            print(f"编辑模式关闭：已写回 gui_{self.gui_number}")
        else:
            QMessageBox.information(
                self, "保存成功",
                f"第 {round_index + 1} 轮修改已写回 gui_{self.gui_number}/"
            )
            self.close()
        return True

    def _reset_for_next_step(self):
        """重置界面状态，准备下一步操作"""
        self.canvas.clear_rect()
        self.screenshot_cache = None
        self._current_screenshot_filename = None
        self._current_screenshot_filepath = None
        self._current_vertices = None
        self._screenshot_missing = False
        self._missing_live = None
        self.validation_timer.stop()
        self.canvas.set_pixmap(None)
        self._clear_inputs()
        self._update_navigation_buttons()
        self._update_step_label()

    def clear_annotations(self):
        """清除当前所有标注信息"""
        self.canvas.clear_rect()
        # 清除标注时同时退出 swipe/scroll 测量状态，避免残留测量标记与多余截图
        self._cancel_swipe_measurement()
        self._cancel_scroll_measurement()
        self._current_vertices = None
        self.coord_x_input.clear()
        self.coord_y_input.clear()
        self.coord2_x_input.clear()
        self.coord2_y_input.clear()
        self.text_input.clear()
        self.time_input.clear()
        self.pixels_input.clear()
        self.intent_input.clear()
        self.action_combo.setCurrentIndex(0)
        self.status_label.setText("标注已清除")

    # ========== 内部方法 ==========

    def _validate_step(self):
        """验证当前步骤必填字段（统一委托 validate_step_at；iOS 口径不校验 intent）"""
        reasons = self.validate_step_at(self.current_step)
        if reasons:
            QMessageBox.warning(self, "提示", reasons[0])
            return False
        return True

    @staticmethod
    def _parse_int(text):
        """将文本解析为整数，失败返回 None（支持 "-200"、负滚动像素等；拒绝 NaN/Inf）"""
        try:
            v = float(text)
            if not math.isfinite(v):
                return None
            return int(v)
        except (ValueError, TypeError, OverflowError):
            return None

    @staticmethod
    def _parse_float(text):
        """将文本解析为浮点数，失败返回 None（拒绝 NaN/Inf）"""
        try:
            v = float(text)
            if not math.isfinite(v):
                return None
            return v
        except (ValueError, TypeError, OverflowError):
            return None

    @staticmethod
    def _is_valid_number(value):
        """是否为有限 int/float（排除 bool、NaN、Inf）"""
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    @classmethod
    def _valid_coord_pair(cls, value):
        """合法坐标点：list/tuple 至少两个有限数；合法则返回 [x, y]，否则 None"""
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            if cls._is_valid_number(value[0]) and cls._is_valid_number(value[1]):
                return [value[0], value[1]]
        return None

    @classmethod
    def _valid_vertices(cls, value):
        """合法拉框：list/tuple 恰 4 个有限数"""
        if isinstance(value, (list, tuple)) and len(value) == 4:
            if all(cls._is_valid_number(v) for v in value):
                return list(value)
        return None

    def _build_action_data(self):
        """根据当前界面输入构建动作数据（缺项一律省略键，不伪造默认值）"""
        action = self._current_action_key()
        data = {"action": action, "element": ""}

        if action in COORD_ACTIONS:
            first_coord = self._valid_coord_pair(getattr(self, '_scroll_first_coord', None))
            if action in SCROLL_ACTIONS and first_coord is not None:
                # scroll动作使用第一个拉框的坐标
                x, y = first_coord
            else:
                x = self._parse_int(self.coord_x_input.text().strip())
                y = self._parse_int(self.coord_y_input.text().strip())
            if self._is_valid_number(x) and self._is_valid_number(y):
                if action in SWIPE_ACTIONS:
                    data["start_coordinate"] = [x, y]
                else:
                    data["coordinate"] = [x, y]

        if action in SWIPE_ACTIONS:
            x2 = self._parse_int(self.coord2_x_input.text().strip())
            y2 = self._parse_int(self.coord2_y_input.text().strip())
            if self._is_valid_number(x2) and self._is_valid_number(y2):
                data["coordinate"] = [x2, y2]

        if action in TEXT_ACTIONS:
            data["text"] = self.text_input.text().strip()

        if action in TIME_ACTIONS:
            t = self._parse_float(self.time_input.text().strip())
            if t is not None:
                data["time"] = t

        if action in BUTTON_ACTIONS:
            button = self.button_combo.currentText().strip()
            if button in SYSTEM_BUTTONS:
                data["element"] = f"系统按钮{button}"
                data["buttons"] = [button]

        if action in SCROLL_ACTIONS:
            p = self._parse_int(self.pixels_input.text().strip())
            if p is not None:
                data["pixels"] = p

        if action == "answer_terminate":
            # 该动作仍以 answer 记录，status 固定为 success
            data["action"] = "answer"
            data["status"] = "success"

        if action == "terminate":
            data["status"] = "success"

        return data

    def _build_coords_entry(self, action_data, vertices=None):
        """从动作数据构建坐标条目"""
        entry = {
            "step": self.current_step,
            "action": action_data.get("action", ""),
        }
        start = self._valid_coord_pair(action_data.get("start_coordinate"))
        if start is not None:
            x, y = start
            valid_vertices = self._valid_vertices(vertices)
            if valid_vertices is not None:
                entry["vertices"] = valid_vertices
            else:
                entry["vertices"] = [x, y, x, y]
            entry["center"] = [x, y]
            # swipe/drag 同时记录终点坐标，避免 coords 输出丢失滑动/拖拽向量
            end = self._valid_coord_pair(action_data.get("coordinate"))
            if end is not None:
                entry["end_center"] = end
        else:
            coord = self._valid_coord_pair(action_data.get("coordinate"))
            if coord is not None:
                x, y = coord
                valid_vertices = self._valid_vertices(vertices)
                if valid_vertices is not None:
                    entry["vertices"] = valid_vertices
                else:
                    entry["vertices"] = [x, y, x, y]
                entry["center"] = coord
        return entry

    def _clear_inputs(self):
        """清空输入字段"""
        # restore/重置会在 setCurrentIndex(0) 触发 on_action_changed 前复位，
        # 避免把上一步的 terminate intent 备份误还原到本步
        self._terminate_intent_saved = False
        self._pre_terminate_intent = ""
        self.intent_input.clear()
        self.coord_x_input.clear()
        self.coord_y_input.clear()
        self.coord2_x_input.clear()
        self.coord2_y_input.clear()
        self.text_input.clear()
        self.time_input.clear()
        self.pixels_input.clear()
        self.action_combo.setCurrentIndex(0)
        self._current_vertices = None
        self._cancel_swipe_measurement()
        self._cancel_scroll_measurement()

    def _update_step_label(self):
        self.step_label.setText(f"步骤: {self.current_step}")

    def _update_navigation_buttons(self):
        self.btn_prev.setEnabled(self.current_step > 0)
        # 删除/插入按钮仅在存在已落表步骤时可用
        has_steps = 0 <= self.current_step < len(self.steps_data)
        if hasattr(self, "btn_delete"):
            self.btn_delete.setEnabled(has_steps)
        if hasattr(self, "btn_insert"):
            self.btn_insert.setEnabled(has_steps)

    def _finish_task(self):
        """完成当前任务，保存所有轮次数据并询问是否继续新任务"""
        # 已完成并落盘后不得再次进入：弹窗/关闭窗口期间的重复确认会把已消费的
        # rounds 再落一遍，或在 steps_data 已清空时写出空洞交付件
        if self._final_data_saved:
            return
        # 结束前全量必填校验（先把界面上的当前步落表），存在缺填项则弹窗拦截
        self._save_current_to_steps()
        missing_list = []
        for i, step in enumerate(self.steps_data):
            reasons = self.validate_step_at(i)
            if reasons:
                action_data = step.get("action_data") or {}
                # answer_terminate 落盘 action 为 answer，对话框中给出更准确的中文名
                if (
                    i == self.current_step
                    and self._current_action_key() == "answer_terminate"
                ):
                    action_label = "回答并结束 (answer+terminate)"
                else:
                    action_label = action_cn_name(action_data.get("action", ""))
                missing_list.append((i, action_label, reasons))
        if missing_list:
            # DI-18：上面的 _save_current_to_steps 可能刚 append 出新步，而拒收分支
            # 不重建侧栏 → 条目数落后于 steps_data、缺填标记停在旧步骤集合上。
            # 弹清单前先全量重建，保证界面与模型一致
            self.sidebar.rebuild_items()
            self._show_validation_fail_dialog(missing_list)
            return

        # 保存当前轮次到列表
        if not self._save_current_round_to_list():
            # B14：缺指令被拒绝落轮 → 中止收尾，不写出缺最后一轮的交付文件
            QMessageBox.warning(
                self, "缺少任务指令",
                "当前轮次还没有任务指令，已中止保存以免轨迹挂到错误指令上。\n"
                "请重新确认本步并输入本轮指令后再完成标注。"
            )
            return

        # 合并所有轮次写入文件
        # 5.7（B31）落盘失败绝不能继续弹"已保存"：用户会以为数据已交付而清场，
        # 实际只剩草稿（甚至草稿也没了）却无人知晓。失败即中止并明确报错。
        if not self._save_all_rounds_to_file():
            QMessageBox.critical(
                self, "保存失败",
                f"本轮数据未能写入 gui_{self.gui_number}/，草稿已保留，"
                "请重新打开工具续采后再完成一次。"
            )
            return

        # 已落盘：置完成标志，同时升门闩阻断弹窗/关闭期间的截图与确认，
        # 避免“是否继续新任务”对话框尚未应答时又生成步骤或重复落盘
        self._final_data_saved = True
        self._round_transition_pending = True

        # 询问是否继续新任务
        reply = QMessageBox.question(
            self,
            "任务完成",
            f"当前任务已保存到 gui_{self.gui_number}/\n\n是否继续新任务？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self._start_new_task()
        else:
            self.close()

    def _prompt_missing_instruction(self):
        """本轮缺少任务指令时弹窗补齐；返回 False 表示用户仍未给出指令。

        B14：取消新轮后 task_instruction 被置空（见 _reset_workspace_after_cancel）。
        放任空指令落轮的话，新一轮轨迹会静默挂到上一轮的旧指令上，事后无从
        分辨哪段轨迹属于哪条指令，因此落轮前必须显式补齐，补齐失败由调用方拒绝落轮。
        """
        new_instruction, ok = QInputDialog.getText(
            self,
            "任务指令",
            f"【{self.app_name}】当前轮次缺少任务指令，请输入本轮对应的指令：",
            QLineEdit.Normal,
            ""
        )
        if ok and new_instruction.strip():
            self.task_instruction = new_instruction.strip()
            return True
        self.status_label.setText("缺少任务指令 - 本轮未落轮，请补齐指令后重新确认")
        return False

    def _save_current_round_to_list(self, prompt_instruction=True):
        """将当前轮次保存到 rounds 列表（不写磁盘，参考 macOS save_current_round）

        :param prompt_instruction: 指令缺失时是否弹窗补齐；无人值守路径传 False 静默拒绝
        :return: True 表示已落轮或本轮无步骤可落；False 表示因缺少任务指令被拒绝落轮，
            调用方必须保持 steps_data 原样并中止后续的切轮/写盘动作
        """
        if not self.steps_data:
            return True  # 无步骤数据，避免重复写入；不构成拒绝
        if not (self.task_instruction or "").strip():
            if not prompt_instruction or not self._prompt_missing_instruction():
                return False

        trajectory = []
        all_coords = []

        for i, step_data in enumerate(self.steps_data):
            action_data = step_data.get("action_data") or {}
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
                "intent": step_data.get("intent", ""),
                "CoT": step_data.get("CoT", ""),
                "observation": {
                    "screenshot": step_data.get("screenshot", ""),
                    "active_window": active_window,
                    "ui_tree_segment": ui_tree_segment
                },
                # 2.7（B42）落轮必须存 action 的深拷贝：直接把 steps_data 里的活对象
                # 塞进 rounds，会让 rounds 与本轮数据共享同一个 dict，任何对步骤
                # action 的原地改写（含嵌套的 coordinate 列表）都会回写到已落轮、
                # 甚至已交付的轮次上。coords 侧无需再包：_build_coords_entry 内的
                # vertices 由 _valid_vertices 返回 list() 副本，且只读 action_data。
                "actions": [copy.deepcopy(action_data)]
            })
            coords_entry = self._build_coords_entry(action_data, step_data.get("vertices"))
            coords_entry["step"] = i
            all_coords.append(coords_entry)

        self.rounds.append({
            "instruction": self.task_instruction,
            "trajectory": trajectory,
            "coords": all_coords
        })

        # 消费当前步骤并重置界面状态，避免后续再次触发时重复写入同一轮次
        self.steps_data = []
        self.coords_data = []
        self.current_step = 0
        self.screenshot_cache = None
        self._current_screenshot_filename = None
        self._current_screenshot_filepath = None

        # 轮次边界：重建侧栏并立即把草稿落盘，异常退出也不丢已完成轮次
        self._missing_cache = []
        self._missing_live = None
        self._screenshot_missing = False
        self.validation_timer.stop()
        self.sidebar.rebuild_items()
        self._write_draft_now()
        return True

    def _save_all_rounds_to_file(self):
        """合并所有轮次，写入 JSON 和 coords JSON 文件

        :return: True 表示交付 JSON 已成功落盘；False 表示无可保存数据或写盘失败
        """
        if not self.rounds:
            return False

        # 使用第一轮的 instruction 作为占位
        json_data = self.data_manager.create_initial_json_structure(
            self.rounds[0].get("instruction", ""),
            self.screen_info, self.app_type
        )
        json_data["messages"] = []

        all_coords = []

        for round_idx, round_data in enumerate(self.rounds):
            json_data["messages"].append({
                "role": "user",
                "instruction": round_data["instruction"]
            })
            json_data["messages"].append({
                "role": "assistant",
                "trajectory": round_data["trajectory"]
            })
            # coords 条目增加 round 标识，避免多轮 step 冲突、无法归属
            for coord in round_data.get("coords", []):
                coord = dict(coord)
                coord["round"] = round_idx
                all_coords.append(coord)

        saved_path = self.data_manager.save_json_data(json_data, self.gui_number)
        if not saved_path:
            # 5.7（B31）写盘失败：草稿与定时器原样保留（下次开屏仍可续采），
            # 由调用方据返回值决定是否谎报"已保存"
            return False
        # 主数据落盘成功后删除草稿；coords 仍按既有契约非空才保存
        if all_coords:
            self.data_manager.save_coords_json(all_coords, self.gui_number)
        self.data_manager.delete_draft(self.gui_number)
        self._draft_discarded = True
        self.draft_timer.stop()

        self.status_label.setText(f"所有轮次已保存到 gui_{self.gui_number}/")
        return True

    def _reset_workspace_after_cancel(self):
        """已落轮后用户放弃开启新轮：把界面清成空白起点（口径对齐 Android 同名方法）。

        _save_current_round_to_list 只消费了数据层（steps_data/coords_data/
        current_step/截图缓存/缺填缓存）并重建侧栏、落草稿，画布上的截图、
        表单输入、导航按钮与步骤标签仍停在上一轮；取消新轮不能只改文案，
        否则用户看到的是上一轮残留，接着采集会把旧表单值带进新轮（B28）。
        """
        self.current_step = 0
        # B14：上一轮已随 answer 落轮并被消费，取消新轮后不得继续持有旧指令，
        # 否则用户接着采集的整轮会被静默挂到上一条指令上（落轮前另有强校验兼做安
        # 全网，两者缺一都会重现指令错乱）。
        self.task_instruction = ""
        self._reset_for_next_step()
        self.sidebar.rebuild_items()
        self.schedule_draft_save()
        self.status_label.setText("已取消新任务 - 可继续截图标注")

    def _start_new_round(self, from_answer=False):
        """开始新一轮任务（同一 gui 文件夹内，参考 macOS answer 流程）"""
        # 门闩回调已进场，切轮窗口结束，恢复采集/编辑入口（B2）
        self._round_transition_pending = False
        new_instruction, ok = QInputDialog.getText(
            self,
            "新任务指令",
            f"请输入【{self.app_name}】的新任务指令：",
            QLineEdit.Normal,
            ""
        )
        if ok and new_instruction.strip():
            self.task_instruction = new_instruction.strip()
            self.current_step = 0
            self.steps_data = []
            self.coords_data = []
            # 注意：rounds 不清空，累积多轮数据到 terminate 时统一写入
            self.screenshot_cache = None
            self._current_screenshot_filename = None
            self._current_screenshot_filepath = None
            self._cancel_swipe_measurement()
            self.canvas.clear_rect()
            self.canvas.set_pixmap(None)
            self._clear_inputs()
            self._update_navigation_buttons()
            self._update_step_label()
            self._missing_cache = []
            self._missing_live = None
            self._screenshot_missing = False
            self.validation_timer.stop()
            self.sidebar.rebuild_items()
            self.schedule_draft_save()

            # 同一 gui 目录继续累积多轮任务
            self.status_label.setText(f"新任务开始 - 指令: {self.task_instruction} - 请截图")
        else:
            if from_answer:
                # 2.3（B28）取消新轮走完整重置，不留下上一轮的界面残留
                self._reset_workspace_after_cancel()
            else:
                self.close()

    def _start_new_task(self):
        """开始新的采标任务"""
        new_instruction, ok = QInputDialog.getText(
            self,
            "新任务指令",
            f"请输入【{self.app_name}】的新任务指令：",
            QLineEdit.Normal,
            ""
        )
        if ok and new_instruction.strip():
            self.task_instruction = new_instruction.strip()
            self.current_step = 0
            self.steps_data = []
            self.coords_data = []
            self.rounds = []
            # 全量重置：编辑态继承的盘上不一致清单不能跟着带进新任务，
            # 否则写回时会拿着旧轮的清单打印误导性的剩余条数提示
            self._coord_issues = []
            self.screenshot_cache = None
            self._current_screenshot_filename = None
            self._current_screenshot_filepath = None
            self.canvas.clear_rect()
            self.canvas.set_pixmap(None)
            self._clear_inputs()
            self._update_navigation_buttons()
            self._update_step_label()

            # 新 gui 编号
            self.gui_number = self.data_manager.get_next_gui_number()
            self.gui_dir = self.data_manager.create_gui_directory(self.gui_number)
            self._draft_discarded = False
            # 新任务重新开放采集：清除上一任务的已完成标志与切轮门闩，
            # 否则截图/确认入口会一直早退
            self._final_data_saved = False
            self._round_transition_pending = False
            self._missing_cache = []
            self._missing_live = None
            self._screenshot_missing = False
            self.validation_timer.stop()
            self.sidebar.rebuild_items()
            self.schedule_draft_save()

            self.status_label.setText(f"新任务已开始 - 指令: {self.task_instruction} - 请截图")

    def closeEvent(self, event):
        """窗口关闭时静默尝试落盘一次草稿，再回调恢复初始化界面"""
        # 重新拉框弹窗先关闭，避免弹窗残留遮挡关闭时的自动写回
        if getattr(self, "_relabel_dialog", None) is not None:
            try:
                self._relabel_dialog.close()
            except RuntimeError:
                pass
            self._relabel_dialog = None
        if self._edit_mode:
            # 编辑已完成任务：不写草稿；未显式保存则把修改静默写回原文件
            if not self._final_data_saved:
                try:
                    self.save_edited_round(silent=True)
                except Exception as e:
                    print(f"编辑模式关闭写回失败: {e}")
        else:
            try:
                self._write_draft_now()
            except Exception:
                pass
        if self._close_callback:
            self._close_callback()
        event.accept()

    # ========== 键盘事件 ==========

    def keyPressEvent(self, event):
        """键盘快捷键处理"""
        # Ctrl+Q: 截图
        if event.key() == Qt.Key_Q and event.modifiers() == Qt.ControlModifier:
            self.start_capture()
        # Ctrl+S: 保存当前截图并进入下一步
        elif event.key() == Qt.Key_S and event.modifiers() == Qt.ControlModifier:
            self.go_next()
        # 右方向键: 保存并进入下一步
        elif event.key() == Qt.Key_Right:
            self.go_next()
        # 左方向键: 回到上一步
        elif event.key() == Qt.Key_Left:
            self.go_previous()
        # ESC: 清除所有标注
        elif event.key() == Qt.Key_Escape:
            self.clear_annotations()
        else:
            super().keyPressEvent(event)
