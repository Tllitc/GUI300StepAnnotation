# -*- coding: utf-8 -*-
"""pytest 全局夹具：桌面端离线测试基础设施。

运行（在项目根目录下）::

    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests -q

本模块必须在任何 PyQt5 import 之前完成 QT_QPA_PLATFORM=offscreen，
并把产品目录插入 sys.path，确保顶层 import
（`from data_manager import DataManager` 等）可用。
"""

# === 最顶部：offscreen 必须在任何 PyQt5 import 之前设置 ===
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

# === 把项目根目录插入 sys.path[0] ===
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# tests 目录本身也加入
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import pytest

from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QApplication, QMessageBox, QInputDialog, QLineEdit

import annotation_editor as _ae
from annotation_editor import AnnotationEditor
from data_manager import DataManager
from fakes import FakeScreenshotCaptureWindow


# ---------------------------------------------------------------------------
# 模态对话框应答控制器
# ---------------------------------------------------------------------------
class DialogController:
    """模态对话框应答控制器（无人值守）。

    默认：question -> Yes；warning/information/critical/about -> None；
    QInputDialog.getText -> (next_instruction, getText_result_ok)。

    测试通过 dialogs fixture 临时改写：
        ctrl.question_result = QMessageBox.No
        ctrl.input_ok = False                # ("", False)
        ctrl.next_instruction = "..."        # 下一轮任务指令
    """

    def __init__(self):
        self.question_result = QMessageBox.Yes
        self.input_ok = True
        self.getText_result_ok = True
        # next_instruction 与 getText_result_text 共用一份后备存储：二者互为别名，
        # 任一赋值都会改变 QInputDialog.getText 的返回值（T8：早期 get_text 只读
        # getText_result_text，导致 next_instruction 是永不生效的死字段）。
        self._instruction = "第二轮新指令"
        self.calls = []  # 记录调用：[("question", title, text), ...]

    @property
    def next_instruction(self):
        return self._instruction

    @next_instruction.setter
    def next_instruction(self, value):
        self._instruction = value

    @property
    def getText_result_text(self):
        return self._instruction

    @getText_result_text.setter
    def getText_result_text(self, value):
        self._instruction = value

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

    def get_text(self, parent=None, title="", label="", *args, **kwargs):
        self.calls.append(("getText", title, label))
        if self.input_ok:
            return self._instruction, bool(self.getText_result_ok)
        return "", False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
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
    return _make_data_manager(tmp_path)


def _make_data_manager(tmp_path):
    manager = DataManager(base_dir=str(tmp_path))
    manager.create_task_directory("windows", "test", "测试App")
    return manager


@pytest.fixture
def dialogs(monkeypatch):
    """非 autouse：patch annotation_editor 模块命名空间内的对话框类。"""
    ctrl = DialogController()
    monkeypatch.setattr(_ae.QMessageBox, "question", ctrl.question)
    monkeypatch.setattr(_ae.QMessageBox, "information", ctrl.information)
    monkeypatch.setattr(_ae.QMessageBox, "warning", ctrl.warning)
    monkeypatch.setattr(_ae.QMessageBox, "critical", ctrl.critical)
    monkeypatch.setattr(_ae.QMessageBox, "about", ctrl.about)
    # QInputDialog 在 annotation_editor 中是函数内 import（from PyQt5.QtWidgets import QInputDialog）
    # 所以必须 patch PyQt5.QtWidgets 原始模块，每次函数 import 都会拿到我们替换后的类
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", ctrl.get_text)
    return ctrl


@pytest.fixture(autouse=True)
def auto_dialogs(dialogs):
    """autouse：保证每个测试都被自动应答夹具覆盖。"""
    return dialogs


@pytest.fixture
def editor_factory(qapp, dialogs, monkeypatch, tmp_path):
    """AnnotationEditor 工厂（对齐安卓端 editor_factory 的 make(auto_init=...) 形态）。

    续采类用例需要在同一测试内构造第二个编辑器读取同一份草稿，故：
      - make() 缺省时每次新建一个指向同一 tmp_path 的 DataManager；
      - make(dm=...) 复用既有 DataManager（editor fixture 用它保持与 dm 的关联）；
      - make(auto_init=False) 不预分配 gui_number / 不建任务目录（用于「构造即校验
        尚未落盘」的场景）。
    teardown 统一 cleanup_resources + close + deleteLater，并在 close 之间推进事件
    循环，避免已析构对象被在途 singleShot 命中。
    """
    # 模块级替换：annotation_editor.py 内 `from screenshot_capture import
    # ScreenshotCaptureWindow` 之后所有引用都指向 Fake
    monkeypatch.setattr(_ae, "ScreenshotCaptureWindow", FakeScreenshotCaptureWindow)

    editors = []

    def make(dm=None, app_name="测试App",
             task_instruction="测试指令：在测试App中完成一件事",
             app_type="测试", screen_info=None, auto_init=True):
        manager = dm if dm is not None else _make_data_manager(tmp_path)
        ed = AnnotationEditor(
            data_manager=manager,
            app_name=app_name,
            task_instruction=task_instruction,
            screen_info=screen_info or {
                "platform": "Windows", "system": "Windows 11",
                "screen_size": [1920, 1080],
            },
            app_type=app_type,
            hotkey_listener=None,
            init_window=None,
        )
        # 产品代码里 gui_number 为 None 时延迟在首次截图分配；这里默认提前分一个，
        # 方便草稿/轮次等测试在截图前也能产生正确路径。
        if auto_init:
            ed.gui_number = manager.get_next_gui_number()
            manager.create_gui_directory(ed.gui_number)

        ed._test_dialogs = dialogs
        editors.append(ed)
        qapp.processEvents()
        return ed

    yield make

    for ed in editors:
        ed.cleanup_resources()
        try:
            if not ed._is_closing:
                ed.close()
        except RuntimeError:
            pass
        try:
            ed.deleteLater()
        except Exception:
            pass
        try:
            qapp.processEvents()
        except Exception:
            pass


@pytest.fixture
def editor(editor_factory, dm):
    """function 级真实 AnnotationEditor（基于 editor_factory，与 dm 同源）。"""
    return editor_factory(dm=dm)
