#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长步骤交付数据集整理工具（PyQt5 界面）。"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:  # 作为包的一部分导入
    from . import core
except ImportError:  # python datasubtool/app.py 直接运行
    import core


@dataclass
class WorkerResult:
    """工作线程回传给界面的结果。"""

    ok: bool
    success: int = 0
    failed: int = 0
    pending: int = 0
    mapping_path: Path | None = None
    errors: list[str] = field(default_factory=list)


class Worker(QThread):
    """在后台线程中读取 Excel、预检并执行复制转换。"""

    log = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    result_ready = pyqtSignal(object)

    def __init__(self, excel_path, source_root, target_root, start_numbers, parent=None):
        super().__init__(parent)
        self._excel_path = Path(excel_path)
        self._source_root = Path(source_root)
        self._target_root = Path(target_root)
        self._start_numbers = dict(start_numbers or {})
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def _emit_progress(self, done: int, total: int, item) -> None:
        self.progress.emit(done, total, item.new_id)

    def run(self) -> None:
        try:
            rows = core.load_excel(self._excel_path)
        except Exception as exc:
            self.log.emit(f"读取 Excel 失败：{exc}")
            self.result_ready.emit(WorkerResult(ok=False, errors=[str(exc)]))
            return
        self.log.emit(f"已读取交付清单 {len(rows)} 行，开始预检")

        try:
            plan = core.build_plan(
                rows, self._source_root, self._target_root, self._start_numbers
            )
        except Exception as exc:
            self.log.emit(f"预检异常：{exc}")
            self.result_ready.emit(WorkerResult(ok=False, errors=[str(exc)]))
            return

        if not plan.ok:
            for message in plan.errors:
                self.log.emit(f"[预检] {message}")
            self.log.emit(
                f"预检未通过，共 {len(plan.errors)} 项问题，未做任何复制"
            )
            self.result_ready.emit(
                WorkerResult(ok=False, errors=list(plan.errors))
            )
            return

        self.log.emit(f"预检通过，共 {len(plan.items)} 条数据集待处理")
        try:
            result = core.convert(
                plan,
                self._target_root,
                on_log=self.log.emit,
                on_progress=self._emit_progress,
                should_cancel=lambda: self._cancel,
            )
        except Exception as exc:
            self.log.emit(f"转换失败：{exc}")
            self.result_ready.emit(WorkerResult(ok=False, errors=[str(exc)]))
            return

        self.result_ready.emit(
            WorkerResult(
                ok=True,
                success=result.success,
                failed=result.failed,
                pending=result.pending,
                mapping_path=result.mapping_path,
                errors=list(result.errors),
            )
        )


