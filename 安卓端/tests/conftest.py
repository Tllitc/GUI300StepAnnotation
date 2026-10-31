# -*- coding: utf-8 -*-
"""pytest 公共夹具：offscreen Qt、编辑器工厂、模态框自动应答"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

_ANDROID_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ANDROID_DIR not in sys.path:
    sys.path.insert(0, _ANDROID_DIR)

import pytest
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox

import annotation_editor
from annotation_editor import AnnotationEditor
from data_manager import DataManager

from fakes import FakeAndroidScreenCapture
from helpers import flush_events


@pytest.fixture(scope="session")
def qapp():
    """session 级 QApplication（offscreen）"""
    app = QApplication.instance()
    if app is None:
        app = QApplication(["pytest"])
    yield app
    app.processEvents()


class ModalAutoAnswer:
    """模态框自动应答记录器；测试可修改 reply 字段定制行为"""

    def __init__(self):
        self.question_reply = QMessageBox.Yes   # 删除/撤销等确认框默认 Yes
        self.finish_reply = QMessageBox.No      # 完成框"是否继续新任务"默认 No
        self.input_text = "后续任务指令"
        self.input_ok = True
        self.questions = []   # (title, text)
        self.warnings = []    # (title, text)
        self.infos = []       # (title, text)
        self.finish_calls = 0


@pytest.fixture
def modal(monkeypatch):
    """自动应答 annotation_editor 命名空间内的全部模态框"""
    rec = ModalAutoAnswer()

    def fake_question(*args, **kwargs):
        title = args[1] if len(args) > 1 else ""
        text = args[2] if len(args) > 2 else ""
        rec.questions.append((title, text))
        return rec.question_reply

    def fake_warning(*args, **kwargs):
        title = args[1] if len(args) > 1 else ""
        text = args[2] if len(args) > 2 else ""
        rec.warnings.append((title, text))
        return QMessageBox.Ok

    def fake_information(*args, **kwargs):
        title = args[1] if len(args) > 1 else ""
        text = args[2] if len(args) > 2 else ""
        rec.infos.append((title, text))
        return QMessageBox.Ok

    def fake_msg_exec(box):
        # 覆盖 _finish_task 中实例化的 QMessageBox.exec_（"是否继续新任务"）
        rec.finish_calls += 1
        return rec.finish_reply

    class FakeInputDialog:
        """替代 _start_new_round/_start_new_task 中的 QInputDialog 实例"""
        def __init__(self, parent=None):
            self._text = ""

        def setWindowTitle(self, t):
            pass

        def setLabelText(self, t):
            pass

        def setTextEchoMode(self, m):
            pass

        def setTextValue(self, t):
            self._text = t

        def x(self):
            return 0

        def y(self):
            return 0

        def move(self, *a):
            pass

        def exec_(self):
            if rec.input_ok:
                self._text = rec.input_text
                return 1
            return 0

        def textValue(self):
            return self._text

    monkeypatch.setattr(annotation_editor.QMessageBox, "question", fake_question)
    monkeypatch.setattr(annotation_editor.QMessageBox, "warning", fake_warning)
    monkeypatch.setattr(annotation_editor.QMessageBox, "information", fake_information)
    monkeypatch.setattr(annotation_editor.QMessageBox, "exec_", fake_msg_exec)
    monkeypatch.setattr(annotation_editor, "QInputDialog", FakeInputDialog)
    monkeypatch.setattr(annotation_editor.ValidationFailDialog, "exec_", lambda self: 0)
    return rec


@pytest.fixture
def editor_factory(tmp_path, qapp, modal):
    """构造 DataManager + AnnotationEditor + FakeAndroidScreenCapture 的工厂

    make(auto_init=True) 时调用 initialize_task 建立 gui 目录；
    用例结束时统一 close + 等待在途 singleShot 触发 + deleteLater。
    """
    editors = []

    def make(app_name="TestApp", task_instruction="测试任务指令", app_type="",
             screen_info=None, auto_init=True):
        dm = DataManager(base_dir=str(tmp_path))
        dm.create_task_directory("Android", app_type, app_name)
        editor = AnnotationEditor(
            data_manager=dm,
            app_name=app_name,
            task_instruction=task_instruction,
            screen_info=screen_info or {"platform": "Android", "system": "",
                                        "screen_size": [1080, 2400]},
            app_type=app_type,
            serial=None,
            init_window=None,
        )
        editor.screen_capture = FakeAndroidScreenCapture()
        if auto_init:
            editor.initialize_task()
        editors.append(editor)
        return editor

    yield make

    for editor in editors:
        try:
            editor.close()
        except Exception:
            pass
    if editors:
        # 等待 50ms 截图延迟 / 800ms 冷却 / 300ms 新轮等无上下文 singleShot
        # 在对象存活期内触发完毕，避免 deleteLater 后回调命中已析构对象
        QTest.qWait(1000)
    for editor in editors:
        editor.deleteLater()
    flush_events(50)
