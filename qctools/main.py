import sys
import os
import json
import copy
import math
from collections import Counter
from PIL import Image, ImageFile
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QListWidget,
    QListWidgetItem, QTreeWidget, QTreeWidgetItem, QSplitter,
    QMessageBox, QInputDialog, QMenu, QScrollArea, QFrame,
    QHeaderView, QAbstractItemView, QSizePolicy, QTextEdit,
    QStyledItemDelegate, QStyle, QDialog, QDialogButtonBox, QToolTip,
    QToolButton
)
from PyQt6.QtCore import Qt, QRect, QPoint, QSize, QPointF, QSizeF, pyqtSignal, QEvent, QTimer, QSettings, QThread
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QFont, QAction, QFontMetrics
import app_version
import updater

# 语义质检模块（与本文件同目录，打包时由 main.spec 的 hiddenimports 保证）；
# 导入失败时降级：GUI 正常启动，仅禁用语义质检入口
try:
    import check_semantic_origin
    import check_semantic_v1
    SEMANTIC_QC_AVAILABLE = True
except Exception:
    check_semantic_origin = None
    check_semantic_v1 = None
    SEMANTIC_QC_AVAILABLE = False

# 任务列表项中保存原始显示文本的 data role（UserRole 已用于保存文件路径）
QC_ORIGINAL_TEXT_ROLE = Qt.ItemDataRole.UserRole + 1


