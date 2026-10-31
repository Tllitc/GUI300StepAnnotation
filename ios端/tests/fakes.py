# -*- coding: utf-8 -*-
"""无真机截图桩件。

FakeScreenCapture 实现与 screenshot_capture.IOSScreenCapture 相同的调用契约：

    success, filepath = capture.capture(output_path)

每次截图像一张 390x844 的纯色 QImage（序号不同颜色不同），并在图上
绘制调用序号，便于测试断言“第 N 步截图 ↔ 第 N 个磁盘文件”的映射关系。

注意：offscreen 平台下 QPixmap 绘图可能为空，因此这里必须使用
QImage.Format_RGB32 直接光栅化后 img.save(...)。
"""

from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QImage, QPainter, QColor, QFont


# 高区分度底色（RGB），循环使用
_DISTINCT_COLORS = [
    (220, 40, 40),    # 红
    (40, 170, 60),    # 绿
    (40, 90, 220),    # 蓝
    (230, 200, 30),   # 黄
    (150, 50, 200),   # 紫
    (30, 190, 200),   # 青
    (230, 130, 20),   # 橙
    (230, 100, 170),  # 粉
    (80, 200, 120),   # 草绿
    (120, 80, 40),    # 棕
]

DEFAULT_WIDTH = 390
DEFAULT_HEIGHT = 844


class FakeScreenCapture:
    """IOSScreenCapture 的离线桩件。

    属性:
        call_count:      成功截图累计次数（失败不计入）
        fail_next:       置 True 后下一次 capture 返回 (False, None)，并自动复位
        captured_files:  成功保存的 output_path 列表（按调用顺序）
        colors:          每次成功截图使用的 (r, g, b) 底色（按调用顺序）
    """

    def __init__(self):
        self.call_count = 0
        self.fail_next = False
        self.captured_files = []
        self.colors = []

    # ------------------------------------------------------------------
    # 与 IOSScreenCapture.capture 一致的契约
    # ------------------------------------------------------------------
    def capture(self, output_path=None):
        """生成一张可区分序号的 PNG 到 output_path。

        返回 (True, output_path)；fail_next 为 True 时返回 (False, None)。
        """
        if self.fail_next:
            self.fail_next = False
            return False, None

        if not output_path:
            return False, None

        color = _DISTINCT_COLORS[self.call_count % len(_DISTINCT_COLORS)]
        image = QImage(DEFAULT_WIDTH, DEFAULT_HEIGHT, QImage.Format_RGB32)
        image.fill(QColor(color[0], color[1], color[2]))

        # 在图面上绘制序号，肉眼/像素双重可辨
        painter = QPainter(image)
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Arial", 48)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRect(0, DEFAULT_HEIGHT // 2 - 60, DEFAULT_WIDTH, 120),
            Qt.AlignCenter,
            f"SHOT {self.call_count + 1}",
        )
        painter.end()

        if not image.save(output_path, "PNG"):
            return False, None

        self.call_count += 1
        self.captured_files.append(output_path)
        self.colors.append(color)
        return True, output_path

    # ------------------------------------------------------------------
    # 测试辅助：按底色反查截图序号（0-based），验证图与步骤映射
    # ------------------------------------------------------------------
    def classify(self, path):
        """读取 PNG 左上角像素底色，返回对应的 0-based 截图序号；无法识别返回 None。"""
        image = QImage(path)
        if image.isNull():
            return None
        rgb = QColor(image.pixel(4, 4))
        target = (rgb.red(), rgb.green(), rgb.blue())
        for idx, color in enumerate(self.colors):
            if color == target:
                return idx
        return None
