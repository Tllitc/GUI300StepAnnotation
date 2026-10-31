# -*- coding: utf-8 -*-
"""pytest 全局夹具：无真机离线测试基础设施。

离线运行（在 ios端 目录下）::

    python -m pytest tests -q

本模块必须在 import PyQt5 之前完成 QT_QPA_PLATFORM=offscreen 设置，
并把 ios端 产品目录插入 sys.path，使产品模块的顶层 import
（`from data_manager import DataManager` 等）可用。
"""

# === 最顶部：offscreen 必须在任何 PyQt5 import 之前设置 ===
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import sys

# === 把 ios端 产品目录插入 sys.path[0] ===
_IOS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _IOS_DIR not in sys.path:
    sys.path.insert(0, _IOS_DIR)
# tests 目录本身也加入，保证 `from helpers import ...` / `from fakes import ...`
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import pytest

from PyQt5.QtWidgets import QApplication, QMessageBox

import annotation_editor as _ae
from annotation_editor import AnnotationEditor
from data_manager import DataManager
from fakes import FakeScreenCapture


class DialogController:
    """模态对话框应答控制器。

    默认策略（无人值守）：
      - question -> Yes（删除/撤销/继续新任务全部选“是”）
      - information/warning/critical/about -> 自动关闭（返回 None）
      - QInputDialog.getText -> (next_instruction, True)

    测试可通过 `dialogs` fixture 临时改写：
      - ctrl.question_result = QMessageBox.No
      - ctrl.input_ok = False             # 输入框取消，返回 ("", False)
      - ctrl.next_instruction = "..."
    """

    def __init__(self):
        self.question_result = QMessageBox.Yes
        self.next_instruction = "第二轮新指令"
        self.input_ok = True
        # 调用记录：[("question", title, text), ("getText", title, ...), ...]
        self.calls = []

    # --- QMessageBox 替身 ---
    def question(self, parent=None, title="", text="", *args, **kwargs):
        self.calls.append(("question", title, text))
        return self.question_result

    @staticmethod
    def information(parent=None, title="", text="", *args, **kwargs):
        return None

    @staticmethod
    def warning(parent=None, title="", text="", *args, **kwargs):
        return None

    @staticmethod
    def critical(parent=None, title="", text="", *args, **kwargs):
        return None

    @staticmethod
    def about(parent=None, title="", text="", *args, **kwargs):
        return None

    # --- QInputDialog 替身 ---
    def get_text(self, parent=None, title="", label="", *args, **kwargs):
        self.calls.append(("getText", title, label))
        if self.input_ok:
            return self.next_instruction, True
        return "", False


@pytest.fixture(scope="session")
def qapp():
    """session 级 QApplication（offscreen）。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def dm(tmp_path):
    """function 级 DataManager，current_dir 指向独立临时目录。"""
    manager = DataManager(base_dir=str(tmp_path))
    return manager


@pytest.fixture
def dialogs(monkeypatch):
    """非 autouse：patch annotation_editor 模块命名空间内的对话框类。

    返回 DialogController，供测试临时改变应答策略。
    """
    ctrl = DialogController()

    monkeypatch.setattr(_ae.QMessageBox, "question", ctrl.question)
    monkeypatch.setattr(_ae.QMessageBox, "information", ctrl.information)
    monkeypatch.setattr(_ae.QMessageBox, "warning", ctrl.warning)
    monkeypatch.setattr(_ae.QMessageBox, "critical", ctrl.critical)
    monkeypatch.setattr(_ae.QMessageBox, "about", ctrl.about)
    monkeypatch.setattr(_ae.QInputDialog, "getText", ctrl.get_text)
    return ctrl


@pytest.fixture(autouse=True)
def auto_dialogs(dialogs):
    """autouse：保证每个测试都被自动应答夹具覆盖。"""
    return dialogs


@pytest.fixture
def editor(qapp, dm, dialogs):
    """function 级真实 AnnotationEditor：

    - 使用临时 DataManager；
    - 构造后调用 initialize_gui_directory() 初始化 gui_XXXXXX 任务目录；
    - 用 FakeScreenCapture 替换 editor.screen_capture（不依赖真机）。
    """
    ed = AnnotationEditor(
        data_manager=dm,
        app_name="测试App",
        task_instruction="测试指令",
        screen_info={"screen_size": [390, 844]},
        app_type="iOS",
        udid=None,
        close_callback=None,
    )
    # 产品代码真实的任务目录初始化入口（设置 gui_number / gui_dir）
    ed.initialize_gui_directory()
    # 注入桩截图器，后续 take_screenshot->_do_screenshot 全链路走真实产品代码
    ed.screen_capture = FakeScreenCapture()
    # 助手函数（helpers.finish_task 等）借此临时调整对话框应答
    ed._test_dialogs = dialogs

    qapp.processEvents()
    yield ed

    ed.close()
    ed.deleteLater()
    qapp.processEvents()
