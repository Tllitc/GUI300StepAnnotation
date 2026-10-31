# -*- coding: utf-8 -*-
"""FakeAndroidScreenCapture：线程安全桩截图器

构造时（主线程）预生成若干张可区分 PNG 的字节（不同底色 + 序号文字），
capture() 在后台线程仅做字节写文件，不触碰 QPixmap/QPainter，保证线程安全。
"""
import threading

from PyQt5.QtCore import QBuffer, QIODevice, Qt
from PyQt5.QtGui import QColor, QFont, QImage, QPainter


class FakeAndroidScreenCapture:
    WIDTH = 360
    HEIGHT = 640

    def __init__(self, count=64, width=None, height=None):
        self._lock = threading.Lock()
        self._index = 0
        self._fail_next = False
        self.calls = []
        w = width or self.WIDTH
        h = height or self.HEIGHT
        self._payloads = [self._render_png(i, w, h) for i in range(count)]

    @staticmethod
    def _render_png(index, w, h):
        """生成可区分 PNG 字节：底色随序号旋转色相，中央绘制序号文字"""
        img = QImage(w, h, QImage.Format_RGB32)
        hue = (index * 137) % 360
        img.fill(QColor.fromHsv(hue, 180, 235))
        painter = QPainter(img)
        painter.setPen(QColor.fromHsv((hue + 180) % 360, 255, 60))
        font = QFont()
        font.setPointSize(48)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(img.rect(), Qt.AlignCenter, f"SHOT {index + 1}")
        painter.end()
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        data = bytes(buf.data())
        buf.close()
        return data

    def fail_next(self):
        """配置下一次 capture 返回 (False, None)"""
        with self._lock:
            self._fail_next = True

    def set_serial(self, serial):
        pass

    def capture(self, output_path=None):
        with self._lock:
            self.calls.append(output_path)
            if self._fail_next:
                self._fail_next = False
                return False, None
            index = self._index
            self._index += 1
        payload = self._payloads[index % len(self._payloads)]
        with open(output_path, "wb") as f:
            f.write(payload)
        return True, output_path