def load_json_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json_file(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def find_json_files(folder_path):
    json_files = []
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            if f.endswith('.json') and not f.endswith('_coords.json'):
                json_files.append(os.path.join(root, f))
    return sorted(json_files)


def get_task_name(json_data):
    messages = json_data.get('messages', [])
    if messages and 'instruction' in messages[0]:
        return messages[0]['instruction']
    return 'Unknown Task'


class PageInfo:
    def __init__(self, page_type, data, screenshot_file=None, coordinates=None, step_index=-1, path_prefix=None, action_type=None):
        self.page_type = page_type
        self.data = data
        self.screenshot_file = screenshot_file
        self.coordinates = coordinates
        self.step_index = step_index
        self.path_prefix = path_prefix if path_prefix is not None else []
        self.action_type = action_type


def check_semantic_one_file(filepath):
    """对单个 gui json 跑与 check_semantic_origin.run 同口径的 B/C/D 语义质检（只读）。
    返回 {"issues": [{cat, step, shot, desc, extra}], "failed": bool, "error": str}。"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    rec, shots, extra_tasks = check_semantic_origin.to_pseudo_record(data)
    res = check_semantic_v1.check_record(rec)
    for t in extra_tasks:
        res += [r for r in check_semantic_v1.check_record(
            {"messages": [{"role": "system", "content": ""},
                          {"role": "user", "content": t}],
             "meta": {}}) if r[1] is None]
    issues = []
    for cat, step, desc, extra in res:
        shot = shots[step] if step is not None and step < len(shots) else ''
        issues.append({'cat': cat, 'step': step, 'shot': shot,
                       'desc': desc, 'extra': extra})
    return {'issues': issues, 'failed': False, 'error': ''}


class SemanticQCWorker(QThread):
    """后台逐文件执行语义质检，结束后一次性回传 (版本号, {abspath: 结果})。"""

    finishedQC = pyqtSignal(int, dict)

    def __init__(self, file_paths, version, parent=None):
        super().__init__(parent)
        self._file_paths = file_paths
        self._version = version

    def run(self):
        results = {}
        for fp in self._file_paths:
            try:
                results[os.path.abspath(fp)] = check_semantic_one_file(fp)
            except Exception as e:
                results[os.path.abspath(fp)] = {
                    'issues': [], 'failed': True, 'error': str(e)
                }
        self.finishedQC.emit(self._version, results)


class MultiLineEditDialog(QDialog):
    def __init__(self, parent=None, text='', title='编辑值'):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(500, 400)

        layout = QVBoxLayout(self)

        self._text_edit = QTextEdit()
        self._text_edit.setPlainText(text)
        self._text_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._text_edit.setAcceptRichText(False)
        layout.addWidget(self._text_edit)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._text_edit.setFocus()

    def get_text(self):
        return self._text_edit.toPlainText()


class ElidedLabel(QLabel):
    """按可用宽度省略显示的单行标签，完整文本通过 Tooltip 展示"""

    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self._full_text = ''
        # 水平方向忽略尺寸提示，由布局按可用宽度分配
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.set_full_text(text)

    def set_full_text(self, text):
        self._full_text = text or ''
        self.setText(self._full_text)
        self.setToolTip(self._full_text)
        self.update()

    def full_text(self):
        return self._full_text

    def sizeHint(self):
        # 忽略长文本撑开的尺寸提示，由布局按可用宽度分配
        return QSize(200, super().sizeHint().height())

    def minimumSizeHint(self):
        # 最小宽度只取设定值，避免长文本把导航行撑出面板
        return QSize(self.minimumWidth(), super().minimumSizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        elided = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, self.width()
        )
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            elided
        )


class WordWrapDelegate(QStyledItemDelegate):
    def __init__(self, tree_widget, parent=None):
        super().__init__(parent)
        self._tree = tree_widget

    def sizeHint(self, option, index):
        if index.column() != 1:
            return super().sizeHint(option, index)

        text = index.data(Qt.ItemDataRole.DisplayRole)
        text_str = str(text) if text else ''

        if not text_str:
            return super().sizeHint(option, index)

        col_width = self._tree.columnWidth(1) - 12
        if col_width < 50:
            col_width = 200

        fm = QFontMetrics(option.font)
        br = fm.boundingRect(QRect(0, 0, col_width, 10000),
                             Qt.TextFlag.TextWordWrap, text_str)

        height = max(28, br.height() + 12)
        return QSize(col_width, height)

    def paint(self, painter, option, index):
        if index.column() != 1:
            super().paint(painter, option, index)
            return

        text = index.data(Qt.ItemDataRole.DisplayRole)
        text_str = str(text) if text else ''

        painter.save()

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
            painter.setPen(option.palette.highlightedText().color())
        else:
            bg_color = QColor('#2a2a2a') if index.row() % 2 == 1 else QColor('#252525')
            painter.fillRect(option.rect, bg_color)
            painter.setPen(option.palette.text().color())

        margin = 4
        text_rect = option.rect.adjusted(margin, margin, -margin, -margin)
        painter.drawText(text_rect, Qt.TextFlag.TextWordWrap, text_str)

        painter.restore()


class JsonTreeWidget(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(['字段', '值'])
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.on_context_menu)
        self.itemChanged.connect(self.on_item_changed)
        self.header().setStretchLastSection(True)
        self.setColumnWidth(0, 300)
        self._current_json_path = None
        self._current_original_data = None
        self._current_page_index = -1
        self._json_data = None
        self._pages = None
        self._rebuilding = False
        self.setUniformRowHeights(False)
        self._delegate = WordWrapDelegate(self)
        self.setItemDelegateForColumn(1, self._delegate)
        self.header().sectionResized.connect(self._on_section_resized)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.pos())
        if item and self.columnAt(event.pos().x()) == 1:
            path = self._get_path_to_item(item)
            if path:
                page = self._pages[self._current_page_index]
                full_path = page.path_prefix + path
                original_value, found = self._get_value_by_path(self._json_data, full_path)
                if found and not isinstance(original_value, (dict, list)):
                    current_text = item.text(1)
                    dialog = MultiLineEditDialog(self, current_text, f'编辑字段 "{path[-1]}"')
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        new_text = dialog.get_text()
                        new_value = self._parse_value(new_text, original_value)
                        self._rebuilding = True
                        self._set_value_by_path(self._json_data, full_path, new_value)
                        item.setText(1, str(new_value) if new_value is not None else '')
                        self._rebuilding = False
                        self.scheduleDelayedItemsLayout()
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def set_json_data(self, json_data, pages, current_page_index, json_path):
        self._json_data = json_data
        self._pages = pages
        self._current_page_index = current_page_index
        if self._current_json_path != json_path:
            self._current_original_data = copy.deepcopy(json_data)
        self._current_json_path = json_path

    def _on_section_resized(self, logicalIndex, oldSize, newSize):
        if logicalIndex == 1:
            self.scheduleDelayedItemsLayout()

    def clear_and_build(self, data):
        self._rebuilding = True
        self.clear()
        self._build_tree_from_data(self.invisibleRootItem(), data)
        self.expandAll()
        self._rebuilding = False
        self.scheduleDelayedItemsLayout()

    def _build_tree_from_data(self, parent_item, data):
        if isinstance(data, dict):
            for key, value in data.items():
                item = QTreeWidgetItem(parent_item)
                item.setText(0, str(key))
                item.setData(0, Qt.ItemDataRole.UserRole, key)
                if isinstance(value, (dict, list)):
                    item.setText(1, f'[{len(value)} 项]' if isinstance(value, list) else f'{{{len(value)} 项}}')
                    item.setData(1, Qt.ItemDataRole.UserRole, key)
                    self._build_tree_from_data(item, value)
                else:
                    item.setText(1, str(value) if value is not None else '')
                    item.setData(1, Qt.ItemDataRole.UserRole, key)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        elif isinstance(data, list):
            for i, value in enumerate(data):
                item = QTreeWidgetItem(parent_item)
                item.setText(0, f'[{i}]')
                item.setData(0, Qt.ItemDataRole.UserRole, i)
                if isinstance(value, (dict, list)):
                    item.setText(1, f'[{len(value)} 项]' if isinstance(value, list) else f'{{{len(value)} 项}}')
                    item.setData(1, Qt.ItemDataRole.UserRole, i)
                    self._build_tree_from_data(item, value)
                else:
                    item.setText(1, str(value) if value is not None else '')
                    item.setData(1, Qt.ItemDataRole.UserRole, i)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)

    def _get_path_to_item(self, item):
        parts = []
        current = item
        root = self.invisibleRootItem()
        while current and current is not root:
            key_data = current.data(0, Qt.ItemDataRole.UserRole)
            parts.insert(0, key_data)
            current = current.parent()
        return parts

    def _get_value_by_path(self, data, path):
        current = data
        for key in path:
            if isinstance(current, list):
                if isinstance(key, int) and 0 <= key < len(current):
                    current = current[key]
                else:
                    return None, False
            elif isinstance(current, dict):
                if key in current:
                    current = current[key]
                else:
                    return None, False
            else:
                return None, False
        return current, True

    def _set_value_by_path(self, data, path, new_value):
        if not path:
            return data
        current = data
        for i, key in enumerate(path[:-1]):
            if isinstance(current, list):
                current = current[key]
            elif isinstance(current, dict):
                current = current[key]
        last_key = path[-1]
        if isinstance(current, list):
            current[last_key] = new_value
        elif isinstance(current, dict):
            current[last_key] = new_value
        return data

    def _delete_by_path(self, data, path):
        if not path:
            return data
        current = data
        for i, key in enumerate(path[:-1]):
            if isinstance(current, list):
                current = current[key]
            elif isinstance(current, dict):
                current = current[key]
        last_key = path[-1]
        if isinstance(current, list):
            del current[last_key]
        elif isinstance(current, dict):
            del current[last_key]
        return data

    def on_context_menu(self, pos):
        item = self.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        delete_action = QAction('删除此字段', self)
        delete_action.triggered.connect(lambda: self.delete_field(item))
        menu.addAction(delete_action)
        menu.exec(self.viewport().mapToGlobal(pos))

    def delete_field(self, item):
        if not item:
            return
        path = self._get_path_to_item(item)
        if not path:
            return
        page = self._pages[self._current_page_index]
        full_path = page.path_prefix + path
        reply = QMessageBox.question(
            self, '确认删除',
            f'确定要删除字段 "{path[-1]}" 吗？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._delete_by_path(self._json_data, full_path)
        self.refresh_display()

    def on_item_changed(self, item, column):
        if self._rebuilding:
            return
        if column != 1:
            return
        path = self._get_path_to_item(item)
        if not path:
            return
        page = self._pages[self._current_page_index]
        full_path = page.path_prefix + path
        original_value, found = self._get_value_by_path(self._json_data, full_path)
        if not found or isinstance(original_value, (dict, list)):
            return
        new_text = item.text(1)
        if new_text is None:
            return
        new_value = self._parse_value(new_text, original_value)
        self._set_value_by_path(self._json_data, full_path, new_value)
        self.scheduleDelayedItemsLayout()

    def _parse_value(self, text, original):
        if isinstance(original, bool):
            text_lower = text.lower().strip()
            if text_lower in ('true', 'false'):
                return text_lower == 'true'
        if isinstance(original, int):
            try:
                return int(text)
            except ValueError:
                pass
        if isinstance(original, float):
            try:
                return float(text)
            except ValueError:
                pass
        if isinstance(original, list):
            try:
                return json.loads(text)
            except (json.JSONDecodeError, ValueError):
                pass
        return text

    def has_unsaved_changes(self):
        if self._current_original_data is None or self._json_data is None:
            return False
        return json.dumps(self._json_data, sort_keys=True, ensure_ascii=False) != \
            json.dumps(self._current_original_data, sort_keys=True, ensure_ascii=False)

    def mark_saved(self):
        self._current_original_data = copy.deepcopy(self._json_data)

    def refresh_display(self):
        if self._pages is None or self._current_page_index < 0:
            return
        if self._current_page_index >= len(self._pages):
            return
        self._rebuilding = True
        page_data = self._get_page_data_from_json()
        self.clear_and_build(page_data)
        self._rebuilding = False

    def _get_page_data_from_json(self):
        if self._pages is None or self._json_data is None:
            return {}
        if self._current_page_index < 0 or self._current_page_index >= len(self._pages):
            return {}
        page = self._pages[self._current_page_index]
        prefix = page.path_prefix
        if not prefix:
            meta_keys = {'platform', 'system', 'screen_size', 'task_type', 'recording_video'}
            result = {}
            for k in meta_keys:
                if k in self._json_data:
                    result[k] = self._json_data[k]
            return result
        data, found = self._get_value_by_path(self._json_data, prefix)
        return data if found else {}

    def get_current_json_data(self):
        return self._json_data

    def get_save_path(self):
        return self._current_json_path

    def get_current_page_index(self):
        return self._current_page_index

    def set_current_page_index(self, index):
        self._current_page_index = index
        self.refresh_display()


class ImagePreviewWidget(QWidget):
    # 缩放比例上下限与单步倍率（均相对于“适应窗口”的倍率）
    MIN_ZOOM = 0.1
    MAX_ZOOM = 20.0
    ZOOM_STEP = 1.25

    # 缩放倍率变化信号（发射相对于适应窗口的倍率，1.0 表示 100%）
    zoomChanged = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._pixmap = None
        self._scaled_pixmap = None
        self._coordinate = None
        self._action_type = None
        self._original_pixmap_size = None
        self._image_offset_x = 0
        self._image_offset_y = 0
        # 缩放/平移状态
        self._zoom = 1.0                        # 相对“适应窗口”的缩放比例，1.0 表示适应窗口
        self._center_img = QPointF(0.0, 0.0)    # 当前视口中心对应的原图像素坐标
        self._panning = False
        self._last_mouse = None
        self._hover_pos = None
        self._image = None                      # 缓存原图 QImage，用于悬停取色（避免每次 repaint 转换）
        self._disp_w = 0                        # 当前显示宽度（像素）
        self._disp_h = 0                        # 当前显示高度（像素）
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setStyleSheet('background-color: #1a1a1a;')
        self._text = '请选择一个任务'

    def set_image(self, image_path, coordinate=None, action_type=None):
        if image_path and os.path.exists(image_path):
            self._pixmap = QPixmap(image_path)
            if self._pixmap.isNull():
                # QPixmap 加载失败（如截断的PNG），尝试用 PIL 修复
                try:
                    ImageFile.LOAD_TRUNCATED_IMAGES = True
                    img = Image.open(image_path)
                    img.load()
                    img.save(image_path)
                    self._pixmap = QPixmap(image_path)
                except Exception:
                    pass
            self._original_pixmap_size = self._pixmap.size() if not self._pixmap.isNull() else None
            self._coordinate = coordinate
            self._action_type = action_type
            self._text = None
            # 缓存原图 QImage，用于悬停取色
            self._image = self._pixmap.toImage() if not self._pixmap.isNull() else None
            # 切换图片时自动复位到适应窗口
            self.reset_view()
        else:
            self._pixmap = None
            self._scaled_pixmap = None
            self._coordinate = None
            self._action_type = None
            self._original_pixmap_size = None
            self._image = None
            self._zoom = 1.0
            self._center_img = QPointF(0.0, 0.0)
            self._disp_w = 0
            self._disp_h = 0
            self._hover_pos = None
            self._text = '图片未找到' if image_path else '没有可显示的图片'
            self._update_scaled()
            self.update()
            self.zoomChanged.emit(self._zoom)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled()

    def _fit_scale(self):
        """返回“适应窗口”时的缩放比例（原图像素 -> 控件像素），非法时返回 0"""
        orig = self._original_pixmap_size
        if not orig or orig.width() <= 0 or orig.height() <= 0:
            return 0.0
        w = self.width() - 20
        h = self.height() - 20
        if w <= 0 or h <= 0:
            return 0.0
        return min(w / orig.width(), h / orig.height())

    def _update_scaled(self):
        orig = self._original_pixmap_size
        fit = self._fit_scale()
        if not self._pixmap or self._pixmap.isNull() or not orig or fit <= 0:
            self._scaled_pixmap = None
            self._disp_w = 0
            self._disp_h = 0
            self._update_cursor()
            return

        orig_w = orig.width()
        orig_h = orig.height()

        # 适应窗口时始终居中
        if self._zoom == 1.0:
            self._center_img = QPointF(orig_w / 2.0, orig_h / 2.0)

        # 视口中心限制在原图坐标范围内
        cx = min(max(self._center_img.x(), 0.0), float(orig_w))
        cy = min(max(self._center_img.y(), 0.0), float(orig_h))
        self._center_img = QPointF(cx, cy)

        # 有效缩放比例
        s = fit * self._zoom
        self._disp_w = max(1, round(orig_w * s))
        self._disp_h = max(1, round(orig_h * s))
        # 内存安全：不再用 self._pixmap.scaled() 生成超大中间图，绘制时直接按目标矩形缩放
        self._scaled_pixmap = None
        self._image_offset_x = round(self.width() / 2.0 - self._center_img.x() * s)
        self._image_offset_y = round(self.height() / 2.0 - self._center_img.y() * s)
        self._update_cursor()

    def _update_cursor(self):
        """按当前状态更新鼠标光标（拖拽中不覆盖 ClosedHand）"""
        if self._panning:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._pixmap and not self._pixmap.isNull() and self._zoom != 1.0:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._text:
            painter.setPen(QColor(200, 200, 200))
            font = QFont('Microsoft YaHei', 14)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
            return

        orig = self._original_pixmap_size
        has_image = bool(self._pixmap and not self._pixmap.isNull() and orig
                         and self._disp_w > 0 and self._disp_h > 0)
        if not has_image:
            return

        orig_w = orig.width()
        orig_h = orig.height()
        # 标注渲染统一使用与绘制一致的有效缩放
        scale_x = self._disp_w / orig_w if orig_w > 0 else 1
        scale_y = self._disp_h / orig_h if orig_h > 0 else 1

        # 内存安全：直接按目标矩形缩放绘制原图（不生成 disp_w×disp_h 的中间 QPixmap）
        # 采样策略：显示尺寸不超过原图 2 倍时用平滑采样，高倍放大改用最近邻避免发糊
        enable_smooth = self._disp_w <= orig_w * 2 and self._disp_h <= orig_h * 2
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, enable_smooth)
        target_rect = QRect(self._image_offset_x, self._image_offset_y, self._disp_w, self._disp_h)
        painter.drawPixmap(target_rect, self._pixmap, QRect(0, 0, orig_w, orig_h))

        if self._coordinate:
            # 通过 action_type 判断是否为拖拽/滑动动作
            action_str = str(self._action_type or '').lower()
            is_drag = 'drag' in action_str or 'swipe' in action_str

            # 判断是否为拉框（4个值: [x1, y1, x2, y2]）且不是拖拽动作
            is_bbox = (not is_drag
                       and isinstance(self._coordinate, list)
                       and len(self._coordinate) == 4
                       and all(isinstance(v, (int, float)) for v in self._coordinate))
            if is_bbox:
                x1, y1, x2, y2 = self._coordinate
                sx1 = int(self._image_offset_x + x1 * scale_x)
                sy1 = int(self._image_offset_y + y1 * scale_y)
                sx2 = int(self._image_offset_x + x2 * scale_x)
                sy2 = int(self._image_offset_y + y2 * scale_y)

                pen = QPen(QColor(255, 80, 80), 3)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(sx1, sy1, sx2 - sx1, sy2 - sy1)
            else:
                # 判断是否为拖拽动作（两个坐标点），优先用 action_type，回退到格式检测
                if not is_drag and self._coordinate:
                    is_drag = isinstance(self._coordinate[0], list)
                # 防御：is_drag 为 True 但 coordinate 是扁平列表时，转换为 [[x1,y1],[x2,y2]]
                if is_drag and isinstance(self._coordinate, list) and self._coordinate and not isinstance(self._coordinate[0], (list, tuple)):
                    if len(self._coordinate) >= 4:
                        self._coordinate = [[self._coordinate[0], self._coordinate[1]], [self._coordinate[2], self._coordinate[3]]]
                    elif len(self._coordinate) >= 2:
                        self._coordinate = [[self._coordinate[0], self._coordinate[1]]]
                if is_drag:
                    coords = self._coordinate
                else:
                    coords = [self._coordinate]

                rect_size = 30

                # 画矩形框
                pen = QPen(QColor(255, 80, 80), 3)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)

                scaled_pts = []
                for pt in coords:
                    x = int(self._image_offset_x + pt[0] * scale_x)
                    y = int(self._image_offset_y + pt[1] * scale_y)
                    scaled_pts.append((x, y))
                    painter.drawRect(x - rect_size // 2, y - rect_size // 2, rect_size, rect_size)

                # 拖拽动作画箭头从第一坐标指向第二坐标
                if is_drag and len(scaled_pts) == 2:
                    x1, y1 = scaled_pts[0]
                    x2, y2 = scaled_pts[1]

                    arrow_pen = QPen(QColor(255, 255, 0), 3)
                    painter.setPen(arrow_pen)
                    painter.drawLine(x1, y1, x2, y2)

                    # 箭头头部
                    angle = math.atan2(y2 - y1, x2 - x1)
                    head_len = 15
                    head_angle = math.pi / 6
                    painter.drawLine(x2, y2,
                        int(x2 - head_len * math.cos(angle - head_angle)),
                        int(y2 - head_len * math.sin(angle - head_angle)))
                    painter.drawLine(x2, y2,
                        int(x2 - head_len * math.cos(angle + head_angle)),
                        int(y2 - head_len * math.sin(angle + head_angle)))

        # 悬停像素信息覆盖层（最后绘制，不影响图片/标注）
        self._draw_hover_overlay(painter, orig_w, orig_h, scale_x, scale_y)

    def _draw_hover_overlay(self, painter, orig_w, orig_h, scale_x, scale_y):
        """在图片显示区域内绘制鼠标位置的原图坐标与 RGB 信息"""
        if not self._image or self._image.isNull() or self._hover_pos is None:
            return
        if self._disp_w <= 0 or self._disp_h <= 0 or orig_w <= 0 or orig_h <= 0:
            return
        if scale_x <= 0 or scale_y <= 0:
            return

        hover = self._hover_pos
        img_x = (hover.x() - self._image_offset_x) / scale_x
        img_y = (hover.y() - self._image_offset_y) / scale_y
        if not (0 <= img_x < orig_w and 0 <= img_y < orig_h):
            return

        disp_rect = QRect(self._image_offset_x, self._image_offset_y, self._disp_w, self._disp_h)
        if not disp_rect.contains(int(hover.x()), int(hover.y())):
            return

        color = self._image.pixelColor(int(img_x), int(img_y))
        text = f'x={int(img_x)}, y={int(img_y)}  RGB({color.red()}, {color.green()}, {color.blue()})'

        font = QFont('Microsoft YaHei', 9)
        painter.setFont(font)
        fm = QFontMetrics(font)
        pad = 6
        box_w = fm.horizontalAdvance(text) + pad * 2
        box_h = fm.height() + pad

        # 默认放在图片显示矩形右下角内侧，空间不足则放左上角
        box_x = disp_rect.right() - box_w - 4
        box_y = disp_rect.bottom() - box_h - 4
        if box_x < disp_rect.left():
            box_x = disp_rect.left() + 4
        if box_y < disp_rect.top():
            box_y = disp_rect.top() + 4

        painter.setBrush(QColor(0, 0, 0, 160))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(box_x, box_y, box_w, box_h, 4, 4)
        painter.setPen(QColor(240, 240, 240))
        painter.drawText(box_x + pad, box_y + pad + fm.ascent(), text)

    def wheelEvent(self, event):
        """滚轮以光标为锚点缩放"""
        if not (self._pixmap and not self._pixmap.isNull()):
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = self.ZOOM_STEP ** (delta / 120.0)
        self._apply_zoom(self._zoom * factor, event.position())
        event.accept()

    def _apply_zoom(self, new_zoom, anchor=None):
        """以 anchor（控件坐标）为锚点缩放，保持锚点下的原图坐标不动"""
        orig = self._original_pixmap_size
        if not self._pixmap or self._pixmap.isNull() or not orig:
            return
        new_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, new_zoom))
        if abs(new_zoom - self._zoom) < 1e-9:
            return
        if anchor is None:
            anchor = QPointF(self.width() / 2.0, self.height() / 2.0)

        # 旧变换下锚点对应的原图坐标
        s_old = self._disp_w / orig.width() if self._disp_w > 0 else self._fit_scale() * self._zoom
        if s_old <= 0:
            return
        img_x = (anchor.x() - self._image_offset_x) / s_old
        img_y = (anchor.y() - self._image_offset_y) / s_old

        self._zoom = new_zoom
        s_new = self._fit_scale() * new_zoom
        if s_new <= 0:
            return
        # 保持锚点下的原图坐标位于同一屏幕位置
        self._center_img = QPointF(
            img_x + (self.width() / 2.0 - anchor.x()) / s_new,
            img_y + (self.height() / 2.0 - anchor.y()) / s_new,
        )
        self._update_scaled()
        self.update()
        self.zoomChanged.emit(self._zoom)

    def reset_view(self):
        """复位到适应窗口"""
        self._zoom = 1.0
        orig = self._original_pixmap_size
        if orig:
            self._center_img = QPointF(orig.width() / 2.0, orig.height() / 2.0)
        else:
            self._center_img = QPointF(0.0, 0.0)
        self._update_scaled()
        self.update()
        self.zoomChanged.emit(self._zoom)

    def zoom_in(self):
        """放大（锚点为控件中心）"""
        self._apply_zoom(self._zoom * self.ZOOM_STEP)

    def zoom_out(self):
        """缩小（锚点为控件中心）"""
        self._apply_zoom(self._zoom / self.ZOOM_STEP)

    def fit_to_window(self):
        """适应窗口"""
        self.reset_view()

    def actual_size(self):
        """按原图 1:1 显示"""
        fit = self._fit_scale()
        if fit > 0:
            self._apply_zoom(1.0 / fit)

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self._pixmap and not self._pixmap.isNull()
                and self._zoom != 1.0):
            self.setFocus()
            self._panning = True
            self._last_mouse = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 始终更新悬停位置（用于像素信息覆盖层）
        self._hover_pos = event.position()
        if self._panning and self._last_mouse is not None:
            cur = event.position()
            dx = cur.x() - self._last_mouse.x()
            dy = cur.y() - self._last_mouse.y()
            orig = self._original_pixmap_size
            if orig and self._disp_w > 0:
                s = self._disp_w / orig.width()
                if s > 0:
                    self._center_img = QPointF(
                        self._center_img.x() - dx / s,
                        self._center_img.y() - dy / s,
                    )
            self._last_mouse = cur
            self._update_scaled()
        self.update()

    def mouseReleaseEvent(self, event):
        if self._panning:
            self._panning = False
            self._last_mouse = None
            self._update_scaled()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pixmap and not self._pixmap.isNull():
            self.reset_view()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event):
        self._hover_pos = None
        self.update()
        super().leaveEvent(event)

    def clear(self):
        self._pixmap = None
        self._scaled_pixmap = None
        self._coordinate = None
        self._action_type = None
        self._original_pixmap_size = None
        self._image = None
        self._zoom = 1.0
        self._center_img = QPointF(0.0, 0.0)
        self._disp_w = 0
        self._disp_h = 0
        self._hover_pos = None
        self._panning = False
        self._last_mouse = None
        self._text = '请选择一个任务'
        self._update_cursor()
        self.update()
        self.zoomChanged.emit(self._zoom)


class QIssueCard(QFrame):
    """语义质检问题卡片：类别徽章+步号/截图一行，描述完整换行，附加信息独立一行；双击触发跳转。"""
    doubleClicked = pyqtSignal(dict)

    CAT_STYLE = {
        'B': ('#ffb86b', 'rgba(255,184,107,0.12)'),
        'C': ('#ff6b6b', 'rgba(255,107,107,0.12)'),
        'D': ('#e3b341', 'rgba(227,179,65,0.12)'),
    }

    def __init__(self, issue, parent=None):
        super().__init__(parent)
        self.issue = issue
        cat_raw = issue.get('cat', '') or ''
        key = cat_raw[:1] if cat_raw[:1] in self.CAT_STYLE else 'D'
        color, bg = self.CAT_STYLE[key]
        self.setObjectName('qcIssueCard')
        self.setProperty('catKey', key)
        step = issue.get('step')
        loc = '任务级' if step is None else f"步 {step} · {issue.get('shot', '') or ''}".rstrip(' ·')
        extra = issue.get('extra', '') or ''
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        badge = QLabel(cat_raw)
        badge.setObjectName('qcBadge')
        badge.setStyleSheet(
            f'color:{color};border:1px solid {color};background:{bg};'
            'border-radius:999px;padding:1px 8px;'
        )
        loc_lbl = QLabel(loc)
        loc_lbl.setObjectName('qcMetaLabel')
        top.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)
        top.addWidget(loc_lbl, 1, Qt.AlignmentFlag.AlignLeft)
        root.addLayout(top)

        desc = QLabel(issue.get('desc', '') or '')
        desc.setObjectName('qcDescLabel')
        desc.setWordWrap(True)
        root.addWidget(desc)

        if extra:
            extra_lbl = QLabel(extra)
            extra_lbl.setObjectName('qcMetaLabel')
            extra_lbl.setWordWrap(True)
            root.addWidget(extra_lbl)

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit(self.issue)
        super().mouseDoubleClickEvent(event)


class QcTitleLabel(QLabel):
    """可点击的标题标签：左键点击发出 clicked 信号。"""
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    # 界面字号（像素）的默认值与允许范围
    FONT_DEFAULT_PX = 13
    FONT_MIN_PX = 9
    FONT_MAX_PX = 18

    def __init__(self):
        super().__init__()
        self.setWindowTitle('GUI质检标注工具 v{}'.format(app_version.__version__))
        self.setMinimumSize(1100, 700)
        self._settings = QSettings('MacOS-QC-Tool', 'GUI-QC-Tool')
        self._font_px = self._load_font_px()
        self._json_files = []
        self._json_data = None
        self._pages = []
        self._current_page_index = 0
        self._current_json_path = None
        self._current_folder = None
        self._last_task_row = -1
        self._splitter_state_restored = False
        self._right_splitter_restored = False   # 纵向分栏状态是否已从配置恢复
        self._user_adjusted_right = False       # 用户是否手动拖拽过右栏分隔条
        self._applying_right_sizes = False      # 是否正在程序化设置右栏尺寸

        # 语义质检状态：key 为 gui json 绝对路径
        self._qc_results = {}
        self._qc_collapsed = False     # 语义问题面板是否折叠
        self._qc_last_height = 0       # 折叠前的面板高度，用于展开还原
        self._qc_run_version = 0
        self._qc_worker = None
        self._qc_workers = []
        # 当前任务的伪步序号 -> GUI 页索引 / 截图文件名
        self._pseudo_to_page = {}
        self._pseudo_shots = {}

        self._setup_ui()
        self._apply_styles()
        self._restore_window_state()
        QApplication.instance().installEventFilter(self)

    def _load_font_px(self):
        """读取界面字号，缺失/非数字/越界时回退默认值"""
        try:
            px = int(self._settings.value('ui/font_px', self.FONT_DEFAULT_PX))
        except (TypeError, ValueError):
            px = self.FONT_DEFAULT_PX
        if px < self.FONT_MIN_PX or px > self.FONT_MAX_PX:
            px = self.FONT_DEFAULT_PX
        return px

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        lbl_folder = QLabel('数据文件夹:')
        lbl_folder.setMinimumWidth(80)
        self._folder_input = QLineEdit()
        self._folder_input.setPlaceholderText('选择包含JSON文件的文件夹...')
        self._folder_input.setReadOnly(True)
        btn_browse = QPushButton('浏览...')
        btn_browse.setMinimumWidth(70)
        btn_browse.clicked.connect(self._on_browse_folder)
        self._btn_semantic_qc = QPushButton('🔍 语义质检')
        self._btn_semantic_qc.setToolTip('对当前文件夹运行 B/C/D 语义质检'
                                         if SEMANTIC_QC_AVAILABLE
                                         else '语义质检模块（check_semantic_origin/check_semantic_v1）不可用')
        self._btn_semantic_qc.setEnabled(False)
        self._btn_semantic_qc.clicked.connect(self._on_semantic_qc_clicked)
        top_bar.addWidget(lbl_folder)
        top_bar.addWidget(self._folder_input)
        top_bar.addWidget(btn_browse)
        top_bar.addWidget(self._btn_semantic_qc)
        main_layout.addLayout(top_bar)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(8)

        left_panel = QWidget()
        left_panel.setMinimumWidth(180)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        lbl_tasks = QLabel('任务列表')
        lbl_tasks.setObjectName('sectionHeaderLabel')
        self._task_list = QListWidget()
        self._task_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._task_list.setWordWrap(False)
        self._task_list.currentRowChanged.connect(self._on_task_selected)
        left_layout.addWidget(lbl_tasks)
        left_layout.addWidget(self._task_list)
        self._splitter.addWidget(left_panel)

        mid_panel = QWidget()
        mid_panel.setMinimumWidth(320)
        mid_layout = QVBoxLayout(mid_panel)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        mid_layout.setSpacing(4)

        self._image_preview = ImagePreviewWidget()

        nav_container = QWidget()
        self._nav_container = nav_container
        nav_outer = QVBoxLayout(nav_container)
        nav_outer.setContentsMargins(0, 0, 0, 0)
        nav_outer.setSpacing(4)

        self._lbl_page_info = QLabel('第 0 / 0 步')
        self._lbl_page_info.setObjectName('pageInfoLabel')
        self._lbl_page_step_desc = ElidedLabel('')
        self._lbl_page_step_desc.setObjectName('stepDescLabel')

        self._btn_prev = QPushButton('◀ 上一步')
        self._btn_prev.clicked.connect(self._on_prev_page)
        self._btn_next = QPushButton('下一步 ▶')
        self._btn_next.clicked.connect(self._on_next_page)

        self._btn_save = QPushButton('💾 保存')
        self._btn_save.clicked.connect(self._on_save)
        self._btn_save.setStyleSheet('background-color: #2d7d46; color: white; font-weight: bold; padding: 6px 16px;')

        self._btn_refresh = QPushButton('🔄 刷新')
        self._btn_refresh.clicked.connect(self._on_refresh)

        self._jump_input = QLineEdit()
        self._jump_input.setFixedWidth(70)
        self._jump_input.setPlaceholderText('页码')
        self._jump_input.setToolTip('输入页码后按回车跳转（1 到总页数）')
        self._jump_input.returnPressed.connect(self._on_jump_to_page)
        self._btn_jump = QPushButton('跳转')
        self._btn_jump.clicked.connect(self._on_jump_to_page)

        # 缩放相关控件与百分比标签
        self._lbl_zoom = QLabel('缩放: 100%')
        self._lbl_zoom.setObjectName('zoomLabel')
        self._btn_zoom_out = QPushButton('➖')
        self._btn_zoom_out.setFixedWidth(38)
        self._btn_zoom_out.setToolTip('缩小 (Ctrl+-)')
        self._btn_zoom_in = QPushButton('➕')
        self._btn_zoom_in.setFixedWidth(38)
        self._btn_zoom_in.setToolTip('放大 (Ctrl+=)')
        self._btn_fit = QPushButton('适应窗口')
        self._btn_fit.setToolTip('适应窗口 (Ctrl+0)')
        self._btn_actual = QPushButton('1:1')
        self._btn_actual.setToolTip('按原始尺寸显示')

        self._btn_zoom_in.clicked.connect(self._image_preview.zoom_in)
        self._btn_zoom_out.clicked.connect(self._image_preview.zoom_out)
        self._btn_fit.clicked.connect(self._image_preview.fit_to_window)
        self._btn_actual.clicked.connect(self._image_preview.actual_size)
        self._image_preview.zoomChanged.connect(self._on_zoom_changed)

        # 第一行：页码 / 步骤描述（延伸）/ 跳转 / 翻页
        nav_top = QHBoxLayout()
        nav_top.setSpacing(8)
        nav_top.addWidget(self._lbl_page_info)
        nav_top.addWidget(self._lbl_page_step_desc, 1)
        nav_top.addWidget(self._jump_input)
        nav_top.addWidget(self._btn_jump)
        nav_top.addWidget(self._btn_prev)
        nav_top.addWidget(self._btn_next)

        # 第二行：保存 / 刷新 / 缩放控制
        nav_bottom = QHBoxLayout()
        nav_bottom.setSpacing(8)
        nav_bottom.addWidget(self._btn_save)
        nav_bottom.addWidget(self._btn_refresh)
        nav_bottom.addStretch()
        nav_bottom.addWidget(self._lbl_zoom)
        nav_bottom.addWidget(self._btn_zoom_out)
        nav_bottom.addWidget(self._btn_zoom_in)
        nav_bottom.addWidget(self._btn_fit)
        nav_bottom.addWidget(self._btn_actual)

        nav_outer.addLayout(nav_top)
        nav_outer.addLayout(nav_bottom)

        mid_layout.addWidget(self._image_preview)
        mid_layout.addWidget(nav_container)
        self._splitter.addWidget(mid_panel)

        right_panel = QWidget()
        right_panel.setMinimumWidth(360)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        # 纵向可拖拽分栏：上为当前指令，下为 JSON 字段结构
        self._right_splitter = QSplitter(Qt.Orientation.Vertical)
        self._right_splitter.setChildrenCollapsible(False)
        self._right_splitter.setHandleWidth(8)

        instruction_container = QWidget()
        instruction_layout = QVBoxLayout(instruction_container)
        instruction_layout.setContentsMargins(0, 0, 0, 0)
        instruction_layout.setSpacing(4)
        lbl_instruction = QLabel('当前指令')
        lbl_instruction.setObjectName('sectionHeaderLabel')
        self._instruction_display = QTextEdit()
        self._instruction_display.setObjectName('instructionDisplay')
        self._instruction_display.setReadOnly(True)
        self._instruction_display.setPlaceholderText('暂无指令')
        self._instruction_display.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._instruction_display.setMinimumHeight(40)
        instruction_layout.addWidget(lbl_instruction)
        instruction_layout.addWidget(self._instruction_display)

        json_container = QWidget()
        json_layout = QVBoxLayout(json_container)
        json_layout.setContentsMargins(0, 0, 0, 0)
        json_layout.setSpacing(4)
        lbl_json = QLabel('JSON 字段结构')
        lbl_json.setObjectName('sectionHeaderLabel')
        self._json_tree = JsonTreeWidget()
        json_layout.addWidget(lbl_json)
        json_layout.addWidget(self._json_tree)

        # 语义质检问题明细面板（常驻，选中任务后展示该任务的全部问题条目；卡片式单列 + 类别筛选）
        qc_container = QWidget()
        qc_layout = QVBoxLayout(qc_container)
        qc_layout.setContentsMargins(0, 0, 0, 0)
        qc_layout.setSpacing(4)
        # 标题行（含折叠按钮）包成独立控件，折叠时仅保留它
        self._qc_header = QWidget()
        header_row = QHBoxLayout(self._qc_header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        self._btn_qc_collapse = QToolButton()
        self._btn_qc_collapse.setObjectName('qcCollapseButton')
        self._btn_qc_collapse.setText('▾')
        self._btn_qc_collapse.setAutoRaise(True)
        self._btn_qc_collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_qc_collapse.setFixedSize(18, 18)
        self._btn_qc_collapse.setToolTip('折叠语义问题')
        self._btn_qc_collapse.clicked.connect(self._toggle_qc_panel)
        self._lbl_qc_title = QcTitleLabel('语义问题（0）')
        self._lbl_qc_title.setObjectName('sectionHeaderLabel')
        self._lbl_qc_title.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lbl_qc_title.clicked.connect(self._toggle_qc_panel)
        self._lbl_qc_hint = QLabel('双击卡片跳转')
        self._lbl_qc_hint.setObjectName('qcHintLabel')
        header_row.addWidget(self._btn_qc_collapse)
        header_row.addWidget(self._lbl_qc_title)
        header_row.addStretch(1)
        header_row.addWidget(self._lbl_qc_hint)
        qc_layout.addWidget(self._qc_header)

        # 类别筛选 chips：全部 / B / C / D
        self._qc_filter = 'ALL'  # ALL | B | C | D
        self._qc_chip_all = self._make_qc_chip('全部', 'ALL')
        self._qc_chip_b = self._make_qc_chip('B', 'B')
        self._qc_chip_c = self._make_qc_chip('C', 'C')
        self._qc_chip_d = self._make_qc_chip('D', 'D')
        self._qc_chips = {'ALL': self._qc_chip_all, 'B': self._qc_chip_b,
                          'C': self._qc_chip_c, 'D': self._qc_chip_d}
        # chips 行包一层容器，折叠时整行隐藏
        self._qc_chips_widget = QWidget()
        chip_row = QHBoxLayout(self._qc_chips_widget)
        chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.setSpacing(6)
        for chip in (self._qc_chip_all, self._qc_chip_b, self._qc_chip_c, self._qc_chip_d):
            chip_row.addWidget(chip)
        chip_row.addStretch(1)
        qc_layout.addWidget(self._qc_chips_widget)

        self._qc_scroll = QScrollArea()
        self._qc_scroll.setWidgetResizable(True)
        self._qc_scroll.setMinimumHeight(120)
        self._qc_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._qc_cards_host = QWidget()
        self._qc_cards_host.setObjectName('qcCardsHost')
        self._qc_cards_layout = QVBoxLayout(self._qc_cards_host)
        self._qc_cards_layout.setContentsMargins(2, 2, 6, 2)
        self._qc_cards_layout.setSpacing(6)
        self._qc_cards_layout.addStretch(1)
        self._qc_scroll.setWidget(self._qc_cards_host)
        qc_layout.addWidget(self._qc_scroll)
        self._qc_current_issues = []  # 当前任务的问题条目（供筛选与跳转共用）
        self._qc_empty_hint = '未选择任务'  # 无卡片时的空态提示文案
        self._qc_chip_all.setChecked(True)
        self._update_qc_chips(Counter(), 0)
        self._add_qc_info_card(self._qc_empty_hint)

        self._qc_container = qc_container
        self._right_splitter.addWidget(instruction_container)
        self._right_splitter.addWidget(json_container)
        self._right_splitter.addWidget(qc_container)
        for i in range(3):
            self._right_splitter.setCollapsible(i, False)
        self._right_splitter.setStretchFactor(0, 0)  # 指令区不主动抢占，靠内容高度决定
        self._right_splitter.setStretchFactor(1, 1)  # JSON 树占据剩余空间
        self._right_splitter.setStretchFactor(2, 0)  # 语义问题面板按内容高度展示
        self._right_splitter.handle(1).setCursor(Qt.CursorShape.SplitVCursor)
        self._right_splitter.handle(2).setCursor(Qt.CursorShape.SplitVCursor)
        self._right_splitter.splitterMoved.connect(self._on_right_splitter_moved)
        right_layout.addWidget(self._right_splitter)
        self._splitter.addWidget(right_panel)

        # 固定三栏折叠行为与拉伸权重
        for i in range(3):
            self._splitter.setCollapsible(i, False)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 3)
        self._splitter.setStretchFactor(2, 3)
        # 分隔条使用水平拖拽光标（先取得 handle 以确保已创建）
        self._splitter.handle(1).setCursor(Qt.CursorShape.SplitHCursor)
        self._splitter.handle(2).setCursor(Qt.CursorShape.SplitHCursor)
        # 外层水平分栏拖拽改变右栏宽度时，同步重算指令换行高度
        self._splitter.splitterMoved.connect(
            lambda *_: (not self._user_adjusted_right)
            and QTimer.singleShot(0, self._fit_instruction_pane)
        )

        main_layout.addWidget(self._splitter)

        self._btn_prev.setEnabled(False)
        self._btn_next.setEnabled(False)
        self._btn_save.setEnabled(False)
        self._btn_refresh.setEnabled(False)
        self._jump_input.setEnabled(False)
        self._btn_jump.setEnabled(False)

        self._apply_default_splitter_sizes()

    def _apply_styles(self):
        """按当前字号生成全局样式并应用，同时同步应用默认字体"""
        base = self._font_px
        small = max(8, self._font_px - 1)
        large = self._font_px + 1
        qss = '''
            QMainWindow {
                background-color: #1a1a1a;
            }
            QListWidget {
                border: 1px solid #404040;
                border-radius: 4px;
                font-size: @BASE@px;
                background-color: #252525;
                color: #dcdcdc;
            }
            QListWidget::item {
                padding: 6px 8px;
                border-bottom: 1px solid #333;
            }
            QListWidget::item:selected {
                background-color: #1e6bb8;
                color: #fff;
            }
            QListWidget::item:hover:!selected {
                background-color: #333;
            }
            QTreeWidget {
                border: 1px solid #404040;
                border-radius: 4px;
                font-size: @SMALL@px;
                background-color: #252525;
                color: #dcdcdc;
                alternate-background-color: #2a2a2a;
            }
            QTreeWidget::item {
                padding: 6px 8px;
                min-height: 28px;
            }
            QTreeWidget::item:selected {
                background-color: #1e6bb8;
                color: #fff;
            }
            QPushButton {
                padding: 5px 14px;
                border: 1px solid #505050;
                border-radius: 4px;
                background-color: #353535;
                color: #dcdcdc;
                font-size: @BASE@px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
            QPushButton:pressed {
                background-color: #5a5a5a;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #666;
            }
            QLineEdit {
                border: 1px solid #404040;
                border-radius: 4px;
                padding: 5px 8px;
                font-size: @BASE@px;
                background-color: #252525;
                color: #dcdcdc;
            }
            QLabel {
                font-size: @BASE@px;
                color: #dcdcdc;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                padding: 4px 8px;
                border: 1px solid #404040;
                font-weight: bold;
                color: #dcdcdc;
                font-size: @BASE@px;
            }
            #sectionHeaderLabel {
                font-size: @LARGE@px;
                font-weight: bold;
                padding: 4px;
            }
            #pageInfoLabel {
                font-size: @BASE@px;
                font-weight: bold;
            }
            #stepDescLabel {
                font-size: @SMALL@px;
                color: #aaa;
            }
            #zoomLabel {
                font-size: @SMALL@px;
                color: #aaa;
            }
            #instructionDisplay {
                background-color: #1e1e2e;
                color: #c9d1d9;
                border: 1px solid #404040;
                border-radius: 4px;
                font-size: @BASE@px;
                padding: 6px;
            }
            QSplitter::handle {
                background-color: #2a2a2a;
            }
            QSplitter::handle:horizontal {
                width: 8px;
            }
            QSplitter::handle:vertical {
                height: 8px;
            }
            QSplitter::handle:hover {
                background-color: #1e6bb8;
            }
            QSplitter::handle:pressed {
                background-color: #2d8ed6;
            }
            QScrollBar:vertical {
                background-color: #1a1a1a;
                width: 12px;
            }
            QScrollBar::handle:vertical {
                background-color: #4a4a4a;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            #qcHintLabel {
                color: #888888;
                font-size: @SMALL@px;
            }
            #qcCollapseButton {
                background: transparent;
                border: none;
                color: #dcdcdc;
                font-size: @LARGE@px;
                font-weight: bold;
                padding: 0px;
            }
            #qcCollapseButton:hover {
                color: #2d8ed6;
            }
            #qcCardsHost {
                background-color: transparent;
            }
            #qcIssueCard {
                background-color: #2a2a2a;
                border: 1px solid #404040;
                border-left: 3px solid #888888;
                border-radius: 6px;
            }
            #qcIssueCard:hover {
                border: 1px solid #1e6bb8;
                border-left: 3px solid #1e6bb8;
            }
            #qcIssueCard[catKey="B"] {
                border-left: 3px solid #ffb86b;
            }
            #qcIssueCard[catKey="C"] {
                border-left: 3px solid #ff6b6b;
            }
            #qcIssueCard[catKey="D"] {
                border-left: 3px solid #e3b341;
            }
            #qcDescLabel {
                color: #dcdcdc;
                font-size: @BASE@px;
            }
            #qcMetaLabel {
                color: #9a9a9a;
                font-size: @SMALL@px;
            }
            #qcInfoLabel {
                color: #888888;
                font-size: @SMALL@px;
                padding: 8px 6px;
            }
            #qcChip {
                padding: 2px 10px;
                border-radius: 999px;
                font-size: @SMALL@px;
                background-color: #2a2a2a;
                color: #aaaaaa;
                border: 1px solid #404040;
            }
            #qcChip:hover {
                color: #dcdcdc;
                border: 1px solid #5a5a5a;
            }
            #qcChip:checked {
                background-color: #1e6bb8;
                color: #ffffff;
                border: 1px solid #1e6bb8;
            }
            #qcChip:disabled {
                color: #555555;
                background-color: #252525;
            }
        '''
        qss = qss.replace('@BASE@', str(base))
        qss = qss.replace('@SMALL@', str(small))
        qss = qss.replace('@LARGE@', str(large))
        self.setStyleSheet(qss)
        # 同步应用默认字体，使对话框、消息框、右键菜单跟随界面字号
        app = QApplication.instance()
        if app is not None:
            font = QFont('Microsoft YaHei')
            font.setPixelSize(self._font_px)
            app.setFont(font)
        # 按新字号下导航区的最小宽度需求保障窗口最小宽度
        self._enforce_nav_min_width()

    def _enforce_nav_min_width(self):
        """保障中栏（导航区）宽度不小于其最小需求，必要时从左右两栏回收"""
        nav_min = self._nav_container.minimumSizeHint().width()
        base = 180 + nav_min + 360 + 28  # 28 = 主布局左右边距 12 + 两个 8px 分隔条
        self.setMinimumWidth(max(1100, base))
        if not self.isVisible():
            return
        total = self._splitter.width()
        if total <= 0:
            total = sum(self._splitter.sizes())
        if total <= 0:
            return
        left, mid, right = self._splitter.sizes()
        if mid >= nav_min:
            return
        deficit = nav_min - mid
        # 优先从右侧 JSON 栏回收，保底 360
        take = min(deficit, max(0, right - 360))
        right -= take
        deficit -= take
        # 再从左侧任务栏回收，保底 180
        if deficit > 0:
            take = min(deficit, max(0, left - 180))
            left -= take
            deficit -= take
        self._splitter.setSizes([left, nav_min, right])

    def _set_font_px(self, px, tooltip_pos=None):
        """统一设置界面字号：夹紧到允许范围并即时刷新样式与指令区高度"""
        self._font_px = max(self.FONT_MIN_PX, min(self.FONT_MAX_PX, int(px)))
        self._apply_styles()
        if self._qc_collapsed:
            # 字号变化会改变标题行高度，折叠态需同步高度上限
            self._set_qc_collapsed(True, apply_sizes=False)
        if tooltip_pos is not None:
            QToolTip.showText(tooltip_pos, f'界面字体: {self._font_px}px', self, QRect(), 1200)
        QTimer.singleShot(0, self._enforce_nav_min_width)
        QTimer.singleShot(0, self._fit_instruction_pane)

    def _apply_default_splitter_sizes(self):
        """按可用宽度分配三栏默认比例（0.17 / 0.45 / 0.38），并保证最小宽度"""
        total = self._splitter.width()
        if total < 100:
            total = self.width()
        minimums = [180, 320, 360]
        if total < sum(minimums):
            sizes = minimums
        else:
            sizes = [max(minimums[0], int(total * 0.17)),
                     max(minimums[1], int(total * 0.45)),
                     max(minimums[2], int(total * 0.38))]
        self._splitter.setSizes(sizes)

    def _instruction_ideal_height(self):
        """按当前可视宽度计算指令文本完整显示所需的高度（含边距/内边距/边框）"""
        te = self._instruction_display
        doc = te.document()
        viewport_w = te.viewport().width()
        if viewport_w <= 0:
            viewport_w = te.width() - 2 * te.frameWidth()
        doc.setPageSize(QSizeF(max(1, viewport_w), 1e6))
        content_h = int(doc.documentLayout().documentSize().height())
        frame = 2 * te.frameWidth()
        margins = int(doc.documentMargin() * 2)
        padding = 12  # 对应样式表 padding:6px 的上下合计
        return content_h + margins + frame + padding + 2

    def _fit_instruction_pane(self):
        """让顶部指令面板高度自适应内容（受上下限约束），剩余空间给 JSON 树"""
        if self._user_adjusted_right:
            return
        total = self._right_splitter.height()
        if total <= 0:
            return
        min_h = 40
        max_h = max(min_h, int(total * 0.7))  # 上限 70%，保证 JSON 树始终可见
        top = max(min_h, min(self._instruction_ideal_height(), max_h))
        self._applying_right_sizes = True
        try:
            sizes = self._right_splitter.sizes()
            if len(sizes) == 3:
                # 三栏：指令区自适应，语义问题面板保持现有高度，剩余给 JSON 树
                qc_h = self._qc_header_height() if self._qc_collapsed else max(min_h, sizes[2])
                sizes = [top, max(min_h, total - top - qc_h), qc_h]
            else:
                sizes = [top, max(min_h, total - top)]
            self._right_splitter.setSizes(sizes)
        finally:
            self._applying_right_sizes = False

    def _on_right_splitter_moved(self, pos, index):
        """仅记录用户真实拖拽；程序自适应高度触发的移动不视为手动调整"""
        if self._applying_right_sizes:
            return
        self._user_adjusted_right = True

    def _available_screen_geometry(self):
        """返回主屏可用区域，无屏幕时回退固定尺寸"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, 1600, 950)
        return screen.availableGeometry()

    def _default_window_rect(self, screen_geo):
        """按屏幕可用区域计算默认窗口矩形（居中且不超出屏幕）"""
        width = min(1600, max(1100, screen_geo.width() - 80))
        height = min(950, max(700, screen_geo.height() - 80))
        width = min(width, screen_geo.width())
        height = min(height, screen_geo.height())
        x = screen_geo.x() + max(0, (screen_geo.width() - width) // 2)
        y = screen_geo.y() + max(0, (screen_geo.height() - height) // 2)
        return QRect(x, y, width, height)

    def _restore_window_state(self):
        """恢复窗口几何与分栏状态，异常一律回退默认布局"""
        screen_geo = self._available_screen_geometry()
        default_rect = self._default_window_rect(screen_geo)
        try:
            geometry = self._settings.value('window/geometry')
            restored = bool(geometry is not None and self.restoreGeometry(geometry))
            if restored:
                # 尺寸小于最小尺寸，或窗口完全落在屏幕外，视为无效
                if (self.width() < self.minimumWidth()
                        or self.height() < self.minimumHeight()
                        or not screen_geo.intersects(self.frameGeometry())):
                    restored = False
            if not restored:
                self.setGeometry(default_rect)
        except Exception:
            self.setGeometry(default_rect)

        try:
            state = self._settings.value('splitter/state')
            applied = bool(state is not None and self._splitter.restoreState(state))
            self._splitter_state_restored = applied
            if not applied:
                self._apply_default_splitter_sizes()
        except Exception:
            self._splitter_state_restored = False
            self._apply_default_splitter_sizes()

        # 独立恢复右栏纵向分栏状态，异常时回退到内容自适应
        try:
            right_state = self._settings.value('splitter/right_state')
            self._right_splitter_restored = bool(
                right_state is not None and self._right_splitter.restoreState(right_state)
            )
        except Exception:
            self._right_splitter_restored = False

        try:
            saved_collapsed = self._settings.value('ui/qc_collapsed', False, type=bool)
        except Exception:
            saved_collapsed = False
        # 仅应用可见性与高度上限，尺寸交给已恢复的分栏状态/后续自适应
        self._set_qc_collapsed(saved_collapsed, apply_sizes=False)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._splitter_state_restored:
            self._splitter_state_restored = True
            # 首次显示后分栏宽度才有效，延迟按比例分配默认分栏，避免被拉伸权重打乱
            QTimer.singleShot(0, self._apply_default_splitter_sizes)
        if not self._right_splitter_restored and not self._user_adjusted_right:
            # 首次显示后高度才有效，延迟按内容适配指令区高度
            QTimer.singleShot(0, self._fit_instruction_pane)
        # 显示后布局宽度有效，再按导航区实际需求保障中栏宽度
        QTimer.singleShot(0, self._enforce_nav_min_width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._user_adjusted_right:
            QTimer.singleShot(0, self._fit_instruction_pane)

    def _save_window_state(self):
        """保存窗口几何与分栏状态"""
        try:
            self._settings.setValue('window/geometry', self.saveGeometry())
            self._settings.setValue('splitter/state', self._splitter.saveState())
            self._settings.setValue('splitter/right_state', self._right_splitter.saveState())
            self._settings.setValue('ui/font_px', self._font_px)
            self._settings.setValue('ui/qc_collapsed', bool(self._qc_collapsed))
            self._settings.sync()
        except Exception:
            pass

    def _on_browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择数据文件夹', self._current_folder or '')
        if not folder:
            return
        self._current_folder = folder
        self._folder_input.setText(folder)
        self._load_json_files(folder)

    def _load_json_files(self, folder):
        # 重新加载文件夹：递增版本号作废尚未返回的旧质检任务，并清空旧结果与标记
        self._qc_run_version += 1
        self._qc_results = {}
        self._pseudo_to_page = {}
        self._pseudo_shots = {}
        self._json_files = find_json_files(folder)
        self._task_list.clear()
        self._json_data = None
        self._pages = []
        self._current_page_index = 0
        self._image_preview.clear()
        self._json_tree.clear()
        # 重置语义问题面板：清空卡片、筛选归位、chip 计数归零
        self._qc_filter = 'ALL'
        self._qc_current_issues = []
        self._qc_empty_hint = '未选择任务'
        self._update_qc_chips(Counter(), 0)
        self._clear_qc_cards()
        self._add_qc_info_card(self._qc_empty_hint)
        self._lbl_qc_title.setText('语义问题（0）')
        self._btn_prev.setEnabled(False)
        self._btn_next.setEnabled(False)
        self._btn_save.setEnabled(False)
        self._btn_refresh.setEnabled(False)
        self._jump_input.setEnabled(False)
        self._btn_jump.setEnabled(False)
        self._jump_input.clear()
        self._instruction_display.clear()
        self._instruction_display.setToolTip('')
        self._update_page_info()

        for filepath in self._json_files:
            try:
                data = load_json_file(filepath)
                task_name = get_task_name(data)
                filename = os.path.basename(filepath)
                display_name = f'[{filename}] {task_name}'
                item = QListWidgetItem(display_name)
                item.setData(Qt.ItemDataRole.UserRole, filepath)
                item.setData(QC_ORIGINAL_TEXT_ROLE, display_name)
                item.setToolTip(display_name)
                self._task_list.addItem(item)
            except Exception as e:
                item = QListWidgetItem(f'[错误] {os.path.basename(filepath)}')
                item.setData(Qt.ItemDataRole.UserRole, filepath)
                item.setData(QC_ORIGINAL_TEXT_ROLE, item.text())
                item.setToolTip(item.text())
                self._task_list.addItem(item)

        # 模块可用时自动后台跑一次语义质检
        if SEMANTIC_QC_AVAILABLE and self._json_files:
            self._start_semantic_qc()
        else:
            self._update_qc_button_state()

    # -------------------------------------------------- 语义质检
    def _on_semantic_qc_clicked(self):
        if not SEMANTIC_QC_AVAILABLE or not self._current_folder:
            return
        self._start_semantic_qc()

    def _start_semantic_qc(self):
        """对当前文件夹的全部任务启动一次后台语义质检（版本号用于作废过期结果）。"""
        if not SEMANTIC_QC_AVAILABLE or not self._json_files:
            self._update_qc_button_state()
            return
        if self._qc_worker is not None and self._qc_worker.isRunning():
            return  # 运行中防重入
        self._qc_run_version += 1
        worker = SemanticQCWorker(list(self._json_files), self._qc_run_version, self)
        self._qc_worker = worker
        self._qc_workers.append(worker)
        worker.finishedQC.connect(self._on_qc_finished)
        worker.finished.connect(self._on_qc_worker_finished)
        worker.start()
        self._update_qc_button_state()

    def _on_qc_finished(self, version, results):
        if version != self._qc_run_version:
            return  # 已被重新加载/重跑作废，丢弃过期结果
        self._qc_results = results
        self._refresh_all_qc_marks()
        self._refresh_qc_detail()
        self._update_qc_button_state()

    def _on_qc_worker_finished(self):
        worker = self.sender()
        if worker is not None:
            try:
                self._qc_workers.remove(worker)
            except ValueError:
                pass
            worker.deleteLater()
        if worker is self._qc_worker:
            self._qc_worker = None
        self._update_qc_button_state()

    def _update_qc_button_state(self):
        running = self._qc_worker is not None and self._qc_worker.isRunning()
        if running:
            self._btn_semantic_qc.setText('质检中…')
            self._btn_semantic_qc.setEnabled(False)
            return
        self._btn_semantic_qc.setText('🔍 语义质检')
        self._btn_semantic_qc.setEnabled(
            SEMANTIC_QC_AVAILABLE and bool(self._current_folder) and bool(self._json_files)
        )

    def _refresh_all_qc_marks(self):
        """按 _qc_results 刷新任务列表项的前缀、配色与 tooltip；未覆盖文件保持原样。"""
        for i in range(self._task_list.count()):
            item = self._task_list.item(i)
            filepath = item.data(Qt.ItemDataRole.UserRole)
            if not filepath:
                continue
            original = item.data(QC_ORIGINAL_TEXT_ROLE) or item.text()
            result = self._qc_results.get(os.path.abspath(filepath))
            if result is None:
                item.setText(original)
                item.setData(Qt.ItemDataRole.ForegroundRole, None)
                item.setBackground(QColor(0, 0, 0, 0))
                item.setToolTip(original)
                continue
            if result.get('failed'):
                item.setText(f'⚠ {original}')
                item.setForeground(QColor('#ffb86b'))
                item.setBackground(QColor(0, 0, 0, 0))
                item.setToolTip(f'{original}\n\n[语义质检解析失败] {result.get("error", "")}')
                continue
            issues = result.get('issues', [])
            if issues:
                item.setText(f'●{len(issues)} {original}')
                item.setForeground(QColor('#ff6b6b'))
                item.setBackground(QColor(0, 0, 0, 0))
                cnt = Counter(iss['cat'] for iss in issues)
                lines = [original, '', f'语义质检问题 {len(issues)} 条（步号对应截图文件名口径）：']
                for cat in check_semantic_v1.CATS:
                    if cnt.get(cat):
                        lines.append(f'  {cat}: {cnt[cat]}')
                item.setToolTip('\n'.join(lines))
            else:
                item.setText(original)
                item.setData(Qt.ItemDataRole.ForegroundRole, None)
                item.setBackground(QColor(0, 0, 0, 0))
                item.setToolTip(original)

    def _qc_header_height(self):
        """折叠态面板需要的高度：标题行高度（含按钮），带下限保护。"""
        if self._qc_header is None:
            return 28
        return max(28, self._qc_header.sizeHint().height(),
                   self._lbl_qc_title.sizeHint().height())

    def _toggle_qc_panel(self):
        """在标题行按钮/标题上点击时切换折叠态。"""
        self._set_qc_collapsed(not self._qc_collapsed)

    def _set_qc_collapsed(self, collapsed, apply_sizes=True):
        """应用折叠态：切换控件可见性、高度上限，并按需重排右栏三栏高度。"""
        collapsed = bool(collapsed)
        sizes = self._right_splitter.sizes()
        if collapsed and not self._qc_collapsed and len(sizes) == 3:
            # 折叠前记录展开态实际高度，供下次展开还原
            header_h = self._qc_header_height()
            if sizes[2] > header_h:
                self._qc_last_height = sizes[2]
        self._qc_collapsed = collapsed
        header_h = self._qc_header_height()
        self._qc_chips_widget.setVisible(not collapsed)
        self._qc_scroll.setVisible(not collapsed)
        self._lbl_qc_hint.setVisible(not collapsed)
        self._btn_qc_collapse.setText('▸' if collapsed else '▾')
        self._btn_qc_collapse.setToolTip('展开语义问题' if collapsed else '折叠语义问题')
        if collapsed:
            self._qc_container.setMaximumHeight(header_h)
        else:
            self._qc_container.setMaximumHeight(16777215)
        if not apply_sizes:
            return
        total = self._right_splitter.height()
        if total <= 0 or len(sizes) != 3:
            return
        min_h = 40
        bottom = header_h if collapsed else max(self._qc_scroll.minimumHeight(), self._qc_last_height)
        top = max(min_h, sizes[0])
        self._applying_right_sizes = True
        try:
            self._right_splitter.setSizes([top, max(min_h, total - top - bottom), bottom])
        finally:
            self._applying_right_sizes = False

    def _make_qc_chip(self, text, key):
        """类别筛选 chip：checkable 且同组 autoExclusive，点击时通过默认参数捕获 key。"""
        chip = QPushButton(text)
        chip.setObjectName('qcChip')
        chip.setProperty('catKey', key)
        chip.setCheckable(True)
        chip.setAutoExclusive(True)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.clicked.connect(lambda _checked=False, k=key: self._on_qc_filter_clicked(k))
        return chip

    def _on_qc_filter_clicked(self, key):
        """切换类别筛选并重渲染卡片；显式同步 chip 选中态（兼容程序化调用）。"""
        self._qc_filter = key
        self._qc_chips[key].setChecked(True)
        self._render_qc_cards()

    def _clear_qc_cards(self):
        """删除卡片布局中 stretch 之外的全部控件。"""
        layout = self._qc_cards_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _add_qc_info_card(self, text):
        """空态/提示信息：弱化色、自动换行的单标签卡片。"""
        lbl = QLabel(text)
        lbl.setObjectName('qcInfoLabel')
        lbl.setWordWrap(True)
        self._qc_cards_layout.insertWidget(self._qc_cards_layout.count() - 1, lbl)

    def _update_qc_chips(self, counts, total):
        """刷新四个筛选 chip 的计数文本、禁用态与选中态。"""
        labels = {'ALL': f'全部 {total}', 'B': f'B {counts.get("B", 0)}',
                  'C': f'C {counts.get("C", 0)}', 'D': f'D {counts.get("D", 0)}'}
        for key, chip in self._qc_chips.items():
            chip.setText(labels[key])
            available = key == 'ALL' or counts.get(key, 0) > 0
            chip.setEnabled(available)
            if key == self._qc_filter and not available:
                self._qc_filter = 'ALL'
        self._qc_chips[self._qc_filter].setChecked(True)

    def _render_qc_cards(self):
        """按当前筛选渲染卡片；无卡片时渲染空态提示（_qc_empty_hint）。"""
        self._clear_qc_cards()
        if not self._qc_current_issues:
            self._add_qc_info_card(self._qc_empty_hint)
            return
        shown = [iss for iss in self._qc_current_issues
                 if self._qc_filter == 'ALL'
                 or (iss.get('cat', '') or '')[:1] == self._qc_filter]
        if not shown:
            self._add_qc_info_card(self._qc_empty_hint)
            return
        for iss in shown:
            card = QIssueCard(iss)
            card.doubleClicked.connect(self._on_qc_issue_double_clicked)
            self._qc_cards_layout.insertWidget(self._qc_cards_layout.count() - 1, card)

    def _refresh_qc_detail(self):
        """按当前选中任务的 abspath 填充语义问题明细面板（卡片 + 类别筛选）。"""
        self._qc_current_issues = []
        if not self._current_json_path:
            self._lbl_qc_title.setText('语义问题（0）')
            self._qc_empty_hint = '未选择任务'
            self._update_qc_chips(Counter(), 0)
            self._render_qc_cards()
            return
        result = self._qc_results.get(os.path.abspath(self._current_json_path))
        if result is None:
            self._lbl_qc_title.setText('语义问题（0）')
            self._qc_empty_hint = '质检进行中或未运行'
            self._update_qc_chips(Counter(), 0)
            self._render_qc_cards()
            return
        if result.get('failed'):
            self._lbl_qc_title.setText('语义问题（0）')
            self._qc_empty_hint = f'该任务解析失败：{result.get("error", "")}'
            self._update_qc_chips(Counter(), 0)
            self._render_qc_cards()
            return
        issues = result.get('issues', [])
        self._qc_current_issues = issues
        self._lbl_qc_title.setText(f'语义问题（{len(issues)}）')
        counts = Counter((iss.get('cat', '') or '')[:1] for iss in issues)
        if not issues:
            self._qc_empty_hint = '未发现语义问题'
        else:
            self._qc_empty_hint = '当前筛选下暂无问题'
        self._update_qc_chips(counts, len(issues))
        self._render_qc_cards()

    def _on_qc_issue_double_clicked(self, issue):
        step = issue.get('step') if isinstance(issue, dict) else None
        if step is None:
            return  # 任务级问题（步号 None）：任务已选中即可，不翻页
        if not isinstance(step, int):
            return
        idx = self._page_index_for_pseudo(step)
        if idx is None:
            self.statusBar().showMessage(f'伪步 {step} 未找到对应 GUI 页面，跳转已忽略', 4000)
            return
        self._current_page_index = idx
        self._display_current_page()
        self._update_page_info()

    def _page_index_for_pseudo(self, step):
        """伪步序号 -> _pages 索引，映射缺失返回 None。"""
        return self._pseudo_to_page.get(step)

    def _rerun_semantic_qc_current(self):
        """保存后对当前单文件同步重检，原子替换其结果并刷新标记与明细；异常置失败。"""
        if not SEMANTIC_QC_AVAILABLE or not self._current_json_path:
            return
        abspath = os.path.abspath(self._current_json_path)
        try:
            result = check_semantic_one_file(abspath)
        except Exception as e:
            result = {'issues': [], 'failed': True, 'error': str(e)}
        self._qc_results[abspath] = result
        self._refresh_all_qc_marks()
        self._refresh_qc_detail()

    def _on_task_selected(self, row):
        if row < 0 or row >= len(self._json_files):
            self._instruction_display.clear()
            self._instruction_display.setToolTip('')
            self._refresh_qc_detail()
            return

        if self._json_tree.has_unsaved_changes():
            reply = QMessageBox.question(
                self, '未保存的更改',
                '当前任务有未保存的更改，是否切换到新任务？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._task_list.blockSignals(True)
                self._task_list.setCurrentRow(self._last_task_row)
                self._task_list.blockSignals(False)
                return

        self._last_task_row = row
        filepath = self._json_files[row]
        if not os.path.exists(filepath):
            return
        try:
            self._json_data = load_json_file(filepath)
            self._current_json_path = filepath
            self._build_pages()
            self._jump_input.clear()
            self._current_page_index = 0
            self._display_current_page()
            self._btn_save.setEnabled(True)
            self._btn_refresh.setEnabled(True)
            # 切换任务时按新指令内容自适应一次高度（用户已拖拽过则内部会跳过）
            QTimer.singleShot(0, self._fit_instruction_pane)
            self._refresh_qc_detail()
        except Exception as e:
            QMessageBox.critical(self, '错误', f'无法加载JSON文件:\n{str(e)}')
            self._refresh_qc_detail()

    @staticmethod
    def _extract_coordinates_from_actions(actions):
        """从 actions 列表中提取坐标。

        swipe/drag 动作使用 start_coordinate -> coordinate 两个点；
        其他动作使用单个 coordinate 点。
        返回 (coordinates, action_type)。
        """
        for action in actions:
            action_type = action.get('action')
            if 'start_coordinate' in action and 'coordinate' in action:
                start = action['start_coordinate']
                end = action['coordinate']
                coordinates = [[start[0], start[1]], [end[0], end[1]]]
                return coordinates, action_type
            if 'coordinate' in action:
                return action['coordinate'], action_type
        return None, None

    def _build_pages(self):
        self._pages = []
        self._pseudo_to_page = {}
        self._pseudo_shots = {}
        pseudo_counter = 0  # 跳过 screenshot 合成步后，与 to_pseudo_record 同序连续编号
        if not self._json_data:
            return

        # 加载 _coords.json 拉框数据（如果存在）
        # coords 中的条目按轨迹步骤顺序排列，可能有多个 trajectory 中 step 号重复
        # 使用游标按顺序消费，避免不同 trajectory 的同号 step 互相覆盖
        coords_list = []
        coords_cursor = 0
        if self._current_json_path:
            json_dir = os.path.dirname(os.path.abspath(self._current_json_path))
            base_name = os.path.splitext(os.path.basename(self._current_json_path))[0]
            coords_path = os.path.join(json_dir, f'{base_name}_coords.json')
            if os.path.exists(coords_path):
                try:
                    coords_data = load_json_file(coords_path)
                    # 兼容两种格式：纯列表，或 {"version": ..., "coords": [...]}
                    if isinstance(coords_data, dict):
                        coords_list = coords_data.get('coords', [])
                    elif isinstance(coords_data, list):
                        coords_list = coords_data
                except Exception:
                    coords_list = []

        top_fields = {k: self._json_data[k] for k in
                      ['platform', 'system', 'screen_size', 'task_type', 'recording_video']
                      if k in self._json_data}
        self._pages.append(PageInfo('top_level', top_fields, path_prefix=[]))

        messages = self._json_data.get('messages', [])
        for mi, msg in enumerate(messages):
            if 'trajectory' in msg:
                trajectory = msg['trajectory']
                for si, step in enumerate(trajectory):
                    screenshot = None
                    coordinates = None
                    observation = step.get('observation', {})
                    screenshot_name = observation.get('screenshot', '')
                    if screenshot_name:
                        json_dir = os.path.dirname(os.path.abspath(self._current_json_path))
                        screenshot = os.path.join(json_dir, screenshot_name)

                    # 优先使用 _coords.json 中的拉框数据（按顺序消费）
                    action_type = None
                    if coords_cursor < len(coords_list) and coords_list[coords_cursor].get('step') == si:
                        entry = coords_list[coords_cursor]
                        coords_cursor += 1
                        entry_action = entry.get('action', '')
                        entry_action_lower = str(entry_action).lower()
                        is_drag_or_swipe = ('drag' in entry_action_lower or 'swipe' in entry_action_lower)

                        if is_drag_or_swipe and 'center' in entry and 'end_center' in entry:
                            # 拖拽/滑动：center 为起点，end_center 为终点
                            c = entry['center']
                            ec = entry['end_center']
                            coordinates = [[c[0], c[1]], [ec[0], ec[1]]]
                            action_type = entry_action
                        elif is_drag_or_swipe and 'center' in entry:
                            # 拖拽/滑动只有起点框（center）时，从 actions 提取 start_coordinate -> coordinate
                            coordinates, fallback_action = self._extract_coordinates_from_actions(
                                step.get('actions', [])
                            )
                            if coordinates is None:
                                coordinates = [entry['center']]
                            if action_type is None:
                                action_type = fallback_action
                        elif 'vertices' in entry:
                            vertices = entry['vertices']
                            # 拖拽/滑动动作：将 [x1,y1,x2,y2] 转为 [[x1,y1],[x2,y2]] 以便 paintEvent 正确渲染
                            if is_drag_or_swipe and len(vertices) == 4:
                                coordinates = [[vertices[0], vertices[1]], [vertices[2], vertices[3]]]
                            else:
                                coordinates = vertices
                            action_type = entry_action
                        elif 'center' in entry:
                            coordinates = entry['center']
                            action_type = entry_action
                        elif entry_action:
                            action_type = entry_action
                        # coords 条目没有坐标数据时，回退到 actions 提取
                        if coordinates is None:
                            coordinates, fallback_action = self._extract_coordinates_from_actions(
                                step.get('actions', [])
                            )
                            if action_type is None:
                                action_type = fallback_action
                    else:
                        # 回退到原有方式：从 actions 中提取坐标
                        coordinates, action_type = self._extract_coordinates_from_actions(
                            step.get('actions', [])
                        )

                    self._pages.append(PageInfo(
                        'trajectory_step', step,
                        screenshot_file=screenshot,
                        coordinates=coordinates,
                        step_index=si,
                        path_prefix=['messages', mi, 'trajectory', si],
                        action_type=action_type
                    ))
                    # 与 check_semantic_origin.to_pseudo_record 同规则：
                    # 跳过 actions[0].action == "screenshot" 的合成步，其余按出现顺序连续编号
                    if msg.get('role') == 'assistant':
                        acts = step.get('actions') or []
                        first_act = acts[0] if acts else {}
                        if first_act.get('action') != 'screenshot':
                            self._pseudo_to_page[pseudo_counter] = len(self._pages) - 1
                            self._pseudo_shots[pseudo_counter] = screenshot_name
                            pseudo_counter += 1
            else:
                self._pages.append(PageInfo('message', msg, step_index=mi, path_prefix=['messages', mi]))

    def _display_current_page(self):
        if not self._pages or self._current_page_index < 0:
            return
        if self._current_page_index >= len(self._pages):
            self._current_page_index = len(self._pages) - 1

        page = self._pages[self._current_page_index]

        self._image_preview.set_image(page.screenshot_file, page.coordinates, page.action_type)

        self._json_tree.set_json_data(self._json_data, self._pages, self._current_page_index, self._current_json_path)
        page_data = self._json_tree._get_page_data_from_json()
        self._json_tree.clear_and_build(page_data)

        self._json_tree.expandAll()

        self._btn_prev.setEnabled(self._current_page_index > 0)
        self._btn_next.setEnabled(self._current_page_index < len(self._pages) - 1)
        self._update_page_info()
        self._update_instruction_display()

    def _on_zoom_changed(self, zoom):
        """更新缩放百分比标签"""
        self._lbl_zoom.setText(f'缩放: {round(zoom * 100)}%')

    def _update_page_info(self):
        total = len(self._pages)
        current = self._current_page_index
        if total == 0:
            self._lbl_page_info.setText('第 0 / 0 步')
            self._lbl_page_step_desc.set_full_text('')
            self._jump_input.setEnabled(False)
            self._btn_jump.setEnabled(False)
        else:
            self._jump_input.setEnabled(True)
            self._btn_jump.setEnabled(True)
            self._jump_input.setPlaceholderText(f'1-{total}')
            page = self._pages[current]
            desc = self._get_page_description(page)
            self._lbl_page_info.setText(f'第 {current + 1} / {total} 步')
            self._lbl_page_step_desc.set_full_text(desc)

    def _get_page_description(self, page):
        if page.page_type == 'top_level':
            return '基础信息'
        elif page.page_type == 'message':
            data = page.data
            role = data.get('role', '')
            if role == 'user':
                inst = data.get('instruction', '')
                return f'用户指令: {inst[:40]}{"..." if len(inst) > 40 else ""}'
            return f'消息 ({role})'
        elif page.page_type == 'trajectory_step':
            data = page.data
            intent = data.get('intent', '')
            return f'步骤{page.step_index}: {intent[:40]}{"..." if len(intent) > 40 else ""}'
        return ''

    def _update_instruction_display(self):
        if not self._json_data:
            return
        messages = self._json_data.get('messages', [])
        if messages:
            msg = messages[0]
            inst = msg.get('instruction', '')
            self._instruction_display.setPlainText(inst)
            self._instruction_display.setToolTip(inst)
        else:
            self._instruction_display.clear()
            self._instruction_display.setToolTip('')
        # 切换步骤只刷新文本，不再重设分栏高度，保持用户已调整的上下比例

    def _on_jump_to_page(self):
        if not self._pages:
            return
        text = self._jump_input.text().strip()
        if not text.isdigit():
            QMessageBox.warning(self, '无效页码', '请输入有效的页码（正整数）')
            self._jump_input.selectAll()
            return
        page_no = int(text)
        page_no = max(1, min(page_no, len(self._pages)))
        self._jump_input.setText(str(page_no))
        self._current_page_index = page_no - 1
        self._display_current_page()

    def _on_prev_page(self):
        if self._current_page_index > 0:
            self._current_page_index -= 1
            self._display_current_page()

    def _on_next_page(self):
        if self._current_page_index < len(self._pages) - 1:
            self._current_page_index += 1
            self._display_current_page()

    def _on_save(self):
        if not self._current_json_path or self._json_data is None:
            return
        try:
            saved_data = copy.deepcopy(self._json_data)
            save_json_file(self._current_json_path, saved_data)
            self._json_tree.mark_saved()
            # 保存成功后仅对当前任务同步增量重检，原子替换该任务的质检结果
            self._rerun_semantic_qc_current()
            QMessageBox.information(self, '保存成功', f'已保存到:\n{self._current_json_path}')
        except Exception as e:
            QMessageBox.critical(self, '保存失败', f'保存时发生错误:\n{str(e)}')

    def _on_refresh(self):
        if not self._current_json_path:
            return
        if not os.path.exists(self._current_json_path):
            QMessageBox.warning(self, '刷新失败', 'JSON文件已不存在')
            return
        if self._json_tree.has_unsaved_changes():
            reply = QMessageBox.question(
                self, '未保存的更改',
                '当前有未保存的更改，刷新将丢失这些更改。确定刷新吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            saved_page_index = self._current_page_index
            self._json_data = load_json_file(self._current_json_path)
            self._build_pages()
            if self._pages:
                self._current_page_index = min(saved_page_index, len(self._pages) - 1)
            else:
                self._current_page_index = 0
            self._display_current_page()
        except Exception as e:
            QMessageBox.critical(self, '刷新失败', f'重新加载JSON文件时发生错误:\n{str(e)}')

    def closeEvent(self, event):
        self._save_window_state()
        # 等待仍在运行的后台质检线程结束，避免线程访问已销毁对象
        for worker in list(self._qc_workers):
            if worker.isRunning():
                worker.wait(2000)
        if self._json_tree.has_unsaved_changes():
            reply = QMessageBox.question(
                self, '未保存的更改',
                '当前任务有未保存的更改，确定要退出吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.No:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            # Ctrl+滚轮实时调节界面字号（主窗口内、无模态框、窗口处于激活状态）
            if (event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    and QApplication.activeModalWidget() is None
                    and self.isActiveWindow()
                    and isinstance(obj, QWidget)
                    and obj.window() is self):
                delta = event.angleDelta().y()
                step = 1 if delta > 0 else (-1 if delta < 0 else 0)
                self._set_font_px(self._font_px + step,
                                  tooltip_pos=event.globalPosition().toPoint())
                return True
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                blocked_mods = (Qt.KeyboardModifier.ControlModifier
                                | Qt.KeyboardModifier.AltModifier
                                | Qt.KeyboardModifier.MetaModifier)
                focus = QApplication.focusWidget()
                is_editable_text = (
                    isinstance(focus, (QLineEdit, QTextEdit))
                    and not focus.isReadOnly()
                )
                if (not (event.modifiers() & blocked_mods)
                        and QApplication.activeModalWidget() is None
                        and self.isActiveWindow()
                        and not isinstance(focus, JsonTreeWidget)
                        and not is_editable_text):
                    if key == Qt.Key.Key_Left:
                        self._on_prev_page()
                    else:
                        self._on_next_page()
                    return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_S and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._on_save()
        elif event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
                self._image_preview.zoom_in()
            elif event.key() == Qt.Key.Key_Minus:
                self._image_preview.zoom_out()
            elif event.key() == Qt.Key.Key_0:
                self._image_preview.fit_to_window()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)


def main():
    app = QApplication(sys.argv)
    font = QFont('Microsoft YaHei')
    font.setPixelSize(MainWindow.FONT_DEFAULT_PX)
    app.setFont(font)
    # 打包后启动时自动检查并应用更新（可能在此处重启进程）；源码运行时为空操作
    updater.ensure_latest(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