class MainWindow(QMainWindow):
    """交付清单整理工具主窗口。"""

    def __init__(self):
        super().__init__()
        self._worker: Worker | None = None
        self._start_spins: dict[str, QSpinBox] = {}
        self._platforms_cache: list[str] = []
        self._build_ui()
        self._apply_defaults()

    # ---------- 界面搭建 ----------

    def _build_ui(self) -> None:
        self.setWindowTitle("长步骤交付数据集整理工具")
        self.resize(900, 680)

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        self.excel_edit = QLineEdit()
        self.source_edit = QLineEdit()
        self.target_edit = QLineEdit()

        self.excel_button = QPushButton("浏览…")
        self.source_button = QPushButton("浏览…")
        self.target_button = QPushButton("浏览…")
        self._browse_buttons = [
            self.excel_button,
            self.source_button,
            self.target_button,
        ]

        rows = (
            ("交付 Excel：", self.excel_edit, self.excel_button),
            ("数据母目录：", self.source_edit, self.source_button),
            ("目标目录：", self.target_edit, self.target_button),
        )
        for index, (label_text, edit, button) in enumerate(rows):
            grid.addWidget(QLabel(label_text), index, 0)
            grid.addWidget(edit, index, 1)
            grid.addWidget(button, index, 2)
        layout.addLayout(grid)

        self.excel_button.clicked.connect(self._browse_excel)
        self.source_button.clicked.connect(self._browse_source)
        self.target_button.clicked.connect(self._browse_target)
        self.excel_edit.editingFinished.connect(self._refresh_platform_starts)
        self.source_edit.editingFinished.connect(self._refresh_platform_starts)

        self.platform_group = QGroupBox("命中平台起始序号（多批次续号用，默认 1）")
        group_layout = QVBoxLayout(self.platform_group)
        self.platform_table = QTableWidget(0, 2)
        self.platform_table.setHorizontalHeaderLabels(["平台", "起始序号"])
        self.platform_table.verticalHeader().setVisible(False)
        self.platform_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.platform_table.setSelectionMode(QAbstractItemView.NoSelection)
        header = self.platform_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.platform_table.setColumnWidth(1, 140)
        self.platform_table.setMinimumHeight(90)
        self.platform_table.setMaximumHeight(150)
        group_layout.addWidget(self.platform_table)
        layout.addWidget(self.platform_group)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("开始转换")
        self.start_button.setDefault(True)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.cancel_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.start_button.clicked.connect(self._on_start)
        self.cancel_button.clicked.connect(self._on_cancel)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("已完成 0 / 0")
        layout.addWidget(self.progress_bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view, 1)

        self.status_label = QLabel("就绪")
        layout.addWidget(self.status_label)

        self._center_on_screen()

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = self.frameGeometry()
        geometry.moveCenter(screen.availableGeometry().center())
        self.move(geometry.topLeft())

    def _apply_defaults(self) -> None:
        default_excel = Path(__file__).with_name("长步骤交付.xlsx")
        if default_excel.is_file():
            self.excel_edit.setText(str(default_excel))

    # ---------- 日志与状态 ----------

    def append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{stamp}] {message}")

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        for button in self._browse_buttons:
            button.setEnabled(not running)
        self.platform_group.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def _refresh_platform_starts(self) -> None:
        """按当前 Excel 与母目录刷新命中平台及其起始序号。"""
        previous = {platform: spin.value() for platform, spin in self._start_spins.items()}
        self._start_spins.clear()
        self.platform_table.setRowCount(0)

        excel_text = self.excel_edit.text().strip()
        source_text = self.source_edit.text().strip()
        if not excel_text or not source_text:
            self._platforms_cache = []
            return
        try:
            rows = core.load_excel(Path(excel_text))
            platforms = core.detect_platforms(rows, Path(source_text))
        except Exception as exc:
            self._platforms_cache = []
            self.append_log(f"读取命中平台失败：{exc}")
            return

        for row_index, platform in enumerate(platforms):
            self.platform_table.insertRow(row_index)
            item = QTableWidgetItem(platform)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.platform_table.setItem(row_index, 0, item)
            spin = QSpinBox()
            spin.setRange(1, 999999)
            spin.setValue(previous.get(platform, 1))
            self.platform_table.setCellWidget(row_index, 1, spin)
            self._start_spins[platform] = spin

        if platforms != self._platforms_cache:
            self.append_log("命中平台：" + "、".join(platforms))
        self._platforms_cache = platforms

    def _collect_start_numbers(self) -> dict[str, int]:
        return {platform: spin.value() for platform, spin in self._start_spins.items()}

    # ---------- 路径选择 ----------

    def _browse_excel(self) -> None:
        current = self.excel_edit.text().strip()
        start_dir = str(Path(current).parent) if current else str(Path.cwd())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择交付 Excel",
            start_dir,
            "Excel 文件 (*.xlsx *.xlsm)",
        )
        if path:
            self.excel_edit.setText(path)
            self._refresh_platform_starts()

    def _browse_source(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "选择数据母目录", self.source_edit.text().strip() or str(Path.cwd())
        )
        if path:
            self.source_edit.setText(path)
            self._refresh_platform_starts()

    def _browse_target(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "选择目标目录", self.target_edit.text().strip() or str(Path.cwd())
        )
        if path:
            self.target_edit.setText(path)

    # ---------- 校验与启动 ----------

    def _validate_paths(self) -> tuple[Path, Path, Path] | None:
        excel_text = self.excel_edit.text().strip()
        source_text = self.source_edit.text().strip()
        target_text = self.target_edit.text().strip()

        if not excel_text:
            QMessageBox.warning(self, "提示", "请先选择交付 Excel 文件")
            return None
        excel_path = Path(excel_text)
        if not excel_path.is_file():
            QMessageBox.warning(
                self, "提示", f"交付 Excel 文件不存在：\n{excel_path}"
            )
            return None

        if not source_text:
            QMessageBox.warning(self, "提示", "请先选择数据母目录")
            return None
        source_root = Path(source_text)
        if not source_root.is_dir():
            QMessageBox.warning(
                self, "提示", f"数据母目录不存在或不是文件夹：\n{source_root}"
            )
            return None

        if not target_text:
            QMessageBox.warning(self, "提示", "请先选择目标目录")
            return None
        target_root = Path(target_text)
        if not target_root.is_dir():
            QMessageBox.warning(
                self, "提示", f"目标目录不存在或不是文件夹：\n{target_root}"
            )
            return None

        return excel_path, source_root, target_root

    def _on_start(self) -> None:
        if self._worker is not None:
            return
        paths = self._validate_paths()
        if paths is None:
            return
        excel_path, source_root, target_root = paths
        if not self._start_spins:
            self._refresh_platform_starts()
        start_numbers = self._collect_start_numbers()
        if start_numbers:
            detail = "，".join(f"{platform} {number}" for platform, number in start_numbers.items())
            self.append_log(f"起始序号：{detail}")

        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("已完成 0 / 0")
        self.status_label.setText("正在处理 0/0")
        self.append_log("开始转换")
        self.append_log(f"交付 Excel：{excel_path}")
        self.append_log(f"数据母目录：{source_root}")
        self.append_log(f"目标目录：{target_root}")

        worker = Worker(excel_path, source_root, target_root, start_numbers, self)
        worker.log.connect(self.append_log)
        worker.progress.connect(self._on_progress)
        worker.result_ready.connect(self._on_worker_finished)
        self._worker = worker
        self._set_running(True)
        worker.start()

    # ---------- 运行期回调 ----------

    def _on_progress(self, done: int, total: int, new_id: str) -> None:
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)
        self.progress_bar.setFormat(f"已完成 {done} / {total}")
        self.status_label.setText(f"正在处理 {done}/{total}")

    def _on_cancel(self) -> None:
        if self._worker is None:
            return
        self._worker.request_cancel()
        self.cancel_button.setEnabled(False)
        self.append_log("已请求取消，将在当前数据集完成后停止")

    def _on_worker_finished(self, result: WorkerResult) -> None:
        worker = self._worker
        if worker is not None:
            worker.wait()
            worker.deleteLater()
        self._worker = None
        self._set_running(False)

        if result.ok:
            self.status_label.setText("完成")
            self.append_log(
                f"处理结束：成功 {result.success}，失败 {result.failed}，"
                f"未处理 {result.pending}"
            )
            if result.mapping_path:
                self.append_log(f"映射表路径：{result.mapping_path}")
        else:
            self.status_label.setText("完成（预检未通过）")

        self._show_result_dialog(result)

    def _show_result_dialog(self, result: WorkerResult) -> None:
        detail = "\n".join(result.errors)
        if len(result.errors) > 15:
            detail = "\n".join(result.errors[:15]) + "\n……"

        if not result.ok:
            message = "预检未通过，未做任何复制。"
            if detail:
                message += "\n\n" + detail
            QMessageBox.warning(self, "预检未通过", message)
            return

        if result.failed or result.pending:
            message = (
                f"处理完成：成功 {result.success}，失败 {result.failed}，"
                f"未处理 {result.pending}。"
            )
            if result.mapping_path:
                message += f"\n\n映射表：{result.mapping_path}"
            if detail:
                message += "\n\n" + detail
            QMessageBox.warning(self, "完成（存在问题）", message)
            return

        message = f"全部完成：成功 {result.success} 条数据集。"
        if result.mapping_path:
            message += f"\n\n映射表：{result.mapping_path}"
        QMessageBox.information(self, "完成", message)

    # ---------- 关闭处理 ----------

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            self._worker.request_cancel()
            self._worker.wait()
            self._worker = None
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("长步骤交付数据集整理工具")
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())