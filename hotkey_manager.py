#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows 全局快捷键管理器
使用 Win32 RegisterHotKey API + 隐藏窗口的 nativeEvent
无需额外依赖（不需要 pynput），无需子进程，直接集成 Qt 事件循环。
"""

import ctypes
from ctypes import wintypes

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import pyqtSignal, QObject, Qt


# Windows API 常量
WM_HOTKEY = 0x0312

MOD_ALT      = 0x0001
MOD_CONTROL  = 0x0002
MOD_NOREPEAT = 0x4000

VK_Q = 0x51
VK_S = 0x53

user32 = ctypes.windll.user32


class _HotkeyReceiver(QWidget):
    """隐藏窗口，直接用 nativeEvent 接收 WM_HOTKEY —— 最可靠的方式"""

    hotkey_triggered = pyqtSignal(int)  # 传递 hotkey_id

    def __init__(self, hotkey_map):
        """
        hotkey_map: dict[int, tuple]  e.g. {1: (MOD_ALT, VK_Q), 2: (MOD_CONTROL, VK_S)}
        """
        super().__init__()
        self._hotkey_map = hotkey_map
        # 设置窗口属性，使其不可见且不影响用户
        self.setWindowTitle("_HotkeyReceiver")
        self.setGeometry(-100, -100, 1, 1)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.show()
        self.hide()

    def register_hotkeys(self) -> bool:
        """注册所有热键到此窗口，返回整体是否成功。"""
        hwnd = int(self.winId())
        all_ok = True
        for hotkey_id, (mods, vk) in self._hotkey_map.items():
            ok = user32.RegisterHotKey(hwnd, hotkey_id, mods | MOD_NOREPEAT, vk)
            if not ok:
                print(f"⚠️ RegisterHotKey 失败: id={hotkey_id} mods={mods} vk={vk} (GetLastError={ctypes.get_last_error()})")
                all_ok = False
            else:
                key_name = chr(vk) if 0x30 <= vk <= 0x5A else f"VK_{vk}"
                print(f"✅ RegisterHotKey 成功: id={hotkey_id} HWND={hwnd}")
        return all_ok

    def unregister_hotkeys(self):
        """注销所有热键。"""
        hwnd = int(self.winId())
        for hotkey_id in self._hotkey_map:
            user32.UnregisterHotKey(hwnd, hotkey_id)

    def nativeEvent(self, eventType, message):
        """Qt5 窗口的原生事件处理 —— WM_HOTKEY 直接投递到此窗口。"""
        try:
            # message 是 sip.voidptr，需通过 __int__() 获取地址
            msg = ctypes.cast(
                ctypes.c_void_p(message.__int__()),
                ctypes.POINTER(wintypes.MSG)
            ).contents
        except Exception:
            return False, 0

        if msg.message == WM_HOTKEY:
            hotkey_id = msg.wParam
            if hotkey_id in self._hotkey_map:
                self.hotkey_triggered.emit(hotkey_id)
                return True, 0

        return False, 0


class GlobalHotkeyManager(QObject):
    """
    Windows 全局快捷键管理器。

    用法:
        manager = GlobalHotkeyManager()
        manager.screenshot_triggered.connect(on_screenshot)
        manager.save_continue_triggered.connect(on_save)
        manager.register_all()
        # 退出前:
        manager.unregister_all()
    """

    screenshot_triggered = pyqtSignal()
    save_continue_triggered = pyqtSignal()

    ID_SCREENSHOT    = 1
    ID_SAVE_CONTINUE = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered = False
        self._receiver = None

    def register_all(self):
        """注册所有全局快捷键。"""
        if self._registered:
            return

        # 仅注册全局截图快捷键；Ctrl+S 已作为截图窗口内的确认键，
        # 不能再注册为系统级全局快捷键，否则按键会被全局接收器吞掉、截图窗收不到
        self._receiver = _HotkeyReceiver({
            self.ID_SCREENSHOT:    (MOD_CONTROL,  VK_Q),
        })
        self._receiver.hotkey_triggered.connect(self._on_hotkey)
        ok = self._receiver.register_hotkeys()

        if ok:
            self._registered = True
            print("✅ 全局快捷键已注册: Ctrl+Q (截图)")
        else:
            print("❌ 全局快捷键注册失败，请检查是否有其他程序占用了 Ctrl+Q")

    def unregister_all(self):
        """注销所有全局快捷键。"""
        if not self._registered:
            return

        if self._receiver:
            self._receiver.unregister_hotkeys()
            self._receiver.close()
            self._receiver.deleteLater()
            self._receiver = None

        self._registered = False
        print("✅ 全局快捷键已注销")

    def _on_hotkey(self, hotkey_id: int):
        """接收来自 _HotkeyReceiver 的信号并转发。"""
        if hotkey_id == self.ID_SCREENSHOT:
            self.screenshot_triggered.emit()
        elif hotkey_id == self.ID_SAVE_CONTINUE:
            self.save_continue_triggered.emit()
