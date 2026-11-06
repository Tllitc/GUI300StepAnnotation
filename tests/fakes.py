# -*- coding: utf-8 -*-
"""桌面端离线截图桩件。

FakeScreenshotCaptureWindow 实现与 screenshot_capture.ScreenshotCaptureWindow
相同的信号契约::

    capture_completed.emit(original_pixmap, marked_pixmap, rect_info, selection_type)

每次截图生成一张可区分的 1920x1080 纯色 QPixmap（序号不同底色不同），并在图面上
绘制调用序号，便于测试断言“第 N 步截图 ↔ 第 N 个磁盘文件”的映射。
"""

from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QImage, QPainter, QColor, QFont
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import pyqtSignal


# 高区分度底色（RGB），循环使用
_DISTINCT_COLORS = [
    (220, 40, 40),     # 红
    (40, 170, 60),     # 绿
    (40, 90, 220),     # 蓝
    (230, 200, 30),    # 黄
    (150, 50, 200),    # 紫
    (30, 190, 200),    # 青
    (230, 130, 20),    # 橙
    (230, 100, 170),   # 粉
    (80, 200, 120),    # 草绿
    (120, 80, 40),     # 棕
]

DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080


def _build_image(call_index, rect_info, selection_type):
    """构造一张 1920x1080 的可区分 PNG，底色随 call_index 切换，
    并在图上绘制序号 + 选择形态文字；若 rect_info 非空则用红框画出。"""
    color = _DISTINCT_COLORS[call_index % len(_DISTINCT_COLORS)]
    image = QImage(DEFAULT_WIDTH, DEFAULT_HEIGHT, QImage.Format_RGB32)
    image.fill(QColor(color[0], color[1], color[2]))

    painter = QPainter(image)
    # 文字：序号 + 选择形态
    painter.setPen(QColor(255, 255, 255))
    font = QFont("Arial", 72)
    font.setBold(True)
    painter.setFont(font)

    shape_text = {
        "drag": "DRAG",
        "fullscreen": "FULL",
        "click": "CLICK",
        "cancelled": "CANCEL",
    }.get(selection_type, selection_type or "?")
    painter.drawText(
        QRect(0, DEFAULT_HEIGHT // 2 - 80, DEFAULT_WIDTH, 160),
        Qt.AlignCenter,
        f"SHOT {call_index + 1} [{shape_text}]",
    )

    # 红框标记（单框或双框）
    painter.setPen(QColor(255, 0, 0))
    from PyQt5.QtGui import QPen
    painter.setPen(QPen(QColor(255, 0, 0), 5))
    if rect_info and isinstance(rect_info, (tuple, list)):
        is_dual = (len(rect_info) == 2
                   and isinstance(rect_info[0], (tuple, list))
                   and len(rect_info[0]) == 4)
        if is_dual:
            first, second = rect_info
            painter.drawRect(QRect(*first))
            painter.drawRect(QRect(*second))
        elif len(rect_info) == 4 and all(isinstance(v, (int, float)) for v in rect_info):
            painter.drawRect(QRect(*rect_info))

    painter.end()
    return image


def _pixmap_from_image(image):
    """QImage → QPixmap（使用 bytes 缓冲区，offscreen 下更稳定）"""
    from PyQt5.QtGui import QPixmap
    buffer = image.bits().asstring(image.byteCount())
    pm = QPixmap()
    pm.loadFromData(buffer)
    if pm.isNull():
        # 兜底：从 bytes 构造
        pm = QPixmap.fromImage(image)
    return pm


class FakeScreenshotCaptureWindow(QWidget):
    """ScreenshotCaptureWindow 的离线桩件。

    属性:
        call_count:        累计调用次数
        fail_next_save:    True 时让下一次返回"已确认选择"信号，但让上层 save_screenshot
                           失败（由测试在 DataManager.save_screenshot 层 patch）；
                           本桩本身只管发信号，不负责真正写盘
        default_rect:      单框 rect_info 默认值（4-int tuple）
        default_dual_rect: 双框 rect_info 默认值（嵌套二元组）
        default_selection_type: 默认 "click"；双框则自动改成 "drag"
        cancelled:         True 时发 selection_type="cancelled"
        colors:            每次截图使用的底色（按调用顺序）
        rect_history:      每次发出的 rect_info 列表
        selection_history: 每次发出的 selection_type 列表
        background_pixmap: 「在原图上重新拉框」入口传入的磁盘原图（普通截图为 None）
    """

    capture_completed = pyqtSignal(object, object, tuple, str)

    # 类级别的"下一次实例标志"——因为 show_capture_window 每次都会 new 一个实例，
    # 测试需要在实例化前预设好 canceled/selection/rect 状态，就通过这几个标志传。
    _next_cancelled = False
    _next_selection_type = None      # None 表示用 default_selection_type
    _next_single_rect = None         # None 表示用 default_rect
    _next_dual_rect = None           # None 表示用 default_dual_rect (嵌套二元组)

    # 每次实例化收到的 background_pixmap（普通截图入口为 None，
    # 「在原图上重新拉框」入口为磁盘原图）。reset_prepare() 会清空。
    background_history = []

    def __init__(self, parent=None, background_pixmap=None):
        super().__init__(parent)
        # 「在原图上重新拉框」入口会传 background_pixmap（磁盘原截图）；
        # 记录它以便断言弹窗拿到的确实是磁盘图而不是新抓的屏
        self.background_pixmap = background_pixmap
        FakeScreenshotCaptureWindow.background_history.append(background_pixmap)
        self.call_count = 0
        self.colors = []
        self.rect_history = []
        self.selection_history = []
        self.fail_next_save = False
        # __init__ 里读类级别的"下一次"标志，读完后清除（只作用一次）
        self.cancelled = FakeScreenshotCaptureWindow._next_cancelled
        FakeScreenshotCaptureWindow._next_cancelled = False
        if FakeScreenshotCaptureWindow._next_single_rect is not None:
            self.default_rect = tuple(int(v) for v in FakeScreenshotCaptureWindow._next_single_rect)
            FakeScreenshotCaptureWindow._next_single_rect = None
        else:
            self.default_rect = (100, 200, 300, 400)
        if FakeScreenshotCaptureWindow._next_dual_rect is not None:
            r1, r2 = FakeScreenshotCaptureWindow._next_dual_rect
            self.default_dual_rect = (tuple(int(v) for v in r1), tuple(int(v) for v in r2))
            FakeScreenshotCaptureWindow._next_dual_rect = None
        else:
            self.default_dual_rect = ((100, 200, 300, 400), (600, 500, 300, 400))
        if FakeScreenshotCaptureWindow._next_selection_type is not None:
            self.default_selection_type = FakeScreenshotCaptureWindow._next_selection_type
            FakeScreenshotCaptureWindow._next_selection_type = None
        else:
            self.default_selection_type = "click"

    # -------------- 公开入口（对应真实 show + 自动 confirm）--------------
    def show(self):
        """替代真实遮罩 show：立即发 capture_completed 并 close 自身。"""
        if self.cancelled:
            rect = ()
            selection = "cancelled"
            image = _build_image(self.call_count, rect, selection)
        elif self.default_selection_type == "drag":
            rect = tuple(tuple(r) for r in self.default_dual_rect)
            selection = "drag"
            image = _build_image(self.call_count, rect, selection)
        else:
            rect = tuple(int(v) for v in self.default_rect)
            selection = self.default_selection_type or "click"
            image = _build_image(self.call_count, rect, selection)

        orig_pm = _pixmap_from_image(image)
        marked_pm = _pixmap_from_image(image)

        # 记录元数据
        self.colors.append(_DISTINCT_COLORS[self.call_count % len(_DISTINCT_COLORS)])
        self.rect_history.append(rect)
        self.selection_history.append(selection)
        self.call_count += 1

        # 发信号后关闭（与真实产品代码中 confirm_selection 的 close 行为一致）
        self.capture_completed.emit(orig_pm, marked_pm, rect, selection)
        self.close()

    # -------------- 类级别的"下一次调用预设"（给 helpers.py 用）--------------
    @classmethod
    def prepare_cancelled(cls):
        cls._next_cancelled = True

    @classmethod
    def prepare_single_box(cls, rect=None, selection_type="click"):
        cls._next_cancelled = False
        cls._next_selection_type = selection_type or "click"
        cls._next_single_rect = tuple(int(v) for v in rect) if rect is not None else None
        cls._next_dual_rect = None

    @classmethod
    def prepare_dual_box(cls, first=None, second=None):
        cls._next_cancelled = False
        cls._next_selection_type = "drag"
        f = tuple(int(v) for v in first) if first is not None else (100, 200, 300, 400)
        s = tuple(int(v) for v in second) if second is not None else (600, 500, 300, 400)
        cls._next_dual_rect = (f, s)
        cls._next_single_rect = None

    @classmethod
    def reset_prepare(cls):
        """每次调用截图前先清干净所有类级别预设标志。"""
        cls._next_cancelled = False
        cls._next_selection_type = None
        cls._next_single_rect = None
        cls._next_dual_rect = None
        cls.background_history = []

    # -------------- 测试辅助 --------------
    def classify(self, path):
        """按底色反查截图 0-based 序号。"""
        image = QImage(path)
        if image.isNull():
            return None
        rgb = QColor(image.pixel(4, 4))
        target = (rgb.red(), rgb.green(), rgb.blue())
        for idx, color in enumerate(self.colors):
            if color == target:
                return idx
        return None
