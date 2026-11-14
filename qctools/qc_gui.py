#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立语义质检 GUI（PyQt6，全程只读）。

与命令行 check_semantic_origin.py 同口径：直接 import 复用 check_semantic_origin（别名 O）
与 check_semantic_v1（别名 C），GUI 内不重写任何 B/C/D 检查规则。
支持添加一个或多个目录 / gui_XXXXXX.json 作为输入，后台线程质检并回传进度，
提供分组/分类统计、组合筛选明细、md/json 导出、截图预览与资源管理器定位。
本程序不提供任何修改 gui json / 截图或编辑保存的入口。

用法：
  python qc_gui.py
"""
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # 与 check_semantic_origin.py 一致，保证同目录模块可导入

# 容错导入检查模块：失败时窗口仍可打开，仅禁用质检/导出入口
IMPORT_ERROR = ""
try:
    import check_semantic_origin as O  # noqa: E402
    import check_semantic_v1 as C      # noqa: E402
except Exception as e:  # 任何导入异常都降级为提示，不崩溃
    O = None
    C = None
    IMPORT_ERROR = f"{type(e).__name__}: {e}"

from PyQt6.QtCore import Qt, QThread, pyqtSignal  # noqa: E402
from PyQt6.QtGui import QAction, QPixmap          # noqa: E402
from PyQt6.QtWidgets import (                     # noqa: E402
    QAbstractItemView, QApplication, QComboBox, QDialog, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# 分组汇总表的短列名，照抄 check_semantic_origin.write_md 里的 short 列表
SHORT = ["B1", "B2", "C1", "C2", "D繁体", "D零宽(intent)", "D零宽(text)", "D动作词错字", "D缺动作词",
         "D观察/提问", "D混入指令", "D反引号", "D换行"]
CATS = C.CATS if C is not None else []
# 行数据在单元格上的存取角色（与步号排序用的 UserRole 区分）
ROW_ROLE = Qt.ItemDataRole.UserRole + 1
DEFAULT_TITLE = "原始数据语义问题报告"


def collect_results(inputs, should_cancel=None, progress_cb=None):
    """与 check_semantic_origin.run 完全同口径的纯函数质检核心（不依赖 Qt）。

    入参 inputs 为目录或 gui json 路径列表；逐行对照 run() 实现：seen 去重、
    group_key/task_label 按各自输入 root 计算、to_pseudo_record + check_record、
    extra_tasks 只补任务文本类（r[1] is None）检查、单文件异常计入 failed 不中断。
    rows 在 CLI 字段外额外带内部字段 src（gui json 绝对路径），供截图预览与资源管理器定位。
    返回 (rows, stats, failed)；被取消时返回 None（不产出结果）。
    """
    rows, stats, failed = [], {}, []
    seen = set()
    plan = []  # (root, fp)：保留文件首次被发现时所属的输入 root（多输入 group_key 口径同 CLI）
    for inp in inputs:
        root = Path(inp).resolve()
        for fp in O.find_task_jsons(root):
            if fp in seen:
                continue
            seen.add(fp)
            plan.append((root, fp))
    total = len(plan)
    for done, (root, fp) in enumerate(plan, 1):
        if should_cancel is not None and should_cancel():
            return None
        if progress_cb is not None:
            progress_cb(done, total, str(fp))
        g = O.group_key(fp, root)
        st = stats.setdefault(g, dict(n=0, bad=0))
        st["n"] += 1
        tid = O.task_label(fp, root)
        try:
            data = json.load(open(fp, encoding="utf-8"))
            rec, shots, extra_tasks = O.to_pseudo_record(data)
            res = C.check_record(rec)
            for t in extra_tasks:  # 多轮追问任务：只做任务文本（任务级）检查，照抄 run()
                res += [r for r in C.check_record({"messages": [{"role": "system", "content": ""},
                                                                  {"role": "user", "content": t}],
                                                    "meta": {}}) if r[1] is None]
        except Exception as e:
            failed.append((str(fp), str(e)))
            continue
        for cat, step, desc, extra in res:
            shot = shots[step] if step is not None and step < len(shots) else ""
            rows.append(dict(group=g, task=tid, step=step, shot=shot, cat=cat,
                             desc=desc, extra=extra, src=str(fp.resolve())))
        if res:
            st["bad"] += 1
    if progress_cb is not None:
        progress_cb(total, total, "")
    return rows, stats, failed


class CheckWorker(QThread):
    """后台质检线程：回传进度与最终结果，支持取消。"""

    progress = pyqtSignal(int, int, str)          # 已完成, 总数, 当前文件绝对路径
    succeeded = pyqtSignal(object)                # (rows, stats, failed)
    failed_fatal = pyqtSignal(str)                # 兜底异常（单文件异常已在核心内捕获）

    def __init__(self, inputs, parent=None):
        super().__init__(parent)
        self._inputs = list(inputs)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            result = collect_results(
                self._inputs,
                should_cancel=lambda: self._cancel,
                progress_cb=lambda done, total, cur: self.progress.emit(done, total, cur),
            )
        except Exception as e:  # 兜底：避免线程内异常静默丢失
            self.failed_fatal.emit(f"{type(e).__name__}: {e}")
            return
        if result is None:
            return  # 已取消：不回传结果
        self.succeeded.emit(result)


class StepItem(QTableWidgetItem):
    """步号列：按数值排序（任务级 None 存为 -1），而不是按文案排序。"""

    def __lt__(self, other):
        try:
            return self.data(Qt.ItemDataRole.UserRole) < other.data(Qt.ItemDataRole.UserRole)
        except TypeError:
            return super().__lt__(other)


class ImageDialog(QDialog):
    """截图预览对话框：QLabel + QScrollArea，大图缩放适配、可滚动。"""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(os.path.basename(path))
        self.resize(960, 720)
        lay = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        label = QLabel()
        pix = QPixmap(str(path))
        screen = QApplication.primaryScreen().availableGeometry()
        max_w, max_h = min(1000, screen.width() - 80), min(760, screen.height() - 80)
        if pix.width() > max_w or pix.height() > max_h:
            pix = pix.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pix)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(label)
        lay.addWidget(scroll)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        lay.addWidget(btn_close)


class QcWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("语义质检工具（B / C / D，只读）")
        self.resize(1280, 860)
        self._rows, self._stats, self._failed = [], {}, []
        self._worker = None
        self._build_ui()
        if O is None or C is None:
            self._apply_degraded()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        root_lay = QVBoxLayout(central)

        # 顶部：输入与运行区
        box_in = QGroupBox("输入（目录或 gui_XXXXXX.json，可添加多个；重复文件自动去重）")
        in_lay = QVBoxLayout(box_in)
        btn_row = QHBoxLayout()
        self.btn_add_dir = QPushButton("添加目录")
        self.btn_add_file = QPushButton("添加文件")
        self.btn_remove = QPushButton("移除选中")
        self.btn_clear = QPushButton("清空")
        for b in (self.btn_add_dir, self.btn_add_file, self.btn_remove, self.btn_clear):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        in_lay.addLayout(btn_row)
        self.input_list = QListWidget()
        self.input_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.input_list.setMaximumHeight(110)
        in_lay.addWidget(self.input_list)

        run_row = QHBoxLayout()
        self.btn_run = QPushButton("开始检查")
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(360)
        self.lbl_progress = QLabel("就绪")
        run_row.addWidget(self.btn_run)
        run_row.addWidget(self.btn_cancel)
        run_row.addWidget(self.progress_bar)
        run_row.addWidget(self.lbl_progress, 1)
        in_lay.addLayout(run_row)

        self.lbl_import_err = QLabel("")
        self.lbl_import_err.setStyleSheet("color: #c00;")
        self.lbl_import_err.setWordWrap(True)
        self.lbl_import_err.hide()
        in_lay.addWidget(self.lbl_import_err)
        root_lay.addWidget(box_in)

        # 中部：统计 + 明细（上下可拖动分割）
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._build_stats_box())
        splitter.addWidget(self._build_detail_box())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root_lay.addWidget(splitter, 1)

        # 底部导出
        export_row = QHBoxLayout()
        self.btn_export_md = QPushButton("导出 md")
        self.btn_export_json = QPushButton("导出 json")
        self.btn_export_md.setEnabled(False)
        self.btn_export_json.setEnabled(False)
        export_row.addWidget(self.btn_export_md)
        export_row.addWidget(self.btn_export_json)
        export_row.addStretch(1)
        root_lay.addLayout(export_row)

        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪")

        self.btn_add_dir.clicked.connect(self._add_dir)
        self.btn_add_file.clicked.connect(self._add_file)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear.clicked.connect(self.input_list.clear)
        self.btn_run.clicked.connect(self._start)
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_export_md.clicked.connect(self._export_md)
        self.btn_export_json.clicked.connect(self._export_json)

    def _build_stats_box(self):
        box = QGroupBox("统计")
        lay = QVBoxLayout(box)
        self.lbl_summary = QLabel("尚未运行")
        lay.addWidget(self.lbl_summary)

        grids = QHBoxLayout()
        # 分组汇总表：分组、任务数、有问题任务 + 13 个类别短列
        self.group_table = QTableWidget(0, 3 + len(SHORT))
        self.group_table.setHorizontalHeaderLabels(["分组", "任务数", "有问题任务"] + SHORT)
        self.group_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.group_table.horizontalHeader().setStretchLastSection(True)
        grids.addWidget(self.group_table, 3)
        # 类别总数表
        self.cat_table = QTableWidget(0, 2)
        self.cat_table.setHorizontalHeaderLabels(["类别", "数量"])
        self.cat_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cat_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        grids.addWidget(self.cat_table, 1)
        lay.addLayout(grids, 1)

        lay.addWidget(QLabel("解析失败清单："))
        self.failed_list = QListWidget()
        self.failed_list.setMaximumHeight(90)
        lay.addWidget(self.failed_list)
        return box

    def _build_detail_box(self):
        box = QGroupBox("问题明细（双击预览截图，右键更多操作）")
        lay = QVBoxLayout(box)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("类别："))
        self.combo_cat = QComboBox()
        self.combo_cat.addItem("全部")
        self.combo_cat.addItems(CATS)
        filter_row.addWidget(self.combo_cat)
        filter_row.addWidget(QLabel("分组："))
        self.combo_group = QComboBox()
        self.combo_group.addItem("全部")
        filter_row.addWidget(self.combo_group)
        filter_row.addWidget(QLabel("关键字："))
        self.edit_kw = QLineEdit()
        self.edit_kw.setPlaceholderText("匹配 任务 / 描述 / 附加 / 截图名（子串，忽略大小写）")
        filter_row.addWidget(self.edit_kw, 1)
        self.lbl_filter = QLabel("筛选后 0 / 总 0")
        filter_row.addWidget(self.lbl_filter)
        lay.addLayout(filter_row)

        self.detail_table = QTableWidget(0, 7)
        self.detail_table.setHorizontalHeaderLabels(["分组", "任务", "步号", "截图文件", "类别", "描述", "附加"])
        self.detail_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.detail_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.detail_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.detail_table.setSortingEnabled(True)
        self.detail_table.horizontalHeader().setStretchLastSection(True)
        self.detail_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lay.addWidget(self.detail_table, 1)

        self.combo_cat.currentIndexChanged.connect(self._apply_filter)
        self.combo_group.currentIndexChanged.connect(self._apply_filter)
        self.edit_kw.textChanged.connect(self._apply_filter)
        self.detail_table.cellDoubleClicked.connect(lambda *_: self._preview())
        self.detail_table.customContextMenuRequested.connect(self._detail_menu)
        return box

    def _apply_degraded(self):
        self.lbl_import_err.setText(f"检查模块导入失败，质检与导出已禁用：{IMPORT_ERROR}")
        self.lbl_import_err.show()
        self.btn_run.setEnabled(False)
        self.btn_export_md.setEnabled(False)
        self.btn_export_json.setEnabled(False)
        self.statusBar().showMessage("检查模块不可用")

    # ------------------------------------------------------------------ 输入
    def _existing_inputs(self):
        return [self.input_list.item(i).text() for i in range(self.input_list.count())]

    def _add_inputs(self, paths):
        existing = set(self._existing_inputs())
        for p in paths:
            if p and p not in existing:
                self.input_list.addItem(p)
                existing.add(p)

    def _add_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择包含 gui_XXXXXX.json 的目录")
        if path:
            self._add_inputs([path])

    def _add_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 gui json", "", "gui JSON (gui_*.json);;所有文件 (*.*)")
        if path:
            self._add_inputs([path])

    def _remove_selected(self):
        for item in self.input_list.selectedItems():
            self.input_list.takeItem(self.input_list.row(item))

    # ------------------------------------------------------------------ 运行
    def _set_running(self, running):
        self.btn_run.setEnabled(not running and O is not None and C is not None)
        self.btn_cancel.setEnabled(running)
        for b in (self.btn_add_dir, self.btn_add_file, self.btn_remove, self.btn_clear):
            b.setEnabled(not running)

    def _start(self):
        inputs = self._existing_inputs()
        if not inputs:
            QMessageBox.warning(self, "提示", "请先添加目录或 gui_XXXXXX.json 文件。")
            return
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.lbl_progress.setText("开始检查…")
        self._set_running(True)
        self.statusBar().showMessage("质检中…")
        self._worker = CheckWorker(inputs)
        self._worker.progress.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed_fatal.connect(self._on_fatal)
        self._worker.finished.connect(self._on_thread_finished)
        self._worker.start()

    def _cancel(self):
        if self._worker is not None:
            self._worker.cancel()
            self.btn_cancel.setEnabled(False)
            self.lbl_progress.setText("正在取消…")
            self.statusBar().showMessage("正在取消…")

    def _on_progress(self, done, total, current):
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)
        name = os.path.basename(current) if current else ""
        self.lbl_progress.setText(f"{done}/{total} {name}")

    def _on_succeeded(self, result):
        self._rows, self._stats, self._failed = result
        self._populate_stats()
        self._rebuild_group_filter()
        self._apply_filter()
        has_result = bool(self._stats)
        self.btn_export_md.setEnabled(has_result)
        self.btn_export_json.setEnabled(has_result)
        total = sum(v["n"] for v in self._stats.values())
        self.statusBar().showMessage(
            f"完成：{total} 个任务，{len(self._rows)} 条问题，解析失败 {len(self._failed)} 个")

    def _on_fatal(self, msg):
        QMessageBox.critical(self, "质检异常", msg)
        self.statusBar().showMessage(f"质检异常：{msg}")

    def _on_thread_finished(self):
        self._set_running(False)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    # ------------------------------------------------------------------ 统计
    def _populate_stats(self):
        rows, stats, failed = self._rows, self._stats, self._failed
        total = sum(v["n"] for v in stats.values())
        bad = sum(v["bad"] for v in stats.values())
        self.lbl_summary.setText(
            f"分组 {len(stats)} 个；任务总数 {total}；有问题任务 {bad}；解析失败 {len(failed)}")
        # 分组汇总（与 write_md 一致：按分组名排序，0 条类别留空）
        self.group_table.setSortingEnabled(False)
        self.group_table.setRowCount(len(stats))
        for i, (g, st) in enumerate(sorted(stats.items())):
            cnt = Counter(r["cat"] for r in rows if r["group"] == g)
            vals = [g, str(st["n"]), str(st["bad"])] + [str(cnt[c]) if cnt[c] else "" for c in CATS]
            for col, text in enumerate(vals):
                self.group_table.setItem(i, col, QTableWidgetItem(text))
        self.group_table.setSortingEnabled(True)
        # 类别总数（13 类全列，含 0）
        all_cnt = Counter(r["cat"] for r in rows)
        self.cat_table.setRowCount(len(CATS))
        for i, c in enumerate(CATS):
            self.cat_table.setItem(i, 0, QTableWidgetItem(c))
            self.cat_table.setItem(i, 1, QTableWidgetItem(str(all_cnt.get(c, 0))))
        # 解析失败清单
        self.failed_list.clear()
        for p, e in failed:
            self.failed_list.addItem(f"{p}  ->  {e}")

    def _rebuild_group_filter(self):
        self.combo_group.blockSignals(True)
        self.combo_group.clear()
        self.combo_group.addItem("全部")
        self.combo_group.addItems(sorted(self._stats.keys()))
        self.combo_group.blockSignals(False)

    # ------------------------------------------------------------------ 明细/筛选
    def _apply_filter(self):
        cat = self.combo_cat.currentText()
        group = self.combo_group.currentText()
        kw = self.edit_kw.text().strip().lower()
        filtered = []
        for r in self._rows:
            if cat != "全部" and r["cat"] != cat:
                continue
            if group != "全部" and r["group"] != group:
                continue
            if kw and not any(kw in str(r[k]).lower() for k in ("task", "desc", "extra", "shot")):
                continue
            filtered.append(r)
        table = self.detail_table
        table.setSortingEnabled(False)
        table.setRowCount(len(filtered))
        for i, r in enumerate(filtered):
            step_text = "任务级" if r["step"] is None else str(r["step"])
            vals = [r["group"], r["task"], step_text, r["shot"], r["cat"], r["desc"], r["extra"]]
            for col, val in enumerate(vals):
                item = StepItem() if col == 2 else QTableWidgetItem()
                item.setText(str(val))
                if col == 2:
                    item.setData(Qt.ItemDataRole.UserRole, -1 if r["step"] is None else int(r["step"]))
                if col == 0:
                    item.setData(ROW_ROLE, r)
                table.setItem(i, col, item)
        table.setSortingEnabled(True)
        self.lbl_filter.setText(f"筛选后 {len(filtered)} / 总 {len(self._rows)}")

    def _current_row(self):
        table = self.detail_table
        item = table.item(table.currentRow(), 0)
        return item.data(ROW_ROLE) if item is not None else None

    def _detail_menu(self, pos):
        index = self.detail_table.indexAt(pos)
        if not index.isValid():
            return
        self.detail_table.selectRow(index.row())
        menu = QMenu(self)
        act_preview = QAction("预览截图", self)
        act_explorer = QAction("在资源管理器中显示", self)
        menu.addAction(act_preview)
        menu.addAction(act_explorer)
        act_preview.triggered.connect(self._preview)
        act_explorer.triggered.connect(self._show_in_explorer)
        menu.exec(self.detail_table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ 定位（只读）
    def _preview(self):
        r = self._current_row()
        if r is None:
            return
        if not r["shot"]:
            QMessageBox.information(self, "无法预览", "该条目为任务级问题或无截图文件名。")
            return
        img_path = Path(r["src"]).parent / r["shot"]
        if not img_path.is_file():
            QMessageBox.warning(self, "无法预览", f"截图文件不存在：\n{img_path}")
            return
        ImageDialog(str(img_path), self).exec()

    def _show_in_explorer(self):
        r = self._current_row()
        if r is None:
            return
        src = r["src"]
        try:  # /select, 逗号语法：打开目录并选中该 gui json
            subprocess.run(["explorer", "/select,", src], check=False)
        except Exception:
            try:  # 降级：只打开所在目录
                if hasattr(os, "startfile"):
                    os.startfile(os.path.dirname(src))
                else:
                    subprocess.run(["explorer", os.path.dirname(src)], check=False)
            except Exception as e:
                QMessageBox.warning(self, "定位失败", str(e))
                return
        self.statusBar().showMessage(f"已在资源管理器中定位：{src}", 8000)

    # ------------------------------------------------------------------ 导出
    def _export_md(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出 md 报告", "语义问题报告.md",
                                              "Markdown (*.md);;所有文件 (*.*)")
        if not path:
            return
        try:
            O.write_md(self._rows, self._stats, self._failed, path, DEFAULT_TITLE)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
            self.statusBar().showMessage("md 导出失败")
            return
        self.statusBar().showMessage(f"md 报告已导出：{path}", 8000)

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出 json 明细", "语义问题明细.json",
                                              "JSON (*.json);;所有文件 (*.*)")
        if not path:
            return
        try:  # 与 CLI --json 同结构（src 为 GUI 附加的内部字段，不影响 md）
            Path(path).write_text(
                json.dumps(dict(rows=self._rows, stats=self._stats, failed=self._failed), ensure_ascii=False),
                encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
            self.statusBar().showMessage("json 导出失败")
            return
        self.statusBar().showMessage(f"json 明细已导出：{path}", 8000)


def main():
    app = QApplication(sys.argv)
    win = QcWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
